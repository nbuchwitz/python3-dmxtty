# SPDX-FileCopyrightText: 2026 Nicolai Buchwitz <nb@tipi-net.de>
#
# SPDX-License-Identifier: BSD-3-Clause

"""Light effects for RGB fixtures.

Fixtures are expected to have red, green and blue on their first three
channels. With --dimmer, the given channel of each fixture controls the
brightness, otherwise the colors are scaled.

    python effects.py /dev/ttyAMA0 1 6 --dimmer 4 --effect fire
"""

from __future__ import annotations

import argparse
import math
import random
import time
from collections.abc import Callable

from dmxtty import DMX
from dmxtty.fx import BLACK, WHITE, Color, Rig, blend, gamma

FPS = 40
FRAME = 1 / FPS

RED: Color = (255, 0, 0)
BLUE: Color = (0, 0, 255)


def breathe(rig: Rig, args: argparse.Namespace) -> None:
    """Pulse slowly like a sleeping laptop."""
    begin = time.monotonic()
    while True:
        phase = (time.monotonic() - begin) / args.period
        rig.fill(args.color, gamma((1 - math.cos(2 * math.pi * phase)) / 2))
        time.sleep(FRAME)


def fire(rig: Rig, args: argparse.Namespace) -> None:
    """Flicker in warm colors like a fireplace."""
    heat = [0.7] * len(rig)
    while True:
        for index in range(len(rig)):
            # smoothed random walk, occasional dips look like gusts
            target = random.uniform(0.3, 1.0) if random.random() < 0.9 else 0.1
            heat[index] += (target - heat[index]) * 0.25
            color = blend((255, 20, 0), (255, 110, 10), heat[index])
            rig.set(index, color, 0.35 + 0.65 * heat[index])
        time.sleep(FRAME * random.choice([1, 2, 3]))


def sunrise(rig: Rig, args: argparse.Namespace) -> None:
    """Rise from night to daylight and set again."""
    stages: list[Color] = [(40, 0, 0), (255, 40, 0), (255, 120, 20), (255, 200, 120), WHITE]
    step = args.period / len(stages)
    while True:
        rig.fill(BLACK, 0.0)
        for color in stages:
            rig.fade(color, step)
        time.sleep(step)
        for color in reversed([BLACK, *stages[:-1]]):
            rig.fade(color, step, level=0.0 if color == BLACK else 1.0)
        time.sleep(step)


def police(rig: Rig, args: argparse.Namespace) -> None:
    """Alternate red and blue double flashes."""
    while True:
        for color, side in ((RED, 0), (BLUE, 1)):
            for _ in range(2):
                for index in range(len(rig)):
                    on = index % 2 == side or len(rig) == 1
                    rig.set(index, color if on else BLACK, 1.0 if on else 0.0)
                time.sleep(0.06)
                rig.fill(BLACK, 0.0)
                time.sleep(0.06)
            time.sleep(0.1)


def lightning(rig: Rig, args: argparse.Namespace) -> None:
    """Thunderstorm with random strikes over a dark sky."""
    sky: Color = (0, 10, 60)
    while True:
        rig.fill(sky, 0.25)
        time.sleep(random.uniform(1.0, 6.0))
        for _ in range(random.randint(1, 3)):
            for index in range(len(rig)):
                rig.set(index, WHITE, random.uniform(0.6, 1.0))
            time.sleep(random.uniform(0.03, 0.08))
            rig.fill(sky, 0.25)
            time.sleep(random.uniform(0.05, 0.15))
        # afterglow
        for i in range(10, 0, -1):
            rig.fill(blend(sky, WHITE, i / 20), 0.25 + 0.05 * i)
            time.sleep(FRAME)


def strobe(rig: Rig, args: argparse.Namespace) -> None:
    """Flash at a fixed rate."""
    while True:
        rig.fill(args.color)
        time.sleep(FRAME)
        rig.fill(BLACK, 0.0)
        time.sleep(max(1 / args.rate - FRAME, FRAME))


def chase(rig: Rig, args: argparse.Namespace) -> None:
    """Run a light with a fading tail back and forth across the fixtures."""
    begin = time.monotonic()
    span = max(len(rig) - 1, 1)
    while True:
        phase = ((time.monotonic() - begin) / args.period) % 1.0
        position = span * (1 - abs(2 * phase - 1))
        for index in range(len(rig)):
            rig.set(index, args.color, gamma(max(0.0, 1 - abs(index - position))))
        time.sleep(FRAME)


def twinkle(rig: Rig, args: argparse.Namespace) -> None:
    """Let random fixtures sparkle in random colors over a warm glow."""
    glow: Color = (255, 80, 10)
    levels = [0.0] * len(rig)
    colors: list[Color] = [WHITE] * len(rig)
    while True:
        for index in range(len(rig)):
            if levels[index] < 0.05 and random.random() < 0.03:
                levels[index] = 1.0
                colors[index] = random.choice([WHITE, (255, 0, 120), (0, 160, 255)])
            levels[index] *= 0.88
            rig.set(index, blend(glow, colors[index], levels[index]), 0.2 + 0.8 * levels[index])
        time.sleep(FRAME)


EFFECTS: dict[str, Callable[[Rig, argparse.Namespace], None]] = {
    "breathe": breathe,
    "fire": fire,
    "sunrise": sunrise,
    "police": police,
    "lightning": lightning,
    "strobe": strobe,
    "chase": chase,
    "twinkle": twinkle,
}


def parse_color(value: str) -> Color:
    """Parse a color given as hex, e.g. ff3300."""
    value = value.removeprefix("#")
    if len(value) != 6:
        raise argparse.ArgumentTypeError(f"expected RRGGBB, got {value!r}")
    try:
        return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected RRGGBB, got {value!r}") from None


def main() -> None:
    """Parse arguments and run the selected effect until interrupted."""
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        epilog="\n".join(f"{name:10} {fn.__doc__}" for name, fn in EFFECTS.items()),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("port", help="serial interface, e.g. /dev/ttyAMA0")
    parser.add_argument("addresses", type=int, nargs="+", help="fixture start addresses")
    parser.add_argument("--effect", choices=EFFECTS, default="fire")
    parser.add_argument("--dimmer", type=int, help="dimmer channel within a fixture (1-based)")
    parser.add_argument(
        "--color", type=parse_color, default=(0, 80, 255), help="RRGGBB for breathe, strobe, chase"
    )
    parser.add_argument(
        "--period", type=float, default=4.0, help="seconds per cycle for breathe, sunrise, chase"
    )
    parser.add_argument("--rate", type=float, default=10.0, help="flashes per second for strobe")
    args = parser.parse_args()

    with DMX(args.port) as dmx:
        dmx.start(rate=FPS)
        rig = Rig(dmx, args.addresses, args.dimmer)
        try:
            EFFECTS[args.effect](rig, args)
        except KeyboardInterrupt:
            pass

        dmx.clear()
        dmx.send()


if __name__ == "__main__":
    main()
