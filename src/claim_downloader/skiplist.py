"""받지 않는 결의서 — 청구서출력이 없어 받을 수 없는 결의서(잔액조정 · 대체 …)를 기억해 두고 목록 읽기에서 뺀다.

담당자 2026-10-21: "지금 받지 못하는 결의서는 받지 않아도 되는 결의서 목록에 추가해주세요". 받기가 그런 결의서를 만나면
(erp.NoPrintScreen — 7절 12번) 건너뛰고 이 목록에 넣고, 다음 목록 읽기부터는 받을 것에서 뺀다.

- 결의서구분에 '청구' 가 든 결의서(일반청구 · 카드청구 · 대량청구)는 넣지 않는다 — 청구서출력이 있어야 할 결의서라 못 받았으면
  화면 탓일 수 있고, 목록에서 빠지면 그 청구서는 영영 안 받힌다(누락이 가장 나쁘다). 결의서구분을 모를 때도 넣지 않는다.
- ERP 알림이 로그인 · 세션 · 권한 이야기면 넣지 않는다 — 결의서 탓이 아니다.
- 이 목록이 생기기 전에 건너뛴 것은 _실행로그.txt 의 '↷ 건너뜀' 줄에서 처음 한 번 가져온다. 그 줄에는 문서번호가 없어
  과제번호 + 결의번호로 알아본다(결의번호는 과제 안에서 하나뿐이다).
- 받기 화면에서 목록을 보고 비울 수 있다. 비우면 다음 받기에서 다시 해 보고, 그래도 못 받으면 다시 들어온다.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from . import settings

NOT_DOCUMENT = re.compile(r"로그인|세션|만료|권한|접속|시간이 초과|시간초과")
STAMP = re.compile(r"^\d{2}:\d{2}:\d{2} ")
RUN_LINE = re.compile(r"════ .* 앱 실행 ════")
PROJECT_LINE = re.compile(r"^── 과제 (\S+) → ")
ITEM_LINE = re.compile(r"^\[\d+/\d+\] No (\S*) \(결의 (\d+)(?: · ([^)]*))?\) · (.*)$")
SKIP_LINE = re.compile(r"^\s*↷ 건너뜀 — (.*) \(결의서구분 '(.*)'\)\s*$")


def _digits(value) -> str:
    return re.sub(r"\D", "", str(value or ""))


def why_not(gubun: str, reason: str) -> str:
    """이 결의서를 목록에 넣지 않을 까닭 — 넣어도 되면 ''."""
    gubun = (gubun or "").strip()
    if not gubun or gubun == "?":
        return "결의서구분을 몰라서"
    if "청구" in gubun:
        return f"'{gubun}' 은 청구서출력이 있어야 할 결의서라서"
    if NOT_DOCUMENT.search(reason or ""):
        return "ERP 알림이 로그인 · 세션 이야기라서"
    return ""


def _read() -> dict | None:
    try:
        data = json.loads(settings.skip_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return {"items": []}
    return data if isinstance(data, dict) and isinstance(data.get("items"), list) else {"items": []}


def _save(items: list[dict]) -> None:
    path = settings.skip_path()
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps({"items": items, "from_log": True}, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def from_log(text: str) -> list[dict]:
    """_실행로그.txt 의 '↷ 건너뜀' 줄 — 그 앞의 '── 과제 … →' 줄과 '[i/N] No … (결의 … · 결의서구분) · 내용' 줄로 어느 결의서인지 안다."""
    found: dict[tuple[str, str], dict] = {}
    project, item = "", None
    for raw in text.splitlines():
        line = STAMP.sub("", raw, count=1)
        if RUN_LINE.search(line):
            project, item = "", None
            continue
        m = PROJECT_LINE.match(line)
        if m:
            project = m.group(1) if re.fullmatch(r"\d{12}", m.group(1)) else ""
            item = None
            continue
        m = ITEM_LINE.match(line)
        if m:
            item = {"no": m.group(1), "seq": m.group(2), "gubun": (m.group(3) or "").strip(), "cont": m.group(4).strip()}
            continue
        m = SKIP_LINE.match(line)
        if m and item and project:
            gubun = m.group(2).strip() if m.group(2).strip() not in ("", "?") else item["gubun"]
            if not why_not(gubun, m.group(1)):
                found[(project, item["seq"])] = {"project": project, "seq": item["seq"], "docNo": "", "gubun": gubun,
                                                 "cont": item["cont"], "reason": m.group(1).strip(), "at": "실행로그"}
            item = None
    return list(found.values())


def load() -> list[dict]:
    """목록. 파일이 아직 없으면(이 기능이 들어온 뒤 처음) 지난 실행로그의 '건너뜀' 줄에서 가져와 만든다."""
    data = _read()
    if data is not None:
        return [item for item in data["items"] if isinstance(item, dict)]
    try:
        text = settings.log_path().read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    items = from_log(text)
    try:
        _save(items)
    except OSError:
        pass
    return items


def matches(items: list[dict], row: dict, project: str = "") -> bool:
    """이 목록 행이 받지 않는 결의서인지 — 문서번호가 같거나, (문서번호를 모르는 항목이면) 과제번호 + 결의번호가 같으면."""
    doc = str(row.get("docNo") or "")
    seq = _digits(row.get("seq"))
    prj = _digits(project or row.get("project"))
    for item in items:
        if doc and item.get("docNo"):
            if item["docNo"] == doc:
                return True
            continue
        if prj and seq and item.get("project") == prj and _digits(item.get("seq")) == seq:
            return True
    return False


def add(row: dict, reason: str, project: str = "") -> tuple[bool, str]:
    """받기가 건너뛴 결의서를 넣는다 — (넣었는지, 안 넣은 까닭)."""
    why = why_not(row.get("gubun") or "", reason)
    if why:
        return False, why
    items = load()
    prj = _digits(project or row.get("project"))
    if matches(items, row, prj):
        return False, "이미 목록에 있음"
    items.append({"project": prj, "seq": _digits(row.get("seq")), "docNo": str(row.get("docNo") or ""),
                  "gubun": (row.get("gubun") or "").strip(), "cont": (row.get("cont") or "").strip()[:80],
                  "reason": (reason or "").strip()[:160], "at": time.strftime("%Y-%m-%d %H:%M")})
    _save(items)
    return True, ""


def clear() -> None:
    """목록을 비운다 — 다음 받기에서 다시 해 본다(실행로그에서 다시 가져오지는 않는다)."""
    _save([])
