"""문서 자동 분류 — docs/04-architecture.md §2."""
from pathlib import Path

from app.classify import classify_pages, needs_confirmation, strip_attachment_list

from .fixtures import (
    INN_FORM7_1,
    INN_FORM8,
    INN_WORKLOG,
    LEE_SJ_EVIDENCE,
    LEE_SJ_REQUEST,
    LEE_SJ_TOLLGATE,
    TA_FORM1,
    TA_FORM2,
    TA_FORM3,
    TA_FORM4,
    TA_ROSTER,
    TA_WORKLOG,
    make_pages,
)


def kinds(name, texts, expense_type, subtype=None):
    documents = classify_pages(Path(name), make_pages(*texts), expense_type, subtype)
    return [doc.kind for doc in documents]


def test_one_file_holding_four_forms_is_split():
    """TA 기본서류 한 파일에 양식1~4 가 들어 있다. 페이지별로 갈라야 한다."""
    assert kinds("26학년도 1학기 TA 기본서류(권석재).pdf",
                 [TA_FORM1, TA_FORM2, TA_FORM3, TA_FORM4],
                 "근로장학금", "TA") == [
        "form1_recommendation", "form2_privacy_consent",
        "form3_id_bankbook", "form4_enrollment",
    ]


def test_scholarship_documents():
    assert kinds("2026년도 3월 TA 근무상황부.pdf", [TA_WORKLOG], "근로장학금", "TA") == ["form5_worklog"]
    assert kinds("2026년도 3월 (나)형 근로장학금 지급내역.pdf", [TA_ROSTER],
                 "근로장학금", "TA") == ["payment_roster"]


def test_innovation_documents():
    assert kinds("혁신인재_5월 AIMPACT_.pdf", [INN_FORM8], "혁신인재지원금") == ["form8_application"]
    assert kinds("활동보고서 (AIMPACT_5월).pdf", [INN_FORM7_1], "혁신인재지원금") == ["form7_1_report"]
    assert kinds("근무상황부_AIMPACT_5월.pdf", [INN_WORKLOG], "혁신인재지원금") == ["attach1_worklog"]


def test_travel_documents():
    assert kinds("국내 출장신청서 (3건).pdf", [LEE_SJ_REQUEST], "출장비") == ["trip_request"]
    assert kinds("이성재 출장증빙.pdf", [LEE_SJ_EVIDENCE], "출장비") == ["trip_evidence"]
    assert kinds("하이패스 이용내역.pdf", [LEE_SJ_TOLLGATE], "출장비") == ["transport_receipts"]


def test_attachment_list_is_cut_before_fingerprinting():
    """서류 끝의 `붙임` 목록에는 다른 서류 이름이 전부 나열돼 있다.

    그대로 지문을 매기면 서류들이 서로 교차 오분류된다.
    """
    body = "장학금 지급 청구서\n청구금액 : 300,000\n붙임 1. 개인정보 동의서 2. 재학증명서 3. 근무상황부\n"
    assert "재학증명서" not in strip_attachment_list(body)
    assert "청구금액" in strip_attachment_list(body)

    # `[붙임1] …` 은 서류 제목이므로 잘라내면 안 된다.
    titled = "[붙임1] 근로장학생 근무상황부\n근로기간 : 2026.5.1 ~ 2026.5.31\n"
    assert strip_attachment_list(titled) == titled


def test_claim_form_with_attachment_list_still_classifies_correctly():
    text = ("장학금 지급 청구서\n프로그램명 : COSS 서포터즈\n청구금액 : 300,000\n"
            "붙임 1. 개인정보 수집·이용 동의서  2. 재학증명서  3. 근무상황부\n")
    assert kinds("청구서_홍길동.pdf", [text], "근로장학금", "SUPPORTERS") == ["claim_form"]


def test_unknown_file_is_flagged_for_confirmation():
    documents = classify_pages(Path("스캔본.pdf"), make_pages("알 수 없는 내용"), "출장비")
    assert needs_confirmation(documents) == documents
