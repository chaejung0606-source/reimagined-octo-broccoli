"""받은 기록과 보관 폴더 스캔.

중복 판단은 **문서번호로만** 한다. 금액+내용으로 맞춰 보면 오탐한다 — 4월
기관부담금 누락이 금액이 같은 5월 건과 짝지어져 숨어 있던 일이 실제로 있었다.

보관 스캔이 조용히 실패하면 이미 받은 것까지 전부 다시 받게 된다. 그래서
실패는 반드시 `ok=False` 와 경고 문구로 돌려주고, 호출부가 받기 전에 멈춘다.
"""
from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .naming import BIMOK, UNSORTED, UPLOAD_DIR

DOC_NO_PATTERN = re.compile(r"문서번호\s*[:：]?\s*([0-9A-Za-z가-힣]+-\d{8}-\d+)")


def load_done(path: Path) -> set[str]:
    try:
        with open(path, encoding="utf-8") as f:
            return set(json.load(f))
    except (OSError, ValueError, TypeError):
        return set()


def save_done(path: Path, done: set[str]) -> None:
    """받은 기록은 늘기만 한다 — 파일에 이미 있던 번호와 합쳐 쓴다. 기록을 읽지 않은 채 받은 건만 들고 있던 세션이
    파일을 덮어써 지난 기록이 사라진 적이 있다(2026-10-14 점검). 처음부터 다시 받으려면 사람이 파일을 지운다(README)."""
    merged = set(done) | load_done(path)
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:            # 쓰다 끊겨도 기록 파일이 반쪽이 되지 않게 임시 파일 → 바꿔치기
        json.dump(sorted(merged), f, ensure_ascii=False, indent=0)
    os.replace(tmp, path)


def read_doc_no(pdf: Path) -> str:
    """청구서 PDF 1쪽에서 문서번호. 못 읽으면 빈 문자열."""
    import pypdf

    text = pypdf.PdfReader(str(pdf)).pages[0].extract_text() or ""
    m = DOC_NO_PATTERN.search(re.sub(r"\s+", " ", text))
    return m.group(1) if m else ""


@dataclass
class ScanReport:
    ok: bool
    added: int = 0          # 이번에 done 에 새로 더한 문서번호 수
    scanned: int = 0        # 캐시에 없어 새로 읽은 PDF 수
    total_pdfs: int = 0
    warning: str = ""
    unreadable: int = 0     # 이번에 읽지 못한 PDF 수 — 캐시에 남기지 않아 다음에 다시 읽는다
    unreadable_names: list[str] = field(default_factory=list)


def scan_archive(out_root: str, cache_path: Path, done: set[str],
                 progress: Callable[[int], None] | None = None,
                 reader: Callable[[Path], str] = read_doc_no) -> ScanReport:
    """보관 폴더(업로드/ 포함, 재귀)의 PDF 에서 문서번호를 읽어 done 에 더한다.

    한 번 읽은 파일은 캐시에 남겨 다음 실행부터는 바로 끝난다.
    """
    if not out_root:
        return ScanReport(ok=False, warning="⚠⚠ 저장 폴더가 지정되지 않았습니다. [설정] 에서 먼저 지정하세요.")
    if not os.path.isdir(out_root):
        return ScanReport(ok=False, warning=(
            f"⚠⚠ 저장 폴더가 없습니다: {out_root}\n"
            "      이대로 받으면 이미 받은 건까지 전부 다시 받게 됩니다. 경로를 확인하세요."))
    try:
        import pypdf  # noqa: F401
    except ImportError:
        if reader is read_doc_no:
            return ScanReport(ok=False, warning="⚠⚠ pypdf 가 없어 보관 폴더를 읽지 못했습니다 — 중복 다운로드 주의")

    try:
        with open(cache_path, encoding="utf-8") as f:
            cache = json.load(f)
        if not isinstance(cache, dict):
            cache = {}
    except (OSError, ValueError):
        cache = {}

    report = ScanReport(ok=True)
    walk_errors: list[str] = []
    for root, _, files in os.walk(out_root, onerror=lambda error: walk_errors.append(str(getattr(error, "filename", "") or error))):
        for fn in files:
            if not fn.lower().endswith(".pdf"):
                continue
            report.total_pdfs += 1
            p = os.path.join(root, fn)
            dn = cache.get(p)
            if dn is None:
                try:
                    dn = reader(Path(p))
                except OSError:
                    # 열지 못한 파일(OneDrive 에만 있는 파일 · 다른 프로그램이 잡고 있는 파일)은 캐시에 남기지 않는다 — 전에는 '' 로
                    # 남겨 다시 읽지 않아, 그 청구서를 영영 '받지 않은 것' 으로 보고 다시 받았다(2026-10-14 점검). 다음 스캔에 다시 읽는다.
                    report.unreadable += 1
                    if len(report.unreadable_names) < 5:
                        report.unreadable_names.append(os.path.relpath(p, out_root))
                    continue
                except Exception:              # noqa: BLE001 — 깨진 PDF 하나로 스캔 전체를 멈추지 않는다(내용이 깨진 것은 다시 읽어도 같다)
                    dn = ""
                cache[p] = dn
                report.scanned += 1
                if progress and report.scanned % 25 == 0:
                    progress(report.scanned)
            if dn and dn not in done:
                done.add(dn)
                report.added += 1
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=0)
    except OSError:
        pass
    if walk_errors:
        # 읽지 못한 폴더가 있으면 그 안의 청구서를 모두 다시 받을 수 있다 — 받기 전에 묻게 ok=False
        report.ok = False
        report.warning = ("⚠⚠ 보관 폴더 중 열지 못한 곳이 있습니다: " + ", ".join(walk_errors[:3])
                          + ("" if len(walk_errors) <= 3 else f" 외 {len(walk_errors) - 3}곳")
                          + "\n      그 안의 청구서는 이미 받은 것인지 가려내지 못합니다. 폴더 권한 · OneDrive 동기화를 확인하세요.")
    return report


@dataclass
class FolderCount:
    name: str
    waiting: int      # 비목 폴더 바로 아래 — 플랫폼 업로드 전
    uploaded: int     # 업로드/ 아래 — 완료


def folder_status(out_root: str) -> list[FolderCount]:
    """비목 폴더별 대기·완료 PDF 수. 읽기만 한다."""
    if not out_root or not os.path.isdir(out_root):
        return []
    names = list(BIMOK.values()) + [UNSORTED]
    out = []
    for name in names:
        folder = Path(out_root) / name
        if not folder.is_dir():
            continue
        waiting = sum(1 for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".pdf")
        upload = folder / UPLOAD_DIR
        uploaded = sum(1 for p in upload.rglob("*.pdf")) if upload.is_dir() else 0
        out.append(FolderCount(name, waiting, uploaded))
    return out
