from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from fetch_bsec import (  # noqa: E402
    FALLBACK_ZIPS,
    MIN_VERSION,
    discover_zip_urls,
    extract_assets,
    parse_bsec_version,
    pick_config_member,
    pick_library_member,
)


def test_parse_and_reject_old_bsec_versions():
    assert parse_bsec_version("bsec_v3-3-0-1.zip") == (3, 3, 0, 1)
    assert parse_bsec_version("https://example/bsec_v3-2-0-0.zip") == (3, 2, 0, 0)
    assert parse_bsec_version("bsec_v3-1-0-0.zip") == (3, 1, 0, 0)
    assert parse_bsec_version("bsec_v3-1-0-0.zip") < MIN_VERSION


def test_discover_zip_urls_keeps_only_official_bsec_3_2_plus():
    html = """
    <a href="/media/boschsensortec/software_tools/software/bme_690/05_12_2024/bsec_v3-1-0-0.zip">old</a>
    <a href="/media/boschsensortec/downloads/software/bme688_development_software/2025_5/bsec_v3-2-1-0.zip">a</a>
    <a href="https://evil.example/bsec_v3-9-9-9.zip">nope</a>
    <a href="/media/boschsensortec/downloads/software/bme688_development_software/2026_08/bsec_v3-3-0-1.zip">new</a>
    """
    urls = discover_zip_urls(html)
    assert urls[0].endswith("bsec_v3-3-0-1.zip")
    assert urls[1].endswith("bsec_v3-2-1-0.zip")
    assert all("bosch-sensortec.com" in url for url in urls)
    assert all("3-1-0-0" not in url for url in urls)
    assert all(url.startswith("https://www.bosch-sensortec.com/") for url in FALLBACK_ZIPS)


def test_pick_pifour_iaq_library_not_selectivity_or_pi3():
    names = [
        "examples/BSEC_Integration_Examples/src/esp32/libalgobsec.a",
        "release_bin/Sel_IAQ/bin/RaspberryPi/PiFour_Armv8/libalgobsec.a",
        "release_bin/IAQ/bin/RaspberryPi/PiThree_ArmV8/libalgobsec.a",
        "release_bin/IAQ/bin/RaspberryPi/PiFour_Armv8/libalgobsec.a",
        "release_bin/IAQ/bin/gcc/Linux/m64/libalgobsec.a",
    ]
    assert pick_library_member(names) == (
        "release_bin/IAQ/bin/RaspberryPi/PiFour_Armv8/libalgobsec.a"
    )


def test_pick_bme690_33v_3s_config():
    names = [
        "release_bin/IAQ/config/bme680/bme680_iaq_33v_3s_4d/bsec_iaq.config",
        "release_bin/IAQ/config/bme690/bme690_iaq_18v_3s_4d/bsec_iaq.config",
        "release_bin/IAQ/config/bme690/bme690_iaq_33v_300s_28d/bsec_iaq.config",
        "release_bin/IAQ/config/bme690/bme690_iaq_33v_3s_4d/bsec_iaq.config",
        "release_bin/IAQ/config/bme690/bme690_iaq_33v_3s_28d/bsec_iaq.config",
        "release_bin/Sel_IAQ/config/bme690/bme690_sel_33v_3s_28d/bsec_selectivity.config",
    ]
    assert pick_config_member(names) == (
        "release_bin/IAQ/config/bme690/bme690_iaq_33v_3s_28d/bsec_iaq.config"
    )


def test_extract_assets_from_official_layout(tmp_path):
    zip_path = tmp_path / "bsec_v3-3-0-1.zip"
    lib_member = "release_bin/IAQ/bin/RaspberryPi/PiFour_Armv8/libalgobsec.a"
    cfg_member = "release_bin/IAQ/config/bme690/bme690_iaq_33v_3s_28d/bsec_iaq.config"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("release_bin/Sel_IAQ/bin/RaspberryPi/PiFour_Armv8/libalgobsec.a", b"sel")
        zf.writestr(lib_member, b"iaq-pifour")
        zf.writestr(cfg_member, b"blob")
        zf.writestr(
            "release_bin/IAQ/config/bme690/bme690_iaq_18v_3s_4d/bsec_iaq.config",
            b"wrong",
        )
    work = tmp_path / "work"
    work.mkdir()
    assets = extract_assets(zip_path, work)
    assert Path(assets["archive"]).read_bytes() == b"iaq-pifour"
    assert assets["member"] == lib_member
    assert Path(assets["config"]).read_bytes() == b"blob"
    assert assets["config_member"] == cfg_member


def test_cli_local_zip_json(tmp_path):
    import subprocess
    import sys

    zip_path = tmp_path / "bsec_v3-2-0-0.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(
            "release_bin/IAQ/bin/RaspberryPi/PiFour_Armv8/libalgobsec.so",
            b"\x7fELFdummy",
        )
    work = tmp_path / "out"
    json_out = tmp_path / "result.json"
    script = Path(__file__).resolve().parent.parent / "scripts" / "fetch_bsec.py"
    subprocess.check_call(
        [
            sys.executable,
            str(script),
            "--work-dir",
            str(work),
            "--local-zip",
            str(zip_path),
            "--json-out",
            str(json_out),
        ]
    )
    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["version"] == "3.2.0.0"
    assert payload["archive_kind"] == "so"
    assert Path(payload["archive"]).is_file()
