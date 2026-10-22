"""로그 보내기 — 개인정보를 가린 실행 기록을 담당자 구글 시트의 '로그' 탭으로 보낸다. Qt 없음(테스트가 PySide6 없이 본다).

담당자 2026-10-22: "오류 생겼거나 했을 때 클로드가 바로 로그내용을 '로그 내용 전송' … 버튼하나만 누르면 … 읽을 수 있도록 … 매번 복붙하거나
파일 저장하고 갔다주고 힘드네" → 깃허브 대신 구글 시트로("깃허브를 사용하지 않고 구글시트를 사용해서").
길은 관리대장 구글 시트 연동(parking_sheet.py)의 웹 앱 그대로 — 새 설정 없이 스크립트만 새로 붙여 넣는다.
- 보내기: share_log.compose 로 가린 기록(최근 SEND_LINES 줄 + 업무 · 오류 머리)을 조각(PART 자)으로 나눠 'log_add' 로 POST.
- 읽기: 스크립트의 doGet 이 열쇠(Config.log_key)가 맞는 GET 에만 그 기록을 글로 돌려준다. 앱은 그 주소를 담은 한 줄(Sent.line)을
  클립보드에 둔다 — 담당자는 채팅에 붙여 넣기만 하고, Claude 는 그 주소를 읽는다(CLAUDE.md 24절).
열쇠로는 기록만 읽힌다(관리대장은 TOKEN). 기록은 가린 사본이라도 과제번호 · 금액 · 적요는 남는다 — 담당자 계정의 시트에만 쌓고 최근 30번만 남긴다.
"""
from __future__ import annotations

import time
import urllib.parse
from collections.abc import Iterable
from dataclasses import dataclass

from . import parking_sheet, share_log

SEND_LINES = 3000       # 붙여 넣던 사본(800줄)보다 넉넉히 — 받기 한 번이 수백 줄이다
PART = 40000            # 시트 칸 하나에 5만 자까지 — 조각 머리 줄을 붙여도 넘지 않게

OLD_SCRIPT = ("구글 시트의 스크립트가 옛 판이라 로그를 받지 못합니다. 설정 → '구글 시트 연동' 의 [스크립트 복사] 로 새 글을 복사해 "
              "Apps Script 에 붙여 넣고 저장한 뒤, 배포 → 배포 관리 → (연필) 수정 → 버전 '새 버전' → 배포 를 눌러 주세요(주소는 그대로).")
NOT_CONNECTED = ("구글 시트가 연결돼 있지 않아 보내지 못했습니다. 설정 → '구글 시트 연동' 에서 한 번 연결하면 "
                 "다음부터 [로그 보내기] 한 번으로 보냅니다.")


def split(text: str, size: int = PART) -> list[str]:
    """줄 경계에서 나눈다(조각을 이으면 원래 글). 한 줄이 size 보다 길면 그 줄만 잘라 나눈다."""
    parts: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        while len(line) > size:
            if current:
                parts.append(current)
                current = ""
            parts.append(line[:size])
            line = line[size:]
        if len(current) + len(line) > size:
            parts.append(current)
            current = ""
        current += line
    if current or not parts:
        parts.append(current)
    return parts


def read_url(config: parking_sheet.Config, log_id: str = "") -> str:
    """Claude 가 읽을 주소 — 웹 앱 주소 + 열쇠(+ 보낸 것의 id)."""
    query = {"key": config.log_key}
    if log_id:
        query["id"] = log_id
    base = config.url.strip()
    return base + ("&" if "?" in base else "?") + urllib.parse.urlencode(query)


@dataclass
class Sent:
    ok: bool = False
    note: str = ""          # 담당자에게 보일 글
    log_id: str = ""
    url: str = ""           # 읽는 주소
    line: str = ""          # 채팅에 붙여 넣을 한 줄(클립보드)
    text: str = ""          # 보낸(또는 보내려던) 가린 기록 — 못 보내면 화면이 이것을 대신 복사한다
    old_script: bool = False


def send(task: str, error: str = "", names: Iterable[str] = (), version: str = "",
         config: parking_sheet.Config | None = None, opener=None, lines: int = SEND_LINES) -> Sent:
    config = config or parking_sheet.load_config()
    extra = [f"업무 {task}" if task else ""]
    if error.strip():
        extra.append("오류 " + " / ".join(part.strip() for part in error.strip().splitlines() if part.strip())[:500])
    keep = share_log.project_numbers()
    text = share_log.compose(names, version, lines, extra, keep)
    if not text:
        return Sent(note="아직 남은 실행 기록이 없습니다.")
    if not config.connected:
        return Sent(note=NOT_CONNECTED, text=text)
    if not config.log_key:
        # 로그 보내기 전에 붙여 넣은 스크립트 — 열쇠를 만들어 두고(다음 [스크립트 복사] 에 들어간다) 새로 붙이게 한다
        parking_sheet.script_text(config)
        return Sent(note=OLD_SCRIPT, text=text, old_script=True)
    # 오류 글도 가린다 — 머리 줄과 같은 규칙
    masked_error = share_log.mask_text(error.strip(), names, keep)[:500]
    try:
        data = parking_sheet.call(config, "log_add", opener=opener, task=task, error=masked_error, version=version, parts=split(text))
    except parking_sheet.SheetError as failure:
        message = str(failure)
        if "log_add" in message or "모르는 요청" in message:
            return Sent(note=OLD_SCRIPT, text=text, old_script=True)
        return Sent(note="로그를 보내지 못했습니다 — " + message, text=text)
    log_id = str(data.get("id") or "")
    if not log_id:
        return Sent(note=OLD_SCRIPT, text=text, old_script=True)
    url = read_url(config, log_id)
    line = f"로그 보냈어요 ({task} · {time.strftime('%m-%d %H:%M')}) {url}" if task else f"로그 보냈어요 ({time.strftime('%m-%d %H:%M')}) {url}"
    return Sent(ok=True, note="보냈습니다", log_id=log_id, url=url, line=line, text=text)
