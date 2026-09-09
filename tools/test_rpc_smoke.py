#!/usr/bin/env python3
"""Exercise a candidate daemon using temporary wallets and local RPC only."""
import argparse
import base64
import http.client
import ipaddress
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import tempfile
import time


def reserve_port(family=socket.AF_INET, address="127.0.0.1"):
    sock = socket.socket(family)
    sock.bind((address, 0))
    return sock


class Node:
    def __init__(self, binary, directory, blocked_peer, bindings=()):
        self.directory = directory
        directory.mkdir(mode=0o700)
        self.user = "freakchain-smoke"
        self.password = secrets.token_hex(32)
        port = reserve_port()
        self.port = port.getsockname()[1]
        port.close()
        config = directory / "FreakChain.conf"
        with config.open("x") as out:
            os.chmod(config, 0o600)
            out.write(f"rpcuser={self.user}\nrpcpassword={self.password}\nrpcallowip=127.0.0.1\n")
            for address in bindings:
                out.write("rpcbind=" + address + "\n")
        self.command = [str(binary), "-datadir=" + str(directory), "-server=1",
                        "-rpcport=" + str(self.port), "-listen=0", "-dnsseed=0",
                        "-dns=0", "-discover=0", "-upnp=0", "-staking=0",
                        "-keypool=2", "-printtoconsole=1",
                        "-connect=127.0.0.1:" + str(blocked_peer)]
        self.process = None
        self.log = None

    def start(self):
        self.log = (self.directory / "process.log").open("a")
        self.process = subprocess.Popen(self.command, stdout=self.log, stderr=subprocess.STDOUT)

    def rpc(self, method, params=(), host="127.0.0.1", bad_password=False):
        password = "invalid" if bad_password else self.password
        authorization = base64.b64encode((self.user + ":" + password).encode()).decode()
        connection = http.client.HTTPConnection(host, self.port, timeout=3)
        try:
            connection.request("POST", "/", json.dumps({"method": method, "params": list(params), "id": 1}),
                               {"Authorization": "Basic " + authorization, "Content-Type": "application/json"})
            response = connection.getresponse()
            data = response.read()
            if response.status == 401:
                return response.status, None
            return response.status, json.loads(data)
        finally:
            connection.close()

    def call(self, method, params=(), host="127.0.0.1"):
        status, body = self.rpc(method, params, host)
        if status != 200 or body.get("error"):
            raise AssertionError("RPC failed: " + method + ": " + str(body.get("error")))
        return body["result"]

    def ready(self):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise AssertionError("Daemon exited before RPC became ready; see " + str(self.directory / "process.log"))
            try:
                self.call("getinfo")
                return
            except (OSError, http.client.HTTPException):
                time.sleep(0.1)
        raise AssertionError("RPC startup timed out")

    def wait_stopped(self):
        self.process.wait(timeout=20)
        self.log.close()
        self.process = None

    def stop(self):
        if self.process is None:
            return
        try:
            if self.process.poll() is None:
                self.call("stop")
            self.wait_stopped()
        except (OSError, AssertionError, subprocess.TimeoutExpired, http.client.HTTPException):
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            self.log.close()
            self.process = None

    def listener_addresses(self):
        # The daemon disables dumpability, which can protect /proc/PID/fd.
        # The network namespace's public socket table still identifies the
        # fresh port whose RPC credentials we have just authenticated.
        result = []
        for name in ("tcp", "tcp6"):
            for row in Path("/proc/net", name).read_text().splitlines()[1:]:
                fields = row.split()
                address, port = fields[1].split(":")
                if fields[3] != "0A" or int(port, 16) != self.port:
                    continue
                raw = bytes.fromhex(address)
                native = b"".join(raw[i:i+4][::-1] for i in range(0, len(raw), 4))
                result.append(ipaddress.ip_address(native))
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=Path(__file__).resolve().parents[1] / "src/FreakChaind")
    args = parser.parse_args()
    binary = args.binary.resolve(strict=True)
    # Keep a loopback port bound but not listening. All P2P attempts target this
    # reserved port, which cannot accidentally be another running pool node.
    with reserve_port() as blocked, tempfile.TemporaryDirectory(prefix="freakchain-rpc-smoke-") as temporary:
        directory = Path(temporary)
        node = Node(binary, directory / "wallet", blocked.getsockname()[1])
        try:
            node.start()
            node.ready()
            assert node.call("getblockhash", [0]) == "000070a13350d97ff6cac06eebcb1ef837b74ebe924d5117cee85a384640e14e", "Mainnet genesis hash changed"
            assert node.call("getconnectioncount") == 0, "Smoke-test node unexpectedly has peers"
            for method in ("getworkex", "getwork", "getblocktemplate"):
                _, response = node.rpc(method)
                assert response["error"] and response["error"]["code"] == -10, "Mining RPC did not retain its initial-sync guard: " + method
            print("PASS: all three mining RPCs retain initial-sync protection with zero peers", flush=True)
            listeners = node.listener_addresses()
            assert listeners and all(address.is_loopback for address in listeners), "RPC has a non-loopback listener"
            assert node.rpc("getinfo", bad_password=True)[0] == 401, "Invalid RPC credentials were accepted"
            if ipaddress.ip_address("::1") in listeners:
                node.call("getinfo", host="::1")
                print("PASS: IPv4 and IPv6 localhost RPC; allowlist does not widen listeners", flush=True)
            else:
                print("PASS: IPv4 localhost RPC (IPv6 unavailable); allowlist does not widen listeners", flush=True)
            address = node.call("getnewaddress")
            private_key = node.call("dumpprivkey", [address])
            backup = directory / "backup.dat"
            node.call("backupwallet", [str(backup)])
            assert backup.is_file(), "Wallet backup was not created"
            passphrase = secrets.token_hex(24)
            node.call("encryptwallet", [passphrase])
            node.wait_stopped()
            node.start()
            node.ready()
            node.call("walletpassphrase", [passphrase, 30, True])
            _, denied = node.rpc("dumpprivkey", [address])
            assert denied["error"] is not None, "Staking-only unlock allowed private-key export"
            node.call("walletlock")
            node.call("walletpassphrase", [passphrase, 30, False])
            assert node.call("dumpprivkey", [address]) == private_key, "Encrypted wallet lost its key across restart"
            node.stop()
            print("PASS: encrypted-wallet restart and staking-only unlock restriction", flush=True)
            restored = Node(binary, directory / "restored", blocked.getsockname()[1], ["127.0.0.1"])
            node = restored
            shutil.copyfile(backup, restored.directory / "wallet.dat")
            node.start()
            node.ready()
            assert node.listener_addresses() == [ipaddress.ip_address("127.0.0.1")], "Explicit RPC binding was not honored"
            assert node.call("dumpprivkey", [address]) == private_key, "Backup restore lost its key"
            node.stop()
            print("PASS: backup restore and explicit IPv4 RPC binding", flush=True)
            node = Node(binary, directory / "bad-bind", blocked.getsockname()[1], ["invalid-address"])
            node.start()
            node.wait_stopped()
            assert "Invalid -rpcbind address" in (node.directory / "process.log").read_text(), "Invalid RPC bind was not rejected"
            print("PASS: invalid explicit RPC binding stops startup", flush=True)
            guards = [
                (["-regtest=1"], "Regression-test mode is not implemented"),
                (["-testnet=1"], "Testnet has no configured genesis"),
                (["-zerotest=1"], "Zerocoin self-test parameters are not initialized"),
                (["-listen=1", "-maxconnections=12"], "-maxconnections must exceed 16"),
            ]
            for index, (flags, message) in enumerate(guards):
                node = Node(binary, directory / ("guard-" + str(index)), blocked.getsockname()[1])
                node.command.extend(flags)
                node.start()
                node.wait_stopped()
                assert message in (node.directory / "process.log").read_text(), "Startup guard failed: " + flags[0]
                assert not (node.directory / "txleveldb").exists(), "Startup guard loaded the chain database"
            print("PASS: unsupported network/self-test modes and invalid inbound budget fail before chain loading", flush=True)
        except Exception:
            # These are synthetic, isolated wallet logs; no real wallet is read.
            node.stop()
            log = node.directory / "process.log"
            if log.exists():
                print(log.read_text()[-5000:])
            raise
        finally:
            node.stop()
    print("RPC smoke tests passed. No production data directory was used.")


if __name__ == "__main__":
    main()
