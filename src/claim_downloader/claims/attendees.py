"""회의록등록 창(카드 (17) 회의비)의 참여인력 · 내부참석자 — 회의록의 사람을 ERP 의 두 사람 찾기 창에서 골라 넣는다.

실측(2026-11-11 14:03 ~ 14:06, 담당자 화면 구조 모음 32 ~ 38번 — 사람 이름 · 사번은 문서에 적지 않는다):

- 참여인력 [행 추가](`#btnRowAdd`) → **참여인력선택** `rcomm_0071_02.act`(별도 창). 그 과제의 참여인력 목록(JGM 그리드, 행마다 체크 —
  여러 명을 고를 수 있음, 숨은 `#CHK_GB`=2): 열 `k_EMP_NO` 사번 · `k_EMP_NM` 성명 · `k_BLNG_DEPT_NM` 소속 · `k_WORK_STS_NM` · `k_PART_TRM_DT` 참여기간 …
  위에 `#EMP_NM` 성명 + `#btn_search`, [확인] `#btnItem`(고른 것이 없으면 "선택된 내역이 없습니다"), 닫기 `self.close()`, 숨은 '선택없음'(누르지 않는다).
  숨은 `#RTN_FUNC`=`uf_rcomm_0071_02Params` · `#START_DATE`=회의일자(그날 참여 중인 사람만 보이는 것으로 보인다).
  [확인] 뒤 회의록등록 창의 참여인력 표에 고른 사람마다 줄(사번 · 성명 읽기전용 · 소속 · 숨은 참여기간)이 생기고 `#IN_COUNT` 가 는다.
- 내부참석자 [행 추가](`#btnRowAdd1`) → **인적정보조회(멀티)** `rcomm_0008_04.act`(별도 창, `#RTN_FUNC`=`uf_rcomm_0008_04Params_multi` · `#RTN_TYPE`=M).
  `#USER_GB` · `#WORK_STS` · `#DGR_CLSS_CD` 거르기 · `#SEARCH_NM` 검색(**성명도 사번 · 학번도** 된다 — 사번으로 찾자 1줄) · `#btn_search`.
  결과는 학교 사람 전체라 같은 이름이 많다(한 이름에 12줄 — 제적 · 졸업한 옛 학생까지). 열 `k_USER_GB_NM` · `k_WORK_STS_NM` 재직상태 · `k_EMP_NO` ·
  `k_EMP_NM` · `k_DEPT_NM` 소속(`학과_입학년` 꼴도) · `k_UP_DEPT_NM` · `k_POS_NM` …. 행의 체크를 켜면 아래 '고른 사람' 표(성명 · 소속, 숨은 `CFRC_IN_EMP_NO`)에
  쌓이고(조금 뒤에), 다시 검색해도 남는다. [확인] 은 id 없는 링크 '확인'. 숨은 '선택없음' · '외부인 등록' 은 누르지 않는다.
  **실제 ERP(2026-11-11 담당자 그림)에서는 체크만으로 '고른 사람' 표가 비어 있었다** — 결과 목록과 그 표 사이 오른쪽에 글자 없는 ⬇(빨강) · ⬆(파랑) 단추가 있다.
  앱은 체크한 뒤 표가 비면 ⬇ 를 사람처럼 누른다(`ARROW_JS` 로 그 사이의 작은 단추를 찾아 '내림' 먼저, 못 가리면 왼쪽부터 둘까지 — '올림' 은 누르지 않음, 구조 저장 전).
  [확인] 뒤 내부참석자 표에 고른 사람마다 줄(사번 읽기전용 · 성명 · 돋보기 · 소속)이 생기고 `#EMP_COUNT` 가 는다.

**참여인력인지는 ERP 의 참여인력선택 목록으로 가린다**(담당자 2026-11-12 회의록등록 그림 — "지금 참여인력을 내부참석자로 입력했습니다": 참여연구원 명단 파일이 없으면
학교 사람은 모두 내부참석자로 갔다). `regroup` 이 넣기 전에 참여인력선택 창을 한 번 열어 그 과제의 참여인력 목록만 읽고 닫은 뒤(`part_rows` — [확인] 없이 창 닫기),
내부참석자 가운데 그 목록에 있는 사람(번호가 있으면 번호 · 이름, 없으면 이름 — 소속이 적혀 있으면 소속도 — 이 맞는 줄 하나)을 참여인력으로 돌려 참여인력선택에서 넣는다.

앱은 **한 사람씩** 창을 열어(검색이 앞 체크를 지울 수 있어서) 검색 → 맞는 줄이 **하나로 확실할 때만** 체크 → [확인] → 회의록등록 창에 그 이름이 생겼는지 본다.
못 정하면 그 창을 닫고(창 닫기 — ERP 단추가 아니다) 까닭을 돌려준다 — card_erp 가 '신청 전 확인할 것' 에 그 이름을 남긴다.
회의록의 사람이 불분명하거나 1인 한도(회의비 · 다과비 5만원)로 사람이 모자라면 `fill_up` 이 참여인력선택에서 **아무나** 골라 채운다
(담당자 2026-11-11 "참여인력에서 임의로 사람을 선택해서 넣고 일단 저장만하기 … 임의로 넣은 사람도 안내").
고르는 규칙: **번호(학번 · 사번)가 있으면 번호로 먼저, 못 찾으면 이름으로**(담당자 2026-11-11). 번호는 참여연구원 명단의 직번이나 증빙(회의록 표 · 서명부 ·
AI 가 읽은 회의록)에서 그 이름 옆에 적힌 학번 · 사번(idnums.py · card.py). 번호로 고를 때도 이름이 같은 줄만 — 번호를 잘못 짝지었으면 이름으로 간다.
참여인력은 연 그대로의 목록(검색 칸은 성명뿐)에서 번호가 같은 줄 → 이름(명단에 직번이 있으면 직번도)이 같은 줄 하나. 참여인력선택 목록에 없으면 인적정보조회에서 직번으로 찾는다.
내부참석자는 이름이 같은 줄 가운데 — 회의록의 소속이 학과 같은 것이면 소속이 맞는 줄 → 여럿이면 재직 · 재학인 줄 — 하나. 소속을 모르면 재직 · 재학인 같은 이름이
하나일 때만(그때는 '신청 전 확인할 것' 에 남긴다). 재직 · 재학이 아닌 줄(제적 · 졸업 · 퇴직 …)은 소속이 맞을 때만 고른다.

누르는 것(tests/test_safety.py): 회의록등록 창의 두 [행 추가] · 두 창의 [검색] · 고른 줄의 체크 · 인적정보조회의 ⬇ · [확인](`#btnItem` · 글자 '확인'). 값을 넣는 칸은 두 창의 검색 칸뿐.
이 모듈은 Playwright 를 들여오지 않는다 — card_erp 가 넘겨준 창만 쓴다.
"""
from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace

from . import participants as part_mod
from .attach import CLICK_TEXT_JS
from .form import SET_TEXT_JS
from .payee import _ROWS_SNIPPET, CLICK_ID_JS, open_popup, wait_closed, wait_until
from .person import MAX_SCROLLS, _row_key, _scroll, listing

PART_ADD_ID = "btnRowAdd"                # 회의록등록 창 참여인력 [행 추가] → 참여인력선택
INTERNAL_ADD_ID = "btnRowAdd1"           # 회의록등록 창 내부참석자 [행 추가] → 인적정보조회(멀티)
SEARCH_ID = "btn_search"                 # 두 창 공통 [검색]
PART_FIELD_ID = "EMP_NM"                 # 참여인력선택 성명 칸
MULTI_FIELD_ID = "SEARCH_NM"             # 인적정보조회(멀티) 검색 칸 — 성명 · 사번/학번
PART_CONFIRM_ID = "btnItem"              # 참여인력선택 [확인]
CONFIRM_TEXT = "확인"                    # 인적정보조회(멀티) [확인] — id 없는 링크
ALLOWED_IDS = frozenset({PART_ADD_ID, INTERNAL_ADD_ID, SEARCH_ID, PART_CONFIRM_ID})
FORBIDDEN_TEXTS = ("선택없음", "외부인 등록")
COL_NO, COL_NAME = "k_EMP_NO", "k_EMP_NM"
ACTIVE_WORDS = ("재직", "재학", "복학", "재입학")   # k_WORK_STS_NM — 제적 · 졸업 · 퇴직 · 수료 · 휴학 · 휴직은 아님
NOT_LISTED = "참여인력선택 목록에 없음"

# 두 창 알아보기 — 숨은 #RTN_FUNC 가 그 창의 되돌림 함수(실측)
PART_PROBE_JS = """() => { const f = document.querySelector('#RTN_FUNC');
  return !!(f && /rcomm_0071_02/.test(f.value || '') && document.querySelector('#EMP_NM') && document.querySelector('#btnItem')); }"""
MULTI_PROBE_JS = """() => { const f = document.querySelector('#RTN_FUNC');
  return !!(f && /rcomm_0008_04/.test(f.value || '') && document.querySelector('#SEARCH_NM')); }"""
# 줄 하나의 체크를 켠다 — 이미 켜져 있으면 그대로(한 번 더 누르면 꺼진다). 줄 번호(r)가 다르면 다시 그려진 것이라 누르지 않는다
CHECK_ROW_JS = "([index, r]) => {" + _ROWS_SNIPPET + """
  const row = rows[index];
  if (!row) return {ok: false, why: '줄이 없음'};
  if (r && row.getAttribute('r') !== r) return {ok: false, why: '줄이 다시 그려짐'};
  const box = row.querySelector('input[type=checkbox]');
  if (!box) return {ok: false, why: '줄에 체크 칸이 없음'};
  if (!box.checked) box.click();
  return {ok: box.checked, why: box.checked ? '' : '체크가 켜지지 않음'};
}"""
# 인적정보조회(멀티)의 '고른 사람' 표 — 체크한 사람이 숨은 CFRC_IN_EMP_NO 로 쌓인다(실측 36 → 37번). 읽기만
BASKET_JS = """() => Array.from(document.querySelectorAll('input[name=CFRC_IN_EMP_NO]')).map(e => (e.value || '').trim()).filter(x => x)"""
# 그 줄의 체크 칸(마우스로 누를 것) — 줄 번호(r)가 다르면 다시 그려진 것이라 돌려주지 않는다
BOX_JS = "([index, r]) => {" + _ROWS_SNIPPET + """
  const row = rows[index];
  if (!row || (r && row.getAttribute('r') !== r)) return null;
  return row.querySelector('input[type=checkbox]');
}"""
# 체크했는데 '고른 사람' 표가 비었을 때 기록에 남길 모양(값 없이 수만) — 다음 기록으로 까닭을 본다
BASKET_STATE_JS = """() => ({checked: document.querySelectorAll('.jgrid-row input[type=checkbox]:checked').length,
  basket: document.querySelectorAll('input[name=CFRC_IN_EMP_NO]').length,
  rows: Array.from(document.querySelectorAll('table tr')).filter(tr => tr.querySelector('input[name=CFRC_IN_EMP_NO]')).length})"""
# 결과 목록과 '고른 사람' 표 사이의 ⬇ · ⬆ 단추(담당자 그림 2026-11-11 — 오른쪽에 빨간 ⬇ · 파란 ⬆, 글자 없음, 구조 저장은 아직).
# 체크만으로는 '고른 사람' 표가 비어 있었다 — ⬇ 로 체크한 줄을 내려 담는 것으로 보인다. 그 사이에 있는 글자 없는 작은 단추를 찾아
# data-coss-arrow 표시를 붙이고(누르기는 Playwright 가 사람처럼) 모양을 돌려준다 — 이름 · id · class · onclick · 그림 주소로 '내림' · '올림' 을 가린다.
# 올림(⬆ — 고른 사람을 빼는 것으로 보임)은 누르지 않는다. 읽기 · 표시만 하고 누르지 않는다.
ARROW_JS = r"""() => {
  const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const txt = e => ((e.innerText || e.textContent || e.value || '') + '').replace(/\s+/g, ' ').trim();
  document.querySelectorAll('[data-coss-arrow]').forEach(e => e.removeAttribute('data-coss-arrow'));
  // 결과 목록 — 학번 칸(k_EMP_NO)이 든 줄들의 목록(아래 '고른 사람' 표도 JGM 일 수 있어 그것과 가린다)
  const rows = Array.from(document.querySelectorAll('.jgrid-row')).filter(r => vis(r) && r.querySelector('.k_EMP_NO, .k_EMP_NM'));
  if (!rows.length) return {ok: false, why: '결과 목록이 안 보임', items: []};
  const boxes = rows.map(r => r.closest('.jgrid-viewport') || r);
  const gridBottom = Math.max(...boxes.map(e => e.getBoundingClientRect().bottom));
  // '고른 사람' 표의 위 — 숨은 CFRC_IN_EMP_NO 가 든 줄, 결과 목록 아래에서 '성명' · '소속' 이 함께 든 짧은 머리, 그것도 없으면 [확인]
  let lower = Infinity;
  for (const e of Array.from(document.querySelectorAll('tr, th, td, div, span')).filter(vis)) {
    const top = e.getBoundingClientRect().top;
    if (top <= gridBottom + 2) continue;
    const t = txt(e);
    if (e.querySelector('input[name=CFRC_IN_EMP_NO]') && t.length < 80 || /성명/.test(t) && /소속/.test(t) && t.length < 40)
      lower = Math.min(lower, top);
  }
  if (lower === Infinity)
    for (const a of Array.from(document.querySelectorAll('a, button, input[type=button]')).filter(vis))
      if (txt(a) === '확인' && a.getBoundingClientRect().top > gridBottom) lower = Math.min(lower, a.getBoundingClientRect().top);
  if (lower === Infinity) lower = gridBottom + 120;
  const clickable = e => /^(A|BUTTON)$/.test(e.tagName) || e.tagName === 'INPUT' && /^(button|image|submit)$/i.test(e.type)
    || e.hasAttribute('onclick') || getComputedStyle(e).cursor === 'pointer';
  let cands = Array.from(document.querySelectorAll('a, button, input, img, span, i, em, div, li')).filter(e => {
    if (!vis(e) || e.type === 'checkbox' || e.type === 'radio' || e.type === 'text' || e.type === 'hidden') return false;
    const r = e.getBoundingClientRect();
    if (r.width > 64 || r.height > 64 || r.top < gridBottom - 4 || r.bottom > lower + 4) return false;
    return txt(e).length <= 2 && clickable(e);
  });
  cands = cands.filter(e => !cands.some(o => o !== e && o.contains(e)));       // a > img 이면 바깥 것 하나
  const describe = e => [e.id, e.className && e.className.baseVal === undefined ? e.className : '', e.getAttribute('onclick'), e.title,
    e.getAttribute('alt'), e.getAttribute('aria-label'), e.getAttribute('src'),
    (e.querySelector('img') || {}).src, (e.querySelector('i,span') || {}).className, txt(e)].filter(x => x).join(' ').slice(0, 300);
  // 내림 · 올림 가리기 — 그림 주소가 가장 믿을 만하고(보이는 화살표), 그다음 id · onclick · title, 글자(alt)는 가장 약하게.
  // 실제 ERP(2026-11-12 기록): ⬆ 은 <img id=…Del alt='추가' src=…btn_bg_funup_off.gif>, ⬇ 은 <img id=…Add alt='삭제' src=…btn_bg_fundown_off.gif> —
  // alt 가 거꾸로 붙어 있어 글자만 보면 ⬆ 을 먼저 눌렀다
  const items = cands.map((e, n) => {
    const d = describe(e);
    const low = d.toLowerCase();
    const src = ((e.getAttribute('src') || '') + ' ' + ((e.querySelector('img') || {}).src || '')).toLowerCase();
    const code = [e.id, e.getAttribute('onclick'), e.title, e.getAttribute('aria-label'),
      e.className && e.className.baseVal === undefined ? e.className : ''].filter(x => x).join(' ').toLowerCase();
    let score = 0;
    if (/down/.test(src)) score += 4; else if (/(^|[^a-z])up|up([_.\-]|$)|funup/.test(src)) score -= 4;
    if (/down|add|plus|insert|append/.test(code)) score += 2;
    if (/(^|[^a-z])up|up(btn|[_.\-(]|$)|remove|minus|delete|_del|del_|del($|[^a-z])|rowdel/.test(code)) score -= 2;
    if (/추가|아래|내리|↓|▼|⬇/.test(low)) score += 1;
    if (/삭제|위로|올리|↑|▲|⬆/.test(low)) score -= 1;
    const kind = score > 0 ? 'down' : score < 0 ? 'up' : '';
    e.setAttribute('data-coss-arrow', String(n));
    const r = e.getBoundingClientRect();
    return {n, kind, x: Math.round(r.left), tag: e.tagName.toLowerCase(), shape: d.slice(0, 120)};
  });
  return {ok: true, why: '', items};
}"""
ARROW_SELECTOR = '[data-coss-arrow="%d"]'
MAX_ARROWS = 2                           # 내림으로 못 가리면 왼쪽부터 두 개까지(그림에서 ⬇ 이 왼쪽)


@dataclass
class AddReport:
    added: list[str] = field(default_factory=list)          # 앱이 넣은 사람(표에 이름이 생긴 것)
    lines: list[str] = field(default_factory=list)          # 결과 창 줄
    review: list[str] = field(default_factory=list)         # 신청 전 확인할 것
    left: dict[str, str] = field(default_factory=dict)      # 못 넣은 사람 → 까닭


def _squash(text) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def _digits(text) -> str:
    return "".join(ch for ch in str(text or "") if ch.isdigit())


def _active(cells: dict) -> bool:
    return any(w in str(cells.get("k_WORK_STS_NM", "")) for w in ACTIVE_WORDS)


def _org_key(org: str) -> str:
    """회의록의 소속에서 견줄 몸통 — 학교 이름뿐이거나 비었으면 ''(그것으로는 사람을 가릴 수 없다)."""
    text = _squash(org)
    for word in ("강원대학교", "강원대"):
        text = text.replace(word, "")
    return text if len(text) >= 2 else ""


def _dept_match(cells: dict, key: str) -> bool:
    for col in ("k_DEPT_NM", "k_UP_DEPT_NM", "k_BLNG_DEPT_NM"):
        dept = _squash(str(cells.get(col, "")).split("_")[0])    # '제어계측공학과_1991' 꼴 — 뒤의 입학년은 뗀다
        if len(dept) >= 2 and (key in dept or dept in key):
            return True
    return False


def choose_part(rows: list[dict], person: part_mod.Attendee) -> tuple[int | None, str]:
    """참여인력선택 목록(cells 의 줄들)에서 이 사람의 줄 — 이름이 같은 줄. 같은 이름이 여럿이면 직번이 같은 줄 하나.
    같은 이름이 하나면 명단의 직번과 목록의 사번이 달라도 그 줄(담당자 2026-11-12 "이름이 참여인력 명단에 있으면 참여인력으로" — 근거에 '다름')."""
    same = [i for i, c in enumerate(rows) if _squash(c.get(COL_NAME)) == _squash(person.name)]
    if not same:
        return None, NOT_LISTED
    if person.emp_no:
        hit = [i for i in same if _digits(rows[i].get(COL_NO)) == _digits(person.emp_no)]
        if len(hit) == 1:
            return hit[0], "참여인력 목록에서 직번 · 이름으로"
        if not hit and len(same) == 1:
            return same[0], "참여인력 목록에서 이름으로(명단의 직번과 목록의 사번이 다름)"
        if not hit:
            return None, f"같은 이름이 {len(same)}줄인데 직번이 같은 줄이 없음"
        same = hit
    if len(same) > 1:
        return None, f"같은 이름이 {len(same)}줄"
    return same[0], "참여인력 목록에서 이름으로"


def choose_person(rows: list[dict], person: part_mod.Attendee) -> tuple[int | None, str, bool]:
    """인적정보조회(멀티) 결과에서 이 사람의 줄 — (줄, 근거, 소속 없이 이름으로만 골랐는지). 확실하지 않으면 (None, 까닭, False)."""
    name = _squash(person.name)
    same = [i for i, c in enumerate(rows) if _squash(c.get(COL_NAME)) == name]
    if person.emp_no:                                       # 번호(직번 · 학번 · 사번)로 찾은 것 — 번호 · 이름이 둘 다 맞는 줄 하나
        hit = [i for i in same if _digits(rows[i].get(COL_NO)) == _digits(person.emp_no)]
        return (hit[0], "번호 · 이름으로", False) if len(hit) == 1 else (None, f"번호 · 이름이 맞는 줄 {len(hit)}개", False)
    if not same:
        return None, "이름이 같은 사람이 없음", False
    key = _org_key(person.org)
    if key:
        hit = [i for i in same if _dept_match(rows[i], key)]
        if not hit:
            return None, f"같은 이름 {len(same)}명 중 소속이 '{person.org}' 인 사람이 없음", False
        if len(hit) > 1:
            hit = [i for i in hit if _active(rows[i])] or hit
        if len(hit) == 1:
            return hit[0], "이름 · 소속으로", False
        return None, f"이름 · 소속이 같은 사람이 {len(hit)}명", False
    active = [i for i in same if _active(rows[i])]
    if len(active) == 1:
        return active[0], f"이름으로(재직 · 재학 {len(same)}명 중 1명)", True
    if not active:
        return None, f"같은 이름 {len(same)}명이 모두 재직 · 재학이 아님(제적 · 졸업 · 퇴직 등)", False
    return None, f"재직 · 재학인 같은 이름이 {len(active)}명(회의록에 소속이 있으면 앱이 고름)", False


def _search(popup, field_id: str, query: str, wait: Callable[[float], None]) -> tuple[bool, str]:
    def signature() -> str:
        try:
            rows, _ = listing(popup)
        except Exception:  # noqa: BLE001 — 그리는 중
            return "?"
        return "\n".join(str(r.get("text", "")) for r in rows)

    before = signature()
    typed = popup.evaluate(SET_TEXT_JS, [field_id, query])
    if not typed.get("ok"):
        return False, "검색 칸에 넣지 못함: " + str(typed.get("why", ""))
    clicked = popup.evaluate(CLICK_ID_JS, SEARCH_ID)
    if not clicked.get("ok"):
        return False, "[검색] 을 누르지 못함: " + str(clicked.get("why", ""))
    wait_until(lambda: signature() not in (before, "?"), wait, tries=10, step=0.5)
    return True, ""


def _scan_all(popup, wait: Callable[[float], None]) -> tuple[list[dict], dict]:
    """결과 줄 전부(가상 스크롤이면 끝까지 내려가며) — (줄들, 줄 열쇠 → 그 줄이 보인 스크롤 위치). 줄은 {'key', 'cells'}."""
    rows, where = listing(popup)
    info = _scroll(where, "info", wait)
    if info is None or info["sh"] <= info["h"] + 5:
        return [{"key": _row_key(r), "cells": r.get("cells") or {}} for r in rows], {}
    out: list[dict] = []
    tops: dict[str, int] = {}
    info = _scroll(where, "top", wait)
    last = -1
    for _ in range(MAX_SCROLLS):
        if info is None:
            break
        rows, where = listing(popup)
        for r in rows:
            key = _row_key(r)
            if key not in tops:
                tops[key] = info["top"]
                out.append({"key": key, "cells": r.get("cells") or {}})
        if info["top"] + info["h"] >= info["sh"] - 5 or info["top"] == last:
            break
        last = info["top"]
        info = _scroll(where, "next", wait)
    return out, tops


def _check(popup, key: str, tops: dict, wait: Callable[[float], None], mouse: bool = False) -> tuple[bool, str]:
    """고른 줄로 돌아가(스크롤했으면) 그 줄의 체크를 켠다. mouse 면 사람처럼 마우스로 누른다(인적정보조회 — 아래 _one)."""
    rows, where = listing(popup)
    if key in tops:
        _scroll(where, tops[key], wait)
        rows, where = listing(popup)
    index = next((i for i, r in enumerate(rows) if _row_key(r) == key), None)
    if index is None:
        return False, "고른 줄로 돌아가지 못함"
    r = rows[index].get("r") or ""
    if mouse:
        try:
            box = where.evaluate_handle(BOX_JS, [index, r]).as_element()
            if box is not None:
                if not box.is_checked():
                    box.click(timeout=5000)
                if box.is_checked():
                    return True, ""
        except Exception:  # noqa: BLE001 — 줄이 다시 그려짐 등 — 화면 스크립트로 한 번 더
            pass
    done = where.evaluate(CHECK_ROW_JS, [index, r])
    return bool(done.get("ok")), str(done.get("why", ""))


def _to_basket(popup, in_basket: Callable[[], bool], wait: Callable[[float], None], log: Callable[[str], None]) -> bool:
    """체크한 줄을 '고른 사람' 표로 — 결과 목록과 그 표 사이의 ⬇ 를 사람처럼 누른다(담당자 그림 2026-11-11: 체크만으로는 표가 비어 있었다).
    '내림' 으로 보이는 단추 먼저, 못 가리면 왼쪽부터 두 개까지. '올림'(⬆ — 빼기로 보임)은 누르지 않는다. 기록에는 단추 모양만(값 없음)."""
    try:
        found = popup.evaluate(ARROW_JS) or {}
    except Exception as error:  # noqa: BLE001 — 창이 닫히는 등
        log("  인적정보: ⬇ 단추를 찾지 못함 — " + (str(error).splitlines()[0][:80] if str(error) else type(error).__name__))
        return False
    items = list(found.get("items") or [])
    log("  인적정보: 체크만으로는 '고른 사람' 표에 안 들어가 ⬇ 단추를 찾습니다 — 후보 %d개%s" % (
        len(items), "".join(f" · [{i['kind'] or '?'}] {i['tag']} {i['shape']}" for i in items[:4])))
    order = [i for i in items if i["kind"] == "down"] or sorted((i for i in items if not i["kind"]), key=lambda i: i["x"])[:MAX_ARROWS]
    for item in order:
        try:
            popup.locator(ARROW_SELECTOR % item["n"]).first.click(timeout=5000)
        except Exception as error:  # noqa: BLE001 — 가려짐 등 — 다음 후보
            log("  인적정보: ⬇ 후보를 누르지 못함 — " + (str(error).splitlines()[0][:80] if str(error) else type(error).__name__))
            continue
        if wait_until(in_basket, wait, tries=10):
            log(f"  인적정보: ⬇ 로 '고른 사람' 표에 담음 ({item['tag']} {item['shape'][:60]})")
            return True
    return False


def _close(popup) -> None:
    """못 고른 창은 닫는다 — 창 닫기일 뿐 ERP 단추가 아니다. 사람이 [행 추가] 로 다시 연다."""
    try:
        if not popup.is_closed():
            popup.close()
    except Exception:  # noqa: BLE001 — 이미 닫힘
        pass


def choose_part_by_no(rows: list[dict], person: part_mod.Attendee) -> tuple[int | None, str]:
    """참여인력선택 목록에서 번호(k_EMP_NO)가 이 사람의 번호인 줄 — 하나이고 이름도 같을 때만(번호를 잘못 짝지었으면 엉뚱한 사람이 들어간다)."""
    want = _digits(person.emp_no)
    hit = [i for i, c in enumerate(rows) if want and _digits(c.get(COL_NO)) == want]
    if not hit:
        return None, f"목록 {len(rows)}줄에 그 번호인 줄이 없음"
    if len(hit) > 1:
        return None, f"번호가 같은 줄이 {len(hit)}개"
    got = _squash(rows[hit[0]].get(COL_NAME))
    if got and got != _squash(person.name):
        return None, "번호는 같은데 이름이 다름"
    return hit[0], "참여인력 목록에서 번호 · 이름으로"


def _rows_shown(popup, wait: Callable[[float], None]) -> None:
    """참여인력선택은 열면 그 과제의 참여인력이 그려져 있다(실측 21줄) — 그려질 때까지 잠깐."""
    def shown() -> bool:
        try:
            return bool(listing(popup)[0])
        except Exception:  # noqa: BLE001 — 그리는 중
            return False

    wait_until(shown, wait, tries=10)


def _one(minutes, person: part_mod.Attendee, multi: bool, log: Callable[[str], None], wait: Callable[[float], None],
         names_now: Callable[[], list[str]]) -> tuple[bool, str, str]:
    """한 사람을 넣는다 — (넣었는지, 근거 · 까닭, 넣었으면 신청 전 확인할 말 — 없으면 '').

    번호(학번 · 사번 — 명단의 직번이나 증빙의 번호)가 있으면 **번호로 먼저**, 못 찾으면 이름으로(담당자 2026-11-11). 인적정보조회는 검색 칸이 번호를 받고(실측),
    참여인력선택은 검색 칸이 성명뿐이라 연 그대로의 목록(그 과제의 참여인력)에서 번호가 같은 줄을 찾는다."""
    button = INTERNAL_ADD_ID if multi else PART_ADD_ID
    assert button in ALLOWED_IDS
    popup, why = open_popup(minutes, minutes, button, MULTI_PROBE_JS if multi else PART_PROBE_JS, log)
    if popup is None:
        return False, ("내부참석자" if multi else "참여인력") + " [행 추가] 창을 열지 못함: " + why, ""
    if not wait_until(lambda: popup.evaluate(MULTI_PROBE_JS if multi else PART_PROBE_JS) is True, wait, tries=40):
        _close(popup)
        return False, "사람 찾기 창이 아님", ""
    done = False
    try:
        no = _digits(person.emp_no)
        what_no = "직번" if person.no_from == part_mod.ROSTER else "번호"
        # (무엇, 검색어, 고르는 규칙) — 검색어가 None 이면 검색하지 않고 연 그대로의 목록에서
        attempts: list[tuple[str, str | None, Callable]] = []
        if no and multi:
            attempts.append((what_no, no, lambda cells: choose_person(cells, person)))
        elif no:
            attempts.append((what_no, None, lambda cells: (*choose_part_by_no(cells, person), False)))
        by_name_person = replace(person, emp_no="") if multi else person   # 번호로 못 찾았으면 이름 · 소속으로(인적정보조회)
        attempts.append(("이름", person.name, (lambda cells: choose_person(cells, by_name_person)) if multi
                         else (lambda cells: (*choose_part(cells, person), False))))
        index = None
        rows: list[dict] = []
        tops: dict = {}
        cells: list[dict] = []
        why, by_name, used = "", False, ""
        for what, query, choose in attempts:
            if query is None:
                _rows_shown(popup, wait)
            else:
                ok, note = _search(popup, MULTI_FIELD_ID if multi else PART_FIELD_ID, query, wait)
                if not ok:
                    return False, note, ""
            rows, tops = _scan_all(popup, wait)
            cells = [r["cells"] for r in rows]
            index, why, by_name = choose(cells)
            # 기록에는 이름 · 사번을 남기지 않는다(로그 보내기로 나간다) — 무엇으로 찾았는지만
            log("  %s 찾기(%s%s) → %d줄: %s" % ("인적정보" if multi else "참여인력", what, "" if query is not None else " · 목록 그대로",
                                            len(rows), why))
            used = what
            if index is not None:
                break
        if index is None:
            return False, why, ""
        review = ""
        if no and used == "이름":
            source = "참여연구원 명단의 직번" if what_no == "직번" else f"증빙({person.no_from or '회의록 · 서명부'})의 학번 · 사번"
            review = f"{source}으로는 찾지 못해 이름으로 골랐습니다({why}) — 회의록등록에서 사번 · 소속을 확인하세요"
        elif by_name:
            review = f"소속 없이 이름으로 골랐습니다({why}) — 회의록등록에서 사번 · 소속을 확인하세요"
        chosen = cells[index]
        # 인적정보조회는 사람처럼 마우스로 체크한다 — 화면 스크립트로 누른 체크는 '고른 사람' 표에 쌓이지 않았다(2026-11-11 20:18 실제:
        # 줄은 체크됐는데 [확인] 에 '선택된 내역이 없습니다' 가 떠 내부참석자를 하나도 못 넣었다. 참여인력선택은 스크립트로 됐다)
        ok, note = _check(popup, rows[index]["key"], tops, wait, mouse=multi)
        if not ok:
            return False, "줄을 체크하지 못함: " + note, ""
        if multi:
            # 체크하면 '고른 사람' 표에 조금 뒤에 쌓인다(실측) — 쌓인 뒤에만 [확인](비었는데 누르면 ERP 가 '선택된 내역이 없습니다' 로 막는다)
            want = _digits(chosen.get(COL_NO))

            def in_basket() -> bool:
                return want in [_digits(v) for v in (popup.evaluate(BASKET_JS) or [])]

            if not wait_until(in_basket, wait, tries=4) and not _to_basket(popup, in_basket, wait, log):
                try:
                    state = popup.evaluate(BASKET_STATE_JS) or {}
                except Exception:  # noqa: BLE001
                    state = {}
                log("  인적정보: 줄을 체크했지만 '고른 사람' 표에 들어가지 않음 (체크된 줄 %s · 고른 사람 칸 %s)"
                    % (state.get("checked", "?"), state.get("basket", "?")))
                return False, "줄을 체크했지만 '고른 사람' 표에 들어가지 않음 — 인적정보조회 창에서 ⬇ 로 내려 담고 [확인] 하세요", ""
            clicked = popup.evaluate(CLICK_TEXT_JS, CONFIRM_TEXT)
        else:
            clicked = popup.evaluate(CLICK_ID_JS, PART_CONFIRM_ID)
        if not clicked.get("ok"):
            return False, "[확인] 을 누르지 못함: " + str(clicked.get("why", "")), ""
        if not wait_closed(popup, wait, seconds=10):
            return False, "[확인] 을 눌렀지만 창이 닫히지 않음", ""
        name = _squash(person.name)
        if not wait_until(lambda: name in {_squash(n) for n in names_now()}, wait, tries=12):
            return False, "[확인] 뒤 회의록등록 창에 이름이 보이지 않음", ""
        done = True
        return True, why, review
    finally:
        if not done:
            _close(popup)


DEPT_COLS = ("k_DEPT_NM", "k_UP_DEPT_NM", "k_BLNG_DEPT_NM")
ERP_PART_LIST = "ERP 참여인력 목록"


def part_rows(minutes, log: Callable[[str], None], wait: Callable[[float], None]) -> list[dict] | None:
    """참여인력선택 창을 열어 그 과제의 참여인력 목록(줄마다 cells)을 읽고 닫는다 — 체크 · [확인] 없이 창 닫기. 못 읽으면 None."""
    assert PART_ADD_ID in ALLOWED_IDS
    popup, why = open_popup(minutes, minutes, PART_ADD_ID, PART_PROBE_JS, log)
    if popup is None:
        log("  참여인력선택 창을 열지 못해 참여인력 목록을 보지 못함: " + why)
        return None
    try:
        if not wait_until(lambda: popup.evaluate(PART_PROBE_JS) is True, wait, tries=40):
            log("  참여인력선택 창이 아니라 참여인력 목록을 보지 못함")
            return None
        _rows_shown(popup, wait)
        rows, _tops = _scan_all(popup, wait)
        cells = [r["cells"] for r in rows]
        cols = sorted({k for c in cells for k, v in c.items() if str(v).strip()})
        named = sum(1 for c in cells if _squash(c.get(COL_NAME)))
        # 값 없이 열 이름 · 수만 — 이름 열을 못 읽었는지(열 이름이 다른지) 기록으로 본다
        log(f"  참여인력선택 목록 {len(cells)}줄 · 이름 읽힌 줄 {named} · 열 {', '.join(cols[:12]) or '없음'}")
        return cells
    finally:
        _close(popup)


def on_part_list(rows: list[dict], person: part_mod.Attendee) -> tuple[str | None, str]:
    """이 사람이 참여인력 목록에 있나 — (목록의 사번 · 없으면 None, 근거 또는 못 돌린 까닭).
    **이름이 목록에 있으면 참여인력**(담당자 2026-11-12 "이름이 참여인력 명단에 있으면 참여인력으로 봐주세요"): 같은 이름이 하나면 그 줄 — 증빙의 번호가
    목록의 사번과 달라도(학생은 학번 · 목록은 사번일 수 있다), 소속이 회의록과 달라도(목록의 소속은 학과가 아니라 사업단 등일 수 있다) 근거에 '다름' 을 적는다.
    같은 이름이 여럿이면 번호 · 이름이 같은 줄, 아니면 소속이 맞는 줄 하나. 참여기간으로 다시 거르지 않는다 — 창이 회의일자(#START_DATE)로 이미 거른 목록이다."""
    name = _squash(person.name)
    same = [c for c in rows if name and _squash(c.get(COL_NAME)) == name]
    if not same:
        return None, f"목록 {len(rows)}줄에 같은 이름이 없음"
    no = _digits(person.emp_no)
    if no:
        hit = [c for c in same if _digits(c.get(COL_NO)) == no]
        if len(hit) == 1:
            return str(hit[0].get(COL_NO, "")).strip(), "번호 · 이름"
        if len(hit) > 1:
            return None, f"번호 · 이름이 같은 줄 {len(hit)}개"
        if len(same) == 1:
            return str(same[0].get(COL_NO, "")).strip(), "이름(증빙의 번호와 목록의 사번이 다름)"
    key = _org_key(person.org)
    if len(same) == 1:
        has_dept = any(str(same[0].get(col, "")).strip() for col in DEPT_COLS)
        if key and has_dept and not _dept_match(same[0], key):
            return str(same[0].get(COL_NO, "")).strip(), "이름(소속은 회의록과 다름)"
        return str(same[0].get(COL_NO, "")).strip(), "이름 · 소속" if key and has_dept else "이름"
    hit = [c for c in same if key and _dept_match(c, key)]
    if len(hit) == 1:
        return str(hit[0].get(COL_NO, "")).strip(), "이름 · 소속"
    return None, f"같은 이름 {len(same)}줄" + (" · 번호가 같은 줄 없음" if no else "")


def regroup(rows: list[dict], people: list[part_mod.Attendee], skip=()) -> tuple[list[part_mod.Attendee], int, list[str]]:
    """내부참석자 가운데 그 과제의 참여인력 목록에 이름이 있는 사람을 참여인력으로(목록의 사번으로 찾게) — (새 목록, 돌린 수, 기록 줄).
    담당자 2026-11-12 "이름이 참여인력 명단에 있으면 참여인력으로 봐주세요" · "소속이 강원대나 데이터보안활용사업단일때만 참여인력으로 보기" —
    외부참석자(소속이 다른 학교 · 회사)는 목록에 같은 이름이 있어도 동명이인으로 보고 돌리지 않는다(classify 가 소속으로 이미 나눴다).
    skip 은 이미 회의록등록 창의 표에 든 이름(띄어쓰기 뺀 것) — 건드리지 않는다. 기록 줄에는 이름을 쓰지 않는다('N번째 사람' — 로그 보내기로 나간다)."""
    out, moved, notes = [], 0, []
    skip = {_squash(n) for n in skip}
    for order, person in enumerate(people, 1):
        if person.kind != "internal" or _squash(person.name) in skip:
            out.append(person)
            continue
        emp_no, how = on_part_list(rows, person)
        if emp_no is None:
            notes.append(f"{order}번째 사람: 내부참석자로 — {how}")
            out.append(person)
            continue
        notes.append(f"{order}번째 사람: 참여인력으로 — {how}")
        if "사번이 다름" in how:
            hint = "증빙의 학번 · 사번이 ERP 참여인력 목록의 사번과 다르지만 이름이 목록에 있어 참여인력으로 넣음 — 같은 사람인지 확인하세요"
        elif "소속은" in how:
            hint = "ERP 참여인력 목록에서 이름으로 참여인력으로 넣었지만 그 목록의 소속이 회의록과 다름 — 같은 사람인지 확인하세요"
        else:
            hint = person.hint
        out.append(replace(person, kind="part", emp_no=emp_no or person.emp_no, hint=hint, note="",
                           no_from=f"{ERP_PART_LIST}({how})" if emp_no else person.no_from))
        moved += 1
    return out, moved, notes


def add(minutes, people: list[part_mod.Attendee], log: Callable[[str], None], wait: Callable[[float], None],
        names_now: Callable[[], list[str]]) -> AddReport:
    """회의록의 참여인력 · 내부참석자 가운데 아직 표에 없는 사람(people)을 넣는다. 확실하지 않은 사람은 left 에 까닭과 함께."""
    report = AddReport()
    for order, person in enumerate(people, 1):
        who = f"{order}번째 사람"                                # 기록용 — 이름은 화면(결과 창 · 노란 띠)에만
        if person.kind == "internal" and person.note:            # 참여연구원 명단에 같은 이름이 여럿 — 직번을 보고 사람이
            report.left[person.name] = person.note
            continue
        multi = person.kind == "internal"
        try:
            ok, why, note = _one(minutes, person, multi, log, wait, names_now)
            if not ok and not multi and person.emp_no and why == NOT_LISTED:
                # 그날 참여기간이 아니거나 목록에 없으면 — 인적정보조회에서 직번으로(내부참석자 줄로 들어간다)
                log(f"  {who}: {NOT_LISTED} — 인적정보조회에서 직번으로 찾습니다")
                multi = True
                ok, why, note = _one(minutes, person, True, log, wait, names_now)
                if ok:
                    report.review.append(f"{person.name}: 참여인력 목록에 없어 내부참석자로 넣음 — 참여기간을 확인하세요")
        except Exception as error:  # noqa: BLE001 — 창이 닫히는 등 — 사람에게
            ok, why, note = False, "오류: " + (str(error).splitlines()[0][:100] if str(error) else type(error).__name__), ""
        kind = "내부참석자" if multi else "참여인력"
        if ok:
            report.added.append(person.name)
            report.lines.append(f"{kind} 자동 선택: {person.name} — {why}")
            log(f"  ✓ {kind} {who} — {why}")
            for text in (note, person.hint):
                if text:
                    report.review.append(f"{person.name}: {text}")
        else:
            report.left[person.name] = why
            log(f"  ✗ {kind} {who}: {why}")
    return report


DATE_IN_TEXT_RE = re.compile(r"(\d{4})[-./]?\s*(\d{1,2})[-./]?\s*(\d{1,2})")


def _covers(text, day) -> bool | None:
    """참여기간 글('2026-03-01 ~ 2027-02-28' 꼴 — 실측 전)에 회의일이 드는지. 날짜를 둘 못 읽거나 회의일을 모르면 None."""
    found = []
    for y, m, d in DATE_IN_TEXT_RE.findall(str(text or "")):
        try:
            found.append(dt.date(int(y), int(m), int(d)))
        except ValueError:
            continue
    if day is None or len(found) < 2:
        return None
    return found[0] <= day <= found[-1]


def choose_any(rows: list[dict], count: int, taken_names, taken_nos=(), day=None) -> list[int]:
    """참여인력선택 목록에서 아무나 count 명(담당자 2026-11-11 — 회의록의 사람이 불분명하거나 1인 한도로 사람이 모자라면 임의로 넣고 일단 저장).
    회의록등록 표에 이미 있는 사람 · 피할 이름은 빼고, 재직상태가 적혀 있으면 재직 · 재학만, 참여기간을 읽을 수 있으면 회의일이 든 사람만 — 목록 차례로."""
    if count <= 0:
        return []
    names = {_squash(n) for n in taken_names if _squash(n)}
    nos = {_digits(n) for n in taken_nos if _digits(n)}
    out: list[int] = []
    seen: set[str] = set()
    for i, cells in enumerate(rows):
        name, no = _squash(cells.get(COL_NAME)), _digits(cells.get(COL_NO))
        if not name or name in names or (no and no in nos) or (no or name) in seen:
            continue
        if str(cells.get("k_WORK_STS_NM", "")).strip() and not _active(cells):
            continue
        if _covers(cells.get("k_PART_TRM_DT", ""), day) is False:
            continue
        seen.add(no or name)
        out.append(i)
        if len(out) >= count:
            break
    return out


def fill_up(minutes, count: int, log: Callable[[str], None], wait: Callable[[float], None], names_now: Callable[[], list[str]],
            avoid=(), taken_nos=(), day=None) -> AddReport:
    """참여인력 [행 추가] 창을 한 번 열어 아무나 count 명을 체크하고 [확인] — 넣은 사람은 added(이름), 모자라면 lines 에 까닭.
    누르는 것은 _one 과 같다(참여인력 [행 추가] · 줄 체크 · [확인] #btnItem). 기록에는 이름을 남기지 않는다."""
    report = AddReport()
    if count <= 0:
        return report
    assert PART_ADD_ID in ALLOWED_IDS
    popup, why = open_popup(minutes, minutes, PART_ADD_ID, PART_PROBE_JS, log)
    if popup is None:
        report.lines.append("참여인력 [행 추가] 창을 열지 못해 임의로 넣지 못함: " + why)
        return report
    done = False
    try:
        if not wait_until(lambda: popup.evaluate(PART_PROBE_JS) is True, wait, tries=40):
            report.lines.append("참여인력선택 창이 아니라 임의로 넣지 못함")
            return report
        rows, tops = _scan_all(popup, wait)
        cells = [r["cells"] for r in rows]
        picked = choose_any(cells, count, list(names_now()) + list(avoid), taken_nos, day)
        log(f"  참여인력선택 목록 {len(rows)}줄 — 임의로 {len(picked)}명 고름(필요 {count}명)")
        checked = []
        for index in picked:
            ok, note = _check(popup, rows[index]["key"], tops, wait)
            if ok:
                checked.append(cells[index])
            else:
                log("  ✗ 임의로 고른 줄을 체크하지 못함: " + note)
        if not checked:
            report.lines.append(f"참여인력선택 목록에서 더 넣을 사람을 찾지 못함(목록 {len(rows)}줄)")
            return report
        clicked = popup.evaluate(CLICK_ID_JS, PART_CONFIRM_ID)
        if not clicked.get("ok"):
            report.lines.append("참여인력선택 [확인] 을 누르지 못함: " + str(clicked.get("why", "")))
            return report
        if not wait_closed(popup, wait, seconds=10):
            report.lines.append("참여인력선택 [확인] 을 눌렀지만 창이 닫히지 않음")
            return report
        done = True
        want = [str(c.get(COL_NAME, "")).strip() for c in checked]
        wait_until(lambda: {_squash(n) for n in want} <= {_squash(n) for n in names_now()}, wait, tries=12)
        now = {_squash(n) for n in names_now()}
        report.added = [n for n in want if _squash(n) in now]
        log(f"  ✓ 참여인력 임의로 {len(report.added)}명 넣음")
        if len(report.added) < count:
            report.lines.append(f"참여인력을 임의로 {count}명 넣어야 하는데 {len(report.added)}명만 넣음")
        return report
    finally:
        if not done:
            _close(popup)
