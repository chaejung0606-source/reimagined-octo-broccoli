"""ERP 청구내역 엑셀 대조 (선택 기능)."""
from __future__ import annotations

import pytest

from claim_downloader.reconcile import reconcile

pd = pytest.importorskip("pandas")
pytest.importorskip("openpyxl")


def test_finds_missing_by_doc_no_only(tmp_path):
    path = tmp_path / "청구내역.xlsx"
    pd.DataFrame([
        {"진행구분": "승인", "문서번호": "A", "지출일자": "2026-04-30", "결의서구분": "일반", "금액": "300000", "내용": "4월 기관부담금"},
        {"진행구분": "승인", "문서번호": "B", "지출일자": "2026-05-31", "결의서구분": "일반", "금액": "300000", "내용": "5월 기관부담금"},
        {"진행구분": "승인", "문서번호": "C", "지출일자": "2026-05-31", "결의서구분": "반납", "금액": "1", "내용": "반납"},
        {"진행구분": "결재중", "문서번호": "D", "지출일자": "", "결의서구분": "일반", "금액": "1", "내용": "x"},
    ]).to_excel(path, index=False)
    logs: list[str] = []
    # 금액이 같은 5월 건(B)을 받았다고 4월 건(A)이 가려지면 안 된다
    missing = reconcile(str(path), {"B"}, logs.append)
    assert [m["docNo"] for m in missing] == ["A"]


def test_missing_file_is_skipped(tmp_path):
    logs: list[str] = []
    assert reconcile(str(tmp_path / "없음.xlsx"), set(), logs.append) == []
    assert logs
