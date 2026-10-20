# Architecture

NetShift is a single-process Tkinter app (CustomTkinter widgets). Everything that touches the system
runs in background threads; results come back to the UI thread through a queue.

```
NetShift.pyw               entry point: DPI awareness, UAC self-elevation, starts App
netshift/
├── __init__.py            __version__
├── netbackend.py          Windows access: read adapters, build/apply netsh commands, adapter actions
├── nettools.py            ICMP ping, ARP, subnet scan, TCP ports, subnet maths, DNS, public IP
├── store.py               JSON persistence: presets, history (undo), settings; data folder resolution
├── ui.py                  palette, fonts, widget helpers, TabHost, Console, dialogs, ConfigForm
├── app.py                 main window: sidebar, header, Configuration / Presets / History tabs
├── tools_view.py          Tools tab: ping, traceroute, scan, ports, DNS, calculator, system commands
├── capture.py             packet decoding, display filters, pcap/pcapng I/O, statistics, raw-socket capture
├── capture_view.py        Tools → Capture UI (table, details, filters, statistics, Wireshark)
├── vpn.py                 Windows VPN connections: read, validate, build PowerShell commands, rasdial
└── vpn_view.py            VPN tab (list, editor, connect / disconnect)
installer/netshift.iss     Inno Setup script (built and tested by the Release workflow)
scripts/make_screenshots.py  documentation screenshots with fictitious data (rendered with PrintWindow)
scripts/make_icon.py       generates the app icon and logos
tests/                     pytest suite (pure logic, capture decoding, screenshot guard)
```

## Reading adapter state

`netbackend.list_adapters()` runs one PowerShell script that queries `Get-NetAdapter`,
`Get-NetIPInterface`, `Get-NetIPAddress`, `Get-NetRoute` (default route) and `Get-DnsClientServerAddress`
in bulk, groups the results by interface index, and returns JSON. Whether DNS servers are manual is read
from the `NameServer` value under `HKLM\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces\{GUID}`.
For disconnected adapters, the persistent store is used as a fallback so static settings are still shown.

PowerShell startup and module loading cost about 3 s, so `_PSSession` keeps **one hidden PowerShell
process** alive. Each script is sent base64-encoded on a single stdin line, wrapped in `try/catch`, and
followed by a unique end marker carrying the exit status. Subsequent refreshes take about 0.25 s, which
makes the 5-second auto-refresh cheap. If the session dies, it restarts transparently; if it cannot start,
a one-shot `powershell.exe` call is used.

## Applying a configuration

A configuration is a plain dict (also the preset format):

```json
{"mode": "static", "ip": "192.168.1.50", "mask": "255.255.255.0", "gateway": "192.168.1.1",
 "dns_mode": "static", "dns1": "1.1.1.1", "dns2": "", "extra_ips": ["10.0.0.5/24"]}
```

1. `validate_config()` returns blocking errors and non-blocking warnings.
2. `build_commands()` turns it into `netsh interface ipv4 …` argument lists, addressing the interface by
   **index** (`name=12`), which avoids problems with localized or non-ASCII adapter names.
3. `apply_config()` runs them in order. A `netsh` "already set" answer is treated as success.
4. Before applying, `Adapter.to_config()` snapshots the current state into the history, which is what
   *Undo* and *Restore* re-apply.
5. After applying, the app refreshes a few times (DHCP leases take a moment) and pings the gateway.

## Network tools

`nettools.py` calls the IP Helper API through `ctypes`:

- `IcmpSendEcho` for ping and traceroute (TTL set through `IP_OPTION_INFORMATION`): no console window,
  no raw socket, no admin rights.
- `SendARP` resolves MAC addresses on the local subnet. The scan combines ICMP and ARP, so hosts with a
  firewall that drops ping are still discovered.

The scan, port check and DNS tools use thread pools and report progress through callbacks, which the UI
marshals with `App.ui()`.

## Threading model

Tk is not thread-safe. Two helpers in `App` handle this:

- `bg(work, done, busy, error)` runs `work()` in a daemon thread, then calls `done(result)` on the UI thread;
  `busy` shows the status-bar spinner.
- `ui(fn, *args)` queues a callable that the UI thread runs on its next 40 ms tick.

## Privileges

`main()` relaunches itself through `ShellExecuteW(..., "runas", ...)` when not elevated. If the user
declines, the app runs read-only: viewing and tools work, and anything that modifies the system is disabled.

## Packet capture

`capture.RawCapture` opens a raw IPv4 socket bound to the adapter's address and enables `SIO_RCVALL`
(administrator rights required). Datagrams are decoded in the capture thread (`capture.decode`) and
queued; the UI drains the queue every 200 ms, keeping at most 50 000 packets in memory and 5 000 rows in
the table. Display filters are compiled once into predicates (`compile_filter`), so re-filtering is a
single pass. Files are read by `read_capture_file` (pcap µs/ns in both byte orders, pcapng) and frames
decoded by `decode_frame` (Ethernet, VLAN, ARP, IPv6, raw IP, Linux SLL). Exports use pcap with
`LINKTYPE_RAW` (IPv4 datagrams), which Wireshark opens directly.

## Installer

`installer/netshift.iss` packages `dist\NetShift.exe` with Inno Setup (Program Files, Start-menu entry,
optional desktop icon, uninstaller). The Release workflow builds it and runs a silent install → file and
shortcut checks → silent uninstall before publishing. An installed copy is detected by the presence of
`unins000.exe` next to the exe, and then stores its data in `%APPDATA%\NetShift`.

## VPN

`vpn.list_vpns()` reads `Get-VpnConnection` for both scopes (current user / `-AllUserConnection`) in one
PowerShell call. Changes are built as PowerShell command strings by pure functions (`build_create`,
`build_update` — which diffs split-tunnel routes —, `build_remove`, `build_recreate` for renames, since Windows
cannot rename a VPN), all single-quote escaped and unit-tested. The L2TP pre-shared key is masked before any
command is logged. Connecting uses `rasdial` (saved or one-time credentials, never stored by NetShift) or the
Windows dialog (`rasphone -d`); disconnecting uses `rasdial /disconnect`.

## Adapter types

`netbackend.classify()` derives a type from `Get-NetAdapter` fields (MediaType, PhysicalMediaType,
InterfaceType, Virtual, HardwareInterface) and well-known driver names (WireGuard, TAP, AnyConnect, Hyper-V,
Parallels…). Hidden types are stored in `settings.json` (`hidden_kinds`).
