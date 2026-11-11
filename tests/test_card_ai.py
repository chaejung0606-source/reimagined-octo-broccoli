"""카드청구 AI 읽기(claims/card_ai.py) — 글자로 못 읽는 영수증 사진 · 회의록 PDF 를 Claude Code 로 읽어 비운 자리만 채운다.

담당자 2026-11-11: "이전에는 사진으로 한글파일에 첨부된 영수증 읽었는데 왜 못읽는다고 하나요" → AI 로 읽기. 진짜 claude 는 부르지 않는다 —
읽은 결과(JSON)를 흉내 내거나, subprocess.run 을 바꿔 끼워 프롬프트에 적힌 자리로 결과 파일을 쓴다. 실명 · 실제 가맹점은 없다.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re

import pytest

from claim_downloader.claims import card, card_ai, card_erp
from claim_downloader.minutes.errors import BackendError
from claim_downloader.minutes.hwpx import build_hwpx

D = dt.date
CLAIM_07 = "07_[기업지원협력활동비] 2026학년도 2학기 WE-Meet 회의비 1차 지원 (10.09~10.27.)"
RECEIPT_JPG = "261012_가나다_교수님회의비영수증.jpg"
MINUTES_PDF = "SDU COSS_가나다_WE-Meet 프로젝트 회의록(261012)_최종.pdf"
NOTICE_PDF = "2026학년도 2학기 WE-Meet 회의비 1차 지원 (10.7~10.27.).pdf"

AI_DATA = {
    "receipts": [{"file": RECEIPT_JPG, "amount": "160,000원", "date": "2026-10-12", "time": "18:40", "merchant": "가나다카페",
                  "address": "강원특별자치도 춘천시 강원대학길 1", "cardLast4": "****-4321", "approvalNo": "3001-2345", "items": "아메리카노 8, 케이크 4"}],
    "meeting": {"file": MINUTES_PDF, "date": "2026-10-12", "start": "17시", "end": "18:30", "place": "공학관 세미나실",
                "agenda": "WE-Meet 프로젝트 2차 회의", "content": "역할을 나누고 다음 일정을 정하였음. 시제품 설계안을 함께 검토하였음.",
                "attendees": [{"org": "컴퓨터공학과", "name": "학생1"}, {"org": "", "name": "학생2"}, {"org": "x"}, "학생3"]},
    "snack": True,
    "notes": "",
}


def touch(path, text="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def make_item_folder(tmp_path):
    claim = tmp_path / "26-10(10.09. ~ 11.08.)" / CLAIM_07
    item = claim / "261012_(17)_가나다"
    touch(item / NOTICE_PDF)
    touch(item / RECEIPT_JPG)
    touch(item / MINUTES_PDF)
    touch(item / "기타" / "옛 영수증.jpg")
    return claim, item


def test_needs_only_what_the_text_reading_left_empty(tmp_path):
    claim, folder = make_item_folder(tmp_path)
    job = card.load_job(str(claim), read_text=lambda p: "")
    item = job.items[0]
    assert item.amount is None and card_ai.needs(item) == ["금액", "회의 내용"]
    assert card_ai.pending(job) == [item]
    item.status = "saved"                                        # 이미 넣은 결제 건은 읽지 않는다
    assert card_ai.needs(item) == []
    # 폴더 이름에 금액이 있고 기타(90)면 읽을 까닭이 없다
    other = claim / "261015_(90)_클로드 결제 22,000원"
    touch(other / "결제 화면.png")
    again = card.load_job(str(claim), read_text=lambda p: "")
    paid = next(i for i in again.items if i.title.startswith("클로드"))
    assert paid.amount == 22000 and card_ai.needs(paid) == []
    # 읽을 파일(PDF · 그림 · 한글 · 워드)이 없으면 읽지 않는다
    bare = claim / "261016_(90)_빈 폴더"
    touch(bare / "메모.txt")
    third = card.load_job(str(claim), read_text=lambda p: "")
    assert card_ai.needs(next(i for i in third.items if i.title == "빈 폴더")) == []


def test_clean_keeps_only_the_shape_the_app_uses():
    data = card_ai.clean(AI_DATA)
    receipt = data["receipts"][0]
    assert receipt["amount"] == 160000 and receipt["cardLast4"] == "4321" and receipt["file"] == RECEIPT_JPG
    meeting = data["meeting"]
    assert meeting["content"] == ["역할을 나누고 다음 일정을 정하였음. 시제품 설계안을 함께 검토하였음."]   # 문자열 하나도 문단으로
    assert meeting["attendees"] == [{"org": "컴퓨터공학과", "name": "학생1"}, {"org": "", "name": "학생2"}]   # 이름 없는 것 · 글자는 뺀다
    assert data["snack"] is True
    odd = card_ai.clean({"receipts": [{"amount": "모름"}, "x"], "meeting": {"file": "", "content": []}, "snack": "네"})
    assert odd["receipts"][0]["amount"] is None and odd["meeting"] is None and odd["snack"] is None
    assert "학생" not in card_ai.found_text(data) and "160" not in card_ai.found_text(data)        # 기록에는 값을 남기지 않는다
    assert card_ai.found_text(data) == "영수증 1장 · 금액 있음 · 회의록(참석자 2명 · 내용 있음)"


def test_cache_follows_the_files(tmp_path):
    _claim, folder = make_item_folder(tmp_path)
    files = card._files_under(str(folder))
    assert all("기타" not in p for p in files)
    assert card_ai.lookup(str(folder), files) is None
    card_ai.remember(str(folder), files, card_ai.clean(AI_DATA))
    assert card_ai.lookup(str(folder), files)["receipts"][0]["amount"] == 160000
    touch(folder / "서명부.pdf")                                   # 파일을 더하면 다시 읽는다
    assert card_ai.lookup(str(folder), card._files_under(str(folder))) is None
    assert card_ai.lookup(str(folder), files) is not None
    card_ai.forget(str(folder))
    assert card_ai.lookup(str(folder), files) is None
    assert card_ai.cache_path().name == "_카드AI읽기.json"


def test_ai_reading_fills_amount_meeting_and_snack(tmp_path):
    claim, folder = make_item_folder(tmp_path)
    data = card_ai.clean(AI_DATA)
    job = card.load_job(str(claim), read_text=lambda p: "", ai_lookup=lambda f, files: data)
    item = job.items[0]
    assert item.ai_read and item.amount == 160000 and item.amount_from == "영수증(AI 로 읽음)"
    assert (item.merchant, item.card_last, item.approval) == ("가나다카페", "4321", "30012345")
    assert item.shop_address.startswith("강원특별자치도 춘천시")
    assert not any("글자를 못 읽는 영수증" in n for n in item.notes)
    assert os.path.basename(item.minutes) == MINUTES_PDF
    m = item.meeting
    assert (m.start, m.end, m.place, m.agenda, m.used) == ("17:00", "18:30", "공학관 세미나실", "WE-Meet 프로젝트 2차 회의", D(2026, 10, 12))
    assert m.attendees == [("컴퓨터공학과", "학생1"), ("", "학생2")]
    assert item.snack and item.snack_from.startswith("AI")
    assert any("다과비로 봄(AI" in n for n in item.notes) and any("AI 가 회의록에서 읽음" in n for n in item.notes)
    assert not item.blocking() and card_ai.pending(job) == []
    values, people, missing = card_erp.meeting_plan(item, [])
    assert values["CFRC_PLCE"] == "공학관 세미나실" and len(people) == 2 and missing == []
    assert "금액" not in " ".join(job.problems())
    plan = card_erp.plan_item(item, 0, [])
    assert any("다과비" in line for line in plan.lines) and any("4명 이상 필요" in line for line in plan.lines)
    assert MINUTES_PDF in " ".join(plan.lines)                                    # 회의록 PDF 는 그대로 첨부


def test_text_and_folder_name_come_before_ai(tmp_path):
    claim = tmp_path / "26-10(10.09. ~ 11.08.)" / CLAIM_07
    folder = claim / "261012_(17)_가나다 150,000원"
    touch(folder / RECEIPT_JPG)
    minutes = folder / "2026-10-12 월 WE-Meet 회의.hwpx"
    build_hwpx({"filenameBase": "x", "agenda": "", "date": "2026. 10. 12. (월) 16:00 ~ 17:00", "place": "사업단 회의실",
                "expensePlace": "가나다카페", "amount": "150,000원", "attendeeCount": 0, "attendees": [],
                "content": [], "supplement": ""}, str(minutes))
    data = card_ai.clean(AI_DATA)
    item = card.load_job(str(claim), read_text=lambda p: "", ai_lookup=lambda f, files: data).items[0]
    assert item.amount == 150000 and item.amount_from == "폴더 이름"
    assert any("금액이 서로 다름" in n and "영수증(AI 로 읽음) 160,000" in n for n in item.notes)   # 사람이 적은 것이 먼저, 다르면 알림
    m = item.meeting
    assert (m.place, m.start, m.end) == ("사업단 회의실", "16:00", "17:00")       # 회의록 생성의 .hwpx 가 먼저
    assert m.agenda == "WE-Meet 프로젝트 2차 회의" and m.attendees == [("컴퓨터공학과", "학생1"), ("", "학생2")]   # 빈 칸만 AI 로
    assert item.minutes.endswith(".hwpx")


def test_start_time_only_means_one_hour_meeting(tmp_path):
    """회의일시에 시각이 하나면 시작 — 끝 시각은 시작 + 1시간(담당자 2026-11-11). 그래서 끝 시각 하나 때문에 AI 를 부르지 않는다."""
    assert card.end_after("16:00") == "17:00" and card.end_after("09:30") == "10:30"
    assert card.end_after("23:30") == "23:59" and card.end_after("") == ""
    claim = tmp_path / "26-10(10.09. ~ 11.08.)" / CLAIM_07
    folder = claim / "261012_(17)_가나다_150,000"
    touch(folder / RECEIPT_JPG)
    build_hwpx({"filenameBase": "x", "agenda": "WE-Meet 회의", "date": "2026. 10. 12. (월) 16:00", "place": "사업단 회의실",
                "expensePlace": "가나다카페", "amount": "150,000원", "attendeeCount": 1, "attendees": [{"org": "컴퓨터공학과", "name": "학생1"}],
                "content": ["프로젝트 진행 상황을 점검하고 다음 일정을 정하였음."], "supplement": ""},
               str(folder / "2026-10-12 월 WE-Meet 회의.hwpx"))
    job = card.load_job(str(claim), read_text=lambda p: "", ai_lookup=lambda f, files: None)
    item = job.items[0]
    assert (item.meeting.start, item.meeting.end, item.meeting.end_guessed) == ("16:00", "17:00", True)
    assert card_ai.needs(item) == [] and card_ai.pending(job) == []
    assert any("16:00~17:00 (끝 시각은 회의록에 없어 시작 + 1시간)" in line for line in card_erp.plan_item(item, 0, []).lines)
    # AI 가 읽은 회의록도 같다 — 끝 시각을 지어내지 않고 비워 두면 앱이 1시간으로
    data = card_ai.clean({**AI_DATA, "meeting": {**AI_DATA["meeting"], "end": ""}})
    claim2, _f = make_item_folder(tmp_path / "둘")
    m = card.load_job(str(claim2), read_text=lambda p: "", ai_lookup=lambda f, files: data).items[0].meeting
    assert (m.start, m.end, m.end_guessed) == ("17:00", "18:00", True)


def test_reading_failed_and_in_progress_are_shown_not_repeated(tmp_path):
    claim, _folder = make_item_folder(tmp_path)
    failed = card.load_job(str(claim), read_text=lambda p: "", ai_lookup=lambda f, files: {"failed": "Claude 로그인이 풀림"})
    item = failed.items[0]
    assert item.ai_read and card_ai.pending(failed) == []
    assert any(n == "AI 로 읽지 못함: Claude 로그인이 풀림" for n in item.notes) and "금액을 모름" in item.blocking()
    assert any("AI 로도" not in n and "글자를 못 읽는 영수증" in n for n in item.notes)
    reading = card.load_job(str(claim), read_text=lambda p: "", ai_lookup=lambda f, files: {"reading": True})
    assert card.AI_READING_NOTE in reading.items[0].notes and card_ai.pending(reading) == []
    empty = card.load_job(str(claim), read_text=lambda p: "",
                          ai_lookup=lambda f, files: card_ai.clean({"receipts": [{"file": RECEIPT_JPG, "amount": ""}], "meeting": None}))
    assert any(n.endswith("AI 로도 금액을 못 읽음") for n in empty.items[0].notes)


def test_read_runs_claude_on_the_listed_files_and_returns_clean_data(tmp_path, monkeypatch):
    _claim, folder = make_item_folder(tmp_path)
    files = card._files_under(str(folder))
    calls = []

    def fake_run(args, **kwargs):
        prompt = args[args.index("-p") + 1]
        calls.append((args, kwargs, prompt))
        path = re.search(r"정확히 '([^']+card\.json)'", prompt).group(1)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(AI_DATA, f, ensure_ascii=False)
        return type("R", (), {"returncode": 0, "stdout": "{}", "stderr": ""})()

    monkeypatch.setattr(card_ai, "find_claude", lambda: "claude")
    monkeypatch.setattr(card_ai.subprocess, "run", fake_run)
    data = card_ai.read(str(folder), files, model="")
    assert data["receipts"][0]["amount"] == 160000 and data["meeting"]["place"] == "공학관 세미나실"
    args, kwargs, prompt = calls[0]
    assert kwargs["cwd"] == str(folder) and "--add-dir" in args and "PowerShell" in args[args.index("--allowedTools") + 1]
    assert f"- {RECEIPT_JPG}" in prompt and f"- {MINUTES_PDF}" in prompt and "옛 영수증" not in prompt   # '기타' 폴더는 넘기지 않는다
    assert "지어내지 마세요" in prompt and "회의장소" in prompt

    def nothing(args, **kwargs):
        return type("R", (), {"returncode": 1, "stdout": "", "stderr": "Error: Invalid API key · Please run /login"})()

    monkeypatch.setattr(card_ai.subprocess, "run", nothing)
    with pytest.raises(BackendError):
        card_ai.read(str(folder), files, model="")
    monkeypatch.setattr(card_ai, "find_claude", lambda: "")
    with pytest.raises(BackendError, match="claude"):
        card_ai.read(str(folder), files, model="")


def test_claim_page_reads_with_ai_in_the_background_and_reloads(tmp_path, monkeypatch):
    """일반청구 카드 줄 — 금액을 모르는 결제 건은 뒤 스레드가 AI 로 읽고, 끝나면 그 폴더를 다시 읽어 금액 · 회의록이 채워진다. 넣기는 그동안 막힌다."""
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from claim_downloader.claims import kinds
    from claim_downloader.ui.pages import claim as claim_page
    from claim_downloader.ui.worker import SessionWorker
    claim, folder = make_item_folder(tmp_path)
    read_calls = []

    def fake_read(path, files, model=None):
        read_calls.append(os.path.basename(path))
        return card_ai.clean(AI_DATA)

    monkeypatch.setattr(card_ai, "read", fake_read)
    page = claim_page.ClaimPage(worker=SessionWorker())
    page._choose_kind(kinds.CARD)
    assert page.add_folder(str(claim), kinds.CARD)
    page.table.selectRow(0)
    assert page._status[0] == "ai" and page._card_ai_busy(page._cards[0])
    assert card.AI_READING_NOTE in page._cards[0].items[0].notes
    page._browser_open = True
    page.dry_run.setChecked(False)
    page._sync_buttons()
    assert not page.fill_button.isEnabled() and "읽는 중" in page.fill_button.toolTip()
    import time
    for _ in range(200):
        app.processEvents()
        if not page._ai_reading:
            break
        time.sleep(0.02)
    assert read_calls == ["261012_(17)_가나다"]
    item = page._cards[0].items[0]
    assert item.amount == 160000 and item.meeting.place == "공학관 세미나실" and page._status[0] in ("read", "problem")
    assert card_ai.lookup(str(folder), card._files_under(str(folder))) is not None          # 캐시에 남아 다시 읽지 않는다
    page._reload_card()
    app.processEvents()
    assert read_calls == ["261012_(17)_가나다"] and not page._ai_reading
    log = page.log_view.toPlainText()
    assert "AI(Claude Code)로 읽습니다" in log and "영수증 1장 · 금액 있음" in log and "가나다카페" not in log and "학생1" not in log
    page.shutdown()


def test_claim_page_asks_to_log_in_and_reads_again_once_logged_in(tmp_path, monkeypatch):
    """담당자 PC 2026-11-11 16:24 — Claude Code 가 로그인돼 있지 않아 첫 건에서 멈췄고 회의 시각 · 장소가 빈 채 남았다.
    이제 로그인 창을 열지 묻고, 위쪽 AI 단추가 '로그인됨' 이 되면 못 읽은 건을 저절로 다시 읽는다."""
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    import time

    from claim_downloader import ai
    from claim_downloader.claims import kinds
    from claim_downloader.ui import ai_status
    from claim_downloader.ui.pages import claim as claim_page
    from claim_downloader.ui.worker import SessionWorker
    claim, folder = make_item_folder(tmp_path)
    logged_in = {"yes": False}

    def fake_read(path, files, model=None):
        if not logged_in["yes"]:
            raise BackendError("Claude 에 로그인되어 있지 않음 (오른쪽 위 [Claude 로그인] 단추를 누르세요)")
        return card_ai.clean(AI_DATA)

    asked, opened = [], []
    monkeypatch.setattr(card_ai, "read", fake_read)
    monkeypatch.setattr(claim_page.QMessageBox, "question", lambda *a, **k: asked.append(a[1]) or claim_page.QMessageBox.Yes)
    monkeypatch.setattr(ai_status.AiStatus, "login", lambda self, parent=None, key="": opened.append(key) or True)

    def settle(page):
        for _ in range(200):
            app.processEvents()
            if not page._ai_reading:
                break
            time.sleep(0.02)
        app.processEvents()

    page = claim_page.ClaimPage(worker=SessionWorker())
    page._choose_kind(kinds.CARD)
    page.add_folder(str(claim), kinds.CARD)
    page.table.selectRow(0)
    settle(page)
    item = page._cards[0].items[0]
    assert item.amount is None and any("AI 로 읽지 못함" in n for n in item.notes)
    assert asked == ["Claude 로그인이 필요합니다"] and len(opened) == 1
    status = ai_status.instance()
    assert status.status(ai.chosen("minutes")).state == ai.NO_LOGIN
    logged_in["yes"] = True
    status.mark(ai.chosen("minutes"), ai.OK)                 # 로그인을 마치면 위쪽 AI 단추가 초록 — 앱이 저절로 다시 맡긴다
    settle(page)
    item = page._cards[0].items[0]
    assert item.amount == 160000 and item.meeting.place == "공학관 세미나실" and item.meeting.start == "17:00"
    assert "다시 읽습니다" in page.log_view.toPlainText()
    page.shutdown()
