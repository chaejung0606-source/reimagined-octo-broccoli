"""데이터 모델 — 필드(값+신뢰도+출처), 문서, 검토 건, 판정 결과.

docs/03-field-dictionary.md §6 의 신뢰도 표와 docs/02-review-criteria.md §1 의
판정 등급을 그대로 옮긴 것이다.
"""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from datetime import date, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Iterator


# ------------------------------------------------------------- 신뢰도 기준

class Confidence:
    """docs/03 §6 추출 신뢰도 표."""

    TEXT_LAYER = 0.98       # PDF 텍스트 레이어 직접 추출
    TABLE_REBUILD = 0.90    # 좌표 기반 표 재조립
    OCR_PRINT = 0.85        # 인쇄물 OCR
    VISION_PRINT = 0.85     # Vision LLM (인쇄물)
    VISION_HANDWRITE = 0.60 # Vision LLM (손글씨) — REVIEW 강등 대상
    NONE = 0.0              # 값 없음 / 파싱 실패

    #: 이 값 미만이면 판정 결과와 무관하게 REVIEW(판독 불가)로 강등한다.
    THRESHOLD = 0.85


class FieldStatus(str, Enum):
    """값이 없을 때 '비어 있음'과 '못 읽음'을 구분한다.

    이 구분이 없으면 `총 이동경로` 공란(→ 🔴 수정 필요)과
    스캔 판독 실패(→ 🔵 판독 불가)를 같은 결과로 처리하게 된다.
    """

    PRESENT = "present"   # 값을 읽었다
    BLANK = "blank"       # 칸은 찾았는데 비어 있다 → 규칙이 정상 평가되어 위반으로 잡힌다
    MISSING = "missing"   # 칸 자체를 찾지 못했다 → REVIEW 강등


class Status(str, Enum):
    """규칙 평가 결과."""

    ERROR = "ERROR"              # 🔴 수정 필요
    WARN = "WARN"                # 🟡 확인 요망
    REVIEW = "REVIEW"            # 🔵 판독 불가
    PASS = "PASS"                # 🟢 이상 없음
    UNSUPPORTED = "UNSUPPORTED"  # ⚪ 이 단계에서 미검사 (OCR/Vision 필요)
    SKIPPED = "SKIPPED"          # ⚪ 미검사 (규정값 미설정 등)


DISPLAY = {
    Status.ERROR: "🔴 수정 필요",
    Status.WARN: "🟡 확인 요망",
    Status.REVIEW: "🔵 판독 불가",
    Status.PASS: "🟢 이상 없음",
    Status.UNSUPPORTED: "⚪ 이번 단계 미지원",
    Status.SKIPPED: "⚪ 미검사",
}

#: 리포트 정렬 순서
STATUS_ORDER = [
    Status.ERROR,
    Status.WARN,
    Status.REVIEW,
    Status.UNSUPPORTED,
    Status.SKIPPED,
    Status.PASS,
]


# ------------------------------------------------------------------ 센티넬

class _Missing:
    """추출되지 않은 값. 어떤 연산에도 참여하지 않고 조용히 False 를 만든다."""

    _instance: "_Missing | None" = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __bool__(self) -> bool:
        return False

    def __eq__(self, other) -> bool:
        return other is self

    def __ne__(self, other) -> bool:
        return other is not self

    def __hash__(self) -> int:
        return hash("<MISSING>")

    def __len__(self) -> int:
        return 0

    def __iter__(self):
        return iter(())

    def __repr__(self) -> str:
        return "<미추출>"

    def __str__(self) -> str:
        return "(미추출)"


MISSING = _Missing()


# -------------------------------------------------------------------- 출처

@dataclass(frozen=True)
class Source:
    """결과에서 원본 위치로 점프하기 위한 앵커."""

    doc_key: str = ""
    doc_label: str = ""
    file: str = ""
    page: int | None = None
    note: str = ""

    def __str__(self) -> str:
        parts = [self.doc_label or self.doc_key or Path(self.file).name]
        if self.page is not None:
            parts.append(f"p.{self.page}")
        if self.note:
            parts.append(self.note)
        return " · ".join(p for p in parts if p)


# -------------------------------------------------------------------- 필드

@dataclass
class Field:
    """값 하나 + 신뢰도 + 출처.

    규칙(YAML)은 전부 이 필드들 위에서만 동작한다. 추출기가 바뀌어도 규칙은 그대로다.
    """

    path: str
    value: Any = None
    confidence: float = Confidence.NONE
    status: FieldStatus = FieldStatus.MISSING
    source: Source | None = None

    @classmethod
    def found(cls, path: str, value: Any, confidence: float = Confidence.TEXT_LAYER,
              source: Source | None = None) -> "Field":
        if value is None or (isinstance(value, str) and not value.strip()):
            return cls.blank(path, confidence=confidence, source=source)
        return cls(path, value, confidence, FieldStatus.PRESENT, source)

    @classmethod
    def blank(cls, path: str, confidence: float = Confidence.TEXT_LAYER,
              source: Source | None = None) -> "Field":
        """칸은 있는데 비어 있다. 신뢰도는 그대로 둔다 — 못 읽은 게 아니라 없는 것이다."""
        return cls(path, None, confidence, FieldStatus.BLANK, source)

    @classmethod
    def missing(cls, path: str, source: Source | None = None) -> "Field":
        return cls(path, None, Confidence.NONE, FieldStatus.MISSING, source)

    @property
    def is_missing(self) -> bool:
        return self.status is FieldStatus.MISSING

    @property
    def is_low_confidence(self) -> bool:
        return self.confidence < Confidence.THRESHOLD

    @property
    def resolved(self) -> Any:
        """표현식에 넣을 값. 미추출은 MISSING, 공란은 None."""
        return MISSING if self.is_missing else self.value

    def display(self) -> str:
        if self.is_missing:
            return "(미추출)"
        if self.status is FieldStatus.BLANK:
            return "(공란)"
        return format_value(self.value)


def format_value(value: Any) -> str:
    """리포트·메시지에 값을 보기 좋게 찍는다."""
    if value is None:
        return "(공란)"
    if value is MISSING:
        return "(미추출)"
    if isinstance(value, bool):
        return "예" if value else "아니오"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, Period):
        return str(value)
    if isinstance(value, (list, tuple, set, frozenset)):
        items = sorted(value, key=str) if isinstance(value, (set, frozenset)) else list(value)
        if not items:
            return "(없음)"
        shown = ", ".join(format_value(v) for v in items[:8])
        return shown + (f" 외 {len(items) - 8}건" if len(items) > 8 else "")
    if isinstance(value, Namespace):
        return str(value)
    return str(value)


# ---------------------------------------------------------------- 네임스페이스

class Namespace:
    """`trip_evidence.dist_total` 처럼 점 표기로 읽는 읽기 전용 묶음.

    없는 키는 예외 대신 MISSING 을 돌려준다. 규칙이 참조하는 필드가
    아직 추출되지 않았다고 해서 엔진이 죽으면 안 된다.
    """

    __slots__ = ("_data", "_label")

    def __init__(self, data: dict[str, Any] | None = None, label: str = ""):
        object.__setattr__(self, "_data", dict(data or {}))
        object.__setattr__(self, "_label", label)

    def __getattribute__(self, name: str) -> Any:
        # 담긴 값이 항상 이긴다. 이게 없으면 `receipt.items` 가 데이터가 아니라
        # Namespace.items 메서드를 돌려줘서 규칙이 엉뚱하게 터진다.
        if not name.startswith("_"):
            data = object.__getattribute__(self, "_data")
            if name in data:
                return data[name]
        return object.__getattribute__(self, name)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return MISSING

    def __getitem__(self, key: str) -> Any:
        return self._data.get(key, MISSING)

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __bool__(self) -> bool:
        return any(v is not MISSING and v is not None for v in self._data.values())

    def keys(self):
        return self._data.keys()

    def items(self):
        return self._data.items()

    def get(self, key: str, default: Any = MISSING) -> Any:
        return self._data.get(key, default)

    def as_dict(self) -> dict[str, Any]:
        return dict(self._data)

    def __repr__(self) -> str:
        return f"Namespace({self._data!r})"

    def __str__(self) -> str:
        if self._label:
            return self._label
        parts = [f"{k}={format_value(v)}" for k, v in self._data.items()
                 if v is not MISSING and v is not None and not isinstance(v, (list, Namespace))]
        return "{" + ", ".join(parts[:4]) + "}"


def build_namespace(flat: dict[str, Any]) -> Namespace:
    """`{'trip_evidence.dist_total': 365}` → 중첩 Namespace."""
    tree: dict[str, Any] = {}
    # 얕은 경로부터 넣는다. `transport_receipts`(목록)와 `transport_receipts.parsed`
    # 가 함께 오면 목록이 먼저 자리를 잡고, 뒤엣것은 버려진다 — 반대로 하면
    # 목록이 Namespace 로 바뀌어 순회 결과가 값이 아닌 키 문자열이 된다.
    for path, value in sorted(flat.items(), key=lambda item: item[0].count(".")):
        parts = path.split(".")
        node = tree
        blocked = False
        for part in parts[:-1]:
            child = node.get(part)
            if child is not None and not isinstance(child, dict):
                blocked = True   # 상위에 이미 값이 들어 있다 — 덮어쓰지 않는다
                break
            if not isinstance(child, dict):
                child = {}
                node[part] = child
            node = child
        if blocked:
            continue
        leaf = parts[-1]
        if isinstance(node.get(leaf), dict):
            continue
        node[leaf] = value

    def freeze(node: Any) -> Any:
        if isinstance(node, dict):
            return Namespace({k: freeze(v) for k, v in node.items()})
        return node

    return freeze(tree)


# -------------------------------------------------------------------- 기간

@dataclass(frozen=True)
class Period:
    """출장기간·근로기간·활동기간. `receipt.datetime in period` 로 쓴다."""

    start: datetime | date | None = None
    end: datetime | date | None = None

    @staticmethod
    def _as_datetime(value: Any, end_of_day: bool = False) -> datetime | None:
        if value is None or value is MISSING:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return datetime(value.year, value.month, value.day,
                            23, 59, 59) if end_of_day else datetime(value.year, value.month, value.day)
        return None

    def __contains__(self, value: Any) -> bool:
        moment = self._as_datetime(value)
        if moment is None:
            return False
        low = self._as_datetime(self.start)
        high = self._as_datetime(self.end, end_of_day=not isinstance(self.end, datetime))
        if low is not None and moment < low:
            return False
        if high is not None and moment > high:
            return False
        return low is not None or high is not None

    @property
    def start_date(self) -> date | None:
        return self.start.date() if isinstance(self.start, datetime) else self.start

    @property
    def end_date(self) -> date | None:
        return self.end.date() if isinstance(self.end, datetime) else self.end

    def dates(self) -> list[date]:
        """기간에 걸친 모든 날짜. R-TRV-004(체류 증빙 일자 완비)가 쓴다."""
        low, high = self.start_date, self.end_date
        if low is None or high is None or high < low:
            return []
        span = (high - low).days
        return [low + timedelta(days=i) for i in range(span + 1)]

    @property
    def days(self) -> int:
        return len(self.dates())

    def __bool__(self) -> bool:
        return self.start is not None or self.end is not None

    def __eq__(self, other) -> bool:
        if not isinstance(other, Period):
            return NotImplemented
        return (self.start_date, self.end_date) == (other.start_date, other.end_date)

    def __hash__(self) -> int:
        return hash((self.start_date, self.end_date))

    def __str__(self) -> str:
        left = format_value(self.start) if self.start else "?"
        right = format_value(self.end) if self.end else "?"
        return f"{left} ~ {right}"


# -------------------------------------------------------------------- 문서

@dataclass
class Page:
    """PDF 한 페이지의 텍스트. 좌표 기반 표 재조립이 필요할 때 words 를 쓴다."""

    number: int
    text: str = ""
    words: list[dict[str, Any]] = dc_field(default_factory=list)
    images: int = 0          # 페이지에 박힌 이미지 수 (활동사진·지도 캡처 판단용)

    @property
    def lines(self) -> list[str]:
        return [line.rstrip() for line in self.text.splitlines()]


@dataclass
class Document:
    """분류가 끝난 서류 하나. 한 PDF 가 여러 서류를 담을 수도 있다(양식1~4 한 파일)."""

    file: Path
    pages: list[Page] = dc_field(default_factory=list)
    kind: str = "unknown"           # 분류 결과 키 (form5_worklog, trip_evidence, ...)
    label: str = ""                 # 사람이 읽는 이름
    kind_confidence: float = 0.0
    kind_reason: str = ""
    page_range: tuple[int, int] | None = None   # 한 파일 안에서 이 서류가 차지하는 페이지
    read_error: str = ""            # 열지 못한 경우의 사유
    fields: dict[str, Field] = dc_field(default_factory=dict)

    @property
    def text(self) -> str:
        return "\n".join(page.text for page in self.pages)

    @property
    def lines(self) -> list[str]:
        return [line for page in self.pages for line in page.lines]

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def readable(self) -> bool:
        """텍스트 레이어가 있는가. 없으면 이 단계(OCR 이전)에서는 내용을 못 본다."""
        return bool(self.text.strip())

    def source(self, page: int | None = None, note: str = "") -> Source:
        return Source(
            doc_key=self.kind,
            doc_label=self.label or self.kind,
            file=str(self.file),
            page=page,
            note=note,
        )

    def __str__(self) -> str:
        return self.label or self.kind or self.file.name


@dataclass
class Case:
    """검토 한 건 = 지출종류 + 제출자 + 서류 묶음."""

    expense_type: str
    subtype: str | None = None
    person_label: str = ""
    root: Path | None = None
    documents: list[Document] = dc_field(default_factory=list)
    settings: dict[str, Any] = dc_field(default_factory=dict)

    def by_kind(self, kind: str) -> list[Document]:
        return [doc for doc in self.documents if doc.kind == kind]

    def first(self, kind: str) -> Document | None:
        docs = self.by_kind(kind)
        return docs[0] if docs else None

    def has(self, kind: str) -> bool:
        return any(doc.kind == kind for doc in self.documents)


# -------------------------------------------------------------------- 결과

@dataclass
class Finding:
    """규칙 하나의 판정 결과.

    docs/02 §1 이 요구하는 [근거 · 검출값 · 조치] 를 전부 들고 있어야
    "수정할 부분을 정리해서 알려준다" 가 성립한다.
    """

    rule_id: str
    layer: str
    title: str
    status: Status
    message: str = ""
    fix: str = ""
    evidence: list[str] = dc_field(default_factory=list)     # 검출값
    anchors: list[Source] = dc_field(default_factory=list)   # 근거 위치
    reason: str = ""                                         # REVIEW/SKIPPED 사유
    scope_label: str = ""                                    # each_row 등 반복 대상 표시

    @property
    def display(self) -> str:
        return DISPLAY[self.status]

    @property
    def actionable(self) -> bool:
        return self.status in (Status.ERROR, Status.WARN, Status.REVIEW)


@dataclass
class ReviewResult:
    case: Case
    findings: list[Finding] = dc_field(default_factory=list)

    def of(self, *statuses: Status) -> list[Finding]:
        return [f for f in self.findings if f.status in statuses]

    def count(self, status: Status) -> int:
        return sum(1 for f in self.findings if f.status is status)

    @property
    def errors(self) -> list[Finding]:
        return self.of(Status.ERROR)

    @property
    def sorted_findings(self) -> list[Finding]:
        order = {status: i for i, status in enumerate(STATUS_ORDER)}
        return sorted(self.findings, key=lambda f: (order[f.status], f.rule_id))

    def summary(self) -> dict[str, int]:
        return {status.value: self.count(status) for status in STATUS_ORDER}


def iter_fields(documents: Iterable[Document]) -> Iterator[tuple[Document, Field]]:
    for doc in documents:
        for field in doc.fields.values():
            yield doc, field
