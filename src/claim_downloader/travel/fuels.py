"""자차 연료 보기 — ERP 출장명령부(국내)교통비 창(rcomm_0027_07.act, CLAUDE.md 14절)의 '연비/전비/수소' 보기를 그대로 쓴다.

담당자 2026-11-10 "연료는 erp에서 출장 교통비 세부내역 작성할 때 연비/전비/수소에 있는 항목 중에 선택할 수 있도록 옵션을 설정해주세요.
이거 이전에 화면구조저장을 했는데 그때 기록 찾아서 해주세요". 그 기록(_화면구조.txt · _화면구조_모음.txt · 바탕화면 등에 복사한
화면구조_모음_*.txt)은 계좌 같은 값이 섞일 수 있어 저장소에 두지 않고 담당자 PC 에만 있다 — 그래서 앱이 담당자 PC 에서 그 파일들을 읽어
`#TRIP_FUEL`(연비/전비/수소) 고르기 칸의 보기 줄('보기: … | …', diagnose.py)을 찾고, 찾으면 설정 travel_fuel_options 에 남긴다
(모음 파일은 3MB 가 넘으면 새로 시작해 옛 기록이 사라질 수 있어서). 못 찾으면 남겨 둔 보기, 그것도 없으면 기본 보기(model.FUELS).
진단 모드는 보기를 앞 12개까지만 적는다(diagnose.py) — 그보다 많으면 뒤는 빠진다. Qt 없음.
"""
from __future__ import annotations

import re
from pathlib import Path

from .. import settings
from .model import FUELS

FIELD_ID = "#TRIP_FUEL"
LABEL = "연비/전비/수소"
# 보기가 아니라 고르라는 안내 글
PLACEHOLDERS = {"", "선택", "선택하세요", "전체", "연비/전비/수소", "-", "--"}
SEP = "|"


def from_text(text: str) -> list[str]:
    """화면 구조 글에서 연비/전비/수소 고르기 칸의 보기 — 여러 번 저장했으면 마지막 것. `#TRIP_FUEL` 줄이 먼저, 없으면 라벨 · 안내 글이
    '연비/전비/수소' 인 고르기 칸."""
    found: list[str] = []
    fallback: list[str] = []
    for line in (text or "").splitlines():
        if "<select" not in line or "보기:" not in line:
            continue
        options = _options(line)
        if not options:
            continue
        if FIELD_ID in line.split("보기:", 1)[0]:
            found = options
        elif LABEL in line:
            fallback = options
    return found or fallback


def _options(line: str) -> list[str]:
    tail = line.split("보기:", 1)[1]
    # 보기 뒤에 붙는 다른 항목(onclick= · class= · [비활성] …)은 두 칸 띄어쓰기로 이어진다
    tail = re.split(r"\s{2,}(?=onclick=|처리기=|href=|class=|\[)", tail)[0]
    out = []
    for option in tail.split(" | "):
        option = option.strip()
        if option not in PLACEHOLDERS and option not in out:
            out.append(option)
    return out


def structure_files() -> list[Path]:
    """화면 구조 기록이 있을 만한 파일들 — 사용자 폴더의 둘과 바탕화면 · 내려받기에 복사한 것. 새것이 뒤."""
    home = Path.home()
    folders = [settings.data_dir(), home / "Desktop", home / "바탕 화면", home / "OneDrive" / "Desktop",
               home / "OneDrive" / "바탕 화면", home / "Downloads"]
    files = {settings.structure_path(), settings.structure_book_path()}
    for folder in folders:
        try:
            files.update(p for p in folder.glob("*화면구조*.txt") if p.is_file())
        except OSError:
            continue
    existing = []
    for path in files:
        try:
            existing.append((path.stat().st_mtime, path))
        except OSError:
            continue
    return [p for _, p in sorted(existing)]


def find() -> tuple[list[str], Path | None]:
    """기록에서 찾은 보기와 그 파일 — 새 파일의 것이 먼저."""
    for path in reversed(structure_files()):
        try:
            options = from_text(path.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
        if options:
            return options, path
    return [], None


def options() -> tuple[list[str], str]:
    """연료 보기와 그 출처 글 — 기록에서 찾으면 설정에 남긴다."""
    found, path = find()
    saved = [o for o in settings.load().travel_fuel_options.split(SEP) if o.strip()]
    if found:
        if found != saved:
            settings.update(travel_fuel_options=SEP.join(found))
        return found, f"ERP 출장 교통비 창의 '연비/전비/수소' 보기({path.name} 에서 찾음)"
    if saved:
        return saved, "ERP 출장 교통비 창의 '연비/전비/수소' 보기(전에 찾아 둔 것)"
    return list(FUELS), ("ERP 화면 구조 기록에서 '연비/전비/수소' 보기를 찾지 못해 기본 보기를 씁니다 — ERP 의 출장명령부(국내)교통비 창을 띄우고 "
                         "화면 구조 저장 업무에서 [화면 구조 저장] 을 누르면 그 보기로 바뀝니다")
