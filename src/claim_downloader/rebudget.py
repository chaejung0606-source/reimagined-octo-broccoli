"""대응자금 파일 정리 — 이미 받은 대응자금 청구서의 비목 번호 · 폴더를 예산 탭 차례로 고친다. Qt 없음.

담당자 2026-10-21: 대응자금 과제(202409710001 · 2 · 3)를 사업비 비목 번호(01 인건비 … 09)로 다 받은 뒤 "대응자금 과제별로 예산비목명이랑
순서만 확인하고 다운받은 파일명만 수정해줄 수 있나?" — 다시 받지 않고, 과제정보 → 예산 탭의 비목 차례(navigate.read_budget, 8절)로
받은 파일의 앞 번호를 바꾸고 'NN. 비목명' 폴더로 옮긴다. 받기가 새로 붙이는 이름과 같다(naming.budget_code · budget_folder).

- 비목은 PDF 앞 세 쪽(결의서 · 지급명세서)의 글자에서 정한다 — 금액 줄의 비목명, 아니면 그 글에 하나만 나오는 비목. 못 정하면 그대로 둔다.
- 문서번호가 이 과제의 것이 아니거나(앞 12자리) 문서번호가 없는 PDF(청구서가 아닌 자료)는 건드리지 않는다.
- `업로드/` 안의 파일은 옮기지 않는다(2절 — 앱은 업로드 폴더에 쓰지도, 거기서 옮기지도 않는다). 바꿀 이름만 보여 준다.
- 덮어쓰지 않는다 — 같은 이름이 있으면 _2, _3. 바꾸기 전에 표로 보여 주고 담당자가 [바꾸기] 를 눌러야 옮긴다(ui/pages/download.py).
"""
from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import naming
from .archive import DOC_NO_PATTERN
from .project_folders import ProjectFolder, folders

CHANGE, SAME, UNSURE, UPLOADED, OTHER = "바꿈", "맞음", "못 정함", "업로드됨", "건드리지 않음"
PAGES = 3                     # 결의서(1~2쪽) · 지급명세서(3쪽) — 그 뒤는 첨부라 다른 비목 이름이 섞일 수 있다
AMOUNT = re.compile(r"_\(([\d,]+)\)(?:_\d+)?\.pdf$", re.IGNORECASE)


@dataclass
class Move:
    project: str
    source: Path
    target: Path | None = None        # 바꿀 경로(바꿈 · 업로드됨일 때)
    status: str = UNSURE
    why: str = ""
    done: bool = False                # 옮겼는지(apply)
    home: Path | None = None          # 과제 폴더 — 화면에는 이 아래 경로만('02. 장학금/02_(…).pdf')

    def place(self) -> str:
        return _rel(self.source, self.home)

    def to(self) -> str:
        return _rel(self.target, self.home) if self.target is not None else ""


@dataclass
class Plan:
    budgets: dict[str, list] = field(default_factory=dict)          # 과제번호 → [[비목코드, 비목명], …]
    folders: dict[str, Path] = field(default_factory=dict)          # 과제번호 → 과제 폴더
    moves: list[Move] = field(default_factory=list)
    blocked: list[tuple[str, str]] = field(default_factory=list)    # 예산 탭을 못 읽은 과제

    def changes(self) -> list[Move]:
        return [m for m in self.moves if m.status == CHANGE]


def _rel(path: Path | None, root: Path | None) -> str:
    try:
        return str(Path(path).relative_to(root)).replace("\\", "/")
    except (ValueError, TypeError):
        return str(path or "")


def fund_folders(out_root: str | Path, erp_names: dict[str, str] | None = None) -> list[ProjectFolder]:
    """저장 폴더 아래의 대응자금 · 연구지원비 과제 폴더 — 폴더 이름이나 ERP 과제명에 그 말이 든 것(naming.own_budget)."""
    names = erp_names or {}
    return [f for f in folders(out_root) if naming.own_budget(f.path.name, names.get(f.no, ""))]


def pdf_text(path: Path, pages: int = PAGES) -> str:
    import pypdf

    reader = pypdf.PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages[:pages])


def _pdfs(root: Path):
    """과제 폴더 바로 아래와 그 아래 폴더(비목 폴더 · 그 안의 업로드 …)의 PDF — (경로, 업로드 안인지)."""
    for top, dirs, files in os.walk(root):
        dirs.sort()
        for name in sorted(files):
            if name.lower().endswith(".pdf"):
                path = Path(top) / name
                yield path, naming.UPLOAD_DIR in path.relative_to(root).parts


def _free(target: Path, taken: set[Path]) -> Path:
    """덮어쓰지 않게 — 있거나 이번에 이미 쓰기로 한 이름이면 _2, _3."""
    if not target.exists() and target not in taken:
        return target
    base, n = target.name[:-4], 2
    while (target.parent / f"{base}_{n}.pdf").exists() or (target.parent / f"{base}_{n}.pdf") in taken:
        n += 1
    return target.parent / f"{base}_{n}.pdf"


def plan_folder(folder: ProjectFolder, budget: list, reader: Callable[[Path], str] = pdf_text) -> list[Move]:
    """한 과제 폴더 안의 PDF 마다 무엇을 할지. 파일은 건드리지 않는다."""
    out: list[Move] = []
    taken: set[Path] = set()
    for path, uploaded in _pdfs(folder.path):
        move = Move(folder.no, path, home=folder.path)
        out.append(move)
        try:
            text = reader(path)
        except Exception:  # noqa: BLE001 — 열지 못한 PDF(동기화 중 · 깨짐)는 그대로 둔다
            move.why = "PDF 를 읽지 못함"
            continue
        m = DOC_NO_PATTERN.search(re.sub(r"\s+", " ", text))
        doc = m.group(1) if m else ""
        if not doc:
            move.status, move.why = OTHER, "문서번호가 없는 파일(청구서가 아님)"
            continue
        head = re.match(r"(\d{12})-\d{8}-\d+$", doc)
        if not head or head.group(1) != folder.no:
            move.status, move.why = OTHER, f"다른 과제의 문서번호({doc})"
            continue
        amount = AMOUNT.search(path.name)
        code = naming.budget_code(budget, path.stem, {"full": text}, amount.group(1).replace(",", "") if amount else "")
        if not code:
            move.why = "PDF 에서 비목을 정하지 못함 — 열어 보고 직접 옮기세요"
            continue
        name = naming.swap_code(path.name, code)   # '0N_(날짜) …' · '(날짜) 0N_…' 의 번호만 — 번호 없는 이름(날짜만)은 그대로
        target_dir = naming.budget_folder(folder.path, code, budget)
        target = target_dir / name
        if target == path:
            move.status, move.why = SAME, "이미 맞음"
            continue
        if uploaded:
            # 업로드 폴더는 앱이 옮기지 않는다 — 플랫폼에 올렸다는 담당자의 표시라서. 고칠 이름만 보여 준다
            move.status, move.target, move.why = UPLOADED, target, "업로드 폴더라 그대로 둠 — 필요하면 직접 고치세요"
            continue
        move.status, move.target = CHANGE, _free(target, taken)
        taken.add(move.target)
        move.why = naming.folder_name(code, budget) + " (예산 탭 " + code + "번)"
    return out


def plan(out_root: str | Path, budget_of: Callable[[str], tuple[list, str]], erp_names: dict[str, str] | None = None,
         reader: Callable[[Path], str] | None = None, log: Callable[[str], None] = lambda _m: None) -> Plan:
    """대응자금 과제 폴더마다 예산 탭 차례(budget_of — ERP 를 읽는다)를 얻고 파일마다 할 일을 정한다."""
    result = Plan()
    for folder in fund_folders(out_root, erp_names):
        budget, why = budget_of(folder.no)
        if not budget:
            result.blocked.append((folder.no, why or "예산 탭을 읽지 못함"))
            log(f"⚠ 과제 {folder.no}: 예산 탭을 읽지 못해 파일을 고치지 않습니다 — {why}")
            continue
        result.budgets[folder.no] = budget
        result.folders[folder.no] = folder.path
        moves = plan_folder(folder, budget, reader or pdf_text)
        result.moves += moves
        log(f"과제 {folder.no} 파일 {len(moves)}개: " + " · ".join(
            f"{status} {n}" for status in (CHANGE, SAME, UNSURE, UPLOADED, OTHER)
            if (n := sum(1 for m in moves if m.status == status))))
    return result


def apply(moves: list[Move], cache_path: Path | None = None, log: Callable[[str], None] = lambda _m: None) -> list[Move]:
    """'바꿈' 인 것만 옮긴다 — 옮기기 직전에 다시 본다(원본이 있고, 바꿀 이름이 비어 있고, 업로드 폴더가 아닌지). 덮어쓰지 않는다."""
    renamed: dict[str, str] = {}
    for move in moves:
        if move.status != CHANGE or move.target is None or move.done:
            continue
        try:
            naming.ensure_not_upload(move.target)
            if naming.UPLOAD_DIR in move.source.parts:
                raise RuntimeError("업로드 폴더의 파일은 옮기지 않습니다")
            if not move.source.is_file():
                raise RuntimeError("파일이 없어졌습니다")
            if move.target.exists():
                raise RuntimeError("같은 이름의 파일이 생겼습니다 — 덮어쓰지 않습니다")
            move.target.parent.mkdir(parents=True, exist_ok=True)
            move.source.rename(move.target)
        except (OSError, RuntimeError) as error:
            move.why = f"옮기지 못함: {error}"
            log(f"   ✖ {move.source.name} — {move.why}")
            continue
        move.done = True
        renamed[str(move.source)] = str(move.target)
        log(f"   ✓ {move.source.parent.name}/{move.source.name} → {move.target.parent.name}/{move.target.name}")
    if renamed and cache_path is not None:
        _rename_cached(cache_path, renamed)
    return moves


def _rename_cached(cache_path: Path, renamed: dict[str, str]) -> None:
    """보관 스캔 캐시(경로 → 문서번호)의 경로도 바꿔 둔다 — 다음 스캔에 다시 읽지 않게. 못 해도 다음 스캔이 다시 읽을 뿐이다."""
    try:
        cache = json.loads(Path(cache_path).read_text(encoding="utf-8"))
        if not isinstance(cache, dict):
            return
        for old, new in renamed.items():
            if old in cache:
                cache[new] = cache.pop(old)
        Path(cache_path).write_text(json.dumps(cache, ensure_ascii=False, indent=0), encoding="utf-8")
    except (OSError, ValueError):
        pass


def emptied(moves: list[Move]) -> list[Path]:
    """옮긴 뒤 빈 폴더(남은 파일 · 폴더가 없는 옛 비목 폴더) — 지우지 않고 알리기만 한다."""
    out = []
    for parent in sorted({m.source.parent for m in moves if m.done}):
        try:
            if parent.is_dir() and not any(parent.iterdir()):
                out.append(parent)
        except OSError:
            continue
    return out
