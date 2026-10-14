"""채운 기록 — 같은 지출 폴더를 두 번 채우지 않게 경고하는 근거. ~/.claim-downloader/_청구입력기록.json

기록은 '앱이 ERP 에 채웠다' 까지다. 저장·신청은 사람이 하므로 실제로 청구가 들어갔는지는 모른다 —
그래서 막지 않고 묻기만 한다.
"""
from __future__ import annotations

import json
import os
import time

from .. import settings


def _load() -> dict:
    try:
        data = json.loads(settings.claim_record_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _key(folder) -> str:
    return os.path.normcase(os.path.abspath(str(folder)))


def previous(folder) -> dict | None:
    """이 폴더를 전에 채운 적이 있으면 그 기록 {when, amount, summary}."""
    return _load().get(_key(folder))


def remember(folder, data: dict) -> None:
    records = _load()
    records[_key(folder)] = {
        "when": time.strftime("%Y-%m-%d %H:%M"),
        "amount": data.get("amount"),
        "summary": data.get("summary", ""),
        "req_cnt": data.get("req_cnt", ""),          # 장학금 등 — 그 폴더를 넣은 ERP 청구서의 결의번호
    }
    settings.claim_record_path().write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
