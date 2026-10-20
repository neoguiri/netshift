# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

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

[Unreleased]: https://github.com/neoguiri/netshift/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/neoguiri/netshift/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/neoguiri/netshift/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/neoguiri/netshift/releases/tag/v1.0.0
