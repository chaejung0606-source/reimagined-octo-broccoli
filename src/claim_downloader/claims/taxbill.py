"""매입(세금)계산서 조회 팝업 — 증빙구분이 세금계산서일 때 [선택] 을 눌러 열고, 내 계산서수신메일·거래처 사업자번호로 조회해 둔다.

실측(CLAUDE.md 14절 '세금계산서 조회 팝업', 2026-10-13): 작성 화면에서 증빙구분을 '세금계산서' 로 고르면 `[선택]`
(#onlyEvdiDivList) 이 나타나고 지출일자(#EXP_DT)는 잠긴다 — 날짜·금액·구매처는 여기서 고른 계산서로 채워진다.
팝업은 별도 창(rcomm_0033_01.act). 결과는 같은 프레임의 JGM 그리드(행마다 라디오 radioJGM4)이고 열은 k_SELR_CORP_NO(공급자
사업자번호, 하이픈 형식) · k_TOTL_AMT(합계) · k_CHRG_AMT(공급가액) · k_REGS_DATE(작성일자) · k_INQ_REQ_BAL_AMT(아직 청구 안 된 잔액) ·
k_BUYR_CHRG_EMAIL1(수신메일). **목록에는 산학협력단 전체 계산서가 다 뜬다** — 담당자(2026-10-13): 계산서수신메일(#self_enter 체크 →
#TAX_RCV_EMAIL_V)에 내 메일을 넣고 조회해야 내 건만 보인다. 메일은 사용자별 값이라 설정(taxbill_email)에 둔다.

담당자 결정(2026-10-13): **확실한 것은 앱이 고르고 애매하면 사람**. 열 값으로 공급자 사업자번호가 같고 합계(또는 공급가액)가 같은 행이
하나일 때(여럿이면 수신메일·작성일자까지 맞는 행이 하나일 때) 고르고 [확인](btn_out) 을 누른 뒤 작성 화면에 계산서가 붙었는지
(TAXBILL_SEQ_NO 또는 지출일자 변화) 확인한다. 이미 다 청구된 계산서(잔액 0)는 후보에서 뺀다. 설정 `claim_auto_pick` 으로 끌 수 있다.

누르는 것은 [선택](onlyEvdiDivList) · 계산서수신메일 체크(self_enter) · [조회](btn_inquiry) · 고른 행 · [확인](btn_out) 뿐이다.
계산서를 새로 만드는 [등록](btn_insert) · [세금계산서 XML 등록](btn_reg_xml) 과 거래처 돋보기(btnSupOrgCd) · [상세조회](btn_detail) 은
누르지 않는다. Playwright 를 들여오지 않는다 — session.py 가 넘겨준 page·frame 만 쓴다.
"""
from __future__ import annotations

import datetime as dt
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .form import SET_SELECT_JS, SET_TEXT_JS, read_state
from .payee import CLICK_ID_JS, PICK_ROW_JS, ROWS_JS, count_rows, digits, open_popup, wait_closed, wait_rows, wait_until

SELECT_LINK_ID = "onlyEvdiDivList"   # 작성 화면의 [선택] — 증빙구분이 세금계산서일 때만 보인다
INQUIRY_BUTTON_ID = "btn_inquiry"    # 팝업의 [조회]
SELLER_SELECT_ID = "SELR_CORP"       # 공급자(거래처)사업자등록번호 | (공급받는자)사업자번호
SELLER_OPTION = "공급자"
BIZNO_TEXT_ID = "CORP_TXT"
NAME_TEXT_ID = "CORP_NM"             # (거래처명/승인번호)
START_DATE_ID = "START_DATE"
END_DATE_ID = "END_DATE"
EVIDENCE_TAXBILL = "세금계산서"
CONFIRM_BUTTON_ID = "btn_out"        # 고른 계산서를 작성 화면으로 넘기는 [확인]
# 절대 누르지 않는다.
FORBIDDEN_IDS = ("btn_insert", "btn_reg_xml", "btnSupOrgCd", "btn_detail")
FORBIDDEN_TEXTS = ("등록", "세금계산서 XML 등록", "상세조회")
ALLOWED_CLICK_IDS = frozenset({SELECT_LINK_ID, INQUIRY_BUTTON_ID, CONFIRM_BUTTON_ID})

# 체크박스 하나를 켠다(이미 켜져 있으면 그대로). EMAIL_CHECK_ID 로만 부른다 — tests/test_safety.py 가 본다.
CHECK_BOX_JS = """(id) => {
  const el = document.getElementById(id);
  if (!el) return {ok: false, why: '체크 칸이 없음'};
  if (el.disabled) return {ok: false, why: '비활성'};
  if (!el.checked) el.click();
  return {ok: true, checked: !!el.checked};
}"""
VERIFY_IDS = ("TAXBILL_SEQ_NO", "EXP_DT", "BUY_WHERE")   # 계산서가 붙으면 바뀌는 작성 화면 칸
DAYS_BEFORE = 31                     # 조회 시작일은 늦어도 지출일자 - 31일. 팝업 기본(3개월)보다 좁히지는 않는다
EMAIL_CHECK_ID = "self_enter"        # '계산서수신메일' 체크 — 켜면 아래 칸에 메일을 넣을 수 있다(실측 2026-10-13)
EMAIL_TEXT_ID = "TAX_RCV_EMAIL_V"    # 계산서수신메일 — 내 메일을 넣고 조회하면 내 건만 보인다(담당자 설명)
# 결과 그리드의 열(실측 2026-10-13). 값은 셀의 title(콤마 없는 숫자) 우선.
COL_SELLER_NO = "k_SELR_CORP_NO"     # 공급자 사업자번호 '578-86-00021' 형식
COL_SELLER_NM = "k_SELR_CORP_NM"
COL_TOTAL = "k_TOTL_AMT"             # 합계(공급가액+세액)
COL_SUPPLY = "k_CHRG_AMT"            # 공급가액
COL_DATE = "k_REGS_DATE"             # 작성일자 'YYYY-MM-DD'
COL_BALANCE = "k_INQ_REQ_BAL_AMT"    # 아직 청구되지 않은 잔액 — 0 이면 이미 다 청구된 계산서
COL_EMAIL = "k_BUYR_CHRG_EMAIL1"     # 공급받는자 담당 메일(계산서수신메일)
LONG_LIST = 25                       # JGM 가상 스크롤 — 이보다 길면 화면 밖 행은 DOM 에 없어 못 읽었을 수 있다

POPUP_PROBE_JS = """() => !!(document.querySelector('#SELR_CORP') && document.querySelector('#CORP_TXT')
  && document.querySelector('#btn_inquiry') && document.querySelector('#btn_out'))"""

# 작성 화면에 [선택] 이 보이는지 — 증빙구분이 세금계산서가 아니면 숨어 있다
LINK_VISIBLE_JS = """(id) => {
  const el = document.getElementById(id);
  if (!el) return false;
  const r = el.getBoundingClientRect();
  return r.width > 0 && r.height > 0;
}"""


@dataclass
class TaxbillReport:
    ok: bool
    query: str = ""
    rows: int | None = None
    messages: list[str] = field(default_factory=list)
    note: str = ""
    picked: bool = False               # 앱이 골라 [확인] 까지 누르고 작성 화면에 붙은 것을 확인함
    pick_note: str = ""

    def lines(self) -> list[str]:
        if self.ok and self.picked:
            out = [f"✓ 세금계산서: 계산서를 골라 [확인] 까지 눌렀습니다 ({self.pick_note})"]
        elif self.ok:
            found = f"결과 {self.rows}행" if self.rows is not None else "결과 수는 세지 못함"
            why = f" — {self.pick_note}" if self.pick_note else ""
            out = [f"✓ 세금계산서 팝업: '{self.query}' 로 조회함 — {found}{why}. 목록에서 계산서를 고르고 [확인] 을 눌러 주세요"]
        else:
            out = [f"✗ 세금계산서 팝업: {self.note or '열지 못함'} — 증빙 [선택] 을 직접 눌러 골라 주세요"]
        out.extend("· 팝업 알림: " + m for m in self.messages)
        return out


def _num(text) -> int | None:
    """셀 값 → 정수. '726,000' · '726000' · '' 를 다룬다. 숫자가 아니면 None."""
    raw = str(text if text is not None else "").replace(",", "").strip()
    if not raw or not re.fullmatch(r"-?\d+(\.0+)?", raw):
        return None
    return int(float(raw))


def _has_amount(text: str, amount) -> bool:
    value = _num(amount)
    if not value:
        return False
    tokens = [digits(tok) for tok in str(text or "").split()]
    return f"{value:,}" in str(text or "") or str(value) in tokens


def _has_date(text: str, date: str) -> bool:
    date = str(date or "")[:10]
    if len(date) != 10:
        return False
    plain = date.replace("-", "")
    return any(form in str(text or "") for form in (date, plain, date.replace("-", "."), date[2:], plain[2:]))


def _row_text(row: dict) -> str:
    return str(row.get("text", "")) + " " + str(row.get("titles", ""))


def _amount_hit(row: dict, amount, supply) -> bool:
    """열(합계·공급가액)이 있으면 그 값으로, 없으면(모양이 다른 목록) 행 글자로 금액을 맞춘다."""
    cells = row.get("cells") or {}
    if COL_TOTAL in cells or COL_SUPPLY in cells:
        total, sup = _num(cells.get(COL_TOTAL)), _num(cells.get(COL_SUPPLY))
        want, want_sup = _num(amount), _num(supply)
        return bool(want and want == total) or bool(want_sup and want_sup == sup) or bool(want and want == sup and not total)
    return _has_amount(_row_text(row), amount) or _has_amount(_row_text(row), supply)


def _date_hit(row: dict, date) -> bool:
    cells = row.get("cells") or {}
    if COL_DATE in cells:
        return str(cells.get(COL_DATE) or "")[:10].replace(".", "-") == str(date or "")[:10]
    return _has_date(_row_text(row), date)


def match(rows: list[dict], data: dict, email: str = "") -> tuple[int | None, str]:
    """결과 행 중 하나를 확실히 고를 수 있으면 (index, 근거), 아니면 (None, 이유).

    ① 공급자 사업자번호 열이 있고 서류의 사업자번호를 알면 그 번호가 같은 행만 남긴다(없으면 사람).
    ② 이미 다 청구된 계산서(잔액 0)는 뺀다. ③ 합계(없으면 공급가액)가 같은 행이 하나면 그 행.
    ④ 여럿이면 수신메일이 내 것인 행 하나 → 작성일자가 지출일자인 행 하나. 그래도 여럿이거나 0행이면 고르지 않는다.
    """
    if not rows:
        return None, "조회 결과가 없음"
    amount = data.get("amount") or data.get("supplyAmount")
    if not _num(amount):
        return None, "금액을 몰라 고르지 않음"
    cand = list(rows)
    basis = []
    biz = digits(data.get("payeeBizNo"))
    if len(biz) == 10 and any(COL_SELLER_NO in (r.get("cells") or {}) for r in cand):
        cand = [r for r in cand if digits((r.get("cells") or {}).get(COL_SELLER_NO)) == biz]
        if not cand:
            return None, f"{len(rows)}행 중 공급자 사업자번호가 서류와 같은 행이 없음"
        basis.append("사업자번호")
    unclaimed = [r for r in cand if _num((r.get("cells") or {}).get(COL_BALANCE)) != 0]
    if cand and not unclaimed:
        return None, "맞는 계산서가 이미 모두 청구됨(잔액 0)"
    if len(unclaimed) < len(cand):
        cand = unclaimed
    hits = [r for r in cand if _amount_hit(r, amount, data.get("supplyAmount"))]
    if not hits:
        tail = " (목록이 길어 다 읽지 못했을 수 있음)" if len(rows) >= LONG_LIST else ""
        return None, f"{len(cand)}행 중 금액 {_num(amount):,} 이 적힌 행이 없음{tail}"
    basis.append("금액")
    if len(hits) == 1:
        return int(hits[0]["index"]), "·".join(basis) + " 일치"
    mail = str(email or "").strip().lower()
    if mail:
        mine = [r for r in hits if mail in ((r.get("cells") or {}).get(COL_EMAIL, "") + " " + _row_text(r)).lower()]
        if len(mine) == 1:
            return int(mine[0]["index"]), "·".join(basis) + "·수신메일 일치"
        hits = mine or hits
    dated = [r for r in hits if _date_hit(r, data.get("expenseDate"))]
    if len(dated) == 1:
        return int(dated[0]["index"]), "·".join(basis) + "·일자 일치"
    return None, f"금액이 같은 행이 {len(hits)}개 — 어느 것인지 애매함"


def pick(popup, frame, data: dict, log: Callable[[str], None], wait: Callable[[float], None] = time.sleep,
         email: str = "") -> tuple[bool, str]:
    """조회 결과에서 확실한 행을 골라 [확인] 을 누르고 작성 화면에 계산서가 붙었는지 본다. (골랐나, 근거/이유)."""
    _, where = count_rows(popup)
    try:
        listing = where.evaluate(ROWS_JS)
    except Exception as error:  # noqa: BLE001
        return False, "결과 목록을 읽지 못함: " + (str(error).splitlines()[0][:80] if str(error) else "")
    index, why = match(list(listing.get("rows") or []), data, email)
    if index is None:
        log("세금계산서 자동 선택 안 함: " + why)
        return False, why
    before = {k: (v or {}).get("value", "") for k, v in read_state(frame, list(VERIFY_IDS)).items()}
    chosen = where.evaluate(PICK_ROW_JS, index)
    if not chosen.get("ok"):
        return False, "행을 고르지 못함: " + str(chosen.get("why", ""))
    wait(0.3)
    confirmed = popup.evaluate(CLICK_ID_JS, CONFIRM_BUTTON_ID)
    if not confirmed.get("ok"):
        return False, "[확인] 을 누르지 못함: " + str(confirmed.get("why", ""))
    wait_closed(popup, wait, seconds=10)
    after = {k: (v or {}).get("value", "") for k, v in read_state(frame, list(VERIFY_IDS)).items()}
    if after.get("TAXBILL_SEQ_NO") or any(after.get(k) != before.get(k) for k in VERIFY_IDS):
        log("세금계산서 자동 선택: %s (지출일자 %s)" % (why, after.get("EXP_DT") or "?"))
        return True, why
    return False, "[확인] 을 눌렀지만 작성 화면에 계산서가 붙지 않음 — 직접 골라 주세요"


def wanted(data: dict) -> bool:
    """증빙구분이 세금계산서인 건만."""
    return EVIDENCE_TAXBILL in str(data.get("evidence") or "").replace(" ", "")


def query_for(data: dict) -> str:
    """조회 조건 — 공급자 사업자등록번호(숫자 10자리). 없으면 거래처 이름."""
    number = digits(data.get("payeeBizNo"))
    if len(number) == 10:
        return number
    return str(data.get("payeeName") or "").strip()


def bizno_forms(number: str) -> list[str]:
    """사업자번호를 넣어 볼 형식들 — 숫자만, 그다음 그리드가 보여 주는 '578-86-00021' 형식. 어느 쪽을 받는지 미실측."""
    number = digits(number)
    if len(number) != 10:
        return []
    return [number, f"{number[:3]}-{number[3:5]}-{number[5:]}"]


def start_date_for(data: dict, default: str = "") -> str:
    """조회 시작일 — 지출일자 31일 전과 팝업 기본 시작일 중 **이른** 쪽. 좁히면 계산서를 놓치고, 넓혀도 금액·사업자번호로 고른다.
    지출일자를 모르면 빈 글(기본값 그대로)."""
    text = str(data.get("expenseDate") or "")
    try:
        day = dt.date.fromisoformat(text[:10])
    except ValueError:
        return ""
    wanted_start = (day - dt.timedelta(days=DAYS_BEFORE)).isoformat()
    try:
        base = dt.date.fromisoformat(str(default or "")[:10]).isoformat()
    except ValueError:
        return wanted_start
    return min(base, wanted_start)


def _inquire(popup, wait, log, label: str) -> int | None:
    """[조회] 를 누르고 결과가 올 때까지 기다린 뒤 행 수(못 세면 None)."""
    clicked = popup.evaluate(CLICK_ID_JS, INQUIRY_BUTTON_ID)
    if not clicked.get("ok"):
        raise RuntimeError("[조회] 를 누르지 못했습니다: " + str(clicked.get("why", "")))
    rows, _ = wait_rows(popup, wait)
    log("세금계산서 조회: %s → %s" % (label, f"{rows}행" if rows is not None else "결과 수 모름"))
    return rows


def search(page, frame, data: dict, log: Callable[[str], None],
           wait: Callable[[float], None] = time.sleep, messages: list[str] | None = None,
           auto_pick: bool = True, email: str = "") -> TaxbillReport:
    """[선택] 을 눌러 팝업을 열고(이미 열려 있으면 그것을 씀) 계산서수신메일(email) · 공급자 사업자번호 · 기간을 넣어 [조회] 를 누른다.

    사업자번호는 숫자만 → 하이픈 형식 차례로 넣어 보고(어느 형식을 받는지 미실측), 둘 다 0행이고 메일이 있으면 번호를 비우고
    메일로만 한 번 더 조회해 사람이 볼 목록을 남긴다. auto_pick 이면 결과가 하나로 확실할 때 골라 [확인] 까지 누른다(pick).
    """
    messages = messages if messages is not None else []
    email = str(email or "").strip()
    query = query_for(data)
    report = TaxbillReport(ok=False, query=query, messages=messages)
    if not query and not email:
        report.note = "거래처 사업자번호도 이름도 없습니다"
        return report
    try:
        if frame.evaluate(LINK_VISIBLE_JS, SELECT_LINK_ID) is not True:
            report.note = "증빙 [선택] 이 보이지 않습니다 — 증빙구분이 세금계산서인지 확인하세요"
            log("세금계산서 팝업: " + report.note)
            return report
    except Exception as error:  # noqa: BLE001
        report.note = "작성 화면을 읽지 못했습니다: " + (str(error).splitlines()[0][:80] if str(error) else "")
        return report
    popup, why = open_popup(page, frame, SELECT_LINK_ID, POPUP_PROBE_JS, log)
    if popup is None:
        report.note = why
        log("세금계산서 팝업: " + why)
        return report
    log("세금계산서 조회 팝업을 열었습니다")

    def on_dialog(dialog) -> None:
        messages.append(dialog.message.strip())
        log("세금계산서 팝업 알림: %s" % dialog.message.strip())
        try:
            dialog.accept()
        except Exception:  # noqa: BLE001
            pass

    popup.on("dialog", on_dialog)
    try:
        if not wait_until(lambda: popup.evaluate(POPUP_PROBE_JS) is True, wait, tries=40):
            report.note = "팝업이 세금계산서 조회 화면이 아닙니다"
            return report
        mailed = False
        if email:
            box = popup.evaluate(CHECK_BOX_JS, EMAIL_CHECK_ID)
            wait(0.3)                                   # 체크의 처리기가 메일 칸을 연다
            typed = popup.evaluate(SET_TEXT_JS, [EMAIL_TEXT_ID, email]) if box.get("ok") else box
            mailed = bool(typed.get("ok"))
            if not mailed:
                log("세금계산서 팝업: 계산서수신메일을 넣지 못해(%s) 메일 없이 조회합니다" % typed.get("why", ""))
        try:
            current = (read_state(popup, [START_DATE_ID]).get(START_DATE_ID) or {}).get("value", "")
        except Exception:  # noqa: BLE001 — 못 읽으면 기본 기간을 모른 채로
            current = ""
        start = start_date_for(data, current)
        if start and start != current:
            dated = popup.evaluate(SET_TEXT_JS, [START_DATE_ID, start])
            if not dated.get("ok"):
                log("세금계산서 팝업: 조회 시작일을 넣지 못해 기본 기간으로 조회합니다")
        period = start or current or "기본"
        attempts = bizno_forms(query) if query.isdigit() else ([query] if query else [])
        if attempts and query.isdigit():
            chosen = popup.evaluate(SET_SELECT_JS, [SELLER_SELECT_ID, SELLER_OPTION])
            if not chosen.get("ok"):
                report.note = "조회 구분을 공급자 사업자번호로 바꾸지 못했습니다: " + str(chosen.get("why", ""))
                return report
        rows = None
        for text in attempts:
            typed = popup.evaluate(SET_TEXT_JS, [BIZNO_TEXT_ID if query.isdigit() else NAME_TEXT_ID, text])
            if not typed.get("ok"):
                report.note = "조회 조건을 넣지 못했습니다: " + str(typed.get("why", ""))
                return report
            report.query = text
            rows = _inquire(popup, wait, log, "'%s'%s (%s~)" % (text, " + 수신메일" if mailed else "", period))
            if rows:
                break
        if not rows and mailed and query.isdigit():
            popup.evaluate(SET_TEXT_JS, [BIZNO_TEXT_ID, ""])      # 번호를 비우고 메일로만 — 사람이 볼 목록이라도 남긴다
            report.query = email
            rows = _inquire(popup, wait, log, "수신메일만 (%s~)" % period)
        elif not attempts:
            report.query = email
            rows = _inquire(popup, wait, log, "수신메일만 (%s~)" % period)
        report.rows = rows
        report.ok = True
        if auto_pick and not (query or mailed):
            # 사업자번호 · 거래처명 · 수신메일 어느 것으로도 좁히지 못한 목록은 산학협력단 전체 계산서다 — 금액만 맞는 남의 계산서를
            # 고를 수 있어 고르지 않는다(2026-10-14 점검)
            report.pick_note = "사업자번호 · 거래처명 · 수신메일 없이 조회한 목록이라 고르지 않음"
            log("세금계산서 자동 선택 안 함: " + report.pick_note)
        elif auto_pick:
            report.picked, report.pick_note = pick(popup, frame, data, log, wait, email)
        return report
    except RuntimeError as error:
        report.note = str(error)
        return report
    finally:
        try:
            popup.remove_listener("dialog", on_dialog)
        except Exception:  # noqa: BLE001
            pass
