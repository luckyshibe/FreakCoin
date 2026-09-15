# FreakChain project handoff — 12 September 2026

> **15 September continuation:** The user reopened performance work because
> 7b4e82a still consumed a CPU core. All three fresh message-handler stacks caught
> locator construction from inventory continuation. See the
> [current fix and evidence](locator-ancestor-performance.md). The previous
> phase's closeout below is historical.

> **Superseded status — 14 September 2026:** The Linux safeguards and verified local
> checkpoint were deployed after this handoff. Both performance fixes are now in
> the tested 7b4e82a source; all 18 native cases and both smoke suites passed, and
> Renato reported that the final rollout "did the trick". Performance work is
> closed for this phase at his request. Read
> [the updated cleanup notes](orphan-cleanup-performance.md) for the latest evidence.
> The older deployment instructions and unresolved-status statements below are
> historical. Keep the pool on Berkeley DB 5.3; Windows x64/x86 builds remain next.
> No rebuild is needed for this documentation-only status update.

## Start here: instructions for the next chat

Read this entire document before proposing changes. This is a continuity summary, not a verbatim chat export. The user is moving from Work mode to regular ChatGPT because usage limits repeatedly interrupted progress.

**Priority #1 is preserving the existing blockchain and compatibility with legacy wallets.** Revive this abandoned coin conservatively. Do not turn this into a broad modernization project. Do not promise that balances from incompatible fork histories can all be retained on one chain.

Continue from the verified state below. First state what is already deployed, what is only published, and the next practical step. Verify your own GitHub capabilities; access in the previous chat does not establish access in this one. If you cannot write the repository, say so and provide a reviewed patch or one-paste script the user can apply. Do not claim to have deployed anything to the VPS.

The immediate task is to compile and deploy the newly published Linux safeguards with Berkeley DB **5.3**, then enable the optional checkpoint using the already-matching block hash. Windows builds follow. Do not start a new investigation from scratch or ask again which project/branch/datadir to use.

## Working agreement

- Repository: https://github.com/luckyshibe/FreakCoin
- Working branch: **network-bootstrap**. Do not modify or merge `master` without explicit authorization.
- Abandoned upstream: https://github.com/Nugetzrul3/FreakChain. Another historical fork mentioned by Elmo: https://github.com/Penny-Admixture/FreakChain. Their current contents were not compared in this task.
- Workflow: assistant reviews/updates the GitHub branch; user pulls and compiles on VPS; user stops the daemon, backs up, installs, and tests on the real pool.
- User dislikes repeated permission questions, scattered manual edits, overcomplication and “one more thing” surprises. Complete authorized work, identify limitations honestly, and give short actionable instructions.
- Preserve genesis, reward rules, transaction/block serialization, wallet format, existing consensus rules and Zerocoin semantics. Do not change checkpoint signing keys or impose a new default network-wide checkpoint.
- Never delete wallet, chain/index files or Berkeley DB logs as a routine recovery instruction. Preserve a complete stopped-data backup before replacement/recovery.
- Do not disturb the working x64 Windows build environment; build x86 separately.
- User and Elmo communicate on Discord. Draft messages only when requested; do not send them.
- Use privacy-safe Git identity: `luckyshibe <69731496+luckyshibe@users.noreply.github.com>`.

## Exact published versus deployed state

| Item | State at handoff |
| --- | --- |
| Linux pool installed build | `ca558ce191fd044b0a7d18e6412da70f1d6f77b9`, confirmed running by user |
| Qt menu cleanup | Published in `9f4d2ba9607289edeabc6e50cf6c0956bf90d3e2`; new Windows executable not compiled |
| Local checkpoint and manual bans | Published in `c3ff3395b627c339ac12777a2d30b8945b04ab73`; **not deployed or activated on production** |
| Safeguard commit tree | `5d41a68fab7f87b22c0181a209251d9a12c0bbe6` |
| This handoff | Added by a subsequent documentation-only commit on the same branch; fetch the branch to obtain its exact current HEAD |
| Production manual bans applied by this chat | None |
| New network-wide hardcoded checkpoint | None |
| Home Windows wallet | Older working wallet, precise binary commit not supplied; user confirmed matching history below |
| Elmo | Offline during final changes; Windows 7 x86 build/testing pending |

## VPS and operational facts

User/host: `shibe@vmi619219`, UID/GID1000, groups include sudo, www-data and crypto-data.

| Purpose | Path/value |
| --- | --- |
| Current source | `/home/shibe/compil/FreakCoin-update` |
| Built daemon | `/home/shibe/compil/FreakCoin-update/src/FreakChaind` |
| Installed daemon | `/usr/bin/FreakChaind` |
| Previous working backup binary | `/usr/bin/FreakChaind-bkp` |
| Active data directory | `/home/crypto-data/wallets/.FreakChain` |
| Active configuration | `/home/crypto-data/wallets/.FreakChain/FreakChain.conf` |
| Known full recovery backup | `/home/shibe/FreakChain-backup-eXGe4hyC/data` |
| Pool P2P | `207.244.243.35:16555` |
| Mainnet RPC | `16556`, loopback only |
| Fallback seed | `198.48.239.248:16555` |

A later full stopped-data backup was also made during replacement using `mktemp -d "$HOME/FreakChain-backup-XXXXXXXX"`, but the user did not paste its resulting path. Do not invent it. The datadir was approximately1002MB and free disk approximately183GB when checked; these are historical measurements.

Preserve this exact existing pool notification setting:

```ini
blocknotify=/home/crypto-data/yiimp/site/stratum/blocknotify stratum.luckydogpool.com:7109 216 %s
```

Historical relevant configuration (inspect actual file before editing; do not replace wholesale):

```ini
port=16555
rpcport=16556
rpcbind=127.0.0.1
rpcallowip=127.0.0.1
bind=0.0.0.0
externalip=207.244.243.35:16555
addnode=198.48.239.248:16555
```

A stale `addnode=66.222.187.250:16555` existed historically. `maxconnections=12` previously rejected every inbound peer because this code reserves16 outbound slots. It was raised;64 was recommended. Newer code rejects a listening configuration with an insufficient budget. Four stale DNAT redirects to `10.8.0.3:16555` were removed; do not flush or broadly rewrite the firewall. The user does not want inbound connectivity to the home wallet.

The Yiimp coin RPC console and Qt debug console take bare commands (`getinfo` etc.). Linux shell commands require the executable and explicit datadir:

```bash
/usr/bin/FreakChaind -datadir=/home/crypto-data/wallets/.FreakChain getinfo
```

Do not expose RPC publicly or paste credentials into chat.

## Database outage: do not repeat this mistake

The earlier assistant incorrectly forced Berkeley DB4.8. The actual previous pool daemon used **5.3**. Running the4.8-linked update against its existing environment failed with:

```text
unsupported log version 19
DB_RUNRECOVERY: Fatal error, run database recovery (-30974)
Error initializing database environment
```

The old error message suggested deleting everything except wallet.dat. **That instruction was not followed.** The full stopped datadir was backed up, `/usr/bin/FreakChaind-bkp` was verified by `ldd` to use `libdb_cxx-5.3.so`, and that binary restarted successfully. No destructive database migration was needed.

Commit `ca558ce` fixed the mistake: supports4.8 and5.3 with explicit build selection, verifies header/runtime versions, forces rebuild on version selection changes, and replaces the destructive startup error text. The pool now successfully runs the5.3 build.

The presence of `/usr/local/BerkeleyDB.4.8/` does not mean the production data environment uses4.8. Keep Linux pool on5.3. Previous Windows builds use4.8. Do not interchange entire environments or promise cross-version wallet migration without validation.

User verified current pool dependencies: Boost1.71, Berkeley DB5.3.28, OpenSSL1.1.1f and GCC10. The installed binary's `getinfo` reported commitca558ce, protocol60014, walletversion60000, no errors, and5 connections. Its balance was2645282.26260000 and stake39125.99430000 at block811288; these are historical snapshots, not targets for later exact balance comparison. Staking moves funds between fields.

## Chain agreement and Elmo's concerns

On12 September both pool and home Windows wallet reported block count **811298** and this identical historical block:

```text
getblockhash 811000
73977bc2631741b4964c36b57f90d134f02509619bbbe0dd6eb48878479c9793
```

This proves matching history through811000, not necessarily equal tips at811298 without comparing that hash too.

The pool's legacy `getcheckpoint` reported:

```json
{"synccheckpoint":"0000000001fa698a7d8ef4d3cbcdeee9fc1fbaede298cb6cc5b76e974818dea4","height":10000,"timestamp":"2020-04-22 00:00:00 UTC","policy":"strict"}
```

The home wallet reported:

```json
{"synccheckpoint":"000070a13350d97ff6cac06eebcb1ef837b74ebe924d5117cee85a384640e14e","height":0,"timestamp":"2020-03-11 12:49:38 UTC","policy":"strict"}
```

These are separately stored synchronized-checkpoint states, not proof of a current fork. Code loads saved state and can reset it when the stored master public key differs; the exact historical reason for this pair was not established. Existing signed checkpoint broadcasts require the existing private signing key, which is not available.

Latest pool peer snapshot, all inbound, protocol60014, banscore0:

| IP | Source port | Advertised startingheight |
| --- | --- | --- |
| 91.9.182.11 | 59160 | 827466 |
| 209.29.187.232 | 22460 | 811287 |
| 206.123.150.153 | 61503 | 811287 |
| 74.104.204.182 | 50090 | 832330 |
| 198.48.239.248 | 41390 | 811288 |
| 198.48.239.248 | 62309 | 811280 |

Home had outbound connections to209.29.187.232:16555 and the pool. Elmo owns several wallets; user also uses a VPN, so IP count is not operator count. **The original handoff identified74.104.204.182 as a home IP; later chat treated it as unidentified. Ownership remains uncertain. Never label it malicious from this snapshot.**

Elmo previously had a wallet at831850 while pool was around805062, later resynced his wallets, and reported they matched the pool. Some wallets stalled. Other peers advertised higher heights, making the GUI say it was thousands of blocks behind.

Technical conclusions from code inspection:

- `startingheight` is a peer's handshake-time claim, not its live verified chain height.
- More peers at one height is not a consensus vote. Validated accumulated `nChainTrust`, subject to validation/checkpoints, selects a chain.
- GUI peer-height estimates use a rolling median of recent announcements; disconnecting a peer does not necessarily clear its cached contribution immediately.
- A higher advertised height alone does not prove a fork, wrongdoing, or greater valid trust.
- An isolated node can stake; moving blocks do not prove it has other peers.
- Compare block hashes at shared heights. Preserve any old divergent data before investigating; do not tell Elmo to delete his wallet or force a resync merely to hide a warning.

## Newly published safeguards

Full operator instructions: `doc/local-peer-safeguards.md` in the repository.

### Optional local checkpoint

One configuration line, disabled by default:

```ini
localcheckpoint=811000:73977bc2631741b4964c36b57f90d134f02509619bbbe0dd6eb48878479c9793
```

This protects each updated node where explicitly enabled. It checks the loaded tip before accepting it at startup, incoming blocks, and chain reorganizations, including already-indexed branches and signed-checkpoint-triggered reorganizations. Rejection occurs before changing best-chain history. A loaded conflicting chain causes a non-destructive startup failure. Sync below the anchor is allowed; initial-download gates keep mining/staking waiting until the anchor is reached. Once reached, rollback below it is refused.

`getcheckpoint` adds a separate `localcheckpoint` object with height, hash and `verified`. Expect true after reaching the matching anchor. Existing legacy checkpoint fields remain unchanged.

It does not impose a new default checkpoint on the network, change a signing key, force legacy wallets to follow the pool, or prevent competing branches after811000. Legacy wallets retain their old protection level. Default consensus and wire formats are unchanged, but enabling a local pin intentionally narrows which histories that node accepts. Do not describe this as universal fork prevention or guaranteed full compatibility with every divergent legacy history.

### Manual IP bans

```text
setban 192.0.2.10 add 86400
listbanned
setban 192.0.2.10 remove
clearbanned
```

The address above is an example, not a real peer recommendation. Numeric IPv4/IPv6 only, no port/subnet/hostname. Default duration24h; allowed1second to10years. All ports for an IP are covered, connected peers are scheduled for disconnect, and bans survive restart in `manual-peer-bans.dat`. Changing IP can bypass an IP ban.

Writes preserve previous bans on failure. Malformed saved bans stop startup before peer networking. Explicit numeric addnode/connect targets are checked before socket connection; resolved hostnames are checked before handshake. Proxy-hidden destinations that cannot be checked are refused while manual bans exist. List/clear operate on manual bans only; legacy automatic misbehavior bans remain separate.

No automatic blacklist or height-based punishment was introduced. No production bans were issued. No Qt network-tab ban button was added; these RPCs will be usable from the newly compiled Windows console.

## Verification completed and limits

Safeguards were built on native Linux using GCC13.3, Boost1.83, OpenSSL3.0.13 and Berkeley DB5.3.28.

- All **13 offline stabilization tests passed**.
- `tools/test_rpc_smoke.py` passed: disposable wallet encryption/backup/restore, retained-log crash recovery, RPC binding and invalid startup options.
- `tools/test_peer_policy.py` passed: synthetic version60014 peer handshake despite a high height claim; bans across changing ports, connected peers and explicit destinations; persistence, removal, expiry and clear; checkpoint mismatch startup preserving wallet/block bytes; correct/future anchors; corrupt ban file refusal.
- Tests used disposable loopback-only nodes. No production wallet or public peer was used.
- A new offline test initially left the global LevelDB handle open and interfered with an existing test. Closing its owned handle fixed the test isolation; the final suite passes.
- No Windows compilation/runtime test has been performed for this latest source. Earlier ca558ce baseline passed native tests with both BDB4.8 and5.3; the new safeguard build was tested with5.3 only.
- No claim of real multi-node fork convergence or exhaustive security auditing. GUI cached-height behavior remains largely unchanged.
- Synthetic tests check the reorganization guard and that a conflicting candidate is rejected before database changes; they do not replay an entire real fork containing historical transactions.

## Next Linux step and deployment sequence

Build while the working pool daemon remains running:

```bash
cd ~/compil/FreakCoin-update &&
git pull --ff-only &&
python3 tools/build_linux.py --bdb-version 5.3 --jobs 2
```

Then verify before stopping production:

```bash
cd ~/compil/FreakCoin-update
git log -1 --format='%H %s'
ldd src/FreakChaind | grep -E 'libdb|not found'
./src/FreakChaind --help | head -n 1
```

Expect5.3 and no missing libraries. The build ID will reflect the branch HEAD, which may be the documentation commit afterc3ff339.

For the next assistant: provide one concise deployment block after inspecting these results. Required order:

1. Record current `getinfo`, `getblockhash 811000` and, if practical, a recent common hash from both nodes.
2. Stop via the currently running daemon RPC. Wait until the actual daemon process exits; `FreakChain server stopping` alone is not confirmation. Verify with `ps`; do not mistake the short-lived RPC client for the server.
3. Make a fresh full stopped-data backup and a uniquely named copy of the currently installed binary. Preserve the existing older backup too. Check copy success before installing.
4. Add the localcheckpoint line exactly once to the existing config, preserving RPC credentials and blocknotify. The older home binary does not enforce it; enable it there only after updating that wallet.
5. Install the compiled binary, then start exactly one daemon using `-datadir=/home/crypto-data/wallets/.FreakChain -daemon`.
6. Check `getinfo`, `getcheckpoint` with local verifiedtrue, blockhash811000, connections, advancing blocks and Yiimp work/share/block behavior. Startup text alone does not establish success.

Do not bundle speculative IP bans into this deployment. A checkpoint secures the chosen history without needing to identify every peer first.

Rollback: stop the new daemon cleanly; preserve any new diagnostics; restore the binary saved immediately before this upgrade using the same BDB5.3; remove/comment the optional localcheckpoint line if necessary; restart with the explicit datadir. A legacy binary ignores the new manual-ban file, so those bans will not be enforced. Do not restore an old wallet/datadir over newer state automatically: diagnose first, especially if transactions occurred.

## Earlier published source changes worth preserving

- `0548b143194fa537f6d9eba186e0542ce2462dac`: previous Windows/network modernization, runtime addnode and bootstrap nodes. It is now in published branch history; the original handoff's uncertainty about whether it was pushed is obsolete.
- `8617178128b4a5201fd5f8c607385b0bacfbb8a2`: RPC credential creation/access checks; explicit RPC binding and loopback defaults; encryption RNG/database failure handling; safer wallet rewrite rollback; refuse incompatible block index without deleting it; bounded orphan cache750blocks/64MiB; connection queue fixes; reject unsupported testnet/regtest/zerotest modes; modern Linux build support and tests. Its initial BDB4.8 enforcement was corrected later.
- `b81be0eafad1f73260940ee84776d2c7564c26eb`: preserves the user's solo mining/staking edits. Staking waits on initial download, not simply absence of peers; extra peer-height wait applies only when peers exist. Removed no-peer errors from getwork/getworkex/getblocktemplate, retaining initial-download checks. Do not regress this accidentally.
- `f8b2369d9961415da27269570a76d54f2fb95461`: fixes wallet backup copy flags for older Boost. `copy_options::overwrite_existing` is used only with newer Boost, older supported Boost gets `copy_option::overwrite_if_exists`. CScript deprecated-copy notes are warnings, not that compile failure.
- `ca558ce191fd044b0a7d18e6412da70f1d6f77b9`: BDB compatibility correction and safe recovery messages, deployed successfully.
- `9f4d2ba9607289edeabc6e50cf6c0956bf90d3e2`: removes the whole Links menu and all Social items except Discord; Discord now opens **https://discord.gg/QNQXCAzatp**. Modified only `src/qt/bitcoingui.cpp` and `.h`; static references checked, new Windows build pending.
- `c3ff3395b627c339ac12777a2d30b8945b04ab73`: current local-checkpoint/manual-ban work described above.

## Windows x64 and x86 continuity

The previous successful x64 environment is on `shibe2@shibe`, Ubuntu22.04.5:

```text
~/compil/freak-win/FreakCoin
~/compil/freak-win/mxe
~/compil/freak-win/deps/db48-win64
```

MXE target`x86_64-w64-mingw32.static`, Qt5.15.19 static, MXE GCC11.5, BDB4.8.30.NC static, LevelDB static. Prior binary was verified PE32+ x86-64. Historical qmake command, to recheck against current source/dependencies before reuse:

```bash
cd ~/compil/freak-win/FreakCoin
export PATH="$HOME/compil/freak-win/mxe/usr/bin:$PATH"
~/compil/freak-win/mxe/usr/x86_64-w64-mingw32.static/qt5/bin/qmake \
  freakchain.pro USE_UPNP=- \
  BOOST_INCLUDE_PATH=$HOME/compil/freak-win/mxe/usr/x86_64-w64-mingw32.static/include \
  BOOST_LIB_PATH=$HOME/compil/freak-win/mxe/usr/x86_64-w64-mingw32.static/lib \
  BOOST_LIB_SUFFIX=-mt-x64 BOOST_THREAD_LIB_SUFFIX=-mt-x64 \
  BDB_INCLUDE_PATH=$HOME/compil/freak-win/deps/db48-win64/include \
  BDB_LIB_PATH=$HOME/compil/freak-win/deps/db48-win64/lib BDB_LIB_SUFFIX=-4.8 \
  OPENSSL_INCLUDE_PATH=$HOME/compil/freak-win/mxe/usr/x86_64-w64-mingw32.static/include \
  OPENSSL_LIB_PATH=$HOME/compil/freak-win/mxe/usr/x86_64-w64-mingw32.static/lib
make -j2
```

Do not disturb that tree to build Elmo's Windows7 x86 version. Planned separate tree:

```text
~/compil/freak-win32/FreakCoin
~/compil/freak-win32/mxe
~/compil/freak-win32/deps/db48-win32
~/compil/freak-win32/build
```

Target`i686-w64-mingw32.static`; all dependencies must be32-bit. Dependency setup and compilation remain pending. Verify PE32, required DLLs, actual Windows7 launch, RPC/peer behavior, staking/sync and menus before publishing. Do not promise Windows7 support merely because it compiles.

Existing Windows changes include modern OpenSSL/Boost compatibility, Qt include fixes, crypt32 link after crypto, runtime addnode, bootstrap seeds, and an English-only translation workaround (`QMAKE_LRELEASE`/`TRANSLATIONS` cleared and translation resources removed). Avoid committing generated Makefiles, release outputs, qmake caches or backup files.

Elmo wants hosted wallet downloads eventually. After tested builds, publish clearly versioned x64/x86 packages with SHA256 checksums, connection info and upgrade instructions. No new release binaries or hosting were produced in this task. An old unsigned binary previously triggered a small number of antivirus engines; that was not proof of either malware or safety. Any release needs assessment of its own artifact.

## Files and continuity limitations

Repository documents/tests are durable on `network-bootstrap`. This document supersedes the earlier `freakchain_astra_handoff(1).md`, especially its BDB4.8-only assumption and stale Git status. The older document should not override newer production evidence.

The previous assistant workspace was `/workspace/scratch/e9f12dbe1079/FreakCoin`; regular ChatGPT must not assume it exists. Native build dependencies/test logs were outside that checkout under `/workspace/scratch/e9f12dbe1079/build-deps`, and may disappear. Reconstruct tests from the committed scripts instead of relying on scratch files.

A GitHub connector was used to publish verified full blobs and a tree matching the local staged tree, followed by a non-forced update of `network-bootstrap` and local fetch verification. Earlier remote whole-file editing had once truncated net.cpp and was reverted. Always inspect diffs, compare full-file hashes/tree IDs and verify branch state; never trust an incomplete tool output as a complete source file.

Next priorities, in order: Linux rollout and checkpoint verification; compile/test the cleaned Windows x64 wallet; isolated Windows7 x86 build for Elmo; compare real common hashes and collect evidence if fork concerns persist; then host tested wallet packages. Broader improvements, chat-in-wallet features, sweeping consensus changes and automatic peer punishment are outside current scope.
