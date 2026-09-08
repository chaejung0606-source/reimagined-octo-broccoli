"""출장비 규칙 판정 (R-TRV-*).

이 유형의 핵심은 '출장기간으로 영수증을 먼저 거르고 나서 합산' 하는 것이다.
거르지 않고 합산하면, 여러 출장의 영수증을 한 장에 뽑아 낸 제출자에게
전부 오탐이 난다(이성재: 8건 33,900원 제출 / 해당 출장분 3건 8,500원 청구).
"""
from __future__ import annotations

import datetime as dt

from .. import normalize as nz
from ..engine import Context, Fail, NeedsReview, check


# ── 헬퍼 ──────────────────────────────────────────────────────────────────

def _trip(ctx: Context) -> dict:
    """검토 대상 출장 1건을 고른다.

    출장신청서 한 장에 여러 사람 또는 여러 출장이 들어 있으므로, 제출자 이름으로
    고른다. 특정할 수 없으면 판정하지 않는다.
    """
    document = ctx.doc("trip_request")
    if document is None:
        raise NeedsReview("출장신청서를 찾지 못했습니다")

    trips = document.fields.get("trips")
    if trips is None or not trips.is_present:
        raise NeedsReview("출장신청서에서 출장 내역을 읽지 못했습니다")

    candidates = trips.value
    owner = nz.strip_spaces(ctx.docs.owner or "")
    if owner:
        mine = [t for t in candidates if nz.strip_spaces(t.get("name") or "") == owner]
        if mine:
            candidates = mine

    if len(candidates) != 1:
        raise NeedsReview(f"정산 대상 출장을 특정하지 못했습니다({len(candidates)}건)")
    return candidates[0]


def _period(ctx: Context) -> tuple[dt.datetime, dt.datetime]:
    trip = _trip(ctx)
    start, end = trip.get("start"), trip.get("end")
    if start is None or end is None:
        raise NeedsReview("출장기간을 읽지 못했습니다")
    return start, end


def _all_receipts(ctx: Context) -> list[dict]:
    """제출된 모든 영수증. 여러 파일에 흩어져 있어 한데 모은다."""
    found: list[dict] = []
    for document in ctx.docs:
        value = document.fields.get("receipts")
        if value is not None and value.is_present:
            for receipt in value.value:
                found.append({**receipt, "_document": document.name, "_source": document.source(1)})
    return found


def _in_period(receipt: dict, start: dt.datetime, end: dt.datetime) -> bool:
    when = receipt.get("datetime")
    return when is not None and start <= when <= end


# ── L0 : 서식 블록 완비성 ─────────────────────────────────────────────────

@check("R-TRV-001")
def approval_complete(ctx: Context):
    document = ctx.doc("trip_request")
    if document is None:
        raise NeedsReview("출장신청서를 찾지 못했습니다")
    doc_no = document.fields.get("doc_no")
    issued = document.fields.get("issued_at")
    if doc_no is None or not doc_no.is_present or issued is None or not issued.is_present:
        return Fail({}, [document.source(1)])
    return None


@check("R-TRV-002")
def transport_block(ctx: Context):
    document = ctx.doc("trip_evidence")
    if document is None:
        raise NeedsReview("출장증빙을 찾지 못했습니다")
    if not ctx.get("trip_evidence.transport_block"):
        return Fail({}, [document.source(1)])
    return None


@check("R-TRV-003")
def route_block(ctx: Context):
    document = ctx.doc("trip_evidence")
    if document is None:
        raise NeedsReview("출장증빙을 찾지 못했습니다")
    if not ctx.get("trip_evidence.route_block"):
        return Fail({}, [document.source(1)])
    return None


@check("R-TRV-004")
def stay_dates_complete(ctx: Context):
    start, end = _period(ctx)
    document = ctx.doc("trip_evidence")
    stay = ctx.value("trip_evidence.stay_dates")
    if stay is None:
        raise NeedsReview("체류 증빙 페이지를 읽지 못했습니다")

    expected = {
        start.date() + dt.timedelta(days=offset)
        for offset in range((end.date() - start.date()).days + 1)
    }
    missing = sorted(expected - set(stay.value or []))
    if missing:
        return Fail(
            {"missing": [d.strftime("%m/%d") for d in missing]},
            [document.source(1)] if document else [],
        )
    return None


@check("R-TRV-005")
def transport_receipts_attached(ctx: Context):
    if any(r.get("kind") == "tollgate" or r.get("amount") for r in _all_receipts(ctx)):
        return None
    # 영수증 파일은 냈는데 스캔이라 못 읽은 경우와, 아예 안 낸 경우를 구분한다.
    # 전자를 '미첨부'로 단정하면 사실이 아닌 반려 사유가 된다.
    from ..pdfio import is_scanned

    unreadable = [
        d.name for d in ctx.docs
        if d.doc_type in ("receipt_tollgate", "receipt_card") and is_scanned(d)
    ]
    if unreadable:
        raise NeedsReview(f"영수증이 스캔 이미지라 읽지 못했습니다: {', '.join(unreadable)}")
    return Fail({})


# ── L1 : 거리·금액 계산 ───────────────────────────────────────────────────

@check("R-TRV-006")
def route_total(ctx: Context):
    if not ctx.get("trip_evidence.route_block"):
        return None  # 블록 자체가 없으면 R-TRV-003 이 보고한다
    document = ctx.doc("trip_evidence")
    out_km, back_km = ctx.require("trip_evidence.dist_out", "trip_evidence.dist_back")
    total = ctx.get("trip_evidence.dist_total")

    if total != out_km + back_km:
        return Fail({"computed": out_km + back_km}, [document.source(1)] if document else [])
    return None


@check("R-TRV-008")
def route_asymmetry(ctx: Context):
    out_km, back_km = ctx.require("trip_evidence.dist_out", "trip_evidence.dist_back")
    if max(out_km, back_km) == 0:
        return None
    ratio = abs(out_km - back_km) / max(out_km, back_km)
    if ratio > float(ctx.settings.get("route_asymmetry_tolerance", 0.3)):
        # 경유 사유가 적혀 있으면 이미 설명된 것으로 본다.
        if ctx.get("trip_evidence.route_note"):
            return None
        return Fail({})
    return None


@check("R-TRV-009")
def transport_amount_matches(ctx: Context):
    if not ctx.get("trip_evidence.transport_block"):
        return None
    stated = ctx.require("trip_evidence.transport_amount")
    start, end = _period(ctx)

    receipts = [r for r in _all_receipts(ctx) if r.get("kind") == "tollgate"]
    if not receipts:
        raise NeedsReview("교통비 영수증을 읽지 못했습니다")

    in_period = [r for r in receipts if _in_period(r, start, end)]
    if not in_period:
        # 영수증이 전부 기간 밖이면 R-TRV-011 이 그 사실을 보고한다.
        # 여기서 '0원으로 정정하세요' 라고 하면 잘못된 조치를 안내하게 된다.
        return None

    total = sum(r["amount"] for r in in_period if r.get("amount"))
    if total != stated:
        return Fail({"computed": total}, ctx.sources("trip_evidence.transport_amount"))
    return None


@check("R-TRV-010")
def receipt_internal_total(ctx: Context):
    failures = []
    for document in ctx.docs:
        stated = document.fields.get("stated_total")
        receipts = document.fields.get("receipts")
        if stated is None or not stated.is_present or receipts is None or not receipts.is_present:
            continue
        total = sum(r.get("amount") or 0 for r in receipts.value)
        if total != stated.value:
            failures.append(Fail(
                {"computed": total, "receipt.stated_total": stated.value},
                [document.source(1)],
            ))
    return failures


# ── L2 : 기간·장소 정합성 ─────────────────────────────────────────────────

@check("R-TRV-011")
def receipts_within_period(ctx: Context):
    start, end = _period(ctx)
    failures = []
    for receipt in _all_receipts(ctx):
        when = receipt.get("datetime")
        if when is None:
            continue
        if not (start <= when <= end):
            failures.append(Fail({
                "receipt.label": f"{receipt['_document']}의 {receipt.get('label', '영수증')}",
                "receipt.datetime": when.strftime("%Y-%m-%d %H:%M"),
                "trip_request.period": f"{start:%Y-%m-%d %H:%M} ~ {end:%Y-%m-%d %H:%M}",
            }, [receipt["_source"]]))
    return failures


@check("R-TRV-012")
def stay_dates_within_period(ctx: Context):
    start, end = _period(ctx)
    stay = ctx.value("trip_evidence.stay_dates")
    if stay is None or not stay.value:
        return None
    failures = []
    for date in stay.value:
        if not (start.date() <= date <= end.date()):
            failures.append(Fail({"stay.date": date.isoformat()}, ctx.sources("trip_evidence.stay_dates")))
    return failures


@check("R-TRV-013")
def receipt_region_matches(ctx: Context):
    trip = _trip(ctx)
    destination = trip.get("destination") or ""
    regions = nz.regions_of(destination)
    if not regions:
        raise NeedsReview("출장지를 읽지 못했습니다")

    failures = []
    for receipt in _all_receipts(ctx):
        address = receipt.get("merchant_address")
        if not address:
            continue
        region = nz.region_of(address)
        # 고속도로 영업소는 이동 중 지출이라 출장지와 달라도 정상이다.
        if not region or receipt.get("kind") == "tollgate":
            continue
        if region not in regions:
            failures.append(Fail({
                "receipt.label": receipt.get("label", "영수증"),
                "receipt.merchant_address": address,
                "trip_request.destination": destination,
            }, [receipt["_source"]]))
    return failures


@check("R-TRV-016")
def allowance_eligible(ctx: Context):
    trip = _trip(ctx)
    eligible = trip.get("allowance_eligible")
    if eligible is None:
        raise NeedsReview("여비지급대상 여부를 읽지 못했습니다")
    if not eligible:
        return Fail({}, ctx.sources("trip_request.trips"))
    return None


@check("R-TRV-017")
def single_trip(ctx: Context):
    document = ctx.doc("trip_request")
    if document is None:
        raise NeedsReview("출장신청서를 찾지 못했습니다")
    trips = document.fields.get("trips")
    if trips is None or not trips.is_present:
        raise NeedsReview("출장 내역을 읽지 못했습니다")

    owner = nz.strip_spaces(ctx.docs.owner or "")
    mine = [t for t in trips.value if not owner or nz.strip_spaces(t.get("name") or "") == owner]
    if len(mine) > 1:
        return Fail({"computed": len(mine)}, [document.source(1)])
    return None


@check("R-TRV-018")
def purpose_supported(ctx: Context):
    trip = _trip(ctx)
    purpose = trip.get("purpose") or ""
    # 강연·발표처럼 개인 일정이 목적이면 근거자료를 요구한다.
    if not any(word in purpose for word in ("강연", "발표", "특강", "심사", "자문")):
        return None
    if ctx.has_doc("purpose_evidence"):
        return None
    return Fail({"trip_request.purpose": purpose})


# ── 중복·부정 방지 ────────────────────────────────────────────────────────

@check("R-TRV-019")
def duplicate_receipts(ctx: Context):
    seen: dict[tuple, list[str]] = {}
    for receipt in _all_receipts(ctx):
        key = (receipt.get("approval_no"), receipt.get("datetime"), receipt.get("amount"))
        if key[0] is None and key[1] is None:
            continue
        seen.setdefault(key, []).append(f"{receipt['_document']}({receipt.get('label', '')})")

    duplicates = [
        f"{key[0] or key[1]} — {', '.join(names)}"
        for key, names in seen.items() if len(names) > 1
    ]
    if duplicates:
        return Fail({"duplicates": duplicates})
    return None


@check("R-TRV-021")
def official_vehicle(ctx: Context):
    uses = ctx.value("trip_request.uses_official_vehicle")
    if uses is None or not uses.is_present:
        raise NeedsReview("공용차량 이용 여부는 서식만으로 판정할 수 없습니다")
    if uses.value and (ctx.get("trip_evidence.transport_amount") or 0) > 0:
        return Fail({})
    return None


@check("R-TRV-022")
def card_consistency(ctx: Context):
    cards = {}
    for receipt in _all_receipts(ctx):
        card_no = receipt.get("card_no")
        if card_no:
            cards.setdefault(card_no, []).append(receipt.get("label", ""))
    if len(cards) > 1:
        return Fail({
            "receipt.label": "제출된 영수증",
            "receipt.card_no": ", ".join(sorted(cards)),
        })
    return None


# ── 경로·인적사항·품목 ────────────────────────────────────────────────────

@check("R-TRV-014")
def tollgate_route_continuity(ctx: Context):
    """하이패스 구간이 사슬처럼 이어지는지 본다.

    한 건의 통행료 영수증은 '입구영업소 → 출구영업소' 한 구간이다. 왕복이면
    가는 길 출구와 오는 길 입구가 같은 영업소여야 이어진다. 끊긴 자리는
    그 사이를 국도로 갔거나, 영수증이 빠졌거나, 다른 출장 건이 섞인 것이다.
    어느 쪽인지는 사람이 판단할 일이라 WARN 으로 올리고 사유 기재를 안내한다.
    """
    start, end = _period(ctx)
    legs = [
        receipt for receipt in _all_receipts(ctx)
        if receipt.get("kind") == "tollgate" and _in_period(receipt, start, end)
        and receipt.get("tollgate_in") and receipt.get("merchant")
    ]
    if len(legs) < 2:
        return None  # 구간이 하나면 이어질 것이 없다

    legs.sort(key=lambda receipt: receipt["datetime"])
    breaks = []
    for previous, following in zip(legs, legs[1:]):
        exit_gate = _gate(previous["merchant"])
        entry_gate = _gate(following["tollgate_in"])
        if exit_gate and entry_gate and exit_gate != entry_gate:
            breaks.append(f"{exit_gate} 출구 → {entry_gate} 입구")

    if breaks:
        return Fail({"breaks": breaks}, [leg["_source"] for leg in legs[:1]])
    return None


def _gate(name: str) -> str:
    """'한국도로공사 대관령영업소' · '대관령(IC)' → '대관령'.

    같은 영업소가 영수증마다 다르게 찍혀 나온다. 접미사를 떼지 않으면
    이어진 구간도 끊긴 것으로 보고한다.
    """
    text = nz.strip_spaces(name)
    for word in ("한국도로공사", "영업소", "톨게이트", "TG", "IC", "(", ")"):
        text = text.replace(word, "")
    return text


@check("R-TRV-015")
def traveller_matches(ctx: Context):
    """출장신청서의 출장자 명단에 검토 대상자가 있는지.

    같은 신청서가 동승자 4명 폴더에 각각 들어 있다. 엉뚱한 사람의 신청서를
    붙여 낸 경우 여기서 걸린다 — 다른 규칙은 전부 이 신청서를 근거로 삼으므로
    이것이 틀리면 나머지 판정이 모두 헛것이 된다.
    """
    document = ctx.doc("trip_request")
    if document is None:
        raise NeedsReview("출장신청서를 찾지 못했습니다")
    trips = document.fields.get("trips")
    if trips is None or not trips.is_present:
        raise NeedsReview("출장신청서에서 출장자 명단을 읽지 못했습니다")

    owner = nz.strip_spaces(ctx.docs.owner or "")
    if not owner:
        raise NeedsReview("검토 대상자의 성명을 확인하지 못했습니다")

    listed = [nz.strip_spaces(trip.get("name") or "") for trip in trips.value]
    listed = [name for name in listed if name]
    if not listed:
        raise NeedsReview("출장신청서에서 출장자 성명을 읽지 못했습니다")

    if owner not in listed:
        return Fail(
            {"values": [f"신청서 {', '.join(listed)}", f"제출자 {owner}"]},
            [document.source(1)],
        )
    return None


@check("R-TRV-023")
def non_reimbursable_items(ctx: Context):
    """체류 영수증의 품목에 정산 불가 품목이 있는지."""
    keywords = ctx.settings.get("non_reimbursable_keywords") or []
    if not keywords:
        return None

    failures, unreadable = [], []
    for receipt in _all_receipts(ctx):
        if receipt.get("kind") == "tollgate":
            continue
        items = receipt.get("items")
        if not items:
            unreadable.append(f"{receipt['_document']}의 {receipt.get('label', '영수증')}")
            continue
        found = [
            item["name"] for item in items
            if any(word in item.get("name", "") for word in keywords)
        ]
        if found:
            failures.append(Fail(
                {"receipt.label": receipt.get("label", "영수증"), "found": found},
                [receipt["_source"]],
            ))

    if failures:
        return failures
    # 읽은 영수증에 문제가 없더라도, 못 읽은 영수증을 통과시키지는 않는다.
    if unreadable:
        raise NeedsReview(f"품목을 읽지 못한 영수증이 있습니다: {', '.join(unreadable)}")
    return None


@check("R-TRV-024")
def spatiotemporal_conflict(ctx: Context):
    """가까운 시각에 서로 먼 지역의 영수증이 함께 있는지.

    통행료 영수증은 제외한다. 고속도로 영업소는 이동 중 지출이라 출장지와
    다른 것이 정상이고(R-TRV-013 과 같은 이유), 넣으면 정상 건마다 걸린다.
    """
    window = dt.timedelta(minutes=ctx.number_setting("conflict_window_minutes", 60))

    located = []
    for receipt in _all_receipts(ctx):
        when, address = receipt.get("datetime"), receipt.get("merchant_address")
        if receipt.get("kind") == "tollgate" or when is None or not address:
            continue
        region = nz.region_of(address)
        if region:
            located.append((when, region, receipt))

    located.sort(key=lambda item: item[0])
    failures = []
    for index, (when, region, receipt) in enumerate(located):
        for other_when, other_region, other in located[index + 1:]:
            if other_when - when > window:
                break
            if other_region != region:
                failures.append(Fail({
                    "time": when.strftime("%m/%d %H:%M"),
                    "receipts": [
                        f"{receipt.get('label', '영수증')}({region})",
                        f"{other.get('label', '영수증')}({other_region})",
                    ],
                }, [receipt["_source"], other["_source"]]))
    return failures
