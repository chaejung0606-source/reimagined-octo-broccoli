"""출장비 서류 추출 — 출장신청서 / 출장증빙 / 영수증.

출장비는 청구액이 서류에 적힌 값이 아니라 **영수증에서 역산**되는 유일한 유형이다.
그래서 영수증 하나하나를 (일시, 금액, 가맹점, 승인번호)로 세워 두는 것이 핵심이고,
R-TRV-009 는 반드시 출장기간 필터를 먼저 걸고 합산해야 오탐이 없다.
"""
from __future__ import annotations

import re
from typing import Any

from .. import normalize as nz
from ..models import Document, Namespace, Period
from .base import (
    FieldBag,
    as_date,
    as_datetime,
    as_money,
    as_name,
    as_period,
    clean,
    document_year,
    find_label_value,
    has_marker,
    is_checked,
)
from .table import table_lines

# --------------------------------------------------------------- 출장신청서

_DOC_NO_LABELS = ("문서번호", "문서 번호", "관리번호")
_ISSUED_LABELS = ("시행일자", "시행", "결재일자", "기안일")
_DEPARTMENT_LABELS = ("부서명", "부서", "소속부서", "기안부서")
_DESTINATION_LABELS = ("출장지", "출장 장소", "행선지", "출장지역")
_PURPOSE_LABELS = ("출장내용", "출장목적", "출장 목적", "용무", "출장사유")
_ELIGIBLE_LABELS = ("여비지급대상여부", "여비지급대상", "여비 지급 대상")
_VEHICLE_LABELS = ("공용차량이용", "공용차량", "관용차량", "차량이용")
_FUNDING_LABELS = ("회계구분", "지급기관", "예산과목", "회계")
_PURPOSE_TYPE_LABELS = ("출장목적구분", "목적구분", "출장구분")

_YES = ("예", "여", "Y", "y", "해당", "대상", "있음", "O", "o", "ㅇ")
_NO = ("아니오", "아니요", "N", "n", "미해당", "비대상", "없음", "X", "x")

_DATETIME = (
    r"\d{2,4}\s*[.\-/년]\s*\d{1,2}\s*[.\-/월]\s*\d{1,2}\s*[일.]?"
    r"(?:\s*\d{1,2}\s*[:시]\s*\d{1,2}\s*분?)?"
)
_PERIOD_RE = re.compile(rf"(?P<start>{_DATETIME})\s*(?:~|～|∼|-|—|부터)\s*(?P<end>{_DATETIME})")


def _yes_no(value: str | None) -> bool | None:
    text = clean(value)
    if text is None:
        return None
    packed = nz.strip_spaces(text) or ""
    if any(packed.startswith(y) for y in _YES):
        return True
    if any(packed.startswith(n) for n in _NO):
        return False
    if is_checked(packed):
        return True
    return None



def _parse_trips(document: Document, year: int | None) -> list[dict[str, Any]]:
    """출장 건을 뽑는다. 신청서 1장에 여러 건이 들어 있을 수 있다 (R-TRV-017)."""
    trips: list[dict[str, Any]] = []
    lines = table_lines(document)
    for line in lines:
        match = _PERIOD_RE.search(line)
        if not match:
            continue
        start = as_datetime(match.group("start"), year)
        end = as_datetime(match.group("end"), year)
        if start is None:
            continue
        head = line[: match.start()]
        tail = line[match.end():]

        name = as_name(head) if re.search(r"[가-힣]{2,5}", head) else None
        rank = _find_rank(head)
        destination = clean(tail.split("  ")[0]) if tail.strip() else None
        purpose = clean(" ".join(tail.split("  ")[1:])) if "  " in tail else None
        trips.append({
            "name": name,
            "rank": rank,
            "period": Period(start, end),
            "destination": destination,
            "purpose": _strip_trailing_flag(purpose),
            "label": f"{start:%Y-%m-%d} ~ {end:%Y-%m-%d}" if end else f"{start:%Y-%m-%d}",
        })
    return trips


def _strip_trailing_flag(text: str | None) -> str | None:
    """행 끝의 `여비지급대상여부` 값(예/아니오)을 출장내용에서 떼어 낸다."""
    if text is None:
        return None
    return clean(re.sub(r"[\s|]*(예|아니오|아니요|Y|N|해당|미해당)\s*$", "", text.strip()))


_RANK_WORDS = ("교수", "부교수", "조교수", "강사", "연구원", "직원", "팀장", "과장",
               "대리", "주임", "학생", "조교", "책임", "선임", "센터장", "단장")


def _find_rank(text: str) -> str | None:
    for word in _RANK_WORDS:
        if word in text:
            return word
    return None


def extract_trip_request(document: Document, bag: FieldBag) -> None:
    lines = table_lines(document)
    year = document_year(document)

    value, slot = find_label_value(lines, _DOC_NO_LABELS, value=r"(?P<value>[A-Za-z0-9\-]{6,})")
    bag.put_optional("trip_request.doc_no", clean(value), found_slot=slot is not None)

    value, slot = find_label_value(lines, _ISSUED_LABELS)
    bag.put_optional("trip_request.issued_at", as_date(value, year) if value else None,
                     found_slot=slot is not None)

    value, _ = find_label_value(lines, _DEPARTMENT_LABELS)
    if value:
        bag.put("trip_request.department", nz.strip_spaces(value))

    approvers = _parse_approvers(lines)
    if approvers:
        bag.put("trip_request.approvers", approvers)
    elif has_marker(document.text, "결재", "결 재"):
        bag.blank("trip_request.approvers")
    else:
        bag.missing("trip_request.approvers", note="결재선을 찾지 못했습니다")

    trips = _parse_trips(document, year)
    bag.put("trip_request.trips", [Namespace(t, label=t["label"]) for t in trips])

    # 인적사항은 라벨이 아니라 출장 건 행에서 가져온다. 신청서의 `성명 직급 …` 은
    # 표 머리행이라 라벨 방식으로 읽으면 값이 아니라 옆 열 이름이 잡힌다.
    if trips:
        if trips[0].get("name"):
            bag.put("person.name", trips[0]["name"])
        if trips[0].get("rank"):
            bag.put("person.rank", trips[0]["rank"])

    period = trips[0]["period"] if trips else None
    if period is None:
        value, slot = find_label_value(lines, ("출장기간", "기간"))
        period = as_period(value, year) if value else None
        bag.put_optional("trip_request.period", period, found_slot=slot is not None)
    else:
        bag.put("trip_request.period", period)
    if period is not None:
        bag.put("period.start", period.start_date)
        bag.put("period.end", period.end_date)

    destination = trips[0]["destination"] if trips and trips[0]["destination"] else None
    if destination is None:
        destination, slot = find_label_value(lines, _DESTINATION_LABELS)
        bag.put_optional("trip_request.destination", clean(destination), found_slot=slot is not None)
    else:
        bag.put("trip_request.destination", destination)

    purpose = trips[0]["purpose"] if trips and trips[0].get("purpose") else None
    if purpose is None:
        purpose, slot = find_label_value(lines, _PURPOSE_LABELS)
        bag.put_optional("trip_request.purpose", clean(purpose), found_slot=slot is not None)
    else:
        bag.put("trip_request.purpose", purpose)

    value, slot = find_label_value(lines, _ELIGIBLE_LABELS)
    bag.put_optional("trip_request.allowance_eligible", _yes_no(value), found_slot=slot is not None)

    value, slot = find_label_value(lines, _VEHICLE_LABELS)
    vehicle = _yes_no(value)
    if slot is not None:
        bag.put_optional("trip_request.uses_official_vehicle", vehicle, found_slot=True)
    else:
        # 서식에 칸 자체가 없으면 '공용차량 아님' 으로 본다 (R-TRV-021 이 조용해야 한다).
        bag.put("trip_request.uses_official_vehicle", False,
                note="서식에 공용차량 항목 없음 → 미이용으로 간주")

    value, _ = find_label_value(lines, _FUNDING_LABELS)
    if value:
        bag.put("trip_request.funding", nz.strip_spaces(value))

    value, _ = find_label_value(lines, _PURPOSE_TYPE_LABELS)
    if value:
        bag.put("trip_request.purpose_type", nz.strip_spaces(value))


_APPROVAL_LINE_RE = re.compile(r"(결\s*재|합\s*의|협\s*조|승\s*인|검\s*토)")


def _parse_approvers(lines: list[str]) -> list[str]:
    """결재선의 성명을 모은다. 전자결재 출력본은 직급+성명이 나란히 찍힌다."""
    names: list[str] = []
    for index, line in enumerate(lines):
        if not _APPROVAL_LINE_RE.search(line):
            continue
        window = " ".join(lines[index: index + 3])
        for match in re.finditer(r"([가-힣]{2,4})\s*(?:\(인\)|인|서명)?", window):
            candidate = match.group(1)
            if candidate in {"결재", "합의", "협조", "승인", "검토", "기안", "전결", "대결"}:
                continue
            if candidate not in names:
                names.append(candidate)
    return names[:6]


# ----------------------------------------------------------------- 출장증빙

_TRANSPORT_MARKERS = ("교통비 증빙", "교통비증빙", "교통비")
_ROUTE_MARKERS = ("이동경로", "이동 경로")
_STAY_MARKERS = ("체류 증빙", "체류증빙")

_DIST_OUT_RE = re.compile(r"출\s*발\s*지\s*(?:→|->|~|-|에서)\s*도\s*착\s*지\s*[:：]?\s*([\d,.]+)?\s*(?:km|㎞|킬로)?")
_DIST_BACK_RE = re.compile(r"도\s*착\s*지\s*(?:→|->|~|-|에서)\s*출\s*발\s*지\s*[:：]?\s*([\d,.]+)?\s*(?:km|㎞|킬로)?")
_DIST_TOTAL_RE = re.compile(r"총\s*이\s*동\s*경\s*로\s*[:：]?\s*([\d,.]+)?\s*(?:km|㎞|킬로)?")
_STAY_DATE_RE = re.compile(r"체\s*류\s*증\s*빙\s*[:：]?\s*(\d{2,4}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일"
                           r"|\d{2,4}[.\-/]\d{1,2}[.\-/]\d{1,2})")
_MAP_DISTANCE_RE = re.compile(r"(?:총\s*거리|경로\s*거리|거리)\s*[:：]?\s*([\d,.]+)\s*(?:km|㎞)")


def _distance(match: re.Match | None) -> tuple[float | None, bool]:
    """(거리, 칸을 찾았는가). 칸은 있는데 숫자가 없으면 '공란' 이다."""
    if match is None:
        return None, False
    raw = match.group(1)
    if not raw:
        return None, True
    try:
        return float(raw.replace(",", "")), True
    except ValueError:
        return None, True


def extract_trip_evidence(document: Document, bag: FieldBag) -> None:
    text = document.text
    year = document_year(document)

    has_transport = has_marker(text, *_TRANSPORT_MARKERS)
    bag.put("trip_evidence.transport_block", has_transport)
    has_route = has_marker(text, *_ROUTE_MARKERS)
    bag.put("trip_evidence.route_block", has_route)

    amount, slot = _transport_amount(document)
    bag.put_optional("trip_evidence.transport_amount", amount,
                     found_slot=slot or has_transport)

    out_value, out_slot = _distance(_DIST_OUT_RE.search(nz.strip_spaces(text) or ""))
    back_value, back_slot = _distance(_DIST_BACK_RE.search(nz.strip_spaces(text) or ""))
    total_value, total_slot = _distance(_DIST_TOTAL_RE.search(nz.strip_spaces(text) or ""))

    bag.put_optional("trip_evidence.dist_out", out_value, found_slot=out_slot or has_route)
    bag.put_optional("trip_evidence.dist_back", back_value, found_slot=back_slot or has_route)
    bag.put_optional("trip_evidence.dist_total", total_value, found_slot=total_slot or has_route)

    map_match = _MAP_DISTANCE_RE.search(text)
    if map_match:
        bag.put("trip_evidence.map_distance", float(map_match.group(1).replace(",", "")))
    else:
        bag.missing("trip_evidence.map_distance", note="지도 캡처는 이미지 — OCR 단계 필요")

    stay_dates: list[Any] = []
    for match in _STAY_DATE_RE.finditer(nz.strip_spaces(text) or ""):
        day = as_date(match.group(1), year)
        if day is not None and day not in stay_dates:
            stay_dates.append(day)
    if stay_dates or has_marker(text, *_STAY_MARKERS):
        bag.put("trip_evidence.stay_dates", sorted(stay_dates))
    else:
        bag.put("trip_evidence.stay_dates", [])

    note, _ = find_label_value(document.lines, ("경유", "사유", "비고"))
    if note:
        bag.put("trip_evidence.route_note", clean(note))

    receipts = parse_receipts(document, default_kind="stay", listed_only=True)
    if receipts:
        bag.put("trip_evidence.receipts", [Namespace(r, label=r["label"]) for r in receipts])


def _transport_amount(document: Document) -> tuple[int | None, bool]:
    """`* 교통비 증빙   18,000원` — 같은 줄 또는 바로 다음 줄의 금액."""
    lines = document.lines
    for index, line in enumerate(lines):
        if not has_marker(line, *_TRANSPORT_MARKERS):
            continue
        for candidate in (line, *(lines[index + 1: index + 3])):
            match = re.search(r"([\d,]{2,12})\s*원", candidate)
            if match:
                return as_money(match.group(1)), True
        return None, True
    return None, False


# ------------------------------------------------------------------ 영수증

_MERCHANT_LABELS = ("가맹점명", "가맹점", "상호", "상 호", "업소명")
_ADDRESS_LABELS = ("주소", "가맹점주소", "소재지", "사업장주소")
_BIZ_NO_LABELS = ("사업자등록번호", "사업자번호", "등록번호")
_CARD_LABELS = ("카드번호", "카드 번호", "카드")
_APPROVAL_LABELS = ("승인번호", "승인 번호", "거래번호")
_TOTAL_LABELS = ("합계금액", "합계", "총액", "결제금액", "승인금액", "판매금액", "통행료 합계")
_TXN_LABELS = ("거래일시", "승인일시", "거래일자", "결제일시", "이용일시", "통행일시")

_TOLLGATE_IN_LABELS = ("입구영업소", "입구", "진입영업소")
_TOLLGATE_OUT_LABELS = ("출구영업소", "출구", "영업소", "진출영업소")

_CARD_NO_RE = re.compile(r"(\d{4}[-\s]?[\d*]{2,4}[-\s]?[\d*]{4}[-\s]?\d{4})")
_BIZ_NO_RE = re.compile(r"(\d{3}\s*-\s*\d{2}\s*-\s*\d{5})")
_STATED_TOTAL_RE = re.compile(r"총\s*(\d{1,3})\s*건.*?([\d,]{3,12})\s*원")

_RECEIPT_LINE_RE = re.compile(
    rf"(?P<when>{_DATETIME}).*?(?P<amount>[\d,]{{3,12}})\s*원?\s*$"
)

#: 하이패스·주유·대중교통 지문
_TRANSPORT_HINTS = ("하이패스", "입구영업소", "한국도로공사", "통행료", "주유", "휘발유",
                    "경유", "승차권", "열차", "고속도로", "톨게이트")


def _receipt_kind(text: str, default_kind: str) -> str:
    packed = nz.strip_spaces(text) or ""
    if any(hint in packed for hint in ("하이패스", "입구영업소", "통행료", "한국도로공사")):
        return "tollgate"
    if any(hint in packed for hint in ("주유", "휘발유", "경유", "리터")):
        return "fuel"
    if any(hint in packed for hint in ("승차권", "열차", "KTX", "버스", "지하철", "택시")):
        return "transit"
    return default_kind


def parse_receipts(document: Document, default_kind: str = "etc",
                   listed_only: bool = False) -> list[dict[str, Any]]:
    """영수증 문서 하나에서 개별 건을 뽑는다.

    하이패스처럼 한 페이지에 여러 건이 나열된 경우와, 카드전표처럼 한 장에 한 건인
    경우를 모두 다룬다. 줄마다 (일시, 금액)이 잡히면 나열형으로 본다.

    ``listed_only`` 는 출장증빙 서식처럼 **영수증이 아닌 문서** 에 쓴다. 한 장짜리
    해석까지 돌리면 서식의 체류 증빙 날짜를 영수증으로 착각해 유령 건이 생긴다.
    """
    if not document.readable:
        return []

    year = document_year(document)
    kind = _receipt_kind(document.text, default_kind)
    lines = table_lines(document)

    rows = _parse_listed_receipts(document, lines, year, kind)
    if rows or listed_only:
        return rows

    single = _parse_single_receipt(document, lines, year, kind)
    return [single] if single else []


def _parse_listed_receipts(document: Document, lines: list[str], year: int | None,
                           kind: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in lines:
        if has_marker(line, "합계", "총액", "소계"):
            continue
        match = _RECEIPT_LINE_RE.search(line.strip())
        if not match:
            continue
        when = as_datetime(match.group("when"), year)
        amount = as_money(match.group("amount"))
        if when is None or amount is None or amount <= 0:
            continue
        tollgates = _tollgates(line)
        rows.append(_receipt_record(
            document=document,
            kind=kind,
            when=when,
            amount=amount,
            merchant=tollgates[1] or tollgates[0],
            tollgate_in=tollgates[0],
            tollgate_out=tollgates[1],
            approval_no=_first(re.findall(r"승인번호\s*[:：]?\s*(\d{4,})", line)),
            card_no=_first(_CARD_NO_RE.findall(line)),
        ))
    if rows:
        # `총 8건 합계 33,900원` 은 **문서 전체**의 합계다. 이걸 영수증마다 복사해
        # 두면 R-TRV-010(영수증 내부 합계)이 건마다 오탐을 낸다.
        stated = _STATED_TOTAL_RE.search(nz.strip_spaces(document.text) or "")
        if stated:
            for row in rows:
                row["page_total"] = as_money(stated.group(2))
                row["page_count"] = int(stated.group(1))
    return rows


_KOREAN_PLACE_RE = re.compile(r"[가-힣]{2,6}")


def _tollgates(line: str) -> tuple[str | None, str | None]:
    """`춘천  횡성  2026/06/29 08:12  3,400` → (입구, 출구)."""
    head = re.split(r"\d{2,4}\s*[.\-/년]", line)[0]
    places = [p for p in _KOREAN_PLACE_RE.findall(head)
              if p not in {"하이패스", "영업소", "입구", "출구", "통행료", "차종", "일시"}]
    if len(places) >= 2:
        return places[0], places[1]
    if len(places) == 1:
        return None, places[0]
    return None, None


def _parse_single_receipt(document: Document, lines: list[str], year: int | None,
                          kind: str) -> dict[str, Any] | None:
    when_text, _ = find_label_value(lines, _TXN_LABELS)
    when = as_datetime(when_text, year) if when_text else None
    if when is None:
        match = re.search(_DATETIME, document.text)
        when = as_datetime(match.group(0), year) if match else None

    amount_text, _ = find_label_value(lines, _TOTAL_LABELS, value=r"(?P<value>[\d,]{2,12})")
    amount = as_money(amount_text) if amount_text else None
    # 금액을 못 읽었으면 영수증으로 세우지 않는다. 유령 건이 생기면
    # R-TRV-011(기간 이탈)·R-TRV-013(소재지)이 통째로 오탐이 된다.
    if amount is None:
        return None

    merchant, _ = find_label_value(lines, _MERCHANT_LABELS)
    address, _ = find_label_value(lines, _ADDRESS_LABELS)
    biz_no, _ = find_label_value(lines, _BIZ_NO_LABELS, value=r"(?P<value>[\d\-\s]{10,15})")
    if not biz_no:
        biz_match = _BIZ_NO_RE.search(document.text)
        biz_no = biz_match.group(1) if biz_match else None
    card_match = _CARD_NO_RE.search(document.text)
    approval, _ = find_label_value(lines, _APPROVAL_LABELS, value=r"(?P<value>[\d]{4,})")

    return _receipt_record(
        document=document,
        kind=kind,
        when=when,
        amount=amount,
        merchant=clean(merchant),
        merchant_address=clean(address),
        biz_no=nz.digits_only(biz_no) if biz_no else None,
        card_no=card_match.group(1) if card_match else None,
        approval_no=clean(approval),
        items=_parse_items(lines),
    )


_ITEM_RE = re.compile(r"^(?P<name>[가-힣A-Za-z][^\d]{1,20}?)\s+(?P<qty>\d{1,3})\s+(?P<amount>[\d,]{3,10})\s*$")


def _parse_items(lines: list[str]) -> list[Namespace]:
    """편의점 전표의 품목 줄. R-TRV-010·023 이 쓴다."""
    items: list[Namespace] = []
    for line in lines:
        match = _ITEM_RE.match(line.strip())
        if not match:
            continue
        name = clean(match.group("name"))
        amount = as_money(match.group("amount"))
        if not name or amount is None:
            continue
        items.append(Namespace({"name": name, "qty": int(match.group("qty")), "amount": amount},
                               label=name))
    return items


def _first(values: list[str]) -> str | None:
    return values[0] if values else None


def _receipt_record(document: Document, kind: str, when: Any, amount: int | None,
                    merchant: str | None = None, merchant_address: str | None = None,
                    biz_no: str | None = None, card_no: str | None = None,
                    approval_no: str | None = None, tollgate_in: str | None = None,
                    tollgate_out: str | None = None, items: list[Namespace] | None = None,
                    ) -> dict[str, Any]:
    label_bits = [merchant or tollgate_out or document.file.name]
    if when is not None:
        label_bits.append(f"{when:%m/%d %H:%M}")
    record = {
        "kind": kind,
        "datetime": when,
        "amount": amount,
        "merchant": merchant,
        "merchant_address": merchant_address,
        "biz_no": biz_no,
        "card_no": card_no,
        "approval_no": approval_no,
        "tollgate_in": tollgate_in,
        "tollgate_out": tollgate_out,
        "tollgate": tollgate_out or tollgate_in,
        "items": items or [],
        "file": document.file.name,
        "label": " ".join(str(b) for b in label_bits if b),
    }
    # 읽지 못한 항목은 키 자체를 두지 않는다. None 으로 남기면 '공란' 으로 취급되어
    # 규칙이 "가맹점 소재지가 출장지와 다릅니다" 같은 판정을 자신 있게 내린다.
    # 실제로는 못 읽은 것이므로 🔵 판독 불가로 가야 한다.
    return {key: value for key, value in record.items() if value is not None}


def extract_receipts(document: Document, bag: FieldBag, kind: str) -> None:
    """`transport_receipts` / `stay_receipts` 문서에서 영수증 목록을 만든다.

    필드 이름을 `parsed_receipts.*` 로 두는 이유: `transport_receipts` 는 규칙이
    **목록 그 자체**로 참조하는 이름이다. 같은 이름 밑에 하위 키를 만들면 목록이
    Namespace 로 바뀌어 `for r in transport_receipts` 가 키 문자열을 돌게 된다.
    """
    default = "tollgate" if kind == "transport_receipts" else "stay"
    receipts = parse_receipts(document, default_kind=default)
    path = f"parsed_receipts.{kind}"
    if not document.readable:
        bag.missing(path, note="텍스트 레이어가 없습니다 — 영수증 판독은 OCR 단계(4단계)")
        return
    bag.put(path, [Namespace(r, label=r["label"]) for r in receipts])


def extract_purpose_evidence(document: Document, bag: FieldBag) -> None:
    bag.put("purpose_evidence.present", True)
    bag.put("purpose_evidence.text", document.text[:2000])
