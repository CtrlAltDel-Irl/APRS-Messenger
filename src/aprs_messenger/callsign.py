"""Amateur radio callsign validation helpers."""

from __future__ import annotations

import re

# ITU-style amateur callsigns: optional prefix digit, 1–2 letters, digit, 1–4 letters/digits
# Allows common variants like W1AW, G0ABC, VK2XYZ, 2E0ABC, JA1YXX, N0CALL-7 (SSID stripped for check)
_CALL_RE = re.compile(
    r"^(?:[0-9][A-Z]{1,2}|[A-Z]{1,2})[0-9][A-Z0-9]{1,4}$",
    re.IGNORECASE,
)


def normalize_callsign(call: str) -> str:
    """Uppercase and strip; keep SSID if present (e.g. N0CALL-7)."""
    call = (call or "").strip().upper()
    # collapse internal spaces
    call = re.sub(r"\s+", "", call)
    return call


def base_callsign(call: str) -> str:
    """Return callsign without SSID."""
    call = normalize_callsign(call)
    if "-" in call:
        return call.split("-", 1)[0]
    return call


def is_valid_callsign(call: str) -> bool:
    """Basic structural validation of an amateur callsign (base, no SSID)."""
    base = base_callsign(call)
    if not base or len(base) < 3 or len(base) > 9:
        return False
    return bool(_CALL_RE.match(base))


def is_valid_destination(call: str) -> bool:
    """
    Valid chat destination: standard callsign, or APRS bot/gateway style
    (letters, digits, hyphen; 3–9 chars), e.g. EMAIL-2, SMSGTE, WXBOT.
    """
    c = normalize_callsign(call)
    if is_valid_callsign(c):
        return True
    if not c or len(c) < 3 or len(c) > 9:
        return False
    return bool(re.match(r"^[A-Z0-9][A-Z0-9\-]{1,8}$", c))


_GRID_RE = re.compile(r"^[A-R]{2}[0-9]{2}([A-X]{2})?$", re.IGNORECASE)


def is_valid_grid(grid: str) -> bool:
    """Maidenhead locator: 4 or 6 characters (e.g. FN31, IO91wm)."""
    g = (grid or "").strip().upper()
    if len(g) not in (4, 6):
        return False
    return bool(_GRID_RE.match(g))


def normalize_grid(grid: str) -> str:
    g = (grid or "").strip().upper()
    if len(g) >= 4:
        # field uppercase, square digits, subsquare lowercase traditionally but we store upper
        return g[:6]
    return g


def aprs_addressee(call: str) -> str:
    """APRS message addressee field: 9 characters, space-padded on the right."""
    c = normalize_callsign(call)
    if len(c) > 9:
        c = c[:9]
    return c.ljust(9)
