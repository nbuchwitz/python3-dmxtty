# SPDX-FileCopyrightText: 2026 Nicolai Buchwitz <nb@tipi-net.de>
#
# SPDX-License-Identifier: BSD-3-Clause

"""Art-Net to DMX node, one universe per serial interface.

Each output maps an Art-Net port-address (0..32767) to a serial interface.
The node answers ArtPoll, so controllers like QLC+ discover it.

    python artnet_node.py 0:/dev/ttyAMA0 1:/dev/ttyAMA2 --name "Stage node"

When packets for a universe stop, the outputs hold their last values. With
--timeout and --loss blackout they are set to 0 instead.

Packets from several controllers for the same universe are not merged, the
latest packet wins.
"""

from __future__ import annotations

import argparse
import socket
import struct
import time
from contextlib import ExitStack
from dataclasses import dataclass, field

from dmxtty import DMX

ARTNET_PORT = 6454
ARTNET_ID = b"Art-Net\x00"
PROTOCOL_VERSION = 14

OP_POLL = 0x2000
OP_POLL_REPLY = 0x2100
OP_DMX = 0x5000

# ArtPollReply PortTypes and GoodOutput: can output DMX512, data transmitted
PORT_TYPE_OUTPUT = 0x80
GOOD_OUTPUT_TRANSMITTING = 0x80
# ESTA manufacturer code reserved for prototyping
ESTA_PROTOTYPE = 0x7FF0
STYLE_NODE = 0x00


@dataclass
class Output:
    """One Art-Net universe driving one serial interface."""

    port_address: int
    dmx: DMX
    sequence: int = 0
    last_packet: float = field(default_factory=time.monotonic)
    blacked_out: bool = False

    def accept_sequence(self, sequence: int) -> bool:
        """Return whether a packet with this sequence number is not outdated.

        Sequence 0 disables reordering protection. Otherwise packets more than
        half the number range behind the last one are taken as a wrap-around.
        """
        if sequence == 0 or self.sequence == 0:
            self.sequence = sequence
            return True
        if 0 < (self.sequence - sequence) % 256 < 128:
            return False
        self.sequence = sequence
        return True


def parse_output(value: str) -> tuple[int, str]:
    """Parse an output given as PORT_ADDRESS:DEVICE, e.g. 0:/dev/ttyAMA0."""
    address, sep, port = value.partition(":")
    try:
        port_address = int(address, 0)
    except ValueError:
        port_address = -1
    if not sep or not port or not 0 <= port_address <= 0x7FFF:
        raise argparse.ArgumentTypeError(f"expected PORT_ADDRESS:DEVICE, got {value!r}")
    return port_address, port


def local_ip_for(peer: str) -> str:
    """Return the local address used to reach a peer."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.connect((peer, ARTNET_PORT))
        return probe.getsockname()[0]


def poll_reply(output: Output, index: int, ip: str, short_name: str, long_name: str) -> bytes:
    """Build the ArtPollReply announcing one output.

    Every output gets its own reply with a single port and BindIndex, so
    outputs are free to use different Net and Sub-Net values.
    """
    net = (output.port_address >> 8) & 0x7F
    sub_net = (output.port_address >> 4) & 0x0F
    universe = output.port_address & 0x0F
    ip_bytes = socket.inet_aton(ip)

    reply = bytearray(239)
    struct.pack_into("<8sH", reply, 0, ARTNET_ID, OP_POLL_REPLY)
    struct.pack_into("<4sH", reply, 10, ip_bytes, ARTNET_PORT)
    struct.pack_into(">HBBH", reply, 16, 1, net, sub_net, 0x00FF)
    struct.pack_into("<H", reply, 24, ESTA_PROTOTYPE)
    struct.pack_into("18s64s", reply, 26, short_name.encode()[:17], long_name.encode()[:63])
    report = f"#0001 [{index:04d}] {output.dmx.port}".encode()[:63]
    struct.pack_into("64s", reply, 108, report)
    struct.pack_into(">H", reply, 172, 1)
    reply[174] = PORT_TYPE_OUTPUT
    reply[182] = GOOD_OUTPUT_TRANSMITTING
    reply[190] = universe
    reply[200] = STYLE_NODE
    struct.pack_into("4sB", reply, 207, ip_bytes, index)
    return bytes(reply)


def handle_dmx(packet: bytes, outputs: dict[int, Output]) -> None:
    """Apply an ArtDmx packet to the matching output."""
    if len(packet) < 18:
        return
    # SubUni and Net form the little endian port-address, Length is big endian
    sequence, _physical, port_address = struct.unpack_from("<BBH", packet, 12)
    (length,) = struct.unpack_from(">H", packet, 16)
    output = outputs.get(port_address & 0x7FFF)
    if output is None or not output.accept_sequence(sequence):
        return

    data = packet[18 : 18 + min(length, output.dmx.channels)]
    output.dmx.set_channels(data)
    output.last_packet = time.monotonic()
    output.blacked_out = False


def main() -> None:
    """Parse arguments and run the node until interrupted."""
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        epilog=__doc__.split("\n\n", 1)[1],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "outputs", type=parse_output, nargs="+", metavar="PORT_ADDRESS:DEVICE", help="output"
    )
    parser.add_argument("--name", default="dmxtty node", help="name shown in controllers")
    parser.add_argument("--bind", default="0.0.0.0", help="address to listen on")
    parser.add_argument(
        "--timeout", type=float, default=2.0, help="seconds without packets until data loss"
    )
    parser.add_argument(
        "--loss", choices=["hold", "blackout"], default="hold", help="action on data loss"
    )
    args = parser.parse_args()

    port_addresses = [address for address, _ in args.outputs]
    if len(set(port_addresses)) != len(port_addresses):
        parser.error("each port-address can only be used once")

    with ExitStack() as stack:
        outputs: dict[int, Output] = {}
        for address, port in args.outputs:
            dmx = stack.enter_context(DMX(port))
            dmx.start()
            outputs[address] = Output(address, dmx)
            print(f"universe {address} -> {port}")

        sock = stack.enter_context(socket.socket(socket.AF_INET, socket.SOCK_DGRAM))
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind((args.bind, ARTNET_PORT))
        sock.settimeout(0.5)
        print(f"listening on {args.bind}:{ARTNET_PORT}")

        try:
            while True:
                try:
                    packet, (peer, _) = sock.recvfrom(1024)
                except TimeoutError:
                    packet = b""

                if packet[:8] == ARTNET_ID and len(packet) >= 12:
                    opcode, version = struct.unpack_from("<H", packet, 8)[0], packet[11]
                    if opcode == OP_DMX and version >= PROTOCOL_VERSION:
                        handle_dmx(packet, outputs)
                    elif opcode == OP_POLL:
                        ip = local_ip_for(peer)
                        for index, output in enumerate(outputs.values(), start=1):
                            reply = poll_reply(output, index, ip, args.name[:17], args.name)
                            # Art-Net 4 allows a unicast reply to the controller
                            sock.sendto(reply, (peer, ARTNET_PORT))

                if args.loss == "blackout":
                    now = time.monotonic()
                    for output in outputs.values():
                        if not output.blacked_out and now - output.last_packet > args.timeout:
                            output.dmx.clear()
                            output.blacked_out = True
                            print(f"universe {output.port_address}: no data, blackout")
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
