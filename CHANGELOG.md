# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

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

[Unreleased]: https://github.com/neoguiri/netshift/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/neoguiri/netshift/releases/tag/v1.0.0
