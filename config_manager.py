"""
Config persistence for HDR Switcher.

Config file is stored as JSON next to this script (config.json).
Writes are atomic: write to a temp file then rename.
"""
import json
import logging
import os
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List

log = logging.getLogger(__name__)

# Config lives alongside main.py / this file.
_SCRIPT_DIR = Path(sys.argv[0]).resolve().parent
CONFIG_PATH = _SCRIPT_DIR / "config.json"


@dataclass
class AppEntry:
    name: str           # human-readable label
    process: str        # e.g. "Cyberpunk2077.exe"
    enabled: bool = True


@dataclass
class Config:
    apps: List[AppEntry] = field(default_factory=list)
    restore_delay: float = 5.0          # seconds before disabling HDR
    start_with_windows: bool = False


# ── serialisation helpers ──────────────────────────────────────────────────────

def _config_to_dict(cfg: Config) -> dict:
    d = asdict(cfg)
    return d


def _dict_to_config(d: dict) -> Config:
    apps = [AppEntry(**a) for a in d.get("apps", [])]
    return Config(
        apps=apps,
        restore_delay=float(d.get("restore_delay", 5.0)),
        start_with_windows=bool(d.get("start_with_windows", False)),
    )


# ── public API ─────────────────────────────────────────────────────────────────

def load_config() -> Config:
    """Load config from disk; returns a default Config if file is missing/invalid."""
    if not CONFIG_PATH.exists():
        log.info("No config file found at %s, using defaults.", CONFIG_PATH)
        return Config()
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        cfg = _dict_to_config(data)
        log.info("Loaded config from %s (%d apps)", CONFIG_PATH, len(cfg.apps))
        return cfg
    except Exception as e:
        log.error("Failed to load config: %s — using defaults.", e)
        return Config()


def save_config(cfg: Config) -> None:
    """Save config atomically (write temp, then rename)."""
    data = _config_to_dict(cfg)
    try:
        dir_ = CONFIG_PATH.parent
        fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".tmp", text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            os.unlink(tmp_path)
            raise
        # Atomic rename
        os.replace(tmp_path, CONFIG_PATH)
        log.info("Config saved to %s", CONFIG_PATH)
    except Exception as e:
        log.error("Failed to save config: %s", e)
        raise
