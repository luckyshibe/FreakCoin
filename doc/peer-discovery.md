# Peer discovery repair — September 18, 2026

The pool should be a stable starting peer from which wallets learn other
reachable listening nodes. Three defects in the shared Linux/Windows source
prevented that in a small network:

1. `CAddrMan::GetAddr` returned 23% of its saved addresses, rounded down. With
   one to four entries it returned none. Filtering that sample for age could
   also discard the entire reply even when other recent entries existed.
2. IPv4 was marked reachable only after discovering/setting a public local
   address. `listen=0` disables that discovery by default. Such wallets could
   connect to the configured pool but discard IPv4 addresses sent by peers.
3. Selecting an already-connected network group ended the connection search
   for that cycle. A recently active pool was repeatedly selected ahead of
   older advertised peers, delaying their connection even after discovery.

The repair shares up to the whole small address book (a floor of 16, limited by
the number of eligible entries). Larger replies keep the existing 23% target
and 2,500-address cap, with existing wire batches of at most 1,000 addresses.
Entries at or before the existing `addrlifespan` cutoff are skipped while
filling the sample; they are not deleted from the address database. An empty
reply completes `getaddr` when there are no new addresses to send.

IPv4 outbound reachability is initialized independently of a public local
address. `onlynet`, manual bans, connection limits, and explicit `connect`
restrictions remain in effect. No incoming listener or router mapping is
enabled by this change.

Peer selection now skips connected/local/disabled destinations within the
existing 100-selection budget. It stops early when every saved address has
been skipped, so a tiny table of already-connected peers does not keep causing
100 redundant selections. The one-outbound-connection-per-network-group rule
is preserved.

## Home wallet settings

Use the active wallet data directory's `FreakChain.conf`. On a default Windows
installation that is `%APPDATA%\FreakChain\FreakChain.conf`.

```ini
addnode=207.244.243.35:16555
listen=0
```

`addnode` keeps trying the pool and permits automatic discovery. `connect`
intentionally limits connections to the explicitly listed destinations. If a
pool-only `connect=207.244.243.35:16555` line exists, replace that line with
`addnode`; adding both does not remove the restriction. Check launch shortcuts
for a `-connect` argument as well. Keep at least two connection slots if more
than one peer is wanted. Restart after editing configuration.

These lines express the existing preference against incoming connections to
the home wallet. They do not set RPC credentials or add a local checkpoint.
Windows wallets remain unpinned unless their operator independently chooses
an anchor. Preserve the pool's already configured local checkpoint.

Discovery still needs another reachable listening endpoint. Two wallets both
using `listen=0`, or both behind routers that reject incoming connections,
cannot connect directly to each other. They can each discover and connect to
other public listeners. Do not copy an inbound peer's temporary source port
from `getpeerinfo` into an `addnode` line; its listening port is a separate
endpoint, normally 16555.

## Build and verification

Update `network-bootstrap` and rebuild the Linux pool and both Windows Qt
architectures from the same source. The Linux pool must retain Berkeley DB
5.3; keep the existing separate BDB 4.8 Windows toolchains. A pool-only upgrade
repairs its address sharing but does not repair an old client's IPv4 filter.
Do not delete `peers.dat`, wallet files, chain files, or database logs as part
of this update.

For the existing VPS checkout, after fetching/fast-forwarding the intended
branch revision:

```bash
python3 tools/build_linux.py --bdb-version 5.3 --check --jobs 2
python3 tools/test_peer_discovery.py
```

The source also includes commit `9679d0e`, the pending fix for the changing
block-locator starts found in the September 15 CPU stacks. See
[locator-ancestor-performance.md](locator-ancestor-performance.md). Its live
deployment and CPU result have not yet been confirmed by the operator.

The native Linux build passed all 23 offline tests, the RPC smoke tests, and
the peer-policy smoke tests. The complete discovery test passed three times
after the selection repair. Windows binaries still need rebuilding with the
existing x86/x64 toolchains; production rollout has not been performed here.

Development validation uses disposable data:

- Native tests cover empty and small address books, advertised listening
  ports, expired candidates, and the existing percentage for larger tables.
- `tools/test_peer_discovery.py` runs a pool, another listening node, and fresh
  outbound-only clients. The client configured only with `addnode=pool` must
  learn the other address and establish a protocol-60014 connection. A client
  configured with `connect=pool` must stay restricted to the pool.
- Synthetic routable IPv4 labels pass through a SOCKS4 relay that maps only to
  explicitly assigned loopback ports. No public peer is contacted. A legacy
  handshake checks the address reply and empty-reply completion.
- The address-sharing failure was reproduced against the pre-repair daemon
  before changing its source. Existing RPC and peer-policy smoke tests remain
  the compatibility checks for the candidate.

These checks do not establish which real peers are online or reachable. After
installing the rebuilt pool and wallets, inspect `getpeerinfo` on each and
compare a common-height block hash. Discovery does not certify a peer's chain.
No peer is banned because of a reported height, and no consensus rule,
protocol version, genesis, reward, checkpoint key, or wallet format is changed.
