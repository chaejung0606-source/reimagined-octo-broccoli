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


def test_plan_for_general_folder_takes_ai_attachments_or_all_files(tmp_path):
    folder = tmp_path / "정수기"
    folder.mkdir()
    for name in ("세금계산서.pdf", "견적서.pdf", "메모.zip"):
        (folder / name).write_bytes(b"x")
    data = {"summary": "09_정수기 임차료(9월)", "attachments": ["세금계산서.pdf", "없는파일.pdf"]}
    plan = reattach.plan_for(kinds.GENERAL, str(folder), data, project_no="202408470003")
    assert plan.rows[0].names == ["세금계산서.pdf"] and plan.rows[0].summary == "09_정수기 임차료(9월)" and not plan.problems
    plan = reattach.plan_for(kinds.TAXBILL, str(folder), {"summary": "09_정수기"})
    assert plan.rows[0].names == ["견적서.pdf", "세금계산서.pdf"]        # 압축 파일은 빼고 폴더 바로 아래 전부
    plan = reattach.plan_for(kinds.GENERAL, str(folder), {})
    assert any("적요" in p for p in plan.problems)
    assert reattach.plan_for(kinds.CARD, str(folder)).problems and not reattach.plan_for(kinds.CARD, str(folder)).rows
    assert reattach.plan_for(kinds.SCHOLARSHIP, str(folder), job=None).problems


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


def test_general_claim_matches_the_only_row(tmp_path, monkeypatch):
    folder = tmp_path / "정수기"
    folder.mkdir()
    (folder / "세금계산서.pdf").write_bytes(b"x")
    plan = reattach.plan_for(kinds.GENERAL, str(folder), {"summary": "09_정수기 임차료(9월)"})
    frame = FakeSheet(rows=["1 일반 09_정수기 임차료(9월) 51,900"], files=[["옛.pdf"]])
    frame.amounts = ["51,900"]
    monkeypatch.setattr(attach, "upload", _upload_fake(frame, []))
    report = reattach.run(object(), frame, plan, lambda m: None, wait=lambda s: None, dry_run=False)
    assert report.saved == 1 and frame.files[0] == ["세금계산서.pdf"]
    # 줄이 여럿이면 적요가 든 줄만
    assert reattach.match_rows(plan, ["1 일반 09_다른 것 1,000", "2 일반 09_정수기 임차료(9월) 51,900"]) == {0: [1]}
    assert reattach.match_rows(plan, ["1 일반 09_다른 것 1,000", "2 일반 09_또 다른 것 2,000"]) == {0: []}


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
    """일반청구 ③ 의 [첨부만 다시 올리기] — 명단 폴더를 넣으면 보이고, '미리 보기만' 이면 브라우저 없이 표 창(줄마다 붙일 파일)을 띄운다."""
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
        assert page.reattach_button.isVisibleTo(page) and page.reattach_button.isEnabled() and page.dry_run.isChecked()
        page._reattach()
        assert _wait(app, lambda: bool(shown), 15)
        kw = shown[0]
        assert kw["columns"] == claim_page.REATTACH_COLUMNS and len(kw["rows"]) == 2
        assert kw["rows"][0].cells[1] == "가나다" and kw["rows"][0].cells[3] == "2개" and kw["rows"][1].cells[3] == "1개"
        assert "7월" in " ".join(kw["summary"]) and "미리 보기" in kw["title"]
        assert not page._erp_running
    finally:
        _close(page)
        app.processEvents()
