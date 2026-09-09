// Copyright (c) 2012 The Bitcoin developers
// Distributed under the MIT/X11 software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.
#include <string>

#include "version.h"

// Name of client reported in the 'version' message. Report the same name
// for both bitcoind and bitcoin-qt, to make it harder for attackers to
// target servers or GUI users specifically.
const std::string CLIENT_NAME("FreakChain");

// Client version number
#define CLIENT_VERSION_SUFFIX   ""


// Generated build information identifies the actual source commit. Source
// exports without that information deliberately report an unknown build.

// First, include build.h if requested
#ifdef HAVE_BUILD_INFO
#    include "build.h"
#endif

#define BUILD_DESC_FROM_COMMIT(maj,min,rev,build,commit) \
    "v" DO_STRINGIZE(maj) "." DO_STRINGIZE(min) "." DO_STRINGIZE(rev) "." DO_STRINGIZE(build) "-g" commit

#define BUILD_DESC_FROM_UNKNOWN(maj,min,rev,build) \
    "v" DO_STRINGIZE(maj) "." DO_STRINGIZE(min) "." DO_STRINGIZE(rev) "." DO_STRINGIZE(build) "-unk"

#ifndef BUILD_DESC
#    ifdef BUILD_COMMIT
#        define BUILD_DESC BUILD_DESC_FROM_COMMIT(CLIENT_VERSION_MAJOR, CLIENT_VERSION_MINOR, CLIENT_VERSION_REVISION, CLIENT_VERSION_BUILD, BUILD_COMMIT)
#    else
#        define BUILD_DESC BUILD_DESC_FROM_UNKNOWN(CLIENT_VERSION_MAJOR, CLIENT_VERSION_MINOR, CLIENT_VERSION_REVISION, CLIENT_VERSION_BUILD)
#    endif
#endif

#ifndef BUILD_DATE
#    define BUILD_DATE __DATE__ ", " __TIME__
#endif

const std::string CLIENT_BUILD(BUILD_DESC CLIENT_VERSION_SUFFIX);
const std::string CLIENT_DATE(BUILD_DATE);
