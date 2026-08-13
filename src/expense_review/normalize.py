"""서류마다 제각각인 표기를 비교 가능한 값으로 바꾼다.

이 단계를 빼면 오탐이 대부분이다. 예를 들어 같은 계좌가 신청서에는
'59220101565992', 지급내역에는 '592201-01-565992' 로 적혀 있다.

docs/03-field-dictionary.md 의 '정규화 함수' 표에 대응한다.
"""
from __future__ import annotations

import datetime as dt
import re
import unicodedata

__all__ = [
    "digits_only",
    "strip_spaces",
    "bank_alias",
    "money",
    "parse_date",
    "parse_datetime",
    "parse_time",
    "hours_between",
    "hours",
    "hangul_amount",
    "region_of",
    "regions_of",
    "similarity",
]

# ── 문자열 ────────────────────────────────────────────────────────────────

_SPACE_RE = re.compile(r"[\s 　]+")


def strip_spaces(value: str | None) -> str:
    """공백·전각공백 제거. '권 석 재' → '권석재'"""
    if value is None:
        return ""
    return _SPACE_RE.sub("", unicodedata.normalize("NFC", str(value)))


def digits_only(value: str | None) -> str:
    """숫자만 남긴다. '592201-01-565992' → '59220101565992'"""
    if value is None:
        return ""
    return re.sub(r"\D", "", str(value))


# 은행 별칭. 서류마다 '국민' / '국민은행' 이 섞여 쓰인다.
_BANK_CANONICAL = {
    "국민": "국민은행",
    "신한": "신한은행",
    "농협": "농협은행",
    "우리": "우리은행",
    "하나": "하나은행",
    "기업": "기업은행",
    "카카오": "카카오뱅크",
    "토스": "토스뱅크",
    "케이": "케이뱅크",
    "새마을": "새마을금고",
    "우체국": "우체국",
    "수협": "수협은행",
    "부산": "부산은행",
    "대구": "대구은행",
    "경남": "경남은행",
    "광주": "광주은행",
    "전북": "전북은행",
    "제주": "제주은행",
    "산업": "산업은행",
    "씨티": "씨티은행",
    "SC": "SC제일은행",
}


def bank_alias(value: str | None) -> str:
    """은행 표기를 정식 명칭으로 통일. '국민' → '국민은행'"""
    name = strip_spaces(value)
    if not name:
        return ""
    # 긴 접두사부터 맞춰야 '전북' 이 '전' 으로 잘리지 않는다.
    for prefix in sorted(_BANK_CANONICAL, key=len, reverse=True):
        if name.startswith(prefix):
            return _BANK_CANONICAL[prefix]
    return name


# ── 금액 ──────────────────────────────────────────────────────────────────

_MONEY_RE = re.compile(r"-?[\d,]+")


def money(value: str | int | float | None) -> int | None:
    """'1,200원' → 1200. 숫자가 없으면 None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    match = _MONEY_RE.search(str(value).replace(" ", ""))
    if not match:
        return None
    digits = match.group().replace(",", "")
    if digits in {"", "-"}:
        return None
    return int(digits)


_HANGUL_DIGITS = "영일이삼사오육칠팔구"
_HANGUL_SMALL_UNITS = ["", "십", "백", "천"]
_HANGUL_BIG_UNITS = ["", "만", "억", "조"]


def hangul_amount(amount: int | None) -> str:
    """240000 → '금이십사만원정'. 청구서·신청서의 한글 금액란 대조에 쓴다."""
    if amount is None:
        return ""
    if amount == 0:
        return "금영원정"

    groups: list[int] = []
    remaining = amount
    while remaining > 0:
        groups.append(remaining % 10000)
        remaining //= 10000

    parts: list[str] = []
    for index in range(len(groups) - 1, -1, -1):
        group = groups[index]
        if group == 0:
            continue
        chunk = ""
        for position in range(3, -1, -1):
            digit = (group // 10**position) % 10
            if digit == 0:
                continue
            # 십/백/천 앞의 '일' 은 적지 않는다. 10 → '십' (X '일십')
            head = "" if (digit == 1 and position > 0) else _HANGUL_DIGITS[digit]
            chunk += head + _HANGUL_SMALL_UNITS[position]
        parts.append(chunk + _HANGUL_BIG_UNITS[index])

    return "금" + "".join(parts) + "원정"


# ── 날짜·시간 ─────────────────────────────────────────────────────────────

# 근무상황부 손글씨에는 '26/03/9' 처럼 연 2자리 + 월일 비제로패딩이 흔하다.
_DATE_PATTERNS = (
    re.compile(r"(?P<y>\d{4})[.\-/년]\s*(?P<m>\d{1,2})[.\-/월]\s*(?P<d>\d{1,2})"),
    re.compile(r"(?P<y>\d{2})[.\-/]\s*(?P<m>\d{1,2})[.\-/]\s*(?P<d>\d{1,2})"),
)
_TIME_RE = re.compile(r"(?P<h>\d{1,2})\s*[:시]\s*(?P<mi>\d{1,2})")


def parse_date(value: str | dt.date | None) -> dt.date | None:
    """'2026.06.29.', '26/03/9', '2026년 6월 29일' 을 모두 흡수한다."""
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    text = strip_spaces(value)
    for pattern in _DATE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        year = int(match.group("y"))
        if year < 100:
            year += 2000
        try:
            return dt.date(year, int(match.group("m")), int(match.group("d")))
        except ValueError:
            return None
    return None


def parse_time(value: str | dt.time | None) -> dt.time | None:
    """'09:00', '13시20분' → time"""
    if value is None:
        return None
    if isinstance(value, dt.time):
        return value
    match = _TIME_RE.search(strip_spaces(value))
    if not match:
        return None
    try:
        return dt.time(int(match.group("h")), int(match.group("mi")))
    except ValueError:
        return None


def parse_datetime(value: str | dt.datetime | None) -> dt.datetime | None:
    """'2026년07월03일 13시20분' → datetime. 시각이 없으면 00:00."""
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value
    date = parse_date(value)
    if date is None:
        return None
    time = parse_time(value) or dt.time(0, 0)
    return dt.datetime.combine(date, time)


def hours_between(start: str | dt.time | None, end: str | dt.time | None) -> float | None:
    """근로 시작~종료 시각의 시간 차. 자정을 넘기는 경우는 다루지 않는다."""
    start_time = parse_time(start)
    end_time = parse_time(end)
    if start_time is None or end_time is None:
        return None
    delta = (
        dt.datetime.combine(dt.date.today(), end_time)
        - dt.datetime.combine(dt.date.today(), start_time)
    )
    return round(delta.total_seconds() / 3600, 2)


def hours(value: str | int | float | None) -> float | None:
    """'5시간', '5', 5.0 → 5.0"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"\d+(?:\.\d+)?", str(value).replace(",", ""))
    return float(match.group()) if match else None


# ── 주소·문자열 유사도 ────────────────────────────────────────────────────

_PROVINCE_ALIAS = {
    "강원특별자치도": "강원",
    "강원도": "강원",
    "서울특별시": "서울",
    "부산광역시": "부산",
    "대구광역시": "대구",
    "인천광역시": "인천",
    "광주광역시": "광주",
    "대전광역시": "대전",
    "울산광역시": "울산",
    "세종특별자치시": "세종",
    "경기도": "경기",
    "충청북도": "충북",
    "충청남도": "충남",
    "전라북도": "전북",
    "전북특별자치도": "전북",
    "전라남도": "전남",
    "경상북도": "경북",
    "경상남도": "경남",
    "제주특별자치도": "제주",
}
_PROVINCE_SHORT = set(_PROVINCE_ALIAS.values())
_CITY_RE = re.compile(r"([가-힣]{2,}?)[시군구](?![가-힣])|([가-힣]{2,}?)[시군구]")
_TOKEN_SPLIT_RE = re.compile(r"[^가-힣A-Za-z]+")


def _strip_provinces(text: str) -> str:
    for full, short in _PROVINCE_ALIAS.items():
        text = text.replace(full, short)
    for short in _PROVINCE_SHORT:
        text = text.replace(short, " ")
    return text


def region_of(address: str | None) -> str:
    """주소에서 시/군 이름을 뽑는다. 접미사는 떼고 돌려준다.

    '강원평창군대관령면대관령로100' → '평창'
    '강원특별자치도 춘천시 효자동'   → '춘천'

    영수증 가맹점 주소와 출장지를 대조할 때 쓴다. 출장지는 '강원 평창, 강릉'
    처럼 접미사 없이 적히므로, 양쪽 모두 접미사를 뗀 형태로 맞춘다.
    """
    text = _strip_provinces(strip_spaces(address))
    if not text:
        return ""
    match = _CITY_RE.search(text)
    if not match:
        return ""
    return match.group(1) or match.group(2) or ""


def regions_of(text: str | None) -> set[str]:
    """자유표기 지역 문자열에서 지역명 후보를 모두 뽑는다.

    '강원 평창, 강릉'        → {'평창', '강릉'}
    '평창 알펜시아 및 강릉'  → {'평창', '알펜시아', '강릉'}
    '한라대학교(원주)'       → {'한라대학교', '원주'}

    후보를 넉넉히 잡는다. 이 집합은 '영수증 지역이 여기 들어 있나' 를 보는 데
    쓰이므로, 후보가 많으면 검사가 느슨해질 뿐 오탐이 늘지는 않는다.
    """
    raw = str(text or "")
    if not raw.strip():
        return set()

    found: set[str] = set()
    # 원문에 붙어 있는 시/군/구 표기를 먼저 건진다.
    for match in _CITY_RE.finditer(_strip_provinces(strip_spaces(raw))):
        name = match.group(1) or match.group(2)
        if name:
            found.add(name)

    # 접미사 없이 적힌 지명은 구분자로 잘라 토큰으로 받는다.
    for token in _TOKEN_SPLIT_RE.split(_strip_provinces(raw)):
        token = token.strip()
        if len(token) >= 2 and token not in _PROVINCE_SHORT:
            found.add(token)
            if len(token) > 2 and token[-1] in "시군구":
                found.add(token[:-1])

    return found


def similarity(left: str | None, right: str | None) -> float:
    """0~1 문자 단위 유사도. 활동주제처럼 자유서술 필드 비교에 쓴다."""
    from difflib import SequenceMatcher

    a, b = strip_spaces(left), strip_spaces(right)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()
