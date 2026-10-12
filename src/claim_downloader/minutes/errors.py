"""오류 해석 — 백엔드의 실패를 한국어 한 줄로 바꾸고, 남은 회의를 계속 돌릴지 가린다.

회의 1건에 20~35턴이 든다. 로그인이 풀렸거나 한도가 찼거나 잔액이 없으면 남은 회의도 똑같이
실패하므로 첫 실패에서 멈춘다(_fatal_kind). 서버 혼잡·네트워크는 일시적일 수 있어 계속 간다.

판정은 _failure_reason() 이 만든 문구를 _LOGIN/_LIMIT/_BALANCE 상수와 startswith 로 비교한다.
**문구를 고치면 상수도 같이 고쳐야 한다.** 백엔드마다 오류 모양이 다르므로(API 는 HTTP 상태코드)
새 백엔드는 자기 오류를 BackendError(kind=...) 로 번역해 던진다 — 400(요청이 잘못됨)은 그 회의만의
문제이므로 kind 를 비워 둔다. 400 을 login 으로 묶으면 자료가 큰 회의 하나 때문에 나머지를 전부
건너뛴다.
"""
from __future__ import annotations

import json
import re


class BackendError(Exception):
    """백엔드가 회의록 데이터를 만들지 못했다. str(error) 는 사람이 읽을 한국어 한 줄.

    kind: "" (그 회의만 실패, 계속 진행) · "login" · "limit" · "balance" (남은 회의 건너뜀).
    kind 를 비워 두면 메시지 문구로 판정한다(fatal_kind).
    """

    def __init__(self, message: str, kind: str = ""):
        super().__init__(message)
        self.kind = kind


def fatal_kind(error) -> str:
    """BackendError 든 문자열이든 — 남은 회의를 건너뛰어야 하는 종류. 아니면 ''."""
    return getattr(error, "kind", "") or _fatal_kind(str(error))


def _extract_json(text):
    """Claude 응답에서 JSON 객체를 최대한 관대하게 뽑아낸다."""
    if not text:
        return None
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    i, j = text.find("{"), text.rfind("}")
    if i != -1 and j > i:
        try:
            return json.loads(text[i:j + 1])
        except Exception:
            pass
    return None


# CLI 가 영어로 돌려주는 대표적인 오류를 한국어 안내로 바꾼다.
_LIMIT = "Claude 사용 한도 초과"
_LOGIN = "Claude 에 로그인되어 있지 않음 (오른쪽 위 [Claude 로그인] 단추를 누르세요)"
_BALANCE = "Claude 잔액 부족"
_KNOWN_ERRORS = [
    ("not logged in", _LOGIN),
    ("please run /login", _LOGIN),
    ("invalid api key", _LOGIN),
    ("authentication_error", _LOGIN),
    ("oauth token", _LOGIN),
    ("credit balance", _BALANCE),
    ("session limit", _LIMIT),
    ("usage limit", _LIMIT),
    ("hit your limit", _LIMIT),
    ("quota", _LIMIT),
    ("rate limit", "요청이 너무 잦음 (잠시 후 다시 시도)"),
    ("overloaded", "Claude 서버가 혼잡함 (잠시 후 다시 시도)"),
    ("network", "네트워크 연결 오류"),
    ("econnrefused", "네트워크 연결 오류"),
    ("etimedout", "네트워크 연결 시간 초과"),
]


def _fatal_kind(info):
    """이번 작업에서 계속 시도해 봐야 소용없는 오류인지 가려낸다.

    로그인·한도·잔액 문제는 남은 회의를 돌려도 똑같이 실패한다.
    회의 1건마다 20~35턴이 들므로 여기서 멈추는 편이 낫다."""
    if not info:
        return ""
    if info.startswith(_LOGIN):
        return "login"
    if info.startswith(_LIMIT):
        return "limit"
    if info.startswith(_BALANCE):
        return "balance"
    return ""


def _failure_reason(r):
    """실패 사유를 사람이 읽을 수 있는 한 줄로 만든다.
    (--output-format json 의 출력이 그대로 노출되지 않도록 result 만 뽑아낸다.)"""
    text = ""
    outer = _extract_json(r.stdout)
    if isinstance(outer, dict):
        text = str(outer.get("result") or outer.get("error") or "").strip()
    if not text:
        text = (r.stderr or "").strip()
        text = text.splitlines()[-1] if text else ""
    low = text.lower()
    for key, korean in _KNOWN_ERRORS:
        if key in low:
            if korean == _LIMIT:
                # '· resets 7:50pm (Asia/Seoul)' 같은 해제 시각을 함께 알려준다.
                m = re.search(r"resets?\s+([^\n·]+)", text, re.I)
                if m:
                    return "%s — %s 에 풀림" % (korean, m.group(1).strip())
                return korean + " (한도가 풀린 뒤 다시 시도)"
            return korean
    if text:
        return text.replace("\n", " ")[:120]
    return "회의록 데이터가 생성되지 않음"
