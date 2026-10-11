# SPDX-FileCopyrightText: 2026 Nicolai Buchwitz <nb@tipi-net.de>
#
# SPDX-License-Identifier: BSD-3-Clause

"""DMX512 transmitter on a Linux RS485 serial interface."""

from __future__ import annotations

import errno
import fcntl
import os
import threading
import time
from collections.abc import Iterable
from types import TracebackType

import serial

from ._rs485 import (
    SER_RS485_ENABLED,
    get_rs485_config,
    get_rs485_flags,
    set_rs485_config,
    set_rs485_flags,
)


class DMX:
    """DMX512 universe sent through an RS485 serial interface.

    The universe keeps the value of every channel. Values are changed with
    :meth:`set_channel` or :meth:`set_channels` and transmitted with
    :meth:`send`. DMX receivers expect packets to be repeated continuously,
    :meth:`start` does that from a background thread.

    Channel addresses are 1-based, as on DMX fixtures.

    Parameters
    ----------
    port : str
        Serial device, e.g. ``/dev/ttyAMA0``
    start_code : int, optional
        Start code sent ahead of the channel slots, ``0x00`` for dimmer data
    channels : int, optional
        Number of channel slots per packet, between :attr:`MIN_CHANNELS` and
        :attr:`MAX_CHANNELS`. Shorter packets allow a higher refresh rate.
    manage_rs485 : bool, optional
        Disable the kernel RS485 mode of ``port`` while it is open and restore
        it on close. Pass False if the transceiver is always enabled, e.g.
        with DE tied high, or if the driver has no RS485 support (USB
        adapters). RS485 mode must then already be off, otherwise no break
        is sent.

    Raises
    ------
    ValueError
        If ``start_code`` or ``channels`` are out of range
    OSError
        If ``manage_rs485`` is set and the RS485 configuration of ``port``
        cannot be read or changed
    serial.SerialException
        If ``port`` cannot be opened or is in use by another process
    """

    BAUDRATE = 250000
    # DMX512-A minimums. time.sleep() overshoots by tens of microseconds,
    # which is fine as both may last up to 1s. Don't use send_break(), its
    # tcsendbreak() ignores the duration on Linux and breaks for ~250ms.
    TIME_BREAK = 176 / 1000000
    TIME_MAB = 8 / 1000000

    START_CODE = 0x00
    MAX_CHANNELS = 512
    # keeps the packet above the 1204us minimum break-to-break time
    MIN_CHANNELS = 24
    # a full 512 slot packet takes ~22.7ms, which limits the rate to ~44Hz
    DEFAULT_REFRESH_RATE = 40.0

    def __init__(
        self,
        port: str,
        *,
        start_code: int = START_CODE,
        channels: int = MAX_CHANNELS,
        manage_rs485: bool = True,
    ) -> None:
        _check_value(start_code, "start code")
        if not self.MIN_CHANNELS <= channels <= self.MAX_CHANNELS:
            raise ValueError(
                f"channels must be between {self.MIN_CHANNELS} and "
                f"{self.MAX_CHANNELS}, got {channels}"
            )

        self._port = port
        self._initial_rs485_config: bytearray | None = None
        self._serial: serial.Serial | None = None

        # start code followed by all channel slots
        self._frame = bytearray(1 + channels)
        self._frame[0] = start_code
        # guards _frame, held only for short copies
        self._frame_lock = threading.Lock()
        # serializes transmissions of send() and the refresh thread
        self._tx_lock = threading.Lock()

        self._refresh_thread: threading.Thread | None = None
        self._refresh_rate = 0.0
        self._refresh_stop = threading.Event()
        self._refresh_error: BaseException | None = None

        # quirk: With RS485 mode enabled, the BREAK signal cannot be handled.
        # Disable it while the interface is in use and restore it on close.
        # This has to happen while the port is closed. PL011 leaves the
        # transmitter disabled when RS485 is turned off on an open port.
        # pyserial then asserts RTS on open, which enables the transceiver.
        if manage_rs485:
            self._disable_rs485_mode()

        try:
            self._serial = serial.Serial(
                port,
                self.BAUDRATE,
                stopbits=serial.STOPBITS_TWO,
                bytesize=serial.EIGHTBITS,
                exclusive=True,
            )
        except BaseException:
            self._restore_rs485_mode()
            raise

    def __repr__(self) -> str:
        state = "open" if self.is_open else "closed"
        return f"<{type(self).__name__} port={self._port!r} channels={self.channels} {state}>"

    @property
    def port(self) -> str:
        """Serial device the universe is sent on."""
        return self._port

    @property
    def channels(self) -> int:
        """Number of channel slots per packet."""
        return len(self._frame) - 1

    @property
    def start_code(self) -> int:
        """Start code sent ahead of the channel slots."""
        return self._frame[0]

    @start_code.setter
    def start_code(self, value: int) -> None:
        _check_value(value, "start code")
        with self._frame_lock:
            self._frame[0] = value

    @property
    def data(self) -> bytes:
        """Snapshot of all channel values, channel 1 first."""
        with self._frame_lock:
            return bytes(self._frame[1:])

    @property
    def is_open(self) -> bool:
        """Whether the serial interface is open."""
        return self._serial is not None and self._serial.is_open

    @property
    def refresh_rate(self) -> float | None:
        """Packets per second of the background refresh, None if it is not running."""
        return self._refresh_rate if self.is_running else None

    @property
    def is_running(self) -> bool:
        """Whether the background refresh started by :meth:`start` is active."""
        return self._refresh_thread is not None and self._refresh_thread.is_alive()

    def get_channel(self, address: int) -> int:
        """Return the value of one channel.

        Parameters
        ----------
        address : int
            Channel address, starting at 1

        Returns
        -------
        int
            Channel value (0..255)

        Raises
        ------
        IndexError
            If ``address`` is outside the universe
        """
        self._check_address(address)
        return self._frame[address]

    def set_channel(self, address: int, value: int) -> None:
        """Set the value of one channel.

        The value is transmitted with the next packet.

        Parameters
        ----------
        address : int
            Channel address, starting at 1
        value : int
            Channel value (0..255)

        Raises
        ------
        IndexError
            If ``address`` is outside the universe
        ValueError
            If ``value`` is out of range
        """
        self._check_address(address)
        _check_value(value, "channel value")
        with self._frame_lock:
            self._frame[address] = value

    def set_channels(self, values: Iterable[int] | bytes, start: int = 1) -> None:
        """Set consecutive channels, leaving all others unchanged.

        Typically used to update a fixture occupying several channels.

        Parameters
        ----------
        values : Iterable[int] | bytes
            Channel values (0..255)
        start : int, optional
            Address of the channel receiving the first value

        Raises
        ------
        IndexError
            If ``values`` do not fit into the universe starting at ``start``
        ValueError
            If a value is out of range
        """
        data = bytes(values)
        self._check_span(start, len(data))

        with self._frame_lock:
            self._frame[start : start + len(data)] = data

    def clear(self) -> None:
        """Set all channels to 0."""
        with self._frame_lock:
            self._frame[1:] = bytes(self.channels)

    def send(self) -> None:
        """Transmit the current channel values as one packet.

        Blocks until the previous packet has left the interface.

        Raises
        ------
        serial.SerialException
            If the interface is closed or the transmission fails
        """
        with self._frame_lock:
            frame = bytes(self._frame)

        self._transmit(frame)

    def send_frame(self, data: Iterable[int] | bytes) -> None:
        """Replace all channel values and transmit them as one packet.

        Channels not covered by ``data`` are set to 0.

        Parameters
        ----------
        data : Iterable[int] | bytes
            Channel values (0..255) starting at channel 1, at most
            :attr:`channels`

        Raises
        ------
        ValueError
            If ``data`` has too many or out of range values
        serial.SerialException
            If the interface is closed or the transmission fails
        """
        data = bytes(data)
        if len(data) > self.channels:
            raise ValueError(f"at most {self.channels} channels, got {len(data)}")

        with self._frame_lock:
            self._frame[1 : 1 + len(data)] = data
            self._frame[1 + len(data) :] = bytes(self.channels - len(data))
            frame = bytes(self._frame)

        self._transmit(frame)

    def start(self, rate: float = DEFAULT_REFRESH_RATE) -> None:
        """Repeat the current channel values from a background thread.

        Channel changes are picked up with the next packet. If the requested
        rate exceeds what the packet length allows, packets are sent back to
        back.

        Parameters
        ----------
        rate : float, optional
            Packets per second

        Raises
        ------
        ValueError
            If ``rate`` is not positive
        RuntimeError
            If the refresh is already running or the interface is closed
        """
        if rate <= 0:
            raise ValueError(f"rate must be positive, got {rate}")
        if self.is_running:
            raise RuntimeError("refresh is already running")
        if not self.is_open:
            raise RuntimeError("interface is closed")

        self._refresh_stop.clear()
        self._refresh_error = None
        self._refresh_rate = rate
        self._refresh_thread = threading.Thread(
            target=self._refresh, args=(1 / rate,), name=f"dmx-{self._port}", daemon=True
        )
        self._refresh_thread.start()

    def stop(self) -> None:
        """Stop the background refresh started by :meth:`start`.

        Does nothing if the refresh is not running.

        Raises
        ------
        Exception
            The error that terminated the refresh thread, if any
        """
        error = self._stop_refresh()
        if error is not None:
            raise error

    def close(self) -> None:
        """Stop the refresh, close the interface and restore its RS485 mode.

        Safe to call more than once.
        """
        self._stop_refresh()

        if self._serial is not None and self._serial.is_open:
            self._serial.close()

        self._restore_rs485_mode()

    def __enter__(self) -> DMX:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def __del__(self) -> None:
        # __init__ may have failed before all attributes were set
        if hasattr(self, "_refresh_stop"):
            self.close()

    def _check_span(self, start: int, count: int) -> None:
        self._check_address(start)
        if start + count - 1 > self.channels:
            raise IndexError(
                f"{count} values starting at channel {start} exceed {self.channels} channels"
            )

    def _check_address(self, address: int) -> None:
        if not 1 <= address <= self.channels:
            raise IndexError(
                f"channel address must be between 1 and {self.channels}, got {address}"
            )

    def _transmit(self, frame: bytes) -> None:
        if self._serial is None or not self._serial.is_open:
            raise serial.SerialException("interface is closed")

        with self._tx_lock:
            # TIOCSBRK does not wait for pending output, so a break issued
            # while the previous packet is still in flight would truncate it
            self._serial.flush()

            # With RS485 mode disabled the receiver stays on and gets our own
            # frames echoed back. Nobody reads them, so drop them before the
            # tty buffer runs full.
            self._serial.reset_input_buffer()

            # break
            self._serial.break_condition = True
            time.sleep(self.TIME_BREAK)
            self._serial.break_condition = False

            # mab
            time.sleep(self.TIME_MAB)

            self._serial.write(frame)

    def _refresh(self, period: float) -> None:
        deadline = time.monotonic()
        try:
            while not self._refresh_stop.is_set():
                self.send()
                deadline += period
                delay = deadline - time.monotonic()
                if delay > 0:
                    self._refresh_stop.wait(delay)
                else:
                    # fell behind, don't try to catch up with a burst
                    deadline = time.monotonic()
        except BaseException as exc:
            self._refresh_error = exc

    def _stop_refresh(self) -> BaseException | None:
        thread = self._refresh_thread
        if thread is None:
            return None

        self._refresh_stop.set()
        if thread is not threading.current_thread():
            thread.join()
        self._refresh_thread = None

        error, self._refresh_error = self._refresh_error, None
        return error

    def _open_fd(self) -> int:
        return os.open(self._port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)

    def _disable_rs485_mode(self) -> None:
        """Disable RS485 mode, keeping the initial configuration for close()."""
        fd = self._open_fd()
        try:
            # Same lock as pyserial's exclusive open. Never change the RS485
            # configuration under another user of the port. Released on close
            # so pyserial can take it.
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise serial.SerialException(
                    errno.EBUSY, f"{self._port} is in use by another process"
                ) from None

            rs485_config = get_rs485_config(fd)
            flags = get_rs485_flags(rs485_config)

            if flags & SER_RS485_ENABLED:
                _rs485_config = bytearray(rs485_config)
                set_rs485_flags(_rs485_config, flags & ~SER_RS485_ENABLED)
                set_rs485_config(fd, _rs485_config)
                self._initial_rs485_config = rs485_config
        finally:
            os.close(fd)

    def _restore_rs485_mode(self) -> None:
        if self._initial_rs485_config is None:
            return

        fd = self._open_fd()
        try:
            set_rs485_config(fd, self._initial_rs485_config)
            self._initial_rs485_config = None
        finally:
            os.close(fd)


def _check_value(value: int, name: str) -> None:
    if not 0 <= value <= 0xFF:
        raise ValueError(f"{name} must be between 0 and 255, got {value}")
