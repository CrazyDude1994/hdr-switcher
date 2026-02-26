"""
HDR Switcher — entry point.

Logs to both hdr_switcher.log (next to this script) and stdout.
Launch with:   python main.py        (shows console for debugging)
               pythonw main.py       (no console, background/tray only)
"""
import logging
import os
import sys
from pathlib import Path

# ── logging ────────────────────────────────────────────────────────────────────

def _setup_logging() -> None:
    if getattr(sys, "frozen", False):
        # Frozen exe: write log to %APPDATA%\HDRSwitcher\ (same dir as config)
        appdata = os.environ.get("APPDATA") or str(Path.home())
        log_dir = Path(appdata) / "HDRSwitcher"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "hdr_switcher.log"
    else:
        script_dir = Path(sys.argv[0]).resolve().parent
        log_file = script_dir / "hdr_switcher.log"

    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    handlers: list[logging.Handler] = [
        logging.FileHandler(log_file, encoding="utf-8"),
    ]
    # Only add StreamHandler when there is actually a terminal attached
    if sys.stdout and sys.stdout.isatty():
        handlers.append(logging.StreamHandler(sys.stdout))
    # Also add it when running with a real console (python, not pythonw)
    elif sys.stdout is not None:
        try:
            handlers.append(logging.StreamHandler(sys.stdout))
        except Exception:
            pass

    logging.basicConfig(level=logging.DEBUG, format=fmt, datefmt=datefmt,
                        handlers=handlers)

    # Quiet noisy third-party loggers
    logging.getLogger("PIL").setLevel(logging.WARNING)
    logging.getLogger("pystray").setLevel(logging.WARNING)


# ── entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    _setup_logging()
    log = logging.getLogger(__name__)
    log.info("HDR Switcher starting (Python %s)", sys.version.split()[0])

    # Import here so logging is configured first
    from tray_app import HDRSwitcherApp

    script_path = str(Path(sys.argv[0]).resolve())
    app = HDRSwitcherApp(script_path=script_path)
    app.run()


if __name__ == "__main__":
    main()
