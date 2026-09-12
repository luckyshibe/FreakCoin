#define BOOST_TEST_MODULE FreakChain_stabilization
#include <boost/test/included/unit_test.hpp>
#include <boost/filesystem.hpp>
#include <boost/filesystem/fstream.hpp>
#include <boost/asio/ip/address.hpp>
#include <openssl/rand.h>
#include <sys/stat.h>
#include <unistd.h>
#include <fstream>
#include <cerrno>

#include "wallet.h"
#include "walletdb.h"
#include "txdb.h"
#include "checkpoints.h"
#include "ui_interface.h"
#include "rpcaccess.h"
#include "secureconfig.h"

// The test binary does not link init.cpp or start any node/RPC threads.
CWallet* pwalletMain = NULL;
CClientUIInterface uiInterface;
bool fConfChange = false;
bool fEnforceCanonical = true;
unsigned int nNodeLifespan = 7;
unsigned int nDerivationMethodIndex = 0;
unsigned int nMinerSleep = 500;
bool fUseFastIndex = true;
Checkpoints::CPMode CheckpointsMode = Checkpoints::STRICT;
void Shutdown(void*) { throw std::runtime_error("Unexpected shutdown in offline tests"); }
void StartShutdown() { throw std::runtime_error("Unexpected shutdown in offline tests"); }
bool ClientAllowed(const boost::asio::ip::address& address);

static int failRandomCall = 0;
extern "C" int __real_RAND_bytes(unsigned char*, int);
extern "C" int __wrap_RAND_bytes(unsigned char* data, int length)
{
    if (failRandomCall > 0 && --failRandomCall == 0)
        return 0;
    return __real_RAND_bytes(data, length);
}

static boost::filesystem::path testDirectory;
struct TestEnvironment {
    TestEnvironment() {
        char path[] = "/tmp/freakchain-tests-XXXXXX";
        if (!mkdtemp(path))
            throw std::runtime_error("Cannot create isolated test directory");
        testDirectory = path;
        mapArgs["-datadir"] = path;
        mapArgs["-keypool"] = "2";
        mapArgs["-connect"] = "0";
        mapArgs["-listen"] = "0";
        mapArgs["-staking"] = "0";
        if (!bitdb.Open(GetDataDir()))
            throw std::runtime_error("Cannot open temporary Berkeley DB environment");
    }
    ~TestEnvironment() {
        failRandomCall = 0;
        { LOCK(cs_main); LimitOrphanBlocks(0, 0); }
        bitdb.Flush(true);
        boost::filesystem::remove_all(testDirectory);
    }
};
BOOST_GLOBAL_FIXTURE(TestEnvironment);

static std::string ReadFile(const boost::filesystem::path& path)
{
    std::ifstream in(path.string().c_str(), std::ios::binary);
    return std::string(std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>());
}

static void CreateWalletFile(const std::string& name)
{
    CWalletDB db(name, "cr+");
}

BOOST_AUTO_TEST_CASE(config_creation_is_private_exclusive_and_fails_closed)
{
    const boost::filesystem::path path = testDirectory / "generated.conf";
    std::string error;
    const mode_t previous = umask(022);
    bool created = CreateRPCConfig(path.string(), error);
    umask(previous);
    BOOST_REQUIRE(created);
    struct stat info;
    BOOST_REQUIRE_EQUAL(stat(path.string().c_str(), &info), 0);
    BOOST_CHECK_EQUAL(info.st_mode & 0777, 0600);
    const std::string original = ReadFile(path);
    BOOST_CHECK(original.find("rpcbind=127.0.0.1\n") != std::string::npos);
    BOOST_CHECK(!CreateRPCConfig(path.string(), error));
    BOOST_CHECK_EQUAL(ReadFile(path), original);
    const boost::filesystem::path link = testDirectory / "config-link";
    BOOST_REQUIRE_EQUAL(symlink(path.string().c_str(), link.string().c_str()), 0);
    BOOST_CHECK(!CreateRPCConfig(link.string(), error));
    BOOST_CHECK_EQUAL(ReadFile(path), original);
    const boost::filesystem::path failed = testDirectory / "rng-failed.conf";
    failRandomCall = 1;
    BOOST_CHECK(!CreateRPCConfig(failed.string(), error));
    BOOST_CHECK(!boost::filesystem::exists(failed));
    BOOST_CHECK(!error.empty());
}

BOOST_AUTO_TEST_CASE(local_checkpoint_preserves_default_rules_and_guards_reorganizations)
{
    struct Reset {
        ~Reset() { std::string ignored; Checkpoints::ConfigureLocalCheckpoint("", ignored); }
    } reset;
    std::string message;
    uint256 zero("01"), goodHash("02"), badHash("03"), tipHash("04");
    CBlockIndex genesis, good, bad, tip, fork;
    genesis.nHeight = 0; genesis.phashBlock = &zero;
    good.nHeight = bad.nHeight = 1;
    good.pprev = bad.pprev = &genesis;
    good.phashBlock = &goodHash; bad.phashBlock = &badHash;
    tip.nHeight = fork.nHeight = 2;
    tip.pprev = &good; fork.pprev = &bad;
    tip.phashBlock = fork.phashBlock = &tipHash;
    BOOST_REQUIRE(Checkpoints::ConfigureLocalCheckpoint("", message));
    BOOST_CHECK(Checkpoints::CheckLocalCheckpointReorg(&fork, &tip));
    BOOST_CHECK_EQUAL(Checkpoints::GetTotalBlocksEstimate(), 10000);
    BOOST_REQUIRE(Checkpoints::ConfigureLocalCheckpoint("1:" + goodHash.GetHex(), message));
    BOOST_CHECK(Checkpoints::CheckLocalCheckpoint(&genesis));
    BOOST_CHECK(Checkpoints::CheckLocalCheckpointBlock(goodHash, &genesis));
    BOOST_CHECK(!Checkpoints::CheckLocalCheckpointBlock(badHash, &genesis));
    BOOST_CHECK(Checkpoints::CheckLocalCheckpoint(&tip));
    BOOST_CHECK(!Checkpoints::CheckLocalCheckpoint(&fork));
    BOOST_CHECK(!Checkpoints::CheckLocalCheckpointReorg(&genesis, &tip));
    BOOST_CHECK(!Checkpoints::CheckLocalCheckpointReorg(&fork, &tip));
    fork.pprev = &good; // A competing branch after the anchor remains eligible.
    BOOST_CHECK(Checkpoints::CheckLocalCheckpointReorg(&fork, &tip));
    fork.pprev = &bad;
    {
        LOCK(cs_main);
        CTxDB db("cr+");
        uint256 sentinel("42"), stored;
        BOOST_REQUIRE(db.WriteHashBestChain(sentinel));
        CBlock block;
        BOOST_CHECK(!block.SetBestChain(db, &fork));
        BOOST_REQUIRE(db.ReadHashBestChain(stored));
        BOOST_CHECK(stored == sentinel); // Rejection precedes database changes.
        db.Close();
    }
    for (const std::string& invalid : {"-1:" + goodHash.GetHex(), "2147483648:" + goodHash.GetHex(),
                                      std::string("1:abcd"), "1:" + std::string(64, 'g'), "1:" + std::string(64, '0')})
        BOOST_CHECK(!Checkpoints::ConfigureLocalCheckpoint(invalid, message));
    BOOST_CHECK_EQUAL(Checkpoints::GetLocalCheckpointHeight(), 1);
    BOOST_CHECK_EQUAL(Checkpoints::GetTotalBlocksEstimate(), 10000);
}

BOOST_AUTO_TEST_CASE(local_checkpoint_keeps_initial_sync_active_until_anchor_is_reached)
{
    LOCK(cs_main);
    struct Reset {
        CBlockIndex* best = pindexBest;
        int height = nBestHeight;
        ~Reset() {
            pindexBest = best; nBestHeight = height;
            std::string ignored; Checkpoints::ConfigureLocalCheckpoint("", ignored);
        }
    } reset;
    CBlockIndex recent;
    recent.nHeight = nBestHeight = 12000;
    recent.nTime = GetTime();
    pindexBest = &recent;
    std::string message;
    BOOST_REQUIRE(Checkpoints::ConfigureLocalCheckpoint("", message));
    BOOST_CHECK(!IsInitialBlockDownload());
    BOOST_REQUIRE(Checkpoints::ConfigureLocalCheckpoint("811000:" + uint256("02").GetHex(), message));
    BOOST_CHECK(IsInitialBlockDownload());
    BOOST_CHECK_EQUAL(GetNumBlocksOfPeers(), 811000);
}

BOOST_AUTO_TEST_CASE(manual_bans_cover_ports_and_preserve_state_on_save_or_load_failure)
{
    std::string message;
    CNetAddr ip, invalid;
    BOOST_REQUIRE(ParseBanAddress("198.51.100.42", ip));
    BOOST_CHECK(!ParseBanAddress("pool.example", invalid));
    BOOST_CHECK(!ParseBanAddress("198.51.100.42:16555", invalid));
    BOOST_CHECK(!ParseBanAddress("198.51.100.0/24", invalid));
    BOOST_REQUIRE(ClearManualBans(message));
    CNode first(INVALID_SOCKET, CAddress(CService(ip, 1111)), "", true);
    CNode second(INVALID_SOCKET, CAddress(CService(ip, 2222)), "", true);
    {
        LOCK(cs_vNodes);
        vNodes.push_back(&first); vNodes.push_back(&second);
    }
    bool saved = UpdateManualBan(ip, GetTime() + 3600, message);
    {
        LOCK(cs_vNodes);
        vNodes.clear();
    }
    BOOST_REQUIRE(saved);
    BOOST_CHECK(first.fDisconnect && second.fDisconnect);
    BOOST_CHECK(CNode::IsBanned(CService(ip, 3333)));
    BOOST_CHECK(CNode::IsBanned(CNetAddr("::ffff:198.51.100.42", false)));
    const auto path = GetDataDir() / "manual-peer-bans.dat";
    const std::string original = ReadFile(path);
    failRandomCall = 1;
    BOOST_CHECK(!UpdateManualBan(ip, 0, message));
    failRandomCall = 0;
    BOOST_CHECK(CNode::IsBanned(ip));
    BOOST_CHECK_EQUAL(ReadFile(path), original);
    const auto preserved = GetDataDir() / "preserved-manual-bans.dat";
    boost::filesystem::rename(path, preserved);
    boost::filesystem::create_directory(path);
    BOOST_CHECK(!ClearManualBans(message));
    BOOST_CHECK(CNode::IsBanned(ip));
    BOOST_CHECK_EQUAL(ReadFile(preserved), original);
    boost::filesystem::remove(path);
    boost::filesystem::rename(preserved, path);
    { std::ofstream out(path.string().c_str()); out << "broken ban file\n"; }
    BOOST_CHECK(!LoadManualBans(message));
    BOOST_CHECK(CNode::IsBanned(ip));
    { std::ofstream out(path.string().c_str()); out << original; }
    BOOST_REQUIRE(LoadManualBans(message));
    BOOST_REQUIRE(UpdateManualBan(ip, 0, message));
    BOOST_CHECK(!CNode::IsBanned(ip));
    BOOST_REQUIRE(LoadManualBans(message));
    BOOST_CHECK(GetManualBans().empty());
    CNetAddr ipv6;
    BOOST_REQUIRE(ParseBanAddress("2001:4860::1234", ipv6));
    BOOST_REQUIRE(UpdateManualBan(ipv6, GetTime() + 3600, message));
    BOOST_CHECK(CNode::IsBanned(CService(ipv6, 16555)));
    BOOST_REQUIRE(ClearManualBans(message));
}

BOOST_AUTO_TEST_CASE(rpc_loopbacks_and_allowlist_do_not_confuse_ipv6)
{
    using boost::asio::ip::make_address;
    mapMultiArgs["-rpcallowip"].clear();
    const char* allowed[] = {"127.0.0.1", "127.1.2.3", "::1", "::ffff:127.0.0.1", "::127.0.0.1"};
    for (size_t i = 0; i < sizeof(allowed) / sizeof(*allowed); ++i)
        BOOST_CHECK_MESSAGE(ClientAllowed(make_address(allowed[i])), allowed[i]);
    const char* denied[] = {"0.0.0.1", "0.0.0.0", "::", "192.0.2.1", "::ffff:192.0.2.1", "2001:db8::1"};
    for (size_t i = 0; i < sizeof(denied) / sizeof(*denied); ++i)
        BOOST_CHECK_MESSAGE(!ClientAllowed(make_address(denied[i])), denied[i]);
    mapMultiArgs["-rpcallowip"].push_back("192.0.2.1");
    BOOST_CHECK(ClientAllowed(make_address("::ffff:192.0.2.1")));
    BOOST_CHECK(!ClientAllowed(make_address("192.0.2.2")));
    mapMultiArgs["-rpcallowip"].clear();
}

BOOST_AUTO_TEST_CASE(rpc_binding_defaults_stay_on_loopback)
{
    std::vector<std::string> requested;
    std::vector<boost::asio::ip::address> addresses;
    std::string error;
    mapMultiArgs["-rpcallowip"].push_back("192.0.2.*");
    BOOST_REQUIRE(RPCBindAddresses(requested, addresses, error));
    BOOST_REQUIRE_EQUAL(addresses.size(), 2U);
    BOOST_CHECK(addresses[0].is_loopback());
    BOOST_CHECK(addresses[1].is_loopback());
    requested.push_back("127.0.0.1");
    requested.push_back("127.0.0.1");
    BOOST_REQUIRE(RPCBindAddresses(requested, addresses, error));
    BOOST_CHECK_EQUAL(addresses.size(), 1U);
    requested.push_back("invalid-address");
    BOOST_CHECK(!RPCBindAddresses(requested, addresses, error));
    BOOST_CHECK(addresses.empty());
    mapMultiArgs["-rpcallowip"].clear();
}

BOOST_AUTO_TEST_CASE(wallet_rng_failures_leave_wallet_unencrypted)
{
    CWallet wallet("rng-wallet.dat");
    CreateWalletFile(wallet.strWalletFile);
    wallet.GenerateNewKey();
    const SecureString passphrase("synthetic-test-passphrase");
    for (int failure = 1; failure <= 2; ++failure) {
        failRandomCall = failure;
        BOOST_CHECK(!wallet.EncryptWallet(passphrase));
        failRandomCall = 0;
        BOOST_CHECK(!wallet.IsCrypted());
        BOOST_CHECK(wallet.mapMasterKeys.empty());
        BOOST_CHECK_EQUAL(wallet.nMasterKeyMaxID, 0U);
    }
}

BOOST_AUTO_TEST_CASE(wallet_encryption_roundtrip_preserves_private_key)
{
    const SecureString passphrase("synthetic-test-passphrase");
    CWallet wallet("roundtrip-wallet.dat");
    CreateWalletFile(wallet.strWalletFile);
    const CPubKey publicKey = wallet.GenerateNewKey();
    CKey original;
    BOOST_REQUIRE(wallet.GetKey(publicKey.GetID(), original));
    BOOST_REQUIRE(wallet.EncryptWallet(passphrase));
    BOOST_CHECK(wallet.IsCrypted());
    BOOST_CHECK(wallet.IsLocked());
    BOOST_CHECK(!wallet.Unlock(SecureString("wrong-passphrase")));
    BOOST_REQUIRE(wallet.Unlock(passphrase));
    CKey recovered;
    BOOST_REQUIRE(wallet.GetKey(publicKey.GetID(), recovered));
    BOOST_CHECK(original.GetPrivKey() == recovered.GetPrivKey());
    wallet.Lock();
    CWallet restored("roundtrip-wallet.dat");
    BOOST_REQUIRE(CWalletDB("roundtrip-wallet.dat").LoadWallet(&restored) == DB_LOAD_OK);
    BOOST_REQUIRE(restored.Unlock(passphrase));
    CKey fromDisk;
    BOOST_REQUIRE(restored.GetKey(publicKey.GetID(), fromDisk));
    BOOST_CHECK(original.GetPrivKey() == fromDisk.GetPrivKey());
}

static int FailPut(DB*, DB_TXN*, DBT*, DBT*, u_int32_t)
{
    return ENOSPC;
}

BOOST_AUTO_TEST_CASE(master_key_write_failure_preserves_wallet_and_allows_retry)
{
    CWallet wallet("write-failure-wallet.dat");
    CreateWalletFile(wallet.strWalletFile);
    const CPubKey publicKey = wallet.GenerateNewKey();
    CKey original;
    BOOST_REQUIRE(wallet.GetKey(publicKey.GetID(), original));
    DB* db = bitdb.mapDb.at(wallet.strWalletFile)->get_DB();
    const auto originalPut = db->put;
    db->put = FailPut;
    const SecureString passphrase("synthetic-test-passphrase");
    const bool encrypted = wallet.EncryptWallet(passphrase);
    db->put = originalPut;
    BOOST_CHECK(!encrypted);
    BOOST_CHECK(!wallet.IsCrypted());
    BOOST_CHECK(wallet.mapMasterKeys.empty());
    BOOST_CHECK_EQUAL(wallet.nMasterKeyMaxID, 0U);
    CWallet restored(wallet.strWalletFile);
    BOOST_REQUIRE(CWalletDB(wallet.strWalletFile).LoadWallet(&restored) == DB_LOAD_OK);
    CKey fromDisk;
    BOOST_REQUIRE(restored.GetKey(publicKey.GetID(), fromDisk));
    BOOST_CHECK(original.GetPrivKey() == fromDisk.GetPrivKey());
    BOOST_REQUIRE(wallet.EncryptWallet(passphrase));
    BOOST_REQUIRE(wallet.Unlock(passphrase));
    CKey recovered;
    BOOST_REQUIRE(wallet.GetKey(publicKey.GetID(), recovered));
    BOOST_CHECK(original.GetPrivKey() == recovered.GetPrivKey());
}

static int FailRename(DB_ENV*, DB_TXN*, const char*, const char*, const char*, u_int32_t)
{
    return ENOSPC;
}

BOOST_AUTO_TEST_CASE(wallet_rewrite_rolls_back_when_rename_fails)
{
    CWallet wallet("rollback-wallet.dat");
    CreateWalletFile(wallet.strWalletFile);
    const CPubKey publicKey = wallet.GenerateNewKey();
    DB_ENV* env = bitdb.dbenv.get_DB_ENV();
    const auto originalRename = env->dbrename;
    env->dbrename = FailRename;
    const bool rewritten = CDB::Rewrite("rollback-wallet.dat");
    env->dbrename = originalRename;
    BOOST_CHECK(!rewritten);
    BOOST_CHECK(boost::filesystem::exists(testDirectory / "rollback-wallet.dat"));
    BOOST_CHECK(boost::filesystem::exists(testDirectory / "rollback-wallet.dat.rewrite"));
    CWallet restored("rollback-wallet.dat");
    BOOST_REQUIRE(CWalletDB("rollback-wallet.dat").LoadWallet(&restored) == DB_LOAD_OK);
    CKey key;
    BOOST_CHECK(restored.GetKey(publicKey.GetID(), key));
    // A previous rewrite is retained, never silently overwritten on retry.
    const std::string prior = ReadFile(testDirectory / "rollback-wallet.dat.rewrite");
    BOOST_CHECK(!CDB::Rewrite("rollback-wallet.dat"));
    BOOST_CHECK_EQUAL(ReadFile(testDirectory / "rollback-wallet.dat.rewrite"), prior);
}

BOOST_AUTO_TEST_CASE(encryption_cleanup_failure_is_not_reported_as_success)
{
    CWallet wallet("cleanup-wallet.dat");
    CreateWalletFile(wallet.strWalletFile);
    wallet.GenerateNewKey();
    const boost::filesystem::path prior = testDirectory / "cleanup-wallet.dat.rewrite";
    { std::ofstream out(prior.string().c_str()); out << "preserve this previous recovery file"; }
    const std::string before = ReadFile(prior);
    BOOST_CHECK(!wallet.EncryptWallet(SecureString("synthetic-test-passphrase")));
    BOOST_CHECK(wallet.IsCrypted());
    BOOST_CHECK(wallet.IsLocked());
    BOOST_CHECK_EQUAL(ReadFile(prior), before);
}

BOOST_AUTO_TEST_CASE(index_version_mismatch_preserves_blocks_and_index)
{
    const boost::filesystem::path blocks = testDirectory / "blk0001.dat";
    { std::ofstream out(blocks.string().c_str()); out << "sentinel block data"; }
    for (int delta = -1; delta <= 1; delta += 2) {
        boost::filesystem::remove_all(testDirectory / "txleveldb");
        { CTxDB db("cr+"); BOOST_REQUIRE(db.WriteVersion(DATABASE_VERSION + delta)); db.Close(); }
        BOOST_CHECK_THROW(CTxDB incompatible("cr+"), std::runtime_error);
        BOOST_CHECK_EQUAL(ReadFile(blocks), "sentinel block data");
        BOOST_CHECK(boost::filesystem::exists(testDirectory / "txleveldb"));
    }
    boost::filesystem::remove_all(testDirectory / "txleveldb");
    { CTxDB db("cr+"); int version = 0; BOOST_CHECK(db.ReadVersion(version)); BOOST_CHECK_EQUAL(version, DATABASE_VERSION); db.Close(); }
}

BOOST_AUTO_TEST_CASE(orphan_cache_limits_preserve_ancestry_and_accounting)
{
    LOCK(cs_main);
    CBlock parent;
    parent.nTime = 1;
    CBlock child;
    child.nTime = 2;
    child.hashPrevBlock = parent.GetHash();
    BOOST_REQUIRE(AddOrphanBlock(parent));
    BOOST_REQUIRE(AddOrphanBlock(child));
    BOOST_CHECK(!AddOrphanBlock(child));
    BOOST_CHECK_EQUAL(LimitOrphanBlocks(1, 1024 * 1024), 1U);
    BOOST_CHECK(mapOrphanBlocks.count(parent.GetHash()));
    BOOST_CHECK(!mapOrphanBlocks.count(child.GetHash()));
    BOOST_CHECK_EQUAL(LimitOrphanBlocks(750, 0), 1U);
    BOOST_CHECK(mapOrphanBlocks.empty());
    BOOST_REQUIRE(AddOrphanBlock(child));
    EraseOrphanBlock(child.GetHash());
    BOOST_CHECK_EQUAL(LimitOrphanBlocks(0, 0), 0U);
    BOOST_REQUIRE(AddOrphanBlock(parent));
    BOOST_CHECK_EQUAL(LimitOrphanBlocks(750, 1024 * 1024), 0U);
    LimitOrphanBlocks(0, 0);
}
