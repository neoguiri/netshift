# Architecture

NetShift is a single-process Tkinter app (CustomTkinter widgets). Everything that touches the system
runs in background threads; results come back to the UI thread through a queue.

```
NetShift.pyw              entry point: DPI awareness, UAC self-elevation, starts App
netshift/
├── __init__.py            __version__
├── netbackend.py          Windows access: read adapters, build/apply netsh commands, adapter actions
├── nettools.py            ICMP ping, ARP, subnet scan, TCP ports, subnet maths, DNS, public IP
├── store.py               JSON persistence: presets, history (undo), settings; data folder resolution
├── ui.py                  palette, fonts, widget helpers, TabHost, Console, dialogs, ConfigForm
├── app.py                 main window: sidebar, header, Configuration / Presets / History tabs
└── tools_view.py          Tools tab: ping, traceroute, scan, ports, DNS, calculator, system commands
scripts/make_screenshots.py  documentation screenshots with fictitious data
tests/                     pytest suite for the pure logic
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
