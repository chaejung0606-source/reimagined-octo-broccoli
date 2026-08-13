"""공통 필드 추출 — 인적사항, 지급내역, 개인정보 동의서."""
from __future__ import annotations

import re

from .. import normalize as nz
from ..models import CONFIDENCE, Document, Value
from ..pdfio import flatten
from ..tables import row_texts

# ── 인적사항 ──────────────────────────────────────────────────────────────

# \b 는 쓰지 않는다. 한글과 숫자는 둘 다 \w 라서 '학번202630395' 사이에
# 단어 경계가 생기지 않아 매칭이 통째로 실패한다. 숫자 전후만 직접 막는다.
_NO_DIGIT_AROUND = r"(?<!\d){}(?!\d)"

_STUDENT_ID_RE = re.compile(_NO_DIGIT_AROUND.format(r"(20\d{7})"))
_RRN_RE = re.compile(_NO_DIGIT_AROUND.format(r"(\d{6}-\d{7})"))
_PHONE_RE = re.compile(_NO_DIGIT_AROUND.format(r"(01[016789][-\s]?\d{3,4}[-\s]?\d{4})"))
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# 학과는 반드시 라벨 뒤에서만 읽는다. 라벨 없이 '...학과' 를 찾으면 평문에서
# 'COSS성명강옥일학과' 같은 쓰레기를 집어 온다. 잘못된 값보다 빈 값이 낫다.
_DEPARTMENT_RE = re.compile(r"(?:소속학과|학과|전공|소속)([가-힣]{2,8}(?:학과|학부))")

# 계좌번호도 라벨을 우선한다. 라벨이 없으면 하이픈 표기만 받는다.
# 라벨 없는 11~16자리 숫자를 허용하면 전화번호(01091558149)를 계좌로 읽는다.
_ACCOUNT_LABELED_RE = re.compile(r"계좌(?:번호)?\s*[:：]?\s*(\d[\d\-]{8,20})")
# 전화번호·팩스번호 뒤의 숫자를 계좌로 읽지 않도록 앞 라벨을 막는다.
_TEL_LABEL_RE = re.compile(r"(?:전화번호|팩스번호|TEL|연락처)\s*[:：]?\s*$")
# 전화번호(010-9155-8149)도 이 모양이라 앞에서 막는다.
_ACCOUNT_HYPHEN_RE = re.compile(
    _NO_DIGIT_AROUND.format(r"(?!01[016789]-)(\d{2,6}-\d{2,6}-\d{2,7}|\d{2,4}-\d{4}-\d{4}-\d{2})")
)
# 지급내역 표의 계좌 셀. 이미 셀 단위로 잘려 있어 느슨하게 봐도 된다.
_ROSTER_ACCOUNT_RE = re.compile(r"(?!01[016789][-\d])\d[\d\-]{9,}")
_BANK_NAMES = ("국민|신한|농협|우리|하나|기업|카카오|토스|케이|새마을|수협|우체국"
               "|씨티|부산|대구|경남|광주|전북|제주|산업")
_BANK_RE = re.compile(rf"({_BANK_NAMES})(?:은행|뱅크)?")
# 라벨 없이 은행명을 찾으면 '기업데이터경진대회' 에서 '기업은행' 을 만들어 낸다.
# 교차대사(R-CMN-006)에서 곧바로 오탐이 되므로 '은행' 라벨 뒤에서만 읽는다.
_BANK_LABELED_RE = re.compile(rf"은행\s*[:：]?\s*(({_BANK_NAMES})(?:은행|뱅크)?)")


def _set(document: Document, name: str, value, raw: str | None = None,
         confidence: float = CONFIDENCE["pdf_text"], page: int | None = None) -> None:
    """이미 채워진 필드는 덮어쓰지 않는다 — 전용 추출기의 값이 우선이다."""
    existing = document.fields.get(name)
    if existing is not None and existing.is_present:
        return
    document.fields[name] = Value(
        value=value, confidence=confidence if value is not None else CONFIDENCE["missing"],
        source=document.source(page), raw=raw,
    )


# 지급내역은 여러 사람이 한 표에 들어 있다. 개인 인적사항을 뽑으면
# 첫 줄 사람의 값이 문서 전체의 값처럼 굳어 교차대사에서 오탐이 된다.
MULTI_PERSON_TYPES = {"payment_roster"}

# 출장 서류에는 신청인의 은행 계좌가 없다. 그대로 두면 승인번호(H673-7301-04539)나
# 전화번호를 계좌로 읽어 교차대사에서 오탐이 된다.
NO_ACCOUNT_TYPES = {"trip_request", "trip_evidence", "receipt_tollgate", "receipt_card", "purpose_evidence"}


def extract_person(document: Document) -> None:
    """어느 서류에서든 뽑을 수 있는 인적사항. 교차 대사(L2)의 입력이 된다."""
    text = document.text
    if not text.strip() or (document.contains & MULTI_PERSON_TYPES):
        return
    flat = flatten(text)

    if (match := _STUDENT_ID_RE.search(flat)):
        _set(document, "student_id", match.group(1), match.group(1))
    if (match := _RRN_RE.search(flat)):
        _set(document, "rrn", nz.digits_only(match.group(1)), match.group(1))
    if (match := _PHONE_RE.search(text)):
        _set(document, "phone", nz.digits_only(match.group(1)), match.group(1))
    if (match := _EMAIL_RE.search(text)):
        _set(document, "email", match.group(0).lower(), match.group(0))
    if (match := _DEPARTMENT_RE.search(flat)):
        _set(document, "department", match.group(1), match.group(1))
    if (match := _BANK_LABELED_RE.search(flat)):
        _set(document, "bank", nz.bank_alias(match.group(1)), match.group(1))
    if document.contains & NO_ACCOUNT_TYPES:
        return
    if (match := _ACCOUNT_LABELED_RE.search(flat)):
        _set(document, "account_no", nz.digits_only(match.group(1)), match.group(1))
    else:
        for match in _ACCOUNT_HYPHEN_RE.finditer(flat):
            if _TEL_LABEL_RE.search(flat[:match.start()]):
                continue
            _set(document, "account_no", nz.digits_only(match.group(1)), match.group(1))
            break


# ── 지급내역 ──────────────────────────────────────────────────────────────

_ROSTER_MONEY_RE = re.compile(r"^[\d,]+$")


def extract_roster(document: Document) -> None:
    """지급내역 표를 사람별 행으로 재조립한다.

    한 사람이 여러 강좌를 맡으면 이름·학번이 병합셀이라 한 행에만 나온다.
    계좌번호가 같은 행끼리 묶어 이름을 채운다.
    """
    rows: list[dict] = []
    for page_index in range(max(len(document.pages), 1)):
        for cells in row_texts(document.path, page_index):
            parsed = _parse_roster_row(cells)
            if parsed:
                parsed["page"] = page_index + 1
                rows.append(parsed)

    if not rows:
        return

    # 계좌번호로 같은 사람의 행을 묶어 이름·학번을 채운다.
    by_account: dict[str, dict] = {}
    for row in rows:
        key = row.get("account_no") or ""
        holder = by_account.setdefault(key, {})
        for field_name in ("name", "student_id", "club_name"):
            if row.get(field_name) and not holder.get(field_name):
                holder[field_name] = row[field_name]
    for row in rows:
        holder = by_account.get(row.get("account_no") or "", {})
        for field_name in ("name", "student_id", "club_name"):
            row.setdefault(field_name, None)
            if not row[field_name]:
                row[field_name] = holder.get(field_name)

    document.fields["rows"] = Value(rows, CONFIDENCE["pdf_table"], document.source(1))


def _parse_roster_row(cells: list[str]) -> dict | None:
    """지급내역 한 행. 형식이 유형마다 달라 위치가 아니라 값 모양으로 판별한다."""
    if len(cells) < 4 or not cells[0].isdigit():
        return None

    row: dict = {"seq": int(cells[0])}
    money_values: list[int] = []

    for cell in cells[1:]:
        if _STUDENT_ID_RE.fullmatch(cell):
            row["student_id"] = cell
        elif cell.endswith("시간"):
            row["hours"] = nz.hours(cell)
        elif cell.endswith("원"):
            row["unit_price"] = nz.money(cell)
        elif _ROSTER_ACCOUNT_RE.fullmatch(cell):
            row["account_no"] = nz.digits_only(cell)
        elif _BANK_RE.fullmatch(cell) or cell.endswith(("은행", "뱅크")):
            row["bank"] = nz.bank_alias(cell)
        elif _ROSTER_MONEY_RE.fullmatch(cell) and "," in cell:
            money_values.append(nz.money(cell))
        elif re.fullmatch(r"[가-힣]{2,4}", cell):
            row.setdefault("name", cell)
        elif cell.strip():
            # 남는 문자열은 강좌명(근로장학금) 또는 소학회명(혁신인재지원금)
            row.setdefault("course_name", cell)
            row.setdefault("club_name", cell)

    if money_values:
        row["amount"] = money_values[-1]
    if "account_no" not in row and "amount" not in row:
        return None
    return row


# ── 개인정보 동의서 ───────────────────────────────────────────────────────

# '동의함 ■  동의안함 □' 처럼 체크박스가 채워진 쪽에 ■ 가 온다.
_CONSENT_RE = re.compile(r"동의함(?P<agree>[■□☑☐V√v])?\s*동의안함(?P<deny>[■□☑☐V√v])?")
_CONSENT_LABELS = ("기본 개인정보", "고유식별정보", "제3자 제공")


def extract_privacy_consent(document: Document) -> None:
    flat = flatten(document.text)
    marks = _CONSENT_RE.findall(flat)
    if not marks:
        return

    results = []
    for index, (agree, deny) in enumerate(marks):
        label = _CONSENT_LABELS[index] if index < len(_CONSENT_LABELS) else f"항목{index + 1}"
        agreed = agree in {"■", "☑", "V", "√", "v"}
        results.append({"label": label, "agreed": agreed})

    document.fields["consents"] = Value(results, CONFIDENCE["pdf_text"], document.source(1))

    if (match := re.search(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일", flat)):
        date = nz.parse_date(f"{match.group(1)}.{match.group(2)}.{match.group(3)}")
        _set(document, "signed_at", date, match.group(0))
