"""추출기 공통 도구.

한글 서식 PDF 는 `성명 홍길동` / `성 명 : 홍길동` / `성명|홍길동` 처럼 라벨과 값이
한 줄에 붙어 나오거나, 라벨만 있고 값은 다음 줄에 오기도 한다. 여기 모아 둔 도구는
그 변형을 흡수한다.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Callable, Iterable, Sequence

from .. import normalize as nz
from ..models import Confidence, Document, Field, Namespace, Period, Source

#: 라벨과 값 사이에 올 수 있는 구분자
_SEP = r"[\s:：\|·．.]*"

#: 값이 없는 칸을 채우는 기호들 (`-`, `–`, `없음`)
_EMPTY_MARKS = {"-", "–", "—", "없음", "해당없음", "N/A", "n/a"}


def spaced(label: str) -> str:
    """`성명` → `성\\s*명` — 표 추출 시 글자 사이에 공백이 끼는 것을 흡수한다."""
    return r"\s*".join(re.escape(ch) for ch in label)


#: 라벨 앞에 올 수 있는 자리 — 줄 첫머리, 셀 경계(공백 2칸 이상), 표 구분자.
#: 이 제한이 없으면 `학점/구분 : 3학점 전공선택` 의 '전공' 이 학과 라벨로 잡힌다.
_LABEL_HEAD = r"(?:^[\s\[\(※*□○▪◦●-]*|(?<=\s\s)|(?<=\|)|(?<=\])|(?<=\)))"


def label_pattern(labels: Sequence[str], value: str = r"(?P<value>.*)") -> re.Pattern:
    alternatives = "|".join(spaced(label) for label in labels)
    return re.compile(rf"{_LABEL_HEAD}(?:{alternatives}){_SEP}{value}")


def clean(text: str | None) -> str | None:
    if text is None:
        return None
    stripped = text.strip().strip("|").strip()
    if not stripped or stripped in _EMPTY_MARKS:
        return None
    return stripped


def find_label_value(lines: Sequence[str], labels: Sequence[str],
                     value: str = r"(?P<value>.*)",
                     look_ahead: bool = True) -> tuple[str | None, int | None]:
    """라벨이 있는 줄을 찾아 값을 돌려준다.

    값이 같은 줄에 없으면 (칸만 있고 비어 있으면) 다음 줄을 한 번 더 본다.
    돌려주는 두 번째 값은 라벨을 찾은 줄 번호 — 찾았다면 '칸은 존재한다'는 뜻이므로
    호출부가 `공란`과 `미추출`을 구분할 수 있다.
    """
    pattern = label_pattern(labels, value)
    for index, line in enumerate(lines):
        if looks_like_header(line):
            continue
        match = pattern.search(line)
        if not match:
            continue
        found = clean(match.groupdict().get("value"))
        if found:
            return found, index
        if look_ahead and index + 1 < len(lines):
            nxt = clean(lines[index + 1])
            if nxt and not _looks_like_label(nxt):
                return nxt, index
        return None, index          # 칸은 있는데 비어 있다
    return None, None


def _looks_like_label(text: str) -> bool:
    """다음 줄이 값이 아니라 또 다른 라벨인지 대충 가린다."""
    packed = nz.strip_spaces(text) or ""
    return packed.endswith(("란", "항목", "구분")) or packed.startswith(("※", "*", "□", "○"))


#: 표 머리행에 모여 나오는 열 이름들
_HEADER_WORDS = (
    "성명", "이름", "학번", "직급", "직위", "소속", "부서", "학과", "연번", "구분",
    "기간", "일자", "요일", "시작", "종료", "시간", "금액", "단가", "은행", "계좌",
    "출장지", "출장내용", "출장목적", "여비", "비고", "강좌", "과목", "내역",
    "역할", "연락처", "차종", "통행료", "영업소", "가맹점",
)


def looks_like_header(line: str) -> bool:
    """표의 머리행인가.

    `성명 직급 출장기간 출장지 출장내용 여비지급대상여부` 를 값이 있는 줄로 읽으면
    성명이 '직급출장기간' 이 된다. 열 이름이 세 개 이상 모여 있으면 머리행으로 본다.
    """
    packed = nz.strip_spaces(line) or ""
    if not packed or len(packed) > 120:
        return False
    hits = sum(1 for word in _HEADER_WORDS if word in packed)
    if hits < 3:
        return False
    # 값이 섞여 있으면(숫자·괄호가 많으면) 데이터 행일 수 있다.
    return not re.search(r"\d{4}|[:：]", line)


def has_marker(text: str, *markers: str) -> bool:
    packed = nz.strip_spaces(text) or ""
    return any((nz.strip_spaces(m) or "") in packed for m in markers)


def all_matches(text: str, pattern: re.Pattern | str) -> list[re.Match]:
    compiled = re.compile(pattern) if isinstance(pattern, str) else pattern
    return list(compiled.finditer(text))


# ------------------------------------------------------------------ 값 파서

#: 성명 자리에 흘러들어오기 쉬운 서식 용어. 이름으로 채택하지 않는다.
_NAME_STOPWORDS = frozenset({
    "성명", "이름", "직급", "직위", "소속", "부서", "학과", "학번", "구분", "연번",
    "기간", "일자", "요일", "시간", "금액", "단가", "은행", "계좌", "비고", "확인자",
    "담당자", "출장지", "출장기간", "출장내용", "출장목적", "여비", "신청인", "회장",
})


def as_name(value: str | None) -> str | None:
    """`홍 길 동 (인)` → `홍길동`.

    한국 사람 이름은 2~4자다. 토큰 단위로 보고 서식 용어는 걸러 낸다 —
    표 머리행이 값으로 잘못 들어오면 성명이 '직급출장기간' 같은 말이 된다.
    """
    if value is None:
        return None
    text = re.sub(r"\((?:인|서명|날인)\)|\[.*?\]", "", value).strip()
    for token in re.split(r"[\s|,/()]+", text):
        packed = nz.strip_spaces(token) or ""
        if re.fullmatch(r"[가-힣]{2,4}", packed) and packed not in _NAME_STOPWORDS:
            return packed
    # 공백 없이 붙어 나온 경우(`성명홍길동`)는 마지막 2~4자를 이름으로 본다.
    packed = nz.strip_spaces(text) or ""
    match = re.search(r"([가-힣]{2,4})$", packed)
    if match and match.group(1) not in _NAME_STOPWORDS:
        return match.group(1)
    return None


def as_digits(value: str | None, min_length: int = 1) -> str | None:
    digits = nz.digits_only(value)
    if digits is None or len(digits) < min_length:
        return None
    return digits


def as_money(value: str | None) -> int | None:
    return nz.money(value)


def as_hours(value: str | None) -> float | None:
    return nz.parse_hours(value)


def as_date(value: str | None, year: int | None = None) -> date | None:
    return nz.parse_date(value, default_year=year)


def as_datetime(value: str | None, year: int | None = None) -> datetime | None:
    return nz.parse_datetime(value, default_year=year)


_RANGE_SPLIT = re.compile(r"\s*(?:~|～|∼|—|–|부터|-)\s*")


def as_period(value: str | None, year: int | None = None) -> Period | None:
    """`2026. 3. 3. ~ 2026. 3. 31.` / `2026.06.29 09:00 ~ 2026.07.01 18:00` → Period."""
    if value is None:
        return None
    text = value.strip()
    # 날짜 뒤의 하이픈은 구분자가 아니라 날짜 표기이므로, 날짜를 먼저 떼어 본다.
    parts = _split_range(text)
    if len(parts) != 2:
        return None
    start = as_datetime(parts[0], year)
    end = as_datetime(parts[1], year)
    if start is None and end is None:
        return None
    # 끝 날짜에 연도가 생략된 경우(`2026.6.29 ~ 7.1`) 시작 연도를 물려준다.
    if end is None and start is not None:
        end = as_datetime(parts[1], start.year)
    # 시각이 적혀 있지 않으면 날짜만 남긴다. 00:00 을 붙여 두면 종료일 당일이
    # 기간 밖으로 밀려 근로일자·영수증이 통째로 오탐이 된다.
    if nz.parse_time(parts[0]) is None and start is not None:
        start = start.date()
    if nz.parse_time(parts[1]) is None and end is not None:
        end = end.date()
    if start is not None and end is not None and _as_sortable(end) < _as_sortable(start):
        return Period(start, None)
    return Period(start, end)


def _as_sortable(value: date | datetime) -> date:
    return value.date() if isinstance(value, datetime) else value


def _split_range(text: str) -> list[str]:
    """`~` 로 나눈다. `-` 는 날짜 구분자와 겹치므로 마지막에만 시도한다."""
    for separator in ("~", "～", "∼", "—", "–", "부터"):
        if separator in text:
            left, _, right = text.partition(separator)
            return [left.strip(), right.strip().lstrip("까지").strip()]
    # `2026-03-03 - 2026-03-31` 처럼 하이픈으로 나뉜 경우
    match = re.match(r"^(.*?\d)\s+-\s+(\d.*)$", text)
    if match:
        return [match.group(1).strip(), match.group(2).strip()]
    return [text]


#: 연도 후보. 학번(`202033445`)에서 앞 4자리를 연도로 잘못 읽지 않도록 순서가 중요하다.
_YEAR_PATTERNS = (
    re.compile(r"(?<!\d)(20\d{2})\s*년"),
    re.compile(r"(?<!\d)(20\d{2})\s*[.\-/]\s*\d{1,2}\s*[.\-/]\s*\d{1,2}"),
    re.compile(r"(?<!\d)(20\d{2})\s*학?년도"),
)


def document_year(document) -> int | None:
    """`7/3` 처럼 연도가 빠진 표기를 해석하기 위한 기준 연도.

    본문에서 `2026년` / `2026-05-06` 처럼 **연도로 쓰인 자리**만 본다.
    그냥 `20\\d{2}` 를 찾으면 학번 `202033445` 의 앞 네 자리를 연도로 읽어
    활동일이 통째로 6년 전으로 밀린다.
    """
    text = document.text
    for pattern in _YEAR_PATTERNS:
        match = pattern.search(text)
        if match:
            return int(match.group(1))
    match = re.search(r"(?<!\d)(20\d{2})(?!\d)", document.file.name)
    return int(match.group(1)) if match else None


CHECKED_MARKS = ("☑", "☒", "■", "●", "▣", "V", "v", "√", "✓", "×", "x", "X")
UNCHECKED_MARKS = ("□", "○", "◯", "☐", "◻")


def is_checked(text: str) -> bool:
    """체크박스 표기를 읽는다. 서식마다 ☑ / ■ / V 가 섞여 나온다."""
    return any(mark in text for mark in CHECKED_MARKS)


# ------------------------------------------------------------- 필드 모으기

class FieldBag:
    """한 문서에서 뽑은 필드들을 출처와 함께 모은다."""

    def __init__(self, document: Document, confidence: float = Confidence.TEXT_LAYER):
        self.document = document
        self.default_confidence = confidence
        self.fields: dict[str, Field] = {}

    # -- 기록 -----------------------------------------------------------
    def put(self, path: str, value: Any, *, page: int | None = None, note: str = "",
            confidence: float | None = None) -> Field:
        """값을 기록한다. None 이면 '공란'(칸은 있으나 비었음)으로 남는다."""
        field = Field.found(
            path, value,
            confidence=confidence if confidence is not None else self.default_confidence,
            source=self._source(page, note),
        )
        self.fields[path] = field
        return field

    def blank(self, path: str, *, page: int | None = None, note: str = "") -> Field:
        field = Field.blank(path, confidence=self.default_confidence, source=self._source(page, note))
        self.fields[path] = field
        return field

    def missing(self, path: str, *, note: str = "") -> Field:
        field = Field.missing(path, source=self._source(None, note))
        self.fields[path] = field
        return field

    def put_optional(self, path: str, value: Any, found_slot: bool, *,
                     page: int | None = None, note: str = "",
                     confidence: float | None = None) -> Field:
        """칸을 찾았는지 여부까지 반영해 기록한다.

        칸을 찾았고 비어 있으면 `공란`(→ 규칙이 위반으로 잡는다),
        칸 자체를 못 찾았으면 `미추출`(→ 🔵 판독 불가)이다.
        """
        if value is not None:
            return self.put(path, value, page=page, note=note, confidence=confidence)
        if found_slot:
            return self.blank(path, page=page, note=note)
        return self.missing(path, note=note)

    def _source(self, page: int | None, note: str) -> Source:
        return self.document.source(page=page, note=note)

    # -- 편의 -----------------------------------------------------------
    def alias(self, source_path: str, *targets: str) -> None:
        """같은 값을 다른 이름으로도 노출한다 (`worklog.*` ↔ `attach1_worklog.*`)."""
        original = self.fields.get(source_path)
        if original is None:
            return
        for target in targets:
            self.fields[target] = Field(
                path=target,
                value=original.value,
                confidence=original.confidence,
                status=original.status,
                source=original.source,
            )

    def alias_prefix(self, source_prefix: str, target_prefix: str) -> None:
        for path in list(self.fields):
            if path == source_prefix or path.startswith(source_prefix + "."):
                self.alias(path, target_prefix + path[len(source_prefix):])

    def result(self) -> dict[str, Field]:
        return self.fields


def rows_to_namespaces(rows: Iterable[dict[str, Any]], label: Callable[[dict], str] | None = None) -> list[Namespace]:
    out = []
    for row in rows:
        out.append(Namespace(row, label=label(row) if label else ""))
    return out
