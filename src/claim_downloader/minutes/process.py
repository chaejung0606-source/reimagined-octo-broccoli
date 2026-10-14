"""회의 1건 처리 — 백엔드가 만든 dict 를 그 회의 폴더 안의 .hwpx 로.

옛 도구 process_meeting 의 뒷부분(파일 이름 → 중복 피하기 → 한글 문서 → 실패하면 워드 문서)이다.
앞부분(CLI 실행)은 백엔드마다 다르므로 backends/ 로 갔다. 이 파일은 백엔드가 무엇이든 같다.

run() 은 여러 회의를 차례로 돌리는 흐름이다. 로그인·한도·잔액 문제(errors.fatal_kind)가 나면 남은
회의를 돌려도 똑같이 실패하므로 '건너뜀' 으로 넘긴다 — 회의 1건에 20~35턴이 든다.
Qt 를 모르는 제너레이터라 화면 없이 테스트한다(tests/test_minutes.py).
"""
from __future__ import annotations

import os
import re
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

from .backends.base import MinutesBackend
from .docx import build_docx
from .errors import BackendError, fatal_kind
from .hwpx import build_hwpx
from .logbook import log
from .naming import _sanitize, _unique, ensure_not_upload
from .rules import load_rules
from .schema import problems


@dataclass
class MeetingResult:
    ok: bool
    info: str          # 성공이면 만든 파일의 전체 경로, 실패면 사유 한 줄(한국어)
    note: str = ""     # 보완요청 (성공일 때만)
    kind: str = ""     # 실패가 남은 회의까지 막는 종류면 login · limit · balance


_XML_BAD = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


def _clean(value):
    """AI 가 돌려준 값에서 XML 에 쓸 수 없는 제어 문자를 걷어낸다 — 그대로 두면 한글이 못 여는 .hwpx 가 '성공' 으로 남았다
    (2026-10-14 점검). hwpx.py 는 손대지 않고 넘기기 전에 여기서."""
    if isinstance(value, str):
        return _XML_BAD.sub("", value)
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def write_minutes(data: dict, meeting_dir: str | Path) -> tuple[str, str]:
    """dict 를 회의 폴더 안의 .hwpx 로. 돌려주는 값은 (경로, 보완요청)."""
    meeting_dir = str(meeting_dir)
    ensure_not_upload(meeting_dir)
    data = _clean(data)
    for problem in problems(data):
        log("회의록 데이터 확인: %s — %s" % (problem, meeting_dir))
    base = _sanitize(data.get("filenameBase") or "회의록")
    # 회의록은 회의 자료가 들어 있는 그 폴더에 저장한다.
    out = _unique(os.path.join(meeting_dir, base + ".hwpx"))
    try:
        build_hwpx(data, out)
    except Exception as e:
        # 한글 문서를 만들지 못하면 회의록을 통째로 잃지 않도록 워드 문서로 남긴다.
        log("한글 문서 생성 오류: %s\n%s" % (meeting_dir, traceback.format_exc()))
        try:
            if os.path.exists(out):
                os.remove(out)
            out = _unique(os.path.join(meeting_dir, base + ".docx"))
            build_docx(data, out)
        except Exception:
            log("워드 문서 생성도 실패\n" + traceback.format_exc())
            raise BackendError("문서 생성 오류: " + str(e)[:60])
    note = str(data.get("supplement", "") or "").strip() or "보완사항 없음"
    return out, note


def process_meeting(meeting_dir: str | Path, backend: MinutesBackend,
                    rules: str | None = None) -> MeetingResult:
    meeting_dir = Path(meeting_dir)
    if not meeting_dir.is_dir():
        return MeetingResult(False, "회의 폴더가 없음")
    try:
        ensure_not_upload(meeting_dir)
        data = backend.generate(meeting_dir, load_rules() if rules is None else rules)
        if not isinstance(data, dict):
            raise BackendError("회의록 데이터가 생성되지 않음")
        out, note = write_minutes(data, meeting_dir)
    except BackendError as error:
        return MeetingResult(False, str(error), kind=fatal_kind(error))
    except RuntimeError as error:          # 업로드 폴더 보호
        return MeetingResult(False, str(error))
    except Exception as error:  # noqa: BLE001 — 한 회의의 오류가 나머지를 막지 않게
        log("회의 처리 중 오류: %s\n%s" % (meeting_dir, traceback.format_exc()))
        return MeetingResult(False, "오류: " + str(error)[:60])
    log("회의록 저장: %s" % out)
    return MeetingResult(True, out, note)


def run(meeting_dirs: list[str | Path], backend: MinutesBackend, rules: str | None = None,
        should_stop: Callable[[], bool] | None = None) -> Iterator[tuple[int, str, object]]:
    """회의를 차례로 돌리며 (번호, 사건, 값)을 낸다.

      ("start", None)           이 회의를 작성하기 시작
      ("done", MeetingResult)   끝남 — 성공이든 실패든
      ("skip", 종류)            앞의 치명적 오류(login · limit · balance)로 건너뜀
      ("stopped", None)         사람이 멈춤을 눌러 남은 회의를 하지 않음
    규칙은 한 번만 읽어 모든 회의에 같은 것을 쓴다.
    """
    rules_text = load_rules() if rules is None else rules
    stop = ""           # 로그인·한도 문제로 남은 회의를 건너뛰는 중이면 그 종류
    for index, meeting_dir in enumerate(meeting_dirs):
        if should_stop is not None and should_stop():
            yield index, "stopped", None
            continue
        if stop:
            yield index, "skip", stop
            continue
        yield index, "start", None
        result = process_meeting(meeting_dir, backend, rules_text)
        if not result.ok:
            stop = result.kind
        yield index, "done", result
