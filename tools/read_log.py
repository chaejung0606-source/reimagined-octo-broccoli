"""담당자가 [로그 보내기] 로 구글 시트 '로그' 탭에 보낸 기록을 Claude 세션이 읽는 도구 (2026-10-23).

채팅에 주소를 붙여 넣지 않아도 되게 — 클라우드 환경 변수 **COSS_LOG_URL** 에 앱 설정의 [로그 읽기 주소 복사] 로 복사한
고정 읽기 주소(`…/exec?key=<열쇠>`, id 없음)를 한 번 넣어 두면 새 세션마다 그대로 읽힌다. 주소 · 열쇠는 저장소 · 문서에 적지 않는다.

    python tools/read_log.py            # 가장 최근 로그
    python tools/read_log.py list       # 보낸 로그 목록(id · 때 · 업무 · 오류)
    python tools/read_log.py <id>       # 그 로그

구글이 script.googleusercontent.com 으로 돌리므로 urllib 로 연다(curl -L 은 그 주소에서 404 — CLAUDE.md 24절). 환경의 네트워크 허용 목록에
script.google.com · script.googleusercontent.com 이 있어야 한다.
"""
from __future__ import annotations

import os
import sys
import urllib.parse
import urllib.request

ENV = "COSS_LOG_URL"


def url_for(base: str, which: str = "") -> str:
    """고정 읽기 주소에 id 를 붙인다 — 'list' 면 목록, 빈 값이면 가장 최근."""
    base = base.strip()
    if not which:
        return base
    return base + ("&" if "?" in base else "?") + urllib.parse.urlencode({"id": which})


def fetch(url: str, opener=None) -> str:
    opener = opener or urllib.request.urlopen
    with opener(url, timeout=60) as response:
        return response.read().decode("utf-8", "replace")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    base = os.environ.get(ENV, "").strip()
    if not base:
        print(f"환경 변수 {ENV} 가 없습니다 — 앱 설정 → 구글 시트 연동의 [로그 읽기 주소 복사] 로 복사한 주소를 "
              "클라우드 환경의 변수(Network secrets 또는 환경 변수)에 넣어 두세요. 새 세션부터 읽힙니다.", file=sys.stderr)
        return 2
    which = argv[0] if argv else ""
    try:
        text = fetch(url_for(base, which))
    except Exception as error:  # noqa: BLE001 — 까닭을 그대로 보인다
        print(f"읽지 못했습니다: {error}", file=sys.stderr)
        return 1
    sys.stdout.write(text if text.endswith("\n") else text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
