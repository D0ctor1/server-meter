#!/usr/bin/env python3
"""Create /etc/server-meter/config.yaml or patch I²C keys. Never changes the password."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--example", required=True)
    parser.add_argument("--dest", required=True)
    parser.add_argument("--bus", type=int, required=True)
    parser.add_argument("--address", required=True)
    parser.add_argument("--bsec-lib", default="")
    args = parser.parse_args()

    dest = Path(args.dest)
    addr = args.address.strip().lower()
    if not addr.startswith("0x"):
        addr = hex(int(addr, 0))

    if dest.is_file():
        text = dest.read_text(encoding="utf-8")
        text, n_addr = re.subn(r"(?m)^(\s*address:\s*)(0x[0-9a-fA-F]+|\d+)", rf"\g<1>{addr}", text, count=1)
        text, n_bus = re.subn(r"(?m)^(\s*bus:\s*)\d+", rf"\g<1>{args.bus}", text, count=1)
        if args.bsec_lib and 'library_path: ""' in text:
            text = text.replace('library_path: ""', f'library_path: "{args.bsec_lib}"', 1)
        dest.write_text(text, encoding="utf-8")
        sys.stdout.write(f"PRESERVE {dest} (I2C bus={args.bus} address={addr} addr_hits={n_addr} bus_hits={n_bus})\n")
        return 0

    text = Path(args.example).read_text(encoding="utf-8")
    text = text.replace("address: 0x77", f"address: {addr}")
    text = text.replace("address: 0x76", f"address: {addr}")
    text = text.replace("bus: 1", f"bus: {args.bus}", 1)
    if args.bsec_lib:
        text = text.replace('library_path: ""', f'library_path: "{args.bsec_lib}"', 1)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    sys.stdout.write(f"WROTE {dest}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
