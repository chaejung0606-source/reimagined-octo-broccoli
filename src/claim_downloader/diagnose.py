"""진단 모드 — ERP 의 아무 화면이나 띄운 상태에서 열린 창·프레임과 입력 요소를 글로 남긴다.

새 화면(일반청구 · 카드청구 작성)을 자동화하기 전에 **실측**하는 도구다. Claude 는 ERP 에 들어갈 수
없으므로(로그인은 사람), 담당자가 원하는 화면을 띄우고 [화면 구조 저장] 을 누르면 이 파일이
~/.claim-downloader/_화면구조.txt 로 남고, 그것을 받아 CLAUDE.md 에 화면 구조 절을 쓴다.

**읽기만 한다.** 아무것도 누르거나 값을 넣지 않는다 — tests/test_safety.py 가 이 JS 에 click · submit ·
값 대입 · 이벤트 발생이 없는지 본다. 비밀번호 칸의 값은 기록하지 않고(값을 읽는 칸 종류를 허용 목록으로 둔다), 다른 값도 40자에서 자른다.
결과 파일은 .gitignore 와 배포 zip(make_bundle.NEVER_PACK_NAMES)에서 제외된다 — 계좌번호 같은 값이
들어 있을 수 있다. 담당자에게는 **빈 작성 화면**에서 돌리라고 안내한다.

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
  const out = [];
  document.querySelectorAll('input,select,textarea,button,a,[role=button],[onclick]').forEach(e => {
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
  return {title: document.title || '', elements: out};
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
    flags = [f for f, on in (("비활성", el.get("disabled")), ("읽기전용", el.get("readonly"))) if on]
    if flags:
        parts.append("[" + " · ".join(flags) + "]")
    return "  ".join(parts)


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
