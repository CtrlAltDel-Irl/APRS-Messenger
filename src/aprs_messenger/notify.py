"""Audio + visual notification helpers for new messages."""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import wave
from pathlib import Path

log = logging.getLogger(__name__)

_SOUNDS = [
    "/usr/share/sounds/freedesktop/stereo/message-new-instant.oga",
    "/usr/share/sounds/freedesktop/stereo/message.oga",
    "/usr/share/sounds/freedesktop/stereo/complete.oga",
    "/usr/share/sounds/gnome/default/alerts/bell.ogg",
    "/usr/share/sounds/freedesktop/stereo/bell.oga",
]


def _find_system_sound() -> str | None:
    for p in _SOUNDS:
        if Path(p).is_file():
            return p
    return None


def _play_file(path: str) -> bool:
    for cmd in (
        ["paplay", path],
        ["pw-play", path],
        ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path],
        ["mpv", "--no-video", "--really-quiet", path],
        ["aplay", path],
    ):
        if not shutil.which(cmd[0]):
            continue
        try:
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except OSError:
            continue
    return False


def _synthesize_bell_wav(path: Path) -> None:
    """Write a short two-tone 'ring' WAV (no external deps)."""
    import math
    import struct

    rate = 22050
    duration = 0.55
    n = int(rate * duration)
    frames = bytearray()
    for i in range(n):
        t = i / rate
        # two-tone ring
        f = 880.0 if (int(t * 6) % 2 == 0) else 660.0
        env = 0.0
        if t < 0.02:
            env = t / 0.02
        elif t > duration - 0.05:
            env = max(0.0, (duration - t) / 0.05)
        else:
            env = 1.0
        # pulse pattern
        if int(t * 4) % 2 == 1:
            env *= 0.15
        sample = int(16000 * env * math.sin(2 * math.pi * f * t))
        frames += struct.pack("<h", max(-32767, min(32767, sample)))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))


def play_message_bell() -> None:
    """Play a ringing-bell style alert in a background thread."""

    def _run() -> None:
        try:
            snd = _find_system_sound()
            if snd and _play_file(snd):
                return
            # fallback synthesized ring
            cache = Path.home() / ".cache" / "aprs-messenger" / "ring.wav"
            if not cache.is_file():
                _synthesize_bell_wav(cache)
            if _play_file(str(cache)):
                return
            # last resort: terminal bell
            print("\a", end="", flush=True)
        except Exception:
            log.exception("notification sound failed")

    threading.Thread(target=_run, name="notify-bell", daemon=True).start()
