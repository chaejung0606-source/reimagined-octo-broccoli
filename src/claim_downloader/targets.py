"""목록에서 받을 대상 고르기.

대상: 진행구분 '승인' + 문서번호 있음 + 지출예정일 있음, 결의서구분의 반납·자금대체 제외.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# 보관 폴더가 제대로 읽혔다면 대상은 보통 한 자릿수다. 이보다 많은데 건너뛴 건이
# 대상보다 적으면, 보관 폴더를 잘못 가리키고 있을 가능성이 크다.
MANY_TARGETS = 20


@dataclass
class Selection:
    targets: list[dict] = field(default_factory=list)
    skipped: int = 0      # 이미 받은(보관된) 건


def select_targets(rows: list[dict], done: set[str]) -> Selection:
    sel = Selection()
    for r in rows:
        if re.search(r"반납|자금대체", r.get("gubun") or ""):
            continue
        state = (r.get("state") or "").replace(" ", "")
        if state != "승인" or not r.get("docNo") or not r.get("expDt"):
            continue
        if r["docNo"] in done:
            sel.skipped += 1
            continue
        sel.targets.append(r)
    return sel


def volume_warning(sel: Selection) -> str:
    n = len(sel.targets)
    if n >= MANY_TARGETS and sel.skipped < n:
        return (f"⚠⚠ 받을 건이 {n}건으로 많습니다(이미 보관되어 건너뛴 건 {sel.skipped}건).\n"
                "      저장 폴더가 맞는지 먼저 확인하세요. 처음 쓰는 것이라면 그대로 진행해도 됩니다.")
    return ""
