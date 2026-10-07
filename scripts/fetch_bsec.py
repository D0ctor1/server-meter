#!/usr/bin/env python3
"""Fetch official Bosch BSEC 3.2+ and extract the Raspberry Pi 5 ARM64 library.

BSEC is proprietary. This script only downloads ZIP files published on
Bosch Sensortec's software-downloads page (bosch-sensortec.com). It does
not scrape third-party mirrors. Running it (via sudo ./install.sh) means
the operator accepts the Bosch Sensortec Software License Agreement.

Stdlib only. Never writes BSEC algorithm state.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urljoin

BOSCH_DOWNLOADS = (
    "https://www.bosch-sensortec.com/en/software-tools/software-downloads.html"
)
BOSCH_ORIGIN = "https://www.bosch-sensortec.com"
LICENSE_PDF = (
    "https://www.bosch-sensortec.com/media/boschsensortec/downloads/software/"
    "bme688_development_software/2024_12/"
    "20241219_clickthrough_license_terms_bsec_bme680_bme688_bme690.pdf"
)
# Exact hrefs observed on Bosch software-downloads.html (newest first).
# Used when the listing page is unreachable. Do not add unofficial mirrors.
FALLBACK_ZIPS = [
    "https://www.bosch-sensortec.com/media/boschsensortec/downloads/software/bme688_development_software/2026_08/bsec_v3-3-0-1.zip",
    "https://www.bosch-sensortec.com/media/boschsensortec/software_tools/software/bme_690/bsec_v3-3-0-0.zip",
    "https://www.bosch-sensortec.com/media/boschsensortec/downloads/software/bme688_development_software/2025_5/bsec_v3-2-1-0.zip",
    "https://www.bosch-sensortec.com/media/boschsensortec/software_tools/software/bme688/06_02_2025_bme690_bme688/bsec_v3-2-0-0.zip",
]
MIN_VERSION = (3, 2, 0, 0)
USER_AGENT = (
    "Mozilla/5.0 (compatible; server-meter-installer; "
    "+https://github.com/D0ctor1/server-meter)"
)
BSEC_ZIP_HREF = re.compile(
    r"""href=["']([^"']*bsec_v3(?:-\d+){3}\.zip)["']""",
    re.IGNORECASE,
)
VERSION_RE = re.compile(r"bsec_v(\d+(?:-\d+){3})\.zip$", re.IGNORECASE)


def parse_bsec_version(name: str) -> tuple[int, int, int, int] | None:
    match = VERSION_RE.search(name.replace("\\", "/").split("/")[-1])
    if not match:
        return None
    parts = [int(p) for p in match.group(1).split("-")]
    while len(parts) < 4:
        parts.append(0)
    return parts[0], parts[1], parts[2], parts[3]


def absolute_bosch_url(href: str) -> str:
    if href.startswith("http://") or href.startswith("https://"):
        return href
    return urljoin(BOSCH_ORIGIN, href)


def discover_zip_urls(html: str) -> list[str]:
    found: dict[tuple[int, int, int, int], str] = {}
    for href in BSEC_ZIP_HREF.findall(html):
        url = absolute_bosch_url(href)
        version = parse_bsec_version(url)
        if version is None or version < MIN_VERSION:
            continue
        if "bosch-sensortec.com" not in url:
            continue
        found[version] = url
    return [found[key] for key in sorted(found, reverse=True)]


def library_score(member: str) -> int:
    path = member.replace("\\", "/")
    lower = path.lower()
    name = path.rsplit("/", 1)[-1].lower()
    if name not in {"libalgobsec.so", "libalgobsec.a"}:
        return -1
    if lower.endswith(".size.log"):
        return -1
    score = 0
    if "sel_iaq" in lower or "selectivity" in lower:
        score -= 80
    if "examples/" in lower:
        score -= 40
    if "release_bin/" in lower:
        score += 20
    if "/iaq/" in lower:
        score += 15
    if "pifour_armv8" in lower:
        score += 100
    elif "pithree_armv8" in lower:
        score += 40
    if "raspberrypi" in lower or "raspberry_pi" in lower:
        score += 20
    if name.endswith(".so"):
        score += 10
    elif name.endswith(".a"):
        score += 5
    return score


def config_score(member: str) -> int:
    path = member.replace("\\", "/")
    lower = path.lower()
    name = path.rsplit("/", 1)[-1].lower()
    if name != "bsec_iaq.config":
        return -1
    if "sel_iaq" in lower or "selectivity" in lower:
        return -1
    score = 0
    if "release_bin/" in lower:
        score += 20
    if "/bme690/" in lower:
        score += 50
    elif "/bme688/" in lower:
        score += 10
    if "33v" in lower:
        score += 20
    if "_3s_" in lower:
        score += 20
    if "_28d" in lower:
        score += 8
    elif "_4d" in lower:
        score += 4
    return score


def pick_library_member(names: list[str]) -> str | None:
    ranked = [(library_score(name), name) for name in names]
    ranked = [item for item in ranked if item[0] >= 0]
    if not ranked:
        return None
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return ranked[0][1]


def pick_config_member(names: list[str]) -> str | None:
    ranked = [(config_score(name), name) for name in names]
    ranked = [item for item in ranked if item[0] >= 0]
    if not ranked:
        return None
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return ranked[0][1]


def _http_get(url: str, dest: Path | None = None, timeout: float = 60.0) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read()
    if dest is not None:
        dest.write_bytes(data)
    return data


def candidate_zip_urls(override: str | None = None) -> list[str]:
    if override:
        return [override]
    urls: list[str] = []
    try:
        html = _http_get(BOSCH_DOWNLOADS, timeout=30).decode("utf-8", "replace")
        urls = discover_zip_urls(html)
    except (urllib.error.URLError, TimeoutError, OSError):
        urls = []
    seen = set(urls)
    for fallback in FALLBACK_ZIPS:
        if fallback not in seen:
            urls.append(fallback)
    return urls


def extract_assets(zip_path: Path, work_dir: Path) -> dict[str, str]:
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        lib_member = pick_library_member(names)
        if not lib_member:
            raise FileNotFoundError("ZIP has no libalgobsec.so / libalgobsec.a for Raspberry Pi")
        cfg_member = pick_config_member(names)
        lib_name = Path(lib_member.replace("\\", "/")).name
        lib_dest = work_dir / lib_name
        lib_dest.write_bytes(zf.read(lib_member))
        result = {
            "archive": str(lib_dest),
            "archive_kind": "so" if lib_name.endswith(".so") else "a",
            "member": lib_member,
        }
        if cfg_member:
            cfg_dest = work_dir / "bsec_iaq.config"
            cfg_dest.write_bytes(zf.read(cfg_member))
            result["config"] = str(cfg_dest)
            result["config_member"] = cfg_member
    return result


def fetch_and_extract(
    work_dir: Path,
    zip_url: str | None = None,
    local_zip: str | None = None,
) -> dict[str, str]:
    work_dir.mkdir(parents=True, exist_ok=True)
    if local_zip:
        zip_path = Path(local_zip)
        if not zip_path.is_file():
            raise FileNotFoundError(f"BSEC zip not found: {zip_path}")
        assets = extract_assets(zip_path, work_dir)
        assets.update({"ok": True, "zip_url": str(zip_path), "version": _version_label(str(zip_path))})
        return assets

    errors: list[str] = []
    for url in candidate_zip_urls(zip_url):
        version = _version_label(url)
        dest = work_dir / f"bsec_{version}.zip"
        try:
            _http_get(url, dest=dest)
            assets = extract_assets(dest, work_dir)
            dest.unlink(missing_ok=True)
            assets.update({"ok": True, "zip_url": url, "version": version})
            return assets
        except Exception as exc:  # noqa: BLE001 — try the next official URL
            errors.append(f"{url}: {exc}")
            dest.unlink(missing_ok=True)
            continue
    raise RuntimeError("Could not download BSEC from Bosch. " + "; ".join(errors[-3:]))


def _version_label(url: str) -> str:
    parsed = parse_bsec_version(url)
    if parsed is None:
        return "unknown"
    return ".".join(str(part) for part in parsed)


def main() -> int:
    parser = argparse.ArgumentParser(description="Download official Bosch BSEC 3.2+ for Pi 5")
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--zip-url", default=os.environ.get("SERVER_METER_BSEC_URL", ""))
    parser.add_argument("--local-zip", default=os.environ.get("SERVER_METER_BSEC_ZIP", ""))
    parser.add_argument("--json-out", default="")
    args = parser.parse_args()
    try:
        result = fetch_and_extract(
            Path(args.work_dir),
            zip_url=args.zip_url or None,
            local_zip=args.local_zip or None,
        )
    except Exception as exc:
        payload = {"ok": False, "error": str(exc), "license": LICENSE_PDF}
        text = json.dumps(payload)
        if args.json_out:
            Path(args.json_out).write_text(text + "\n", encoding="utf-8")
        sys.stdout.write(text + "\n")
        return 1
    payload = {"license": LICENSE_PDF, **result}
    text = json.dumps(payload)
    if args.json_out:
        Path(args.json_out).write_text(text + "\n", encoding="utf-8")
    sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
