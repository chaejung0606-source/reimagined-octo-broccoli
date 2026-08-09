"""정규화 함수 — docs/03-field-dictionary.md §1 구현.

서류마다 표기가 제각각이라 비교 전에 반드시 정규화한다.
이 단계를 빼면 오탐이 대부분이다. (예: `592201-01-565992` vs `59220101565992`)
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime

__all__ = [
    "digits_only",
    "strip_spaces",
    "bank_alias",
    "money",
    "parse_date",
    "parse_datetime",
    "parse_hours",
    "parse_time",
    "hangul_amount",
    "parse_hangul_amount",
    "region_of",
    "regions_of",
    "RegionSet",
    "similarity",
    "is_blank",
]

# 전각 공백·비가시 문자까지 포함한다. 한글 PDF 는 U+00A0, U+3000 을 자주 흘린다.
_SPACE_RE = re.compile(r"[\s  -‏  　﻿]+")
_DIGIT_RE = re.compile(r"\d+")


def is_blank(value) -> bool:
    """None / 빈 문자열 / 공백만 있는 문자열을 '값 없음'으로 본다."""
    if value is None:
        return True
    if isinstance(value, str):
        return _SPACE_RE.sub("", value) == ""
    return False


def strip_spaces(value) -> str | None:
    """`권 석 재` → `권석재`. 표 추출 시 글자 사이에 공백이 끼는 경우가 흔하다."""
    if is_blank(value):
        return None
    return _SPACE_RE.sub("", str(value))


def digits_only(value) -> str | None:
    """`592201-01-565992` → `59220101565992`."""
    if is_blank(value):
        return None
    out = "".join(_DIGIT_RE.findall(str(value)))
    return out or None


# ---------------------------------------------------------------- 은행 별칭

# 서류마다 `국민` / `국민은행` / `KB국민은행` 이 섞여 나온다. 정식명칭으로 모은다.
_BANK_ALIASES: dict[str, str] = {}


def _register_bank(canonical: str, *aliases: str) -> None:
    _BANK_ALIASES[canonical] = canonical
    for alias in aliases:
        _BANK_ALIASES[alias] = canonical


_register_bank("국민은행", "국민", "KB", "KB국민", "KB국민은행", "kb국민은행")
_register_bank("신한은행", "신한", "신한금융", "SHINHAN")
_register_bank("우리은행", "우리")
_register_bank("하나은행", "하나", "KEB하나", "KEB하나은행", "외환은행")
_register_bank("농협은행", "농협", "NH", "NH농협", "NH농협은행", "단위농협", "지역농협")
_register_bank("기업은행", "기업", "IBK", "IBK기업", "IBK기업은행")
_register_bank("카카오뱅크", "카카오", "카뱅")
_register_bank("케이뱅크", "K뱅크", "케이", "kbank")
_register_bank("토스뱅크", "토스")
_register_bank("새마을금고", "새마을", "MG새마을금고", "MG새마을")
_register_bank("신협", "신용협동조합")
_register_bank("우체국", "우정사업본부", "우체국예금")
_register_bank("수협은행", "수협")
_register_bank("부산은행", "부산")
_register_bank("대구은행", "대구", "iM뱅크", "아이엠뱅크")
_register_bank("경남은행", "경남")
_register_bank("광주은행", "광주")
_register_bank("전북은행", "전북")
_register_bank("제주은행", "제주")
_register_bank("산업은행", "KDB", "KDB산업은행")
_register_bank("SC제일은행", "SC", "제일은행", "SC은행")
_register_bank("씨티은행", "씨티", "한국씨티은행")


def bank_alias(value) -> str | None:
    """`국민` → `국민은행`, `카카오` → `카카오뱅크`. 사전에 없으면 공백만 제거해 돌려준다."""
    key = strip_spaces(value)
    if key is None:
        return None
    if key in _BANK_ALIASES:
        return _BANK_ALIASES[key]
    upper = key.upper()
    if upper in _BANK_ALIASES:
        return _BANK_ALIASES[upper]
    # `(주)카카오뱅크`, `카카오뱅크(주)` 같은 군더더기를 떼고 한 번 더 본다.
    trimmed = re.sub(r"\(주\)|주식회사|㈜", "", key)
    if trimmed in _BANK_ALIASES:
        return _BANK_ALIASES[trimmed]
    return key


# ------------------------------------------------------------------- 금액

def money(value) -> int | None:
    """`1,200원` → `1200`. 음수(`-1,200`)와 `\\` 접두도 받는다."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = strip_spaces(value)
    if text is None:
        return None
    negative = text.lstrip().startswith("-") or "△" in text or "▲" in text
    digits = digits_only(text)
    if digits is None:
        return None
    return -int(digits) if negative else int(digits)


# ------------------------------------------------------------------- 날짜

# `2026.06.29.` / `2026-06-29` / `2026/6/29` / `26/03/9`
_YMD_RE = re.compile(r"(?<!\d)(\d{2,4})\s*[.\-/]\s*(\d{1,2})\s*[.\-/]\s*(\d{1,2})\s*\.?(?!\d)")
# `2026년 6월 29일`
_KOR_YMD_RE = re.compile(r"(\d{2,4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")
# `6월 29일` — 연도는 문맥(default_year)에서 받는다.
_KOR_MD_RE = re.compile(r"(?<!\d)(\d{1,2})\s*월\s*(\d{1,2})\s*일")
# `7/3`, `6/29` — 근무상황부·영수증에서 흔하다.
_MD_RE = re.compile(r"(?<!\d)(\d{1,2})\s*[./\-]\s*(\d{1,2})(?!\s*[./\-]?\d)")
# `13시20분` / `13:20` / `09:00`
_TIME_RE = re.compile(r"(?<!\d)(\d{1,2})\s*(?::|시)\s*(\d{1,2})\s*분?(?!\d)")


def _expand_year(raw: int) -> int:
    """2자리 연도 보정. `26` → `2026`. 근무상황부 손글씨에서 흔하다."""
    if raw >= 1900:
        return raw
    if raw < 100:
        return 2000 + raw
    return raw


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(_expand_year(year), month, day)
    except ValueError:
        return None


def parse_date(value, default_year: int | None = None) -> date | None:
    """docs 에 나열된 표기를 전부 흡수한다.

    `2026.06.29.` `26/03/9` `2026년 6월 29일` `2026. 03. 31.` → `date(2026, 6, 29)` 등.
    연도가 없는 `6월 29일` / `6/29` 는 ``default_year`` 가 있을 때만 해석한다.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value)
    if is_blank(text):
        return None

    m = _KOR_YMD_RE.search(text)
    if m:
        return _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    m = _YMD_RE.search(text)
    if m:
        return _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    if default_year is not None:
        m = _KOR_MD_RE.search(text)
        if m:
            return _safe_date(default_year, int(m.group(1)), int(m.group(2)))
        m = _MD_RE.search(text)
        if m:
            return _safe_date(default_year, int(m.group(1)), int(m.group(2)))
    return None


def parse_time(value) -> tuple[int, int] | None:
    """`09:00` / `13시20분` → `(9, 0)` / `(13, 20)`."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.hour, value.minute
    text = str(value)
    m = _TIME_RE.search(text)
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2))
    if not (0 <= hour <= 24 and 0 <= minute < 60):
        return None
    return hour, minute


def parse_datetime(value, default_year: int | None = None) -> datetime | None:
    """`2026년07월03일 13시20분` → `datetime(2026, 7, 3, 13, 20)`.

    시각이 없으면 00:00 으로 채운다. 날짜가 없으면 None.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    day = parse_date(value, default_year=default_year)
    if day is None:
        return None
    clock = parse_time(value)
    if clock is None:
        return datetime(day.year, day.month, day.day)
    hour, minute = clock
    if hour == 24:  # `24:00` 은 그날의 끝으로 본다.
        return datetime(day.year, day.month, day.day, 23, 59)
    return datetime(day.year, day.month, day.day, hour, minute)


# ------------------------------------------------------------------- 시간

_HOURS_RE = re.compile(r"(?<!\d)(\d+(?:\.\d+)?)\s*(?:시간|h|H)?")


def parse_hours(value) -> float | None:
    """`5`, `5시간`, `5.0` → `5.0`. `4시간 30분` → `4.5`."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = strip_spaces(value)
    if text is None:
        return None
    hm = re.search(r"(\d+)\s*시간\s*(\d+)\s*분", text)
    if hm:
        return int(hm.group(1)) + int(hm.group(2)) / 60
    m = _HOURS_RE.search(text)
    if not m:
        return None
    return float(m.group(1))


# -------------------------------------------------------------- 한글 금액

_DIGIT_HANGUL = ["", "일", "이", "삼", "사", "오", "육", "칠", "팔", "구"]
_SMALL_UNITS = ["", "십", "백", "천"]
_BIG_UNITS = ["", "만", "억", "조", "경"]


def _hangul_below_10000(chunk: int) -> str:
    out = ""
    for position in range(4):
        digit = (chunk // (10**position)) % 10
        if digit == 0:
            continue
        # `일십` `일백` 은 쓰지 않는다 (`십오만` 이지 `일십오만` 이 아니다).
        head = "" if (digit == 1 and position > 0) else _DIGIT_HANGUL[digit]
        out = head + _SMALL_UNITS[position] + out
    return out


def hangul_amount(value) -> str | None:
    """`240000` → `금이십사만원정`. R-INN-002 가 쓰는 함수."""
    amount = money(value)
    if amount is None:
        return None
    if amount == 0:
        return "금영원정"
    sign = "-" if amount < 0 else ""
    amount = abs(amount)

    parts: list[str] = []
    index = 0
    while amount > 0:
        chunk = amount % 10000
        if chunk:
            parts.append(_hangul_below_10000(chunk) + _BIG_UNITS[index])
        amount //= 10000
        index += 1
    return f"{sign}금" + "".join(reversed(parts)) + "원정"


_HANGUL_DIGITS = {h: i for i, h in enumerate(_DIGIT_HANGUL) if h}
_HANGUL_SMALL = {"십": 10, "백": 100, "천": 1000}
_HANGUL_BIG = {"만": 10**4, "억": 10**8, "조": 10**12, "경": 10**16}


def parse_hangul_amount(value) -> int | None:
    """`금이십사만원정` → `240000`. 서류에 적힌 한글 표기를 숫자로 되돌린다."""
    text = strip_spaces(value)
    if text is None:
        return None
    text = text.strip("금").replace("원정", "").replace("원", "")
    if not text:
        return None

    total = 0
    section = 0
    current = 0
    for char in text:
        if char in _HANGUL_DIGITS:
            current = _HANGUL_DIGITS[char]
        elif char in _HANGUL_SMALL:
            section += (current or 1) * _HANGUL_SMALL[char]
            current = 0
        elif char in _HANGUL_BIG:
            section += current
            total += (section or 1) * _HANGUL_BIG[char]
            section = 0
            current = 0
        elif char.isdigit():
            current = current * 10 + int(char)
        else:
            return None
    return total + section + current


# --------------------------------------------------------------- 지역 비교

# 긴 표기를 먼저 지워야 `서울특별시` 에서 `특별시` 가 남지 않는다.
_SIDO_ALIASES: list[tuple[str, tuple[str, ...]]] = [
    ("강원", ("강원특별자치도", "강원도", "강원")),
    ("서울", ("서울특별시", "서울시", "서울")),
    ("부산", ("부산광역시", "부산시", "부산")),
    ("대구", ("대구광역시", "대구시", "대구")),
    ("인천", ("인천광역시", "인천시", "인천")),
    ("광주", ("광주광역시", "광주시", "광주")),
    ("대전", ("대전광역시", "대전시", "대전")),
    ("울산", ("울산광역시", "울산시", "울산")),
    ("세종", ("세종특별자치시", "세종시", "세종")),
    ("경기", ("경기도", "경기")),
    ("충북", ("충청북도", "충북")),
    ("충남", ("충청남도", "충남")),
    ("전북", ("전북특별자치도", "전라북도", "전북")),
    ("전남", ("전라남도", "전남")),
    ("경북", ("경상북도", "경북")),
    ("경남", ("경상남도", "경남")),
    ("제주", ("제주특별자치도", "제주도", "제주")),
]
_SIDO_PATTERN = re.compile(
    "^(" + "|".join(alias for _, aliases in _SIDO_ALIASES for alias in aliases) + ")"
)
_SIDO_CANONICAL = {alias: canonical for canonical, aliases in _SIDO_ALIASES for alias in aliases}
_SIGUNGU_RE = re.compile(r"^([가-힣]+?[시군구])")


def _region_key(text: str) -> tuple[str | None, str | None]:
    """`강원평창군대관령면...` → `('강원', '평창')`.

    `시/군/구` 접미사는 떼고 돌려준다. 출장지 표기(`강원 평창, 강릉`)에는
    접미사가 없기 때문에, 접미사를 붙인 채로는 영수증 주소와 맞출 수 없다.
    """
    packed = strip_spaces(text)
    if packed is None:
        return None, None

    sido = None
    match = _SIDO_PATTERN.match(packed)
    if match:
        sido = _SIDO_CANONICAL[match.group(1)]
        packed = packed[match.end():]

    core = None
    match = _SIGUNGU_RE.match(packed)
    if match:
        core = match.group(1)[:-1]  # 시/군/구 제거
    elif packed:
        # 접미사 없는 지명(`평창`, `강릉`). 뒤따르는 읍/면/동/로 앞까지만 취한다.
        head = re.match(r"^([가-힣]{2,4}?)(?=읍|면|동|리|로|길|가|\d|$)", packed)
        core = head.group(1) if head else packed[:3]
    return sido, core


class RegionSet:
    """`region_of(...) in regions_of(...)` 를 위한 비교 전용 집합.

    시·도 표기가 한쪽에만 있는 경우가 많아(`강원 평창군` vs `평창`),
    시·군 이름이 같으면 일치로 본다.
    """

    def __init__(self, items: list[tuple[str | None, str | None]], labels: list[str]):
        self._items = [item for item in items if item[1]]
        self.labels = labels

    def __contains__(self, other) -> bool:
        if isinstance(other, RegionSet):
            return any(item in self for item in other.labels)
        sido, core = _region_key(str(other))
        if core is None:
            return False
        for other_sido, other_core in self._items:
            if core != other_core:
                continue
            if sido and other_sido and sido != other_sido:
                continue
            return True
        return False

    def __bool__(self) -> bool:
        return bool(self._items)

    def __iter__(self):
        return iter(self.labels)

    def __len__(self) -> int:
        return len(self._items)

    def __repr__(self) -> str:
        return f"RegionSet({', '.join(self.labels)})"

    def __str__(self) -> str:
        return ", ".join(self.labels)


def region_of(address) -> str | None:
    """주소 → `강원 평창군` 형태의 시군구 표기.

    docs/03 의 예: `강원평창군대관령면대관령로100` → `강원 평창군`
    """
    if is_blank(address):
        return None
    packed = strip_spaces(address)
    sido, core = _region_key(packed)
    if core is None:
        return None
    # 원문에 붙어 있던 시/군/구 접미사를 되살려 사람이 읽기 좋게 만든다.
    suffix_match = re.search(re.escape(core) + r"([시군구])", packed)
    suffix = suffix_match.group(1) if suffix_match else ""
    return f"{sido} {core}{suffix}".strip() if sido else f"{core}{suffix}"


def regions_of(destination) -> RegionSet:
    """출장지 표기를 지역 집합으로.

    `강원 평창, 강릉` → 평창·강릉 두 곳. 앞에 붙은 시·도는 뒤 항목에도 적용한다.
    """
    if is_blank(destination):
        return RegionSet([], [])
    text = str(destination)
    chunks = [c for c in re.split(r"[,/·∼~]|\s{2,}", text) if strip_spaces(c)]
    items: list[tuple[str | None, str | None]] = []
    labels: list[str] = []
    inherited_sido: str | None = None
    for chunk in chunks:
        sido, core = _region_key(chunk)
        if sido:
            inherited_sido = sido
        else:
            sido = inherited_sido
        if core:
            items.append((sido, core))
            labels.append(chunk.strip())
    return RegionSet(items, labels)


# ------------------------------------------------------------------- 기타

def similarity(left, right) -> float:
    """R-INN-010 이 쓰는 문자열 유사도. 공백·구두점을 지우고 비교한다."""
    from difflib import SequenceMatcher

    a = strip_spaces(left)
    b = strip_spaces(right)
    if a is None or b is None:
        return 0.0
    a = unicodedata.normalize("NFKC", a)
    b = unicodedata.normalize("NFKC", b)
    return SequenceMatcher(None, a, b).ratio()
