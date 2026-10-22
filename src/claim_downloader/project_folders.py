"""과제 폴더 — 저장 폴더 아래 `(과제번호)_…` 폴더마다 그 과제의 비목 폴더(01. 인건비 …)를 둔다.

담당자가 2026-10-21 에 보관 폴더를 과제마다 나눴다: `바탕화면\\지출결의서\\(202408470003)_2026년도 사업비_4,438,000,000\\` 처럼 이름 앞 괄호에
과제번호(ERP 과제현황의 과제번호)를 적은 폴더가 과제 수만큼 있고, 그 안에 전처럼 비목 폴더 · `업로드\\` 가 있다. 같은 날 요청:
"과제번호로 과제 구분해서 청구서 다운받을 수 있도록" · "일단 지금 폴더 만든 과제만 다운받아주세요" — 그래서 받기는 **폴더가 있는 과제만**,
그 과제의 폴더 안에 저장한다. 폴더가 하나도 없는 저장 폴더(옛 모양 — 비목 폴더가 바로 아래)는 전처럼 그 폴더에 둔다.
폴더는 읽기만 하고 만들지 않는다 — 과제 폴더 이름(연도 · 사업비)은 담당자가 정한다.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

PROJECT_DIR = re.compile(r"^\s*\(\s*(\d{6,})\s*\)\s*[_\-\s]*(.*)$")


@dataclass
class ProjectFolder:
    no: str
    path: Path

    @property
    def title(self) -> str:
        """폴더 이름의 과제번호 뒤 — '2026년도 사업비_4,438,000,000'."""
        m = PROJECT_DIR.match(self.path.name)
        return (m.group(2) if m else self.path.name).strip()

    def short(self) -> str:
        """좁은 칸 — '202408470003 2026년도 사업비' (끝의 금액은 뺀다)."""
        title = re.sub(r"[_\s]*[\d,]{5,}\s*$", "", self.title).strip(" _")
        return f"{self.no} {title}" if title else self.no


def project_of(path: str | Path) -> str:
    """폴더 이름이 `(과제번호)…` 이면 그 번호, 아니면 ''."""
    m = PROJECT_DIR.match(Path(path).name)
    return m.group(1) if m else ""


def folders(out_root: str | Path) -> list[ProjectFolder]:
    """저장 폴더 바로 아래의 과제 폴더(이름 순). 저장 폴더가 없으면 빈 목록."""
    try:
        entries = sorted(os.scandir(out_root), key=lambda e: e.name) if out_root else []
    except OSError:
        return []
    out = []
    for entry in entries:
        try:
            if entry.is_dir() and project_of(entry.name):
                out.append(ProjectFolder(project_of(entry.name), Path(entry.path)))
        except OSError:
            continue
    return out


def signature(out_root: str | Path) -> tuple[str, ...]:
    """지금 있는 과제 폴더의 과제번호 묶음(이름 순) — 받기 화면이 열릴 때 이것이 바뀌었으면 과제 칸을 다시 채운다
    (담당자가 앱을 켠 채 과제 폴더를 더 만든 2026-10-22 — 다시 켜지 않아도 칸에 보이게)."""
    return tuple(f.no for f in folders(out_root))


def by_project(out_root: str | Path) -> dict[str, list[ProjectFolder]]:
    found: dict[str, list[ProjectFolder]] = {}
    for folder in folders(out_root):
        found.setdefault(folder.no, []).append(folder)
    return found


def pick(found: list[str], saved: str) -> list[str]:
    """고른 과제(설정에 쉼표로 남긴 번호) 중 지금 폴더가 있는 것 — 폴더 차례대로. 폴더를 지웠으면 빠진다."""
    wanted = set(re.findall(r"\d{6,}", str(saved or "")))
    return [no for no in found if no in wanted]


def initial_choice(found: list[str], scope: str, saved: str, last: str) -> list[str]:
    """받기 화면 ② 를 열 때 체크해 둘 과제 — 지난번 고른 그대로. 'all'(모두 체크했던 것)이면 지금 있는 과제 모두 — 그 뒤에 만든 폴더도
    (담당자가 과제 폴더를 더 만든 2026-10-22). 남은 것이 없으면(폴더를 지웠으면) 모두."""
    if scope == "some":
        chosen = pick(found, saved)
    elif scope == "one":
        chosen = [last] if last in found else []
    else:
        chosen = list(found)
    return chosen or list(found)


def scope_of(chosen: list[str], found: list[str]) -> str:
    """설정 download_scope 에 남길 말 — 모두 체크했으면 'all'(다음에 폴더가 늘면 그것도 체크), 하나면 'one', 그 밖은 'some'."""
    if chosen and set(found) <= set(chosen):
        return "all"
    return "one" if len(chosen) == 1 else "some"


def _plain(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def matches(query: str, *texts: str) -> bool:
    """과제 찾기 칸 — 띄어쓰기로 나눈 낱말이 모두 과제번호 · 폴더 이름 · ERP 과제명 어딘가에 있으면(띄어쓰기 · 대소문자는 보지 않는다).
    담당자 2026-10-22 "그리고 검색 기능도" — 과제가 13개로 늘어 '연구지원비' · '0003' 처럼 일부만 넣어 찾는다."""
    haystack = _plain(" ".join(texts))
    return all(_plain(word) in haystack for word in str(query or "").split())


def save_root(out_root: str | Path, project_no: str) -> tuple[Path | None, str]:
    """그 과제의 청구서를 둘 폴더(비목 폴더가 바로 아래 생기는 곳)와, 못 정했으면 그 까닭.

    - 저장 폴더 아래에 과제 폴더가 있으면(새 모양) 이름의 과제번호가 같은 폴더 하나. 없거나 둘이면 받지 않는다.
    - 저장 폴더 자체가 과제 폴더면 그 과제만.
    - 과제 폴더가 하나도 없으면(옛 모양) 저장 폴더 그대로 — 과제를 가리지 않는다.
    """
    project = re.sub(r"\D", "", str(project_no or ""))
    root = Path(out_root)
    own = project_of(root)
    if own:
        if project and project != own:
            return None, f"저장 폴더가 다른 과제({own})의 폴더입니다 — 과제 {project} 의 청구서는 받지 않았습니다"
        return root, ""
    found = by_project(root)
    if not found:
        return root, ""
    if not project:
        return None, "어느 과제의 청구서인지 몰라 받지 않았습니다 — 받기 화면에서 과제를 고르세요"
    mine = found.get(project, [])
    if len(mine) == 1:
        return mine[0].path, ""
    if mine:
        return None, (f"과제 {project} 의 폴더가 {len(mine)}개입니다(" + " · ".join(f.path.name for f in mine)
                      + ") — 하나만 남기세요. 받지 않았습니다")
    return None, (f"저장 폴더에 과제 {project} 의 폴더가 없어 받지 않았습니다 — 받으려면 '({project})_…' 폴더를 만드세요")


def migrate(out_root: str) -> str:
    """설정의 저장 폴더가 사라졌고 그 위 폴더에 과제 폴더가 있으면 그 위 폴더 — 담당자가 옛 저장 폴더
    (지출결의서\\2026년도(e나라도움))를 과제 폴더로 옮겨 정리한 경우다(2026-10-21). 아니면 ''."""
    if not out_root or os.path.isdir(out_root):
        return ""
    parent = os.path.dirname(os.path.normpath(out_root))
    if parent and os.path.isdir(parent) and folders(parent):
        return parent
    return ""
