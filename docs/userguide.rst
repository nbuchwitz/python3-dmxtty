User Guide
==========

Opening the Interface
---------------------

:class:`~dmxtty.DMX` opens the serial interface immediately. Use it as a
context manager so the interface is closed and its RS485 configuration is
restored deterministically:

.. code-block:: python

   from dmxtty import DMX

   with DMX("/dev/ttyAMA0") as dmx:
       dmx.send_frame([255, 0, 0, 255])

The port is opened exclusively.

Setting Channels
----------------

Channel addresses are 1-based, matching the start address configured on a
fixture. Values range from 0 to 255 and are kept until changed:

.. code-block:: python

   dmx.set_channel(4, 255)                  # one channel
   dmx.set_channels([255, 51, 0], start=1)  # channels 1 to 3
   dmx.clear()                              # all channels to 0
   print(dmx.get_channel(4), dmx.data)

:meth:`~dmxtty.DMX.send_frame` instead replaces the whole universe and sets
every channel not covered by the given data to 0.

Keeping the Universe Refreshed
------------------------------

DMX receivers expect packets to be repeated continuously and many fall back
to a default state if packets stop. Either call :meth:`~dmxtty.DMX.send` in
the application loop or let a background thread repeat the packets:

.. code-block:: python

   import time

   with DMX("/dev/ttyAMA0") as dmx:
       dmx.start(rate=40)
       for level in range(256):
           dmx.set_channel(4, level)
           time.sleep(0.02)

Changes are picked up with the next packet. A full packet with 512 channels
takes about 23 ms, limiting the refresh to about 44 packets per second.
Universes with fewer channels allow faster refresh rates:

.. code-block:: python

   dmx = DMX("/dev/ttyAMA0", channels=32)

:meth:`~dmxtty.DMX.stop` ends the refresh and raises the error that
terminated it, if any. :meth:`~dmxtty.DMX.close` stops it as well.

RS485 Mode
----------

The DMX break cannot be generated while the interface is in kernel RS485
mode. :class:`~dmxtty.DMX` therefore disables RS485 mode before opening the
port and restores the initial configuration on close. The transceiver is
enabled through RTS instead, which stays asserted while the port is open.

As a side effect, the receiver stays enabled and transmitted packets are
echoed back. The library discards them before each packet.

If the process is killed without closing the interface, RS485 mode stays
disabled until it is configured again.

.. note::

   Patches that lift this limitation have been submitted to the Linux kernel.
   Once they land in a release, the break can be sent with RS485 mode enabled
   and this workaround will no longer be needed.

Multiple Universes
------------------

Each :class:`~dmxtty.DMX` instance drives one universe on one serial
interface. Boards with several UARTs, such as the Raspberry Pi 4 and 5, can
serve several universes at once by opening one instance per UART, each with
its own transceiver:

.. code-block:: python

   with DMX("/dev/ttyAMA0") as stage, DMX("/dev/ttyAMA2") as hall:
       stage.start()
       hall.start()
