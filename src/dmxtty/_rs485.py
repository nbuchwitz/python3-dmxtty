# SPDX-FileCopyrightText: 2026 Nicolai Buchwitz <nb@tipi-net.de>
#
# SPDX-License-Identifier: BSD-3-Clause

"""Access to the Linux ``struct serial_rs485`` of a serial interface."""

import fcntl
import struct

# from linux/serial.h
SER_RS485_ENABLED = 1 << 0
SER_RS485_RTS_ON_SEND = 1 << 1
SER_RS485_RTS_AFTER_SEND = 1 << 2
SER_RS485_RX_DURING_TX = 1 << 3
SER_RS485_TERMINATE_BUS = 1 << 4

# from include/uapi/asm-generic/ioctls.h (differs on alpha, mips, ppc, sparc)
TIOCGRS485 = 0x542E
TIOCSRS485 = 0x542F

# struct serial_rs485: flags, delay_rts_before_send, delay_rts_after_send,
# followed by a 20 byte addr/padding union
SERIAL_RS485_SIZE = 32


def get_rs485_config(fd: int) -> bytearray:
    """Get ``struct serial_rs485`` from an open serial interface.

    Parameters
    ----------
    fd : int
        File descriptor of the serial interface

    Returns
    -------
    bytearray
        Raw ``struct serial_rs485``
    """
    rs485conf = bytearray(SERIAL_RS485_SIZE)
    fcntl.ioctl(fd, TIOCGRS485, rs485conf)

    return rs485conf


def set_rs485_config(fd: int, rs485conf: bytes | bytearray) -> None:
    """Set ``struct serial_rs485`` for an open serial interface.

    Parameters
    ----------
    fd : int
        File descriptor of the serial interface
    rs485conf : bytes | bytearray
        Raw ``struct serial_rs485``

    Raises
    ------
    ValueError
        If ``rs485conf`` does not have the size of ``struct serial_rs485``
    """
    if len(rs485conf) != SERIAL_RS485_SIZE:
        raise ValueError(f"struct serial_rs485 must be {SERIAL_RS485_SIZE} bytes")

    fcntl.ioctl(fd, TIOCSRS485, bytes(rs485conf))


def get_rs485_flags(rs485conf: bytes | bytearray) -> int:
    """Return the ``flags`` field of a raw ``struct serial_rs485``.

    Parameters
    ----------
    rs485conf : bytes | bytearray
        Raw ``struct serial_rs485``

    Returns
    -------
    int
        Combination of ``SER_RS485_*`` flags
    """
    return struct.unpack_from("=I", rs485conf)[0]


def set_rs485_flags(rs485conf: bytearray, flags: int) -> None:
    """Replace the ``flags`` field of a raw ``struct serial_rs485`` in place.

    Parameters
    ----------
    rs485conf : bytearray
        Raw ``struct serial_rs485``
    flags : int
        Combination of ``SER_RS485_*`` flags
    """
    struct.pack_into("=I", rs485conf, 0, flags)
