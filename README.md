# dmxtty

[![Tests](https://github.com/nbuchwitz/python3-dmxtty/actions/workflows/pytest.yml/badge.svg)](https://github.com/nbuchwitz/python3-dmxtty/actions/workflows/pytest.yml)
[![Linting](https://github.com/nbuchwitz/python3-dmxtty/actions/workflows/lint.yml/badge.svg)](https://github.com/nbuchwitz/python3-dmxtty/actions/workflows/lint.yml)
[![Documentation Status](https://readthedocs.org/projects/dmxtty/badge/?version=latest)](https://dmxtty.readthedocs.io/en/latest/?badge=latest)

A Python library that sends DMX512 through Linux serial interfaces with an
RS485 transceiver.

All it needs is a UART and an RS485 transceiver, which makes it easy to turn
embedded Linux boards like the Raspberry Pi into a DMX controller. The
Raspberry Pi 4 and 5 provide several UARTs, so a single board can serve
multiple universes.

## Features

- Works with any Linux tty driving an RS485 transceiver
- 1-based channel addressing, matching fixture start addresses
- Background refresh at a configurable rate
- Configurable start code and universe size (24 to 512 channels)
- Restores the interface's RS485 configuration on close
- One universe per UART, multiple universes on boards with several UARTs

Support for the PIO of the Raspberry Pi is planned for the future.

## Installation

```bash
pip install dmxtty
```

### Dependencies

- Python 3.11+
- pyserial

## Documentation

Documentation is available at [dmxtty.readthedocs.io](https://dmxtty.readthedocs.io/).

## Quick Start

```python
from dmxtty import DMX

with DMX("/dev/ttyAMA0") as dmx:
    dmx.start()                              # repeat packets in the background
    dmx.set_channels([255, 51, 0], start=1)  # RGB fixture at address 1
    dmx.set_channel(4, 255)                  # its dimmer
```

Without the background refresh, packets are sent explicitly:

```python
dmx.send()                        # current channel values
dmx.send_frame([255, 0, 0, 255])  # replace all channels, rest set to 0
```

The interface's RS485 mode is disabled while it is in use, because the DMX
break cannot be generated while RS485 mode is enabled. The initial
configuration is restored on close. Patches that lift this limitation have
been submitted to the Linux kernel, so newer releases will hopefully no longer
need this workaround.

## Examples

- [`examples/rainbow.py`](examples/rainbow.py): rainbow across RGB fixtures, each shifted in hue
- [`examples/fade.py`](examples/fade.py): fade fixtures in and out with random colors

```bash
python examples/rainbow.py /dev/ttyAMA0 1 6 11 16 --dimmer 4
```

## License

BSD-3-Clause
