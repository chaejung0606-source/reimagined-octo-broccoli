"""소득자 찾기 — 인건비(소득성 경비) 탭의 소득자 돋보기 팝업에서 학생(인적정보) · 참여인력을 이름으로 검색해 학번/사번이 맞는 행을 고른다.

실측(CLAUDE.md 14절 '장학금' ④ · 참여인력 탭, 2026-10-14): 입금처조회 팝업(rexpe_0084_rcv_pop.act)과 같은 창인데 인건비 탭에서 열면
구분 라디오가 참여인력 · 인적정보 둘이다. 검색은 `#SEARCH_NM`(성명) + [검색](`btn_search`), 결과는 같은 프레임의 JGM 그리드
(열 `k_EMP_NO` 학번/사번 · `k_EMP_NM` 이름). **같은 이름이 두 행** 나온 적이 있어 이름만으로는 고르지 않는다 — 명단의 학번(9자리)
또는 사번(6자리)이 `k_EMP_NO` 와 같은 행이 **하나**일 때만 고르고 [확인] 을 누른다. 인적정보 탭의 [확인] 은 `btn_s_confirm3`,
참여인력 탭은 `btn_s_confirm4`. 고른 뒤 작성 화면 `#RCV_CD` 에 그 학번이 들어왔는지 본다 — 아니면 사람에게.

검색어는 **학번/사번 먼저**, 결과가 없으면 이름(담당자 요청 2026-10-14). 실제 ERP 에서 흔한 이름('김형준')을 검색하자 결과가
21행만 읽혀 그 아래에 있던 학번을 못 찾았다(18:10) — JGM 그리드는 보이는 줄 근처만 그린다(CLAUDE.md 7절 함정 2). 인적정보 탭의 검색 칸
라벨은 '성명' 이 아니라 '검색' 이라 학번을 받을 것으로 보지만(추정 — 참여인력 탭은 '성명') 실측은 아직이다. 그래서 학번으로 0행이면
이름으로 다시 검색하고, 이름 결과에서 학번이 안 보이면 목록을 위에서부터 내려가며(스크롤 — 누르지 않는다) 끝까지 찾는다.

누르는 것은 돋보기 · 구분 라디오 · [검색] · 고른 행 · [확인] 뿐이다('외부인 등록' 은 절대 아니다 — tests/test_safety.py).
JS 는 payee.py 의 것을 빌려 쓴다. Playwright 를 들여오지 않는다.
"""
from __future__ import annotations

import re
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

# 결과 그리드 스크롤 — 누르지 않는다. 'info' 는 위치만 읽고, 'top' 은 맨 위로, 숫자는 그 위치로, 'next' 는 한 화면 아래로.
# erp.select_row 가 결의서 목록에서 쓰는 것과 같은 `.jgrid-viewport` (실측된 JGM 구조).
SCROLL_JS = """(how) => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const v = Array.from(document.querySelectorAll('.jgrid-viewport')).find(e => vis(e) && e.querySelector('.jgrid-row'));
  if (!v) return {ok: false};
  if (how === 'info') { /* 읽기만 */ }
  else if (how === 'top') v.scrollTop = 0;
  else if (typeof how === 'number') v.scrollTop = how;
  else v.scrollTop = Math.min(v.scrollHeight, v.scrollTop + Math.max(40, v.clientHeight - 60));
  return {ok: true, top: v.scrollTop, h: v.clientHeight, sh: v.scrollHeight};
}"""
MAX_SCROLLS = 80                          # 한 화면에 10줄 남짓이면 800줄 — 그보다 긴 이름 검색 결과는 사람에게


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
    query: str = ""                     # 마지막으로 검색한 말(학번/사번 또는 이름)
    tried: str = ""                     # 처음 고른 구분에서 못 찾아 다른 구분으로 찾았으면 처음 구분(참여인력)

    def lines(self) -> list[str]:
        if self.ok and self.picked:
            where = f" — {self.tried}에 없어 {self.tab}에서 찾음" if self.tried else ""
            return [f"✓ 소득자: {self.name}({self.chosen_no}) 를 골라 [확인] 까지 눌렀습니다 ({self.pick_note}){where}"]
        if self.ok:
            found = f"결과 {self.rows}행" if self.rows is not None else "결과 수는 세지 못함"
            why = f" — {self.pick_note}" if self.pick_note else ""
            return [f"소득자 팝업: '{self.query or self.name}' 로 검색함 — {found}{why}. 목록에서 고르고 [확인] 을 눌러 주세요"]
        return [f"✗ 소득자 팝업: {self.note or '열지 못함'} — 돋보기를 직접 눌러 골라 주세요"]


def _squash(text) -> str:
    """이름 비교용 — 공백 · 탭 · NBSP 를 모두 걷어낸다."""
    return re.sub(r"\s+", "", str(text or ""))


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
        got = _squash((row.get("cells") or {}).get(COL_NAME, ""))
        if got and name and got != _squash(name):
            return None, f"학번은 같은데 이름이 다름 (목록: {got})"
        return int(row["index"]), "학번 일치"
    if not hits:
        return None, f"{len(rows)}행 중 학번 {want} 인 행이 없음"
    return None, f"학번이 같은 행이 {len(hits)}개"


def _digits(text) -> str:
    return "".join(ch for ch in str(text or "") if ch.isdigit())


def listing(popup) -> tuple[list[dict], object]:
    """지금 그려진 결과 행들과 그 프레임. 못 읽으면 예외."""
    _, where = count_rows(popup)
    listing = where.evaluate(ROWS_JS)
    return list(listing.get("rows") or []), where


def _signature(popup) -> str:
    try:
        rows, _ = listing(popup)
    except Exception:  # noqa: BLE001 — 아직 그리는 중
        return "?"
    return "\n".join(str(r.get("text", "")) for r in rows)


def run_search(popup, query: str, wait: Callable[[float], None]) -> tuple[bool, str, int | None]:
    """검색 칸(#SEARCH_NM)에 query 를 넣고 [검색] — 국적 팝업(nation.py)도 같은 칸을 쓴다. 앞 검색의 행을 새 결과로 읽지 않도록 목록이 바뀔 때까지(최대 ~5초) 본다."""
    before = _signature(popup)
    typed = popup.evaluate(SET_TEXT_JS, [SEARCH_NAME_ID, query])
    if not typed.get("ok"):
        return False, "검색어를 넣지 못했습니다: " + str(typed.get("why", "")), None
    clicked = popup.evaluate(CLICK_ID_JS, SEARCH_BUTTON_ID)
    if not clicked.get("ok"):
        return False, "[검색] 을 누르지 못했습니다: " + str(clicked.get("why", "")), None
    wait_until(lambda: _signature(popup) not in (before, "?"), wait, tries=10, step=0.5)
    rows, _ = wait_rows(popup, wait, seconds=1.0)
    return True, "", rows


def _row_key(row: dict) -> str:
    """다시 그려져도 같은 줄 — JGM 줄 번호(r)가 있으면 그것, 없으면 줄 글자(같은 글자의 두 줄은 하나로 보인다)."""
    r = row.get("r")
    return f"r{r}" if r not in (None, "") else "t" + str(row.get("text", ""))


def _scroll(where, how, wait: Callable[[float], None]) -> dict | None:
    try:
        info = where.evaluate(SCROLL_JS, how)
    except Exception:  # noqa: BLE001
        return None
    if not info or not info.get("ok"):
        return None
    if how != "info":
        wait(0.25)                                # 스크롤 처리기가 줄을 다시 그린다
    return info


def _scan(popup, name: str, student_no: str, log: Callable[[str], None],
          wait: Callable[[float], None]) -> tuple[int | None, str, object]:
    """학번이 맞는 행 (index, 근거, 프레임). 목록이 그려진 것보다 길면(가상 스크롤) 위에서부터 끝까지 내려가 보고,
    학번이 맞는 줄이 **하나**일 때만 그 줄이 보이는 곳으로 돌아가 고른다."""
    rows, where = listing(popup)
    index, why = match(rows, name, student_no)
    if index is None and not why.endswith("인 행이 없음"):
        return index, why, where                   # 여럿 · 이름 다름 · 학번 없음 — 더 내려가 볼 것 없이 사람에게
    info = _scroll(where, "info", wait)
    if info is None or info["sh"] <= info["h"] + 5:
        return index, why, where                   # 스크롤이 없다 — 그려진 줄이 전부
    want = _digits(student_no)
    found: dict[str, int] = {}                     # 학번이 맞는 줄 → 그 줄이 보인 스크롤 위치
    seen: set[str] = set()
    info = _scroll(where, "top", wait)
    last = -1
    for _ in range(MAX_SCROLLS):
        if info is None:
            break
        rows, where = listing(popup)
        for row in rows:
            key = _row_key(row)
            seen.add(key)
            if _digits((row.get("cells") or {}).get(COL_NO, "")) == want:
                found.setdefault(key, info["top"])
        if info["top"] + info["h"] >= info["sh"] - 5 or info["top"] == last:
            break
        last = info["top"]
        info = _scroll(where, "next", wait)
    else:
        return None, f"목록이 너무 길어 끝까지 보지 못함 ({len(seen)}행 넘게)", where
    log("소득자 목록을 끝까지 내려가 봄: %d행 중 학번 %s 인 행 %d개" % (len(seen), want, len(found)))
    if not found:
        return None, f"{len(seen)}행 중 학번 {want} 인 행이 없음", where
    if len(found) > 1:
        return None, f"학번이 같은 행이 {len(found)}개", where
    (key, top), = found.items()
    _scroll(where, top, wait)
    rows, where = listing(popup)
    index, why = match(rows, name, student_no)
    if index is None or _row_key(rows[index]) != key:
        return None, "찾은 행으로 돌아가지 못함 — " + why, where
    return index, why, where


def pick(popup, frame, name: str, student_no: str, confirm_id: str, log: Callable[[str], None],
         wait: Callable[[float], None] = time.sleep) -> tuple[bool, str, str]:
    """확실한 행을 골라 [확인] 을 누르고 작성 화면의 소득자 코드(RCV_CD)가 학번으로 채워졌는지 본다."""
    try:
        index, why, where = _scan(popup, name, student_no, log, wait)
    except Exception as error:  # noqa: BLE001
        return False, "결과 목록을 읽지 못함: " + (str(error).splitlines()[0][:80] if str(error) else ""), ""
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
    got_no = _digits((state.get("RCV_CD") or {}).get("value", ""))
    got_name = (state.get("RCV_NM") or {}).get("value", "")
    if got_no and got_no == _digits(student_no):
        log("소득자 자동 선택: %s(%s) — %s" % (got_name or name, got_no, why))
        return True, why, got_no
    # 남지 않으면 기록에 아무 줄도 없이 사람을 기다렸다(2026-10-21 10:50 — 10분)
    log("소득자 자동 선택: %s(%s) 를 골라 [확인] 했지만 작성 화면의 소득자가 바뀌지 않음 (지금 %s %s)"
        % (name, _digits(student_no), got_name or "—", got_no))
    return False, "[확인] 을 눌렀지만 작성 화면의 소득자가 바뀌지 않음 — 작성 화면의 돋보기를 눌러 다시 골라 주세요", got_no


def _not_found(report: PersonReport) -> bool:
    """아무 줄도 고르지 않았고 그 까닭이 '없음' 인지 — 검색 결과 0행이거나 학번이 맞는 줄이 없음(누른 것 없음)."""
    return not report.picked and (not report.rows or report.pick_note.endswith("인 행이 없음"))


def queries_for(name: str, student_no: str, tab: str = TAB_STUDENT) -> list[tuple[str, str]]:
    """검색할 말 차례 — (무엇, 검색어). 학번/사번이 있으면 그것 먼저(담당자 요청 2026-10-14), 그다음 이름."""
    out = []
    no = _digits(student_no)
    if no:
        out.append(("학번" if tab == TAB_STUDENT else "사번", no))
    if name:
        out.append(("이름", name))
    return out


def search(page, frame, name: str, student_no: str, log: Callable[[str], None],
           wait: Callable[[float], None] = time.sleep, messages: list[str] | None = None,
           tab: str = TAB_STUDENT, auto_pick: bool = True) -> PersonReport:
    """돋보기 → 구분(인적정보/참여인력) → 학번/사번(결과가 없으면 이름) → [검색].
    auto_pick 이면 학번이 맞는 행 하나를 골라 [확인] 까지."""
    messages = messages if messages is not None else []
    report = PersonReport(ok=False, name=name, student_no=student_no, tab=tab, messages=messages)
    if not name:
        report.note = "이름이 없습니다"
        return report
    if tab not in CONFIRM_IDS:
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
        # 참여인력에서 못 찾으면 인적정보에서 한 번 더 — 담당자 실제(2026-10-21): 근로장학생 명단을 '참여인력' 으로 넣자 학번 · 이름 둘 다
        # 결과가 없어 멈췄다. 인적정보는 학생 학번 · 교직원 사번을 다 찾는다(2026-10-20). 거꾸로(인적정보 → 참여인력)는 하지 않는다.
        tabs = [tab] + ([TAB_STUDENT] if tab == TAB_STAFF and auto_pick else [])
        for n, tab_now in enumerate(tabs):
            if n:
                if report.picked or not _not_found(report):
                    break                                # 찾았거나 여럿 · 이름 다름 · 확인 실패 — 다른 구분에서 찾지 않고 사람에게
                log("소득자를 %s에서 찾지 못해 %s에서 다시 찾습니다" % (tab, tab_now))
                report.rows, report.pick_note = None, ""
            div = popup.evaluate(CHECK_DIV_JS, [DIV_RADIO_NAME, tab_now])
            if not div.get("ok"):
                if n:
                    report.pick_note = f"{tab}에서 찾지 못함 · 구분을 '{tab_now}' 로 바꾸지 못함"
                    break
                report.note = f"구분을 '{tab_now}' 로 바꾸지 못했습니다: " + str(div.get("why", ""))
                return report
            if not div.get("same"):
                wait(0.5)                                # 탭이 바뀌며 칸이 다시 그려진다
            report.tab, report.tried = tab_now, (tab if n else "")
            for what, query in queries_for(name, student_no, tab_now):
                ok, note, rows = run_search(popup, query, wait)
                if not ok:
                    report.note = note
                    return report
                report.ok, report.rows, report.query = True, rows, query
                log("소득자 검색(%s, %s): '%s' → %s" % (tab_now, what, query, f"{rows}행" if rows is not None else "결과 수 모름"))
                if not rows:
                    continue                             # 0행 — 다음 검색어(이름)로
                if not auto_pick:
                    break                                # 사람이 고를 목록
                report.picked, report.pick_note, report.chosen_no = pick(popup, frame, name, student_no, CONFIRM_IDS[tab_now], log, wait)
                # 학번이 맞는 줄이 없을 때만(아무것도 누르지 않았다) 다음 검색어로 — 여럿 · 이름 다름 · 확인 실패는 사람에게
                if report.picked or not report.pick_note.endswith("인 행이 없음"):
                    break
            if auto_pick and not report.rows and not report.pick_note:
                report.pick_note = "검색 결과가 없음"
                log("소득자 자동 선택 안 함: 검색 결과가 없음" + (f" ({tab_now})" if len(tabs) > 1 else ""))
        return report
    finally:
        try:
            popup.remove_listener("dialog", on_dialog)
        except Exception:  # noqa: BLE001
            pass
