"""개인정보 마스킹 — docs/04-architecture.md §6.

검토 대상이 개인정보 동의서인 앱이 정작 개인정보를 흘리면 안 된다.
리포트·로그로 나가는 모든 문자열은 여기를 거친다.

- `basic`  (기본) 주민등록번호는 전부 가리고, 계좌번호는 뒤 4자리만 남긴다.
- `strict` 성명·학번까지 가린다. 결과를 외부로 공유할 때 쓴다.
- `off`    가리지 않는다. 담당자 본인이 화면에서 원본을 대조할 때만.
"""
from __future__ import annotations

import re

LEVELS = ("off", "basic", "strict")

_RRN_RE = re.compile(r"(?<!\d)(\d{6})\s*-\s*(\d{7})(?!\d)")
_RRN_PACKED_RE = re.compile(r"(?<!\d)(\d{6})(\d{7})(?!\d)")
_ACCOUNT_RE = re.compile(r"(?<!\d)(\d{2,6})[-\s]?(\d{2,6})[-\s]?(\d{4,8})(?!\d)")
_NAME_RE = re.compile(r"(?<![가-힣])([가-힣])([가-힣]{1,3})(?![가-힣])")
_STUDENT_ID_RE = re.compile(r"(?<!\d)(20\d{2})(\d{4,6})(?!\d)")


def mask_rrn(text: str) -> str:
    text = _RRN_RE.sub(lambda m: f"{m.group(1)[:2]}****-*******", text)
    return _RRN_PACKED_RE.sub(lambda m: f"{m.group(1)[:2]}**********", text)


def mask_account(text: str) -> str:
    """계좌번호는 뒤 4자리만 남긴다 — 담당자가 어느 계좌인지는 알아야 한다."""
    def replace(match: re.Match) -> str:
        digits = "".join(match.groups())
        if len(digits) < 9:          # 계좌로 보기엔 짧다 (금액·날짜일 수 있다)
            return match.group(0)
        return "*" * (len(digits) - 4) + digits[-4:]
    return _ACCOUNT_RE.sub(replace, text)


def mask_name(text: str) -> str:
    return _NAME_RE.sub(lambda m: m.group(1) + "*" * len(m.group(2)), text)


def mask_student_id(text: str) -> str:
    return _STUDENT_ID_RE.sub(lambda m: f"{m.group(1)}{'x' * len(m.group(2))}", text)


def mask(text: str, level: str = "basic") -> str:
    """마스킹 단계를 적용한다."""
    if not text or level == "off":
        return text
    masked = mask_rrn(text)
    masked = mask_account(masked)
    if level == "strict":
        masked = mask_student_id(masked)
        masked = mask_name(masked)
    return masked
