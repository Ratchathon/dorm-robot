import pytest

from control import (
    DEFAULT_TILT,
    ControllerLock,
    sanitize_command,
    stop_command,
)


def cmd(**kw):
    base = {"move": {"forward": False, "backward": False, "left": False, "right": False},
            "tilt": 90, "blower": False}
    base.update(kw)
    return base


# ---------- sanitize_command: never raises, always returns a safe dict ----------

@pytest.mark.parametrize("raw", [None, [], "hello", 42, 3.5, True])
def test_non_dict_input_becomes_stop_with_default_tilt(raw):
    out = sanitize_command(raw)
    assert out == cmd(tilt=DEFAULT_TILT)


def test_valid_command_passes_through():
    raw = cmd(move={"forward": True, "backward": False, "left": True, "right": False}, tilt=120, blower=True)
    assert sanitize_command(raw) == raw


@pytest.mark.parametrize("tilt, expected", [
    ("abc", 77), (None, 77), ([], 77), ({}, 77), (float("nan"), 77), (float("inf"), 77),
    (-10, 0), (999, 180), (45.7, 45), ("100", 100),
])
def test_bad_or_out_of_range_tilt_falls_back_or_clamps(tilt, expected):
    out = sanitize_command({"tilt": tilt}, last_tilt=77)
    assert out["tilt"] == expected


def test_missing_tilt_keeps_last_tilt_not_90():
    assert sanitize_command({"move": {"forward": True}}, last_tilt=33)["tilt"] == 33


def test_move_not_a_dict_means_no_movement():
    out = sanitize_command({"move": "forward"})
    assert out["move"] == {"forward": False, "backward": False, "left": False, "right": False}


def test_only_strict_true_counts_as_pressed():
    out = sanitize_command({"move": {"forward": "yes", "left": 1, "right": True}, "blower": "true"})
    assert out["move"]["forward"] is False
    assert out["move"]["left"] is False
    assert out["move"]["right"] is True
    assert out["blower"] is False


def test_opposite_directions_cancel_out():
    out = sanitize_command({"move": {"forward": True, "backward": True, "left": True, "right": True}})
    assert out["move"] == {"forward": False, "backward": False, "left": False, "right": False}


def test_unknown_fields_are_dropped():
    out = sanitize_command({**cmd(), "pan": 10, "evil": "x"})
    assert set(out) == {"move", "tilt", "blower"}


# ---------- stop_command: stop wheels + blower, keep camera where it is ----------

def test_stop_keeps_tilt_and_stops_everything_else():
    assert stop_command(last_tilt=35) == cmd(tilt=35)


# ---------- ControllerLock: one driver at a time ----------

def test_lock_allows_only_one_holder():
    lock = ControllerLock()
    assert lock.acquire("a") is True
    assert lock.acquire("b") is False
    assert lock.holder == "a"


def test_lock_release_by_non_holder_is_ignored():
    lock = ControllerLock()
    lock.acquire("a")
    lock.release("b")
    assert lock.holder == "a"
    lock.release("a")
    assert lock.acquire("b") is True


def test_same_holder_can_reacquire():
    lock = ControllerLock()
    lock.acquire("a")
    assert lock.acquire("a") is True
