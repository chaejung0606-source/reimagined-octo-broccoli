"""업로드된 파일이 어떤 서류인지 판정한다 (docs/04 §2).

파일명이 자유롭기 때문에 파일명만으로는 부족하다. 2단계로 본다.

  1차: 페이지 텍스트의 지문 (`[양식5]`, `* 체류 증빙`, `하이패스는` …)
  2차: 파일명 키워드
  실패: None — 사용자에게 직접 고르게 한다

PDF 한 개에 여러 서류가 들어 있는 경우가 흔하다. 예를 들어
`26학년도 1학기 TA 기본서류.pdf` 한 파일에 양식1~4가 모두 들어 있다.
그래서 페이지마다 판정해 `Document.contains` 에 모아 둔다. 서류 완비성(L0)은
파일 개수가 아니라 이 집합으로 판단해야 한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .models import Document
from .pdfio import flatten

# ── 서류 종류 (규칙 YAML 의 required_documents 키와 일치해야 한다) ──────────

DOC_LABELS: dict[str, str] = {
    "payment_roster": "지급내역",
    "privacy_consent": "개인정보 수집·이용 동의서",
    "id_card_bankbook": "신분증 및 통장 사본",
    "enrollment_cert": "재학증명서",
    "ta_recommendation": "[양식1] TA 추천 및 서약서",
    "worklog": "근로장학생 근무상황부",
    "worklog_handwrite": "운영활동 보고서(근무일지)",
    "claim_form": "장학금 지급 청구서",
    "monthly_report": "월간 활동 결과 보고서",
    "innovation_application": "[양식8] 혁신인재지원금 신청서",
    "club_report": "[양식7-1] 월별 활동 결과 보고서",
    "trip_request": "국내 출장신청서",
    "trip_evidence": "출장증빙",
    "receipt_tollgate": "하이패스 통행료 영수증",
    "receipt_card": "카드 매출전표",
    "purpose_evidence": "출장목적 근거자료",
}


@dataclass(frozen=True)
class Fingerprint:
    doc_type: str
    # 이 중 하나라도 있어야 한다 (없으면 조건 없음)
    any_of: tuple[str, ...] = ()
    # 전부 있어야 한다
    all_of: tuple[str, ...] = ()
    # 하나라도 있으면 탈락
    none_of: tuple[str, ...] = ()
    priority: int = 0   # 클수록 먼저 본다

    def matches(self, text: str) -> bool:
        if any(token in text for token in self.none_of):
            return False
        if self.all_of and not all(token in text for token in self.all_of):
            return False
        if self.any_of and not any(token in text for token in self.any_of):
            return False
        return bool(self.any_of or self.all_of)


# 지문은 flatten() 으로 공백·줄바꿈을 제거한 텍스트에 대해 검사한다.
# 한글 서식 PDF 는 '근로장학생\n근무상황부' 처럼 글자 단위로 줄바꿈되기 때문이다.
FINGERPRINTS: tuple[Fingerprint, ...] = (
    # ── 출장비 ──
    Fingerprint("receipt_tollgate", all_of=("하이패스",), any_of=("영업소", "영수증"), priority=90),
    Fingerprint("trip_request", any_of=("국내출장신청서", "다음과같이출장을명함"), priority=90),
    Fingerprint("trip_evidence", any_of=("체류증빙", "교통비증빙", "이동경로"), priority=85),
    Fingerprint("receipt_card", all_of=("승인번호",), any_of=("가맹점명", "사업자등록번호", "매출전표"), priority=70),
    # ── 근로장학금 ──
    Fingerprint("ta_recommendation", any_of=("[양식1]", "TA추천및서약서"), priority=90),
    Fingerprint("worklog", any_of=("근로장학생근무상황부", "근무상황부"), priority=88),
    Fingerprint("claim_form", any_of=("장학금지급청구서",), priority=88),
    Fingerprint("monthly_report", any_of=("활동결과보고서",), none_of=("[양식7-1]", "소학회"), priority=80),
    Fingerprint("worklog_handwrite", any_of=("운영활동보고서",), priority=85),
    # ── 혁신인재지원금 ──
    Fingerprint("innovation_application", any_of=("[양식8]", "혁신인재지원금신청서"), priority=92),
    Fingerprint("club_report", any_of=("[양식7-1]", "월별활동결과보고서", "소학회활동현황보고"), priority=92),
    # ── 공통 첨부 ──
    Fingerprint("payment_roster", all_of=("지급내역",), any_of=("연번", "합계"), priority=95),
    Fingerprint("privacy_consent", any_of=("개인정보수집․이용동의서", "개인정보수집ㆍ이용", "개인정보수집및이용동의서"), priority=75),
    Fingerprint("id_card_bankbook", all_of=("신분증", "통장"), priority=60),
    Fingerprint("enrollment_cert", any_of=("재학증명서",), priority=55),
)

# 파일명 키워드 — 스캔본이라 텍스트가 없을 때 쓴다.
# 예: `근무일지_강옥일(확인).pdf` 는 전면 손글씨라 지문이 하나도 안 잡힌다.
FILENAME_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("지급내역", "payment_roster"),
    ("출장신청서", "trip_request"),
    ("출장증빙", "trip_evidence"),
    ("하이패스", "receipt_tollgate"),
    ("영수증", "receipt_card"),
    ("체류", "receipt_card"),
    ("근무상황부", "worklog"),
    ("근무일지", "worklog_handwrite"),
    ("운영활동", "worklog_handwrite"),
    ("청구서", "claim_form"),
    ("활동보고서", "club_report"),
    ("활동 결과 보고서", "monthly_report"),
    ("결과보고서", "monthly_report"),
    ("혁신인재", "innovation_application"),
    ("기본정보", "privacy_consent"),
    ("기본서류", "ta_recommendation"),
    ("재학증명", "enrollment_cert"),
    ("강연정보", "purpose_evidence"),
)


# 서식 끝의 '붙임' 목록은 다른 서류 이름을 전부 나열한다. 그대로 두면 청구서가
# 근무상황부로, 활동보고서가 청구서로 잡힌다. 지문 검사 전에 잘라낸다.
# 다만 '[붙임1] 개인정보 수집·이용 동의서' 처럼 대괄호가 붙은 것은 서식 제목이므로 남긴다.
_ATTACHMENT_LIST_RE = re.compile(r"(?<!\[)붙임(?!\s*\d*\s*\])")


def strip_attachment_list(flat_text: str) -> str:
    match = _ATTACHMENT_LIST_RE.search(flat_text)
    return flat_text[: match.start()] if match else flat_text


def classify_page(text: str) -> str | None:
    """페이지 텍스트 하나를 서류 종류로 판정한다."""
    flat = strip_attachment_list(flatten(text))
    if not flat:
        return None
    matched = [fp for fp in FINGERPRINTS if fp.matches(flat)]
    if not matched:
        return None
    return max(matched, key=lambda fp: fp.priority).doc_type


def classify_by_filename(path: Path) -> str | None:
    """파일명으로 판정한다. 스캔본이라 텍스트가 없을 때 쓴다.

    상위 폴더명도 함께 본다. `이성재/현지영수증/260703.png` 처럼 파일명은
    날짜뿐이고 폴더명이 서류 종류를 말해 주는 경우가 있다.
    """
    candidates = [flatten(path.stem), flatten(path.parent.name)]
    for name in candidates:
        for keyword, doc_type in FILENAME_KEYWORDS:
            if flatten(keyword) in name:
                return doc_type
    return None


def classify(document: Document) -> Document:
    """Document 에 doc_type / contains 를 채워 돌려준다."""
    page_types: list[str | None] = [classify_page(page) for page in document.pages]
    document.page_types = page_types
    contains = {t for t in page_types if t}

    if contains:
        # 대표 종류는 페이지를 가장 많이 차지한 것. 동수면 지문 우선순위로 가른다
        # (한 파일에 양식1~4 가 한 장씩 든 'TA 기본서류' 같은 경우).
        priority = {fp.doc_type: fp.priority for fp in FINGERPRINTS}
        document.doc_type = max(
            contains, key=lambda t: (page_types.count(t), priority.get(t, 0))
        )
    else:
        by_name = classify_by_filename(document.path)
        if by_name:
            document.doc_type = by_name
            contains = {by_name}
            document.notes.append(
                "본문에서 서류 종류를 찾지 못해 파일명으로 판정했습니다. 확인이 필요합니다."
            )
        else:
            document.notes.append("서류 종류를 판정하지 못했습니다. 직접 선택해 주세요.")

    document.contains = contains
    document.doc_label = DOC_LABELS.get(document.doc_type or "", "미분류")
    return document


def load_and_classify(path: Path) -> Document:
    from .pdfio import load_document

    return classify(load_document(path))
