"""근로장학금 서류 추출 — 근무상황부, 청구서, 활동보고서, TA 추천서."""
from __future__ import annotations

import re

from .. import normalize as nz
from ..models import CONFIDENCE, Document, Value
from ..pdfio import flatten

# ── 근무상황부 (양식5 / 붙임1) ────────────────────────────────────────────

# 근로일자 한 행: 26/03/9 월 09:00 14:00 5
# 시간 뒤에 바로 다음 행의 날짜가 붙어 나오므로(예: '...12:003' + '26/05/6'),
# 시간 숫자는 뒤따르는 내용으로 경계를 잡아야 한다. 그냥 \d+ 로 두면 '32' 를 먹는다.
_WORKLOG_ROW_RE = re.compile(
    r"(?P<date>\d{2}/\d{1,2}/\d{1,2})"
    r"(?P<weekday>[월화수목금토일])"
    r"(?P<start>\d{1,2}:\d{2})"
    r"(?P<end>\d{1,2}:\d{2})"
    r"(?P<hours>\d{1,4}(?:\.\d)?)"
    r"(?=\d{2}/\d{1,2}/\d{1,2}|총|위의|[가-힣]|$)"
)
_PERIOD_RE = re.compile(r"근로기간(.+?)근로학생")
_RANGE_RE = re.compile(r"(.+?)~(.+)")


def extract_worklog(document: Document) -> None:
    flat = flatten(document.text)
    if not flat:
        return

    _capture(document, "program", flat, r"프로그램/역할(.+?)근로기간")
    _capture(document, "name", flat, r"이름([가-힣]{2,4}?)(?=은행|학과|학번|생년|주민|연락처)")
    _capture(document, "bank", flat, r"은행([가-힣]+(?:은행|뱅크))", cast=nz.bank_alias)
    _capture(document, "department", flat, r"학과([가-힣]+학과)")
    _capture(document, "account_no", flat, r"계좌번호([\d\-]+)", cast=nz.digits_only)
    _capture(document, "student_id", flat, r"학번(20\d{7})")
    _capture(document, "approver", flat, r"확인자\(교수,담당자\)\s*:?\s*([가-힣]{2,4}?)(?=서명|신청인|날인|$)")
    _capture(document, "applicant", flat, r"신청인\(근로장학생\)\s*:?\s*([가-힣]{2,4}?)(?=서명|날인|데이터|$)")
    _capture(document, "total_hours", flat, r"총근로시간(\d{1,4}(?:\.\d)?)", cast=nz.hours)

    if (match := _PERIOD_RE.search(flat)) and (span := _RANGE_RE.search(match.group(1))):
        start, end = nz.parse_date(span.group(1)), nz.parse_date(span.group(2))
        if start and end:
            document.fields["period"] = Value(
                (start, end), CONFIDENCE["pdf_text"], document.source(1), match.group(1)
            )

    rows = _parse_worklog_rows(flat)
    if rows:
        document.fields["rows"] = Value(rows, CONFIDENCE["pdf_text"], document.source(1))

    # 서명 아래의 작성일 (예: '2026.  05.   31.')
    if (match := re.search(r"청구합니다\.?\s*(\d{4}\.\s*\d{1,2}\.\s*\d{1,2})", flat)):
        document.fields["submitted_at"] = Value(
            nz.parse_date(match.group(1)), CONFIDENCE["pdf_text"], document.source(1), match.group(1)
        )


def _parse_worklog_rows(flat: str) -> list[dict]:
    rows: list[dict] = []
    matches = list(_WORKLOG_ROW_RE.finditer(flat))
    for index, match in enumerate(matches):
        # 행 사이의 글자는 근로상세내역이다. 마지막 행은 '총 근로시간' 앞까지.
        tail_start = match.end()
        tail_end = matches[index + 1].start() if index + 1 < len(matches) else flat.find("총근로시간", tail_start)
        detail = flat[tail_start: tail_end if tail_end > 0 else tail_start].strip()

        stated = nz.hours(match.group("hours"))
        rows.append({
            "date": nz.parse_date(match.group("date")),
            "weekday": match.group("weekday"),
            "start": match.group("start"),
            "end": match.group("end"),
            "hours": stated,
            "computed_hours": nz.hours_between(match.group("start"), match.group("end")),
            "detail": detail,
        })
    return rows


def extract_worklog_handwrite(document: Document) -> None:
    """손글씨 근무일지. 텍스트 레이어가 없어 4단계(Vision)에서 채운다.

    지금은 '판독 불가' 라는 사실만 기록한다. 규칙 엔진이 이 신뢰도를 보고
    관련 규칙을 REVIEW 로 강등한다.
    """
    if not flatten(document.text):
        document.fields["rows"] = Value(None, CONFIDENCE["missing"], document.source(1))
        document.fields["total_hours"] = Value(None, CONFIDENCE["missing"], document.source(1))
        document.notes.append(
            "손글씨 근무일지입니다. 자동 판독은 Vision 단계에서 지원하며, 지금은 직접 확인이 필요합니다."
        )


# ── 장학금 지급 청구서 ────────────────────────────────────────────────────

def extract_claim_form(document: Document) -> None:
    flat = flatten(document.text)
    if not flat:
        return

    # 서식이 '청구금액 원300,000' 처럼 단위를 숫자 앞에 찍는다.
    _capture(document, "amount", flat, r"청구금액[^\d]{0,4}([\d,]+)", cast=nz.money)
    _capture(document, "program_name", flat, r"프로그램명(.+?)활동내용")
    # 청구서의 성명은 앞뒤에 믿을 만한 라벨이 없다. 잘못 뽑으면 교차대사(R-CMN-003)에서
    # 오탐이 되므로 비워 둔다 — 다른 서류에서 얻은 성명으로 대사한다.

    if (match := re.search(r"활동기간[^\d]*(\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\.?\s*~\s*\d{1,2}\.\s*\d{1,2}\.)", flat)):
        document.fields["period"] = Value(
            _parse_short_range(match.group(1)), CONFIDENCE["pdf_text"], document.source(1), match.group(1)
        )


def _parse_short_range(text: str) -> tuple | None:
    """'2026. 4. 7. ~ 4. 30.' 처럼 끝 날짜에 연도가 없는 표기를 처리한다."""
    left, _, right = text.partition("~")
    start = nz.parse_date(left)
    if start is None:
        return None
    end = nz.parse_date(right)
    if end is None:
        numbers = re.findall(r"\d{1,2}", right)
        if len(numbers) >= 2:
            end = nz.parse_date(f"{start.year}.{numbers[0]}.{numbers[1]}")
    return (start, end) if end else None


# ── 월간 활동 결과 보고서 (서포터즈) ──────────────────────────────────────

def extract_monthly_report(document: Document) -> None:
    flat = flatten(document.text)
    if not flat:
        return

    _capture(document, "name", flat, r"성명([가-힣]{2,4}?)(?=학과|전공|연락처|소속)")
    _capture(document, "hours", flat, r"(\d{1,3})\s*H", cast=nz.hours)

    if (match := re.search(r"(\d{1,2})\s*/\s*(\d{1,2})\s*~\s*(\d{1,2})\s*/\s*(\d{1,2})", flat)):
        document.fields["activity_span"] = Value(
            match.group(0), CONFIDENCE["pdf_text"], document.source(1)
        )

    # 활동사진은 서식상 '활동 사진[N]' 자리표시자로 들어간다.
    photos = re.findall(r"활동사진\[?\s*(\d+)\s*\]?", flat)
    document.fields["photo_slots"] = Value(len(photos), CONFIDENCE["pdf_text"], document.source(1))


# ── [양식1] TA 추천 및 서약서 ─────────────────────────────────────────────

def extract_ta_recommendation(document: Document) -> None:
    flat = flatten(document.text)
    if not flat:
        return

    _capture(document, "course", flat, r"과목명(.+?)담당교수")
    _capture(document, "professor", flat, r"담당교수([가-힣]{2,4}?)(?=운영일|첫수업|$)")
    _capture(document, "name", flat, r"이름([가-힣]{2,4}?)(?=은행|학과|학번|생년|주민|연락처)")
    _capture(document, "credit", flat, r"학점/구분(.+?)TA정보")

    if (match := re.search(r"첫수업일\(\s*([\d.]+)\s*\)~종강일\(\s*([\d.]+)\s*\)", flat)):
        year = re.search(r"(20\d{2})", flat)
        prefix = year.group(1) if year else "2026"
        start = nz.parse_date(f"{prefix}.{match.group(1)}")
        end = nz.parse_date(f"{prefix}.{match.group(2)}")
        if start and end:
            document.fields["operating_period"] = Value(
                (start, end), CONFIDENCE["pdf_text"], document.source(1), match.group(0)
            )


# ── 공용 ──────────────────────────────────────────────────────────────────

def _capture(document: Document, name: str, text: str, pattern: str, cast=None) -> None:
    match = re.search(pattern, text)
    if not match:
        return
    raw = match.group(1)
    value = cast(raw) if cast else raw.strip()
    document.fields[name] = Value(value, CONFIDENCE["pdf_text"], document.source(1), raw)
