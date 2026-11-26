"""출장증빙 — 앱이 글자로 못 읽는 증빙(영수증 사진 · 결제 화면 캡처 · 영수증 그림이 든 PDF)을 AI 로 읽는다.

담당자 2026-11-16: KTX 영수증이 그림으로 든 대중교통 증빙 PDF 에 "결제금액 및 일자, 이동편, 출발지 목적지 정보 다있음" 인데 앱이 '금액 없음' ·
'확인 필요' 로 칠했다 — 그 PDF 는 글자가 제목 한 줄뿐이고 영수증은 그림이라 pypdf 로는 읽을 것이 없었다. 카드청구(claims/card_ai.py)처럼
회의록 생성과 같은 Claude Code CLI(이 PC 에 로그인된 구독)로 읽는다.

- 어느 증빙만: 표에서 그 항목에 꼭 있어야 할 칸이 빈 증빙(체류: 가맹점 지역 · 일자, 대중교통: 일자 · 금액 · 이동편 · 출발지 · 목적지,
  하이패스: 이용일자 · 금액, 숙박: 입실일 · 금액). 기타 증빙은 읽지 않는다. 화면이 고른다(ui/pages/travel.py — _ai_pending).
- 비운 칸만 채운다: 파일 이름 · PDF 글자 · 사람이 적은 값이 먼저다(체류 증빙 이름 끝의 번호는 일자가 아니다 — 일자는 영수증에서).
- 다시 읽지 않게: 결과를 `_출장AI읽기.json` 에 파일 경로 · 서명(크기 · 고친 때)과 함께 남긴다. 그 파일에는 가맹점 주소 · 역 이름이 들어 있어
  저장소 · 배포 · CI 에서 뺀다(.gitignore · NEVER_PACK · ci.yml).
- 기록에는 값을 남기지 않는다 — 몇 개를 읽었고 무엇을 찾았는지(일자 · 금액 있음)만.

Qt 없음. 부르는 곳: ui/travel_ai_worker.py(뒤 스레드) · ui/pages/travel.py(lookup 으로 캐시만 읽는다).
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import os
import re
import shutil
import subprocess
import tempfile
import traceback
from pathlib import Path

from .. import settings
from ..minutes.backends.claude_cli import _run_kwargs, claude_command, find_claude
from ..minutes.errors import BackendError, _extract_json, _failure_reason
from ..minutes.logbook import log
from ..minutes.textfile import _read_text
from . import model

TIMEOUT_SEC = 900
CACHE_NAME = "_출장AI읽기.json"
CACHE_LIMIT = 600
READ_V = 4                   # 3: 한 그림에 나란히 든 매출전표도 한 장씩(2026-11-24) — 그 전에 한 장으로 읽은 그림이 둘로 오려지면 다시 읽는다(older)
                             # 4: 나란히 붙여 스캔한 종이 영수증은 높이가 달라도 왼쪽부터(2026-11-26) — 좁은 틈으로도 오리게 되어 차례가 그림과 맞아야 한다
ORDER_V = 4                  # 2: 여러 장이면 보이는 차례로(하이패스 영수증 상자와 짝지으려고, 2026-11-16) · 4: 위 — 그 전에 읽은 여러 장 파일은 다시 읽는다
BATCH = 6                    # 한 번에 읽힐 파일 수 — 많으면 한 번 실패에 다 잃고, 적으면 CLI 를 띄우는 데 시간이 든다
MODES = ("열차", "고속버스", "시외버스", "시내버스", "택시", "지하철", "항공")
KIND_TEXT = {model.STAY: "체류 영수증(출장지에 머문 증빙 — 카드 승인전표 · 결제 화면 · 영수증)",
             model.PUBLIC: "대중교통 승차권 · 영수증(열차 · 버스 · 택시 · 항공)",
             model.TOLL: "하이패스 · 고속도로 통행료 이용 내역",
             model.LODGING: "숙박 영수증"}


def available() -> bool:
    return bool(find_claude())


def cache_path() -> Path:
    return settings.data_dir() / CACHE_NAME


def file_key(path) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def signature(path) -> str:
    try:
        stat = os.stat(path)
    except OSError:
        return "?"
    return f"{stat.st_size}|{int(stat.st_mtime)}"


def _load() -> dict:
    try:
        data = json.loads(cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    items = data.get("items") if isinstance(data, dict) else None
    return items if isinstance(items, dict) else {}


def _save(items: dict) -> None:
    if len(items) > CACHE_LIMIT:
        for old in sorted(items, key=lambda k: str(items[k].get("at", "")))[:len(items) - CACHE_LIMIT]:
            items.pop(old, None)
    path = cache_path()
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"v": 1, "items": items}, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def lookup(path) -> dict | None:
    """그 파일을 전에 AI 로 읽었고 파일이 그대로면 그 결과(빠르다)."""
    entry = _load().get(file_key(path))
    if not isinstance(entry, dict) or entry.get("sig") != signature(path):
        return None
    data = entry.get("data")
    if not isinstance(data, dict):
        return None
    if entry.get("v", 1) < ORDER_V and len(data.get("receipts") or []) > 1:
        return None                                   # 영수증 차례를 정하지 않고 읽은 것 — 상자와 짝지을 수 없다
    return data


def older(path, version: int = READ_V) -> bool:
    """그 파일을 version 전의 판으로 읽었는가(파일이 그대로일 때만) — 화면이 다시 읽힐지 정한다."""
    entry = _load().get(file_key(path))
    return isinstance(entry, dict) and entry.get("sig") == signature(path) and entry.get("v", 1) < version


def remember(results: dict) -> None:
    """results = {경로: 읽은 것} — 한 번에 남긴다."""
    items = _load()
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    for path, data in results.items():
        items[file_key(path)] = {"sig": signature(path), "at": now, "v": READ_V, "data": data}
    _save(items)


# ── 읽기 ───────────────────────────────────────────────────────────────
def build_prompt(files: list[tuple[str, str]], json_path: str) -> str:
    """files = [(파일 경로, 항목)]."""
    names = "\n".join(f"- {path}  ← {KIND_TEXT.get(kind, kind)}" for path, kind in files)
    return (
        "당신은 대학 사업단의 출장비 증빙을 정리하는 도구입니다.\n"
        "아래 파일만 읽으세요(PDF 와 그림은 직접 보고, PDF 안에 붙은 영수증 그림도 읽으세요). 다른 파일은 보지 마세요.\n"
        + names + "\n"
        "결과를 정확히 '" + json_path + "' 경로에 UTF-8 JSON 파일로 저장하세요(Write 도구 사용).\n"
        "JSON 스키마:\n"
        "{\n"
        '  "files": [{"file": "위 목록의 파일 경로 그대로", "receipts": [{"date": "YYYY-MM-DD", "amount": 29800, '
        '"mode": "열차", "origin": "출발역 · 출발지", "goal": "도착역 · 목적지", "address": "가맹점 · 숙소 주소", '
        '"approvalNo": "승인번호(숫자)", "nights": 1}]}]\n'
        "}\n"
        "[규칙]\n"
        "- 파일마다 그 안에 보이는 영수증 · 승차권 · 이용 내역을 receipts 에 하나씩 담으세요. 같은 결제를 두 번 담지 마세요. 영수증이 없으면 [] 입니다.\n"
        "- 한 그림 · 한 쪽에 영수증 · 매출전표 · 승차권이 나란히(또는 위아래로) 여러 장 있으면 한 장씩 따로 담으세요 — 일자가 다르면 꼭 따로입니다.\n"
        "- 한 파일에 영수증이 여럿이면 보이는 차례로 담으세요 — 위에서 아래로, 같은 줄은 왼쪽에서 오른쪽으로(PDF 는 쪽 차례). 날짜 · 금액 차례로 바꾸지 마세요.\n"
        "  세로로 긴 종이 영수증을 옆으로 나란히 붙여 스캔한 것은 영수증마다 위 끝 높이가 달라도 한 줄입니다 — 왼쪽 영수증부터 오른쪽으로 담으세요.\n"
        "- date 는 실제로 이용한 날입니다 — 승차권은 승차(출발)일, 체류 · 하이패스는 거래 · 이용일, 숙박은 입실일. 예매 · 승인 · 발행 · 인쇄일이 아닙니다.\n"
        "- amount 는 실제로 결제한 금액(원, 숫자만)입니다. 할인 전 운임 · 부가세 · 공급가가 아닙니다.\n"
        "- mode 는 대중교통만: " + " · ".join(MODES) + " 중 하나(KTX · SRT · ITX · 무궁화는 열차). 그 밖은 빈 문자열.\n"
        "- origin · goal 은 대중교통만: 승차권에 적힌 출발 · 도착 역(터미널) 이름 그대로. 그 밖은 빈 문자열.\n"
        "- address 는 체류 · 숙박 영수증의 가맹점(숙소) 주소 그대로. 보이지 않으면 빈 문자열.\n"
        "- nights 는 숙박만: 묵은 박 수. 그 밖은 null.\n"
        "- 보이지 않는 값은 빈 문자열(숫자는 null)로 두세요. 지어내지 마세요.\n"
        "위 JSON 파일 하나만 저장하고 다른 파일은 고치거나 지우지 마세요.\n"
    )


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def _int(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) if value > 0 else None
    number = model.amount_of(_text(value))
    return number if number and number > 0 else None


def clean_receipt(raw: dict) -> dict:
    out = {key: _text(raw.get(key))[:120] for key in ("date", "mode", "origin", "goal", "address")}
    day = model.guess_day(out["date"], dt.date.today().year) if out["date"] else None
    out["date"] = day.isoformat() if day else ""
    mode = out["mode"]
    out["mode"] = mode if mode in MODES else (model.mode_of(mode) or "")
    out["amount"] = _int(raw.get("amount"))
    nights = _int(raw.get("nights"))
    out["nights"] = nights if nights and nights <= 60 else None
    digits = re.sub(r"\D", "", _text(raw.get("approvalNo")))
    out["approvalNo"] = digits if len(digits) >= 6 else ""
    return out


def clean(data: dict, files: list[str]) -> dict:
    """AI 결과 → {경로: {"receipts": [...]}} — 목록에 없는 파일은 버린다(경로 · 파일 이름으로 맞춤)."""
    by_key = {file_key(p): p for p in files}
    by_name = {}
    for p in files:
        by_name.setdefault(Path(p).name, []).append(p)
    out: dict = {}
    for raw in data.get("files") or []:
        if not isinstance(raw, dict):
            continue
        name = _text(raw.get("file"))
        if not name:
            continue
        path = by_key.get(file_key(name))
        if path is None:
            same = by_name.get(Path(name).name, [])
            path = same[0] if len(same) == 1 else None      # 이름만 적었으면 — 같은 이름이 둘이면 어느 것인지 모른다
        if path is None:
            continue
        receipts = [clean_receipt(r) for r in raw.get("receipts") or [] if isinstance(r, dict)]
        out[path] = {"receipts": receipts}
    for path in files:
        out.setdefault(path, {"receipts": []})          # 못 읽었다고 답했거나 빠뜨린 파일도 남긴다(다시 읽지 않게)
    return out


def summary(kind: str, data: dict) -> dict:
    """한 파일의 영수증들 → 표 한 줄에 넣을 값. 여럿이면 금액은 더하고, 일자 · 이동편은 모두 같을 때만, 출발지는 처음 · 목적지는 마지막."""
    receipts = data.get("receipts") or []
    if not receipts:
        return {}
    days = {r["date"] for r in receipts if r.get("date")}
    amounts = [r["amount"] for r in receipts if r.get("amount")]
    modes = {r["mode"] for r in receipts if r.get("mode")}
    out = {"date": next(iter(days)) if len(days) == 1 else "",
           "amount": sum(amounts) if amounts and len(amounts) == len(receipts) else (amounts[0] if len(amounts) == 1 and len(receipts) == 1 else None),
           "mode": next(iter(modes)) if len(modes) == 1 else "",
           "origin": receipts[0].get("origin", ""), "goal": receipts[-1].get("goal", ""),
           "address": next((r["address"] for r in receipts if r.get("address")), ""),
           "nights": sum(r["nights"] for r in receipts if r.get("nights")) or None,
           "approvalNo": receipts[0].get("approvalNo", "") if len(receipts) == 1 else "",
           "count": len(receipts)}
    if kind == model.LODGING and len(days) > 1:
        out["date"] = min(days)                           # 숙박이 둘이면 첫 입실일
    if kind in (model.TOLL, model.PUBLIC, model.STAY) and len(receipts) > 1:
        # 한 파일의 영수증 여러 장 — 화면이 영수증마다 줄로 나눈다(receipts, 담당자 2026-11-16 하이패스 · 2026-11-23 KTX 영수증 둘 "일자별로 구분해주세요").
        # 못 나누면(사람이 일자를 적었음 · 같은 날인데 그림을 못 오림) 한 줄 — 하이패스는 첫 이용일 · 합계(days 는 말풍선에)
        out["receipts"] = [{key: r.get(key) for key in ("date", "amount", "mode", "origin", "goal", "address", "approvalNo")} for r in receipts]
        out["days"] = sorted(days)
        if kind == model.TOLL and len(days) > 1:
            out["date"] = min(days)
    return out


def found_text(results: dict) -> str:
    """기록에 남길 한 줄 — 값은 적지 않는다."""
    receipts = sum(len(d.get("receipts") or []) for d in results.values())
    dated = sum(1 for d in results.values() for r in d.get("receipts") or [] if r.get("date"))
    paid = sum(1 for d in results.values() for r in d.get("receipts") or [] if r.get("amount"))
    return f"파일 {len(results)}개 · 영수증 {receipts}장(일자 있음 {dated} · 금액 있음 {paid})"


def read(files: list[tuple[str, str]], model_name: str | None = None) -> dict:
    """files = [(경로, 항목)] 를 Claude Code 로 읽는다. 실패하면 BackendError(kind 'login' · 'limit' · 'balance' 면 남은 것도 그만)."""
    exe = find_claude()
    if not exe:
        raise BackendError("claude 명령을 찾을 수 없음")
    if not files:
        return {}
    model_name = settings.load().minutes_model if model_name is None else model_name
    folder = os.path.commonpath([os.path.dirname(p) for p, _ in files]) if len(files) > 1 else os.path.dirname(files[0][0])
    tmp = tempfile.mkdtemp(prefix="travel_")
    json_path = os.path.join(tmp, "travel.json")
    cli_args = [
        "-p", build_prompt(files, json_path),
        "--output-format", "json",
        "--permission-mode", "acceptEdits",
        "--allowedTools", "Read,Glob,Grep,Write,Edit,Bash,PowerShell",
        "--add-dir", tmp,
    ]
    if model_name:
        cli_args += ["--model", model_name]
    try:
        r = subprocess.run(claude_command(exe, cli_args), **_run_kwargs(folder, TIMEOUT_SEC))
    except FileNotFoundError:
        shutil.rmtree(tmp, ignore_errors=True)
        raise BackendError("claude 실행 파일을 열 수 없음")
    except subprocess.TimeoutExpired:
        shutil.rmtree(tmp, ignore_errors=True)
        raise BackendError("시간 초과")
    except Exception as error:  # noqa: BLE001
        shutil.rmtree(tmp, ignore_errors=True)
        log("출장 AI 읽기 실행 오류\n" + traceback.format_exc())
        raise BackendError("실행 오류: " + str(error)[:60])
    data = None
    if not os.path.exists(json_path):
        found = glob.glob(os.path.join(tmp, "*.json"))
        json_path = found[0] if found else ""
    if json_path and os.path.exists(json_path):
        try:
            text = _read_text(json_path)
        except Exception:  # noqa: BLE001
            text = ""
        try:
            data = json.loads(text)
        except ValueError:
            data = _extract_json(text)
    if data is None:
        outer = _extract_json(r.stdout)
        if isinstance(outer, dict) and outer.get("result"):
            data = _extract_json(str(outer.get("result")))
    shutil.rmtree(tmp, ignore_errors=True)
    if not isinstance(data, dict):
        # stdout 에는 영수증 글(가맹점 · 주소)이 섞일 수 있어 남기지 않는다 — 까닭 한 줄과 stderr 앞부분만
        log("출장 AI 읽기 결과 없음: rc=%s · %s\nstderr=%s" % (r.returncode, _failure_reason(r), (r.stderr or "")[:600]))
        raise BackendError(_failure_reason(r))
    return clean(data, [p for p, _ in files])


def batches(files: list[tuple[str, str]]) -> list[list[tuple[str, str]]]:
    return [files[i:i + BATCH] for i in range(0, len(files), BATCH)]
