# SPDX-FileCopyrightText: 2026 Nicolai Buchwitz <nb@tipi-net.de>
#
# SPDX-License-Identifier: BSD-3-Clause

"""Fake serial port and RS485 ioctls shared by the tests."""

from __future__ import annotations

import errno

import pytest

import dmxtty.interface
from dmxtty import DMX
from dmxtty._rs485 import (
    SER_RS485_ENABLED,
    SER_RS485_RTS_ON_SEND,
    SER_RS485_TERMINATE_BUS,
    SERIAL_RS485_SIZE,
    get_rs485_flags,
    set_rs485_flags,
)


class FakeSerial:
    instances: list[FakeSerial] = []

    def __init__(self, port, baudrate, **kwargs):
        self.port = port
        self.baudrate = baudrate
        self.kwargs = kwargs
        self.is_open = True
        self.events = []
        self.frames = []
        FakeSerial.instances.append(self)

    def flush(self):
        self.events.append("flush")

    def reset_input_buffer(self):
        self.events.append("reset_input")

    @property
    def break_condition(self):
        raise AttributeError

    @break_condition.setter
    def break_condition(self, value):
        self.events.append(f"break={value}")

    def write(self, data):
        self.events.append("write")
        self.frames.append(bytes(data))
        return len(data)

    def close(self):
        self.is_open = False


class FakeRS485:
    """Mimics the serial core handling of struct serial_rs485."""

    def __init__(self, flags, *, supported=True, termination=True):
        self.config = bytearray(SERIAL_RS485_SIZE)
        set_rs485_flags(self.config, flags)
        self.supported = supported
        self.has_termination = termination
        # GPIO state, set from the flags at boot
        self.terminated = termination and bool(flags & SER_RS485_TERMINATE_BUS)
        self.history = []
        self.open_fds = 0
        self.locked_by_other = False

    def get(self, fd):
        return bytearray(self.config)

    def set(self, fd, config):
        if not self.supported:
            raise OSError(errno.ENOTTY, "Inappropriate ioctl for device")

        config = bytearray(config)
        flags = get_rs485_flags(config)
        if not flags & SER_RS485_ENABLED:
            # uart_sanitize_serial_rs485() clears everything, the
            # termination GPIO keeps its state
            config = bytearray(SERIAL_RS485_SIZE)
        else:
            if not self.has_termination:
                flags &= ~SER_RS485_TERMINATE_BUS
                set_rs485_flags(config, flags)
            if self.has_termination:
                self.terminated = bool(flags & SER_RS485_TERMINATE_BUS)

        self.config = config
        self.history.append(get_rs485_flags(config))

    def os_open(self, path, flags):
        self.open_fds += 1
        return 42

    def os_close(self, fd):
        self.open_fds -= 1

    def flock(self, fd, operation):
        if self.locked_by_other:
            raise BlockingIOError(errno.EAGAIN, "Resource temporarily unavailable")


@pytest.fixture
def rs485(monkeypatch):
    fake = FakeRS485(SER_RS485_ENABLED | SER_RS485_RTS_ON_SEND)
    monkeypatch.setattr(dmxtty.interface, "get_rs485_config", fake.get)
    monkeypatch.setattr(dmxtty.interface, "set_rs485_config", fake.set)
    monkeypatch.setattr(dmxtty.interface.os, "open", fake.os_open)
    monkeypatch.setattr(dmxtty.interface.os, "close", fake.os_close)
    monkeypatch.setattr(dmxtty.interface.fcntl, "flock", fake.flock)
    monkeypatch.setattr(dmxtty.interface.serial, "Serial", FakeSerial)
    FakeSerial.instances.clear()
    return fake


@pytest.fixture
def universe(rs485):
    with DMX("/dev/ttyAMA0") as d:
        yield d


@pytest.fixture
def frames():
    return lambda: FakeSerial.instances[-1].frames
