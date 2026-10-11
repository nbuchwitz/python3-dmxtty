# SPDX-FileCopyrightText: 2026 Nicolai Buchwitz <nb@tipi-net.de>
#
# SPDX-License-Identifier: BSD-3-Clause

"""Run a rainbow across RGB fixtures, each one shifted in hue.

Example for four fixtures with red, green, blue on their first channels and
a dimmer on the fourth, patched at addresses 1, 6, 11 and 16:

    python rainbow.py /dev/ttyAMA0 1 6 11 16 --dimmer 4
"""

import argparse
import colorsys
import time

from dmxtty import DMX

FPS = 40


def main() -> None:
    """Parse arguments and run the rainbow until interrupted."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("port", help="serial interface, e.g. /dev/ttyAMA0")
    parser.add_argument("addresses", type=int, nargs="+", help="fixture start addresses")
    parser.add_argument("--period", type=float, default=10.0, help="seconds per full rainbow cycle")
    parser.add_argument(
        "--dimmer", type=int, help="dimmer channel within a fixture (1-based), set to full"
    )
    parser.add_argument(
        "--brightness", type=float, default=1.0, help="color brightness, 0.0 to 1.0"
    )
    args = parser.parse_args()

    with DMX(args.port) as dmx:
        if args.dimmer is not None:
            for address in args.addresses:
                dmx.set_channel(address + args.dimmer - 1, 255)

        dmx.start(rate=FPS)

        start = time.monotonic()
        try:
            while True:
                phase = (time.monotonic() - start) / args.period
                for index, address in enumerate(args.addresses):
                    # spread the fixtures evenly over the color wheel
                    hue = (phase + index / len(args.addresses)) % 1.0
                    rgb = colorsys.hsv_to_rgb(hue, 1.0, args.brightness)
                    dmx.set_channels([round(c * 255) for c in rgb], start=address)
                time.sleep(1 / FPS)
        except KeyboardInterrupt:
            pass

        # blackout before the receivers time out on their last state
        dmx.clear()
        dmx.send()


if __name__ == "__main__":
    main()
