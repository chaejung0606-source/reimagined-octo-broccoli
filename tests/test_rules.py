"""규칙 판정 테스트.

각 테스트는 샘플 서류에서 실제로 관찰된 상황을 재현한다(docs/01 참고).
'정상 건에서 아무것도 잡지 않는다'는 테스트가 특히 중요하다 — 오탐이 나면
담당자가 앱을 쓰지 않는다.
"""
from __future__ import annotations

import datetime as dt

from conftest import ids, make_document, run


# ── 출장비 ────────────────────────────────────────────────────────────────

def _trip_request(start=dt.datetime(2026, 6, 29, 9, 0), end=dt.datetime(2026, 7, 1, 18, 0),
                  name="임채정", destination="평창,강릉", trips=None):
    return make_document(
        "trip_request", "국내 출장신청서.pdf",
        doc_no="HRHFB260626UF0000000002160002101",
        issued_at=dt.date(2026, 6, 26),
        trips=trips or [{
            "name": name, "start": start, "end": end, "destination": destination,
            "allowance_eligible": True, "purpose": "워크숍 참석",
        }],
    )


def _tollgate(*receipts):
    return make_document("receipt_tollgate", "하이패스.pdf", receipts=list(receipts))


def toll(when, amount, label="하이패스 1"):
    return {"kind": "tollgate", "label": label, "datetime": when, "amount": amount,
            "merchant": "한국도로공사 대관령영업소", "approval_no": f"H000-0000-{amount:05d}"}


def test_clean_travel_submission_reports_nothing():
    """정상 제출건에서는 확정 지적이 나오지 않아야 한다."""
    documents = [
        _trip_request(),
        make_document("trip_evidence", "출장증빙.pdf",
                      transport_block=True, route_block=True,
                      dist_out=211, dist_back=154, dist_total=365,
                      transport_amount=10920,
                      route_note="경유지가 달라 왕복 거리가 다름",
                      stay_dates=[dt.date(2026, 6, 29), dt.date(2026, 6, 30), dt.date(2026, 7, 1)]),
        _tollgate(toll(dt.datetime(2026, 6, 29, 11, 31), 10920)),
        make_document("receipt_card", "체류영수증.pdf",
                      receipts=[{"kind": "stay", "label": "카드전표 1",
                                 "datetime": dt.datetime(2026, 6, 29, 12, 26), "amount": 1200,
                                 "approval_no": "00485918"}]),
    ]
    assert ids(run("출장비", documents, owner="임채정")) == set()


def test_missing_route_total_is_reported_with_computed_value():
    """이성재·이동재 사례: 총 이동경로 칸이 비어 있다."""
    documents = [
        _trip_request(name="이성재"),
        make_document("trip_evidence", "출장증빙.pdf",
                      transport_block=True, route_block=True,
                      dist_out=206, dist_back=206, dist_total=None,
                      transport_amount=8500,
                      stay_dates=[dt.date(2026, 6, 29), dt.date(2026, 6, 30), dt.date(2026, 7, 1)]),
        _tollgate(toll(dt.datetime(2026, 6, 29, 13, 44), 8500)),
        make_document("receipt_card", "체류.pdf", receipts=[
            {"kind": "stay", "label": "전표", "datetime": dt.datetime(2026, 6, 30, 9, 0), "amount": 5000}]),
    ]
    result = run("출장비", documents, owner="이성재")
    assert "R-TRV-006" in ids(result)
    finding = next(f for f in result.findings if f.rule_id == "R-TRV-006")
    assert "412" in finding.fix     # 조치 문구에 정답을 제시한다


def test_receipt_outside_trip_period_is_reported():
    """이동재 사례: 출장 종료 7/3 12:00 인데 통행료가 7/3 13:20."""
    documents = [
        _trip_request(start=dt.datetime(2026, 7, 2, 18, 0), end=dt.datetime(2026, 7, 3, 12, 0),
                      name="이동재", destination="평창"),
        make_document("trip_evidence", "출장증빙.pdf",
                      transport_block=True, route_block=True,
                      dist_out=82, dist_back=82, dist_total=164,
                      transport_amount=4350,
                      stay_dates=[dt.date(2026, 7, 2), dt.date(2026, 7, 3)]),
        _tollgate(toll(dt.datetime(2026, 7, 3, 13, 20), 4350)),
        make_document("receipt_card", "체류.pdf", receipts=[
            {"kind": "stay", "label": "전표", "datetime": dt.datetime(2026, 7, 2, 20, 0), "amount": 9000}]),
        make_document("purpose_evidence", "강연정보.pdf"),
    ]
    assert "R-TRV-011" in ids(run("출장비", documents, owner="이동재"))


def test_missing_stay_evidence_date_is_reported():
    documents = [
        _trip_request(start=dt.datetime(2026, 7, 2, 18, 0), end=dt.datetime(2026, 7, 3, 12, 0),
                      name="이동재", destination="평창"),
        make_document("trip_evidence", "출장증빙.pdf",
                      transport_block=True, route_block=True,
                      dist_out=82, dist_back=82, dist_total=164, transport_amount=4350,
                      stay_dates=[dt.date(2026, 7, 2)]),
        _tollgate(toll(dt.datetime(2026, 7, 3, 9, 0), 4350)),
        make_document("receipt_card", "체류.pdf", receipts=[]),
    ]
    result = run("출장비", documents, owner="이동재")
    assert "R-TRV-004" in ids(result)
    assert "07/03" in next(f for f in result.findings if f.rule_id == "R-TRV-004").message


def test_transport_total_filters_receipts_by_trip_period():
    """이성재 사례: 8건 33,900원 중 기간 내 3건 8,500원만 청구 — 정상이어야 한다.

    기간 필터 없이 합산하면 여기서 오탐이 난다.
    """
    documents = [
        _trip_request(name="이성재"),
        make_document("trip_evidence", "출장증빙.pdf",
                      transport_block=True, route_block=True,
                      dist_out=206, dist_back=206, dist_total=412, transport_amount=8500,
                      stay_dates=[dt.date(2026, 6, 29), dt.date(2026, 6, 30), dt.date(2026, 7, 1)]),
        _tollgate(
            toll(dt.datetime(2026, 6, 29, 13, 44), 4100, "1"),
            toll(dt.datetime(2026, 6, 29, 16, 25), 2000, "2"),
            toll(dt.datetime(2026, 7, 1, 14, 15), 2400, "3"),
            # 아래 5건은 다른 출장분이라 이번 정산에 들어가면 안 된다.
            toll(dt.datetime(2026, 7, 2, 16, 59), 4100, "4"),
            toll(dt.datetime(2026, 7, 4, 21, 29), 9800, "5"),
        ),
        make_document("receipt_card", "체류.pdf", receipts=[
            {"kind": "stay", "label": "전표", "datetime": dt.datetime(2026, 6, 30, 9, 0), "amount": 5000}]),
    ]
    assert "R-TRV-009" not in ids(run("출장비", documents, owner="이성재"))


def test_missing_evidence_blocks_are_reported():
    """황승재·방석훈·이세영 사례: 교통비·이동경로 블록 자체가 없다."""
    documents = [
        _trip_request(name="황승재"),
        make_document("trip_evidence", "출장증빙.pdf",
                      transport_block=False, route_block=False,
                      stay_dates=[dt.date(2026, 6, 29), dt.date(2026, 6, 30), dt.date(2026, 7, 1)]),
        make_document("receipt_card", "영수증.pdf", receipts=[
            {"kind": "stay", "label": "전표", "datetime": dt.datetime(2026, 6, 29, 12, 26),
             "amount": 1200, "approval_no": "00485918"}]),
    ]
    found = ids(run("출장비", documents, owner="황승재"))
    assert {"R-TRV-002", "R-TRV-003"} <= found


def test_duplicate_receipt_is_reported():
    same = toll(dt.datetime(2026, 6, 29, 11, 31), 3100)
    documents = [
        _trip_request(),
        make_document("trip_evidence", "출장증빙.pdf",
                      transport_block=True, route_block=True,
                      dist_out=211, dist_back=211, dist_total=422, transport_amount=3100,
                      stay_dates=[dt.date(2026, 6, 29), dt.date(2026, 6, 30), dt.date(2026, 7, 1)]),
        make_document("receipt_tollgate", "하이패스A.pdf", receipts=[same]),
        make_document("receipt_card", "하이패스B.pdf", receipts=[dict(same)]),
    ]
    assert "R-TRV-019" in ids(run("출장비", documents, owner="임채정"))


# ── 근로장학금 ────────────────────────────────────────────────────────────

def _worklog(rows=None, total=15.0, period=(dt.date(2026, 3, 3), dt.date(2026, 3, 31))):
    rows = rows if rows is not None else [
        {"date": dt.date(2026, 3, 9), "start": "09:00", "end": "14:00",
         "hours": 5.0, "computed_hours": 5.0, "detail": "강의실 환경 개선"},
        {"date": dt.date(2026, 3, 16), "start": "09:00", "end": "14:00",
         "hours": 5.0, "computed_hours": 5.0, "detail": "기자재 점검"},
        {"date": dt.date(2026, 3, 23), "start": "09:00", "end": "14:00",
         "hours": 5.0, "computed_hours": 5.0, "detail": "실습 환경 세팅"},
    ]
    return make_document(
        "worklog", "근무상황부.pdf", rows=rows, total_hours=total, period=period,
        approver="손경호", applicant="권석재", name="권석재", student_id="202630395",
        account_no="110493878372", bank="신한은행", program="데이터보안활용융합진로설계/TA",
    )


def _roster(**overrides):
    row = {"seq": 1, "name": "권석재", "student_id": "202630395",
           "account_no": "110493878372", "bank": "신한은행",
           "unit_price": 20000, "hours": 15.0, "amount": 300000,
           "course_name": "데이터보안활용융합진로설계"}
    row.update(overrides)
    return make_document("payment_roster", "지급내역.pdf", rows=[row])


def _ta_docs():
    return [
        make_document("ta_recommendation", "TA기본서류.pdf",
                      professor="손경호", name="권석재",
                      operating_period=(dt.date(2026, 3, 3), dt.date(2026, 6, 19))),
        make_document("privacy_consent", "동의서.pdf",
                      consents=[{"label": "기본 개인정보", "agreed": True},
                                {"label": "고유식별정보", "agreed": True},
                                {"label": "제3자 제공", "agreed": True}]),
        make_document("id_card_bankbook", "신분증통장.pdf"),
        make_document("enrollment_cert", "재학증명서.pdf"),
    ]


def test_clean_ta_submission_reports_nothing():
    """권석재 실제 건: 15시간 × 20,000원 = 300,000원이 세 서류에서 일치한다."""
    documents = [_worklog(), _roster(), *_ta_docs()]
    assert ids(run("근로장학금", documents, owner="권석재", subtype="TA")) == set()


def test_row_hour_miscalculation_is_reported():
    rows = [{"date": dt.date(2026, 3, 9), "start": "09:00", "end": "14:00",
             "hours": 6.0, "computed_hours": 5.0, "detail": "강의실 환경 개선"}]
    documents = [_worklog(rows=rows, total=6.0), _roster(hours=6.0, amount=120000), *_ta_docs()]
    result = run("근로장학금", documents, owner="권석재", subtype="TA")
    assert "R-SCH-001" in ids(result)


def test_total_hours_mismatch_is_reported():
    documents = [_worklog(total=20.0), _roster(hours=20.0, amount=400000), *_ta_docs()]
    assert "R-SCH-002" in ids(run("근로장학금", documents, owner="권석재", subtype="TA"))


def test_amount_calculation_error_is_reported():
    documents = [_worklog(), _roster(amount=350000), *_ta_docs()]
    assert "R-SCH-009" in ids(run("근로장학금", documents, owner="권석재", subtype="TA"))


def test_approver_other_than_professor_is_reported():
    worklog = _worklog()
    worklog.fields["approver"].value = "전상철"
    documents = [worklog, _roster(), *_ta_docs()]
    assert "R-SCH-013" in ids(run("근로장학금", documents, owner="권석재", subtype="TA"))


def test_work_date_outside_period_is_reported():
    rows = [{"date": dt.date(2026, 4, 5), "start": "09:00", "end": "14:00",
             "hours": 5.0, "computed_hours": 5.0, "detail": "수업 지원"}]
    documents = [_worklog(rows=rows, total=5.0), _roster(hours=5.0, amount=100000), *_ta_docs()]
    assert "R-SCH-003" in ids(run("근로장학금", documents, owner="권석재", subtype="TA"))


def test_missing_required_document_is_reported():
    documents = [_worklog(), _roster()]      # 양식1~4 없음
    result = run("근로장학금", documents, owner="권석재", subtype="TA")
    assert "R-CMN-001" in ids(result)


# ── 혁신인재지원금 ────────────────────────────────────────────────────────

def _innovation_docs(**overrides):
    application = make_document(
        "innovation_application", "신청서.pdf",
        club_name="AIMPACT", advisor="강경필", activity_field="클라우드",
        topic="클라우드 환경에서 AI를 활용한 보안 및 데이터 분석 프로젝트",
        applicant="김예린", student_id="202314338", account_no="59220101565992",
        bank="국민은행", amount=240000, amount_hangul="금이십사만원정",
        department="컴퓨터공학과",
    )
    report = make_document(
        "club_report", "활동보고서.pdf",
        club_name="AIMPACT", advisor="강경필", president="김예린",
        field_checked=overrides.get("field_checked", "클라우드"),
        topic="클라우드 환경에서 AI를 활용한 보안 및 데이터 분석 프로젝트",
        page_count=1,
        activity_dates=overrides.get("activity_dates", [dt.date(2026, 5, 6)]),
        members=overrides.get("members", [
            {"role": "회장", "name": "김예린", "department": "컴퓨터공학과",
             "student_id": "202314338", "phone": "010-9986-0144"},
        ]),
        text_anomalies=overrides.get("text_anomalies"),
    )
    worklog = make_document(
        "worklog", "근무상황부.pdf",
        rows=[{"date": dt.date(2026, 5, 6), "start": "09:00", "end": "12:00",
               "hours": 3.0, "computed_hours": 3.0, "detail": "성과공유회 준비"},
              {"date": dt.date(2026, 5, 6), "start": "13:00", "end": "18:00",
               "hours": 5.0, "computed_hours": 5.0, "detail": "자료 정리"},
              {"date": dt.date(2026, 5, 13), "start": "09:00", "end": "12:00",
               "hours": 3.0, "computed_hours": 3.0, "detail": "공모전 준비"},
              {"date": dt.date(2026, 5, 20), "start": "13:00", "end": "18:00",
               "hours": 5.0, "computed_hours": 5.0, "detail": "스터디 진행"}],
        total_hours=16.0, period=(dt.date(2026, 5, 1), dt.date(2026, 5, 31)),
        approver=overrides.get("approver", "강경필"), applicant="김예린",
        name="김예린", student_id="202314338", account_no="59220101565992",
        bank="국민은행", department="컴퓨터공학과",
    )
    roster = make_document("payment_roster", "지급내역.pdf", rows=[{
        "seq": 1, "name": "김예린", "student_id": "202314338",
        "account_no": "59220101565992", "bank": "국민은행",
        "amount": 240000, "club_name": "AIMPACT"}])
    return [application, report, worklog, roster,
            make_document("id_card_bankbook", "기본정보.pdf"),
            make_document("enrollment_cert", "재학증명서.pdf")]


def test_clean_innovation_submission_reports_nothing():
    assert ids(run("혁신인재지원금", _innovation_docs(), owner="김예린")) == set()


def test_account_notation_difference_is_not_a_finding():
    """신청서 '59220101565992' vs 지급내역 '592201-01-565992' — 정규화하면 같다."""
    documents = _innovation_docs()
    documents[3].fields["rows"].value[0]["account_no"] = "592201-01-565992"
    assert "R-CMN-005" not in ids(run("혁신인재지원금", documents, owner="김예린"))


def test_report_activity_date_without_work_record_is_reported():
    """AIMPACT 5월 사례: 보고서 5/4·5/18 vs 근무상황부 5/6·5/13·5/20."""
    documents = _innovation_docs(activity_dates=[dt.date(2026, 5, 4), dt.date(2026, 5, 18)])
    result = run("혁신인재지원금", documents, owner="김예린")
    assert "R-INN-012" in ids(result)
    assert "05/04" in next(f for f in result.findings if f.rule_id == "R-INN-012").message


def test_member_student_id_format_is_reported():
    members = [
        {"role": "회장", "name": "김예린", "department": "컴퓨터공학과",
         "student_id": "202314338", "phone": "010-9986-0144"},
        {"role": "팀원", "name": "최용빈", "department": "생화학공학과",
         "student_id": "20213452", "phone": "010-8620-5679"},   # 8자리
    ]
    assert "R-INN-014" in ids(run("혁신인재지원금", _innovation_docs(members=members), owner="김예린"))


def test_text_anomaly_is_reported():
    documents = _innovation_docs(text_anomalies=["5원4일"])
    assert "R-INN-020" in ids(run("혁신인재지원금", documents, owner="김예린"))


def test_approver_other_than_advisor_is_reported():
    documents = _innovation_docs(approver="전상철")
    assert "R-INN-008" in ids(run("혁신인재지원금", documents, owner="김예린"))


def test_activity_field_mismatch_is_reported():
    documents = _innovation_docs(field_checked="블록체인")
    assert "R-INN-009" in ids(run("혁신인재지원금", documents, owner="김예린"))


# ── 통장·재학증명서·작성일 (공통) ─────────────────────────────────────────

def _ta_docs_with(bankbook=None, cert=None, consent_date=dt.date(2026, 4, 1)):
    """TA 기본서류에 통장·재학증명서 값을 실제로 채워 넣은 판."""
    documents = _ta_docs()
    for document in documents:
        if document.doc_type == "id_card_bankbook" and bankbook:
            document.fields.update(make_document("id_card_bankbook", **bankbook).fields)
        if document.doc_type == "enrollment_cert" and cert:
            document.fields.update(make_document("enrollment_cert", **cert).fields)
        if document.doc_type == "privacy_consent":
            document.fields.update(
                make_document("privacy_consent", signed_at=consent_date).fields
            )
    return documents


def test_bankbook_holder_other_than_applicant_is_reported():
    """가족 명의 통장을 낸 경우. 지급 자체가 막히므로 🔴 다."""
    documents = [_worklog(), _roster(),
                 *_ta_docs_with(bankbook={"bankbook_holder": "권미영",
                                          "bankbook_account_no": "110493878372"})]
    result = run("근로장학금", documents, owner="권석재", subtype="TA")
    assert "R-CMN-015" in ids(result)
    assert "권미영" in next(f for f in result.findings if f.rule_id == "R-CMN-015").message


def test_bankbook_account_mismatch_is_reported():
    documents = [_worklog(), _roster(),
                 *_ta_docs_with(bankbook={"bankbook_holder": "권석재",
                                          "bankbook_account_no": "110493870000"})]
    assert "R-CMN-016" in ids(run("근로장학금", documents, owner="권석재", subtype="TA"))


def test_bankbook_account_notation_difference_is_not_a_finding():
    """김예린 사례와 같은 표기 차이. 하이픈만 다르면 정상이다."""
    documents = [_worklog(), _roster(),
                 *_ta_docs_with(bankbook={"bankbook_holder": "권석재",
                                          "bankbook_account_no": "110-493-878372"})]
    assert ids(run("근로장학금", documents, owner="권석재", subtype="TA")) == set()


def test_stale_enrollment_certificate_is_reported():
    """근로기간 종료(3/31) 뒤 4/1 제출인데 재학증명서는 2/1 발급 — 59일 경과."""
    documents = [_worklog(), _roster(),
                 *_ta_docs_with(bankbook={"bankbook_holder": "권석재",
                                          "bankbook_account_no": "110493878372"},
                                cert={"issued_at": dt.date(2026, 2, 1)})]
    result = run("근로장학금", documents, owner="권석재", subtype="TA")
    assert "R-CMN-013" in ids(result)
    assert "59일" in next(f for f in result.findings if f.rule_id == "R-CMN-013").message


def test_fresh_enrollment_certificate_is_not_a_finding():
    documents = [_worklog(), _roster(),
                 *_ta_docs_with(bankbook={"bankbook_holder": "권석재",
                                          "bankbook_account_no": "110493878372"},
                                cert={"issued_at": dt.date(2026, 3, 20)})]
    assert ids(run("근로장학금", documents, owner="권석재", subtype="TA")) == set()


def test_worklog_written_before_activity_end_is_reported():
    """근로기간이 3/31 까지인데 근무상황부 작성일이 3/20 이다."""
    worklog = _worklog()
    worklog.fields.update(make_document("worklog", submitted_at=dt.date(2026, 3, 20)).fields)
    result = run("근로장학금", [worklog, _roster(), *_ta_docs()], owner="권석재", subtype="TA")
    assert "R-CMN-017" in ids(result)


def test_worklog_written_after_activity_end_is_not_a_finding():
    worklog = _worklog()
    worklog.fields.update(make_document("worklog", submitted_at=dt.date(2026, 3, 31)).fields)
    assert ids(run("근로장학금", [worklog, _roster(), *_ta_docs()],
                   owner="권석재", subtype="TA")) == set()


# ── 강좌명 대사 (근로장학금) ──────────────────────────────────────────────

def test_program_role_suffix_is_not_a_course_mismatch():
    """근무상황부는 '강좌명/TA', 지급내역은 강좌명만 적는다. 정상이다."""
    assert "R-SCH-014" not in ids(run("근로장학금", [_worklog(), _roster(), *_ta_docs()],
                                      owner="권석재", subtype="TA"))


def test_course_name_mismatch_is_reported():
    documents = [_worklog(), _roster(course_name="운영체제"), *_ta_docs()]
    result = run("근로장학금", documents, owner="권석재", subtype="TA")
    assert "R-SCH-014" in ids(result)
    assert "운영체제" in next(f for f in result.findings if f.rule_id == "R-SCH-014").message


# ── 하이패스 경로·출장자·품목·장소 (출장비) ──────────────────────────────

def _leg(when, amount, entry, exit_gate, label):
    return {"kind": "tollgate", "label": label, "datetime": when, "amount": amount,
            "tollgate_in": entry, "merchant": exit_gate,
            "approval_no": f"H000-0000-{amount:05d}"}


def _travel_docs(*receipt_documents, owner="임채정", **evidence):
    fields = {"transport_block": True, "route_block": True,
              "dist_out": 211, "dist_back": 154, "dist_total": 365,
              "transport_amount": 10920,
              "route_note": "경유지가 달라 왕복 거리가 다름",
              "stay_dates": [dt.date(2026, 6, 29), dt.date(2026, 6, 30), dt.date(2026, 7, 1)]}
    fields.update(evidence)
    return [_trip_request(name=owner), make_document("trip_evidence", "출장증빙.pdf", **fields),
            *receipt_documents]


def test_connected_tollgate_legs_are_not_a_finding():
    """가는 길 출구와 오는 길 입구가 같은 영업소면 이어진 것이다."""
    receipts = _tollgate(
        _leg(dt.datetime(2026, 6, 29, 11, 31), 5460, "춘천", "한국도로공사 대관령영업소", "하이패스 1"),
        _leg(dt.datetime(2026, 7, 1, 17, 10), 5460, "대관령(IC)", "춘천영업소", "하이패스 2"),
    )
    assert "R-TRV-014" not in ids(run("출장비", _travel_docs(receipts), owner="임채정"))


def test_broken_tollgate_route_is_reported():
    """대관령으로 나갔는데 다음 구간이 부산에서 시작한다."""
    receipts = _tollgate(
        _leg(dt.datetime(2026, 6, 29, 11, 31), 5460, "춘천", "대관령영업소", "하이패스 1"),
        _leg(dt.datetime(2026, 7, 1, 17, 10), 5460, "부산", "춘천영업소", "하이패스 2"),
    )
    result = run("출장비", _travel_docs(receipts), owner="임채정")
    assert "R-TRV-014" in ids(result)
    assert "대관령" in next(f for f in result.findings if f.rule_id == "R-TRV-014").message


def test_traveller_not_in_trip_request_is_reported():
    """동승자 4명 폴더에 같은 신청서가 들어간다. 엉뚱한 사람 것이면 여기서 걸린다."""
    documents = _travel_docs(_tollgate(toll(dt.datetime(2026, 6, 29, 11, 31), 10920)),
                             owner="전상철")
    result = run("출장비", documents, owner="황승재")
    assert "R-TRV-015" in ids(result)


def test_non_reimbursable_item_is_reported():
    stay = make_document("receipt_card", "체류영수증.pdf", receipts=[{
        "kind": "stay", "label": "카드전표 1", "datetime": dt.datetime(2026, 6, 29, 19, 20),
        "amount": 32000, "approval_no": "00485918",
        "items": [{"name": "삼겹살", "quantity": 2, "amount": 26000},
                  {"name": "소주", "quantity": 2, "amount": 6000}],
    }])
    documents = _travel_docs(_tollgate(toll(dt.datetime(2026, 6, 29, 11, 31), 10920)), stay)
    result = run("출장비", documents, owner="임채정")
    assert "R-TRV-023" in ids(result)
    assert "소주" in next(f for f in result.findings if f.rule_id == "R-TRV-023").message


def test_readable_receipt_without_banned_item_is_not_a_finding():
    stay = make_document("receipt_card", "체류영수증.pdf", receipts=[{
        "kind": "stay", "label": "카드전표 1", "datetime": dt.datetime(2026, 6, 29, 19, 20),
        "amount": 26000, "approval_no": "00485918",
        "items": [{"name": "삼겹살", "quantity": 2, "amount": 26000}],
    }])
    documents = _travel_docs(_tollgate(toll(dt.datetime(2026, 6, 29, 11, 31), 10920)), stay)
    assert "R-TRV-023" not in ids(run("출장비", documents, owner="임채정"))


def test_receipts_in_two_regions_within_the_hour_are_reported():
    stay = make_document("receipt_card", "체류영수증.pdf", receipts=[
        {"kind": "stay", "label": "카드전표 1", "datetime": dt.datetime(2026, 6, 29, 12, 26),
         "amount": 12000, "merchant_address": "강원특별자치도 평창군 대관령면",
         "items": [{"name": "된장찌개", "quantity": 1, "amount": 12000}]},
        {"kind": "stay", "label": "카드전표 2", "datetime": dt.datetime(2026, 6, 29, 12, 50),
         "amount": 9000, "merchant_address": "강원특별자치도 강릉시 교동",
         "items": [{"name": "아메리카노", "quantity": 2, "amount": 9000}]},
    ])
    documents = _travel_docs(_tollgate(toll(dt.datetime(2026, 6, 29, 11, 31), 10920)), stay)
    result = run("출장비", documents, owner="임채정")
    assert "R-TRV-024" in ids(result)


def test_receipts_far_apart_in_time_are_not_a_finding():
    stay = make_document("receipt_card", "체류영수증.pdf", receipts=[
        {"kind": "stay", "label": "카드전표 1", "datetime": dt.datetime(2026, 6, 29, 12, 26),
         "amount": 12000, "merchant_address": "강원특별자치도 평창군 대관령면",
         "items": [{"name": "된장찌개", "quantity": 1, "amount": 12000}]},
        {"kind": "stay", "label": "카드전표 2", "datetime": dt.datetime(2026, 6, 29, 19, 40),
         "amount": 9000, "merchant_address": "강원특별자치도 강릉시 교동",
         "items": [{"name": "아메리카노", "quantity": 2, "amount": 9000}]},
    ])
    documents = _travel_docs(_tollgate(toll(dt.datetime(2026, 6, 29, 11, 31), 10920)), stay)
    assert "R-TRV-024" not in ids(run("출장비", documents, owner="임채정"))
