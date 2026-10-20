# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.5.0] - 2026-10-20

### Added
- **English interface** (and an i18n framework for more languages): every UI string goes through `_()` with
  French as the source language and `netshift/locales/en.py` as the English catalog. The language is detected
  from Windows on first start and can be switched in the sidebar (Français / English), with an automatic restart.
- `tests/test_i18n.py`: every UI string must have a translation with identical placeholders.
- English screenshots in `docs/screenshots/en/` (used by the English README).

### Fixed
- Coloured buttons (green, blue, red) now look neutral when disabled; previously a disabled button kept its bright
  colour with grey text, which was hard to read and looked clickable.

## [1.4.0] - 2026-10-20

### Added
- **IPv6 configuration** per adapter and in presets: *unchanged* (default, so older presets never touch IPv6),
  *automatic* (router advertisements / DHCPv6), *static* (address, prefix length, gateway, DNS) or *disabled*
  (`ms_tcpip6` binding). Previous manual addresses and default routes are cleaned up; the link-local address is
  always kept. Applied with `netsh interface ipv6` and included in undo snapshots.
- Current IPv6 state in the configuration panel (mode, global addresses, gateway, DNS) and in the apply summary.

## [1.3.0] - 2026-10-20

### Added
- **System tray icon** (pystray): open NetShift, apply any preset in two clicks (directly on its default adapter,
  or by picking an adapter), adapter status at a glance, quit. Optional "close = minimize to tray" and a Windows
  notification when a change is applied while the window is hidden.
- **Default adapter per preset**, used by Apply, double-click and the tray menu; kept (shown as "absente")
  while the adapter is unplugged.
- **Advanced options** in the configuration editor: interface metric (auto or 1–9999) and connection-specific
  DNS suffix; both shown in the current configuration and captured in the undo history.
- **Manufacturer column** in the network scan, from the embedded IEEE OUI registry (`scripts/update_oui.py`);
  randomized/private MAC addresses are flagged.

### Changed
- New runtime dependencies: `pystray` and `pillow` (the app still starts without them, just without the tray icon).
- GitHub Actions updated (checkout, setup-python, upload-artifact v7, action-gh-release v3).

## [1.2.0] - 2026-10-20

### Added
- **VPN tab**: list Windows VPN connections (current user and all users) with live status and IP; create, edit,
  duplicate, rename, delete (server, tunnel type, authentication, encryption, L2TP pre-shared key, DNS suffix,
  split tunneling and routes); connect with saved credentials, one-time credentials or the Windows dialog;
  disconnect; explanations for common `rasdial` errors. The pre-shared key is never written to the log.
- Adapter types (Ethernet, Wi-Fi, VPN, Bluetooth, mobile, virtual, other) with a badge on each card and
  one-click chips to show or hide each type; count of hidden adapters under the list.

### Changed
- "Virtual adapters" switch replaced by the per-type chips (previous setting migrated).
- Disconnected Wi-Fi / Bluetooth / VPN adapters show "Déconnectée" instead of "Câble déconnecté".

## [1.1.0] - 2026-10-20

### Added
- **Packet capture** tool (Tools → Capture): live IPv4 capture on the selected adapter, colour-coded table,
  packet details and hexdump, Wireshark-style display filters with `and` / `or` / `not`, quick filters,
  syntax help, Ctrl+F, right-click "filter on host / conversation".
- Open `.pcap` and `.pcapng` files (Ethernet, 802.1Q VLAN, ARP, IPv6, raw IP, Linux SLL).
- Capture statistics: protocols, top conversations and hosts.
- Export to `.pcap` and **Open in Wireshark** (live on the selected adapter via Npcap, or on an exported file).
- **Windows installer** (Inno Setup): Start-menu and optional desktop shortcuts, uninstaller; tested
  automatically (install / check / uninstall) in the release workflow.
- New app icon and logo.

### Changed
- Project renamed **NetShift** (formerly IP Manager).
- Installed version stores its data in `%APPDATA%\NetShift`; the portable version keeps `data\` next to the exe.
- Compact adapter and preset cards.
- Release assets now include `SHA256SUMS.txt`.

## [1.0.0] - 2026-10-20

First public release.

### Added
- Adapter list with live status, IP, DHCP/static and APIPA detection; auto-refresh every 5 s.
- Configuration editor: DHCP / static, mask as dotted or CIDR, gateway helper, secondary IPs,
  manual DNS (also in DHCP mode), public DNS shortcuts, live validation.
- Apply via `netsh` with a confirmation summary and a post-apply gateway check.
- Presets: create, edit, duplicate, reorder, search, import/export JSON, apply to any adapter.
- History of applied changes with undo / restore / re-apply; exportable activity log.
- Adapter actions: enable/disable, rename, MTU, DHCP renew/release.
- Tools: native ping and traceroute, ICMP + ARP subnet scan, TCP port check, DNS lookup,
  subnet calculator, public IP, common Windows network commands.
- Light / dark / system theme, automatic UAC elevation with read-only fallback, desktop shortcut.
- Standalone `NetShift.exe` built by GitHub Actions for each release.

[Unreleased]: https://github.com/neoguiri/netshift/compare/v1.5.0...HEAD
[1.5.0]: https://github.com/neoguiri/netshift/compare/v1.4.0...v1.5.0
[1.4.0]: https://github.com/neoguiri/netshift/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/neoguiri/netshift/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/neoguiri/netshift/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/neoguiri/netshift/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/neoguiri/netshift/releases/tag/v1.0.0
