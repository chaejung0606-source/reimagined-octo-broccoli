"""문서 자동 분류 — docs/04-architecture.md §2.

파일명은 자유롭게 붙기 때문에 파일명만으로는 부족하다. 3단계로 판정한다.

    1차  파일명 키워드      "근무상황부" / "출장신청서" / "지급내역" …
    2차  페이지 텍스트 지문  "[양식5]" / "국내 출장신청서" / "* 체류 증빙" …
    3차  둘 다 실패 → unknown 으로 남기고 사용자에게 물어본다

한 PDF 가 여러 서류를 담는 경우가 있어(TA 기본서류 = 양식1~4 한 파일) 페이지 단위로
판정한 뒤 연속 구간을 묶는다.

**주의:** 서류 끝의 `붙임` 목록에는 다른 서류 이름이 전부 나열되어 있어서, 그대로
지문을 매칭하면 서류들이 서로 교차 오분류된다. 지문 매칭 전에 붙임 목록을 잘라낸다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field
from pathlib import Path

from .models import Document, Page
from .pdfio import load_document_pages
from .normalize import strip_spaces

#: 이 아래로 떨어지면 사용자 확인이 필요한 것으로 본다.
CONFIDENT = 0.60

#: 페이지에 이만큼도 글자가 없으면 스캔본으로 본다(손글씨 근무일지 등).
SPARSE_TEXT_CHARS = 40


@dataclass(frozen=True)
class DocType:
    """분류 대상 서류 한 종류."""

    key: str
    label: str
    filename: tuple[str, ...] = ()          # 파일명 키워드
    fingerprints: tuple[str, ...] = ()      # 본문 지문
    strong: tuple[str, ...] = ()            # 이것 하나만 맞아도 확정에 가까운 지문
    negative: tuple[str, ...] = ()          # 있으면 감점 (다른 서류와 헷갈릴 때)
    expense_types: frozenset[str] = frozenset()
    subtypes: frozenset[str] = frozenset()  # 비면 모든 하위유형
    page_scoped: bool = True                # 한 파일 안에서 페이지별로 나뉠 수 있는가
    scanned: bool = False                   # 텍스트 레이어가 없는 것이 정상인 서류


# ------------------------------------------------------------------ 공통 서류

_PAYMENT_ROSTER = DocType(
    key="payment_roster",
    label="지급내역",
    filename=("지급내역", "지급 내역", "지급명세"),
    fingerprints=("지급내역", "연번", "합 계", "합계", "지급액"),
    strong=("지급내역",),
    expense_types=frozenset({"근로장학금", "혁신인재지원금"}),
    page_scoped=False,
)

_PRIVACY_CONSENT_FINGERPRINTS = (
    "개인정보 수집",
    "개인정보수집",
    "이용 동의서",
    "고유식별정보",
    "제3자 제공",
    "동의함",
)

_ENROLLMENT_FINGERPRINTS = ("재학증명서", "재 학 증 명 서", "위와 같이 재학하고 있음")
_ID_BANKBOOK_FINGERPRINTS = ("신분증", "통장 사본", "통장사본", "예금주", "계좌번호")


# --------------------------------------------------------------- 근로장학금

_SCHOLARSHIP_TYPES: tuple[DocType, ...] = (
    DocType(
        key="form1_recommendation",
        label="[양식1] TA 추천 및 서약서",
        filename=("추천", "서약", "기본서류", "TA 기본"),
        fingerprints=("추천 및 서약서", "서약서", "담당교수", "운영일", "첫 수업일"),
        strong=("[양식1]", "추천 및 서약서"),
        expense_types=frozenset({"근로장학금"}),
        subtypes=frozenset({"TA"}),
    ),
    DocType(
        key="form2_privacy_consent",
        label="[양식2] 개인정보 수집·이용 동의서",
        filename=("개인정보", "동의서"),
        fingerprints=_PRIVACY_CONSENT_FINGERPRINTS,
        strong=("[양식2]",),
        expense_types=frozenset({"근로장학금"}),
        subtypes=frozenset({"TA"}),
    ),
    DocType(
        key="form3_id_bankbook",
        label="[양식3] 신분증 및 통장 사본",
        filename=("신분증", "통장"),
        fingerprints=_ID_BANKBOOK_FINGERPRINTS,
        strong=("[양식3]",),
        expense_types=frozenset({"근로장학금"}),
        subtypes=frozenset({"TA"}),
        scanned=True,
    ),
    DocType(
        key="form4_enrollment",
        label="[양식4] 재학증명서",
        filename=("재학증명",),
        fingerprints=_ENROLLMENT_FINGERPRINTS,
        strong=("[양식4]", "재학증명서"),
        expense_types=frozenset({"근로장학금"}),
        subtypes=frozenset({"TA"}),
        scanned=True,
    ),
    DocType(
        key="form5_worklog",
        label="[양식5] 근로장학생 근무상황부",
        filename=("근무상황부",),
        fingerprints=("근로장학생 근무상황부", "근무상황부", "근로기간", "근로일자", "근로상세내역", "확인자"),
        strong=("[양식5]", "근로장학생 근무상황부"),
        expense_types=frozenset({"근로장학금"}),
        subtypes=frozenset({"TA"}),
    ),
    DocType(
        key="claim_form",
        label="장학금 지급 청구서",
        filename=("청구서", "지급 청구"),
        fingerprints=("장학금 지급 청구서", "청구금액", "활동기간", "위와 같이 청구합니다"),
        strong=("장학금 지급 청구서",),
        expense_types=frozenset({"근로장학금"}),
        subtypes=frozenset({"SUPPORTERS"}),
    ),
    DocType(
        key="monthly_report",
        label="월간 활동 결과 보고서",
        filename=("월간 활동", "활동 결과 보고서", "활동결과보고서"),
        fingerprints=("월간 활동 결과 보고서", "활동 시간", "목표 달성", "자체 평가", "개선사항"),
        strong=("월간 활동 결과 보고서",),
        expense_types=frozenset({"근로장학금"}),
        subtypes=frozenset({"SUPPORTERS"}),
    ),
    DocType(
        key="worklog_handwrite",
        label="[붙임2] 운영활동 보고서(근무일지)",
        filename=("근무일지", "운영활동"),
        fingerprints=("운영활동 보고서", "근무일지", "이용자 수", "운영 내용", "사업팀장"),
        strong=("근무일지", "운영활동 보고서"),
        expense_types=frozenset({"근로장학금"}),
        subtypes=frozenset({"SUPPORTERS"}),
        scanned=True,
    ),
    DocType(
        key="privacy_consent",
        label="[붙임1] 개인정보 수집·이용 동의서",
        filename=("개인정보", "동의서", "기본정보"),
        fingerprints=_PRIVACY_CONSENT_FINGERPRINTS,
        expense_types=frozenset({"근로장학금"}),
        subtypes=frozenset({"SUPPORTERS"}),
    ),
    DocType(
        key="id_bankbook_enrollment",
        label="[붙임2] 신분증·통장 사본, 재학증명서",
        filename=("신분증", "통장", "재학증명", "기본정보"),
        fingerprints=_ID_BANKBOOK_FINGERPRINTS + _ENROLLMENT_FINGERPRINTS,
        expense_types=frozenset({"근로장학금"}),
        subtypes=frozenset({"SUPPORTERS"}),
        scanned=True,
    ),
    _PAYMENT_ROSTER,
)


# ------------------------------------------------------------ 혁신인재지원금

_INNOVATION_TYPES: tuple[DocType, ...] = (
    DocType(
        key="form8_application",
        label="[양식8] 혁신인재지원금 신청서",
        filename=("혁신인재", "신청서"),
        fingerprints=("혁신인재지원금 신청서", "지원금액", "소학회", "지도교수", "활동분야"),
        strong=("[양식8]", "혁신인재지원금 신청서"),
        expense_types=frozenset({"혁신인재지원금"}),
    ),
    DocType(
        key="form7_1_report",
        label="[양식7-1] 월별 활동 결과 보고서",
        filename=("활동보고서", "활동 보고서", "월별 활동"),
        fingerprints=("월별 활동 결과 보고서", "회장", "팀원", "대표 성과", "향후 계획", "활동 주제"),
        strong=("[양식7-1]", "월별 활동 결과 보고서"),
        expense_types=frozenset({"혁신인재지원금"}),
    ),
    DocType(
        key="attach1_worklog",
        label="[붙임1] 근로장학생 근무상황부",
        filename=("근무상황부",),
        fingerprints=("근로장학생 근무상황부", "근무상황부", "근로기간", "근로일자", "확인자"),
        strong=("근로장학생 근무상황부",),
        expense_types=frozenset({"혁신인재지원금"}),
    ),
    DocType(
        key="id_bankbook",
        label="신분증 및 통장 사본",
        filename=("신분증", "통장", "기본정보"),
        fingerprints=_ID_BANKBOOK_FINGERPRINTS,
        expense_types=frozenset({"혁신인재지원금"}),
        scanned=True,
    ),
    DocType(
        key="enrollment_cert",
        label="재학증명서",
        filename=("재학증명",),
        fingerprints=_ENROLLMENT_FINGERPRINTS,
        strong=("재학증명서",),
        expense_types=frozenset({"혁신인재지원금"}),
        scanned=True,
    ),
    _PAYMENT_ROSTER,
)


# ------------------------------------------------------------------- 출장비

_TRAVEL_TYPES: tuple[DocType, ...] = (
    DocType(
        key="trip_request",
        label="국내 출장신청서 (전자결재본)",
        filename=("출장신청서", "출장 신청서", "국내출장"),
        fingerprints=("국내 출장신청서", "다음과 같이 출장을 명함", "실사구시",
                      "여비지급대상", "출장기간", "출장지", "결재"),
        strong=("국내 출장신청서", "다음과 같이 출장을 명함"),
        expense_types=frozenset({"출장비"}),
        page_scoped=False,
    ),
    DocType(
        key="trip_evidence",
        label="출장증빙 (교통비·이동경로·체류)",
        filename=("출장증빙", "출장 증빙", "증빙"),
        fingerprints=("교통비 증빙", "이동경로", "체류 증빙", "출발지", "도착지", "총 이동경로"),
        strong=("교통비 증빙", "총 이동경로", "체류 증빙"),
        expense_types=frozenset({"출장비"}),
        page_scoped=False,
    ),
    DocType(
        key="transport_receipts",
        label="교통비 영수증 (하이패스/주유/대중교통)",
        filename=("하이패스", "통행료", "주유", "교통", "승차권", "KTX"),
        fingerprints=("하이패스", "입구영업소", "한국도로공사", "통행료", "출구영업소",
                      "주유", "휘발유", "경유", "승차권", "열차"),
        strong=("하이패스", "입구영업소", "한국도로공사"),
        expense_types=frozenset({"출장비"}),
    ),
    DocType(
        key="stay_receipts",
        label="체류 영수증",
        filename=("체류", "영수증", "카드전표"),
        fingerprints=("승인번호", "가맹점명", "사업자등록번호", "합계금액", "부가세", "카드번호"),
        negative=("하이패스", "입구영업소", "한국도로공사"),
        expense_types=frozenset({"출장비"}),
        scanned=True,
    ),
    DocType(
        key="purpose_evidence",
        label="출장목적 근거자료 (프로그램·강연정보 등)",
        filename=("강연", "프로그램", "초청", "안내", "COSS", "아카데미"),
        fingerprints=("강연", "프로그램", "일정", "연사", "초청"),
        expense_types=frozenset({"출장비"}),
    ),
)


CATALOG: dict[str, tuple[DocType, ...]] = {
    "근로장학금": _SCHOLARSHIP_TYPES,
    "혁신인재지원금": _INNOVATION_TYPES,
    "출장비": _TRAVEL_TYPES,
}

#: 어떤 서류가 다른 필수 서류를 대신 충족시키는가.
#: 예) 체류 영수증은 출장증빙 서식의 `체류 증빙` 페이지 안에 붙어 오는 경우가 많다.
SATISFIED_BY: dict[str, tuple[str, ...]] = {
    "stay_receipts": ("trip_evidence",),
    "privacy_consent": ("id_bankbook_enrollment",),
    "id_bankbook_enrollment": ("privacy_consent",),
    "enrollment_cert": ("id_bankbook",),
    "id_bankbook": ("enrollment_cert",),
}


# ------------------------------------------------------------- 붙임 목록 제거

# `[붙임1] …` 은 서류 제목이므로 남기고, 줄 첫머리의 맨 `붙임`/`첨부` 는 목록으로 보고 자른다.
_ATTACHMENT_LIST_RE = re.compile(r"^\s*[※*ㅁ□○●]?\s*(붙\s*임|첨\s*부|첨부파일|제출\s*서류)\s*[:：]?\s*(\d|$|[가-힣])")


def strip_attachment_list(text: str) -> str:
    """지문 매칭에서 붙임 목록을 빼낸다.

    서류 끝의 `붙임 1. 개인정보 동의서 2. 재학증명서 …` 가 다른 서류의 지문을 전부
    포함해 버려서, 그대로 두면 서류들이 서로 교차 오분류된다.
    """
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if _ATTACHMENT_LIST_RE.match(line) and not line.lstrip().startswith("[붙임"):
            return "\n".join(lines[:index])
    return text


# -------------------------------------------------------------------- 채점

@dataclass
class Score:
    doc_type: DocType
    points: float = 0.0
    reasons: list[str] = dc_field(default_factory=list)

    def add(self, points: float, reason: str) -> None:
        self.points += points
        self.reasons.append(reason)


def _normalized(text: str) -> str:
    """지문 비교용. 표 추출 시 끼어드는 공백(`합   계`)을 없앤다."""
    return strip_spaces(text) or ""


def _candidates(expense_type: str, subtype: str | None) -> list[DocType]:
    types = CATALOG.get(expense_type, ())
    out = []
    for doc_type in types:
        if doc_type.expense_types and expense_type not in doc_type.expense_types:
            continue
        if doc_type.subtypes and subtype and subtype not in doc_type.subtypes:
            continue
        out.append(doc_type)
    return out


def score_text(doc_type: DocType, packed_text: str, packed_filename: str) -> Score:
    score = Score(doc_type)

    for keyword in doc_type.filename:
        if _normalized(keyword) in packed_filename:
            score.add(2.0, f"파일명 '{keyword}'")
            break

    for marker in doc_type.strong:
        if _normalized(marker) in packed_text:
            score.add(5.0, f"지문 '{marker}'")
            break

    hits = [f for f in doc_type.fingerprints if _normalized(f) in packed_text]
    if hits:
        # 지문이 여러 개 맞을수록 확실하지만, 흔한 단어 하나로 확정되지 않게 체감시킨다.
        score.add(min(len(hits), 4) * 1.2, "지문 " + "·".join(f"'{h}'" for h in hits[:4]))

    for marker in doc_type.negative:
        if _normalized(marker) in packed_text:
            score.add(-4.0, f"제외 지문 '{marker}'")

    return score


def classify_page(page: Page, filename: str, candidates: list[DocType]) -> tuple[Score | None, list[Score]]:
    body = strip_attachment_list(page.text)
    packed_text = _normalized(body)
    packed_filename = _normalized(filename)

    scores = [score_text(dt, packed_text, packed_filename) for dt in candidates]

    # 텍스트가 거의 없는 페이지는 스캔본이다. 스캔이 정상인 서류에 가점.
    if len(packed_text) < SPARSE_TEXT_CHARS:
        for score in scores:
            if score.doc_type.scanned:
                score.add(1.5, "텍스트 레이어 없음(스캔본)")

    scores.sort(key=lambda s: s.points, reverse=True)
    best = scores[0] if scores and scores[0].points > 0 else None
    return best, scores


def _confidence(best: Score, runner_up: Score | None) -> float:
    """1등 점수와 2등과의 격차로 신뢰도를 만든다."""
    base = min(0.99, 0.45 + best.points * 0.06)
    if runner_up is not None and runner_up.points > 0:
        gap = best.points - runner_up.points
        if gap < 1.5:
            base -= 0.20
        elif gap < 3.0:
            base -= 0.08
    return max(0.0, round(base, 2))


def classify_file(path: Path, expense_type: str, subtype: str | None = None) -> list[Document]:
    """파일 하나 → Document 목록. 한 파일에 여러 서류가 들어 있으면 나눠서 돌려준다."""
    pages, error = load_document_pages(path)
    return classify_pages(path, pages, expense_type, subtype, error)


def classify_pages(path: Path, pages: list[Page], expense_type: str,
                   subtype: str | None = None, error: str = "") -> list[Document]:
    """이미 읽어 둔 페이지를 분류한다. 테스트와 재분류에서 파일을 다시 읽지 않게 한다."""
    candidates = _candidates(expense_type, subtype)

    if not pages:
        # 열지 못했거나 이미지 파일. 파일명만으로 판정한다.
        packed_filename = _normalized(path.name)
        scores = sorted(
            (score_text(dt, "", packed_filename) for dt in candidates),
            key=lambda s: s.points,
            reverse=True,
        )
        best = scores[0] if scores and scores[0].points > 0 else None
        doc = Document(file=path, pages=[], read_error=error)
        if best:
            doc.kind = best.doc_type.key
            doc.label = best.doc_type.label
            doc.kind_confidence = min(_confidence(best, scores[1] if len(scores) > 1 else None), 0.6)
            doc.kind_reason = ", ".join(best.reasons)
        else:
            doc.kind = "unknown"
            doc.label = path.name
            doc.kind_reason = error or "판정 근거 없음"
        return [doc]

    per_page: list[tuple[Score | None, list[Score]]] = [
        classify_page(page, path.name, candidates) for page in pages
    ]

    # 페이지별로 나뉘지 않는 서류(출장신청서·지급내역 등)는 파일 전체를 한 서류로 본다.
    page_scoped = all(
        best is None or best.doc_type.page_scoped for best, _ in per_page
    )
    if not page_scoped or len({b.doc_type.key for b, _ in per_page if b}) <= 1:
        return [_whole_file_document(path, pages, per_page, error)]

    return _split_document(path, pages, per_page, error)


def _aggregate(per_page: list[tuple[Score | None, list[Score]]]) -> tuple[Score | None, Score | None]:
    """페이지별 점수를 서류 종류별로 합산해 1·2등을 고른다."""
    totals: dict[str, Score] = {}
    for _, scores in per_page:
        for score in scores:
            bucket = totals.setdefault(score.doc_type.key, Score(score.doc_type))
            bucket.points += score.points
            for reason in score.reasons:
                if reason not in bucket.reasons:
                    bucket.reasons.append(reason)
    ranked = sorted(totals.values(), key=lambda s: s.points, reverse=True)
    best = ranked[0] if ranked and ranked[0].points > 0 else None
    runner_up = ranked[1] if len(ranked) > 1 else None
    return best, runner_up


def _whole_file_document(path: Path, pages: list[Page],
                         per_page: list[tuple[Score | None, list[Score]]],
                         error: str) -> Document:
    best, runner_up = _aggregate(per_page)
    doc = Document(file=path, pages=pages, read_error=error)
    if best:
        doc.kind = best.doc_type.key
        doc.label = best.doc_type.label
        doc.kind_confidence = _confidence(best, runner_up)
        doc.kind_reason = ", ".join(best.reasons[:4])
    else:
        doc.kind = "unknown"
        doc.label = path.name
        doc.kind_reason = "파일명·지문 모두 일치하지 않음"
    doc.page_range = (pages[0].number, pages[-1].number) if pages else None
    return doc


def _split_document(path: Path, pages: list[Page],
                    per_page: list[tuple[Score | None, list[Score]]],
                    error: str) -> list[Document]:
    """연속된 같은 종류의 페이지를 하나의 서류로 묶는다 (TA 기본서류 = 양식1~4)."""
    documents: list[Document] = []
    current_key: str | None = None
    buffer: list[Page] = []
    buffer_scores: list[tuple[Score | None, list[Score]]] = []

    def flush() -> None:
        if not buffer:
            return
        doc = _whole_file_document(path, list(buffer), list(buffer_scores), error)
        doc.page_range = (buffer[0].number, buffer[-1].number)
        documents.append(doc)

    for page, entry in zip(pages, per_page):
        best = entry[0]
        key = best.doc_type.key if best else current_key
        if key != current_key and buffer:
            flush()
            buffer.clear()
            buffer_scores.clear()
        current_key = key
        buffer.append(page)
        buffer_scores.append(entry)
    flush()
    return documents


def classify_all(paths: list[Path], expense_type: str,
                 subtype: str | None = None) -> list[Document]:
    documents: list[Document] = []
    for path in paths:
        documents.extend(classify_file(path, expense_type, subtype))
    return documents


def needs_confirmation(documents: list[Document]) -> list[Document]:
    """사용자에게 "이 파일은 무엇인가요?" 를 물어야 하는 문서들."""
    return [doc for doc in documents
            if doc.kind == "unknown" or doc.kind_confidence < CONFIDENT]
