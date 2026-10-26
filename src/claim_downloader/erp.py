"""ERP 화면 조작 (Playwright).

2026-09-17 ~ 10-12 실제 ERP 화면에서 검증한 동작을 옮긴 것이다. 화면 구조는
CLAUDE.md 'ERP 화면 구조' 절에 있다. 추측으로 바꾸지 않는다.

  - 전부 한 창 안의 iframe 이다. 프레임은 URL 이 아니라 **내용으로** 찾는다.
  - 목록은 가상 스크롤이라 화면에 보이는 30여 행만 DOM 에 있다.
    그래서 행은 r 속성으로 바로 찾지 않고 문서번호로 스크롤하며 찾는다.

이 모듈은 다운로드만 한다. ERP 에 값을 넣거나 저장·신청·제출을 누르지 않는다.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from . import naming

_GRID_PROBE = "()=>!!document.querySelector('.k_REQ_DOC_NO')||!!document.querySelector('#btnDetail')"
_DETAIL_PROBE = ("()=>{const E=document.querySelectorAll('a,span,button,input');"
                 "for(const e of E){const s=(e.textContent||e.value||'').trim();"
                 "if(s==='청구서출력')return true;}return false;}")

# 상세화면 멈춤 계열 오류. 이 문구가 들어간 실패만 새로고침 후 재시도한다.
FREEZE_HINTS = ("안 뜸", "찾지 못", "Timeout", "timeout")


def is_freeze_error(message: str) -> bool:
    return any(hint in message for hint in FREEZE_HINTS)


class NoPrintScreen(RuntimeError):
    """상세조회로 뜬 화면에 '청구서출력' 이 없다 · 상세조회 뒤 ERP 알림이 떴다 — 멈춤(freeze)이 아니라 청구서가 아닌 결의서로 본다.

    2026-10-21 실제: 끝난 과제(202408470001)의 'No 1 · 정산 완료 후 잔액조정' 에서 60초를 기다린 뒤 멈춤으로 보고 ERP 를 새로 열어
    다시 로그인을 물었다. 청구서출력이 없는 결의서는 몇 번을 다시 해도 같으니 건너뛰고 다음 건으로 간다(session.download)."""


# 상세조회 뒤 새로 뜨거나 바뀐 화면이 결의서 목록도 청구서 상세도 아닌지 — 읽기만 한다. 출력 단추 글자는 기록용.
_OTHER_SCREEN_JS = r"""() => {
  if (!document.body) return null;
  if (document.querySelector('.k_REQ_DOC_NO') || document.querySelector('#btnDetail')) return null;
  const t = document.body.innerText || '';
  if (t.length < 200) return null;
  const outs = [];
  document.querySelectorAll('a,span,button,input').forEach(e => {
    const s = (e.textContent || e.value || '').trim();
    if (/출력/.test(s) && s.length <= 12 && !outs.includes(s)) outs.push(s);
  });
  if (outs.includes('청구서출력')) return null;
  return {title: (document.title || '').slice(0, 40), outs: outs.slice(0, 6)};
}"""
OTHER_SCREEN_GRACE = 10      # 초 — 청구서가 아닌 화면이 이만큼 그대로면 건너뛴다(느린 청구서 상세가 아니라고 본다)
ALERT_GRACE = 5              # 초 — 상세조회 뒤 ERP 알림이 왔는데 이만큼 청구서 상세가 안 뜨면 건너뛴다


def _other_screen(page, before_frames: list, before_pages: list) -> dict | None:
    """상세조회 뒤 새로 생겼거나 주소가 바뀐 프레임(새 창 포함) 중 청구서출력 없는 화면 하나."""
    old = {id(fr): url for fr, url in before_frames}
    frames = [fr for fr in page.frames if old.get(id(fr)) != fr.url]
    for pg in list(page.context.pages):
        if pg is not page and all(pg is not b for b in before_pages):
            frames += list(pg.frames)
    for fr in frames:
        try:
            got = fr.evaluate(_OTHER_SCREEN_JS)
        except Exception:      # noqa: BLE001 — 그리는 중인 프레임
            continue
        if got:
            got["url"] = str(fr.url or "").split("?", 1)[0].rsplit("/", 1)[-1]
            return got
    return None


def _close_new_pages(page, before_pages: list) -> None:
    """상세조회로 새로 뜬 창은 닫는다(ERP 단추가 아니라 창 닫기) — 다음 건이 그 창을 상세화면으로 보지 않게."""
    for pg in list(page.context.pages):
        if pg is not page and all(pg is not b for b in before_pages):
            try:
                pg.close()
            except Exception:  # noqa: BLE001
                pass


def _frame_matches(fr, probe) -> bool:
    try:
        return fr.evaluate(probe) is True
    except Exception:          # noqa: BLE001 — 로딩 중인 프레임은 evaluate 가 실패한다
        return False


def grid_frame(page):
    """이 창의 프레임 중 결의서내역 그리드가 있는 프레임."""
    for fr in page.frames:
        if _frame_matches(fr, _GRID_PROBE):
            return fr
    return None


def detail_frame(page):
    """이 창의 프레임 중 '청구서출력' 이 있는 상세 프레임."""
    for fr in page.frames:
        if _frame_matches(fr, _DETAIL_PROBE):
            return fr
    return None


def find_grid(context):
    """열린 모든 창을 뒤져 결의서내역 그리드가 있는 (창, 프레임)."""
    for pg in context.pages:
        for fr in pg.frames:
            if _frame_matches(fr, _GRID_PROBE):
                return pg, fr
    return None, None


GRID_ROWS_JS = "() => document.querySelectorAll('.jgrid-row').length"
# 목록의 스크롤 칸이 화면에 보이는지 — ERP 는 위쪽 탭마다 iframe 을 두고 뒤에 있는 탭은 숨긴다. 숨은 목록은 높이가 0 이라
# 가상 스크롤이 움직이지 않고, 처음 그려 둔 26~32행만 읽힌다(담당자 실제 2026-10-21: 일반청구 작성 탭이 앞에 있는 채 [목록 읽기] →
# '수집 26행 · 대상 0건' — 받을 청구서가 있었는데 못 찾았다).
GRID_SHOWN_JS = """() => { const v = document.querySelector('.jgrid-viewport'); if (!v) return false;
  const r = v.getBoundingClientRect(); return r.width > 0 && r.height > 0; }"""


def grid_shown(fr) -> bool:
    try:
        return fr.evaluate(GRID_SHOWN_JS) is True
    except Exception:  # noqa: BLE001 — 그리는 중 · 프레임이 바뀌는 중
        return False


def grid_rows_shown(context) -> int:
    """결의서내역 목록(그리드)에 그려진 행 수 — 목록이 없거나 다른 탭 뒤에 숨어 있으면 0. 읽기만 한다(목록이 뜨기를 기다릴 때).
    숨은 목록을 세면 목록 자동 읽기가 사람이 다른 화면(일반청구 작성)을 보는 중에 끼어든다."""
    _page, fr = find_grid(context)
    if fr is None or not grid_shown(fr):
        return 0
    try:
        return int(fr.evaluate(GRID_ROWS_JS) or 0)
    except Exception:  # noqa: BLE001 — 그리는 중 · 프레임이 바뀌는 중
        return 0


def wait_for_grid(context, tries: int = 40, interval_ms: int = 500):
    """목록이 눈에 보여도 첫 evaluate 는 실패할 수 있다. 한 번 보고 포기하지 않는다."""
    for _ in range(tries):
        page, fr = find_grid(context)
        if fr:
            return page, fr
        if context.pages:
            context.pages[0].wait_for_timeout(interval_ms)
        else:
            time.sleep(interval_ms / 1000)
    return None, None


def frame_kind(fr) -> str:
    """진단용: 이 프레임이 무엇인지 알아본 이름. 모르면 빈 문자열."""
    if _frame_matches(fr, _GRID_PROBE):
        return "결의서 목록"
    if _frame_matches(fr, _DETAIL_PROBE):
        return "상세(청구서출력)"
    return ""


def dump_context(context) -> str:
    """진단용: 열린 모든 창과 프레임 주소."""
    out = []
    for pi, pg in enumerate(context.pages):
        try:
            u = pg.url
        except Exception:      # noqa: BLE001
            u = "?"
        try:
            t = pg.title()
        except Exception:      # noqa: BLE001
            t = "?"
        out.append("[창 %d] %s | %s" % (pi, t, u))
        for fi, fr in enumerate(pg.frames):
            kind = frame_kind(fr)
            mark = ("  <== " + kind + "!") if kind else ""
            out.append("    프레임 %d: %s%s" % (fi, (fr.url or ""), mark))
    return "\n".join(out) if out else "(열린 창이 없음)"


# ── 목록 ───────────────────────────────────────────────────────────────
_PARSE_ROWS_JS = r"""
() => {
  const rows = [];
  document.querySelectorAll('.jgrid-row').forEach(el => {
    const c = k => {
      const d = el.querySelector('.k_'+k);
      if(!d) return '';
      const t = d.getAttribute('title');
      return (t && t.trim()) ? t.trim() : (d.textContent||'').trim();
    };
    if(!el.querySelector('.k_REQ_DOC_NO')) return;
    rows.push({
      r: el.getAttribute('r'),
      no: c('ROW_NO').replace(/[^0-9]/g,''),
      seq: c('REQ_DOC_NO').replace(/[^0-9]/g,''),
      gubun: c('PROC_TYP_NM'),
      cont: c('APPL_CONT'),
      amt: c('REQ_AMT').replace(/[^0-9\-]/g,''),
      state: c('APPR_DIV_NM'),
      docNo: c('DOC_NO'),
      expDt: c('SLIP_DT')||c('APPR_DT')||c('APPL_DT')
    });
  });
  return rows;
}"""

_SCROLL_TOP_JS = "() => { const v=document.querySelector('.jgrid-viewport'); if(v) v.scrollTop=0; }"
_SCROLL_INFO_JS = """() => { const v=document.querySelector('.jgrid-viewport');
    return v ? {top:v.scrollTop, h:v.clientHeight, sh:v.scrollHeight} : null; }"""
_SCROLL_NEXT_JS = """() => { const v=document.querySelector('.jgrid-viewport');
    if(v) v.scrollTop = Math.min(v.scrollHeight, v.scrollTop + v.clientHeight - 60); }"""


def parse_rows(fr) -> list[dict]:
    try:
        return fr.evaluate(_PARSE_ROWS_JS)
    except Exception:          # noqa: BLE001
        return []


def collect_all(fr) -> list[dict]:
    """가상 스크롤 목록을 끝까지 내리며 전 행 수집(문서번호/결의번호 기준 중복 제거)."""
    seen, out = set(), []

    def grab():
        for r in parse_rows(fr):
            key = r["docNo"] or (r["gubun"] + "#" + r["seq"])
            if r["seq"] and key not in seen:
                seen.add(key)
                out.append(r)

    try:
        fr.evaluate(_SCROLL_TOP_JS)
    except Exception:          # noqa: BLE001
        pass
    grab()
    last = -1
    for _ in range(400):
        try:
            info = fr.evaluate(_SCROLL_INFO_JS)
        except Exception:      # noqa: BLE001
            info = None
        if not info:
            break
        if info["top"] + info["h"] >= info["sh"] - 5 and info["top"] == last:
            break
        last = info["top"]
        fr.evaluate(_SCROLL_NEXT_JS)
        fr.page.wait_for_timeout(250)
        grab()
    return out


# ── 상세화면: 이체자(입금처>예금주) + 비목명 ─────────────────────────────
_OWNERS_JS = r"""
() => {
  const txt = el => (el ? (el.textContent||'').replace(/\s+/g,' ').trim() : '');
  const trs = document.querySelectorAll('tr');
  let head=null, col={};
  for(const tr of trs){
    const cs=tr.cells; if(!cs||cs.length<4) continue;
    let m={},a=false,b=false;
    for(let j=0;j<cs.length;j++){ const k=txt(cs[j]).replace(/\s/g,''); if(!k)continue;
      if(m[k]===undefined)m[k]=j; if(k==='비목')a=true; if(k==='예금주'||k==='입금처')b=true; }
    if(a&&b){head=tr;col=m;break;}
  }
  const out={owners:[], bimok:'', full: (document.body.innerText||'')};
  if(!head) return out;
  let tbl=head.parentNode; while(tbl&&tbl.tagName!=='TABLE') tbl=tbl.parentNode;
  if(!tbl) return out;
  const p=col['입금처'], q=col['예금주'], bcol=col['비목'];
  for(let i=head.rowIndex+1;i<tbl.rows.length;i++){
    const c=tbl.rows[i].cells; if(!c)continue;
    if(!out.bimok && bcol!==undefined && c[bcol]){ const bv=txt(c[bcol]);
      if(bv&&bv!=='비목'&&!/^합\s*계/.test(bv)) out.bimok=bv; }
    let v=(p!==undefined&&c[p])?txt(c[p]):''; if(!v&&q!==undefined&&c[q]) v=txt(c[q]);
    if(!v||v==='입금처'||v==='예금주'||/^합\s*계/.test(v)) continue;
    if(out.owners.indexOf(v)<0) out.owners.push(v);
  }
  return out;
}"""


def read_owners_and_bimok(dfr) -> dict:
    try:
        return dfr.evaluate(_OWNERS_JS)
    except Exception:          # noqa: BLE001
        return {"owners": [], "bimok": "", "full": ""}


# ── OZ 보고서 팝업에서 PDF 저장 ───────────────────────────────────────────
def save_oz_pdf(popup, dest_path: Path) -> bool:
    """OZ 가 다운로드 훅을 우회하므로 Playwright 의 다운로드 캡처로 받아
    원하는 이름으로 직접 저장한다. 이것이 매크로에서 앱으로 옮긴 핵심 이유다."""
    popup.wait_for_load_state("domcontentloaded")
    popup.wait_for_selector("input.btnSAVEAS", timeout=360000)   # 보고서 생성 대기
    popup.wait_for_timeout(2500)                                  # 생성 완료 안정화
    with popup.expect_download(timeout=600000) as dl_info:
        popup.click("input.btnSAVEAS")
        # 저장 형식 대화상자: select 에서 Adobe PDF(value=3) 선택 후 '확인'
        try:
            popup.wait_for_selector(".ozbasedlg select", timeout=20000)
            popup.eval_on_selector(
                ".ozbasedlg select",
                "el => { el.value='3'; el.dispatchEvent(new Event('change',{bubbles:true})); }",
            )
            popup.evaluate(
                """() => { const dlg=document.querySelector('.ozbasedlg');
                    if(!dlg) return; const bs=dlg.querySelectorAll('button');
                    for(const b of bs){ if((b.textContent||'').trim()==='확인'){ b.click(); return; } } }"""
            )
        except Exception:      # noqa: BLE001 — 대화상자 없이 바로 받아지는 경우도 있다
            pass
    dl = dl_info.value
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dl.save_as(str(dest_path))
    if not (dest_path.exists() and dest_path.stat().st_size > 0):
        return False
    # PDF 인지 본다 — OZ 저장 형식이 바뀌어 다른 파일이 .pdf 로 저장되면 받은 것으로 기록돼 다시 받지 않게 된다(2026-10-14 점검).
    # 방금 이 함수가 만든 파일이라 지워도 남의 파일을 지우는 것이 아니다.
    with open(dest_path, "rb") as f:
        head = f.read(5)
    if head != b"%PDF-":
        dest_path.unlink(missing_ok=True)
        return False
    return True


# ── 대상 행을 스크롤로 찾아 선택 ─────────────────────────────────────────
_FIND_ROW_JS = r"""
(t) => {
  const cell = (el,k) => { const d=el.querySelector('.k_'+k); if(!d) return '';
    const a=d.getAttribute('title'); return (a&&a.trim())?a.trim():(d.textContent||'').trim(); };
  const rows=document.querySelectorAll('.jgrid-row');
  for(const el of rows){
    if(!el.querySelector('.k_REQ_DOC_NO')) continue;
    const dn=cell(el,'DOC_NO');
    const sq=cell(el,'REQ_DOC_NO').replace(/[^0-9]/g,'');
    const rn=cell(el,'ROW_NO').replace(/[^0-9]/g,'');
    const hit = (t.docNo && dn===t.docNo) ||
                (!t.docNo && t.seq && sq===t.seq) ||
                (!t.docNo && !t.seq && t.no && rn===t.no);
    if(hit){
      document.querySelectorAll('.jgrid-row input[type=checkbox]').forEach(c=>{ if(c.checked) c.click(); });
      const cb=el.querySelector('input[type=checkbox]');
      if(cb && !cb.checked) cb.click();
      el.scrollIntoView({block:'center'});
      return true;
    }
  }
  return false;
}"""


def select_row(page, gfr, target: dict) -> bool:
    """문서번호(없으면 결의번호/No)로 목록을 위에서부터 스크롤하며 찾아 체크한다."""
    arg = {"docNo": target.get("docNo") or "", "seq": target.get("seq") or "",
           "no": target.get("no") or ""}
    try:
        gfr.evaluate(_SCROLL_TOP_JS)
    except Exception:          # noqa: BLE001
        pass
    page.wait_for_timeout(200)
    last = -1
    for _ in range(400):
        try:
            if gfr.evaluate(_FIND_ROW_JS, arg) is True:
                page.wait_for_timeout(200)
                return True
        except Exception:      # noqa: BLE001
            pass
        try:
            info = gfr.evaluate(_SCROLL_INFO_JS)
        except Exception:      # noqa: BLE001
            info = None
        if not info:
            break
        if info["top"] + info["h"] >= info["sh"] - 5 and info["top"] == last:
            break
        last = info["top"]
        gfr.evaluate(_SCROLL_NEXT_JS)
        page.wait_for_timeout(200)
    return False


_DETAIL_READY_JS = r"""(doc) => {
  const t=document.body?document.body.innerText:''; if(t.length<200) return null;
  // 문서번호는 앞뒤가 숫자가 아닐 때만 같은 것으로 — '…-1' 이 '…-12' 의 옛 상세화면에 맞지 않게(2026-10-14 점검)
  if(doc){ const esc=doc.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
           if(!new RegExp('(^|[^0-9])'+esc+'([^0-9]|$)').test(t)) return null; }
  const els=document.querySelectorAll('a,span,button,input');
  for(const e of els){ const s=(e.textContent||e.value||'').trim(); if(s==='청구서출력') return true; }
  return false;
}"""
_CLICK_PRINT_JS = """() => { const els=document.querySelectorAll('a,span,button,input');
  for(const e of els){ const s=(e.textContent||e.value||'').trim(); if(s==='청구서출력'){ e.click(); return; } } }"""
_CLICK_LIST_JS = """() => { const els=document.querySelectorAll('a,span');
  for(const e of els){ if((e.textContent||'').trim()==='목록'){ e.click(); return; } } }"""


def process_one(page, row: dict, out_root: str, name_format: str, wait_sec: float,
                log: Callable[[str], None]) -> tuple[str, Path]:
    """한 건: 행 선택 → 상세조회 → 청구서출력 → PDF 저장 → 목록 복귀. (비목 코드, 저장 경로)."""
    gfr = grid_frame(page)
    if not gfr:
        raise RuntimeError("목록 프레임을 찾지 못함")
    if not select_row(page, gfr, row):
        raise RuntimeError("목록에서 해당 행을 찾지 못함(스크롤/선택 실패)")
    page.wait_for_timeout(500)
    before_frames = [(fr, fr.url) for fr in page.frames]
    before_pages = list(page.context.pages)
    alerts: list[str] = []

    def heard(dialog) -> None:
        # 듣기만 한다 — 닫는 것은 session 의 처리기(_on_dialog)가 한다
        try:
            alerts.append((dialog.message or "").strip())
        except Exception:      # noqa: BLE001
            pass

    try:
        page.context.on("dialog", heard)
    except Exception:          # noqa: BLE001
        pass
    gfr.evaluate("() => { const b=document.querySelector('#btnDetail'); if(b) b.click(); }")

    # 상세 프레임에 이 건의 문서번호와 '청구서출력' 이 함께 보일 때까지 기다린다.
    # 문서번호를 안 보면 직전 건의 상세화면을 이 건으로 착각해 이름이 뒤바뀐다.
    deadline = time.time() + 60
    dfr = None
    other_since = alert_since = None
    try:
        while True:
            if time.time() >= deadline:
                raise TimeoutError("상세화면(청구서출력)이 안 뜸")
            dfr = detail_frame(page)
            if dfr:
                try:
                    if dfr.evaluate(_DETAIL_READY_JS, row.get("docNo") or "") is True:
                        break
                except Exception:  # noqa: BLE001
                    pass
            now = time.time()
            if alerts:
                alert_since = alert_since or now
                if now - alert_since >= ALERT_GRACE:
                    _close_new_pages(page, before_pages)
                    raise NoPrintScreen("상세조회 뒤 ERP 알림: " + alerts[-1][:120])
            other = _other_screen(page, before_frames, before_pages)
            if other:
                other_since = other_since or now
                if now - other_since >= OTHER_SCREEN_GRACE:
                    _close_new_pages(page, before_pages)
                    raise NoPrintScreen("상세화면에 '청구서출력' 이 없음 — 화면 " + (other.get("url") or other.get("title") or "?")
                                        + (" · 출력 단추 " + ", ".join(other.get("outs") or []) if other.get("outs") else " · 출력 단추 없음"))
            else:
                other_since = None
            page.wait_for_timeout(500)
    finally:
        try:
            page.context.remove_listener("dialog", heard)
        except Exception:      # noqa: BLE001
            pass

    page.wait_for_timeout(800)
    info = read_owners_and_bimok(dfr)
    code, fname = naming.build_name(row, info, name_format)
    dest = naming.destination(out_root, code, fname, row.get("budget"))
    log("      → %s / %s" % (dest.parent.name, dest.name))

    with page.context.expect_page(timeout=60000) as pop_info:
        dfr.evaluate(_CLICK_PRINT_JS)
    popup = pop_info.value
    try:
        ok = save_oz_pdf(popup, dest)
    finally:
        try:
            popup.close()
        except Exception:      # noqa: BLE001
            pass
    if not ok:
        raise RuntimeError("PDF 저장 실패")

    try:
        dfr2 = detail_frame(page)
        if dfr2:
            dfr2.evaluate(_CLICK_LIST_JS)
    except Exception:          # noqa: BLE001
        pass
    for _ in range(50):
        if grid_frame(page):
            break
        page.wait_for_timeout(400)
    page.wait_for_timeout(int(wait_sec * 1000))
    return code, dest
