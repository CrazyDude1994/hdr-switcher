"""
System tray application for HDR Switcher.

- pystray handles the tray icon and menu (runs on the main thread).
- App Manager GUI uses tkinter (opened in a per-window daemon thread).
- HDR state machine with optional restore delay timer.
"""
from __future__ import annotations
import logging
import threading
import tkinter as tk
import winreg
from tkinter import messagebox, ttk

import psutil
import pystray
from PIL import Image, ImageDraw, ImageFont

import hdr_control
from config_manager import AppEntry, Config, load_config, save_config
from process_monitor import ProcessMonitor

log = logging.getLogger(__name__)

# ── icon drawing ───────────────────────────────────────────────────────────────

_ICON_SIZE = 64
_FONT_SIZE = 20


def _make_icon(state: str) -> Image.Image:
    """
    state: "off" | "on" | "paused"
    Returns a 64x64 PIL RGBA image.
    """
    colors = {
        "off":    "#3C3C3C",
        "on":     "#0078D4",
        "paused": "#B87800",
    }
    bg = colors.get(state, "#3C3C3C")

    img = Image.new("RGBA", (_ICON_SIZE, _ICON_SIZE), bg)
    draw = ImageDraw.Draw(img)

    # Try to load a small system font; fall back to default
    try:
        font = ImageFont.truetype("arial.ttf", _FONT_SIZE)
    except Exception:
        font = ImageFont.load_default()

    text = "HDR"
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    x = (_ICON_SIZE - w) // 2
    y = (_ICON_SIZE - h) // 2
    draw.text((x, y), text, fill="white", font=font)

    if state == "on":
        # bright dot in top-right corner
        draw.ellipse([48, 4, 60, 16], fill="#00FF88")

    return img


# ── registry helpers ───────────────────────────────────────────────────────────

_REG_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
_REG_KEY = "HDRSwitcher"


def _set_startup(enabled: bool, script_path: str) -> None:
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _REG_RUN,
            0, winreg.KEY_SET_VALUE,
        )
        with key:
            if enabled:
                value = f'pythonw.exe "{script_path}"'
                winreg.SetValueEx(key, _REG_KEY, 0, winreg.REG_SZ, value)
                log.info("Start-with-Windows enabled: %s", value)
            else:
                try:
                    winreg.DeleteValue(key, _REG_KEY)
                    log.info("Start-with-Windows disabled")
                except FileNotFoundError:
                    pass
    except Exception as e:
        log.error("Registry error: %s", e)


# ── App Manager window ─────────────────────────────────────────────────────────

class AppManagerWindow:
    """
    Opens a tkinter Tk() window (in its own thread) for managing the app list.
    """

    def __init__(self, config: Config, on_save: "Callable[[Config], None]"):
        self._config = Config(
            apps=list(config.apps),
            restore_delay=config.restore_delay,
            start_with_windows=config.start_with_windows,
        )
        self._on_save = on_save

    def open(self) -> None:
        t = threading.Thread(target=self._run, name="AppManager", daemon=True)
        t.start()

    def _run(self) -> None:
        root = tk.Tk()
        root.title("HDR Switcher — App Manager")
        root.resizable(False, False)
        root.geometry("480x460")

        self._build_ui(root)
        root.mainloop()

    def _build_ui(self, root: tk.Tk) -> None:
        # ── App list ──────────────────────────────────────────────────────────
        list_frame = ttk.LabelFrame(root, text="Monitored Applications", padding=8)
        list_frame.pack(fill="both", expand=True, padx=10, pady=(10, 4))

        cols = ("Name", "Process", "Enabled")
        self._tree = ttk.Treeview(
            list_frame, columns=cols, show="headings", height=8
        )
        for col in cols:
            self._tree.heading(col, text=col)
        self._tree.column("Name",    width=140)
        self._tree.column("Process", width=180)
        self._tree.column("Enabled", width=60, anchor="center")

        sb = ttk.Scrollbar(list_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        self._tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self._refresh_tree()

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_frame = ttk.Frame(root)
        btn_frame.pack(fill="x", padx=10, pady=4)

        ttk.Button(btn_frame, text="Add from running…",
                   command=self._add_from_running).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="Add manually…",
                   command=self._add_manually).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="Remove selected",
                   command=self._remove_selected).pack(side="left", padx=2)

        # ── Settings ──────────────────────────────────────────────────────────
        cfg_frame = ttk.LabelFrame(root, text="Settings", padding=8)
        cfg_frame.pack(fill="x", padx=10, pady=4)

        ttk.Label(cfg_frame, text="Restore delay (s):").grid(
            row=0, column=0, sticky="w"
        )
        self._delay_var = tk.DoubleVar(value=self._config.restore_delay)
        ttk.Spinbox(
            cfg_frame, from_=0, to=300, increment=1,
            textvariable=self._delay_var, width=6,
        ).grid(row=0, column=1, sticky="w", padx=4)

        self._startup_var = tk.BooleanVar(value=self._config.start_with_windows)
        ttk.Checkbutton(
            cfg_frame, text="Start with Windows",
            variable=self._startup_var,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))

        # ── Save / Close ──────────────────────────────────────────────────────
        bottom = ttk.Frame(root)
        bottom.pack(fill="x", padx=10, pady=8)
        ttk.Button(bottom, text="Save", command=self._save,
                   style="Accent.TButton").pack(side="right", padx=2)
        ttk.Button(bottom, text="Close",
                   command=root.destroy).pack(side="right", padx=2)

        self._root = root

    def _refresh_tree(self) -> None:
        self._tree.delete(*self._tree.get_children())
        for app in self._config.apps:
            self._tree.insert(
                "", "end",
                values=(app.name, app.process, "Yes" if app.enabled else "No"),
            )

    def _add_from_running(self) -> None:
        """Show a Toplevel picklist of currently running processes."""
        top = tk.Toplevel(self._root)
        top.title("Select a running process")
        top.geometry("360x400")
        top.grab_set()

        ttk.Label(top, text="Double-click to add:").pack(pady=(8, 2))

        lb_frame = ttk.Frame(top)
        lb_frame.pack(fill="both", expand=True, padx=8, pady=4)

        sb = ttk.Scrollbar(lb_frame)
        sb.pack(side="right", fill="y")
        lb = tk.Listbox(lb_frame, yscrollcommand=sb.set, selectmode="single")
        lb.pack(fill="both", expand=True)
        sb.config(command=lb.yview)

        seen: set[str] = set()
        procs: list[str] = []
        for p in psutil.process_iter(["name"]):
            try:
                name = p.info["name"] or ""
                if name and name.lower() not in seen:
                    seen.add(name.lower())
                    procs.append(name)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        procs.sort(key=str.lower)
        for n in procs:
            lb.insert("end", n)

        def on_select(event=None):
            sel = lb.curselection()
            if not sel:
                return
            proc_name = lb.get(sel[0])
            display_name = proc_name.rsplit(".", 1)[0]  # strip .exe
            self._add_app(AppEntry(name=display_name, process=proc_name))
            top.destroy()

        lb.bind("<Double-Button-1>", on_select)
        ttk.Button(top, text="Add", command=on_select).pack(pady=4)

    def _add_manually(self) -> None:
        top = tk.Toplevel(self._root)
        top.title("Add application")
        top.geometry("300x140")
        top.grab_set()

        ttk.Label(top, text="Display name:").grid(row=0, column=0, padx=8, pady=8, sticky="w")
        name_var = tk.StringVar()
        ttk.Entry(top, textvariable=name_var, width=22).grid(row=0, column=1, padx=4)

        ttk.Label(top, text="Process (e.g. game.exe):").grid(row=1, column=0, padx=8, sticky="w")
        proc_var = tk.StringVar()
        ttk.Entry(top, textvariable=proc_var, width=22).grid(row=1, column=1, padx=4)

        def do_add():
            name = name_var.get().strip()
            proc = proc_var.get().strip()
            if not name or not proc:
                messagebox.showwarning("Missing fields", "Both fields are required.", parent=top)
                return
            self._add_app(AppEntry(name=name, process=proc))
            top.destroy()

        ttk.Button(top, text="Add", command=do_add).grid(
            row=2, column=0, columnspan=2, pady=12
        )

    def _add_app(self, entry: AppEntry) -> None:
        existing = [a.process.lower() for a in self._config.apps]
        if entry.process.lower() in existing:
            messagebox.showinfo(
                "Already added",
                f"{entry.process} is already in the list.",
                parent=self._root,
            )
            return
        self._config.apps.append(entry)
        self._refresh_tree()

    def _remove_selected(self) -> None:
        sel = self._tree.selection()
        if not sel:
            return
        idx = self._tree.index(sel[0])
        self._config.apps.pop(idx)
        self._refresh_tree()

    def _save(self) -> None:
        self._config.restore_delay = self._delay_var.get()
        self._config.start_with_windows = self._startup_var.get()
        try:
            save_config(self._config)
        except Exception as e:
            messagebox.showerror("Save failed", str(e), parent=self._root)
            return
        self._on_save(self._config)
        messagebox.showinfo("Saved", "Configuration saved.", parent=self._root)


# ── Main tray application ──────────────────────────────────────────────────────

class HDRSwitcherApp:
    def __init__(self, script_path: str):
        self._script_path = script_path
        self._config = load_config()

        self._hdr_managed = False       # did we enable HDR?
        self._paused = False
        self._restore_timer: threading.Timer | None = None
        self._lock = threading.Lock()

        self._monitor = ProcessMonitor(
            on_started=self._on_process_started,
            on_all_stopped=self._on_all_processes_stopped,
        )
        self._monitor.set_monitored(self._enabled_process_names())

        self._icon: pystray.Icon | None = None

    # ── helpers ────────────────────────────────────────────────────────────────

    def _enabled_process_names(self) -> set:
        return {
            a.process.lower()
            for a in self._config.apps
            if a.enabled
        }

    def _current_icon_state(self) -> str:
        if self._paused:
            return "paused"
        if self._hdr_managed:
            return "on"
        return "off"

    def _update_icon(self) -> None:
        if self._icon is None:
            return
        state = self._current_icon_state()
        self._icon.icon = _make_icon(state)
        self._build_menu()

    def _build_menu(self) -> None:
        if self._icon is None:
            return

        state_label = "HDR: ON" if self._hdr_managed else "HDR: OFF"

        self._icon.menu = pystray.Menu(
            pystray.MenuItem(state_label, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Manage Apps…", self._open_app_manager),
            pystray.MenuItem("Toggle HDR Now", self._toggle_hdr_now),
            pystray.MenuItem(
                "Pause Monitoring",
                self._toggle_pause,
                checked=lambda item: self._paused,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", self._exit),
        )

    # ── process callbacks ──────────────────────────────────────────────────────

    def _on_process_started(self, name: str) -> None:
        with self._lock:
            self._cancel_restore_timer()
            if self._paused:
                log.info("Paused — ignoring start of %s", name)
                return
            if not self._hdr_managed:
                log.info("Enabling HDR (triggered by %s)", name)
                hdr_control.set_hdr(True)
                self._hdr_managed = True
                self._update_icon()

    def _on_all_processes_stopped(self) -> None:
        with self._lock:
            if not self._hdr_managed or self._paused:
                return
            delay = self._config.restore_delay
            log.info("All monitored apps stopped; scheduling HDR disable in %.1fs", delay)
            self._start_restore_timer(delay)

    # ── restore timer ──────────────────────────────────────────────────────────

    def _start_restore_timer(self, delay: float) -> None:
        self._cancel_restore_timer()
        if delay <= 0:
            self._do_restore()
        else:
            t = threading.Timer(delay, self._do_restore)
            t.daemon = True
            t.start()
            self._restore_timer = t

    def _cancel_restore_timer(self) -> None:
        if self._restore_timer is not None:
            self._restore_timer.cancel()
            self._restore_timer = None

    def _do_restore(self) -> None:
        with self._lock:
            self._restore_timer = None
            if self._hdr_managed and not self._paused:
                log.info("Disabling HDR (restore timer fired)")
                hdr_control.set_hdr(False)
                self._hdr_managed = False
                self._update_icon()

    # ── menu actions ───────────────────────────────────────────────────────────

    def _toggle_pause(self, icon, item) -> None:
        with self._lock:
            self._paused = not self._paused
            log.info("Monitoring %s", "paused" if self._paused else "resumed")
            if not self._paused and self._restore_timer is None and self._hdr_managed:
                # If apps are gone while paused, start the timer now
                if not self._monitor._active:
                    self._start_restore_timer(self._config.restore_delay)
        self._update_icon()

    def _toggle_hdr_now(self, icon, item) -> None:
        with self._lock:
            self._cancel_restore_timer()
            if self._hdr_managed:
                log.info("Manual HDR disable")
                hdr_control.set_hdr(False)
                self._hdr_managed = False
            else:
                log.info("Manual HDR enable")
                hdr_control.set_hdr(True)
                self._hdr_managed = True
        self._update_icon()

    def _open_app_manager(self, icon, item) -> None:
        win = AppManagerWindow(
            config=self._config,
            on_save=self._on_config_saved,
        )
        win.open()

    def _on_config_saved(self, new_config: Config) -> None:
        with self._lock:
            self._config = new_config
            self._monitor.set_monitored(self._enabled_process_names())
            _set_startup(new_config.start_with_windows, self._script_path)
        log.info("Config reloaded: %d apps", len(new_config.apps))

    def _exit(self, icon, item) -> None:
        log.info("Exiting")
        self._monitor.stop()
        self._cancel_restore_timer()
        if self._icon:
            self._icon.stop()

    # ── run ────────────────────────────────────────────────────────────────────

    def run(self) -> None:
        self._monitor.start()

        icon_img = _make_icon(self._current_icon_state())
        self._icon = pystray.Icon(
            "HDRSwitcher",
            icon=icon_img,
            title="HDR Switcher",
        )
        self._build_menu()

        log.info("Tray icon starting")
        self._icon.run()
