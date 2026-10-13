"""지출 폴더 → 일반청구 dict. 1단계 백엔드는 Claude Code CLI 하나 (회의록과 같은 규약).

규약은 minutes/backends/base.py 의 MinutesBackend 와 같다 — available() · generate(folder, rules) -> dict.
CLI 를 돌리는 함수(find_claude · claude_command · _run_kwargs · check_claude)는 회의록 쪽 것을 그대로
쓴다. 프롬프트만 다르다. 폴더 경로 한 줄만 넘기고 자료는 에이전트가 스스로 읽는다(PDF·이미지 직접,
.docx 는 풀어서; .hwp 는 못 읽으면 notes 에 적는다).
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import tempfile
import traceback
from pathlib import Path

from .. import settings
from ..minutes.backends.base import BackendError, MinutesBackend
from ..minutes.backends import claude_cli as claude_cli_module
from ..minutes.backends.claude_cli import TIMEOUT_SEC, _run_kwargs, check_claude, claude_command, find_claude
from ..minutes.errors import _extract_json, _failure_reason
from ..minutes.logbook import log
from ..minutes.textfile import _read_text
from .rules import load_rules
from .schema import EVIDENCE_KINDS, EXP_CATEGORIES, SETTLE_METHODS


def build_prompt(folder: str, json_path: str, rules: str | None = None) -> str:
    return (
        "당신은 대학 사업단의 ERP '일반청구' 작성을 돕는 도구입니다.\n"
        "'" + folder + "' 폴더 바로 아래의 지출 자료 파일을 모두 읽으세요(하위 폴더는 보지 마세요).\n"
        "PDF와 이미지(세금계산서·통장사본 사진 등)는 직접 읽으세요.\n"
        ".docx 는 ZIP 압축 파일이므로, Bash 도구에서 사용 가능한 방법(unzip, python, powershell 등 "
        "그 환경에서 실제로 동작하는 것)으로 풀어 word/document.xml 의 본문 텍스트를 읽으세요.\n"
        ".hwp 는 직접 읽기 어려우니 읽지 못하면 notes 에 '한글(.hwp) 파일은 PDF로 변환 후 다시 넣어주세요'라고 적으세요.\n"
        "아래 [규칙]에 따라 값을 정리한 뒤, 결과를 정확히 '" + json_path + "' 경로에 UTF-8 JSON 파일로 저장하세요(Write 도구 사용).\n"
        "JSON 스키마:\n"
        "{\n"
        '  "summary": "ERP 적요 (NN_내용)",\n'
        '  "expCategory": "비목 — ' + " | ".join(EXP_CATEGORIES) + '",\n'
        '  "expDetail": "세목(없으면 빈 문자열)",\n'
        '  "evidence": "' + " | ".join(EVIDENCE_KINDS) + '",\n'
        '  "expenseDate": "YYYY-MM-DD",\n'
        '  "amount": 51900, "supplyAmount": 47182, "taxAmount": 4718,\n'
        '  "payeeName": "거래처 상호", "payeeBizNo": "000-00-00000",\n'
        '  "bank": "은행명", "accountNo": "계좌번호", "owner": "예금주",\n'
        '  "settleMethod": "' + " | ".join(SETTLE_METHODS) + '",\n'
        '  "attachments": ["첨부할 파일 이름"],\n'
        '  "notes": "확인이 필요한 점 (없으면 빈 문자열)"\n'
        "}\n"
        "위 JSON 파일 하나만 저장하고 다른 파일은 만들지 마세요. 폴더 안의 파일을 고치거나 지우지 마세요. "
        "반드시 한국어로 작성하세요.\n\n"
        "[규칙]\n" + (rules if rules is not None else load_rules())
    )


class ClaudeCliExtractor:
    key = "claude-cli"
    label = "Claude Code (이 PC 에 로그인된 Claude 구독)"

    def __init__(self, model: str | None = None):
        self.model = settings.load().minutes_model if model is None else model
        self.last_state = ""

    def available(self) -> tuple[bool, str]:
        state, info = check_claude()
        self.last_state = state
        if state == "no_claude":
            return False, info
        if state == "no_login":
            return True, "로그인이 풀린 것으로 보입니다 (틀릴 수 있어 막지는 않습니다)"
        return True, "Claude Code " + info

    def generate(self, folder: Path, rules: str) -> dict:
        folder = str(folder)
        exe = find_claude()
        if not exe:
            raise BackendError("claude 명령을 찾을 수 없음")
        tmp = tempfile.mkdtemp(prefix="cl_")
        json_path = os.path.join(tmp, "claim.json")
        cli_args = [
            "-p", build_prompt(folder, json_path, rules),
            "--output-format", "json",
            "--permission-mode", "acceptEdits",
            "--allowedTools", "Read,Glob,Grep,Write,Edit,Bash,PowerShell",
            "--add-dir", tmp,
        ]
        if self.model:
            cli_args += ["--model", self.model]
        try:
            r = subprocess.run(claude_command(exe, cli_args), **_run_kwargs(folder, TIMEOUT_SEC))
        except FileNotFoundError:
            shutil.rmtree(tmp, ignore_errors=True)
            raise BackendError("claude 실행 파일을 열 수 없음")
        except subprocess.TimeoutExpired:
            shutil.rmtree(tmp, ignore_errors=True)
            log("시간 초과: %s" % folder)
            raise BackendError("시간 초과(자료가 너무 많음)")
        except Exception as e:  # noqa: BLE001
            shutil.rmtree(tmp, ignore_errors=True)
            log("실행 오류: %s\n%s" % (folder, traceback.format_exc()))
            raise BackendError("실행 오류: " + str(e)[:60])

        data = None
        if not os.path.exists(json_path):
            cands = glob.glob(os.path.join(tmp, "*.json"))
            json_path = cands[0] if cands else None
        if json_path and os.path.exists(json_path):
            try:
                text = _read_text(json_path)
            except Exception:  # noqa: BLE001
                log("결과 파일을 읽지 못함: %s\n%s" % (json_path, traceback.format_exc()))
                text = ""
            try:
                data = json.loads(text)
            except Exception:  # noqa: BLE001
                data = _extract_json(text)
        if data is None:
            outer = _extract_json(r.stdout)
            if isinstance(outer, dict) and outer.get("result"):
                data = _extract_json(str(outer.get("result")))
        shutil.rmtree(tmp, ignore_errors=True)
        if not isinstance(data, dict):
            log("청구 데이터 없음: %s\nrc=%s\nstdout=%s\nstderr=%s"
                % (folder, r.returncode, (r.stdout or "")[:4000], (r.stderr or "")[:4000]))
            raise BackendError(_failure_reason(r))
        return data


DEFAULT_KEY = ClaudeCliExtractor.key
_REGISTRY: dict[str, type] = {}


def register(cls: type) -> type:
    _REGISTRY[cls.key] = cls
    return cls


register(ClaudeCliExtractor)


def keys() -> list[str]:
    return list(_REGISTRY)


def labels() -> list[tuple[str, str]]:
    return [(key, cls.label) for key, cls in _REGISTRY.items()]


def get(key: str = "") -> MinutesBackend:
    cls = _REGISTRY.get(key) or _REGISTRY[DEFAULT_KEY]
    return cls()
