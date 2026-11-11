"""카드청구 넣기 준비물 — 회의록 표(참석자 · 시각 · 내용) · 참여연구원 명단 · 참석자 나누기 · 계획 · 이 청구서인지 · 기록.

담당자 규칙(2026-10-20): 회의록의 소속이 비었거나 · 강원대학교 · 학과명이면 참여인력이나 내부참석자, 그 밖의 소속은 외부참석자.
회의비 · 물품 줄 적요 앞 `NN_` 은 건별 공문의 비목. 실명 · 직번은 없다 — 모양만 같은 가짜 값이다.
ERP 화면을 실제로 누르는 흐름은 모의 카드청구 화면 + Chromium 으로 확인했다(CLAUDE.md 19절).
"""
from __future__ import annotations

import datetime as dt
import os

import openpyxl
import pytest

from claim_downloader.claims import attendees, card, card_erp, participants
from claim_downloader.claims.form import STATE_JS
from claim_downloader.minutes.docx import build_docx
from claim_downloader.minutes.hwpx import build_hwpx

from test_card import RECEIPT, make_goods, minutes_data, reader, touch

D = dt.date

PDF_TEXT = """참여연구원 현황표
과제번호 202400000000 사업명 가짜사업
연구책임자 성명 김책임 소속 가나다학과
당해사업비 1,000,000 당해연구기간 2026-03-01 ~ 2027-02-28
성명 소속 역할 직급 학위과정 소득구분 지급비목 지급구분
참여시작일 참여종료일 개월 계상률 월지급액 총지급액 지급방법
김책임 가나다학과 책임연구원 교수 박사과정졸업
(100001) 0.00 0.00 % 0 0
이연구 산학협력단_근로
장학생 공동연구원 연구원 석사과정졸업 근로소득 인건비 현금
(900001) 2026-08-01 2027-02-28 7.00 100.00 % 1,000 7,000 계좌입금
박학생
데이터보안·활용혁
신융합대학사업단 보조연구원 연구원 대학(교)졸업
1/4
(202600001) 2026-04-01 2027-02-28 11.00 100.00 % 1,000 11,000 계좌입금
최긴번 가나다학 보조연구원 대학원생(석사) 석사과정재학
(2024000000001)
0.00 0.00 % 0 0
합계(미지급,현물 제외) 18,000
2/4"""


# ── 참여연구원 명단 ────────────────────────────────────────────────
def test_participant_pdf_two_lines_per_person_even_across_pages():
    """한 사람이 두 줄(윗줄 이름 · 소속 …, 아랫줄 (직번) …). 소속이 꺾이거나 쪽이 바뀌어도, 직번이 6 · 9 · 13자리여도."""
    got = participants.read_pdf_text(PDF_TEXT)
    assert [(m.name, m.emp_no) for m in got] == [("김책임", "100001"), ("이연구", "900001"), ("박학생", "202600001"),
                                                 ("최긴번", "2024000000001")]
    assert got[0].dept == "가나다학과" and got[1].dept == "산학협력단_근로"


def test_participant_xlsx_name_then_emp_no_row(tmp_path):
    """ERP 출력 엑셀(Prn_PrjPartInfo.xlsx, 14절): A열 윗줄 이름 · B열 소속, 아랫줄 A열 '(직번)'."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A9"], ws["B9"] = "성명\n(직번)", "소속"
    ws["A11"], ws["B11"], ws["E11"] = "김책임", "가나다학과", "책임연구원"
    ws["A12"], ws["B12"] = "(100001)", None
    ws["A13"], ws["B13"] = "이연구", "산학협력단_근로장학생"
    ws["A14"], ws["B14"] = "(900001)", "2026-08-01"
    path = tmp_path / "Prn_PrjPartInfo.xlsx"
    wb.save(path)
    got = participants.read(str(path))
    assert [(m.name, m.emp_no, m.dept) for m in got] == [("김책임", "100001", "가나다학과"), ("이연구", "900001", "산학협력단_근로장학생")]
    assert participants.find_file("", str(tmp_path)) == str(path)              # 설정이 비면 폴더에서 찾는다
    assert participants.find_file(str(path)) == str(path)


def test_attendee_rule_blank_knu_or_department_is_inside():
    """담당자 규칙: 소속이 공란 · 강원대학교 · 학과명이면 참여인력/내부참석자, 그 밖은 외부참석자."""
    for org in ("", "강원대학교", "강원대 AI융합학과", "컴퓨터공학과", "정보보호학", "데이터보안·활용혁신융합대학사업단", "산학협력단", "공과대학"):
        assert participants.is_internal_org(org), org
    for org in ("한림대학교", "(주)가나다", "가나다 주식회사", "한국가나다재단", "춘천시청", "한국전자통신연구원"):
        assert not participants.is_internal_org(org), org
    members = [participants.Member("김책임", "100001"), participants.Member("이연구", "900001"), participants.Member("이연구", "900002")]
    got = participants.classify([("강원대학교", "김책임"), ("", "홍길동"), ("한림대학교", "김책임"), ("가나다학과", "이연구")], members)
    assert [(a.kind, a.emp_no) for a in got] == [("part", "100001"), ("internal", ""), ("external", ""), ("internal", "")]
    assert "외부참석자로" in got[2].note and "2명" in got[3].note


# ── 회의록 표 ────────────────────────────────────────────────────────
def test_minutes_table_reads_merged_orgs_times_and_content(tmp_path):
    """소속 칸은 같은 소속끼리 세로로 합쳐져(hwpx rowSpan · docx vMerge) 글자 순서로는 못 가린다 — 칸 주소로 읽는다."""
    data = minutes_data(attendees=[{"org": "강원대학교", "name": "가"}, {"org": "강원대학교", "name": "나"}, {"org": "한림대학교", "name": "다"}],
                        attendeeCount=5, date="2026. 9. 15. (화) 9:30 ~ 11:00",
                        content=["첫째 문단을 논의하였음.", "둘째 문단을 정하였음."])
    for build, name in ((build_hwpx, "m.hwpx"), (build_docx, "m.docx")):
        path = tmp_path / name
        build(data, str(path))
        got = card.read_minutes(str(path))
        assert got.attendees == [("강원대학교", "가"), ("강원대학교", "나"), ("한림대학교", "다")], name   # 빈 칸 둘은 뺀다
        assert (got.start, got.end) == ("09:30", "11:00"), name
        assert got.agenda == "사업단 운영회의" and got.place == "사업단 회의실" and got.used == D(2026, 9, 15)
        assert got.content == ["첫째 문단을 논의하였음.", "둘째 문단을 정하였음."], name


# ── 계획 · 적요 ──────────────────────────────────────────────────────
def _meeting_item(tmp_path, notice_text="제목 운영회의 회의비\n예산과목: 기타운영경비\n장소: 사업단 회의실(춘천)", **over):
    period = tmp_path / "26-09(09.09. ~ 10.08.)"
    folder = period / "기타운영경비 0915 사업단 운영회의"
    touch(folder / "0915 영수증.pdf")
    touch(folder / "회의비 지출 공문.pdf")
    touch(folder / "사진.jpg")
    build_hwpx(minutes_data(**over), str(folder / "2026-09-15 화 운영회의.hwpx"))
    job = card.load_job(str(period), read_text=reader({"0915 영수증.pdf": RECEIPT, "회의비 지출 공문.pdf": notice_text}))
    return job, job.items[0]


def test_meeting_line_prefix_comes_from_the_notice(tmp_path):
    """담당자(2026-10-20): 회의비 줄 적요는 ERP 가 회의록에서 채운 글 앞에 '건별로 공문을 확인하고 공문에 있는 비목' 을 붙인다."""
    job, item = _meeting_item(tmp_path)
    assert item.req_div == "17" and item.notice_code == "09" and item.line_code == "09"
    assert item.prefixed("회의일자:2026-09-15/ 회의장소:사업단 회의실") == "09_회의일자:2026-09-15/ 회의장소:사업단 회의실"
    assert item.prefixed("09_회의일자:…") == "09_회의일자:…" and item.prefixed("") == ""
    job, item = _meeting_item(tmp_path / "b", notice_text="제목 운영회의\n예산과목: 기업지원·협력활동비")
    assert item.code == "09" and item.line_code == "07" and any("공문의 비목(07)" in n for n in item.notes)


def test_plan_shows_who_the_app_types_and_who_the_person_adds(tmp_path):
    job, item = _meeting_item(tmp_path, attendees=[{"org": "강원대학교", "name": "가"}, {"org": "가나다학과", "name": "나"},
                                                    {"org": "한림대학교", "name": "다"}],
                              content=["운영 현황과 일정을 함께 논의하였음.", "다음 회의 날짜를 정하였음."])
    plan = card_erp.plan_item(item, 0, [participants.Member("가", "100001")])
    text = "\n".join(plan.lines)
    assert "회의록등록: 11:00~12:00 · 장소 사업단 회의실" in text
    assert "참여인력: 가(100001)" in text and "내부참석자: 나 · 가나다학과 — 앱이 [행 추가] 창에서 고름(이름 · 소속이 하나일 때)" in text
    assert "외부참석자: 다 · 한림대학교 — 앱이 넣음" in text and "09_" in text
    assert card_erp.attachments(item)[0].endswith("회의비 지출 공문.pdf")          # 공문이 맨 앞, PDF · 그림만
    assert {os.path.basename(p) for p in card_erp.attachments(item)} == {"회의비 지출 공문.pdf", "0915 영수증.pdf", "사진.jpg"}
    _v, _p, missing = card_erp.meeting_plan(item, [])
    assert not missing
    job, short = _meeting_item(tmp_path / "s", content=["짧음."], attendees=[])
    _v, _p, missing = card_erp.meeting_plan(short, [])
    assert "회의내용이 20자보다 짧음" in missing and "참석자 이름" in missing


def test_plan_for_other_and_goods(tmp_path):
    period = tmp_path / "26-09"
    touch(period / "기타운영경비 0920 소프트웨어 구독 33,000원" / "결제.pdf")
    (period / "기타운영경비 0925 사무용품").mkdir(parents=True)
    make_goods(period / "기타운영경비 0925 사무용품" / "구매의뢰.xlsx")
    job = card.load_job(str(period), read_text=reader({}))
    other, goods = job.items
    assert "청구내역: 09_소프트웨어 구독" in card_erp.plan_item(other, 0).lines
    assert any("사람이 넣음" in line for line in card_erp.plan_item(goods, 1).lines)
    assert card_erp.main_summary(job.sheets[0], test_mode=True).startswith("[시험] 09_[그밖의사업운영경비] 카드 결제 건")


def test_plan_for_a_claim_kind_number(tmp_path):
    """폴더 이름의 청구종류 번호(담당자 2026-11-11) — (17) · (85) · (90) 밖의 번호는 앱이 청구구분만 고르고 증빙 창은 사람이."""
    period = tmp_path / "26-09"
    touch(period / "기타운영경비 16 0920 점심 12,000원" / "결제.pdf")
    item = card.load_job(str(period), read_text=reader({})).items[0]
    assert (item.req_div, item.req_div_name) == ("16", "(16) 식대")
    lines = card_erp.plan_item(item, 0).lines
    assert any("(16) 식대: 앱이 청구구분을 고르고" in line for line in lines)
    assert any("증빙이 없으면 09_점심" in line for line in lines)


class EvidenceFrame:
    """증빙 단추 · 붙은 증빙 링크만 흉내 — 사람이 [계속] 을 누르면 증빙이 붙는다."""
    def __init__(self, buttons: bool):
        self.buttons, self.link = buttons, ""

    def evaluate(self, js, arg=None):
        if js == card_erp.EVIDENCE_BUTTONS_JS:
            return self.buttons
        if js == card_erp.LINK_TEXT_JS:
            return self.link
        raise AssertionError(js)


def test_other_claim_kinds_ask_a_person_only_when_evidence_buttons_show():
    item = card.CardItem(folder="x", name="기타운영경비 16 0920 점심", code="09", req_div="16", title="점심")
    asked: list[str] = []
    quiet = EvidenceFrame(buttons=False)
    assert card_erp._evidence_by_person(quiet, item, lambda m: asked.append(m) or True, lambda s: None) == (True, "", False)
    assert asked == []                                                          # 증빙 단추가 없으면 (90) 처럼
    frame = EvidenceFrame(buttons=True)

    def person(message):
        asked.append(message)
        frame.link = "식대:점심"                                                # 사람이 증빙 창을 작성했다
        return True

    ok, _why, needs = card_erp._evidence_by_person(frame, item, person, lambda s: None)
    assert (ok, needs, len(asked)) == (True, True, 1)                          # 한 번 묻고, 증빙이 붙어 이어 간다
    assert "(16) 식대" in asked[0] and "[신규등록]" in asked[0]
    stopped = EvidenceFrame(buttons=True)
    ok, why, needs = card_erp._evidence_by_person(stopped, item, lambda m: False, lambda s: None)
    assert (ok, needs) == (False, True) and "멈춤" in why


# ── 이 청구서인지 · 기록 ───────────────────────────────────────────────
class FakeFrame:
    def __init__(self, **values):
        self.values = values

    def evaluate(self, js, arg=None):
        assert js == STATE_JS
        return {k: {"tag": "input", "value": self.values.get(k, "")} for k in arg}


def test_sheet_owner_new_same_number_or_same_summary():
    sheet = card.CardSheet("09", D(2026, 9, 9), D(2026, 10, 8))
    summary = sheet.main_summary
    assert card_erp.sheet_owner(FakeFrame(), sheet, summary)[0]                                    # 새 카드청구서
    ok, why = card_erp.sheet_owner(FakeFrame(REQ_CNT="335", APPR_DIV_CD="40"), sheet, summary)
    assert not ok and "335" in why                                                                  # 남의 청구서
    sheet.req_cnt = "335"
    assert card_erp.sheet_owner(FakeFrame(REQ_CNT="335", APPR_DIV_CD="40"), sheet, summary)[0]     # 이 청구서(결의번호)
    sheet.req_cnt = ""
    assert card_erp.sheet_owner(FakeFrame(REQ_CNT="336", APPR_DIV_CD="40", APPL_CONT=summary), sheet, summary)[0]


def test_record_and_restore_saved_items(tmp_path):
    period = tmp_path / "26-09"
    touch(period / "기타운영경비 0920 소프트웨어 구독 33,000원" / "결제.pdf")
    touch(period / "기타운영경비 0921 도메인 연장 22,000원" / "결제.pdf")
    job = card.load_job(str(period), read_text=reader({}))
    sheet = job.sheets[0]
    report = card_erp.CardReport(dry_run=False, summary=sheet.main_summary, req_cnt="335",
                                 results=[card_erp.ItemResult(0, sheet.items[0].name, "saved")])
    sheet.items[0].status = "saved"
    card_erp.record_sheet(job, sheet, report)
    again = card.load_job(str(period), read_text=reader({}))
    card_erp.restore(again)
    assert again.sheets[0].req_cnt == "335"
    assert [i.status for i in again.sheets[0].items] == ["saved", ""]


def test_dry_run_plans_every_item_without_a_browser(tmp_path):
    job, item = _meeting_item(tmp_path)
    report = card_erp.run(None, None, job, job.sheets[0], lambda _m: None, ask=lambda _m: False, dry_run=True)
    assert report.dry_run and [r.status for r in report.results] == ["planned"] and not report.blocked
    assert report.lines()[0] == "미리 보기 (ERP 에 넣지 않음)"


# ── 회의록등록 창의 참석자 표 (실측 2026-11-11 11:34 의 모양 — 이름 · 번호는 가짜) ──────────────────────────
MINUTES_WINDOW = """<html><body>
<input id="CFRC_ST_DTM" class="text" value=""><input id="CFRC_END_DTM" class="text" value="">
<input id="IN_COUNT" value="0" readonly><input id="EMP_COUNT" value="1" readonly><input id="OUT_COUNT" value="1">
<table id="rtaskTb"><thead><tr><th></th><th>사번/학번*</th><th>성명*</th><th>소속*</th><th>참여기간</th></tr></thead><tbody>
  <tr style="display:none"><td><input type="checkbox" name="supOrgChk"></td><td><input name="CFRC_IN_EMP_NO" readonly></td>
      <td><input name="CFRC_IN_EMP_NM" readonly></td><td><input name="DEPT_NM"></td></tr></tbody></table>
<table id="rtaskTb1"><thead><tr><th></th><th>사번/학번*</th><th>성명*</th><th>소속*</th></tr></thead><tbody>
  <tr style="display:none"><td><input type="checkbox" name="supOrgChk1"></td><td><input name="CFRC_IN_EMP_NO" readonly></td>
      <td><input name="CFRC_OUT_EMP_NM"><input type="button" name="btnEmpInfo"></td><td><input name="DEPT_NM"></td></tr>
  <tr class="generated"><td><input type="checkbox" name="supOrgChk1"></td><td><input name="CFRC_IN_EMP_NO" value="100002" readonly></td>
      <td><input name="CFRC_OUT_EMP_NM" value="나"><input type="button" name="btnEmpInfo"></td><td><input name="DEPT_NM" value="가나다학과"></td></tr>
</tbody></table>
<input type="button" id="btnRowAdd2" value="행 추가" onclick="add()">
<table id="rtaskTb2"><thead><tr><th></th><th>성명*</th><th>소속*</th></tr></thead><tbody>
  <tr id="tpl" style="display:none"><td><input type="checkbox" name="supOrgChk2"></td><td><input name="CFRC_OUT_EMP_NM" class="text dynamic-input"></td>
      <td><input name="DEPT_NM" class="text dynamic-input"></td></tr>
  <tr class="generated"><td><input type="checkbox" name="supOrgChk2"></td><td><input name="CFRC_OUT_EMP_NM" class="text dynamic-input"></td>
      <td><input name="DEPT_NM" class="text dynamic-input"></td></tr>
</tbody></table>
<script>
window.adds = 0;
function add() { window.adds++; const tr = document.getElementById('tpl').cloneNode(true); tr.removeAttribute('id'); tr.style.display = '';
  tr.className = 'generated'; document.querySelector('#rtaskTb2 tbody').appendChild(tr);
  const c = document.getElementById('OUT_COUNT'); c.value = String(parseInt(c.value || '0') + 1); }
</script></body></html>"""


def test_missing_inside_people_are_named_whichever_table_they_are_in():
    inside = [participants.Attendee("가", kind="part", emp_no="100001"), participants.Attendee("나", org="가나다학과", kind="internal")]
    on = [{"kind": "internal", "name": "나", "no": "100002"}]
    left = card_erp._missing_inside(inside, on)
    assert [p.name for p in left] == ["가"]
    assert card_erp._inside_request(left) == "참여인력 [행 추가]: 가(100001)"
    assert card_erp._missing_inside(inside, on + [{"kind": "internal", "name": "가 ", "no": ""}]) == []   # 내부참석자 표에 넣어도 든 것
    assert "사람 찾기 창에서(여러 명을 한 번에): 나 · 가나다학과" in card_erp._inside_request(inside)


def test_minutes_window_names_and_the_empty_external_row_in_a_browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    executable = os.environ.get("CHROMIUM_PATH", "/opt/pw-browsers/chromium")
    try:
        with sync_api.sync_playwright() as p:
            browser = p.chromium.launch(executable_path=executable if os.path.exists(executable) else None)
            page = browser.new_page()
            page.set_content(MINUTES_WINDOW)
            assert page.evaluate(card_erp.INSIDE_NAMES_JS) == [{"kind": "internal", "name": "나", "no": "100002"}]   # 숨은 본뜸 줄은 빼고
            assert page.evaluate(card_erp.EXTERNAL_EMPTY_JS) == 1
            people = [participants.Attendee("다", org="한림대학교", kind="external"), participants.Attendee("라", org="가나 주식회사", kind="external")]
            added = card_erp._add_externals(page, people, lambda _m: None, lambda s: page.wait_for_timeout(int(s * 1000)))
            assert added == 2 and page.evaluate("window.adds") == 1        # 처음부터 있던 빈 줄을 먼저 채우고 [행 추가] 는 한 번만
            assert card_erp._external_names(page) == ["다", "라"]
            assert page.evaluate(card_erp.EXTERNAL_EMPTY_JS) == 0
            assert card_erp._add_externals(page, people[:1], lambda _m: None, lambda s: None) == 1 and page.evaluate("window.adds") == 1
            browser.close()
    except Exception as error:  # noqa: BLE001 — 브라우저가 없는 곳(CI)
        if "Executable doesn't exist" in str(error) or "BrowserType.launch" in str(error):
            pytest.skip(f"브라우저 없음: {str(error).splitlines()[0][:80]}")
        raise


# ── 사람 찾기 창 두 개 (실측 2026-11-11 14:03 ~ 14:06 의 모양 — 이름 · 번호는 가짜) ─────────────────────────────
def test_choose_part_needs_one_row_and_the_same_emp_no():
    rows = [{"k_EMP_NO": "100001", "k_EMP_NM": "가"}, {"k_EMP_NO": "100002", "k_EMP_NM": "나"}, {"k_EMP_NO": "100003", "k_EMP_NM": "나"}]
    assert attendees.choose_part(rows, participants.Attendee("가", kind="part", emp_no="100001"))[0] == 0
    assert attendees.choose_part(rows, participants.Attendee("가", kind="part", emp_no="999999"))[0] is None
    assert attendees.choose_part(rows, participants.Attendee("나", kind="part"))[1] == "같은 이름이 2줄"
    assert attendees.choose_part(rows, participants.Attendee("다", kind="part"))[1] == attendees.NOT_LISTED


def test_choose_person_uses_org_then_active_status_and_never_a_lone_inactive_row():
    def row(no, name, sts, dept, up=""):
        return {"k_EMP_NO": no, "k_EMP_NM": name, "k_WORK_STS_NM": sts, "k_DEPT_NM": dept, "k_UP_DEPT_NM": up}

    rows = [row("19910001", "라", "제적", "가나다학과_1991"), row("200001", "라", "재직(직원)", "산학협력단_근로계약자", "산학협력단"),
            row("202400001", "라", "재학(학생)", "마바사학과", "공과대학")]
    index, why, by_name = attendees.choose_person(rows, participants.Attendee("라", org="마바사학과", kind="internal"))
    assert index == 2 and not by_name                                         # 소속이 맞는 사람 하나
    assert attendees.choose_person(rows, participants.Attendee("라", org="강원대학교", kind="internal"))[0] is None   # 재직 · 재학 둘
    assert attendees.choose_person(rows[:1], participants.Attendee("라", kind="internal"))[0] is None                # 제적 하나뿐 — 안 고른다
    index, why, by_name = attendees.choose_person(rows[:2], participants.Attendee("라", kind="internal"))
    assert index == 1 and by_name                                                                                   # 이름으로만 — 확인할 것
    assert attendees.choose_person(rows, participants.Attendee("라", org="자차카학과", kind="internal"))[0] is None
    assert attendees.choose_person(rows, participants.Attendee("라", kind="part", emp_no="200001"))[0] == 1          # 직번으로 찾은 것


PART_WINDOW = """<html><body>
<input id="EMP_NM"><input type="button" id="btn_search" value="검색" onclick="search()">
<div class="jgrid-viewport" style="height:300px;overflow:auto"><div id="grid"></div></div>
<a id="btnItem" href="javascript:" onclick="ok()">확인</a> <a href="javascript:" style="display:none">선택없음</a>
<input type="hidden" id="RTN_FUNC" value="uf_rcomm_0071_02Params"><input type="hidden" id="CHK_GB" value="2">
<script>
const all = [['100001', '가', '가나다학과'], ['100002', '나', '가나다학과'], ['100004', '바', '산학협력단']];
let shown = all;
function draw() { document.getElementById('grid').innerHTML = shown.map((p, i) =>
  '<div class="jgrid-row" r="' + i + '"><input type="checkbox" class="checkmg"><span class="k_EMP_NO" title="' + p[0] + '">' + p[0] +
  '</span> <span class="k_EMP_NM">' + p[1] + '</span> <span class="k_BLNG_DEPT_NM">' + p[2] + '</span></div>').join(''); }
function search() { const q = document.getElementById('EMP_NM').value.trim(); shown = all.filter(p => !q || p[1] === q); setTimeout(draw, 100); }
function ok() { const picked = Array.from(document.querySelectorAll('.jgrid-row')).filter(r => r.querySelector('input').checked)
    .map(r => shown[+r.getAttribute('r')]);
  if (!picked.length) { alert('선택된 내역이 없습니다.'); return; } window.opener.addPart(picked); window.close(); }
draw();
</script></body></html>"""

MULTI_WINDOW = """<html><body>
<input id="SEARCH_NM" value=""><input type="button" id="btn_search" value="검색" onclick="search()">
<div class="jgrid-viewport" style="height:300px;overflow:auto"><div id="grid"></div></div>
<table id="basket"><tr><th>성명*</th><th>소속*</th></tr></table>
<a href="#none" onclick="ok()">확인</a> <a href="#none" style="display:none">선택없음</a> <a href="#none" style="display:none">외부인 등록</a>
<input type="hidden" id="RTN_FUNC" value="uf_rcomm_0008_04Params_multi"><input type="hidden" id="RTN_TYPE" value="M">
<script>
const all = [['19910001', '라', '제적', '가나다학과_1991'], ['200001', '라', '재직(직원)', '산학협력단_근로계약자'],
             ['202400001', '라', '재학(학생)', '마바사학과'], ['100009', '마', '재직(직원)', '가나다학과'], ['300001', '사', '졸업', '아자학과']];
let shown = [];
function draw() { document.getElementById('grid').innerHTML = shown.map((p, i) =>
  '<div class="jgrid-row" r="' + i + '"><input type="checkbox" class="checkmg" onclick="pick(' + i + ', this)"><span class="k_EMP_NO">' + p[0] +
  '</span> <span class="k_EMP_NM">' + p[1] + '</span> <span class="k_WORK_STS_NM">' + p[2] + '</span> <span class="k_DEPT_NM">' + p[3] + '</span></div>').join(''); }
function search() { const q = document.getElementById('SEARCH_NM').value.trim(); shown = all.filter(p => p[1] === q || p[0] === q); setTimeout(draw, 100); }
function pick(i, box) { if (!box.checked) return; const p = shown[i];
  setTimeout(() => { const tr = document.createElement('tr');   // 고른 사람 표에는 조금 뒤에 쌓인다(실측)
    tr.innerHTML = '<td>' + p[1] + '<input type="hidden" name="CFRC_IN_EMP_NO" value="' + p[0] + '"></td><td>' + p[3] + '</td>';
    document.getElementById('basket').appendChild(tr); }, 300); }
function ok() { const picked = Array.from(document.querySelectorAll('input[name=CFRC_IN_EMP_NO]')).map(e => all.find(p => p[0] === e.value));
  window.opener.addInternal(picked); window.close(); }
draw();
</script></body></html>"""

FINDER_BUTTONS = (
    "<input type='button' id='btnRowAdd' value='행 추가' onclick=\"window.open('http://erp.test/part', 'part', 'width=700,height=500')\">\n"
    "<input type='button' id='btnRowAdd1' value='행 추가' onclick=\"window.open('http://erp.test/multi', 'multi', 'width=700,height=500')\">\n")
ADD_ROWS_JS = """
function addPart(list) { for (const p of list) { const tr = document.createElement('tr'); tr.className = 'generated';
  tr.innerHTML = '<td><input type="checkbox" name="supOrgChk"></td><td><input name="CFRC_IN_EMP_NO" value="' + p[0] + '" readonly></td>' +
    '<td><input name="CFRC_IN_EMP_NM" value="' + p[1] + '" readonly></td><td><input name="DEPT_NM" value="' + p[2] + '"></td>';
  document.querySelector('#rtaskTb tbody').appendChild(tr); } }
function addInternal(list) { for (const p of list) { const tr = document.createElement('tr'); tr.className = 'generated';
  tr.innerHTML = '<td><input type="checkbox" name="supOrgChk1"></td><td><input name="CFRC_IN_EMP_NO" value="' + p[0] + '" readonly></td>' +
    '<td><input name="CFRC_OUT_EMP_NM" value="' + p[1] + '"><input type="button" name="btnEmpInfo"></td><td><input name="DEPT_NM" value="' + p[3] + '"></td>';
  document.querySelector('#rtaskTb1 tbody').appendChild(tr); } }
</script></body></html>"""
MINUTES_WITH_FINDERS = (MINUTES_WINDOW.replace('<input type="button" id="btnRowAdd2"', FINDER_BUTTONS + '<input type="button" id="btnRowAdd2"', 1)
                        .replace("</script></body></html>", ADD_ROWS_JS))


def test_attendees_are_picked_in_the_two_finder_windows_only_when_certain():
    sync_api = pytest.importorskip("playwright.sync_api")
    executable = os.environ.get("CHROMIUM_PATH", "/opt/pw-browsers/chromium")
    pages = {"http://erp.test/minutes": MINUTES_WITH_FINDERS, "http://erp.test/part": PART_WINDOW, "http://erp.test/multi": MULTI_WINDOW}
    try:
        with sync_api.sync_playwright() as p:
            browser = p.chromium.launch(executable_path=executable if os.path.exists(executable) else None)
            context = browser.new_context()
            context.route("http://erp.test/**", lambda route: route.fulfill(status=200, content_type="text/html; charset=utf-8",
                                                                            body=pages[route.request.url]))
            context.on("dialog", lambda d: d.dismiss())
            minutes = context.new_page()
            minutes.goto("http://erp.test/minutes")
            people = [participants.Attendee("가", "가나다학과", "part", "100001"),       # 참여인력 목록에서 직번 · 이름
                      participants.Attendee("라", "마바사학과", "internal"),              # 같은 이름 셋 중 소속이 맞는 하나
                      participants.Attendee("마", "", "part", "100009"),                 # 참여인력 목록에 없음 → 인적정보에서 직번으로
                      participants.Attendee("사", "", "internal"),                       # 졸업 하나뿐 — 안 고른다
                      participants.Attendee("자", "", "internal", note="참여연구원 명단에 같은 이름이 2명")]
            wait = lambda s: minutes.wait_for_timeout(int(s * 1000))  # noqa: E731
            lines: list[str] = []
            names = lambda: [x["name"] for x in card_erp._inside_names(minutes)]  # noqa: E731
            report = attendees.add(minutes, people, lines.append, wait, names)
            assert report.added == ["가", "라", "마"]
            assert set(report.left) == {"사", "자"} and "재직 · 재학이 아님" in report.left["사"]
            assert lines and not any(n in line for line in lines for n in ("100001", "100009", "202400001", "마바사학과"))   # 기록에 사번 · 소속 없음
            assert all("번째 사람" in line for line in lines if "✓" in line or "✗" in line)                               # 사람은 차례로만
            assert any("마: 참여인력 목록에 없어 내부참석자로" in r for r in report.review)
            on = card_erp._inside_names(minutes)
            assert [(x["kind"], x["name"], x["no"]) for x in on] == [("part", "가", "100001"), ("internal", "나", "100002"),
                                                                        ("internal", "라", "202400001"), ("internal", "마", "100009")]
            assert len(context.pages) == 1                             # 못 고른 사람의 창도 닫았다
            left = card_erp._missing_inside(people[:4], on)
            assert [x.name for x in left] == ["사"]
            assert "사 (같은 이름 1명이 모두 재직 · 재학이 아님" in card_erp._inside_request(left, report.left)
            browser.close()
    except Exception as error:  # noqa: BLE001 — 브라우저가 없는 곳(CI)
        if "Executable doesn't exist" in str(error) or "BrowserType.launch" in str(error):
            pytest.skip(f"브라우저 없음: {str(error).splitlines()[0][:80]}")
        raise
