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
            throw std::runtime_error("Cannot open temporary BDB 4.8 environment");
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
