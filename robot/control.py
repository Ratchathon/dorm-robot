"""Pure control logic: turn untrusted WebSocket JSON into a safe ESP32 command.

Nothing here touches hardware, so it can be unit-tested on any laptop.
Protocol to the ESP32 is unchanged: {"move": {...4 bools}, "tilt": int 0-180, "blower": bool}
"""

import math
import threading

DEFAULT_TILT = 90
TILT_MIN, TILT_MAX = 0, 180
DIRECTIONS = ("forward", "backward", "left", "right")


def _parse_tilt(value, fallback: int) -> int:
    if isinstance(value, bool):  # bool is an int subclass; never a real angle
        return fallback
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(number):
        return fallback
    return max(TILT_MIN, min(TILT_MAX, int(number)))


def sanitize_command(raw, last_tilt: int = DEFAULT_TILT) -> dict:
    """Never raises. Anything unexpected becomes 'not pressed' / 'keep last tilt'."""
    if not isinstance(raw, dict):
        return stop_command(last_tilt)

    move_raw = raw.get("move")
    move_raw = move_raw if isinstance(move_raw, dict) else {}
    move = {d: move_raw.get(d) is True for d in DIRECTIONS}
    # Opposite keys held together cancel, so the ESP32 never gets a contradictory order.
    if move["forward"] and move["backward"]:
        move["forward"] = move["backward"] = False
    if move["left"] and move["right"]:
        move["left"] = move["right"] = False

    return {
        "move": move,
        "tilt": _parse_tilt(raw.get("tilt"), last_tilt) if "tilt" in raw else last_tilt,
        "blower": raw.get("blower") is True,
    }


def stop_command(last_tilt: int = DEFAULT_TILT) -> dict:
    """Stop wheels and blower but leave the camera where it was aimed."""
    return {"move": {d: False for d in DIRECTIONS}, "tilt": last_tilt, "blower": False}


class ControllerLock:
    """Only one browser may drive at a time; others can watch the video."""

    def __init__(self):
        self._holder = None
        self._lock = threading.Lock()

    @property
    def holder(self):
        return self._holder

    def acquire(self, who) -> bool:
        with self._lock:
            if self._holder is None or self._holder == who:
                self._holder = who
                return True
            return False

    def release(self, who) -> None:
        with self._lock:
            if self._holder == who:
                self._holder = None
