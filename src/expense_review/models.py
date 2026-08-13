"""핵심 자료구조.

설계의 뼈대는 '서류 → 정규화된 필드 → 규칙 평가' 2단계다(docs/02 §0).
여기서는 그 가운데 단계인 필드(Value)와, 마지막 산출물인 Finding 을 정의한다.

모든 필드는 값과 함께 confidence 를 들고 다닌다. 손글씨·스캔이 섞여 있어
'위반/정상' 2분법이 위험하기 때문이다(docs/02 §1). 신뢰도가 임계값 미만이면
규칙 결과와 무관하게 REVIEW 로 강등한다.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterator

# 이 값 미만이면 판정하지 않고 사람에게 넘긴다.
CONFIDENCE_THRESHOLD = 0.85

# 추출 경로별 기본 신뢰도 (docs/03 §6)
CONFIDENCE = {
    "pdf_text": 0.98,      # PDF 텍스트 레이어 직접 추출
    "pdf_table": 0.90,     # 좌표 기반 표 재조립
    "ocr_print": 0.85,     # 인쇄물 OCR
    "vision_print": 0.85,  # Vision LLM (인쇄물)
    "vision_hand": 0.60,   # Vision LLM (손글씨)
    "missing": 0.0,        # 값 없음 / 파싱 실패
}


class Severity(str, Enum):
    """판정 등급 (docs/02 §1)."""

    ERROR = "ERROR"      # 🔴 수정 필요
    WARN = "WARN"        # 🟡 확인 요망
    REVIEW = "REVIEW"    # 🔵 판독 불가 — 신뢰도 미달로 판정 보류
    INFO = "INFO"
    PASS = "PASS"        # 🟢 이상 없음

    @property
    def marker(self) -> str:
        return {
            Severity.ERROR: "🔴",
            Severity.WARN: "🟡",
            Severity.REVIEW: "🔵",
            Severity.INFO: "⚪",
            Severity.PASS: "🟢",
        }[self]

    @property
    def label(self) -> str:
        return {
            Severity.ERROR: "수정 필요",
            Severity.WARN: "확인 요망",
            Severity.REVIEW: "판독 불가",
            Severity.INFO: "참고",
            Severity.PASS: "이상 없음",
        }[self]


# 심각도 정렬 순서 (심한 것부터)
SEVERITY_ORDER = {
    Severity.ERROR: 0,
    Severity.WARN: 1,
    Severity.REVIEW: 2,
    Severity.INFO: 3,
    Severity.PASS: 4,
}


@dataclass(frozen=True)
class Source:
    """필드를 어느 서류 몇 페이지에서 가져왔는지. 결과에서 원본으로 점프할 때 쓴다."""

    document: str
    page: int | None = None

    def __str__(self) -> str:
        return f"{self.document}" + (f" p.{self.page}" if self.page else "")


@dataclass
class Value:
    """정규화된 필드 하나."""

    value: Any
    confidence: float = CONFIDENCE["pdf_text"]
    source: Source | None = None
    raw: str | None = None  # 정규화 전 원문 (결과 화면에서 보여준다)

    @property
    def is_reliable(self) -> bool:
        return self.confidence >= CONFIDENCE_THRESHOLD

    @property
    def is_present(self) -> bool:
        if self.value is None:
            return False
        if isinstance(self.value, str) and not self.value.strip():
            return False
        return True

    def __bool__(self) -> bool:
        return self.is_present

    def __str__(self) -> str:
        if not self.is_present:
            return "(없음)"
        if isinstance(self.value, dt.datetime):
            return self.value.strftime("%Y-%m-%d %H:%M")
        if isinstance(self.value, dt.date):
            return self.value.isoformat()
        return str(self.value)


@dataclass
class Document:
    """업로드된 파일 하나 + 판정된 서류 종류 + 추출된 필드."""

    path: Path
    doc_type: str | None = None          # 대표 서류 종류 (classify.DOC_LABELS 키)
    doc_label: str | None = None         # 사람이 읽는 이름
    pages: list[str] = field(default_factory=list)   # 페이지별 텍스트
    fields: dict[str, Value] = field(default_factory=dict)
    owner: str | None = None             # 묶음 검토 시 제출자 구분 (폴더명)
    notes: list[str] = field(default_factory=list)   # 추출 중 발생한 경고
    # PDF 한 개에 여러 서류가 들어 있는 경우가 흔하다(TA 기본서류 = 양식1~4).
    # 서류 완비성(L0)은 파일 개수가 아니라 이 집합으로 판단한다.
    contains: set[str] = field(default_factory=set)
    page_types: list[str | None] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.path.name

    def page_of(self, doc_type: str) -> int | None:
        """해당 서류가 몇 페이지에 있는지. 결과에서 원본으로 점프할 때 쓴다."""
        for index, page_type in enumerate(self.page_types, start=1):
            if page_type == doc_type:
                return index
        return None

    @property
    def text(self) -> str:
        return "\n".join(self.pages)

    def source(self, page: int | None = None) -> Source:
        return Source(self.name, page)


@dataclass
class DocumentSet:
    """한 건의 검토 단위. 지출종류 + 그 사람이 낸 서류 전부."""

    expense_type: str
    documents: list[Document] = field(default_factory=list)
    subtype: str | None = None
    owner: str | None = None
    settings: dict[str, Any] = field(default_factory=dict)

    def of_type(self, *doc_types: str) -> list[Document]:
        """해당 서류를 (일부 페이지에라도) 담고 있는 파일을 모두 돌려준다."""
        wanted = set(doc_types)
        return [d for d in self.documents if d.contains & wanted or d.doc_type in wanted]

    @property
    def available_types(self) -> set[str]:
        found: set[str] = set()
        for document in self.documents:
            found |= document.contains
            if document.doc_type:
                found.add(document.doc_type)
        return found

    def first(self, *doc_types: str) -> Document | None:
        found = self.of_type(*doc_types)
        return found[0] if found else None

    def get(self, path: str) -> Value | None:
        """'worklog.total_hours' 처럼 '문서종류.필드' 로 값을 찾는다."""
        doc_type, _, field_name = path.partition(".")
        for document in self.of_type(doc_type):
            value = document.fields.get(field_name)
            if value is not None and value.is_present:
                return value
        return None

    def collect(self, field_name: str) -> list[tuple[Document, Value]]:
        """모든 서류에서 같은 이름의 필드를 모은다. 교차 대사(L2)에 쓴다."""
        found = []
        for document in self.documents:
            value = document.fields.get(field_name)
            if value is not None and value.is_present:
                found.append((document, value))
        return found

    def __iter__(self) -> Iterator[Document]:
        return iter(self.documents)


@dataclass
class Finding:
    """검토 결과 한 줄. 사용자에게는 [근거·검출값·조치] 3종이 함께 보인다."""

    rule_id: str
    title: str
    severity: Severity
    layer: str
    message: str                       # 검출값이 채워진 설명
    fix: str = ""                      # 그대로 복사해 보낼 수 있는 조치 문구
    sources: list[Source] = field(default_factory=list)
    owner: str | None = None

    @property
    def evidence(self) -> str:
        return " / ".join(str(s) for s in self.sources) if self.sources else "—"

    def __str__(self) -> str:
        return f"[{self.rule_id}] {self.severity.marker} {self.message}"


@dataclass
class ReviewResult:
    """한 건의 검토 결과 전체."""

    expense_type: str
    owner: str | None
    findings: list[Finding] = field(default_factory=list)
    documents: list[Document] = field(default_factory=list)
    skipped_rules: list[str] = field(default_factory=list)  # 미구현/비활성 규칙

    def by_severity(self, severity: Severity) -> list[Finding]:
        return [f for f in self.findings if f.severity is severity]

    @property
    def sorted_findings(self) -> list[Finding]:
        return sorted(
            self.findings,
            key=lambda f: (SEVERITY_ORDER[f.severity], f.rule_id),
        )

    @property
    def counts(self) -> dict[Severity, int]:
        return {s: len(self.by_severity(s)) for s in (Severity.ERROR, Severity.WARN, Severity.REVIEW)}

    @property
    def is_clean(self) -> bool:
        return not any(self.counts.values())
