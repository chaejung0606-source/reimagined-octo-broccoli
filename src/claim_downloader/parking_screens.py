"""주차등록 — '할인 적용'(차량번호로 바로 할인) · '운영 → 할인 내역' 화면. 담당자 요청 2026-10-21:
"할인적용에서 바로 차량번호 입력해서 주차등록할 수 있는 기능도 있습니다 … 운영-할인내역도 살펴볼 수 있도록 끌어와주세요".

두 화면 모두 **아직 실측 전**이다(실측 ① 의 왼쪽 메뉴에서 주소만 안다: `/discount-apply` · `/discount-history` — CLAUDE.md 20절).
그래서 여기서는 누르지 않는다:
- 할인 적용: 화면을 열고, 차량번호로 보이는 글 칸이 **하나**일 때만 그 칸에 번호를 넣어 둔다(Enter · [조회] · [적용] 은 사람이).
  화면에 보인 칸 · 단추 글자를 기록에 남겨 다음 실측 없이도 모양을 본다. 실측을 받으면 앱이 끝까지 하게 고친다.
- 할인 내역: 화면을 열고 보이는 표(줄이 가장 많은 것)의 머리글 · 줄을 읽기만 한다. 쪽 넘기기 · 기간 바꾸기 · [조회] 는 누르지 않는다 —
  사이트가 처음 보여 주는 쪽만. 차량번호가 든 줄은 앱 화면에만 보이고 기록 · 파일에는 남기지 않는다(머리글과 줄 수만).
Playwright 를 들여오지 않는다 — 창(page)은 session.py 가 넘겨준다.
"""
from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from . import parking

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


def _evaluate(frame, js):
    try:
        return frame.evaluate(js)
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
@dataclass
class ApplyReport:
    opened: bool = False
    filled: bool = False
    note: str = ""
    steps: list[str] = field(default_factory=list)
    shape: dict = field(default_factory=dict)     # 화면의 칸 · 단추 글자(메뉴 밖) — 실측 전이라 기록에 남긴다

    def lines(self) -> list[str]:
        if not self.opened:
            return ["✗ 할인 적용 화면을 열지 못했습니다" + (f" — {self.note}" if self.note else "")]
        if self.filled:
            head = "✓ 할인 적용 화면의 차량번호 칸에 넣었습니다 — 브라우저에서 [조회] · [적용] 을 눌러 주세요"
        else:
            head = "· 할인 적용 화면을 열었습니다" + (f" — {self.note}" if self.note else "")
        return [head] + ["  · " + s for s in self.steps]


def open_apply(page, car: str, log: Callable[[str], None], wait: Callable[[float], None], base_url: str = "",
               tries: int = 16) -> ApplyReport:
    """할인 적용 화면을 열고, 차량번호 칸이 하나로 확실하면 번호를 넣어 둔다. 아무것도 누르지 않는다."""
    report = ApplyReport()
    frame = page.main_frame
    _goto(page, base_url, APPLY_PATH, report)
    shape: dict = {}
    for _ in range(tries):                        # 화면이 그려질 때까지(칸이 생기거나 로그인 화면)
        if _logged_out(frame):
            report.note = NOT_LOGGED_IN
            return report
        shape = _evaluate(frame, MARK_CAR_JS) or {}
        if shape.get("ok") or shape.get("inputs") or shape.get("buttons"):
            break
        wait(0.5)
    report.opened = True
    report.shape = shape
    log("주차 할인 적용 화면: 글 칸 " + (" · ".join(shape.get("inputs") or []) or "없음")
        + " / 고르기 " + (" · ".join(shape.get("selects") or []) or "없음")
        + " / 단추 " + (" · ".join(shape.get("buttons") or []) or "없음"))
    number = car_number(car)
    if not number:
        report.note = "차량번호를 넣지 않아 화면만 열었습니다"
        return report
    if not shape.get("ok"):
        report.note = (shape.get("why") or "화면을 읽지 못함") + " — 브라우저에서 직접 넣어 주세요"
        return report
    page.main_frame.fill(CAR_SELECTOR, number)
    if _evaluate(frame, CAR_VALUE_JS) != number:
        report.note = "차량번호를 넣었지만 칸에 남지 않았습니다 — 브라우저에서 직접 넣어 주세요"
        return report
    report.filled = True
    report.steps.append(f"'{shape.get('label') or '차량번호'}' 칸에 넣음")
    return report


# ── 할인 내역 ──────────────────────────────────────────────────────────
@dataclass
class HistoryReport:
    ok: bool = False
    note: str = ""
    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    empty_note: str = ""          # 사이트가 띄운 '내역 없음' 글
    pager: str = ""               # 쪽 넘기기 글자 — 있으면 첫 쪽만 읽은 것
    total: str = ""               # 화면의 '총 N건'
    read_at: str = ""
    steps: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        if not self.ok:
            return ["✗ 할인 내역을 읽지 못했습니다" + (f" — {self.note}" if self.note else "")]
        head = f"✓ 할인 내역 {len(self.rows)}줄을 읽었습니다" + (f" ({self.total})" if self.total else "")
        if self.empty_note:
            head = f"✓ 할인 내역 — 사이트: {self.empty_note}"
        out = [head]
        if self.pager:
            out.append("  · 사이트가 처음 보여 주는 쪽만 읽었습니다 — 다른 쪽 · 다른 기간은 브라우저에서")
        return out


def read_history(page, log: Callable[[str], None], wait: Callable[[float], None], base_url: str = "",
                 tries: int = 20) -> HistoryReport:
    """할인 내역 화면을 열고 표를 읽는다(읽기만). 줄 수가 두 번 연달아 같으면(목록을 받아 오는 중이 아니면) 끝."""
    report = HistoryReport()
    frame = page.main_frame
    _goto(page, base_url, HISTORY_PATH, report)
    table: dict = {}
    last = None
    for i in range(tries):
        if _logged_out(frame):
            report.note = NOT_LOGGED_IN
            return report
        table = _evaluate(frame, TABLE_JS) or {}
        count = (len(table.get("rows") or []), table.get("note") or "")
        loading = bool(LOADING.search(count[1]))
        if table.get("tables") and not loading and (count == last and (count[0] or count[1] or i >= 6)):
            break
        last = count if table.get("tables") else None
        wait(0.5)
    if not table.get("tables"):
        report.note = "화면에 표가 없습니다 — 사이트 모양이 다르면 [화면 구조 저장] 을 보내 주세요"
        return report
    report.ok = True
    report.headers = [str(h) for h in table.get("headers") or []]
    report.rows = [[str(c) for c in r] for r in table.get("rows") or []]
    report.empty_note = str(table.get("note") or "")
    if LOADING.search(report.empty_note):
        report.ok, report.note = False, f"표가 '{report.empty_note}' 에서 넘어가지 않았습니다 — 잠시 뒤 다시 [불러오기]"
        return report
    report.pager = str(table.get("pager") or "")
    report.total = str(table.get("total") or "")
    report.read_at = dt.datetime.now().strftime("%H:%M")
    # 줄에는 차량번호가 있어 기록에는 머리글 · 줄 수만
    log(f"주차 할인 내역 열: {' | '.join(report.headers) or '(머리글 없음)'} · {len(report.rows)}줄"
        + (f" · {report.total}" if report.total else "") + (" · 쪽 넘기기 있음" if report.pager else ""))
    return report
