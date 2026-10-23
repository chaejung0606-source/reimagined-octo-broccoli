"""첨부만 다시 올리기 — ERP 에 이미 있는 청구서(임시저장 · 보완요청)의 청구내역 줄마다 첨부문서를 지우고 폴더의 지금 파일을 다시 붙여 [저장].

담당자 요청(2026-10-23): "일반청구 기능과 똑같은데 이미 청구서가 있고 청구내역은 입력하지 않고 첨부문서만 첨부" — "이미 업로드 된 문서 삭제 후 현재
기준 문서로 재첨부 후 저장". 첨부문서 목록(#fileList)의 파일 이름은 기록할 것 없고 넣어야 하는 문서를 넣는다. 첨부문서 목록 옆의 '삭제' 는 앱이
눌러도 된다("네 삭제 눌러도 됩니다") — 여러 개를 한 번에 골라 한 번에 지운다("첨부문서가 여러개인 경우 여러개를 한번에 선택해서 한번에 삭제").

흐름(session.reattach_files): 그 과제의 결의서내역에서 대표적요가 같고 진행구분이 임시저장 · 보완요청인 청구서 하나 → 줄을 골라 [상세조회/변경]
(navigate.open_saved_sheet — 받기와 같은 #btnDetail) → 작성 화면(결의번호가 그것) → 청구내역 줄(○ CUR_REQ)마다 ① 줄을 다시 열어 입력 칸에 그 줄의
적요 · 청구액이 들어오면 ② 보이는 #fileList 의 보기를 모두 골라 그 옆 '삭제' → 목록이 빌 때까지 ③ attach.upload(폴더 파일) ④ [저장](form.save_draft)
⑤ 청구내역 줄 수 · 결의번호가 그대로인지(늘었으면 고친 것이 아니라 새 줄 — 멈추고 사람이 지운다).

**① 줄 다시 열기와 ② '삭제' 는 실측 전이다**(2026-10-23 — 담당자에게 네 장면의 [화면 구조 저장] 을 부탁해 두었다). 그래서 둘 다 화면이 기대대로
바뀌지 않으면 노란 띠로 사람에게 넘긴다(그 줄을 열거나 지운 뒤 [계속]) — 실측이 오면 JS 를 고친다. 값 넣기(form.fill) · 파일 넣기(set_input_files)는
여기 없다 — 첨부는 attach.py, [저장] 은 form.py 가 한다. 누르는 것: 청구내역 줄의 ○(OPEN_ROW_JS) · 첨부문서 목록 옆 '삭제'(CLICK_FILE_DELETE_JS —
#fileList 와 같은 칸 안의 글자 '삭제' 하나, 청구내역 줄의 '[삭제]'(btn_del_N) · 결의서 목록의 [삭제](btnDelete) 가 아니다) · 그리고 attach 의 '첨부' ·
[업로드], form 의 [저장]. [신청] · 줄 [삭제] · 전체 체크는 없다(tests/test_safety.py).
"""
from __future__ import annotations

import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from . import attach, kinds
from .form import PICK_EL_JS, PROBE_JS, read_state, save_draft
from .payee import wait_until
from .scholarship import MAX_ASKS, Ask, _read_sheet

STATE_WORDS = ("임시저장", "보완")      # 결의서내역 진행구분 — 이 상태의 청구서만(담당자 2026-10-23: "임시저장이거나 보완요청이 온 상태")
# 넣기 전 중복 확인 띠(session._duplicate_check)의 셋째 단추 글 — 물음에 이 글이 들어 있으면 일반청구 화면이 그 단추를 보인다(ui/pages/claim.py)
REATTACH_CHOICE = "[첨부만 다시 올리기]"
ROW_RADIO_NAME = "CUR_REQ"             # 청구내역 줄의 ○(실측 ⑤ — '다시 열어 고치기' 로 본 라디오)
DELETE_TEXT = "삭제"                   # 첨부문서 목록(#fileList) 옆의 링크 글자(실측 14절 표: select + 링크 '첨부' '삭제' '순서변경')
FILE_LIST_ID = "fileList"
PREFIX_MIN = 20                        # 입력 칸의 적요가 청구내역 줄 글자(잘렸을 수 있음)와 같은지 볼 앞 글자 수 — sheet_check.PREFIX_MIN 과 같다
ROW_TRIES = 32                         # 줄을 열고 입력 칸이 채워지기까지 기다리는 횟수(0.25초씩 — 8초)

# 청구내역의 저장된 줄(글자가 있는 줄 — SHEET_ROWS_JS 와 같은 규칙) 중 n 번째의 ○ 를 누른다. 읽기만 하는 SHEET_ROWS_JS 와 줄 번호가 맞아야 한다.
OPEN_ROW_JS = """(n) => {
  const txt = e => (e.innerText || e.textContent || '').replace(/\\s+/g, ' ').trim();
  const rows = Array.from(document.querySelectorAll('input[name=CUR_REQ]')).filter(r => {
    const t = r.closest('tr') ? txt(r.closest('tr')) : '';
    return /[가-힣A-Za-z]/.test(t) && !/조회된.*없|내역이 없|데이터가 없/.test(t); });
  const r = rows[n];
  if (!r) return {ok: false, why: '청구내역의 저장된 줄이 ' + rows.length + '개뿐'};
  if (r.disabled) return {ok: false, why: '줄의 선택 칸이 비활성'};
  r.click();
  if (!r.checked) { r.checked = true; r.dispatchEvent(new Event('change', {bubbles: true})); }
  return {ok: true, text: txt(r.closest('tr'))};
}"""

# 보이는 첨부문서 목록(#fileList)의 보기를 모두 고른다 — 담당자: 여러 개를 한 번에 골라 한 번에 지울 수 있다. 목록이 multiple 이 아니면 하나만 골라진다(selected 로 안다)
SELECT_ALL_FILES_JS = """() => {
  """ + PICK_EL_JS + """
  const el = pickEl('fileList');
  if (!el || el.tagName !== 'SELECT') return {ok: false, why: '첨부문서 목록(#fileList)이 없음', count: 0, selected: 0};
  const opts = Array.from(el.options);
  for (const o of opts) o.selected = true;
  el.dispatchEvent(new Event('change', {bubbles: true}));
  return {ok: true, count: opts.length, selected: opts.filter(o => o.selected).length,
          names: opts.map(o => (o.textContent || '').replace(/\\s+/g, ' ').trim())};
}"""

# 첨부문서 목록 옆의 '삭제' 하나 — #fileList 와 같은 칸(td · 그 위 tr · div, 다섯 단계까지)에서 글자가 정확히 '삭제' 인 보이는 것 하나일 때만.
# 청구내역 줄의 '[삭제]'(id btn_del_N, 글자도 괄호가 있다) · 결의서 목록의 [삭제](다른 프레임) · 파일등록 창의 삭제(다른 창)는 아니다.
CLICK_FILE_DELETE_JS = """() => {
  """ + PICK_EL_JS + """
  const list = pickEl('fileList');
  if (!list) return {ok: false, why: '첨부문서 목록(#fileList)이 없음'};
  const norm = s => (s || '').replace(/\\s+/g, '');
  const vis = e => { const r = e.getBoundingClientRect(), s = getComputedStyle(e);
                     return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden'; };
  let scope = list.parentElement, hits = [], seen = 0;
  for (let depth = 0; scope && depth < 5; depth++, scope = scope.parentElement) {
    const all = Array.from(scope.querySelectorAll('a, button, input[type=button], span[onclick]')).filter(e => {
      if (norm(e.textContent || e.value) !== '삭제') return false;
      if (/^btn_del/.test(e.id || '')) return false;
      const tr = e.closest('tr');
      return !(tr && tr.querySelector('input[name=CUR_REQ]'));
    });
    seen += all.length;
    const shown = all.filter(vis);
    hits = shown.filter(h => !shown.some(o => o !== h && h.contains(o)));
    if (hits.length) break;
  }
  if (hits.length !== 1) return {ok: false, why: hits.length ? "첨부문서 목록 옆에 보이는 '삭제' 가 여럿(" + hits.length + ")"
                                                              : "첨부문서 목록 옆에 보이는 '삭제' 가 없음(숨은 것 " + seen + "개)"};
  hits[0].click();
  return {ok: true};
}"""


def _squash(text) -> str:
    return re.sub(r"\s+", "", str(text or ""))


# ── 계획 ───────────────────────────────────────────────────────────────
@dataclass
class RowPlan:
    index: int                 # 명단 index(일반은 0) — 화면의 학생 표 · 결과와 맞춘다
    label: str                 # 이름(강좌) · 폴더 이름
    summary: str               # 이 줄의 적요 — 청구내역 표에서 줄을 찾는 데
    files: list[str] = field(default_factory=list)
    note: str = ""

    @property
    def names(self) -> list[str]:
        return [os.path.basename(f) for f in self.files]


@dataclass
class Plan:
    folder: str
    kind: str
    summary: str               # 대표적요 — 결의서내역에서 청구서를 찾는 데
    project_no: str = ""
    rows: list[RowPlan] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)      # 넣기를 막는 것
    job: object = None         # 명단 청구의 Job — 청구내역 줄을 사람에게 붙일 때(sheet_check.match_rows)

    @property
    def name(self) -> str:
        return os.path.basename(os.path.normpath(self.folder))

    @property
    def kind_name(self) -> str:
        return kinds.name_of(self.kind)

    def files_total(self) -> int:
        return sum(len(r.files) for r in self.rows)

    def summary_lines(self) -> list[str]:
        return [f"폴더: {self.name} ({self.kind_name})",
                f"대표적요: {self.summary or '—'}",
                f"ERP 과제: {self.project_no or '— (비어 있음: 마지막에 고른 과제부터, 오늘이 기간에 든 과제를 차례로 찾습니다)'}",
                f"줄 {len(self.rows)}개 · 붙일 파일 {self.files_total()}개 — 줄마다 첨부문서를 모두 지우고 다시 올린 뒤 [저장]"]


def plan_for_job(job) -> Plan:
    """명단 청구(장학금 · 혁신인재지원금 · 개인 지급) — 체크한 사람마다 공통 + 개별 파일(Job.files_for)."""
    rows = []
    for i in job.chosen():
        p = job.people[i]
        files = attach.attachable(job.files_for(i))
        label = p.name + (f" ({p.course})" if getattr(p, "course", "") else "")
        rows.append(RowPlan(i, label, job.row_summary(i), files, "" if files else "올릴 파일 없음 — 건너뜀"))
    problems = []
    if not job.main_summary:
        problems.append("대표적요가 비어 있습니다")
    if not rows:
        problems.append("체크한 사람이 없습니다")
    elif not any(r.files for r in rows):
        problems.append("올릴 파일이 없습니다(공통 · 개별 폴더)")
    return Plan(job.folder, job.kind, job.main_summary, getattr(job, "project_no", ""), rows, problems, job=job)


def plan_for_data(folder: str, data: dict, kind: str, project_no: str = "") -> Plan:
    """일반 · 세금계산서 — 청구내역 한 줄. 파일은 AI 가 고른 첨부 후보(attachments), 없으면 폴더 바로 아래 파일 전부."""
    names = [str(n) for n in (data.get("attachments") or [])]
    files = attach.attachable([os.path.join(folder, n) for n in names])
    if not files and os.path.isdir(folder):
        files = attach.attachable(sorted(os.path.join(folder, n) for n in os.listdir(folder)))
    summary = str(data.get("summary") or "").strip()
    rows = [RowPlan(0, os.path.basename(os.path.normpath(folder)), summary, files, "" if files else "올릴 파일 없음")]
    problems = []
    if not summary:
        problems.append("적요가 비어 있습니다 — [내용 읽기] 로 읽거나 오른쪽 칸에 ERP 청구서와 같은 적요를 넣으세요")
    if not files:
        problems.append("올릴 파일이 없습니다(폴더 바로 아래)")
    return Plan(folder, kind, summary, project_no, rows, problems)


def plan_for(kind: str, folder: str, data: dict | None = None, job=None, project_no: str = "") -> Plan:
    if kind == kinds.CARD:
        return Plan(folder, kind, "", project_no, [], ["카드 청구서는 아직 — 결제 건마다 증빙 창이 달라 다음에 만듭니다"])
    if kinds.uses_roster(kind):
        if job is None:
            return Plan(folder, kind, "", project_no, [], ["명단을 읽지 못한 폴더입니다"])
        return plan_for_job(job)
    return plan_for_data(folder, dict(data or {}), kind, project_no)


# ── 결과 ───────────────────────────────────────────────────────────────
@dataclass
class RowResult:
    index: int
    label: str
    status: str = "planned"            # planned · saved · skipped · failed · stopped · waiting
    note: str = ""
    sheet_row: int = -1                # 청구내역 줄 번호(0부터)
    removed: int = 0
    uploaded: int = 0
    files: list[str] = field(default_factory=list)
    detail: list[str] = field(default_factory=list)
    review: list[str] = field(default_factory=list)   # [신청] 전에 확인할 것(사람이 대신 한 단계)

    @property
    def label_text(self) -> str:
        return {"planned": "할 것", "saved": "저장", "skipped": "건너뜀", "failed": "실패", "stopped": "멈춤",
                "waiting": "대기", "erp": "넣는 중"}.get(self.status, self.status)


@dataclass
class ReattachReport:
    dry_run: bool
    plan: Plan | None = None
    results: list[RowResult] = field(default_factory=list)
    blocked: str = ""
    stopped: bool = False
    req_cnt: str = ""
    state: str = ""
    messages: list[str] = field(default_factory=list)

    @property
    def saved(self) -> int:
        return sum(1 for r in self.results if r.status == "saved")

    def review_items(self) -> list[str]:
        return [f"{r.label}: {item}" for r in self.results for item in r.review]

    def lines(self) -> list[str]:
        name = self.plan.name if self.plan is not None else "?"
        if self.dry_run:
            out = [f"첨부만 다시 올리기 — 미리 보기 (ERP 에 넣지 않음): {name}"]
        else:
            out = [f"첨부만 다시 올리기 결과: {name} — 저장 {self.saved}/{len(self.results)}줄"
                   + (f" · 결의번호 {self.req_cnt}" if self.req_cnt else "") + (f" ({self.state})" if self.state else "")
                   + (" · 멈춤" if self.stopped else "")]
        if self.blocked:
            out.append("✗ " + self.blocked)
        for r in self.results:
            out.append(f"{r.label_text} {r.label}" + (f" — 청구내역 {r.sheet_row + 1}번째 줄" if r.sheet_row >= 0 else "")
                       + f" · 파일 {len(r.files)}개" + (f" · 지움 {r.removed} · 올림 {r.uploaded}" if r.status == "saved" else "")
                       + (f" — {r.note}" if r.note else ""))
        review = self.review_items()
        if review:
            out.append("신청 전 확인할 것:")
            out.extend("  · " + item for item in review)
        if not self.dry_run:
            out.append("ERP 에서 청구내역의 첨부를 검토하고 [신청] 은 직접 누르세요 — 앱은 누르지 않습니다")
        return out


# ── 실행 ───────────────────────────────────────────────────────────────
def match_rows(plan: Plan, sheet_rows: list[str]) -> dict[int, list[int]]:
    """계획의 줄(index 가 아니라 rows 의 차례 k)마다 청구내역 줄 번호들. 명단 청구는 sheet_check 의 맞추기(개별 적요 · 잘렸으면 이름),
    일반은 적요가 든 줄 — 청구내역이 한 줄뿐이고 계획도 한 줄이면 그 줄(대표적요로 이미 이 청구서를 찾았다)."""
    if plan.job is not None and kinds.uses_roster(plan.kind):
        from . import sheet_check
        hits, _strangers, _named = sheet_check.match_rows(plan.job, sheet_rows)
        return {k: list(hits.get(rp.index, [])) for k, rp in enumerate(plan.rows)}
    out: dict[int, list[int]] = {}
    for k, rp in enumerate(plan.rows):
        want = _squash(rp.summary)
        found = [r for r, text in enumerate(sheet_rows) if want and want in _squash(text)]
        if not found and len(sheet_rows) == 1 and len(plan.rows) == 1:
            found = [0]
        out[k] = found
    return out


def _state(frame, ids) -> dict:
    state = read_state(frame, list(ids))
    return {k: str((state.get(k) or {}).get("value", "") or "") for k in ids}


def row_loaded(frame, summary: str, sheet_text: str) -> tuple[bool, str]:
    """줄을 다시 연 뒤 — 입력 칸의 적요가 계획의 적요(또는 그 줄의 글자)와 같고 청구액이 있으면 열린 것."""
    st = _state(frame, ["REQ_PTCL", "REQ_AMT"])
    ptcl = _squash(st["REQ_PTCL"])
    if not ptcl:
        return False, "입력 칸의 적요가 비어 있음"
    want = _squash(summary)
    same = bool(want) and (want in ptcl or ptcl in want)
    if not same and ptcl[:PREFIX_MIN] not in _squash(sheet_text):
        return False, f"입력 칸의 적요 '{st['REQ_PTCL'][:40]}' 가 이 줄과 다름"
    if not _squash(st["REQ_AMT"]).strip("0,"):
        return False, "입력 칸의 청구액이 비어 있음"
    return True, ""


def open_row(frame, n: int, summary: str, sheet_text: str, wait: Callable[[float], None], log: Callable[[str], None]) -> tuple[bool, str]:
    """청구내역 n 번째 줄의 ○ 를 눌러 입력 칸에 그 줄이 들어올 때까지(실측 전 — 안 되면 부르는 쪽이 사람에게 묻는다)."""
    try:
        result = frame.evaluate(OPEN_ROW_JS, n) or {}
    except Exception as error:  # noqa: BLE001
        result = {"ok": False, "why": str(error).splitlines()[0][:80] if str(error) else "오류"}
    if not result.get("ok"):
        return False, "줄의 ○ 를 누르지 못함: " + str(result.get("why", ""))
    log("청구내역 %d번째 줄의 ○ 를 눌렀습니다" % (n + 1))
    wait_until(lambda: row_loaded(frame, summary, sheet_text)[0], wait, tries=ROW_TRIES)
    return row_loaded(frame, summary, sheet_text)


def clear_files(frame, wait: Callable[[float], None], log: Callable[[str], None]) -> tuple[bool, int, str]:
    """보이는 첨부문서 목록을 비운다 — 보기를 모두 골라 '삭제'(확인 창은 부르는 쪽의 처리기가 [확인]). 목록이 한 개씩만 골라지면 되풀이한다.
    (됐는지, 지운 수, 까닭)."""
    removed = 0
    for _ in range(40):
        count = attach.file_count(frame)
        if count == 0:
            return True, removed, ""
        try:
            picked = frame.evaluate(SELECT_ALL_FILES_JS) or {}
        except Exception as error:  # noqa: BLE001
            return False, removed, str(error).splitlines()[0][:80] if str(error) else "목록을 읽지 못함"
        if not picked.get("ok"):
            return False, removed, str(picked.get("why", ""))
        chosen = int(picked.get("selected") or 0)
        if chosen <= 0:
            return False, removed, "첨부문서 목록의 보기를 고르지 못함"
        try:
            clicked = frame.evaluate(CLICK_FILE_DELETE_JS) or {}
        except Exception as error:  # noqa: BLE001
            clicked = {"ok": False, "why": str(error).splitlines()[0][:80] if str(error) else "오류"}
        if not clicked.get("ok"):
            return False, removed, str(clicked.get("why", ""))
        log("첨부문서 %d개(목록 %d개)를 골라 '삭제' 를 눌렀습니다" % (chosen, count))
        if not wait_until(lambda: attach.file_count(frame) < count, wait, tries=ROW_TRIES):
            return False, removed, "'삭제' 를 눌렀지만 첨부문서 목록이 줄지 않음(%d개)" % count
        removed += count - attach.file_count(frame)
    return False, removed, "첨부문서 목록이 다 비지 않음"


def _ask_until(check: Callable[[], tuple[bool, str]], ask: Ask, message_for: Callable[[str], str],
               wait: Callable[[float], None]) -> tuple[bool, str]:
    ok, why = check()
    asks = 0
    while not ok and asks < MAX_ASKS:
        asks += 1
        if not ask(message_for(why)):
            return False, why + " — 멈춤"
        wait(0.5)
        ok, why = check()
    return ok, why


def _reattach_row(page, frame, rp: RowPlan, res: RowResult, sheet_index: int, sheet_text: str, log, ask: Ask, wait,
                  messages: list[str]) -> tuple[bool, str]:
    res.sheet_row = sheet_index
    # ① 줄 다시 열기 — 실측 전: 안 되면 사람이 열고 [계속]
    ok, why = open_row(frame, sheet_index, rp.summary, sheet_text, wait, log)
    if not ok:
        log("줄 다시 열기 — " + why)
        ok, why = _ask_until(
            lambda: row_loaded(frame, rp.summary, sheet_text), ask,
            lambda w: (f"청구내역 {sheet_index + 1}번째 줄({rp.label})을 다시 열지 못했습니다 — {w}. ERP 작성 화면에서 그 줄의 ○ 를 눌러"
                       "(ERP 의 방법으로) 입력 칸에 그 줄의 적요 · 청구액이 보이게 한 뒤 [계속]. 앱이 하게 고치려면 그 상태에서 "
                       "[화면 구조 저장] 을 보내 주세요."), wait)
        if not ok:
            return False, "줄 다시 열기: " + why
        res.review.append("줄 다시 열기는 사람이 했음 — [화면 구조 저장] 을 보내 주시면 앱이 합니다")
    res.detail.append("✓ 청구내역 %d번째 줄 다시 열림" % (sheet_index + 1))
    loaded_amt = _state(frame, ["REQ_AMT"]).get("REQ_AMT", "")
    # ② 첨부문서 비우기 — 실측 전: 안 되면 사람이 지우고 [계속]
    before = attach.file_count(frame)
    if before:
        ok, removed, why = clear_files(frame, wait, log)
        res.removed = removed
        if not ok:
            log("첨부문서 지우기 — " + why)
            ok, why = _ask_until(
                lambda: (attach.file_count(frame) == 0, f"첨부문서가 아직 {attach.file_count(frame)}개"), ask,
                lambda w: (f"첨부문서를 지우지 못했습니다({why}) — ERP 작성 화면의 첨부문서 목록에서 모두 고르고 '삭제' 를 누른 뒤 [계속]. "
                           f"({w})"), wait)
            if not ok:
                return False, "첨부문서 지우기: " + why
            res.removed = before
            res.review.append("첨부문서 지우기는 사람이 했음")
        res.detail.append("✓ 첨부문서 %d개 지움" % res.removed)
    else:
        res.detail.append("첨부문서 없음 — 지울 것 없음")
    # ③ 올리기 — attach.py(한 개씩 넣고 [업로드])
    up = attach.upload(page, frame, rp.files, log, wait, messages)
    res.detail.extend(up.lines())
    if not up.ok:
        ok, why = _ask_until(
            lambda: (attach.file_count(frame) >= len(rp.files), f"첨부문서 {attach.file_count(frame)}개(기대 {len(rp.files)}개)"), ask,
            lambda w: (f"첨부를 올리지 못했습니다({up.note}) — ERP 의 '첨부' 로 이 줄의 파일 {len(rp.files)}개를 직접 올린 뒤 [계속]. ({w})"),
            wait)
        if not ok:
            return False, "첨부 올리기: " + why
        res.review.append("첨부 올리기는 사람이 했음 — 올린 파일이 맞는지 확인")
    res.uploaded = up.uploaded if up.ok else attach.file_count(frame)
    # 담당자 그림(2026-10-23): 첨부문서를 '삭제' 한 뒤 청구액 칸이 비어 보였다. 이 기능은 청구내역 값을 넣지 않으므로(담당자 "청구내역은 입력하지 않고
    # 첨부문서만") 앱이 채우지 않고, 비어 있으면 사람이 줄의 청구액을 확인해 넣은 뒤 [계속] — 사람이 했으면 '신청 전 확인할 것' 에 남긴다.
    def amount_back():
        now = _state(frame, ["REQ_AMT"]).get("REQ_AMT", "")
        return bool(now.strip("0, ")), "청구액 칸이 비어 있음"
    if loaded_amt.strip("0, ") and not amount_back()[0]:
        log("첨부를 다시 올린 뒤 청구액 칸이 비어 있습니다(줄을 열 때는 %s) — 사람에게 묻습니다" % loaded_amt)
        ok, why = _ask_until(amount_back, ask,
                             lambda w: (f"첨부를 지우고 다시 올린 뒤 청구액 칸이 비었습니다(줄을 열 때는 {loaded_amt}). ERP 작성 화면의 청구액에 그 값을 넣은 뒤 [계속]. ({w})"), wait)
        if not ok:
            return False, "청구액: " + why
        res.review.append(f"첨부를 지운 뒤 청구액 칸이 비어 사람이 다시 넣었음(줄을 열 때 {loaded_amt}) — 청구액 확인")
    # ④ [저장] — 수정 저장. 앞 줄의 알림이 남아 있으면 이 줄 저장이 끝난 것으로 보이므로 비운다(scholarship 과 같다)
    messages.clear()
    save = save_draft(frame, log, messages, wait)
    res.detail.extend(save.lines()[:3])
    if not save.ok:
        return False, "[저장]: " + (save.note or " / ".join(save.messages) or "화면이 바뀌지 않음")
    return True, ""


def run(page, frame, plan: Plan, log: Callable[[str], None], ask: Ask | None = None, wait: Callable[[float], None] = time.sleep,
        messages: list[str] | None = None, should_stop: Callable[[], bool] = lambda: False, on_row=None,
        dry_run: bool = True, req_cnt: str = "", state: str = "") -> ReattachReport:
    """계획의 줄마다 첨부를 지우고 다시 올려 [저장]. page · frame 은 그 청구서의 작성 화면(navigate.open_saved_sheet). dry_run 이면 계획만.
    on_row(index, status, note) 는 줄마다 화면에. 사람에게 묻는 단계는 ask — False 면 [멈추기](남은 줄은 손대지 않는다)."""
    ask = ask or (lambda _m: False)
    on_row = on_row or (lambda _i, _s, _n: None)
    messages = messages if messages is not None else []
    report = ReattachReport(dry_run=dry_run, plan=plan, req_cnt=req_cnt, state=state, messages=messages)
    report.results = [RowResult(rp.index, rp.label, files=list(rp.files), note=rp.note,
                                status="skipped" if not rp.files else "planned") for rp in plan.rows]
    if dry_run or page is None or frame is None:
        return report
    log("첨부만 다시 올리기 시작: %s — %d줄 · 파일 %d개%s" % (plan.name, len(plan.rows), plan.files_total(),
                                                        f" · 결의번호 {req_cnt}({state})" if req_cnt else ""))
    if not wait_until(lambda: frame.evaluate(PROBE_JS) is True, wait, tries=40):
        report.blocked = "작성 화면이 뜨지 않았습니다"
        log(report.blocked)
        return report
    first_cnt, sheet_rows, _appr = _read_sheet(frame)
    if not sheet_rows:
        report.blocked = "작성 화면의 청구내역에 저장된 줄이 없습니다 — 첨부를 다시 올릴 줄이 없습니다"
        log(report.blocked)
        return report
    hits = match_rows(plan, sheet_rows)
    log("청구내역 %d줄 — 계획 %d줄 중 맞춘 것 %d줄" % (len(sheet_rows), len(plan.rows), sum(1 for k in hits if hits[k])))
    count_before = len(sheet_rows)
    for k, (rp, res) in enumerate(zip(plan.rows, report.results)):
        if should_stop():
            res.status, res.note = "stopped", "멈춤 요청"
            report.stopped = True
            on_row(rp.index, "stopped", res.note)
            break
        if not rp.files:
            on_row(rp.index, "skipped", res.note)
            continue
        targets = hits.get(k, [])
        if not targets:
            res.status, res.note = "skipped", "청구내역에 이 줄(적요)이 없음"
            on_row(rp.index, "skipped", res.note)
            log("%s — %s" % (rp.label, res.note))
            continue
        if len(targets) > 1:
            res.note = "청구내역에 같은 적요 줄이 %d개 — 모두에 붙임" % len(targets)
        on_row(rp.index, "erp", "")
        log("── %s (청구내역 %s번째 줄 · 파일 %d개)" % (rp.label, " · ".join(str(t + 1) for t in targets), len(rp.files)))
        ok, why = True, ""
        for target in targets:
            if not wait_until(lambda: frame.evaluate(PROBE_JS) is True, wait, tries=40):
                ok, why = False, "작성 화면이 다시 뜨지 않음"
                break
            ok, why = _reattach_row(page, frame, rp, res, target, sheet_rows[target], log, ask, wait, messages)
            if not ok:
                break
            # ⑤ 줄 수 · 결의번호가 그대로인지 — 늘었으면 고친 것이 아니라 새 줄로 저장된 것(사람이 지운다, 앱은 줄의 [삭제] 를 누르지 않는다)
            wait_until(lambda: frame.evaluate(PROBE_JS) is True, wait, tries=40)
            now_cnt, rows_after, _a = _read_sheet(frame)
            if len(rows_after) != count_before or (first_cnt and now_cnt and now_cnt != first_cnt):
                ok = False
                why = ("청구내역 줄이 %d → %d 로 바뀌었습니다 — 고친 것이 아니라 새 줄로 저장된 듯합니다. ERP 에서 늘어난 줄을 지우세요"
                       "(앱은 줄의 [삭제] 를 누르지 않습니다)" % (count_before, len(rows_after)) if len(rows_after) != count_before else
                       f"결의번호가 {first_cnt} → {now_cnt} 로 바뀌었습니다 — 다른 청구서에 저장된 듯합니다")
                res.status, res.note = "failed", why
                break
            sheet_rows = rows_after
        if ok:
            res.status = "saved"
            on_row(rp.index, "saved", res.note)
            log("✓ %s — 지움 %d · 올림 %d · [저장]" % (rp.label, res.removed, res.uploaded))
            continue
        res.status = "stopped" if why.endswith("멈춤") else "failed"
        res.note = why
        on_row(rp.index, res.status, why)
        log("✗ %s — %s" % (rp.label, why))
        report.stopped = True
        break
    for res in report.results:                       # 멈춘 뒤의 줄 — 손대지 않았다
        if res.status == "planned":
            res.status = "waiting"
            on_row(res.index, "waiting", "")
    return report
