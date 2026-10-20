# Security policy

## Supported versions

Only the latest release receives fixes.

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Use GitHub's
[private vulnerability reporting](https://github.com/neoguiri/netshift/security/advisories/new)
instead. You should get a reply within a week.

## Design notes

NetShift runs with administrator rights in order to change network settings. Relevant points:

- System changes go exclusively through `netsh` and the PowerShell `NetAdapter` cmdlets. `netsh` arguments
  are passed as lists (no shell string building); adapter names used in PowerShell are quoted.
- Presets and history are local JSON files. Importing a preset file only creates presets and never
  executes anything; presets are validated before being applied.
- The app makes no network calls on its own, except the optional public-IP lookup (`api.ipify.org`,
  with fallbacks) when you click that button.
- Release executables are built from source by GitHub Actions. They are not code-signed.
