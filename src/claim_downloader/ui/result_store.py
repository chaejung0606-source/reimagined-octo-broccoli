"""일반청구 결과 창 다시 보기 — 폴더마다 최근 결과 창의 내용(_청구결과.json).

담당자 2026-11-11(카드청구 결과 그림): "일반청구 결과내용이 새창에 뜨는데 이걸 한번 닫으면 다시 내용을 확인할 수 없습니다".
결과 창(카드청구 · 장학금 · 혁신인재지원금 · 첨부만 다시 올리기)의 내용을 넣은 폴더마다 남기고, ④ 의 [결과 다시 보기] 가 다시 띄운다.
앱을 다시 켜도(F5 새로고침 포함) 남는다. 학생 이름 · 금액 · 가맹점이 들어 있어 사용자 폴더에만 둔다(.gitignore · NEVER_PACK · CI).

여기는 JSON 만 다룬다(Qt 없음) — 창의 내용을 JSON 으로 바꾸는 것은 report_dialog.report_to_data · report_from_data.
"""
from __future__ import annotations

import datetime as dt
import json
import os

from .. import settings

NAME = "_청구결과.json"
KEEP_PER_FOLDER = 5          # 폴더마다 최근 결과 다섯
KEEP_FOLDERS = 80            # 폴더가 이보다 많으면 오래된 폴더부터 뺀다

_cache: dict | None = None   # 읽은 것 · 쓰지 못한 것도(쓰기가 막혀도 앱을 켜 둔 동안은 다시 본다)
_cache_path = None           # 그 캐시를 읽은 파일 — 사용자 폴더가 바뀌면(테스트) 다시 읽는다


def path():
    return settings.data_dir() / NAME


def _key(folder: str) -> str:
    return os.path.normcase(os.path.abspath(str(folder)))


def _load() -> dict:
    global _cache, _cache_path
    if _cache is None or _cache_path != path():
        _cache_path = path()
        try:
            data = json.loads(path().read_text(encoding="utf-8"))
            _cache = data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            _cache = {}
    return _cache


def forget_cache() -> None:
    """테스트 · 사용자 폴더를 바꿨을 때 — 다음에 파일을 다시 읽는다."""
    global _cache
    _cache = None


def save(folder: str, title: str, heading: str, report: dict, when: dt.datetime | None = None) -> str:
    """결과 창 하나를 남긴다. 돌려주는 것은 못 쓴 까닭('' 이면 씀) — 못 써도 앱을 켜 둔 동안은 다시 볼 수 있다."""
    data = _load()
    entry = {"when": (when or dt.datetime.now()).strftime("%Y-%m-%d %H:%M"), "folder": str(folder),
             "title": title, "heading": heading, "report": report}
    key = _key(folder)
    data[key] = ([entry] + [e for e in data.get(key, []) if isinstance(e, dict)])[:KEEP_PER_FOLDER]
    if len(data) > KEEP_FOLDERS:
        newest = sorted(data, key=lambda k: max((e.get("when", "") for e in data[k] if isinstance(e, dict)), default=""), reverse=True)
        for old in newest[KEEP_FOLDERS:]:
            data.pop(old, None)
    target = path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, target)
    except OSError as error:
        return str(error).splitlines()[0] if str(error) else type(error).__name__
    return ""


def entries(folder: str) -> list[dict]:
    """그 폴더의 결과 — 새것부터. 항목은 {'when', 'title', 'heading', 'report'}."""
    if not folder:
        return []
    return [e for e in _load().get(_key(folder), []) if isinstance(e, dict) and isinstance(e.get("report"), dict)]
