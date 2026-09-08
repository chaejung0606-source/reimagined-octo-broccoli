"""서류 종류별 필드 추출기.

각 추출기는 Document 를 받아 `document.fields` 에 정규화된 Value 를 채운다.
규칙 엔진은 여기서 나온 필드만 본다 — 추출 방식이 바뀌어도 규칙은 그대로다.

4단계(OCR/Vision) 전까지는 텍스트 레이어가 있는 서류만 추출된다. 값이 비면
규칙 엔진이 자동으로 REVIEW(판독 불가)로 처리하므로, 여기서 억지로 채우지 않는다.
"""
from __future__ import annotations

from typing import Callable

from ..models import Document
from . import common, innovation, scholarship, travel

Extractor = Callable[[Document], None]

REGISTRY: dict[str, Extractor] = {
    "payment_roster": common.extract_roster,
    "privacy_consent": common.extract_privacy_consent,
    "enrollment_cert": common.extract_enrollment_cert,
    "id_card_bankbook": common.extract_id_card_bankbook,
    "worklog": scholarship.extract_worklog,
    "worklog_handwrite": scholarship.extract_worklog_handwrite,
    "claim_form": scholarship.extract_claim_form,
    "monthly_report": scholarship.extract_monthly_report,
    "ta_recommendation": scholarship.extract_ta_recommendation,
    "innovation_application": innovation.extract_application,
    "club_report": innovation.extract_club_report,
    "trip_request": travel.extract_trip_request,
    "trip_evidence": travel.extract_trip_evidence,
    "receipt_tollgate": travel.extract_tollgate_receipts,
    "receipt_card": travel.extract_card_receipts,
}


def extract(document: Document) -> Document:
    """문서에 담긴 모든 서류 종류에 대해 추출기를 돌린다."""
    for doc_type in sorted(document.contains) or [document.doc_type]:
        extractor = REGISTRY.get(doc_type or "")
        if extractor is None:
            continue
        try:
            extractor(document)
        except Exception as exc:  # 한 서류의 파싱 실패가 전체 검토를 막지 않게 한다
            document.notes.append(f"'{doc_type}' 추출 중 오류: {exc}")
    common.extract_person(document)
    return document


__all__ = ["extract", "REGISTRY", "common", "scholarship", "innovation", "travel"]
