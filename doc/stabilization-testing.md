# Stabilization candidate: build and test

Work stays on `network-bootstrap`. This candidate changes local RPC setup,
wallet error handling, database migration safeguards, and networking resource
policy. It does not change mainnet genesis, rewards, target calculations,
transaction validation, the database-version constant, or wallet serialization.

## Clone into a separate directory

Keep the source used to build the running daemon, its local changes, its binary,
and the known-good x64 Windows environment. A fresh clone avoids overwriting any
other VPS-only changes. The five solo-mining/staking edits supplied from
`~/compil/FreakCoin` at commit `7f8feb13091d0fef399909e82c21d16b35a0823b`
are now committed directly in this branch. Both mining source files match the
file hashes shown in the supplied VPS diff.

```sh
git clone --single-branch --branch network-bootstrap https://github.com/luckyshibe/FreakCoin.git FreakCoin-stabilization
cd FreakCoin-stabilization
git rev-parse HEAD
python3 tools/build_linux.py --jobs 2
```

The helper checks tools, compiles and runs a dependency probe, and builds
`src/FreakChaind`. It installs nothing and does not start the daemon on your
wallet or connect to the pool. UPnP is disabled in this build path.

The agreed pool workflow is compile, back up the wallet and installed binary,
stop the current daemon, replace the binary, and test on the existing chain.
Keep the existing data directory, RPC credentials, and block notification
configuration. A failed build is not a reason to stop or replace the daemon.

## Optional automated checks

These checks were run during development; they are available on the VPS too:

```sh
python3 tools/build_linux.py --check --jobs 2
python3 tools/test_rpc_smoke.py
```

The smoke-test script launches the candidate on private temporary wallets. RPC
listens on local ephemeral ports; P2P attempts target a reserved, non-listening
loopback port. It tests actual listener addresses, authentication, encrypted
restart, staking-only unlock restrictions, backup restore, and invalid binding.
It never selects the production configuration or data directory.
It also checks the mainnet genesis hash and verifies that unsupported modes and
an invalid inbound connection budget fail before the chain database is loaded.
All three mining RPCs must still report initial synchronization on a fresh
zero-peer node, rather than requiring a peer or issuing work before sync.

If dependencies are outside standard locations, supply the paths used by the
working Linux build through `BOOST_INCLUDE_PATH`, `BOOST_LIB_PATH`,
`BDB_INCLUDE_PATH`, `BDB_LIB_PATH`, `OPENSSL_INCLUDE_PATH`, and
`OPENSSL_LIB_PATH`. `BDB_LIB_SUFFIX` defaults to `-4.8` and `BOOST_LIB_SUFFIX`
defaults to empty. `CXX`, `CXXFLAGS`, and `LDFLAGS` are supported. Use
`--preflight-only` to check these settings without compiling the project.

Berkeley DB 4.8 is required both at compile time and when opening the wallet
environment. Using a newer BDB library to get past a build error is not supported.
The test suite requires Linux and a linker supporting `--wrap=RAND_bytes`.

## What the offline tests cover

The `check` target executes the new stabilization suite. It creates a private
temporary directory under `/tmp`, uses synthetic keys and wallets, and starts no
P2P or RPC server threads. It covers secure config creation and failure,
RPC loopback/allowlist/bind behavior, master-key and salt RNG failures,
failed master-key writes and retry, encrypted-wallet key recovery from disk,
failed rewrite rollback, incomplete
encryption cleanup, incompatible index versions, and orphan-cache accounting.

Inherited Bitcoin test fixtures are not all repaired or included in this target.
This is not yet a full consensus suite or a historical-chain replay. Neither
`-regtest` nor this branch's unfinished `-testnet` is a safe test environment;
startup now rejects these unsupported modes with a clear error. `-zerotest` is
also rejected because its parameter object is not initialized.

## Behavior changes to check before rollout

- New RPC credentials use cryptographic randomness. Existing credentials are
  preserved. New POSIX config files are owner-readable/writable only; Windows
  creation requests a protected owner-only ACL.
- Linux build identity now includes the actual Git commit and a dirty marker
  for tracked local changes. Application, protocol and database version numbers
  are unchanged. Builds without generated metadata report an unknown build.
- RPC defaults to IPv4/IPv6 loopback even when `rpcallowip` is present.
  `rpcbind=127.0.0.1` is now honored. `rpcbind` accepts numeric IP addresses,
  may be repeated, and uses the separate `rpcport` setting. An explicit bind
  failure stops startup instead of falling back to a different interface.
- The pool's existing `rpcbind=127.0.0.1`, `rpcallowip=127.0.0.1`, and
  `rpcport=16556` remain suitable. Never expose RPC publicly. P2P uses 16555.
- P2P listening with `maxconnections` at or below 16 is rejected with an
  explanation. `maxconnections=64` avoids the old inbound-capacity trap.
  An outbound-only home wallet can use `listen=0` with a smaller positive limit.
- One-shot peer requests remain queued until an outbound slot is available.
  The orphan cache is limited to 750 blocks and 64 MiB of serialized block data;
  this is cache policy, not a change to valid-block rules.
- The pool's existing solo-mining/staking edits are preserved: zero peers alone
  do not block staking or `getworkex`, `getwork`, and `getblocktemplate`.
  Initial-sync protection remains active. The extra staking synchronization
  delay applies when connected peers report a greater height.
- Wallet encryption checks randomness and database writes. After encryption is
  committed, incomplete cleanup is reported explicitly and the wallet remains
  locked. The RPC/GUI asks the process to stop; preserve the passphrase and all
  wallet/rewrite/database-log files if recovery is needed.
- Wallet rewrite replacement uses a durable BDB transaction. An existing
  `.rewrite` file is preserved and causes a reported failure, so a failed prior
  attempt cannot be silently overwritten.
- An incompatible block-index version stops startup. It no longer deletes the
  index and block files. No automatic version migration is implemented.

## Pool checks after replacement

Confirm that the wallet opens with its existing balances and chain tip, RPC
listens on localhost, Yiimp obtains work and submits blocks, block notifications
arrive, and staking resumes when the existing wallet is unlocked for staking.
Keep the previous binary and wallet backup available for rollback.

The earlier fork investigation remains separate: preserve both chain histories
and compare common-height hashes, chain trust, and checkpoint state. A larger
height alone does not identify the history to keep.

Development checks do not establish historical-chain equivalence or Windows
compatibility. Windows x86 remains a separate later build.

## Verification recorded on 9 September 2026

The Linux x86-64 daemon and the 10-case stabilization suite were built with
GCC 13.3, the default `-O2` optimization and hardening flags, Boost 1.83.0,
Berkeley DB 4.8.30, and OpenSSL 3.0.13. All 10 offline cases passed. The runtime
script passed its listener/authentication, encrypted restart, staking-only
unlock, backup restore, binding failure, genesis, and startup-guard checks.

After applying the supplied VPS solo-mining/staking diff, the Linux build,
all 10 offline cases, and the runtime script passed again. The runtime check
also confirmed that `getworkex`, `getwork`, and `getblocktemplate` each return
the initial-sync error on a fresh zero-peer node. The reconciled source hashes
are `295e24f5af47f397525f79d6e4dcb8fd1419be1d` (`src/miner.cpp`) and
`6f1d49ea6493a271e92d59917d7b246379617b2f` (`src/rpcmining.cpp`).

The local dependency sources were Boost commit
`564e2ac16907019696cdaba8a93e3588ec596062` (with its pinned submodules) and
Berkeley DB commit `396612c40e7120ce7a4bb7408c60255c15691551`. BDB was built as a
static C++ library with `--enable-cxx --disable-shared --with-pic` and
`CXXFLAGS='-O2 -std=gnu++11'`; its internal `__atomic_compare_exchange` helper in
`dbinc/atomic.h` was renamed to `__db_atomic_compare_exchange` to avoid a modern
GCC builtin-name collision. No BDB wallet format or database logic was changed.

These checks used synthetic wallets only. Windows/Qt compilation, Windows ACL
behavior, historical-chain replay, live peer/failover load tests, and the pool's
Yiimp/solo-staking behavior still require their own validation. The rewrite test
injects a rename failure and verifies rollback; it is not a power-loss test.
