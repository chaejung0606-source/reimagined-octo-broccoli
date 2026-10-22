"""주차등록 — '할인 적용'(차량번호로 바로 할인) · '운영 → 할인 내역' 화면. 담당자 요청 2026-10-21:
"할인적용에서 바로 차량번호 입력해서 주차등록할 수 있는 기능도 있습니다 … 운영-할인내역도 살펴볼 수 있도록 끌어와주세요".

두 화면 모두 **아직 [화면 구조 저장] 실측 전**이다(실측 ① 의 왼쪽 메뉴에서 주소만 안다: `/discount-apply` · `/discount-history` — CLAUDE.md 20절).

- 할인 적용: 담당자가 순서를 알려 주었다(같은 날 — "차량번호를 입력하고 보유 할인권에서 공무확인증 클릭, 그리고 할인선택에서 공무확인증
  선택하고 종료 버튼 클릭하면 할인이 적용됩니다. 이런 과정이 어플내에서 이뤄질 수 있도록"). 그래서 앱이 그 차례대로 하되, 단계마다 화면을 다시
  읽어 **할 것이 하나로 확실할 때만** 누른다: 차량번호 칸(하나) → Enter(안 넘어가면 [조회] · [검색] 이 하나일 때) → 그 차가 화면에 보이는지 →
  (그 차의 줄이 누를 수 있는 것 하나면 그 줄) → '보유 할인권' 의 '공무확인증'(하나) → '할인 선택' 의 '공무확인증'(고르기 칸의 보기 하나 또는
  누를 것 하나) → 골라졌는지 → [종료](하나). 어느 단계든 0개 · 여럿 · 사이트의 실패 알림이면 **[종료] 전에** 멈추고, 그 화면 모양을 남기게 한다
  (session.py 가 _화면구조_모음.txt 에 — 차량번호는 가림). 그 파일로 실측을 대신해 고친다.
- 할인 내역: 화면을 열고 보이는 표(줄이 가장 많은 것)의 머리글 · 줄을 읽기만 한다. 쪽 넘기기 · 기간 바꾸기 · [조회] 는 누르지 않는다 —
  사이트가 처음 보여 주는 쪽만.
차량번호는 앱 화면에만 보이고 기록 · 파일에는 남기지 않는다(mask_cars). Playwright 를 들여오지 않는다 — 창(page)은 session.py 가 넘겨준다.
"""
from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from . import parking, parking_ledger

APPLY_PATH = "/discount-apply"
HISTORY_PATH = "/discount-history"

_VIS = "const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };"
_CLEAN = "const clean = s => String(s || '').replace(/\\s+/g, ' ').trim();"
# 위쪽 계정 메뉴 · 왼쪽 메뉴 밖의 것만 — 계정 메뉴 글자에는 사이트 아이디가 보인다(기록에 남기지 않는다)
_MAIN = ("const inMenu = e => !!e.closest('nav, header, aside, .navbar, .sidebar, .dropdown-menu, .dropdown');")

# 차량번호 칸을 찾아 표시를 붙인다 — 이름 · 안내문 · label 에 차량 · 차번 · 번호판 · car · plate · vehicle 이 든 글 칸이 하나면 그것,
# 그런 칸이 없고 화면의 글 칸이 하나뿐이면 그것. 아니면 넣지 않는다. 화면의 칸 · 단추 글자도 돌려준다(기록용, 메뉴 밖만).
MARK_CAR_JS = """() => {
  %s %s %s
  document.querySelectorAll('[data-coss-car]').forEach(e => e.removeAttribute('data-coss-car'));
  const labelOf = e => {
    let t = [e.getAttribute('aria-label'), e.getAttribute('placeholder'), e.name, e.id].filter(Boolean).join(' ');
    if (e.id) { const l = document.querySelector('label[for="' + e.id + '"]'); if (l) t = clean(l.innerText) + ' ' + t; }
    const box = e.closest('label, .form-group, .mb-3, .input-group, td, div');
    const l = box && box.querySelector('label, .form-label');
    if (l && !l.contains(e)) t = clean(l.innerText) + ' ' + t;
    return clean(t).slice(0, 40);
  };
  const inputs = Array.from(document.querySelectorAll('input')).filter(e => vis(e) && !inMenu(e) && !e.disabled && !e.readOnly
    && /^(text|search|tel|)$/.test((e.getAttribute('type') || '').toLowerCase()));
  const words = /차량|차번|번호판|car|plate|vehicle/i;
  const hits = inputs.filter(e => words.test(labelOf(e)));
  const pick = hits.length === 1 ? hits[0] : (!hits.length && inputs.length === 1 ? inputs[0] : null);
  const buttons = Array.from(document.querySelectorAll('button, input[type=submit], input[type=button], a.btn'))
    .filter(b => vis(b) && !inMenu(b)).map(b => clean(b.innerText || b.value).slice(0, 20)).filter(Boolean).slice(0, 15);
  const selects = Array.from(document.querySelectorAll('select')).filter(s => vis(s) && !inMenu(s)).map(labelOf).slice(0, 5);
  const shape = {inputs: inputs.map(labelOf).slice(0, 10), selects, buttons};
  if (!pick) return Object.assign(shape, {ok: false, why: hits.length > 1 ? '차량번호로 보이는 칸이 여럿'
    : inputs.length ? '차량번호 칸을 알아보지 못함(글 칸 ' + inputs.length + '개)' : '글 칸이 없음'});
  pick.setAttribute('data-coss-car', '1');
  return Object.assign(shape, {ok: true, label: labelOf(pick)});
}""" % (_VIS, _CLEAN, _MAIN)
CAR_SELECTOR = "[data-coss-car]"
CAR_VALUE_JS = "() => { const e = document.querySelector('[data-coss-car]'); return e ? e.value : null; }"

# 보이는 표 중 줄이 가장 많은 것의 머리글 · 줄. 한 칸짜리 줄('조회된 내역이 없습니다' 같은)은 빈 표의 알림으로 본다.
TABLE_JS = """() => {
  %s %s
  const tables = Array.from(document.querySelectorAll('table')).filter(vis);
  if (!tables.length) return {tables: 0, headers: [], rows: []};
  const bodyRows = t => Array.from(t.tBodies.length ? t.querySelectorAll('tbody tr') : t.rows)
    .filter(tr => !tr.closest('thead') && Array.from(tr.cells).some(c => c.tagName === 'TD'));
  const table = tables.reduce((a, b) => bodyRows(b).length > bodyRows(a).length ? b : a);
  let headers = Array.from(table.querySelectorAll('thead th')).map(th => clean(th.innerText));
  if (!headers.length) {
    const first = Array.from(table.rows).find(tr => Array.from(tr.cells).every(c => c.tagName === 'TH'));
    headers = first ? Array.from(first.cells).map(th => clean(th.innerText)) : [];
  }
  const rows = bodyRows(table).map(tr => Array.from(tr.cells).map(td => clean(td.innerText))).filter(r => r.some(Boolean));
  const note = rows.length === 1 && rows[0].length === 1 && headers.length > 1 ? rows[0][0] : '';
  const pager = Array.from(document.querySelectorAll('.pagination, [class*=paging], [class*=pager]')).filter(vis)
    .map(p => clean(p.innerText)).join(' ').slice(0, 80);
  const total = (clean(document.body.innerText).match(/(총|전체)\\s*[\\d,]+\\s*(건|개|대)/) || [''])[0];
  return {tables: tables.length, headers, rows: note ? [] : rows, note, pager, total};
}""" % (_VIS, _CLEAN)


# 할인 내역의 거르기 칸(실측 2026-10-22 10:07): 시작일 · 종료일(date) · 차량번호 · 할인유형 · 적용방식 · [검색] · 엑셀, 표 아래 건수 고르기(10 · 20 · 50 · 100건)와
# 쪽 단추(« ‹ 1 2 3 4 › », class page-link). 표시만 붙이고 누르는 것은 Playwright(아래 read_history). 값을 넣는 칸은 시작일 하나, 고르기는 건수 하나.
HISTORY_CONTROLS_JS = """() => {
  %s %s
  document.querySelectorAll('[data-coss-history]').forEach(e => e.removeAttribute('data-coss-history'));
  const away = e => !!e.closest('nav, aside, .sidebar, .dropdown-menu');
  const labelOf = e => {
    let t = [e.getAttribute('aria-label'), e.getAttribute('title'), e.getAttribute('placeholder'), e.name, e.id].filter(Boolean).join(' ');
    if (e.id) { const l = document.querySelector('label[for="' + e.id + '"]'); if (l) t = clean(l.innerText) + ' ' + t; }
    return clean(t);
  };
  const dates = Array.from(document.querySelectorAll('input[type=date]')).filter(e => vis(e) && !away(e) && !e.disabled);
  const from = dates.find(e => /시작|from|start/i.test(labelOf(e))) || (dates.length === 2 ? dates[0] : null);
  if (from) from.setAttribute('data-coss-history', 'from');
  const sizes = Array.from(document.querySelectorAll('select')).filter(e => vis(e) && !away(e)
    && Array.from(e.options).some(o => /^100\\s*(건|개)?$/.test(clean(o.text))));
  const size = sizes.length === 1 ? sizes[0] : null;
  let big = '';
  if (size) {
    size.setAttribute('data-coss-history', 'size');
    big = clean(Array.from(size.options).find(o => /^100\\s*(건|개)?$/.test(clean(o.text))).text);
  }
  const searches = Array.from(document.querySelectorAll('button, input[type=submit], input[type=button]'))
    .filter(b => vis(b) && !away(b) && !b.disabled && /검색|조회/.test(clean(b.innerText || b.value)) && clean(b.innerText || b.value).length <= 12);
  if (searches.length === 1) searches[0].setAttribute('data-coss-history', 'search');
  return {from: from ? from.value : null, dates: dates.length, size: size ? clean(size.options[size.selectedIndex].text) : null,
          big, searches: searches.length};
}""" % (_VIS, _CLEAN)

# 다음 쪽 단추 '›'(또는 '다음' · aria-label next) 하나 — 꺼져 있으면(disabled · li.disabled · aria-disabled) 없음으로. 지금 쪽 · 보이는 쪽 번호도.
HISTORY_NEXT_JS = """() => {
  %s %s
  document.querySelectorAll('[data-coss-history=next]').forEach(e => e.removeAttribute('data-coss-history'));
  const links = Array.from(document.querySelectorAll('.pagination a, .pagination button, a.page-link, button.page-link')).filter(vis);
  const off = b => b.disabled || b.getAttribute('aria-disabled') === 'true' || !!(b.closest('li') && b.closest('li').classList.contains('disabled'));
  const nexts = links.filter(b => { const t = clean(b.innerText), a = b.getAttribute('aria-label') || '';
    return t === '›' || t === '>' || t === '다음' || /^next/i.test(a) || a === '다음'; });
  const active = links.find(b => (b.closest('li') && b.closest('li').classList.contains('active')) || b.getAttribute('aria-current') === 'page');
  const numbers = links.map(b => clean(b.innerText)).filter(t => /^\\d+$/.test(t)).map(Number);
  const out = {current: active ? clean(active.innerText) : '', last: numbers.length ? Math.max(...numbers) : 0, next: false};
  if (nexts.length === 1 && !off(nexts[0])) { nexts[0].setAttribute('data-coss-history', 'next'); out.next = true; }
  return out;
}""" % (_VIS, _CLEAN)
HISTORY_MAX_PAGES = 60
HISTORY_FROM = "[data-coss-history=from]"
HISTORY_SIZE = "[data-coss-history=size]"


def _evaluate(frame, js, arg=None):
    try:
        return frame.evaluate(js) if arg is None else frame.evaluate(js, arg)
    except Exception:  # noqa: BLE001 — 바뀌는 중인 화면
        return None


def _goto(page, base_url: str, path: str, report) -> None:
    if base_url:
        page.goto(base_url.rstrip("/") + path, wait_until="domcontentloaded")
        report.steps.append(path + " 화면을 엶")


def _logged_out(frame) -> bool:
    return (_evaluate(frame, parking.LOGIN_FORM_JS) or 0) > 0


# 표가 아직 받아 오는 중이라는 한 칸 줄 — 이것을 '내역 없음' 으로 보면 빈 표로 끝난다(모의 화면에서 겪음)
LOADING = re.compile(r"불러오|로딩|loading|잠시|조회\s*중|읽는\s*중", re.I)

NOT_LOGGED_IN = "주차 사이트에 로그인돼 있지 않습니다 — 설정의 '주차등록 로그인 정보' 를 넣거나 브라우저에서 로그인한 뒤 다시"


def car_number(text: str) -> str:
    """차량번호는 띄어쓰기만 뗀다 — 사이트가 받는 꼴(전체 · 뒤 4자리)은 실측 전이라 바꾸지 않는다."""
    return re.sub(r"\s+", "", str(text or ""))


# ── 할인 적용 ──────────────────────────────────────────────────────────
TICKET_WORD = "공무확인증"            # 담당자 2026-10-21: 보유 할인권 · 할인 선택에서 고르는 것

# 할인 적용 화면을 읽는다 — 그 차가 보이는지 · 그 차의 줄 · 이름에 '공무확인증' 이 든 누를 것(보유 할인권 / 할인 선택 구역) · 고르기 칸 ·
# [조회] · [종료]. 누를 후보에 표시(data-coss-apply)를 붙이기만 하고 누르지 않는다 — 누르기는 Playwright click 으로(진짜 마우스 입력).
# 구역은 가까운 조상 안에서 그 요소 앞에 있는 짧은 글자('보유 할인권' · '할인 선택')로 정한다(실측 전이라 모양을 가정하지 않는다).
SCAN_APPLY_JS = """(arg) => {
  %s %s %s
  const squash = s => String(s || '').replace(/\\s+/g, '').toLowerCase();
  const car = squash(arg.car), word = squash(arg.word);
  document.querySelectorAll('[data-coss-apply]').forEach(e => e.removeAttribute('data-coss-apply'));
  const carInput = document.querySelector('[data-coss-car]');
  const pointer = e => { try { return getComputedStyle(e).cursor === 'pointer'; } catch (x) { return false; } };
  const clickable = e => e.matches('button, a, label, [onclick], [tabindex], [role=button], [role=option], [role=tab], [role=radio], '
    + '.btn, .list-group-item, input[type=button], input[type=submit], input[type=radio], input[type=checkbox]') || pointer(e);
  const all = Array.from(document.querySelectorAll('body *')).filter(e => !/^(SCRIPT|STYLE|SELECT|OPTION|svg|path)$/i.test(e.tagName));
  const heads = all.filter(e => { const t = squash(e.textContent); return t.length <= 12 && /보유|할인선택|선택할인/.test(t); })
    .filter(e => vis(e) && !inMenu(e));
  const leafHeads = heads.filter(h => !heads.some(o => o !== h && h.contains(o))).map(h => [h, squash(h.textContent)]);
  const sectionOf = e => {
    for (let p = e.parentElement, i = 0; p && p !== document.documentElement && i < 10; p = p.parentElement, i++) {
      const inside = leafHeads.filter(([h]) => p.contains(h) && !h.contains(e) && !e.contains(h)
        && (h.compareDocumentPosition(e) & Node.DOCUMENT_POSITION_FOLLOWING));
      if (inside.length) return /보유/.test(inside[inside.length - 1][1]) ? 'own' : 'pick';
    }
    return '';
  };
  const minimal = list => list.filter(e => !list.some(o => o !== e && e.contains(o)));
  const activeOf = e => {
    const box = e.matches('input') ? e : e.querySelector('input[type=radio], input[type=checkbox]');
    if (box) return !!box.checked;
    return /(^|\\s)(active|selected|checked|on)(\\s|$)/.test(e.className || '') || e.getAttribute('aria-selected') === 'true'
      || e.getAttribute('aria-pressed') === 'true' || e.getAttribute('aria-checked') === 'true';
  };
  const textOf = e => clean(e.innerText || e.textContent || e.value).slice(0, 40);
  const tickets = minimal(all.filter(e => { const t = squash(e.textContent || e.value); return t.includes(word) && t.length <= 40
    && vis(e) && !inMenu(e) && clickable(e) && !e.querySelector('select'); }))
    .map((e, i) => { e.setAttribute('data-coss-apply', 'ticket-' + i);
      return {text: textOf(e), section: sectionOf(e), active: activeOf(e)}; });
  const selects = Array.from(document.querySelectorAll('select')).filter(s => vis(s) && !inMenu(s) && !s.disabled)
    .map((s, i) => { s.setAttribute('data-coss-apply', 'select-' + i);
      const options = Array.from(s.options).map((o, j) => ({index: j, text: clean(o.text)})).filter(o => squash(o.text).includes(word));
      const chosen = s.selectedIndex >= 0 ? clean(s.options[s.selectedIndex].text) : '';
      return {options, chosen, section: sectionOf(s)}; });
  const body = squash(document.body.innerText);
  const cars = car ? minimal(all.filter(e => { const t = squash(e.textContent); return t.includes(car) && t.length <= 80
    && vis(e) && !inMenu(e) && clickable(e) && !(carInput && (e.contains(carInput) || e === carInput)); }))
    .map((e, i) => { e.setAttribute('data-coss-apply', 'car-' + i); return 1; }).length : 0;
  const named = re => Array.from(document.querySelectorAll('button, a, input[type=button], input[type=submit], [role=button]'))
    .filter(b => vis(b) && !inMenu(b) && !b.disabled && re.test(squash(b.innerText || b.value)));
  const finishes = named(/^종료(하기)?$/);
  finishes.forEach((b, i) => b.setAttribute('data-coss-apply', 'finish-' + i));
  const searches = named(/^(조회|검색|찾기|search)$/);
  searches.forEach((b, i) => b.setAttribute('data-coss-apply', 'search-' + i));
  const pickText = leafHeads.filter(([h, t]) => !/보유/.test(t)).map(([h]) => {
    let p = h.parentElement; for (let i = 0; i < 3 && p && squash(p.textContent).length < 12; i++) p = p.parentElement;
    return squash(p ? p.textContent : ''); }).join(' ');
  return {carShown: !!car && body.includes(car), cars, tickets, selects, finishes: finishes.length, searches: searches.length,
    heads: leafHeads.map(([h, t]) => t).slice(0, 6), pickHasWord: pickText.includes(word)};
}""" % (_VIS, _CLEAN, _MAIN)

# 사이트가 띄운 글(알림 상자 · 토스트 · 창 안 글) — [종료] 뒤 됐는지 볼 때
FEEDBACK_JS = """() => {
  %s %s
  return Array.from(document.querySelectorAll('.alert, .toast, .toast-body, [role=alert], .swal2-popup, .modal-body, .invalid-feedback'))
    .filter(vis).map(e => clean(e.innerText)).filter(Boolean).slice(0, 5);
}""" % (_VIS, _CLEAN)

FAIL_WORDS = re.compile(r"실패|오류|에러|없습니다|없는|초과|부족|불가|못|만료|error|fail", re.I)
DONE_WORDS = re.compile(r"완료|적용되|적용 되|성공|처리되|등록되|저장되")
_PLATE = re.compile(r"\d{2,3}\s?[가-힣]\s?\d{4}")


def mask_cars(text: str) -> str:
    """기록 · 화면 구조 파일에서 차량번호(12가3456 꼴)를 가린다 — 차량번호는 앱 화면에만."""
    return _PLATE.sub("(차량번호)", str(text or ""))


@dataclass
class ApplyReport:
    opened: bool = False
    filled: bool = False
    applied: bool = False         # [종료](또는 공무확인증)를 누른 뒤 사이트가 실패를 알리지 않음 — 관리대장에 적는다
    confirmed: bool = False       # 사이트가 '완료 · 적용되었습니다' 같은 글을 띄움
    pressed_finish: bool = False
    capture: bool = False         # 멈춘 화면의 모양을 남길지(실측 전이라 — session.py 가 _화면구조_모음.txt 에)
    saved: str = ""               # 남긴 화면 구조 파일 이름(session.save_parking_screen)
    ticket: str = ""              # 고른 할인권 글자
    left_before: int | None = None   # 보유 할인권 글자에 보인 남은 수(누르기 전) — 적용되면 1 줄어든 수가 사이트 잔량
    note: str = ""
    steps: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)   # 사이트 알림(차량번호는 가림)
    shape: dict = field(default_factory=dict)

    def lines(self) -> list[str]:
        """기록에 남기는 줄 — 차량번호는 넣지 않는다."""
        if not self.opened:
            return ["✗ 할인 적용 화면을 열지 못했습니다" + (f" — {self.note}" if self.note else "")]
        if self.applied:
            head = "✓ 할인을 적용했습니다" + (f" — {self.ticket}" if self.ticket else "") + ("" if self.confirmed else " (사이트의 완료 글은 못 봄)")
        else:
            head = "✗ 할인을 적용하지 못했습니다" + (f" — {self.note}" if self.note else "")
            if not self.pressed_finish:
                head += " · [종료] 는 누르지 않았습니다"
        return [head] + ["  · " + s for s in self.steps] + ["  사이트 알림: " + m for m in self.messages]


def _click(frame, mark: str) -> str:
    """표시를 붙인 것을 Playwright 로 누른다(진짜 마우스 입력). 못 누르면 까닭."""
    try:
        frame.click(f"[data-coss-apply={mark}]", timeout=5000)
        return ""
    except Exception as error:  # noqa: BLE001 — 가려졌거나 사라짐
        return str(error).splitlines()[0][:100] if str(error) else type(error).__name__


def _pick_option(options: list[dict], ticket: str) -> dict | None:
    """할인 선택 고르기 칸의 '공무확인증' 보기 — 하나면 그것, 여럿이면 보유 할인권에서 누른 글자와 같은(한쪽이 다른 쪽을 담는) 것 하나."""
    if len(options) == 1:
        return options[0]
    key = re.sub(r"\s+", "", product_label(ticket)).lower()
    same = [o for o in options if key and (key in re.sub(r"\s+", "", o["text"]).lower() or re.sub(r"\s+", "", o["text"]).lower() in key)]
    return same[0] if len(same) == 1 else None


def product_label(text: str) -> str:
    """'교환공무확인증4시간 (잔량 85)' · '공무확인증 4시간 85매' · '공무확인증 4시간 (85)' → 남은 수를 뗀 이름."""
    text = re.sub(r"\(\s*(잔량[^)]*|\d+\s*(매|장|개)?)\s*\)", "", str(text or ""))
    return re.sub(r"\s*\d+\s*(매|장|개)\s*$", "", text).strip()


def apply_discount(page, car: str, log: Callable[[str], None], wait: Callable[[float], None], base_url: str = "",
                   word: str = TICKET_WORD, step: float = 0.5, finish_wait: float = 8.0) -> ApplyReport:
    """할인 적용 화면에서 담당자가 알려 준 차례대로 — 차량번호 → 보유 할인권 '공무확인증' → 할인 선택 '공무확인증' → [종료].
    단계마다 할 것이 하나로 확실할 때만 누르고, 아니면 [종료] 전에 멈춘다(report.capture — 그 화면 모양을 남긴다)."""
    report = ApplyReport()
    number = car_number(car)
    if not number:
        report.note = "차량번호를 넣어 주세요"
        return report
    frame = page.main_frame
    _goto(page, base_url, APPLY_PATH, report)
    shape: dict = {}
    for _ in range(16):                          # 화면이 그려질 때까지(칸이 생기거나 로그인 화면)
        if _logged_out(frame):
            report.note = NOT_LOGGED_IN
            return report
        shape = _evaluate(frame, MARK_CAR_JS) or {}
        if shape.get("ok") or shape.get("inputs") or shape.get("buttons"):
            break
        wait(step)
    report.opened = True
    report.shape = shape
    log("주차 할인 적용 화면: 글 칸 " + (" · ".join(shape.get("inputs") or []) or "없음")
        + " / 고르기 " + (" · ".join(shape.get("selects") or []) or "없음")
        + " / 단추 " + (" · ".join(shape.get("buttons") or []) or "없음"))
    if not shape.get("ok"):
        report.note, report.capture = (shape.get("why") or "화면을 읽지 못함"), True
        return report
    frame.fill(CAR_SELECTOR, number)
    if _evaluate(frame, CAR_VALUE_JS) != number:
        report.note, report.capture = "차량번호를 넣었지만 칸에 남지 않았습니다", True
        return report
    report.filled = True
    report.steps.append(f"'{shape.get('label') or '차량번호'}' 칸에 차량번호를 넣음")

    def on_dialog(dialog) -> None:              # 사이트 알림 · 확인 — 담당자가 앱의 [할인 적용] 을 눌렀으니 [확인]
        try:
            report.messages.append(mask_cars((dialog.message or "").strip())[:200])
            dialog.accept()
        except Exception:  # noqa: BLE001
            pass

    def scan() -> dict:
        return _evaluate(frame, SCAN_APPLY_JS, {"car": number, "word": word}) or {}

    def failed_now() -> str:
        bad = [m for m in report.messages if FAIL_WORDS.search(m)]
        return bad[-1] if bad else ""

    def stop(note: str) -> ApplyReport:
        report.note, report.capture = note, True
        seen = scan()
        log("주차 할인 적용 — 멈춘 화면: 구역 " + (" · ".join(seen.get("heads") or []) or "없음")
            + f" / '{word}' 누를 것 {len(seen.get('tickets') or [])} · 고르기 칸 {len(seen.get('selects') or [])}"
            + f" · [종료] {seen.get('finishes', 0)} · 그 차 보임 {'예' if seen.get('carShown') else '아니요'}")
        return report

    page.on("dialog", on_dialog)
    try:
        frame.press(CAR_SELECTOR, "Enter")
        report.steps.append("Enter")
        # ① 그 차가 화면에 보일 때까지 — Enter 로 안 넘어가면 [조회] · [검색] 이 하나일 때 한 번
        searched = car_clicked = False
        seen: dict = {}
        for tick in range(30):
            wait(step)
            if failed_now():
                return stop("사이트 알림: " + failed_now())
            seen = scan()
            if seen.get("carShown"):
                break
            if tick == 5 and not searched and seen.get("searches") == 1:
                why = _click(frame, "search-0")
                if why:
                    return stop("[조회] 를 누르지 못했습니다: " + why)
                searched = True
                report.steps.append("[조회] 누름")
        else:
            return stop("그 차량을 찾지 못했습니다 — 입차 기록이 없거나 번호가 다릅니다(전체 번호로 넣어 보세요)")
        # ② 그 차의 줄이 누를 수 있는 것으로 하나면 누른다(목록에서 차를 골라야 하는 화면). 여럿이면 어느 차인지 모른다
        own = [t for t in seen.get("tickets") or [] if t.get("section") != "pick"]
        if seen.get("cars", 0) > 1:
            return stop(f"번호가 같은 차가 {seen['cars']}대 보입니다 — 전체 번호로 넣어 주세요")
        if seen.get("cars") == 1 and not own:
            why = _click(frame, "car-0")
            if why:
                return stop("그 차의 줄을 누르지 못했습니다: " + why)
            car_clicked = True
            report.steps.append("그 차의 줄을 누름")
        # ③ 보유 할인권의 '공무확인증' — 구역을 알면 '보유' 구역에서, 모르면(구역 글자가 없는 화면) 누를 것이 하나일 때만
        ticket = None
        for _ in range(12):
            if car_clicked or ticket is None:
                seen = scan()
            tickets = seen.get("tickets") or []
            own = [(i, t) for i, t in enumerate(tickets) if t.get("section") == "own"] or \
                  [(i, t) for i, t in enumerate(tickets) if not t.get("section")]
            if len(own) == 1:
                ticket = own[0]
                break
            if len(own) > 1:
                return stop(f"보유 할인권에 '{word}' 가 여럿입니다: " + " / ".join(t.get("text", "") for _, t in own[:4]))
            wait(step)
        if ticket is None:
            return stop(f"보유 할인권에서 '{word}' 를 찾지 못했습니다")
        report.ticket = product_label(ticket[1].get("text", "")) or word
        report.left_before = parking_ledger.left_of(ticket[1].get("text", ""))
        why = _click(frame, f"ticket-{ticket[0]}")
        if why:
            return stop(f"보유 할인권 '{report.ticket}' 를 누르지 못했습니다: " + why)
        report.steps.append(f"보유 할인권 '{report.ticket}' 누름")
        # ④ 할인 선택의 '공무확인증' — 고르기 칸이면 그 보기, 누를 것이면 '할인 선택' 구역의 것 하나. 누르자마자 사이트가 적용했으면 거기서 끝
        chosen = by_select = False
        for _ in range(12):
            wait(step)
            if failed_now():
                return stop("사이트 알림: " + failed_now())
            if any(DONE_WORDS.search(m) for m in report.messages):
                report.applied = report.confirmed = True
                report.steps.append("보유 할인권을 누르자 사이트가 적용을 알림")
                return report
            seen = scan()
            selects = [(i, s) for i, s in enumerate(seen.get("selects") or []) if s.get("options")]
            picks = [(i, t) for i, t in enumerate(seen.get("tickets") or []) if t.get("section") == "pick"]
            if len(selects) > 1:
                return stop(f"'{word}' 보기가 든 고르기 칸이 여럿입니다")
            if selects:
                index, box = selects[0]
                option = _pick_option(box["options"], report.ticket)
                if option is None:
                    return stop(f"할인 선택의 '{word}' 보기가 여럿입니다: " + " / ".join(o["text"] for o in box["options"][:4]))
                if word not in re.sub(r"\s+", "", box.get("chosen", "")):
                    frame.select_option(f"[data-coss-apply=select-{index}]", index=option["index"])
                    report.steps.append(f"할인 선택에서 '{option['text']}' 고름")
                chosen = by_select = True
                break
            if len(picks) > 1:
                return stop(f"할인 선택에 '{word}' 가 여럿입니다: " + " / ".join(t.get("text", "") for _, t in picks[:4]))
            if picks:
                index, item = picks[0]
                if not item.get("active"):
                    why = _click(frame, f"ticket-{index}")
                    if why:
                        return stop(f"할인 선택의 '{item.get('text')}' 를 누르지 못했습니다: " + why)
                    report.steps.append(f"할인 선택에서 '{product_label(item.get('text', ''))}' 누름")
                chosen = True
                break
        if not chosen:
            # '할인 선택' 에 글자만 들어가고 고를 것이 안 보이는 화면도 여기서 멈춘다 — 골랐는지 모른 채 [종료] 하지 않는다
            return stop(f"할인 선택에서 '{word}' 를 고를 칸을 찾지 못했습니다" + (" (글자는 보임)" if seen.get("pickHasWord") else ""))
        # ⑤ 골라졌는지 다시 보고 [종료] — 하나일 때만
        wait(step)
        seen = scan()
        if failed_now():
            return stop("사이트 알림: " + failed_now())
        # 고르기 칸이면 골라진 보기를 다시 본다. 누를 것이었으면 누른 것으로(눌린 모양은 화면마다 달라 보지 않는다)
        if by_select and not any(word in re.sub(r"\s+", "", s.get("chosen", "")) for s in seen.get("selects") or [] if s.get("options")):
            return stop(f"할인 선택에 '{word}' 가 골라지지 않았습니다")
        if seen.get("finishes") != 1:
            return stop("[종료] 단추가 " + ("여럿입니다" if seen.get("finishes") else "보이지 않습니다"))
        before = len(report.messages)
        why = _click(frame, "finish-0")
        if why:
            return stop("[종료] 를 누르지 못했습니다: " + why)
        report.pressed_finish = True
        report.steps.append("[종료] 누름")
        for _ in range(max(1, int(finish_wait / step))):
            wait(step)
            if len(report.messages) > before and not any(m.endswith("?") for m in report.messages[before:]):
                break
        after = report.messages[before:] + [mask_cars(m) for m in (_evaluate(frame, FEEDBACK_JS) or [])]
        bad = [m for m in after if FAIL_WORDS.search(m) and not DONE_WORDS.search(m)]
        if bad:
            report.note, report.capture = "사이트 알림: " + bad[-1] + " — 할인 내역에서 확인해 주세요", True
            return report
        report.confirmed = any(DONE_WORDS.search(m) for m in after)
        # 완료 글이 없으면 화면이 처음으로 돌아갔는지(차량번호 칸이 비거나 그 차가 안 보임)로 본다 — 둘 다 아니면 적용됐는지 모른다
        reset = not (_evaluate(frame, CAR_VALUE_JS) or "") or not scan().get("carShown")
        if report.confirmed or reset:
            report.applied = True
            if not report.confirmed:
                report.steps.append("사이트가 완료 글 없이 처음 화면으로 돌아감")
            return report
        report.note, report.capture = "[종료] 는 눌렀지만 적용됐는지 사이트가 알리지 않았습니다 — 할인 내역에서 확인해 주세요", True
        return report
    finally:
        try:
            page.remove_listener("dialog", on_dialog)
        except Exception:  # noqa: BLE001
            pass


# ── 할인 내역 ──────────────────────────────────────────────────────────
@dataclass
class HistoryReport:
    ok: bool = False
    note: str = ""
    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    empty_note: str = ""          # 사이트가 띄운 '내역 없음' 글
    pager: str = ""               # 다 읽지 못했을 때 그 까닭(쪽 넘기기가 안 됨 등) — 비었으면 모든 쪽을 읽은 것
    products: list[str] = field(default_factory=list)   # 같이 읽은 할인권 상품 보기(보유 잔량, parking_link.read_products)
    total: str = ""               # 화면의 '총 N건'
    read_at: str = ""
    read_stamp: str = ""          # 읽은 때 'YYYY-MM-DD HH:MM:SS' — 다음에 읽을 때 잔량 변화와 그 사이 사용을 맞춰 본다
    since: str = ""               # 시작일(거르기) — 비었으면 사이트 기본 기간
    pages: int = 0                # 읽은 쪽 수
    steps: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        if not self.ok:
            return ["✗ 할인 내역을 읽지 못했습니다" + (f" — {self.note}" if self.note else "")]
        head = f"✓ 할인 내역 {len(self.rows)}줄을 읽었습니다" + (f" ({self.pages}쪽" + (f" · {self.since}부터" if self.since else "") + ")"
                                                               if self.pages else "")
        if self.empty_note:
            head = f"✓ 할인 내역 — 사이트: {self.empty_note}"
        out = [head]
        if self.pager:
            out.append("  · " + self.pager)
        return out


def _signature(table: dict) -> tuple:
    rows = table.get("rows") or []
    return (len(rows), tuple(rows[0]) if rows else (), tuple(rows[-1]) if rows else (), table.get("pager") or "", table.get("note") or "")


def _settle(frame, wait: Callable[[float], None], tries: int, before: tuple | None = None) -> dict:
    """표를 다시 읽어 줄 수가 두 번 연달아 같을 때(목록을 받아 오는 중이 아닐 때)까지. before 가 있으면 그 모양에서 바뀐 뒤를 기다리되,
    끝내 안 바뀌면(거르기를 바꿔도 같은 목록) 그대로 돌려준다. 표가 없으면 {}."""
    table: dict = {}
    last = None
    changed = before is None
    for i in range(tries):
        if _logged_out(frame):
            return {"logged_out": True}
        table = _evaluate(frame, TABLE_JS) or {}
        sig = _signature(table) if table.get("tables") else None
        loading = bool(LOADING.search(str(table.get("note") or "")))
        changed = changed or (sig is not None and sig != before) or i >= tries // 2
        if sig is not None and not loading and changed and sig == last and (sig[0] or sig[4] or i >= 6):
            break
        last = sig
        wait(0.5)
    return table


def _press(frame, mark: str) -> str:
    try:
        frame.click(f"[data-coss-history={mark}]", timeout=5000)
        return ""
    except Exception as error:  # noqa: BLE001 — 가려졌거나 사라짐
        return str(error).splitlines()[0][:100] if str(error) else type(error).__name__


def _widen(frame, wait: Callable[[float], None], since: str, table: dict, report: HistoryReport) -> dict:
    """한 쪽에 100건 · 시작일을 since 로(사이트 기본은 한 달 전부터 20건씩) — 담당자 2026-10-22 "전체 페이지 확인해주세요".
    값을 넣는 것은 시작일 하나, 누르는 것은 [검색] 하나. 칸을 못 알아보면 그대로 두고 기본 기간만 읽는다(까닭을 남긴다)."""
    controls = _evaluate(frame, HISTORY_CONTROLS_JS) or {}
    if controls.get("size") is not None and controls.get("big") and controls.get("size") != controls.get("big"):
        try:
            before = _signature(table)
            frame.select_option(HISTORY_SIZE, label=controls["big"], timeout=5000)
            report.steps.append(f"한 쪽에 {controls['big']}")
            table = _settle(frame, wait, 16, before) or table
        except Exception as error:  # noqa: BLE001
            report.steps.append("건수를 바꾸지 못함: " + (str(error).splitlines()[0][:80] if str(error) else type(error).__name__))
        controls = _evaluate(frame, HISTORY_CONTROLS_JS) or {}
    current = controls.get("from")
    if not since:
        return table
    if current is None:
        report.pager = "시작일 칸을 알아보지 못해 사이트 기본 기간만 읽었습니다"
        return table
    if current and current <= since:
        report.since = current
        return table
    if controls.get("searches") != 1:
        report.pager = "[검색] 단추를 알아보지 못해 사이트 기본 기간만 읽었습니다"
        return table
    try:
        frame.fill(HISTORY_FROM, since, timeout=5000)
    except Exception as error:  # noqa: BLE001
        report.pager = "시작일을 넣지 못해 사이트 기본 기간만 읽었습니다(" + (str(error).splitlines()[0][:60] if str(error) else "") + ")"
        return table
    before = _signature(table)
    why = _press(frame, "search")
    if why:
        report.pager = "[검색] 을 누르지 못해 사이트 기본 기간만 읽었습니다(" + why + ")"
        return table
    report.since = since
    report.steps.append(f"시작일 {since} · [검색]")
    table = _settle(frame, wait, 20, before) or table
    again = _evaluate(frame, HISTORY_CONTROLS_JS) or {}
    if again.get("size") is not None and again.get("big") and again.get("size") != again.get("big"):   # [검색] 이 건수를 되돌렸으면
        return _widen(frame, wait, "", table, report)
    return table


def read_history(page, log: Callable[[str], None], wait: Callable[[float], None], base_url: str = "",
                 tries: int = 20, since: str = "") -> HistoryReport:
    """할인 내역 화면을 열고 표를 **모든 쪽** 읽는다(담당자 2026-10-22 "지금 1페이지만 확인했는데 전체 페이지 확인해주세요").
    시작일을 since 로 바꾸고 한 쪽에 100건으로 한 뒤 '›' 로 끝 쪽까지 — 표의 줄 · 차량번호 단추 · 엑셀은 누르지 않는다(읽기만)."""
    report = HistoryReport()
    frame = page.main_frame
    _goto(page, base_url, HISTORY_PATH, report)
    table = _settle(frame, wait, tries)
    if table.get("logged_out"):
        report.note = NOT_LOGGED_IN
        return report
    if not table.get("tables"):
        report.note = "화면에 표가 없습니다 — 사이트 모양이 다르면 '화면 구조 저장' 업무로 그 화면을 저장해 보내 주세요"
        return report
    table = _widen(frame, wait, since, table, report)
    if table.get("logged_out"):
        report.note = NOT_LOGGED_IN
        return report
    report.empty_note = str(table.get("note") or "")
    if LOADING.search(report.empty_note):
        report.note = f"표가 '{report.empty_note}' 에서 넘어가지 않았습니다 — 잠시 뒤 다시"
        return report
    report.headers = [str(h) for h in table.get("headers") or []]
    seen: set[tuple] = set()

    def take(t: dict) -> None:
        for r in t.get("rows") or []:
            row = [str(c) for c in r]
            if tuple(row) not in seen:          # 읽는 사이 새 줄이 생겨 앞 쪽 줄이 밀려 오면 한 번만
                seen.add(tuple(row))
                report.rows.append(row)

    take(table)
    report.pages = 1
    while report.pages < HISTORY_MAX_PAGES:
        pager = _evaluate(frame, HISTORY_NEXT_JS) or {}
        if not pager.get("next"):
            break
        before = _signature(table)
        why = _press(frame, "next")
        if why:
            report.pager = f"{report.pages}쪽 다음으로 넘기지 못해 거기까지만 읽었습니다({why})"
            break
        table = _settle(frame, wait, 16, before)
        if table.get("logged_out") or not table.get("tables"):
            report.pager = f"{report.pages}쪽 다음에서 표가 사라져 거기까지만 읽었습니다"
            break
        if _signature(table) == before:
            last = pager.get("last") or 0
            if not (last and str(last) == str(pager.get("current"))):
                report.pager = f"{report.pages}쪽에서 다음 쪽으로 넘어가지 않아 거기까지만 읽었습니다"
            break
        take(table)
        report.pages += 1
    else:
        report.pager = f"{HISTORY_MAX_PAGES}쪽까지만 읽었습니다"
    report.ok = True
    report.total = str(table.get("total") or "")
    now = dt.datetime.now()
    report.read_at, report.read_stamp = now.strftime("%H:%M"), now.strftime("%Y-%m-%d %H:%M:%S")
    # 줄에는 차량번호가 있어 기록에는 머리글 · 줄 수만
    log(f"주차 할인 내역 열: {' | '.join(report.headers) or '(머리글 없음)'} · {len(report.rows)}줄 · {report.pages}쪽"
        + (f" · {report.since}부터" if report.since else "") + (f" · {report.total}" if report.total else "")
        + (f" · {report.pager}" if report.pager else "") + (" · " + " · ".join(report.steps[1:]) if len(report.steps) > 1 else ""))
    return report
