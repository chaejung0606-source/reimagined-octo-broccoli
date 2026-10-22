"""로그인 뒤 청구서 화면까지 — 메인화면 '과제현황' 에서 고른 과제를 열고 과제정보의 '청구서' 탭(결의서내역)까지 간다.

담당자 허락(2026-10-19): 로그인은 사람이 하고(9절 — 아이디 · 비밀번호는 어디에도 두지 않는다), 그 뒤 결의서내역까지의 이동은 앱이 한다.
과제는 설정의 과제번호(기본 202408470003, 담당자 지정)로 고른다. 실측(같은 날 15:14 · 15:15 [화면 구조 저장]):

- 로그인 직후 창 0 의 프레임 `rmain_0002_01.act`(대시보드)에 '과제현황' 탭(기본으로 켜짐)의 표 — 과제책임자 | 과제번호 | 과제명 | 과제담당자 |
  과제기간(`2026-03-01~2027-02-28`) | 사업비 | 잔여기간 | 청구가능액. 줄마다 과제명 링크 `<a class="txt_ellipsis link" onclick="fnPage('01','<과제번호>',…)">`
  가 있다. 목록은 '진행과제'(기본, 끝난 과제도 섞여 나옴) · 다섯 줄씩 쪽 나눔(#prevBtn · #nextBtn).
- 과제명 링크를 누르면 위쪽 탭 '과제정보' 가 열리고 프레임 `rtask_0008_t00_01.act?PRJ_NO=<과제번호>&…&TAB_ID=01` 이 뜬다. 거기 숨은 `#PRJ_NO` 와
  하위 탭 링크(기본정보 · 예산 · 참여인력 · **청구서** · 지출현황 · …, id 없음)가 있다.
- '청구서' 를 누른 뒤의 화면은 6절의 결의서내역 그리드(`erp.find_grid`)가 뜨는 것으로 본다 — 이 단계는 아직 실측이 없어, 그리드가 안 뜨면
  사람에게 넘긴다(아무것도 바꾸지 않았으니 사람이 하던 대로 이어 하면 된다).

새 청구서(담당자 허락 2026-10-19 — 폴더를 여럿 넣을 때 앱이 띄운다, 실측 같은 날 15:19 · 15:20 · 15:21):
- '청구서' 탭을 누르면 프레임 `rtask_0008_t04_01.act`(결의서 목록, `erp.find_grid`)가 뜨고 그 위에 `#P10 '일반청구'` · `#P11 '카드청구'` · `#P12 '대량청구'` ….
- `#P10` 을 누르면 위쪽 탭 '청구서(일반)' 에 새 작성 화면(`rexpe_0084_01.act`, `#REQ_CNT` 빔 · `#MOD_YN`=N · 새 `#REQ_SEQ_NO`=`TMP_REQ_…`)이 뜬다.
- 일반청구 · 카드청구 탭은 함께 열리지 않는다 — 일반청구 탭을 둔 채 [카드청구] 를 누르면 그 탭이 카드청구로 바뀐다(담당자). 같은 자리를 쓰므로
  [일반청구] 를 다시 누르면 있던 작성 화면이 새 것으로 바뀐다고 본다 — 그래서 **지금 작성 화면이 저장된 청구서이고 입력 칸이 비었을 때만** 누른다
  (저장 전 입력이 있으면 날아간다). 누른 뒤 결의번호 없는 새 작성 화면이 떴는지 본다. 작성 화면의 '새 청구서' 단추는 누르지 않는다(무엇을 하는지 미실측).

누르는 것은 과제명 링크 · '청구서' 탭 · '예산' 탭(대응자금 과제의 비목 차례 읽기, 2026-10-21) · 결의서 목록의 `#P10` · `#P11` · 위쪽 '메인화면' · '과제정보' 탭, 그리고 고른 과제가 과제현황 첫 쪽에
없을 때만 과제현황의 쪽 번호 · 쪽 단추(`#prevBtn` · `#nextBtn`)와 거르기 '전체과제'(`#SEARCH_GB` → 보기 '전체과제', 목록이 그대로면 [검색]) —
2026-10-21 담당자 "전체과제로 설정하고 2페이지를 눌러야함" — 뿐이다(tests/test_safety.py). 값을 넣지 않는다. Playwright 를 들여오지 않는다 —
프레임의 evaluate 와, 쪽 단추를 화면 스크립트로 눌러도 쪽이 안 바뀔 때 그 단추 하나를 프레임의 click 으로 한 번 더 누르는 것뿐이다.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass

from . import erp, logout, settings

CLAIM_TAB_TEXT = "청구서"

# 과제현황 표의 과제 — 과제명 링크의 onclick(fnPage('01','<과제번호>', …))에서 번호를, 그 줄 글자에서 과제기간을 읽는다. 읽기만 한다.
# 과제기간 칸은 숨은 사본 글자가 붙어 두 번 보일 수 있어(실측 '2026-03-01~2027-02-28…-0') 첫 날짜 쌍만 쓴다.
PROJECTS_JS = r"""() => {
  const txt = e => (e.innerText || e.textContent || '').replace(/\s+/g, ' ').trim();
  const out = [], seen = new Set();
  document.querySelectorAll('a[onclick]').forEach(a => {
    const m = (a.getAttribute('onclick') || '').match(/fnPage\(\s*'01'\s*,\s*'(\d{6,})'/);
    if (!m || seen.has(m[1])) return;
    seen.add(m[1]);
    let period = null;
    for (let cur = a.parentElement, i = 0; cur && i < 6 && !period; cur = cur.parentElement, i++) {
      period = (cur.innerText || cur.textContent || '').match(/(\d{4}-\d{2}-\d{2})\s*~\s*(\d{4}-\d{2}-\d{2})/);
    }
    const r = a.getBoundingClientRect();
    out.push({no: m[1], name: txt(a).slice(0, 80), start: period ? period[1] : '', end: period ? period[2] : '',
              visible: r.width > 0 && r.height > 0});
  });
  return out;
}"""

# 고른 과제의 과제명 링크를 누른다 — 화면에 보이는 것만(과제현황 탭이 켜진 대시보드). 하나가 아니면 누르지 않는다.
CLICK_PROJECT_JS = r"""(no) => {
  const want = new RegExp("fnPage\\(\\s*'01'\\s*,\\s*'" + no + "'");
  const shown = Array.from(document.querySelectorAll('a[onclick]')).filter(a => {
    const r = a.getBoundingClientRect();
    return want.test(a.getAttribute('onclick') || '') && r.width > 0 && r.height > 0;
  });
  if (shown.length !== 1) return {ok: false, why: shown.length ? '과제명 링크가 여럿' : '과제현황에 이 과제가 보이지 않음'};
  shown[0].click();
  return {ok: true};
}"""

# 과제현황 표의 쪽 넘김 — 고른 과제가 다른 쪽에 있을 때만 누른다(받기의 '폴더 만든 과제 모두' 가 끝난 과제까지 찾아가게, 담당자 2026-10-21).
# 화면 이동일 뿐 값을 바꾸지 않는다. 실측(2026-10-21 17:36, 전체과제 2쪽): `#prevBtn` · `<a id="1">1</a>` · `<strong>2</strong>`(지금 쪽) · `#nextBtn`.
# which 가 숫자면 그 쪽 번호 링크 — #prevBtn 과 #nextBtn 을 함께 담은 묶음 안의 숫자뿐인 링크 하나(과제 줄의 금액 링크 fnPage 는 빼고).
# 'nextBtn' · 'prevBtn' 이면 그 단추 — 보이고 막히지 않았을 때만.
CLICK_PAGE_JS = r"""(which) => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  if (/^[0-9]{1,2}$/.test(which)) {
    const nb = document.getElementById('nextBtn'), pb = document.getElementById('prevBtn');
    let box = nb && pb ? nb.parentElement : null;
    for (let i = 0; box && !box.contains(pb) && i < 2; i++) box = box.parentElement;
    if (!box || !box.contains(pb)) return {ok: false, why: '쪽 번호가 없음'};
    let hits = Array.from(box.querySelectorAll('a')).filter(a => vis(a) && (a.innerText || a.textContent || '').trim() === which
      && !/fnPage/.test(a.getAttribute('onclick') || ''));
    if (hits.length > 1) hits = hits.filter(a => a.id === which);
    if (hits.length !== 1) return {ok: false, why: hits.length ? '쪽 번호가 여럿' : '쪽 번호가 없음'};
    hits[0].click();
    return {ok: true};
  }
  if (which !== 'nextBtn' && which !== 'prevBtn') return {ok: false, why: '쪽 단추가 아님'};
  const b = document.getElementById(which);
  if (!b) return {ok: false, why: '쪽 단추가 없음'};
  const r = b.getBoundingClientRect();
  if (!(r.width > 0 && r.height > 0)) return {ok: false, why: '쪽 단추가 보이지 않음'};
  if (b.disabled || /disabled/i.test(b.className || '') || b.getAttribute('aria-disabled') === 'true') return {ok: false, why: '끝 쪽'};
  b.click();
  return {ok: true};
}"""
PAGE_BUTTONS = ("nextBtn", "prevBtn")
MAX_PAGES = 6

# 쪽 단추를 누르기 전에 볼 것 — 읽기만 한다. 누를 수 있으면 '', 아니면 까닭(CLICK_PAGE_JS 와 같은 글).
PAGE_STATE_JS = r"""(which) => {
  const b = document.getElementById(which);
  if (!b) return '쪽 단추가 없음';
  const r = b.getBoundingClientRect();
  if (!(r.width > 0 && r.height > 0)) return '쪽 단추가 보이지 않음';
  if (b.disabled || /disabled/i.test(b.className || '') || b.getAttribute('aria-disabled') === 'true') return '끝 쪽';
  return '';
}"""

# 과제현황 쪽 넘김의 모양 — 기록용으로 읽기만 한다(2026-10-21 실제 ERP 에서 #nextBtn 으로 둘째 쪽을 못 넘겨, 다음에는 기록으로 까닭을 본다).
# 단추마다 있음 · 보임 · 막힘 · 크기 · 같은 id 수, 단추 둘레의 쪽 표시(숫자 · 빗금만 — 실측에 '<strong>1</strong>' 이 있었다), 과제명 링크 수.
PAGER_JS = r"""() => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const btn = id => {
    const all = document.querySelectorAll('[id="' + id + '"]');
    if (!all.length) return '없음';
    const b = all[0], r = b.getBoundingClientRect();
    const off = b.disabled || /disabled/i.test(b.className || '') || b.getAttribute('aria-disabled') === 'true';
    return (vis(b) ? '보임' : '숨김') + (off ? '·막힘' : '') + ' ' + Math.round(r.width) + '×' + Math.round(r.height)
      + (b.tagName === 'BUTTON' ? ' ' + (b.getAttribute('type') || '(type 없음)') : ' ' + b.tagName.toLowerCase())
      + (b.form ? ' · form 안' : '') + (all.length > 1 ? ' · 같은 id ' + all.length + '개' : '');
  };
  const txt = e => (e.innerText || e.textContent || '').replace(/\s+/g, ' ').trim();
  const links = Array.from(document.querySelectorAll('a[onclick]')).filter(a => /fnPage\(\s*'01'/.test(a.getAttribute('onclick') || ''));
  let pages = '';
  const nb = document.getElementById('nextBtn'), pb = document.getElementById('prevBtn');
  for (let cur = nb && nb.parentElement, i = 0; cur && i < 2 && !pages; cur = cur.parentElement, i++) {
    const t = (cur.innerText || cur.textContent || '').replace(/[^0-9\/]+/g, ' ').replace(/\s+/g, ' ').trim();
    if (t) pages = t.slice(0, 20);
  }
  // 쪽 번호(누를 수 있는 숫자 링크)와 지금 쪽(링크가 아닌 숫자 — 실측 <strong>) — CLICK_PAGE_JS 와 같은 묶음에서
  const nums = [];
  let now = '';
  let box = nb && pb ? nb.parentElement : null;
  for (let i = 0; box && !box.contains(pb) && i < 2; i++) box = box.parentElement;
  if (box && box.contains(pb)) {
    box.querySelectorAll('a').forEach(a => {
      const t = txt(a);
      if (/^[0-9]{1,2}$/.test(t) && vis(a) && !/fnPage/.test(a.getAttribute('onclick') || '') && !nums.includes(t)) nums.push(t);
    });
    for (const e of box.querySelectorAll('strong, em, b, span, li')) {
      const t = txt(e);
      if (/^[0-9]{1,2}$/.test(t) && vis(e) && !e.closest('a') && !e.querySelector('a')) { now = t; break; }
    }
  }
  // 과제현황 거르기(#SEARCH_GB — 진행과제 · 전체과제 …)와 검색 칸에 글자가 있는지(글자는 읽지 않는다)
  const gb = document.getElementById('SEARCH_GB'), q = document.getElementById('S_PRJ_NM');
  return {next: btn('nextBtn'), prev: btn('prevBtn'), links: links.length, shown: links.filter(vis).length, pages,
          nums, now, filter: gb ? txt(gb) : '', query: !!(q && String(q.value || '').trim())};
}"""

# 과제현황 거르기를 '전체과제' 로 — 담당자 2026-10-21 "전체과제로 설정하고 2페이지를 눌러야함". 끝난 과제(202408470001 · 202409710001 ·
# 202502320001)는 기본 거르기 '진행과제'(8과제 · 한 쪽)에 없고 '전체과제'(13과제 · 두 쪽)의 둘째 쪽에 있다(실측 같은 날 17:36).
# step 'open' = 거르기 단추(#SEARCH_GB)를 눌러 보기를 펼침 · 'pick' = 바로 곁의 보기 '전체과제' 하나 · 'search' = 거르기가 바뀌었는데
# 목록이 그대로일 때만 과제현황 [검색](#btnPrjSearch, 검색 칸이 비었을 때만). 카드미청구 탭의 같은 보기(#CARD_SEARCH_GB 곁)는 고르지 않는다.
ALL_PROJECTS = "전체과제"
ALL_PROJECTS_JS = r"""(step) => {
  const txt = e => (e.innerText || e.textContent || '').replace(/\s+/g, ' ').trim();
  const sel = document.getElementById('SEARCH_GB');
  if (!sel) return {ok: false, why: '과제현황 거르기 칸(#SEARCH_GB)이 없음'};
  if (step === 'search') {
    if (txt(sel) !== '전체과제') return {ok: false, why: "거르기가 '전체과제' 가 아님"};
    const q = document.getElementById('S_PRJ_NM'), b = document.getElementById('btnPrjSearch');
    if (!b || txt(b) !== '검색') return {ok: false, why: '과제현황 [검색] 이 없음'};
    if (q && String(q.value || '').trim()) return {ok: false, why: '과제현황 검색 칸에 글자가 있음'};
    b.click();
    return {ok: true};
  }
  if (txt(sel) === '전체과제') return {ok: true, done: true};
  if (step === 'open') { sel.click(); return {ok: true}; }
  const card = document.getElementById('CARD_SEARCH_GB');
  let opts = [];
  for (let box = sel.parentElement, i = 0; box && i < 3 && !opts.length; box = box.parentElement, i++) {
    if (card && box.contains(card)) break;
    opts = Array.from(box.querySelectorAll('button, a, li')).filter(e => e !== sel && !e.contains(sel) && txt(e) === '전체과제'
      && !e.querySelector('button, a'));
  }
  if (opts.length !== 1) return {ok: false, why: opts.length ? "보기 '전체과제' 가 여럿" : "보기 '전체과제' 가 없음"};
  opts[0].click();
  return {ok: true};
}"""

# 과제정보 프레임(rtask_0008_t00_01) — 숨은 #PRJ_NO 와 '기본정보' · '청구서' 하위 탭 링크가 함께 있는 프레임. 읽기만 한다.
TOOLBAR_JS = r"""() => {
  const txt = e => (e.innerText || e.textContent || '').replace(/\s+/g, ' ').trim();
  const prj = document.getElementById('PRJ_NO');
  const links = Array.from(document.querySelectorAll('a')).map(txt);
  if (!prj || !links.includes('청구서') || !links.includes('기본정보')) return null;
  let shown = true;
  try { const f = window.frameElement; if (f) { const r = f.getBoundingClientRect(); shown = r.width > 0 && r.height > 0; } } catch (e) {}
  return {prj: String(prj.value || ''), shown};
}"""

# 과제정보의 '청구서' 하위 탭 — 글자가 정확히 '청구서' 이고 화면에 보이는 링크가 하나일 때만 누른다.
CLICK_CLAIM_TAB_JS = r"""() => {
  const txt = e => (e.innerText || e.textContent || '').replace(/\s+/g, ' ').trim();
  const shown = Array.from(document.querySelectorAll('a')).filter(a => {
    const r = a.getBoundingClientRect();
    return txt(a) === '청구서' && r.width > 0 && r.height > 0;
  });
  if (shown.length !== 1) return {ok: false, why: shown.length ? "'청구서' 탭이 여럿" : "'청구서' 탭이 보이지 않음"};
  shown[0].click();
  return {ok: true};
}"""

# 과제정보의 '예산' 하위 탭 — 대응자금 과제의 비목 차례를 읽으려고(담당자 2026-10-21 "과제정보-예산에서 확인하고 순서대로 숫자를 붙여주세요").
# '청구서' 탭과 같이 글자가 정확히 '예산' 이고 보이는 링크가 하나일 때만. 그 화면의 [변경신청서작성] · [삭제] · [예산출력] 은 누르지 않는다.
BUDGET_TAB_TEXT = "예산"
CLICK_BUDGET_TAB_JS = r"""() => {
  const txt = e => (e.innerText || e.textContent || '').replace(/\s+/g, ' ').trim();
  const shown = Array.from(document.querySelectorAll('a')).filter(a => {
    const r = a.getBoundingClientRect();
    return txt(a) === '예산' && r.width > 0 && r.height > 0;
  });
  if (shown.length !== 1) return {ok: false, why: shown.length ? "'예산' 탭이 여럿" : "'예산' 탭이 보이지 않음"};
  shown[0].click();
  return {ok: true};
}"""

# 예산 탭의 예산내역 — 머리글에 '비목코드' · '비목명' 이 있는 화면에서, 줄(tr · JGM .jgrid-row)마다 비목코드 꼴(A10110002)인 칸과 그 다음 칸(비목명)을
# 차례대로 읽는다(실측 그림 2026-10-21: 재원 | 비목분류명 | 지급구분 | 비목코드 | 비목명 | 당초예산액 …, 재원 · 비목분류명은 여러 줄을 합친 칸).
# 표 모양(table 인지 JGM 인지)은 아직 구조 저장으로 실측하지 않아 칸 차례에 기대지 않는다. 소계 · 합계 줄은 비목코드가 없어 빠진다. 읽기만 한다.
BUDGET_JS = r"""() => {
  const txt = e => {
    const t = e.getAttribute && e.getAttribute('title');
    return ((t && t.trim()) ? t : (e.innerText || e.textContent || '')).replace(/\s+/g, ' ').trim();
  };
  const flat = (document.body ? (document.body.innerText || document.body.textContent || '') : '').replace(/\s+/g, '');
  if (flat.indexOf('비목코드') < 0 || flat.indexOf('비목명') < 0) return null;
  let shown = true;
  try { const f = window.frameElement; if (f) { const r = f.getBoundingClientRect(); shown = r.width > 0 && r.height > 0; } } catch (e) {}
  const prj = document.getElementById('PRJ_NO');
  const CODE = /^[A-Z]{1,3}[0-9]{5,12}$/;
  const rows = Array.from(document.querySelectorAll('tr, .jgrid-row'))
    .filter(row => row.tagName === 'TR' || !row.parentElement || !row.parentElement.closest('.jgrid-row'));
  const order = row => { const r = row.getAttribute && row.getAttribute('r'); return r !== null && r !== '' && !isNaN(+r) ? +r : null; };
  const items = [], seen = {};
  const jgmCells = row => {
    const all = Array.from(row.querySelectorAll('[class]')).filter(e => Array.from(e.classList).some(c => /^k_/.test(c)));
    return all.filter(e => !all.some(o => o !== e && o.contains(e)));       // 칸 안의 칸은 빼고 바깥 칸만
  };
  rows.forEach((row, at) => {
    const cells = row.tagName === 'TR' ? Array.from(row.cells) : jgmCells(row);
    for (let j = 0; j < cells.length - 1; j++) {
      const code = txt(cells[j]);
      if (!CODE.test(code)) continue;
      let name = '';
      for (let k = j + 1; k < cells.length && !name; k++) name = txt(cells[k]);
      if (!name || CODE.test(name) || !/[가-힣A-Za-z]/.test(name)) break;      // 비목명 대신 금액 · 빈칸이면 이 줄은 읽지 않는다
      const key = code + '|' + name;
      if (!seen[key]) { seen[key] = 1; items.push({code, name, r: order(row), at}); }
      break;
    }
  });
  items.sort((a, b) => (a.r !== null && b.r !== null) ? a.r - b.r : a.at - b.at);
  return {prj: prj ? String(prj.value || '') : null, shown, items: items.map(i => [i.code, i.name])};
}"""


NEW_SHEET_ID = "P10"
# 결의서 목록의 [일반청구] — id 와 글자가 둘 다 맞을 때만 누른다(#P11 카드청구 · #P21 반납요구 같은 이웃 단추와 헷갈리지 않게).
CLICK_NEW_SHEET_JS = r"""() => {
  const b = document.getElementById('P10');
  const t = b ? (b.innerText || b.textContent || '').replace(/\s+/g, ' ').trim() : '';
  if (!b || t !== '일반청구') return {ok: false, why: "결의서 목록의 [일반청구] 를 찾지 못함"};
  b.click();
  return {ok: true};
}"""

CARD_SHEET_ID = "P11"
# 결의서 목록의 [카드청구](담당자 허락 2026-10-20 "네") — [일반청구] 와 같이 id 와 글자가 둘 다 맞을 때만 누른다
CLICK_CARD_SHEET_JS = r"""() => {
  const b = document.getElementById('P11');
  const t = b ? (b.innerText || b.textContent || '').replace(/\s+/g, ' ').trim() : '';
  if (!b || t !== '카드청구') return {ok: false, why: "결의서 목록의 [카드청구] 를 찾지 못함"};
  b.click();
  return {ok: true};
}"""


@dataclass
class Project:
    no: str
    name: str = ""
    start: str = ""          # YYYY-MM-DD
    end: str = ""

    def running(self, today: dt.date | None = None) -> bool:
        """과제기간에 오늘이 드는지 — 담당자 요청(2026-10-19): 설정의 과제 고르기에는 이런 과제만 보인다. 기간을 못 읽었으면 아니라고 본다."""
        today = today or dt.date.today()
        try:
            return dt.date.fromisoformat(self.start) <= today <= dt.date.fromisoformat(self.end)
        except ValueError:
            return False

    def label(self) -> str:
        period = f"{self.start} ~ {self.end}" if self.start and self.end else "기간 모름"
        return f"{self.no}  {self.name}  ({period})" if self.name else f"{self.no}  ({period})"

    def short(self) -> str:
        """과제 고르기 칸 — 과제번호와 과제명(과제기간은 말풍선 label). 과제명을 자르지 않는다 — 칸이 고른 과제명만큼 넓어진다
        (ui/project_box.ProjectBox, 담당자 2026-10-21 "과제명이 잘 안보이네요. 과제명에 따라서 길이가 수정되도록")."""
        return f"{self.no} {self.name}" if self.name else self.no


def _frames(context):
    for page in list(getattr(context, "pages", []) or []):
        for frame in list(getattr(page, "frames", []) or []):
            yield page, frame


def logged_out(context) -> bool:
    """ERP 창이 로그인 화면인지(자동 로그아웃 뒤 · 로그인 전) — 그때는 과제를 못 찾은 까닭을 '로그인하세요' 로 알린다. 읽기만 한다."""
    host = str(settings.ERP_URL).split("://", 1)[-1].split("/", 1)[0].lower()
    for page in list(getattr(context, "pages", []) or []):
        url = str(getattr(page, "url", "") or "")
        frame = getattr(page, "main_frame", None)
        if frame is not None and url.split("://", 1)[-1].split("/", 1)[0].lower() == host \
                and _evaluate(frame, logout.STATE_JS) == "out":
            return True
    return False


def _evaluate(frame, js, *args):
    try:
        return frame.evaluate(js, *args)
    except Exception:  # noqa: BLE001 — 그리는 중 · 바뀌는 중인 프레임
        return None


def read_projects(context) -> list[Project]:
    """메인화면 과제현황의 과제들. 대시보드가 없으면(로그인 전 · 다른 화면) 빈 목록."""
    for _page, frame in _frames(context):
        rows = _evaluate(frame, PROJECTS_JS)
        if rows:
            return [Project(str(r.get("no", "")), str(r.get("name", "")), str(r.get("start", "")), str(r.get("end", "")))
                    for r in rows if r.get("no")]
    return []


def running(projects: list[Project], today: dt.date | None = None) -> list[Project]:
    return [p for p in projects if p.running(today)]


def save_projects(projects: list[Project]) -> None:
    """마지막으로 읽은 과제 목록 — 설정 화면이 과제 고르기 칸에 쓴다(ERP 에 들어가지 않고도). 과제번호 · 과제명 · 기간만 둔다(사람 이름 없음).
    전에 읽어 둔 과제는 남긴다 — 로그인 뒤 보이는 '진행과제' 한 쪽만 다시 읽어도 '전체과제' 에서 모아 둔 끝난 과제의 과제기간이 사라지지 않게
    (2026-10-22, 구매요청(계약) 서류가 과제기간으로 조회 범위를 정한다). 같은 과제는 새로 읽은 것으로(기간이 비었으면 옛 기간을 둔다)."""
    merged: dict[str, Project] = {}
    old = {p.no: p for p in load_projects()[0]}
    for p in projects:
        before = old.get(p.no)
        merged[p.no] = p if (p.start and p.end) or before is None else Project(p.no, p.name or before.name, before.start, before.end)
    for no, p in old.items():
        merged.setdefault(no, p)
    data = {"read_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "projects": [asdict(p) for p in merged.values()]}
    path = settings.projects_path()
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def load_projects() -> tuple[list[Project], str]:
    """(과제들, 읽은 때). 파일이 없거나 깨졌으면 ([], '')."""
    try:
        data = json.loads(settings.projects_path().read_text(encoding="utf-8"))
        rows = data.get("projects") or []
        return [Project(str(r.get("no", "")), str(r.get("name", "")), str(r.get("start", "")), str(r.get("end", "")))
                for r in rows if isinstance(r, dict) and r.get("no")], str(data.get("read_at", ""))
    except (OSError, ValueError, AttributeError):
        return [], ""


def choices(selected: str, today: dt.date | None = None, short: bool = False) -> list[tuple[str, str]]:
    """일반청구 화면의 과제 고르기 칸 — (과제번호, 보이는 글). 과제기간에 오늘이 든 과제만(담당자 요청 2026-10-19), 읽은 목록이 없으면
    기본 과제번호 하나. 지금 고른 번호는 목록에 없어도 남긴다(폴더에 붙은 과제가 칸에서 사라지지 않게). short 면 좁은 칸용 글."""
    projects, _when = load_projects()
    out = [(p.no, p.short() if short else p.label()) for p in running(projects, today)]
    if not out:
        out = [(settings.DEFAULT_PROJECT_NO, settings.DEFAULT_PROJECT_NO)]
    if selected and selected not in {no for no, _ in out}:
        known = {p.no: p for p in projects}
        text = (known[selected].short() if short else known[selected].label()) if selected in known else selected
        out.append((selected, text + (" — 과제기간 아님" if selected in known else "")))
    return out


def label_of(project_no: str) -> str:
    """과제번호의 긴 글(말풍선 · 확인 창). 읽은 목록에 없으면 번호만."""
    for p in load_projects()[0]:
        if p.no == project_no:
            return p.label()
    return project_no


# 작성 화면 · 결의서 목록 · 과제정보 프레임 모두 숨은 #PRJ_NO 에 과제번호가 있다(실측 2026-10-19 2 · 4 · 5번). 읽기만 한다.
PRJ_JS = "() => { const e = document.getElementById('PRJ_NO'); return e ? String(e.value || '') : null; }"
# 위쪽 탭 '메인화면'(틀 프레임의 a.mul_txt) — 다른 과제의 과제정보 · 청구서 탭이 앞에 있어 과제현황이 가려졌을 때만 누른다.
CLICK_MAIN_TAB_JS = r"""() => {
  const txt = e => (e.innerText || e.textContent || '').replace(/\s+/g, ' ').trim();
  const shown = Array.from(document.querySelectorAll('a.mul_txt')).filter(a => {
    const r = a.getBoundingClientRect();
    return txt(a) === '메인화면' && r.width > 0 && r.height > 0;
  });
  if (shown.length !== 1) return {ok: false, why: "위쪽 '메인화면' 탭이 보이지 않음"};
  shown[0].click();
  return {ok: true};
}"""


# 위쪽 탭 '과제정보' — 결의서 목록이 다른 탭(청구서(일반)) 뒤에 가려졌을 때 앞으로. 목록은 가상 스크롤이라 가려진 채로는 끝까지 못 읽는다.
CLICK_PROJECT_TAB_JS = r"""() => {
  const txt = e => (e.innerText || e.textContent || '').replace(/\s+/g, ' ').trim();
  const shown = Array.from(document.querySelectorAll('a.mul_txt')).filter(a => {
    const r = a.getBoundingClientRect();
    return txt(a) === '과제정보' && r.width > 0 && r.height > 0;
  });
  if (shown.length !== 1) return {ok: false, why: "위쪽 '과제정보' 탭이 하나가 아님"};
  shown[0].click();
  return {ok: true};
}"""


def frame_project(frame) -> str:
    """이 프레임의 과제번호(숨은 #PRJ_NO, 숫자만). 없으면 ''."""
    return re.sub(r"\D", "", str(_evaluate(frame, PRJ_JS) or ""))


def list_frame(context, project_no: str = ""):
    """결의서 목록 프레임(erp 의 그리드 확인과 같은 기준). project_no 를 주면 그 과제의 것만. 없으면 None."""
    for _page, frame in _frames(context):
        if _evaluate(frame, erp._GRID_PROBE) is True and (not project_no or frame_project(frame) == project_no):
            return frame
    return None


def _toolbar(context, project_no: str):
    """고른 과제의 과제정보 프레임(보이는 것 먼저). 없으면 None."""
    found = []
    for _page, frame in _frames(context):
        state = _evaluate(frame, TOOLBAR_JS)
        if state and state.get("prj") == project_no:
            found.append((not state.get("shown", True), frame))
    return sorted(found, key=lambda pair: pair[0])[0][1] if found else None


def _wait(check: Callable[[], object], wait: Callable[[float], None], tries: int, step: float = 0.5):
    for _ in range(tries):
        got = check()
        if got:
            return got
        wait(step)
    return check()


def _try_click(context, project_no: str) -> tuple[bool, str]:
    for _page, frame in _frames(context):
        result = _evaluate(frame, CLICK_PROJECT_JS, project_no)
        if result and result.get("ok"):
            return True, ""
        if result and result.get("why") == "과제명 링크가 여럿":
            return False, f"과제현황에 과제 {project_no} 링크가 여럿이라 누르지 않았습니다 — 직접 여세요"
    return False, ""


def _shown_projects(frame) -> frozenset:
    return frozenset(r.get("no") for r in (_evaluate(frame, PROJECTS_JS) or []) if r.get("visible"))


def _dashboard(context):
    """과제현황(과제명 링크)이 보이는 프레임 — 쪽을 넘기면 프레임이 다시 열릴 수 있어 그때마다 새로 찾는다."""
    return next((f for _p, f in _frames(context) if _shown_projects(f)), None)


def _now(context) -> frozenset:
    frame = _dashboard(context)
    return _shown_projects(frame) if frame is not None else frozenset()


def _mouse_click(frame, which: str) -> str:
    """쪽 단추를 브라우저 마우스로 누른다 — 화면 스크립트의 click() 으로는 쪽이 안 바뀌는 단추가 있다(2026-10-21 실제 ERP, 까닭 미확인).
    누른 결과 한 마디('' = 누름). 쪽 단추 둘 밖은 누르지 않는다. 오류 글은 화면 글자가 섞일 수 있어 기록에 그대로 남기지 않는다."""
    if which not in PAGE_BUTTONS:
        return "쪽 단추가 아님"
    click = getattr(frame, "click", None)
    if click is None:
        return "마우스로 누를 수 없음"
    try:
        click(f"#{which}", timeout=3000)
        return ""
    except Exception as error:  # noqa: BLE001
        text = str(error)
        for word, said in (("intercepts pointer", "다른 것에 가려짐"), ("not visible", "보이지 않음"), ("not enabled", "막힘"),
                           ("disabled", "막힘"), ("Timeout", "시간 초과")):
            if word in text:
                return said
        return error.__class__.__name__


NO_TURN = "눌러도 쪽이 바뀌지 않음"


def _turn(context, which: str, before: frozenset, wait: Callable[[float], None], say: Callable[[str], None],
          how: dict) -> tuple[frozenset, str]:
    """쪽 번호 · 쪽 단추 하나를 눌러 과제현황의 보이는 과제가 바뀌기를 기다린다 — (바뀐 뒤 보이는 과제, 못 넘긴 까닭).
    쪽 단추는 화면 스크립트로 누르고 6초 안에 안 바뀌면 같은 단추를 마우스로 한 번 더 누른다. 통한 방법은 how['by'] 에 남겨 다음 쪽부터
    그것만 쓴다(마지막 쪽에서도 단추가 막히지 않으면 두 번씩 기다리게 되므로). 쪽 번호는 화면 스크립트로만."""
    frame = _dashboard(context)
    if frame is None:
        return frozenset(), "과제현황이 보이지 않음"
    button = which in PAGE_BUTTONS
    label = f"#{which}" if button else f"쪽 {which}"

    def changed():
        now = _now(context)
        return now if now and now != before else None

    if button:
        state = _evaluate(frame, PAGE_STATE_JS, which)
        if state:
            return frozenset(), state                   # 단추 없음 · 숨음 · 막힘(끝 쪽)
    if how.get("by") != "mouse" or not button:
        result = _evaluate(frame, CLICK_PAGE_JS, which)
        if result is not None and not result.get("ok"):
            return frozenset(), result.get("why", "")
        after = _wait(changed, wait, tries=12)
        if after:
            if button:
                how["by"] = "script"
            say(f"과제현황 쪽 넘김({label}) → 보이는 과제 {len(after)}개")
            return after, ""
        if not button:
            say(f"과제현황 {label} 를 눌러도 쪽이 바뀌지 않았습니다")
            return frozenset(), NO_TURN
        if how.get("by") == "script":
            return frozenset(), "끝 쪽"                  # 앞 쪽은 스크립트로 넘어갔다 — 더 넘길 쪽이 없다
    trouble = _mouse_click(frame, which)
    if trouble:
        say(f"과제현황 쪽 단추({label})를 눌러도 쪽이 바뀌지 않았습니다 — 마우스로 다시 누르지 못함({trouble})")
        return frozenset(), NO_TURN
    after = _wait(changed, wait, tries=12)
    if after:
        how["by"] = "mouse"
        say(f"과제현황 쪽 넘김({label}, 마우스) → 보이는 과제 {len(after)}개")
        return after, ""
    if how.get("by") == "mouse":
        return frozenset(), "끝 쪽"
    say(f"과제현황 쪽 단추({label})를 화면 스크립트 · 마우스로 눌러도 쪽이 바뀌지 않았습니다")
    return frozenset(), NO_TURN


def _pager(context) -> dict:
    frame = _dashboard(context)
    return (_evaluate(frame, PAGER_JS) or {}) if frame is not None else {}


def _page_through(context, project_no: str, wait: Callable[[float], None], say: Callable[[str], None]) -> tuple[bool, list[str], int]:
    """지금 거르기의 과제현황 쪽을 차례로 보며 그 과제를 찾는다 — (찾았는지 — 그 쪽이 보인 채, 못 넘긴 까닭들, 본 쪽 수).
    쪽 번호가 있으면 번호를 작은 것부터(실측 모양), 번호 없이 단추만 있으면 다음 쪽으로 끝까지 · 앞 쪽으로 끝까지."""
    frame = _dashboard(context)
    if frame is None:
        return False, [], 0
    info = _evaluate(frame, PAGER_JS) or {}
    hidden = any(r.get("no") == project_no and not r.get("visible") for r in (_evaluate(frame, PROJECTS_JS) or []))
    nums = [str(n) for n in info.get("nums") or []]
    say(f"과제현황에 과제 {project_no} 가 안 보여 쪽을 봅니다 — 거르기 '{info.get('filter', '')}' · 쪽 번호 {' '.join(nums) or '없음'}"
        f" (지금 {info.get('now') or '?'}) · 다음 쪽 단추 {info.get('next', '?')} · 이전 쪽 단추 {info.get('prev', '?')}"
        f" · 쪽 표시 '{info.get('pages', '')}' · 과제명 링크 보임 {info.get('shown', '?')}/{info.get('links', '?')}"
        + (" · 이 과제의 링크는 화면에 있지만 숨어 있음" if hidden else ""))
    seen = {_shown_projects(frame)}
    how: dict = {}
    reasons: list[str] = []
    if nums or info.get("now"):
        # 쪽 번호가 있는 모양 — 지금 쪽만 있고 번호 링크가 없으면 한 쪽뿐이다(실측: 진행과제 8과제는 '<strong>1</strong>' 하나)
        visited = {str(info.get("now") or "")}
        for _ in range(MAX_PAGES):
            todo = sorted((n for n in (_pager(context).get("nums") or []) if str(n) not in visited), key=int)
            if not todo:
                break
            number = str(todo[0])
            visited.add(number)
            after, why = _turn(context, number, _now(context), wait, say, how)
            if not after:
                reasons.append(f"쪽 {number}: {why}")
                continue
            if project_no in after:
                return True, [], len(seen) + 1
            seen.add(after)
        if not reasons:
            return False, [], len(seen)
    # 쪽 번호가 없거나 번호로 못 넘겼으면 다음 · 이전 단추.
    # 쪽 표시가 '지금 / 전체' 꼴이면 갈 수 없는 쪽으로는 누르지 않는다 — 마지막 쪽에서도 [다음] 이 막히지 않으면 12초를 헛기다린다
    where = re.fullmatch(r"(\d+) ?/ ?(\d+)", str(info.get("pages", "")))
    skip = set()
    if where and 1 <= int(where.group(1)) <= int(where.group(2)):
        if int(where.group(1)) == int(where.group(2)):
            skip.add("nextBtn")
        if int(where.group(1)) == 1:
            skip.add("prevBtn")
    for which in (b for b in PAGE_BUTTONS if b not in skip):
        for _ in range(MAX_PAGES):
            after, why = _turn(context, which, _now(context), wait, say, how)
            if not after:
                if why == NO_TURN:
                    reasons.append(f"#{which}: {why}")
                break                                    # 끝 쪽 · 단추 없음(한 쪽뿐) · 못 넘김
            if project_no in after:
                return True, [], len(seen) + 1
            if after in seen:
                break                                    # 본 쪽으로 돌아왔다
            seen.add(after)
    return False, (reasons if len(seen) == 1 else []), len(seen)


def _show_all(context, wait: Callable[[float], None], say: Callable[[str], None]) -> tuple[bool, str]:
    """과제현황 거르기를 '전체과제' 로 바꾼다 — (바꿨는지, 못 바꾼 까닭). 이미 '전체과제' 면 (False, '')."""
    info = _pager(context)
    if not info or info.get("filter") == ALL_PROJECTS:
        return False, ""
    frame = _dashboard(context)
    before = (_now(context), info.get("now"), tuple(info.get("nums") or ()))
    say(f"과제현황 거르기를 '{info.get('filter') or '?'}' 에서 '{ALL_PROJECTS}' 로 바꿉니다 (끝난 과제는 '{ALL_PROJECTS}' 에만 있다)")
    opened = _evaluate(frame, ALL_PROJECTS_JS, "open") or {}
    if not opened.get("ok"):
        return False, opened.get("why", "거르기 칸을 읽지 못함")
    wait(0.5)
    picked = _evaluate(_dashboard(context) or frame, ALL_PROJECTS_JS, "pick") or {}
    if not picked.get("ok"):
        return False, picked.get("why", "보기를 읽지 못함")

    def redrawn():
        now = _pager(context)
        if now.get("filter") != ALL_PROJECTS:
            return None
        shown = _now(context)
        return shown if shown and (shown, now.get("now"), tuple(now.get("nums") or ())) != before else None

    after = _wait(redrawn, wait, tries=12)
    if not after:
        if _pager(context).get("filter") != ALL_PROJECTS:
            return False, f"'{ALL_PROJECTS}' 를 눌러도 거르기가 바뀌지 않음"
        searched = _evaluate(_dashboard(context) or frame, ALL_PROJECTS_JS, "search") or {}
        say(f"거르기는 '{ALL_PROJECTS}' 인데 목록이 그대로라 과제현황 [검색] 을 누릅니다"
            + ("" if searched.get("ok") else f" — 못 누름({searched.get('why', '?')})"))
        after = _wait(redrawn, wait, tries=12)
    now = _pager(context)
    say(f"과제현황 거르기 '{now.get('filter', '?')}' → 보이는 과제 {len(_now(context))}개 · 쪽 번호 {' '.join(map(str, now.get('nums') or [])) or '없음'}"
        f" (지금 {now.get('now') or '?'})" + ("" if after else " — 목록이 다시 그려졌는지는 모름"))
    return True, ""


def _page_to(context, project_no: str, wait: Callable[[float], None], say: Callable[[str], None] = lambda _m: None) -> tuple[bool, str]:
    """과제현황의 다른 쪽에서 그 과제를 찾는다 — 지금 거르기의 쪽을 다 보고, 없으면 거르기를 '전체과제' 로 바꿔 다시 본다
    (담당자 2026-10-21 "전체과제로 설정하고 2페이지를 눌러야함"). (찾았는지 — 그 쪽이 보인 채, 못 찾은 까닭)."""
    found, reasons, pages = _page_through(context, project_no, wait, say)
    if found:
        return True, ""
    switched, trouble = _show_all(context, wait, say)
    if trouble:
        return False, (f"과제현황 거르기를 '{ALL_PROJECTS}' 로 바꾸지 못했습니다({trouble}) — 브라우저에서 과제현황을 '{ALL_PROJECTS}' 로 바꾼 뒤 다시 누르세요"
                       + (" · " + " · ".join(reasons) if reasons else ""))
    if switched:
        if project_no in _now(context):
            return True, ""
        found, reasons, pages = _page_through(context, project_no, wait, say)
        if found:
            return True, ""
    if reasons:
        return False, "과제현황의 쪽을 넘기지 못했습니다(" + " · ".join(reasons) + ")"
    if pages > 1 or switched:
        return False, (f"과제현황 '{_pager(context).get('filter') or ALL_PROJECTS}' 의 쪽 {pages}개를 다 봤지만 없습니다 — "
                       "ERP 과제현황에 없는 과제면 직접 과제정보 → 청구서를 여세요")
    return False, ""


def _show_dashboard(context, wait: Callable[[float], None]) -> str:
    """과제현황이 보이게 — 다른 위쪽 탭이 앞이면 '메인화면' 탭을 누른다. 보이면 '', 아니면 까닭."""
    if _dashboard(context) is not None:
        return ""
    tab = next((r for r in (_evaluate(f, CLICK_MAIN_TAB_JS) for _p, f in _frames(context)) if r and r.get("ok")), None)
    if tab is not None and _wait(lambda: _dashboard(context) is not None, wait, tries=20):
        return ""
    if logged_out(context):
        return "ERP 에 로그인돼 있지 않습니다 — 브라우저에서 로그인한 뒤 다시 하세요"
    return "메인화면 과제현황이 보이지 않습니다 — 브라우저에서 '메인화면' 탭을 띄운 뒤 다시 하세요"


def collect_all_projects(context, log: Callable[[str], None], wait: Callable[[float], None]) -> tuple[list[Project], str]:
    """과제현황을 '전체과제' 로 바꾸고 모든 쪽을 넘기며 과제번호 · 과제명 · 과제기간을 모은다 — (과제들, 못 한 까닭).
    끝난 과제는 기본 거르기 '진행과제' 에 없어 과제기간을 몰랐다(2026-10-22 실제 — 구매요청(계약) 서류 7과제가 '과제기간을 몰라' 로 빠짐,
    담당자 "메인화면에 과제기간이 있잖아 · 전체과제로 설정하면 이전 과제도 다 보이는데"). 누르는 것은 청구서 찾기와 같다(메인화면 탭 · 거르기 · 쪽)."""
    trouble = _show_dashboard(context, wait)
    if trouble:
        return [], trouble
    _switched, trouble = _show_all(context, wait, log)
    if trouble:
        return [], f"과제현황 거르기를 '{ALL_PROJECTS}' 로 바꾸지 못했습니다({trouble}) — 브라우저에서 과제현황을 '{ALL_PROJECTS}' 로 바꾼 뒤 다시 하세요"
    found: dict[str, Project] = {}

    def grab():
        for p in read_projects(context):
            if p.no not in found or (p.start and p.end and not (found[p.no].start and found[p.no].end)):
                found[p.no] = p

    grab()
    info = _pager(context)
    how: dict = {}
    pages = 1
    if info.get("nums") or info.get("now"):
        visited = {str(info.get("now") or "")}
        for _ in range(MAX_PAGES):
            todo = sorted((n for n in (_pager(context).get("nums") or []) if str(n) not in visited), key=int)
            if not todo:
                break
            number = str(todo[0])
            visited.add(number)
            after, why = _turn(context, number, _now(context), wait, log, how)
            if not after:
                log(f"과제현황 쪽 {number} 을 넘기지 못했습니다({why})")
                continue
            pages += 1
            grab()
    else:
        seen = {_now(context)}
        for _ in range(MAX_PAGES):
            after, _why = _turn(context, "nextBtn", _now(context), wait, log, how)
            if not after or after in seen:
                break
            seen.add(after)
            pages += 1
            grab()
    dated = sum(1 for p in found.values() if p.start and p.end)
    log(f"과제현황 '{_pager(context).get('filter') or ALL_PROJECTS}' {pages}쪽에서 과제 {len(found)}개를 읽었습니다 (과제기간 있는 과제 {dated}개)")
    return list(found.values()), ""


def _click_project(context, project_no: str, wait: Callable[[float], None] | None = None,
                   log: Callable[[str], None] | None = None) -> tuple[bool, str]:
    """과제현황의 과제명 링크를 누른다. 과제현황이 가려져 있으면(다른 과제의 과제정보 · 청구서 탭이 앞) '메인화면' 탭을 먼저 누르고,
    wait 를 주면 그 과제가 다른 쪽에 있을 때 쪽을 넘겨 찾는다."""
    paged = ""
    for attempt in range(2):
        ok, why = _try_click(context, project_no)
        if ok or why:
            return ok, why
        shown = any(_shown_projects(f) for _p, f in _frames(context))
        if not shown and attempt == 0:
            tab = next((r for r in (_evaluate(f, CLICK_MAIN_TAB_JS) for _p, f in _frames(context)) if r and r.get("ok")), None)
            if tab is None:
                break
            if wait is not None:
                _wait(lambda: any(_shown_projects(f) for _p, f in _frames(context)), wait, tries=20)
            continue
        if shown and wait is not None:
            found, paged = _page_to(context, project_no, wait, log or (lambda _m: None))
            if found:
                ok, why = _try_click(context, project_no)
                if ok or why:
                    return ok, why
        break
    if logged_out(context):
        return False, "ERP 에 로그인돼 있지 않습니다 — 브라우저에서 로그인한 뒤 다시 하세요 (오래 쓰지 않으면 앱이 자동 로그아웃합니다)"
    if paged:
        return False, f"메인화면 과제현황에서 과제 {project_no} 를 찾지 못했습니다 — {paged}"
    return False, (f"메인화면 과제현황에 과제 {project_no} 가 보이지 않습니다 — 과제현황 목록(진행과제 · 전체과제)에 없거나 다른 화면이 떠 있으면 "
                   "직접 과제정보 → 청구서를 여세요")


def go_to_claims(context, project_no: str, log: Callable[[str], None], wait: Callable[[float], None]) -> tuple[bool, str]:
    """그 과제의 결의서내역 목록까지 간다. (됐는지, 글). 그 과제의 목록이 이미 있으면 아무것도 누르지 않는다.
    폴더마다 과제가 다를 수 있어(담당자 2026-10-19 — 일반청구에서 폴더를 넣을 때 과제를 고른다) 목록의 #PRJ_NO 로 그 과제 것인지 본다."""
    project_no = re.sub(r"\D", "", str(project_no or ""))      # 메모장으로 고친 설정에 빈칸 · 글자가 섞여도 JS 정규식이 깨지지 않게
    if not project_no:
        return False, "과제번호가 없습니다 — 일반청구 화면에서 폴더의 과제를 고르세요"
    if list_frame(context, project_no) is not None:
        return True, f"과제 {project_no} 의 결의서내역 목록이 이미 떠 있습니다"
    toolbar = _toolbar(context, project_no)
    if toolbar is None:
        ok, why = _click_project(context, project_no, wait, log)
        if not ok:
            return False, why
        log(f"과제 {project_no} 를 엽니다 (과제현황의 과제명)")
        toolbar = _wait(lambda: _toolbar(context, project_no), wait, tries=30)
        if toolbar is None:
            return False, f"과제 {project_no} 의 과제정보 화면이 뜨지 않았습니다 — 직접 청구서 탭을 누르세요"
    result = _evaluate(toolbar, CLICK_CLAIM_TAB_JS) or {}
    if not result.get("ok"):
        return False, f"과제정보의 청구서 탭을 누르지 못했습니다({result.get('why', '화면을 읽지 못함')}) — 직접 누르세요"
    log("과제정보 → 청구서 탭을 눌렀습니다")
    if _wait(lambda: list_frame(context, project_no) is not None, wait, tries=40):
        return True, f"과제 {project_no} 의 결의서내역 목록까지 왔습니다"
    return False, "청구서 탭을 눌렀지만 결의서내역 목록이 보이지 않습니다 — 직접 결의서내역을 띄우세요"


def _shown(frame) -> bool:
    from .claims.form import FRAME_VISIBLE_JS
    return _evaluate(frame, FRAME_VISIBLE_JS) is True


def show_list(context, project_no: str, log: Callable[[str], None], wait: Callable[[float], None]):
    """그 과제의 결의서 목록을 화면 앞으로 — (프레임 또는 None, 못 한 까닭). 목록이 다른 탭 뒤에 있으면 위쪽 '과제정보' 탭을 누르고,
    없으면 과제현황에서 연다(go_to_claims)."""
    project_no = re.sub(r"\D", "", str(project_no or ""))
    frame = list_frame(context, project_no)
    if frame is not None and _shown(frame):
        return frame, ""
    if frame is not None:
        # 과제정보는 앞인데 다른 하위 탭(예산)이 떠 있으면 '청구서' 하위 탭을, 다른 위쪽 탭이 앞이면 '과제정보' 탭을 누른다
        frame = _claim_tab_again(context, project_no, log, wait)
        if frame is not None:
            return frame, ""
        if any((r or {}).get("ok") for r in (_evaluate(f, CLICK_PROJECT_TAB_JS) for _p, f in _frames(context))):
            log("결의서 목록을 보려고 위쪽 '과제정보' 탭을 앞으로 가져옵니다")
            frame = _wait(lambda: next((f for f in [list_frame(context, project_no)] if f is not None and _shown(f)), None), wait, tries=20)
            if frame is None:
                frame = _claim_tab_again(context, project_no, log, wait)
            if frame is not None:
                return frame, ""
    ok, why = go_to_claims(context, project_no, log, wait)
    frame = list_frame(context, project_no) if ok else None
    if frame is not None and _shown(frame):
        return frame, ""
    # go_to_claims 가 '목록이 이미 떠 있습니다' 로 끝났는데 보이지 않으면 — 다른 탭 뒤에 있고 '과제정보' 탭을 누르지 못한 것이다
    return None, ("결의서 목록이 다른 탭 뒤에 있는데 위쪽 '과제정보' 탭을 누르지 못했습니다" if ok else why) or "결의서 목록이 화면에 보이지 않습니다"


def _claim_tab_again(context, project_no: str, log: Callable[[str], None], wait: Callable[[float], None]):
    """과제정보가 앞에 있는데 결의서 목록이 다른 하위 탭(예산) 뒤에 숨었으면 '청구서' 하위 탭을 다시 누른다 — 보이는 목록 프레임 또는 None."""
    toolbar = _toolbar(context, project_no)
    if toolbar is None or not (_evaluate(toolbar, TOOLBAR_JS) or {}).get("shown", True):
        return None
    if not (_evaluate(toolbar, CLICK_CLAIM_TAB_JS) or {}).get("ok"):
        return None
    log("과제정보 → 청구서 탭을 다시 눌렀습니다")
    return _wait(lambda: next((f for f in [list_frame(context, project_no)] if f is not None and _shown(f)), None), wait, tries=40)


def _budget_now(context, project_no: str) -> list:
    """지금 보이는 예산내역의 비목([[비목코드, 비목명], …]) — 그 과제의 화면(숨은 #PRJ_NO 가 같거나, 없으면 보이는 화면)만."""
    for _page, frame in _frames(context):
        got = _evaluate(frame, BUDGET_JS)
        if not got or not got.get("items") or not got.get("shown", True):
            continue
        prj = re.sub(r"\D", "", str(got.get("prj") or ""))
        if got.get("prj") is None or prj == project_no:
            return [[str(c), str(n)] for c, n in got["items"]]
    return []


def read_budget(context, project_no: str, log: Callable[[str], None], wait: Callable[[float], None]) -> tuple[list, str]:
    """그 과제의 과제정보 → 예산 탭의 비목을 차례대로 — ([[비목코드, 비목명], …], 못 읽은 까닭). 대응자금 과제의 비목 번호를 붙이려고
    (담당자 2026-10-21). 결의서 목록까지 간 뒤(show_list) '예산' 하위 탭을 누르고, 읽은 뒤에는 '청구서' 탭을 다시 눌러 목록을 앞에 둔다.
    누르는 것은 '예산' · '청구서' 하위 탭(과 show_list 의 화면 이동)뿐이다."""
    project_no = re.sub(r"\D", "", str(project_no or ""))
    frame, why = show_list(context, project_no, log, wait)
    toolbar = _toolbar(context, project_no) if frame is not None else None
    if toolbar is None:
        return [], why or f"과제 {project_no} 의 과제정보 화면이 보이지 않음"
    result = _evaluate(toolbar, CLICK_BUDGET_TAB_JS) or {}
    if not result.get("ok"):
        return [], f"과제정보의 예산 탭을 누르지 못함({result.get('why', '화면을 읽지 못함')})"
    log("과제정보 → 예산 탭을 눌렀습니다 (비목 차례 읽기)")
    last: list = []
    budget: list = []
    for _ in range(40):              # 예산내역이 그려질 때까지 — 같은 것을 두 번 연달아 읽으면 다 그려진 것으로 본다
        now = _budget_now(context, project_no)
        if now and now == last:
            budget = now
            break
        last = now
        wait(0.5)
    else:
        budget = last
    # 못 읽었으면 머리글은 보였는지 — 표 모양이 달라 줄을 못 읽은 것인지, 예산내역 화면이 안 뜬 것인지(다음 실측의 실마리)
    header = not budget and any(_evaluate(f, BUDGET_JS) is not None for _p, f in _frames(context))
    if _claim_tab_again(context, project_no, log, wait) is None:
        log("⚠ 예산 탭을 읽은 뒤 청구서 탭으로 돌아오지 못했습니다 — 받을 때 앱이 다시 띄웁니다")
    if not budget:
        return [], ("예산 탭의 예산내역 머리글(비목코드 · 비목명)은 보이는데 비목 줄을 읽지 못함" if header
                    else "예산 탭에 예산내역(비목코드 · 비목명)이 보이지 않음")
    return budget, ""


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def existing_claims(context, project_no: str, summary: str, log: Callable[[str], None], wait: Callable[[float], None],
                    move: bool = True):
    """그 과제의 결의서내역에서 대표적요가 summary 와 같은 청구서들 — ([행], 읽은 줄 수, 까닭). 목록을 못 읽으면 (None, 0, 까닭).
    담당자 요청(2026-10-19): 앱에 넣은 이력보다 실제 ERP 내역에 같은 것이 있는지가 먼저다. 읽기만 한다(가상 스크롤을 내리기만).
    move=False 면 화면을 옮기지 않는다 — 목록이 이미 앞에 있을 때만 읽는다(새 청구서를 앱이 띄우지 않을 때 사람이 띄운 작성 화면을 가리지 않게)."""
    if move:
        frame, why = show_list(context, project_no, log, wait)
    else:
        frame = list_frame(context, re.sub(r"\D", "", str(project_no or "")))
        frame, why = (frame, "") if frame is not None and _shown(frame) else (None, "결의서 목록이 화면 앞에 없음")
    if frame is None:
        return None, 0, why
    _wait(lambda: (_evaluate(frame, erp.GRID_ROWS_JS) or 0) > 0, wait, tries=10)     # 목록이 그려질 때까지(빈 과제면 ~5초 뒤 0줄)
    rows = erp.collect_all(frame)
    want = _squash(summary)
    return [r for r in rows if want and _squash(r.get("cont", "")) == want], len(rows), ""


def _sheet_state(frame) -> dict:
    from .claims import form
    try:
        state = form.read_state(frame, ["REQ_CNT", "APPR_DIV_CD", "REQ_SEQ_NO", "REQ_AMT", "REQ_PTCL", "RCV_NM"])
    except Exception:  # noqa: BLE001 — 다시 열리는 중
        return {}
    return {key: str((state.get(key) or {}).get("value", "") or "").strip() for key in state}


def typed_fields(state: dict) -> list[str]:
    """작성 화면에 저장하지 않은 입력이 남은 칸 — 새 청구서를 띄우면 날아간다."""
    return [label for key, label in (("REQ_AMT", "청구액"), ("REQ_PTCL", "적요"), ("RCV_NM", "입금처"))
            if state.get(key) and state.get(key) not in ("0",)]


def open_new_sheet(context, log: Callable[[str], None], wait: Callable[[float], None], project_no: str = "",
                   replace_empty: bool = False):
    """결의서 목록의 [일반청구](#P10)로 새 일반청구 작성 화면을 띄운다. (됐는지, 글, 새 작성 프레임 또는 None).
    project_no 를 주면 그 과제의 결의서 목록에서 누르고, 새 작성 화면이 그 과제 것인지 본다.

    지금 작성 화면이 있으면 **저장된 청구서이거나 다른 과제의 것이고, 입력 칸(청구액 · 적요 · 입금처)이 비었을 때만** 누른다 — 같은 탭 자리를
    새 화면이 차지하므로 저장 전 입력은 날아간다. 같은 과제의 저장 전(결의번호 없음) 빈 화면은 이미 새 청구서라 누르지 않는다 —
    replace_empty 면(결의서 목록을 읽느라 그 화면이 뒤로 갔을 때) 빈 화면이니 새로 띄워 앞으로 가져온다."""
    from .claims import form
    project_no = re.sub(r"\D", "", str(project_no or ""))
    _page, current = form.find_form(context)
    before = _sheet_state(current) if current is not None else {}
    if current is not None:
        other = bool(project_no) and frame_project(current) not in ("", project_no)
        if not other and not replace_empty and not (before.get("REQ_CNT") or before.get("APPR_DIV_CD") == "40"):
            return False, "작성 화면이 아직 저장 전인 청구서입니다 — 새로 띄우지 않았습니다", None
        typed = typed_fields(before)
        if typed:
            return False, f"작성 화면에 저장하지 않은 입력({' · '.join(typed)})이 있어 새 청구서를 띄우지 않았습니다", None
    grid = list_frame(context, project_no)
    if grid is None:
        return False, (f"과제 {project_no} 의 " if project_no else "") + "결의서 목록(과제정보 → 청구서)이 열려 있지 않아 새 청구서를 띄우지 못했습니다", None
    result = _evaluate(grid, CLICK_NEW_SHEET_JS) or {}
    if not result.get("ok"):
        return False, str(result.get("why") or "결의서 목록을 읽지 못했습니다"), None
    log("결의서 목록의 [일반청구] 로 새 청구서를 띄웁니다" + (f" — 과제 {project_no}" if project_no else "")
        + (f" (앞 청구서 결의번호 {before.get('REQ_CNT')})" if before.get("REQ_CNT") else ""))

    def fresh():
        _p, frame = form.find_form(context)
        if frame is None:
            return None
        now = _sheet_state(frame)
        new = now and not now.get("REQ_CNT") and now.get("APPR_DIV_CD") != "40"
        mine = not project_no or frame_project(frame) in ("", project_no)
        return frame if new and mine and now.get("REQ_SEQ_NO") != before.get("REQ_SEQ_NO") else None

    frame = _wait(fresh, wait, tries=30)
    if frame is None:
        return False, "[일반청구] 를 눌렀지만 새 작성 화면이 뜨지 않았습니다", None
    log("✓ 새 청구서 작성 화면이 떴습니다")
    return True, "새 청구서", frame


def typed_card_fields(state: dict) -> list[str]:
    """카드청구 작성 화면에 저장하지 않은 입력 — 결제 건을 고르면 청구액이 들어온다. 입금처는 늘 숨은 '카드청구' 라 보지 않는다."""
    return [label for key, label in (("REQ_AMT", "청구액"), ("REQ_PTCL", "청구내역")) if state.get(key) and state.get(key) not in ("0",)]


def open_card_sheet(context, log: Callable[[str], None], wait: Callable[[float], None], project_no: str = "",
                    replace_empty: bool = False):
    """결의서 목록의 [카드청구](#P11)로 새 카드청구 작성 화면을 띄운다(담당자 허락 2026-10-20). (됐는지, 글, 새 카드 프레임 또는 None).

    일반청구 · 카드청구 작성 화면은 위쪽 탭 한 자리를 같이 쓴다(14절 — [카드청구] 를 누르면 일반청구 탭이 '청구서(카드)' 로 바뀐다). 그래서 지금 떠 있는
    작성 화면(일반이든 카드든)에 **저장하지 않은 입력이 있으면 누르지 않는다**. 같은 과제의 저장 전 빈 카드 화면이면 이미 새 것이라 누르지 않는다 —
    replace_empty 면(결의서 목록을 읽느라 그 화면이 뒤로 갔을 때) 새로 띄워 앞으로 가져온다."""
    from .claims import card_erp, form
    project_no = re.sub(r"\D", "", str(project_no or ""))
    _page, current = card_erp.find_card_form(context)
    before = _sheet_state(current) if current is not None else {}
    if current is not None:
        other = bool(project_no) and frame_project(current) not in ("", project_no)
        fresh_now = not (before.get("REQ_CNT") or before.get("APPR_DIV_CD") == "40")
        if not other and fresh_now and not replace_empty:
            return False, "카드청구 화면이 아직 저장 전인 청구서입니다 — 새로 띄우지 않았습니다", None
        typed = typed_card_fields(before)
        if typed:
            return False, f"카드청구 화면에 저장하지 않은 입력({' · '.join(typed)})이 있어 새 카드청구 화면을 띄우지 않았습니다", None
    _gpage, general = form.find_form(context)
    if general is not None:
        typed = typed_fields(_sheet_state(general))
        if typed:
            return False, f"일반청구 작성 화면에 저장하지 않은 입력({' · '.join(typed)})이 있어 [카드청구] 를 누르지 않았습니다(같은 탭 자리)", None
    grid = list_frame(context, project_no)
    if grid is None:
        return False, (f"과제 {project_no} 의 " if project_no else "") + "결의서 목록(과제정보 → 청구서)이 열려 있지 않아 카드청구 화면을 띄우지 못했습니다", None
    result = _evaluate(grid, CLICK_CARD_SHEET_JS) or {}
    if not result.get("ok"):
        return False, str(result.get("why") or "결의서 목록을 읽지 못했습니다"), None
    log("결의서 목록의 [카드청구] 로 새 카드청구 화면을 띄웁니다" + (f" — 과제 {project_no}" if project_no else "")
        + (f" (앞 청구서 결의번호 {before.get('REQ_CNT')})" if before.get("REQ_CNT") else ""))

    def fresh():
        _p, frame = card_erp.find_card_form(context)
        if frame is None:
            return None
        now = _sheet_state(frame)
        new = now and not now.get("REQ_CNT") and now.get("APPR_DIV_CD") != "40"
        mine = not project_no or frame_project(frame) in ("", project_no)
        return frame if new and mine and now.get("REQ_SEQ_NO") != before.get("REQ_SEQ_NO") else None

    frame = _wait(fresh, wait, tries=30)
    if frame is None:
        return False, "[카드청구] 를 눌렀지만 새 카드청구 화면이 뜨지 않았습니다", None
    log("✓ 새 카드청구 화면이 떴습니다")
    return True, "새 카드청구서", frame
