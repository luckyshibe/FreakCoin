#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "src" / "zerocoin" / "ParamGeneration.cpp"

OLD_INCLUDE = '#include <string>\n#include "Zerocoin.h"\n'
NEW_INCLUDE = '#include <string>\n#include <memory>\n#include "Zerocoin.h"\n'

OLD_CALL = '''\tcalculateGroupModulusAndOrder(seed, pLen, qLen, &(result.modulus),\n\t                              &(result.groupOrder), &pSeed, &qSeed);'''
NEW_CALL = '''\tcalculateGroupModulusAndOrder(seed, pLen, qLen, std::addressof(result.modulus),\n\t                              std::addressof(result.groupOrder), &pSeed, &qSeed);'''


def die(msg):
    print('ERROR: ' + msg, file=sys.stderr)
    raise SystemExit(1)


def main():
    if not PATH.exists():
        die(f'cannot find {PATH}')

    text = PATH.read_text()

    if NEW_CALL in text:
        die('ParamGeneration.cpp already appears modernized; refusing to run twice')

    if text.count(OLD_CALL) != 1:
        die('expected calculateGroupModulusAndOrder call was not found exactly once; no changes made')

    if '#include <memory>' not in text:
        if text.count(OLD_INCLUDE) != 1:
            die('expected include block was not found exactly once; no changes made')
        text = text.replace(OLD_INCLUDE, NEW_INCLUDE, 1)

    text = text.replace(OLD_CALL, NEW_CALL, 1)

    if '&(result.modulus)' in text or '&(result.groupOrder)' in text:
        die('legacy overloaded-address expressions remain; no changes made')
    if text.count('std::addressof(result.modulus)') != 1 or text.count('std::addressof(result.groupOrder)') != 1:
        die('post-transform address checks failed; no changes made')

    PATH.write_text(text)
    print(f'Updated {PATH}')
    print('Bypassed CBigNum::operator& for the two Zerocoin Bignum* output parameters')
    print('Safety checks passed')


if __name__ == '__main__':
    main()
