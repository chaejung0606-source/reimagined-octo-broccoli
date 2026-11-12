"""학생이 낸 회의록 PDF 의 글자를 앱이 읽기(claims/minutes_pdf.py · card.pdf_minutes).

담당자 2026-11-12: WE-Meet 회의비 11건 미리 보기가 모두 'AI 가 읽는 중' 이라 회의 시각 · 장소 · 참석자가 비었다 — "아직 못읽는 것 같습니다" · 회의록 그림
(한글에서 PDF/A 로 저장한 표: 회의 일시 | 장 소 · 팀 명 · 참 석 자(구분 | 이름 | 학과 | 학번 | 연락처) · 회의 주제 · 안 건 · 회의 내용).
실제 PDF 의 글자 배치는 못 봤다 — pypdf 가 내놓을 만한 꼴 넷(한 줄에 칸 여럿 · 칸마다 줄 · 합친 칸 이름이 표 가운데 · 한 글자씩 띄움)으로 본다.
이름 · 학번 · 전화는 모두 가짜다.
"""
from __future__ import annotations

import datetime as dt

import pytest

from claim_downloader.claims import card, card_ai, card_erp, minutes_pdf

ROWS = """지도교수 가지도 컴퓨터공학과 - 010-1111-2222
교수 나교원 자유전공학부 - 010-3333-4444
대학원생 다대원 데이터사이언스학과 202630001 010-5555-6666
팀장 라팀장 컴퓨터공학과 202411111 010-7777-8888
팀원 마팀원 컴퓨터공학과 202110002 010-9999-0000"""
CONTENT = """이번 회의에서는 멘토링에서 안내받은 내용을 바탕으로 Kubernetes와 Slurm의 실습
준비 사항과 진행 순서를 논의하였다.
먼저 환경 설정을 위해 필요한 자료와 준비 사항을 공유하고, 추가로 확인해야 할
내용을 정리하였다."""
ONE_LINE = f"""[양식1] 회의록
WE-Meet 프로젝트 회의록
회의 일시 2026.10.12. 17:00 장 소 공학6호관 413호
팀 명 가나다GPU(가나다)
참 석 자
구분 이름 학과 학번 연락처
{ROWS}
회의 주제 Kubernetes·Slurm 실습 준비 및 진행 계획 점검
안 건
▪안건1: 멘토링 내용 공유 및 환경 설정 준비 사항 확인
▪안건2: 기본 실습 범위와 진행 순서 논의
회의 내용
{CONTENT}"""
PEOPLE = [("컴퓨터공학과", "가지도", ""), ("자유전공학부", "나교원", ""), ("데이터사이언스학과", "다대원", "202630001"),
          ("컴퓨터공학과", "라팀장", "202411111"), ("컴퓨터공학과", "마팀원", "202110002")]


def cell_per_line(text: str) -> str:
    return (text.replace(ROWS, "\n".join(ROWS.split()))
                .replace("구분 이름 학과 학번 연락처", "구분\n이름\n학과\n학번\n연락처")
                .replace("회의 일시 2026.10.12. 17:00 장 소 공학6호관 413호", "회의 일시\n2026.10.12. 17:00\n장 소\n공학6호관 413호"))


LAYOUTS = {
    "한 줄에 칸 여럿": ONE_LINE,
    "칸마다 줄": cell_per_line(ONE_LINE),
    "합친 '참 석 자' 가 표 가운데": ONE_LINE.replace("참 석 자\n구분", "구분").replace("팀장 라팀장", "참 석 자\n팀장 라팀장"),
    "한 글자씩 띄운 머리글 · 학과": ONE_LINE.replace("데이터사이언스학과", "데 이 터 사 이 언 스 학 과")
                                       .replace("구분 이름 학과 학번 연락처", "구 분 이 름 학 과 학 번 연 락 처"),
}


def test_the_minutes_form_is_read_in_every_likely_text_layout():
    for name, text in LAYOUTS.items():
        got = minutes_pdf.parse(text)
        assert (got.used, got.start, got.end) == (dt.date(2026, 10, 12), "17:00", ""), name
        assert got.place == "공학6호관 413호", name
        assert got.agenda == "Kubernetes·Slurm 실습 준비 및 진행 계획 점검", name      # 회의목적은 주제 한 줄
        assert got.people == PEOPLE, name                                           # 학번 '-' 은 번호 없음, 전화는 번호가 아님
        assert got.content[0].startswith("이번 회의에서는") and got.content[-1].endswith("정리하였다."), name
        assert minutes_pdf.looks_like(text, "SDU COSS_가나다_최종.pdf"), name    # 이름에 '회의록' 이 없어도


def test_other_minutes_shapes_colon_lines_and_sign_sheet_table():
    colon = minutes_pdf.parse("""회 의 록
1. 일시: 2026. 10. 15.(목) 오후 3시 ~ 4시 30분
2. 장소: 공학관 201호
3. 참석자: 가나다, 라마바(컴퓨터공학과), 사아자 외 1명
4. 안건: 프로젝트 중간 점검
5. 회의내용
지난주 진행 상황을 공유하였다.
사진 촬영은 다음 회의에 하기로 하였다.
사진
작성자: 가나다""")
    assert (colon.used, colon.start, colon.end, colon.place) == (dt.date(2026, 10, 15), "15:00", "16:30", "공학관 201호")
    assert colon.agenda == "프로젝트 중간 점검" and [p[1] for p in colon.people] == ["가나다", "라마바", "사아자"]
    # '사진 촬영은 …' 줄은 본문, '사진' 만 있는 줄 · '작성자' 줄에서 내용이 끝난다
    assert " ".join(colon.content) == "지난주 진행 상황을 공유하였다. 사진 촬영은 다음 회의에 하기로 하였다."
    sheet = minutes_pdf.parse("회의록\n회의일시 2026-10-20 14:00 회의장소 춘천 카페\n참석자\n소속 성명 서명\n"
                              "컴퓨터공학과 가나다\n컴퓨터 공학과 라마바\n경영학과 사아자\n회의내용\n사업 계획을 논의하였습니다.")
    assert sheet.people == [("컴퓨터공학과", "가나다", ""), ("컴퓨터 공학과", "라마바", ""), ("경영학과", "사아자", "")]


def test_a_notice_is_not_minutes_and_unreadable_text_leaves_a_masked_shape():
    notice = "수신 내부결재\n제목 WE-Meet 회의비 지원\n1. 일시: 2026.10.12.\n2. 참석자: 가나다\n회의록 제출\n시행 2026.10.01"
    assert not minutes_pdf.looks_like(notice, "공문.pdf")
    assert minutes_pdf.parse("회의록\n아무 칸도 없는 글").score() < 2
    lines = "\n".join(minutes_pdf.shape(ONE_LINE))
    for secret in ("라팀장", "202411111", "7777", "공학6호관", "Kubernetes"):
        assert secret not in lines
    assert "참 석 자" in lines and "구분 이름 학과 학번 연락처" in lines and "회의" in lines


def make_folder(tmp_path, minutes_name="SDU COSS_가나다_최종.pdf"):
    claim = tmp_path / "26-10(10.09. ~ 11.08.)" / "07_[기업지원협력활동비] 2026학년도 2학기 WE-Meet 회의비 1차 지원 (10.09~10.27.)"
    item = claim / "261012_(17)_가나다 147,000원"
    item.mkdir(parents=True)
    for name in (minutes_name, "영수증.jpg", "공문.pdf"):
        (item / name).write_text("x", encoding="utf-8")
    return claim, item


def test_the_card_item_reads_the_minutes_pdf_text_without_ai(tmp_path):
    claim, item_dir = make_folder(tmp_path)

    def read_text(path, pages=3):
        return ONE_LINE if path.endswith("최종.pdf") else ""
    job = card.load_job(str(claim), read_text=read_text)
    item = job.items[0]
    m = item.meeting
    assert item.minutes.endswith("최종.pdf") and item.req_div == "17" and not item.notice.endswith("최종.pdf")
    assert (m.used, m.start, m.end, m.end_guessed) == (dt.date(2026, 10, 12), "17:00", "18:00", True)
    assert m.place == "공학6호관 413호" and m.attendees[2] == ("데이터사이언스학과", "다대원")
    assert m.numbers == {"다대원": "202630001", "라팀장": "202411111", "마팀원": "202110002"}
    assert m.number_from["라팀장"] == "SDU COSS_가나다_최종.pdf"
    assert m.sources["place"] == "pdf" and card.ai_keys(m) == []
    assert card_ai.needs(item) == []                         # 금액은 폴더 이름, 회의 칸은 PDF 글자 — AI 를 부르지 않는다
    assert item.read_log and item.read_log[0].startswith("회의록 PDF 글자로 읽음: SDU COSS_가나다_최종.pdf — 참석자(표 5명 · 번호 3명)")
    assert not any("AI" in n for n in item.notes)
    values, plan, missing = card_erp.meeting_plan(item, [])
    assert not missing and values["CFRC_PLCE"] == "공학6호관 413호"
    assert [(a.name, a.emp_no) for a in plan][2:] == [("다대원", "202630001"), ("라팀장", "202411111"), ("마팀원", "202110002")]
    shown = {e.label: e for e in card_erp.plan_item(item, 1).entries}
    assert shown["장소"].source == "회의록 PDF 글자" and shown["장소"].check == "" and shown["내용"].check == ""
    assert shown["회의 시간"].value == "17:00 ~ 18:00"


def test_ai_fills_only_what_the_pdf_text_left_empty(tmp_path):
    claim, _item = make_folder(tmp_path, "회의록.pdf")
    text = ONE_LINE.replace("회의 내용\n" + CONTENT, "")
    ai = {"meeting": {"file": "회의록.pdf", "date": "2026-10-12", "start": "09:00", "end": "", "place": "다른 곳", "agenda": "",
                      "content": ["AI 가 정리한 회의 내용 문단입니다. 스무 자가 넘습니다."], "attendees": [{"org": "", "name": "가지도", "no": ""}]},
          "receipts": [], "snack": None, "notes": ""}
    job = card.load_job(str(claim), read_text=lambda path, pages=3: text if path.endswith("회의록.pdf") else "",
                        ai_lookup=lambda folder, files: ai)
    m = job.items[0].meeting
    assert m.place == "공학6호관 413호" and m.start == "17:00" and m.sources["place"] == "pdf"   # PDF 글자가 먼저
    assert m.content == ["AI 가 정리한 회의 내용 문단입니다. 스무 자가 넘습니다."] and card.ai_keys(m) == ["content"]
    assert len(m.attendees) == 5


def test_a_minutes_pdf_whose_cells_cannot_be_split_logs_its_masked_shape(tmp_path):
    claim, _item = make_folder(tmp_path, "회의록.pdf")
    job = card.load_job(str(claim), read_text=lambda path, pages=3: "회의록\n가나다 라마바 202411111\n아무 칸 이름 없음" if path.endswith("회의록.pdf") else "")
    item = job.items[0]
    assert item.meeting is None and card_ai.needs(item) == ["회의 내용"]
    assert item.read_log[0].startswith("회의록 PDF 의 칸을 글자로 못 나눔 — AI 로 읽습니다: 회의록.pdf")
    assert not any("라마바" in line or "202411111" in line for line in item.read_log)


def test_a_real_table_pdf_drawn_cell_by_cell_is_read_through_pypdf(tmp_path, monkeypatch):
    """한글이 PDF 로 저장하듯 표 칸마다 따로 그린 PDF — pypdf 는 배분 정렬한 칸 이름을 글자마다 줄을 바꿔('회\\n의\\n일\\n시') 내놓고,
    글꼴에 없는 쌍점 · 하이픈은 빠지거나 제어 문자로 나온다('17\\x1b00'). 그래도 칸을 읽는다."""
    pytest.importorskip("pypdf")
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtCore import QRectF, Qt
        from PySide6.QtGui import QFont, QPageSize, QPainter, QPdfWriter
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        pytest.skip(str(exc))
    QApplication.instance() or QApplication([])
    path = tmp_path / "SDU COSS_가나다_최종.pdf"
    writer = QPdfWriter(str(path))
    writer.setPageSize(QPageSize(QPageSize.A4))
    writer.setResolution(150)
    painter = QPainter(writer)
    painter.setFont(QFont("Sans", 9))

    def cell(x, y, w, h, text, spread=False):
        painter.drawRect(QRectF(x, y, w, h))
        if spread:                                       # 배분 정렬 — 글자마다 따로 그린다
            step = (w - 40) / max(1, len(text) - 1)
            for i, ch in enumerate(text):
                painter.drawText(QRectF(x + 5 + i * step, y, 30, h), Qt.AlignCenter, ch)
        else:
            painter.drawText(QRectF(x + 8, y + 4, w - 16, h - 8), Qt.AlignVCenter | Qt.AlignLeft | Qt.TextWordWrap, text)
    painter.drawText(QRectF(300, 110, 600, 50), Qt.AlignCenter, "WE-Meet 프로젝트 회의록")
    y = 180
    cell(100, y, 150, 50, "회의일시", True)
    cell(250, y, 300, 50, "2026.10.12.  17:00")
    cell(550, y, 150, 50, "장소", True)
    cell(700, y, 300, 50, "공학6호관 413호")
    y += 50
    cell(100, y, 150, 300, "참석자", True)
    for r, row in enumerate([["구분", "이름", "학과", "학번", "연락처"]] + [line.split() for line in ROWS.splitlines()]):
        for c, text in enumerate(row):
            cell(250 + c * 150, y + r * 50, 150, 50, text)
    y += 300
    cell(100, y, 150, 60, "회의주제", True)
    cell(250, y, 750, 60, "Kubernetes·Slurm 실습 준비 및 진행 계획 점검")
    y += 60
    cell(100, y, 150, 200, "회의내용", True)
    cell(250, y, 750, 200, CONTENT.replace("\n", " "))
    painter.end()
    text = card.pdf_text(str(path), pages=4)
    assert minutes_pdf.looks_like(text, path.name)
    got = minutes_pdf.parse(text)
    assert (got.used, got.start, got.place) == (dt.date(2026, 10, 12), "17:00", "공학6호관 413호")
    assert [(name, no) for _org, name, no in got.people] == [(name, no) for _org, name, no in PEOPLE]
    assert got.agenda.startswith("Kubernetes") and "정리하였다." in " ".join(got.content)
