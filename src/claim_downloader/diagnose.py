"""진단 모드 — ERP 의 아무 화면이나 띄운 상태에서 열린 창·프레임과 입력 요소를 글로 남긴다.

새 화면(일반청구 · 카드청구 작성)을 자동화하기 전에 **실측**하는 도구다. Claude 는 ERP 에 들어갈 수
없으므로(로그인은 사람), 담당자가 원하는 화면을 띄우고 [화면 구조 저장] 을 누르면 이 파일이
~/.claim-downloader/_화면구조.txt 로 남고, 그것을 받아 CLAUDE.md 에 화면 구조 절을 쓴다.

**읽기만 한다.** 아무것도 누르거나 값을 넣지 않는다 — tests/test_safety.py 가 이 JS 에 click · submit ·
값 대입 · 이벤트 발생이 없는지 본다. 비밀번호 칸의 값은 기록하지 않고(값을 읽는 칸 종류를 허용 목록으로 둔다), 다른 값도 40자에서 자른다.
결과 파일은 .gitignore 와 배포 zip(make_bundle.NEVER_PACK_NAMES)에서 제외된다 — 계좌번호 같은 값이
들어 있을 수 있다. 담당자에게는 **빈 작성 화면**에서 돌리라고 안내한다.

목록(그리드)도 적는다(2026-10-13 입금처 팝업 실측 뒤 추가) — 입력 요소만 적으면 검색 결과 목록의 열과 행을 고르는
방법을 알 수 없어서다. JGM 그리드(`.jgrid-row` · `k_열이름` 셀)와 머리글(th)이 있는 표의 열 이름 · 행 수 · 첫 행 값을
적되, 첫 행 값에서 6자리 이상 숫자(계좌번호 · 사업자번호)는 가린다.

Playwright 를 들여오지 않는다(브라우저를 띄우는 곳은 session.py 하나). 프레임 객체의 evaluate 만 쓴다.
"""
from __future__ import annotations

import time
from collections.abc import Callable

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
    if (/(pw|pass|pwd|secret|비밀|login|userid|user_id|usr_id|loginid|암호)/.test(key)) value = value ? '(가림)' : '';
    const clickable = tag === 'button' || tag === 'a' || e.getAttribute('role') === 'button'
                      || type === 'button' || type === 'submit' || type === 'image';
    out.push({
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
  return {title: document.title || '', elements: out};
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
  return out.slice(0, 12);
}"""

VALUE_LIMIT = 40        # 값은 여기서 자른다 — 계좌번호·긴 적요가 통째로 남지 않게
# 값을 적는 input 종류의 허용 목록. 비밀번호·파일 칸은 여기 없으므로 값이 남지 않는다(JS 와 같은 목록).
SAFE_VALUE_TYPES = {"", "text", "number", "tel", "search", "email", "url", "date", "datetime-local",
                    "month", "week", "time", "hidden", "checkbox", "radio", "button", "submit", "reset", "image"}
PER_FRAME_LIMIT = 400   # 프레임 하나에 이보다 많으면 '… 외 N개'


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
        url = fr.url or ""
    except Exception:  # noqa: BLE001
        url = "?"
    data["url"] = url
    return data


def capture(context, frame_kind: Callable[[object], str] | None = None) -> list[dict]:
    """열린 모든 창의 모든 프레임을 읽는다. frame_kind 는 프레임을 알아본 이름('결의서 목록' 등)."""
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


def format_report(windows: list[dict], when: str | None = None) -> str:
    when = when or time.strftime("%Y-%m-%d %H:%M")
    out = [
        f"COSS 업무데스크 화면 구조  ({when})",
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
            elements = fr.get("elements", [])
            shown = [e for e in elements if e.get("visible")]
            hidden = [e for e in elements if not e.get("visible")]
            out.append(f"    요소 {len(elements)}개 (보임 {len(shown)} · 숨김 {len(hidden)})")
            for line in _grid_lines(fr.get("grids", [])):
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
