"""
Process monitor: polls psutil every second and fires callbacks when
monitored processes start or all stop.
"""
from __future__ import annotations
import logging
import threading
import time
from typing import Callable, Set

import psutil

log = logging.getLogger(__name__)


class ProcessMonitor:
    """
    Polls the process list every `interval` seconds.

    Callbacks:
        on_started(name: str)  — called when the first monitored app launches
        on_all_stopped()       — called when the last monitored app closes
    """

    def __init__(
        self,
        on_started: Callable[[str], None],
        on_all_stopped: Callable[[], None],
        interval: float = 1.0,
    ):
        self.on_started = on_started
        self.on_all_stopped = on_all_stopped
        self.interval = interval

        self.monitored: Set[str] = set()   # lowercase process names
        self._active: Set[str] = set()     # currently-running monitored procs

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    # ── public API ─────────────────────────────────────────────────────────────

    def set_monitored(self, names: Set[str]) -> None:
        """Update the set of watched process names (lowercase)."""
        self.monitored = {n.lower() for n in names}
        log.debug("Monitored processes: %s", self.monitored)

    def start(self) -> None:
        """Start the polling daemon thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, name="ProcessMonitor", daemon=True
        )
        self._thread.start()
        log.info("ProcessMonitor started (interval=%.1fs)", self.interval)

    def stop(self) -> None:
        """Stop the polling thread."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        log.info("ProcessMonitor stopped")

    # ── internals ──────────────────────────────────────────────────────────────

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._poll()
            except Exception as e:
                log.error("ProcessMonitor poll error: %s", e)
            self._stop_event.wait(self.interval)

    def _poll(self) -> None:
        if not self.monitored:
            if self._active:
                # All were cleared from config — treat as stopped
                self._active.clear()
            return

        running: Set[str] = set()
        try:
            for proc in psutil.process_iter(["name"]):
                try:
                    name = (proc.info["name"] or "").lower()
                    if name in self.monitored:
                        running.add(name)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception as e:
            log.debug("process_iter error: %s", e)
            return

        prev_active = self._active
        new_active = running

        started = new_active - prev_active
        stopped = prev_active - new_active

        if started:
            log.info("Monitored process(es) started: %s", started)
            self._active = new_active
            for name in started:
                try:
                    self.on_started(name)
                except Exception as e:
                    log.error("on_started callback error: %s", e)

        if stopped:
            self._active = new_active
            log.info("Monitored process(es) stopped: %s", stopped)
            if not self._active:
                try:
                    self.on_all_stopped()
                except Exception as e:
                    log.error("on_all_stopped callback error: %s", e)

        if not started and not stopped:
            # keep _active in sync quietly
            self._active = new_active
