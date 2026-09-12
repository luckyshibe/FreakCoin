# Local chain checkpoint and manual peer bans

These controls are optional local operator policy. They do not change the genesis, rewards, transaction format, protocol 60014, built-in checkpoints, or checkpoint signing key. Unconfigured nodes retain their existing chain-selection rules. Legacy wallets can still communicate with updated nodes, but do not acquire these protections automatically.

## Pin a verified historical block

Add exactly one line to the active data directory's `FreakChain.conf`, then restart the updated daemon:

```ini
localcheckpoint=811000:73977bc2631741b4964c36b57f90d134f02509619bbbe0dd6eb48878479c9793
```

This example is the hash the operator reported matching on the pool and home Windows wallet on 2026-09-12. Verify it against your own existing chain before enabling it. It is not a newly declared network-wide checkpoint.

The node checks the loaded chain at startup, incoming blocks, and chain reorganizations, including already-indexed branches. A conflicting loaded chain stops startup without resetting the chain. Initial synchronization below the selected height is allowed, but mining/staking remain gated by initial download until that height is reached. Once reached, reorganizations below the anchor are refused.

`getcheckpoint` retains its existing synchronized-checkpoint fields and adds:

```json
"localcheckpoint": {
  "height": 811000,
  "hash": "73977bc2631741b4964c36b57f90d134f02509619bbbe0dd6eb48878479c9793",
  "verified": true
}
```

`verified` is false while below the anchor. The existing `synccheckpoint` may remain at height 0 or 10000; this is separate stored state.

The anchor cannot prevent forks after height 811000, force old wallets to follow the pool, or reconcile balances earned on incompatible histories. Removing the option and restarting removes this local restriction. Preserve data and investigate a mismatch; do not delete wallet or chain files to silence it.

## Persistent manual IP bans

In the wallet debug console or Yiimp coin RPC console:

```text
setban 192.0.2.10 add 86400
listbanned
setban 192.0.2.10 remove
clearbanned
```

The IP above is a documentation example, not a recommended peer to ban. Use a numeric IPv4 or IPv6 address without a port, subnet, or hostname. A ban covers every P2P port of that IP and schedules connected peers for disconnection. Default duration is 86400 seconds; allowed range is 1 second to 10 years. Changing source ports does not evade the ban; changing IP can.

Bans persist in `manual-peer-bans.dat`, separate from the wallet and chain databases. Saves use an exclusive temporary file, checked flush, and replacement before updating in-memory state. Malformed saved bans stop startup before peer networking, preserving the file for repair. `listbanned` and `clearbanned` cover manual bans only; existing automatic misbehavior bans remain separate.

Explicit numeric `addnode`/`connect` destinations are checked before connecting. Named destinations are checked after resolution and before the protocol handshake. Proxy-resolved destinations whose IP cannot be checked are refused while active manual bans exist.

A peer's `startingheight` is only its claim at connection time, not proof of a fork or misconduct. No IPs are automatically banned for height, and no production peer is hardcoded into a blacklist. Peer count is not a consensus vote. Legacy chain selection compares validated accumulated chain trust, subject to validation and checkpoints. The GUI's cached peer-height estimate can still be misleading; this change does not redesign that estimate.

## Build and validate

The existing Linux pool uses Berkeley DB **5.3**, not 4.8:

```bash
cd ~/compil/FreakCoin-update &&
git pull --ff-only &&
python3 tools/build_linux.py --bdb-version 5.3 --jobs 2
```

Do not switch Berkeley DB versions against an existing environment. Compile while the working daemon stays running. Before replacement, stop cleanly, confirm it exited, and back up the entire data directory and installed binary. Start one daemon only, using the explicit data directory. Verify its build ID, linked Berkeley DB library, `getinfo`, `getcheckpoint`, block hashes, and pool operation.

Optional developer checks use disposable data, not production:

```bash
python3 tools/build_linux.py --bdb-version 5.3 --check --jobs 2
python3 tools/test_rpc_smoke.py
python3 tools/test_peer_policy.py
```

The changes were compiled and tested on native Linux with BDB 5.3.28, Boost 1.83, GCC 13.3 and OpenSSL 3.0.13. Windows Qt/x64/x86 compilation and live-network rollout remain pending. The Windows source includes the same core controls; no GUI ban button was added.
