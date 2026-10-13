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


def process_folder(folder: str | Path, backend: MinutesBackend, rules: str | None = None) -> ExtractResult:
    folder = Path(folder)
    if not folder.is_dir():
        return ExtractResult(False, "폴더가 없음")
    if UPLOAD_DIR in folder.parts:
        # 업로드 폴더 안을 읽는 것은 막지 않지만, 거기 결과를 쓰는 일은 없어야 한다 — 읽기만 한다
        log("주의: 업로드 폴더 안의 자료를 읽음 — %s" % folder)
    try:
        raw = backend.generate(folder, load_rules() if rules is None else rules)
        if not isinstance(raw, dict):
            raise BackendError("청구 데이터가 생성되지 않음")
    except BackendError as error:
        return ExtractResult(False, str(error), kind=fatal_kind(error))
    except Exception as error:  # noqa: BLE001
        log("폴더 처리 중 오류: %s\n%s" % (folder, traceback.format_exc()))
        return ExtractResult(False, "오류: " + str(error)[:60])
    data = normalize(raw)
    found = problems(data)
    log("읽음: %s\n  " % folder + "\n  ".join(summary_lines(data))
        + ("\n  확인: " + " · ".join(found) if found else ""))
    return ExtractResult(True, "", data, found)


def run(folders: list[str | Path], backend: MinutesBackend, rules: str | None = None,
        should_stop: Callable[[], bool] | None = None) -> Iterator[tuple[int, str, object]]:
    """(번호, 사건, 값): ('start', None) · ('done', ExtractResult) · ('skip', 종류) · ('stopped', None)."""
    rules_text = load_rules() if rules is None else rules
    stop = ""
    for index, folder in enumerate(folders):
        if should_stop is not None and should_stop():
            yield index, "stopped", None
            continue
        if stop:
            yield index, "skip", stop
            continue
        yield index, "start", None
        result = process_folder(folder, backend, rules_text)
        if not result.ok:
            stop = result.kind
        yield index, "done", result
