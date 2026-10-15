"""채운 기록 — 같은 지출 폴더를 두 번 채우지 않게 경고하는 근거. ~/.claim-downloader/_청구입력기록.json

기록은 '앱이 ERP 에 채웠다(명단 청구는 임시저장했다)' 까지다. 신청은 사람이 하고, 사람이 ERP 에서 지웠을 수도 있으므로
실제로 청구가 남아 있는지는 모른다 — 그래서 막지 않고 묻기만 한다.

폴더마다 마지막 기록(when · amount · summary · req_cnt) 위에, 넣을 때마다의 기록(runs)과 명단 청구에서 임시저장한 사람(saved)을
쌓는다(2026-10-14 점검 뒤 담당자 요청 '추가하면 좋을 기능' — 중복 임시저장 알림). 전에는 마지막 기록 하나만 남아,
같은 폴더를 다른 종류로 다시 넣거나(결의번호 324: 장학금 → 혁신인재지원금) 앱을 껐다 켜서 이미 넣은 학생을 다시 넣어도
'언제 넣었다' 한 줄만 보였다.
"""
from __future__ import annotations

import json
import os
import re
import time

from .. import settings

MAX_RUNS = 20


def _load() -> dict:
    try:
        data = json.loads(settings.claim_record_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(records: dict) -> None:
    path = settings.claim_record_path()
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)                  # 쓰다가 꺼져도 기록 파일이 반쯤 남지 않게


def _key(folder) -> str:
    return os.path.normcase(os.path.abspath(str(folder)))


def person_key(name: str, student_no: str = "", course: str = "") -> str:
    """명단의 한 줄 — 같은 학생이라도 강좌(TA)가 다르면 다른 줄이다."""
    return "|".join(re.sub(r"\s+", "", str(v or "")) for v in (name, student_no, course))


def previous(folder) -> dict | None:
    """이 폴더를 전에 채운 적이 있으면 그 기록 {when, amount, summary, req_cnt, kind, runs, saved}."""
    entry = _load().get(_key(folder))
    return entry if isinstance(entry, dict) else None


def remember(folder, data: dict, kind: str = "", people: list[dict] | None = None) -> None:
    """people: 이번에 임시저장한 사람 [{name, no, course, row}] — 명단 청구만."""
    records = _load()
    key = _key(folder)
    old = records.get(key) if isinstance(records.get(key), dict) else {}
    now = time.strftime("%Y-%m-%d %H:%M")
    entry = {
        "when": now,
        "amount": data.get("amount"),
        "summary": data.get("summary", ""),
        "req_cnt": data.get("req_cnt", ""),          # 장학금 등 — 그 폴더를 넣은 ERP 청구서의 결의번호
        "kind": kind or old.get("kind", ""),
    }
    runs = [r for r in (old.get("runs") or []) if isinstance(r, dict)]
    if not runs and old.get("when"):
        # 옛 판의 기록(마지막 하나뿐)도 이력의 첫 줄로 남긴다
        runs.append({"when": old.get("when"), "kind": old.get("kind", ""), "req_cnt": old.get("req_cnt", ""),
                     "summary": old.get("summary", ""), "amount": old.get("amount")})
    runs.append({"when": now, "kind": entry["kind"], "req_cnt": entry["req_cnt"], "summary": entry["summary"],
                 "amount": entry["amount"], "count": len(people) if people is not None else None})
    entry["runs"] = runs[-MAX_RUNS:]
    saved = {s.get("key"): s for s in (old.get("saved") or []) if isinstance(s, dict) and s.get("key")}
    for person in people or []:
        k = person_key(person.get("name", ""), person.get("no", ""), person.get("course", ""))
        saved[k] = {"key": k, "name": person.get("name", ""), "when": now, "kind": entry["kind"], "req_cnt": entry["req_cnt"]}
    if saved:
        entry["saved"] = list(saved.values())
    records[key] = entry
    _write(records)


def already_saved(folder, people) -> list[dict]:
    """이번에 넣으려는 사람(roster.Person 들) 중 전에 이 폴더에서 임시저장한 사람의 기록."""
    entry = previous(folder) or {}
    saved = {s.get("key"): s for s in (entry.get("saved") or []) if isinstance(s, dict)}
    out = []
    for p in people:
        hit = saved.get(person_key(p.name, p.student_no, p.course))
        if hit:
            out.append(hit)
    return out


def same_summary_elsewhere(folder, summary: str) -> list[tuple[str, dict]]:
    """다른 폴더에서 같은 대표적요로 넣은 기록 — 폴더를 복사해 두고 둘 다 넣는 것을 막으려고."""
    want = re.sub(r"\s+", "", summary or "")
    if not want:
        return []
    me = _key(folder)
    out = []
    for key, entry in _load().items():
        if key == me or not isinstance(entry, dict):
            continue
        if re.sub(r"\s+", "", re.sub(r"\s*\(\d+명\)$", "", str(entry.get("summary", "")))) == want:
            out.append((key, entry))
    return out


def history_lines(entry: dict | None, names: dict[str, str] | None = None) -> list[str]:
    """넣은 이력 — '2026-10-14 19:22 장학금 · 결의번호 324 · 6명'. names: 종류 키 → 화면 이름."""
    if not entry:
        return []
    runs = [r for r in (entry.get("runs") or []) if isinstance(r, dict)] or [entry]
    out = []
    for r in runs[-6:]:
        kind = (names or {}).get(r.get("kind", ""), r.get("kind", ""))
        bits = [str(r.get("when", "?"))] + ([kind] if kind else [])
        if r.get("req_cnt"):
            bits.append(f"결의번호 {r['req_cnt']}")
        if r.get("count") is not None:
            bits.append(f"{r['count']}명")
        elif r.get("summary"):
            bits.append(str(r["summary"])[:40])
        out.append(" · ".join(bits))
    if len(runs) > 6:
        out.insert(0, f"(앞의 {len(runs) - 6}번은 줄임)")
    return out
