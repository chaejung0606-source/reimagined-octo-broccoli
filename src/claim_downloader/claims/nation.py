"""국적 고르기 — 인건비 탭 소득자의 국적 돋보기(#btnNationCd) → 국적조회 팝업에서 명단 엑셀의 국적을 검색해, 하나로 확실하면 골라 [확인] 까지.

실측(담당자 2026-10-14 18:45 · 18:46, 외국인 학생 노란 띠에서 [화면 구조 저장]): 국적조회 팝업 `rcomm_0038_01.act`(별도 창).
`#SEARCH_NM`(라벨 '검색') + `#btn_search`, 결과는 같은 프레임의 JGM 그리드 — 열 `k_NATION_CD`(UZ) · `k_NATION_NM`(우즈베키스탄), 행 라디오
`name=radioJGM4`. 검색 전에도 나라 목록이 그려져 있다(첫 줄 '가나'). '우즈' 로 검색하자 `UZ 우즈베키스탄` 한 줄 — 글자 일부로도 찾는다.
[확인] 은 **id 없는 '확인' 링크**이고, 숨은 `#RTN_FUNC`=`ctl.uf_rcomm_0038_01Params` 가 작성 화면의 `#NATION_CD`/`#NATION_NM` 을 채운다(추정 — 고른 뒤 두 칸을 읽어 확인한다).
**누르지 않는다**: 숨은 '선택없음'(국적을 지운다).

담당자 결정(2026-10-14): 어느 나라인지는 명단 엑셀의 '국적' 열에서 온다(roster.Person.foreign_nation). 이름이 같은 나라가 **하나**일 때만 앱이 고르고,
없거나 여럿이면 팝업을 열어 둔 채 사람에게 넘긴다. 검색은 person.run_search 를 그대로 쓴다(칸 id 가 같다). Playwright 를 들여오지 않는다.
"""
from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass

from .attach import CLICK_TEXT_JS
from .form import read_state
from .payee import PICK_ROW_JS, open_popup, wait_closed, wait_until
from .person import listing, run_search

OPEN_BUTTON_ID = "btnNationCd"            # 작성 화면(인건비 탭) 국적 돋보기
CONFIRM_TEXT = "확인"                     # 팝업의 [확인] — id 없는 링크
FORBIDDEN_TEXTS = ("선택없음",)
COL_CODE = "k_NATION_CD"
COL_NAME = "k_NATION_NM"
HOME_CODE = "KR"

# 국적조회 팝업 알아보기 — 숨은 #RTN_FUNC 가 이 팝업의 되돌림 함수이고 검색 칸이 있는 창
POPUP_PROBE_JS = """() => { const f = document.querySelector('#RTN_FUNC');
  return !!(f && /rcomm_0038_01/.test(f.value || '') && document.querySelector('#SEARCH_NM')); }"""


def core(text: str) -> str:
    """나라 이름 비교용 — 공백 · 괄호 · '공화국' 같은 꼬리를 뗀다. '우즈베키스탄 공화국' → '우즈베키스탄'."""
    t = re.sub(r"\s+|\(.*?\)", "", str(text or "")).lower()
    return re.sub(r"(인민공화국|민주공화국|공화국|연방|왕국)$", "", t)


def same_country(a: str, b: str) -> bool:
    """'우즈베키스탄' == '우즈베키스탄 공화국' — 꼬리를 떼고 한쪽이 다른 쪽을 담으면 같다고 본다."""
    x, y = core(a), core(b)
    return bool(x and y) and (x in y or y in x)


def same_nation(roster: str, code: str, name: str) -> bool:
    """명단 국적이 작성 화면의 국적과 같은지. 명단에 'UZ' 처럼 두세 글자 코드를 적었으면 코드끼리 본다(실제 시험 2026-10-14 19:3x —
    명단 'UZ' 와 ERP '우즈베키스탄' 을 이름으로만 맞춰 '다름' 으로 잘못 남겼다)."""
    r = str(roster or "").strip()
    if re.fullmatch(r"[A-Za-z]{2,3}", r):
        return r.upper() == str(code or "").strip().upper()
    return same_country(r, name)


@dataclass
class NationReport:
    ok: bool                       # 팝업을 열고 검색까지 했는지
    nation: str = ""               # 명단 국적
    picked: bool = False           # 앱이 골라 [확인] 까지 누르고 작성 화면에 들어간 것을 확인함
    code: str = ""                 # 작성 화면에 들어간 국적 코드
    name: str = ""
    note: str = ""                 # 못 한 이유 · 고른 근거

    def lines(self) -> list[str]:
        if self.picked:
            return [f"✓ 국적: {self.name}({self.code}) 를 골라 [확인] 까지 눌렀습니다 ({self.note})"]
        if self.ok:
            return [f"국적 팝업: '{self.nation}' 로 검색함 — {self.note}. 목록에서 고르고 [확인] 을 눌러 주세요"]
        return [f"✗ 국적 팝업: {self.note or '열지 못함'} — 국적 돋보기를 직접 눌러 골라 주세요"]


def match(rows: list[dict], nation: str) -> tuple[int | None, str]:
    """(고를 행 번호, 근거) — 이름(또는 두세 글자 코드)이 명단 국적과 같은 줄이 하나면 그것, 같은 줄이 없으면 이름을 담은 줄이 하나면 그것."""
    if not rows:
        return None, "검색 결과가 없음"
    want = core(nation)
    code = nation.strip().upper() if re.fullmatch(r"[A-Za-z]{2,3}", nation.strip()) else ""

    def cell(row: dict, key: str) -> str:
        return str((row.get("cells") or {}).get(key, ""))

    exact = [r for r in rows if core(cell(r, COL_NAME)) == want or (code and cell(r, COL_CODE).upper() == code)]
    if len(exact) == 1:
        return int(exact[0]["index"]), "국적 이름 일치"
    if len(exact) > 1:
        return None, f"이름이 같은 나라가 {len(exact)}줄"
    near = [r for r in rows if same_country(nation, cell(r, COL_NAME))]
    if len(near) == 1:
        return int(near[0]["index"]), f"국적 이름이 비슷함({cell(near[0], COL_NAME)})"
    if near:
        return None, f"'{nation}' 를 담은 나라가 {len(near)}줄"
    return None, f"{len(rows)}줄 중 '{nation}' 인 나라가 없음"


def queries_for(nation: str) -> list[str]:
    """검색어 차례 — 명단에 적힌 그대로, 꼬리('공화국' 등)를 뗀 것이 다르면 그것도."""
    out = [nation.strip()]
    short = re.sub(r"\s+", "", re.sub(r"(인민공화국|민주공화국|공화국)$", "", re.sub(r"\s+", "", nation.strip())))
    if short and short not in out:
        out.append(short)
    return [q for q in out if q]


def pick(page, frame, nation: str, log: Callable[[str], None], wait: Callable[[float], None] = time.sleep,
         messages: list[str] | None = None) -> NationReport:
    """국적 돋보기 → 명단 국적으로 [검색] → 하나로 확실하면 골라 [확인] → 작성 화면 #NATION_CD 가 그 코드인지 본다."""
    messages = messages if messages is not None else []
    report = NationReport(ok=False, nation=nation)
    if not nation.strip():
        report.note = "명단에 국적이 없음"
        return report
    popup, why = open_popup(page, frame, OPEN_BUTTON_ID, POPUP_PROBE_JS, log)
    if popup is None:
        report.note = why
        log("국적 팝업: " + why)
        return report

    def on_dialog(dialog) -> None:
        messages.append(dialog.message.strip())
        log("국적 팝업 알림: %s" % dialog.message.strip())
        try:
            dialog.accept()
        except Exception:  # noqa: BLE001
            pass

    popup.on("dialog", on_dialog)
    try:
        if not wait_until(lambda: popup.evaluate(POPUP_PROBE_JS) is True, wait, tries=40):
            report.note = "팝업이 국적조회 화면이 아닙니다"
            return report
        index, where = None, popup
        for query in queries_for(nation):
            ok, note, rows = run_search(popup, query, wait)
            if not ok:
                report.note = note
                return report
            report.ok = True
            log("국적 검색: '%s' → %s" % (query, f"{rows}줄" if rows is not None else "결과 수 모름"))
            found, where = listing(popup)
            index, report.note = match(found, nation)
            if index is not None or found:
                break                                   # 결과가 있으면 그 목록에서 정한다 — 0줄일 때만 다음 검색어
        if index is None:
            log("국적 자동 선택 안 함: " + report.note)
            return report
        chosen_code = str(((found[index].get("cells") or {}).get(COL_CODE, ""))).upper()
        chosen = where.evaluate(PICK_ROW_JS, index)
        if not chosen.get("ok"):
            report.note = "행을 고르지 못함: " + str(chosen.get("why", ""))
            return report
        wait(0.3)
        confirmed = popup.evaluate(CLICK_TEXT_JS, CONFIRM_TEXT)
        if not confirmed.get("ok"):
            report.note = "[확인] 을 누르지 못함: " + str(confirmed.get("why", ""))
            return report
        wait_closed(popup, wait, seconds=10)
        wait(0.3)
        state = read_state(frame, ["NATION_CD", "NATION_NM"])
        report.code = str((state.get("NATION_CD") or {}).get("value", "")).strip().upper()
        report.name = str((state.get("NATION_NM") or {}).get("value", "")).strip()
        if report.code and report.code != HOME_CODE and (not chosen_code or report.code == chosen_code):
            report.picked = True
            log("국적 자동 선택: %s(%s) — %s" % (report.name, report.code, report.note))
        else:
            report.note = f"[확인] 을 눌렀지만 작성 화면의 국적이 '{report.name or report.code or '비어 있음'}' 입니다"
        return report
    finally:
        try:
            popup.remove_listener("dialog", on_dialog)
        except Exception:  # noqa: BLE001
            pass
