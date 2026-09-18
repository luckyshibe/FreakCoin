#!/usr/bin/env python3
"""Test address sharing and automatic peer discovery with disposable local nodes.

Public-looking IPv4 addresses are labels inside a loopback SOCKS4 relay. The
relay only opens connections to its explicit loopback mapping; it never dials
the advertised addresses. No production wallet or public peer is used.
"""
import argparse
from contextlib import ExitStack
import hashlib
from pathlib import Path
import select
import socket
import socketserver
import struct
import tempfile
import threading
import time

from test_peer_policy import eventually, legacy_peer, message
from test_rpc_smoke import Node, reserve_port


POOL = "8.1.0.1"
PEER = "9.2.0.1"
P2P_PORT = 16555


def receive_exact(connection, length):
    result = b""
    while len(result) < length:
        data = connection.recv(length - len(result))
        if not data:
            raise EOFError("Peer disconnected before completing a message")
        result += data
    return result


def receive_message(connection, wanted):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        connection.settimeout(max(0.01, deadline - time.monotonic()))
        header = receive_exact(connection, 24)
        assert header[:4] == bytes.fromhex("9dd118e9"), "Wrong network magic"
        length = struct.unpack("<I", header[16:20])[0]
        assert length <= 1000000, "Unexpectedly large message in discovery test"
        payload = receive_exact(connection, length)
        assert hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4] == header[20:24]
        if header[4:16].rstrip(b"\0").decode() == wanted:
            return payload
    raise AssertionError("Did not receive " + wanted)


def wire_address(ip):
    return (struct.pack("<IQ", int(time.time()), 1)
            + bytes.fromhex("00000000000000000000ffff")
            + socket.inet_aton(ip) + struct.pack(">H", P2P_PORT))


class LocalRelay(socketserver.ThreadingTCPServer):
    daemon_threads = True

    def __init__(self, mapping):
        self.mapping = mapping
        super().__init__(("127.0.0.1", 0), RelayConnection)
        self.worker = threading.Thread(target=self.serve_forever, daemon=True)
        self.worker.start()

    def close(self):
        self.shutdown()
        self.server_close()
        self.worker.join(timeout=5)


class RelayConnection(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            self.request.settimeout(5)
            header = receive_exact(self.request, 8)
            assert header[:2] == b"\x04\x01", "Expected a SOCKS4 connection"
            for _ in range(256):
                if receive_exact(self.request, 1) == b"\0":
                    break
            else:
                raise AssertionError("SOCKS4 user ID is too long")
            target = (socket.inet_ntoa(header[4:8]), struct.unpack(">H", header[2:4])[0])
            port = self.server.mapping.get(target)
            if port is None:
                self.request.sendall(b"\0\x5b" + header[2:8])
                return
            with socket.create_connection(("127.0.0.1", port), timeout=5) as remote:
                self.request.sendall(b"\0\x5a" + header[2:8])
                while True:
                    readable, _, _ = select.select([self.request, remote], [], [], 1)
                    for source in readable:
                        data = source.recv(65536)
                        if not data:
                            return
                        (remote if source is self.request else self.request).sendall(data)
        except (OSError, EOFError):
            pass  # Normal shutdown/disconnection of a disposable node.


def listening_node(binary, root, name, blocked, external_ip):
    with reserve_port() as reserved:
        port = reserved.getsockname()[1]
    node = Node(binary, root / name, blocked, ["127.0.0.1"])
    node.command += ["-listen=1", "-bind=127.0.0.1", "-port=" + str(port),
                     "-maxconnections=32", "-externalip=" + external_ip]
    return node, port


def wait_for_wallet(wallet, check, description, timeout=20):
    try:
        eventually(check, description, timeout=timeout)
    except AssertionError:
        print((wallet.directory / "process.log").read_text()[-12000:], flush=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path,
                        default=Path(__file__).resolve().parents[1] / "src/FreakChaind")
    args = parser.parse_args()
    binary = args.binary.resolve(strict=True)
    with ExitStack() as cleanup:
        blocked = cleanup.enter_context(reserve_port())
        root = Path(cleanup.enter_context(tempfile.TemporaryDirectory(prefix="freakchain-discovery-")))
        pool, pool_port = listening_node(binary, root, "pool", blocked.getsockname()[1], POOL)
        other, other_port = listening_node(binary, root, "other", blocked.getsockname()[1], PEER)
        relay = LocalRelay({(POOL, P2P_PORT): pool_port, (PEER, P2P_PORT): other_port})
        cleanup.callback(relay.close)
        for node in (pool, other):
            cleanup.callback(node.stop)
            node.start()
            node.ready()

        # A legacy peer announces two listening endpoints to the pool. A pong
        # confirms the preceding addr message was processed before disconnect.
        with legacy_peer(pool_port) as announcer:
            announcer.sendall(message("addr", b"\x02" + wire_address(POOL) + wire_address(PEER)))
            nonce = struct.pack("<Q", 42)
            announcer.sendall(message("ping", nonce))
            assert receive_message(announcer, "pong") == nonce
        with legacy_peer(pool_port) as requester:
            requester.sendall(message("getaddr"))
            try:
                payload = receive_message(requester, "addr")
            except (OSError, EOFError) as error:
                raise AssertionError("Pool did not share its two saved peer addresses") from error
            assert len(payload) == 61 and payload[0] == 2, "Small address book was not shared"
            addresses = {(socket.inet_ntoa(payload[offset + 24:offset + 28]),
                          struct.unpack(">H", payload[offset + 28:offset + 30])[0])
                         for offset in (1, 31)}
            assert addresses == {(POOL, P2P_PORT), (PEER, P2P_PORT)}, "Listening endpoints changed"
            # Already-known addresses still need an empty reply to finish the request.
            requester.sendall(message("getaddr"))
            assert receive_message(requester, "addr") == b"\0", "Empty getaddr reply was omitted"
        print("PASS: a legacy peer receives a small address book and completed empty replies", flush=True)

        # Only the pool is configured. A fresh, outbound-only wallet must learn
        # the second peer via addr, then connect automatically using addrman.
        for mode in ("addnode", "connect"):
            wallet = Node(binary, root / mode, blocked.getsockname()[1], ["127.0.0.1"])
            cleanup.callback(wallet.stop)
            wallet.command = [arg for arg in wallet.command if not arg.startswith("-connect=")]
            wallet.command += ["-" + mode + "=" + POOL + ":" + str(P2P_PORT),
                               "-proxy=127.0.0.1:" + str(relay.server_address[1]),
                               "-socks=4", "-onlynet=ipv4", "-tor=0", "-maxconnections=4", "-debug=1"]
            wallet.start()
            wallet.ready()

            def connected():
                return {peer["addr"] for peer in wallet.call("getpeerinfo") if peer["version"] == 60014}

            pool_address = POOL + ":" + str(P2P_PORT)
            other_address = PEER + ":" + str(P2P_PORT)
            wait_for_wallet(wallet, lambda: pool_address in connected(), "Wallet did not connect to its configured pool")
            if mode == "addnode":
                wait_for_wallet(wallet, lambda: other_address in connected(),
                                "Outbound-only wallet failed to discover/connect to the second peer")
                assert all(not peer["inbound"] for peer in wallet.call("getpeerinfo")), "Wallet gained an inbound connection"
                print("PASS: with only addnode=pool, an outbound-only wallet discovers and connects to another peer", flush=True)
            else:
                time.sleep(3)
                assert connected() == {pool_address}, "Explicit connect= restriction was overridden"
            wallet.stop()
            if mode == "connect":
                # Read after shutdown: stdout is buffered when redirected to a
                # regular log file, so live log polling can miss received data.
                assert "received: addr (61 bytes)" in (wallet.directory / "process.log").read_text(), \
                    "Explicit-connect wallet did not receive the address book"
                print("PASS: explicit connect=pool still restricts connections to the pool", flush=True)
        print("Peer discovery tests passed. All sockets terminate on loopback; no public peer or production wallet was used.")


if __name__ == "__main__":
    main()
