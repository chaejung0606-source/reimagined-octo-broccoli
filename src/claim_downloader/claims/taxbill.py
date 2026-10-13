"""매입(세금)계산서 조회 팝업 — 증빙구분이 세금계산서일 때 [선택] 을 눌러 열고, 거래처 사업자번호로 조회까지 해 둔다.

실측(CLAUDE.md 14절 '세금계산서 조회 팝업', 2026-10-13): 작성 화면에서 증빙구분을 '세금계산서' 로 고르면 `[선택]`
(#onlyEvdiDivList) 이 나타나고 지출일자(#EXP_DT)는 잠긴다 — 날짜·금액·구매처는 여기서 고른 계산서로 채워진다.
팝업은 별도 창(rcomm_0033_01.act). 조회 조건 칸은 실측됐고 결과 목록의 생김새는 미실측이라 payee.ROWS_JS 로 일반적인
모양(JGM 그리드 행 · 표 본문 행)을 읽는다. 담당자 결정(2026-10-13): **확실한 것은 앱이 고르고 애매하면 사람** — 조회가 이미
사업자번호로 걸러진 뒤이므로, 청구액(또는 공급가액)이 적힌 행이 하나일 때(여럿이면 지출일자까지 맞는 행이 하나일 때) 고르고
[확인](btn_out) 을 누른 뒤 작성 화면에 계산서가 붙었는지(TAXBILL_SEQ_NO 또는 지출일자 변화) 확인한다. 설정 `claim_auto_pick` 으로 끌 수 있다.

누르는 것은 [선택](onlyEvdiDivList) · [조회](btn_inquiry) · 고른 행 · [확인](btn_out) 뿐이다. 계산서를 새로 만드는 [등록](btn_insert) ·
[세금계산서 XML 등록](btn_reg_xml) 과 거래처 돋보기(btnSupOrgCd) · [상세조회](btn_detail) 은 누르지 않는다.
Playwright 를 들여오지 않는다 — session.py 가 넘겨준 page·frame 만 쓴다.
"""
from __future__ import annotations

import datetime as dt
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .form import SET_SELECT_JS, SET_TEXT_JS, read_state
from .payee import CLICK_ID_JS, PICK_ROW_JS, RESULT_COUNT_JS, ROWS_JS, digits, open_popup, wait_closed, wait_until

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
VERIFY_IDS = ("TAXBILL_SEQ_NO", "EXP_DT", "BUY_WHERE")   # 계산서가 붙으면 바뀌는 작성 화면 칸
DAYS_BEFORE = 31                     # 조회 시작일 = 지출일자 - 31일. 계산서 발행일이 지출일보다 앞설 수 있다

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


def _has_amount(text: str, amount) -> bool:
    try:
        value = int(str(amount).replace(",", "").strip() or 0)
    except ValueError:
        return False
    if value <= 0:
        return False
    tokens = [digits(tok) for tok in str(text or "").split()]
    return f"{value:,}" in str(text or "") or str(value) in tokens


def _has_date(text: str, date: str) -> bool:
    date = str(date or "")[:10]
    if len(date) != 10:
        return False
    plain = date.replace("-", "")
    return any(form in str(text or "") for form in (date, plain, date.replace("-", "."), date[2:], plain[2:]))


def match(rows: list[dict], data: dict) -> tuple[int | None, str]:
    """결과 행 중 하나를 확실히 고를 수 있으면 (index, 근거), 아니면 (None, 이유).

    조회가 이미 사업자번호로 걸러진 뒤다. 청구액(없으면 공급가액)이 적힌 행이 하나면 그 행, 여럿이면 지출일자까지
    맞는 행이 하나일 때만. 0행·금액 없는 행뿐·여전히 여럿이면 고르지 않는다.
    """
    if not rows:
        return None, "조회 결과가 없음"
    amount = data.get("amount") or data.get("supplyAmount")
    if not amount:
        return None, "금액을 몰라 고르지 않음"
    hits = [r for r in rows if _has_amount(str(r.get("text", "")), amount) or _has_amount(str(r.get("text", "")), data.get("supplyAmount"))]
    if len(hits) == 1:
        return int(hits[0]["index"]), "금액 일치"
    if not hits:
        return None, f"{len(rows)}행 중 금액 {amount} 가 적힌 행이 없음"
    dated = [r for r in hits if _has_date(str(r.get("text", "")), data.get("expenseDate"))]
    if len(dated) == 1:
        return int(dated[0]["index"]), "금액·일자 일치"
    return None, f"금액이 같은 행이 {len(hits)}개 — 어느 것인지 애매함"


def pick(popup, frame, data: dict, log: Callable[[str], None], wait: Callable[[float], None] = time.sleep) -> tuple[bool, str]:
    """조회 결과에서 확실한 행을 골라 [확인] 을 누르고 작성 화면에 계산서가 붙었는지 본다. (골랐나, 근거/이유)."""
    try:
        listing = popup.evaluate(ROWS_JS)
    except Exception as error:  # noqa: BLE001
        return False, "결과 목록을 읽지 못함: " + (str(error).splitlines()[0][:80] if str(error) else "")
    index, why = match(list(listing.get("rows") or []), data)
    if index is None:
        log("세금계산서 자동 선택 안 함: " + why)
        return False, why
    before = {k: (v or {}).get("value", "") for k, v in read_state(frame, list(VERIFY_IDS)).items()}
    chosen = popup.evaluate(PICK_ROW_JS, index)
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
    digits = re.sub(r"\D", "", str(data.get("payeeBizNo") or ""))
    if len(digits) == 10:
        return digits
    return str(data.get("payeeName") or "").strip()


def start_date_for(data: dict, today: dt.date | None = None) -> str:
    """조회 시작일 — 지출일자 31일 전. 지출일자를 모르면 빈 글(팝업 기본값 그대로)."""
    text = str(data.get("expenseDate") or "")
    try:
        day = dt.date.fromisoformat(text[:10])
    except ValueError:
        return ""
    return (day - dt.timedelta(days=DAYS_BEFORE)).isoformat()


def search(page, frame, data: dict, log: Callable[[str], None],
           wait: Callable[[float], None] = time.sleep, messages: list[str] | None = None,
           auto_pick: bool = True) -> TaxbillReport:
    """[선택] 을 눌러 팝업을 열고(이미 열려 있으면 그것을 씀) 공급자 사업자번호·기간을 넣어 [조회] 를 누른다.
    auto_pick 이면 결과가 하나로 확실할 때 골라 [확인] 까지 누른다(pick)."""
    messages = messages if messages is not None else []
    query = query_for(data)
    report = TaxbillReport(ok=False, query=query, messages=messages)
    if not query:
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
        if query.isdigit():
            chosen = popup.evaluate(SET_SELECT_JS, [SELLER_SELECT_ID, SELLER_OPTION])
            if not chosen.get("ok"):
                report.note = "조회 구분을 공급자 사업자번호로 바꾸지 못했습니다: " + str(chosen.get("why", ""))
                return report
            typed = popup.evaluate(SET_TEXT_JS, [BIZNO_TEXT_ID, query])
        else:
            typed = popup.evaluate(SET_TEXT_JS, [NAME_TEXT_ID, query])
        if not typed.get("ok"):
            report.note = "조회 조건을 넣지 못했습니다: " + str(typed.get("why", ""))
            return report
        start = start_date_for(data)
        if start:
            dated = popup.evaluate(SET_TEXT_JS, [START_DATE_ID, start])
            if not dated.get("ok"):
                log("세금계산서 팝업: 조회 시작일을 넣지 못해 기본 기간으로 조회합니다")
        clicked = popup.evaluate(CLICK_ID_JS, INQUIRY_BUTTON_ID)
        if not clicked.get("ok"):
            report.note = "[조회] 를 누르지 못했습니다: " + str(clicked.get("why", ""))
            return report
        wait(1.5)
        try:
            counted = popup.evaluate(RESULT_COUNT_JS)
            report.rows = int(counted.get("rows")) if counted.get("kind") != "unknown" else None
        except Exception:  # noqa: BLE001
            report.rows = None
        report.ok = True
        log("세금계산서 조회: '%s' (%s~) → %s" % (query, start or "기본", f"{report.rows}행" if report.rows is not None else "결과 수 모름"))
        if auto_pick:
            report.picked, report.pick_note = pick(popup, frame, data, log, wait)
        return report
    finally:
        try:
            popup.remove_listener("dialog", on_dialog)
        except Exception:  # noqa: BLE001
            pass
