"""파일별 보완사항 집계 테스트.

'어떤 파일을 고쳐야 하는지' 가 화면의 핵심이므로, 지적이 올바른 파일에
붙는지와 정렬 순서를 확인한다.
"""
from __future__ import annotations

import datetime as dt

from conftest import make_document, run
from expense_review.models import Severity


def _travel_documents():
    return [
        make_document(
            "trip_request", "출장신청서.pdf",
            doc_no="HRHFB260626UF0000000002160002101",
            issued_at=dt.date(2026, 6, 26),
            trips=[{"name": "이동재",
                    "start": dt.datetime(2026, 7, 2, 18, 0),
                    "end": dt.datetime(2026, 7, 3, 12, 0),
                    "destination": "평창", "allowance_eligible": True,
                    "purpose": "코위크 아카데미 강연"}],
        ),
        make_document(
            "trip_evidence", "출장증빙.pdf",
            transport_block=True, route_block=True,
            dist_out=82, dist_back=82, dist_total=None, transport_amount=4350,
            stay_dates=[dt.date(2026, 7, 2)],
        ),
        make_document(
            "receipt_tollgate", "하이패스.pdf",
            receipts=[{"kind": "tollgate", "label": "하이패스 1",
                       "datetime": dt.datetime(2026, 7, 3, 13, 20),
                       "amount": 4350, "approval_no": "H673-7301-04539"}],
        ),
        make_document("receipt_card", "체류영수증.pdf", receipts=[
            {"kind": "stay", "label": "전표", "datetime": dt.datetime(2026, 7, 2, 20, 0),
             "amount": 9000, "approval_no": "00485918"}]),
        make_document("purpose_evidence", "강연정보.pdf"),
    ]


def test_findings_are_grouped_under_the_file_they_came_from():
    result = run("출장비", _travel_documents(), owner="이동재")
    grouped = result.by_document()

    # 총 이동경로 공란·체류증빙 누락은 출장증빙 파일의 문제다.
    evidence = {f.rule_id for f in grouped["출장증빙.pdf"]}
    assert {"R-TRV-004", "R-TRV-006"} <= evidence

    # 기간을 벗어난 통행료는 그 영수증 파일에 붙어야 한다.
    tollgate = {f.rule_id for f in grouped["하이패스.pdf"]}
    assert "R-TRV-011" in tollgate


def test_document_summary_lists_every_uploaded_file():
    documents = _travel_documents()
    result = run("출장비", documents, owner="이동재")
    names = {summary.name for summary in result.document_summary()}
    assert {document.name for document in documents} <= names


def test_clean_file_reports_no_findings_and_passes_status():
    result = run("출장비", _travel_documents(), owner="이동재")
    lookup = {s.name: s for s in result.document_summary()}
    assert lookup["강연정보.pdf"].findings == []
    assert lookup["강연정보.pdf"].status is Severity.PASS


def test_summaries_are_sorted_worst_first():
    result = run("출장비", _travel_documents(), owner="이동재")
    weights = [summary.weight for summary in result.document_summary()]
    assert weights == sorted(weights, reverse=True)


def test_findings_without_a_source_go_to_the_general_bucket():
    """필수 서류 누락처럼 특정 파일에 속하지 않는 지적이 사라지지 않아야 한다."""
    documents = [make_document("trip_evidence", "출장증빙.pdf",
                               transport_block=True, route_block=True,
                               dist_out=10, dist_back=10, dist_total=20,
                               stay_dates=[])]
    result = run("출장비", documents, owner="아무개")
    summaries = {s.name: s for s in result.document_summary()}
    assert "서류 전체" in summaries
    assert any(f.rule_id == "R-CMN-001" for f in summaries["서류 전체"].findings)
