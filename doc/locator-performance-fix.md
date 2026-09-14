# Locator performance fix and Linux rollout — 14 September 2026

> **Historical procedure:** The locator fix was deployed, followed by the orphan
> cleanup fix in 7b4e82a. All 18 native tests and both smoke suites passed, and
> Renato confirmed the final update worked. He has closed performance work for
> this phase. Do not repeat the rollout or measurement campaign below by default;
> see [the latest cleanup notes](orphan-cleanup-performance.md).

## Status and finding

The user reports production running `4568a8572eec379ac7b2d4f1cd917474f66efe6a` with the local checkpoint enabled and verified. This supersedes the deployment status in the September12 handoff. The chain is alive, but the message-handler thread consumes roughly one CPU core and Yiimp sometimes returns504.

Three supplied GDB samples caught `CBlockLocator::Set -> CNode::PushGetBlocks -> ProcessBlock`. Independent source inspection confirms that changing orphan roots defeat the existing exact-request duplicate check. Each request then walks essentially the whole indexed ancestry despite emitting only a short locator. `ProcessMessages` holds `cs_main` while doing this, so RPCs that need that lock can be delayed. The orphan flood predates the checkpoint release; supplied logs contain no local-checkpoint conflict rejections.

The repeated full-chain traversal is a confirmed expensive mechanism, reproduced below. It is strongly supported as the sampled CPU bottleneck. **Production CPU and Yiimp recovery remain unverified until the operator deploys and measures.** This patch does not establish the cause of every orphan or promise that the orphan flood itself will end.

## Small source change

`src/net.cpp` and `src/net.h` retain one immutable block locator per peer. The existing starting-index pointer keys the cache; a different starting block rebuilds it, including a same-height fork, rollback, normal sync continuation or null start. Indexed blocks and their `pprev` ancestry remain stable during a running node's lifetime. The shared chain lock already serializes every production call; an assertion documents that requirement.

A changed stop hash reuses the locator and still sends the request immediately. Exact duplicates remain filtered exactly as before. Memory is bounded to one small locator per connected CNode, released with it. Caching state is not serialized to disk or sent as a new protocol field.

There is no throttle, global clock, new ban, consensus change, checkpoint change, wallet/database-format change or altered PoW/PoS validation. `ProcessBlock`, `WantedByOrphan`, `AskFor` and `CBlockLocator::Set` remain unchanged. Shared source applies to Windows too, but Windows compilation/runtime validation for this change remains pending.

Why not the proposed global throttle? Any peer could consume its time slot and suppress another peer's needed recovery request. Even a per-peer throttle needs retry/progress design. `AskFor` is skipped during initial download and its scheduled requests are not equivalent to the locator exchange, so it cannot justify silently dropping those calls. We avoid that behavior change by removing repeated computation instead.

Upstream comparison: [Peercoin v0.4.0's PushGetBlocks](https://github.com/peercoin/peercoin/blob/v0.4.0ppc/src/net.cpp) has the same uncached construction. [Bitcoin v0.10.0's GetLocator](https://github.com/bitcoin/bitcoin/blob/v0.10.0/src/chain.cpp) uses a height-indexed active chain and skip-list ancestors. Adopting those structures would be a substantially broader backport than this fix.

Other work in the orphan path includes orphan-ancestry lookups, leaf eviction and a proof-of-stake duplicate scan, bounded by the750-block cache, plus block validation, request queuing and logging. Those remain possible costs if load persists. Alternating starting blocks or reconnecting causes cache rebuilds; this is a fix for repeated requests from the same start, not universal protection against all P2P resource exhaustion.

## Verification

Native Linux: GCC13.3, Boost1.83, OpenSSL3.0.13, Berkeley DB5.3.28, normal optimized/hardened build.

| Same synthetic workload: height812000,256 distinct recovery requests | Process CPU time |
| --- | --- |
| Original published request implementation | 3.200596seconds |
| Per-peer locator cache | 0.015026seconds |

Approximately213times less CPU in this isolated workload; not a forecast of total production speedup. No timing threshold is used as a flaky unit-test gate.

All **15 offline tests pass**. New deterministic checks verify cache reuse, peer independence, exact duplicate handling, null start, tip advance, same-height branch change and return to an earlier tip. They inspect the actual queued `getblocks` header, checksum and payload against the legacy locator serialization. Every distinct request must be sent immediately; the proposed global/per-peer time throttles fail that expectation. The long-chain test reports CPU time to reproduce the sampled hot path.

Both existing daemon scripts passed: `tools/test_rpc_smoke.py` and `tools/test_peer_policy.py`. They cover disposable wallet/recovery/RPC behavior and local-checkpoint/manual-ban behavior. No real wallet or public peer was used.

`tools/measure_pool.py` was exercised with a disposable daemon, injected new orphan/eviction log lines and a local HTTP server. It successfully measured both RPCs, CPU and HTTP and counted only new lines. The test environment uses a different PID namespace from its mounted /proc; the test supplied the matching /proc PID via `--pid`. A normal VPS uses its daemon PID file directly.

## 1. Inspect the VPS checkout first

The assistant cannot inspect this remote shell. Run these read-only commands and retain the output before changing its Git state. They deliberately disable the pager:

```bash
cd ~/compil/FreakCoin-update
git --no-pager status
git --no-pager status --short
git --no-pager log -3 --oneline --decorate
git --no-pager show --stat --oneline HEAD
git --no-pager show HEAD -- src/net.cpp
git --no-pager diff
git --no-pager diff HEAD^ HEAD -- src/net.cpp
```

Do not amend/reset/rebase the local throttle commit. Do not commit `src/net.cpp.pre-orphan-throttle-*` backup files. The next step uses a separate worktree, so both the local commit and any uncommitted patch remain available untouched in the original checkout.

## 2. Build the reviewed branch in a clean worktree

After reviewing that inspection, fetch the published branch and create a new build directory. If the destination already exists, stop and inspect it; do not overwrite it.

```bash
git -C ~/compil/FreakCoin-update fetch origin network-bootstrap &&
git -C ~/compil/FreakCoin-update worktree add --detach ../FreakCoin-locator-fix origin/network-bootstrap &&
cd ~/compil/FreakCoin-locator-fix &&
python3 tools/build_linux.py --bdb-version 5.3 --check --jobs 2 &&
python3 tools/test_rpc_smoke.py &&
python3 tools/test_peer_policy.py
```

This builds the published source, without combining it with the unpublished throttle. It does not require GitHub write credentials. Do not paste commands at a Git username/password prompt; cancel an unexpected prompt with Ctrl+C and inspect the remote configuration first.

Production must stay on **BDB5.3**. Do not point this build at `/usr/local/BerkeleyDB.4.8`. Before stopping production, inspect:

```bash
cd ~/compil/FreakCoin-locator-fix
git --no-pager status --short
git --no-pager log -1 --format='%H %s'
ldd src/FreakChaind | grep -E 'libdb|not found'
./src/FreakChaind -datadir=/home/crypto-data/wallets/.FreakChain --help | head -n 1
```

Expect no tracked changes, the reviewed published commit, `libdb_cxx-5.3.so`, no missing dependencies, and a matching build version. Keep the working daemon running until build/tests/linkage checks all pass.

## 3. Measure the current daemon before replacement

The read-only measurement helper uses the existing installed CLI and active datadir by default. It does not stop the daemon, touch configuration, ban peers or print wallet balances/credentials.

```bash
cd ~/compil/FreakCoin-locator-fix
python3 tools/measure_pool.py --label before --seconds 60 > "$HOME/FreakChain-performance-before.json"
cat "$HOME/FreakChain-performance-before.json"
/usr/bin/FreakChaind -datadir=/home/crypto-data/wallets/.FreakChain getcheckpoint
/usr/bin/FreakChaind -datadir=/home/crypto-data/wallets/.FreakChain getblockhash 811000
```

Expected historical hash:

```text
73977bc2631741b4964c36b57f90d134f02509619bbbe0dd6eb48878479c9793
```

Retain the verified checkpoint. Do not ban74.104.204.182 (confirmed home wallet) or172.111.177.138 (associated Windows wallet). The prior experiment excluding91.9.182.11 did not remove the reported load; do not change bans/peer topology for this before/after comparison.

## 4. Stop, confirm exit, back up

No command block here uses `set -e` or changes interactive shell failure handling.

```bash
/usr/bin/FreakChaind -datadir=/home/crypto-data/wallets/.FreakChain stop
ps -C FreakChaind -o user,pid,stat,comm
```

Wait until the daemon has exited; repeat the `ps` check if necessary. Do not force-kill it to speed up this rollout. If it will not stop, preserve logs and diagnose before continuing.

Once stopped, this guarded block makes a new full backup and keeps the current4568a85 binary for rollback. It preserves the earlier `/usr/bin/FreakChaind-pre-20260913-164704` and `/home/shibe/FreakChain-backup-20260913-164704/data` too.

```bash
if pgrep -x FreakChaind >/dev/null; then
    printf '%s\n' 'Daemon is still running. No backup or install performed.'
else
    freak_backup="$(mktemp -d "$HOME/FreakChain-before-locator-XXXXXXXX")" &&
    sudo cp -a /home/crypto-data/wallets/.FreakChain "$freak_backup/data" &&
    sudo cp -a /usr/bin/FreakChaind "$freak_backup/FreakChaind" &&
    sudo cmp -s /usr/bin/FreakChaind "$freak_backup/FreakChaind" &&
    touch "$freak_backup/backup-complete" &&
    printf 'Backup and rollback binary saved in: %s\n' "$freak_backup"
fi
```

Retain the printed path. Continue only after both copies succeed. If a supervisor automatically restarts the daemon, stop that supervisor before the backup; never copy an actively changing wallet environment as a stopped-data backup.

## 5. Install and start one daemon

After successful backup and all earlier checks:

```bash
if pgrep -x FreakChaind >/dev/null; then
    printf '%s\n' 'Daemon is running. Installation skipped.'
elif test -n "$freak_backup" && test -f "$freak_backup/backup-complete" && test -f "$freak_backup/data/wallet.dat" && test -f "$freak_backup/FreakChaind"; then
    sudo install -m 0755 "$HOME/compil/FreakCoin-locator-fix/src/FreakChaind" /usr/bin/FreakChaind &&
    /usr/bin/FreakChaind -datadir=/home/crypto-data/wallets/.FreakChain -daemon
else
    printf '%s\n' 'Completed backup not confirmed. Installation skipped.'
fi
```

No config edits are needed. Keep the local checkpoint, RPC bind and Yiimp blocknotify unchanged. `FreakChain server starting` alone does not establish successful startup. Check:

```bash
/usr/bin/FreakChaind -datadir=/home/crypto-data/wallets/.FreakChain getinfo
/usr/bin/FreakChaind -datadir=/home/crypto-data/wallets/.FreakChain getcheckpoint
/usr/bin/FreakChaind -datadir=/home/crypto-data/wallets/.FreakChain getblockhash 811000
```

Confirm the new build ID, no new errors, localcheckpoint verifiedtrue, historical hash unchanged, advancing chain and working Yiimp mining/staking/notifications. Do not paste wallet-unlock passphrases into chat.

## 6. Measure after replacement

Wait until normal peers and workload are back, then:

```bash
cd ~/compil/FreakCoin-locator-fix
python3 tools/measure_pool.py --label after --seconds 60 > "$HOME/FreakChain-performance-after.json"
cat "$HOME/FreakChain-performance-after.json"
```

Repeat another60-second sample after the node has run for several minutes, saving a different filename. Avoid compiling or other new heavy tasks during either comparison.

The JSON reports:

- `cpu_percent`: total daemon CPU averaged over the actual interval;100%means one fully occupied core.
- `threads`: same-interval per-thread CPU, including the message-handler name (Linux may truncate it to `FreakChain-msgh`). Only threads present at both boundaries have per-thread deltas; the process total covers all threads.
- `new_orphan_lines`, `orphans_per_second`, and eviction log-line count. It reads only newly appended debug.log content. Rotation/truncation invalidates the rate and is flagged.
- `rpc_and_web.getpeerinfo/getinfo`: individual durations, success/failure, median and maximum successful latency. Calls use the datadir's existing credentials automatically.
- `rpc_and_web.yiimp`: timed requests to the actual coin page, with HTTP status/errors. Check it in a browser too if behavior is intermittent.

The default request timeout is10seconds. A timeout is recorded as a failure, not a successful10-second response. Use `--timeout 30` if you need to observe the previously seen21-second call. A request already in progress can extend the nominal interval; `elapsed_seconds` is the actual CPU/log measurement duration. HTTP timings are from the VPS's network vantage point, not a guarantee about every user's browser.

Success requires sustained lower message-handler/total CPU, responsive RPC and Yiimp under comparable peer/orphan load, and continued chain agreement. Orphan count need not fall and might rise as processing gets faster. If CPU remains high, the fix is not yet sufficient: retain these samples and obtain another short profile of the remaining hot path before changing anything else.

## Rollback if needed

Use the newly saved4568a85 binary, keeping the configured checkpoint and current data. Do not restore an old wallet/datadir over newer transactions by default.

```bash
/usr/bin/FreakChaind -datadir=/home/crypto-data/wallets/.FreakChain stop
ps -C FreakChaind -o user,pid,stat,comm
```

After confirmed exit, in the same shell where `freak_backup` was set (or set it to the exact printed backup directory):

```bash
if pgrep -x FreakChaind >/dev/null; then
    printf '%s\n' 'Daemon is still running. Rollback skipped.'
elif test -n "$freak_backup" && test -f "$freak_backup/backup-complete" && test -f "$freak_backup/FreakChaind"; then
    sudo install -m 0755 "$freak_backup/FreakChaind" /usr/bin/FreakChaind &&
    /usr/bin/FreakChaind -datadir=/home/crypto-data/wallets/.FreakChain -daemon
else
    printf '%s\n' 'Set freak_backup to the exact saved backup directory first.'
fi
```

Recheck `getinfo`, `getcheckpoint` and the known hash. Preserve performance reports and logs. This change requires no database migration or data rollback.
