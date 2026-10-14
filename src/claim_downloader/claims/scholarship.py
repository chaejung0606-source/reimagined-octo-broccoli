"""장학금 청구 — 지출 1건 폴더(명단 엑셀 + 공통증빙\\ + 개별증빙\\)를 읽어 ERP 작성 화면의 인건비(소득성 경비) 탭에 학생 한 명씩 넣고 [저장].

설계는 docs/roadmap.md 2-1절(담당자 확인 2026-10-14), 실측은 CLAUDE.md 14절 '장학금'. 학생 한 명마다:

    인건비 탭(#20) → 비목 '장학금' → 소득구분 '장학금' → 소득자 돋보기(person.py: 인적정보 탭, 학번이 맞는 행 하나) →
    계좌 대조 · 예금주조회 결과 확인 → 청구액 · 지급예정년월 · 적요(행 적요) → 첨부(attach.py: 공통 + 개별) → 저장 전 검사 → [저장](form.save_draft)
    → 청구내역에 한 줄 늘고 공제합계 0 인지 → 다음 사람

어느 단계에서든 앱이 확신을 못 하면(소득자 후보가 여럿 · 예금주조회 결과 없음 · 첨부 실패 · 계좌 불일치) 그 자리에서 멈추고 **사람에게 묻는다**
(ask: 받기 화면의 재로그인 띠처럼 [계속]/[멈추기]). 사람이 ERP 에서 그 단계를 마치고 [계속] 을 누르면 다시 확인하고 이어 간다. [멈추기] 면 거기서 끝 —
몇 번째 사람까지 저장됐는지 보고한다. 기본은 미리 보기(dry_run). [신청] · [삭제] · [초기화] · '복사하기' 는 절대 누르지 않는다.
인건비구분 라디오(PSNL_EXPN_DIV_CD)는 건드리지 않는다 — 장학금도 (90) 기타 그대로(담당자 확정 2026-10-14).

누르는 것: 탭 `#20`(CLICK_ID_JS) · 저장(form.save_draft) · 그 밖은 person.py · attach.py 가 누른다. Playwright 를 들여오지 않는다.
"""
from __future__ import annotations

import os
import re
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field

from .. import settings
from ..minutes.logbook import log as file_log
from ..minutes.textfile import _read_text
from . import attach, kinds, person, roster as roster_mod
from .form import PROBE_JS, SET_SELECT_JS, SET_TEXT_JS, read_state, save_draft
from .payee import CLICK_ID_JS, wait_until

TAB_ID = "20"                         # 작성 화면 서브탭 '인건비(소득성 경비)' — <a id="20">
TAB_VALUE = "20"                      # 숨은 #TAB_GB 가 이 값이면 인건비 탭
CATEGORY = "장학금"                    # 비목 보기 글자
INCOME_KIND = "장학금"                 # 소득구분 보기 글자 — 비목이 장학금이면 소득구분도 장학금(담당자 확정 2026-10-14)
COMMON_DIR_WORD = kinds.COMMON_WORD    # 폴더 이름에 이 글자가 들면 공통증빙
PERSON_DIR_WORD = kinds.PERSON_WORD    # 폴더 이름에 이 글자가 들면 개별증빙
EXCEL_SUFFIXES = kinds.EXCEL_SUFFIXES
MAX_ASKS = 3                          # 한 단계에서 사람에게 묻는 횟수

# 적요 규칙 — 담당자가 고칠 수 있다(~/.claim-downloader/장학금규칙.txt). {제목}=명단 B2 제목, {대표적요}, {이름}, {학번}, {강좌명}, {금액}
# TA 근로장학금은 한 학생이 여러 교과목을 맡으면 줄이 교과목마다 하나라, 개별 적요에 교과목을 넣어 줄을 구분한다.
# 담당자 지정(2026-10-14): 대표적요에서 명단 제목 끝의 '지급내역' 을 빼고(…근로장학금), TA 줄은 '대표적요(이름_교과목명)'.
# 예: 02_2026년도 9월 (나)형 근로장학금(홍길동_자료구조). 그 전 기본값 '행적요(나): {대표적요}({이름}_{학번}_{강좌명})' 은 지난 청구서 PDF 에서 읽은 꼴이었다.
RULES_HEADER = (
    "# 장학금 청구 적요 규칙\n"
    "# 대표적요·행 적요를 어떻게 만들지 정합니다. 저장만 하면 다음 [폴더 읽기] 부터 반영됩니다.\n"
    "# 쓸 수 있는 자리표: {제목} {대표적요} {이름} {학번} {강좌명} {금액}   ({강좌명} = 명단의 강좌명 · 교과목 열)\n"
    "# '제목에서 뺄 말' 은 {제목}(명단 B2 제목)에서 지울 말입니다. 쉼표로 여럿. 비우면 제목 그대로 씁니다.\n"
    "# '행적요(강좌)' 는 명단에 강좌명(교과목) 이 적힌 줄(TA 근로장학금)에 쓰입니다.\n"
    "# '행적요(나)' 처럼 괄호 안이 한 글자면 명단 제목의 '(나)형' 유형에만 쓰입니다(있으면 가장 먼저). 둘 다 아니면 '행적요' 를 씁니다.\n"
    "# 기본값으로 되돌리려면 이 파일을 지우고 프로그램을 다시 켜세요.\n\n"
)
RULES_DEFAULT = """대표적요: 02_{제목}
제목에서 뺄 말: 지급내역, 지급 내역
행적요: {대표적요}_{이름}
행적요(강좌): {대표적요}({이름}_{강좌명})"""

# 저장 뒤 '청구내역' 표 — 줄 수(행 라디오 CUR_REQ)와 '합계' 줄의 숫자(청구액 · 실지급액 · 공제합계 순, 실측 ⑤)
SUMMARY_JS = """() => {
  const rows = document.querySelectorAll('input[name=CUR_REQ]').length;
  const txt = e => (e.innerText || e.textContent || '').replace(/\\s+/g, ' ').trim();
  let totals = [];
  for (const tr of Array.from(document.querySelectorAll('tr'))) {
    const cells = Array.from(tr.children).map(txt);
    const i = cells.findIndex(c => c.replace(/\\s/g, '') === '합계');
    if (i < 0) continue;
    const nums = cells.slice(i + 1).map(c => c.replace(/[^\\d-]/g, '')).filter(c => c !== '' && c !== '-').map(Number);
    if (nums.length >= 2) { totals = nums; break; }
  }
  return {rows, totals};
}"""


# ── 규칙 ─────────────────────────────────────────────────────────────────
def parse_rules(text: str) -> dict[str, str]:
    rules: dict[str, str] = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        rules[key.strip().replace(" ", "")] = value.strip()
    return rules


def load_rules() -> dict[str, str]:
    """장학금규칙.txt(담당자) · 장학금규칙.기본값.txt(기준) 쌍 — 회의록·일반청구 규칙과 같은 방식."""
    path, base = str(settings.scholarship_rules_path()), str(settings.scholarship_rules_base_path())
    try:
        if os.path.exists(path):
            cur = _read_text(path)
            was = _read_text(base) if os.path.exists(base) else ""
            if cur.strip() and cur.strip() != was.strip():
                parsed = parse_rules(cur)
                if parsed.get("대표적요") and parsed.get("행적요"):
                    return parsed
        for p in (path, base):
            with open(p, "w", encoding="utf-8") as f:
                f.write(RULES_HEADER + RULES_DEFAULT + "\n")
    except Exception:  # noqa: BLE001
        file_log("장학금 규칙 파일 처리 실패\n" + traceback.format_exc())
    return parse_rules(RULES_DEFAULT)


def _render(template: str, values: dict) -> str:
    out = template
    for key, value in values.items():
        out = out.replace("{" + key + "}", str(value if value is not None else ""))
    return re.sub(r"\s+", " ", out).strip()


def clean_title(title: str, rules: dict[str, str] | None = None) -> str:
    """명단 B2 제목에서 '제목에서 뺄 말' 을 지운다 — '…근로장학금 지급내역' → '…근로장학금'."""
    rules = rules or parse_rules(RULES_DEFAULT)
    out = str(title or "")
    for word in (w.strip() for w in rules.get("제목에서뺄말", "").split(",")):
        if word:
            out = out.replace(word, " ")
    return re.sub(r"\s+", " ", out).strip()


def main_summary(title: str, rules: dict[str, str] | None = None) -> str:
    rules = rules or parse_rules(RULES_DEFAULT)
    return _render(rules.get("대표적요", "02_{제목}"), {"제목": clean_title(title, rules)})


def row_summary(main: str, p: roster_mod.Person, kind: str, rules: dict[str, str] | None = None) -> str:
    rules = rules or parse_rules(RULES_DEFAULT)
    template = rules.get(f"행적요({kind})") if kind else None
    if not template and p.course:
        template = rules.get("행적요(강좌)")         # TA — 한 학생의 교과목마다 줄이 따로라 교과목으로 구분
    template = template or rules.get("행적요", "{대표적요}_{이름}")
    return _render(template, {"대표적요": main, "이름": p.name, "학번": p.student_no, "강좌명": p.course,
                              "금액": f"{p.amount:,}" if p.amount else ""})


# ── 폴더 ─────────────────────────────────────────────────────────────────
@dataclass
class Job:
    folder: str
    roster: roster_mod.Roster
    excel_candidates: list[str] = field(default_factory=list)
    common_files: list[str] = field(default_factory=list)
    person_files: dict[int, list[str]] = field(default_factory=dict)   # 명단 index → 그 학생의 개별 파일
    unmatched: list[str] = field(default_factory=list)                 # 어느 학생 것인지 못 정한 개별 파일
    main_summary: str = ""
    pay_ym: str = ""                                                    # 지급예정년월 YYYY-MM
    tab: str = person.TAB_STUDENT
    selected: list[bool] = field(default_factory=list)
    rules: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def people(self) -> list[roster_mod.Person]:
        return self.roster.people

    def chosen(self) -> list[int]:
        return [i for i, on in enumerate(self.selected) if on]

    def count_text(self, indexes: list[int] | None = None) -> str:
        """'3명', 또는 한 학생이 교과목 여럿이면 '4줄(3명)' — ERP 에는 줄 수만큼 [저장] 한다."""
        indexes = self.chosen() if indexes is None else indexes
        students = len({(self.people[i].name.replace(" ", ""), self.people[i].student_no or f"#{i}") for i in indexes})
        return f"{len(indexes)}명" if students == len(indexes) else f"{len(indexes)}줄({students}명)"

    def files_for(self, index: int) -> list[str]:
        return list(self.common_files) + list(self.person_files.get(index, []))

    def row_summary(self, index: int) -> str:
        return row_summary(self.main_summary, self.people[index], self.roster.kind, self.rules)

    def problems(self) -> list[str]:
        out = list(self.warnings) + self.roster.problems()
        if not self.main_summary:
            out.append("대표적요가 비어 있습니다")
        if not re.fullmatch(r"\d{4}-\d{2}", self.pay_ym or ""):
            out.append("지급예정년월은 YYYY-MM 꼴이어야 합니다")
        if self.unmatched:
            out.append("어느 학생 것인지 모르는 개별증빙 %d개: %s" % (len(self.unmatched), " · ".join(os.path.basename(f) for f in self.unmatched[:5])))
        # ERP 청구내역 표에서는 줄을 적요로 구분한다 — 같은 적요가 둘이면 어느 줄이 누구 것인지 모른다
        summaries = [self.row_summary(i) for i in range(len(self.people))]
        same = sorted({t for t in summaries if t and summaries.count(t) > 1})
        for text in same:
            out.append(f"개별 적요가 같은 줄이 둘 이상입니다: {text} — 장학금규칙.txt 로 구분되게 고치세요")
        return out

    def summary_lines(self) -> list[str]:
        chosen = self.chosen()
        total = sum(self.people[i].amount or 0 for i in chosen)
        return [f"폴더: {self.folder}", f"명단: {os.path.basename(self.roster.path)} — {self.roster.title or '제목 없음'}",
                f"대표적요: {self.main_summary}", f"지급예정년월: {self.pay_ym} · 소득자 구분: {self.tab}",
                f"넣을 사람 {self.count_text(chosen)} / 명단 {self.count_text(list(range(len(self.people))))} · 합계 {total:,}원",
                f"공통증빙 {len(self.common_files)}개 · 개별증빙 {sum(len(v) for v in self.person_files.values())}개"]


def _files_under(folder: str) -> list[str]:
    out = []
    for root, _dirs, files in os.walk(folder):
        for fn in sorted(files):
            out.append(os.path.join(root, fn))
    return attach.attachable(out)


def _subdirs_with(folder: str, word: str) -> list[str]:
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    return [os.path.join(folder, n) for n in names if word in n and os.path.isdir(os.path.join(folder, n))]


def _rows_of_student(key: str, indexes: list[int], people: list[roster_mod.Person]) -> list[int]:
    """같은 이름 줄들 중 이 파일(경로 글자 key)의 줄. 담당자 규칙(2026-10-14): 학번이 다르면 다른 학생, 학번까지 같으면
    한 학생이 교과목 여럿을 맡은 것. 그래서 학번으로 학생을 정하고(동명이인이면 경로에 학번이 있어야 한다), 그 학생의 줄이
    여럿이면 경로에 교과목이 있는 줄 하나 — 교과목이 없으면 그 학생의 모든 줄(교과목마다 같은 개인 서류를 붙인다)."""
    if len({people[i].student_no for i in indexes}) > 1:
        indexes = [i for i in indexes if people[i].student_no and people[i].student_no in key]
        if len({people[i].student_no for i in indexes}) != 1:
            return []
    by_course = [i for i in indexes if people[i].course and people[i].course.replace(" ", "") in key]
    return by_course if len(by_course) == 1 else indexes


def assign_person_files(files: list[str], base: str, people: list[roster_mod.Person]) -> tuple[dict[int, list[str]], list[str]]:
    """개별증빙 파일을 학생에게 — 파일명이나 상위 폴더 이름에 이름이 들어 있으면 그 학생. 같은 이름이 둘이면 학번으로 가린다."""
    by_name: dict[str, list[int]] = {}
    for i, p in enumerate(people):
        by_name.setdefault(p.name.replace(" ", ""), []).append(i)
    assigned: dict[int, list[str]] = {}
    unmatched: list[str] = []
    for path in files:
        rel = os.path.relpath(path, base).replace("\\", "/")
        key = rel.replace(" ", "")
        hits: set[int] = set()
        for name, indexes in by_name.items():
            if name and name in key:
                hits.update(_rows_of_student(key, indexes, people))
        # 한 학생의 줄만 맞았을 때만 붙인다 — 두 학생에 걸리면 사람이 정한다
        students = {(people[i].name.replace(" ", ""), people[i].student_no) for i in hits}
        if hits and len(students) == 1:
            for i in sorted(hits):
                assigned.setdefault(i, []).append(path)
        else:
            unmatched.append(path)
    return assigned, unmatched


def load_job(folder: str, excel: str | None = None, rules: dict[str, str] | None = None) -> Job:
    """폴더를 읽어 Job 을 만든다. 엑셀이 둘 이상이면 excel 로 고른다(없으면 warnings 에 알리고 첫째)."""
    rules = rules or load_rules()
    folder = str(folder)
    try:
        entries = sorted(os.listdir(folder))
    except OSError:
        entries = []
    candidates = [os.path.join(folder, n) for n in entries
                  if n.lower().endswith(EXCEL_SUFFIXES) and not n.startswith(("~$", "."))]
    chosen = excel if excel and os.path.isfile(excel) else (candidates[0] if candidates else "")
    roster = roster_mod.read(chosen) if chosen else roster_mod.Roster(path="", warnings=["폴더 바로 아래에 명단 엑셀(.xlsx)이 없습니다"])
    job = Job(folder=folder, roster=roster, excel_candidates=candidates, rules=rules)
    if len(candidates) > 1 and not excel:
        job.warnings.append("엑셀이 %d개 있어 첫 것을 읽었습니다: %s" % (len(candidates), os.path.basename(chosen)))
    for d in _subdirs_with(folder, COMMON_DIR_WORD):
        job.common_files.extend(_files_under(d))
    person_dirs = _subdirs_with(folder, PERSON_DIR_WORD)
    files = [f for d in person_dirs for f in _files_under(d)]
    if person_dirs:
        job.person_files, job.unmatched = assign_person_files(files, person_dirs[0] if len(person_dirs) == 1 else folder, roster.people)
    if not job.common_files and not files:
        job.warnings.append("공통증빙\\ · 개별증빙\\ 폴더가 비어 있거나 없습니다 — 첨부 없이 넣습니다")
    job.main_summary = main_summary(roster.title, rules) if roster.title else ""
    job.pay_ym = time.strftime("%Y-%m")
    job.selected = [bool(p.name) and p.amount is not None and p.amount > 0 for p in roster.people]
    return job


# ── ERP 흐름 ──────────────────────────────────────────────────────────────
@dataclass
class PersonResult:
    index: int
    name: str
    status: str = "waiting"          # planned · saved · stopped · failed
    lines: list[str] = field(default_factory=list)
    note: str = ""
    # 화면의 결과 표가 쓰는 값 — 글 줄(lines)을 다시 쪼개지 않게 따로 둔다
    student_no: str = ""
    course: str = ""
    amount: int | None = None
    summary: str = ""
    files: list[str] = field(default_factory=list)     # 공통 먼저, 그다음 개별
    common_count: int = 0


@dataclass
class ScholarshipReport:
    dry_run: bool
    results: list[PersonResult] = field(default_factory=list)
    blocked: str = ""
    stopped: bool = False
    messages: list[str] = field(default_factory=list)

    @property
    def saved(self) -> int:
        return sum(1 for r in self.results if r.status == "saved")

    def lines(self) -> list[str]:
        out = ["미리 보기 (ERP 에 넣지 않음)" if self.dry_run else f"ERP 임시저장 {self.saved}명" + (" — 멈춤" if self.stopped else "")]
        if self.blocked:
            out.append("✗ " + self.blocked)
        for r in self.results:
            mark = {"saved": "✓", "planned": "·", "stopped": "■", "failed": "✗"}.get(r.status, "·")
            out.append(f"{mark} {r.index + 1}. {r.name}" + (f" — {r.note}" if r.note else ""))
            out.extend("    " + line for line in r.lines)
        if not self.dry_run:
            out.append("사람이 할 것: ERP 에서 청구내역을 검토하고 [신청] 을 직접 누르세요 — 앱은 누르지 않습니다")
        return out


Ask = Callable[[str], bool]       # 사람에게 묻는다 — True 면 [계속], False 면 [멈추기]


def _state(frame, ids) -> dict:
    state = read_state(frame, list(ids))
    return {k: (state.get(k) or {}).get("value", "") for k in ids}


def _set(frame, kind: str, element_id: str, value: str) -> dict:
    try:
        return frame.evaluate(SET_SELECT_JS if kind == "select" else SET_TEXT_JS, [element_id, value])
    except Exception as error:  # noqa: BLE001
        return {"ok": False, "why": str(error).splitlines()[0][:80] if str(error) else "오류"}


def _digits(text: str) -> str:
    return re.sub(r"\D", "", str(text or ""))


def _same(a, b) -> bool:
    return re.sub(r"\s+", "", str(a or "")) == re.sub(r"\s+", "", str(b or ""))


def _select_text(frame, element_id: str) -> str:
    return ((read_state(frame, [element_id]).get(element_id) or {}).get("text", "")) or ""


def _ensure_income(frame, wait, log, result: PersonResult, when: str) -> tuple[bool, str]:
    """소득구분이 '장학금' 이 아니면 다시 고른다.

    담당자 첫 시험(2026-10-14 15:34): 비목 다음에 '장학금' 으로 골랐는데(✓) 첨부까지 마친 뒤 저장 전 검사에서는 다른 값이었다.
    소득자를 고르면 ERP 가 소득구분을 그 사람의 기본값으로 되돌리는 것으로 보인다(추정 — 어느 단계인지는 로그의 이 줄로 본다).
    그래서 소득자를 고른 뒤와 저장 직전에 다시 보고 고친다. 고쳐지지 않으면 사람에게 묻는다(_ask_until)."""
    now = _select_text(frame, "INCM_DIV_CD")
    if _same(now, INCOME_KIND):
        return True, now
    log("소득구분이 '%s' 로 바뀌어 있어 다시 '%s' 로 고릅니다 (%s)" % (now or "비어 있음", INCOME_KIND, when))
    r = _set(frame, "select", "INCM_DIV_CD", INCOME_KIND)
    wait(0.4)
    after = _select_text(frame, "INCM_DIV_CD")
    if _same(after, INCOME_KIND):
        result.lines.append(f"✓ 소득구분 장학금 ({when} '{now or '비어 있음'}' 이어서 다시 고름)")
        return True, after
    return False, (f"소득구분이 '{after or now or '비어 있음'}' 입니다"
                   + ("" if r.get("ok") else f" — 다시 고르지 못함: {r.get('why', '')}"))


def new_result(job: Job, index: int, status: str = "waiting") -> PersonResult:
    p = job.people[index]
    return PersonResult(index=index, name=p.name, status=status, student_no=p.student_no, course=p.course,
                        amount=p.amount, summary=job.row_summary(index), files=job.files_for(index),
                        common_count=len(job.common_files))


def plan_person(job: Job, index: int) -> PersonResult:
    p = job.people[index]
    files = job.files_for(index)
    result = new_result(job, index, "planned")
    result.lines = [f"학번 {p.student_no or '—'} · 청구액 {p.amount:,}원" if p.amount else f"학번 {p.student_no or '—'} · 청구액 —",
                    f"적요: {job.row_summary(index)}",
                    f"첨부 {len(files)}개" + (": " + " · ".join(os.path.basename(f) for f in files[:6]) if files else "")]
    if p.note:
        result.note = p.note
    return result


def run(page, frame, job: Job, log: Callable[[str], None], ask: Ask, wait: Callable[[float], None] = time.sleep,
        messages: list[str] | None = None, should_stop: Callable[[], bool] = lambda: False,
        on_person: Callable[[int, str, str], None] | None = None, dry_run: bool = True,
        auto_pick: bool = True) -> ScholarshipReport:
    """고른 사람을 차례로 넣는다. dry_run 이면 계획만. on_person(index, 상태, 설명)으로 진행을 알린다."""
    # messages 는 ERP 알림을 받는 쪽(session)이 채우는 살아 있는 목록이다. 학생마다 비우고 보고서에 옮겨 둔다 —
    # 앞 학생의 '저장되었습니다' 가 남아 있으면 다음 학생의 저장이 끝나기 전에 끝난 것으로 볼 수 있다.
    live = messages if messages is not None else []
    report = ScholarshipReport(dry_run=dry_run)
    chosen = job.chosen()
    log("장학금 청구 %s — %d명" % ("미리 보기" if dry_run else "시작", len(chosen)))
    for line in job.summary_lines():
        log("  " + line)
    if dry_run:
        report.results = [plan_person(job, i) for i in chosen]
        return report
    notify = on_person or (lambda _i, _s, _d: None)
    for index in chosen:
        if should_stop():
            report.stopped = True
            break
        p = job.people[index]
        notify(index, "running", "")
        result = new_result(job, index)
        live.clear()
        try:
            ok, note = _run_person(page, frame, job, index, log, ask, wait, live, result, auto_pick)
        except Exception as error:  # noqa: BLE001 — 한 사람에서 터져도 어디까지 됐는지는 알려 준다
            log("장학금 청구 오류(%s)\n%s" % (p.name, traceback.format_exc()))
            ok, note = False, "오류: " + (str(error).splitlines()[0][:100] if str(error) else type(error).__name__)
        report.messages.extend(live)
        live.clear()
        result.note = note
        result.status = "saved" if ok else "stopped"
        report.results.append(result)
        notify(index, result.status, note)
        if not ok:
            report.stopped = True
            log("장학금 청구 멈춤 — %d. %s: %s" % (index + 1, p.name, note))
            break
    log("장학금 청구 끝 — 임시저장 %d명%s" % (report.saved, " (멈춤)" if report.stopped else ""))
    return report


def _ask_until(check: Callable[[], tuple[bool, str]], ask: Ask, message_for: Callable[[str], str],
               wait: Callable[[float], None]) -> tuple[bool, str]:
    """check 가 (True, ·) 를 줄 때까지 사람에게 묻는다. [멈추기] 면 (False, 이유)."""
    ok, why = check()
    asks = 0
    while not ok and asks < MAX_ASKS:
        asks += 1
        if not ask(message_for(why)):
            return False, why + " — 멈춤"
        wait(0.5)
        ok, why = check()
    return ok, why


def _run_person(page, frame, job: Job, index: int, log, ask: Ask, wait, messages: list[str],
                result: PersonResult, auto_pick: bool) -> tuple[bool, str]:
    p = job.people[index]
    summary = job.row_summary(index)
    log("── %d. %s (학번 %s · %s원)" % (index + 1, p.name, p.student_no or "—", f"{p.amount:,}" if p.amount else "—"))

    # 0. 작성 화면 — [저장] 뒤에는 프레임이 다시 열린다(실측 ⑤). 다 뜰 때까지 기다린다
    if not wait_until(lambda: frame.evaluate(PROBE_JS) is True, wait, tries=40):
        return False, "작성 화면이 다시 뜨지 않음"

    # 1. 인건비 탭
    clicked = frame.evaluate(CLICK_ID_JS, TAB_ID)
    if not clicked.get("ok"):
        return False, "인건비(소득성 경비) 탭을 누르지 못함: " + str(clicked.get("why", ""))
    if not wait_until(lambda: _state(frame, ["TAB_GB"])["TAB_GB"] == TAB_VALUE, wait, tries=20):
        return False, "인건비(소득성 경비) 탭으로 바뀌지 않음"
    wait(0.3)

    # 2. 비목 → 소득구분 (인건비구분 라디오는 건드리지 않는다)
    r = _set(frame, "select", "PAY_EXP_CD", CATEGORY)
    if not r.get("ok"):
        return False, "비목을 '장학금' 으로 고르지 못함: " + str(r.get("why", ""))
    wait(0.6)                                                   # 비목을 고르면 잔액·인건비구분이 다시 그려진다
    r = _set(frame, "select", "INCM_DIV_CD", INCOME_KIND)
    if not r.get("ok"):
        return False, "소득구분을 '장학금' 으로 고르지 못함: " + str(r.get("why", ""))
    result.lines.append("✓ 비목 장학금 · 소득구분 장학금")

    # 3. 소득자 — 학번이 맞는 행 하나면 앱이, 아니면 사람
    def person_ok() -> tuple[bool, str]:
        s = _state(frame, ["RCV_CD", "RCV_NM"])
        if p.student_no and _digits(s["RCV_CD"]) == p.student_no:
            return True, ""
        if not p.student_no and s["RCV_NM"].replace(" ", "") == p.name.replace(" ", ""):
            return True, ""
        return False, f"작성 화면의 소득자가 {p.name}({p.student_no or '학번 없음'}) 이 아님 (지금: {s['RCV_NM'] or '—'} {s['RCV_CD'] or ''})"

    found = person.search(page, frame, p.name, p.student_no, log, wait=wait, messages=messages, tab=job.tab, auto_pick=auto_pick)
    result.lines.extend(found.lines())
    ok, why = _ask_until(person_ok, ask, lambda w: ("%d. %s — 소득자 팝업에서 %s 을(를) 고르고 [확인] 을 누른 뒤 [계속] 을 누르세요.\n(%s)"
                                                    % (index + 1, p.name, p.name, found.pick_note or found.note or w)), wait)
    if not ok:
        return False, "소득자를 고르지 못함"
    wait(0.5)

    def income_message(why: str) -> str:
        return ("%d. %s — ERP 작성 화면의 소득구분을 '장학금' 으로 골라 주세요 (%s). 고른 뒤 [계속], 아니면 [멈추기]."
                % (index + 1, p.name, why))

    ok, why = _ask_until(lambda: _ensure_income(frame, wait, log, result, "소득자를 고른 뒤"), ask, income_message, wait)
    if not ok:
        return False, why + " — 저장하지 않았습니다"

    # 4. 계좌 대조 · 예금주조회 결과
    s = _state(frame, ["ACCT_NO", "BNK_CD", "OWNR", "OWNR_INQ_RSLT"])
    if p.account_digits and _digits(s["ACCT_NO"]) and p.account_digits != _digits(s["ACCT_NO"]):
        msg = ("%d. %s — 명단의 계좌(%s)와 ERP 가 채운 계좌(%s)가 다릅니다. ERP 의 계좌가 맞는지 확인한 뒤 [계속], 아니면 [멈추기]."
               % (index + 1, p.name, p.account, s["ACCT_NO"]))
        log("계좌 불일치: 명단 %s / ERP %s" % (p.account, s["ACCT_NO"]))
        if not ask(msg):
            return False, "계좌가 명단과 다름 — 멈춤"
        result.lines.append("! 계좌가 명단과 달라 사람이 확인함")
    else:
        result.lines.append("✓ 계좌 %s (명단과 %s)" % (s["ACCT_NO"] or "—", "같음" if p.account_digits else "대조 안 함"))

    def owner_ok() -> tuple[bool, str]:
        v = _state(frame, ["OWNR_INQ_RSLT"])["OWNR_INQ_RSLT"]
        return (v.startswith("성공"), v or "비어 있음")

    ok, why = _ask_until(owner_ok, ask, lambda w: ("%d. %s — 예금주조회 결과가 '%s' 입니다. ERP 에서 [예금주조회] 를 눌러 '성공' 을 확인한 뒤 [계속] 을 누르세요."
                                                   % (index + 1, p.name, w)), wait)
    if not ok:
        return False, "예금주조회 결과 없음"
    result.lines.append("✓ 예금주조회 " + _state(frame, ["OWNR_INQ_RSLT"])["OWNR_INQ_RSLT"])

    # 5. 청구액 · 지급예정년월 · 적요 (· 첫 사람이면 대표적요)
    for element_id, value, label in (("REQ_AMT", str(p.amount or ""), "청구액"), ("PAY_PLAN_YM", job.pay_ym, "지급예정년월"),
                                     ("REQ_PTCL", summary, "적요")):
        r = _set(frame, "text", element_id, value)
        if not r.get("ok"):
            return False, f"{label} 을(를) 넣지 못함: " + str(r.get("why", ""))
    appl = read_state(frame, ["APPL_CONT"]).get("APPL_CONT") or {}
    if appl and not appl.get("readonly") and not appl.get("disabled") and not (appl.get("value") or "").strip():
        r = _set(frame, "text", "APPL_CONT", job.main_summary)
        if r.get("ok"):
            result.lines.append("✓ 대표적요 " + job.main_summary)
    result.lines.append("✓ 청구액 %s · 지급예정년월 %s · 적요 %s" % (f"{p.amount:,}" if p.amount else "—", job.pay_ym, summary))

    # 6. 첨부
    files = job.files_for(index)
    if files:
        def attach_ok() -> tuple[bool, str]:
            rep = attach.upload(page, frame, files, log, wait=wait, messages=messages)
            result.lines.extend(rep.lines())
            return rep.ok, rep.note

        ok, why = _ask_until(attach_ok, ask, lambda w: ("%d. %s — 첨부를 올리지 못했습니다(%s). ERP 의 '첨부' 로 %d개를 직접 올린 뒤 [계속] 을 누르세요. "
                                                       "(앱이 다시 시도합니다 — 이미 올렸으면 [계속] 을 누르고 중복된 것은 ERP 에서 지우세요)"
                                                       % (index + 1, p.name, w, len(files))), wait)
        if not ok:
            return False, "첨부 실패"
    else:
        result.lines.append("· 첨부 없음")

    # 7. 저장 전 검사 — 소득구분은 첨부 뒤에도 한 번 더 보고 고친다(위 _ensure_income)
    ok, why = _ask_until(lambda: _ensure_income(frame, wait, log, result, "저장 직전"), ask, income_message, wait)
    if not ok:
        return False, why + " — 저장하지 않았습니다"
    s = read_state(frame, ["PAY_EXP_CD", "INCM_DIV_CD", "REQ_AMT", "REQ_PTCL", "RCV_NM"])
    pay = (s.get("PAY_EXP_CD") or {}).get("text", "")
    income = (s.get("INCM_DIV_CD") or {}).get("text", "")
    amount = (s.get("REQ_AMT") or {}).get("value", "")
    checks = {
        f"비목(지금: {pay or '비어 있음'})": _same(pay, CATEGORY),
        f"소득구분(지금: {income or '비어 있음'})": _same(income, INCOME_KIND),
        f"청구액(지금: {amount or '비어 있음'})": _digits(amount) == str(p.amount or ""),
        "적요(비어 있음)": bool((s.get("REQ_PTCL") or {}).get("value", "").strip()),
        "소득자(비어 있음)": bool((s.get("RCV_NM") or {}).get("value", "").strip()),
    }
    bad = [k for k, v in checks.items() if not v]
    if bad:
        log("저장 전 검사 어긋남: " + " · ".join(bad))
        return False, "저장 전 검사에서 어긋남: " + " · ".join(bad) + " — 저장하지 않았습니다"

    # 8. [저장]
    before = _summary(frame)
    saved = save_draft(frame, log, messages, wait=wait)
    result.lines.extend(saved.lines()[:3])
    after = before
    wait_until(lambda: frame.evaluate(PROBE_JS) is True, wait, tries=40)     # 다시 열리는 중
    for _ in range(8):
        after = _summary(frame)
        if int(after.get("rows") or 0) > int(before.get("rows") or 0):
            break
        wait(0.5)
    rows_before, rows_after = int(before.get("rows") or 0), int(after.get("rows") or 0)
    if not saved.ok and rows_after <= rows_before:
        return False, saved.note or "저장이 확인되지 않음"
    if rows_after <= rows_before:
        log("청구내역 줄 수가 늘지 않음 (%d → %d) — ERP 에서 확인 필요" % (rows_before, rows_after))
        if not ask("%d. %s — [저장] 을 눌렀지만 청구내역 표에 줄이 늘지 않았습니다(%d → %d). ERP 에서 저장됐는지 확인한 뒤 [계속], 아니면 [멈추기]."
                   % (index + 1, p.name, rows_before, rows_after)):
            return False, "저장 뒤 청구내역이 늘지 않음 — 멈춤"
    totals = list(after.get("totals") or [])
    if len(totals) >= 3 and totals[2]:
        log("합계 줄 공제합계가 %s — 소득구분을 확인하세요" % f"{totals[2]:,}")
        if not ask("%d. %s — 청구내역 합계의 공제합계가 %s 입니다(장학금이면 0 이어야 함). ERP 에서 소득구분을 확인한 뒤 [계속], 아니면 [멈추기]."
                   % (index + 1, p.name, f"{totals[2]:,}")):
            return False, "공제합계가 0 이 아님 — 멈춤"
    result.lines.append("✓ 청구내역 %d줄" % rows_after + (f" · 공제합계 {totals[2]:,}" if len(totals) >= 3 else ""))
    return True, "임시저장"


def _summary(frame) -> dict:
    try:
        return frame.evaluate(SUMMARY_JS) or {}
    except Exception:  # noqa: BLE001 — 저장 뒤 다시 열리는 중
        return {}


def record_job(job: Job, report: ScholarshipReport) -> None:
    """채운 기록(_청구입력기록.json) — 같은 폴더를 다시 넣으려 하면 묻는 근거."""
    from . import record
    record.remember(job.folder, {"amount": sum(job.people[r.index].amount or 0 for r in report.results if r.status == "saved"),
                                 "summary": job.main_summary + f" ({report.saved}명)"})

