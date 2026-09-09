#ifndef FREAKCHAIN_RPCACCESS_H
#define FREAKCHAIN_RPCACCESS_H

#include <boost/asio/ip/address.hpp>
#include <string>
#include <vector>

inline boost::asio::ip::address NormalizeRPCAddress(const boost::asio::ip::address& address)
{
    using namespace boost::asio::ip;
    if (!address.is_v6() || address.to_v6().is_loopback() || address.to_v6().is_unspecified())
        return address;
    const address_v6::bytes_type bytes = address.to_v6().to_bytes();
    bool mapped = true;
    bool compatible = true;
    for (int i = 0; i < 10; ++i)
        if (bytes[i] != 0)
            mapped = false;
    mapped = mapped && bytes[10] == 0xff && bytes[11] == 0xff;
    for (int i = 0; i < 12; ++i)
        if (bytes[i] != 0)
            compatible = false;
    if (!mapped && !compatible)
        return address;
    address_v4::bytes_type v4 = {{bytes[12], bytes[13], bytes[14], bytes[15]}};
    return address_v4(v4);
}

inline bool RPCBindAddresses(const std::vector<std::string>& requested,
                             std::vector<boost::asio::ip::address>& addresses,
                             std::string& error)
{
    using namespace boost::asio::ip;
    addresses.clear();
    error.clear();
    if (requested.empty()) {
        addresses.push_back(address_v6::loopback());
        addresses.push_back(address_v4::loopback());
        return true;
    }
    for (size_t i = 0; i < requested.size(); ++i) {
        boost::system::error_code ec;
        address value = make_address(requested[i], ec);
        if (ec) {
            addresses.clear();
            error = "Invalid -rpcbind address: " + requested[i] + ". Use a numeric IP address and -rpcport for the port.";
            return false;
        }
        bool duplicate = false;
        for (size_t j = 0; j < addresses.size(); ++j)
            duplicate = duplicate || addresses[j] == value;
        if (!duplicate)
            addresses.push_back(value);
    }
    return true;
}

#endif
