"""작업 폴더 찾기 — 폴더 고르기 창이 처음 여는 곳(Qt 없음).

담당자의 작업 폴더는 바탕화면의 '★★지출진행' 아래 업무마다 하나다(`2. 카드` · `3. 출장비 및 프로그램참여지원비` …).
개인 경로를 코드에 적지 않고(9절) 설정 값이 있으면 그것, 없으면 바탕화면에서 이름으로 찾는다.
"""

from __future__ import annotations

from pathlib import Path

WORK = "지출진행"          # 바탕화면의 '★★지출진행' 폴더
CARD = "카드"              # 그 안의 '2. 카드' — 카드청구 결제 기간 폴더들이 있는 곳(담당자 2026-11-11)
TRAVEL = "출장비"          # 그 안의 '3. 출장비 및 프로그램참여지원비'(담당자 2026-11-10)


def find(saved: str, desktops, word: str) -> str:
    """설정한 폴더가 있으면 그것, 없으면 바탕화면들의 이름에 '지출진행' 이 든 폴더 안에서 이름에 word 가 든 첫 폴더.
    못 찾으면 ''(운영체제가 고른 곳)."""
    if saved and Path(saved).is_dir():
        return saved
    for desk in desktops:
        try:
            works = sorted(d for d in Path(desk).iterdir() if d.is_dir() and WORK in d.name)
        except OSError:
            continue
        for work in works:
            try:
                hits = sorted(d for d in work.iterdir() if d.is_dir() and word in d.name)
            except OSError:
                continue
            if hits:
                return str(hits[0])
    return ""
