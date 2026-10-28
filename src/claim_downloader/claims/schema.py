"""비목 이름 · 번호와 금액 읽기 — 명단 청구 · 카드청구 · 지급 공문 읽기가 같이 쓴다.

ERP #PAY_EXP_CD 의 보기 글자(2026-10-13 실측, CLAUDE.md 14절)와 적요 앞 비목 번호(8절)를 짝짓는다.
일반(AI 읽기) 청구의 dict 규약(KEYS · normalize · problems …)은 2026-10-28 그 종류와 함께 걷어냈다 — git 이력에만 있다.
"""
from __future__ import annotations

import re

from ..naming import normnm

# ERP #PAY_EXP_CD 의 보기 (실측 그대로). 적요 앞의 비목 번호와 짝지어 둔다.
CATEGORY_CODES = {
    "01": "인건비", "02": "장학금", "03": "교육·연구프로그램개발·운영비", "04": "교육·연구환경개선비",
    "05": "실험·실습장비및기자재구입·운영비", "06": "지자체 연계ㆍ협업비용", "07": "기업지원·협력활동비",
    "08": "성과활용·확산지원비", "09": "기타운영경비", "10": "간접비",
}
# 서류·보관 폴더에서 다르게 적히는 이름들 → 비목 번호
_CATEGORY_ALIASES = {
    "06": ["지역연계협업지원비", "지자체연계협업비용"],
    "09": ["그밖의사업운영경비", "그밖의사업운영비", "기타운영경비", "기타사업운영경비"],
}


def category_code(name) -> str:
    """비목 이름(어떤 표기든) → 번호. 모르면 ''."""
    key = normnm(name)
    if not key:
        return ""
    for code, canonical in CATEGORY_CODES.items():
        if key == normnm(canonical) or key in (normnm(a) for a in _CATEGORY_ALIASES.get(code, [])):
            return code
    if re.fullmatch(r"0?\d|10", key) and key.zfill(2) in CATEGORY_CODES:
        return key.zfill(2)
    return ""


def parse_amount(value) -> int | None:
    """'51,900원' · 51900 · '51900.0' → 51900. 못 읽으면 None."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(round(value))
    text = re.sub(r"[,\s원₩]", "", str(value))
    # 소수점이 있는 글('51900.0' · '51,900.00')은 실수로 읽는다 — 숫자만 남기면 점이 빠져 10배 · 100배가 됐다(2026-10-14 점검)
    if re.fullmatch(r"-?\d+(\.\d+)?", text):
        return int(round(float(text)))
    digits = re.sub(r"[^0-9\-]", "", text)
    try:
        return int(digits)
    except ValueError:
        return None
