"""구글시트 연동 테스트 — URL 변환, CSV 해석, 오버라이드 우선순위."""
from __future__ import annotations

import pytest

from expense_review import config, sheets
from expense_review.engine import load_ruleset
from expense_review.models import Severity


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("EXPENSE_REVIEW_HOME", str(tmp_path / "home"))
    yield


# ── URL 변환 ──────────────────────────────────────────────────────────────

def test_browser_url_becomes_csv_export_url():
    url = "https://docs.google.com/spreadsheets/d/abc123XYZ/edit#gid=456"
    assert sheets.to_csv_export_url(url) == (
        "https://docs.google.com/spreadsheets/d/abc123XYZ/export?format=csv&gid=456"
    )


def test_url_without_gid_defaults_to_first_tab():
    url = "https://docs.google.com/spreadsheets/d/abc123XYZ/edit"
    assert "gid=0" in sheets.to_csv_export_url(url)


def test_published_csv_url_is_kept_as_is():
    url = "https://docs.google.com/spreadsheets/d/e/2PACX/pub?output=csv"
    assert sheets.to_csv_export_url(url) == url


# ── CSV 해석 ──────────────────────────────────────────────────────────────

CSV = """종류,대상,항목,값
설정,출장비,km_rate,300
설정,근로장학금,max_hours_per_month,60
규칙,R-TRV-008,등급,수정 필요
규칙,R-TRV-008,사용,아니오
규칙,R-CMN-002,조치 문구,최종본 1부만 남기세요
이상한종류,x,y,z
"""


def test_parse_settings_and_rules():
    data = sheets.parse_overrides(CSV)
    assert data["settings"]["출장비"]["km_rate"] == 300
    assert data["settings"]["근로장학금"]["max_hours_per_month"] == 60
    assert data["rules"]["R-TRV-008"]["severity"] == "ERROR"     # '수정 필요' 매핑
    assert data["rules"]["R-TRV-008"]["enabled"] is False        # '아니오' 매핑
    assert data["rules"]["R-CMN-002"]["fix"] == "최종본 1부만 남기세요"


def test_unknown_rows_are_reported_not_fatal():
    data = sheets.parse_overrides(CSV)
    assert any("알 수 없는 종류" in issue for issue in data["issues"])


def test_login_html_raises_permission_error(monkeypatch):
    """공유가 안 된 시트는 구글이 로그인 페이지 HTML을 돌려준다."""
    class FakeResponse:
        def read(self):
            return b"<!DOCTYPE html><html>Sign in</html>"
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False

    monkeypatch.setattr(sheets.urllib.request, "urlopen", lambda *a, **k: FakeResponse())
    with pytest.raises(PermissionError):
        sheets.fetch_csv("https://docs.google.com/spreadsheets/d/x/edit")


# ── 우선순위: 배포본 < 시트 < 로컬 ────────────────────────────────────────

def _rule(rule_id):
    return {r.id: r for r in load_ruleset("출장비").rules}[rule_id]


def test_sheet_overrides_apply_from_cache_without_network():
    sheets.save_cache("종류,대상,항목,값\n규칙,R-TRV-008,등급,수정 필요\n설정,출장비,km_rate,300\n")
    assert _rule("R-TRV-008").severity is Severity.ERROR          # 배포본은 WARN
    assert load_ruleset("출장비").settings["km_rate"] == 300


def test_local_edit_beats_sheet():
    sheets.save_cache("종류,대상,항목,값\n규칙,R-TRV-008,등급,수정 필요\n")
    config.set_rule_override("R-TRV-008", "severity", "INFO")
    assert _rule("R-TRV-008").severity is Severity.INFO


def test_result_rows_contain_summary_only():
    """기록 행에는 요약만 담긴다 — 지적 문구·개인정보가 들어가지 않는다."""
    from conftest import make_document, run

    documents = [make_document("trip_evidence", "출장증빙.pdf",
                               transport_block=False, route_block=False,
                               stay_dates=[])]
    rows = sheets.result_rows([run("출장비", documents, owner="홍길동")])
    assert len(rows) == 1
    row = rows[0]
    assert row[1] == "출장비" and row[2] == "홍길동"
    assert all(isinstance(v, int) for v in row[3:6])
    assert "R-TRV-002" in row[6]                     # 규칙 ID 목록만
    joined = " ".join(str(v) for v in row)
    assert "블록" not in joined                       # 지적 문구 원문 없음
