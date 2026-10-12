"""공용 준비물.

테스트는 실제 ERP·브라우저·청구서 PDF 없이 돈다. 목록 행은 ERP 그리드에서
읽어 오는 dict 와 같은 모양으로 직접 만든다. **실제 청구서를 커밋해서 테스트를
짜지 않는다** — 계좌번호와 이체자 이름이 들어 있다.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """설정·기록이 사용자 홈(~/.claim-downloader)을 건드리지 않게 한다."""
    home = tmp_path / "home"
    monkeypatch.setenv("CLAIM_DOWNLOADER_HOME", str(home))
    return home


def make_row(**overrides) -> dict:
    """결의서내역 그리드 한 행 (erp.parse_rows 가 돌려주는 모양)."""
    row = {
        "r": "0", "no": "1", "seq": "101", "gubun": "일반청구",
        "cont": "09_2026년 사업단 정수기 임차료(9월)", "amt": "51900",
        "state": "승인", "docNo": "산학-20261008-0001", "expDt": "2026-10-08",
    }
    row.update(overrides)
    return row
