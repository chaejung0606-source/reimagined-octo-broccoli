#!/usr/bin/env python3
"""화면 구조 저장 — 독립 실행 도구 (COSS 업무데스크 diagnose.py 에서 떼어 낸 것, 2026-10-26).

새 플랫폼(K-Cloud 등)의 화면을 자동화하기 **전에** 실측하는 도구다. AI(Claude)는 사이트에 들어갈 수 없으므로
(로그인은 사람), 담당자가 이 도구로 띄운 브라우저에서 로그인하고 실측할 화면을 띄운 뒤 터미널에서 Enter 를 치면
열린 창 · 프레임 · 입력 요소 · 목록 · 그림 · 화면 틀(WebSquare 등)이 글 파일로 남는다. 그 파일을 받아 CLAUDE.md 에
화면 구조 절(프레임 · 칸 · 절대 누르지 않을 단추)을 쓴 뒤에야 설계 · 구현으로 간다(README.md 3절).

쓰는 법
    pip install playwright
    python -m playwright install chromium
    python structure_capture.py https://kcloud.kangwon.ac.kr/websquare/websquare.jsp?w2xPath=/cm/main/index_tabControl.xml
      → 브라우저가 뜬다. 사람이 로그인하고 실측할 화면을 띄운다.
      → 이 창에서 화면 이름을 적고 Enter(이름 없이 Enter 도 됨) — 화면마다 되풀이. q 로 끝.
      → ~/화면구조/화면구조_YYYYMMDD_HHMM.txt 하나씩 + 화면구조_모음.txt 에 차례로 쌓인다(담당자는 모음 하나만 보낸다).
    이미 떠 있는 크롬에 붙기(설치된 크롬으로 로그인해 둔 채):
      chrome.exe --remote-debugging-port=9222   로 띄운 뒤
      python structure_capture.py --cdp http://localhost:9222
    --site kcloud.kangwon.ac.kr   그 호스트의 창만 읽기 · --out 폴더   저장 위치 · --once   묻지 않고 한 번 저장하고 끝

**읽기만 한다.** 아무것도 누르거나 값을 넣지 않는다 — 새 저장소의 tests/test_safety.py 가 이 파일에 click · submit ·
값 대입 · 이벤트 발생이 없는지 본다(test_safety_template.py 참고). 비밀번호 · 파일 칸의 값은 기록하지 않고(값을 읽는 칸 종류를
허용 목록으로 둔다), 이름에 pw · auth · token · sso 가 든 칸도 가리며, 다른 값은 40자에서 자르고 목록의 첫 줄 값에서 6자리
이상 숫자는 가린다. 그래도 계좌번호 · 이름 같은 값이 섞일 수 있으니 **빈 작성 화면**에서 돌리고 보내기 전에 한 번 훑는다.
결과 파일은 저장소에 올리지 않는다(gitignore.template).

목록(그리드 · 표)도 적는다 — 입력 요소만 적으면 검색 결과에서 줄을 고르는 방법을 알 수 없어서다. JGM 그리드(`.jgrid-row` ·
`k_열이름` 셀) · 머리글(th) 표 · IBSheet 표(DOM 줄 + 스크립트 `getDataRows` · `getValue` · `Cols`) · role=grid/table 표를 읽는다.
새 플랫폼의 목록 제품이 다르면 첫 실측 뒤 여기에 그 제품의 읽기를 더한다(ERP 에서 IBSheet 가 그렇게 들어왔다).
그림(`<img>`)은 크거나 서버 파일을 가리키는 것만 주소 · 크기로 적는다.

Playwright 는 main() 안에서만 들여온다 — 테스트가 브라우저 없이 글 만들기 · 가림 규칙을 볼 수 있게.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

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

# 화면 틀 — WebSquare(인스웨이브, K-Cloud 가 쓰는 것으로 보인다: 주소의 websquare.jsp · w2xPath) 처럼 DOM 을 제 방식으로 그리는 틀이
# 있으면 한 줄로 알린다. 전역 객체가 있으면 판, class 가 w2… 인 요소를 종류별로 센다. 읽기만 한다. 다른 틀(예: 넥사크로 · 엑스플랫폼)은
# 첫 실측에서 전역 객체 이름을 보고 여기에 더한다.
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

# role=grid · table · treegrid 로 그린 목록(WebSquare gridView 가 이 꼴일 수 있다 — 실측 전). 머리글(columnheader)과 줄(row) 수,
# 첫 줄의 칸 값(긴 숫자는 가림)만 적는다. 위 _GRID_JS 가 못 잡는 표의 보조.
_ARIA_GRID_JS = r"""() => {
  const txt = e => (e.innerText || e.textContent || '').replace(/\s+/g, ' ').trim();
  const mask = s => s.replace(/\d{6,}/g, m => m.slice(0, 2) + '…').slice(0, 24);
  const out = [];
  document.querySelectorAll('[role=grid],[role=table],[role=treegrid]').forEach(g => {
    if (out.length >= 8) return;
    const r = g.getBoundingClientRect();
    const heads = Array.from(g.querySelectorAll('[role=columnheader]')).map(h => txt(h).slice(0, 16)).filter(Boolean);
    const rows = Array.from(g.querySelectorAll('[role=row]')).filter(row => !row.querySelector('[role=columnheader]'));
    const first = rows.length ? Array.from(rows[0].querySelectorAll('[role=gridcell],[role=cell]')).map(c => mask(txt(c))) : [];
    out.push({role: g.getAttribute('role'), id: g.id || '', cls: (typeof g.className === 'string' ? g.className : '').slice(0, 60),
              visible: r.width > 0 && r.height > 0, rows: rows.length, heads: heads.slice(0, 40), first: first.slice(0, 40)});
  });
  return out;
}"""

VALUE_LIMIT = 40        # 값은 여기서 자른다 — 계좌번호 · 긴 적요가 통째로 남지 않게
# 값을 적는 input 종류의 허용 목록. 비밀번호 · 파일 칸은 여기 없으므로 값이 남지 않는다(JS 와 같은 목록).
SAFE_VALUE_TYPES = {"", "text", "number", "tel", "search", "email", "url", "date", "datetime-local",
                    "month", "week", "time", "hidden", "checkbox", "radio", "button", "submit", "reset", "image"}
PER_FRAME_LIMIT = 400   # 프레임 하나에 이보다 많으면 '… 외 N개'
EVAL_TIMEOUT_MS = 8000  # 확인 창(alert · confirm)이 떠 있으면 화면 스크립트가 멈춘다 — 그때 끝없이 기다리지 않게


def _run_js(fr, js: str):
    """프레임에서 읽기 JS 를 돌린다. wait_for_function 은 시간 제한이 있어 확인 창이 떠 있어도 8초 뒤 포기한다(evaluate 는 멈춘다)."""
    try:
        handle = fr.wait_for_function(js, timeout=EVAL_TIMEOUT_MS)
        return handle.json_value()
    except AttributeError:          # 옛 Playwright — 시간 제한 없이
        return fr.evaluate(js)


def _frame_report(fr) -> dict:
    """프레임 하나를 읽는다. 로딩 중이라 읽기가 실패하면 그 사실만 적는다."""
    try:
        data = _run_js(fr, _PROBE_JS)
        if not isinstance(data, dict):
            data = {"title": "", "elements": [], "error": "읽기 결과가 비어 있음"}
    except Exception as error:  # noqa: BLE001 — 진단은 어떤 프레임에서도 멈추면 안 된다
        first = str(error).splitlines()[0] if str(error) else "읽기 실패"
        if "Timeout" in first or "timeout" in first:
            first = "시간 초과 — 확인 창이 떠 있거나 화면이 멈춤 (창을 닫고 다시 Enter)"
        data = {"title": "", "elements": [], "error": first}
    for key, js in (("grids", _GRID_JS), ("aria", _ARIA_GRID_JS)):
        try:
            data[key] = _run_js(fr, js) if not data.get("error") else []
        except Exception:  # noqa: BLE001 — 목록은 못 읽어도 요소 목록은 남긴다
            data[key] = []
    try:
        data["framework"] = _run_js(fr, _FRAMEWORK_JS) if not data.get("error") else ""
    except Exception:  # noqa: BLE001
        data["framework"] = ""
    try:
        url = fr.url or ""
    except Exception:  # noqa: BLE001
        url = "?"
    data["url"] = url
    data["kind"] = frame_kind(url)
    return data


def frame_kind(url: str) -> str:
    """프레임을 알아본 이름. WebSquare 는 주소의 w2xPath 가 화면 이름 역할을 한다(ERP 는 내용으로 알아봤다 — 새 플랫폼에서 표식을 찾으면 여기에)."""
    try:
        query = parse_qs(urlparse(url).query)
    except ValueError:
        return ""
    path = (query.get("w2xPath") or [""])[0]
    return f"w2xPath {path}" if path else ""


def capture(contexts, keep=None) -> list[dict]:
    """열린 모든 창의 모든 프레임을 읽는다. keep(url) 을 주면 그 창만(--site)."""
    windows = []
    for context in contexts:
        for pg in context.pages:
            try:
                if pg.is_closed():          # 닫히는 중인 팝업이 목록에 남아 있을 수 있다
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
            windows.append({"title": title, "url": url, "frames": [_frame_report(fr) for fr in pg.frames]})
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
    """목록(그리드 · 표) 한 줄씩 — 열 이름과 줄 수, 첫 줄의 값(가린 것)."""
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
            out.append(f"{hidden}IBSheet 표: 글자 줄 {g.get('rows', 0)} · table {g.get('tables', 0)}개"
                       + (" · 칸 속성: " + ",".join(g["attrs"]) if g.get("attrs") else "")
                       + (" · 안쪽 class: " + ",".join(g["classes"]) if not g.get("rows") and g.get("classes") else ""))
            for i, cells in enumerate(g.get("sample", [])[:3], 1):
                out.append(f"{hidden}  줄 {i}: " + " | ".join(v for v in cells if v))
        elif g.get("kind") == "ibsheet-api":
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


def _aria_lines(grids: list[dict]) -> list[str]:
    out = []
    for g in grids or []:
        hidden = "" if g.get("visible", True) else "[숨김] "
        head = f"{hidden}role={g.get('role', '')} 표"
        head += f" #{g['id']}" if g.get("id") else ""
        head += f" class={g['cls']}" if g.get("cls") else ""
        out.append(f"{head}: 행 {g.get('rows', 0)} · 머리글: " + " | ".join(g.get("heads", [])))
        first = " | ".join(v for v in g.get("first", []) if v)
        if first:
            out.append(f"{hidden}  첫 행: {first}")
    return out


def _image_lines(images: list[dict]) -> list[str]:
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


def format_report(windows: list[dict], when: str | None = None, label: str = "", target: str = "") -> str:
    when = when or time.strftime("%Y-%m-%d %H:%M")
    out = [
        f"화면 구조  ({when})" + (f" · {label}" if label else "") + (f" · 대상: {target}" if target else ""),
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
            for line in _grid_lines(fr.get("grids", [])) + _aria_lines(fr.get("aria", [])) + _image_lines(fr.get("images", [])):
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


BOOK_NAME = "화면구조_모음.txt"
BOOK_LIMIT = 3_000_000      # 모음이 이보다 커지면 새로 시작한다(지난 실측이 끝없이 쌓이지 않게)


def new_file(folder: Path, now: dt.datetime | None = None) -> Path:
    """화면구조_YYYYMMDD_HHMM.txt — 같은 분에 또 저장하면 _2, _3. 덮어쓰지 않는다."""
    stem = "화면구조" + (now or dt.datetime.now()).strftime("_%Y%m%d_%H%M")
    target = folder / f"{stem}.txt"
    n = 2
    while target.exists():
        target = folder / f"{stem}_{n}.txt"
        n += 1
    return target


def append_to_book(path: Path, report: str) -> int:
    """저장한 화면 구조를 모음 파일 끝에 붙인다. 몇 번째인지 돌려준다. 쓰지 못하면 0 — 모음은 덤이라 저장 자체를 실패로 두지 않는다."""
    try:
        old = path.read_text(encoding="utf-8") if path.exists() and path.stat().st_size < BOOK_LIMIT else ""
        number = len(re.findall(r"^════ 화면 구조 \d+번째", old, re.M)) + 1
        head = f"════ 화면 구조 {number}번째 ════\n"
        path.write_text(old + ("\n" if old and not old.endswith("\n\n") else "") + head + report, encoding="utf-8")
        return number
    except OSError:
        return 0


def save(contexts, folder: Path, label: str = "", site: str = "", target: str = "") -> tuple[Path, int]:
    """한 번 읽어 파일 하나 + 모음에 붙인다. (파일 경로, 모음에서 몇 번째) 를 돌려준다."""
    keep = (lambda url: _host(url).endswith(site.lower())) if site else None
    report = format_report(capture(contexts, keep), label=label, target=target)
    folder.mkdir(parents=True, exist_ok=True)
    path = new_file(folder)
    path.write_text(report, encoding="utf-8")
    return path, append_to_book(folder / BOOK_NAME, report)


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="열린 화면의 창 · 프레임 · 입력 요소 · 목록을 읽기만 해서 글 파일로 남긴다.")
    parser.add_argument("url", nargs="?", default="", help="처음 열 주소(로그인 화면). 사람이 로그인한다")
    parser.add_argument("--cdp", default="", help="이미 띄운 크롬의 원격 디버깅 주소 (예: http://localhost:9222)")
    parser.add_argument("--out", default=str(Path.home() / "화면구조"), help="저장 폴더 (기본: 사용자 홈의 화면구조)")
    parser.add_argument("--site", default="", help="이 호스트의 창만 읽기 (예: kcloud.kangwon.ac.kr). 비우면 열린 창 모두")
    parser.add_argument("--once", action="store_true", help="묻지 않고 바로 한 번 저장하고 끝 (--cdp 와 함께 쓴다)")
    args = parser.parse_args(argv)
    if not args.url and not args.cdp:
        parser.error("처음 열 주소나 --cdp 가 필요합니다")

    from playwright.sync_api import sync_playwright     # 여기서만 — 테스트는 브라우저 없이 글 만들기만 본다

    folder = Path(args.out)
    target = args.site or _host(args.url)
    with sync_playwright() as pw:
        if args.cdp:
            browser = pw.chromium.connect_over_cdp(args.cdp)
            contexts = list(browser.contexts)
        else:
            browser = pw.chromium.launch(headless=False)
            context = browser.new_context(no_viewport=True)     # 화면이 창 크기를 따라가게(기본값은 1280×720 에 묶인다)
            # 확인 창(alert · confirm)에 처리기를 두되 손대지 않는다 — 처리기가 없으면 Playwright 가 띄우지 않고 바로 닫아(confirm 은 취소)
            # 사람이 로그인 · 화면을 다룰 때 사이트의 알림이 보이지 않는다. 떠 있는 동안 읽기는 멈추므로 Enter 전에 닫는다(EVAL_TIMEOUT_MS).
            context.on("page", lambda pg: pg.on("dialog", lambda d: None))
            page = context.new_page()
            page.on("dialog", lambda d: None)
            page.goto(args.url)
            contexts = [context]
        print(f"저장 폴더: {folder}")
        if args.once:
            path, number = save(contexts, folder, site=args.site, target=target)
            print(f"저장함: {path}  (모음 {number}번째)")
            return 0
        print("브라우저에서 로그인하고 실측할 화면을 띄운 뒤, 여기서 화면 이름을 적고 Enter (이름 없이 Enter 도 됨 · q 끝).")
        print("확인 창이 떠 있으면 먼저 닫으세요. 빈 작성 화면에서 저장하세요 — 값이 섞일 수 있습니다.")
        while True:
            try:
                label = input("화면 이름 › ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if label.lower() in ("q", "quit", "exit", "끝"):
                break
            try:
                path, number = save(contexts, folder, label=label, site=args.site, target=target)
            except Exception as error:  # noqa: BLE001 — 브라우저가 닫혔으면 알리고 끝
                print(f"저장하지 못함: {str(error).splitlines()[0] if str(error) else error}")
                if "closed" in str(error).lower():
                    break
                continue
            print(f"저장함: {path}  (모음 {number}번째)")
        print(f"보낼 파일: {folder / BOOK_NAME}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
