# SPDX-FileCopyrightText: 2026 Nicolai Buchwitz <nb@tipi-net.de>
#
# SPDX-License-Identifier: BSD-3-Clause

"""Helpers for colors, fades and groups of RGB fixtures.

Everything here builds on the public :class:`~dmxtty.DMX` API.
"""

from __future__ import annotations

import colorsys
import time
from collections.abc import Iterable, Sequence

from .interface import DMX

Color = tuple[int, int, int]
"""Red, green and blue, each 0..255."""

BLACK: Color = (0, 0, 0)
WHITE: Color = (255, 255, 255)


def blend(a: Color, b: Color, t: float) -> Color:
    """Mix two colors linearly.

    Parameters
    ----------
    a : Color
        Color at ``t = 0``
    b : Color
        Color at ``t = 1``
    t : float
        Mix ratio, 0.0 to 1.0

    Returns
    -------
    Color
        Mixed color
    """
    return (
        round(a[0] + (b[0] - a[0]) * t),
        round(a[1] + (b[1] - a[1]) * t),
        round(a[2] + (b[2] - a[2]) * t),
    )


def gamma(level: float, exponent: float = 2.2) -> float:
    """Map a linear brightness to a perceptually even one.

    Dimmers respond linearly, but the eye does not. Without correction,
    fades appear to rush through the dark end.

    Parameters
    ----------
    level : float
        Linear brightness, 0.0 to 1.0
    exponent : float, optional
        Gamma exponent

    Returns
    -------
    float
        Corrected brightness, 0.0 to 1.0
    """
    return min(max(level, 0.0), 1.0) ** exponent


def hsv(hue: float, saturation: float = 1.0, value: float = 1.0) -> Color:
    """Convert a hue, saturation, value triple to a color.

    Parameters
    ----------
    hue : float
        Position on the color wheel, 0.0 to 1.0 (wraps around)
    saturation : float, optional
        0.0 gives white, 1.0 the pure hue
    value : float, optional
        Brightness, 0.0 to 1.0

    Returns
    -------
    Color
        Converted color
    """
    r, g, b = colorsys.hsv_to_rgb(hue % 1.0, saturation, value)
    return (round(r * 255), round(g * 255), round(b * 255))


def fade(dmx: DMX, values: Iterable[int] | bytes, duration: float, start: int = 1) -> None:
    """Fade consecutive channels linearly from their current values.

    Blocks until the fade is complete. Each step is picked up by the
    background refresh if it is running, otherwise every step is sent as a
    packet. Channels outside the range are left unchanged.

    Parameters
    ----------
    dmx : DMX
        Universe to fade in
    values : Iterable[int] | bytes
        Target channel values (0..255)
    duration : float
        Fade time in seconds, 0 sets the values immediately
    start : int, optional
        Address of the channel receiving the first value

    Raises
    ------
    IndexError
        If ``values`` do not fit into the universe starting at ``start``
    ValueError
        If a value is out of range or ``duration`` is negative
    serial.SerialException
        If the refresh is not running and a transmission fails
    """
    target = bytes(values)
    if duration < 0:
        raise ValueError(f"duration must not be negative, got {duration}")
    end = start + len(target) - 1
    if start < 1 or end > dmx.channels:
        raise IndexError(
            f"{len(target)} values starting at channel {start} exceed {dmx.channels} channels"
        )
    origin = dmx.data[start - 1 : end]

    period = 1 / (dmx.refresh_rate or DMX.DEFAULT_REFRESH_RATE)
    begin = time.monotonic()
    while True:
        progress = min((time.monotonic() - begin) / duration, 1.0) if duration else 1.0
        step = bytes(round(a + (b - a) * progress) for a, b in zip(origin, target, strict=True))
        dmx.set_channels(step, start)

        if not dmx.is_running:
            dmx.send()
        if progress >= 1.0:
            return

        # pace steps from the start, so slow sends don't stretch the fade
        elapsed = time.monotonic() - begin
        time.sleep(max(0.0, period - elapsed % period))


class Rig:
    """A group of RGB fixtures in one universe.

    Fixtures are expected to have red, green and blue on their first three
    channels. With a dimmer channel, brightness is set there, otherwise the
    colors are scaled.

    Parameters
    ----------
    dmx : DMX
        Universe the fixtures are patched in
    addresses : Sequence[int]
        Start address of each fixture
    dimmer : int | None, optional
        Dimmer channel within a fixture (1-based, 4 or higher), None if the
        fixtures have none

    Raises
    ------
    ValueError
        If ``addresses`` is empty or ``dimmer`` overlaps the color channels
    """

    def __init__(self, dmx: DMX, addresses: Sequence[int], dimmer: int | None = None) -> None:
        if not addresses:
            raise ValueError("at least one fixture address is required")
        if dimmer is not None and dimmer < 4:
            raise ValueError(f"dimmer must follow red, green and blue (4 or higher), got {dimmer}")

        self.dmx = dmx
        self.addresses = list(addresses)
        self.dimmer = dimmer

    def __len__(self) -> int:
        return len(self.addresses)

    def channels(self, color: Color, level: float = 1.0) -> list[int]:
        """Return the channel values of one fixture, starting at its address.

        Channels between blue and the dimmer are set to 0.

        Parameters
        ----------
        color : Color
            Fixture color
        level : float, optional
            Brightness, 0.0 to 1.0

        Returns
        -------
        list[int]
            Values for the fixture's channels up to its dimmer
        """
        level = min(max(level, 0.0), 1.0)
        if self.dimmer is None:
            return [round(c * level) for c in color]

        values = [*color, *([0] * (self.dimmer - 3))]
        values[self.dimmer - 1] = round(255 * level)
        return values

    def set(self, index: int, color: Color, level: float = 1.0) -> None:
        """Set color and brightness of one fixture.

        Parameters
        ----------
        index : int
            Fixture index
        color : Color
            Fixture color
        level : float, optional
            Brightness, 0.0 to 1.0
        """
        self.dmx.set_channels(self.channels(color, level), self.addresses[index])

    def fill(self, color: Color, level: float = 1.0) -> None:
        """Set all fixtures to the same color and brightness.

        Parameters
        ----------
        color : Color
            Fixture color
        level : float, optional
            Brightness, 0.0 to 1.0
        """
        for index in range(len(self)):
            self.set(index, color, level)

    def fade(self, color: Color, duration: float, level: float = 1.0) -> None:
        """Crossfade all fixtures to one color, blocking until done.

        Parameters
        ----------
        color : Color
            Target color
        duration : float
            Fade time in seconds
        level : float, optional
            Target brightness, 0.0 to 1.0
        """
        fixture = self.channels(color, level)
        first = min(self.addresses)
        last = max(self.addresses) + len(fixture) - 1

        target = bytearray(self.dmx.data[first - 1 : last])
        for address in self.addresses:
            offset = address - first
            target[offset : offset + len(fixture)] = bytes(fixture)
        fade(self.dmx, target, duration, start=first)
