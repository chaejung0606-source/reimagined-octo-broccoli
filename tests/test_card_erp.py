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
    assert "참여인력: 가(100001)" in text and "내부참석자: 나 · 가나다학과 — 앱이 [행 추가] 창에서 고름(학번 · 사번이 있으면 번호로 먼저, 없으면 이름 · 소속이 하나일 때)" in text
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
    assert card_erp._missing_inside(inside, on + [{"kind": "internal", "name": "가 ", "no": ""}]) == []   # 내부참석자 표에 넣어도 든 것


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
            browser.close()
    except Exception as error:  # noqa: BLE001 — 브라우저가 없는 곳(CI)
        if "Executable doesn't exist" in str(error) or "BrowserType.launch" in str(error):
            pytest.skip(f"브라우저 없음: {str(error).splitlines()[0][:80]}")
        raise


# ── 증빙의 학번 · 사번으로 먼저 찾기 (담당자 2026-11-11) ─────────────────────────────────────────────
def test_minutes_table_takes_numbers_out_of_the_name_cell(tmp_path):
    """회의록 이름 칸에 '이름(학번)' 으로 적었으면 번호를 떼어 내 ERP 에서 번호로 먼저 찾는다 — 이름 칸에는 이름만."""
    data = minutes_data(attendees=[{"org": "강원대학교", "name": "가(202600001)"}, {"org": "가나다학과", "name": "나"}])
    for build, name in ((build_hwpx, "m.hwpx"), (build_docx, "m.docx")):
        path = tmp_path / name
        build(data, str(path))
        got = card.read_minutes(str(path))
        assert got.attendees == [("강원대학교", "가"), ("가나다학과", "나")], name
        assert got.numbers == {"가": "202600001"} and got.number_from == {"가": "회의록 표"}, name


def test_sign_sheet_numbers_are_used_to_find_people_first(tmp_path):
    """결제 건 폴더의 서명부 PDF 에 '이름 학번' 이 같은 줄에 있으면 그 번호 — 계획에 어디서 읽었는지 보이고, 참석자는 그 번호로 찾는다."""
    period = tmp_path / "26-09(09.09. ~ 10.08.)"
    folder = period / "기타운영경비 0915 사업단 운영회의"
    touch(folder / "0915 영수증.pdf")
    touch(folder / "회의 서명부.pdf")
    build_hwpx(minutes_data(attendees=[{"org": "강원대학교", "name": "가가"}, {"org": "가나다학과", "name": "나나"},
                                       {"org": "한림대학교", "name": "다다"}]), str(folder / "2026-09-15 화 운영회의.hwpx"))
    sheet = "연번 소속 성명 학번 서명\n1 가나다학과 나나 202600002 (서명)\n2 한림대학교 다다 202699999\n3 강원대학교 가가"
    job = card.load_job(str(period), read_text=reader({"0915 영수증.pdf": RECEIPT, "회의 서명부.pdf": sheet}))
    m = job.items[0].meeting
    assert m.numbers == {"나나": "202600002", "다다": "202699999"} and m.number_from["나나"] == "회의 서명부.pdf"
    _v, people, _missing = card_erp.meeting_plan(job.items[0], [participants.Member("가가", "100001")])
    assert [(p.name, p.kind, p.emp_no) for p in people] == [("가가", "part", "100001"), ("나나", "internal", "202600002"),
                                                            ("다다", "external", "")]     # 외부참석자는 ERP 에서 찾지 않는다(글로 넣음)
    plan = card_erp.plan_item(job.items[0], 0, [participants.Member("가가", "100001")])
    inside = next(e for e in plan.entries if e.label == "내부참석자")
    assert "학번 · 사번: 회의 서명부.pdf" in inside.source and "번호로 먼저" in inside.source


def test_classify_uses_the_evidence_number_before_the_name():
    members = [participants.Member("라", "200001"), participants.Member("라", "200002"), participants.Member("가", "100001")]
    numbers = {"라": "200002", "가": "202600009", "신": "202600005", "외": "202600006"}
    got = participants.classify([("", "라"), ("", "가"), ("", "신"), ("한림대학교", "외"), ("", "무")], members, numbers,
                                {"신": "서명부.pdf"})
    by = {p.name: p for p in got}
    assert (by["라"].kind, by["라"].emp_no, by["라"].note) == ("part", "200002", "")        # 동명이인이어도 번호로 한 사람
    assert (by["가"].kind, by["가"].emp_no) == ("internal", "202600009") and "참여연구원 명단의 같은 이름" in by["가"].hint
    assert (by["신"].kind, by["신"].emp_no, by["신"].no_from) == ("internal", "202600005", "서명부.pdf")
    assert (by["외"].kind, by["외"].emp_no) == ("external", "")
    assert (by["무"].kind, by["무"].emp_no) == ("internal", "")
    # 번호가 없으면 전처럼 — 명단의 같은 이름이 둘이면 사람에게
    assert participants.classify([("", "라")], members)[0].note.startswith("참여연구원 명단에 같은 이름이 2명")


def test_finder_windows_search_by_number_first_then_by_name():
    sync_api = pytest.importorskip("playwright.sync_api")
    executable = os.environ.get("CHROMIUM_PATH", "/opt/pw-browsers/chromium")
    pages = {"http://erp.test/minutes": MINUTES_WITH_FINDERS, "http://erp.test/part": PART_WINDOW, "http://erp.test/multi": MULTI_WINDOW}
    try:
        with sync_api.sync_playwright() as p:
            browser = p.chromium.launch(executable_path=executable if os.path.exists(executable) else None)
            context = browser.new_context()
            # 검색 칸에 넣은 말을 회의록등록 창에 모은다 — 번호가 먼저인지
            record = "function search() { const q0 = (document.getElementById('SEARCH_NM') || document.getElementById('EMP_NM')).value.trim(); " \
                     "(window.opener.qs = window.opener.qs || []).push(q0); "
            pages = {url: body.replace("function search() { ", record, 1) for url, body in pages.items()}
            context.route("http://erp.test/**", lambda route: route.fulfill(status=200, content_type="text/html; charset=utf-8",
                                                                            body=pages[route.request.url]))
            context.on("dialog", lambda d: d.dismiss())
            minutes = context.new_page()
            minutes.goto("http://erp.test/minutes")
            people = [participants.Attendee("바", "", "part", "100004", no_from=participants.ROSTER),      # 목록 그대로에서 직번으로 — 검색 없이
                      participants.Attendee("마", "", "internal", "100009", no_from="서명부.pdf"),         # 인적정보조회에서 번호로
                      participants.Attendee("라", "마바사학과", "internal", "999999", no_from="서명부.pdf")]  # 번호로 0줄 → 이름 · 소속으로
            wait = lambda s: minutes.wait_for_timeout(int(s * 1000))  # noqa: E731
            lines: list[str] = []
            names = lambda: [x["name"] for x in card_erp._inside_names(minutes)]  # noqa: E731
            report = attendees.add(minutes, people, lines.append, wait, names)
            assert report.added == ["바", "마", "라"]
            assert minutes.evaluate("window.qs") == ["100009", "999999", "라"]   # 참여인력선택은 검색하지 않았다(목록 그대로에서 직번)
            assert any("직번 · 목록 그대로" in line for line in lines) and any("인적정보 찾기(번호)" in line for line in lines)
            assert any(r.startswith("라: 증빙(서명부.pdf)의 학번 · 사번으로는 찾지 못해 이름으로 골랐습니다") for r in report.review)
            assert not any(n in line for line in lines for n in ("100004", "100009", "999999", "202400001"))   # 기록에 번호 없음
            on = card_erp._inside_names(minutes)
            assert [(x["kind"], x["name"], x["no"]) for x in on] == [("part", "바", "100004"), ("internal", "나", "100002"),   # 나: 처음부터 있던 줄
                                                                        ("internal", "마", "100009"), ("internal", "라", "202400001")]
            browser.close()
    except Exception as error:  # noqa: BLE001 — 브라우저가 없는 곳(CI)
        if "Executable doesn't exist" in str(error) or "BrowserType.launch" in str(error):
            pytest.skip(f"브라우저 없음: {str(error).splitlines()[0][:80]}")
        raise


def _server(pages: dict):
    """모의 ERP 응답 — Playwright 는 처리기의 인자가 둘이면 요청을 둘째로 넘기므로 인자 하나짜리 함수로."""
    def serve(route):
        route.fulfill(status=200, content_type="text/html; charset=utf-8", body=pages[route.request.url])
    return serve


def test_internal_attendee_is_checked_with_the_mouse_and_never_confirmed_with_an_empty_basket():
    """2026-11-11 20:18 실제: 인적정보조회에서 화면 스크립트로 누른 체크가 '고른 사람' 표에 쌓이지 않아 [확인] 에 '선택된 내역이 없습니다' —
    내부참석자를 하나도 못 넣었다. 이제 사람처럼 마우스로 체크하고(진짜 입력만 받는 창도 됨), 표가 비면 [확인] 을 누르지 않고 까닭을 남긴다."""
    sync_api = pytest.importorskip("playwright.sync_api")
    executable = os.environ.get("CHROMIUM_PATH", "/opt/pw-browsers/chromium")
    click = "onclick=\"pick(' + i + ', this)\""
    trusted = MULTI_WINDOW.replace(click, "onclick=\"if (event.isTrusted) pick(' + i + ', this)\"")
    never = MULTI_WINDOW.replace(click, "")
    assert trusted != MULTI_WINDOW and never != MULTI_WINDOW
    try:
        with sync_api.sync_playwright() as p:
            browser = p.chromium.launch(executable_path=executable if os.path.exists(executable) else None)
            for window, picked in ((trusted, True), (never, False)):
                pages = {"http://erp.test/minutes": MINUTES_WITH_FINDERS, "http://erp.test/part": PART_WINDOW, "http://erp.test/multi": window}
                context = browser.new_context()
                context.route("http://erp.test/**", _server(pages))
                alerts: list[str] = []
                context.on("dialog", lambda d: (alerts.append(d.message), d.dismiss()))
                minutes = context.new_page()
                minutes.goto("http://erp.test/minutes")
                wait = lambda s, m=minutes: m.wait_for_timeout(int(s * 1000))  # noqa: E731
                lines: list[str] = []
                names = lambda m=minutes: [x["name"] for x in card_erp._inside_names(m)]  # noqa: E731
                report = attendees.add(minutes, [participants.Attendee("라", "마바사학과", "internal")], lines.append, wait, names)
                if picked:
                    assert report.added == ["라"] and alerts == []
                else:
                    assert report.added == [] and "'고른 사람' 표에 들어가지 않음" in report.left["라"] and alerts == []   # [확인] 을 누르지 않았다
                    assert any("체크된 줄 1 · 고른 사람 칸 0" in line for line in lines)
                    assert len(context.pages) == 1                                   # 그 창은 닫았다
                context.close()
            browser.close()
    except Exception as error:  # noqa: BLE001 — 브라우저가 없는 곳(CI)
        if "Executable doesn't exist" in str(error) or "BrowserType.launch" in str(error):
            pytest.skip(f"브라우저 없음: {str(error).splitlines()[0][:80]}")
        raise


# ── 회의비 · 다과비 1인 한도와 다과비 칸 (담당자 2026-11-11) ─────────────────────────────────────────────
def test_need_heads_is_cost_over_the_per_person_limit_rounded_up():
    """16만원이면 4명 이상(1인 5만원). 한도가 없으면 따지지 않는다."""
    assert card_erp.need_heads(160000, 50000) == 4
    assert card_erp.need_heads(150000, 50000) == 3 and card_erp.need_heads(150001, 50000) == 4
    assert card_erp.need_heads(30000, 50000) == 1
    assert card_erp.need_heads(0, 50000) == 0 and card_erp.need_heads(160000, 0) == 0


def test_choose_any_skips_people_already_in_the_tables_inactive_rows_and_other_periods():
    rows = [{"k_EMP_NO": "100001", "k_EMP_NM": "가", "k_WORK_STS_NM": "재직(직원)"},
            {"k_EMP_NO": "100002", "k_EMP_NM": "나", "k_WORK_STS_NM": "퇴직"},
            {"k_EMP_NO": "100003", "k_EMP_NM": "다", "k_PART_TRM_DT": "2025-03-01 ~ 2026-02-28"},
            {"k_EMP_NO": "100004", "k_EMP_NM": "라", "k_PART_TRM_DT": "2026-03-01 ~ 2027-02-28"},
            {"k_EMP_NO": "100004", "k_EMP_NM": "라"},                       # 같은 사람 두 줄
            {"k_EMP_NO": "100005", "k_EMP_NM": "마"},
            {"k_EMP_NO": "100006", "k_EMP_NM": "바"}]
    day = D(2026, 10, 12)
    assert attendees.choose_any(rows, 5, ["가"], day=day) == [3, 5, 6]          # 가: 이미 있음 · 나: 퇴직 · 다: 참여기간 밖 · 라 둘째 줄: 같은 사람
    assert attendees.choose_any(rows, 2, [], taken_nos=["100001"], day=day) == [3, 5]
    assert attendees.choose_any(rows, 9, [], day=None) == [0, 2, 3, 5, 6]      # 회의일을 모르면 참여기간은 안 본다
    assert attendees.choose_any(rows, 0, []) == []


def test_snack_is_read_from_folder_minutes_then_shop_name():
    m = card.Minutes(merchant="가나다 식당", agenda="운영 회의", content=["다과를 곁들여 운영 현황을 논의하였음."])
    assert card.snack_of("09_ 1015 다과 운영회의", None, "") == (True, "폴더 이름")
    assert card.snack_of("09_ 1015 식비 운영회의", m, "스타벅스 춘천점") == (False, "폴더 이름")     # 사람이 적은 것이 먼저
    assert card.snack_of("09_ 1015 운영회의", m, "가나다 식당") == (True, "회의록")
    assert card.snack_of("09_ 1015 운영회의", card.Minutes(content=["식사와 다과"]), "") == (False, "")    # 둘 다 있으면 모름
    assert card.snack_of("09_ 1015 운영회의", None, "스타벅스 춘천점") == (True, "가맹점 '스타벅스 춘천점'")
    assert card.snack_of("09_ 1015 운영회의", None, "가나다 식당") == (False, "")


def test_plan_says_snack_and_arbitrary_people_for_the_per_person_limit(tmp_path):
    job, item = _meeting_item(tmp_path, attendees=[{"org": "강원대학교", "name": "가"}, {"org": "가나다학과", "name": "나"}],
                              content=["운영 현황과 일정을 함께 논의하였음.", "다음 회의 날짜를 정하였음."])
    item.amount, item.snack, item.snack_from = 160000, True, "폴더 이름"
    plan = card_erp.plan_item(item, 0, [])
    text = "\n".join(plan.lines)
    assert "다과비(폴더 이름) — 회의록등록 창에서 식비청구 '아니오' · 회의비(다과)(B) 160,000원" in text
    assert "1인 50,000원 한도로 4명 이상 필요 — 회의록 2명, 2명은 참여인력에서 임의로 넣고 저장(확인 필요)" in text
    assert any("2명을 참여인력에서 임의로 넣음" in r for r in plan.review)


CARD_FORM = """<html><body>
<input id="REQ_PTCL" value=""><span id="REQ_DIV_LNK"></span>
<input type="button" id="btn_addEvid2" value="신규등록" onclick="window.open('http://erp.test/minutes', 'mw', 'width=900,height=700')">
<script>function fn_evidCallback(t) { document.getElementById('REQ_PTCL').value = t; document.getElementById('REQ_DIV_LNK').textContent = t; }</script>
</body></html>"""

MEETING_FIELDS = """
<input id="CFRC_DT" class="text dis" value="2026-10-12" readonly><input id="WEEKEND" value="월요일" readonly>
<input id="CFRC_PLCE" class="text"><textarea id="CFRC_PURS"></textarea><textarea id="CFRC_CONT"></textarea><input id="RMK" class="text">
<input type="hidden" id="CARD_ADDR" value="강원 춘천시 가나다로 1">
<label><input type="radio" id="MEAL_REQ_YN_1" name="MEAL_REQ_YN" class="radio" checked>예</label>
<label><input type="radio" id="MEAL_REQ_YN_2" name="MEAL_REQ_YN" class="radio">아니오</label>
<input id="MEAL_COST" class="text num" value="160,000" onkeyup="sum()"><input id="SNACK_COST" class="text num" onkeyup="sum()">
<input id="MEAL_SNACK_COST" class="text num dis" value="160,000" readonly>
<input type="hidden" id="CFRC_LIMITED_YN" value="Y"><input type="hidden" id="CFRC_LIMITED_AMT" value="50000">
<a id="save" name="save" href="javascript:" onclick="save()">저장</a>
"""
MEETING_SCRIPT = """
function num(v) { return parseInt(String(v || '').replace(/[^0-9]/g, '') || '0'); }
function sum() { MEAL_SNACK_COST.value = (num(MEAL_COST.value) + num(SNACK_COST.value)).toLocaleString(); }
function heads() { return document.querySelectorAll('#rtaskTb tr.generated, #rtaskTb1 tr.generated').length +
  Array.from(document.querySelectorAll('#rtaskTb2 tr.generated input[name=CFRC_OUT_EMP_NM]')).filter(e => e.value.trim()).length; }
function save() { if (!confirm('저장하시겠습니까?')) return;
  if (num(MEAL_SNACK_COST.value) / heads() > num(CFRC_LIMITED_AMT.value)) { alert('1인당 회의비가 한도를 넘습니다.'); return; }
  opener.saved = {heads: heads(), meal: num(MEAL_COST.value), snack: num(SNACK_COST.value), no: MEAL_REQ_YN_2.checked};
  opener.fn_evidCallback('회의일자:20261012/ 회의장소:' + CFRC_PLCE.value); window.close(); }
</script></body></html>"""
MEETING_WINDOW = (MINUTES_WITH_FINDERS.replace('<input type="button" id="btnRowAdd2"', MEETING_FIELDS + '<input type="button" id="btnRowAdd2"', 1)
                  .replace("</script></body></html>", MEETING_SCRIPT))


def test_snack_and_per_person_limit_fill_arbitrary_participants_and_save_without_asking():
    """다과비 16만원 · 회의록 참석자 넷 중 하나(졸업한 사람)를 못 정함 — 식비청구 '아니오' · 다과 칸에 금액, 참여인력에서 한 명을 임의로 채워
    4명으로 저장하고, 못 정한 사람 · 임의로 넣은 사람을 '확인 필요' 로 남긴다. 노란 띠로 묻지 않는다."""
    sync_api = pytest.importorskip("playwright.sync_api")
    executable = os.environ.get("CHROMIUM_PATH", "/opt/pw-browsers/chromium")
    pages = {"http://erp.test/card": CARD_FORM, "http://erp.test/minutes": MEETING_WINDOW, "http://erp.test/part": PART_WINDOW,
             "http://erp.test/multi": MULTI_WINDOW}
    item = card.CardItem(folder="x", name="09_ 1012 다과 운영회의", code="09", used=D(2026, 10, 12), amount=160000, req_div="17",
                         snack=True, snack_from="폴더 이름", meeting_region="춘천",
                         meeting=card.Minutes(start="10:00", end="11:00", place="사업단 회의실", agenda="운영 회의",
                                              content=["사업단 운영 현황과 하반기 일정을 논의하였음."],
                                              attendees=[("가나다학과", "가"), ("", "사"), ("한림대학교", "다")]))
    members = [participants.Member("가", "100001", "가나다학과")]
    try:
        with sync_api.sync_playwright() as p:
            browser = p.chromium.launch(executable_path=executable if os.path.exists(executable) else None)
            context = browser.new_context()
            context.route("http://erp.test/**", lambda route: route.fulfill(status=200, content_type="text/html; charset=utf-8",
                                                                            body=pages[route.request.url]))
            page = context.new_page()
            page.goto("http://erp.test/card")
            wait = lambda s: page.wait_for_timeout(int(s * 1000))  # noqa: E731
            logs: list[str] = []
            asked: list[str] = []
            result = card_erp.ItemResult(index=0, name=item.name)
            ok, why = card_erp._minutes(page, page.main_frame, item, logs.append, lambda m: asked.append(m) or False, wait, [], result, members)
            assert (ok, asked) == (True, []), (why, asked, logs)
            saved = page.evaluate("window.saved")
            assert saved == {"heads": 4, "meal": 0, "snack": 160000, "no": True}       # 나(창에 있던 사람) · 가 · 다 · 임의 1명
            assert any("다과비(폴더 이름) — 식비청구 '아니오' · 회의비(다과) 160,000원" in line for line in result.lines)
            assert any(r.startswith("회의록에서 못 정한 사람(확인 필요): 사") for r in result.review)
            arbitrary = [r for r in result.review if r.startswith("임의로 넣은 참여인력(확인 필요): 바")]
            assert arbitrary and "회의록에서 못 정한 사람 1명" in arbitrary[0]
            assert not any("회의록에 없는 참여인력: 바" in r for r in result.review)            # 임의로 넣은 사람은 따로 알린다
            assert not any(n in line for line in logs for n in ("100004", "바 ", "'바'"))      # 기록에 사번 · 이름 없음
            assert any("임의로 1명 넣음" in line for line in logs)
            browser.close()
    except Exception as error:  # noqa: BLE001 — 브라우저가 없는 곳(CI)
        if "Executable doesn't exist" in str(error) or "BrowserType.launch" in str(error):
            pytest.skip(f"브라우저 없음: {str(error).splitlines()[0][:80]}")
        raise
