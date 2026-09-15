# Locator ancestor lookup — 15 September 2026

Renato reopened CPU performance work after the earlier improvement made Yiimp
load but left FreakChain consuming a core. This supersedes the previous phase's
performance closeout. Preservation of the chain and legacy compatibility remain
the first priority.

## Production evidence

The supplied 30.006-second measurement confirms the running binary was
`7b4e82ab28e8cc01863fef7d34fd82c4010c7a99`, PID 597149, at height 812940
with five peers and an empty errors field. It measured:

- Total daemon CPU: 102.781% of one logical core.
- Message-handler CPU: 94.282%; staking thread: 2.466%.
- 1,282 orphan arrival log lines and 1,282 evictions, or 42.725 arrivals/second.
- getinfo: two successful calls, 3.822 and 4.310 seconds.
- getpeerinfo: two successful calls, 0.364 and 3.284 seconds.

`ps` confirmed one daemon process. All three message-handler stack captures
showed `CBlockLocator::Set -> CNode::PushGetBlocks -> ProcessMessage`, called
from the inventory continuation path at main.cpp:3169 in that version. RPC
and staking workers were waiting for locks. These snapshots locate a remaining
hot path; they do not measure the percentage of time in each function.

The previous per-peer cache holds one locator. It helps repeated requests with
an identical start block, but changing between the best tip and a previously
known inventory block rebuilds it. Each build still walked pprev to genesis,
touching roughly 813,000 indexes. The earlier benchmark kept the start fixed
and did not cover that cost.

## Change and compatibility

Add one in-memory ancestor pointer to each CBlockIndex. Its target height clears
the current height's lowest set bit. Ancestor lookup uses the shortcut only when
it cannot pass the requested height, otherwise following pprev. It follows the
starting block's own ancestry, including side branches; it does not depend on
the currently selected best chain or pnext links.

Both constructors initialize the pointer to null. New block indexes build it
after parent/height assignment. Startup reconstructs it in the existing
height-sorted pass after index loading. Missing shortcuts fall back to pprev.
No new file, serialized field, database version, or migration is introduced.
The added pointer is approximately 6.2 MiB for 813,000 indexes on a 64-bit build,
apart from any structure alignment differences.

CBlockLocator retains the legacy sequence, including the distinction between
landing on genesis and stepping beyond it, and the final genesis hash. Request
selection, ordering, duplicate filtering, per-peer caching, and stop hashes are
unchanged. No requests are throttled or dropped. Validation, rewards, chain
trust, checkpoint rules, peer bans, wallet format, and Berkeley DB selection
are unchanged. Linux pool builds must continue using Berkeley DB 5.3.

## Verification

Three new cases extend the 18-case native suite:

- Compare serialized locator bytes with an independent copy of the old loop
  at every height through 2048, on main and side branches, with both genesis
  tails and absent/initialized shortcuts. Check branch-specific ancestors and
  out-of-range queries.
- Check that the pointer has no effect on disk-index bytes and can be rebuilt
  from parent links after clearing transient state.
- At height 812940, issue 256 requests with a different starting block on each
  iteration, alternating continuation and orphan-recovery stop hashes. Compare
  every full message and checksum against the old locator output. Report the
  legacy construction and new request/verification CPU times separately.

The assistant compiled the complete daemon and ran all 21 native cases
successfully with GCC 13, Boost 1.83, Berkeley DB 5.3.28 and OpenSSL 3.0.13.
Both disposable RPC and peer-policy smoke suites also passed, including wallet
restart, retained-log recovery, checkpoint conflicts and a protocol-60014 peer.
These tests used isolated data directories and no production wallet or public peer.

For 256 changing-start requests at height 812940, the independent legacy
locator loop took 3.117752 CPU seconds; the shortcut requests plus complete
byte/checksum comparisons took 0.009733 CPU seconds on the same host. All
messages matched. The old fixed-start case also passed (0.020341 CPU seconds).
Timings are reported, not used as flaky pass/fail thresholds. These measurements
are synthetic; neither a full historical chain replay nor a Windows build is
claimed. The VPS has different compiler/Boost/OpenSSL versions, so its normal
build and checks are still required before deployment.

This change targets measured locator work. Incoming orphan traffic and required
block validation still consume resources. Do not claim production CPU is fixed
from a synthetic benchmark alone; obtain one after-install measurement.

## VPS workflow

Use the current detached worktree at `/home/shibe/compil/FreakCoin-locator-fix`.
The old `/home/shibe/compil/FreakCoin-update` tree still has the local throttle
commit 9589919 and must not be merged or deployed.

First fetch the reviewed source and compile/test with the existing BDB 5.3
selection. The next reply supplies the exact commit to advance to. The build
does not install anything or touch the production data directory. Once passed,
use the established clean stop, stopped full backup, binary install and restart
procedure. Do not delete wallet, block, index or BDB log files.

After installation, check the running version, empty errors, and verified local
checkpoint at 811000. Measure the same workload once:

```sh
python3 tools/measure_pool.py --label after-ancestor-fix --seconds 30
```

Compare total/message-handler CPU, incoming orphan rate, and RPC latency with
the baseline above. The helper's public HTTP request does not represent the
authenticated Yiimp status page; also refresh that page normally. Do not
infer a stalled chain solely from an unchanged height in a short sample.

Windows x64/x86 compilation remains pending. This shared-source change should
be included when those wallets are built, but no Windows build is claimed here.
