# Orphan cleanup candidate — 14 September 2026

## Current production evidence

Production is running `b9ec4048fbb2a0c2fc02905db04df9459eb8de28`
from `/home/shibe/compil/FreakCoin-locator-fix`. The installed executable is
`/usr/bin/FreakChaind`, using Berkeley DB 5.3 and the existing data directory
`/home/crypto-data/wallets/.FreakChain`.

The locator cache improved the observed RPC timings, but did not resolve CPU
saturation. In the supplied 60-second after measurement, the message-handler
thread used 86.911% of one CPU core, total daemon CPU was 104.944%, and the log
recorded 355 orphan arrivals and 355 evictions (5.916 per second).
All six getpeerinfo and six getinfo requests succeeded; their median durations
were 0.376 and 0.360 seconds respectively. The authenticated Yiimp status page
eventually loaded, after a delay. The helper's public HTTP probe does not
measure that authenticated page or its AJAX requests.

Subsequent listtransactions calls both succeeded: 10 entries took 1.527 seconds
and 500 took 0.097 seconds. These two samples do not establish a persistent
transaction-list bottleneck or explain why the first call was slower.

Three fresh message-handler stack captures showed:

1. `CTransaction::IsCoinStake -> EraseOrphanBlock -> LimitOrphanBlocks`:
   scanning retained orphans when removing a stake entry.
2. `scrypt_blockhash -> CBlock::GetHash -> ProcessMessage`:
   calculating an incoming block's hash.
3. `CKey::Verify -> CheckBlockSignature -> CheckBlock -> ProcessBlock`:
   checking a proof-of-stake block signature.

None of these samples caught the previous locator loop. Three stacks do not
give a reliable time breakdown or prove that cleanup accounts for all remaining
CPU usage. The second sample is incoming-block hashing, not evidence that it
was hashing inside the eviction traversal.

## Scope of this candidate

The runtime change is confined to orphan-cache bookkeeping in `src/main.cpp`:

- The parent-to-child index stores the child hash already computed at insertion.
  Eviction follows the same first child and selects the same leaf, without
  recalculating scrypt hashes at every step.
- A count tracks how many cached orphan blocks share a stake. Removing one
  updates the existing membership set only when the last reference disappears.
  This replaces the full-cache scan observed in the first stack.
- Orphan processing resolves the indexed child hash to its existing cached
  block and continues to call `AcceptBlock`. It preserves sibling iteration
  order and uses the saved hash for the recovery queue and removal.

The count map has at most one entry per distinct stake in the bounded cache.
The existing 750-block / 64-MiB serialized-data limits are unchanged. Hashes are
stored in the orphan index, not cached on mutable general-purpose CBlock objects.

The source for block hashing, CheckBlock, AcceptBlock, signature verification,
and ProcessBlock's validation and duplicate-stake checks is unchanged.
No consensus, protocol, wallet format, Berkeley DB version, reward, checkpoint,
peer-ban rule, mining setting or GUI behavior is changed. Required validation
work remains, and the size of any production CPU improvement is unknown.

One makefile prerequisite is corrected so changing the generated build header
rebuilds `obj/version.o`. This addresses the previously observed stale version
string on incremental builds and helps identify the binary actually deployed.

## Review and tests

Three offline regression cases were added to the existing stabilization suite
(18 cases total):

- Shared stake membership survives until its final cached block is removed;
  duplicate insertion, repeated removal, unrelated stakes, non-stake blocks
  and re-insertion preserve bookkeeping.
- Branched orphan graphs, siblings and children arriving before parents retain
  the previous implementation's exact eviction order and stake membership.
- A 750-block synthetic stake chain repeatedly adds and evicts its leaf for
  256 requests, reports CPU time without a timing-based pass/fail threshold,
  checks the retained blocks, then drains the cache.

The existing count/byte-limit, locator, wallet and peer-policy tests remain.
Cache fixtures are synthetic and do not claim to be valid historical blocks.

Source review verified that the validation regions named above were unchanged.
A JavaScript algorithm model compared 32,768 operations across 64 synthetic
forests against the previous bookkeeping/selection behavior, including count
and byte limits, duplicates and arbitrary removal; the states and eviction
orders matched. That is a review aid, not execution of the C++ implementation.

**No C++ build, native regression run, Windows build, or production test of this
candidate was performed by the assistant: its execution workspace was unavailable.**
The VPS build and tests below are required before replacing the running daemon.
Do not treat the earlier b9ec404 test results as results for this candidate.

## Compile and test on the VPS

The current locator checkout was created as a detached worktree. Fast-forward it
to the published candidate on `network-bootstrap`; a detached HEAD can use
`git merge --ff-only`. The older checkout with the private throttle commit and
its source backup files remains separate.

```sh
cd ~/compil/FreakCoin-locator-fix &&
git diff --quiet &&
git diff --cached --quiet &&
git fetch origin network-bootstrap &&
git merge --ff-only origin/network-bootstrap &&
git update-index --refresh &&
python3 tools/build_linux.py --bdb-version 5.3 --check --jobs 2 &&
python3 tools/test_rpc_smoke.py &&
python3 tools/test_peer_policy.py
```

The build installs nothing. The tests use private temporary data directories.
After all checks succeed, inspect the build identity and library linkage:

```sh
git --no-pager log -1 --format='%H %s'
ldd src/FreakChaind | grep -E 'libdb|not found'
./src/FreakChaind -datadir=/home/crypto-data/wallets/.FreakChain --help | head -n 1
```

The version must contain the checkout's current commit, with no dirty marker.
Keep Berkeley DB 5.3 for this pool. Compilation, test or version failures should
be resolved before stopping the working daemon.

## Deployment and comparison still pending

After native checks pass, use the agreed workflow: graceful stop, confirm the
daemon has exited, copy the entire data directory and installed executable to a
new backup, install the tested executable, and restart with the explicit pool
data directory. Never delete chain, wallet, or Berkeley DB log files to recover
from a failed startup.

The last known complete pre-locator backup is
`/home/shibe/FreakChain-before-locator-CJE36rSn`; it contains the previous
4568a85 binary, its stopped data snapshot and `backup-complete` marker.
Make a new backup of the currently working b9ec404 deployment before replacing
it with this candidate.

After deployment, verify getinfo, getcheckpoint and getblockhash 811000, then run:

```sh
python3 tools/measure_pool.py --label after-orphan-cleanup --seconds 60 > "$HOME/FreakChain-performance-after-orphan-cleanup.json" &&
cat "$HOME/FreakChain-performance-after-orphan-cleanup.json"
```

Compare message-handler CPU, orphan/eviction rate, RPC success and latency,
actual Yiimp status-page behavior, and chain progress. A lower CPU result during
lower incoming traffic is not an equivalent-load comparison.

The verified local checkpoint is still:
`811000:73977bc2631741b4964c36b57f90d134f02509619bbbe0dd6eb48878479c9793`.
It is an opt-in local policy, not network-wide finality. The stored signed
checkpoint remains at height 10000 on the pool. Keep the same chain and preserve
compatibility with legacy wallets as the first priority. Windows x64/x86 builds
and distribution remain later work; this candidate is not a Windows release.
