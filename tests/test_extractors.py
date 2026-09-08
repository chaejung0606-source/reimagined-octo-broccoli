"""추출기 테스트 — 서류 텍스트에서 필드를 제대로 뽑는지.

실제 PDF 대신 그 안의 텍스트 레이어를 그대로 옮겨 시험한다. 검토 대상 서류에는
주민등록번호·계좌번호가 들어 있어 저장소에 넣을 수 없기 때문이다(conftest 참고).
값을 잘못 뽑으면 교차 대사에서 오탐이 되므로, '안 뽑는 경우' 도 함께 시험한다.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from expense_review.extractors import common, travel
from expense_review.models import Document


def _document(text: str, doc_type: str) -> Document:
    return Document(path=Path(f"{doc_type}.pdf"), doc_type=doc_type,
                    contains={doc_type}, pages=[text], page_types=[doc_type])


# ── 재학증명서 ────────────────────────────────────────────────────────────

def test_enrollment_cert_reads_labeled_issue_date():
    document = _document("재 학 증 명 서\n학번 202630395\n발급일자 : 2026년 03월 20일\n",
                         "enrollment_cert")
    common.extract_enrollment_cert(document)
    assert document.fields["issued_at"].value == dt.date(2026, 3, 20)


def test_enrollment_cert_reads_date_before_the_issuing_authority():
    """라벨이 없는 서식. 증명 주체 바로 앞의 날짜가 발급일이다."""
    document = _document(
        "위와 같이 재학 중임을 증명합니다.\n2026. 3. 20.\n강원대학교총장\n",
        "enrollment_cert",
    )
    common.extract_enrollment_cert(document)
    assert document.fields["issued_at"].value == dt.date(2026, 3, 20)


def test_enrollment_cert_scan_leaves_the_field_empty():
    """스캔본은 값을 채우지 않는다. 규칙 엔진이 '판독 불가' 로 넘긴다."""
    document = _document("", "enrollment_cert")
    common.extract_enrollment_cert(document)
    assert "issued_at" not in document.fields


# ── 통장 사본 ─────────────────────────────────────────────────────────────

def test_bankbook_reads_holder_and_account():
    document = _document(
        "통장 사본\n은행 : 신한은행\n예금주 : 권석재\n계좌번호 : 110-493-878372\n",
        "id_card_bankbook",
    )
    common.extract_id_card_bankbook(document)
    assert document.fields["bankbook_holder"].value == "권석재"
    assert document.fields["bankbook_account_no"].value == "110493878372"
    assert document.fields["bankbook_bank"].value == "신한은행"


def test_bankbook_does_not_read_the_branch_name_as_holder():
    """라벨 없이 한글을 집으면 지점명·상호를 예금주로 읽는다. 그러면 안 된다."""
    document = _document("신한은행 춘천지점\n고객님 감사합니다\n", "id_card_bankbook")
    common.extract_id_card_bankbook(document)
    assert "bankbook_holder" not in document.fields


def test_bankbook_account_is_kept_out_of_the_shared_field():
    """통장 계좌는 account_no 로 새지 않는다 — R-CMN-005 와 이중 보고를 막는다."""
    document = _document(
        "신분증 및 통장 사본\n예금주 : 권석재\n계좌번호 : 110-493-878372\n",
        "id_card_bankbook",
    )
    common.extract_person(document)
    assert "account_no" not in document.fields


# ── 카드 매출전표 품목 ────────────────────────────────────────────────────

def test_receipt_items_are_read_without_the_summary_rows():
    items = travel._parse_items(
        "승인번호 : 00485918\n"
        "가맹점명 : 대관령휴게소\n"
        "아메리카노  2  9,000\n"
        "생맥주 500  1  6,000\n"
        "공급가액        13,636\n"
        "부가세           1,364\n"
        "합계  15,000\n"
    )
    assert [item["name"] for item in items] == ["아메리카노", "생맥주 500"]
    assert items[0]["quantity"] == 2 and items[0]["amount"] == 9000


def test_merchant_address_is_not_read_as_an_item():
    """주소가 번지로 끝나면 품목 줄과 모양이 같다. 지명이 든 줄은 버린다."""
    items = travel._parse_items(
        "가맹점명 : 대관령휴게소\n"
        "강원 평창군 대관령면 100\n"
        "짜장면  1  9,000\n"
    )
    assert [item["name"] for item in items] == ["짜장면"]


def test_receipt_without_item_lines_yields_nothing():
    assert travel._parse_items("승인번호 : 00485918\n합계  15,000\n") == []
