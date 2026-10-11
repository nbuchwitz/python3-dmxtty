# SPDX-FileCopyrightText: 2026 Nicolai Buchwitz <nb@tipi-net.de>
#
# SPDX-License-Identifier: BSD-3-Clause

"""Tests for the DMX transmitter."""

from __future__ import annotations

import time

import pytest
import serial

import dmxtty.interface
from conftest import FakeSerial
from dmxtty import DMX
from dmxtty._rs485 import SER_RS485_ENABLED, SER_RS485_RTS_ON_SEND, set_rs485_flags


def last_frame():
    return FakeSerial.instances[-1].frames[-1]


def test_open_configures_port(universe):
    port = FakeSerial.instances[-1]
    assert port.port == "/dev/ttyAMA0"
    assert port.baudrate == 250000
    assert port.kwargs["stopbits"] == serial.STOPBITS_TWO
    assert port.kwargs["exclusive"] is True
    assert universe.is_open
    assert universe.channels == 512


def test_rs485_mode_disabled_while_open_and_restored(rs485):
    initial = bytes(rs485.config)
    d = DMX("/dev/ttyAMA0")
    assert rs485.history == [SER_RS485_RTS_ON_SEND]
    d.close()
    assert bytes(rs485.config) == initial
    assert rs485.open_fds == 0
    assert not d.is_open

    # second close is a no-op
    d.close()
    assert len(rs485.history) == 2


def test_rs485_untouched_when_disabled(rs485):
    set_rs485_flags(rs485.config, 0)
    DMX("/dev/ttyAMA0").close()
    assert rs485.history == []


def test_port_in_use_is_left_alone(rs485):
    rs485.locked_by_other = True
    initial = bytes(rs485.config)
    with pytest.raises(serial.SerialException, match="in use"):
        DMX("/dev/ttyAMA0")
    assert rs485.history == []
    assert bytes(rs485.config) == initial
    assert rs485.open_fds == 0


def test_rs485_restored_when_open_fails(rs485, monkeypatch):
    def fail(*args, **kwargs):
        raise serial.SerialException("busy")

    monkeypatch.setattr(dmxtty.interface.serial, "Serial", fail)
    with pytest.raises(serial.SerialException):
        DMX("/dev/ttyAMA0")
    assert rs485.history[-1] & SER_RS485_ENABLED


@pytest.mark.parametrize("kwargs", [{"start_code": 256}, {"channels": 23}, {"channels": 513}])
def test_invalid_arguments(rs485, kwargs):
    with pytest.raises(ValueError):
        DMX("/dev/ttyAMA0", **kwargs)
    assert rs485.history == []


def test_send_sequence(universe):
    universe.send()
    port = FakeSerial.instances[-1]
    assert port.events == ["flush", "reset_input", "break=True", "break=False", "write"]
    assert last_frame() == bytes(513)


def test_send_frame_zeroes_remaining(universe):
    universe.set_channel(10, 99)
    universe.send_frame([1, 2, 3])
    assert last_frame()[:5] == b"\x00\x01\x02\x03\x00"
    assert last_frame()[10] == 0
    assert universe.data[:3] == b"\x01\x02\x03"


def test_send_frame_rejects_too_many(universe):
    with pytest.raises(ValueError):
        universe.send_frame(bytes(513))


def test_send_frame_rejects_out_of_range(universe):
    with pytest.raises(ValueError):
        universe.send_frame([256])


def test_set_channels_keeps_others(universe):
    universe.set_channel(1, 7)
    universe.set_channels([4, 5, 6], start=10)
    universe.send()
    assert last_frame()[1] == 7
    assert last_frame()[10:13] == b"\x04\x05\x06"
    assert universe.get_channel(11) == 5


def test_set_channels_fills_last_channel(universe):
    universe.set_channels([1, 2], start=511)
    assert universe.data[-2:] == b"\x01\x02"
    with pytest.raises(IndexError):
        universe.set_channels([1, 2, 3], start=511)


@pytest.mark.parametrize("address", [0, 513])
def test_address_out_of_range(universe, address):
    with pytest.raises(IndexError):
        universe.set_channel(address, 1)
    with pytest.raises(IndexError):
        universe.get_channel(address)


def test_value_out_of_range(universe):
    with pytest.raises(ValueError):
        universe.set_channel(1, 256)
    with pytest.raises(ValueError):
        universe.set_channel(1, -1)


def test_clear(universe):
    universe.set_channels([255] * 512)
    universe.clear()
    assert universe.data == bytes(512)


def test_start_code(rs485):
    with DMX("/dev/ttyAMA0", start_code=0xCC, channels=24) as d:
        d.send()
        assert last_frame() == b"\xcc" + bytes(24)
        d.start_code = 0x17
        d.send()
        assert last_frame()[0] == 0x17
        with pytest.raises(ValueError):
            d.start_code = 0x100


def test_send_after_close(rs485):
    d = DMX("/dev/ttyAMA0")
    d.close()
    with pytest.raises(serial.SerialException):
        d.send()


def test_refresh(universe):
    universe.set_channel(1, 1)
    universe.start(rate=1000)
    assert universe.is_running
    with pytest.raises(RuntimeError):
        universe.start()

    port = FakeSerial.instances[-1]
    deadline = time.monotonic() + 2
    while len(port.frames) < 3 and time.monotonic() < deadline:
        time.sleep(0.001)
    universe.set_channel(1, 2)
    count = len(port.frames)
    while len(port.frames) == count and time.monotonic() < deadline:
        time.sleep(0.001)

    assert universe.refresh_rate == 1000
    universe.stop()
    assert not universe.is_running
    assert universe.refresh_rate is None
    assert port.frames[0][1] == 1
    assert port.frames[-1][1] == 2


def test_refresh_error_raised_on_stop(universe, monkeypatch):
    port = FakeSerial.instances[-1]

    def fail(data):
        raise serial.SerialException("gone")

    monkeypatch.setattr(port, "write", fail)
    universe.start()
    universe._refresh_thread.join(timeout=2)
    assert not universe.is_running
    with pytest.raises(serial.SerialException, match="gone"):
        universe.stop()
    universe.stop()


def test_close_stops_refresh(rs485):
    d = DMX("/dev/ttyAMA0")
    d.start()
    d.close()
    assert not d.is_running
    assert not d.is_open


def test_start_requires_open_and_positive_rate(rs485):
    d = DMX("/dev/ttyAMA0")
    with pytest.raises(ValueError):
        d.start(rate=0)
    d.close()
    with pytest.raises(RuntimeError):
        d.start()


def test_rs485_unmanaged_leaves_config_alone(rs485, frames):
    initial = bytes(rs485.config)
    with DMX("/dev/ttyAMA0", manage_rs485=False) as d:
        d.send()
    assert rs485.history == []
    assert rs485.open_fds == 0
    assert bytes(rs485.config) == initial
    assert len(frames()) == 1


def test_rs485_unmanaged_without_rs485_support(rs485, monkeypatch):
    def unsupported(fd):
        raise OSError(25, "Inappropriate ioctl for device")

    monkeypatch.setattr(dmxtty.interface, "get_rs485_config", unsupported)
    with pytest.raises(OSError):
        DMX("/dev/ttyAMA0")
    DMX("/dev/ttyAMA0", manage_rs485=False).close()
