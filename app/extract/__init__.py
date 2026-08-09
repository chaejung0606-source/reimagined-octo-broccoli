"""추출 파이프라인 — 분류된 서류를 필드로 바꾼다.

docs/04-architecture.md §3 의 4단 파이프라인 중 **1단(텍스트 레이어)** 만 구현한 것이다.
OCR·Vision 은 4단계 작업이라, 텍스트 레이어가 없는 문서는 값을 만들지 않고
`미추출` 로 남긴다. 그래야 규칙 엔진이 조용히 통과시키지 않고 🔵 판독 불가로 올린다.
"""
from __future__ import annotations

from typing import Any, Callable

from ..fields import FieldIndex
from ..models import MISSING, Case, Confidence, Document, Field, Namespace, Source
from .base import FieldBag
from . import common, innovation, roster, scholarship, travel, worklog

Extractor = Callable[[Document, FieldBag], None]

#: 서류 종류 → 전용 추출기
EXTRACTORS: dict[str, Extractor] = {
    # 근로장학금
    "form1_recommendation": scholarship.extract_form1,
    "form5_worklog": worklog.extract_form5,
    "claim_form": scholarship.extract_claim_form,
    "monthly_report": scholarship.extract_monthly_report,
    "worklog_handwrite": worklog.extract_handwrite,
    # 혁신인재지원금
    "form8_application": innovation.extract_application,
    "form7_1_report": innovation.extract_report,
    "attach1_worklog": worklog.extract_attach1,
    # 공통
    "payment_roster": roster.extract,
    "form3_id_bankbook": common.extract_bankbook,
    "form4_enrollment": common.extract_enrollment,
    "id_bankbook": common.extract_bankbook,
    "enrollment_cert": common.extract_enrollment,
    "id_bankbook_enrollment": lambda doc, bag: (
        common.extract_bankbook(doc, bag), common.extract_enrollment(doc, bag)
    ),
    # 출장비
    "trip_request": travel.extract_trip_request,
    "trip_evidence": travel.extract_trip_evidence,
    "transport_receipts": lambda doc, bag: travel.extract_receipts(doc, bag, "transport_receipts"),
    "stay_receipts": lambda doc, bag: travel.extract_receipts(doc, bag, "stay_receipts"),
    "purpose_evidence": travel.extract_purpose_evidence,
}

#: 인적사항 추출을 건너뛰는 서류 (지급내역은 여러 사람이 섞여 있어 개인 필드로 쓰면 안 된다)
_NO_PERSON = {"payment_roster", "transport_receipts", "stay_receipts", "purpose_evidence"}


def extract_document(document: Document) -> dict[str, Field]:
    """서류 하나에서 필드를 뽑는다."""
    bag = FieldBag(document)
    if not document.readable:
        # 스캔·이미지 서류. 존재 자체는 L0 가 확인하고, 내용은 4단계에서 읽는다.
        return bag.result()

    if document.kind not in _NO_PERSON:
        common.extract_person(document, bag)
        if document.kind == "trip_request":
            common.extract_travel_person(document, bag)

    extractor = EXTRACTORS.get(document.kind)
    if extractor is not None:
        extractor(document, bag)
    return bag.result()


def extract_case(case: Case) -> FieldIndex:
    """검토 건 전체를 필드 색인으로 만든다."""
    index = FieldIndex()
    for document in case.documents:
        document.fields = extract_document(document)
        index.add_many(document, document.fields)

    _finalize_receipts(case, index)
    _finalize_roster(case, index)
    _finalize_documents(case, index)
    return index


# ------------------------------------------------------------- 마무리 처리

def _case_source(case: Case, note: str) -> Source:
    return Source(doc_key="(집계)", doc_label="검토 건 전체",
                  file=str(case.root or ""), note=note)


def _put(index: FieldIndex, case: Case, path: str, value: Any,
         confidence: float = Confidence.TEXT_LAYER, note: str = "") -> None:
    index.add(None, Field.found(path, value, confidence=confidence,
                                source=_case_source(case, note)))


def _finalize_receipts(case: Case, index: FieldIndex) -> None:
    """흩어진 영수증을 한 목록으로 모은다.

    영수증은 별도 파일로도 오고, 출장증빙 서식 안에 붙어서도 온다.
    R-TRV-009(기간 내 합계)와 R-TRV-011(기간 이탈)은 둘 다 봐야 한다.
    """
    if case.expense_type != "출장비":
        return

    transport: list[Namespace] = []
    stay: list[Namespace] = []
    unreadable: list[str] = []

    for document in case.documents:
        parsed = document.fields.get(f"parsed_receipts.{document.kind}")
        if parsed is not None and parsed.value:
            target = transport if document.kind == "transport_receipts" else stay
            target.extend(parsed.value)
        elif parsed is not None and parsed.is_missing:
            unreadable.append(str(document))

        embedded = document.fields.get("trip_evidence.receipts")
        if embedded is not None and embedded.value:
            for receipt in embedded.value:
                (transport if receipt.kind in ("tollgate", "fuel", "transit") else stay).append(receipt)

    _put(index, case, "transport_receipts", transport,
         note=f"교통비 영수증 {len(transport)}건")
    _put(index, case, "stay_receipts", stay, note=f"체류 영수증 {len(stay)}건")
    _put(index, case, "receipts", transport + stay,
         note=f"영수증 합계 {len(transport) + len(stay)}건")

    if unreadable:
        index.add(None, Field.missing(
            "receipts.unreadable",
            source=_case_source(case, "판독 불가: " + ", ".join(unreadable[:3])),
        ))


def _finalize_roster(case: Case, index: FieldIndex) -> None:
    """지급내역에서 이 검토 건의 대상자 행을 골라 `roster.*` 로 펼친다."""
    rows_field = index.best("roster.rows")
    if rows_field is None or not rows_field.value:
        return

    name_field = index.best("person.name")
    id_field = index.best("person.student_id")
    row = roster.select_row(
        list(rows_field.value),
        name_field.value if name_field else None,
        id_field.value if id_field else None,
    )
    if row is None:
        return

    document = next(iter(index.documents_for("roster.rows")), None)
    source = document.source(note="지급내역 대상자 행") if document else _case_source(case, "지급내역")
    for key in ("name", "student_id", "bank", "account_no", "unit_price",
                "hours", "amount", "course_name", "club_name", "department"):
        value = row[key]
        if value is MISSING or value is None:
            continue
        field = Field.found(f"roster.{key}", value,
                            confidence=rows_field.confidence, source=source)
        index.add(document, field)

    if row.club_name:
        index.add(document, Field.found("club.name", row.club_name,
                                        confidence=rows_field.confidence, source=source))


def _finalize_documents(case: Case, index: FieldIndex) -> None:
    """서류 존재 여부를 필드로 노출한다 (L0 규칙과 `checkbox_matches_attachments` 용)."""
    kinds = sorted({doc.kind for doc in case.documents if doc.kind != "unknown"})
    _put(index, case, "documents.present", kinds, note=f"제출 서류 {len(kinds)}종")
    _put(index, case, "documents.count", len(case.documents))
    unreadable = [str(doc) for doc in case.documents if not doc.readable]
    _put(index, case, "documents.unreadable", unreadable,
         note=f"텍스트 판독 불가 {len(unreadable)}건")
