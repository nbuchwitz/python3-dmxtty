# SPDX-FileCopyrightText: 2026 Nicolai Buchwitz <nb@tipi-net.de>
#
# SPDX-License-Identifier: BSD-3-Clause

"""Tests for the color, fade and fixture helpers."""

from __future__ import annotations

import threading

import pytest

from dmxtty.fx import BLACK, WHITE, Rig, blend, fade, gamma, hsv


def test_blend():
    assert blend(BLACK, WHITE, 0) == BLACK
    assert blend(BLACK, WHITE, 1) == WHITE
    assert blend((0, 100, 200), (100, 100, 0), 0.5) == (50, 100, 100)


def test_gamma():
    assert gamma(0) == 0
    assert gamma(1) == 1
    assert gamma(0.5) < 0.5
    assert gamma(2) == 1
    assert gamma(-1) == 0


def test_hsv():
    assert hsv(0) == (255, 0, 0)
    assert hsv(1 / 3) == (0, 255, 0)
    assert hsv(1.0) == hsv(0.0)
    assert hsv(0, saturation=0) == WHITE
    assert hsv(0, value=0) == BLACK


def test_fade_sends_steps_without_refresh(universe, frames):
    universe.set_channels([100, 0], start=5)
    universe.set_channel(1, 42)
    fade(universe, [200, 50], 0.2, start=5)

    sent = frames()
    assert len(sent) > 3
    firsts = [f[5] for f in sent]
    seconds = [f[6] for f in sent]
    assert firsts == sorted(firsts) and seconds == sorted(seconds)
    assert sent[-1][5:7] == bytes([200, 50])
    assert all(f[1] == 42 for f in sent)


def test_fade_down(universe, frames):
    universe.set_channel(3, 255)
    fade(universe, [0], 0.1, start=3)
    values = [f[3] for f in frames()]
    assert values == sorted(values, reverse=True)
    assert universe.get_channel(3) == 0


def test_fade_zero_duration(universe, frames):
    fade(universe, [9, 8, 7], 0)
    assert frames() == [bytes([0, 9, 8, 7]) + bytes(509)]


def test_fade_with_refresh_does_not_send_itself(universe, monkeypatch):
    universe.start(rate=200)
    callers = []
    monkeypatch.setattr(universe, "send", lambda: callers.append(threading.current_thread()))
    fade(universe, [255], 0.05, start=1)
    universe.stop()
    assert threading.main_thread() not in callers
    assert universe.get_channel(1) == 255


def test_fade_validation(universe, frames):
    with pytest.raises(ValueError):
        fade(universe, [1], -1)
    with pytest.raises(ValueError):
        fade(universe, [256], 1)
    with pytest.raises(IndexError):
        fade(universe, [1, 2], 1, start=512)
    with pytest.raises(IndexError):
        fade(universe, [1], 1, start=0)
    assert frames() == []


def test_rig_without_dimmer_scales_color(universe):
    rig = Rig(universe, [1, 4])
    rig.set(1, (200, 100, 50), 0.5)
    assert universe.data[:6] == bytes([0, 0, 0, 100, 50, 25])


def test_rig_with_dimmer(universe):
    rig = Rig(universe, [1, 6], dimmer=5)
    universe.set_channel(10, 99)
    rig.fill((10, 20, 30), 1.0)
    assert universe.data[:10] == bytes([10, 20, 30, 0, 255, 10, 20, 30, 0, 255])
    assert rig.channels(WHITE, 2.0)[-1] == 255


def test_rig_fade_keeps_channels_between_fixtures(universe):
    rig = Rig(universe, [1, 10], dimmer=4)
    universe.set_channel(6, 77)
    rig.fade((255, 0, 0), 0)
    assert universe.data[:13] == bytes([255, 0, 0, 255, 0, 77, 0, 0, 0, 255, 0, 0, 255])


@pytest.mark.parametrize("kwargs", [{"addresses": []}, {"addresses": [1], "dimmer": 3}])
def test_rig_validation(universe, kwargs):
    with pytest.raises(ValueError):
        Rig(universe, **kwargs)
