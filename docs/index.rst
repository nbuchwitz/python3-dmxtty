dmxtty - DMX512 over RS485 serial interfaces
============================================

A Python library that sends DMX512 packets through any Linux serial interface
with an RS485 transceiver. It keeps the state of one universe and transmits it
on request or continuously from a background thread.

All it needs is a UART and an RS485 transceiver, which makes it easy to turn
embedded Linux boards like the Raspberry Pi into a DMX controller. The
Raspberry Pi 4 and 5 provide several UARTs, so a single board can serve
multiple universes.

The library is a transmitter only. It does not receive DMX and does not
implement RDM.

Features
--------

* Works with any Linux tty driving an RS485 transceiver
* 1-based channel addressing, matching fixture start addresses
* Background refresh at a configurable rate
* Helpers for crossfades, colors and fixture groups
* Configurable start code and universe size (24 to 512 channels)
* Restores the interface's RS485 configuration on close
* One universe per UART, multiple universes on boards with several UARTs

Planned
-------

* Support for the PIO of the Raspberry Pi, generating DMX without a UART

Quick Example
-------------

.. code-block:: python

   from dmxtty import DMX

   with DMX("/dev/ttyAMA0") as dmx:
       dmx.start()
       dmx.set_channels([255, 51, 0], start=1)
       dmx.set_channel(4, 255)

Documentation
-------------

.. toctree::
   :maxdepth: 2
   :caption: User Guide

   installation
   userguide

.. toctree::
   :maxdepth: 2
   :caption: API Reference

   api/dmx

Indices and Tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
