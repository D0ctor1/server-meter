#!/usr/bin/env python3
"""Create /etc/server-meter/config.yaml or patch I²C keys.

Never changes the password, bind address, port, or web.locale.
Missing locale is left missing; the application defaults to CZ.

On upgrade, history.max_samples is bumped from the old shipped defaults
(10000 / 20000) to 2000000. Any other value is left alone.
"""

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
    parser.add_argument("--bsec-config", default="")
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
        if args.bsec_config and 'config_blob_path: ""' in text:
            text = text.replace('config_blob_path: ""', f'config_blob_path: "{args.bsec_config}"', 1)
        try:
            from server_meter.config import bump_legacy_history_max_samples
        except ImportError:
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
            from server_meter.config import bump_legacy_history_max_samples
        text, n_hist = bump_legacy_history_max_samples(text)
        dest.write_text(text, encoding="utf-8")
        sys.stdout.write(
            f"PRESERVE {dest} (I2C bus={args.bus} address={addr} "
            f"addr_hits={n_addr} bus_hits={n_bus} history_max_bump={n_hist})\n"
        )
        return 0

    text = Path(args.example).read_text(encoding="utf-8")
    text = text.replace("address: 0x77", f"address: {addr}")
    text = text.replace("address: 0x76", f"address: {addr}")
    text = text.replace("bus: 1", f"bus: {args.bus}", 1)
    if args.bsec_lib:
        text = text.replace('library_path: ""', f'library_path: "{args.bsec_lib}"', 1)
    if args.bsec_config:
        text = text.replace('config_blob_path: ""', f'config_blob_path: "{args.bsec_config}"', 1)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    sys.stdout.write(f"WROTE {dest}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
