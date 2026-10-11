# SPDX-FileCopyrightText: 2026 Nicolai Buchwitz <nb@tipi-net.de>
#
# SPDX-License-Identifier: BSD-3-Clause

"""Fade two RGB fixtures with dimmer channel in and out, changing colors in the dark."""

import random
import sys
import time

from dmxtty import DMX

COLORS = [
    (0xFF, 0x00, 0x00),
    (0x00, 0xFF, 0x00),
    (0x00, 0x00, 0xFF),
    (0xFF, 0x33, 0x00),
    (0x80, 0x00, 0x80),
    (0xFF, 0xFF, 0xFF),
]

# start addresses of fixtures with channels red, green, blue, dimmer, strobe
FIXTURES = [1, 6]

port = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyAMA0"

with DMX(port) as dmx:
    dmx.start()
    try:
        while True:
            for address in FIXTURES:
                dmx.set_channels(random.choice(COLORS), address)
            for level in [*range(0, 256, 5), *range(255, -1, -5)]:
                for address in FIXTURES:
                    dmx.set_channel(address + 3, level)
                time.sleep(0.02)
    except KeyboardInterrupt:
        pass
