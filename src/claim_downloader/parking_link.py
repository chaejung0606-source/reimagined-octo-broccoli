"""주차등록 2단계 — 앱 칸에 넣은 값으로 주차 사이트의 할인 링크를 만든다(담당자 요청 2026-10-21: "어플에서 등록 누르면 사이트에도 눌리는걸로").

실측(2026-10-21 15:06, 담당자가 '할인 링크' 화면에서 [새 링크] 를 눌러 둔 채 [화면 구조 저장]) — CLAUDE.md 20절:
- 화면 `/discount-links`. 단추에 id 가 없다 — [새 링크] 는 글자 'add새 링크'(앞의 add 는 그림 글자) · `btn btn-primary btn-sm`.
- [새 링크] 창(같은 화면 안): 글 칸 하나(`form-control`) · 고르기 둘(주차장 '강원대학교 춘천캠퍼스' 하나뿐 · 할인권 상품 '교환공무확인증4시간 (잔량 85)') ·
  날짜시각 칸 둘(`datetime-local`) · 체크 `#dl-show-restart`(완료 화면에 '처음으로' 버튼 표시, 꺼짐) · `#dl-active`(활성, 켜짐) · '취소' · **'저장'(submit)**.
  칸 이름(label)은 실측에 잡히지 않았다 — 목록 머리글(링크 명 | 주차장 | 할인권 상품 | 할인 템플릿 | 유효기간 | 활성)과 같은 차례로 보고, label 글자가
  보이면 그것을 먼저 쓴다(기록에 남겨 다음 실측 없이 확인한다).

누르는 것은 [새 링크](창을 여는 것)와 그 창의 [저장] 둘뿐이다 — '삭제' · '수정' · '취소' · 'QR 보기' · 로그아웃 · 비밀번호 변경은 누르지 않는다(tests/test_safety.py).
같은 이름의 링크가 목록에 있으면 넣지 않는다(두 번 누름 막기). Playwright 를 들여오지 않는다 — 창(page)은 session.py 가 넘겨준다.
"""
from __future__ import annotations

import datetime as dt
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from . import parking

LINKS_PATH = "/discount-links"

_VIS = "const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };"
_SQUASH = "const squash = s => String(s || '').replace(/\\s+/g, '');"

# 할인 링크 목록 — 줄마다 칸 글자(첫 칸이 링크 명)
ROWS_JS = """() => Array.from(document.querySelectorAll('table tbody tr')).map(tr =>
  Array.from(tr.cells).map(td => (td.innerText || td.textContent || '').replace(/\\s+/g, ' ').trim()))
  .filter(cells => cells.length > 1)"""

# [새 링크] — 보이는 단추 중 글자(그림 글자 'add' 를 뺀)가 '새 링크' 인 것이 하나일 때만
_OPEN_CANDS = ("Array.from(document.querySelectorAll('button, a')).filter(b => vis(b)"
               " && squash(b.innerText || b.textContent).replace(/^add/, '') === '새링크')")
OPEN_COUNT_JS = "() => { %s %s return %s.length; }" % (_VIS, _SQUASH, _OPEN_CANDS)
OPEN_JS = """() => {
  %s %s
  const cands = %s;
  if (cands.length !== 1) return {ok: false, why: cands.length ? "'새 링크' 단추가 여럿" : "'새 링크' 단추가 없음"};
  cands[0].click();
  return {ok: true};
}""" % (_VIS, _SQUASH, _OPEN_CANDS)

# [새 링크] 창의 칸에 표시를 붙이고(값은 Playwright fill · select_option 으로 넣는다 — 화면 처리기가 돈다) 모양을 돌려준다
MARK_FORM_JS = """() => {
  %s %s
  const active = document.getElementById('dl-active');
  if (!active || !vis(active)) return {open: false};
  const scope = active.closest('form') || active.closest('.modal') || document;
  const labelOf = e => {
    if (e.id) { const l = scope.querySelector('label[for="' + e.id + '"]'); if (l) return squash(l.innerText); }
    let p = e.parentElement;
    for (let i = 0; i < 3 && p && p !== scope.parentElement; i++, p = p.parentElement) {
      const ls = Array.from(p.querySelectorAll('label, .form-label')).filter(l => !l.contains(e)
        && !l.querySelector('input,select') && (l.compareDocumentPosition(e) & Node.DOCUMENT_POSITION_FOLLOWING));
      if (ls.length) return squash(ls[ls.length - 1].innerText);
    }
    return '';
  };
  const texts = Array.from(scope.querySelectorAll('input')).filter(e => vis(e)
    && /^(text|)$/.test((e.getAttribute('type') || '').toLowerCase()));
  const selects = Array.from(scope.querySelectorAll('select')).filter(vis);
  const dates = Array.from(scope.querySelectorAll('input[type="datetime-local"]')).filter(vis);
  const restart = document.getElementById('dl-show-restart');
  const saves = Array.from(scope.querySelectorAll('button')).filter(b => vis(b) && squash(b.innerText) === '저장');
  const pick = (list, words, fallback) => list.find(e => words.test(labelOf(e))) || fallback;
  const name = pick(texts, /링크|이름|명/, texts[0]);
  const lot = pick(selects, /주차장/, selects[0]);
  const product = pick(selects, /상품|할인권/, selects.find(s => s !== lot));
  const why = !name ? '글 칸이 없음' : !lot || !product || lot === product ? '고르기 칸이 둘이 아님'
    : dates.length !== 2 ? '날짜시각 칸이 둘이 아님(' + dates.length + ')' : saves.length !== 1 ? "'저장' 단추가 " + (saves.length ? '여럿' : '없음') : '';
  document.querySelectorAll('[data-coss-link]').forEach(e => e.removeAttribute('data-coss-link'));
  if (why) return {open: true, ok: false, why};
  name.setAttribute('data-coss-link', 'name');
  lot.setAttribute('data-coss-link', 'lot');
  product.setAttribute('data-coss-link', 'product');
  dates[0].setAttribute('data-coss-link', 'start');
  dates[1].setAttribute('data-coss-link', 'end');
  active.setAttribute('data-coss-link', 'active');
  if (restart) restart.setAttribute('data-coss-link', 'restart');
  saves[0].setAttribute('data-coss-link', 'save');
  const options = s => Array.from(s.options).map(o => (o.text || '').trim());
  return {open: true, ok: true,
    labels: {name: labelOf(name), lot: labelOf(lot), product: labelOf(product), start: labelOf(dates[0]), end: labelOf(dates[1])},
    lots: options(lot), lot_index: lot.selectedIndex, products: options(product), product_index: product.selectedIndex,
    restart: !!restart};
}""" % (_VIS, _SQUASH)

NAME_SELECTOR = "[data-coss-link=name]"
LOT_SELECTOR = "[data-coss-link=lot]"
PRODUCT_SELECTOR = "[data-coss-link=product]"
START_SELECTOR = "[data-coss-link=start]"
END_SELECTOR = "[data-coss-link=end]"
ACTIVE_SELECTOR = "[data-coss-link=active]"
RESTART_SELECTOR = "[data-coss-link=restart]"
SAVE_SELECTOR = "[data-coss-link=save]"

# 넣은 값을 다시 읽는다 — 화면이 값을 받았는지([저장] 전에)
READ_FORM_JS = """() => {
  const q = k => document.querySelector('[data-coss-link=' + k + ']');
  const sel = s => s && s.selectedIndex >= 0 ? (s.options[s.selectedIndex].text || '').trim() : '';
  return {name: (q('name') || {}).value || '', lot: sel(q('lot')), product: sel(q('product')),
    start: (q('start') || {}).value || '', end: (q('end') || {}).value || '',
    active: !!(q('active') || {}).checked, restart: q('restart') ? !!q('restart').checked : null};
}"""

# [저장] 뒤 창이 그대로면 화면에 뜬 검사 글(빨간 글 · 알림 상자)을 모은다
FEEDBACK_JS = """() => {
  %s
  return Array.from(document.querySelectorAll('.invalid-feedback, .alert, .toast-body, [role=alert]')).filter(vis)
    .map(e => (e.innerText || '').replace(/\\s+/g, ' ').trim()).filter(Boolean).slice(0, 5);
}""" % _VIS

FORM_OPEN_JS = """() => { const a = document.getElementById('dl-active'); if (!a) return false;
  const r = a.getBoundingClientRect(); return r.width > 0 && r.height > 0; }"""

# [새 링크] 창의 할인권 상품 보기 — '교환공무확인증4시간 (잔량 85)'(실측 ②). 보유 잔량을 읽으려고 보기만 읽는다(read_products)
PRODUCTS_JS = """() => {
  %s
  const a = document.getElementById('dl-active');
  if (!a || !vis(a)) return null;
  const scope = a.closest('form') || a.closest('.modal') || document;
  const lists = Array.from(scope.querySelectorAll('select')).filter(vis).map(s => Array.from(s.options).map(o => (o.text || '').trim()));
  return lists.find(texts => texts.some(t => /잔량/.test(t))) || [];
}""" % _VIS

_QUOTA = re.compile(r"\s*\(\s*잔량[^)]*\)\s*$")
CHOOSE = "선택"


def product_name(label: str) -> str:
    """'교환공무확인증4시간 (잔량 85)' → '교환공무확인증4시간' — 남은 수는 날마다 바뀌어 이름으로 맞출 때 뗀다."""
    return _QUOTA.sub("", str(label or "")).strip()


def choose(options: list[str], wanted: str = "") -> tuple[int | None, str]:
    """고를 보기의 차례 · 못 고른 까닭. wanted 가 있으면 이름(남은 수 뺀)이 같은 보기, 없으면 '선택' 밖의 보기가 하나일 때만."""
    real = [(i, o) for i, o in enumerate(options) if o and product_name(o) != CHOOSE]
    if wanted:
        hits = [i for i, o in real if re.sub(r"\s+", "", product_name(o)) == re.sub(r"\s+", "", product_name(wanted))]
        if len(hits) == 1:
            return hits[0], ""
        return None, f"'{product_name(wanted)}' 보기가 " + ("여럿" if hits else "없음")
    if len(real) == 1:
        return real[0][0], ""
    return None, "보기가 " + ("여럿이라 골라야 함" if real else "없음")


def local_value(value: dt.datetime) -> str:
    """datetime-local 칸의 값 꼴 — 'YYYY-MM-DDTHH:MM'."""
    return value.strftime("%Y-%m-%dT%H:%M")


@dataclass
class LinkRequest:
    name: str
    start: dt.datetime
    end: dt.datetime
    product: str = ""            # 비우면 사이트에 상품이 하나뿐일 때 그것
    lot: str = ""                # 비우면 이미 골라져 있거나 하나뿐인 주차장
    active: bool = True
    show_restart: bool = False

    def problems(self) -> list[str]:
        out = []
        if not self.name.strip():
            out.append("링크 이름을 넣어 주세요")
        if self.end <= self.start:
            out.append("유효기간 끝이 시작보다 뒤여야 합니다")
        return out


@dataclass
class LinkReport:
    ok: bool = False
    note: str = ""
    steps: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)   # 사이트 알림
    products: list[str] = field(default_factory=list)   # 사이트의 할인권 상품 보기(남은 수 포함) — 화면의 고르기 칸을 채운다
    row: list[str] = field(default_factory=list)        # 만들어진 줄(목록의 칸 글자)

    def lines(self) -> list[str]:
        head = ("✓ 할인 링크를 만들었습니다" if self.ok else "✗ 할인 링크를 만들지 못했습니다") + (f" — {self.note}" if self.note else "")
        out = [head] + ["  · " + s for s in self.steps]
        if self.row:
            out.append("  목록: " + " | ".join(self.row[:6]))
        out += ["  사이트 알림: " + m for m in self.messages]
        return out


def _evaluate(frame, js):
    try:
        return frame.evaluate(js)
    except Exception:  # noqa: BLE001 — 바뀌는 중인 화면
        return None


@dataclass
class ProductsReport:
    ok: bool = False
    products: list[str] = field(default_factory=list)   # 할인권 상품 보기(남은 수 포함)
    note: str = ""


def read_products(page, log: Callable[[str], None], wait: Callable[[float], None], base_url: str = "") -> ProductsReport:
    """사이트 보유 잔량 — [새 링크] 창을 열어 할인권 상품 보기만 읽고, 저장하지 않고 화면을 다시 연다(창은 버려진다 — '취소' 도 누르지 않는다).
    담당자 2026-10-22 "보유할인권을 보면 현재 잔여 개수가 있습니다" — 그 수는 실측된 이 보기에 '(잔량 N)' 으로 보인다."""
    report = ProductsReport()
    frame = page.main_frame
    if base_url:
        page.goto(base_url.rstrip("/") + LINKS_PATH, wait_until="domcontentloaded")
    for _ in range(20):
        if (_evaluate(frame, OPEN_COUNT_JS) or 0) > 0:
            break
        if (_evaluate(frame, parking.LOGIN_FORM_JS) or 0) > 0:
            report.note = "주차 사이트에 로그인돼 있지 않습니다"
            return report
        wait(0.5)
    products = _evaluate(frame, PRODUCTS_JS)
    if products is None:
        opened = _evaluate(frame, OPEN_JS) or {}
        if not opened.get("ok"):
            report.note = "보유 잔량을 읽지 못했습니다(" + (opened.get("why") or "[새 링크] 를 누르지 못함") + ")"
            return report
        for _ in range(10):
            wait(0.5)
            products = _evaluate(frame, PRODUCTS_JS)
            if products is not None:
                break
    if base_url:                                  # 창을 저장하지 않고 버린다 — 화면을 다시 연다
        page.goto(base_url.rstrip("/") + LINKS_PATH, wait_until="domcontentloaded")
    report.products = [o for o in products or [] if o and product_name(o) != CHOOSE]
    report.ok = bool(report.products)
    if not report.ok:
        report.note = "할인권 상품 보기를 읽지 못했습니다"
    log("주차 보유 잔량: " + (" · ".join(report.products) or report.note))
    return report


def _names(rows) -> list[str]:
    return [r[0] for r in rows or [] if r]


def create(page, request: LinkRequest, log: Callable[[str], None], wait: Callable[[float], None],
           base_url: str = "", save_timeout: float = 10.0) -> LinkReport:
    """[새 링크] 창을 열고 칸을 채운 뒤 [저장] 까지. 됐는지는 창이 닫히고 목록에 그 이름의 줄이 생겼는지로 본다."""
    report = LinkReport()
    problems = request.problems()
    if problems:
        report.note = " · ".join(problems)
        return report
    frame = page.main_frame
    if base_url:
        # 늘 새로 연다 — 떠 있던 목록은 오래됐을 수 있고(같은 이름 확인), 사이트 접속이 끝났으면 여기서 로그인 화면으로 바뀐다
        page.goto(base_url.rstrip("/") + LINKS_PATH, wait_until="domcontentloaded")
        report.steps.append("할인 링크 화면을 새로 엶")
    for _ in range(20):                                          # 목록이 그려질 때까지
        if _evaluate(frame, ROWS_JS) is not None and (_evaluate(frame, OPEN_COUNT_JS) or 0) > 0:
            break
        if (_evaluate(frame, parking.LOGIN_FORM_JS) or 0) > 0:                 # 로그인 화면으로 돌아감
            report.note = "주차 사이트에 로그인돼 있지 않습니다 — 설정에서 로그인 정보를 넣거나 브라우저에서 로그인한 뒤 다시 [등록]"
            return report
        wait(0.5)
    rows = _evaluate(frame, ROWS_JS) or []
    before = _names(rows)
    if request.name.strip() in before:
        report.note = f"같은 이름의 링크 '{request.name.strip()}' 가 이미 있어 넣지 않았습니다 — 이름을 바꾸세요"
        return report

    shape = _evaluate(frame, MARK_FORM_JS) or {}
    if not shape.get("open"):
        opened = _evaluate(frame, OPEN_JS) or {}
        if not opened.get("ok"):
            report.note = opened.get("why") or "[새 링크] 를 누르지 못했습니다"
            return report
        report.steps.append("[새 링크] 누름")
        for _ in range(10):
            wait(0.5)
            shape = _evaluate(frame, MARK_FORM_JS) or {}
            if shape.get("open"):
                break
    if not shape.get("open"):
        report.note = "[새 링크] 창이 뜨지 않았습니다"
        return report
    if not shape.get("ok"):
        report.note = f"[새 링크] 창 모양이 실측과 다릅니다({shape.get('why')}) — 브라우저에서 직접 넣어 주세요"
        return report
    report.products = [o for o in shape.get("products") or [] if product_name(o) != CHOOSE]
    log("주차 [새 링크] 창 칸 이름: " + " · ".join(f"{k}={v or '?'}" for k, v in (shape.get("labels") or {}).items()))

    lots = shape.get("lots") or []
    lot_now = shape.get("lot_index", -1)
    if request.lot:
        lot_index, why = choose(lots, request.lot)
    elif 0 <= lot_now < len(lots) and product_name(lots[lot_now]) != CHOOSE:
        lot_index, why = lot_now, ""
    else:
        lot_index, why = choose(lots)
    if lot_index is None:
        report.note = "주차장 " + why
        return report
    product_index, why = choose(shape.get("products") or [], request.product)
    if product_index is None:
        report.note = "할인권 상품 " + why + (" — 앱의 '할인권 상품' 에서 고르세요" if report.products else "")
        return report

    frame.fill(NAME_SELECTOR, request.name.strip())
    frame.select_option(LOT_SELECTOR, index=lot_index)
    frame.select_option(PRODUCT_SELECTOR, index=product_index)
    frame.fill(START_SELECTOR, local_value(request.start))
    frame.fill(END_SELECTOR, local_value(request.end))
    frame.set_checked(ACTIVE_SELECTOR, request.active)
    if shape.get("restart"):
        frame.set_checked(RESTART_SELECTOR, request.show_restart)
    got = _evaluate(frame, READ_FORM_JS) or {}
    wanted = {"name": request.name.strip(), "lot": lots[lot_index], "product": shape["products"][product_index],
              "start": local_value(request.start), "end": local_value(request.end), "active": request.active}
    wrong = [k for k, v in wanted.items() if got.get(k) != v]
    if wrong:
        report.note = "넣은 값이 칸에 남지 않았습니다(" + ", ".join(wrong) + ") — [저장] 은 누르지 않았습니다. 브라우저에서 확인해 주세요"
        return report
    report.steps.append(f"넣음: {wanted['name']} · {wanted['lot']} · {product_name(wanted['product'])} · "
                        f"{wanted['start'].replace('T', ' ')} ~ {wanted['end'].replace('T', ' ')} · {'활성' if request.active else '비활성'}")

    def on_dialog(dialog) -> None:          # [저장] 의 확인 · 알림 — 담당자가 [등록] 을 눌렀으니 [확인]
        try:
            report.messages.append((dialog.message or "").strip()[:200])
            dialog.accept()
        except Exception:  # noqa: BLE001
            pass

    page.on("dialog", on_dialog)
    try:
        frame.click(SAVE_SELECTOR)
        report.steps.append("[저장] 누름")
        deadline = time.monotonic() + save_timeout
        while time.monotonic() < deadline:
            wait(0.5)
            if _evaluate(frame, FORM_OPEN_JS):
                continue
            rows = _evaluate(frame, ROWS_JS) or []
            mine = [r for r in rows if r and r[0] == request.name.strip()]
            if mine:
                report.ok, report.row = True, mine[0]
                return report
    finally:
        try:
            page.remove_listener("dialog", on_dialog)
        except Exception:  # noqa: BLE001
            pass
    shown = _evaluate(frame, FEEDBACK_JS) or []
    report.note = ("[저장] 뒤에도 창이 그대로입니다" if _evaluate(frame, FORM_OPEN_JS) else "[저장] 뒤 목록에서 새 링크를 찾지 못했습니다") \
        + (": " + " / ".join(shown) if shown else "") + " — 브라우저 화면을 확인해 주세요"
    return report
