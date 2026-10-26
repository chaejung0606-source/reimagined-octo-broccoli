"""진단 모드 — ERP 의 아무 화면이나 띄운 상태에서 열린 창·프레임과 입력 요소를 글로 남긴다.

새 화면(일반청구 · 카드청구 작성)을 자동화하기 전에 **실측**하는 도구다. Claude 는 ERP 에 들어갈 수
없으므로(로그인은 사람), 담당자가 원하는 화면을 띄우고 [화면 구조 저장] 을 누르면 이 파일이
~/.claim-downloader/_화면구조.txt 로 남고, 그것을 받아 CLAUDE.md 에 화면 구조 절을 쓴다.

**읽기만 한다.** 아무것도 누르거나 값을 넣지 않는다 — tests/test_safety.py 가 이 JS 에 click · submit ·
값 대입 · 이벤트 발생이 없는지 본다. 비밀번호 칸의 값은 기록하지 않고(값을 읽는 칸 종류를 허용 목록으로 둔다), 다른 값도 40자에서 자른다.
결과 파일은 .gitignore 와 배포 zip(make_bundle.NEVER_PACK_NAMES)에서 제외된다 — 계좌번호 같은 값이
들어 있을 수 있다. 담당자에게는 **빈 작성 화면**에서 돌리라고 안내한다.

목록(그리드)도 적는다(2026-10-13 입금처 팝업 실측 뒤 추가) — 입력 요소만 적으면 검색 결과 목록의 열과 행을 고르는
방법을 알 수 없어서다. JGM 그리드(`.jgrid-row` · `k_열이름` 셀)와 머리글(th)이 있는 표, IBSheet 표(`div.SheetMain`, 구매·자산 메뉴 — DOM 줄과 함께
IBSheet 객체의 Get… 함수로 열 SaveName · 앞 줄도)의 열 이름 · 행 수 · 첫 행 값을 적되, 첫 행 값에서 6자리 이상 숫자(계좌번호 · 사업자번호)는 가린다.
그림(`<img>`)은 크거나 서버 파일을 가리키는 것만 주소 · 크기로 적는다(2026-10-22 물품내역팝업의 물품 사진 주소를 보려고).

Playwright 를 들여오지 않는다(브라우저를 띄우는 곳은 session.py 하나). 프레임 객체의 evaluate 만 쓴다.
"""
from __future__ import annotations

import datetime as dt
import re
import shutil
import time
from collections.abc import Callable
from pathlib import Path

# 프레임 하나의 입력 요소. 값은 읽기만 한다(e.value 읽기 · 선택된 option 글자).
_PROBE_JS = r"""() => {
  const txt = e => (e.innerText || e.textContent || '').replace(/\s+/g, ' ').trim();
  const esc = s => (window.CSS && CSS.escape) ? CSS.escape(s) : s.replace(/([^\w-])/g, '\\$1');
  const labelFor = e => {
    if (e.id) { const l = document.querySelector('label[for="' + esc(e.id) + '"]'); if (l && txt(l)) return txt(l); }
    const a = e.getAttribute('aria-label') || e.getAttribute('title') || e.getAttribute('placeholder');
    if (a) return a;
    const lab = e.closest('label'); if (lab && txt(lab)) return txt(lab);
    const cell = e.closest('td,th');
    if (cell) {
      let p = cell.previousElementSibling;
      while (p && !txt(p)) p = p.previousElementSibling;
      if (p) return txt(p);
      const tr = cell.parentElement, table = cell.closest('table');
      if (tr && table) {
        const idx = Array.from(tr.children).indexOf(cell), head = table.querySelector('tr');
        if (head && head !== tr && head.children[idx]) return txt(head.children[idx]);
      }
    }
    return '';
  };
  const visible = e => {
    const r = e.getBoundingClientRect(), s = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const SAFE_TYPES = ['', 'text', 'number', 'tel', 'search', 'email', 'url', 'date', 'datetime-local',
                      'month', 'week', 'time', 'hidden', 'button', 'submit', 'reset', 'image'];
  const out = [], picked = new Set();
  document.querySelectorAll('input,select,textarea,button,a,[role=button],[onclick]').forEach(e => {
    picked.add(e);
    const tag = e.tagName.toLowerCase();
    const type = (e.getAttribute('type') || '').toLowerCase();
    let value = '', options = null;
    if (tag === 'select') {
      const o = e.options[e.selectedIndex];
      value = o ? txt(o) : '';
      options = Array.from(e.options).slice(0, 12).map(o => txt(o));
    } else if (tag === 'textarea') {
      value = String(e.value || '');
    } else if (tag === 'input') {
      // 값을 읽는 종류를 허용 목록으로 둔다 — 비밀번호 · 파일 같은 칸은 여기 없으므로 값이 남지 않는다
      if (type === 'checkbox' || type === 'radio') value = e.checked ? '켜짐' : '꺼짐';
      else if (SAFE_TYPES.includes(type)) value = String(e.value || '');
    }
    // 이름이 로그인 · 비밀번호를 뜻하는 칸은 값을 적지 않는다 — 로그인 화면에서 누르면 아이디 · 숨은 비밀번호 사본이 남을 수 있었다
    const key = ((e.id || '') + ' ' + (e.getAttribute('name') || '')).toLowerCase();
    // 로그인 · 비밀번호 칸, 그리고 접속 열쇠(authKey · SSO_KEY · token) — 2026-10-21 실측에 ERP 틀의 authKey 앞부분이 그대로 찍혔다
    if (/(pw|pass|pwd|secret|비밀|login|userid|user_id|usr_id|loginid|암호|auth|token|csrf|sso)/.test(key)) value = value ? '(가림)' : '';
    const clickable = tag === 'button' || tag === 'a' || e.getAttribute('role') === 'button'
                      || type === 'button' || type === 'submit' || type === 'image';
    // jQuery 로 붙인 click 처리기(읽기만) — 구매진행관리의 #btnDetail 처럼 onclick 속성이 없는 단추가 어느 함수를 부르는지 보려고(2026-10-22).
    // 처리기 글에 fn_… · uf_… 같은 전역 함수 이름이 있으면 그 함수의 앞부분도 적는다(한 개).
    let handler = '';
    if (clickable && e.id && !e.getAttribute('onclick')) {
      try {
        const jq = window.jQuery; const ev = jq && jq._data ? jq._data(e, 'events') : null;
        const list = ev && (ev.click || ev.mousedown || ev.mouseup); const h = list && list[0] && list[0].handler;
        if (typeof h === 'function') {
          handler = String(h).replace(/\s+/g, ' ').slice(0, 240);
          const m = handler.match(/\b(?!function\b)((?:fn|uf|f|ctl|go|do)_?[A-Za-z]\w*)\s*\(/);
          if (m && typeof window[m[1]] === 'function') handler += '  → ' + m[1] + ': ' + String(window[m[1]]).replace(/\s+/g, ' ').slice(0, 400);
        }
      } catch (err) { /* jQuery 없음 */ }
    }
    out.push({
      handler,
      tag, type,
      id: e.id || '',
      name: e.getAttribute('name') || '',
      cls: (typeof e.className === 'string' ? e.className : '').trim(),
      label: labelFor(e),
      text: clickable ? (txt(e) || String(e.value || '')) : '',
      value, options,
      onclick: e.getAttribute('onclick') || '',
      href: tag === 'a' ? (e.getAttribute('href') || '') : '',
      disabled: !!e.disabled, readonly: !!e.readOnly, visible: visible(e),
    });
  });
  // 메뉴 · 탭 — a · button · onclick 속성 없이 스크립트로만 누르는 글자(li · span · div …). 손가락 커서(cursor: pointer)로 알아본다.
  // 로그인 뒤 메뉴(과제관리 → 과제정보 → 청구서)를 앱이 누르려면 그 글자와 id · class 를 먼저 알아야 한다(담당자 허락 2026-10-19, 실측 전).
  // 겹친 요소는 가장 안쪽(글자 든 손가락 자식이 없는 것)만 적는다. 글자가 긴 것(메뉴 묶음 전체)도 뺀다.
  const pointer = e => { try { return getComputedStyle(e).cursor === 'pointer'; } catch (err) { return false; } };
  let pointers = 0;
  document.querySelectorAll('li,span,div,td,th,img,em,strong,b,p,dt,dd,label,i,font,ul').forEach(e => {
    if (pointers >= 300 || picked.has(e) || e.closest('a,button,[role=button],[onclick]') || !pointer(e)) return;
    const t = txt(e) || e.getAttribute('alt') || e.getAttribute('title') || '';
    if (!t || t.length > 30) return;
    if (Array.from(e.children).some(c => pointer(c) && txt(c))) return;      // 글자 든 손가락 자식이 있으면 묶음 — 자식을 적는다
    pointers += 1;
    out.push({tag: e.tagName.toLowerCase(), type: '', id: e.id || '', name: '',
              cls: (typeof e.className === 'string' ? e.className : '').trim(), label: '', text: t, value: '', options: null,
              onclick: '', href: '', disabled: false, readonly: false, visible: visible(e), pointer: true});
  });
  // 그림(img) — 물품내역팝업(2026-10-22 13:49 실측)에 물품 사진이 있었는데 숨은 칸 IMGFILE_SEQ_NO 만 잡혀 사진 파일의 주소 모양을 알 수 없었다.
  // 작은 아이콘(단추 그림)은 빼고, 크거나 주소가 서버 파일(.act · FILE_SEQ …)을 가리키는 것만 적는다. 읽기만 한다.
  const images = [];
  document.querySelectorAll('img').forEach(img => {
    if (images.length >= 40) return;
    const src = img.getAttribute('src') || '';
    if (!src || src.startsWith('data:')) return;
    const r = img.getBoundingClientRect();
    const big = r.width >= 48 || r.height >= 48 || img.naturalWidth >= 48;
    if (!big && !/\.act|FILE_SEQ|ATTFILE/i.test(src)) return;
    images.push({src: src.slice(0, 160), alt: (img.getAttribute('alt') || img.getAttribute('title') || '').slice(0, 40),
                 w: Math.round(r.width), h: Math.round(r.height), nw: img.naturalWidth || 0, nh: img.naturalHeight || 0,
                 id: img.id || '', onclick: (img.getAttribute('onclick') || '').slice(0, 80), visible: visible(img)});
  });
  return {title: document.title || '', elements: out, images};
}"""

# 프레임 안의 목록(그리드·표). 읽기만 한다. 첫 행 값은 짧게 자르고 긴 숫자는 가린다.
_GRID_JS = r"""() => {
  const txt = e => (e.innerText || e.textContent || '').replace(/\s+/g, ' ').trim();
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const mask = s => s.replace(/\d{6,}/g, m => m.slice(0, 2) + '…').slice(0, 24);
  const out = [];
  // JGM 그리드 — 셀 class 가 k_열이름. 머리글은 그리드 안에서 행(.jgrid-row) 밖에 있는 같은 class 의 셀
  const grids = new Map();
  document.querySelectorAll('[class*="k_"]').forEach(cell => {
    const key = (cell.className.match(/(?:^|\s)(k_[A-Za-z0-9_]+)/) || [])[1];
    if (!key) return;
    // 그리드의 맨 바깥 상자로 묶는다 — 머리글(.jgrid-hdr)과 행(.jgrid-row)이 따로 묶이지 않게
    let root = document.body;
    for (let cur = cell.parentElement; cur && cur !== document.body; cur = cur.parentElement) {
      if (/jgrid/.test(String(cur.className || '')) || cur.tagName === 'TABLE') root = cur;
    }
    if (!grids.has(root)) grids.set(root, {cols: new Map(), rows: 0});
    const g = grids.get(root);
    const inRow = !!cell.closest('.jgrid-row, tbody tr');
    if (!g.cols.has(key)) g.cols.set(key, {head: '', sample: ''});
    const col = g.cols.get(key);
    if (!inRow && !col.head) col.head = txt(cell).slice(0, 16);
    else if (inRow && !col.sample) col.sample = mask(cell.getAttribute('title') || txt(cell));
  });
  grids.forEach((g, root) => {
    const rows = root.querySelectorAll('.jgrid-row').length || root.querySelectorAll('tbody tr').length;
    out.push({kind: 'grid', visible: vis(root), rows,
              cols: Array.from(g.cols, ([key, c]) => ({key, head: c.head, sample: c.sample}))});
  });
  // 머리글(th)이 있는 표 — 그리드가 아닌 결과 목록. 배치용 표는 th 가 없어 걸러진다
  document.querySelectorAll('table').forEach(t => {
    if (grids.has(t) || !t.querySelector('th')) return;
    const heads = Array.from(t.querySelectorAll('th')).map(th => txt(th).slice(0, 16)).filter(Boolean);
    const body = Array.from(t.querySelectorAll('tr')).filter(tr => !tr.querySelector('th') && tr.children.length >= 2);
    if (heads.length < 2 || !body.length) return;
    const first = Array.from(body[0].children).map(td => mask(td.getAttribute('title') || txt(td)));
    const picks = Array.from(body[0].querySelectorAll('input[type=radio],input[type=checkbox]')).length;
    out.push({kind: 'table', visible: vis(t), rows: body.length, heads, first, picks,
              onclick: (body[0].getAttribute('onclick') || '').slice(0, 60)});
  });
  // IBSheet 표(구매·자산 메뉴 — 2026-10-22 구매진행관리 · 구매요구서작성). JGM 이 아니라 셀 class 가 k_… 가 아니고 th 도 없어
  // 위 둘로는 'div.SheetMain' 한 줄만 남았다. 안쪽 tr 을 글자 있는 칸이 둘 이상인 줄로 읽고, 열을 알아볼 단서로 첫 칸의 속성 이름을 적는다.
  // 줄이 하나도 안 잡히면(표가 table 이 아닐 때) 안쪽 class 이름을 적어 다음 판에서 읽는 법을 정한다.
  document.querySelectorAll('.SheetMain, [onclick*="IBSheet"]').forEach(root => {
    if (out.some(g => g.root === root)) return;
    const rows = Array.from(root.querySelectorAll('tr'))
      .map(tr => Array.from(tr.children).map(td => mask(td.getAttribute('title') || txt(td))))
      .filter(cells => cells.filter(Boolean).length >= 2);
    const cell = root.querySelector('td');
    const attrs = cell ? Array.from(cell.attributes).map(a => a.name).filter(n => n !== 'style').slice(0, 8) : [];
    const classes = [];
    for (const e of root.querySelectorAll('*')) {
      const c = (typeof e.className === 'string' ? e.className : '').trim().split(/\s+/)[0];
      if (c && !classes.includes(c)) classes.push(c);
      if (classes.length >= 8) break;
    }
    out.push({kind: 'ibsheet', root, visible: vis(root), rows: rows.length, tables: root.querySelectorAll('table').length,
              attrs, classes, sample: rows.slice(0, 3)});
  });
  out.forEach(g => delete g.root);
  // IBSheet 의 스크립트(읽기 함수만) — DOM 의 tr 로는 머리글 줄과 자료 줄의 칸 수가 달라(고정 열 · 가로 스크롤 table 로 나뉜다) 열을 자리로 못 맞췄다
  // (2026-10-22 13:46 구매진행관리 실측: 머리글 27칸 · 자료 줄 20칸). 14:19 실측에서 IBSheet 가 **8 판**으로 드러났다(GetRows · GetValue · GetFixedRows · GetCaption …,
  // GetTotalRows · LastCol 같은 5~7 판 함수는 없고 version 은 함수) — 8 판은 줄이 객체(Kind 'Data' · 'Header')이고 열은 Cols(이름 → 열) 이다. 두 판의 함수를 다 부른다(있는 것만).
  // 열 이름(Name) · 머리글 · 앞 세 줄 · 있는 Get… 함수 이름을 적는다. Set… · Select… · Focus 는 부르지 않는다.
  try {
    const sheets = window.IBSheet;
    const list = !sheets ? [] : (Array.isArray(sheets) || typeof sheets.length === 'number') ? Array.from(sheets) : Object.values(sheets);
    list.slice(0, 6).forEach((s, i) => {
      if (!s || typeof s !== 'object') return;
      const call = (name, ...args) => { try { return typeof s[name] === 'function' ? s[name](...args) : undefined; } catch (err) { return undefined; } };
      const num = v => (typeof v === 'number' && isFinite(v)) ? v : (typeof v === 'string' && /^\d+$/.test(v) ? Number(v) : undefined);
      const str = v => (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean') ? String(v) : '';
      // 함수 이름은 다 모은 뒤 API 꼴(get… · Get… · set… · do… · Rows · Cols …)을 앞에, 짧은 난독 이름(gTC · nH)은 뒤에 — 14:48 실측에서
      // 열거 차례대로 160개를 적으니 난독 이름과 Action… 뿐이라 GetRows 같은 쓸 이름이 하나도 안 보였다
      let funcs = [], events = [];
      try {
        for (const k in s) {
          if (typeof s[k] !== 'function') continue;
          if (/^on[A-Z]/i.test(k)) { if (events.length < 12) events.push({name: k, src: String(s[k]).replace(/\s+/g, ' ').slice(0, 240)}); continue; }
          if (!/^_/.test(k) && funcs.length < 800) funcs.push(k);
        }
      } catch (err) { /* 열거가 막힌 객체 */ }
      const apiLike = k => /^(get|set|do|is|has|can|focus|select|search|load|save|show|hide|add|remove|refresh|render|Get|Set|Do|Is|Select|Focus|Search|Load|Save|Show|Hide|Add|Remove|Rows?$|Cols?$)/.test(k);
      const minified = k => /^[a-z][A-Za-z]{0,3}$/.test(k) || /^Action/.test(k);
      funcs = funcs.filter(apiLike).sort().concat(funcs.filter(k => !apiLike(k) && !minified(k)).sort()).slice(0, 200);
      const version = str(s.version) || str(s.Version) || str(window.IBSheet && window.IBSheet.version) || '';
      // 8 판: 자료 줄 객체 · Cols. 14:48 실측에서 GetDataRows · GetRows 로는 줄이 안 나왔다 — IBSheet 8 의 제 API 는 소문자(getDataRows · getValue),
      // 대문자(GetFirst · GetNext · GetValue · Rows · Cols)는 바탕인 TreeGrid 의 것이라 둘 다 부른다(읽기 함수만).
      const isData = r => r && typeof r === 'object' && (r.Kind === 'Data' || r.Kind === undefined);
      let dataRows = call('getDataRows');
      if (!Array.isArray(dataRows)) dataRows = call('GetDataRows');
      if (!Array.isArray(dataRows)) {           // TreeGrid 걷기 — 첫 줄부터 다음 줄로(자식 줄은 안 들어간다)
        const walk = (first, next) => { const acc = []; let r = call(first); for (let n = 0; r && n < 5000; n++) { if (isData(r)) acc.push(r); r = call(next, r); } return acc; };
        if (typeof s.GetFirst === 'function' && typeof s.GetNext === 'function') dataRows = walk('GetFirst', 'GetNext');
        if ((!dataRows || !dataRows.length) && typeof s.getFirstRow === 'function' && typeof s.getNextRow === 'function') dataRows = walk('getFirstRow', 'getNextRow');
      }
      if (!Array.isArray(dataRows) || !dataRows.length) { const rows = call('GetRows'); if (Array.isArray(rows)) dataRows = rows.filter(isData); }
      if ((!Array.isArray(dataRows) || !dataRows.length) && s.Rows && typeof s.Rows === 'object') {
        const rows = Object.values(s.Rows).filter(isData);
        if (rows.length) dataRows = rows;
      }
      const rowsHow = Array.isArray(dataRows) && dataRows.length ? (typeof s.getDataRows === 'function' ? 'getDataRows' : (typeof s.GetFirst === 'function' ? 'GetFirst/GetNext' : 'GetRows/Rows')) : '';
      const colsObj = (s.Cols && typeof s.Cols === 'object') ? s.Cols : null;
      let cols = [];
      if (!colsObj && Array.isArray(dataRows) && dataRows[0] && typeof dataRows[0] === 'object') {
        // Cols 가 없는 판 — 줄 객체의 키(값이 글자 · 숫자인 것)를 열 이름으로 본다
        cols = Object.keys(dataRows[0]).filter(k => ['string', 'number', 'boolean'].includes(typeof dataRows[0][k])).slice(0, 60)
          .map(name => ({save: name.slice(0, 24), head: str(call('GetCaption', name)).replace(/\s+/g, ' ').slice(0, 16), type: ''}));
      }
      if (colsObj) cols = Object.keys(colsObj).slice(0, 60).map(name => {
        const c = colsObj[name] || {};
        const head = str(call('GetCaption', name)) || str(c.Header) || str(c.Caption) || '';
        return {save: name.slice(0, 24), head: head.replace(/\s+/g, ' ').slice(0, 16), type: str(c.Type).slice(0, 10)};
      });
      let total = Array.isArray(dataRows) && dataRows.length ? dataRows.length
        : (num(call('getRowCount')) ?? num(call('getTotalRowCount')) ?? num(call('GetTotalRowCount')) ?? num(call('GetDataRowCount')));
      let headerRows = Array.isArray(call('GetHeaderRows')) ? call('GetHeaderRows').length : undefined;
      const sample = [];
      if (cols.length && Array.isArray(dataRows)) dataRows.slice(0, 3).forEach(row => {
        sample.push(cols.map(c => mask(str(call('getText', row, c.save)) || str(call('getString', row, c.save)) || str(call('getValue', row, c.save))
                                        || str(call('GetText', row, c.save)) || str(call('GetString', row, c.save)) || str(call('GetValue', row, c.save))
                                        || (row && typeof row === 'object' ? str(row[c.save]) : ''))));
      });
      // 5~7 판: 줄 번호 · ColSaveName
      if (!cols.length) {
        total = total ?? num(call('GetTotalRows')) ?? num(call('RowCount')) ?? num(call('LastRow'));
        const lastCol = num(call('LastCol')) ?? num(call('GetColCount')) ?? num(call('ColCount'));
        headerRows = headerRows ?? num(call('HeaderRows'));
        if (lastCol !== undefined) for (let c = 0; c <= lastCol && c < 60; c++) {
          const save = call('ColSaveName', c) ?? call('GetColSaveName', c) ?? '';
          const head = call('GetHeaderText', c) ?? (headerRows ? call('GetCellText', headerRows - 1, c) : undefined) ?? '';
          cols.push({save: String(save || '').slice(0, 24), head: String(head || '').replace(/\s+/g, ' ').slice(0, 16)});
        }
        const firstRow = headerRows !== undefined ? headerRows : 1;
        if (total && cols.length) for (let r = firstRow; r < firstRow + 3 && r <= (num(call('LastRow')) ?? firstRow + total - 1); r++) {
          sample.push(cols.map((c, idx) => mask(String(call('GetCellText', r, idx) ?? call('GetCellValue', r, idx) ?? ''))));
        }
      }
      const pages = num(call('getPageNum')) ?? num(call('GetPageNum')) ?? num(call('GetTotalPage')) ?? num(call('GetPageCount'));
      const totalAll = num(call('getTotalRowCount')) ?? num(call('GetTotalRowCount')) ?? num(call('GetTotalCount'));
      out.push({kind: 'ibsheet-api', index: i, id: str(s.id || s.Id || s.Name).slice(0, 30), version: version.slice(0, 20),
                total, totalAll, pages, headerRows, funcs, events, cols, sample, rowsHow});
    });
  } catch (err) { /* IBSheet 없음 */ }
  return out.slice(0, 16);
}"""

VALUE_LIMIT = 40        # 값은 여기서 자른다 — 계좌번호·긴 적요가 통째로 남지 않게
# 값을 적는 input 종류의 허용 목록. 비밀번호·파일 칸은 여기 없으므로 값이 남지 않는다(JS 와 같은 목록).
SAFE_VALUE_TYPES = {"", "text", "number", "tel", "search", "email", "url", "date", "datetime-local",
                    "month", "week", "time", "hidden", "checkbox", "radio", "button", "submit", "reset", "image"}
PER_FRAME_LIMIT = 400   # 프레임 하나에 이보다 많으면 '… 외 N개'


# 화면 틀 알아보기 — K-Cloud(강원대 통합정보시스템, 27절)는 주소가 websquare.jsp 라 WebSquare(인스웨이브) 로 보인다. ERP 의 JGM · IBSheet 처럼
# 틀마다 목록 · 칸을 읽는 법이 다르므로, 어느 틀인지와 w2 요소(w2input · w2grid …)가 몇 개인지만 한 줄로 적는다. 읽기만 한다 — 실측이 오면 그 틀의 읽기를 더한다.
_FRAMEWORK_JS = r"""() => {
  try {
    const ws = window.WebSquare;
    const w2 = document.querySelectorAll('[class*="w2"]');
    if (!ws && !w2.length) return '';
    let ver = '';
    try { ver = typeof ws.version === 'function' ? ws.version() : (ws.version || ''); } catch (err) { ver = ''; }
    const kinds = {};
    w2.forEach(e => { const m = String(e.className || '').match(/\bw2[A-Za-z]+/); if (m) kinds[m[0]] = (kinds[m[0]] || 0) + 1; });
    const top = Object.entries(kinds).sort((a, b) => b[1] - a[1]).slice(0, 14).map(([k, v]) => k + ' ' + v).join(' · ');
    return 'WebSquare' + (ver ? ' ' + String(ver).slice(0, 24) : '') + (ws ? '' : '(전역 객체 없음)') + ' · w2 요소 ' + w2.length + (top ? ' · ' + top : '');
  } catch (err) { return ''; }
}"""


def _frame_report(fr) -> dict:
    """프레임 하나를 읽는다. 로딩 중이라 evaluate 가 실패하면 그 사실만 적는다."""
    try:
        data = fr.evaluate(_PROBE_JS)
    except Exception as error:  # noqa: BLE001 — 진단은 어떤 프레임에서도 멈추면 안 된다
        data = {"title": "", "elements": [], "error": str(error).splitlines()[0] if str(error) else "읽기 실패"}
    try:
        data["grids"] = fr.evaluate(_GRID_JS) if not data.get("error") else []
    except Exception:  # noqa: BLE001 — 목록은 못 읽어도 요소 목록은 남긴다
        data["grids"] = []
    try:
        data["framework"] = fr.evaluate(_FRAMEWORK_JS) if not data.get("error") else ""
    except Exception:  # noqa: BLE001
        data["framework"] = ""
    try:
        url = fr.url or ""
    except Exception:  # noqa: BLE001
        url = "?"
    data["url"] = url
    return data


def capture(context, frame_kind: Callable[[object], str] | None = None,
            keep: Callable[[str], bool] | None = None) -> list[dict]:
    """열린 모든 창의 모든 프레임을 읽는다. frame_kind 는 프레임을 알아본 이름('결의서 목록' 등).
    keep 을 주면 창 주소로 고른 창만(화면 구조 저장 업무에서 ERP · 주차등록 사이트 중 고른 곳 — 2026-10-21)."""
    windows = []
    for pg in context.pages:
        try:
            if pg.is_closed():          # 닫히는 중인 팝업이 목록에 남아 있을 수 있다(실측 2026-10-13)
                continue
        except Exception:  # noqa: BLE001
            pass
        try:
            title = pg.title()
        except Exception:  # noqa: BLE001
            title = "?"
        try:
            url = pg.url
        except Exception:  # noqa: BLE001
            url = "?"
        if keep is not None and not keep(url):
            continue
        frames = []
        for fr in pg.frames:
            report = _frame_report(fr)
            report["kind"] = frame_kind(fr) if frame_kind else ""
            frames.append(report)
        windows.append({"title": title, "url": url, "frames": frames})
    return windows


def _clean_value(el: dict) -> str:
    """허용 목록 밖의 칸(비밀번호 등)은 JS 에서 이미 비웠지만 한 번 더 막는다. 긴 값은 자른다."""
    if el.get("tag") == "input" and (el.get("type") or "").lower() not in SAFE_VALUE_TYPES:
        return ""
    value = str(el.get("value") or "").replace("\n", " ")
    return value if len(value) <= VALUE_LIMIT else value[:VALUE_LIMIT] + "…"


def _element_line(el: dict) -> str:
    tag, type_ = el.get("tag", ""), el.get("type", "")
    head = f"<{tag}{(' ' + type_) if type_ else ''}>"
    parts = [head]
    if el.get("id"):
        parts.append("#" + el["id"])
    if el.get("name"):
        parts.append("name=" + el["name"])
    if el.get("text"):
        parts.append(f"'{el['text'][:40]}'")
    if el.get("label"):
        parts.append("라벨: " + el["label"][:40])
    value = _clean_value(el)
    if value:
        parts.append("값: " + value)
    if el.get("options"):
        parts.append("보기: " + " | ".join(o[:20] for o in el["options"]))
    if el.get("onclick"):
        parts.append("onclick=" + el["onclick"][:80])
    if el.get("handler"):
        parts.append("처리기=" + el["handler"])
    if el.get("href") and el["href"] not in ("#", "javascript:void(0)", "javascript:;"):
        parts.append("href=" + el["href"][:80])
    if el.get("cls"):
        parts.append("class=" + el["cls"][:60])
    flags = [f for f, on in (("비활성", el.get("disabled")), ("읽기전용", el.get("readonly")),
                             ("누를 수 있음", el.get("pointer"))) if on]
    if flags:
        parts.append("[" + " · ".join(flags) + "]")
    return "  ".join(parts)


def _grid_lines(grids: list[dict]) -> list[str]:
    """목록(그리드·표) 한 줄씩 — 열 이름과 행 수, 첫 행의 값(가린 것)."""
    out = []
    for g in grids or []:
        hidden = "" if g.get("visible", True) else "[숨김] "
        if g.get("kind") == "grid":
            cols = " | ".join(f"{c['key']}({c['head']})" if c.get("head") else c["key"] for c in g.get("cols", []))
            out.append(f"{hidden}그리드: 행 {g.get('rows', 0)} · 열: {cols}")
            sample = " | ".join(f"{c['key']}={c['sample']}" for c in g.get("cols", []) if c.get("sample"))
            if sample:
                out.append(f"{hidden}  첫 행: {sample}")
        elif g.get("kind") == "ibsheet":
            # 머리글과 줄이 한 표인지 따로인지 모르므로 앞 세 줄을 그대로 적는다 — 첫 줄이 머리글일 가능성이 크다
            out.append(f"{hidden}IBSheet 표: 글자 줄 {g.get('rows', 0)} · table {g.get('tables', 0)}개"
                       + (" · 칸 속성: " + ",".join(g["attrs"]) if g.get("attrs") else "")
                       + (" · 안쪽 class: " + ",".join(g["classes"]) if not g.get("rows") and g.get("classes") else ""))
            for i, cells in enumerate(g.get("sample", [])[:3], 1):
                out.append(f"{hidden}  줄 {i}: " + " | ".join(v for v in cells if v))
        elif g.get("kind") == "ibsheet-api":
            # IBSheet 스크립트로 읽은 것 — 열은 SaveName(머리글), 줄은 칸 차례 그대로(빈 칸은 '-')
            head = f"IBSheet 스크립트 [{g.get('index', 0)}]"
            head += f" id {g['id']}" if g.get("id") else ""
            head += f" 판 {g['version']}" if g.get("version") else ""
            head += f" · 줄 {g['total']}" if g.get("total") is not None else " · 줄 수 모름"
            head += f" · 열 {len(g['cols'])}" if g.get("cols") else " · 열 수 모름"
            head += f" · 머리글 줄 {g['headerRows']}" if g.get("headerRows") is not None else ""
            head += f" · 전체 줄 {g['totalAll']}" if g.get("totalAll") is not None else ""
            head += f" · 쪽 {g['pages']}" if g.get("pages") is not None else ""
            out.append(head)
            if g.get("rowsHow"):
                out[-1] += f" · 줄은 {g['rowsHow']} 로 읽음"
            if g.get("funcs"):
                out.append("  함수: " + " ".join(g["funcs"][:200]))
            for ev in g.get("events", [])[:12]:
                out.append(f"  처리기 {ev.get('name', '')}: {ev.get('src', '')}")
            if g.get("cols"):
                out.append("  열: " + " | ".join((c.get("save") or "?") + (f"({c['head']})" if c.get("head") else "")
                                                 + (f"<{c['type']}>" if c.get("type") else "") for c in g["cols"]))
            for i, cells in enumerate(g.get("sample", [])[:3], 1):
                out.append(f"  줄 {i}: " + " | ".join(v or "-" for v in cells))
        else:
            out.append(f"{hidden}표: 행 {g.get('rows', 0)} · 머리글: " + " | ".join(g.get("heads", [])))
            extra = []
            if g.get("picks"):
                extra.append(f"행마다 선택 칸 {g['picks']}개")
            if g.get("onclick"):
                extra.append("행 onclick=" + g["onclick"])
            first = " | ".join(v for v in g.get("first", []) if v)
            if first or extra:
                out.append(f"{hidden}  첫 행: {first}" + (("  (" + " · ".join(extra) + ")") if extra else ""))
    return out


def _image_lines(images: list[dict]) -> list[str]:
    """그림(img) 한 줄씩 — 주소 · 크기 · alt. 물품 사진처럼 서버 파일을 가리키는 그림의 주소 모양을 보려는 것."""
    out = []
    for img in images or []:
        hidden = "" if img.get("visible", True) else "[숨김] "
        parts = [f"{hidden}그림: {img.get('src', '')}"]
        size = f"{img.get('w', 0)}×{img.get('h', 0)}"
        if img.get("nw") or img.get("nh"):
            size += f" (원본 {img.get('nw', 0)}×{img.get('nh', 0)})"
        parts.append(size)
        if img.get("id"):
            parts.append("#" + img["id"])
        if img.get("alt"):
            parts.append(f"alt='{img['alt']}'")
        if img.get("onclick"):
            parts.append("onclick=" + img["onclick"])
        out.append("  ".join(parts))
    return out


def _collapsed(elements: list[dict]) -> list[str]:
    """똑같이 생긴 요소가 잇달아 나오면(목록 행마다 있는 체크박스 등) 한 줄로 접고 개수를 적는다."""
    lines: list[str] = []
    counts: list[int] = []
    for el in elements:
        line = _element_line(el)
        if lines and lines[-1] == line:
            counts[-1] += 1
        else:
            lines.append(line)
            counts.append(1)
    return [f"{line}  (× {n})" if n > 1 else line for line, n in zip(lines, counts)]


def format_report(windows: list[dict], when: str | None = None, target: str = "") -> str:
    when = when or time.strftime("%Y-%m-%d %H:%M")
    out = [
        f"COSS 업무데스크 화면 구조  ({when})" + (f" · 대상: {target}" if target else ""),
        "읽기만 했습니다. 아무것도 누르거나 넣지 않았습니다. 비밀번호 칸의 값은 기록하지 않습니다.",
        "보이는 요소를 먼저, 숨은 요소는 뒤에 '[숨김]' 으로 적습니다.",
        "a · button 이 아닌데 손가락 커서가 뜨는 글자(메뉴 · 탭)는 '[누를 수 있음]' 으로 적습니다.",
        "",
    ]
    if not windows:
        out.append("(열린 창이 없음)")
        return "\n".join(out) + "\n"
    for wi, win in enumerate(windows):
        out.append(f"[창 {wi}] {win.get('title') or '(제목 없음)'} | {win.get('url') or ''}")
        for fi, fr in enumerate(win.get("frames", [])):
            kind = f"  <== {fr['kind']}" if fr.get("kind") else ""
            title = f" ({fr['title']})" if fr.get("title") else ""
            out.append(f"  프레임 {fi}: {fr.get('url') or '(주소 없음)'}{title}{kind}")
            if fr.get("error"):
                out.append(f"    (읽지 못함: {fr['error']})")
                continue
            if fr.get("framework"):
                out.append(f"    틀: {fr['framework']}")
            elements = fr.get("elements", [])
            shown = [e for e in elements if e.get("visible")]
            hidden = [e for e in elements if not e.get("visible")]
            out.append(f"    요소 {len(elements)}개 (보임 {len(shown)} · 숨김 {len(hidden)})")
            for line in _grid_lines(fr.get("grids", [])):
                out.append("    " + line)
            for line in _image_lines(fr.get("images", [])):
                out.append("    " + line)
            for line in _collapsed(shown)[:PER_FRAME_LIMIT]:
                out.append("    " + line)
            if len(shown) > PER_FRAME_LIMIT:
                out.append(f"    … 외 {len(shown) - PER_FRAME_LIMIT}개")
            budget = max(0, PER_FRAME_LIMIT - len(shown))
            for line in _collapsed(hidden)[:budget]:
                out.append("    [숨김] " + line)
            if len(hidden) > budget:
                out.append(f"    [숨김] … 외 {len(hidden) - budget}개")
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


BOOK_LIMIT = 3_000_000      # 모음이 이보다 커지면 새로 시작한다(지난 실측이 끝없이 쌓이지 않게)


def copy_to_desktop(desktop: Path, book: Path, single: Path, now: dt.datetime | None = None) -> Path:
    """저장한 화면 구조를 바탕화면에 복사한다(담당자 2026-10-22 "바탕화면 저장하기 버튼" — 사용자 폴더(.claim-downloader)를 찾아 들어가기
    번거롭다). 모음 파일이 있으면 그것(저장한 화면이 모두 들어 있다), 없으면 마지막 화면. 바탕화면의 파일은 덮어쓰지 않고 이름에 저장한 때를 붙인다
    — 같은 분에 또 누르면 _2. 바탕화면 폴더가 없거나 복사하지 못하면 OSError."""
    source = book if book.exists() and book.stat().st_size else single
    if not source.exists():
        raise FileNotFoundError("저장한 화면 구조가 없습니다 — 먼저 [화면 구조 저장] 을 누르세요")
    if not desktop.is_dir():
        raise FileNotFoundError(f"바탕화면 폴더를 찾지 못했습니다: {desktop}")
    stem = ("화면구조_모음" if source == book else "화면구조") + (now or dt.datetime.now()).strftime("_%Y%m%d_%H%M")
    target = desktop / f"{stem}.txt"
    n = 2
    while target.exists():
        target = desktop / f"{stem}_{n}.txt"
        n += 1
    shutil.copyfile(source, target)
    return target


def append_to_book(path, report: str) -> int:
    """저장한 화면 구조를 모음 파일 끝에 붙인다. 몇 번째인지 돌려준다. 메뉴 이동처럼 화면을 차례로 실측할 때 담당자가 마지막에
    모음 하나만 보내면 된다(2026-10-19). 쓰지 못하면 0 — 모음은 덤이라 저장 자체를 실패로 두지 않는다."""
    try:
        old = path.read_text(encoding="utf-8") if path.exists() and path.stat().st_size < BOOK_LIMIT else ""
        number = len(re.findall(r"^════ 화면 구조 \d+번째", old, re.M)) + 1
        head = f"════ 화면 구조 {number}번째 ════\n"
        path.write_text(old + ("\n" if old and not old.endswith("\n\n") else "") + head + report, encoding="utf-8")
        return number
    except OSError:
        return 0
