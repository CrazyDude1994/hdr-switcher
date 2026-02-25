# HDR Switcher

A Windows system tray app that automatically toggles **Windows HD Color (HDR)** based on which processes are running. Launch a game — HDR turns on. Close it — HDR turns off after a configurable delay.

## Features

- Automatically enables HDR when a monitored process starts
- Disables HDR after a configurable delay once all monitored apps close
- System tray icon shows current HDR state (off / on / paused)
- GUI app manager to add/remove monitored processes
- "Pause Monitoring" to temporarily suppress all automatic toggling
- "Toggle HDR Now" for manual override
- Optional start with Windows (via registry)

## Requirements

- Windows 10/11 with an HDR-capable display
- Python 3.8+

## Installation

```
pip install -r requirements.txt
```

Or run the helper:

```
install.bat
```

## Usage

```
python main.py          # with console (useful for debugging)
pythonw main.py         # silent background launch (no console window)
```

The app runs in the system tray. Right-click the icon to access the menu.

## Configuration

Open **Manage Apps…** from the tray menu to:

- Add processes to monitor (pick from running processes or enter manually)
- Remove processes
- Set the restore delay (seconds to wait before disabling HDR after apps close)
- Enable/disable start with Windows

Settings are saved to `config.json` next to the script.

## How it works

- Uses the Windows **Display Config API** (`DisplayConfigSetDeviceInfo`) via ctypes to toggle HDR on all active displays
- Polls the process list with `psutil` every second
- All state mutations are lock-protected across threads

## File structure

```
hdr-switcher/
├── main.py            — entry point + logging
├── hdr_control.py     — Windows Display Config API (ctypes)
├── process_monitor.py — psutil polling + callbacks
├── config_manager.py  — config dataclasses + JSON persistence
├── tray_app.py        — tray icon + App Manager GUI
├── requirements.txt
└── install.bat
```

## Logging

Logs are written to `hdr_switcher.log` next to the script.
