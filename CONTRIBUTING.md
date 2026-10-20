# Contributing to NetShift

Thanks for your interest! Issues and pull requests are welcome, in **English or French**.

## Reporting bugs

Open an [issue](https://github.com/neoguiri/netshift/issues/new/choose) with:

- your Windows version and how you run the app (`.exe`, or source + Python version);
- what you did, what you expected, and what happened;
- the relevant lines from **Historique & journal → Journal** (the exact `netsh` commands are logged there).

Remove anything you consider sensitive (internal IPs, hostnames, MAC addresses) before posting.

## Development setup

```bat
git clone https://github.com/neoguiri/netshift.git
cd netshift
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
python NetShift.pyw --no-elevate
```

`--no-elevate` skips the UAC prompt and starts in read-only mode. To test applying configurations,
run from an elevated terminal or drop the flag. **Tip:** test on a spare USB Ethernet adapter so you
never cut your own connection.

## Checks

```bat
ruff check .
pytest
```

Both run in CI on every push and pull request (Windows, Python 3.9 and 3.12).

## Project layout

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). In short: `netbackend.py` talks to Windows,
`nettools.py` holds the network tools, `store.py` handles persistence, and `ui.py`, `app.py` and
`tools_view.py` make up the GUI.

## Guidelines

- Keep runtime dependencies minimal: CustomTkinter plus the standard library.
- Never block the UI thread: run system calls with `App.bg(...)`, or a thread plus `App.ui(...)`.
- Anything that modifies the system must ask for confirmation and appear in the log.
- Add or update tests for pure logic (validation, command building, parsing).
- Follow the existing style (ruff config in `pyproject.toml`, line length 120).
- UI strings are currently French; keep new strings easy to extract for future i18n.

## Screenshots

`python scripts/make_screenshots.py` regenerates `docs/screenshots/` using **fictitious** data only:
no real adapter, network or host information is captured. Set `THEME=light` for the light variants.

The script renders the app window itself (Win32 `PrintWindow`), so other windows on your screen can never
end up in an image. `tests/test_screenshots.py` additionally fails if any committed screenshot is not purely
the NetShift window. **Always open every image before committing it.**

## Releasing

1. Update `__version__` in `netshift/__init__.py`, `version` in `pyproject.toml`, and `CHANGELOG.md`.
2. Tag and push: `git tag v1.1.0 && git push origin v1.1.0`.
3. The *Release* workflow builds `NetShift.exe` and publishes the GitHub release.
