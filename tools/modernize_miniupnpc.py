#!/usr/bin/env python3
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
path = root / "src" / "net.cpp"
text = path.read_text()

old = "devlist = upnpDiscover(2000, multicastif, minissdpdpath, 0, 0, &error);"
new = "devlist = upnpDiscover(2000, multicastif, minissdpdpath, 0, 0, 2, &error);"

if old not in text:
    if new in text:
        print("miniupnpc upnpDiscover call is already modernized")
        raise SystemExit(0)
    print("ERROR: expected legacy upnpDiscover call not found; no changes made", file=sys.stderr)
    raise SystemExit(1)

if text.count(old) != 1:
    print(f"ERROR: expected exactly one legacy upnpDiscover call, found {text.count(old)}; no changes made", file=sys.stderr)
    raise SystemExit(1)

text = text.replace(old, new, 1)
path.write_text(text)

print(f"Updated {path}")
print("Changed upnpDiscover() to the modern 7-argument miniupnpc signature")
print("TTL set to 2, matching miniupnpc's normal local-network discovery scope")
