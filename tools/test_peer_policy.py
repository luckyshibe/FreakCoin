#!/usr/bin/env python3
"""Test local checkpoint and manual ban policy on disposable, loopback-only nodes."""
import argparse
import hashlib
from pathlib import Path
import secrets
import socket
import struct
import tempfile
import time

from test_rpc_smoke import Node, reserve_port

GENESIS = "000070a13350d97ff6cac06eebcb1ef837b74ebe924d5117cee85a384640e14e"


def eventually(check, description, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.1)
    raise AssertionError(description)


def message(command, payload=b""):
    checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    return bytes.fromhex("9dd118e9") + command.encode().ljust(12, b"\0") + struct.pack("<I", len(payload)) + checksum + payload


def legacy_peer(port):
    peer = socket.create_connection(("127.0.0.1", port), timeout=5)
    netaddr = struct.pack("<Q", 1) + bytes.fromhex("00000000000000000000ffff7f000001") + struct.pack(">H", port)
    agent = b"/FreakChain:1.0.0/"
    payload = struct.pack("<iQq", 60014, 1, int(time.time())) + netaddr * 2
    payload += struct.pack("<Q", secrets.randbits(64)) + bytes([len(agent)]) + agent + struct.pack("<i", 900000)
    peer.sendall(message("version", payload) + message("verack"))
    return peer


def rejected(port):
    with socket.create_connection(("127.0.0.1", port), timeout=5) as peer:
        peer.settimeout(5)
        try:
            assert peer.recv(1) == b"", "Banned incoming peer received a response"
        except ConnectionResetError:
            pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=Path(__file__).resolve().parents[1] / "src/FreakChaind")
    args = parser.parse_args()
    binary = args.binary.resolve(strict=True)
    with reserve_port() as blocked, tempfile.TemporaryDirectory(prefix="freakchain-peer-policy-") as temporary:
        root = Path(temporary)
        reservation = reserve_port()
        port = reservation.getsockname()[1]
        reservation.close()
        node = Node(binary, root / "wallet", blocked.getsockname()[1], ["127.0.0.1"])
        node.command += ["-listen=1", "-bind=127.0.0.1", "-port=" + str(port), "-maxconnections=32"]
        peers = []
        try:
            node.start()
            node.ready()
            original_checkpoint = node.call("getcheckpoint")
            assert "localcheckpoint" not in original_checkpoint, "Local checkpoint unexpectedly enabled by default"
            peers.append(legacy_peer(port))
            eventually(lambda: any(p["version"] == 60014 and p["startingheight"] == 900000 for p in node.call("getpeerinfo")), "Legacy peer handshake was not accepted")
            assert node.call("getblockcount") == 0, "Peer's claimed height changed the local chain"
            assert node.call("listbanned") == [], "High advertised height caused a manual ban"
            print("PASS: legacy protocol peer connects; advertised height alone neither advances the chain nor causes a ban", flush=True)

            for ip in ("localhost", "127.0.0.1:16555", "127.0.0.0/8"):
                _, response = node.rpc("setban", [ip, "add"])
                assert response["error"] and response["error"]["code"] == -8, "Invalid ban address accepted"
            for duration in (0, -1, 315360001):
                _, response = node.rpc("setban", ["127.0.0.1", "add", duration])
                assert response["error"] and response["error"]["code"] == -8, "Invalid ban duration accepted"
            node.call("setban", ["127.0.0.1", "add", 3600])
            eventually(lambda: node.call("getconnectioncount") == 0, "Banned connected peer was not disconnected")
            rejected(port)
            rejected(port)  # A different client source port must still be blocked.
            assert node.call("listbanned")[0]["address"] == "127.0.0.1"
            with reserve_port() as target:
                target.listen()
                target.settimeout(2)
                address = "127.0.0.1:" + str(target.getsockname()[1])
                node.call("addnode", [address, "onetry"])
                try:
                    unexpected, _ = target.accept()
                except socket.timeout:
                    pass
                else:
                    unexpected.close()
                    raise AssertionError("Numeric addnode bypassed an IP ban")
            with reserve_port() as target:
                target.listen()
                target.settimeout(10)
                node.call("addnode", ["localhost:" + str(target.getsockname()[1]), "onetry"])
                try:
                    resolved, _ = target.accept()
                except socket.timeout:
                    pass  # Also valid if name resolution avoided the connection.
                else:
                    with resolved:
                        resolved.settimeout(5)
                        assert resolved.recv(1) == b"", "Named addnode completed a handshake with a banned IP"
            node.stop()
            node.start()
            node.ready()
            rejected(port)
            assert node.call("listbanned")[0]["address"] == "127.0.0.1", "Manual ban lost across restart"
            node.call("setban", ["::ffff:127.0.0.1", "remove"])
            peers.append(legacy_peer(port))
            eventually(lambda: any(p["version"] == 60014 for p in node.call("getpeerinfo")), "Unbanned legacy peer could not reconnect")
            node.call("setban", ["127.0.0.1", "add", 1])
            eventually(lambda: node.call("listbanned") == [], "Manual ban did not expire")
            node.call("setban", ["127.0.0.1", "add", 3600])
            node.call("clearbanned")
            node.stop()
            node.start()
            node.ready()
            assert node.call("listbanned") == [], "Cleared ban returned after restart"
            node.stop()
            print("PASS: manual bans cover changing ports, existing peers and explicit connections; persistence, removal, expiry and clear work", flush=True)

            wallet = node.directory / "wallet.dat"
            original_wallet = wallet.read_bytes()
            original_blocks = {p.name: hashlib.sha256(p.read_bytes()).digest() for p in node.directory.glob("blk*.dat")}
            node.command.append("-localcheckpoint=0:" + "1" * 64)
            node.start()
            node.wait_stopped()
            assert "Loaded chain conflicts with -localcheckpoint" in (node.directory / "process.log").read_text()
            assert wallet.read_bytes() == original_wallet, "Conflicting startup changed wallet.dat"
            assert original_blocks and all(hashlib.sha256((node.directory / name).read_bytes()).digest() == digest for name, digest in original_blocks.items()), "Conflicting startup changed block files"
            node.command[-1] = "-localcheckpoint=0:" + GENESIS
            node.start()
            node.ready()
            checkpoint = node.call("getcheckpoint")
            assert checkpoint["localcheckpoint"] == {"height": 0, "hash": GENESIS, "verified": True}
            assert checkpoint["synccheckpoint"] == original_checkpoint["synccheckpoint"], "Local checkpoint changed the legacy stored checkpoint"
            node.stop()
            node.command[-1] = "-localcheckpoint=811000:" + "7" * 64
            node.start()
            node.ready()
            assert node.call("getcheckpoint")["localcheckpoint"]["verified"] is False, "Future local checkpoint incorrectly reported as verified"
            node.stop()
            node.command.pop()
            print("PASS: conflicting local checkpoint stops startup and preserves wallet/blocks; matching and future anchors report correctly", flush=True)

            bans = node.directory / "manual-peer-bans.dat"
            bans.write_text("invalid saved bans\n")
            node.start()
            node.wait_stopped()
            assert "Cannot load manual-peer-bans.dat" in (node.directory / "process.log").read_text()
            assert bans.read_text() == "invalid saved bans\n", "Invalid ban file was discarded"
            print("PASS: invalid saved bans stop startup instead of silently allowing peer connections", flush=True)
        except Exception:
            node.stop()
            log = node.directory / "process.log"
            if log.exists():
                print(log.read_text()[-5000:])
            raise
        finally:
            for peer in peers:
                peer.close()
            node.stop()
    print("Peer policy tests passed. No production wallet or public peer was used.")


if __name__ == "__main__":
    main()
