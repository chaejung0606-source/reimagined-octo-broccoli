"""확인할 것 — 무엇 · 어디서 · 할 일 · 무게(claims/checks.py) — 담당자 2026-11-11 장학금 미리 보기 그림:
"뭘 어디서 어떤걸 확인해야 하는지 모르겠잖아요" · "확인필요 세부사항은 목록 위에서만 보여지도록 … 아래 박스로 되어있는건 삭제".

명단은 가짜 이름 · 학번으로 openpyxl 로 만든다(10절). 화면 쪽(표 위 한 칸 · 표의 번호 · 아래 '자세히' 칸 없음)은 PySide6 가 있을 때만.
"""
from __future__ import annotations

import os

import pytest

from claim_downloader.claims import checks

openpyxl = pytest.importorskip("openpyxl")


def make_roster(folder, rows, nation_row=None, total=None):
    """(나)형 모양 — 강좌명 · 국적 열. rows: (이름, 학번, 강좌, 금액)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "TA장학금"
    ws["B2"] = "2026년도 10월 (나)형 근로장학금 지급내역"
    for col, text in zip("BCDEFGHIJK", ("연번", "이름", "학번", "강좌명", "은행", "계좌", "단가", "시간", "금액", "국적")):
        ws[f"{col}3"] = text
    r = 4
    for i, (name, no, course, amount) in enumerate(rows, 1):
        for col, value in zip("BCDEFGHIJ", (i, name, no, course, "국민", "123-45-678901", 15000, "20", amount)):
            ws[f"{col}{r}"] = value
        if nation_row == i:
            ws[f"K{r}"] = "UZ"
        r += 1
    ws[f"B{r}"] = "합계"
    ws[f"J{r}"] = total if total is not None else sum(a or 0 for *_x, a in rows)
    path = os.path.join(folder, "2026학년도 (나)형 근로장학금 지급내역.xlsx")
    wb.save(path)
    return path


def make_folder(tmp_path, people_files=(), **roster):
    folder = tmp_path / "10월"
    (folder / "공통 증빙").mkdir(parents=True)
    (folder / "개별 증빙").mkdir()
    (folder / "공통 증빙" / "지급 공문.pdf").write_bytes(b"%PDF-1.4")
    for name in people_files:
        (folder / "개별 증빙" / name).write_bytes(b"%PDF-1.4")
    make_roster(str(folder), **roster)
    return str(folder)


ROWS = [("가나다", 202600001, "자료구조", 300000), ("사아자", 202600003, "데이터활용개론", 300000),
        ("사아자", 202600003, "컴퓨터개론", 300000), ("차카타", 202600004, "알고리즘", 300000),
        ("누락이", 202600006, "웹개발", None)]
FILES = ("가나다_자료구조.pdf", "차카타_알고리즘.pdf", "사아자_데이터활용개론.pdf", "사아자_컴퓨터개론.pdf", "사아자_신분증.pdf", "누구것인지모름.pdf")


def test_note_is_the_old_text_with_parts():
    note = checks.Note("21행 홍길동: 금액이 없음", what="홍길동 — 금액이 비어 있음", where="명단 엑셀 21행", todo="금액을 적고", person=3)
    assert note == "21행 홍길동: 금액이 없음" and isinstance(note, str)          # 글로 쓰던 곳은 그대로
    assert (note.level, note.level_name, note.what, note.person) == ("check", "확인", "홍길동 — 금액이 비어 있음", 3)
    plain = checks.as_note("그냥 글")
    assert plain.what == "그냥 글" and plain.level == "check" and checks.as_note(note) is note


def test_ordered_puts_fixes_first_and_keeps_same_text_for_different_people():
    a = checks.Note("같은 글", person=1)
    b = checks.Note("같은 글", person=2)
    fix = checks.Note("고칠 글", level=checks.FIX)
    info = checks.Note("참고 글", level=checks.INFO)
    out = checks.ordered([info, a, b, a, fix])
    assert [str(n) for n in out] == ["고칠 글", "같은 글", "같은 글", "참고 글"] and [n.person for n in out[1:3]] == [1, 2]
    assert checks.count_text(out) == "고칠 것 1 · 확인 2 · 참고 1"


def test_job_checks_say_what_where_and_what_to_do(tmp_path):
    from claim_downloader.claims import scholarship as sch
    folder = make_folder(tmp_path, FILES, rows=ROWS, nation_row=4)
    job = sch.load_job(folder)
    problems = job.problems()
    missing = next(p for p in problems if "누락이" in p)
    # 옛 글 그대로(기록 · 다른 화면) + 어느 파일의 몇 행 · 어느 칸 · 할 일
    assert missing == "8행 누락이: 금액이 없음"
    assert missing.what == "누락이 — 금액이 비어 있음" and missing.level == checks.CHECK and missing.person == 4
    assert "2026학년도 (나)형 근로장학금 지급내역.xlsx" in missing.where and "8행" in missing.where and "금액 칸" in missing.where
    assert "[다시 읽기]" in missing.todo and "넣지 않습니다" in missing.todo
    unmatched = next(p for p in problems if "모르는 개별증빙" in p)
    assert "누구것인지모름.pdf" in unmatched.where and "파일 이름" in unmatched.todo
    # 넣기를 막는 것만 '고칠 것'
    assert not any(p.level == checks.FIX for p in problems)
    job.main_summary, job.pay_ym = "", "2026/11"
    fixes = [p for p in job.problems() if p.level == checks.FIX]
    assert [p.where for p in fixes] == ["③ 오른쪽 칸 '대표적요'", "③ 오른쪽 칸 '지급예정년월'"]


def test_person_notes_mark_what_the_app_does_as_info(tmp_path):
    from claim_downloader.claims import scholarship as sch
    folder = make_folder(tmp_path, FILES, rows=ROWS, nation_row=4)
    job = sch.load_job(folder)
    plans = {i: sch.plan_person(job, i) for i in job.chosen()}
    assert 4 not in plans                                                     # 금액 없는 사람은 체크가 풀려 있다
    foreign = plans[3].notes
    assert [n.level for n in foreign] == [checks.INFO] and "국적 UZ" in foreign[0].what and "할 일 없음" in foreign[0].todo
    # 한 학생의 교과목 줄 둘 — 교과목 이름 없는 서류(사아자_신분증)가 두 줄에 다 붙는다고 줄마다 알린다
    shared = [n for i in (1, 2) for n in plans[i].notes]
    assert [n.person for n in shared] == [1, 2] and all("사아자_신분증.pdf" in n.where for n in shared)
    assert plans[0].notes == [] and "외국인(UZ)" in plans[3].note                # 기록용 한 줄 글은 그대로


def _qt_app():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_preview_shows_checks_above_the_list_only(tmp_path):
    _qt_app()
    from PySide6.QtCore import QUrl

    from claim_downloader.claims import scholarship as sch
    from claim_downloader.ui.pages import claim
    from claim_downloader.ui.report_dialog import ReportDialog
    folder = make_folder(tmp_path, FILES, rows=ROWS, nation_row=4)
    job = sch.load_job(folder)
    notes, rows = claim.scholarship_view(job, [sch.plan_person(job, i) for i in job.chosen()], job.problems())
    assert [n.level for n in notes] == ["check", "check", "check", "check", "info"]
    by_no = {row.cells[0]: row for row in rows}
    # 표의 '확인' 칸은 위 칸의 번호만 — 참고뿐인 줄은 '넣을 것' 그대로
    assert by_no["2"].cells[-1] == "위 3" and by_no["2"].status == "확인 필요"
    assert by_no["4"].cells[-1] == "위 5 (참고)" and by_no["4"].status == "넣을 것"
    assert by_no["1"].cells[-1] == "" and all(not row.detail and not row.html for row in rows)
    assert "사아자_신분증.pdf" in by_no["2"].tips[5]                            # 첨부 목록은 마우스를 올리면
    dialog = ReportDialog(None, title="미리 보기", heading="h", columns=claim.SCH_COLUMNS, stretch=claim.SCH_STRETCH,
                          rows=rows, notes=notes)
    assert dialog.detail is None                                             # 아래 '자세히' 칸 없음
    html = dialog.notes.toHtml()
    assert "어디서" in html and "할 일" in html and "고칠 것" not in html and "표에서 보기 (4번)" in html
    dialog._go_row(QUrl("row:3"))
    assert dialog.table.currentRow() == 3


def test_failed_student_reason_goes_above_the_list(tmp_path):
    _qt_app()
    from claim_downloader.claims import scholarship as sch
    from claim_downloader.ui.pages import claim
    folder = make_folder(tmp_path, FILES, rows=ROWS)
    job = sch.load_job(folder)
    failed = sch.new_result(job, 0, "failed")
    failed.note = "소득자를 고르지 못했습니다"
    saved = sch.new_result(job, 1, "saved")
    saved.review = ["소득구분이 '기타소득' 입니다"]
    notes, rows = claim.scholarship_view(job, [failed, saved], claim.review_notes([failed, saved]))
    assert [(n.level, n.person) for n in notes] == [("fix", 0), ("check", 1)]
    assert "넣지 못함: 소득자를 고르지 못했습니다" in notes[0].what and "다시 누르면" in notes[0].todo
    assert [row.cells[-1] for row in rows] == ["위 1", "위 2"] and rows[1].status == "저장·확인"
