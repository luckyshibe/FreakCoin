#!/usr/bin/env python3
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]

# --- rpcmining.cpp ---
rpc_path = root / "src" / "rpcmining.cpp"
rpc = rpc_path.read_text()

peer_check = '''    if (vNodes.empty())
        throw JSONRPCError(RPC_CLIENT_NOT_CONNECTED, "FreakChain is not connected!");

'''
peer_check_ex = '''    if (vNodes.empty())
        throw JSONRPCError(-9, "FreakChain is not connected!");

'''

count_normal = rpc.count(peer_check)
count_ex = rpc.count(peer_check_ex)

if count_normal == 0 and count_ex == 0:
    print("rpcmining.cpp peer gates are already removed")
else:
    if count_normal != 2 or count_ex != 1:
        print(f"ERROR: expected 2 normal peer gates and 1 getworkex peer gate; found {count_normal} and {count_ex}. No changes made.", file=sys.stderr)
        raise SystemExit(1)
    rpc = rpc.replace(peer_check, "")
    rpc = rpc.replace(peer_check_ex, "")
    rpc_path.write_text(rpc)
    print("Updated src/rpcmining.cpp: getwork, getworkex and getblocktemplate no longer require an active peer")

# --- miner.cpp ---
miner_path = root / "src" / "miner.cpp"
miner = miner_path.read_text()

old_wait = '''        while (vNodes.empty() || IsInitialBlockDownload())
        {
            nLastCoinStakeSearchInterval = 0;
            fTryToSync = true;
            MilliSleep(1000);
            if (fShutdown)
                return;
        }
'''
new_wait = '''        while (IsInitialBlockDownload())
        {
            nLastCoinStakeSearchInterval = 0;
            fTryToSync = true;
            MilliSleep(1000);
            if (fShutdown)
                return;
        }
'''

old_sync = '''        if (fTryToSync)
        {
            fTryToSync = false;
            if (vNodes.size() < 3 || nBestHeight < GetNumBlocksOfPeers())
            {
                MilliSleep(60000);
                continue;
            }
        }
'''
new_sync = '''        if (fTryToSync)
        {
            fTryToSync = false;
            if (!vNodes.empty() && nBestHeight < GetNumBlocksOfPeers())
            {
                MilliSleep(60000);
                continue;
            }
        }
'''

already_wait = new_wait in miner
already_sync = new_sync in miner

if already_wait and already_sync:
    print("miner.cpp solo-staking guards are already modernized")
else:
    if miner.count(old_wait) != 1 or miner.count(old_sync) != 1:
        print("ERROR: expected legacy StakeMiner peer/sync blocks not found exactly once; no miner.cpp changes made", file=sys.stderr)
        raise SystemExit(1)
    miner = miner.replace(old_wait, new_wait, 1)
    miner = miner.replace(old_sync, new_sync, 1)
    miner_path.write_text(miner)
    print("Updated src/miner.cpp: staking may run with zero peers, while IBD and behind-peer checks remain enforced")

print("Done. Consensus rules were not changed; only local mining/staking availability gates were adjusted.")
