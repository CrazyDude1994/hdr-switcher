"""
HDR control via Windows Display Config API (ctypes).

Uses DisplayConfigSetDeviceInfo / DisplayConfigGetDeviceInfo with
DISPLAYCONFIG_SET_ADVANCED_COLOR_STATE to toggle HDR on all active displays.
"""
from __future__ import annotations
import ctypes
import ctypes.wintypes
import logging

log = logging.getLogger(__name__)

# ── Win32 constants ────────────────────────────────────────────────────────────
QDC_ONLY_ACTIVE_PATHS = 0x00000002

DISPLAYCONFIG_DEVICE_INFO_GET_ADVANCED_COLOR_INFO = 9
DISPLAYCONFIG_DEVICE_INFO_SET_ADVANCED_COLOR_STATE = 10

ERROR_SUCCESS = 0

# ── ctypes structures ──────────────────────────────────────────────────────────

class LUID(ctypes.Structure):
    """8 bytes: DWORD LowPart + LONG HighPart."""
    _fields_ = [
        ("LowPart",  ctypes.wintypes.DWORD),
        ("HighPart", ctypes.wintypes.LONG),
    ]


class DISPLAYCONFIG_DEVICE_INFO_HEADER(ctypes.Structure):
    """20 bytes."""
    _fields_ = [
        ("type",        ctypes.wintypes.UINT),
        ("size",        ctypes.wintypes.UINT),
        ("adapterId",   LUID),
        ("id",          ctypes.wintypes.UINT),
    ]


class DISPLAYCONFIG_SET_ADVANCED_COLOR_STATE(ctypes.Structure):
    """24 bytes: header(20) + value(4)."""
    _fields_ = [
        ("header", DISPLAYCONFIG_DEVICE_INFO_HEADER),
        ("value",  ctypes.wintypes.UINT),          # bit 0 = enableAdvancedColor
    ]


class DISPLAYCONFIG_GET_ADVANCED_COLOR_INFO(ctypes.Structure):
    """32 bytes: header(20) + value(4) + colorEncoding(4) + bitsPerChannel(4)."""
    _fields_ = [
        ("header",          DISPLAYCONFIG_DEVICE_INFO_HEADER),
        ("value",           ctypes.wintypes.UINT),
        ("colorEncoding",   ctypes.wintypes.UINT),
        ("bitsPerColorChannel", ctypes.wintypes.UINT),
    ]


class DISPLAYCONFIG_RATIONAL(ctypes.Structure):
    _fields_ = [
        ("Numerator",   ctypes.wintypes.UINT),
        ("Denominator", ctypes.wintypes.UINT),
    ]


class DISPLAYCONFIG_PATH_SOURCE_INFO(ctypes.Structure):
    """20 bytes."""
    _fields_ = [
        ("adapterId",       LUID),
        ("id",              ctypes.wintypes.UINT),
        ("modeInfoIdx",     ctypes.wintypes.UINT),
        ("statusFlags",     ctypes.wintypes.UINT),
    ]


class DISPLAYCONFIG_PATH_TARGET_INFO(ctypes.Structure):
    """48 bytes."""
    _fields_ = [
        ("adapterId",           LUID),
        ("id",                  ctypes.wintypes.UINT),
        ("modeInfoIdx",         ctypes.wintypes.UINT),
        ("outputTechnology",    ctypes.wintypes.UINT),
        ("rotation",            ctypes.wintypes.UINT),
        ("scaling",             ctypes.wintypes.UINT),
        ("refreshRate",         DISPLAYCONFIG_RATIONAL),
        ("scanLineOrdering",    ctypes.wintypes.UINT),
        ("targetAvailable",     ctypes.wintypes.BOOL),
        ("statusFlags",         ctypes.wintypes.UINT),
    ]


class DISPLAYCONFIG_PATH_INFO(ctypes.Structure):
    """72 bytes: sourceInfo(20) + targetInfo(48) + flags(4)."""
    _fields_ = [
        ("sourceInfo",  DISPLAYCONFIG_PATH_SOURCE_INFO),
        ("targetInfo",  DISPLAYCONFIG_PATH_TARGET_INFO),
        ("flags",       ctypes.wintypes.UINT),
    ]


# DISPLAYCONFIG_MODE_INFO needs a proper union so ctypes sizes it to 64 bytes.
class _ModeInfoUnion(ctypes.Union):
    class _TargetMode(ctypes.Structure):
        _fields_ = [("targetVideoSignalInfo", ctypes.c_byte * 48)]

    class _SourceMode(ctypes.Structure):
        _fields_ = [("width", ctypes.wintypes.UINT),
                    ("height", ctypes.wintypes.UINT),
                    ("pixelFormat", ctypes.wintypes.UINT),
                    ("position", ctypes.wintypes.POINT)]

    _fields_ = [
        ("targetMode", _TargetMode),
        ("sourceMode", _SourceMode),
        ("padding",    ctypes.c_byte * 48),
    ]


class DISPLAYCONFIG_MODE_INFO(ctypes.Structure):
    """64 bytes: infoType(4) + id(4) + adapterId(8) + union(48)."""
    _fields_ = [
        ("infoType",    ctypes.wintypes.UINT),
        ("id",          ctypes.wintypes.UINT),
        ("adapterId",   LUID),
        ("modeInfo",    _ModeInfoUnion),
    ]


# ── helpers ────────────────────────────────────────────────────────────────────

def _get_active_paths():
    """Return list of DISPLAYCONFIG_PATH_INFO for all active display paths."""
    user32 = ctypes.windll.user32

    num_paths = ctypes.wintypes.UINT(0)
    num_modes = ctypes.wintypes.UINT(0)

    ret = user32.GetDisplayConfigBufferSizes(
        QDC_ONLY_ACTIVE_PATHS,
        ctypes.byref(num_paths),
        ctypes.byref(num_modes),
    )
    if ret != ERROR_SUCCESS:
        raise ctypes.WinError(ret)

    paths = (DISPLAYCONFIG_PATH_INFO * num_paths.value)()
    modes = (DISPLAYCONFIG_MODE_INFO * num_modes.value)()

    ret = user32.QueryDisplayConfig(
        QDC_ONLY_ACTIVE_PATHS,
        ctypes.byref(num_paths),
        paths,
        ctypes.byref(num_modes),
        modes,
        None,
    )
    if ret != ERROR_SUCCESS:
        raise ctypes.WinError(ret)

    return list(paths)


# ── public API ─────────────────────────────────────────────────────────────────

def set_hdr(enable: bool) -> bool:
    """Enable or disable HDR on all available displays. Returns True on success."""
    try:
        paths = _get_active_paths()
    except OSError as e:
        log.error("Failed to query display config: %s", e)
        return False

    success = True
    for path in paths:
        if not path.targetInfo.targetAvailable:
            continue

        req = DISPLAYCONFIG_SET_ADVANCED_COLOR_STATE()
        req.header.type = DISPLAYCONFIG_DEVICE_INFO_SET_ADVANCED_COLOR_STATE
        req.header.size = ctypes.sizeof(DISPLAYCONFIG_SET_ADVANCED_COLOR_STATE)
        req.header.adapterId = path.targetInfo.adapterId
        req.header.id = path.targetInfo.id
        req.value = 1 if enable else 0

        ret = ctypes.windll.user32.DisplayConfigSetDeviceInfo(ctypes.byref(req))
        if ret != ERROR_SUCCESS:
            log.warning(
                "DisplayConfigSetDeviceInfo failed for target %d: error %d",
                path.targetInfo.id, ret,
            )
            success = False
        else:
            log.debug(
                "HDR %s for target id=%d",
                "enabled" if enable else "disabled",
                path.targetInfo.id,
            )

    return success


def get_hdr_state() -> bool | None:
    """
    Read the current HDR state from the first available display.
    Returns True/False, or None on error.
    """
    try:
        paths = _get_active_paths()
    except OSError as e:
        log.error("Failed to query display config: %s", e)
        return None

    for path in paths:
        if not path.targetInfo.targetAvailable:
            continue

        req = DISPLAYCONFIG_GET_ADVANCED_COLOR_INFO()
        req.header.type = DISPLAYCONFIG_DEVICE_INFO_GET_ADVANCED_COLOR_INFO
        req.header.size = ctypes.sizeof(DISPLAYCONFIG_GET_ADVANCED_COLOR_INFO)
        req.header.adapterId = path.targetInfo.adapterId
        req.header.id = path.targetInfo.id

        ret = ctypes.windll.user32.DisplayConfigGetDeviceInfo(ctypes.byref(req))
        if ret == ERROR_SUCCESS:
            # bit 0 of value = advancedColorSupported
            # bit 1 of value = advancedColorEnabled
            enabled = bool(req.value & 0x2)
            log.debug("HDR state query: value=0x%X enabled=%s", req.value, enabled)
            return enabled

    log.warning("No available display targets found")
    return None
