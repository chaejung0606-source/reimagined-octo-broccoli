"""일반청구 한 건의 데이터 — 추출(AI)과 채우기(ERP 작성 화면) 사이의 계약.

  summary        ERP 적요. 'NN_내용' (NN = 비목 번호, CLAUDE.md 8절)
  expCategory    비목 — ERP 보기(EXP_CATEGORIES) 중 하나
  expDetail      세목 (서류에 있으면)
  evidence       증빙구분 — EVIDENCE_KINDS 중 하나
  expenseDate    지출(증빙) 일자 'YYYY-MM-DD'
  amount         청구액(원, 정수) · supplyAmount 공급가액 · taxAmount 부가세
  payeeName      입금처(거래처) 이름 · payeeBizNo 사업자등록번호 — 입금처 팝업 검색어
  approvalNo     세금계산서 승인번호(국세청, 24자리) — 세금계산서 조회 팝업의 '거래처명/승인번호' 검색어(담당자 2026-10-22)
  receiverEmail  세금계산서의 공급받는자(수신) 이메일 — 설정에 계산서수신메일이 없을 때 조회에 쓴다
  claimDiv       청구종류(청구구분) — CLAIM_DIVS 중 하나. 일반청구 탭에서 증빙구분 다음에 고르고 그 증빙 창을 작성한다(담당자 2026-10-22).
                 그 증빙 창은 미실측이라 앱이 누르지 않고 사람에게 보여 주기만 한다
  bank · accountNo · owner     은행 · 계좌번호 · 예금주
  settleMethod   결제방법 — SETTLE_METHODS 중 하나 (보통 계좌이체)
  attachments    첨부 후보 파일 이름 목록 (폴더 안)
  notes          확인이 필요한 점 (서류 간 불일치 등)

값을 못 찾으면 빈 문자열(금액은 None). 지어내지 않는다. 보기 값은 2026-10-13 실측(CLAUDE.md 14절).
"""
from __future__ import annotations

import re

from ..naming import normnm

KEYS = ("summary", "expCategory", "expDetail", "evidence", "expenseDate", "amount", "supplyAmount",
        "taxAmount", "payeeName", "payeeBizNo", "approvalNo", "receiverEmail", "claimDiv", "bank", "accountNo", "owner",
        "settleMethod", "attachments", "notes")
AMOUNT_KEYS = ("amount", "supplyAmount", "taxAmount")

# ERP #PAY_EXP_CD 의 보기 (실측 그대로). 적요 앞의 비목 번호와 짝지어 둔다.
CATEGORY_CODES = {
    "01": "인건비", "02": "장학금", "03": "교육·연구프로그램개발·운영비", "04": "교육·연구환경개선비",
    "05": "실험·실습장비및기자재구입·운영비", "06": "지자체 연계ㆍ협업비용", "07": "기업지원·협력활동비",
    "08": "성과활용·확산지원비", "09": "기타운영경비", "10": "간접비",
}
EXP_CATEGORIES = tuple(CATEGORY_CODES.values())
# 서류·보관 폴더에서 다르게 적히는 이름들 → 비목 번호
_CATEGORY_ALIASES = {
    "06": ["지역연계협업지원비", "지자체연계협업비용"],
    "09": ["그밖의사업운영경비", "그밖의사업운영비", "기타운영경비", "기타사업운영경비"],
}
EVIDENCE_KINDS = ("세금계산서", "계산서", "법인카드", "개인카드", "기타")
SETTLE_METHODS = ("계좌이체", "현금/지로", "수기이체", "자동이체")
# 일반청구 탭의 청구구분(name=REQ_DIV_CD, 14절) 중 세금계산서 지출에 쓰이는 것 — 사람이 고를 때 앱이 알려 주는 이름
CLAIM_DIVS = ("물품구매", "용역구매", "도서구매", "학회비", "기타")
EVIDENCE_TAXBILL = "세금계산서"
REQUIRED = ("summary", "expCategory", "evidence", "expenseDate", "amount")


def category_code(name) -> str:
    """비목 이름(어떤 표기든) → 번호. 모르면 ''."""
    key = normnm(name)
    if not key:
        return ""
    for code, canonical in CATEGORY_CODES.items():
        if key == normnm(canonical) or key in (normnm(a) for a in _CATEGORY_ALIASES.get(code, [])):
            return code
    if re.fullmatch(r"0?\d|10", key) and key.zfill(2) in CATEGORY_CODES:
        return key.zfill(2)
    return ""


def category_name(value) -> str:
    """비목 번호나 어떤 표기든 → ERP 보기 글자. 모르면 입력 그대로(사람이 고치게)."""
    code = category_code(value)
    return CATEGORY_CODES[code] if code else str(value or "").strip()


def parse_amount(value) -> int | None:
    """'51,900원' · 51900 · '51900.0' → 51900. 못 읽으면 None."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(round(value))
    text = re.sub(r"[,\s원₩]", "", str(value))
    # 소수점이 있는 글('51900.0' · '51,900.00')은 실수로 읽는다 — 숫자만 남기면 점이 빠져 10배 · 100배가 됐다(2026-10-14 점검)
    if re.fullmatch(r"-?\d+(\.\d+)?", text):
        return int(round(float(text)))
    digits = re.sub(r"[^0-9\-]", "", text)
    try:
        return int(digits)
    except ValueError:
        return None


def normalize_date(value) -> str:
    """2026.10.13 · 20261013 · 2026-10-13 · 2026년 10월 13일 → 2026-10-13. 못 읽으면 입력 그대로."""
    text = str(value or "").strip()
    # 구분자가 '년 ' · '. ' 처럼 두 글자 이상이어도 — '2026년 10월 13일' · '2026. 10. 13.'
    m = re.search(r"(\d{4})\D{0,3}?(\d{1,2})\D{0,3}?(\d{1,2})", text)
    if not m:
        return text
    y, mo, d = (int(g) for g in m.groups())
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return text
    return f"{y:04d}-{mo:02d}-{d:02d}"


def normalize(data: dict) -> dict:
    """AI 가 돌려준 dict 를 계약 모양으로 — 키를 모두 두고, 금액은 정수, 비목은 ERP 보기 글자로."""
    out = {key: data.get(key, "") for key in KEYS}
    for key in KEYS:
        if key in AMOUNT_KEYS:
            out[key] = parse_amount(data.get(key))
        elif key == "attachments":
            raw = data.get(key) or []
            out[key] = [str(x).strip() for x in (raw if isinstance(raw, list) else [raw]) if str(x).strip()]
        else:
            out[key] = str(data.get(key) or "").strip()
    out["expCategory"] = category_name(out["expCategory"])
    out["expenseDate"] = normalize_date(out["expenseDate"])
    out["approvalNo"] = normalize_approval(out["approvalNo"])
    out["receiverEmail"] = out["receiverEmail"].lower()
    out["claimDiv"] = normalize_claim_div(out["claimDiv"])
    if out["evidence"] and out["evidence"] not in EVIDENCE_KINDS:
        for kind in EVIDENCE_KINDS:
            if normnm(kind) in normnm(out["evidence"]):
                out["evidence"] = kind
                break
    if not out["settleMethod"]:
        out["settleMethod"] = "계좌이체"
    return out


def normalize_approval(text) -> str:
    """세금계산서 승인번호 — 숫자 24자리면 국세청 표기 '8-8-8' 하이픈 꼴로, 아니면 공백만 뗀 글자 그대로(모르는 꼴은 지우지 않는다)."""
    raw = str(text or "").strip()
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 24:
        return f"{digits[:8]}-{digits[8:16]}-{digits[16:]}"
    return raw.replace(" ", "")


def normalize_claim_div(text) -> str:
    """청구구분 — '(25) 물품구매(일반)' · '물품 구매' 같은 표기를 CLAIM_DIVS 의 이름으로. 모르면 입력 그대로."""
    key = normnm(text)
    if not key:
        return ""
    for name in CLAIM_DIVS:
        if normnm(name) in key:
            return name
    return str(text).strip()


def problems(data: dict) -> list[str]:
    """채우기 전에 사람이 봐야 할 점. 비어 있으면 채워도 된다."""
    found = []
    labels = {"summary": "적요", "expCategory": "비목", "evidence": "증빙구분", "expenseDate": "지출일자", "amount": "청구액"}
    for key in REQUIRED:
        value = data.get(key)
        if value is None or value == "":
            found.append(f"{labels[key]} 없음")
    if data.get("expCategory") and data["expCategory"] not in EXP_CATEGORIES:
        found.append(f"비목 '{data['expCategory']}' 은 ERP 보기에 없음")
    if data.get("evidence") and data["evidence"] not in EVIDENCE_KINDS:
        found.append(f"증빙구분 '{data['evidence']}' 은 ERP 보기에 없음")
    if data.get("settleMethod") and data["settleMethod"] not in SETTLE_METHODS:
        found.append(f"결제방법 '{data['settleMethod']}' 은 ERP 보기에 없음")
    date = data.get("expenseDate") or ""
    if date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        found.append(f"지출일자 '{date}' 형식이 YYYY-MM-DD 가 아님")
    amount, supply, tax = (data.get(k) for k in AMOUNT_KEYS)
    if amount is not None and amount <= 0:
        found.append("청구액이 0 이하")
    if amount is not None and supply is not None and tax is not None and supply + tax != amount:
        found.append(f"공급가액 {supply:,} + 부가세 {tax:,} ≠ 청구액 {amount:,}")
    acct = data.get("accountNo") or ""
    if acct and not re.fullmatch(r"[0-9\-]+", acct):
        found.append("계좌번호에 숫자·하이픈 외 글자가 있음")
    if not acct:
        found.append("계좌번호 없음 (ERP 에서 직접 넣어야 함)")
    return found


def summary_lines(data: dict) -> list[str]:
    """사람이 읽을 요약 — 확인 창 · 로그에 같은 글로."""
    def money(v):
        return f"{v:,}원" if isinstance(v, int) else "—"
    out = [
        f"적요: {data.get('summary') or '—'}",
        f"비목: {data.get('expCategory') or '—'}" + (f" / 세목: {data['expDetail']}" if data.get("expDetail") else ""),
        f"증빙: {data.get('evidence') or '—'} · 일자: {data.get('expenseDate') or '—'} · 결제: {data.get('settleMethod') or '—'}",
        f"청구액: {money(data.get('amount'))} (공급가액 {money(data.get('supplyAmount'))} · 부가세 {money(data.get('taxAmount'))})",
        f"입금처: {data.get('payeeName') or '—'}" + (f" ({data['payeeBizNo']})" if data.get("payeeBizNo") else ""),
        f"계좌: {data.get('bank') or '—'} {data.get('accountNo') or '—'} · 예금주 {data.get('owner') or '—'}",
    ]
    if data.get("approvalNo") or data.get("receiverEmail"):
        out.append("세금계산서: " + " · ".join(bit for bit in (
            f"승인번호 {data['approvalNo']}" if data.get("approvalNo") else "",
            f"수신메일 {data['receiverEmail']}" if data.get("receiverEmail") else "") if bit))
    if data.get("claimDiv"):
        out.append(f"청구종류: {data['claimDiv']}")
    if data.get("notes"):
        out.append(f"확인: {data['notes']}")
    return out
