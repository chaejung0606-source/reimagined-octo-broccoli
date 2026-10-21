"""입금처조회 팝업 — 돋보기(#btnRcvCd)를 눌러 팝업을 열고 거래처를 검색한 뒤, 결과가 하나로 확실하면 골라 [확인]까지.

실측(CLAUDE.md 14절 '입금처조회 팝업', 2026-10-13): 팝업은 iframe 이 아니라 **별도 창**(rexpe_0084_rcv_pop.act)이다.
검색 조건 칸(구분 라디오 · 거래처명 칸 · [검색])은 실측됐고 결과 목록의 생김새는 아직 미실측이라, 목록은 일반적인
모양 둘(JGM 그리드 행 `.jgrid-row` · 머리글 있는 표의 본문 행)을 다 읽는다(ROWS_JS). 담당자 결정(2026-10-13):
**확실한 것은 앱이 고르고, 애매하거나 정보가 모자라면 사람이 고른다** — 사업자번호가 같은 행이 하나, 또는 상호를 담은
행이 하나일 때만 고른다(`match`). 고른 뒤 [확인] 을 누르고 작성 화면의 입금처(RCV_NM)가 채워졌는지 확인한다 —
안 채워졌으면 사람에게 넘긴다. 설정 `claim_auto_pick` 으로 끌 수 있다.

누르는 것은 돋보기(btnRcvCd) · 구분 라디오('거래처') · [검색](btn_search) · 고른 행의 선택 칸(또는 행) · [확인](btn_s_confirm1)
뿐이다. 기준 정보를 바꾸는 계좌등록 · 계좌수정 · 거래처등록 · 거래처수정 · 외부인 등록은 FORBIDDEN 에 두고 절대 누르지
않는다(tests/test_safety.py 가 본다). Playwright 를 들여오지 않는다 — session.py 가 넘겨준 page·frame 만 쓴다.
"""
from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .form import SET_TEXT_JS, read_state

OPEN_BUTTON_ID = "btnRcvCd"          # 작성 화면의 입금처 돋보기
SEARCH_BUTTON_ID = "btn_search"      # 팝업의 [검색]
SEARCH_TEXT_ID = "SEARCH_GB_NM1"     # 거래처명 · 사업자번호 · 대표자명
DIV_RADIO_NAME = "RCV_DIV_CD"        # 거래처 · 참여인력 · 인적정보
DIV_LABEL = "거래처"
CONFIRM_BUTTON_ID = "btn_s_confirm1"  # '거래처' 탭의 [확인] — 고른 행을 작성 화면으로 넘긴다
# 절대 누르지 않는다 — 기준 정보(거래처·계좌)를 만들거나 바꾼다.
FORBIDDEN_IDS = ("btnReg", "btnUpd", "rbaseRegg", "rbaseUpt")
FORBIDDEN_TEXTS = ("계좌등록", "계좌수정", "거래처등록", "거래처수정", "외부인 등록")

# 팝업 알아보기 — 입금처조회 팝업에만 있는 조합
POPUP_PROBE_JS = """() => !!(document.querySelector('input[name=RCV_DIV_CD]') && document.querySelector('#SEARCH_GB_NM1')
  && document.querySelector('#btn_s_confirm1'))"""

# id 로 단추 하나를 누른다. 허용 목록(ALLOWED_CLICK_IDS)의 id 로만 부른다.
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
ALLOWED_CLICK_IDS = frozenset({OPEN_BUTTON_ID, SEARCH_BUTTON_ID, CONFIRM_BUTTON_ID})

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
  if (best) return {rows: best, kind: 'table'};
  // 머리글(k_열이름 셀)만 있고 행이 없는 JGM 그리드 — 조회 결과 0행 (실측: 세금계산서 팝업은 조회 전엔 그리드 자체가 없다)
  if (document.querySelector('[class*="k_"]')) return {rows: 0, kind: 'grid'};
  // 머리글 칸도 없이 빈 틀만 남은 JGM 그리드 — 담당자 실제(2026-10-21): 소득자 팝업 참여인력 탭에서 명단에 없는 학생을 찾자
  // '결과 수 모름' 이 됐다. 그리드 틀(.jgrid-viewport)이 보이면 0행으로 센다
  if (Array.from(document.querySelectorAll('.jgrid-viewport')).some(vis)) return {rows: 0, kind: 'grid'};
  return {rows: 0, kind: 'unknown'};
}"""


@dataclass
class PayeeReport:
    ok: bool
    query: str = ""
    rows: int | None = None            # 검색 결과 행 수 (못 세면 None)
    messages: list[str] = field(default_factory=list)   # 팝업이 띄운 알림
    note: str = ""
    picked: bool = False               # 앱이 골라 [확인] 까지 누르고 작성 화면에 들어간 것을 확인함
    pick_note: str = ""                # 고른 근거, 또는 사람에게 넘긴 이유
    chosen: str = ""                   # 작성 화면에 들어간 입금처 이름

    def lines(self) -> list[str]:
        if self.ok and self.picked:
            out = [f"✓ 입금처: '{self.chosen or self.query}' 를 골라 [확인] 까지 눌렀습니다 ({self.pick_note})"]
        elif self.ok:
            found = f"결과 {self.rows}행" if self.rows is not None else "결과 수는 세지 못함"
            why = f" — {self.pick_note}" if self.pick_note else ""
            out = [f"✓ 입금처 팝업: '{self.query}' 로 검색함 — {found}{why}. 목록에서 거래처를 고르고 [확인] 을 눌러 주세요"]
        else:
            out = [f"✗ 입금처 팝업: {self.note or '열지 못함'} — 돋보기를 직접 눌러 골라 주세요"]
        out.extend("· 팝업 알림: " + m for m in self.messages)
        return out


def normalize(text: str) -> str:
    """상호 비교용 — 공백·기호·법인 표기를 걷어낸다. '코웨이(주)' == '㈜코웨이' == '코웨이 주식회사'."""
    text = re.sub(r"주식회사|\(주\)|㈜|\(유\)|\(사\)|\(재\)", "", str(text or ""))
    return re.sub(r"[\s·ㆍ・.,\-()\[\]{}_/\\'\"]", "", text).lower()


def digits(text: str) -> str:
    return re.sub(r"\D", "", str(text or ""))


def match(rows: list[dict], data: dict) -> tuple[int | None, str]:
    """결과 행 중 하나를 확실히 고를 수 있으면 (index, 근거), 아니면 (None, 사람에게 넘기는 이유).

    ① 사업자번호(10자리)가 어느 한 토큰과 같은 행이 하나 → 그 행. ② 아니면 상호(정규화)를 담은 행이 하나 → 그 행.
    0행·여러 행·상호가 2자 미만이면 고르지 않는다.
    """
    if not rows:
        return None, "검색 결과가 없음"

    def tokens(row: dict) -> list[str]:
        cells = [str(v) for v in (row.get("cells") or {}).values()]
        return cells + str(row.get("text", "")).split() + str(row.get("titles", "")).split()

    biz = digits(data.get("payeeBizNo"))
    if len(biz) == 10:
        hits = [r for r in rows if any(digits(tok) == biz for tok in tokens(r))]
        if len(hits) == 1:
            return int(hits[0]["index"]), "사업자번호 일치"
        if len(hits) > 1:
            return None, f"사업자번호가 같은 행이 {len(hits)}개"
        # 목록에 사업자번호가 보이는데 서류의 번호인 행이 없다 — 이름이 같아도 다른 거래처다. 이름으로 고르지 않는다(2026-10-14 점검)
        if any(len(digits(tok)) == 10 for r in rows for tok in tokens(r)):
            return None, f"{len(rows)}행 중 사업자번호 {data.get('payeeBizNo')} 인 행이 없음"
    name = normalize(data.get("payeeName"))
    if len(name) < 2:
        return None, "상호가 너무 짧아 고르지 않음"
    # 상호는 정확히 같은 칸만 — '한빛' 이 '한빛소프트' 를 고르던 것을 막는다
    hits = [r for r in rows if any(normalize(tok) == name for tok in tokens(r))]
    if len(hits) == 1:
        return int(hits[0]["index"]), "상호 일치"
    if not hits:
        near = [r for r in rows if name in normalize(str(r.get("text", "")) + " " + str(r.get("titles", "")))]
        if near:
            return None, f"상호 '{data.get('payeeName')}' 를 담은 행이 {len(near)}개 있지만 이름이 똑같지 않아 고르지 않음"
        return None, f"{len(rows)}행 중 상호 '{data.get('payeeName')}' 를 담은 행이 없음"
    return None, f"상호가 같은 행이 {len(hits)}개 — 어느 것인지 애매함"


def pick(popup, frame, data: dict, log: Callable[[str], None], wait: Callable[[float], None] = time.sleep) -> tuple[bool, str, str]:
    """검색 결과에서 확실한 행을 골라 [확인] 을 누르고 작성 화면의 입금처가 채워졌는지 본다. (골랐나, 근거/이유, 들어간 이름)."""
    _, where = count_rows(popup)
    try:
        listing = where.evaluate(ROWS_JS)
    except Exception as error:  # noqa: BLE001
        return False, "결과 목록을 읽지 못함: " + (str(error).splitlines()[0][:80] if str(error) else ""), ""
    index, why = match(list(listing.get("rows") or []), data)
    if index is None:
        log("입금처 자동 선택 안 함: " + why)
        return False, why, ""
    before = (read_state(frame, ["RCV_NM"]).get("RCV_NM") or {}).get("value", "")
    chosen = where.evaluate(PICK_ROW_JS, index)
    if not chosen.get("ok"):
        return False, "행을 고르지 못함: " + str(chosen.get("why", "")), ""
    wait(0.3)
    confirmed = popup.evaluate(CLICK_ID_JS, CONFIRM_BUTTON_ID)
    if not confirmed.get("ok"):
        return False, "[확인] 을 누르지 못함: " + str(confirmed.get("why", "")), ""
    wait_closed(popup, wait, seconds=10)
    after = (read_state(frame, ["RCV_NM"]).get("RCV_NM") or {}).get("value", "")
    if after and after != before:
        log("입금처 자동 선택: %s (%s)" % (after, why))
        return True, why, after
    return False, "[확인] 을 눌렀지만 작성 화면의 입금처가 채워지지 않음 — 직접 골라 주세요", ""


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


def search(page, frame, data: dict, log: Callable[[str], None],
           wait: Callable[[float], None] = time.sleep, messages: list[str] | None = None,
           auto_pick: bool = True) -> PayeeReport:
    """돋보기를 눌러 팝업을 열고(이미 열려 있으면 그것을 씀) '거래처' 구분으로 검색어를 넣어 [검색] 을 누른다.
    auto_pick 이면 결과가 하나로 확실할 때 골라 [확인] 까지 누른다(pick).

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
        report.rows, _ = wait_rows(popup, wait)     # 결과가 서버에서 온다 — 행이 보일 때까지(최대 6초)
        report.ok = True
        log("입금처 검색: '%s' → %s" % (query, f"{report.rows}행" if report.rows is not None else "결과 수 모름"))
        if auto_pick:
            report.picked, report.pick_note, report.chosen = pick(popup, frame, data, log, wait)
        return report
    finally:
        try:
            popup.remove_listener("dialog", on_dialog)
        except Exception:  # noqa: BLE001 — 창이 이미 닫힘
            pass
