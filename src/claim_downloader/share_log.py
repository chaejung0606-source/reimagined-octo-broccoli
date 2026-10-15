"""문제 보내기 — 최근 실행 기록(_실행로그.txt)에서 개인정보를 가린 사본을 만든다. Qt 없음(테스트가 PySide6 없이 본다).

담당자는 문제가 생기면 `_실행로그.txt` 를 통째로 채팅에 붙여 왔다. 그 기록에는 학생 이름 · 학번 · 계좌번호 · 예금주가 그대로 있어
(장학금 흐름이 진단을 위해 남긴다) 매번 손으로 가려야 했다. 그래서 가린 사본을 `_공유용로그.txt` 로 남기고 클립보드에 복사한다.

가리는 것: 주민번호 · 계좌번호(끝 4자리만 남김) · 학번(입학 연도만 남김) · 전화 · 메일 · 사용자 폴더 이름 · 이름.
이름은 규칙으로 다 찾을 수 없다 — 앱에 읽어 둔 명단의 이름(names)과, 기록에서 이름이 오는 자리(예금주 · '성공:' · 파일명의
`_이체자_(금액)` · 'N. 이름 (학번' 등)을 가린다. 그래서 보내기 전에 한 번 훑어보시라고 안내한다.
진단에 필요한 것(시각 · 단계 · ERP 알림 · 금액 · 문서번호 · 결의번호 · 날짜)은 그대로 둔다.
"""
from __future__ import annotations

import re
import time
from collections.abc import Iterable
from pathlib import Path

from . import settings

TAIL_LINES = 800                 # 최근 기록만 — 문제 하나를 보는 데는 이만큼이면 된다
HIDDEN = "○"


def mask_name(name: str) -> str:
    name = str(name or "").strip()
    if not name:
        return name
    if re.search(r"[가-힣]", name):
        return name[0] + HIDDEN * max(1, len(name) - 1)
    return name[0] + "***"


def _keep_last(match: re.Match, keep: int = 4) -> str:
    """숫자는 끝 keep 자리만 남기고 *, 하이픈 · 공백 자리는 그대로."""
    text = match.group(0)
    total = sum(c.isdigit() for c in text)
    seen = 0
    out = []
    for c in text:
        if c.isdigit():
            seen += 1
            out.append(c if seen > total - keep else "*")
        else:
            out.append(c)
    return "".join(out)


_SSN = re.compile(r"(?<![\d*#])[\d#*]{6}\s?-\s?[1-8#*][\d#*]{6}(?![\d*#])")
_PHONE = re.compile(r"(?<!\d)01[016789]-?\d{3,4}-?\d{4}(?!\d)")
_MAIL = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
_DASHED = re.compile(r"(?<![\w-])\d{2,8}(?:-\d{1,8}){1,4}(?![\w-])")
_LONG = re.compile(r"(?<!\d)\d{10,16}(?!\d)")
_STUDENT_NO = re.compile(r"(?<![\d-])(20\d{2})\d{5}(?![\d-])")
_WIN_USER = re.compile(r"(?i)([A-Z]:\\Users\\)[^\\\s/]+")
_NIX_USER = re.compile(r"(/home/|/Users/)[^/\s]+")
# 기록에서 이름이 오는 자리(scholarship · session 의 log 글 모양). 여기서 찾은 이름은 기록 전체에서 가린다 —
# 같은 학생이 적요 · 파일 경로 · 신청 전 확인 줄에도 나오는데 그 자리는 이름인지 알 수 없어서다.
_NAME_SPOTS = [
    re.compile(r"(성공\s*:\s*)([^\s·/,)'\]]+(?: [A-Z]{1,4})?)"),                      # 예금주조회 결과
    re.compile(r"(· 예금주 )([^·\s(][^·]*?)(?= · )"),                                 # 소득자를 고른 뒤 ERP 계좌: … · 예금주 X · …
    re.compile(r"(비어 있어 ')([^']+)(?=' 을)"),                                       # 예금주 칸이 비어 있어 'X' 을(를) 넣음
    re.compile(r"(_)([가-힣]{2,5})(?=(?: 등 \d+명)?_\()"),                            # 받은 파일명 _이체자_(금액)
    re.compile(r"((?:^|\s|\()\d{1,3}\. )([가-힣]{2,5}|[A-Z][A-Z ]{2,30}[A-Z])(?= \(| —|\(|:|$)", re.M),   # 1. 이름 (학번 …
    re.compile(r"(소득자 자동 선택: )([^(\s]+)(?=\()"),
    re.compile(r"(^|[\s_(])([가-힣]{2,4})(?= 등 \d+명)", re.M),                      # 첫이름 등 N명
]
# 이름 자리에 올 수 있지만 이름이 아닌 말 — 기록 전체에서 가리면 글이 망가진다
_NOT_NAMES = {"학생", "사람", "외국인", "교수", "직원", "강사", "비어", "없음", "확인", "저장", "멈춤", "학번", "이름"}


def harvest_names(text: str) -> set[str]:
    found = set()
    for spot in _NAME_SPOTS:
        for m in spot.finditer(text):
            name = m.group(2).strip()
            if len(name) >= 2 and name not in _NOT_NAMES and not re.search(r"\d", name):
                found.add(name)
    return found


def _is_document_number(text: str) -> bool:
    """문서번호 · 결의서 번호(과제번호-YYYYMMDD-N) · 날짜는 개인정보가 아니고 진단에 쓴다."""
    head = text.split("-")[0]
    return bool(re.fullmatch(r"20\d{6}", head)) or bool(re.fullmatch(r"20\d{2}-\d{1,2}-\d{1,2}", text))


def mask_text(text: str, names: Iterable[str] = ()) -> str:
    text = _SSN.sub("******-*******", text)
    text = _PHONE.sub(lambda m: m.group(0)[:3] + "-****-****", text)
    text = _MAIL.sub(lambda m: "***@" + m.group(1), text)
    text = _DASHED.sub(lambda m: m.group(0) if _is_document_number(m.group(0)) or sum(c.isdigit() for c in m.group(0)) < 10
                       else _keep_last(m), text)
    text = _LONG.sub(_keep_last, text)
    text = _STUDENT_NO.sub(lambda m: m.group(1) + "*****", text)
    text = _WIN_USER.sub(r"\1<사용자>", text)
    text = _NIX_USER.sub(r"\1<사용자>", text)
    every = {str(n).strip() for n in names if n and len(str(n).strip()) >= 2} | harvest_names(text)
    for name in sorted(every, key=len, reverse=True):          # '김민수' 를 '김민' 보다 먼저
        text = text.replace(name, mask_name(name))
    return text


def tail(path: Path, lines: int = TAIL_LINES) -> str:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(raw.splitlines()[-lines:])


def build(names: Iterable[str] = (), version: str = "", lines: int = TAIL_LINES) -> tuple[str, Path]:
    """가린 사본을 _공유용로그.txt 로 쓰고 (글, 경로) 를 돌려준다. 기록이 없으면 글이 비어 있다."""
    body = tail(settings.log_path(), lines)
    path = settings.data_dir() / "_공유용로그.txt"
    if not body.strip():
        return "", path
    head = [
        "COSS 업무데스크 공유용 기록 — 주민번호 · 계좌 · 학번 · 전화 · 메일 · 이름을 가렸습니다.",
        f"만든 때 {time.strftime('%Y-%m-%d %H:%M')}" + (f" · 앱 {version}" if version else "") + f" · 최근 {lines}줄",
        "─" * 40,
    ]
    text = "\n".join(head) + "\n" + mask_text(body, names) + "\n"
    path.write_text(text, encoding="utf-8")
    return text, path
