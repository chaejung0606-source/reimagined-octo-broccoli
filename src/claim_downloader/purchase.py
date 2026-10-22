"""구매요청(계약) 서류 받기 — ERP 구매·자산 메뉴에서 구매요청 때 올린 첨부 · 검사처리 때 올린 첨부 · 물품 사진을 받아 과제별 폴더에 둔다.

담당자(2026-10-22): "구매요청시 업로드한 서류와 검사처리시 업로드한 서류" 둘을, "상태 상관없이 첨부문서가 있다면", 물품 사진도("물품등록할 경우 물품사진을
다운받을 수 있습니다"), ERP 에서 과제를 고르지 않고 구매·자산 메뉴로 바로 들어가 **앱에서 고른 과제의 과제기간**으로 일자 범위를 두고(2년씩 —
"구매요청일자는 최대2년까지 가능함" · 실제 [검색] 처리기 `fn_validation` 이 730일을 넘으면 알림), 받은 것은 **과제별로** `구매요청(계약) 서류\\` 아래에.
실측은 CLAUDE.md 23절(2026-10-22 1 · 2 · 9~12 · 14 · 15 · 18 · 19번) — 값의 이름은 거기서 가져왔다:

- 구매진행관리 목록 `rexpe_0155_01.act`(IBSheet 8 — TreeGrid 바탕): 줄은 `IBSheet[0].getDataRows()`, 값은 `getValue(줄, 열)`, 열은 `PURCH_REQ_NO` 구매요구번호 ·
  `PRJ_NO` 대표과제번호 · `REQ_DT` 요청일자 · `PURCH_CONT` 내용(대표건명) · `PURCH_PROG_STS_NM` 진행상태 · `PURCH_KIND_NM` 구분 · `PURCH_AMT` 구매요구액 ·
  `CONT_NO` · `CONT_PROG_STS_NM` · `chk` 선택. [상세조회/변경](`#btnDetail`)의 처리기는 `sheet.getRowsByChecked("chk")` 가 **하나**일 때 그 건의 상세
  (구매요구서작성 `rexpe_0156_01.act`, `#PROC_TYP_CD`=C10)를 **같은 프레임 자리**에 띄운다(19번 실측) — 그래서 그 줄의 `chk` 만 1 로 두고 단추를 누른다.
  상세의 증빙문서는 `a[href*="comm0008_01.act"][href*="ATTFILE_SEQ_NO"]` 링크(글자 = 파일 이름, PDF · xlsx …). `#btnList` 로 목록으로 돌아온다.
- 검사처리 `rexpe_0201_01.act`(JGM 그리드): 줄마다 `k_PURCH_REQ_NO` · `k_CONT_NM` · `k_CONT_DT` · 행 라디오. 줄을 고르면 아래 숨은 `#PURCH_REQ_NO` ·
  `#PRJ_NO` 가 채워지고 첨부 표의 `a.btn_lnk` 링크(같은 주소 모양) · 물품정보 표(`k_CONT_ITEM_NM_KR`)가 보인다. 물품정보 줄을 **더블클릭**하면
  물품내역팝업(`rexpe_0054_t01_02.act`, 별도 창) — 숨은 `#IMGFILE_SEQ_NO` · `#IMGFILE_SEQ_NO2` 와 `<img id="USER_PICTURE" src="/comm0008_01.act?…&PROC_CD=preview">`
  (둘째 사진이 없으면 `img_noimage.png`). 사진은 그 주소를 같은 묶음의 쿠키로 바로 받는다(오른쪽 클릭 저장 대신).
- 파일은 `page.request.get(주소)`(같은 브라우저 묶음의 쿠키)로 받아 **이름 그대로** 둔다. 같은 이름이 이미 있으면 받지 않는다(이것이 중복 방지 —
  문서번호 같은 열쇠가 없다). 출력물([구매요청서])은 받지 않는다(담당자).

**누르는 것**(tests/test_safety.py): 위 메뉴 `#menu_id_3` '구매·자산' · 왼쪽 메뉴 글자 '구매진행관리' · '검사처리' · 위쪽 탭 '구매진행관리' · '검사처리' ·
목록 [검색](`#btnSearch`) · 줄의 `chk`(IBSheet setValue — 선택 칸뿐) · [상세조회/변경](`#btnDetail`) · [진행관리목록](`#btnList`) · 검사처리 줄의 라디오 ·
물품정보 줄 더블클릭. 값을 넣는 칸은 조회 조건의 일자(`#START_DATE` · `#END_DATE`)뿐. 등록 · 삭제 · 저장 · 구매요청 · 취소 · 검사처리(취소) · 완료 ·
첨부 추가/삭제 · 사진등록/삭제 · [구매진행상세] · [구매요청서] 는 누르지 않는다. Playwright 를 들여오지 않는다(브라우저를 띄우는 곳은 session.py 하나) —
프레임 · 창 객체의 evaluate · dblclick · request 만 쓴다. Qt 없음.
"""
from __future__ import annotations

import datetime as dt
import mimetypes
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin

from . import naming, navigate, project_folders, settings

KIND = "purchase"                      # 받기 표의 줄 종류 — 청구서 줄과 섞여 들어간다(session.download 가 가른다)
FOLDER_NAME = "구매요청(계약) 서류"     # 저장 폴더 바로 아래, 과제 폴더 옆(담당자가 만들어 둔 이름)
INSPECT_DIR = "검사처리"               # 건 폴더 안 — 검사처리 때 올린 첨부 · 물품 사진
MAX_DAYS = 730                         # 구매요청일자 조회 한도(실측 19번 fn_validation: dayLimit = 730)
LIST_TRIES = 40                        # 0.5초씩 — 메뉴를 누른 뒤 목록 · 상세 · 검사처리 화면이 뜨기를 기다리는 횟수
SETTLE_TRIES = 30                      # [검색] 뒤 줄 수가 두 번 연달아 같을 때까지
POPUP_TIMEOUT_MS = 8000
NAME_ROOM = 120                        # 파일 이름 · 건 폴더 이름의 글자 한도(경로 260 안에 들게)

# ── 날짜 · 폴더 (Qt · 브라우저 없이) ─────────────────────────────────────────


def _date(text: str) -> dt.date | None:
    digits = re.sub(r"\D", "", str(text or ""))
    if len(digits) < 8:
        return None
    try:
        return dt.date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
    except ValueError:
        return None


def iso(text: str) -> str:
    """'20260617' · '2026-06-17' · '2026.06.17' → '2026-06-17'. 못 읽으면 ''."""
    d = _date(text)
    return d.isoformat() if d else ""


def req_date(req_no: str) -> str:
    """구매요구번호 앞 8자리는 요청일(실측 10번: 202606170005 ↔ REQ_DT 2026-06-17)."""
    return iso(str(req_no or "")[:8]) if re.match(r"\d{8}", str(req_no or "")) else ""


def span(projects: list, today: dt.date | None = None) -> tuple[str, str] | None:
    """고른 과제들의 과제기간을 합친 범위 — 가장 이른 시작일 ~ 가장 늦은 종료일(오늘을 넘지 않게). 기간을 아는 과제가 없으면 None."""
    today = today or dt.date.today()
    starts = [d for d in (_date(getattr(p, "start", "")) for p in projects) if d]
    ends = [d for d in (_date(getattr(p, "end", "")) for p in projects) if d]
    if not starts or not ends:
        return None
    end = min(max(ends), today)
    start = min(starts)
    if start > end:
        return None
    return start.isoformat(), end.isoformat()


def windows(start: str, end: str, max_days: int = MAX_DAYS) -> list[tuple[str, str]]:
    """범위를 max_days 일 이하 창으로 나눈다 — 구매요청일자는 한 번에 2년까지만 조회된다."""
    a, b = _date(start), _date(end)
    if not a or not b or a > b:
        return []
    out = []
    while a <= b:
        e = min(a + dt.timedelta(days=max_days - 1), b)
        out.append((a.isoformat(), e.isoformat()))
        a = e + dt.timedelta(days=1)
    return out


def window_for(day: str, start: str, end: str) -> tuple[str, str] | None:
    """그 날이 든 창(없으면 None)."""
    d = _date(day)
    for s, e in windows(start, end):
        if d and _date(s) <= d <= _date(e):
            return s, e
    return None


def _trim(text: str, room: int) -> str:
    text = naming.safe_name(text)
    return text if len(text) <= room else text[: max(room - 1, 1)].rstrip() + "…"


def case_dir_name(req_no: str, title: str, req_dt: str = "") -> str:
    """건 폴더 이름 `(YYMMDD) 대표건명_(구매요구번호)`. 날짜는 요청일자, 없으면 구매요구번호 앞 8자리."""
    day = iso(req_dt) or req_date(req_no)
    stamp = day[2:4] + day[5:7] + day[8:10] if day else "날짜모름"
    tail = f"_({req_no})"
    return f"({stamp}) " + _trim(title or "제목 없음", NAME_ROOM - len(tail) - 9) + tail


def google_drive_folders() -> list[Path]:
    """PC 의 구글 드라이브 데스크톱 '내 드라이브' 폴더 후보 — 있으면 구매 서류 저장 위치로 권한다(담당자 2026-10-22).
    드라이브 데스크톱은 보통 G: 같은 새 드라이브 글자 아래 '내 드라이브'(영문판 'My Drive')를 만든다. 옛 판은 사용자 폴더의 'Google Drive'."""
    names = ("내 드라이브", "My Drive")
    found: list[Path] = []
    if os.name == "nt":
        for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
            for name in names:
                p = Path(f"{letter}:\\") / name
                try:
                    if p.is_dir():
                        found.append(p)
                except OSError:
                    pass
    home = Path.home()
    for p in (home / "Google Drive" / "내 드라이브", home / "Google Drive" / "My Drive", home / "Google Drive",
              home / "내 드라이브", home / "My Drive"):
        try:
            if p.is_dir() and p not in found:
                found.append(p)
        except OSError:
            pass
    return found


def purchase_home(out_root: str | Path) -> Path:
    """구매 서류의 맨 위 폴더 — 설정 purchase_root 가 있으면 그것, 없으면 저장 폴더 아래 '구매요청(계약) 서류'."""
    chosen = (getattr(settings.load(), "purchase_root", "") or "").strip()
    if chosen:
        return Path(chosen)
    root = Path(out_root)
    return (root.parent if project_folders.project_of(root) else root) / FOLDER_NAME


def project_base(out_root: str | Path, project_no: str) -> tuple[Path | None, str]:
    """그 과제의 구매 서류를 둘 과제 폴더 — `<저장 폴더>/구매요청(계약) 서류/<과제 폴더 이름 그대로>`. 과제 폴더가 없으면 (None, 까닭).
    저장 폴더 자체가 과제 폴더면 그 위에 둔다. 과제 폴더를 새로 만들지는 않는다(22절과 같은 규칙 — 담당자가 만든 과제만)."""
    project = re.sub(r"\D", "", str(project_no or ""))
    root = Path(out_root)
    if not project:
        return None, "어느 과제의 건인지 몰라(대표과제번호 없음) 받지 않았습니다"
    own = project_folders.project_of(root)
    if own:
        if project != own:
            return None, f"저장 폴더가 다른 과제({own})의 폴더라 과제 {project} 의 서류는 받지 않았습니다"
        return purchase_home(root) / root.name, ""
    mine = project_folders.by_project(root).get(project, [])
    if len(mine) == 1:
        return purchase_home(root) / mine[0].path.name, ""
    if mine:
        return None, f"과제 {project} 의 폴더가 {len(mine)}개라 받지 않았습니다 — 하나만 남기세요"
    return None, f"저장 폴더에 과제 {project} 의 폴더가 없어 받지 않았습니다 — 받으려면 '({project})_…' 폴더를 만드세요"


def case_dir(out_root: str | Path, project_no: str, req_no: str, title: str, req_dt: str = "") -> tuple[Path | None, str]:
    """건 폴더 — 이미 같은 구매요구번호로 끝나는 폴더가 있으면(대표건명이 바뀌었어도) 그것을 쓴다."""
    base, why = project_base(out_root, project_no)
    if base is None:
        return None, why
    if base.is_dir():
        for child in sorted(base.iterdir()):
            if child.is_dir() and child.name.endswith(f"_({req_no})"):
                return child, ""
    return base / case_dir_name(req_no, title, req_dt), ""


def existing_files(folder: Path | None) -> int:
    """건 폴더(검사처리 하위 포함)에 이미 있는 파일 수 — 표의 '폴더 있음' 표시용."""
    if folder is None or not folder.is_dir():
        return 0
    return sum(1 for p in folder.rglob("*") if p.is_file())


def file_name(name: str, fallback: str = "파일") -> str:
    """링크 글자를 파일 이름으로 — 금지문자는 공백, 너무 길면 줄인다(확장자는 남김)."""
    clean = naming.safe_name(name) or fallback
    if len(clean) <= NAME_ROOM:
        return clean
    stem, dot, ext = clean.rpartition(".")
    if dot and len(ext) <= 5:
        return stem[: NAME_ROOM - len(ext) - 2].rstrip() + "…." + ext
    return clean[: NAME_ROOM - 1].rstrip() + "…"


def photo_name(item: str, index: int, content_type: str) -> str:
    ext = mimetypes.guess_extension((content_type or "").split(";")[0].strip()) or ".jpg"
    ext = {".jpe": ".jpg", ".jpeg": ".jpg"}.get(ext, ext)
    return f"물품사진_{_trim(item or '물품', 60)}_{index}{ext}"


# ── 화면 스크립트(읽기 · 허용된 누르기만) ─────────────────────────────────────

# 프레임 알아보기 — 주소가 아니라 내용으로(6절). 구매진행관리 목록 · 구매요구서작성(상세) · 검사처리.
LIST_PROBE_JS = """() => !!document.getElementById('btnDetail') && !!document.getElementById('START_DATE')
  && !!document.getElementById('SEARCH_PURCH_REQ_NO') && !!document.querySelector('.SheetMain')"""
DETAIL_PROBE_JS = """() => { const p = document.getElementById('PROC_TYP_CD');
  return !!p && String(p.value) === 'C10' && !!document.getElementById('PURCH_REQ_NO') && !!document.getElementById('btnList'); }"""
INSPECT_PROBE_JS = """() => !!document.getElementById('btnPunch') && !!document.getElementById('DLVR_DT') && !!document.getElementById('START_DATE')"""
VISIBLE_JS = """() => { try { const f = window.frameElement; if (!f) return true;
  const r = f.getBoundingClientRect(); return r.width > 0 && r.height > 0; } catch (e) { return true; } }"""

# 위 메뉴 '구매·자산'(틀 프레임 #menu_id_3 — 실측 1번 · 10:54). 메인화면에서 바로 들어간다(담당자: 과제를 고르지 않는다).
MENU_JS = """() => {
  const m = document.getElementById('menu_id_3');
  const t = m ? (m.innerText || m.textContent || '').replace(/[\\s·ㆍ]/g, '') : '';
  if (!m || t !== '구매자산') return {ok: false, why: "위 메뉴 '구매·자산' 을 찾지 못함"};
  m.click();
  return {ok: true};
}"""
# 구매 화면 안의 왼쪽 메뉴 글자('구매진행관리' · '검사처리' — a, href=javascript:, id 없음). 보이는 것이 하나일 때만.
LEFT_MENU_JS = """(text) => {
  const txt = e => (e.innerText || e.textContent || '').replace(/\\s+/g, ' ').trim();
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const hits = Array.from(document.querySelectorAll('a')).filter(a => txt(a) === text && vis(a));
  if (hits.length !== 1) return {ok: false, why: hits.length ? `왼쪽 메뉴 '${text}' 가 여럿` : `왼쪽 메뉴 '${text}' 가 보이지 않음`};
  hits[0].click();
  return {ok: true};
}"""
# 위쪽 탭(a.mul_txt)을 앞으로 — 숨은 탭의 JGM 그리드는 줄이 안 그려진다(7절 11번). 글자가 정확히 같은 보이는 탭 하나만.
TOP_TAB_JS = """(text) => {
  const txt = e => (e.innerText || e.textContent || '').replace(/\\s+/g, ' ').trim();
  const shown = Array.from(document.querySelectorAll('a.mul_txt')).filter(a => {
    const r = a.getBoundingClientRect(); return txt(a) === text && r.width > 0 && r.height > 0; });
  if (shown.length !== 1) return {ok: false, why: `위쪽 '${text}' 탭이 하나가 아님`};
  shown[0].click();
  return {ok: true};
}"""
# 조회 조건의 일자 둘(구매진행관리 구매요청일자 · 검사처리 계약일자 — 둘 다 #START_DATE · #END_DATE). 값을 넣는 칸은 이 둘뿐.
SET_RANGE_JS = """([start, end]) => {
  const a = document.getElementById('START_DATE'), b = document.getElementById('END_DATE');
  if (!a || !b) return {ok: false, why: '일자 칸이 없음'};
  for (const [el, v] of [[a, start], [b, end]]) {
    el.value = v;
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
  }
  return {ok: true, start: String(a.value || ''), end: String(b.value || '')};
}"""
RANGE_JS = """() => { const v = id => { const e = document.getElementById(id); return e ? String(e.value || '') : ''; };
  return {start: v('START_DATE'), end: v('END_DATE')}; }"""
SEARCH_JS = """() => {
  const b = document.getElementById('btnSearch');
  if (!b) return {ok: false, why: '[검색] 단추가 없음'};
  b.click();
  return {ok: true};
}"""
# IBSheet 8 목록 읽기(읽기만) — getDataRows · getValue · getText(실측 19번: 이 둘로 25줄 · 30열이 읽혔다)
SHEET_ROWS_JS = """() => {
  const s = window.IBSheet && window.IBSheet[0];
  if (!s || typeof s.getDataRows !== 'function') return null;
  let rows; try { rows = s.getDataRows(); } catch (e) { return null; }
  if (!Array.isArray(rows)) return null;
  const get = (r, c) => { try { const v = s.getValue(r, c); return v === null || v === undefined ? '' : String(v); } catch (e) { return ''; } };
  const txt = (r, c) => { try { if (typeof s.getText === 'function') { const v = s.getText(r, c); if (v !== null && v !== undefined && String(v)) return String(v); } }
                          catch (e) {} return get(r, c); };
  return rows.map(r => ({req_no: get(r, 'PURCH_REQ_NO'), prj_no: get(r, 'PRJ_NO'), req_dt: txt(r, 'REQ_DT'), title: get(r, 'PURCH_CONT'),
                         state: get(r, 'PURCH_PROG_STS_NM'), kind: get(r, 'PURCH_KIND_NM'), amount: get(r, 'PURCH_AMT'),
                         cont_no: get(r, 'CONT_NO'), cont_state: get(r, 'CONT_PROG_STS_NM'), seq: get(r, 'ROW_SEQ'), prj_nm: get(r, 'PRJ_NM')}));
}"""
SHEET_SIGNATURE_JS = """() => {
  const s = window.IBSheet && window.IBSheet[0];
  if (!s || typeof s.getDataRows !== 'function') return '';
  try { const rows = s.getDataRows(); if (!Array.isArray(rows)) return '';
        const no = r => { try { return String(s.getValue(r, 'PURCH_REQ_NO') || ''); } catch (e) { return ''; } };
        return rows.length + '|' + (rows.length ? no(rows[0]) + '|' + no(rows[rows.length - 1]) : ''); } catch (e) { return ''; }
}"""
# 그 구매요구번호 줄의 선택 칸(chk)만 체크하고 [상세조회/변경] — 단추의 처리기가 체크된 줄 하나를 상세로 띄운다(실측 19번 btnDetail_click).
PICK_DETAIL_JS = """(no) => {
  const s = window.IBSheet && window.IBSheet[0];
  if (!s || typeof s.getDataRows !== 'function' || typeof s.setValue !== 'function') return {ok: false, why: 'IBSheet 목록을 읽지 못함'};
  const rows = s.getDataRows();
  const hit = rows.filter(r => String(s.getValue(r, 'PURCH_REQ_NO') || '') === String(no));
  if (hit.length !== 1) return {ok: false, why: hit.length ? '같은 구매요구번호 줄이 여럿' : '목록에 그 구매요구번호 줄이 없음'};
  rows.forEach(r => { if (r !== hit[0] && Number(s.getValue(r, 'chk')) === 1) s.setValue(r, 'chk', 0, 1); });
  s.setValue(hit[0], 'chk', 1, 1);
  const checked = typeof s.getRowsByChecked === 'function' ? s.getRowsByChecked('chk') : [hit[0]];
  if (!Array.isArray(checked) || checked.length !== 1 || checked[0] !== hit[0]) return {ok: false, why: '선택 칸이 체크되지 않음'};
  const b = document.getElementById('btnDetail');
  const t = b ? (b.innerText || b.textContent || '').replace(/\\s+/g, '') : '';
  if (!b || !t.startsWith('상세조회')) return {ok: false, why: '[상세조회/변경] 단추를 찾지 못함'};
  b.click();
  return {ok: true};
}"""
# 구매요구서작성(상세) — 숨은 값과 증빙문서 링크(글자 = 파일 이름). 읽기만.
DETAIL_JS = """() => {
  const v = id => { const e = document.getElementById(id); return e ? String(e.value || '') : ''; };
  const txt = e => (e.innerText || e.textContent || '').replace(/\\s+/g, ' ').trim();
  const files = [];
  document.querySelectorAll('a[href*="comm0008_01.act"][href*="ATTFILE_SEQ_NO"]').forEach(a => {
    const name = txt(a); const href = a.getAttribute('href') || '';
    if (name && href && !files.some(f => f.href === href)) files.push({name, href});
  });
  return {req_no: v('PURCH_REQ_NO'), prj_no: v('PRJ_NO'), req_dt: v('REQ_DT'), title: v('PURCH_CONT'), state: v('PURCH_PROG_STS_NM'), files};
}"""
LIST_BACK_JS = """() => {
  const b = document.getElementById('btnList');
  const t = b ? (b.innerText || b.textContent || '').replace(/\\s+/g, '') : '';
  if (!b || !t.includes('목록')) return {ok: false, why: '[진행관리목록] 단추를 찾지 못함'};
  b.click();
  return {ok: true};
}"""
# 검사처리 계약 건 목록(JGM) — 구매요구번호 칸이 있는 줄만(재원 · 첨부 · 물품정보 표는 없다). 가상 스크롤이라 보이는 줄만 그려진다.
INSPECT_ROWS_JS = """() => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const out = [];
  document.querySelectorAll('.jgrid-row').forEach(el => {
    if (!el.querySelector('.k_PURCH_REQ_NO') || !vis(el)) return;
    const c = k => { const d = el.querySelector('.k_' + k); if (!d) return '';
      const t = d.getAttribute('title'); return (t && t.trim()) ? t.trim() : (d.textContent || '').trim(); };
    out.push({r: el.getAttribute('r'), req_no: c('PURCH_REQ_NO').replace(/\\D/g, ''), cont_nm: c('CONT_NM'), cont_dt: c('CONT_DT'),
              cont_no: c('CONT_NO'), state: c('CONT_PROG_STS_NM'), prj_nm: c('PRJ_NM'), seq: c('ROW_SEQ')});
  });
  return out;
}"""
INSPECT_SCROLL_JS = """(how) => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const v = Array.from(document.querySelectorAll('.jgrid-viewport')).find(e => vis(e) && e.querySelector('.k_PURCH_REQ_NO'));
  if (!v) return null;
  if (how === 'top') v.scrollTop = 0;
  else if (how === 'next') v.scrollTop = Math.min(v.scrollHeight, v.scrollTop + Math.max(40, v.clientHeight - 60));
  return {top: v.scrollTop, h: v.clientHeight, sh: v.scrollHeight};
}"""
# 검사처리 줄 고르기 — 그 줄(r)의 라디오(이름은 그리드를 다시 그리면 바뀐다 — radioJGM5 로 고정하지 않는다)
INSPECT_PICK_JS = """(r) => {
  const vis = e => { const b = e.getBoundingClientRect(); return b.width > 0 && b.height > 0; };
  const row = Array.from(document.querySelectorAll('.jgrid-row')).find(e => vis(e) && e.querySelector('.k_PURCH_REQ_NO') && String(e.getAttribute('r')) === String(r));
  if (!row) return {ok: false, why: '그 줄이 화면에 없음'};
  const box = row.querySelector('input[type=radio]');
  if (!box) return {ok: false, why: '줄에 선택 칸이 없음'};
  box.click();
  return {ok: true};
}"""
INSPECT_SELECTED_JS = """() => { const v = id => { const e = document.getElementById(id); return e ? String(e.value || '') : ''; };
  return {req_no: v('PURCH_REQ_NO').replace(/\\D/g, ''), prj_no: v('PRJ_NO').replace(/\\D/g, ''), cont_seq: v('CONT_SEQ_NO')}; }"""
# 고른 건의 첨부 표 링크(a.btn_lnk, 실측 11번) — 줄의 증빙구분(select)도 함께. 읽기만.
INSPECT_FILES_JS = """() => {
  const txt = e => (e.innerText || e.textContent || '').replace(/\\s+/g, ' ').trim();
  const files = [];
  document.querySelectorAll('a[href*="comm0008_01.act"][href*="ATTFILE_SEQ_NO"]').forEach(a => {
    const name = txt(a); const href = a.getAttribute('href') || '';
    if (!name || !href || files.some(f => f.href === href)) return;
    const row = a.closest('.jgrid-row, tr');
    const sel = row ? row.querySelector('select') : null;
    const kind = sel && sel.options[sel.selectedIndex] ? txt(sel.options[sel.selectedIndex]) : '';
    files.push({name, href, kind});
  });
  return files;
}"""
# 고른 건의 물품정보 표 줄(JGM, k_CONT_ITEM_NM_KR) — 더블클릭해 물품내역팝업을 연다(담당자 2026-10-22). 읽기만.
ITEMS_JS = """() => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const out = [];
  document.querySelectorAll('.jgrid-row').forEach(el => {
    const d = el.querySelector('.k_CONT_ITEM_NM_KR'); if (!d || !vis(el)) return;
    const t = d.getAttribute('title'); const name = (t && t.trim()) ? t.trim() : (d.textContent || '').trim();
    const no = el.querySelector('.k_ITEM_VIEW_NO');
    out.push({r: el.getAttribute('r'), name, view_no: no ? (no.textContent || '').trim() : ''});
  });
  return out;
}"""
ITEM_ROW_SELECTOR = '.jgrid-row[r="{r}"] .k_CONT_ITEM_NM_KR'
# 물품내역팝업 — 사진 번호 · 그림 주소(실측 12 · 15번). 읽기만.
POPUP_JS = """() => {
  const v = id => { const e = document.getElementById(id); return e ? String(e.value || '') : ''; };
  const src = id => { const e = document.getElementById(id); return e ? String(e.getAttribute('src') || '') : ''; };
  if (!document.getElementById('IMGFILE_SEQ_NO') && !document.getElementById('USER_PICTURE')) return null;
  return {item: v('ITEM_NM') || v('CONT_ITEM_NM_KR'), seq1: v('IMGFILE_SEQ_NO'), seq2: v('IMGFILE_SEQ_NO2'),
          src1: src('USER_PICTURE'), src2: src('USER_PICTURE2')};
}"""


# ── 결과 ───────────────────────────────────────────────────────────────────


@dataclass
class CaseResult:
    req_no: str
    title: str = ""
    project: str = ""
    folder: str = ""
    saved: list[str] = field(default_factory=list)       # 이번에 받은 파일 이름(검사처리 것은 '검사처리/…')
    existed: int = 0                                      # 이미 있어 받지 않은 파일 수
    failed: list[str] = field(default_factory=list)      # 못 받은 파일 — '이름: 까닭'
    photos: int = 0
    inspected: bool = False                               # 검사처리 화면에서 이 건을 봤는지
    note: str = ""                                        # 건 전체의 까닭(과제 폴더 없음 · 상세를 못 띄움 …)
    ok: bool = True

    def summary(self) -> str:
        parts = []
        if self.saved:
            parts.append(f"새 파일 {len(self.saved)}개")
        if self.existed:
            parts.append(f"이미 있음 {self.existed}개")
        if self.photos:
            parts.append(f"물품 사진 {self.photos}장")
        if not self.saved and not self.existed and not self.failed and self.ok:
            parts.append("첨부 없음")
        if self.failed:
            parts.append(f"못 받음 {len(self.failed)}개")
        if self.note:
            parts.append(self.note)
        return " · ".join(parts)


@dataclass
class PurchaseSummary:
    cases: list[CaseResult] = field(default_factory=list)
    inspected_rows: int = 0            # 검사처리에서 본 계약 건 수(고른 과제 밖 포함)
    stopped: bool = False
    note: str = ""                     # 검사처리를 못 연 까닭 등

    @property
    def ok(self) -> int:
        return sum(1 for c in self.cases if c.ok)

    @property
    def failed(self) -> list[CaseResult]:
        return [c for c in self.cases if not c.ok]

    @property
    def files(self) -> int:
        return sum(len(c.saved) for c in self.cases)


def as_target(row: dict, folder: Path | None = None) -> dict:
    """목록 줄 → 받기 표의 줄(청구서 줄과 같은 칸 이름을 쓴다: no · expDt · cont · amt · gubun · project)."""
    req_dt = iso(row.get("req_dt", "")) or req_date(row.get("req_no", ""))
    state = row.get("state") or ""
    gubun = "구매요청" + (f"({row['kind']})" if row.get("kind") else "") + (f" · {state}" if state else "")
    return {"kind": KIND, "req_no": str(row.get("req_no") or ""), "project": re.sub(r"\D", "", str(row.get("prj_no") or "")),
            "no": str(row.get("seq") or ""), "expDt": req_dt, "cont": str(row.get("title") or ""),
            "amt": re.sub(r"[^0-9\-]", "", str(row.get("amount") or "")), "gubun": gubun, "state": state,
            "cont_state": str(row.get("cont_state") or ""), "docNo": "", "existing": existing_files(folder)}


# ── 브라우저 쪽(프레임 · 창 객체는 받아서만 쓴다) ────────────────────────────


def _frames(context):
    for page in list(getattr(context, "pages", []) or []):
        try:
            if page.is_closed():
                continue
        except Exception:  # noqa: BLE001
            pass
        for frame in list(getattr(page, "frames", []) or []):
            yield page, frame


def _eval(frame, js, *args):
    try:
        return frame.evaluate(js, *args)
    except Exception:  # noqa: BLE001 — 그리는 중 · 바뀌는 중
        return None


def _find(context, probe_js: str):
    """probe 가 참인 프레임 — 보이는 것 먼저. 없으면 None."""
    found = []
    for _page, frame in _frames(context):
        if _eval(frame, probe_js) is True:
            found.append((0 if _eval(frame, VISIBLE_JS) is True else 1, frame))
    return sorted(found, key=lambda pair: pair[0])[0][1] if found else None


def list_frame(context):
    return _find(context, LIST_PROBE_JS)


def detail_frame(context):
    return _find(context, DETAIL_PROBE_JS)


def inspect_frame(context):
    return _find(context, INSPECT_PROBE_JS)


def _wait_for(check: Callable[[], object], wait: Callable[[float], None], tries: int, step: float = 0.5):
    for _ in range(tries):
        got = check()
        if got:
            return got
        wait(step)
    return check()


def _click_any(context, js: str, *args) -> tuple[bool, str]:
    why = ""
    for _page, frame in _frames(context):
        got = _eval(frame, js, *args) or {}
        if got.get("ok"):
            return True, ""
        why = got.get("why") or why
    return False, why or "그 단추를 찾지 못함"


def show_tab(context, text: str, log: Callable[[str], None]) -> None:
    ok, _why = _click_any(context, TOP_TAB_JS, text)
    if ok:
        log(f"위쪽 '{text}' 탭을 앞으로 가져옵니다")


def open_list(context, log: Callable[[str], None], wait: Callable[[float], None]):
    """구매진행관리 목록 프레임 — 이미 있으면 그대로(상세가 떠 있으면 [진행관리목록] 으로), 없으면 위 메뉴 '구매·자산' 으로 연다."""
    frame = list_frame(context)
    if frame is not None:
        return frame, ""
    detail = detail_frame(context)
    if detail is not None:
        frame = back_to_list(context, detail, log, wait)
        if frame is not None:
            return frame, ""
    ok, why = _click_any(context, LEFT_MENU_JS, "구매진행관리")      # 검사처리 화면이 떠 있으면 그 왼쪽 메뉴로
    if ok:
        log("왼쪽 메뉴 '구매진행관리' 를 눌렀습니다")
    else:
        ok, why = _click_any(context, MENU_JS)
        if not ok:
            if navigate.logged_out(context):
                return None, "ERP 에 로그인돼 있지 않습니다 — 브라우저에서 로그인한 뒤 다시 하세요"
            return None, f"구매·자산 메뉴로 들어가지 못했습니다({why}) — 로그인했는지 보고, 메인화면이 보이게 한 뒤 다시 하세요"
        log("위 메뉴 '구매·자산' 을 눌렀습니다 (과제는 고르지 않습니다 — 담당자 2026-10-22)")
    frame = _wait_for(lambda: list_frame(context), wait, LIST_TRIES)
    if frame is None:
        return None, "구매·자산 메뉴를 눌렀지만 구매진행관리 목록이 뜨지 않았습니다 — 브라우저에서 구매진행관리를 띄운 뒤 다시 하세요"
    return frame, ""


def current_range(frame) -> tuple[str, str]:
    got = _eval(frame, RANGE_JS) or {}
    return iso(got.get("start", "")), iso(got.get("end", ""))


def search(frame, start: str, end: str, log: Callable[[str], None], wait: Callable[[float], None], what: str = "구매요청일자") -> tuple[bool, str]:
    """일자 범위를 넣고 [검색] — 목록이 다시 그려져 줄 수가 두 번 연달아 같을 때까지 기다린다. (됐는지, 까닭)."""
    before = _eval(frame, SHEET_SIGNATURE_JS) or ""
    got = _eval(frame, SET_RANGE_JS, [start, end]) or {}
    if not got.get("ok"):
        return False, got.get("why") or "일자 칸을 넣지 못함"
    if iso(got.get("start", "")) != start or iso(got.get("end", "")) != end:
        return False, f"일자 칸에 값이 남지 않음({got.get('start')} ~ {got.get('end')})"
    got = _eval(frame, SEARCH_JS) or {}
    if not got.get("ok"):
        return False, got.get("why") or "[검색] 을 누르지 못함"
    log(f"{what} {start} ~ {end} 로 [검색]")
    wait(1.0)
    last, same = None, 0
    for _ in range(SETTLE_TRIES):
        now = _eval(frame, SHEET_SIGNATURE_JS) if what == "구매요청일자" else str(len(_eval(frame, INSPECT_ROWS_JS) or []))
        if now == last and (now != before or same >= 2):
            same += 1
            if same >= 2:
                break
        else:
            same = 0
        last = now
        wait(0.5)
    return True, ""


def read_rows(frame) -> list[dict] | None:
    rows = _eval(frame, SHEET_ROWS_JS)
    return rows if isinstance(rows, list) else None


def open_detail(context, frame, req_no: str, log: Callable[[str], None], wait: Callable[[float], None]):
    """그 건의 상세(구매요구서작성) 프레임 또는 (None, 까닭)."""
    got = _eval(frame, PICK_DETAIL_JS, req_no) or {}
    if not got.get("ok"):
        return None, got.get("why") or "상세를 띄우지 못함"

    def ready():
        d = detail_frame(context)
        if d is None:
            return None
        info = _eval(d, DETAIL_JS) or {}
        return d if re.sub(r"\D", "", str(info.get("req_no") or "")) == re.sub(r"\D", "", req_no) else None

    detail = _wait_for(ready, wait, LIST_TRIES)
    if detail is None:
        other = detail_frame(context)
        if other is not None:
            info = _eval(other, DETAIL_JS) or {}
            return None, f"다른 건({info.get('req_no') or '?'})의 상세가 떴습니다"
        return None, "[상세조회/변경] 을 눌렀지만 구매요구서작성 화면이 뜨지 않았습니다"
    return detail, ""


def back_to_list(context, detail, log: Callable[[str], None], wait: Callable[[float], None]):
    got = _eval(detail, LIST_BACK_JS) or {}
    if not got.get("ok"):
        log("⚠ " + (got.get("why") or "[진행관리목록] 을 누르지 못함"))
        return None
    return _wait_for(lambda: list_frame(context), wait, LIST_TRIES)


def fetch(page, url: str):
    """같은 브라우저 묶음의 쿠키로 파일을 받는다 → (bytes, content_type, 까닭). 로그인 화면(HTML)이 오면 받지 않는다."""
    try:
        resp = page.request.get(url, timeout=60000)
    except Exception as error:  # noqa: BLE001
        return None, "", str(error).splitlines()[0][:120] if str(error) else type(error).__name__
    try:
        ctype = str((resp.headers or {}).get("content-type", "")).lower()
        if not resp.ok:
            return None, ctype, f"HTTP {resp.status}"
        body = resp.body()
    except Exception as error:  # noqa: BLE001
        return None, "", str(error).splitlines()[0][:120] if str(error) else type(error).__name__
    if ctype.startswith("text/html") or body[:15].lstrip().lower().startswith((b"<!doctype", b"<html")):
        return None, ctype, "HTML 이 왔습니다(로그인이 풀렸거나 파일이 아님)"
    if not body:
        return None, ctype, "빈 파일"
    return body, ctype, ""


# 실제 ERP(2026-10-22 17:41)에서 page.request.get 이 파일마다 HTML 을 받았다 — 쿠키만으로는 안 되고
# 화면 안에서 부른 요청(같은 출처 · Referer)이어야 주는 것으로 본다. 그래서 그 프레임 안에서 fetch 해 받는다.
FRAME_FETCH_JS = r"""
async (href) => {
  try {
    const r = await fetch(href, {credentials: 'include'});
    const ctype = (r.headers.get('content-type') || '').toLowerCase();
    const buf = new Uint8Array(await r.arrayBuffer());
    const head = String.fromCharCode.apply(null, buf.slice(0, 15)).trim().toLowerCase();
    if (ctype.startsWith('text/html') || head.startsWith('<!doctype') || head.startsWith('<html')) {
      const text = new TextDecoder().decode(buf.slice(0, 4000));
      const m = text.match(/<title[^>]*>([^<]{0,60})/i);
      // 무엇이 왔는지 보려고 form action · 스크립트의 주소 꼴 · 글자 앞부분만 (값은 적지 않는다)
      const act = (text.match(/action=["']([^"'?]{0,60})/i) || [])[1] || '';
      const go = (text.match(/(location[.\w]*\s*=|\.submit\(|window\.open|alert\()/) || [])[1] || '';
      const body = text.replace(/<script[\s\S]*?<\/script>/gi, ' ').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 60);
      return {ok: false, why: 'HTML 이 왔습니다' + (m ? " (제목 '" + m[1].trim() + "')" : '') + ' · HTTP ' + r.status
        + (act ? ' · form ' + act : '') + (go ? ' · ' + go : '') + (body ? " · 글 '" + body + "'" : '')};
    }
    if (!r.ok) return {ok: false, why: 'HTTP ' + r.status};
    if (!buf.length) return {ok: false, why: '빈 파일'};
    let bin = '';
    for (let i = 0; i < buf.length; i += 32768) bin += String.fromCharCode.apply(null, buf.subarray(i, i + 32768));
    return {ok: true, ctype, data: btoa(bin)};
  } catch (e) { return {ok: false, why: String(e).slice(0, 120)}; }
}
"""


def fetch_in(frame, page, url: str):
    """그 화면 안에서 받기 → 안 되면 page.request 로. (bytes, content_type, 까닭)."""
    why_frame = ""
    if frame is not None:
        try:
            got = frame.evaluate(FRAME_FETCH_JS, url) or {}
        except Exception as error:  # noqa: BLE001
            got = {"why": str(error).splitlines()[0][:120] if str(error) else type(error).__name__}
        if got.get("ok"):
            import base64
            return base64.b64decode(got.get("data") or ""), str(got.get("ctype") or ""), ""
        why_frame = str(got.get("why") or "")
    body, ctype, why = fetch(page, url)
    if body is None and why_frame:
        why = f"화면 안에서: {why_frame} · 직접: {why}"
    return body, ctype, why


CLICK_TIMEOUT_MS = 30000


def click_download(frame, page, href: str, dest: Path):
    """주소로 받으면 HTML 이 오는 ERP(2026-10-22 실제) — 사람이 하듯 그 링크를 눌러 내려받는다.
    링크에 붙은 ERP 처리기가 진짜 받기 요청을 만드는 것으로 본다. → (bytes 크기, 까닭)."""
    if frame is None or not href:
        return None, "링크를 누를 화면이 없음"
    link = frame.locator(f'a[href="{href}"]').first
    before = list(page.context.pages)
    try:
        if not link.count():
            return None, "화면에 그 링크가 없음"
        with page.expect_download(timeout=CLICK_TIMEOUT_MS) as got:
            link.click(timeout=5000)
        download = got.value
        fail = download.failure()
        if fail:
            return None, f"내려받기 실패({fail})"
        dest.parent.mkdir(parents=True, exist_ok=True)
        temp = dest.with_name(dest.name + ".part")
        download.save_as(str(temp))
        head = temp.read_bytes()[:15].lstrip().lower()
        if head.startswith((b"<!doctype", b"<html")) or temp.stat().st_size == 0:
            temp.unlink(missing_ok=True)
            return None, "눌러 받아도 HTML 이 왔습니다"
        size = temp.stat().st_size
        temp.replace(dest)
        return size, ""
    except Exception as error:  # noqa: BLE001
        return None, "링크 누르기: " + (str(error).splitlines()[0][:100] if str(error) else type(error).__name__)
    finally:
        # 눌러서 새 창(파일 보기)이 떴으면 닫는다 — ERP 단추가 아니라 창 닫기
        try:
            for extra in page.context.pages:
                if extra not in before and extra is not page:
                    extra.close()
        except Exception:  # noqa: BLE001
            pass


def _save(page, base_url: str, href: str, dest: Path, log: Callable[[str], None], frame=None) -> str:
    """파일 하나 — 'saved' · 'exists' · 'failed: 까닭'. 덮어쓰지 않는다."""
    if dest.exists():
        return "exists"
    body, _ctype, why = fetch_in(frame, page, urljoin(base_url, href))
    if body is None:
        size, click_why = click_download(frame, page, href, dest)
        if size is not None:
            log(f"      ✓ {dest.name} ({size:,} B · 링크를 눌러 받음)")
            return "saved"
        why = f"{why} · {click_why}"
        log(f"      ✖ {dest.name} — {why}")
        return "failed: " + why
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp = dest.with_name(dest.name + ".part")
    temp.write_bytes(body)
    temp.replace(dest)
    log(f"      ✓ {dest.relative_to(dest.parents[1]) if len(dest.parents) > 1 else dest.name} ({len(body):,} B)")
    return "saved"


def _save_files(page, base_url: str, files: list[dict], folder: Path, result: CaseResult, log: Callable[[str], None],
                prefix: str = "", frame=None) -> None:
    for f in files:
        name = file_name(f.get("name", ""))
        dest = folder / name
        got = _save(page, base_url, f.get("href", ""), dest, log, frame)
        if got == "saved":
            result.saved.append(prefix + name)
        elif got == "exists":
            result.existed += 1
        else:
            result.failed.append(f"{prefix}{name}: {got[8:]}")
            result.ok = False


def _frame_url(frame) -> str:
    try:
        return str(frame.url or "")
    except Exception:  # noqa: BLE001
        return ""


def receive_case(context, page, frame, target: dict, out_root: str, log: Callable[[str], None],
                 wait: Callable[[float], None]) -> tuple[CaseResult, object]:
    """구매진행관리 목록에서 한 건 — chk → [상세조회/변경] → 증빙문서 링크 받기 → [진행관리목록]. (결과, 다시 뜬 목록 프레임 또는 None)."""
    req_no = str(target.get("req_no") or "")
    result = CaseResult(req_no, target.get("cont", ""), target.get("project", ""))
    detail, why = open_detail(context, frame, req_no, log, wait)
    if detail is None:
        result.ok, result.note = False, why
        return result, list_frame(context)
    info = _eval(detail, DETAIL_JS) or {}
    project = re.sub(r"\D", "", str(info.get("prj_no") or "")) or result.project
    result.project = project
    result.title = info.get("title") or result.title
    folder, why = case_dir(out_root, project, req_no, result.title, info.get("req_dt") or target.get("expDt", ""))
    if folder is None:
        result.ok, result.note = False, why
        log("      ⚠ " + why)
    else:
        result.folder = str(folder)
        files = info.get("files") or []
        log(f"      구매요구서작성 — 증빙문서 {len(files)}개 → {folder.name}")
        _save_files(page, _frame_url(detail), files, folder, result, log, frame=detail)
    return result, back_to_list(context, detail, log, wait)


def _has_row(frame, req_no: str) -> bool:
    return any(str(r.get("req_no") or "") == str(req_no) for r in (read_rows(frame) or []))


def ensure_range(frame, start: str, end: str, log: Callable[[str], None], wait: Callable[[float], None], req_no: str = "") -> tuple[bool, str]:
    """목록의 일자 범위가 이 범위이고 그 건의 줄이 보일 때까지 — [진행관리목록] 으로 돌아온 목록은 조회 조건을 지닌 채 다시 그려지는 동안 줄이 비어 있다.
    범위가 다르거나 기다려도 줄이 안 보이면 범위를 넣고 [검색]."""
    if current_range(frame) == (start, end):
        if not req_no or _wait_for(lambda: _has_row(frame, req_no), wait, 16):
            return True, ""
    ok, why = search(frame, start, end, log, wait)
    if not ok:
        return False, why
    # [검색] 뒤 목록이 늦게 다시 그려질 수 있다(2026-10-22 18:31 실제: 하루 범위 조회 직후 줄을 못 봄)
    if req_no and not _wait_for(lambda: _has_row(frame, req_no), wait, 16):
        return False, f"{start} ~ {end} 로 조회한 목록에 구매요구 {req_no} 줄이 없음"
    return True, ""


def collect_inspection(frame, wait: Callable[[float], None]) -> list[dict]:
    """검사처리 계약 건 목록을 가상 스크롤을 내리며 전부(구매요구번호 + 줄 번호로 중복 제거)."""
    seen, out = set(), []

    def grab():
        for r in _eval(frame, INSPECT_ROWS_JS) or []:
            key = (r.get("req_no"), r.get("cont_no"), r.get("r"))
            if r.get("req_no") and key not in seen:
                seen.add(key)
                out.append(r)

    _eval(frame, INSPECT_SCROLL_JS, "top")
    grab()
    last = -1
    for _ in range(400):
        info = _eval(frame, INSPECT_SCROLL_JS, "info")
        if not info:
            break
        if info["top"] + info["h"] >= info["sh"] - 5 and info["top"] == last:
            break
        last = info["top"]
        _eval(frame, INSPECT_SCROLL_JS, "next")
        wait(0.25)
        grab()
    return out


def _scroll_to_row(frame, r: str, wait: Callable[[float], None]) -> bool:
    """가상 스크롤 목록에서 줄 r 이 그려질 때까지 내린다."""
    if any(str(x.get("r")) == str(r) for x in (_eval(frame, INSPECT_ROWS_JS) or [])):
        return True
    _eval(frame, INSPECT_SCROLL_JS, "top")
    last = -1
    for _ in range(400):
        if any(str(x.get("r")) == str(r) for x in (_eval(frame, INSPECT_ROWS_JS) or [])):
            return True
        info = _eval(frame, INSPECT_SCROLL_JS, "info")
        if not info or (info["top"] + info["h"] >= info["sh"] - 5 and info["top"] == last):
            break
        last = info["top"]
        _eval(frame, INSPECT_SCROLL_JS, "next")
        wait(0.2)
    return False


def select_inspection(frame, row: dict, wait: Callable[[float], None]) -> tuple[bool, str]:
    if not _scroll_to_row(frame, row.get("r", ""), wait):
        return False, "그 줄을 화면에 못 그림"
    got = _eval(frame, INSPECT_PICK_JS, row.get("r", "")) or {}
    if not got.get("ok"):
        return False, got.get("why") or "줄을 고르지 못함"
    want = re.sub(r"\D", "", str(row.get("req_no") or ""))
    chosen = _wait_for(lambda: (_eval(frame, INSPECT_SELECTED_JS) or {}).get("req_no") == want, wait, 20)
    return (True, "") if chosen else (False, "줄을 골랐지만 아래 칸에 그 건이 채워지지 않음")


def _photo_urls(info: dict) -> list[tuple[int, str]]:
    out = []
    for index, (seq, src) in enumerate(((info.get("seq1"), info.get("src1")), (info.get("seq2"), info.get("src2"))), 1):
        seq = str(seq or "").strip()
        src = str(src or "")
        if not src or "noimage" in src.lower() or not re.search(r"ATTFILE_SEQ_NO=\d+", src, re.I):
            continue
        if seq in ("", "0") and "ATTFILE_SEQ_NO=0" in src:
            continue
        out.append((index, src))
    return out


def item_photos(context, page, frame, item: dict, folder: Path, result: CaseResult, log: Callable[[str], None],
                wait: Callable[[float], None]) -> None:
    """물품정보 줄을 더블클릭해 물품내역팝업을 열고 사진을 받은 뒤 그 창을 닫는다."""
    popup = None
    try:
        with context.expect_page(timeout=POPUP_TIMEOUT_MS) as opened:
            frame.dblclick(ITEM_ROW_SELECTOR.format(r=item.get("r", "")), timeout=5000)
        popup = opened.value
        try:
            popup.wait_for_load_state("domcontentloaded", timeout=POPUP_TIMEOUT_MS)
        except Exception:  # noqa: BLE001
            pass
        info = _wait_for(lambda: _eval(popup.main_frame, POPUP_JS), wait, 16)
    except Exception as error:  # noqa: BLE001
        why = str(error).splitlines()[0][:100] if str(error) else type(error).__name__
        result.failed.append(f"물품 '{item.get('name', '')}' 사진: 팝업이 뜨지 않음({why})")
        result.ok = False
        info = None
    if info:
        name = info.get("item") or item.get("name") or "물품"
        for index, src in _photo_urls(info):
            body, ctype, why = fetch_in(popup.main_frame, page, urljoin(str(popup.url or ""), src))
            if body is None:
                result.failed.append(f"물품사진 {name} {index}: {why}")
                result.ok = False
                continue
            dest = folder / INSPECT_DIR / photo_name(name, index, ctype)
            if dest.exists():
                result.existed += 1
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(body)
            result.saved.append(f"{INSPECT_DIR}/{dest.name}")
            result.photos += 1
            log(f"      ✓ {INSPECT_DIR}/{dest.name} ({len(body):,} B)")
    elif popup is not None:
        result.failed.append(f"물품 '{item.get('name', '')}' 사진: 팝업에 사진 칸이 없음")
        result.ok = False
    if popup is not None:
        try:
            popup.close()
        except Exception:  # noqa: BLE001
            pass


def open_inspection(context, log: Callable[[str], None], wait: Callable[[float], None]):
    frame = inspect_frame(context)
    if frame is None:
        ok, why = _click_any(context, LEFT_MENU_JS, "검사처리")
        if not ok:
            return None, f"왼쪽 메뉴 '검사처리' 를 누르지 못했습니다({why})"
        log("왼쪽 메뉴 '검사처리' 를 눌렀습니다")
        frame = _wait_for(lambda: inspect_frame(context), wait, LIST_TRIES)
        if frame is None:
            return None, "'검사처리' 를 눌렀지만 그 화면이 뜨지 않았습니다"
    if _eval(frame, VISIBLE_JS) is not True:
        show_tab(context, "검사처리", log)
        _wait_for(lambda: _eval(frame, VISIBLE_JS) is True, wait, 10)
    return frame, ""


def inspect_cases(context, page, cases: dict[str, CaseResult], folders: dict[str, Path], start: str, end: str,
                  log: Callable[[str], None], wait: Callable[[float], None], should_stop: Callable[[], bool],
                  summary: PurchaseSummary) -> None:
    """검사처리 화면 — 계약일자 범위마다 목록을 읽고, 받은 건(구매요구번호)의 줄을 골라 첨부 · 물품 사진을 그 건 폴더의 '검사처리' 에."""
    frame, why = open_inspection(context, log, wait)
    if frame is None:
        summary.note = why
        log("⚠ 검사처리 서류는 받지 못했습니다 — " + why)
        return
    for s, e in windows(start, end):
        if should_stop():
            summary.stopped = True
            return
        ok, why = search(frame, s, e, log, wait, what="계약일자")
        if not ok:
            summary.note = f"검사처리 조회 실패: {why}"
            log("⚠ " + summary.note)
            return
        rows = collect_inspection(frame, wait)
        mine = [r for r in rows if r.get("req_no") in cases]
        summary.inspected_rows += len(rows)
        log(f"검사처리 계약 건 {len(rows)}줄 — 그중 받은 건의 것 {len(mine)}줄")
        for row in mine:
            if should_stop():
                summary.stopped = True
                return
            result = cases[row["req_no"]]
            folder = folders.get(row["req_no"])
            if folder is None:
                continue
            ok, why = select_inspection(frame, row, wait)
            if not ok:
                result.failed.append(f"검사처리 줄({row.get('cont_nm', '')[:20]}): {why}")
                result.ok = False
                continue
            result.inspected = True
            files = _eval(frame, INSPECT_FILES_JS) or []
            items = _eval(frame, ITEMS_JS) or []
            log(f"      검사처리 '{row.get('cont_nm', '')[:30]}' — 첨부 {len(files)}개 · 물품 {len(items)}개")
            _save_files(page, _frame_url(frame), files, folder / INSPECT_DIR, result, log, prefix=INSPECT_DIR + "/", frame=frame)
            for item in items:
                item_photos(context, page, frame, item, folder, result, log, wait)


def run(context, page, targets: list[dict], out_root: str, log: Callable[[str], None], wait: Callable[[float], None],
        notify: Callable[[int, str, str], None], should_stop: Callable[[], bool] = lambda: False) -> PurchaseSummary:
    """받기 표의 구매 줄들(as_target 모양)을 받는다. notify(표 번호, 상태, 글)는 청구서 받기와 같은 신호."""
    summary = PurchaseSummary()
    if not targets:
        return summary
    days = [t.get("expDt") or req_date(t.get("req_no", "")) for t in targets]
    days = [d for d in days if d]
    start, end = (min(days), max(days)) if days else ("", "")
    frame, why = open_list(context, log, wait)
    if frame is None:
        log("⚠ " + why)
        for i, t in enumerate(targets):
            summary.cases.append(CaseResult(str(t.get("req_no") or ""), t.get("cont", ""), t.get("project", ""), note=why, ok=False))
            notify(i, "failed", why)
        return summary
    cases: dict[str, CaseResult] = {}
    folders: dict[str, Path] = {}
    order = sorted(range(len(targets)), key=lambda i: (targets[i].get("expDt") or "", i))
    for n, i in enumerate(order, 1):
        target = targets[i]
        if should_stop():
            summary.stopped = True
            log("멈춤 요청 — 여기서 그만 받습니다.")
            break
        notify(i, "running", "")
        log("[%d/%d] 구매요구 %s · %s" % (n, len(targets), target.get("req_no"), (target.get("cont") or "")[:30]))
        day = target.get("expDt") or req_date(target.get("req_no", ""))
        window = window_for(day, start, end) if day else None
        if window is None:
            window = windows(start, end)[0] if windows(start, end) else None
        if frame is None or window is None:
            frame, why = open_list(context, log, wait)
            if frame is None:
                result = CaseResult(str(target.get("req_no") or ""), target.get("cont", ""), target.get("project", ""), note=why, ok=False)
                summary.cases.append(result)
                notify(i, "failed", why)
                continue
        if window is not None:
            ok, why = ensure_range(frame, window[0], window[1], log, wait, str(target.get("req_no") or ""))
            if not ok:
                log("      ✖ " + why)
                result = CaseResult(str(target.get("req_no") or ""), target.get("cont", ""), target.get("project", ""), note=why, ok=False)
                summary.cases.append(result)
                notify(i, "failed", why)
                continue
        result, frame = receive_case(context, page, frame, target, out_root, log, wait)
        summary.cases.append(result)
        cases[result.req_no] = result
        if result.folder:
            folders[result.req_no] = Path(result.folder)
        notify(i, "running" if result.ok else "failed", result.summary() + ("" if not result.ok else " · 검사처리 확인 중"))
    if folders and not summary.stopped and start:
        inspect_cases(context, page, cases, folders, start, end, log, wait, should_stop, summary)
    for i in order:
        req_no = str(targets[i].get("req_no") or "")
        result = cases.get(req_no)
        if result is not None:
            notify(i, "done" if result.ok else "failed", result.summary())
    log("── 구매요청(계약) 서류 끝: 건 %d · 새 파일 %d개 · 못 받은 건 %d" % (len(summary.cases), summary.files, len(summary.failed)))
    return summary
