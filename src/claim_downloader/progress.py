"""다운로드 현황 — 증빙 다운로드가 읽은 결의서내역 · 구매요구내역의 건마다 받았는지를 과제별로 쌓아(`_증빙현황.json`) 담당자 구글 시트의
'다운로드 현황' 탭에 한 표로 쓴다. Qt · Playwright 없음.

담당자 2026-10-23: "과제별로 청구서일 때는 결의서 내역을 구매요청 서류일때는 구매요구내역을 … 어디까지 다운이 완료되었고 무슨 건은 어떤서류를
다운받지 못함 … 표로 정리" → "구글시트에다가" → "다운로드 현황 버튼을 생성해서 클릭하면 구글시트가 열려서" → "하나의 시트에 정리" →
"건별로 청구서, 구매요청, 검사처리 항목에 다운로드했으면 O로 못했으면 X로 해당 건이 청구서 다운로드 대상이 아니면 회색으로".

- 건 = 결의서내역의 한 줄(청구서) 또는 구매진행관리의 한 줄(구매요청(계약) 서류). 줄마다 세 칸 — 청구서 · 구매요청 · 검사처리 — 에 표시:
  O 받음 · X 못 받음 · △ 받을 것(아직 안 받음) · 빈칸 = 그 서류의 대상이 아님(시트에서 회색, 까닭은 '못 받은 것 · 까닭' 칸).
  결의서 줄은 청구서 칸만, 구매요구 줄은 구매요청(구매요구서작성의 증빙문서) · 검사처리(검사처리 첨부 + 물품 사진) 칸만 뜻이 있다.
- 쌓는 때(브라우저 스레드, session.py): 결의서 목록을 읽을 때(record_claims — 목록의 모든 줄, 받을 것인지 · 왜 아닌지) · 건을 받을 때마다(record_claim_item) ·
  구매진행관리를 읽을 때(record_purchases) · 구매 건을 받은 뒤(record_purchase_results). ERP 가 기준이다 — 목록을 다시 읽으면 그 과제의 줄은 새 목록으로
  바뀌고, 지난번 X 는 다시 받아 O 가 될 때까지 남는다(다시 읽었다고 못 받은 까닭이 지워지지 않게).
- 시트에 쓰는 때(화면 스레드 뒤, ui/sheet_sync.py): [다운로드 현황] 을 누를 때(쓴 뒤 시트를 연다) · 목록을 읽은 뒤 · 받기가 끝난 뒤(조용히).
  스크립트(parking_sheet.SCRIPT 의 status_put)가 탭을 통째로 다시 쓰고 서식(머리 고정 · 거르기 · 칸 너비 · O/X 색)을 입힌다.
파일에는 대표적요(사람 이름이 들 수 있음)가 있어 저장소 · 배포 · CI 에서 뺀다(.gitignore · NEVER_PACK).
"""
from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import navigate, parking_sheet, project_folders, settings, skiplist
from .minutes.logbook import log

SHEET = "다운로드 현황"
CLAIM, PURCHASE = "claim", "purchase"
MARK_OK, MARK_FAIL, MARK_WAIT, MARK_NONE = "O", "X", "△", ""
HEAD = ["과제", "서류", "No", "번호", "문서번호", "일자", "내용", "금액", "구분 · 진행", "청구서", "구매요청", "검사처리",
        "받은 파일 · 폴더", "못 받은 것 · 까닭", "마지막 확인"]
MARK_COLS = (10, 11, 12)          # 시트의 칸 번호(1부터) — 스크립트가 O/X 색을 입히는 칸
AMOUNT_COL = 8
TEXT_COLS = (3, 4, 5, 6, 15)      # 번호 · 날짜 — 시트가 숫자 · 날짜로 바꾸지 않게 글자 서식
WIDTHS = [150, 90, 45, 110, 170, 90, 360, 100, 150, 60, 70, 70, 260, 320, 110]
INSPECT_PREFIXES = ("검사처리/", "검사처리 줄", "물품")      # CaseResult.failed 가운데 검사처리 쪽 것
LEGEND = "O 받음 · X 못 받음 · △ 받을 것(아직 안 받음) · 회색 = 그 서류의 대상이 아님(까닭은 '못 받은 것 · 까닭' 칸)"
NOT_CONNECTED = ("구글 시트가 연결돼 있지 않아 다운로드 현황을 시트에 쓰지 못합니다. 설정 → '구글 시트 연동' 에서 한 번 연결하면 "
                 "[다운로드 현황] 한 번으로 시트에 쓰고 엽니다.")
OLD_SCRIPT = ("구글 시트의 스크립트가 옛 판이라 '다운로드 현황' 탭을 쓰지 못합니다. 설정 → '구글 시트 연동' 의 [스크립트 복사] 로 새 글을 복사해 "
              "Apps Script 에 붙여 넣고 저장한 뒤, 배포 → 배포 관리 → (연필) 수정 → 버전 '새 버전' → 배포 를 눌러 주세요(주소는 그대로).")
VERSION = 1
_LOCK = threading.Lock()


@dataclass
class Entry:
    project: str
    kind: str                 # CLAIM | PURCHASE
    key: str                  # 결의서: 문서번호(없으면 결의번호) · 구매요구: 구매요구번호
    no: str = ""
    seq: str = ""             # 결의번호 · 구매요구번호
    doc_no: str = ""
    date: str = ""            # 지출예정일 · 요청일자
    cont: str = ""            # 대표적요 · 대표건명
    amt: str = ""
    gubun: str = ""           # 결의서구분 · 진행구분 / 구매구분 · 진행상태
    claim: str = MARK_NONE
    request: str = MARK_NONE
    inspect: str = MARK_NONE
    files: str = ""           # 받은 파일 · 폴더
    detail: str = ""          # 못 받은 것 · 까닭
    seen: str = ""            # 마지막으로 확인한 때

    @property
    def marks(self) -> tuple[str, str, str]:
        return self.claim, self.request, self.inspect

    def row(self, label: str) -> list:
        amount = int(self.amt) if re.fullmatch(r"-?\d+", self.amt or "") else self.amt
        return [label, "청구서" if self.kind == CLAIM else "구매요청(계약)", self.no, self.seq, self.doc_no, self.date, self.cont, amount,
                self.gubun, self.claim, self.request, self.inspect, self.files, self.detail, self.seen]


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M")


# ── 파일 ───────────────────────────────────────────────────────────────────
def _load() -> dict:
    try:
        data = json.loads(settings.progress_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"v": VERSION, CLAIM: {}, PURCHASE: {}}
    if not isinstance(data, dict) or data.get("v") != VERSION:
        return {"v": VERSION, CLAIM: {}, PURCHASE: {}}
    for kind in (CLAIM, PURCHASE):
        if not isinstance(data.get(kind), dict):
            data[kind] = {}
    return data


def _save(data: dict) -> None:
    path = settings.progress_path()
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    temp.replace(path)


def _entry(raw: dict) -> Entry | None:
    try:
        return Entry(**{k: str(raw.get(k, "") or "") for k in Entry.__dataclass_fields__})
    except TypeError:
        return None


def _update(kind: str, project: str, change) -> None:
    """change(그 과제의 {key: Entry}) → 새 {key: Entry}. 파일은 잠그고 통째로 바꿔 쓴다(브라우저 스레드가 쓰고 화면 스레드가 읽는다)."""
    with _LOCK:
        data = _load()
        current = {k: e for k, v in (data[kind].get(project) or {}).items() if (e := _entry(v)) is not None}
        data[kind][project] = {k: asdict(e) for k, e in change(current).items()}
        _save(data)


def forget() -> None:
    settings.progress_path().unlink(missing_ok=True)


# ── 결의서(청구서) ─────────────────────────────────────────────────────────
def claim_key(row: dict) -> str:
    return str(row.get("docNo") or "") or (f"결의 {row.get('seq')}" if row.get("seq") else f"No {row.get('no')}")


def claim_mark(row: dict, done: set[str], unwanted: list[dict] | None = None, project: str = "") -> tuple[str, str]:
    """목록의 한 줄이 받을 것인지 — (표시, 까닭). targets.select_targets · session.read_list 의 거르기와 같은 규칙."""
    gubun = str(row.get("gubun") or "")
    if re.search(r"반납|자금대체", gubun):
        return MARK_NONE, f"결의서구분 '{gubun}' — 반납 · 자금대체는 받지 않음"
    state = str(row.get("state") or "").replace(" ", "")
    if state != "승인":
        return MARK_NONE, f"진행구분 '{state or '없음'}' — 승인된 결의서만 받음"
    if not row.get("docNo"):
        return MARK_NONE, "문서번호 없음 — 받지 않음"
    if not row.get("expDt"):
        return MARK_NONE, "지출예정일 없음 — 받지 않음"
    if row["docNo"] in done:
        return MARK_OK, ""
    unwanted = skiplist.load() if unwanted is None else unwanted
    if unwanted:
        kind = skiplist.kind_of(skiplist.kinds(unwanted), row)
        if kind:
            return MARK_NONE, f"결의서구분 '{kind}' 은 청구서출력이 없어 받지 않음"
        if skiplist.matches(unwanted, row, project):
            return MARK_NONE, "받지 않는 결의서 목록에 있음(청구서출력 없음)"
    return MARK_WAIT, ""


def _files_by_doc(root: Path | None) -> dict[str, str]:
    """보관 스캔 캐시(_보관목록.json: 경로 → 문서번호)를 뒤집어 문서번호 → 과제 폴더 안 상대 경로."""
    try:
        cache = json.loads(settings.archive_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, str] = {}
    for path, doc in (cache.items() if isinstance(cache, dict) else []):
        if not doc or doc in out:
            continue
        text = str(path)
        if root is not None:
            try:
                text = str(Path(text).relative_to(root))
            except ValueError:
                pass
        out[str(doc)] = text.replace("\\", "/")
    return out


def record_claims(project: str, rows: list[dict], done: set[str], unwanted: list[dict] | None = None,
                  root: Path | None = None, blocked: str = "") -> None:
    """결의서 목록을 읽은 뒤 — 그 과제의 줄을 목록 전체로 바꾼다. 지난번 X(못 받음)는 다시 받아 O 가 될 때까지 남긴다.
    blocked 는 과제 폴더가 없거나 예산 탭을 못 읽어 그 과제를 받지 않는 까닭 — 받을 줄이 모두 그 까닭으로 회색이 된다."""
    files = _files_by_doc(root)
    now = _now()

    def change(old: dict[str, Entry]) -> dict[str, Entry]:
        new: dict[str, Entry] = {}
        for row in rows:
            key = claim_key(row)
            mark, why = claim_mark(row, done, unwanted, project)
            if mark == MARK_WAIT and blocked:
                mark, why = MARK_NONE, blocked
            before = old.get(key)
            entry = Entry(project, CLAIM, key, str(row.get("no") or ""), str(row.get("seq") or ""), str(row.get("docNo") or ""),
                          str(row.get("expDt") or ""), str(row.get("cont") or ""), str(row.get("amt") or ""),
                          " · ".join(t for t in (str(row.get("gubun") or ""), str(row.get("state") or "")) if t),
                          claim=mark, detail=why, seen=now)
            if mark == MARK_OK:
                entry.files = files.get(entry.doc_no, "") or (before.files if before else "")
            elif mark == MARK_WAIT and before is not None and before.claim == MARK_FAIL:
                entry.claim, entry.detail = MARK_FAIL, before.detail
            new[key] = entry
        return new

    _update(CLAIM, project, change)


def record_claim_item(row: dict, status: str, detail: str = "") -> None:
    """받기에서 건 하나의 결과 — session.download 의 notify 와 같은 상태 글(done · failed · unwanted). running · retry 는 적지 않는다."""
    if row.get("kind") == PURCHASE or status not in ("done", "failed", "unwanted"):
        return
    project = re.sub(r"\D", "", str(row.get("project") or ""))
    key = claim_key(row)
    now = _now()

    def change(old: dict[str, Entry]) -> dict[str, Entry]:
        entry = old.get(key) or Entry(project, CLAIM, key, str(row.get("no") or ""), str(row.get("seq") or ""), str(row.get("docNo") or ""),
                                      str(row.get("expDt") or ""), str(row.get("cont") or ""), str(row.get("amt") or ""),
                                      " · ".join(t for t in (str(row.get("gubun") or ""), str(row.get("state") or "")) if t))
        entry.seen = now
        if status == "done":
            entry.claim, entry.detail = MARK_OK, ""
            entry.files = detail if detail and detail != "이미 받음" else entry.files
        elif status == "failed":
            entry.claim, entry.detail = MARK_FAIL, detail or "못 받음"
        else:
            entry.claim, entry.detail = MARK_NONE, detail or "청구서출력이 없는 결의서 — 받지 않음"
        old[key] = entry
        return old

    _update(CLAIM, project, change)


# ── 구매요구(구매요청(계약) 서류) ───────────────────────────────────────────
def _purchase_entry(project: str, row: dict) -> Entry:
    """구매진행관리의 줄(purchase.read_rows) → Entry. 번호 · 날짜 꼴은 purchase.as_target 과 같다."""
    from . import purchase
    req_no = str(row.get("req_no") or "")
    state = str(row.get("state") or "")
    kind = str(row.get("kind") or "")
    gubun = " · ".join(t for t in ((f"구매요청({kind})" if kind else "구매요청"), state) if t)
    return Entry(project, PURCHASE, req_no, str(row.get("seq") or ""), req_no, "",
                 purchase.iso(str(row.get("req_dt") or "")) or purchase.req_date(req_no), str(row.get("title") or ""),
                 re.sub(r"[^0-9\-]", "", str(row.get("amount") or "")), gubun, request=MARK_WAIT, inspect=MARK_WAIT)


def record_purchases(project: str, rows: list[dict], done_before: dict | None = None) -> None:
    """구매진행관리를 읽은 뒤 — 그 과제의 구매요구 줄을 읽은 목록으로 바꾼다. 지난 받기에서 끝까지 받은 건(done_before)은 O, 지난번 결과(O · X)가 있으면 그대로."""
    done_before = done_before or {}
    now = _now()

    def change(old: dict[str, Entry]) -> dict[str, Entry]:
        new: dict[str, Entry] = {}
        for row in rows:
            entry = _purchase_entry(project, row)
            if not entry.key:
                continue
            before = old.get(entry.key)
            entry.seen = now
            if before is not None and (before.request != MARK_WAIT or before.inspect != MARK_WAIT):
                entry.request, entry.inspect, entry.files, entry.detail = before.request, before.inspect, before.files, before.detail
            if entry.key in done_before:
                record = done_before[entry.key]
                entry.request = MARK_OK
                if entry.inspect == MARK_WAIT:
                    entry.inspect = MARK_OK
                entry.files = entry.files or f"지난 받기({record.get('at', '')})에서 파일 {record.get('files', '?')}개"
                entry.detail = ""
            new[entry.key] = entry
        return new

    _update(PURCHASE, project, change)


def record_purchase_results(cases: list) -> None:
    """purchase.run 의 건마다 결과(CaseResult) — 구매요청 칸은 증빙문서, 검사처리 칸은 검사처리 첨부 · 물품 사진."""
    now = _now()
    by_project: dict[str, list] = {}
    for case in cases:
        if getattr(case, "req_no", ""):
            by_project.setdefault(re.sub(r"\D", "", str(case.project or "")), []).append(case)
    for project, mine in by_project.items():
        def change(old: dict[str, Entry], mine=mine) -> dict[str, Entry]:
            for case in mine:
                entry = old.get(case.req_no) or Entry(project, PURCHASE, case.req_no, "", case.req_no, "", "", case.title or "", "", "구매요청")
                entry.cont = case.title or entry.cont
                entry.seen = now
                _apply_case(entry, case)
                old[case.req_no] = entry
            return old
        _update(PURCHASE, project, change)


def _apply_case(entry: Entry, case) -> None:
    failed = list(case.failed)
    inspect_failed = [f for f in failed if f.startswith(INSPECT_PREFIXES)]
    request_failed = [f for f in failed if f not in inspect_failed]
    request_saved = [f for f in case.saved if not f.startswith("검사처리/")]
    inspect_saved = [f for f in case.saved if f.startswith("검사처리/")]
    notes: list[str] = []
    if case.note:
        notes.append(case.note)
    if case.note and not case.folder:
        # 상세를 못 띄웠거나 과제 폴더가 없다 — 건 전체를 못 받은 것
        entry.request, entry.inspect = MARK_FAIL, (MARK_NONE if entry.inspect in (MARK_NONE, MARK_WAIT) else entry.inspect)
    else:
        if request_failed:
            entry.request = MARK_FAIL
            notes += request_failed
        elif request_saved or case.existed:
            entry.request = MARK_OK
        elif not inspect_saved and not failed:
            entry.request = MARK_NONE
            notes.append("구매요청 때 올린 첨부 없음")
        else:
            entry.request = MARK_OK
        if not case.inspected:
            entry.inspect = MARK_NONE
            notes.append("검사처리 화면에 이 건이 없음(검사 전이거나 조회 범위 밖)")
        elif inspect_failed:
            entry.inspect = MARK_FAIL
            notes += inspect_failed
        elif inspect_saved or case.photos or getattr(case, "inspect_seen", 0):
            entry.inspect = MARK_OK
        else:
            entry.inspect = MARK_NONE
            notes.append("검사처리 때 올린 첨부 · 물품 사진 없음")
    parts = []
    if case.folder:
        parts.append(Path(case.folder).name)
    if case.saved:
        parts.append(f"새 파일 {len(case.saved)}개")
    if case.existed:
        parts.append(f"이미 있음 {case.existed}개")
    if case.photos:
        parts.append(f"물품 사진 {case.photos}장")
    entry.files = " · ".join(parts)
    entry.detail = " / ".join(notes)[:900]


# ── 표 ────────────────────────────────────────────────────────────────────
def _labels(out_root: str) -> dict[str, str]:
    labels = {f.no: f.short() for f in project_folders.folders(out_root)} if out_root else {}
    for p in navigate.load_projects()[0]:
        labels.setdefault(p.no, p.short())
    return labels


def _no(entry: Entry) -> int:
    return int(entry.no) if entry.no.isdigit() else 10 ** 9


def entries(out_root: str = "") -> list[tuple[str, Entry]]:
    """(과제 글, 줄) — 과제 폴더 차례 → 청구서 먼저 → No 차례."""
    with _LOCK:
        data = _load()
    labels = _labels(out_root)
    order = {no: i for i, no in enumerate(labels)}
    out: list[tuple[str, Entry]] = []
    for kind in (CLAIM, PURCHASE):
        for project, rows in data[kind].items():
            for raw in rows.values():
                entry = _entry(raw)
                if entry is not None:
                    out.append((labels.get(project, project or "(과제 모름)"), entry))
    out.sort(key=lambda pair: (order.get(pair[1].project, len(order)), pair[1].project, pair[1].kind != CLAIM, _no(pair[1]), pair[1].seq))
    return out


def counts(items: list[tuple[str, Entry]]) -> dict[str, dict[str, int]]:
    out = {CLAIM: {MARK_OK: 0, MARK_FAIL: 0, MARK_WAIT: 0, "n": 0}, PURCHASE: {MARK_OK: 0, MARK_FAIL: 0, MARK_WAIT: 0, "n": 0}}
    for _label, e in items:
        bucket = out[e.kind]
        bucket["n"] += 1
        marks = (e.claim,) if e.kind == CLAIM else (e.request, e.inspect)
        if MARK_FAIL in marks:
            bucket[MARK_FAIL] += 1
        elif MARK_WAIT in marks:
            bucket[MARK_WAIT] += 1
        elif MARK_OK in marks:
            bucket[MARK_OK] += 1
    return out


def summary_text(out_root: str = "") -> str:
    items = entries(out_root)
    c = counts(items)
    projects = len({e.project for _l, e in items})

    def part(kind: str, name: str) -> str:
        b = c[kind]
        return f"{name} {b['n']}건(O {b[MARK_OK]} · X {b[MARK_FAIL]} · △ {b[MARK_WAIT]})"
    return f"과제 {projects}개 · " + part(CLAIM, "청구서") + " · " + part(PURCHASE, "구매요청(계약)")


def table(out_root: str = "") -> tuple[list[str], list[list], str]:
    """(머리글, 줄, 설명 한 줄) — 스크립트 status_put 에 그대로 보낸다."""
    items = entries(out_root)
    legend = f"{LEGEND} — 앱이 {_now()} 에 씀 · {summary_text(out_root)}"
    return list(HEAD), [e.row(label) for label, e in items], legend


def push(config: parking_sheet.Config | None = None, out_root: str = "", opener=None) -> parking_sheet.Result:
    """'다운로드 현황' 탭을 통째로 다시 쓴다. 옛 스크립트(status_put 을 모름)면 그 까닭을."""
    config = config or parking_sheet.load_config()
    if not config.connected:
        return parking_sheet.Result(note=NOT_CONNECTED)
    head, rows, legend = table(out_root)
    try:
        data = parking_sheet.call(config, "status_put", opener=opener, head=head, rows=rows, legend=legend, marks=list(MARK_COLS),
                                  amount=AMOUNT_COL, texts=list(TEXT_COLS), widths=WIDTHS)
    except parking_sheet.SheetError as error:
        note = OLD_SCRIPT if "모르는 요청" in str(error) else str(error)
        log(f"다운로드 현황을 구글 시트에 쓰지 못했습니다 — {note.splitlines()[0]}")
        return parking_sheet.Result(note=note, sheet_url=config.sheet_url, sheet_name=config.sheet_name)
    parking_sheet._remember(config, data)
    log(f"다운로드 현황을 구글 시트 '{SHEET}' 탭에 썼습니다 — {len(rows)}줄")
    return parking_sheet.Result(ok=True, note=f"'{SHEET}' 탭에 {len(rows)}줄을 썼습니다", total=len(rows),
                                sheet_url=config.sheet_url, sheet_name=config.sheet_name)
