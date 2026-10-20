"""카드청구 넣기 — 결제 기간 폴더(card.CardJob)의 청구서 하나(비목 하나)를 ERP 카드청구 작성 화면에 결제 건마다 한 줄씩 넣고 [저장].

실측(CLAUDE.md 14절 '카드청구 작성 화면' ① 14:14 · ② 14:32 회의록등록 · ④ 15:10 저장 뒤 · 15:32 (85) 등록 뒤, 2026-10-20).
화면은 `rexpe_0083_01.act`(#PROC_TYP_CD=P11). 결제 건 하나마다:

    미청구 카드내역 [조회] → 결제 건 라디오(card.pick — 사용일 · 금액 · 승인번호 · 카드 뒷자리 · 가맹점이 맞는 줄 **하나**일 때만)
    → ERP 가 채운 사용일 · 청구액이 폴더와 같은지 → 비목(#PAY_EXP_CD — 청구구분보다 먼저, 담당자) → 청구구분 라디오
    → (90) 기타: 청구내역(#REQ_PTCL) = `NN_건명`
      (17) 회의비: 증빙 [신규등록] → 회의록등록 창에 회의록(.hwpx)의 시간 · 장소 · 목적 · 내용 · 외부참석자 → 창의 [저장]
                   → ERP 가 채운 청구내역 앞에 `NN_`(공문의 비목). 참여인력 · 내부참석자는 돋보기 창이 미실측이라 **사람이** 넣는다
      (85) 소모성물품: [등록] 창이 미실측이라 **사람이** 물품 내역 · 물품검수 정보를 넣고 [계속] → 청구내역 앞에 `NN_`
    → 첨부(PDF · 그림) → 대표적요(#APPL_CONT) → 저장 전 검사 → [저장](form.save_draft) → 결의번호 · 줄이 늘었는지

확실하지 않으면 그 자리에서 **사람에게 묻는다**(ask — 장학금과 같은 노란 띠). 누르는 것(담당자 허락 2026-10-20 "네 눌러도 됩니다"):
[조회](#btn_cardList) · 결제 건 라디오 · 청구구분 라디오 · 증빙 [신규등록](#btn_addEvid2) · 회의록등록 창의 외부참석자 [행 추가](#btnRowAdd2) ·
그 창의 [저장](#save) · 작성 화면 [저장] · 첨부(attach.py). [신청] · [삭제] · [초기화] · '새 청구서' · [카드매출전표] · '과제카드' 링크 ·
[불러오기] · 회의록 출력 · 행 삭제는 누르지 않는다(tests/test_safety.py). 새 카드청구 화면은 session 이 결의서내역의 [카드청구](#P11)로 띄운다
(navigate.open_card_sheet, 담당자 허락 2026-10-20) — 이 모듈은 그 화면 안에서만 누른다.

이 모듈은 Playwright 를 들여오지 않는다 — session.py 가 넘겨준 page · frame 만 쓴다.
"""
from __future__ import annotations

import datetime as dt
import os
import re
import time
import traceback
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field

from . import attach, card, participants as part_mod
from .form import FRAME_VISIBLE_JS, SET_SELECT_JS, SET_TEXT_JS, read_state, save_draft
from .payee import CLICK_ID_JS, ROWS_JS, open_popup, wait_closed, wait_until
from .schema import CATEGORY_CODES, parse_amount

Ask = Callable[[str], bool]
MAX_ASKS = 3
TEST_PREFIX = "[시험] "

LIST_BUTTON_ID = "btn_cardList"          # 미청구 카드내역 [조회]
MINUTES_BUTTON_ID = "btn_addEvid2"       # (17) 증빙 [신규등록] → 회의록등록 창
MINUTES_SAVE_ID = "save"                 # 회의록등록 창의 [저장]
EXTERNAL_ADD_ID = "btnRowAdd2"           # 회의록등록 창의 외부참석자 [행 추가]
ALLOWED_CLICK_IDS = frozenset({LIST_BUTTON_ID, MINUTES_BUTTON_ID, MINUTES_SAVE_ID, EXTERNAL_ADD_ID})
# 절대 누르지 않는다 — 신청 · 지우기 · 다른 창(미실측) · 다른 증빙 불러오기
FORBIDDEN_IDS = ("btn_addEvid", "btn_addEvid3", "btn_gridCard", "btnRowAdd", "btnRowAdd1", "btnRowDel", "btnRowDel1", "btnRowDel2",
                 "btnEmpInfo", "CALL_PRE_SFRC", "oz_report", "confirmBtn", "btn_addCheckDate", "btn_addUser", "btn_addRCVRUserNm",
                 "btnRcvr", "bgtAmtPU", "btnModApplCont")
ATTACH_SUFFIXES = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".bmp")
WEEKEND_WORDS = ("토요일", "일요일")
MIN_CONTENT = 20                         # 회의내용 20자 이상(#CFRC_CONTENT_LENGTH_LIMITED, 실측 ②)

# 카드청구 작성 화면 — 일반청구(P10) 와 같은 칸 이름이 많아 #PROC_TYP_CD 로 가른다
PROBE_JS = """() => { const p = document.querySelector('#PROC_TYP_CD');
  return !!(p && p.value === 'P11' && document.querySelector('#btn_cardList') && document.querySelector('#REQ_PTCL')); }"""
MINUTES_PROBE_JS = """() => !!(document.querySelector('#CFRC_PLCE') && document.querySelector('#CFRC_ST_DTM')
  && document.querySelector('#CFRC_CONT') && document.querySelector('#save'))"""

# 보이는 청구구분 라디오(name=REQ_DIV_CD) 중 값이나 글자가 '(code)' 인 것을 켠다. 비목을 고르기 전에는 비활성이다(담당자 2026-10-20).
REQ_DIV_CLICK_JS = """(code) => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const txt = e => (e.innerText || e.textContent || '').replace(/\\s+/g, ' ').trim();
  // 라디오마다 id 가 모두 'REQ_DIV_CD' 라(실측 ①) label[for] 로는 못 가린다 — 값, 아니면 감싼 label · 바로 뒤 글자
  const labelOf = r => {
    const lab = r.closest('label'); if (lab) return txt(lab);
    let n = r.nextSibling; while (n && n.nodeType === 3 && !n.textContent.trim()) n = n.nextSibling;
    if (n && n.nodeType === 3) return n.textContent.trim();
    if (n && n.nodeType === 1 && n.tagName !== 'INPUT') return txt(n);
    return '';
  };
  const radios = Array.from(document.querySelectorAll('input[type=radio][name=REQ_DIV_CD]'));
  const want = String(code);
  const hits = radios.filter(r => r.value === want || labelOf(r).replace(/\\s+/g, '').startsWith('(' + want + ')'));
  const hit = hits.find(vis) || hits[0];
  if (!hit) return {ok: false, why: '청구구분에 (' + want + ') 가 없음'};
  if (hit.disabled) return {ok: false, why: '청구구분이 비활성 — 비목을 먼저 고르세요'};
  if (!vis(hit)) return {ok: false, why: '청구구분이 화면에 보이지 않음'};
  if (hit.checked) return {ok: true, same: true};
  hit.click();
  return {ok: hit.checked, why: hit.checked ? '' : '눌렀는데 켜지지 않음'};
}"""
REQ_DIV_JS = """() => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const all = Array.from(document.querySelectorAll('input[name=REQ_DIV_CD]'));
  const on = all.filter(r => r.checked);
  return {value: String(((on.filter(vis)[0]) || on[0] || {}).value || ''), enabled: all.some(r => vis(r) && !r.disabled)};
}"""
# 보이는 링크의 글자 — 붙은 증빙 요약(#REQ_DIV_LNK '물품명:…' · '회의일자:…', 실측 15:32)
LINK_TEXT_JS = """(id) => { const all = Array.from(document.querySelectorAll('[id="' + id + '"]'));
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const el = all.find(vis); return el ? (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim() : ''; }"""
# JGM 줄 번호(r)로 그 줄의 라디오를 누른다 — 행 라디오의 name 은 그리드를 다시 그리면 바뀐다(radioJGM13 → radioJGM22, 실측 ④)
PICK_R_JS = """(r) => {
  const vis = e => { const b = e.getBoundingClientRect(); return b.width > 0 && b.height > 0; };
  const row = Array.from(document.querySelectorAll('.jgrid-row')).find(e => vis(e) && String(e.getAttribute('r')) === String(r));
  if (!row) return {ok: false, why: '그 줄이 화면에 없음'};
  const box = row.querySelector('input[type=radio]');
  if (!box) return {ok: false, why: '줄에 선택 칸이 없음'};
  box.click();
  if (!box.checked) { box.checked = true; box.dispatchEvent(new Event('change', {bubbles: true})); }
  return {ok: true};
}"""
SCROLL_JS = """(how) => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const v = Array.from(document.querySelectorAll('.jgrid-viewport')).find(e => vis(e) && e.querySelector('.jgrid-row'));
  if (!v) return {ok: false};
  if (how === 'top') v.scrollTop = 0;
  else if (typeof how === 'number') v.scrollTop = how;
  else if (how === 'next') v.scrollTop = Math.min(v.scrollHeight, v.scrollTop + Math.max(40, v.clientHeight - 60));
  return {ok: true, top: v.scrollTop, h: v.clientHeight, sh: v.scrollHeight};
}"""
GRID_SIGNATURE_JS = """() => { const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const rows = Array.from(document.querySelectorAll('.jgrid-row')).filter(vis);
  return rows.length + '|' + rows.map(r => (r.textContent || '').replace(/\\s+/g, '')).join('/').slice(0, 400); }"""
# 회의록등록 창 — 외부참석자 표(머리글 '성명* | 소속*' 둘뿐인 표)의 보이는 줄 수 · 빈 마지막 줄 채우기. 표를 못 찾으면 dynamic-input 칸으로.
EXTERNAL_ROWS_SNIPPET = """
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const norm = s => (s || '').replace(/[\\s*]/g, '');
  const table = Array.from(document.querySelectorAll('table')).find(t => {
    const heads = Array.from(t.querySelectorAll('th')).map(th => norm(th.textContent)).filter(x => x);
    return heads.length === 2 && heads[0] === '성명' && heads[1] === '소속';
  });
  const rows = table ? Array.from(table.querySelectorAll('tr')).filter(tr => vis(tr) && tr.querySelector('input[name=CFRC_OUT_EMP_NM]'))
                     : Array.from(document.querySelectorAll('input[name=CFRC_OUT_EMP_NM].dynamic-input')).filter(vis).map(e => e.closest('tr') || e.parentElement);
"""
EXTERNAL_COUNT_JS = "() => {" + EXTERNAL_ROWS_SNIPPET + " return rows.length; }"
EXTERNAL_FILL_JS = "([name, org]) => {" + EXTERNAL_ROWS_SNIPPET + """
  const row = rows.slice().reverse().find(tr => { const n = tr.querySelector('input[name=CFRC_OUT_EMP_NM]'); return n && !n.value.trim(); });
  if (!row) return {ok: false, why: '빈 외부참석자 줄이 없음'};
  const put = (el, value) => { if (!el || el.readOnly || el.disabled) return false; el.focus(); el.value = value;
    for (const t of ['input', 'keyup', 'change']) el.dispatchEvent(new Event(t, {bubbles: true})); el.blur(); return true; };
  const okName = put(row.querySelector('input[name=CFRC_OUT_EMP_NM]'), name);
  const okOrg = put(row.querySelector('input[name=DEPT_NM]'), org);
  return {ok: okName && okOrg, why: okName ? (okOrg ? '' : '소속 칸에 넣지 못함') : '성명 칸에 넣지 못함'};
}"""
EXTERNAL_NAMES_JS = "() => {" + EXTERNAL_ROWS_SNIPPET + """
  return rows.map(tr => { const n = tr.querySelector('input[name=CFRC_OUT_EMP_NM]'); return n ? n.value.trim() : ''; }).filter(x => x); }"""


# ── 결과 ─────────────────────────────────────────────────────────────────
@dataclass
class ItemResult:
    index: int
    name: str
    status: str = "waiting"          # planned · saved · skipped · stopped
    lines: list[str] = field(default_factory=list)
    note: str = ""
    review: list[str] = field(default_factory=list)     # 저장했지만 [신청] 전에 사람이 볼 것


@dataclass
class CardReport:
    dry_run: bool
    summary: str = ""                 # 대표적요
    results: list[ItemResult] = field(default_factory=list)
    blocked: str = ""
    stopped: bool = False
    req_cnt: str = ""
    messages: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)       # 청구서 전체에 대한 신청 전 확인할 것
    appl_ok: bool = True

    @property
    def saved(self) -> int:
        return sum(1 for r in self.results if r.status == "saved")

    def review_items(self) -> list[str]:
        return list(self.notes) + [f"{r.index + 1}. {r.name} — {item}" for r in self.results for item in r.review]

    def lines(self) -> list[str]:
        head = "미리 보기 (ERP 에 넣지 않음)" if self.dry_run else f"ERP 임시저장 {self.saved}건" + (" — 멈춤" if self.stopped else "")
        out = [head, f"대표적요: {self.summary}"] + ([f"결의번호 {self.req_cnt}"] if self.req_cnt else [])
        if self.blocked:
            out.append("✗ " + self.blocked)
        review = self.review_items()
        if review:
            out.append(f"신청 전 확인할 것 {len(review)}건:")
            out.extend("  ! " + item for item in review)
        for r in self.results:
            mark = {"saved": "✓", "planned": "·", "skipped": "–", "stopped": "■"}.get(r.status, "·")
            out.append(f"{mark} {r.index + 1}. {r.name}" + (f" — {r.note}" if r.note else ""))
            out.extend("    " + line for line in r.lines)
        if not self.dry_run:
            out.append("사람이 할 것: ERP 에서 청구내역을 검토하고 [신청] 을 직접 누르세요 — 앱은 누르지 않습니다")
        return out


# ── 계획(미리 보기) ────────────────────────────────────────────────────────
def main_summary(sheet: card.CardSheet, test_mode: bool = False) -> str:
    return (TEST_PREFIX if test_mode else "") + sheet.main_summary


def attachments(item: card.CardItem) -> list[str]:
    """올릴 파일 — 결제 건 폴더의 PDF · 그림. 공문을 맨 앞에. 회의록(.hwpx) · 물품 표(.xlsx)는 PDF 로 저장해 두면 붙는다."""
    files = [p for p in item.files if p.lower().endswith(ATTACH_SUFFIXES)]
    files.sort(key=lambda p: (p != item.notice, p))
    return attach.attachable(files)


def meeting_plan(item: card.CardItem, members: list[part_mod.Member]) -> tuple[dict, list[part_mod.Attendee], list[str]]:
    """회의록등록 창에 넣을 값 · 참석자 나누기 · 모자란 것. 값 키는 창의 칸 id."""
    m = item.meeting or card.Minutes()
    values = {"CFRC_ST_DTM": m.start, "CFRC_END_DTM": m.end, "CFRC_PLCE": m.place, "CFRC_PURS": m.agenda,
              "CFRC_CONT": " ".join(p.strip() for p in m.content if p.strip())}
    missing = [label for key, label in (("CFRC_ST_DTM", "회의 시작 시각"), ("CFRC_END_DTM", "끝 시각"), ("CFRC_PLCE", "회의장소"),
                                        ("CFRC_PURS", "회의목적(안건)"), ("CFRC_CONT", "회의내용")) if not values[key]]
    if values["CFRC_CONT"] and len(values["CFRC_CONT"].replace(" ", "")) < MIN_CONTENT:
        missing.append(f"회의내용이 {MIN_CONTENT}자보다 짧음")
    people = part_mod.classify(m.attendees, members)
    if not people:
        missing.append("참석자 이름")
    return values, people, missing


def plan_item(item: card.CardItem, index: int, members: list[part_mod.Member] | None = None) -> ItemResult:
    result = ItemResult(index=index, name=item.name, status="planned")
    lines = result.lines
    lines.append(f"결제 건: 사용일 {item.used:%Y-%m-%d} · {item.amount:,}원" if item.used and item.amount is not None
                 else "결제 건: " + " · ".join(item.blocking()))
    lines.append(f"비목 {CATEGORY_CODES.get(item.code, '?')} → 청구구분 {item.req_div_name or '?'}")
    if item.req_div == "90":
        lines.append(f"청구내역: {item.summary}")
    elif item.req_div == "17":
        values, people, missing = meeting_plan(item, members or [])
        lines.append(f"회의록등록: {values['CFRC_ST_DTM'] or '?'}~{values['CFRC_END_DTM'] or '?'} · 장소 {values['CFRC_PLCE'] or '?'} · "
                     f"목적 {values['CFRC_PURS'][:30] or '?'}")
        for kind in ("part", "internal", "external"):
            who = [p.label() for p in people if p.kind == kind]
            if who:
                lines.append(f"  {part_mod.Attendee('', kind=kind).kind_name}: " + ", ".join(who)
                             + (" — 앱이 넣음" if kind == "external" else " — 사람이 돋보기로"))
        lines.append(f"청구내역: ERP 가 회의록에서 채운 글 앞에 {item.line_code or '?'}_")
        if missing:
            result.review.append("회의록에서 못 읽음: " + " · ".join(missing))
    elif item.req_div == "85":
        lines.append("소모성물품: [등록] 창 · 물품검수 정보는 사람이 넣음 (창 미실측)")
        lines.append(f"청구내역: ERP 가 채운 글 앞에 {item.line_code or '?'}_")
    files = attachments(item)
    lines.append(f"첨부 {len(files)}개: " + (" · ".join(os.path.basename(f) for f in files) or "없음"))
    result.review += item.blocking() + item.notes
    return result


# ── 화면 찾기 ────────────────────────────────────────────────────────────
def _matches(frame) -> bool:
    try:
        return frame.evaluate(PROBE_JS) is True
    except Exception:  # noqa: BLE001 — 로딩 중
        return False


def find_card_form(context):
    """열린 창에서 카드청구 작성 프레임. 여럿이면 화면에 보이는 것. (창, 프레임) 또는 (None, None)."""
    found = [(page, frame) for page in context.pages for frame in page.frames if _matches(frame)]
    for page, frame in found:
        try:
            if frame.evaluate(FRAME_VISIBLE_JS) is True:
                return page, frame
        except Exception:  # noqa: BLE001
            continue
    return found[0] if found else (None, None)


def wait_for_card_form(context, wait: Callable[[float], None], tries: int = 12):
    for attempt in range(max(1, tries)):
        page, frame = find_card_form(context)
        if frame is not None:
            return page, frame
        if attempt + 1 < tries:
            wait(0.5)
    return None, None


# ── 작은 도구 ────────────────────────────────────────────────────────────
def _state(frame, ids) -> dict:
    state = read_state(frame, list(ids))
    return {k: (state.get(k) or {}).get("value", "") if isinstance(state.get(k), dict) else "" for k in ids}


def _text_of(frame, element_id: str) -> str:
    """고르기 칸이면 고른 보기의 글자, 글 칸이면 값."""
    item = read_state(frame, [element_id]).get(element_id) or {}
    return str(item.get("text") if item.get("tag") == "select" else item.get("value", "")).strip()


def _set(frame, kind: str, element_id: str, value: str) -> dict:
    try:
        return frame.evaluate(SET_SELECT_JS if kind == "select" else SET_TEXT_JS, [element_id, value])
    except Exception as error:  # noqa: BLE001
        return {"ok": False, "why": str(error).splitlines()[0][:80] if str(error) else "오류"}


def _click(where, element_id: str) -> dict:
    assert element_id in ALLOWED_CLICK_IDS
    try:
        return where.evaluate(CLICK_ID_JS, element_id)
    except Exception as error:  # noqa: BLE001
        return {"ok": False, "why": str(error).splitlines()[0][:80] if str(error) else "오류"}


def _link(frame, element_id: str) -> str:
    try:
        return str(frame.evaluate(LINK_TEXT_JS, element_id) or "")
    except Exception:  # noqa: BLE001
        return ""


def _squash(text) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def _day(value: str) -> dt.date | None:
    digits = re.sub(r"\D", "", str(value or ""))
    try:
        return dt.date(int(digits[:4]), int(digits[4:6]), int(digits[6:8])) if len(digits) >= 8 else None
    except ValueError:
        return None


def _ask_until(check: Callable[[], tuple[bool, str]], ask: Ask, message_for: Callable[[str], str],
               wait: Callable[[float], None]) -> tuple[bool, str]:
    ok, why = check()
    asks = 0
    while not ok and asks < MAX_ASKS:
        asks += 1
        if not ask(message_for(why)):
            return False, why + " — 멈춤"
        wait(0.5)
        ok, why = check()
    return ok, why


@contextmanager
def _collect(where, messages: list[str], log: Callable[[str], None]):
    """앱이 창을 다루는 동안의 ERP 알림 · 확인 창 — 글을 모으고 [확인]. 사람을 기다리기 전에 떼야 사람에게 창이 보인다(7절 10번)."""
    def on_dialog(dialog) -> None:
        messages.append(dialog.message.strip())
        log("ERP 알림(회의록등록 창): %s" % dialog.message.strip()[:200])
        try:
            dialog.accept()
        except Exception:  # noqa: BLE001
            pass
    try:
        where.on("dialog", on_dialog)
    except Exception:  # noqa: BLE001 — 닫힌 창
        yield
        return
    try:
        yield
    finally:
        try:
            where.remove_listener("dialog", on_dialog)
        except Exception:  # noqa: BLE001
            pass


# ── 미청구 카드내역 ────────────────────────────────────────────────────────
def _signature(frame) -> str:
    try:
        return str(frame.evaluate(GRID_SIGNATURE_JS))
    except Exception:  # noqa: BLE001
        return "?"


def search(frame, start: dt.date | None, end: dt.date | None, log, wait) -> tuple[bool, str]:
    """[조회] — 결제예정월(기간)(기본 조건)을 결제 기간 첫 달 ~ 끝 달의 다음 달로 넓힌다. 사용일 9일 ~ 다음 달 8일의 결제는 대개 끝 달에
    빠져나가지만(실측: 10-12 사용 → 11-23 결제) 앞뒤 달을 더 봐도 고르는 규칙(사용일 · 금액)이 같아 해가 없다.
    조회 조건이 다른 것으로 바뀌어 있으면 화면에 있는 조건 그대로 조회한다."""
    if end:
        first = dt.date((start or end).year, (start or end).month, 1)
        after = dt.date(end.year + (end.month == 12), end.month % 12 + 1, 1)
        choice = _text_of(frame, "CARD_DATE")
        if choice.replace(" ", "") == "결제예정월(기간)":
            for element_id, value in (("START_YM", f"{first:%Y-%m}"), ("END_YM", f"{after:%Y-%m}")):
                done = _set(frame, "text", element_id, value)
                if not done.get("ok"):
                    log("조회 조건 %s 을 %s 로 두지 못함 — %s" % (element_id, value, done.get("why", "")))
        else:
            log("조회 조건이 '%s' 라 그대로 조회합니다" % (choice or "?"))
    before = _signature(frame)
    clicked = _click(frame, LIST_BUTTON_ID)
    if not clicked.get("ok"):
        return False, "[조회] 를 누르지 못함: " + str(clicked.get("why", ""))
    wait_until(lambda: _signature(frame) not in (before, "?"), wait, tries=16, step=0.5)
    wait(0.5)
    return True, ""


def read_payments(frame, wait, max_scrolls: int = 40) -> list[card.Payment]:
    """그리드의 결제 건 전부 — 가상 스크롤이면 위에서 끝까지 내리며 줄 번호(r)로 모은다. Payment.index = 줄 번호."""
    seen: dict[str, dict] = {}

    def grab() -> None:
        try:
            listing = frame.evaluate(ROWS_JS)
        except Exception:  # noqa: BLE001
            return
        if listing.get("kind") != "grid":
            return
        for row in listing.get("rows") or []:
            key = str(row.get("r") if row.get("r") not in (None, "") else f"t{row.get('text', '')}")
            cells = row.get("cells") or {}
            if "k_USED_DATE" in cells or "k_USED_COST" in cells:
                seen.setdefault(key, cells)

    info = _scroll(frame, "top", wait)
    grab()
    last = -1
    for _ in range(max_scrolls):
        if not info or info["top"] + info["h"] >= info["sh"] - 5 or info["top"] == last:
            break
        last = info["top"]
        info = _scroll(frame, "next", wait)
        grab()
    _scroll(frame, "top", wait)
    out = []
    for position, (key, cells) in enumerate(seen.items()):
        payment = card.payment_from_cells(int(key) if key.isdigit() else -1 - position, cells)
        out.append(payment)
    return out


def _scroll(frame, how, wait) -> dict | None:
    try:
        info = frame.evaluate(SCROLL_JS, how)
    except Exception:  # noqa: BLE001
        return None
    if not info or not info.get("ok"):
        return None
    if how != "info":
        wait(0.2)
    return info


def pick_row(frame, key: int, wait) -> tuple[bool, str]:
    """줄 번호 key 의 라디오를 누른다 — 화면에 안 그려졌으면 위에서부터 내리며 찾는다."""
    info = _scroll(frame, "top", wait)
    for _ in range(40):
        try:
            done = frame.evaluate(PICK_R_JS, key)
        except Exception as error:  # noqa: BLE001
            done = {"ok": False, "why": str(error).splitlines()[0][:80] if str(error) else "오류"}
        if done.get("ok") or done.get("why") != "그 줄이 화면에 없음":
            return bool(done.get("ok")), str(done.get("why", ""))
        if not info or info["top"] + info["h"] >= info["sh"] - 5:
            break
        top = info["top"]
        info = _scroll(frame, "next", wait)
        if not info or info["top"] == top:
            break
    return False, "고를 줄을 목록에서 찾지 못함"


# ── 넣기 ─────────────────────────────────────────────────────────────────
SELECTED_IDS = ("EXP_DT", "BUY_WHERE", "REQ_AMT", "LNK_CARD_NO", "LNK_REQ_SEQ_NO", "SLIP_DT")


def _selected(frame) -> dict:
    return _state(frame, SELECTED_IDS)


def _is_selected(state: dict) -> bool:
    return bool(state.get("EXP_DT") and state.get("REQ_AMT") and (state.get("LNK_REQ_SEQ_NO") or state.get("BUY_WHERE")))


def _selection_matches(item: card.CardItem, state: dict) -> tuple[bool, str]:
    used = _day(state.get("EXP_DT", ""))
    amount = parse_amount(state.get("REQ_AMT"))
    bad = []
    if item.used and used and used != item.used:
        bad.append(f"사용일이 폴더({item.used:%m-%d})와 다름({used:%m-%d})")
    if item.amount is not None and amount is not None and amount != item.amount:
        bad.append(f"청구액이 폴더({item.amount:,}원)와 다름({amount:,}원)")
    if not _is_selected(state):
        bad.append("결제 건이 골라지지 않음")
    return (not bad), " · ".join(bad)


def sheet_owner(frame, sheet: card.CardSheet, summary: str) -> tuple[bool, str]:
    """카드청구 화면이 새 청구서이거나 이 청구서(결의번호 · 대표적요)인지."""
    s = _state(frame, ["REQ_CNT", "APPR_DIV_CD", "APPL_CONT"])
    if not s["REQ_CNT"] and s["APPR_DIV_CD"] != "40":
        return True, "새 카드청구서"
    if sheet.req_cnt and s["REQ_CNT"] == sheet.req_cnt:
        return True, f"이 청구서(결의번호 {s['REQ_CNT']})에 이어서"
    if s["APPL_CONT"] and _squash(s["APPL_CONT"]) == _squash(summary):
        return True, f"대표적요가 같은 청구서(결의번호 {s['REQ_CNT'] or '?'})에 이어서"
    return False, f"카드청구 화면이 이미 저장된 다른 청구서입니다(결의번호 {s['REQ_CNT'] or '?'} · 대표적요 '{s['APPL_CONT'] or '없음'}')"


def run(page, frame, job: card.CardJob, sheet: card.CardSheet, log: Callable[[str], None], ask: Ask,
        wait: Callable[[float], None] = time.sleep, messages: list[str] | None = None,
        should_stop: Callable[[], bool] = lambda: False, on_item: Callable[[int, str, str], None] | None = None,
        dry_run: bool = True, members: list[part_mod.Member] | None = None, test_mode: bool = False,
        find_frame: Callable[[], tuple] | None = None) -> CardReport:
    """청구서 하나(sheet)의 결제 건을 차례로 넣는다. find_frame() 은 사람이 새 화면을 띄운 뒤 카드청구 프레임을 다시 찾는다."""
    live = messages if messages is not None else []
    members = members or []
    summary = main_summary(sheet, test_mode)
    items = sheet.items
    left = sum(1 for item in items if item.status != "saved")
    log("카드청구 %s — %s · 결제 %d건" % ("미리 보기" if dry_run else "시작", summary, len(items))
        + (f" (남은 {left}건)" if left != len(items) and not test_mode else ""))
    if dry_run:
        report = CardReport(dry_run=True, summary=summary, req_cnt=sheet.req_cnt)
        report.results = [plan_item(item, i, members) for i, item in enumerate(items) if item.status != "saved"]
        return report
    if not test_mode:
        return _run(page, frame, job, sheet, summary, log, ask, wait, live, should_stop, on_item, members, find_frame)
    # 시험 — 진짜 결의번호 · 저장 표시와 섞지 않는다(시험 청구서는 담당자가 ERP 에서 지운다. 지우기 전까지 그 결제 건은 미청구 목록에서 빠진다)
    real_req, real_status = sheet.req_cnt, [i.status for i in items]
    sheet.req_cnt = sheet.test_req_cnt
    for item in items:
        item.status = ""
    try:
        return _run(page, frame, job, sheet, summary, log, ask, wait, live, should_stop, on_item, members, find_frame)
    finally:
        sheet.test_req_cnt, sheet.req_cnt = sheet.req_cnt, real_req
        for item, status in zip(items, real_status):
            item.status = status


def _run(page, frame, job, sheet, summary, log, ask, wait, live, should_stop, on_item, members, find_frame) -> CardReport:
    report = CardReport(dry_run=False, summary=summary, req_cnt=sheet.req_cnt)
    items = sheet.items
    notify = on_item or (lambda _i, _s, _d: None)

    # 청구서 하나에 한 비목 — 다른 청구서가 떠 있으면 사람이 새 카드청구 화면을 띄운다(#P11 은 앱이 누르지 않는다)
    def owner() -> tuple[bool, str]:
        nonlocal page, frame
        if find_frame is not None:
            found_page, found = find_frame()
            if found is not None:
                page, frame = found_page, found
        ok, why = sheet_owner(frame, sheet, summary)
        if not ok:
            return False, why + ". 결의서내역에서 [카드청구] 를 눌러 새 카드청구 화면을 띄운 뒤"
        try:
            shown = frame.evaluate(FRAME_VISIBLE_JS) is not False
        except Exception:  # noqa: BLE001
            shown = True
        # 결의서내역을 읽느라(18절) 목록 탭이 앞으로 오면 카드 화면이 숨는다 — 숨은 그리드는 줄이 그려지지 않아 결제 건을 못 고른다
        return (True, why) if shown else (False, "카드청구 화면이 다른 탭 뒤에 있습니다. 위쪽 '청구서(카드)' 탭을 눌러 앞으로 가져온 뒤")

    ok, why = _ask_until(owner, ask, lambda w: f"{w} [계속].", wait)
    if not ok:
        report.blocked, report.stopped = why, True
        return report
    log("카드청구 — " + why)

    ok, why = search(frame, job.start, job.end, log, wait)
    if not ok:
        report.blocked, report.stopped = why, True
        return report
    payments = read_payments(frame, wait)
    log("미청구 카드내역 %d건" % len(payments))
    pending = [i for i, item in enumerate(items) if item.status != "saved"]
    plan = dict(zip(pending, card.assign([items[i] for i in pending], payments)))
    for i in pending:
        key, why = plan[i]
        log("  %d. %s → %s" % (i + 1, items[i].name, ("줄 %s (%s)" % (key, why)) if key is not None else why))

    for i in pending:
        if should_stop():
            report.stopped = True
            break
        item = items[i]
        result = ItemResult(index=i, name=item.name)
        notify(i, "running", "")
        live.clear()
        try:
            ok, note = _run_item(page, frame, job, sheet, item, i, plan[i], summary, log, ask, wait, live, result, members)
        except Exception as error:  # noqa: BLE001 — 한 건에서 터져도 어디까지 됐는지는 알려 준다
            log("카드청구 오류(%s)\n%s" % (item.name, traceback.format_exc()))
            ok, note = False, "오류: " + (str(error).splitlines()[0][:100] if str(error) else type(error).__name__)
        report.messages.extend(live)
        live.clear()
        result.note = note
        if ok == "skipped":
            result.status = "skipped"
        else:
            result.status = "saved" if ok else "stopped"
        if result.status == "saved":
            item.status = "saved"
            report.req_cnt = sheet.req_cnt
        report.results.append(result)
        notify(i, "review" if result.status == "saved" and result.review else result.status, note)
        if result.status == "stopped":
            report.stopped = True
            log("카드청구 멈춤 — %d. %s: %s" % (i + 1, item.name, note))
            break
    if report.saved:
        try:
            appl = _state(frame, ["APPL_CONT"])["APPL_CONT"]
        except Exception:  # noqa: BLE001
            appl = ""
        report.appl_ok = _squash(appl) == _squash(summary)
        if not report.appl_ok:
            # 대표적요는 줄을 [저장] 할 때 함께 저장되는 것으로 보인다(미실측) — 마지막 줄 뒤에 넣은 값은 저장되지 않았을 수 있다
            report.notes.append(f"대표적요 '{summary}' 가 저장됐는지 ERP 의 대표적요 칸에서 확인하세요 (지금 칸: '{appl or '빔'}')")
    log("카드청구 끝 — 임시저장 %d건%s" % (report.saved, " (멈춤)" if report.stopped else ""))
    for line in report.review_items():
        log("  신청 전 확인: " + line)
    return report


def _run_item(page, frame, job, sheet, item: card.CardItem, index: int, planned: tuple, summary: str, log, ask: Ask, wait,
              messages: list[str], result: ItemResult, members) -> tuple[object, str]:
    log("── %d. %s (사용일 %s · %s원 · %s)" % (index + 1, item.name, f"{item.used:%m-%d}" if item.used else "?",
                                          f"{item.amount:,}" if item.amount is not None else "?", item.req_div_name))
    if item.blocking():
        return False, "폴더에서 " + " · ".join(item.blocking()) + " — 폴더 이름이나 파일을 고친 뒤 [다시 읽기]"

    # 1. 결제 건 — 맞는 줄이 하나면 앱이, 아니면 사람이 라디오를 누른다
    key, why = planned
    payments = read_payments(frame, wait)
    if not payments:
        # 저장 뒤 화면이 다시 열리면 목록이 비어 있을 수 있다 — 다시 [조회]
        searched, _w = search(frame, job.start, job.end, log, wait)
        payments = read_payments(frame, wait) if searched else []
    again, again_why = card.pick(item, payments)
    if key is not None and again is not None:
        key = again
    elif key is not None:
        key, why = None, again_why
    if key is not None:
        done, pick_why = pick_row(frame, key, wait)
        if not done:
            key, why = None, pick_why
    if key is not None:
        wait_until(lambda: _is_selected(_selected(frame)), wait, tries=16, step=0.5)
        log("결제 건 고름: 줄 %s (%s)" % (key, why))
    else:
        log("결제 건을 앱이 고르지 않음: " + why)
        if "목록에 없음" in why:
            if not ask(f"{item.name}: {why}. 이미 청구한 건이면 [계속] 을 누르면 이 건을 건너뜁니다. 아니면 조회 조건(기간)을 바꿔 [조회] 하고 "
                       "맞는 줄의 라디오를 직접 고른 뒤 [계속]."):
                return False, why + " — 멈춤"
            if not _is_selected(_selected(frame)):
                result.lines.append("건너뜀 — 미청구 카드내역에 없음")
                return "skipped", "미청구 카드내역에 없어 건너뜀(이미 청구했을 수 있음)"
        else:
            if not ask(f"{item.name}: 결제 건을 앱이 고르지 못했습니다 — {why}. 미청구 카드내역에서 사용일 {item.used:%m-%d} · "
                       f"{item.amount:,}원 줄의 라디오를 직접 고른 뒤 [계속]."):
                return False, why + " — 멈춤"
    ok, why = _ask_until(lambda: _selection_matches(item, _selected(frame)), ask,
                         lambda w: f"{item.name}: {w}. 미청구 카드내역에서 맞는 줄을 고른 뒤 [계속].", wait)
    if not ok:
        return False, why
    chosen = _selected(frame)
    result.lines.append(f"결제 건: {chosen.get('EXP_DT')} · {chosen.get('BUY_WHERE')} · {chosen.get('REQ_AMT')}원")

    # 2. 비목 → 청구구분(비목을 먼저 골라야 청구구분이 살아난다)
    category = CATEGORY_CODES.get(sheet.code, "")
    done = _set(frame, "select", "PAY_EXP_CD", category)
    if not done.get("ok"):
        return False, f"비목 '{category}' 을 고르지 못함: {done.get('why', '')}"
    wait_until(lambda: frame.evaluate(REQ_DIV_JS).get("enabled"), wait, tries=12, step=0.5)
    done = frame.evaluate(REQ_DIV_CLICK_JS, item.req_div)
    if not done.get("ok"):
        if not ask(f"{item.name}: 청구구분 ({item.req_div})를 앱이 고르지 못했습니다 — {done.get('why', '')}. 직접 고른 뒤 [계속]."):
            return False, "청구구분을 고르지 못함 — 멈춤"
    wait(0.5)
    log("비목 %s · 청구구분 %s" % (category, item.req_div_name))

    # 3. 청구구분마다 증빙 · 청구내역
    if item.req_div == "17":
        ok, why = _minutes(page, frame, item, log, ask, wait, messages, result, members)
        if not ok:
            return False, why
    elif item.req_div == "85":
        ok, why = _goods_by_person(frame, item, ask, wait)
        if not ok:
            return False, why
    if item.req_div in ("17", "85"):
        filled = _state(frame, ["REQ_PTCL"])["REQ_PTCL"]
        wanted = item.prefixed(filled)
        if wanted and wanted != filled:
            done = _set(frame, "text", "REQ_PTCL", wanted)
            if not done.get("ok"):
                result.review.append(f"청구내역 앞에 {item.line_code}_ 를 붙이지 못함 — ERP 에서 고치세요")
        if item.notice_code and item.notice_code != sheet.code:
            result.review.append(f"공문의 비목({item.notice_code})이 이 청구서의 비목({sheet.code})과 다름")
    else:
        done = _set(frame, "text", "REQ_PTCL", item.summary)
        if not done.get("ok"):
            return False, "청구내역을 넣지 못함: " + str(done.get("why", ""))
    result.lines.append("청구내역: " + _state(frame, ["REQ_PTCL"])["REQ_PTCL"])

    # 4. 첨부 — 앱이 한 번만 올리고, 안 되면 사람이 마저(장학금과 같은 규칙)
    files = attachments(item)
    if item.minutes and not any(_is_minutes_pdf(p) for p in files):
        result.review.append("회의록 PDF 가 폴더에 없어 첨부하지 않음 — 한글에서 PDF 로 저장해 넣거나 ERP 에서 직접 첨부")
    if files:
        before = attach.file_count(frame)
        sent = attach.upload(page, frame, files, log, wait, messages)
        result.lines.extend(sent.lines())
        if not sent.ok:
            ok, why = _ask_until(lambda: (attach.file_count(frame) - before >= len(files), f"첨부 {attach.file_count(frame) - before}/{len(files)}개"),
                                 ask, lambda w: f"{item.name}: 첨부를 마치지 못했습니다({sent.note}). '첨부' 로 마저 올린 뒤 [계속].", wait)
            if not ok:
                return False, "첨부: " + why

    # 5. 대표적요 — 첫 저장 전에는 칸이 숨어 있다(①). 넣어 두고, 저장 뒤 다시 본다
    current = _state(frame, ["APPL_CONT"])["APPL_CONT"]
    if _squash(current) != _squash(summary):
        done = _set(frame, "text", "APPL_CONT", summary)
        if not done.get("ok"):
            log("대표적요를 넣지 못함: " + str(done.get("why", "")))

    # 6. 저장 전 검사
    def ready() -> tuple[bool, str]:
        s = _state(frame, ["REQ_PTCL", "REQ_AMT", "EXP_DT"])
        bad = []
        if _text_of(frame, "PAY_EXP_CD").replace(" ", "") != category.replace(" ", ""):
            bad.append(f"비목이 '{_text_of(frame, 'PAY_EXP_CD')}'")
        div = str(frame.evaluate(REQ_DIV_JS).get("value", ""))
        if div and div != item.req_div:
            bad.append(f"청구구분이 ({div})")
        if not s["REQ_PTCL"]:
            bad.append("청구내역이 빔")
        if not parse_amount(s["REQ_AMT"]):
            bad.append("청구액이 빔")
        if item.req_div in ("17", "85") and not _link(frame, "REQ_DIV_LNK"):
            bad.append("증빙이 붙지 않음")
        return not bad, " · ".join(bad)

    ok, why = _ask_until(ready, ask, lambda w: f"{item.name}: 저장 전 검사 — {w}. ERP 에서 고친 뒤 [계속].", wait)
    if not ok:
        return False, "저장 전 검사: " + why

    # 7. [저장]
    rows_before = _sheet_rows(frame)
    messages.clear()
    saved = save_draft(frame, log, messages, wait=wait)
    if not saved.ok:
        return False, "임시저장 안 됨: " + (saved.note or " / ".join(saved.messages) or "화면이 바뀌지 않음")
    req_cnt = saved.after.get("REQ_CNT") or _state(frame, ["REQ_CNT"])["REQ_CNT"]
    if req_cnt:
        sheet.req_cnt = req_cnt
    rows_after = _sheet_rows(frame)
    result.lines.append(f"임시저장 — 결의번호 {req_cnt or '?'} · 청구내역 {rows_before} → {rows_after}줄")
    if rows_after <= rows_before:
        result.review.append("저장했는데 청구내역 줄이 늘지 않음 — ERP 에서 확인")
    if _squash(_state(frame, ["APPL_CONT"])["APPL_CONT"]) != _squash(summary):
        # 첫 저장 뒤에야 대표적요 칸이 보인다(④) — 다음 결제 건의 [저장] 때 함께 저장되게 넣어 둔다. 마지막 건 뒤에는 run 이 알린다
        _set(frame, "text", "APPL_CONT", summary)
    return True, "임시저장 됨"


def _is_minutes_pdf(path: str) -> bool:
    name = os.path.basename(path)
    return name.lower().endswith(".pdf") and ("회의록" in name or bool(re.match(r"^\d{4}-\d{2}-\d{2}\s+\S+\s+.+", name)))


SHEET_ROWS_JS = """() => Array.from(document.querySelectorAll('input[name=CUR_REQ]')).filter(r => {
  const tr = r.closest('tr'); const text = tr ? (tr.innerText || tr.textContent || '') : '';
  return /[가-힣A-Za-z]/.test(text) && !/조회된.*없|내역이 없|데이터가 없/.test(text); }).length"""


def _sheet_rows(frame) -> int:
    try:
        return int(frame.evaluate(SHEET_ROWS_JS) or 0)
    except Exception:  # noqa: BLE001
        return 0


def _goods_by_person(frame, item: card.CardItem, ask: Ask, wait) -> tuple[bool, str]:
    """(85) 소모성물품 — [등록] 창이 미실측이라 사람이 물품 내역 · 물품검수 정보를 넣는다. 다 됐는지는 앱이 본다."""
    rows = item.goods.rows if item.goods else []
    goods = ", ".join(f"{r['name']}×{r.get('qty') or '?'}" for r in rows[:6]) + (" 외" if len(rows) > 6 else "")

    def done() -> tuple[bool, str]:
        s = _state(frame, ["CHECKDATE", "CHECKUSER", "RCVR_USER_NM"])
        bad = [] if _link(frame, "REQ_DIV_LNK") else ["[등록] 증빙이 없음"]
        bad += [label for key, label in (("CHECKDATE", "검수일자"), ("CHECKUSER", "검수자"), ("RCVR_USER_NM", "인수자")) if not s[key]]
        return not bad, " · ".join(bad)

    return _ask_until(done, ask, lambda w: (f"{item.name}: 소모성물품 — {w}. [등록] 으로 물품 내역({goods or '물품 표 없음'})을 넣고 그 창의 [저장], "
                                            "물품검수 정보(검수일자 · 검수자 · 인수자)를 넣은 뒤 [계속]."), wait)


def _minutes(page, frame, item: card.CardItem, log, ask: Ask, wait, messages: list[str], result: ItemResult,
             members) -> tuple[bool, str]:
    """(17) 회의비 — 증빙 [신규등록] → 회의록등록 창(실측 ②)에 회의록 값 · 외부참석자를 넣고 그 창의 [저장]."""
    values, people, missing = meeting_plan(item, members)
    popup, why = open_popup(page, frame, MINUTES_BUTTON_ID, MINUTES_PROBE_JS, log)
    if popup is None:
        ok, why2 = _ask_until(lambda: (bool(_link(frame, "REQ_DIV_LNK")), "증빙이 없음"), ask,
                              lambda w: f"{item.name}: 회의록등록 창을 열지 못했습니다({why}). 증빙 [신규등록] 으로 직접 등록한 뒤 [계속].", wait)
        return ok, why2
    if not wait_until(lambda: popup.evaluate(MINUTES_PROBE_JS) is True, wait, tries=40):
        return False, "회의록등록 창이 아닙니다"
    s = _state(popup, ["CFRC_DT", "WEEKEND", "CARD_ADDR", "MEAL_COST", "CFRC_LIMITED_AMT"])
    log("회의록등록 창: 회의일자 %s %s · 회의비 %s원" % (s["CFRC_DT"], s["WEEKEND"], s["MEAL_COST"]))

    # 회의 장소와 가맹점 주소의 시 · 군이 같아야 한다(담당자 2026-10-20 — 영수증이 없으면 카드매출전표로 갈음하는 규칙)
    shop = card.address_region(s["CARD_ADDR"]) if s["CARD_ADDR"] else card.address_region(item.shop_address)
    conflict = card.region_conflict(item.meeting_region, s["CARD_ADDR"] or item.shop_address)
    if conflict:
        log("지역 확인: " + conflict)
        if not ask(f"{item.name}: {conflict}. 그래도 넣으려면(타지역 사유가 있는 경우) 회의록등록 창에서 사유를 넣고 [계속], 아니면 [멈추기]."):
            return False, conflict + " — 멈춤"
        result.review.append(conflict)
    elif shop:
        result.lines.append(f"지역: 회의 {item.meeting_region or '?'} · 가맹점 {shop}")

    with _collect(popup, messages, log):
        for key, value in values.items():
            if not value:
                continue
            done = _set(popup, "text", key, value)
            log("  %s %s: %s%s" % ("✓" if done.get("ok") else "✗", key, value[:40], "" if done.get("ok") else " — " + str(done.get("why", ""))))
            if not done.get("ok"):
                missing.append(f"{key} 를 넣지 못함")
        externals = [p for p in people if p.kind == "external"]
        added = _add_externals(popup, externals, log, wait)
        if added < len(externals):
            missing.append(f"외부참석자 {len(externals) - added}명을 넣지 못함")
        out_count = _state(popup, ["OUT_COUNT"])["OUT_COUNT"]
        total_out = len(_external_names(popup))
        if total_out and parse_amount(out_count) != total_out:
            _set(popup, "text", "OUT_COUNT", str(total_out))

    # 참여인력 · 내부참석자 — 돋보기 창(rcomm_0071_02 등)이 미실측이라 사람이 넣는다
    inside = [p for p in people if p.kind in ("part", "internal")]
    weekend = s["WEEKEND"] in WEEKEND_WORDS
    asks = []
    if inside:
        parts = [p.label() for p in inside if p.kind == "part"]
        others = [p.label() + (f" ({p.note})" if p.note else "") for p in inside if p.kind == "internal"]
        asks.append(("참여인력 [행 추가]: " + ", ".join(parts) if parts else "")
                    + (" / " if parts and others else "") + ("내부참석자 [행 추가] 후 돋보기: " + ", ".join(others) if others else ""))
    if weekend:
        asks.append(f"회의일이 {s['WEEKEND']} — 비고에 휴일 집행 사유")
    if missing:
        asks.append("회의록에서 못 넣은 것: " + " · ".join(missing))

    def inside_ok() -> tuple[bool, str]:
        if popup.is_closed():
            return True, ""                # 사람이 창의 [저장] 까지 눌렀다 — 아래에서 작성 화면을 본다
        c = _state(popup, ["IN_COUNT", "EMP_COUNT", "OUT_COUNT", "RMK", "CFRC_CONT", "CFRC_ST_DTM", "CFRC_END_DTM", "CFRC_PLCE", "CFRC_PURS"])
        bad = []
        have = (parse_amount(c["IN_COUNT"]) or 0) + (parse_amount(c["EMP_COUNT"]) or 0)
        if have < len(inside):
            bad.append(f"참여인력 · 내부참석자 {have}/{len(inside)}명")
        if not have and not (parse_amount(c["OUT_COUNT"]) or 0) and not _external_names(popup):
            bad.append("참석자가 없음")
        if weekend and not c["RMK"].strip():
            bad.append("휴일 사유가 빔")
        if len(_squash(c["CFRC_CONT"])) < MIN_CONTENT:
            bad.append(f"회의내용 {MIN_CONTENT}자 미만")
        bad += [label for key, label in (("CFRC_ST_DTM", "회의 시작 시각"), ("CFRC_END_DTM", "끝 시각"), ("CFRC_PLCE", "회의장소"),
                                         ("CFRC_PURS", "회의목적")) if not c[key].strip()]
        return not bad, " · ".join(bad)

    if asks or not inside_ok()[0]:
        ok, why = _ask_until(inside_ok, ask, lambda w: (f"{item.name} 회의록등록 창: " + " / ".join(a for a in asks if a)
                                                         + f" — 지금: {w}. 넣은 뒤 [계속] (창의 [저장] 은 앱이 누릅니다)."), wait)
        if not ok:
            if popup.is_closed():
                return False, "회의록등록 창이 닫힘 — 멈춤"
            return False, "회의록등록: " + why
    if popup.is_closed():
        # 사람이 창의 [저장] 까지 눌렀다 — 작성 화면에 증빙이 붙었는지만 본다
        return _evidence_attached(frame, item, ask, wait)

    counts = _state(popup, ["IN_COUNT", "EMP_COUNT", "OUT_COUNT", "MEAL_COST", "CFRC_LIMITED_AMT"])
    heads = sum(parse_amount(counts[k]) or 0 for k in ("IN_COUNT", "EMP_COUNT", "OUT_COUNT"))
    limit = parse_amount(counts["CFRC_LIMITED_AMT"]) or 0
    cost = parse_amount(counts["MEAL_COST"]) or item.amount or 0
    if heads and limit and cost / heads > limit:
        result.review.append(f"1인당 회의비 {cost // heads:,}원 — 한도 {limit:,}원을 넘음")
    result.lines.append("참석자: " + ", ".join(f"{p.kind_name} {p.name}" for p in people) if people else "참석자: 회의록에 없음")

    # 창의 [저장] — 확인 창은 앱이 [확인](담당자 허락). 창이 닫히면 작성 화면에 증빙이 붙는다
    with _collect(popup, messages, log):
        clicked = _click(popup, MINUTES_SAVE_ID)
        if not clicked.get("ok"):
            return False, "회의록등록 [저장] 을 누르지 못함: " + str(clicked.get("why", ""))
        log("회의록등록 [저장] 누름")
        closed = wait_closed(popup, wait, seconds=20)
    if not closed:
        shown = " / ".join(messages[-3:]) or "알림 없음"
        ok, why = _ask_until(lambda: (popup.is_closed(), "창이 아직 열려 있음"), ask,
                             lambda w: f"{item.name}: 회의록등록 창이 닫히지 않았습니다(ERP: {shown}). 창에서 고치고 [저장] 한 뒤 [계속].", wait)
        if not ok:
            return False, "회의록등록 저장: " + why
    return _evidence_attached(frame, item, ask, wait)


def _evidence_attached(frame, item: card.CardItem, ask: Ask, wait) -> tuple[bool, str]:
    def check() -> tuple[bool, str]:
        link = _link(frame, "REQ_DIV_LNK")
        text = _state(frame, ["REQ_PTCL"])["REQ_PTCL"]
        return bool(link and text), ("" if link else "증빙이 붙지 않음") + ("" if text else " 청구내역이 빔")

    wait_until(lambda: check()[0], wait, tries=12, step=0.5)
    return _ask_until(check, ask, lambda w: f"{item.name}: 회의록을 저장했는데 작성 화면에 {w.strip()}. 확인한 뒤 [계속].", wait)


def _external_names(popup) -> list[str]:
    try:
        return [str(x) for x in popup.evaluate(EXTERNAL_NAMES_JS) or []]
    except Exception:  # noqa: BLE001
        return []


def _add_externals(popup, externals: list[part_mod.Attendee], log, wait) -> int:
    """외부참석자 [행 추가] → 새 줄에 성명 · 소속. 이미 같은 이름이 있으면 건너뛴다(다시 이을 때). 넣은 수."""
    have = {_squash(n) for n in _external_names(popup)}
    added = 0
    for person in externals:
        if _squash(person.name) in have:
            added += 1
            continue
        try:
            before = int(popup.evaluate(EXTERNAL_COUNT_JS))
        except Exception:  # noqa: BLE001
            before = 0
        clicked = _click(popup, EXTERNAL_ADD_ID)
        if not clicked.get("ok") or not wait_until(lambda: int(popup.evaluate(EXTERNAL_COUNT_JS)) > before, wait, tries=10):
            log("  ✗ 외부참석자 줄을 더하지 못함: " + str(clicked.get("why", "") or "줄이 생기지 않음"))
            break
        done = popup.evaluate(EXTERNAL_FILL_JS, [person.name, person.org])
        log("  %s 외부참석자: %s · %s%s" % ("✓" if done.get("ok") else "✗", person.name, person.org,
                                         "" if done.get("ok") else " — " + str(done.get("why", ""))))
        if done.get("ok"):
            added += 1
            have.add(_squash(person.name))
    return added


def record_sheet(job: card.CardJob, sheet: card.CardSheet, report: CardReport) -> None:
    """넣은 기록 — 폴더#비목 마다 결의번호와 임시저장한 결제 건. 앱을 다시 켜도 이어 넣을 수 있게."""
    from . import record
    saved = [{"name": r.name, "no": "", "course": ""} for r in report.results if r.status == "saved"]
    if not saved:
        return
    record.remember(sheet_key(job, sheet), {"summary": report.summary, "req_cnt": report.req_cnt,
                                            "amount": sum(i.amount or 0 for i in sheet.items if i.status == "saved")},
                    kind="card", people=saved)


def record_warning(job: card.CardJob, sheet: card.CardSheet) -> str:
    """결의서내역을 못 읽을 때 묻는 글 — 이 폴더 · 비목을 전에 넣은 앱 기록(18절과 같은 쓰임)."""
    from . import record
    entry = record.previous(sheet_key(job, sheet))
    if not entry:
        return ""
    saved = len(entry.get("saved") or [])
    return ("이 청구서를 전에 넣은 기록이 있습니다 — " + " / ".join(record.history_lines(entry))
            + (f" · 저장한 결제 건 {saved}건" if saved else ""))


def sheet_key(job: card.CardJob, sheet: card.CardSheet) -> str:
    return f"{job.folder}#{sheet.code}"


def restore(job: card.CardJob) -> None:
    """기록에서 결의번호 · 저장한 결제 건을 되살린다(폴더를 다시 읽은 뒤)."""
    from . import record
    for sheet in job.sheets:
        entry = record.previous(sheet_key(job, sheet)) or {}
        if entry.get("req_cnt"):
            sheet.req_cnt = str(entry["req_cnt"])
        names = {str(s.get("name", "")) for s in entry.get("saved") or [] if isinstance(s, dict)}
        for item in sheet.items:
            if item.name in names:
                item.status = "saved"
