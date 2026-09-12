// Copyright (c) 2009-2012 Bitcoin Developers
// Distributed under the MIT/X11 software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#include "net.h"
#include "bitcoinrpc.h"
#include "alert.h"
#include "wallet.h"
#include "db.h"
#include "walletdb.h"
#include <boost/assign/list_of.hpp>

using namespace json_spirit;
using namespace std;

// Runtime -addnode list. Defined in net.cpp and shared with the
// added-connections thread so RPC changes take effect without a restart.
extern vector<string> vAddedNodes;
extern CCriticalSection cs_vAddedNodes;

Value getconnectioncount(const Array& params, bool fHelp)
{
    if (fHelp || params.size() != 0)
        throw runtime_error(
            "getconnectioncount\n"
            "Returns the number of connections to other nodes.");

    LOCK(cs_vNodes);
    return (int)vNodes.size();
}

static void CopyNodeStats(std::vector<CNodeStats>& vstats)
{
    vstats.clear();

    LOCK(cs_vNodes);
    vstats.reserve(vNodes.size());
    BOOST_FOREACH(CNode* pnode, vNodes) {
        CNodeStats stats;
        pnode->copyStats(stats);
        vstats.push_back(stats);
    }
}

Value getpeerinfo(const Array& params, bool fHelp)
{
    if (fHelp || params.size() != 0)
        throw runtime_error(
            "getpeerinfo\n"
            "Returns data about each connected network node.");

    vector<CNodeStats> vstats;
    CopyNodeStats(vstats);

    Array ret;

    BOOST_FOREACH(const CNodeStats& stats, vstats) {
        Object obj;

        obj.push_back(Pair("addr", stats.addrName));
        obj.push_back(Pair("services", strprintf("%08"PRIx64, stats.nServices)));
        obj.push_back(Pair("lastsend", (int64_t)stats.nLastSend));
        obj.push_back(Pair("lastrecv", (int64_t)stats.nLastRecv));
        obj.push_back(Pair("conntime", (int64_t)stats.nTimeConnected));
        obj.push_back(Pair("version", stats.nVersion));
        obj.push_back(Pair("subver", stats.strSubVer));
        obj.push_back(Pair("inbound", stats.fInbound));
        obj.push_back(Pair("startingheight", stats.nStartingHeight));
        obj.push_back(Pair("banscore", stats.nMisbehavior));

        ret.push_back(obj);
    }

    return ret;
}

Value setban(const Array& params, bool fHelp)
{
    if (fHelp || params.size() < 2 || params.size() > 3)
        throw runtime_error(
            "setban <ip> <add|remove> [seconds=86400]\n"
            "Add or remove a persistent manual IP ban. All P2P ports are covered.\n"
            "Use a numeric IPv4 or IPv6 address, without a port or subnet.\n"
            "Adding schedules matching peers for disconnection. Duration: 1 second to 10 years.\n"
            "This controls connections only; it does not select a chain.");
    RPCTypeCheck(params, boost::assign::list_of(str_type)(str_type)(int_type));
    CNetAddr address;
    if (!ParseBanAddress(params[0].get_str(), address))
        throw JSONRPCError(RPC_INVALID_PARAMETER, "Expected a numeric IP address without a port or subnet");
    const std::string action = params[1].get_str();
    int64_t until = 0;
    if (action == "add") {
        const int64_t duration = params.size() == 3 ? params[2].get_int64() : 86400;
        if (duration <= 0 || duration > int64_t(10) * 365 * 24 * 60 * 60)
            throw JSONRPCError(RPC_INVALID_PARAMETER, "Ban duration must be between 1 second and 10 years");
        until = GetTime() + duration;
    } else if (action != "remove" || params.size() != 2) {
        throw JSONRPCError(RPC_INVALID_PARAMETER, "Use add [seconds] or remove");
    }
    std::string message;
    if (!UpdateManualBan(address, until, message))
        throw JSONRPCError(RPC_MISC_ERROR, message);
    return Value::null;
}

Value listbanned(const Array& params, bool fHelp)
{
    if (fHelp || !params.empty())
        throw runtime_error("listbanned\nList active persistent manual IP bans. Automatic misbehavior bans are separate.");
    Array result;
    for (const auto& ban : GetManualBans()) {
        Object entry;
        entry.push_back(Pair("address", ban.first.ToStringIP()));
        entry.push_back(Pair("banned_until", ban.second));
        entry.push_back(Pair("ban_reason", "manually added"));
        result.push_back(entry);
    }
    return result;
}

Value clearbanned(const Array& params, bool fHelp)
{
    if (fHelp || !params.empty())
        throw runtime_error("clearbanned\nRemove all persistent manual bans. Automatic misbehavior bans are unchanged.");
    std::string message;
    if (!ClearManualBans(message))
        throw JSONRPCError(RPC_MISC_ERROR, message);
    return Value::null;
}

Value addnode(const Array& params, bool fHelp)
{
    string strCommand = "add";
    if (params.size() == 2)
        strCommand = params[1].get_str();

    if (fHelp || params.size() < 1 || params.size() > 2 ||
        (strCommand != "onetry" && strCommand != "add" && strCommand != "remove"))
        throw runtime_error(
            "addnode <node> [add|remove|onetry]\n"
            "Add or remove <node> from the live addnode list, or try it once.\n"
            "With no action specified, 'add' is used. A leading '=' before <node> is accepted.");

    string strNode = params[0].get_str();
    if (!strNode.empty() && strNode[0] == '=')
        strNode.erase(0, 1);
    if (strNode.empty())
        throw JSONRPCError(RPC_INVALID_PARAMETER, "Node address cannot be empty");

    if (strCommand == "onetry")
    {
        AddOneShot(strNode);
        return Value::null;
    }

    {
        LOCK(cs_vAddedNodes);
        vector<string>::iterator it = vAddedNodes.begin();
        for (; it != vAddedNodes.end(); ++it)
            if (strNode == *it)
                break;

        if (strCommand == "add")
        {
            if (it != vAddedNodes.end())
                throw JSONRPCError(RPC_INVALID_PARAMETER, "Error: Node already added");
            vAddedNodes.push_back(strNode);
        }
        else
        {
            if (it == vAddedNodes.end())
                throw JSONRPCError(RPC_INVALID_PARAMETER, "Error: Node has not been added");
            vAddedNodes.erase(it);
        }
    }

    // Do not wait for the two-minute persistent retry cycle when adding a node.
    if (strCommand == "add")
        AddOneShot(strNode);

    return Value::null;
}
 
// ppcoin: send alert.  
// There is a known deadlock situation with ThreadMessageHandler
// ThreadMessageHandler: holds cs_vSend and acquiring cs_main in SendMessages()
// ThreadRPCServer: holds cs_main and acquiring cs_vSend in alert.RelayTo()/PushMessage()/BeginMessage()
Value sendalert(const Array& params, bool fHelp)
{
    if (fHelp || params.size() < 6)
        throw runtime_error(
            "sendalert <message> <privatekey> <minver> <maxver> <priority> <id> [cancelupto]\n"
            "<message> is the alert text message\n"
            "<privatekey> is hex string of alert master private key\n"
            "<minver> is the minimum applicable internal client version\n"
            "<maxver> is the maximum applicable internal client version\n"
            "<priority> is integer priority number\n"
            "<id> is the alert id\n"
            "[cancelupto] cancels all alert id's up to this number\n"
            "Returns true or false.");

    CAlert alert;
    CKey key;

    alert.strStatusBar = params[0].get_str();
    alert.nMinVer = params[2].get_int();
    alert.nMaxVer = params[3].get_int();
    alert.nPriority = params[4].get_int();
    alert.nID = params[5].get_int();
    if (params.size() > 6)
        alert.nCancel = params[6].get_int();
    alert.nVersion = PROTOCOL_VERSION;
    alert.nRelayUntil = GetAdjustedTime() + 365*24*60*60;
    alert.nExpiration = GetAdjustedTime() + 365*24*60*60;

    CDataStream sMsg(SER_NETWORK, PROTOCOL_VERSION);
    sMsg << (CUnsignedAlert)alert;
    alert.vchMsg = vector<unsigned char>(sMsg.begin(), sMsg.end());

    vector<unsigned char> vchPrivKey = ParseHex(params[1].get_str());
    key.SetPrivKey(CPrivKey(vchPrivKey.begin(), vchPrivKey.end())); // if key is not correct openssl may crash
    if (!key.Sign(Hash(alert.vchMsg.begin(), alert.vchMsg.end()), alert.vchSig))
        throw runtime_error(
            "Unable to sign alert, check private key?\n");  
    if(!alert.ProcessAlert()) 
        throw runtime_error(
            "Failed to process alert.\n");
    // Relay alert
    {
        LOCK(cs_vNodes);
        BOOST_FOREACH(CNode* pnode, vNodes)
            alert.RelayTo(pnode);
    }

    Object result;
    result.push_back(Pair("strStatusBar", alert.strStatusBar));
    result.push_back(Pair("nVersion", alert.nVersion));
    result.push_back(Pair("nMinVer", alert.nMinVer));
    result.push_back(Pair("nMaxVer", alert.nMaxVer));
    result.push_back(Pair("nPriority", alert.nPriority));
    result.push_back(Pair("nID", alert.nID));
    if (alert.nCancel > 0)
        result.push_back(Pair("nCancel", alert.nCancel));
    return result;
}

Value getnettotals(const Array& params, bool fHelp)
{
    if (fHelp || params.size() > 0)
        throw runtime_error(
            "getnettotals\n"
            "Returns information about network traffic, including bytes in, bytes out,\n"
            "and current time.");

    Object obj;
    obj.push_back(Pair("totalbytesrecv", static_cast< boost::uint64_t>(CNode::GetTotalBytesRecv())));
    obj.push_back(Pair("totalbytessent", static_cast<boost::uint64_t>(CNode::GetTotalBytesSent())));
    obj.push_back(Pair("timemillis", static_cast<boost::int64_t>(GetTimeMillis())));
    return obj;
}
