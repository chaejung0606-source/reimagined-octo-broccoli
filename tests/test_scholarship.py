"""장학금 청구(claims/roster.py · person.py · attach.py · scholarship.py).

실제 명단·청구서 없이 돈다 — 명단 엑셀은 openpyxl 로 가짜 이름·학번으로 만든다(10절). ERP 는 evaluate 가 JS 상수를
알아보고 화면처럼 반응하는 가짜 프레임으로 흉내 낸다. 실제 화면 모양은 CLAUDE.md 14절 '장학금' ①~⑤.
"""
from __future__ import annotations

import pathlib

import pytest

openpyxl = pytest.importorskip("openpyxl")

from claim_downloader.claims import attach, form, person, roster, scholarship  # noqa: E402
from claim_downloader.claims import payee  # noqa: E402


# ── 가짜 명단 ─────────────────────────────────────────────────────────
def make_ga(path, rows=None, total=None, title="2026년도 7월 (가)형 근로장학금 지급내역"):
    """(가)형 모양 — 실측(2026-10-14): 시트 'TA장학금', B2 제목, 3~4행 머리글(산출내역 병합), 5행부터 학생, 합계 행."""
    rows = rows or [("가나다", 202600001, "국민", "123-45-678901", 12000, "25", 300000),
                    ("라마바", 202600002, "토스", "1000-0000-0001", 12000, "20", 240000)]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "TA장학금"
    ws["B2"] = title
    ws.merge_cells("B2:I2")
    for col, text in zip("BCDEF", ("연번", "이   름", "학   번", "은행", "계   좌")):
        ws[f"{col}3"] = text
        ws.merge_cells(f"{col}3:{col}4")
    ws["G3"] = "산출내역"
    ws.merge_cells("G3:I3")
    ws["G4"], ws["H4"], ws["I4"] = "단가(A)", "시간(B)", "금액(C=A*B)"
    r = 5
    for i, (name, no, bank, acct, unit, hours, amount) in enumerate(rows, 1):
        for col, value in zip("BCDEFGHI", (i, name, no, bank, acct, unit, hours, amount)):
            ws[f"{col}{r}"] = value
        r += 1
    ws[f"B{r}"] = "합   계"
    ws.merge_cells(f"B{r}:H{r}")
    ws[f"I{r}"] = total if total is not None else sum(x[-1] for x in rows)
    wb.save(path)
    return path


def make_na(path):
    """(나)형 TA 모양 — 강좌명 열이 끼고, 한 학생이 두 강좌면 두 줄 + 이름·학번·은행·계좌 세로 병합."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "TA장학금"
    ws["B2"] = "2026년도 6월 (나)형 근로장학금 지급내역"
    for col, text in zip("BCDEFG", ("연번", "이름", "학번", "강좌명", "은행", "계좌")):
        ws[f"{col}3"] = text
        ws.merge_cells(f"{col}3:{col}4")
    ws["H3"] = "산출내역"
    ws.merge_cells("H3:J3")
    ws["H4"], ws["I4"], ws["J4"] = "단가(A)", "시간(B)", "금액(C=A*B)"
    ws["M3"], ws["N3"] = "연락처", "이메일"
    data = [(1, "사아자", 202600010, "자료구조", "국민은행", "111-11-111111", 15000, "10", 150000),
            (2, None, None, "운영체제", None, None, 15000, "8", 120000),
            (3, "차카타", 202600011, "알고리즘", "토스뱅크", "1000-1111-2222", 20000, "5", 100000)]
    for i, row in enumerate(data):
        for col, value in zip("BCDEFGHIJ", row):
            ws[f"{col}{5 + i}"] = value
    ws.merge_cells("C5:C6")
    ws.merge_cells("D5:D6")
    ws["B8"] = "합계"
    ws["J8"] = 370000
    wb.save(path)
    return path


def test_roster_reads_ga_layout_by_header_words(tmp_path):
    r = roster.read(make_ga(tmp_path / "명단.xlsx"))
    assert r.title == "2026년도 7월 (가)형 근로장학금 지급내역" and r.kind == "가"
    assert [p.name for p in r.people] == ["가나다", "라마바"]
    assert [p.student_no for p in r.people] == ["202600001", "202600002"]
    assert [p.amount for p in r.people] == [300000, 240000]       # '금액(C=A*B)' 열 — 단가·시간 열이 아니다
    assert r.people[0].account_digits == "12345678901" and r.people[1].bank == "토스"
    assert r.sheet_total == 540000 and r.total == 540000 and r.problems() == []


def test_roster_fills_merged_second_row_and_reads_course(tmp_path):
    r = roster.read(make_na(tmp_path / "TA.xlsx"))
    assert r.kind == "나"
    assert [(p.name, p.student_no, p.course, p.amount) for p in r.people] == [
        ("사아자", "202600010", "자료구조", 150000), ("사아자", "202600010", "운영체제", 120000),
        ("차카타", "202600011", "알고리즘", 100000)]
    assert r.people[1].account == "111-11-111111"                  # 병합된 둘째 줄은 앞 줄 값을 내려받는다
    assert r.sheet_total == 370000 and not any("합계" in p for p in r.problems())
    # 학번까지 같고 교과목이 다르면 한 학생이 교과목 둘을 맡은 것 — 문제가 아니다(담당자 규칙 2026-10-14)
    assert r.duplicate_problems() == [] and not any("중복" in p for p in r.problems())


def _people(*rows):
    return [roster.Person(name=n, student_no=no, course=c, amount=1, row=5 + i) for i, (n, no, c) in enumerate(rows)]


def test_same_name_is_told_apart_by_student_no_then_course():
    ok = roster.Roster(path="", people=_people(("가나다", "202600001", "자료구조"),
                                                ("가나다", "202600002", "자료구조"),     # 동명이인 — 학번이 다르다
                                                ("가나다", "202600001", "운영체제")))    # 같은 학생의 다른 교과목
    assert ok.duplicate_problems() == []
    twice = roster.Roster(path="", people=_people(("가나다", "202600001", "자료구조"), ("가나다", "202600001", "자료구조")))
    assert any("중복" in p and "자료구조" in p for p in twice.duplicate_problems())
    no_course = roster.Roster(path="", people=_people(("가나다", "202600001", ""), ("가나다", "202600001", "")))
    assert any("중복" in p for p in no_course.duplicate_problems())
    wrong = roster.Roster(path="", people=_people(("가나다", "202600001", ""), ("라마바", "202600001", "")))
    assert any("이름이 다릅니다" in p for p in wrong.duplicate_problems())


def test_roster_flags_total_mismatch_and_missing_student_no(tmp_path):
    rows = [("가나다", None, "국민", "1", 10000, "1", 10000), ("라마바", 202600002, "국민", "2", 10000, "2", 20000)]
    r = roster.read(make_ga(tmp_path / "x.xlsx", rows=rows, total=99999))
    problems = " / ".join(r.problems())
    assert "합계" in problems and "학번이 없음" in problems


def test_summaries_follow_type_rules():
    rules = scholarship.parse_rules(scholarship.RULES_DEFAULT)
    main = scholarship.main_summary("2026년도 7월 (가)형 근로장학금 지급내역", rules)
    assert main == "02_2026년도 7월 (가)형 근로장학금"             # '지급내역' 은 뺀다 (담당자 지정 2026-10-14)
    assert scholarship.main_summary("2026년도 7월 (가)형 근로장학금 지급 내역", rules) == main
    ga = roster.Person(name="가나다", student_no="202600001", amount=1)
    assert scholarship.row_summary(main, ga, "가", rules) == main + "_가나다"
    # TA 근로장학금: 대표적요(이름_교과목명) — 담당자 지정 2026-10-14. 제목에 '(나)형' 이 없어도 교과목이 있으면 이 꼴
    na = roster.Person(name="사아자", student_no="202600010", course="자료구조", amount=1)
    ta_main = scholarship.main_summary("2026년도 9월 (나)형 근로장학금 지급내역", rules)
    assert scholarship.row_summary(ta_main, na, "나", rules) == "02_2026년도 9월 (나)형 근로장학금(사아자_자료구조)"
    assert scholarship.row_summary("02_X", na, "", rules) == "02_X(사아자_자료구조)"
    # 유형 글자 규칙을 담당자가 따로 적었으면 그것이 먼저
    typed = scholarship.parse_rules(scholarship.RULES_DEFAULT + "\n행적요(나): {대표적요}({이름}_{학번}_{강좌명})")
    assert scholarship.row_summary("02_X", na, "나", typed) == "02_X(사아자_202600010_자료구조)"
    custom = scholarship.parse_rules("대표적요: 02_[선지원금] {제목}\n행적요: {대표적요}-{이름}")
    assert scholarship.main_summary("T", custom) == "02_[선지원금] T"
    assert scholarship.main_summary("T 지급내역", custom) == "02_[선지원금] T 지급내역"   # '뺄 말' 이 없는 규칙이면 제목 그대로


def test_load_job_splits_common_and_person_files(tmp_path):
    folder = tmp_path / "7월 (가)형"
    folder.mkdir()
    make_ga(folder / "2026학년도 (가)형 근로장학금 지급내역.xlsx")
    common = folder / "공통증빙"
    common.mkdir()
    (common / "지급 공문.pdf").write_bytes(b"%PDF")
    (common / "명단.pdf").write_bytes(b"%PDF")
    each = folder / "개별증빙"
    each.mkdir()
    (each / "가나다.pdf").write_bytes(b"%PDF")
    (each / "라마바").mkdir()
    (each / "라마바" / "근무일지.pdf").write_bytes(b"%PDF")
    (each / "라마바" / "청구서.pdf").write_bytes(b"%PDF")
    (each / "근무일지 등.zip").write_bytes(b"PK")                  # 압축은 올리지 않는다
    (each / "누군지모름.pdf").write_bytes(b"%PDF")
    job = scholarship.load_job(str(folder))
    assert job.roster.kind == "가" and len(job.people) == 2 and job.selected == [True, True]
    assert sorted(f.split("/")[-1].split("\\")[-1] for f in job.common_files) == ["명단.pdf", "지급 공문.pdf"]
    assert [len(job.person_files.get(i, [])) for i in range(2)] == [1, 2]
    assert len(job.files_for(1)) == 4                              # 공통 2 + 개별 2
    assert [f.rsplit("/", 1)[-1] for f in job.unmatched] == ["누군지모름.pdf"]
    assert any("모르는 개별증빙" in p for p in job.problems())
    assert job.main_summary.startswith("02_2026년도 7월 (가)형")


def test_old_default_rules_file_is_upgraded_but_edited_one_is_kept():
    from claim_downloader import settings
    old = scholarship.RULES_HEADER + "대표적요: 02_{제목}\n행적요: {대표적요}_{이름}\n행적요(나): {대표적요}({이름}_{학번}_{강좌명})\n"
    path, base = settings.scholarship_rules_path(), settings.scholarship_rules_base_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(old, encoding="utf-8")
    base.write_text(old, encoding="utf-8")
    rules = scholarship.load_rules()                      # 손대지 않은 옛 기본값 → 새 기본값으로
    assert "행적요(강좌)" in rules and "행적요(나)" not in rules
    assert rules["행적요(강좌)"] == "{대표적요}({이름}_{강좌명})" and "지급내역" in rules["제목에서뺄말"]
    path.write_text(old.replace("02_{제목}", "02_[선지원금] {제목}"), encoding="utf-8")
    rules = scholarship.load_rules()                      # 담당자가 고친 것 → 그대로
    assert rules["대표적요"] == "02_[선지원금] {제목}" and "행적요(나)" in rules


def test_job_warns_when_two_rows_get_the_same_summary(tmp_path):
    rows = [("가나다", 202600001, "국민", "1", 10000, "1", 10000), ("가나다", 202600002, "국민", "2", 10000, "1", 10000)]
    folder = tmp_path / "7월"
    folder.mkdir()
    make_ga(folder / "명단.xlsx", rows=rows, total=20000)
    job = scholarship.load_job(str(folder))
    assert any("개별 적요가 같은 줄" in p for p in job.problems())      # (가)형 동명이인은 '대표적요_이름' 이 같아진다


def test_ta_student_with_two_courses_gets_files_per_course_or_both(tmp_path):
    people = [roster.Person("사아자", "202600010", course="자료구조"), roster.Person("사아자", "202600010", course="운영체제"),
              roster.Person("차카타", "202600011", course="알고리즘")]
    files = [str(tmp_path / "사아자.pdf"), str(tmp_path / "사아자_운영체제 근무일지.pdf"), str(tmp_path / "차카타.pdf")]
    assigned, unmatched = scholarship.assign_person_files(files, str(tmp_path), people)
    # 교과목이 없는 개인 서류는 그 학생의 두 줄 모두에, 교과목이 적힌 것은 그 줄에만
    assert assigned == {0: [files[0]], 1: [files[0], files[1]], 2: [files[2]]} and unmatched == []
    job = scholarship.Job(folder=str(tmp_path), roster=roster.Roster(path="", people=people), selected=[True, True, True])
    assert job.count_text() == "3줄(2명)" and job.count_text([0, 2]) == "2명"
    # 결과 표(ui/report_dialog)가 쓰는 값 — 줄글을 다시 쪼개지 않고 칸마다 읽는다
    job.person_files, job.common_files = assigned, [str(tmp_path / "공문.pdf")]
    plan = scholarship.plan_person(job, 1)
    assert (plan.student_no, plan.course, plan.common_count) == ("202600010", "운영체제", 1)
    assert plan.files == [job.common_files[0], files[0], files[1]] and plan.summary == job.row_summary(1)


def test_same_name_needs_student_no_in_file_name(tmp_path):
    people = [roster.Person("가나다", "202600001"), roster.Person("가나다", "202600002")]
    files = [str(tmp_path / "가나다.pdf"), str(tmp_path / "가나다_202600002.pdf")]
    assigned, unmatched = scholarship.assign_person_files(files, str(tmp_path), people)
    assert assigned == {1: [files[1]]} and unmatched == [files[0]]


# ── 소득자 팝업 · 첨부 팝업 ─────────────────────────────────────────────
def _grid(*rows):
    return [{"index": i, "text": f"{nm} {no}", "titles": "", "pick": True, "cells": {"k_EMP_NO": no, "k_EMP_NM": nm}}
            for i, (nm, no) in enumerate(rows)]


def test_person_match_uses_student_number_not_name():
    rows = _grid(("가나다", "202600001"), ("가나다", "202500099"))   # 실측: 같은 이름이 두 행
    assert person.match(rows, "가나다", "202600001") == (0, "학번 일치")
    index, why = person.match(rows, "가나다", "")
    assert index is None and "학번이 없어" in why
    index, why = person.match(rows, "가나다", "209999999")
    assert index is None and "없음" in why
    index, why = person.match(_grid(("다른이", "202600001")), "가나다", "202600001")
    assert index is None and "이름이 다름" in why


def test_attachable_skips_archives_and_temp_files(tmp_path):
    keep = tmp_path / "a.pdf"
    keep.write_bytes(b"%PDF")
    for name in ("b.zip", "~$c.xlsx", "d.lnk"):
        (tmp_path / name).write_bytes(b"x")
    assert attach.attachable([str(tmp_path / n) for n in ("a.pdf", "b.zip", "~$c.xlsx", "d.lnk", "없음.pdf")]) == [str(keep)]


# ── 흐름 (가짜 작성 화면) ──────────────────────────────────────────────
class FakeForm:
    """인건비 탭 작성 화면 — 탭 클릭 · select/text · 저장(청구내역 한 줄 + REQ_CNT)을 흉내."""

    def __init__(self, owner_result="성공:이름", save_works=True, deduction=0, account=None,
                 reset_income=False, lock_income=False):
        self.v = {"TAB_GB": "10", "APPR_DIV_CD": "", "REQ_CNT": "", "REQ_SEQ_NO": "TMP_REQ_1", "MOD_YN": "N",
                  "OWNR_INQ_RSLT": "", "ACCT_NO": "", "RCV_CD": "", "RCV_NM": "", "fileList": 0}
        self.text = {}
        self.rows = 0
        self.saved = []
        self.clicks = []
        self.owner_result = owner_result
        self.save_works = save_works
        self.deduction = deduction
        self.account = account
        self.reset_income = reset_income      # 소득자를 고르면 ERP 가 소득구분을 기타소득으로 되돌린다(담당자 첫 시험에서 본 것)
        self.lock_income = lock_income        # 소득구분을 바꿔도 그대로 — 사람이 고쳐야 하는 경우

    def pick_person(self, name, no):
        # ERP 가 소득자를 고르면 채우는 계좌 — 기본은 명단(make_ga)과 같은 계좌
        acct = self.account or {"202600001": "12345678901", "202600002": "100000000001"}.get(no, "")
        self.v.update(RCV_CD=no, RCV_NM=name, ACCT_NO=acct, OWNR_INQ_RSLT=self.owner_result)
        if self.reset_income:
            self.v["INCM_DIV_CD"] = self.text["INCM_DIV_CD"] = "기타소득"

    def evaluate(self, js, arg=None):
        if js is form.PROBE_JS:
            return True
        if js is payee.CLICK_ID_JS:
            self.clicks.append(arg)
            if arg == scholarship.TAB_ID:
                self.v["TAB_GB"] = "20"
            return {"ok": True}
        if js is form.STATE_JS:
            out = {}
            for i in arg:
                info = {"tag": "input", "value": str(self.v.get(i, ""))}
                if i in self.text:
                    info["text"] = self.text[i]
                if i == "fileList":
                    info["options"] = ["f"] * int(self.v["fileList"])
                out[i] = info
            return out
        if js is form.SET_SELECT_JS:
            element_id, wanted = arg
            if element_id == "INCM_DIV_CD" and self.lock_income and self.text.get(element_id):
                return {"ok": True, "now": self.text[element_id]}
            self.v[element_id], self.text[element_id] = wanted, wanted
            return {"ok": True, "now": wanted}
        if js is form.SET_TEXT_JS:
            element_id, value = arg
            self.v[element_id] = value
            return {"ok": True, "now": value}
        if js is form.CLICK_SAVE_JS:
            self.clicks.append("저장:" + arg)
            if self.save_works:
                self.saved.append(dict(self.v))
                self.rows += 1
                self.v.update(REQ_CNT="322", APPR_DIV_CD="40", REQ_SEQ_NO=f"TMP_REQ_{self.rows + 1}", TAB_GB="10",
                              RCV_CD="", RCV_NM="", OWNR_INQ_RSLT="", ACCT_NO="", REQ_AMT="", REQ_PTCL="")
                self.text.clear()
            return {"ok": True}
        if js is scholarship.SUMMARY_JS:
            return {"rows": self.rows, "totals": [1, 1, self.deduction] if self.rows else []}
        raise AssertionError("모르는 JS: " + str(js)[:60])


@pytest.fixture
def job(tmp_path):
    folder = tmp_path / "건"
    folder.mkdir()
    make_ga(folder / "명단.xlsx")
    (folder / "공통증빙").mkdir()
    (folder / "공통증빙" / "공문.pdf").write_bytes(b"%PDF")
    return scholarship.load_job(str(folder))


def _patch_popups(monkeypatch, frame, picks=True, attach_ok=True):
    calls = {"person": [], "attach": []}

    def fake_search(page, fr, name, no, log, wait=None, messages=None, tab=None, auto_pick=True):
        calls["person"].append((name, no, tab))
        if picks:
            frame.pick_person(name, no)
        return person.PersonReport(ok=True, name=name, student_no=no, picked=picks, chosen_no=no if picks else "",
                                   pick_note="학번 일치" if picks else "검색 결과가 없음")

    def fake_upload(page, fr, paths, log, wait=None, messages=None):
        calls["attach"].append(list(paths))
        if attach_ok:
            frame.v["fileList"] = int(frame.v["fileList"]) + len(paths)
        return attach.AttachReport(ok=attach_ok, files=list(paths), uploaded=len(paths) if attach_ok else 0,
                                   note="" if attach_ok else "팝업이 열리지 않았습니다")

    monkeypatch.setattr(scholarship.person, "search", fake_search)
    monkeypatch.setattr(scholarship.attach, "upload", fake_upload)
    return calls


def test_run_puts_each_student_and_saves_without_pressing_apply(monkeypatch, job):
    frame = FakeForm()
    calls = _patch_popups(monkeypatch, frame)
    asked = []
    report = scholarship.run(object(), frame, job, lambda m: None, ask=lambda m: asked.append(m) or False,
                             wait=lambda s: None, dry_run=False)
    assert report.saved == 2 and not report.stopped and asked == []
    assert [c[:2] for c in calls["person"]] == [("가나다", "202600001"), ("라마바", "202600002")]
    first, second = frame.saved
    assert first["PAY_EXP_CD"] == "장학금" and first["INCM_DIV_CD"] == "장학금"         # 비목=장학금 → 소득구분=장학금
    assert first["REQ_AMT"] == "300000" and first["REQ_PTCL"] == job.main_summary + "_가나다"
    assert first["APPL_CONT"] == job.main_summary and first["PAY_PLAN_YM"] == job.pay_ym
    assert second["REQ_PTCL"] == job.main_summary + "_라마바"
    assert frame.clicks.count(scholarship.TAB_ID) == 2                            # 저장 뒤 탭이 돌아가므로 사람마다 다시
    assert all(c in (scholarship.TAB_ID, "저장:저장") for c in frame.clicks)     # 누른 것은 탭과 [저장] 뿐
    assert calls["attach"][0] == job.files_for(0)
    assert "[신청]" in report.lines()[-1]


def test_income_kind_is_picked_again_when_erp_resets_it_after_person(monkeypatch, job):
    """담당자 첫 시험(2026-10-14): 소득구분을 '장학금' 으로 골랐는데 저장 전에는 다른 값 — 소득자를 고른 뒤 다시 고른다."""
    frame = FakeForm(reset_income=True)
    _patch_popups(monkeypatch, frame)
    logs, asked = [], []
    report = scholarship.run(object(), frame, job, logs.append, ask=lambda m: asked.append(m) or False,
                             wait=lambda s: None, dry_run=False)
    assert report.saved == 2 and asked == []
    assert all(row["INCM_DIV_CD"] == "장학금" for row in frame.saved)
    assert any("다시 고름" in line for line in report.results[0].lines)
    assert any("기타소득" in line and "다시" in line for line in logs)            # 무엇으로 바뀌어 있었는지 로그에 남긴다


def test_income_kind_that_will_not_change_is_saved_and_listed_for_review(monkeypatch, job):
    """담당자 결정(2026-10-14): 앱이 다시 골라도 소득구분이 안 바뀌면 멈추지 말고 그대로 임시저장 + 신청 전 확인 목록."""
    frame = FakeForm(reset_income=True, lock_income=True, deduction=26400)
    _patch_popups(monkeypatch, frame)
    asked, logs, notified = [], [], []
    report = scholarship.run(object(), frame, job, logs.append, ask=lambda m: asked.append(m) or False,
                             wait=lambda s: None, dry_run=False, on_person=lambda i, st, n: notified.append((i, st)))
    assert report.saved == 2 and not report.stopped and asked == []             # 묻지도 멈추지도 않는다
    assert [row["INCM_DIV_CD"] for row in frame.saved] == ["기타소득", "기타소득"]   # 그대로 저장
    review = report.review_items()
    assert len(review) == 3 and all(item.startswith(("1. 가나다", "2. 라마바")) for item in review)
    assert "기타소득" in review[0] and "[신청]" in review[0]
    assert "공제 26,400원" in review[1]                                         # 첫 줄을 넣고 공제가 생겼다
    assert not any("공제" in item for item in report.results[1].review)         # 둘째 줄은 공제가 늘지 않았다(합계 그대로)
    assert ("review" in [st for _i, st in notified]) and "신청 전 확인" in "\n".join(report.lines())
    assert any("신청 전 확인" in line for line in logs)


def test_run_stops_and_asks_when_unsure(monkeypatch, job):
    frame = FakeForm(owner_result="")                           # 예금주조회 결과가 비어 있다
    _patch_popups(monkeypatch, frame)
    asked = []
    report = scholarship.run(object(), frame, job, lambda m: None, ask=lambda m: asked.append(m) or False,
                             wait=lambda s: None, dry_run=False)
    assert report.saved == 0 and report.stopped and frame.saved == []
    assert asked and "예금주조회" in asked[0]


def test_run_asks_for_person_when_popup_is_ambiguous_then_continues(monkeypatch, job):
    frame = FakeForm()
    _patch_popups(monkeypatch, frame, picks=False)
    answers = []

    def ask(message):
        answers.append(message)
        # 사람이 팝업에서 골랐다 — 작성 화면에 그 학생이 들어온다
        name = "가나다" if "가나다" in message else "라마바"
        frame.pick_person(name, "202600001" if name == "가나다" else "202600002")
        return True

    report = scholarship.run(object(), frame, job, lambda m: None, ask=ask, wait=lambda s: None, dry_run=False)
    assert report.saved == 2 and len(answers) == 2 and "소득자" in answers[0]


def test_run_refuses_to_save_on_account_mismatch_if_person_says_stop(monkeypatch, job):
    frame = FakeForm(account="99999999999")
    _patch_popups(monkeypatch, frame)
    asked = []
    report = scholarship.run(object(), frame, job, lambda m: None, ask=lambda m: asked.append(m) or False,
                             wait=lambda s: None, dry_run=False)
    assert report.saved == 0 and "계좌" in asked[0] and frame.saved == []


def _text_pdf(path, *lines):
    """글자가 든 아주 작은 PDF — 학생이 낸 '지출자료' 처럼 계좌가 적힌 개별증빙을 흉내 낸다(숫자·영문만)."""
    body = "BT /F1 12 Tf 50 750 Td " + " ".join(f"({line}) Tj 0 -16 Td" for line in lines) + " ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(body)} >>\nstream\n{body}\nendstream", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = "%PDF-1.4\n", []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{obj}\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n" + "".join(f"{o:010d} 00000 n \n" for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    pathlib.Path(path).write_bytes(out.encode("latin-1"))
    return str(path)


def test_accounts_are_read_from_person_pdfs(tmp_path):
    pdf = _text_pdf(tmp_path / "a.pdf", "Bank 110-594-395796", "Phone 010-1234-5678", "ID 202416354")
    found, read = scholarship.accounts_in_files([pdf, str(tmp_path / "없음.pdf"), str(tmp_path / "b.jpg")])
    assert read == 1 and "110594395796" in found and "202416354" not in found      # 학번(9자리)은 계좌로 보지 않는다


def _mismatch_job(tmp_path, pdf_lines=None):
    folder = tmp_path / "건"
    folder.mkdir()
    make_ga(folder / "명단.xlsx", rows=[("가나다", 202600001, "신한", "110-594-395796", 12000, "25", 300000)])
    if pdf_lines is not None:
        (folder / "개별증빙").mkdir()
        _text_pdf(folder / "개별증빙" / "가나다 지출자료.pdf", *pdf_lines)
    return scholarship.load_job(str(folder))


def test_account_mismatch_puts_the_document_account_then_asks_for_owner_check(monkeypatch, tmp_path):
    """담당자 결정(2026-10-14): ERP 계좌가 다르면 첨부서류의 계좌를 넣는다 — [예금주조회] 는 사람이 누르고 [계속]."""
    job = _mismatch_job(tmp_path, ["Account 110-594-395796"])
    frame = FakeForm(account="30120104410673")
    _patch_popups(monkeypatch, frame)
    asked = []
    report = scholarship.run(object(), frame, job, lambda m: None, ask=lambda m: asked.append(m) or True,
                             wait=lambda s: None, dry_run=False)
    assert report.saved == 1 and frame.saved[0]["ACCT_NO"] == "110594395796" and frame.saved[0]["BNK_CD"] == "신한"
    assert len(asked) == 1 and "예금주조회" in asked[0] and "30120104410673" in asked[0]
    assert report.review_items() == []                                              # 첨부서류로 확인된 계좌
    assert any("첨부서류의" in line and "바꿈" in line for line in report.results[0].lines)
    assert "btn_ownrInq" not in str(frame.clicks)                                   # 예금주조회는 누르지 않는다


def test_account_mismatch_without_readable_document_uses_roster_and_lists_it(monkeypatch, tmp_path):
    job = _mismatch_job(tmp_path, pdf_lines=None)
    frame = FakeForm(account="30120104410673")
    _patch_popups(monkeypatch, frame)
    report = scholarship.run(object(), frame, job, lambda m: None, ask=lambda m: True, wait=lambda s: None, dry_run=False)
    assert report.saved == 1 and frame.saved[0]["ACCT_NO"] == "110594395796"
    assert any("첨부서류에서 계좌를 읽지 못해" in item for item in report.review_items())


def test_account_mismatch_keeps_erp_account_when_document_agrees_with_erp(monkeypatch, tmp_path):
    job = _mismatch_job(tmp_path, ["Account 301-2010-4410-673"])
    frame = FakeForm(account="30120104410673")
    _patch_popups(monkeypatch, frame)
    asked = []
    report = scholarship.run(object(), frame, job, lambda m: None, ask=lambda m: asked.append(m) or True,
                             wait=lambda s: None, dry_run=False)
    assert report.saved == 1 and frame.saved[0]["ACCT_NO"] == "30120104410673" and asked == []
    assert any("명단 엑셀을 확인" in line for line in report.results[0].lines)


def test_run_flags_nonzero_deduction_after_save(monkeypatch, job):
    """공제가 0 이 아니면 멈추지 않고 신청 전 확인 목록으로(담당자 결정 2026-10-14) — 늘어난 줄에만 붙는다."""
    frame = FakeForm(deduction=26400)
    _patch_popups(monkeypatch, frame)
    asked = []
    report = scholarship.run(object(), frame, job, lambda m: None, ask=lambda m: asked.append(m) or False,
                             wait=lambda s: None, dry_run=False)
    assert report.saved == 2 and not report.stopped and asked == [] and len(frame.saved) == 2
    assert report.review_items() == [report.review_items()[0]] and "공제 26,400원" in report.review_items()[0]


def test_dry_run_touches_nothing(job):
    report = scholarship.run(None, None, job, lambda m: None, ask=lambda m: False, dry_run=True)
    assert report.dry_run and [r.status for r in report.results] == ["planned", "planned"]
    assert "가나다" in "\n".join(report.lines()) and report.lines()[0].startswith("미리 보기")


def test_save_detection_follows_measured_reload():
    """실측 ⑤: 저장 뒤 REQ_CNT 가 생기고 APPR_DIV_CD=40, MOD_YN 은 N 그대로."""
    before = {"REQ_SEQ_NO": "TMP_REQ_1", "MOD_YN": "N", "APPR_DIV_CD": "", "REQ_CNT": ""}
    assert form._changed(before, dict(before, REQ_CNT="322", APPR_DIV_CD="40", REQ_SEQ_NO="TMP_REQ_2"))
    assert not form._changed(before, dict(before))


def test_previous_students_save_message_does_not_count_for_the_next(monkeypatch, job):
    """둘째 학생의 [저장] 이 안 먹었는데 첫 학생의 '저장되었습니다' 가 남아 있어 끝난 것으로 보면 안 된다."""
    frame = FakeForm()
    _patch_popups(monkeypatch, frame)
    live = []
    original = frame.evaluate

    def evaluate(js, arg=None):
        if js is form.CLICK_SAVE_JS:
            if frame.rows == 0:
                live.append("저장되었습니다.")
                return original(js, arg)
            frame.clicks.append("저장:" + arg)          # 둘째 학생: 눌렀지만 아무 일도 없음
            return {"ok": True}
        return original(js, arg)

    frame.evaluate = evaluate
    asked = []
    report = scholarship.run(object(), frame, job, lambda m: None, ask=lambda m: asked.append(m) or False,
                             wait=lambda s: None, messages=live, dry_run=False)
    assert report.saved == 1 and report.stopped and report.results[1].status == "stopped"
    assert report.messages == ["저장되었습니다."]


# ── 청구 종류 (일반청구 화면에서 폴더마다 고른다) ─────────────────────────
def test_kind_guess_recognizes_scholarship_folder_shape(tmp_path):
    from claim_downloader.claims import kinds

    general = tmp_path / "정수기 9월"
    general.mkdir()
    (general / "세금계산서.pdf").write_bytes(b"%PDF")
    assert kinds.guess(str(general)) == kinds.GENERAL

    sch_dir = tmp_path / "7월 (가)형"
    sch_dir.mkdir()
    make_ga(sch_dir / "명단.xlsx")
    assert kinds.guess(str(sch_dir)) == kinds.GENERAL           # 엑셀만 있고 증빙 폴더가 없으면 아직 일반
    (sch_dir / "개별증빙").mkdir()
    assert kinds.guess(str(sch_dir)) == kinds.SCHOLARSHIP
    (sch_dir / "~$명단.xlsx").write_bytes(b"x")                  # 엑셀이 열려 있을 때 생기는 임시 파일은 엑셀로 치지 않는다
    assert kinds.looks_like_scholarship(str(sch_dir))


def test_kind_resolve_honors_choice_and_refuses_unready(tmp_path):
    from claim_downloader.claims import kinds

    folder = tmp_path / "건"
    folder.mkdir()
    assert kinds.resolve(kinds.AUTO, str(folder)) == kinds.GENERAL
    assert kinds.resolve(kinds.SCHOLARSHIP, str(folder)) == kinds.SCHOLARSHIP     # 담당자가 고르면 모양과 상관없이 그 종류
    for key in (kinds.TRAVEL, kinds.CARD):
        assert not kinds.find(key).ready
        with pytest.raises(ValueError):
            kinds.resolve(key, str(folder))
    assert [k.name for k in kinds.KINDS] == ["일반", "장학금", "출장비", "카드"]
