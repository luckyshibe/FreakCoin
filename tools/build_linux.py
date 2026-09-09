#!/usr/bin/env python3
"""Preflight and build the Linux daemon; optionally run isolated regression tests.

Uses the existing makefile's BOOST_*, BDB_*, OPENSSL_*, CXXFLAGS, and LDFLAGS
environment settings. Installs nothing and never starts a production node.
"""
import argparse
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = (
    "BOOST_INCLUDE_PATH", "BOOST_LIB_PATH", "BOOST_LIB_SUFFIX",
    "BDB_INCLUDE_PATH", "BDB_LIB_PATH", "BDB_LIB_SUFFIX",
    "OPENSSL_INCLUDE_PATH", "OPENSSL_LIB_PATH", "CXXFLAGS", "LDFLAGS",
)
PROBE = r'''
#include <iostream>
#include <db_cxx.h>
#include <boost/version.hpp>
#include <boost/asio/ssl.hpp>
#include <boost/filesystem.hpp>
#include <boost/thread.hpp>
#include <boost/chrono.hpp>
#include <boost/program_options.hpp>
#include <openssl/crypto.h>
#include <openssl/rand.h>
#if DB_VERSION_MAJOR != FREAK_BDB_MAJOR || DB_VERSION_MINOR != FREAK_BDB_MINOR
#error Berkeley DB headers do not match --bdb-version. Check BDB_INCLUDE_PATH.
#endif
#if OPENSSL_VERSION_NUMBER < 0x10100000L
#error OpenSSL 1.1 or later is required by this source.
#endif
int main() {
    int major = 0, minor = 0, patch = 0;
    DbEnv::version(&major, &minor, &patch);
    if (major != DB_VERSION_MAJOR || minor != DB_VERSION_MINOR) {
        std::cerr << "Berkeley DB header/library mismatch: headers "
                  << DB_VERSION_MAJOR << '.' << DB_VERSION_MINOR
                  << "; library " << major << '.' << minor << '\n';
        return 2;
    }
    boost::asio::io_context io;
    boost::asio::ssl::context ssl(boost::asio::ssl::context::sslv23);
    boost::thread thread([] {}); thread.join();
    boost::program_options::options_description options("probe");
    if (!boost::filesystem::exists(".")) return 3;
    (void)boost::chrono::steady_clock::now();
    unsigned char random[32];
    if (RAND_bytes(random, sizeof(random)) != 1) return 4;
    std::cout << "Boost " << BOOST_LIB_VERSION << "; Berkeley DB "
              << major << '.' << minor << '.' << patch << "; "
              << OpenSSL_version(OPENSSL_VERSION) << '\n';
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bdb-version", choices=("4.8", "5.3"), required=True,
                        help="match the Berkeley DB version used by the existing wallet environment")
    parser.add_argument("--check", action="store_true", help="build and run the offline regression suite")
    parser.add_argument("--preflight-only", action="store_true", help="check tools, headers, linking and library versions")
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    cxx = shlex.split(os.environ.get("CXX", "g++"))
    if not cxx or not shutil.which(cxx[0]) or not shutil.which("make"):
        parser.exit(1, "A C++ compiler and make are required. No build was started.\n")
    settings = {name: os.environ[name] for name in SETTINGS if name in os.environ}
    settings.setdefault("BDB_LIB_SUFFIX", "-" + args.bdb_version)
    if "BDB_INCLUDE_PATH" not in settings:
        for candidate in ("/usr/include/db" + args.bdb_version,
                          "/usr/local/BerkeleyDB." + args.bdb_version + "/include"):
            if (Path(candidate) / "db_cxx.h").is_file():
                settings["BDB_INCLUDE_PATH"] = candidate
                break
    includes = ["-I" + settings[name] for name in SETTINGS if name.endswith("_INCLUDE_PATH") and settings.get(name)]
    libraries = ["-L" + settings[name] for name in SETTINGS if name.endswith("_LIB_PATH") and settings.get(name)]
    suffix = settings.get("BOOST_LIB_SUFFIX", "")
    libs = ["-lboost_" + name + suffix for name in ("filesystem", "program_options", "thread", "chrono")]
    libs += ["-ldb_cxx" + settings["BDB_LIB_SUFFIX"], "-lssl", "-lcrypto", "-lpthread", "-ldl", "-lz"]
    print("Checking the compiler, dependency headers, linking, and runtime versions...", flush=True)
    with tempfile.TemporaryDirectory(prefix="freakchain-preflight-") as directory:
        source = Path(directory) / "probe.cpp"
        binary = Path(directory) / "probe"
        source.write_text(PROBE)
        major, minor = args.bdb_version.split(".")
        command = cxx + ["-std=gnu++17", "-pthread", "-DFREAK_BDB_MAJOR=" + major,
                         "-DFREAK_BDB_MINOR=" + minor] + includes
        command += shlex.split(settings.get("CXXFLAGS", "")) + [str(source), "-o", str(binary)]
        command += libraries + shlex.split(settings.get("LDFLAGS", "")) + libs
        result = subprocess.run(command, cwd=ROOT)
        if result.returncode:
            print("Preflight failed. Set BOOST_INCLUDE_PATH/BOOST_LIB_PATH, BDB_INCLUDE_PATH/BDB_LIB_PATH, or OPENSSL_INCLUDE_PATH/OPENSSL_LIB_PATH to the working dependencies. No project build was started.", file=sys.stderr)
            return result.returncode
        result = subprocess.run([str(binary)], cwd=ROOT)
        if result.returncode:
            print("Dependency runtime check failed. Verify the selected Berkeley DB version and the loader's library paths. No project build was started.", file=sys.stderr)
            return result.returncode
    if args.preflight_only:
        return 0
    # Make does not track changes to library selection in command-line flags.
    # Force every object to rebuild on the first selection and every BDB change.
    # Record the selection only after a successful build so failed attempts retry.
    stamp = ROOT / "src/obj/bdb-version"
    rebuild = not stamp.is_file() or stamp.read_text().strip() != args.bdb_version
    if rebuild and stamp.exists():
        stamp.unlink()
    (ROOT / "src/obj/zerocoin").mkdir(parents=True, exist_ok=True)
    command = ["make", "-f", "makefile.unix", "-j" + str(args.jobs), "all"]
    if rebuild:
        command.append("-B")
    if args.check:
        command.append("check")
    command += ["USE_UPNP=-", "CXX=" + shlex.join(cxx)]
    command += [name + "=" + value for name, value in settings.items()]
    print("Building the daemon" + (" and running offline tests" if args.check else "") + "...", flush=True)
    result = subprocess.run(command, cwd=ROOT / "src")
    if result.returncode == 0:
        stamp.write_text(args.bdb_version + "\n")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
