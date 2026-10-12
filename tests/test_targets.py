"""받을 대상 고르기."""
from __future__ import annotations

from claim_downloader.targets import MANY_TARGETS, Selection, select_targets, volume_warning
from conftest import make_row


def test_filters():
    rows = [
        make_row(docNo="A"),
        make_row(docNo="B", state="승 인"),                 # 공백이 끼어도 승인
        make_row(docNo="C", state="결재중"),
        make_row(docNo=""),
        make_row(docNo="D", expDt=""),
        make_row(docNo="E", gubun="반납결의"),
        make_row(docNo="F", gubun="자금대체"),
        make_row(docNo="G"),
    ]
    sel = select_targets(rows, done={"G"})
    assert [r["docNo"] for r in sel.targets] == ["A", "B"]
    assert sel.skipped == 1


def test_many_targets_with_few_skipped_warns():
    sel = Selection(targets=[make_row(docNo=str(i)) for i in range(MANY_TARGETS)], skipped=3)
    assert "⚠⚠" in volume_warning(sel)


def test_usual_run_does_not_warn():
    sel = Selection(targets=[make_row()] * 11, skipped=200)
    assert volume_warning(sel) == ""
