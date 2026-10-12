"""회의록 데이터 — 모든 백엔드가 돌려줘야 하는 dict 의 모양과, 문서 양식의 고정값.

    build_hwpx() · build_docx() 는 이 dict 하나만 먹는다. 그 모양이 백엔드와의 계약이다.

  filenameBase    저장 파일명의 바탕 ('yyyy-mm-dd 요일 안건요약')
  agenda          회의안건
  date            회의일시 'YYYY. M. D. (요일) HH:MM ~ HH:MM'
  place           회의장소
  expensePlace    회의비 사용처(영수증 가맹점명)
  amount          금액 ('120,000원')
  attendeeCount   기안공문에 적힌 참석 인원 수 — 참석자 칸을 몇 줄 만들지만 정한다
  attendees       [{"org": 소속, "name": 이름}] 이름을 아는 사람만. 모자라는 칸은 빈칸(이름을 지어내지 않는다)
  content         회의내용 문단 목록. 길이 2 또는 3
  supplement      보완요청. 없으면 정확히 '보완사항 없음'

값을 못 찾으면 빈 문자열·빈 배열·0 이다(추측 금지). 키가 빠져도 문서는 만들어지므로 여기서 막지
않고, problems() 로 이상한 점만 기록에 남긴다.
"""
from __future__ import annotations

import re

# 양식 고정값
FONT = "맑은 고딕"
HEADER_TITLE = "데이터보안·활용 융합 혁신융합대학사업단 회의록"
PROJECT_NAME = "첨단분야 혁신 융합대학 (데이터보안·활용융합)"
DEFAULT_ORG = "강원대학교"
SHADE = "F2F2F2"                   # 표 라벨 칸의 바탕색

KEYS = ("filenameBase", "agenda", "date", "place", "expensePlace", "amount",
        "attendeeCount", "attendees", "content", "supplement")


def problems(data) -> list[str]:
    """계약에서 벗어난 점. 문서는 그래도 만들어지므로 기록용이다."""
    found = []
    if not isinstance(data, dict):
        return ["dict 가 아님"]
    for key in KEYS:
        if key not in data:
            found.append(f"'{key}' 없음")
    content = data.get("content", [])
    if isinstance(content, str):
        content = [content]
    if not isinstance(content, list) or len(content) not in (2, 3):
        found.append("content 문단 수가 2 또는 3 이 아님")
    if not isinstance(data.get("attendees", []), list):
        found.append("attendees 가 목록이 아님")
    return found


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _norm_att(a):
    if isinstance(a, dict):
        org = str(a.get("org") or a.get("소속") or "").strip()
        name = str(a.get("name") or a.get("이름") or "").strip()
    else:
        org, name = "", str(a).strip()
    return (org or DEFAULT_ORG), name


def _attendee_rows(data):
    """참석자 표에 넣을 (소속, 이름) 목록.

    회의비 기안공문에 적힌 인원 수(attendeeCount)만큼 칸을 만든다.
    이름을 아는 사람부터 채우고, 모자라는 만큼은 빈칸으로 남겨
    나중에 손으로 적을 수 있게 한다."""
    rows = [_norm_att(a) for a in (data.get("attendees") or []) if _norm_att(a)[1]]
    try:
        want = int(re.sub(r"[^0-9]", "", str(data.get("attendeeCount") or "")) or 0)
    except Exception:
        want = 0
    want = min(want, 60)                 # 비정상적으로 큰 값 방어
    while len(rows) < want:
        rows.append((DEFAULT_ORG, ""))
    return rows or [(DEFAULT_ORG, "")]
