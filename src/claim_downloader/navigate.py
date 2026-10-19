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

누르는 것은 과제명 링크 · '청구서' 탭 · 결의서 목록의 `#P10` 셋뿐이다(tests/test_safety.py). 값을 넣지 않는다. Playwright 를 들여오지 않는다(프레임의 evaluate 만).
"""
from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass

from . import erp, settings

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


NEW_SHEET_ID = "P10"
# 결의서 목록의 [일반청구] — id 와 글자가 둘 다 맞을 때만 누른다(#P11 카드청구 · #P21 반납요구 같은 이웃 단추와 헷갈리지 않게).
CLICK_NEW_SHEET_JS = r"""() => {
  const b = document.getElementById('P10');
  const t = b ? (b.innerText || b.textContent || '').replace(/\s+/g, ' ').trim() : '';
  if (!b || t !== '일반청구') return {ok: false, why: "결의서 목록의 [일반청구] 를 찾지 못함"};
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


def _frames(context):
    for page in list(getattr(context, "pages", []) or []):
        for frame in list(getattr(page, "frames", []) or []):
            yield page, frame


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
    """마지막으로 읽은 과제 목록 — 설정 화면이 과제 고르기 칸에 쓴다(ERP 에 들어가지 않고도). 과제번호 · 과제명 · 기간만 둔다(사람 이름 없음)."""
    data = {"read_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "projects": [asdict(p) for p in projects]}
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


def choices(selected: str, today: dt.date | None = None) -> list[tuple[str, str]]:
    """설정 화면의 과제 고르기 칸 — (과제번호, 보이는 글). 과제기간에 오늘이 든 과제만, 읽은 목록이 없으면 기본 과제번호 하나.
    지금 고른 번호는 목록에 없어도 남긴다(설정 값이 칸에서 사라지지 않게)."""
    projects, _when = load_projects()
    out = [(p.no, p.label()) for p in running(projects, today)]
    if not out:
        out = [(settings.DEFAULT_PROJECT_NO, settings.DEFAULT_PROJECT_NO)]
    if selected and selected not in {no for no, _ in out}:
        known = {p.no: p for p in projects}
        out.append((selected, (known[selected].label() + " — 과제기간 아님") if selected in known else selected))
    return out


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


def go_to_claims(context, project_no: str, log: Callable[[str], None], wait: Callable[[float], None]) -> tuple[bool, str]:
    """결의서내역 목록까지 간다. (됐는지, 글). 이미 목록이 떠 있으면 아무것도 누르지 않는다."""
    project_no = re.sub(r"\D", "", str(project_no or ""))      # 메모장으로 고친 설정에 빈칸 · 글자가 섞여도 JS 정규식이 깨지지 않게
    if not project_no:
        return False, "설정에 과제번호가 없습니다 — 설정 → ERP 과제에서 고르세요"
    if erp.grid_rows_shown(context) > 0:
        return True, "결의서내역 목록이 이미 떠 있습니다"
    toolbar = _toolbar(context, project_no)
    if toolbar is None:
        clicked = None
        for _page, frame in _frames(context):
            result = _evaluate(frame, CLICK_PROJECT_JS, project_no)
            if result and result.get("ok"):
                clicked = frame
                break
            if result and result.get("why") == "과제명 링크가 여럿":
                return False, f"과제현황에 과제 {project_no} 링크가 여럿이라 누르지 않았습니다 — 직접 여세요"
        if clicked is None:
            return False, (f"메인화면 과제현황에 과제 {project_no} 가 보이지 않습니다 — 다음 쪽에 있거나 다른 화면이 떠 있으면 "
                           "직접 과제정보 → 청구서를 여세요")
        log(f"과제 {project_no} 를 엽니다 (과제현황의 과제명)")
        toolbar = _wait(lambda: _toolbar(context, project_no), wait, tries=30)
        if toolbar is None:
            return False, f"과제 {project_no} 의 과제정보 화면이 뜨지 않았습니다 — 직접 청구서 탭을 누르세요"
    result = _evaluate(toolbar, CLICK_CLAIM_TAB_JS) or {}
    if not result.get("ok"):
        return False, f"과제정보의 청구서 탭을 누르지 못했습니다({result.get('why', '화면을 읽지 못함')}) — 직접 누르세요"
    log("과제정보 → 청구서 탭을 눌렀습니다")
    if _wait(lambda: erp.grid_rows_shown(context) > 0, wait, tries=40):
        return True, f"과제 {project_no} 의 결의서내역 목록까지 왔습니다"
    return False, "청구서 탭을 눌렀지만 결의서내역 목록이 보이지 않습니다 — 직접 결의서내역을 띄우세요"


def _sheet_state(frame) -> dict:
    from .claims import form
    try:
        state = form.read_state(frame, ["REQ_CNT", "APPR_DIV_CD", "REQ_SEQ_NO", "REQ_AMT", "REQ_PTCL", "RCV_NM"])
    except Exception:  # noqa: BLE001 — 다시 열리는 중
        return {}
    return {key: str((state.get(key) or {}).get("value", "") or "").strip() for key in state}


def open_new_sheet(context, log: Callable[[str], None], wait: Callable[[float], None]):
    """결의서 목록의 [일반청구](#P10)로 새 일반청구 작성 화면을 띄운다. (됐는지, 글, 새 작성 프레임 또는 None).

    지금 작성 화면이 있으면 **저장된 청구서이고 입력 칸(청구액 · 적요 · 입금처)이 비었을 때만** 누른다 — 같은 탭 자리를 새 화면이 차지하므로
    저장 전 입력은 날아간다. 저장 전(결의번호 없음) 화면은 이미 새 청구서라 누를 까닭이 없다."""
    from .claims import form
    _page, current = form.find_form(context)
    before = _sheet_state(current) if current is not None else {}
    if current is not None:
        if not (before.get("REQ_CNT") or before.get("APPR_DIV_CD") == "40"):
            return False, "작성 화면이 아직 저장 전인 청구서입니다 — 새로 띄우지 않았습니다", None
        typed = [label for key, label in (("REQ_AMT", "청구액"), ("REQ_PTCL", "적요"), ("RCV_NM", "입금처"))
                 if before.get(key) and before.get(key) not in ("0",)]
        if typed:
            return False, f"작성 화면에 저장하지 않은 입력({' · '.join(typed)})이 있어 새 청구서를 띄우지 않았습니다", None
    _gpage, grid = erp.find_grid(context)
    if grid is None:
        return False, "결의서 목록(과제정보 → 청구서)이 열려 있지 않아 새 청구서를 띄우지 못했습니다", None
    result = _evaluate(grid, CLICK_NEW_SHEET_JS) or {}
    if not result.get("ok"):
        return False, str(result.get("why") or "결의서 목록을 읽지 못했습니다"), None
    log("결의서 목록의 [일반청구] 로 새 청구서를 띄웁니다" + (f" (앞 청구서 결의번호 {before.get('REQ_CNT')})" if before.get("REQ_CNT") else ""))

    def fresh():
        _p, frame = form.find_form(context)
        if frame is None:
            return None
        now = _sheet_state(frame)
        new = now and not now.get("REQ_CNT") and now.get("APPR_DIV_CD") != "40"
        return frame if new and now.get("REQ_SEQ_NO") != before.get("REQ_SEQ_NO") else None

    frame = _wait(fresh, wait, tries=30)
    if frame is None:
        return False, "[일반청구] 를 눌렀지만 새 작성 화면이 뜨지 않았습니다", None
    log("✓ 새 청구서 작성 화면이 떴습니다")
    return True, "새 청구서", frame
