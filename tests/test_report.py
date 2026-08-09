"""결과 출력 — 담당자가 그대로 복사해 보낼 수 있어야 한다."""
import json

from app.engine import review_case
from app.models import Status
from app.report import render_json, render_markdown, render_text, to_dict

from . import fixtures as fx


def test_text_report_shows_evidence_and_fix():
    """docs/02 §1 이 요구하는 [근거 · 검출값 · 조치] 가 모두 나와야 한다."""
    text = render_text(review_case(fx.travel_lee_dj_case()))
    assert "R-TRV-006" in text
    assert "근거" in text
    assert "검출값" in text
    assert "조치" in text
    assert "🔴 수정 필요" in text


def test_markdown_report_is_a_correction_request():
    markdown = render_markdown(review_case(fx.travel_lee_dj_case()))
    assert markdown.startswith("# 지출 서류 수정 요청")
    assert "**조치:**" in markdown
    # 자동 검토가 못 본 항목도 남겨야 담당자가 직접 확인할 수 있다.
    assert "확인하지 못한 항목" in markdown


def test_json_report_round_trips():
    result = review_case(fx.ta_case())
    payload = json.loads(render_json(result))
    assert payload["expense_type"] == "근로장학금"
    assert payload["subtype"] == "TA"
    assert payload["summary"]["ERROR"] == 0
    assert {d["kind"] for d in payload["documents"]} >= {"form5_worklog", "payment_roster"}


def test_clean_case_reports_no_problem():
    text = render_text(review_case(fx.ta_case()))
    assert "자동 검토에서 문제를 찾지 못했습니다" in text


def test_summary_counts_match_findings():
    result = review_case(fx.travel_hwang_case())
    summary = to_dict(result)["summary"]
    assert summary["ERROR"] == result.count(Status.ERROR)
    assert sum(summary.values()) == len(result.findings)
