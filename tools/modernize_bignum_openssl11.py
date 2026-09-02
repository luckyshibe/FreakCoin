#!/usr/bin/env python3
"""Modernize src/bignum.h for OpenSSL 1.1+ opaque BIGNUM.

This is intentionally conservative. It only rewrites the exact legacy
CBigNum class prologue audited in FreakCoin, then replaces uses of `this`
with the owned BIGNUM pointer only on lines containing OpenSSL BN_* calls.
It refuses to write the file if the expected legacy source shape is not
present or if legacy BN_init / BN_*(...this...) uses remain afterward.
"""

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "src" / "bignum.h"

OLD = r'''/** C++ wrapper for BIGNUM (OpenSSL bignum) */
class CBigNum : public BIGNUM
{
public:
    CBigNum()
    {
        BN_init(this);
    }

    CBigNum(const CBigNum& b)
    {
        BN_init(this);
        if (!BN_copy(this, &b))
        {
            BN_clear_free(this);
            throw bignum_error("CBigNum::CBigNum(const CBigNum&) : BN_copy failed");
        }
    }

    CBigNum& operator=(const CBigNum& b)
    {
        if (!BN_copy(this, &b))
            throw bignum_error("CBigNum::operator= : BN_copy failed");
        return (*this);
    }

    ~CBigNum()
    {
        BN_clear_free(this);
    }

    //CBigNum(char n) is not portable.  Use 'signed char' or 'unsigned char'.
    CBigNum(signed char n)        { BN_init(this); if (n >= 0) setulong(n); else setint64(n); }
    CBigNum(short n)              { BN_init(this); if (n >= 0) setulong(n); else setint64(n); }
    CBigNum(int n)                { BN_init(this); if (n >= 0) setulong(n); else setint64(n); }
    CBigNum(long n)               { BN_init(this); if (n >= 0) setulong(n); else setint64(n); }
    CBigNum(long long n)          { BN_init(this); setint64(n); }
    CBigNum(unsigned char n)      { BN_init(this); setulong(n); }
    CBigNum(unsigned short n)     { BN_init(this); setulong(n); }
    CBigNum(unsigned int n)       { BN_init(this); setulong(n); }
    CBigNum(unsigned long n)      { BN_init(this); setulong(n); }
    CBigNum(unsigned long long n) { BN_init(this); setuint64(n); }
    explicit CBigNum(uint256 n)   { BN_init(this); setuint256(n); }

    explicit CBigNum(const std::vector<unsigned char>& vch)
    {
        BN_init(this);
        setvch(vch);
    }
'''

NEW = r'''/** C++ wrapper for BIGNUM (OpenSSL bignum) */
class CBigNum
{
private:
    BIGNUM* bn;

    void init()
    {
        bn = BN_new();
        if (bn == NULL)
            throw bignum_error("CBigNum : BN_new() returned NULL");
    }

public:
    // Preserve the legacy call style used throughout this codebase:
    // BN_cmp(&a, &b), BN_add(&r, &a, &b), etc. With opaque BIGNUM in
    // OpenSSL 1.1+, taking the address of a CBigNum returns its owned BIGNUM.
    BIGNUM* operator&() { return bn; }
    const BIGNUM* operator&() const { return bn; }

    CBigNum()
    {
        init();
    }

    CBigNum(const CBigNum& b)
    {
        init();
        if (!BN_copy(bn, &b))
        {
            BN_clear_free(bn);
            bn = NULL;
            throw bignum_error("CBigNum::CBigNum(const CBigNum&) : BN_copy failed");
        }
    }

    CBigNum& operator=(const CBigNum& b)
    {
        if (!BN_copy(bn, &b))
            throw bignum_error("CBigNum::operator= : BN_copy failed");
        return (*this);
    }

    ~CBigNum()
    {
        if (bn != NULL)
            BN_clear_free(bn);
    }

    //CBigNum(char n) is not portable.  Use 'signed char' or 'unsigned char'.
    CBigNum(signed char n)        { init(); if (n >= 0) setulong(n); else setint64(n); }
    CBigNum(short n)              { init(); if (n >= 0) setulong(n); else setint64(n); }
    CBigNum(int n)                { init(); if (n >= 0) setulong(n); else setint64(n); }
    CBigNum(long n)               { init(); if (n >= 0) setulong(n); else setint64(n); }
    CBigNum(long long n)          { init(); setint64(n); }
    CBigNum(unsigned char n)      { init(); setulong(n); }
    CBigNum(unsigned short n)     { init(); setulong(n); }
    CBigNum(unsigned int n)       { init(); setulong(n); }
    CBigNum(unsigned long n)      { init(); setulong(n); }
    CBigNum(unsigned long long n) { init(); setuint64(n); }
    explicit CBigNum(uint256 n)   { init(); setuint256(n); }

    explicit CBigNum(const std::vector<unsigned char>& vch)
    {
        init();
        setvch(vch);
    }
'''


def die(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    if not PATH.exists():
        die(f"cannot find {PATH}")

    text = PATH.read_text()

    if OLD not in text:
        if "class CBigNum\n{" in text and "BIGNUM* bn;" in text:
            die("bignum.h already appears to be modernized; refusing to run twice")
        die("expected legacy CBigNum prologue was not found; no changes made")

    if text.count(OLD) != 1:
        die("legacy CBigNum prologue did not occur exactly once; no changes made")

    out = text.replace(OLD, NEW, 1)

    # Inside member functions, old code passes `this` directly to BN_* APIs.
    # Every such occurrence in this audited file is on one physical line.
    lines = []
    changed_bn_this = 0
    for line in out.splitlines(keepends=True):
        if "BN_" in line and re.search(r"\bthis\b", line):
            new_line, count = re.subn(r"\bthis\b", "bn", line)
            changed_bn_this += count
            line = new_line
        lines.append(line)
    out = "".join(lines)

    # OpenSSL 1.1+ no longer supports stack/inherited BIGNUM initialization.
    if "BN_init(" in out:
        die("BN_init remains after transformation; no changes made")

    # No BN_* invocation should still receive the C++ `this` pointer.
    leftovers = [
        line.strip()
        for line in out.splitlines()
        if "BN_" in line and re.search(r"\bthis\b", line)
    ]
    if leftovers:
        die("BN_* calls still reference `this`: " + " | ".join(leftovers[:5]))

    required = [
        "class CBigNum\n{",
        "BIGNUM* bn;",
        "bn = BN_new();",
        "BIGNUM* operator&() { return bn; }",
        "const BIGNUM* operator&() const { return bn; }",
        "BN_clear_free(bn);",
    ]
    for marker in required:
        if marker not in out:
            die(f"post-transform safety marker missing: {marker!r}")

    # This count is deliberately checked so a future source change cannot
    # silently make the transform incomplete. The legacy constructor block
    # is replaced as a unit; these are the remaining BN_* argument uses.
    EXPECTED_BN_THIS_REPLACEMENTS = 40
    if changed_bn_this != EXPECTED_BN_THIS_REPLACEMENTS:
        die(
            f"expected {EXPECTED_BN_THIS_REPLACEMENTS} BN_* uses of `this`, "
            f"found {changed_bn_this}; no changes made"
        )

    PATH.write_text(out)
    print(f"Updated {PATH}")
    print(f"Converted {changed_bn_this} BN_* uses of `this` to the owned BIGNUM pointer")
    print("Safety checks passed: no BN_init calls and no BN_* calls using `this` remain")
    print("Review with: git diff -- src/bignum.h")


if __name__ == "__main__":
    main()
