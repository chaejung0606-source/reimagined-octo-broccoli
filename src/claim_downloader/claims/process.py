"""지출 폴더 여러 건을 차례로 읽는 흐름 — 회의록(minutes/process.run)과 같은 모양.

로그인·한도·잔액 문제는 남은 폴더도 똑같이 실패하므로 첫 실패에서 멈추고 '건너뜀'. Qt 를 모른다.
"""
from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

from ..minutes.backends.base import BackendError, MinutesBackend
from ..minutes.errors import fatal_kind
from ..minutes.logbook import log
from ..naming import UPLOAD_DIR
from .rules import load_rules
from .schema import normalize, problems, summary_lines


@dataclass
class ExtractResult:
    ok: bool
    info: str                      # 실패 사유 한 줄 (성공이면 '')
    data: dict = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    kind: str = ""                 # login · limit · balance 면 남은 폴더 건너뜀


FIXED_RULE = "- 이 지출의 증빙구분(evidence)은 '{value}' 입니다. 세금계산서(계산서)에서 공급자 상호 · 사업자등록번호 · 승인번호 · 공급받는자 이메일 · 작성일 · 공급가액 · 세액을 읽으세요."


def process_folder(folder: str | Path, backend: MinutesBackend, rules: str | None = None,
                   fixed: dict | None = None) -> ExtractResult:
    """fixed 는 청구 종류가 정해 둔 값({'evidence': '세금계산서'}) — 규칙에 한 줄 더해 AI 에 알리고, 읽은 뒤에도 그 값으로 둔다."""
    folder = Path(folder)
    if not folder.is_dir():
        return ExtractResult(False, "폴더가 없음")
    if UPLOAD_DIR in folder.parts:
        # 업로드 폴더 안을 읽는 것은 막지 않지만, 거기 결과를 쓰는 일은 없어야 한다 — 읽기만 한다
        log("주의: 업로드 폴더 안의 자료를 읽음 — %s" % folder)
    rules_text = load_rules() if rules is None else rules
    if fixed and fixed.get("evidence"):
        rules_text = rules_text.rstrip() + "\n" + FIXED_RULE.format(value=fixed["evidence"])
    try:
        raw = backend.generate(folder, rules_text)
        if not isinstance(raw, dict):
            raise BackendError("청구 데이터가 생성되지 않음")
    except BackendError as error:
        return ExtractResult(False, str(error), kind=fatal_kind(error))
    except Exception as error:  # noqa: BLE001
        log("폴더 처리 중 오류: %s\n%s" % (folder, traceback.format_exc()))
        return ExtractResult(False, "오류: " + str(error)[:60])
    data = normalize(raw)
    for key, value in (fixed or {}).items():
        if data.get(key) != value:
            log("%s: AI 가 읽은 %s '%s' 대신 청구 종류의 '%s' 로 둡니다" % (folder, key, data.get(key) or "", value))
            data[key] = value
    found = problems(data)
    log("읽음: %s\n  " % folder + "\n  ".join(summary_lines(data))
        + ("\n  확인: " + " · ".join(found) if found else ""))
    return ExtractResult(True, "", data, found)


def run(folders: list[str | Path], backend: MinutesBackend, rules: str | None = None,
        should_stop: Callable[[], bool] | None = None, fixed: list[dict | None] | None = None) -> Iterator[tuple[int, str, object]]:
    """(번호, 사건, 값): ('start', None) · ('done', ExtractResult) · ('skip', 종류) · ('stopped', None). fixed 는 폴더마다의 고정값."""
    rules_text = load_rules() if rules is None else rules
    fixed = list(fixed or [])
    stop = ""
    for index, folder in enumerate(folders):
        if should_stop is not None and should_stop():
            yield index, "stopped", None
            continue
        if stop:
            yield index, "skip", stop
            continue
        yield index, "start", None
        result = process_folder(folder, backend, rules_text, fixed[index] if index < len(fixed) else None)
        if not result.ok:
            stop = result.kind
        yield index, "done", result
