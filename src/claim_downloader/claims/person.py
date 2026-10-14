"""소득자 찾기 — 인건비(소득성 경비) 탭의 소득자 돋보기 팝업에서 학생(인적정보) · 참여인력을 이름으로 검색해 학번/사번이 맞는 행을 고른다.

실측(CLAUDE.md 14절 '장학금' ④ · 참여인력 탭, 2026-10-14): 입금처조회 팝업(rexpe_0084_rcv_pop.act)과 같은 창인데 인건비 탭에서 열면
구분 라디오가 참여인력 · 인적정보 둘이다. 검색은 `#SEARCH_NM`(성명) + [검색](`btn_search`), 결과는 같은 프레임의 JGM 그리드
(열 `k_EMP_NO` 학번/사번 · `k_EMP_NM` 이름). **같은 이름이 두 행** 나온 적이 있어 이름만으로는 고르지 않는다 — 명단의 학번(9자리)
또는 사번(6자리)이 `k_EMP_NO` 와 같은 행이 **하나**일 때만 고르고 [확인] 을 누른다. 인적정보 탭의 [확인] 은 `btn_s_confirm3`,
참여인력 탭은 `btn_s_confirm4`. 고른 뒤 작성 화면 `#RCV_CD` 에 그 학번이 들어왔는지 본다 — 아니면 사람에게.

누르는 것은 돋보기 · 구분 라디오 · [검색] · 고른 행 · [확인] 뿐이다('외부인 등록' 은 절대 아니다 — tests/test_safety.py).
JS 는 payee.py 의 것을 빌려 쓴다. Playwright 를 들여오지 않는다.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .form import SET_TEXT_JS, read_state
from .payee import (
    CHECK_DIV_JS,
    CLICK_ID_JS,
    DIV_RADIO_NAME,
    OPEN_BUTTON_ID,
    PICK_ROW_JS,
    ROWS_JS,
    SEARCH_BUTTON_ID,
    count_rows,
    open_popup,
    wait_closed,
    wait_rows,
    wait_until,
)

SEARCH_NAME_ID = "SEARCH_NM"             # 성명 칸 (참여인력 · 인적정보 탭 공통)
COL_NO = "k_EMP_NO"                      # 학번(9자리) / 사번(6자리)
COL_NAME = "k_EMP_NM"
TAB_STUDENT = "인적정보"                   # 장학생 — 학번
TAB_STAFF = "참여인력"                     # 참여인력 명단의 사번
CONFIRM_IDS = {TAB_STUDENT: "btn_s_confirm3", TAB_STAFF: "btn_s_confirm4"}
FORBIDDEN_TEXTS = ("외부인 등록", "선택없음")

# 인건비 탭에서 연 소득자 팝업 알아보기 — 구분 라디오 + 성명 칸 + (인적정보 또는 참여인력의) [확인]
POPUP_PROBE_JS = """() => !!(document.querySelector('input[name=RCV_DIV_CD]') && document.querySelector('#SEARCH_NM')
  && (document.querySelector('#btn_s_confirm3') || document.querySelector('#btn_s_confirm4')))"""


@dataclass
class PersonReport:
    ok: bool
    name: str = ""
    student_no: str = ""
    tab: str = TAB_STUDENT
    rows: int | None = None
    messages: list[str] = field(default_factory=list)
    note: str = ""
    picked: bool = False
    pick_note: str = ""
    chosen_no: str = ""                 # 작성 화면에 들어간 학번/사번

    def lines(self) -> list[str]:
        if self.ok and self.picked:
            return [f"✓ 소득자: {self.name}({self.chosen_no}) 를 골라 [확인] 까지 눌렀습니다 ({self.pick_note})"]
        if self.ok:
            found = f"결과 {self.rows}행" if self.rows is not None else "결과 수는 세지 못함"
            why = f" — {self.pick_note}" if self.pick_note else ""
            return [f"소득자 팝업: '{self.name}' 으로 검색함 — {found}{why}. 목록에서 고르고 [확인] 을 눌러 주세요"]
        return [f"✗ 소득자 팝업: {self.note or '열지 못함'} — 돋보기를 직접 눌러 골라 주세요"]


def match(rows: list[dict], name: str, student_no: str) -> tuple[int | None, str]:
    """`k_EMP_NO` 가 학번과 같은 행이 하나면 (index, 근거). 아니면 (None, 이유). 학번이 없으면 고르지 않는다."""
    if not rows:
        return None, "검색 결과가 없음"
    want = "".join(ch for ch in str(student_no or "") if ch.isdigit())
    if not want:
        return None, "명단에 학번이 없어 고르지 않음"
    hits = []
    for row in rows:
        cells = row.get("cells") or {}
        no = "".join(ch for ch in str(cells.get(COL_NO, "")) if ch.isdigit())
        if not no:
            # 열 이름이 다른 목록 — 행 글자 토큰 중 숫자만 같은 것이 있는지
            tokens = ["".join(ch for ch in t if ch.isdigit()) for t in str(row.get("text", "")).split()]
            if want in tokens:
                hits.append(row)
            continue
        if no == want:
            hits.append(row)
    if len(hits) == 1:
        row = hits[0]
        got = str((row.get("cells") or {}).get(COL_NAME, "")).replace(" ", "")
        if got and name and got != name.replace(" ", ""):
            return None, f"학번은 같은데 이름이 다름 (목록: {got})"
        return int(row["index"]), "학번 일치"
    if not hits:
        return None, f"{len(rows)}행 중 학번 {want} 인 행이 없음"
    return None, f"학번이 같은 행이 {len(hits)}개"


def pick(popup, frame, name: str, student_no: str, confirm_id: str, log: Callable[[str], None],
         wait: Callable[[float], None] = time.sleep) -> tuple[bool, str, str]:
    """확실한 행을 골라 [확인] 을 누르고 작성 화면의 소득자 코드(RCV_CD)가 학번으로 채워졌는지 본다."""
    _, where = count_rows(popup)
    try:
        listing = where.evaluate(ROWS_JS)
    except Exception as error:  # noqa: BLE001
        return False, "결과 목록을 읽지 못함: " + (str(error).splitlines()[0][:80] if str(error) else ""), ""
    index, why = match(list(listing.get("rows") or []), name, student_no)
    if index is None:
        log("소득자 자동 선택 안 함: " + why)
        return False, why, ""
    chosen = where.evaluate(PICK_ROW_JS, index)
    if not chosen.get("ok"):
        return False, "행을 고르지 못함: " + str(chosen.get("why", "")), ""
    wait(0.3)
    confirmed = popup.evaluate(CLICK_ID_JS, confirm_id)
    if not confirmed.get("ok"):
        return False, "[확인] 을 누르지 못함: " + str(confirmed.get("why", "")), ""
    wait_closed(popup, wait, seconds=10)
    wait(0.3)
    state = read_state(frame, ["RCV_CD", "RCV_NM"])
    got_no = "".join(ch for ch in (state.get("RCV_CD") or {}).get("value", "") if ch.isdigit())
    got_name = (state.get("RCV_NM") or {}).get("value", "")
    if got_no and got_no == "".join(ch for ch in student_no if ch.isdigit()):
        log("소득자 자동 선택: %s(%s) — %s" % (got_name or name, got_no, why))
        return True, why, got_no
    return False, "[확인] 을 눌렀지만 작성 화면의 소득자가 바뀌지 않음 — 직접 골라 주세요", got_no


def search(page, frame, name: str, student_no: str, log: Callable[[str], None],
           wait: Callable[[float], None] = time.sleep, messages: list[str] | None = None,
           tab: str = TAB_STUDENT, auto_pick: bool = True) -> PersonReport:
    """돋보기 → 구분(인적정보/참여인력) → 성명 → [검색]. auto_pick 이면 학번이 맞는 행 하나를 골라 [확인] 까지."""
    messages = messages if messages is not None else []
    report = PersonReport(ok=False, name=name, student_no=student_no, tab=tab, messages=messages)
    if not name:
        report.note = "이름이 없습니다"
        return report
    confirm_id = CONFIRM_IDS.get(tab)
    if confirm_id is None:
        report.note = f"모르는 구분 '{tab}'"
        return report
    popup, why = open_popup(page, frame, OPEN_BUTTON_ID, POPUP_PROBE_JS, log)
    if popup is None:
        report.note = why
        log("소득자 팝업: " + why)
        return report

    def on_dialog(dialog) -> None:
        messages.append(dialog.message.strip())
        log("소득자 팝업 알림: %s" % dialog.message.strip())
        try:
            dialog.accept()
        except Exception:  # noqa: BLE001
            pass

    popup.on("dialog", on_dialog)
    try:
        if not wait_until(lambda: popup.evaluate(POPUP_PROBE_JS) is True, wait, tries=40):
            report.note = "팝업이 소득자 조회 화면이 아닙니다"
            return report
        div = popup.evaluate(CHECK_DIV_JS, [DIV_RADIO_NAME, tab])
        if not div.get("ok"):
            report.note = f"구분을 '{tab}' 로 바꾸지 못했습니다: " + str(div.get("why", ""))
            return report
        if not div.get("same"):
            wait(0.5)                                    # 탭이 바뀌며 칸이 다시 그려진다
        typed = popup.evaluate(SET_TEXT_JS, [SEARCH_NAME_ID, name])
        if not typed.get("ok"):
            report.note = "성명을 넣지 못했습니다: " + str(typed.get("why", ""))
            return report
        clicked = popup.evaluate(CLICK_ID_JS, SEARCH_BUTTON_ID)
        if not clicked.get("ok"):
            report.note = "[검색] 을 누르지 못했습니다: " + str(clicked.get("why", ""))
            return report
        report.rows, _ = wait_rows(popup, wait)
        report.ok = True
        log("소득자 검색(%s): '%s' → %s" % (tab, name, f"{report.rows}행" if report.rows is not None else "결과 수 모름"))
        if auto_pick:
            report.picked, report.pick_note, report.chosen_no = pick(popup, frame, name, student_no, confirm_id, log, wait)
        return report
    finally:
        try:
            popup.remove_listener("dialog", on_dialog)
        except Exception:  # noqa: BLE001
            pass
