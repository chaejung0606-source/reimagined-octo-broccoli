"""설정 파일."""
from __future__ import annotations

import json

from claim_downloader import settings


def test_defaults():
    loaded = settings.load()
    assert loaded.out_root == ""             # 동료에게 그대로 공유할 수 있어야 한다
    assert loaded.name_date_first is False   # 비목 번호로 시작하는 이름이 기본


def test_roundtrip_and_env_override(isolated_home):
    settings.update(out_root=r"C:\지출결의서\2026년도", name_date_first=True)
    loaded = settings.load()
    assert loaded.out_root == r"C:\지출결의서\2026년도"
    assert loaded.name_date_first is True
    assert settings.config_path().parent == isolated_home


def test_broken_or_odd_file_falls_back(isolated_home):
    settings.config_path().write_text("{깨짐", encoding="utf-8")
    assert settings.load() == settings.Settings()

    settings.config_path().write_text(json.dumps(
        {"wait_sec": "많이", "freeze_reload": "yes", "out_root": 3, "모르는키": 1}), encoding="utf-8")
    assert settings.load() == settings.Settings()

    settings.config_path().write_text(json.dumps({"wait_sec": 5}), encoding="utf-8")
    assert settings.load().wait_sec == 5.0
