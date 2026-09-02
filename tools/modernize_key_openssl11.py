#!/usr/bin/env python3
"""Modernize src/key.cpp ECDSA_SIG access for OpenSSL 1.1+.

Conservative source transform: only exact audited FreakCoin blocks are changed.
The script is idempotent enough to refuse or skip already-modernized sections.
"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
KEY = ROOT / "src" / "key.cpp"
BIGNUM = ROOT / "src" / "bignum.h"


def die(msg):
    print("ERROR: " + msg, file=sys.stderr)
    raise SystemExit(1)


def replace_exact(text, old, new, label):
    count = text.count(old)
    if count != 1:
        die("%s: expected exact source block once, found %d; no changes written" % (label, count))
    return text.replace(old, new, 1)


def main():
    key = KEY.read_text()
    bn = BIGNUM.read_text()

    # Fix the one name-shadowing case produced by the first CBigNum transform:
    # ToString() has a local CBigNum named `bn`, so BN_is_negative(bn) is wrong.
    if "if (BN_is_negative(this->bn))" not in bn:
        if bn.count("if (BN_is_negative(bn))") != 1:
            die("bignum.h: expected the ToString BN_is_negative shadowing line once")
        bn = bn.replace("if (BN_is_negative(bn))", "if (BN_is_negative(this->bn))", 1)

    # ECDSA_SIG became opaque in OpenSSL 1.1. Use get0/set0 accessors.
    old = """    const EC_GROUP *group = EC_KEY_get0_group(eckey);\n    if ((ctx = BN_CTX_new()) == NULL) { ret = -1; goto err; }\n"""
    new = """    const EC_GROUP *group = EC_KEY_get0_group(eckey);\n    const BIGNUM *sig_r = NULL;\n    const BIGNUM *sig_s = NULL;\n    ECDSA_SIG_get0(ecsig, &sig_r, &sig_s);\n    if (sig_r == NULL || sig_s == NULL) return -1;\n    if ((ctx = BN_CTX_new()) == NULL) { ret = -1; goto err; }\n"""
    if "ECDSA_SIG_get0(ecsig, &sig_r, &sig_s);" not in key:
        key = replace_exact(key, old, new, "recover accessor setup")

    replacements = {
        "BN_add(x, x, ecsig->r)": "BN_add(x, x, sig_r)",
        "BN_mod_inverse(rr, ecsig->r, order, ctx)": "BN_mod_inverse(rr, sig_r, order, ctx)",
        "BN_mod_mul(sor, ecsig->s, rr, order, ctx)": "BN_mod_mul(sor, sig_s, rr, order, ctx)",
    }
    for old_expr, new_expr in replacements.items():
        if old_expr in key:
            if key.count(old_expr) != 1:
                die("unexpected duplicate expression: " + old_expr)
            key = key.replace(old_expr, new_expr, 1)

    old = """    BN_rshift1(halforder, order);\n    if (BN_cmp(sig->s, halforder) > 0) {\n        // enforce low S values, by negating the value (modulo the order) if above order/2.\n        BN_sub(sig->s, order, sig->s);\n    }\n"""
    new = """    BN_rshift1(halforder, order);\n    const BIGNUM *sig_r = NULL;\n    const BIGNUM *sig_s = NULL;\n    ECDSA_SIG_get0(sig, &sig_r, &sig_s);\n    if (BN_cmp(sig_s, halforder) > 0) {\n        // Enforce low S without accessing opaque ECDSA_SIG internals.\n        BIGNUM *new_r = BN_dup(sig_r);\n        BIGNUM *new_s = BN_new();\n        if (new_r == NULL || new_s == NULL || !BN_sub(new_s, order, sig_s)) {\n            if (new_r != NULL) BN_free(new_r);\n            if (new_s != NULL) BN_free(new_s);\n            BN_CTX_end(ctx);\n            BN_CTX_free(ctx);\n            ECDSA_SIG_free(sig);\n            return false;\n        }\n        if (!ECDSA_SIG_set0(sig, new_r, new_s)) {\n            BN_free(new_r);\n            BN_free(new_s);\n            BN_CTX_end(ctx);\n            BN_CTX_free(ctx);\n            ECDSA_SIG_free(sig);\n            return false;\n        }\n    }\n"""
    if "BN_cmp(sig->s, halforder)" in key:
        key = replace_exact(key, old, new, "Sign low-S normalization")

    old = """    vchSig.clear();\n    vchSig.resize(65,0);\n    int nBitsR = BN_num_bits(sig->r);\n    int nBitsS = BN_num_bits(sig->s);\n"""
    new = """    vchSig.clear();\n    vchSig.resize(65,0);\n    const BIGNUM *sig_r = NULL;\n    const BIGNUM *sig_s = NULL;\n    ECDSA_SIG_get0(sig, &sig_r, &sig_s);\n    int nBitsR = BN_num_bits(sig_r);\n    int nBitsS = BN_num_bits(sig_s);\n"""
    if "BN_num_bits(sig->r)" in key:
        key = replace_exact(key, old, new, "SignCompact accessor setup")

    if "BN_bn2bin(sig->r" in key:
        if key.count("BN_bn2bin(sig->r") != 1 or key.count("BN_bn2bin(sig->s") != 1:
            die("unexpected compact-signature field-access count")
        key = key.replace("BN_bn2bin(sig->r", "BN_bn2bin(sig_r", 1)
        key = key.replace("BN_bn2bin(sig->s", "BN_bn2bin(sig_s", 1)

    old = """    ECDSA_SIG *sig = ECDSA_SIG_new();\n    BN_bin2bn(&vchSig[1],32,sig->r);\n    BN_bin2bn(&vchSig[33],32,sig->s);\n\n"""
    new = """    ECDSA_SIG *sig = ECDSA_SIG_new();\n    if (sig == NULL)\n        return false;\n    BIGNUM *sig_r = BN_bin2bn(&vchSig[1], 32, NULL);\n    BIGNUM *sig_s = BN_bin2bn(&vchSig[33], 32, NULL);\n    if (sig_r == NULL || sig_s == NULL || !ECDSA_SIG_set0(sig, sig_r, sig_s))\n    {\n        if (sig_r != NULL) BN_free(sig_r);\n        if (sig_s != NULL) BN_free(sig_s);\n        ECDSA_SIG_free(sig);\n        return false;\n    }\n\n"""
    if "sig->r" in key or "sig->s" in key:
        # At this point the only allowed remaining direct accesses are this reconstruction block.
        key = replace_exact(key, old, new, "SetCompactSignature construction")

    leftovers = [line.strip() for line in key.splitlines() if "->r" in line or "->s" in line]
    if leftovers:
        die("opaque ECDSA_SIG field access remains: " + " | ".join(leftovers[:10]))

    if "ECDSA_SIG_get0(" not in key or "ECDSA_SIG_set0(" not in key:
        die("post-transform accessor safety markers missing")

    # Write only after every validation passes.
    BIGNUM.write_text(bn)
    KEY.write_text(key)
    print("Updated src/bignum.h: fixed ToString() name shadowing")
    print("Updated src/key.cpp: converted ECDSA_SIG r/s access to OpenSSL 1.1+ accessors")
    print("Safety checks passed: no direct ->r or ->s access remains in key.cpp")
    print("Review with: git diff -- src/bignum.h src/key.cpp")


if __name__ == "__main__":
    main()
