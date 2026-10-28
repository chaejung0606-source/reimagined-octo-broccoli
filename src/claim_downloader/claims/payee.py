"""입금처조회 팝업 · 별도 창 팝업의 도움 — 장학금 · 혁신인재지원금의 소득자 팝업(person.py) · 국적조회(nation.py) · 파일등록(attach.py) ·
카드청구 회의록등록(card_erp.py)이 같이 쓴다.

실측(CLAUDE.md 14절 '입금처조회 팝업', 2026-10-13): 팝업은 iframe 이 아니라 **별도 창**이다. 결과 목록은 JGM 그리드 행 `.jgrid-row` ·
머리글 있는 표의 본문 행 둘 다 읽는다(ROWS_JS). 일반청구 탭의 '거래처' 검색 · 자동 선택(search · match · pick)은 일반 종류와 함께
2026-10-28 걷어냈다(담당자 "일반청구에서는 장학금, 혁신인재지원금, 카드만") — 코드는 git 이력에만 있다.

기준 정보를 바꾸는 계좌등록 · 계좌수정 · 거래처등록 · 거래처수정 · 외부인 등록은 FORBIDDEN 에 두고 절대 누르지 않는다(tests/test_safety.py).
Playwright 를 들여오지 않는다 — session.py 가 넘겨준 page·frame 만 쓴다.
"""
from __future__ import annotations

from collections.abc import Callable

OPEN_BUTTON_ID = "btnRcvCd"          # 작성 화면의 입금처(소득자) 돋보기
SEARCH_BUTTON_ID = "btn_search"      # 팝업의 [검색]
DIV_RADIO_NAME = "RCV_DIV_CD"        # 거래처 · 참여인력 · 인적정보
# 절대 누르지 않는다 — 기준 정보(거래처·계좌)를 만들거나 바꾼다.
FORBIDDEN_IDS = ("btnReg", "btnUpd", "rbaseRegg", "rbaseUpt")
FORBIDDEN_TEXTS = ("계좌등록", "계좌수정", "거래처등록", "거래처수정", "외부인 등록")

# id 로 단추 하나를 누른다. 부르는 쪽이 정한 id 로만(tests/test_safety.py 가 파일마다 본다).
CLICK_ID_JS = """(id) => {
  // 같은 id 가 두 탭에 하나씩 있을 수 있다(작성 화면 btnRcvCd, 실측 ①) — 보이는 쪽을 누른다
  const all = Array.from(document.querySelectorAll('[id="' + String(id).replace(/"/g, '\\"') + '"]'));
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const el = all.find(vis) || all[0];
  if (!el) return {ok: false, why: '단추가 없음'};
  if (el.disabled) return {ok: false, why: '비활성'};
  el.click();
  return {ok: true};
}"""

# 결과 목록 읽기 — 보이는 JGM 그리드 행(.jgrid-row), 없으면 머리글(th)이 있는 표의 본문 행. 행 글자와 선택 칸 유무만.
_ROWS_SNIPPET = """
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const txt = e => (e.innerText || e.textContent || '').replace(/\\s+/g, ' ').trim();
  let rows = Array.from(document.querySelectorAll('.jgrid-row')).filter(vis);
  let kind = 'grid';
  if (!rows.length) {
    kind = 'table';
    for (const t of Array.from(document.querySelectorAll('table')).filter(t => vis(t) && t.querySelector('th'))) {
      const body = Array.from(t.querySelectorAll('tr')).filter(tr => vis(tr) && !tr.querySelector('th') && tr.children.length >= 2);
      if (body.length > rows.length) rows = body;
    }
  }
"""
ROWS_JS = "() => {" + _ROWS_SNIPPET + """
  // 열 값 — JGM 셀의 class 가 k_열이름 (실측: 세금계산서 팝업 k_SELR_CORP_NO · k_TOTL_AMT …). title 이 원본 값(콤마 없는 숫자)이다
  const cells = r => {
    const out = {};
    r.querySelectorAll('[class*="k_"]').forEach(c => {
      const key = (c.className.match(/(?:^|\\s)(k_[A-Za-z0-9_]+)/) || [])[1];
      if (key && !(key in out)) out[key] = (c.getAttribute('title') || txt(c)).slice(0, 120);
    });
    return out;
  };
  // r — JGM 행의 줄 번호 속성(실측: 결의서 목록 .jgrid-row[r]). 가상 스크롤로 다시 그려져도 같은 줄을 알아보는 데 쓴다(person._scan)
  return {kind, rows: rows.map((r, i) => ({index: i, r: r.getAttribute('r'), text: txt(r).slice(0, 300),
    titles: Array.from(r.querySelectorAll('[title]')).map(e => e.getAttribute('title') || '').join(' ').slice(0, 300),
    pick: !!r.querySelector('input[type=radio], input[type=checkbox]'), cells: cells(r)}))};
}"""
# 행 하나 고르기 — 행 안의 선택 칸(라디오·체크)을 누르고, 없으면 첫 셀을 누른다(JGM 은 행 클릭으로도 고른다).
PICK_ROW_JS = "(index) => {" + _ROWS_SNIPPET + """
  const row = rows[index];
  if (!row) return {ok: false, why: '행이 없음'};
  const box = row.querySelector('input[type=radio], input[type=checkbox]');
  if (box) {
    box.click();
    if (!box.checked) { box.checked = true; box.dispatchEvent(new Event('change', {bubbles: true})); }
    return {ok: true, how: '선택 칸'};
  }
  (row.querySelector('td, [class*="k_"]') || row).click();
  return {ok: true, how: '행'};
}"""

# 구분 라디오 중 글자가 label(참여인력 · 인적정보)인 것을 켠다(이미 켜져 있으면 그대로). 라디오를 누르면 화면의 처리기가 탭을 바꾼다.
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
  if (best) return {rows: best, kind: 'table'};
  // 머리글(k_열이름 셀)만 있고 행이 없는 JGM 그리드 — 조회 결과 0행 (실측: 세금계산서 팝업은 조회 전엔 그리드 자체가 없다)
  if (document.querySelector('[class*="k_"]')) return {rows: 0, kind: 'grid'};
  // 머리글 칸도 없이 빈 틀만 남은 JGM 그리드 — 담당자 실제(2026-10-21): 소득자 팝업 참여인력 탭에서 명단에 없는 학생을 찾자
  // '결과 수 모름' 이 됐다. 그리드 틀(.jgrid-viewport)이 보이면 0행으로 센다
  if (Array.from(document.querySelectorAll('.jgrid-viewport')).some(vis)) return {rows: 0, kind: 'grid'};
  return {rows: 0, kind: 'unknown'};
}"""


def find_popup(context, probe_js: str):
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


# 팝업이 지금 작성 화면에서 열린 것인지 — 작성 프레임의 창에 표시를 남기고, 팝업의 opener(팝업을 연 창)가 그 표시를 가졌는지 본다.
# 담당자 실제(2026-10-21 10:50): 앞 청구서에서 열린 소득자 팝업이 남은 채 앱이 새 청구서를 띄웠고, 그 팝업을 '그대로 써' [확인] 을 눌렀지만
# 새 청구서에는 아무것도 들어가지 않아 10분 동안 사람을 기다렸다. 팝업은 자기를 연 화면(opener)에만 값을 돌려준다.
OWNER_MARK_JS = "() => window.__cossOwner || (window.__cossOwner = Date.now().toString(36) + Math.random().toString(36).slice(2))"
OPENER_MARK_JS = """() => { try { return (window.opener && !window.opener.closed && window.opener.__cossOwner) || ''; }
  catch (e) { return ''; } }"""


def opened_from(popup, frame) -> bool:
    """이 팝업을 연 창이 지금 작성 프레임(지금 떠 있는 그 문서)인지. 알 수 없으면 False — 다시 열면 되고, 남의 화면에 값을 넣지 않는 쪽이 안전하다.
    앱이 연 팝업은 열 때의 표시(remember_owner)로 본다 — 같은 iframe 에 새 청구서가 다시 뜨면 opener 는 같은 자리를 가리켜 구분이 안 된다
    (새 문서의 창에는 표시가 새로 붙으므로 열 때의 표시와 다르다). 사람이 연 팝업은 opener 의 표시로 본다."""
    try:
        mark = frame.evaluate(OWNER_MARK_JS)
        owner = getattr(popup, "_coss_owner", None)
        if owner is not None:
            return bool(mark) and owner == mark
        return bool(mark) and popup.evaluate(OPENER_MARK_JS) == mark
    except Exception:  # noqa: BLE001 — 닫히는 중 · 가짜 창
        return False


def owner_mark(frame) -> str:
    """팝업을 열기 전에 — 작성 프레임의 표시(없으면 붙인다)."""
    try:
        return str(frame.evaluate(OWNER_MARK_JS) or "")
    except Exception:  # noqa: BLE001
        return ""


def remember_owner(popup, mark: str) -> None:
    try:
        popup._coss_owner = mark                  # Playwright 창 객체에 붙여 둔다 — 같은 창이면 다음에 다시 쓸 때 본다
    except Exception:  # noqa: BLE001
        pass


def close_stale(popup, log: Callable[[str], None], what: str = "팝업") -> None:
    """앞 화면에서 열린 채 남은 팝업을 닫는다 — 창을 닫을 뿐 ERP 단추는 누르지 않는다."""
    log(f"앞 화면에서 열린 {what}이 남아 있어 닫고 새로 엽니다")
    try:
        popup.close()
    except Exception:  # noqa: BLE001 — 이미 닫힘
        pass


def open_popup(page, frame, button_id: str, probe_js: str, log: Callable[[str], None]):
    """작성 프레임의 단추(button_id)를 눌러 팝업을 연다. 이 화면에서 연 팝업이 이미 열려 있으면 그것을 쓴다. (팝업, 못 연 이유)."""
    popup = find_popup(page.context, probe_js)
    if popup is not None and opened_from(popup, frame):
        log("팝업이 이미 열려 있어 그대로 씁니다")
        return popup, ""
    if popup is not None:
        close_stale(popup, log)
    mark = owner_mark(frame)
    try:
        with page.expect_popup(timeout=8000) as info:
            result = frame.evaluate(CLICK_ID_JS, button_id)
            if not result.get("ok"):
                raise RuntimeError("단추를 누르지 못했습니다: " + str(result.get("why", "")))
        remember_owner(info.value, mark)
        return info.value, ""
    except Exception as error:  # noqa: BLE001 — 팝업이 안 뜨면 사람이 연다
        return None, (str(error).splitlines()[0][:120] if str(error) else "팝업이 열리지 않았습니다")


def _frames(popup) -> list:
    """팝업 창의 프레임들 — 첫째가 창 자체. 입금처 팝업에는 빈 iframe 이 하나 더 있어(실측 2026-10-13) 결과가 거기 뜰 수도 있다."""
    try:
        frames = list(popup.frames)
    except Exception:  # noqa: BLE001 — 가짜 객체나 닫힌 창
        frames = []
    main = getattr(popup, "main_frame", None)       # Playwright 의 page.frames[0] 는 창 자체(main_frame)와 같은 문서
    return [popup] + [f for f in frames if f is not popup and f is not main]


def count_rows(popup) -> tuple[int | None, object]:
    """결과 행 수와 그 행이 있는 프레임. 어느 프레임에도 목록이 없으면 (None, 창)."""
    best, where = None, popup
    for fr in _frames(popup):
        try:
            counted = fr.evaluate(RESULT_COUNT_JS)
        except Exception:  # noqa: BLE001 — 아직 로딩 중인 프레임
            continue
        if counted.get("kind") == "unknown":
            continue
        rows = int(counted.get("rows") or 0)
        if best is None or rows > best:
            best, where = rows, fr
    return best, where


def wait_rows(popup, wait: Callable[[float], None], seconds: float = 6.0) -> tuple[int | None, object]:
    """[검색]/[조회] 뒤 결과가 올 때까지(행이 하나라도 보일 때까지) 기다린다. 끝까지 안 오면 그때의 수(0 또는 None)."""
    found: dict = {}

    def check() -> bool:
        found["rows"], found["frame"] = count_rows(popup)
        return bool(found["rows"])

    wait_until(check, wait, tries=max(1, int(seconds / 0.5)), step=0.5)
    return found.get("rows"), found.get("frame", popup)


def wait_closed(popup, wait: Callable[[float], None], seconds: float = 180.0) -> bool:
    """사람이 팝업에서 고르고 [확인] 을 눌러 창이 닫힐 때까지 기다린다. 시간이 다 되면 False."""
    return wait_until(lambda: popup.is_closed(), wait, tries=max(1, int(seconds / 0.5)), step=0.5)
