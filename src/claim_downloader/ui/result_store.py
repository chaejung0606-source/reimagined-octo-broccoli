"""일반청구 결과 다시 보기 — 최근 결과 창 열 개의 내용(_청구결과.json).

담당자 2026-11-11(카드청구 결과 그림): "일반청구 결과내용이 새창에 뜨는데 이걸 한번 닫으면 다시 내용을 확인할 수 없습니다" →
같은 날 "결과내용을 목록을 저장하고 다시 확인할 수 있도록 해주세요. 홈화면에 결과확인을 이어서 작업하기 오른쪽에 목록을 넣고 목록중 한건을
클릭하면 새탭에서 결과내용 확인하기. 최근 10건만 저장".
결과 창(카드청구 · 장학금 · 혁신인재지원금 · 첨부만 다시 올리기)을 띄울 때마다 남기고 — 모든 폴더를 합쳐 **최근 열 건만** — 홈의 '결과 확인' 목록과
일반청구 ④ 의 [결과 다시 보기](그 폴더의 것만)가 다시 띄운다. 앱을 다시 켜도(F5 새로고침 포함) 남는다.
학생 이름 · 금액 · 가맹점이 들어 있어 사용자 폴더에만 둔다(.gitignore · NEVER_PACK · CI).

여기는 JSON 만 다룬다(Qt 없음) — 창의 내용을 JSON 으로 바꾸는 것은 report_dialog.report_to_data · report_from_data.
"""
from __future__ import annotations

import datetime as dt
import json
import os

from .. import settings

NAME = "_청구결과.json"
KEEP = 10                    # 모든 폴더를 합쳐 최근 열 건(담당자 2026-11-11 "최근 10건만 저장")

_cache: list | None = None   # 읽은 것 · 쓰지 못한 것도(쓰기가 막혀도 앱을 켜 둔 동안은 다시 본다)
_cache_path = None           # 그 캐시를 읽은 파일 — 사용자 폴더가 바뀌면(테스트) 다시 읽는다
_serial = 0                  # 같은 순간에 남긴 결과도 id 가 다르게


def path():
    return settings.data_dir() / NAME


def _key(folder: str) -> str:
    return os.path.normcase(os.path.abspath(str(folder)))


def _from_file(data) -> list[dict]:
    """파일 → 새것부터의 목록. 옛 판(2026-11-11 낮 — 폴더마다 다섯 {폴더: [결과…]})도 읽어 합친다."""
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        items = data["items"]
    elif isinstance(data, dict):
        items = [e for entries in data.values() if isinstance(entries, list) for e in entries]
    else:
        items = []
    items = [e for e in items if isinstance(e, dict) and isinstance(e.get("report"), dict)]
    for n, entry in enumerate(items):
        entry.setdefault("id", f"{entry.get('when', '')}#{n}")
    items.sort(key=lambda e: str(e.get("at") or e.get("when") or ""), reverse=True)
    return items[:KEEP]


def _load() -> list[dict]:
    global _cache, _cache_path
    if _cache is None or _cache_path != path():
        _cache_path = path()
        try:
            _cache = _from_file(json.loads(path().read_text(encoding="utf-8")))
        except (OSError, ValueError):
            _cache = []
    return _cache


def forget_cache() -> None:
    """테스트 · 사용자 폴더를 바꿨을 때 — 다음에 파일을 다시 읽는다."""
    global _cache
    _cache = None


def save(folder: str, title: str, heading: str, report: dict, when: dt.datetime | None = None) -> str:
    """결과 창 하나를 남긴다(가장 오래된 것부터 지워 열 건). 돌려주는 것은 못 쓴 까닭('' 이면 씀) — 못 써도 앱을 켜 둔 동안은 다시 볼 수 있다."""
    global _cache, _serial
    moment = when or dt.datetime.now()
    _serial += 1
    entry = {"id": f"{moment:%Y%m%d-%H%M%S}-{_serial}", "at": moment.strftime("%Y-%m-%d %H:%M:%S"),
             "when": moment.strftime("%Y-%m-%d %H:%M"), "folder": str(folder), "title": title, "heading": heading, "report": report}
    items = [entry] + [e for e in _load() if e.get("id") != entry["id"]]
    items.sort(key=lambda e: str(e.get("at") or e.get("when") or ""), reverse=True)
    _cache = items[:KEEP]
    target = path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(json.dumps({"v": 2, "items": _cache}, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, target)
    except OSError as error:
        return str(error).splitlines()[0] if str(error) else type(error).__name__
    return ""


def recent() -> list[dict]:
    """모든 결과 — 새것부터(열 건까지). 항목은 {'id', 'when', 'folder', 'title', 'heading', 'report'}. 홈의 '결과 확인' 목록."""
    return list(_load())


def entries(folder: str) -> list[dict]:
    """그 폴더의 결과 — 새것부터. 일반청구 ④ 의 [결과 다시 보기]."""
    if not folder:
        return []
    key = _key(folder)
    return [e for e in _load() if _key(e.get("folder", "")) == key]


def find(result_id: str) -> dict | None:
    return next((e for e in _load() if e.get("id") == result_id), None)
