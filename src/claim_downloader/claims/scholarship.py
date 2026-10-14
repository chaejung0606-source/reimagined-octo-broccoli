"""장학금 청구 — 지출 1건 폴더(명단 엑셀 + 공통증빙\\ + 개별증빙\\)를 읽어 ERP 작성 화면의 인건비(소득성 경비) 탭에 학생 한 명씩 넣고 [저장].

설계는 docs/roadmap.md 2-1절(담당자 확인 2026-10-14), 실측은 CLAUDE.md 14절 '장학금'. 학생 한 명마다:

    인건비 탭(#20) → 비목 '장학금' → 소득구분 '장학금' → 소득자 돋보기(person.py: 인적정보 탭, 학번이 맞는 행 하나) →
    계좌 대조 · 예금주조회 결과 확인 → 청구액 · 지급예정년월 · 적요(행 적요) → 첨부(attach.py: 공통 + 개별) → 저장 전 검사 → [저장](form.save_draft)
    → 청구내역에 한 줄 늘고 공제합계 0 인지 → 다음 사람

어느 단계에서든 앱이 확신을 못 하면(소득자 후보가 여럿 · 예금주조회 결과 없음 · 첨부 실패 · 계좌 불일치) 그 자리에서 멈추고 **사람에게 묻는다**
(ask: 받기 화면의 재로그인 띠처럼 [계속]/[멈추기]). 사람이 ERP 에서 그 단계를 마치고 [계속] 을 누르면 다시 확인하고 이어 간다. [멈추기] 면 거기서 끝 —
몇 번째 사람까지 저장됐는지 보고한다. 기본은 미리 보기(dry_run). [신청] · [삭제] · [초기화] · '복사하기' 는 절대 누르지 않는다.
인건비구분 라디오(PSNL_EXPN_DIV_CD)는 건드리지 않는다 — 장학금도 (90) 기타 그대로(담당자 확정 2026-10-14).

누르는 것: 탭 `#20` · [예금주조회](CLICK_ID_JS) · 저장(form.save_draft) · 그 밖은 person.py · attach.py 가 누른다. Playwright 를 들여오지 않는다.
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
from . import attach, kinds, nation as nation_mod, person, roster as roster_mod
from .nation import same_country  # noqa: F401 — 테스트 · 화면이 scholarship.same_country 로 부른다
from .form import PROBE_JS, SET_SELECT_JS, SET_TEXT_JS, read_state, save_draft
from .payee import CLICK_ID_JS, wait_until

TAB_ID = "20"                         # 작성 화면 서브탭 '인건비(소득성 경비)' — <a id="20">
TAB_VALUE = "20"                      # 숨은 #TAB_GB 가 이 값이면 인건비 탭
CATEGORY = "장학금"                    # 비목 보기 글자 (장학금)
INCOME_KIND = "장학금"                 # 소득구분 보기 글자 — 비목이 장학금이면 소득구분도 장학금(담당자 확정 2026-10-14). 혁신인재지원금도 장학금(공제 0)
# [예금주조회] — 담당자 결정(2026-10-14): 앱이 누르고, 새 결과가 '성공:학생이름' 이 아니면 사람에게 맡긴다.
# 계좌 예금주를 확인만 하는 조회다(돈이 나가지 않는다). '일괄예금주조회' 는 누르지 않는다.
OWNER_CHECK_ID = "btn_ownrInq"
# 외국인 학생 — 외국인등록번호는 뒷자리 첫 숫자가 5~8 이다(내국인 1~4). 작성 화면 #VW_SSN 은 '######-3******' 처럼 그 숫자만 보인다(실측 ②).
# 국적(#NATION_CD, 읽기전용 · 기본 KR)은 #btnNationCd 돋보기 → 국적조회 팝업에서 고른다(nation.py, 실측 2026-10-14 18:45). 나라는
# 명단 엑셀의 '국적' 열에서 온다 — 없거나 앱이 못 고르면 사람이 신분증을 보고 고른다. 끝나면 #NATION_CD 가 KR 이 아닌지 본다.
FOREIGN_SSN_DIGITS = "5678"
HOME_NATION = "KR"
# 보이는 단추가 있는지만 — 같은 id 가 안 쓰는 탭에도 숨어 있다(14절 ① 함정). 숨은 쪽을 누르면 다른 탭의 빈 계좌를 조회한다.
VISIBLE_ID_JS = """(id) => Array.from(document.querySelectorAll('[id="' + String(id).replace(/"/g, '\\"') + '"]'))
  .some(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; })"""
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


@dataclass(frozen=True)
class Spec:
    """명단으로 사람마다 인건비 탭에 넣는 청구 종류마다 다른 것 — 담당자(2026-10-14): 혁신인재지원금은 장학금과 ERP 쓰는 법이 같고 비목만 다르다.
    (청구서 PDF 로도 확인: 혁신인재지원금도 인건비 탭 · 소득구분 장학금 · 공제 0 — CLAUDE.md 14절 '장학금 밖의 청구')"""
    kind: str
    name: str                    # 화면 · 로그에 보이는 이름
    category: str                # ERP 비목(#PAY_EXP_CD) 보기 글자 — 실측 그대로
    code: str                    # 대표적요 앞의 비목 번호(8절)
    rules_path: Callable[[], object]
    rules_base_path: Callable[[], object]

    @property
    def rules_file(self) -> str:
        return os.path.basename(str(self.rules_path()))

    @property
    def rules_default(self) -> str:
        return RULES_DEFAULT.replace("02_", f"{self.code}_", 1)


SPECS = {
    kinds.SCHOLARSHIP: Spec(kinds.SCHOLARSHIP, "장학금", CATEGORY, "02",
                            settings.scholarship_rules_path, settings.scholarship_rules_base_path),
    kinds.INNOVATION: Spec(kinds.INNOVATION, "혁신인재지원금", "교육·연구프로그램개발·운영비", "03",
                           settings.innovation_rules_path, settings.innovation_rules_base_path),
}


def spec_for(kind: str) -> Spec:
    return SPECS.get(kind, SPECS[kinds.SCHOLARSHIP])


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


def load_rules(spec: Spec | None = None) -> dict[str, str]:
    """장학금규칙.txt(담당자) · 장학금규칙.기본값.txt(기준) 쌍 — 회의록·일반청구 규칙과 같은 방식. 혁신인재지원금은 그 이름의 파일 쌍."""
    spec = spec or SPECS[kinds.SCHOLARSHIP]
    default = spec.rules_default
    header = RULES_HEADER.replace("# 장학금 청구 적요 규칙", f"# {spec.name} 청구 적요 규칙", 1)
    path, base = str(spec.rules_path()), str(spec.rules_base_path())
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
                f.write(header + default + "\n")
    except Exception:  # noqa: BLE001
        file_log(f"{spec.name} 규칙 파일 처리 실패\n" + traceback.format_exc())
    return parse_rules(default)


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
    kind: str = kinds.SCHOLARSHIP          # 장학금 · 혁신인재지원금 — 비목 · 규칙 파일이 갈린다(Spec)
    req_cnt: str = ""                       # 이 폴더를 넣은 ERP 청구서의 결의번호(#REQ_CNT) — 첫 [저장] 뒤에 생긴다

    @property
    def spec(self) -> Spec:
        return spec_for(self.kind)

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
            out.append(f"개별 적요가 같은 줄이 둘 이상입니다: {text} — {self.spec.rules_file} 로 구분되게 고치세요")
        return out

    def summary_lines(self) -> list[str]:
        chosen = self.chosen()
        total = sum(self.people[i].amount or 0 for i in chosen)
        return [f"종류: {self.spec.name} (비목 {self.spec.category})",
                f"폴더: {self.folder}", f"명단: {os.path.basename(self.roster.path)} — {self.roster.title or '제목 없음'}",
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


def load_job(folder: str, excel: str | None = None, rules: dict[str, str] | None = None,
             kind: str = kinds.SCHOLARSHIP) -> Job:
    """폴더를 읽어 Job 을 만든다. 엑셀이 둘 이상이면 excel 로 고른다(없으면 warnings 에 알리고 첫째).
    kind 는 장학금 · 혁신인재지원금 — 규칙 파일과 비목이 갈린다."""
    rules = rules or load_rules(spec_for(kind))
    folder = str(folder)
    try:
        entries = sorted(os.listdir(folder))
    except OSError:
        entries = []
    candidates = [os.path.join(folder, n) for n in entries
                  if n.lower().endswith(EXCEL_SUFFIXES) and not n.startswith(("~$", "."))]
    chosen = excel if excel and os.path.isfile(excel) else (candidates[0] if candidates else "")
    roster = roster_mod.read(chosen) if chosen else roster_mod.Roster(path="", warnings=["폴더 바로 아래에 명단 엑셀(.xlsx)이 없습니다"])
    job = Job(folder=folder, roster=roster, excel_candidates=candidates, rules=rules, kind=spec_for(kind).kind)
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
    # 저장은 했지만 [신청] 전에 사람이 ERP 에서 봐야 할 것 — 담당자 결정(2026-10-14): 소득구분이 앱으로 안 바뀌면
    # 멈추지 말고 그대로 임시저장한 뒤 신청 전 확인 목록으로 알린다
    review: list[str] = field(default_factory=list)


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

    def review_items(self) -> list[str]:
        """[신청] 전에 ERP 에서 확인할 것 — 결과 창 · 진행 기록 · 로그에 그대로 보인다."""
        return [f"{r.index + 1}. {r.name} — {item}" for r in self.results for item in r.review]

    def lines(self) -> list[str]:
        out = ["미리 보기 (ERP 에 넣지 않음)" if self.dry_run else f"ERP 임시저장 {self.saved}명" + (" — 멈춤" if self.stopped else "")]
        if self.blocked:
            out.append("✗ " + self.blocked)
        review = self.review_items()
        if review:
            out.append(f"신청 전 확인할 것 {len(review)}건:")
            out.extend("  ! " + item for item in review)
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


# 계좌처럼 생긴 숫자 — 하이픈으로 묶인 것(110-594-395796) 또는 10~14자리 한 덩어리(30120104410673)
_ACCOUNT_RE = re.compile(r"(?<![\d-])\d{2,6}(?:-\d{2,8}){1,4}(?![\d-])|(?<!\d)\d{10,14}(?!\d)")


def accounts_in_files(paths: list[str], pages: int = 8) -> tuple[set[str], int]:
    """개별증빙 PDF 글자에서 계좌처럼 생긴 숫자를 모은다(숫자만). (찾은 것, 글자를 읽을 수 있었던 PDF 수).

    학생이 낸 '근로장학금 지출자료' 에 계좌가 적혀 있다. 그림으로만 된 PDF(스캔)는 글자가 없어 못 읽는다 — 그때는 읽은 수가 0.
    전화번호 · 주민번호도 섞여 들어오지만 특정 계좌가 '들어 있는지' 만 보므로 상관없다."""
    found: set[str] = set()
    read = 0
    try:
        import pypdf
    except Exception:  # noqa: BLE001
        return found, 0
    for path in paths:
        if not str(path).lower().endswith(".pdf"):
            continue
        try:
            reader = pypdf.PdfReader(str(path))
            text = "\n".join((page.extract_text() or "") for page in reader.pages[:pages])
        except Exception:  # noqa: BLE001 — 깨진 PDF 는 건너뛴다
            continue
        if text.strip():
            read += 1
        for hit in _ACCOUNT_RE.finditer(text):
            digits = re.sub(r"\D", "", hit.group())
            if 10 <= len(digits) <= 16:
                found.add(digits)
    return found, read


_HANGUL_RE = re.compile(r"[가-힣]")
_LATIN_RE = re.compile(r"[A-Za-z]")


def latin_name(text: str) -> str:
    """영문 이름이면 그 글자, 아니면 ''. 외국인 학생은 은행 예금주가 'SUNATULLAEV GO' 처럼 영문이다(실제 시험 2026-10-14 18:25)."""
    t = str(text or "").strip()
    return t if _LATIN_RE.search(t) and not _HANGUL_RE.search(t) else ""


def foreign_reason(vw_ssn: str, owners: list[str], nation: str = "") -> str:
    """외국인 학생으로 볼 까닭(글) — 아니면 ''. 주민번호 칸의 뒷자리 첫 숫자 → 명단의 국적 열(담당자가 적은 것) →
    (숫자가 안 보일 때만) 영문 예금주 순으로 본다. nation 은 명단 국적 중 외국인 것만(Person.foreign_nation)."""
    m = re.search(r"-\s*(\d)", str(vw_ssn or ""))
    if m and m.group(1) in FOREIGN_SSN_DIGITS:
        return "외국인등록번호"
    if nation:
        return f"명단 국적 {nation}"
    if m:
        return ""
    latin = next((latin_name(o.split(":", 1)[-1]) for o in owners if latin_name(o.split(":", 1)[-1])), "")
    return f"예금주가 영문 이름({latin})" if latin else ""


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
    if p.foreign_nation:
        result.lines.append(f"국적 {p.nation}(명단) — 넣을 때 앱이 ERP 국적조회에서 고릅니다(못 고르면 노란 띠로 묻습니다)")
    notes = [p.note] if p.note else []
    if p.foreign_nation:
        notes.append(f"외국인({p.nation}) — 국적은 앱이 고름")
    if notes:
        result.note = " · ".join(notes)
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
    log("%s 청구 %s — %d명" % (job.spec.name, "미리 보기" if dry_run else "시작", len(chosen)))
    for line in job.summary_lines():
        log("  " + line)
    if dry_run:
        report.results = [plan_person(job, i) for i in chosen]
        return report
    notify = on_person or (lambda _i, _s, _d: None)
    # 폴더마다 청구서 하나 — 작성 화면이 다른 폴더의 청구서(이미 저장된 줄이 있는)면 섞이지 않게 새 청구서를 띄우게 한다
    ok, frame, why = _ensure_own_sheet(page, frame, job, ask, wait, log)
    if not ok:
        report.blocked = why
        report.stopped = True
        log("%s 청구 멈춤 — %s" % (job.spec.name, why))
        return report
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
            log("%s 청구 오류(%s)\n%s" % (job.spec.name, p.name, traceback.format_exc()))
            ok, note = False, "오류: " + (str(error).splitlines()[0][:100] if str(error) else type(error).__name__)
        report.messages.extend(live)
        live.clear()
        result.note = note
        result.status = "saved" if ok else "stopped"
        report.results.append(result)
        notify(index, "review" if ok and result.review else result.status, note)     # 저장했지만 신청 전 확인할 것이 있다
        if not ok:
            report.stopped = True
            log("%s 청구 멈춤 — %d. %s: %s" % (job.spec.name, index + 1, p.name, note))
            break
    log("%s 청구 끝 — 임시저장 %d명%s" % (job.spec.name, report.saved, " (멈춤)" if report.stopped else ""))
    for item in report.review_items():
        log("  신청 전 확인: " + item)
    return report


# 청구내역 표의 저장된 줄(행마다 CUR_REQ 라디오, 실측 ⑤)의 글자 — 읽기만. 적요가 그 줄에 들어 있다.
SHEET_ROWS_JS = """() => Array.from(document.querySelectorAll('input[name=CUR_REQ]')).map(r => {
  const tr = r.closest('tr'); return tr ? (tr.innerText || tr.textContent || '').replace(/\\s+/g, ' ').trim() : ''; })"""


def sheet_owner(job: Job, req_cnt: str, rows: list[str]) -> tuple[bool, str]:
    """작성 화면의 청구서가 이 폴더 것인지(또는 새 청구서인지). (이어도 되는지, 근거)."""
    req_cnt = (req_cnt or "").strip()
    if not req_cnt and not rows:
        return True, "새 청구서"
    from . import record
    known = job.req_cnt or str((record.previous(job.folder) or {}).get("req_cnt") or "")
    if req_cnt and known and req_cnt == known:
        return True, f"이 폴더의 청구서(결의번호 {req_cnt})에 이어서"
    main = re.sub(r"\s+", "", job.main_summary or "")
    if rows and main and all(main in re.sub(r"\s+", "", t) for t in rows):
        return True, f"이 폴더의 청구서(청구내역 {len(rows)}줄의 적요가 대표적요와 같음)에 이어서"
    return False, f"작성 화면이 이미 저장된 다른 청구서입니다(결의번호 {req_cnt or '?'} · 청구내역 {len(rows)}줄)"


def _read_sheet(frame) -> tuple[str, list[str]]:
    try:
        rows = [str(t) for t in (frame.evaluate(SHEET_ROWS_JS) or [])]
    except Exception:  # noqa: BLE001 — 읽지 못하면 줄 없음으로
        rows = []
    return _state(frame, ["REQ_CNT"])["REQ_CNT"], rows


def _ensure_own_sheet(page, frame, job: Job, ask: Ask, wait, log) -> tuple[bool, object, str]:
    """넣기 전에 — 작성 화면이 새 청구서이거나 이 폴더의 청구서인지. 아니면 새 청구서를 띄우게 묻고, 띄운 화면을 다시 찾는다."""
    if not wait_until(lambda: frame.evaluate(PROBE_JS) is True, wait, tries=20):
        return True, frame, ""                                    # 화면을 못 읽으면 사람 단계(_run_person)가 알린다
    ok, why = sheet_owner(job, *_read_sheet(frame))
    asks = 0
    while not ok and asks < MAX_ASKS:
        asks += 1
        log("%s — %s" % (job.spec.name, why))
        if not ask(f"{job.spec.name} '{job.main_summary}' — {why}. 이 폴더의 사람이 다른 청구서에 섞이지 않게, ERP 에서 새 청구서"
                   "(작성 화면의 [새 청구서] 또는 결의서내역 → [일반청구])를 띄운 뒤 [계속]."):
            return False, frame, why + " — 멈춤"
        wait(0.5)
        try:
            from .form import find_form
            _page, found = find_form(page.context)
            frame = found or frame
        except Exception:  # noqa: BLE001 — 가짜 창(테스트) · 닫힌 창이면 그대로
            pass
        ok, why = sheet_owner(job, *_read_sheet(frame))
    if not ok:
        return False, frame, why + " — 새 청구서를 띄운 뒤 다시 누르세요"
    log("%s — %s" % (job.spec.name, why))
    return True, frame, why


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
    category = job.spec.category
    r = _set(frame, "select", "PAY_EXP_CD", category)
    if not r.get("ok"):
        return False, f"비목을 '{category}' 으로 고르지 못함: " + str(r.get("why", ""))
    wait(0.6)                                                   # 비목을 고르면 잔액·인건비구분이 다시 그려진다
    r = _set(frame, "select", "INCM_DIV_CD", INCOME_KIND)
    if not r.get("ok"):
        return False, "소득구분을 '장학금' 으로 고르지 못함: " + str(r.get("why", ""))
    result.lines.append(f"✓ 비목 {category} · 소득구분 {INCOME_KIND}")

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

    _ensure_income(frame, wait, log, result, "소득자를 고른 뒤")      # 안 바뀌어도 여기서는 넘어간다 — 저장 직전에 다시 본다

    # 3-1. 외국인 학생이면 국적 — 국적 팝업은 미실측이라 사람이 신분증을 보고 고른다(담당자 2026-10-14)
    s = _state(frame, ["VW_SSN", "OWNR", "OWNR_INQ_RSLT"])
    foreign = foreign_reason(s["VW_SSN"], [s["OWNR"], s["OWNR_INQ_RSLT"]], p.foreign_nation)
    if foreign:
        log("외국인 학생으로 봄: %d. %s (%s)" % (index + 1, p.name, foreign))
        ok, why = _ensure_nation(page, frame, ask, wait, index, p, foreign, "소득자를 고른 뒤", result, log, messages, auto_pick)
        if not ok:
            return False, why
        result.lines.append("✓ 국적 " + why)

    # 4. 계좌 대조 · 예금주조회 결과 — 소득자를 고르면 ERP 가 인적정보에 등록된 은행 · 계좌를 채운다. 늦게 채워질 수 있어 잠깐 기다린다.
    #    ERP 계좌가 비었거나 명단과 다르면 지급내역(명단) · 개별증빙의 계좌를 넣는다(담당자 2026-10-14 — 실제 시험 19:47 에서
    #    인적정보에 계좌가 없는 학생이 있었고, 앱이 빈 계좌로 [예금주조회] 를 눌러 '은행/계좌번호는 필수' 알림으로 멈췄다).
    #    은행이 '해당없음' 이어도 예금주조회가 같은 알림을 내므로 은행도 본다. 담당자는 "계좌 정상" 이라 했다 — ERP 가 늦게 채웠을 수도 있어
    #    기다리는 시간(~3초)을 두고, 그래도 비었으면 명단 값을 넣는다. 무엇을 보고 정했는지 로그에 남긴다.
    #    ERP 가 이미 '성공:학생이름' 을 채웠으면 은행 · 계좌가 확인된 것이니 은행 칸 글자는 따지지 않는다.
    def account_shown() -> bool:
        now = _state(frame, ["ACCT_NO", "OWNR_INQ_RSLT"])
        return bool(_digits(now["ACCT_NO"])) and bool(_bank_shown(frame) or _owner_result_ok(now["OWNR_INQ_RSLT"], p.name)[0])

    wait_until(account_shown, wait, tries=12)
    s = _state(frame, ["ACCT_NO", "BNK_CD", "OWNR", "OWNR_INQ_RSLT"])
    s["BANK"] = _bank_shown(frame)
    s["BANK_OK"] = bool(s["BANK"]) or _owner_result_ok(s["OWNR_INQ_RSLT"], p.name)[0]
    log("소득자를 고른 뒤 ERP 계좌: 은행 %s · 계좌 %s · 예금주 %s · 예금주조회 %s" % (
        s["BANK"] or "(비어 있음)", s["ACCT_NO"] or "(비어 있음)", s["OWNR"] or "(비어 있음)", s["OWNR_INQ_RSLT"] or "(비어 있음)"))
    changed_account = False
    if not _digits(s["ACCT_NO"]) or not s["BANK_OK"] or (p.account_digits and p.account_digits != _digits(s["ACCT_NO"])):
        ok, why, changed_account = _use_document_account(frame, job, index, s, log, ask, wait, result)
        if not ok:
            return False, why
    else:
        result.lines.append("✓ 계좌 %s (명단과 %s)" % (s["ACCT_NO"] or "—", "같음" if p.account_digits else "대조 안 함"))

    def owner_ok() -> tuple[bool, str]:
        return _owner_result_ok(_state(frame, ["OWNR_INQ_RSLT"])["OWNR_INQ_RSLT"], p.name)

    # 예금주조회 — 소득자를 고르면 ERP 가 대개 '성공:이름' 을 채워 둔다. 아니거나 계좌를 바꿨으면 앱이 [예금주조회] 를 누르고,
    # 새 결과가 '성공:학생이름' 이 아니면 사람에게 맡긴다(담당자 결정 2026-10-14).
    ok, why = (False, "계좌를 바꿈") if changed_account else owner_ok()
    if ok:
        result.lines.append("✓ 예금주조회 " + why)
    else:
        ok, detail = _press_owner_check(frame, p, log, wait, messages, why)
        if ok:
            result.lines.append("✓ 예금주조회(앱이 누름) " + detail)
        else:
            def owner_message(w: str) -> str:
                return ("%d. %s — 앱이 [예금주조회] 를 눌렀지만 '성공' 이 나오지 않았습니다(%s). ERP 에서 계좌를 확인하고 [예금주조회] 로 "
                        "'성공' 이 나오면 [계속], 아니면 [멈추기]." % (index + 1, p.name, w))
            # 한 번은 꼭 묻는다 — 남은 '성공' 글이 바꾸기 전 계좌의 것일 수 있어 결과 칸만 보고 넘어가지 않는다
            if not ask(owner_message(detail)):
                return False, "예금주조회 '성공' 을 확인하지 못함 — 멈춤"
            ok, why = _ask_until(owner_ok, ask, owner_message, wait)
            if not ok:
                return False, "예금주조회 '성공' 을 확인하지 못함 — 멈춤"
            result.lines.append("✓ 예금주조회(사람이 확인) " + why)

    _fill_owner_name(frame, p, log, result)
    owner = latin_name(_state(frame, ["OWNR_INQ_RSLT"])["OWNR_INQ_RSLT"].split(":", 1)[-1])
    if owner:
        item = f"예금주가 영문 이름({owner})이라 {p.name} 과(와) 같은 사람인지 앱이 맞춰 보지 못함 — 신분증·통장과 같은지 확인한 뒤 [신청]"
        result.review.append(item)
        log("신청 전 확인: %d. %s — %s" % (index + 1, p.name, item))

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

    # 7. 저장 전 검사 — 소득구분은 첨부 뒤에도 한 번 더 보고 고친다(위 _ensure_income). 그래도 안 바뀌면 멈추지 않고
    #    그대로 임시저장한 뒤 '신청 전 확인할 것' 으로 남긴다(담당자 결정 2026-10-14) — [신청] 은 어차피 사람이 검토하고 누른다.
    income_ok, income_why = _ensure_income(frame, wait, log, result, "저장 직전")
    if not income_ok:
        item = f"{income_why} — 앱이 '장학금' 으로 바꾸지 못한 채 임시저장함. ERP 에서 이 줄의 소득구분을 '장학금' 으로 고친 뒤 [신청]"
        result.review.append(item)
        log("신청 전 확인: %d. %s — %s" % (index + 1, p.name, item))
    if foreign:
        ok, why = _ensure_nation(page, frame, ask, wait, index, p, foreign, "저장 직전", result, log, messages, auto_pick)
        if not ok:
            return False, why
    s = read_state(frame, ["PAY_EXP_CD", "INCM_DIV_CD", "REQ_AMT", "REQ_PTCL", "RCV_NM"])
    pay = (s.get("PAY_EXP_CD") or {}).get("text", "")
    income = (s.get("INCM_DIV_CD") or {}).get("text", "")
    amount = (s.get("REQ_AMT") or {}).get("value", "")
    checks = {
        f"비목(지금: {pay or '비어 있음'})": _same(pay, category),
        f"소득구분(지금: {income or '비어 있음'})": _same(income, INCOME_KIND) or not income_ok,   # 못 바꾼 것은 위에서 확인 목록으로
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
    if not job.req_cnt:
        job.req_cnt = _state(frame, ["REQ_CNT"])["REQ_CNT"].strip()       # 다음 폴더가 이 청구서에 섞이지 않게(_ensure_own_sheet)
    rows_before, rows_after = int(before.get("rows") or 0), int(after.get("rows") or 0)
    if not saved.ok and rows_after <= rows_before:
        return False, saved.note or "저장이 확인되지 않음"
    if rows_after <= rows_before:
        log("청구내역 줄 수가 늘지 않음 (%d → %d) — ERP 에서 확인 필요" % (rows_before, rows_after))
        if not ask("%d. %s — [저장] 을 눌렀지만 청구내역 표에 줄이 늘지 않았습니다(%d → %d). ERP 에서 저장됐는지 확인한 뒤 [계속], 아니면 [멈추기]."
                   % (index + 1, p.name, rows_before, rows_after)):
            return False, "저장 뒤 청구내역이 늘지 않음 — 멈춤"
    totals = list(after.get("totals") or [])
    before_totals = list(before.get("totals") or [])
    # 합계 줄의 공제합계는 청구서 전체 값이다 — 이 사람을 넣고 **늘어난 만큼**이 이 줄의 공제다. 장학금이면 0 이어야 한다.
    # 소득구분 문제와 같은 뿌리라 멈추지 않고 신청 전 확인 목록으로 남긴다(담당자 결정 2026-10-14).
    added = (totals[2] - (before_totals[2] if len(before_totals) >= 3 else 0)) if len(totals) >= 3 else 0
    if added:
        item = f"공제 {added:,}원이 잡힘(장학금이면 0) — ERP 에서 이 줄의 소득구분을 확인한 뒤 [신청]"
        result.review.append(item)
        log("신청 전 확인: %d. %s — %s" % (index + 1, p.name, item))
    result.lines.append("✓ 청구내역 %d줄" % rows_after + (f" · 공제합계 {totals[2]:,}" if len(totals) >= 3 else ""))
    if result.review:
        result.lines.extend("! " + item for item in result.review)
        return True, "임시저장 — 신청 전 확인: " + " / ".join(result.review)
    return True, "임시저장"


def _use_document_account(frame, job: Job, index: int, s: dict, log, ask: Ask, wait,
                          result: PersonResult) -> tuple[bool, str, bool]:
    """ERP 가 채운 계좌(인적정보에 등록된 것)가 비었거나 명단 계좌와 다를 때 — 지급내역(명단) · 개별증빙의 계좌를 넣는다
    (담당자 결정 2026-10-14: "계좌정보가 불일치하거나 없을 경우 지급내역이나 개별증빙에 있는 정보 참고해서 입력").

    - 그 학생의 개별증빙 PDF 에서 계좌를 찾는다. 명단 계좌가 있으면(또는 PDF 를 못 읽으면) 명단의 은행 · 계좌를 ERP 칸에 넣는다.
      명단은 담당자가 첨부서류를 보고 옮긴 것이다. 명단 계좌를 첨부서류에서 확인하지 못했으면 '신청 전 확인할 것' 에 남긴다
      — ERP 계좌가 비어 있던 경우는 PDF 를 읽었는데도 명단 계좌가 없을 때만(스캔 PDF 라 못 읽은 것까지 매번 묻지 않는다).
    - ERP 계좌가 있고, PDF 에 ERP 계좌만 있고 명단 계좌가 없으면 첨부서류는 ERP 와 같은 것 — 명단이 틀렸다. 바꾸지 않는다.
    - 명단에 은행이나 계좌가 없으면 사람에게 — 개별증빙에서 계좌 같은 숫자를 찾았으면 띠에 함께 보인다.
    - 계좌를 넣으면 [예금주조회] 를 새로 해야 한다 — 돌려주는 셋째 값(넣었는지)을 보고 부르는 쪽이 누른다(_press_owner_check).
    돌려주는 것: (계속해도 되는지, 멈춘 이유, 계좌를 넣었는지)."""
    p = job.people[index]
    erp_acct, erp_digits = s["ACCT_NO"], _digits(s["ACCT_NO"])
    empty = not erp_digits
    no_bank = bool(erp_digits) and not s.get("BANK_OK", True) and (not p.account_digits or p.account_digits == erp_digits)
    found, read = accounts_in_files(job.person_files.get(index, []))
    log("%s: 명단 %s %s / ERP %s %s — 개별증빙 PDF %d개에서 %s" % (
        "ERP 계좌 없음" if empty else "ERP 은행 없음" if no_bank else "계좌 불일치", p.bank or "", p.account or "(없음)",
        s.get("BANK") or "(은행 없음)", erp_acct or "(비어 있음)", read,
        "명단과 같은 계좌를 찾음" if p.account_digits and p.account_digits in found else
        "ERP 와 같은 계좌만 찾음" if erp_digits and erp_digits in found else
        "계좌 같은 숫자 %d개를 찾음" % len(found) if found else "계좌를 찾지 못함"))
    if erp_digits and erp_digits in found and p.account_digits not in found:
        result.lines.append(f"! 명단 계좌({p.account})가 첨부서류와 다름 — 첨부서류 · ERP 계좌({erp_acct}) 그대로 둠(명단 엑셀을 확인하세요)")
        return True, "", False
    erp_label = ("ERP 에 이 학생의 계좌가 없는데" if empty else "ERP 에 이 학생의 은행이 없는데" if no_bank else
                 f"ERP 계좌({erp_acct})가 명단 계좌({p.account})와 다른데")
    if not (p.bank and p.account_digits):
        hint = (" 개별증빙에서 찾은 계좌 같은 숫자: " + ", ".join(sorted(found)[:4]) + ".") if found else ""
        ok = ask("%d. %s — %s 명단에 %s 없어 넣지 못했습니다.%s 개별증빙을 보고 ERP 에 은행 · 계좌를 넣고 [예금주조회] 로 '성공' 을 "
                 "확인한 뒤 [계속], 아니면 [멈추기]." % (index + 1, p.name, erp_label, "계좌가" if not p.account_digits else "은행이", hint))
        return (True, "", False) if ok else (False, "계좌를 넣지 못함 — 멈춤", False)
    from_document = p.account_digits in found
    r_bank = _set(frame, "select", "BNK_CD", p.bank)
    r_acct = _set(frame, "text", "ACCT_NO", p.account_digits)
    wait(0.5)
    now = _state(frame, ["ACCT_NO"])["ACCT_NO"]
    if not (r_bank.get("ok") and r_acct.get("ok")) or _digits(now) != p.account_digits:
        why = r_bank.get("why") or r_acct.get("why") or f"넣은 뒤 계좌 칸이 {now or '비어 있음'}"
        ok = ask("%d. %s — %s 명단의 %s %s 를 넣지 못했습니다(%s). ERP 에서 직접 넣고 [예금주조회] 로 '성공' 을 확인한 뒤 [계속], 아니면 [멈추기]."
                 % (index + 1, p.name, erp_label, p.bank, p.account, why))
        return (True, "", False) if ok else (False, "계좌를 넣지 못함 — 멈춤", False)
    note = ("첨부서류" if from_document else "명단 엑셀" if empty and not read or no_bank else
            "명단 엑셀(첨부서류에서 계좌를 읽지 못함)")
    before = "ERP 계좌 칸이 비어 있었음" if empty else "ERP 은행 칸이 비어 있었음" if no_bank else f"ERP 에 있던 계좌 {erp_acct}"
    result.lines.append(f"✓ 계좌를 {note}의 {r_bank.get('now') or p.bank} {p.account} 로 넣음 ({before})")
    log("계좌를 %s의 %s %s 로 넣음 (%s)" % (note, p.bank, p.account, before))
    if not from_document and not no_bank and (not empty or read):
        result.review.append(f"첨부서류에서 계좌를 읽지 못해 명단 엑셀의 계좌({p.bank} {p.account})로 넣음 — 첨부서류와 같은지 확인한 뒤 [신청]")
    return True, "", True          # 넣은 계좌는 예금주조회가 새로 필요하다 — 부르는 쪽이 [예금주조회] 를 누른다


def _bank_shown(frame) -> str:
    """작성 화면 은행 칸(#BNK_CD)에 고른 은행 이름 — '선택' · '해당없음' 이거나 비었으면 ''."""
    info = read_state(frame, ["BNK_CD"]).get("BNK_CD") or {}
    text = str(info.get("text", info.get("value", "")) or "").strip()
    return "" if not str(info.get("value", "")).strip() or text in ("", "선택", "해당없음") else text


def _fill_owner_name(frame, p, log, result: PersonResult) -> None:
    """예금주 칸(#OWNR, 필수)이 비어 있으면 예금주조회가 돌려준 이름을 넣는다. 인적정보에 계좌가 없던 학생은 앱이 계좌를 넣었으니
    예금주 칸도 비어 있을 수 있다 — 예금주조회가 그 칸을 채우는지는 미실측이라 비었을 때만, 은행이 확인해 준 이름으로 넣는다."""
    s = _state(frame, ["OWNR", "OWNR_INQ_RSLT"])
    if s["OWNR"].strip():
        return
    result_text = s["OWNR_INQ_RSLT"].strip()
    holder = result_text.split(":", 1)[1].strip() if result_text.startswith("성공") and ":" in result_text else ""
    name = holder or p.name
    r = _set(frame, "text", "OWNR", name)
    if r.get("ok"):
        result.lines.append(f"✓ 예금주 칸이 비어 있어 {name} 을(를) 넣음")
        log("예금주 칸이 비어 있어 '%s' 을(를) 넣음 (예금주조회 %s)" % (name, result_text or "결과 없음"))
    else:
        log("예금주 칸이 비어 있는데 넣지 못함: %s" % r.get("why", ""))


def _ensure_nation(page, frame, ask: Ask, wait, index: int, p, foreign: str, when: str, result: PersonResult,
                   log, messages: list[str], auto_pick: bool) -> tuple[bool, str]:
    """외국인 학생의 국적(#NATION_CD)이 KR 이 아니게 한다. (됐는지, '국가이름(코드)' 또는 멈춘 이유).

    명단에 국적이 있으면 앱이 국적 팝업에서 그 나라를 골라 본다(nation.pick — 하나로 확실할 때만). 못 고르면, 또는 명단에 국적이
    없으면 노란 띠로 사람에게 묻는다. 사람이 고른 국적이 명단과 다르면 멈추지 않고 '신청 전 확인할 것' 으로 남긴다."""
    def nation_ok() -> tuple[bool, str]:
        s = _state(frame, ["NATION_CD", "NATION_NM"])
        code = s["NATION_CD"].strip().upper()
        if code and code != HOME_NATION:
            return True, f"{s['NATION_NM'] or '?'}({code})"
        return False, f"국적이 '{s['NATION_NM'] or code or '비어 있음'}' 입니다"

    tried = ""
    if not nation_ok()[0] and p.foreign_nation and auto_pick:
        try:
            found = nation_mod.pick(page, frame, p.foreign_nation, log, wait=wait, messages=messages)
            result.lines.extend(found.lines())
            tried = "" if found.picked else f"앱이 고르지 못함: {found.note}. "
        except Exception as error:  # noqa: BLE001 — 팝업이 안 뜨거나 닫혀도 사람에게 넘기면 된다
            tried = "앱이 고르지 못함: " + (str(error).splitlines()[0][:80] if str(error) else type(error).__name__) + ". "
            log("국적 자동 선택 실패: " + tried)
    if p.foreign_nation:
        hint = f"명단 국적: {p.nation}. {tried}"
    else:
        hint = "개별증빙의 신분증(외국인등록증)을 보고 — 명단 엑셀의 '국적' 열에 적어 두면 앱이 고릅니다 — "

    def message(w: str) -> str:
        return ("%d. %s — 외국인 학생입니다(%s, %s). %sERP 의 국적 돋보기로 국적을 고른 뒤 [계속]. (%s)"
                % (index + 1, p.name, foreign, when, hint, w))
    ok, why = _ask_until(nation_ok, ask, message, wait)
    if not ok:
        return False, "외국인 학생의 국적을 고르지 못함 — " + why
    now = _state(frame, ["NATION_CD", "NATION_NM"])
    chosen = now["NATION_NM"]
    if p.foreign_nation and not nation_mod.same_nation(p.foreign_nation, now["NATION_CD"], chosen):
        item = f"ERP 국적 '{chosen or why}' 가 명단 국적 '{p.nation}' 과 다름 — 같은 나라인지 확인한 뒤 [신청]"
        if item not in result.review:
            result.review.append(item)
    return True, why


def _owner_result_ok(value: str, name: str) -> tuple[bool, str]:
    """예금주조회 결과 칸이 '성공:학생이름' 인지. 이름이 다르면(다른 사람 계좌) 통과시키지 않는다."""
    v = (value or "").strip()
    if not v.startswith("성공"):
        return False, f"결과 '{v or '비어 있음'}'"
    who = v.split(":", 1)[1].strip() if ":" in v else ""
    if who and latin_name(who):
        return True, v          # 외국인 학생의 영문 예금주 — 한글 이름과 맞춰 볼 수 없다. 부르는 쪽이 '신청 전 확인' 으로 남긴다
    if who and re.sub(r"\s+", "", who) != re.sub(r"\s+", "", name):
        return False, f"결과의 예금주 '{who}' 가 {name} 이(가) 아님"
    return True, v


def _press_owner_check(frame, p, log, wait, messages: list[str], why: str) -> tuple[bool, str]:
    """[예금주조회] 를 앱이 누르고 **새** 결과를 본다(담당자 결정 2026-10-14). '성공:학생이름' 이면 (True, 결과), 아니면 (False, 이유).

    결과 칸이 그대로이고 ERP 알림도 없으면 조회가 됐는지 알 수 없다 — 남은 '성공' 이 바꾸기 전 계좌의 것일 수 있어 통과시키지 않는다."""
    try:
        visible = frame.evaluate(VISIBLE_ID_JS, OWNER_CHECK_ID)
    except Exception:  # noqa: BLE001
        visible = False
    if not visible:
        return False, "화면에 [예금주조회] 단추가 보이지 않음"
    ids = ["OWNR_INQ_RSLT", "OWNR_INQ_RSLT_CD"]
    before, seen = _state(frame, ids), len(messages)
    clicked = frame.evaluate(CLICK_ID_JS, OWNER_CHECK_ID)
    if not clicked.get("ok"):
        return False, "[예금주조회] 를 누르지 못함: " + str(clicked.get("why", ""))
    shown = _state(frame, ["ACCT_NO"])["ACCT_NO"]
    log("[예금주조회] 누름 (%s · 은행 %s · 계좌 %s)" % (why, _bank_shown(frame) or "비어 있음", shown or "비어 있음"))
    now = before
    for _ in range(30):                         # ~7.5초 — 펌뱅킹 조회라 몇 초 걸릴 수 있다
        wait(0.25)
        now = _state(frame, ids)
        if (now != before or len(messages) > seen) and now["OWNR_INQ_RSLT"]:
            break
    alerts = messages[seen:]
    log("예금주조회 결과: %s%s" % (now["OWNR_INQ_RSLT"] or "비어 있음", (" · 알림: " + " / ".join(alerts)) if alerts else ""))
    if now == before and not alerts:
        return False, f"눌렀지만 결과가 바뀌지 않음(지금 '{now['OWNR_INQ_RSLT'] or '비어 있음'}')"
    return _owner_result_ok(now["OWNR_INQ_RSLT"], p.name)


def _summary(frame) -> dict:
    try:
        return frame.evaluate(SUMMARY_JS) or {}
    except Exception:  # noqa: BLE001 — 저장 뒤 다시 열리는 중
        return {}


def record_job(job: Job, report: ScholarshipReport) -> None:
    """채운 기록(_청구입력기록.json) — 같은 폴더를 다시 넣으려 하면 묻는 근거."""
    from . import record
    record.remember(job.folder, {"amount": sum(job.people[r.index].amount or 0 for r in report.results if r.status == "saved"),
                                 "summary": job.main_summary + f" ({report.saved}명)", "req_cnt": job.req_cnt})

