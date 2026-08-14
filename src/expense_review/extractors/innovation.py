"""혁신인재지원금 서류 추출 — [양식8] 신청서, [양식7-1] 월별 활동 결과 보고서."""
from __future__ import annotations

import re

from .. import normalize as nz
from ..models import CONFIDENCE, Document, Value
from ..pdfio import flatten
from ..tables import extract_words, row_texts

ACTIVITY_FIELDS = ("사이버보안", "개인정보보호", "클라우드", "블록체인")
CHECK_MARKS = "√✓✔V∨"


# ── [양식8] 혁신인재지원금 신청서 ─────────────────────────────────────────

def extract_application(document: Document) -> None:
    flat = flatten(document.text)
    if not flat:
        return

    # '소학회명지도교수활동분야' 다음에 세 값이 붙어 나온다: 'AIMPACT강경필클라우드'
    # 활동분야는 어휘가 정해져 있어 뒤에서부터 끊어 낼 수 있다.
    pattern = r"소학회명지도교수활동분야(?P<club>.+?)(?P<advisor>[가-힣]{2,4})(?P<field>%s)" % "|".join(ACTIVITY_FIELDS)
    if (match := re.search(pattern, flat)):
        _put(document, "club_name", match.group("club"))
        _put(document, "advisor", match.group("advisor"))
        _put(document, "activity_field", match.group("field"))

    _capture(document, "topic", flat, r"활동주제(.+?)신청자정보")
    # 라벨 뒤에 붙은 숫자를 그대로 믿으면 안 된다. 표가 평문으로 눌리면
    # '주민등록번호' 다음에 옆 칸의 학번이 따라붙어 202312559 를 주민번호로 읽고
    # '13자리로 기재하라'는 엉뚱한 요청이 나간다. 자릿수가 맞을 때만 받는다.
    _capture(document, "rrn", flat, r"주민등록번호(\d{6}\s*-\s*\d{7})", cast=nz.digits_only)
    _capture(document, "account_no", flat, r"계좌번호(\d[\d\-]*)", cast=nz.digits_only)
    _capture(document, "bank", flat, r"은행([가-힣]+(?:은행|뱅크))", cast=nz.bank_alias)

    # 이름/학과/학번은 표 좌표로 읽는다. 평문에서는 '김예린컴퓨터공학과' 가 한 덩어리로
    # 붙어 나와 어디서 끊어야 할지 알 수 없다.
    if (row := _row_after(document, ("이름", "학과", "학번"))):
        for cell in row:
            if re.fullmatch(r"20\d{7}", cell):
                _put(document, "student_id", cell)
            elif cell.endswith(("학과", "학부")):
                _put(document, "department", cell)
            elif re.fullmatch(r"[가-힣]{2,4}", cell):
                _put(document, "applicant", cell)

    if (match := re.search(r"지원금액([\d,]+)원\s*\((금[가-힣]+정)\)", flat)):
        _put(document, "amount", nz.money(match.group(1)), match.group(1))
        _put(document, "amount_hangul", match.group(2))

    if (match := re.search(r"(\d{4}\.\d{1,2}\.\d{1,2})\s*신청자\s*:?\s*([가-힣]{2,4})", flat)):
        _put(document, "submitted_at", nz.parse_date(match.group(1)), match.group(1))
        _put(document, "applicant", match.group(2))

    # 개인정보 수집·이용 동의 (신청서 본문의 단일 항목)
    if "동의함" in flat:
        agreed = bool(re.search(r"[■☑√✓]\s*동의함", flat))
        _put(document, "consent_agreed", agreed)

    checked = re.findall(r"[■☑√✓]\s*([^\s□■]{4,30}?)(?=\s*[□■]|$)", document.text)
    if checked:
        _put(document, "attachments_checked", checked)


# ── [양식7-1] 월별 활동 결과 보고서 ───────────────────────────────────────

_MEMBER_ROLES = ("회장", "팀원")
# '5월 18일' 형태. '5원 4일' 같은 오탈자도 잡아 R-INN-020 에서 따로 보고한다.
_ACTIVITY_DATE_RE = re.compile(r"(\d{1,2})\s*([월원])\s*(\d{1,2})\s*일")


def extract_club_report(document: Document) -> None:
    flat = flatten(document.text)
    if not flat:
        return

    _capture(document, "club_name", flat, r"소학회명(.+?)지도교수")
    _capture(document, "advisor", flat, r"지도교수([가-힣]{2,4}?)(?=활동|소학회|$)")
    _capture(document, "president", flat, r"작성자\(소학회회장\)([가-힣]{2,4}?)(?=\(|데이터|$)")
    _capture(document, "topic", flat, r"활동주제(.+?)(?:성과및결과|$)")
    _capture(document, "submitted_at", flat, r"(\d{4}\.\d{1,2}\.\d{1,2})\.?작성자", cast=nz.parse_date)

    if (match := re.search(r"\(\s*(\d{1,2})\s*\)\s*월", flat)):
        _put(document, "month", int(match.group(1)), match.group(1))

    members = _extract_members(document)
    if members:
        document.fields["members"] = Value(members, CONFIDENCE["pdf_table"], document.source(1))
        for member in members:
            if member["role"] == "회장":
                _put(document, "president", member["name"])
                break

    _put(document, "page_count", len(document.pages))
    _extract_checked_field(document)
    _extract_activity_dates(document, flat)


def _row_after(document: Document, header: tuple[str, ...]) -> list[str] | None:
    """헤더 행 바로 다음 행을 돌려준다."""
    rows = row_texts(document.path, 0)
    for index, row in enumerate(rows[:-1]):
        if all(label in row for label in header):
            return rows[index + 1]
    return None


def _extract_members(document: Document) -> list[dict]:
    """팀원 명단을 표 좌표로 읽는다.

    평문에서는 '김예린컴퓨터공학과' 가 붙어 나와 이름과 학과의 경계를 알 수 없다.
    표에서는 셀이 나뉘어 있으므로 그대로 읽으면 된다.
    """
    members: list[dict] = []
    for page_index in range(max(len(document.pages), 1)):
        for row in row_texts(document.path, page_index):
            if not row or row[0] not in _MEMBER_ROLES:
                continue
            member = {"role": row[0], "name": None, "department": None,
                      "student_id": None, "phone": None}
            for cell in row[1:]:
                if re.fullmatch(r"01[016789][-\s]?\d{3,4}[-\s]?\d{4}", cell):
                    member["phone"] = cell
                elif re.fullmatch(r"\d{7,10}", cell):
                    member["student_id"] = cell
                elif cell.endswith(("학과", "학부")):
                    member["department"] = cell
                elif re.fullmatch(r"[가-힣]{2,4}", cell):
                    member["name"] = member["name"] or cell
            if member["name"]:
                members.append(member)
    return members


def _extract_checked_field(document: Document) -> None:
    """활동분야 체크(√)가 어느 항목 위에 찍혔는지 좌표로 판정한다.

    텍스트만 뽑으면 '사이버보안개인정보보호클라우드블록체인√' 처럼 √ 가 맨 뒤로
    밀려 나와, 어느 항목이 선택됐는지 알 수 없다.
    """
    words = extract_words(document.path, 0)
    if not words:
        return

    labels = {w.text: w for w in words if w.text in ACTIVITY_FIELDS}
    marks = [w for w in words if any(c in w.text for c in CHECK_MARKS)]
    if not labels or not marks:
        return

    mark = marks[0]
    mark_center = (mark.x0 + mark.x1) / 2
    nearest = min(labels.values(), key=lambda w: abs((w.x0 + w.x1) / 2 - mark_center))
    distance = abs((nearest.x0 + nearest.x1) / 2 - mark_center)

    # 체크가 어느 항목에도 가깝지 않으면 판정하지 않는다 — REVIEW 로 넘긴다.
    if distance > 60:
        document.notes.append("활동분야 체크 위치를 특정하지 못했습니다. 직접 확인해 주세요.")
        return
    document.fields["field_checked"] = Value(
        nearest.text, CONFIDENCE["pdf_table"], document.source(1)
    )


def _extract_activity_dates(document: Document, flat: str) -> None:
    """본문 자유서술에서 활동 일자를 뽑는다. '5월 18일 정기 성과공유회' → 05-18"""
    month = document.fields.get("month")
    year = 2026
    if (match := re.search(r"(20\d{2})", flat)):
        year = int(match.group(1))

    dates, typos = [], []
    for match in _ACTIVITY_DATE_RE.finditer(flat):
        month_number, unit, day = int(match.group(1)), match.group(2), int(match.group(3))
        if unit == "원":  # '5원 4일' — 월/원 오타
            typos.append(match.group(0))
        try:
            import datetime as dt

            dates.append(dt.date(year, month_number, day))
        except ValueError:
            continue

    if month is not None and month.is_present:
        dates = [d for d in dates if d.month == month.value]

    if dates:
        document.fields["activity_dates"] = Value(
            sorted(set(dates)), CONFIDENCE["pdf_text"], document.source(1)
        )
    if typos:
        document.fields["text_anomalies"] = Value(typos, CONFIDENCE["pdf_text"], document.source(1))


# ── 공용 ──────────────────────────────────────────────────────────────────

def _put(document: Document, name: str, value, raw: str | None = None) -> None:
    document.fields[name] = Value(
        value,
        CONFIDENCE["pdf_text"] if value is not None else CONFIDENCE["missing"],
        document.source(1),
        raw,
    )


def _capture(document: Document, name: str, text: str, pattern: str, cast=None) -> None:
    match = re.search(pattern, text)
    if not match:
        return
    raw = match.group(1)
    _put(document, name, cast(raw) if cast else raw.strip(), raw)
