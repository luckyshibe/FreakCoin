#!/usr/bin/env python3
"""Modernize the legacy Boost.Asio RPC calls in src/bitcoinrpc.cpp for Boost 1.71+.

The transformation is intentionally narrow and exact-match based. It updates
only APIs removed/changed by newer Boost.Asio and refuses to write unless every
expected legacy occurrence is present exactly as audited.
"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "src" / "bitcoinrpc.cpp"

REPLACEMENTS = [
    (
        "ip::tcp::resolver resolver(stream.get_io_service());",
        "ip::tcp::resolver resolver(stream.get_executor());",
        1,
    ),
    (
        "AcceptedConnectionImpl<Protocol>* conn = new AcceptedConnectionImpl<Protocol>(acceptor->get_io_service(), context, fUseSSL);",
        "AcceptedConnectionImpl<Protocol>* conn = new AcceptedConnectionImpl<Protocol>(static_cast<asio::io_service&>(acceptor->get_executor().context()), context, fUseSSL);",
        1,
    ),
    (
        "ssl::context context(io_service, ssl::context::sslv23);",
        "ssl::context context(ssl::context::sslv23);",
        2,
    ),
    (
        "SSL_CTX_set_cipher_list(context.impl(), strCiphers.c_str());",
        "SSL_CTX_set_cipher_list(context.native_handle(), strCiphers.c_str());",
        1,
    ),
]


def die(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    if not PATH.exists():
        die(f"cannot find {PATH}")

    text = PATH.read_text()
    out = text

    for old, new, expected in REPLACEMENTS:
        found = out.count(old)
        if found != expected:
            die(f"expected {expected} occurrence(s) of {old!r}, found {found}; no changes made")
        out = out.replace(old, new)

    forbidden = [
        ".get_io_service()",
        "context.impl()",
        "ssl::context context(io_service, ssl::context::sslv23)",
    ]
    for marker in forbidden:
        if marker in out:
            die(f"legacy Boost.Asio marker remains after transformation: {marker!r}; no changes made")

    required = [
        "resolver(stream.get_executor())",
        "acceptor->get_executor().context()",
        "context.native_handle()",
        "ssl::context context(ssl::context::sslv23);",
    ]
    for marker in required:
        if marker not in out:
            die(f"post-transform marker missing: {marker!r}; no changes made")

    PATH.write_text(out)
    print(f"Updated {PATH}")
    print("Converted legacy Boost.Asio RPC APIs for Boost 1.71+")
    print("Safety checks passed: removed get_io_service(), context.impl(), and old ssl::context constructors")
    print("Review with: git diff -- src/bitcoinrpc.cpp")


if __name__ == "__main__":
    main()
