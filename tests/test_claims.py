"""일반청구 (claims/) 의 공통 부품 — 비목 번호 · 금액 읽기 · 넣은 기록 · 작성 화면 [저장](임시저장). 브라우저 없이 본다.

ERP 프레임은 가짜(evaluate 가 JS 상수를 알아보고 흉내 낸다). 명단 청구는 test_scholarship.py, 카드는 test_card*.py.
일반(AI 읽기) · 세금계산서 · 개인 지급 종류의 테스트는 그 종류와 함께 2026-10-28 걷어냈다.
"""
from __future__ import annotations

from pathlib import Path

from claim_downloader import settings
from claim_downloader.claims import form, record, schema

CLAIMS = Path(__file__).resolve().parents[1] / "src" / "claim_downloader" / "claims"


# ── schema ───────────────────────────────────────────────────────────
def test_category_code_accepts_any_spelling():
    assert schema.category_code("그 밖의 사업운영 경비") == "09"
    assert schema.category_code("기타운영경비") == "09"
    assert schema.category_code("09") == "09"
    assert schema.category_code("교육연구프로그램개발운영비") == "03"
    assert schema.category_code("지역연계협업지원비") == "06"
    assert schema.category_code("") == "" and schema.category_code("모르는비목") == ""


def test_amounts_with_decimals():
    assert schema.parse_amount("51900.0") == 51900 and schema.parse_amount("51,900.00") == 51900
    assert schema.parse_amount("51,900원") == 51900 and schema.parse_amount("₩ 51,900") == 51900
    assert schema.parse_amount(None) is None and schema.parse_amount("") is None and schema.parse_amount(True) is None


# ── record ───────────────────────────────────────────────────────────
def test_record_remembers_filled_folders(isolated_home, tmp_path):
    folder = tmp_path / "지출1"
    assert record.previous(folder) is None
    record.remember(folder, {"amount": 51900, "summary": "09_정수기"})
    before = record.previous(str(folder))
    assert before["amount"] == 51900 and before["summary"] == "09_정수기" and before["when"]
    assert settings.claim_record_path().parent == isolated_home


# ── form ([저장] 만) ─────────────────────────────────────────────────
class FakeFrame:
    """evaluate 가 form.py 의 JS 상수를 알아보고 ERP 작성 화면처럼 반응한다."""

    def __init__(self, screen=None, save_works=True):
        self.values = dict(screen or {})
        self.clicks = []
        self.save_works = save_works

    def evaluate(self, js, arg=None):
        if js is form.PROBE_JS:
            return True
        if js is form.STATE_JS:
            return {i: {"tag": "input", "value": self._value(i)} for i in arg}
        if js is form.CLICK_SAVE_JS:
            self.clicks.append(arg)
            if arg == form.SAVE_TEXT and self.save_works:
                self.values["REQ_SEQ_NO"] = "REQ-2026-0001"
                self.values["MOD_YN"] = "Y"
            return {"ok": True}
        raise AssertionError("모르는 JS")

    def _value(self, element_id):
        if element_id in self.values:
            return self.values[element_id]
        if element_id == "MOD_YN":
            return "N"
        if element_id == "PROC_TYP_CD":
            return "P10"
        return ""


def test_form_module_clicks_only_save():
    text = (CLAIMS / "form.py").read_text(encoding="utf-8")
    assert text.count(".click(") == 1 and ".click(" in form.CLICK_SAVE_JS      # 누르는 곳은 임시저장 하나
    assert "submit" not in text.lower()
    assert "import playwright" not in text and "from playwright" not in text
    assert "신청" in form.FORBIDDEN_TEXTS and form.SAVE_TEXT not in form.FORBIDDEN_TEXTS


def test_save_draft_waits_for_payee_and_reports_change():
    """입금처가 비어 있으면 누르지 않고, 다 있으면 [저장] 하나만 눌러 결의번호가 생기는 것을 확인한다."""
    frame = FakeFrame(screen={"REQ_PTCL": "09_정수기", "REQ_AMT": "51,900", "RCV_NM": ""})
    report = form.save_draft(frame, lambda m: None, [], wait=lambda s: None)
    assert not report.ok and "입금처" in report.note and frame.clicks == []

    frame = FakeFrame(screen={"REQ_PTCL": "09_정수기", "REQ_AMT": "51,900", "RCV_NM": "코웨이(주)"})
    messages = []
    report = form.save_draft(frame, lambda m: None, messages, wait=lambda s: None)
    assert report.ok and frame.clicks == [form.SAVE_TEXT]
    assert report.after["REQ_SEQ_NO"] == "REQ-2026-0001" and report.after["MOD_YN"] == "Y"
    assert "[신청] 은 직접 누르세요" in " ".join(report.lines())

    frame = FakeFrame(screen={"REQ_PTCL": "x", "REQ_AMT": "1", "RCV_NM": "y"}, save_works=False)
    report = form.save_draft(frame, lambda m: None, ["필수 항목이 비어 있습니다"], wait=lambda s: None, tries=2)
    assert not report.ok and report.messages == ["필수 항목이 비어 있습니다"]
    # 화면은 안 바뀌어도 '저장되었습니다' 가 뜨면 됨으로, '저장하시겠습니까?' 만 떴으면 아직 아님
    frame = FakeFrame(screen={"REQ_PTCL": "x", "REQ_AMT": "1", "RCV_NM": "y"}, save_works=False)
    assert form.save_draft(frame, lambda m: None, ["저장하시겠습니까?", "저장되었습니다."], wait=lambda s: None, tries=2).ok
    frame = FakeFrame(screen={"REQ_PTCL": "x", "REQ_AMT": "1", "RCV_NM": "y"}, save_works=False)
    assert not form.save_draft(frame, lambda m: None, ["저장하시겠습니까?"], wait=lambda s: None, tries=2).ok


def test_save_is_not_counted_when_the_page_navigated_away():
    """[저장] 뒤 로그인 · 오류 화면으로 넘어가 칸이 모두 비면 저장된 것으로 보지 않는다."""
    before = {"REQ_SEQ_NO": "TMP_REQ_1", "MOD_YN": "N", "APPR_DIV_CD": "", "REQ_CNT": ""}
    assert not form._changed(before, {k: "" for k in before})
    assert form._changed(before, {**before, "REQ_CNT": "322", "APPR_DIV_CD": "40"})


def test_saved_sheet_reads_the_claim_number():
    """저장 뒤에도 MOD_YN 은 N 이다(실측 ⑤) — 결의번호(REQ_CNT)나 진행구분 40 이 있으면 이미 저장된 청구서."""
    assert form.saved_sheet({"REQ_CNT": "324"}) and not form.saved_sheet({"REQ_CNT": "", "APPR_DIV_CD": ""})
