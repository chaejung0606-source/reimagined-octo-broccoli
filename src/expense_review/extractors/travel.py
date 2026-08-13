"""출장비 서류 추출 — 출장신청서, 출장증빙, 하이패스·카드 영수증.

출장비는 청구액이 서류에 적힌 값이 아니라 영수증에서 역산된다. 그래서
영수증의 '일시'가 가장 중요한 필드다. 출장기간 밖의 영수증을 걸러 내는 데
쓰이기 때문이다(R-TRV-009, R-TRV-011).
"""
from __future__ import annotations

import datetime as dt
import re

from .. import normalize as nz
from ..models import CONFIDENCE, Document, Value
from ..pdfio import flatten
from ..tables import extract_words

# ── 국내 출장신청서 ───────────────────────────────────────────────────────

# \b 는 한글 바로 뒤에서 경계를 만들지 못한다('강원대학교HRHFB…').
_DOC_NO_RE = re.compile(r"([A-Z]{4,8}\d{6}[A-Z]{2}\d{10,25})")
_TRIP_DT = r"\d{4}\.\d{1,2}\.\d{1,2}\.\([월화수목금토일]\)\d{1,2}:\d{2}"
_TRIP_RANGE_RE = re.compile(
    rf"(?P<start>{_TRIP_DT})(?P<middle>.*?)~(?P<end>{_TRIP_DT})"
)
_RANK_NAME_RE = re.compile(r"(?:\(프로젝트\)|중점교수|조교수|부교수|정교수|연구원|팀장)\s*([가-힣]{2,4})")
_ELIGIBLE_RE = re.compile(r"(예|아니오)$")
# 성명 열에 섞여 들어오는 서식 라벨. 사람 이름이 아니다.
_NOT_A_NAME = {
    "지급기관", "회계구분", "출장목적", "공용차량", "연구비", "대상여부", "이동사항",
    "출장비고", "추가비고", "협조자", "부서명", "성명", "직급", "소속", "출장지",
    "출장내용", "출장기간", "내부결재", "업무회의", "여비지급",
}


def extract_trip_request(document: Document) -> None:
    flat = flatten(document.text)
    if not flat:
        return

    if (match := _DOC_NO_RE.search(flat)):
        _put(document, "doc_no", match.group(1))
    _capture(document, "department", flat, r"부서명(.+?)국내출장신청서")
    _capture(document, "purpose_type", flat, r"출장목적(업무회의|공무|기타|교육|출장)")
    # '공용차량이용' 은 모든 신청서에 인쇄돼 있는 라벨이다. 텍스트만으로는 실제로
    # 선택됐는지 알 수 없으므로 판정하지 않는다 — 관련 규칙은 REVIEW 로 넘어간다.
    _put(document, "uses_official_vehicle", None)
    if "공용차량이용" in flat:
        document.notes.append("공용차량 이용 여부는 서식 라벨만으로 판정할 수 없어 확인이 필요합니다.")

    if (match := re.search(r"(\d{4}\.\d{1,2}\.\d{1,2})\.?부서명", flat)):
        _put(document, "issued_at", nz.parse_date(match.group(1)), match.group(1))

    _put(document, "approval_line", "내부결재" in flat or "결재" in flat)

    # 결재선에도 '조교수' 같은 직급이 나온다. 출장 표 영역에서만 성명을 읽어야
    # 결재자 이름을 출장자로 잘못 잡지 않는다.
    marker = flat.find("여비지급대상여부")
    table = flat[marker + len("여비지급대상여부"):] if marker >= 0 else flat

    names = _names_from_column(document) or _RANK_NAME_RE.findall(table)
    trips: list[dict] = []
    for index, match in enumerate(_TRIP_RANGE_RE.finditer(table)):
        middle = match.group("middle")
        eligible_match = _ELIGIBLE_RE.search(middle)
        trips.append({
            "name": names[index] if index < len(names) else None,
            "start": nz.parse_datetime(match.group("start")),
            "end": nz.parse_datetime(match.group("end")),
            "destination": _ELIGIBLE_RE.sub("", middle).strip(),
            "allowance_eligible": (eligible_match.group(1) == "예") if eligible_match else None,
            "purpose": _purpose_before(table, match.start(), names[index] if index < len(names) else None),
        })

    if trips:
        document.fields["trips"] = Value(trips, CONFIDENCE["pdf_text"], document.source(1))


def _names_from_column(document: Document) -> list[str]:
    """'성명' 열의 x 좌표로 출장자 이름을 읽는다.

    평문에서는 이름 뒤에 출장내용이 바로 붙어('이동재코위크아카데미강연') 어디까지가
    이름인지 알 수 없다. 표에서 열 위치를 잡으면 정확히 끊긴다.
    """
    columns = ("소속", "직급", "성명", "출장내용", "출장기간", "출장지")
    names: list[str] = []

    for page_index in range(max(len(document.pages), 1)):
        words = extract_words(document.path, page_index)
        header = {w.text: w for w in words if w.text in columns}
        if "성명" not in header or len(header) < 3:
            continue

        # 열 경계로 자르면 안 된다. 출장내용 칸의 글자가 헤더 왼쪽 끝보다 앞에서
        # 시작해 성명 칸으로 새어 들어온다. 헤더 중심에 가장 가까운 열로 배정한다.
        anchors = {name: (word.x0 + word.x1) / 2 for name, word in header.items()}
        header_top = header["성명"].top

        for word in sorted(words, key=lambda w: (w.top, w.x0)):
            if word.top <= header_top or not re.fullmatch(r"[가-힣]{2,4}", word.text):
                continue
            if word.text in _NOT_A_NAME:
                continue
            center = (word.x0 + word.x1) / 2
            nearest = min(anchors, key=lambda name: abs(anchors[name] - center))
            if nearest == "성명":
                names.append(word.text)
    return names


def _purpose_before(flat: str, position: int, name: str | None) -> str:
    """출장기간 바로 앞, 성명 뒤의 문자열이 출장내용이다."""
    head = flat[:position]
    if name and (index := head.rfind(name)) >= 0:
        return head[index + len(name):].strip()
    return ""


# ── 출장증빙 ──────────────────────────────────────────────────────────────

_STAY_DATE_RE = re.compile(r"체류증빙(\d{4})년(\d{1,2})월(\d{1,2})일")
_KM_RE = re.compile(r"([\d,]+)\s*km", re.IGNORECASE)
_WON_RE = re.compile(r"([\d,]+)\s*원")


def extract_trip_evidence(document: Document) -> None:
    flat = flatten(document.text)
    if not flat:
        return

    has_route = "이동경로" in flat
    has_transport = "교통비증빙" in flat
    _put(document, "route_block", has_route)
    _put(document, "transport_block", has_transport)

    # 거리 3개(가는 길·오는 길·총계)가 순서대로 나온다. 2개뿐이면 총계가 공란이다.
    if has_route:
        distances = [nz.money(value) for value in _KM_RE.findall(flat)]
        distances = [d for d in distances if d is not None]
        _put(document, "dist_out", distances[0] if len(distances) >= 1 else None)
        _put(document, "dist_back", distances[1] if len(distances) >= 2 else None)
        _put(document, "dist_total", distances[2] if len(distances) >= 3 else None)

    if has_transport and (amounts := _WON_RE.findall(flat)):
        _put(document, "transport_amount", nz.money(amounts[0]), amounts[0])

    stay_dates = [
        dt.date(int(y), int(m), int(d))
        for y, m, d in _STAY_DATE_RE.findall(flat)
    ]
    if stay_dates:
        document.fields["stay_dates"] = Value(
            sorted(set(stay_dates)), CONFIDENCE["pdf_text"], document.source(1)
        )
    elif "체류증빙" in flat:
        document.fields["stay_dates"] = Value([], CONFIDENCE["pdf_text"], document.source(1))

    for line in document.text.splitlines():
        note = line.strip().lstrip("*").strip()
        if not note or note.startswith(("이동경로", "교통비", "체류", "총 이동", "출발지", "도착지")):
            continue
        if any(word in note for word in ("경유", "이동", "참가", "워크숍")):
            _put(document, "route_note", note)
            break


# ── 하이패스 통행료 영수증 ────────────────────────────────────────────────

_TOLL_BLOCK_RE = re.compile(r"하이패스는")
_TOLL_FIELDS = {
    "merchant": re.compile(r"^(.*?영업소)\s*$", re.MULTILINE),
    "datetime": re.compile(r"(\d{4}년\d{2}월\d{2}일\s*\d{1,2}시\d{1,2}분)"),
    "tollgate_in": re.compile(r"입구영업소\s*:\s*(\S+)"),
    "amount": re.compile(r"\d+\s*종\s*([\d,]+)\s*원"),
    "card_no": re.compile(r"(\d{4}-\d{2}\*{2}-\*{4}-\d{4})"),
    "approval_no": re.compile(r"(?<![\w-])(H\d{3}-\d{4}-\d{5})(?![\w-])"),
    "biz_no": re.compile(r"사업자번호\s*:\s*([\d\-]+)"),
}
_TOLL_TOTAL_RE = re.compile(r"총\s*(\d+)\s*건\s*/\s*([\d,]+)\s*원")


def extract_tollgate_receipts(document: Document) -> None:
    text = document.text
    if not text.strip():
        return

    blocks = _split_blocks(text, _TOLL_BLOCK_RE)
    receipts = []
    for index, block in enumerate(blocks, start=1):
        receipt = {"kind": "tollgate", "label": f"하이패스 {index}"}
        for name, pattern in _TOLL_FIELDS.items():
            if (match := pattern.search(block)):
                receipt[name] = match.group(1).strip()
        receipt["amount"] = nz.money(receipt.get("amount"))
        receipt["datetime"] = nz.parse_datetime(receipt.get("datetime"))
        if receipt.get("merchant"):
            receipt["merchant_address"] = receipt["merchant"]
        if receipt["amount"] is not None and receipt["datetime"] is not None:
            receipts.append(receipt)

    if receipts:
        document.fields["receipts"] = Value(receipts, CONFIDENCE["pdf_text"], document.source(1))
    if (match := _TOLL_TOTAL_RE.search(text)):
        _put(document, "stated_count", int(match.group(1)))
        _put(document, "stated_total", nz.money(match.group(2)), match.group(2))


# ── 카드 매출전표 (체류 영수증) ───────────────────────────────────────────

_CARD_FIELDS = {
    "approval_no": re.compile(r"승인번호\s*[:\s]\s*(\S+)"),
    "datetime": re.compile(r"거래일자\s*[:\s]\s*([\d.]+\s*[·\s]\s*[\d:]+)"),
    "merchant": re.compile(r"가맹점명\s*[:\s]\s*(\S+)"),
    "merchant_address": re.compile(r"주소\(ADDRESS\)\s*(\S+)"),
    "biz_no": re.compile(r"사업자등록번호\s*[:\s]\s*([\d\-]+)"),
    "card_no": re.compile(r"카드번호\s*\(?([\d*\-]+)\)?"),
    "amount": re.compile(r"합계\s*([\d,]+)\s*원"),
}


def extract_card_receipts(document: Document) -> None:
    text = document.text
    if not text.strip():
        return

    blocks = _split_blocks(text, re.compile(r"카드번호|승인번호"))
    receipts = []
    for index, block in enumerate(blocks, start=1):
        receipt = {"kind": "stay", "label": f"카드전표 {index}"}
        for name, pattern in _CARD_FIELDS.items():
            if (match := pattern.search(block)):
                receipt[name] = match.group(1).strip()
        receipt["amount"] = nz.money(receipt.get("amount"))
        receipt["datetime"] = _parse_slip_datetime(receipt.get("datetime"))
        if receipt["amount"] is not None:
            receipts.append(receipt)

    if receipts:
        existing = document.fields.get("receipts")
        merged = (existing.value if existing and existing.is_present else []) + receipts
        document.fields["receipts"] = Value(merged, CONFIDENCE["pdf_text"], document.source(1))


def _parse_slip_datetime(value: str | None) -> dt.datetime | None:
    """'26.6.29·12:26:19' 형태의 전표 거래일자."""
    if not value:
        return None
    return nz.parse_datetime(value.replace("·", " "))


# ── 공용 ──────────────────────────────────────────────────────────────────

def _split_blocks(text: str, marker: re.Pattern) -> list[str]:
    """영수증 여러 건이 한 페이지에 나열된다. 표시자 기준으로 자른다."""
    positions = [m.start() for m in marker.finditer(text)]
    if not positions:
        return [text]
    bounds = positions + [len(text)]
    return [text[bounds[i]: bounds[i + 1]] for i in range(len(positions))]


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
