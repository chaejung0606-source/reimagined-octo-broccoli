"""첨부만 다시 올리기(claims/reattach.py · navigate.open_saved_sheet · session.reattach_files) — 담당자 요청 2026-10-23.

실제 ERP 없이 돈다. 작성 화면은 evaluate 가 JS 상수를 알아보고 반응하는 가짜 프레임 — 청구내역 줄(○)을 누르면 입력 칸에 그 줄의 값과 첨부
목록이 들어오고, 보기를 모두 골라 '삭제' 하면 목록이 비고, [저장] 은 줄을 고친다(adds_row 면 ERP 가 새 줄로 저장하는 경우).
줄 다시 열기 · '삭제' 는 실측 전이라 안 되는 경우마다 사람에게 묻는 길도 본다.
"""
from __future__ import annotations

import os

import pytest

from claim_downloader import navigate
from claim_downloader.claims import attach, form, kinds, reattach, scholarship
from test_scholarship import make_ga  # noqa: F401 — 가짜 명단


class FakeSheet:
    """임시저장된 청구서의 작성 화면 — 청구내역 줄 둘(실측 ⑤ 모양), 줄마다 첨부 목록."""

    def __init__(self, rows=None, files=None, opens=True, deletes=True, saves=True, adds_row=False, multiple=True, req_cnt="336"):
        self.rows = list(rows if rows is not None else ["1 장학금 02_2026년도 7월 (가)형 근로장학금_가나다 300,000",
                                                       "2 장학금 02_2026년도 7월 (가)형 근로장학금_라마바 240,000"])
        self.amounts = ["300,000", "240,000"]
        self.files = {i: list(f) for i, f in enumerate(files if files is not None else [["옛공문.pdf", "옛명단.pdf"], ["옛공문.pdf"]])}
        self.opens, self.deletes, self.saves, self.adds_row, self.multiple = opens, deletes, saves, adds_row, multiple
        self.v = {"REQ_CNT": req_cnt, "APPR_DIV_CD": "40", "REQ_SEQ_NO": "TMP_REQ_1", "MOD_YN": "N",
                  "REQ_PTCL": "", "REQ_AMT": "", "RCV_NM": "", "PROC_TYP_CD": "P10"}
        self.current = -1
        self.list: list[str] = []
        self.clicks: list[str] = []
        self.saved: list[tuple[int, list[str]]] = []
        self.selected = 0

    def evaluate(self, js, arg=None):
        if js is form.PROBE_JS:
            return True
        if js is form.STATE_JS:
            out = {}
            for i in arg:
                info = {"tag": "input", "value": str(self.v.get(i, ""))}
                if i == "fileList":
                    info["options"] = list(self.list)
                out[i] = info
            return out
        if js is scholarship.SHEET_ROWS_JS:
            return list(self.rows)
        if js is reattach.OPEN_ROW_JS:
            self.clicks.append(f"○{arg}")
            if arg >= len(self.rows):
                return {"ok": False, "why": "줄이 %d개뿐" % len(self.rows)}
            if self.opens:
                self.load(arg)
            return {"ok": True, "text": self.rows[arg]}
        if js is reattach.SELECT_ALL_FILES_JS:
            self.selected = len(self.list) if self.multiple else min(1, len(self.list))
            return {"ok": True, "count": len(self.list), "selected": self.selected, "names": list(self.list)}
        if js is reattach.CLICK_FILE_DELETE_JS:
            self.clicks.append("삭제")
            if self.deletes:
                self.list = self.list[self.selected:] if self.multiple else self.list[1:]
            return {"ok": True}
        if js is form.SET_TEXT_JS:
            self.v[arg[0]] = arg[1]
            self.clicks.append("넣기:%s=%s" % tuple(arg))
            return {"ok": True}
        if js is form.CLICK_SAVE_JS:
            self.clicks.append("저장:" + arg)
            if self.saves:
                self.saved.append((self.current, list(self.list)))
                if self.adds_row:
                    self.rows.append("%d 장학금 %s %s" % (len(self.rows) + 1, self.v["REQ_PTCL"], self.v["REQ_AMT"]))
                else:
                    self.files[self.current] = list(self.list)
                # 저장하면 프레임이 다시 열린다(실측 ⑤) — 입력 칸이 비고 임시 번호가 바뀐다
                self.v.update(REQ_SEQ_NO="TMP_REQ_%d" % (len(self.saved) + 1), REQ_PTCL="", REQ_AMT="", RCV_NM="")
                self.list, self.current = [], -1
            return {"ok": True}
        raise AssertionError("모르는 JS: " + str(js)[:60])

    def load(self, n):
        """사람이 ○ 를 눌렀을 때(또는 앱이) ERP 가 입력 칸에 그 줄을 넣는 것."""
        self.current = n
        self.v.update(REQ_PTCL=self.rows[n].split(" ", 2)[2].rsplit(" ", 1)[0], REQ_AMT=self.amounts[n], RCV_NM="학생")
        self.list = list(self.files.get(n, []))


@pytest.fixture
def job(tmp_path):
    folder = tmp_path / "7월"
    folder.mkdir()
    make_ga(folder / "2026학년도 (가)형 근로장학금 지급내역.xlsx")
    (folder / "공통증빙").mkdir()
    (folder / "공통증빙" / "공문.pdf").write_bytes(b"%PDF")
    (folder / "공통증빙" / "명단.pdf").write_bytes(b"%PDF")
    (folder / "개별증빙").mkdir()
    (folder / "개별증빙" / "가나다.pdf").write_bytes(b"%PDF")
    j = scholarship.load_job(str(folder))
    j.project_no = "202408470003"
    return j


def _upload_fake(frame, calls):
    def upload(page, fr, files, log, wait=None, messages=None):
        calls.append([os.path.basename(f) for f in files])
        fr.list = fr.list + [os.path.basename(f) for f in files]
        return attach.AttachReport(ok=True, files=list(files), uploaded=len(files))
    return upload


# ── 계획 ─────────────────────────────────────────────────────────────
def test_plan_for_roster_job_uses_common_and_person_files(job):
    plan = reattach.plan_for_job(job)
    assert plan.summary == job.main_summary and plan.kind == kinds.SCHOLARSHIP and plan.job is job and not plan.problems
    assert [r.label for r in plan.rows] == ["가나다", "라마바"]
    assert [r.names for r in plan.rows] == [["공문.pdf", "명단.pdf", "가나다.pdf"], ["공문.pdf", "명단.pdf"]]
    assert plan.rows[0].summary.endswith("_가나다") and plan.files_total() == 5
    assert "줄 2개" in " ".join(plan.summary_lines())
    # 체크를 풀면 빠진다
    job.selected[1] = False
    assert [r.label for r in reattach.plan_for_job(job).rows] == ["가나다"]


def test_plan_for_takes_only_roster_jobs(tmp_path, job):
    """일반 · 세금계산서 종류는 2026-10-28 걷어냈다 — 명단 청구만 계획을 만들고, 카드 · 명단을 못 읽은 폴더는 까닭만."""
    folder = tmp_path / "정수기"
    folder.mkdir()
    assert reattach.plan_for(kinds.CARD, str(folder)).problems and not reattach.plan_for(kinds.CARD, str(folder)).rows
    assert reattach.plan_for(kinds.SCHOLARSHIP, str(folder), job=None).problems
    plan = reattach.plan_for(kinds.SCHOLARSHIP, job.folder, job=job, project_no="202408470003")
    assert [r.label for r in plan.rows] == ["가나다", "라마바"] and not plan.problems


def test_dry_run_touches_nothing(job):
    plan = reattach.plan_for_job(job)
    report = reattach.run(None, None, plan, lambda m: None, dry_run=True)
    assert report.dry_run and [r.status for r in report.results] == ["planned", "planned"] and report.lines()[0].startswith("첨부만 다시 올리기 — 미리 보기")
    job.person_files, job.common_files = {}, []
    plan = reattach.plan_for_job(job)
    assert plan.problems and [r.status for r in reattach.run(None, None, plan, lambda m: None, dry_run=True).results] == ["skipped", "skipped"]


# ── 실행 ─────────────────────────────────────────────────────────────
def test_run_clears_uploads_and_saves_each_matched_row(job, monkeypatch):
    frame = FakeSheet()
    uploads: list[list[str]] = []
    monkeypatch.setattr(attach, "upload", _upload_fake(frame, uploads))
    plan = reattach.plan_for_job(job)
    logs: list[str] = []
    seen: list[tuple[int, str]] = []
    report = reattach.run(object(), frame, plan, logs.append, ask=lambda m: False, wait=lambda s: None, dry_run=False,
                          on_row=lambda i, st, n: seen.append((i, st)), req_cnt="336", state="임시저장")
    assert [r.status for r in report.results] == ["saved", "saved"] and report.saved == 2 and not report.stopped and not report.blocked
    assert [r.sheet_row for r in report.results] == [0, 1]
    assert [r.removed for r in report.results] == [2, 1] and [r.uploaded for r in report.results] == [3, 2]
    assert uploads == [["공문.pdf", "명단.pdf", "가나다.pdf"], ["공문.pdf", "명단.pdf"]]
    assert frame.clicks == ["○0", "삭제", "저장:저장", "○1", "삭제", "저장:저장"]
    assert frame.files == {0: ["공문.pdf", "명단.pdf", "가나다.pdf"], 1: ["공문.pdf", "명단.pdf"]}     # 옛 파일은 없고 새 파일만
    assert (0, "erp") in seen and (0, "saved") in seen and (1, "saved") in seen
    assert not report.review_items()
    assert "저장 2/2줄" in report.lines()[0] and "결의번호 336" in report.lines()[0]


def test_single_select_list_is_emptied_one_by_one(job, monkeypatch):
    frame = FakeSheet(multiple=False)
    monkeypatch.setattr(attach, "upload", _upload_fake(frame, []))
    report = reattach.run(object(), frame, reattach.plan_for_job(job), lambda m: None, wait=lambda s: None, dry_run=False)
    assert report.saved == 2 and frame.clicks.count("삭제") == 3 and report.results[0].removed == 2


def test_row_open_failure_asks_person_then_continues(job, monkeypatch):
    """줄 다시 열기는 실측 전 — ○ 를 눌러도 입력 칸이 안 채워지면 사람에게 묻고, 사람이 열면 이어 간다. [멈추기] 면 남은 줄은 그대로."""
    frame = FakeSheet(opens=False)
    monkeypatch.setattr(attach, "upload", _upload_fake(frame, []))
    asked: list[str] = []

    def ask(message):
        asked.append(message)
        frame.load(len(asked) - 1)          # 사람이 그 줄을 연다
        return True
    report = reattach.run(object(), frame, reattach.plan_for_job(job), lambda m: None, ask=ask, wait=lambda s: None, dry_run=False)
    assert report.saved == 2 and len(asked) == 2 and "다시 열지 못했습니다" in asked[0] and "화면 구조 저장" in asked[0]
    assert all("줄 다시 열기는 사람이 했음" in item for item in report.review_items()) and len(report.review_items()) == 2

    frame = FakeSheet(opens=False)
    report = reattach.run(object(), frame, reattach.plan_for_job(job), lambda m: None, ask=lambda m: False, wait=lambda s: None, dry_run=False)
    assert [r.status for r in report.results] == ["stopped", "waiting"] and report.stopped and "줄 다시 열기" in report.results[0].note
    assert "삭제" not in frame.clicks and not frame.saved


def test_delete_failure_asks_person(job, monkeypatch):
    frame = FakeSheet(deletes=False)
    monkeypatch.setattr(attach, "upload", _upload_fake(frame, []))
    asked: list[str] = []

    def ask(message):
        asked.append(message)
        frame.list = []                     # 사람이 지운다
        return True
    report = reattach.run(object(), frame, reattach.plan_for_job(job), lambda m: None, ask=ask, wait=lambda s: None, dry_run=False)
    assert report.saved == 2 and len(asked) == 2 and "지우지 못했습니다" in asked[0] and "'삭제'" in asked[0]
    assert report.results[0].removed == 2 and "첨부문서 지우기는 사람이 했음" in report.review_items()[0]


def test_upload_failure_asks_person(job, monkeypatch):
    frame = FakeSheet()
    monkeypatch.setattr(attach, "upload", lambda page, fr, files, log, wait=None, messages=None:
                        attach.AttachReport(ok=False, files=list(files), note="팝업이 열리지 않았습니다"))
    asked: list[str] = []

    def ask(message):
        asked.append(message)
        frame.list = ["a", "b", "c"]        # 사람이 올린다
        return True
    report = reattach.run(object(), frame, reattach.plan_for_job(job), lambda m: None, ask=ask, wait=lambda s: None, dry_run=False)
    assert report.saved == 2 and "직접 올린 뒤" in asked[0] and report.results[0].uploaded == 3


def test_save_that_adds_a_row_stops_run(job, monkeypatch):
    """[저장] 이 고치지 않고 새 줄을 더하면(실측 전) — 그 줄에서 멈추고 사람이 지운다(앱은 줄의 [삭제] 를 누르지 않는다)."""
    frame = FakeSheet(adds_row=True)
    monkeypatch.setattr(attach, "upload", _upload_fake(frame, []))
    report = reattach.run(object(), frame, reattach.plan_for_job(job), lambda m: None, wait=lambda s: None, dry_run=False)
    assert [r.status for r in report.results] == ["failed", "waiting"] and report.stopped
    assert "2 → 3" in report.results[0].note and "새 줄" in report.results[0].note and len(frame.saved) == 1


def test_save_failure_and_missing_rows_are_reported(job, monkeypatch):
    frame = FakeSheet(saves=False)
    monkeypatch.setattr(attach, "upload", _upload_fake(frame, []))
    report = reattach.run(object(), frame, reattach.plan_for_job(job), lambda m: None, wait=lambda s: None, dry_run=False)
    assert report.results[0].status == "failed" and "[저장]" in report.results[0].note and report.stopped
    # 청구내역에 없는 사람은 건너뛰고 다음 사람으로
    frame = FakeSheet(rows=["1 장학금 02_2026년도 7월 (가)형 근로장학금_라마바 240,000"], files=[["x.pdf"]])
    frame.amounts = ["240,000"]
    monkeypatch.setattr(attach, "upload", _upload_fake(frame, []))
    report = reattach.run(object(), frame, reattach.plan_for_job(job), lambda m: None, wait=lambda s: None, dry_run=False)
    assert [r.status for r in report.results] == ["skipped", "saved"] and "청구내역에 이 줄" in report.results[0].note
    # 저장된 줄이 없으면 하지 않는다
    frame = FakeSheet(rows=[])
    report = reattach.run(object(), frame, reattach.plan_for_job(job), lambda m: None, wait=lambda s: None, dry_run=False)
    assert report.blocked and "저장된 줄이 없습니다" in report.blocked and frame.clicks == []


def test_row_loaded_compares_summary_or_row_text():
    frame = FakeSheet()
    assert reattach.row_loaded(frame, "02_x_가나다", frame.rows[0]) == (False, "입력 칸의 적요가 비어 있음")
    frame.load(0)
    assert reattach.row_loaded(frame, "02_2026년도 7월 (가)형 근로장학금_가나다", frame.rows[0])[0]
    assert reattach.row_loaded(frame, "02_다른 적요_홍길동", frame.rows[0])[0]            # 계획과 달라도 줄 글자와 같으면 열린 것
    ok, why = reattach.row_loaded(frame, "02_다른 적요", "9 전혀 다른 줄")
    assert not ok and "다름" in why
    frame.v["REQ_AMT"] = "0"
    assert reattach.row_loaded(frame, "02_2026년도 7월 (가)형 근로장학금_가나다", frame.rows[0]) == (False, "입력 칸의 청구액이 비어 있음")


def test_row_loaded_rejects_another_course_row_of_the_same_claim():
    """담당자 실제(2026-10-26): TA 학생의 교과목 줄 셋은 적요 앞 글자가 같다 — 연 줄의 입력 칸 적요가 그 줄의 (잘린) 글자와 이어져야 열린 것."""
    main = "02_2026년도 9월 (나)형 근로장학금"
    frame = FakeSheet(rows=[f"1 장학금 {main}(진규정_데이터보안활용혁신융합진로설계) 300,000",
                            f"2 장학금 {main}(진규정_첨단ICT 기술이해) 300,000"])
    frame.load(1)                                                   # 입력 칸에는 첨단ICT 줄이 들어왔다
    sheet_text = f"2 장학금 진규정 300,000 {main}(진규정_첨단ICT 기술이 ..."
    assert reattach.row_loaded(frame, f"{main}(진규정_첨단ICT 기술이해)", sheet_text)[0]
    # 계획은 데이터보안 줄인데 열린 것은 첨단ICT 줄 — 앞 20자가 같아도 '다름'
    wrong_sheet = f"1 장학금 진규정 300,000 {main}(진규정_데이터보안활용 ..."
    ok, why = reattach.row_loaded(frame, f"{main}(진규정_데이터보안활용혁신융합진로설계)", wrong_sheet)
    assert not ok and "다름" in why


def test_match_rows_for_ta_plan_uses_visible_course(tmp_path):
    """계획(사람마다 줄) ↔ 청구내역 — 잘린 적요의 교과목 앞부분으로 맞춘다(sheet_check 와 같은 규칙)."""
    from claim_downloader.claims import roster
    people = [roster.Person("진규정", "202630756", course="데이터보안활용혁신융합진로설계", amount=300000),
              roster.Person("진규정", "202630756", course="첨단ICT 기술이해", amount=300000)]
    j = scholarship.Job(folder=str(tmp_path), roster=roster.Roster(path="", people=people), selected=[True, True],
                        main_summary="02_2026년도 9월 (나)형 근로장학금", common_files=[str(tmp_path / "공문.pdf")])
    plan = reattach.plan_for_job(j)
    main = j.main_summary
    rows = [f"1 진규정 300,000 {main}(진규정_첨단ICT 기술이 ...", f"2 진규정 300,000 {main}(진규정_데이터보안활용 ..."]
    assert reattach.match_rows(plan, rows) == {0: [1], 1: [0]}


# ── 결의서내역에서 그 청구서 열기 ─────────────────────────────────────
class _Grid:
    def __init__(self):
        self.page = object()


def _patch_list(monkeypatch, rows, opened_after_click=True, seq="336"):
    grid = _Grid()
    calls: list[str] = []
    monkeypatch.setattr(navigate, "show_list", lambda ctx, project, log, wait: (grid, ""))
    monkeypatch.setattr(navigate.erp, "collect_all", lambda fr: rows)
    monkeypatch.setattr(navigate.erp, "select_row", lambda page, fr, target: calls.append("줄:" + target["seq"]) or True)
    state = {"clicked": False}

    def evaluate(frame, js, *args):
        if js is navigate.CLICK_DETAIL_JS:
            calls.append("상세조회")
            state["clicked"] = True
            return {"ok": True}
        return 1
    monkeypatch.setattr(navigate, "_evaluate", evaluate)
    form_frame = type("F", (), {})()

    def find_form(ctx):
        if state["clicked"] and opened_after_click:
            return "창", form_frame
        return None, None
    from claim_downloader.claims import form as form_mod
    monkeypatch.setattr(form_mod, "find_form", find_form)
    monkeypatch.setattr(form_mod, "describe_frames", lambda ctx: "창 1개")
    monkeypatch.setattr(navigate, "_sheet_state", lambda f: {"REQ_CNT": seq} if f is form_frame else {})
    return calls, form_frame


def test_open_saved_sheet_picks_the_draft_and_presses_detail(monkeypatch):
    rows = [{"seq": "335", "cont": "02_2026년도 7월 (가)형 근로장학금", "state": "승인", "amt": "540000"},
            {"seq": "336", "cont": "02_2026년도  7월 (가)형 근로장학금", "state": "임시저장", "amt": "540000"},
            {"seq": "337", "cont": "09_다른 것", "state": "보완요청", "amt": "1000"}]
    calls, form_frame = _patch_list(monkeypatch, rows)
    logs: list[str] = []
    page, frame, row, why = navigate.open_saved_sheet(object(), "202408470003", "02_2026년도 7월 (가)형 근로장학금", logs.append, lambda s: None)
    assert frame is form_frame and row["seq"] == "336" and why == "" and calls == ["줄:336", "상세조회"]
    assert any("[상세조회/변경]" in line for line in logs) and any("작성 화면이 떴습니다" in line for line in logs)
    # 보완요청도 된다
    _patch_list(monkeypatch, rows, seq="337")
    page, frame, row, why = navigate.open_saved_sheet(object(), "202408470003", "09_다른 것", lambda m: None, lambda s: None)
    assert row["seq"] == "337" and frame is not None


def test_open_saved_sheet_refuses_when_none_or_many(monkeypatch):
    rows = [{"seq": "335", "cont": "02_x", "state": "승인", "amt": "1"}]
    calls, _f = _patch_list(monkeypatch, rows)
    page, frame, row, why = navigate.open_saved_sheet(object(), "202408470003", "02_x", lambda m: None, lambda s: None)
    assert frame is None and "진행구분이 임시저장 · 보완 이(가) 아닙니다" in why and "결의번호 335(승인)" in why and calls == []
    page, frame, row, why = navigate.open_saved_sheet(object(), "202408470003", "없는 적요", lambda m: None, lambda s: None)
    assert frame is None and "청구서가 없습니다" in why
    rows = [{"seq": "1", "cont": "02_x", "state": "임시저장", "amt": "1"}, {"seq": "2", "cont": "02_x", "state": "임시저장", "amt": "1"}]
    calls, _f = _patch_list(monkeypatch, rows)
    page, frame, row, why = navigate.open_saved_sheet(object(), "202408470003", "02_x", lambda m: None, lambda s: None)
    assert frame is None and "2개입니다" in why and calls == []
    # 눌렀는데 작성 화면이 안 뜨면 까닭
    rows = [{"seq": "1", "cont": "02_x", "state": "임시저장", "amt": "1"}]
    calls, _f = _patch_list(monkeypatch, rows, opened_after_click=False)
    page, frame, row, why = navigate.open_saved_sheet(object(), "202408470003", "02_x", lambda m: None, lambda s: None)
    assert frame is None and "뜨지 않았습니다" in why and calls == ["줄:1", "상세조회"]


def test_open_saved_sheet_reuses_the_open_form(monkeypatch):
    rows = [{"seq": "336", "cont": "02_x", "state": "임시저장", "amt": "1"}]
    calls, form_frame = _patch_list(monkeypatch, rows)
    from claim_downloader.claims import form as form_mod
    monkeypatch.setattr(form_mod, "find_form", lambda ctx: ("창", form_frame))        # 이미 떠 있다
    page, frame, row, why = navigate.open_saved_sheet(object(), "202408470003", "02_x", lambda m: None, lambda s: None)
    assert frame is form_frame and calls == []                                           # 아무것도 누르지 않는다


# ── session ───────────────────────────────────────────────────────────
def test_session_reattach_blocks_on_typed_sheet_and_runs_otherwise(monkeypatch, job):
    from claim_downloader import session as session_mod
    s = session_mod.ErpSession(lambda m: None, lambda m: True, should_stop=lambda: False, process=lambda *a: None)
    s.page = type("P", (), {"context": object()})()
    monkeypatch.setattr(type(s), "browser_open", property(lambda self: True))
    plan = reattach.plan_for_job(job)
    assert s.reattach_files(plan, dry_run=True).dry_run
    from claim_downloader.claims import form as form_mod
    monkeypatch.setattr(form_mod, "wait_for_form", lambda ctx, tries=12, log=None, **kw: (None, "frame"))
    monkeypatch.setattr(s, "_typed_sheet", lambda f: ["청구액"])
    report = s.reattach_files(plan, dry_run=False)
    assert report.blocked and "저장하지 않은 입력" in report.blocked
    monkeypatch.setattr(s, "_typed_sheet", lambda f: [])
    monkeypatch.setattr(navigate, "open_saved_sheet", lambda *a, **k: (None, None, {}, "청구서가 없습니다"))
    assert s.reattach_files(plan, dry_run=False).blocked == "청구서가 없습니다"

    class Page:
        def __init__(self):
            self.handlers = []

        def on(self, name, fn):
            self.handlers.append(name)

        def remove_listener(self, name, fn):
            self.handlers.remove(name)

        def wait_for_timeout(self, ms):
            pass
    page = Page()
    monkeypatch.setattr(navigate, "open_saved_sheet", lambda *a, **k: (page, "frame", {"seq": "336", "state": "임시저장"}, ""))
    seen = {}

    def fake_run(pg, fr, pl, log, **kw):
        seen.update(kw)
        return reattach.ReattachReport(dry_run=False, plan=pl, req_cnt=kw["req_cnt"], state=kw["state"])
    monkeypatch.setattr(reattach, "run", fake_run)
    report = s.reattach_files(plan, dry_run=False, ask=lambda m: True, on_row=lambda *a: None)
    assert report.req_cnt == "336" and report.state == "임시저장" and seen["dry_run"] is False and page.handlers == []


# ── 화면 ─────────────────────────────────────────────────────────────
def test_claim_page_button_previews_without_browser(tmp_path, monkeypatch):
    """② 오른쪽 칸 위 '할 일' 을 '첨부만 다시 올리기' 로 고르면(담당자 2026-10-23 "2단계에서 선택하게 하면 헷갈릴게 줄어들지 않을까") ③ 의 큰 단추가
    그것이 되고 ③ 제목도 바뀐다. '미리 보기만' 이면 브라우저 없이 표 창(줄마다 붙일 파일). 따로 있던 ③ 단추는 없다."""
    from test_log_button import _close, _qt_app, _wait
    app = _qt_app()
    from claim_downloader.ui.pages import claim as claim_page
    from claim_downloader.ui.worker import SessionWorker

    folder = tmp_path / "7월"
    folder.mkdir()
    make_ga(folder / "2026학년도 (가)형 근로장학금 지급내역.xlsx")
    (folder / "공통증빙").mkdir()
    (folder / "공통증빙" / "공문.pdf").write_bytes(b"%PDF")
    (folder / "개별증빙").mkdir()
    (folder / "개별증빙" / "가나다.pdf").write_bytes(b"%PDF")
    worker = SessionWorker()
    page = claim_page.ClaimPage(worker=worker)
    shown: list[dict] = []
    monkeypatch.setattr(claim_page, "show_report", lambda parent, **kw: shown.append(kw) or True)
    try:
        assert page.add_folder(str(folder), kinds.SCHOLARSHIP)
        assert _wait(app, lambda: page._jobs and page._jobs[0] is not None, 10)
        page._sync_buttons()
        assert not hasattr(page, "reattach_button")
        assert page.row_action.isVisibleTo(page) and page.row_action.currentData() == claim_page.ACTION_FILL
        assert page.fill_button.text().startswith("미리 보기") and "첨부" not in page.fill_button.text()
        assert page.step_put.title.text().startswith("ERP 에 넣으세요")
        page.row_action.setCurrentIndex(page.row_action.findData(claim_page.ACTION_REATTACH))
        assert page._actions == [claim_page.ACTION_REATTACH]
        assert page.fill_button.isEnabled() and page.fill_button.text().startswith("미리 보기 (첨부") and page.dry_run.isChecked()
        assert page.step_put.title.text().startswith("첨부만 다시 올리세요") and "첨부만 다시 올리기" in page._guide
        page.dry_run.setChecked(False)
        assert page.fill_button.text().startswith("첨부만 다시 올리기 (") and not page.fill_button.isEnabled()      # 브라우저가 닫혀 있다
        assert not hasattr(page, "save_button")                 # 일반 종류의 [임시저장] 단추는 2026-10-28 걷어냈다
        page.dry_run.setChecked(True)
        page._fill()                                            # 큰 단추 — 할 일이 첨부만이면 그쪽으로
        assert _wait(app, lambda: bool(shown), 15)
        kw = shown[0]
        assert kw["columns"] == claim_page.REATTACH_COLUMNS and len(kw["rows"]) == 2
        assert kw["rows"][0].cells[1] == "가나다" and kw["rows"][0].cells[3] == "2개" and kw["rows"][1].cells[3] == "1개"
        assert "7월" in " ".join(kw["summary"]) and "미리 보기" in kw["title"]
        assert not page._erp_running
        # 다시 '새 청구서에 넣기' 로 — 큰 단추도 돌아온다
        page.row_action.setCurrentIndex(page.row_action.findData(claim_page.ACTION_FILL))
        assert page._actions == [claim_page.ACTION_FILL] and "첨부" not in page.fill_button.text()
        assert page.step_put.title.text().startswith("ERP 에 넣으세요")
    finally:
        _close(page)
        app.processEvents()


def test_open_saved_sheet_accepts_url_or_summary_when_req_cnt_is_missing(monkeypatch):
    """담당자 실제 2026-10-23: 보완요청 결의번호 223 을 열자 작성 프레임은 떴는데 숨은 #REQ_CNT 가 그 번호가 아니라 멈췄다 —
    주소의 REQ_CNT=223 이나(결의번호 칸이 없으면) 새로 뜬 화면의 대표적요로도 그 청구서로 본다. 다른 번호면 여전히 아니다."""
    rows = [{"seq": "223", "cont": "09_정수기 임차료(9월)", "state": "보완요청", "amt": "7800000"}]
    calls, form_frame = _patch_list(monkeypatch, rows, seq="")
    form_frame.url = "https://erp/rexpe_0084_01.act?PRJ_NO=202408470003&REQ_CNT=223&APPR_DIV_CD=45"
    page, frame, row, why = navigate.open_saved_sheet(object(), "202408470003", "09_정수기 임차료(9월)", lambda m: None, lambda s: None)
    assert frame is form_frame and why == "" and calls == ["줄:223", "상세조회"]
    # 주소에도 없으면 — 눌러서 새로 뜬 화면의 대표적요로
    calls, form_frame = _patch_list(monkeypatch, rows, seq="")
    form_frame.url = "https://erp/rexpe_0084_01.act?PRJ_NO=202408470003"
    monkeypatch.setattr(navigate, "_appl_cont", lambda f: "09_정수기  임차료(9월)")
    page, frame, row, why = navigate.open_saved_sheet(object(), "202408470003", "09_정수기 임차료(9월)", lambda m: None, lambda s: None)
    assert frame is form_frame and why == ""
    # 대표적요도 다르면 모름 — 까닭에 본 값
    monkeypatch.setattr(navigate, "_appl_cont", lambda f: "02_다른 청구서")
    page, frame, row, why = navigate.open_saved_sheet(object(), "202408470003", "09_정수기 임차료(9월)", lambda m: None, lambda s: None)
    assert frame is None and "02_다른 청구서" in why and "뜨지 않았습니다" in why
    # 다른 결의번호의 화면은 아니다
    calls, form_frame = _patch_list(monkeypatch, rows, seq="224")
    page, frame, row, why = navigate.open_saved_sheet(object(), "202408470003", "09_정수기 임차료(9월)", lambda m: None, lambda s: None)
    assert frame is None and "결의번호 224 의 것" in why


def test_open_saved_sheet_accepts_the_visible_request_info_cell(monkeypatch):
    """담당자 그림(2026-10-23): 보완요청 청구서의 '신청정보' 칸에 `223 2026-10-19 …` 가 보인다 — 숨은 칸 · 주소에 없어도 그것으로 알아본다."""
    rows = [{"seq": "223", "cont": "02_x", "state": "보완요청", "amt": "1"}]
    calls, form_frame = _patch_list(monkeypatch, rows, seq="")
    form_frame.url = "https://erp/rexpe_0084_01.act?PRJ_NO=1"
    monkeypatch.setattr(navigate, "_shown_req_cnt", lambda f: "223")
    monkeypatch.setattr(navigate, "_appl_cont", lambda f: "")
    page, frame, row, why = navigate.open_saved_sheet(object(), "202408470003", "02_x", lambda m: None, lambda s: None)
    assert frame is form_frame and why == ""
    monkeypatch.setattr(navigate, "_shown_req_cnt", lambda f: "224")
    page, frame, row, why = navigate.open_saved_sheet(object(), "202408470003", "02_x", lambda m: None, lambda s: None)
    assert frame is None and "결의번호 224 의 것" in why


def test_reattach_asks_when_file_delete_empties_the_amount(monkeypatch, job):
    """담당자 그림 2026-10-23: 첨부문서를 '삭제' 한 뒤 청구액 칸이 비어 보였다 — 앱은 값을 넣지 않고(청구내역은 사람 몫) 사람에게 묻는다."""
    job.selected[1] = False
    plan = reattach.plan_for_job(job)
    frame = FakeSheet(files=[["옛.pdf"], []])
    orig_clear = reattach.clear_files

    def clearing(fr, wait, log):
        ok = orig_clear(fr, wait, log)
        fr.v["REQ_AMT"] = ""            # ERP 가 삭제 뒤 청구액을 비운 듯
        return ok
    monkeypatch.setattr(reattach, "clear_files", clearing)
    monkeypatch.setattr(attach, "upload", _upload_fake(frame, []))
    asked: list[str] = []

    def person(msg):
        asked.append(msg)
        frame.v["REQ_AMT"] = "300,000"  # 사람이 넣고 [계속]
        return True
    report = reattach.run(object(), frame, plan, lambda m: None, ask=person, wait=lambda s: None, dry_run=False)
    assert report.saved == 1 and len(asked) == 1 and "300,000" in asked[0]
    assert any("청구액 확인" in r for r in report.results[0].review)
    assert not any(c.startswith("넣기:") for c in frame.clicks)
    # [멈추기] 면 그 줄은 실패
    frame = FakeSheet(files=[["옛.pdf"], []])
    monkeypatch.setattr(attach, "upload", _upload_fake(frame, []))
    report = reattach.run(object(), frame, plan, lambda m: None, ask=lambda m: False, wait=lambda s: None, dry_run=False)
    assert report.saved == 0 and "청구액" in (report.results[0].note or "")


def test_open_saved_sheet_accepts_a_fresh_sheet_whose_hidden_number_differs(monkeypatch):
    """담당자 실제 2026-10-23 16:16 · 16:42: 보완요청 결의번호 223 줄을 [상세조회/변경] 으로 열자 작성 화면의 숨은 #REQ_CNT · 주소가 323 이었다
    (그 화면의 '신청정보' 는 223 — 담당자 그림). '신청정보' 를 못 읽어도, 그 번호가 결의서내역의 다른 줄이 아니고 눌러서 새로 뜬 화면의 대표적요가 같으면
    같은 청구서의 다른 번호로 보고 기록에 적는다. 목록의 다른 줄 번호면 다른 청구서라 여전히 멈춘다."""
    rows = [{"seq": "223", "cont": "02_2026년도 9월 (나)형 근로장학금", "state": "보완요청", "amt": "7800000"},
            {"seq": "224", "cont": "09_다른 것", "state": "승인", "amt": "1"}]
    calls, form_frame = _patch_list(monkeypatch, rows, seq="323")
    form_frame.url = "https://erp/rexpe_0084_01.act?PRJ_NO=202408470003&REQ_CNT=323&APPR_DIV_CD=45"
    monkeypatch.setattr(navigate, "_shown_req_cnt", lambda f: "")
    monkeypatch.setattr(navigate, "_appl_cont", lambda f: "02_2026년도 9월 (나)형  근로장학금")
    logs: list[str] = []
    page, frame, row, why = navigate.open_saved_sheet(object(), "202408470003", "02_2026년도 9월 (나)형 근로장학금", logs.append, lambda s: None)
    assert frame is form_frame and why == "" and calls == ["줄:223", "상세조회"]
    assert any("숨은 결의번호(#REQ_CNT · 주소)는 323" in line and "대표적요" in line for line in logs)
    # '신청정보' 로 알아봤을 때도 숨은 번호를 기록에 적는다
    calls, form_frame = _patch_list(monkeypatch, rows, seq="323")
    monkeypatch.setattr(navigate, "_shown_req_cnt", lambda f: "223")
    logs.clear()
    page, frame, row, why = navigate.open_saved_sheet(object(), "202408470003", "02_2026년도 9월 (나)형 근로장학금", logs.append, lambda s: None)
    assert frame is form_frame and why == "" and any("323" in line and "신청정보" in line for line in logs)
    # 대표적요가 다르면 모름 — 까닭에 '결의서내역에 없는 번호' 와 본 대표적요
    calls, form_frame = _patch_list(monkeypatch, rows, seq="323")
    monkeypatch.setattr(navigate, "_shown_req_cnt", lambda f: "")
    monkeypatch.setattr(navigate, "_appl_cont", lambda f: "02_다른 청구서")
    page, frame, row, why = navigate.open_saved_sheet(object(), "202408470003", "02_2026년도 9월 (나)형 근로장학금", lambda m: None, lambda s: None)
    assert frame is None and "결의번호 323 의 것" in why and "결의서내역에 없는 번호" in why and "02_다른 청구서" in why
    # 숨은 번호가 목록의 다른 줄(224)이면 대표적요가 같아도 다른 청구서다
    calls, form_frame = _patch_list(monkeypatch, rows, seq="224")
    monkeypatch.setattr(navigate, "_appl_cont", lambda f: "02_2026년도 9월 (나)형 근로장학금")
    page, frame, row, why = navigate.open_saved_sheet(object(), "202408470003", "02_2026년도 9월 (나)형 근로장학금", lambda m: None, lambda s: None)
    assert frame is None and "결의번호 224 의 것" in why and "결의서내역의 다른 줄" in why
    # 이미 떠 있던 화면(누르기 전)은 대표적요만으로는 그 청구서로 보지 않는다 — 신청정보나 번호로만
    from claim_downloader.claims import form as form_mod
    calls, form_frame = _patch_list(monkeypatch, rows, seq="323")
    monkeypatch.setattr(navigate, "_shown_req_cnt", lambda f: "")
    monkeypatch.setattr(form_mod, "find_form", lambda ctx: ("창", form_frame))
    monkeypatch.setattr(navigate, "_sheet_state", lambda f: {"REQ_CNT": "323", "REQ_SEQ_NO": "TMP_1"})
    page, frame, row, why = navigate.open_saved_sheet(object(), "202408470003", "02_2026년도 9월 (나)형 근로장학금", lambda m: None, lambda s: None)
    assert frame is None and "누르기 전" not in why and "결의번호 323 의 것" in why and calls == ["줄:223", "상세조회"]


def test_claim_page_band_offers_reattach_and_starts_it_when_the_fill_stops(tmp_path, monkeypatch):
    """담당자 2026-10-23: 보완요청이 온 명단 폴더로 [ERP 에 넣기] 를 누르자 중복 확인 띠('이미 있습니다 — 결의번호 223(보완요청)')에 막혔다 —
    "그냥 장학금 청구하는 것처럼 파일만 다시 올려달라고". 띠에 [첨부만 다시 올리기] 가 보이고, 누르면 넣기를 멈춘 뒤 같은 폴더로 첨부만 다시 올리기를
    확인 창 없이 · '미리 보기만' 과 상관없이 · 브라우저 바쁨 표시가 남아 있어도 시작한다. 다른 물음(소득자 못 찾음)에는 그 단추가 없다."""
    from test_log_button import _close, _qt_app, _wait
    app = _qt_app()
    from claim_downloader.ui.pages import claim as claim_page
    from claim_downloader.ui.worker import SessionWorker
    from claim_downloader.claims import scholarship as sch

    folder = tmp_path / "9월"
    folder.mkdir()
    make_ga(folder / "2026학년도 (가)형 근로장학금 지급내역.xlsx")
    (folder / "공통증빙").mkdir()
    (folder / "공통증빙" / "공문.pdf").write_bytes(b"%PDF")
    (folder / "개별증빙").mkdir()
    (folder / "개별증빙" / "가나다.pdf").write_bytes(b"%PDF")
    worker = SessionWorker()
    page = claim_page.ClaimPage(worker=worker)
    answers: list[bool] = []
    started: list[tuple] = []
    shown: list[dict] = []
    monkeypatch.setattr(worker, "answer_relogin", lambda ok: answers.append(ok))
    monkeypatch.setattr(worker, "reattach_files", lambda plan, dry_run=True: started.append((plan, dry_run)))
    monkeypatch.setattr(claim_page, "show_report", lambda parent, **kw: shown.append(kw) or True)

    def no_warning(*a, **k):
        raise AssertionError("경고 창이 떠서는 안 된다")
    monkeypatch.setattr(claim_page.QMessageBox, "warning", no_warning)
    try:
        assert page.add_folder(str(folder), kinds.SCHOLARSHIP)
        assert _wait(app, lambda: page._jobs and page._jobs[0] is not None, 10)
        page._erp_row = 0
        page._erp_running = True
        page._browser_open = True
        page._on_sch_ask("ERP 결의서내역에 대표적요 '02_x' 청구서가 이미 있습니다 — 결의번호 223(보완요청 · 7,800,000원).\n"
                         "첨부문서만 바꾸려는 것이면(보완요청 · 임시저장) " + reattach.REATTACH_CHOICE + " — …")
        assert page.ask_banner.isVisibleTo(page) and page.reattach_now_button.isVisibleTo(page)
        page._answer_reattach()
        assert answers == [False] and page._reattach_pending == 0 and not page.reattach_now_button.isVisibleTo(page)
        assert page._actions == [claim_page.ACTION_REATTACH] and page.row_action.currentData() == claim_page.ACTION_REATTACH
        page._browser_busy = True                                   # 넣기가 막 멈춘 뒤 — 바쁨 표시가 아직 남아 있어도 보낸다
        assert page.dry_run.isChecked()                             # '미리 보기만' 이 켜져 있어도 실제로
        page._on_sch_done(sch.ScholarshipReport(dry_run=False, blocked="ERP 결의서내역에 대표적요가 같은 청구서가 있어 멈춤"))
        assert len(started) == 1 and started[0][1] is False and shown == []     # 확인 창 없이 바로
        assert started[0][0].rows and page._erp_running and page._reattach_pending == -1
        # 중복 확인이 아닌 물음에는 그 단추가 없다
        page._on_sch_ask("소득자를 찾지 못했습니다 — ERP 에서 고른 뒤 [계속]")
        assert page.ask_banner.isVisibleTo(page) and not page.reattach_now_button.isVisibleTo(page)
        page._answer(False)
        # 띠에서 [여기서 멈추기] 를 눌렀으면 첨부 다시 올리기로 가지 않는다 — 전처럼 까닭 창
        page._erp_running = True
        monkeypatch.setattr(claim_page.QMessageBox, "warning", lambda *a, **k: shown.append({"warning": a[2]}))
        page._on_sch_done(sch.ScholarshipReport(dry_run=False, blocked="멈춤"))
        assert len(started) == 1 and shown and "warning" in shown[-1]
    finally:
        _close(page)
        app.processEvents()


def test_session_reattach_tries_the_other_running_projects_when_the_folder_has_none(monkeypatch, job):
    """담당자 실제 2026-10-23 17:18: 폴더에 과제가 없어 마지막 과제 202409710003(대응자금)의 결의서내역에서 찾아 '없습니다' — 청구서 223 은
    202408470003 에 있었다. 과제가 비어 있으면 오늘이 기간에 든 다른 과제도 차례로 본다. 폴더에 과제가 있으면 그 과제만."""
    from claim_downloader import session as session_mod
    from claim_downloader import settings as settings_mod
    s = session_mod.ErpSession(lambda m: None, lambda m: True, should_stop=lambda: False, process=lambda *a: None,
                               load_settings=lambda: settings_mod.Settings(project_no="202409710003"))
    s.page = type("P", (), {"context": object()})()
    monkeypatch.setattr(type(s), "browser_open", property(lambda self: True))
    from claim_downloader.claims import form as form_mod
    monkeypatch.setattr(form_mod, "wait_for_form", lambda ctx, tries=12, log=None, **kw: (None, None))
    monkeypatch.setattr(s, "_typed_sheet", lambda f: [])
    monkeypatch.setattr(navigate, "choices", lambda selected, **kw: [("202409710003", "대응자금"), ("202408470003", "사업비")])

    class Page:
        def on(self, name, fn):
            pass

        def remove_listener(self, name, fn):
            pass

        def wait_for_timeout(self, ms):
            pass
    page = Page()
    tried: list[str] = []

    def open_saved_sheet(ctx, project, summary, log, wait, states=()):
        tried.append(project)
        if project == "202408470003":
            return page, "frame", {"seq": "223", "state": "보완요청"}, ""
        return None, None, {}, f"과제 {project} 의 결의서내역(2건)에 대표적요 '{summary}' 청구서가 없습니다"
    monkeypatch.setattr(navigate, "open_saved_sheet", open_saved_sheet)
    seen = {}

    def fake_run(pg, fr, pl, log, **kw):
        seen.update(kw)
        return reattach.ReattachReport(dry_run=False, plan=pl, req_cnt=kw["req_cnt"], state=kw["state"])
    monkeypatch.setattr(reattach, "run", fake_run)
    job.project_no = ""
    plan = reattach.plan_for_job(job)
    assert plan.project_no == "" and "비어 있음" in " ".join(plan.summary_lines())
    report = s.reattach_files(plan, dry_run=False)
    assert not report.blocked and seen["req_cnt"] == "223" and tried == ["202409710003", "202408470003"]
    # 폴더에 과제가 있으면 그 과제만 본다 — 없으면 그대로 멈춤
    tried.clear()
    job.project_no = "202409710003"
    report = s.reattach_files(reattach.plan_for_job(job), dry_run=False)
    assert report.blocked and "청구서가 없습니다" in report.blocked and tried == ["202409710003"]
    # 다른 과제에 둘 이상이면 그 까닭으로 멈춘다
    tried.clear()
    job.project_no = ""

    def many(ctx, project, summary, log, wait, states=()):
        tried.append(project)
        if project == "202408470003":
            return None, None, {}, "진행구분이 임시저장 · 보완 인 대표적요 '…' 청구서가 2개입니다"
        return None, None, {}, f"과제 {project} 의 결의서내역(2건)에 대표적요 '{summary}' 청구서가 없습니다"
    monkeypatch.setattr(navigate, "open_saved_sheet", many)
    report = s.reattach_files(reattach.plan_for_job(job), dry_run=False)
    assert report.blocked and "2개입니다" in report.blocked and "없습니다" in report.blocked and tried == ["202409710003", "202408470003"]
