"""입금처조회 팝업 — 돋보기(#btnRcvCd)를 눌러 팝업을 열고 거래처를 검색해 둔다. 1차에서 고르기·[확인] 은 사람.

실측(CLAUDE.md 14절 '입금처조회 팝업', 2026-10-13): 팝업은 iframe 이 아니라 **별도 창**(rexpe_0084_rcv_pop.act)이다.
검색 조건 칸(구분 라디오 · 거래처명 칸 · [검색])까지는 실측됐지만 검색 결과 목록(행을 고르는 방법)은 아직
실측 전이라, 여기서는 검색까지만 하고 목록에서 고르는 것과 [확인] 은 사람이 한다. 결과 목록 실측이 오면
`pick()` 을 더한다.

누르는 것은 돋보기(btnRcvCd) · 구분 라디오('거래처') · [검색](btn_search) 셋뿐이다. 기준 정보를 바꾸는
계좌등록 · 계좌수정 · 거래처등록 · 거래처수정 · 외부인 등록은 FORBIDDEN 에 두고 절대 누르지 않는다
(tests/test_safety.py 가 본다). Playwright 를 들여오지 않는다 — session.py 가 넘겨준 page·frame 만 쓴다.
"""
from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .form import SET_TEXT_JS

OPEN_BUTTON_ID = "btnRcvCd"          # 작성 화면의 입금처 돋보기
SEARCH_BUTTON_ID = "btn_search"      # 팝업의 [검색]
SEARCH_TEXT_ID = "SEARCH_GB_NM1"     # 거래처명 · 사업자번호 · 대표자명
DIV_RADIO_NAME = "RCV_DIV_CD"        # 거래처 · 참여인력 · 인적정보
DIV_LABEL = "거래처"
# 절대 누르지 않는다 — 기준 정보(거래처·계좌)를 만들거나 바꾼다. [확인](btn_s_confirm1)은 결과 목록 실측 뒤에.
FORBIDDEN_IDS = ("btnReg", "btnUpd", "rbaseRegg", "rbaseUpt")
FORBIDDEN_TEXTS = ("계좌등록", "계좌수정", "거래처등록", "거래처수정", "외부인 등록")

# 팝업 알아보기 — 입금처조회 팝업에만 있는 조합
POPUP_PROBE_JS = """() => !!(document.querySelector('input[name=RCV_DIV_CD]') && document.querySelector('#SEARCH_GB_NM1')
  && document.querySelector('#btn_s_confirm1'))"""

# id 로 단추 하나를 누른다. 허용 목록(ALLOWED_CLICK_IDS)의 id 로만 부른다.
CLICK_ID_JS = """(id) => {
  const el = document.getElementById(id);
  if (!el) return {ok: false, why: '단추가 없음'};
  if (el.disabled) return {ok: false, why: '비활성'};
  el.click();
  return {ok: true};
}"""
ALLOWED_CLICK_IDS = frozenset({OPEN_BUTTON_ID, SEARCH_BUTTON_ID})

# 구분 라디오 중 글자가 '거래처' 인 것을 켠다(이미 켜져 있으면 그대로). 라디오를 누르면 화면의 처리기가 탭을 바꾼다.
CHECK_DIV_JS = """([name, label]) => {
  const txt = e => (e.innerText || e.textContent || '').replace(/\\s+/g, ' ').trim();
  const esc = s => (window.CSS && CSS.escape) ? CSS.escape(s) : s;
  const labelOf = r => {
    if (r.id) { const l = document.querySelector('label[for="' + esc(r.id) + '"]'); if (l && txt(l)) return txt(l); }
    const lab = r.closest('label'); if (lab) return txt(lab);
    let n = r.nextSibling; while (n && n.nodeType === 3 && !n.textContent.trim()) n = n.nextSibling;
    if (n && n.nodeType === 3) return n.textContent.trim();
    if (n && n.nodeType === 1 && n.tagName !== 'INPUT') return txt(n);
    return r.parentElement ? txt(r.parentElement) : '';
  };
  const radios = Array.from(document.querySelectorAll('input[type=radio][name="' + esc(name) + '"]'));
  if (!radios.length) return {ok: false, why: '구분 라디오가 없음'};
  const hit = radios.find(r => labelOf(r).startsWith(label)) || radios.find(r => labelOf(r).includes(label));
  if (!hit) return {ok: false, why: '구분에 ' + label + ' 가 없음', labels: radios.map(labelOf)};
  if (hit.checked) return {ok: true, same: true};
  hit.click();
  return {ok: true};
}"""

# 검색 뒤 결과 수 — 읽기만. 목록 구조를 모르는 채로도 행이 몇 개인지는 세어 본다(JGM 그리드 행 · 표의 본문 행).
RESULT_COUNT_JS = """() => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const grid = Array.from(document.querySelectorAll('.jgrid-row')).filter(vis).length;
  if (grid) return {rows: grid, kind: 'grid'};
  let best = 0;
  document.querySelectorAll('table').forEach(t => {
    if (!vis(t) || !t.querySelector('th')) return;
    const body = Array.from(t.querySelectorAll('tbody tr, tr')).filter(tr => vis(tr) && !tr.querySelector('th') && tr.children.length >= 2);
    best = Math.max(best, body.length);
  });
  return {rows: best, kind: best ? 'table' : 'unknown'};
}"""


@dataclass
class PayeeReport:
    ok: bool
    query: str = ""
    rows: int | None = None            # 검색 결과 행 수 (못 세면 None)
    messages: list[str] = field(default_factory=list)   # 팝업이 띄운 알림
    note: str = ""

    def lines(self) -> list[str]:
        if self.ok:
            found = f"결과 {self.rows}행" if self.rows is not None else "결과 수는 세지 못함"
            out = [f"✓ 입금처 팝업: '{self.query}' 로 검색함 — {found}. 목록에서 거래처를 고르고 [확인] 을 눌러 주세요"]
        else:
            out = [f"✗ 입금처 팝업: {self.note or '열지 못함'} — 돋보기를 직접 눌러 골라 주세요"]
        out.extend("· 팝업 알림: " + m for m in self.messages)
        return out


def query_for(data: dict) -> str:
    """검색어 — 거래처 상호. 없으면 사업자등록번호(숫자만)."""
    name = str(data.get("payeeName") or "").strip()
    if name:
        return name
    return re.sub(r"\D", "", str(data.get("payeeBizNo") or ""))


def find_popup(context, probe_js: str = POPUP_PROBE_JS):
    """이미 열려 있는 팝업 창(probe_js 가 참인 창). 없으면 None."""
    for page in context.pages:
        try:
            if page.evaluate(probe_js) is True:
                return page
        except Exception:  # noqa: BLE001 — 로딩 중이거나 닫힌 창
            continue
    return None


def wait_until(check: Callable[[], bool], wait: Callable[[float], None], tries: int, step: float = 0.25) -> bool:
    for _ in range(tries):
        try:
            if check():
                return True
        except Exception:  # noqa: BLE001 — 아직 준비 안 됨
            pass
        wait(step)
    return False


def open_popup(page, frame, button_id: str, probe_js: str, log: Callable[[str], None]):
    """작성 프레임의 단추(button_id)를 눌러 팝업을 연다. 이미 열려 있으면 그것을 쓴다. (팝업, 못 연 이유)."""
    popup = find_popup(page.context, probe_js)
    if popup is not None:
        log("팝업이 이미 열려 있어 그대로 씁니다")
        return popup, ""
    try:
        with page.expect_popup(timeout=8000) as info:
            result = frame.evaluate(CLICK_ID_JS, button_id)
            if not result.get("ok"):
                raise RuntimeError("단추를 누르지 못했습니다: " + str(result.get("why", "")))
        return info.value, ""
    except Exception as error:  # noqa: BLE001 — 팝업이 안 뜨면 사람이 연다
        return None, (str(error).splitlines()[0][:120] if str(error) else "팝업이 열리지 않았습니다")


def wait_closed(popup, wait: Callable[[float], None], seconds: float = 180.0) -> bool:
    """사람이 팝업에서 고르고 [확인] 을 눌러 창이 닫힐 때까지 기다린다. 시간이 다 되면 False."""
    return wait_until(lambda: popup.is_closed(), wait, tries=max(1, int(seconds / 0.5)), step=0.5)


def search(page, frame, data: dict, log: Callable[[str], None],
           wait: Callable[[float], None] = time.sleep, messages: list[str] | None = None) -> PayeeReport:
    """돋보기를 눌러 팝업을 열고(이미 열려 있으면 그것을 씀) '거래처' 구분으로 검색어를 넣어 [검색] 을 누른다.

    page 는 작성 화면이 있는 창, frame 은 작성 프레임. 팝업이 띄우는 알림(alert)은 messages 에 모으고 넘긴다.
    """
    messages = messages if messages is not None else []
    query = query_for(data)
    report = PayeeReport(ok=False, query=query, messages=messages)
    if not query:
        report.note = "입금처 이름이 없습니다"
        return report
    popup, why = open_popup(page, frame, OPEN_BUTTON_ID, POPUP_PROBE_JS, log)
    if popup is None:
        report.note = why
        log("입금처 팝업: " + why)
        return report
    log("입금처 팝업을 열었습니다")

    def on_dialog(dialog) -> None:
        messages.append(dialog.message.strip())
        log("입금처 팝업 알림: %s" % dialog.message.strip())
        try:
            dialog.accept()
        except Exception:  # noqa: BLE001
            pass

    popup.on("dialog", on_dialog)
    try:
        if not wait_until(lambda: popup.evaluate(POPUP_PROBE_JS) is True, wait, tries=40):
            report.note = "팝업이 입금처조회 화면이 아닙니다"
            return report
        div = popup.evaluate(CHECK_DIV_JS, [DIV_RADIO_NAME, DIV_LABEL])
        if not div.get("ok"):
            report.note = "구분을 '거래처' 로 바꾸지 못했습니다: " + str(div.get("why", ""))
            return report
        typed = popup.evaluate(SET_TEXT_JS, [SEARCH_TEXT_ID, query])
        if not typed.get("ok"):
            report.note = "검색어를 넣지 못했습니다: " + str(typed.get("why", ""))
            return report
        clicked = popup.evaluate(CLICK_ID_JS, SEARCH_BUTTON_ID)
        if not clicked.get("ok"):
            report.note = "[검색] 을 누르지 못했습니다: " + str(clicked.get("why", ""))
            return report
        wait(1.5)                                   # 결과가 서버에서 온다
        try:
            counted = popup.evaluate(RESULT_COUNT_JS)
            report.rows = int(counted.get("rows")) if counted.get("kind") != "unknown" else None
        except Exception:  # noqa: BLE001 — 세지 못해도 검색은 됐다
            report.rows = None
        report.ok = True
        log("입금처 검색: '%s' → %s" % (query, f"{report.rows}행" if report.rows is not None else "결과 수 모름"))
        return report
    finally:
        try:
            popup.remove_listener("dialog", on_dialog)
        except Exception:  # noqa: BLE001 — 창이 이미 닫힘
            pass
