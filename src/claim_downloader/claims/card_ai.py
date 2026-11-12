"""카드청구 — 앱이 글자로 못 읽는 증빙(영수증 사진 · 학생이 낸 회의록 PDF · 한글 파일에 붙은 영수증 그림)을 AI 로 읽는다.

담당자 2026-11-11: "이전에는 사진으로 한글파일에 첨부된 영수증 읽었는데 왜 못읽는다고 하나요" — 그때 사진을 읽은 것은 회의록 생성(13절)의
AI 였고, 카드청구(card.py)는 그 회의록(.hwpx)의 '금액' 칸 글자만 읽었다. 결제 건 폴더에 영수증 JPG 와 학생이 낸 회의록 PDF 만 있으면
읽을 글자가 없어 '금액을 모름' 으로 막혔다 → 담당자가 'AI 로 읽기' 를 골랐다.

- 어느 결제 건만: 금액을 모르거나 · 회의비(17)인데 회의록에서 시각 · 장소 · 목적 · 내용 · 참석자를 다 못 읽은 것(`needs`). 이미 저장한 건 · 읽을 파일이
  없는 건은 하지 않는다. 폴더 이름의 금액 · 영수증 PDF 글자 · 회의록 생성의 .hwpx 가 먼저다 — AI 는 그것들이 비운 자리만 채운다(card.read_item).
- 무엇으로: 회의록 생성과 같은 Claude Code CLI(이 PC 에 로그인된 구독) — 실행 함수는 minutes/backends/claude_cli 것을 그대로 쓰고 프롬프트만 다르다.
  결제 건 폴더의 파일 이름을 하나하나 적어 넘기고('기타' 폴더는 넣지 않는다 — card._files_under) 그것만 읽게 한다.
- 다시 읽지 않게: 결과를 `_카드AI읽기.json` 에 결제 건 폴더 · 파일 서명(이름 · 크기 · 고친 때)과 함께 남긴다. 파일을 바꾸거나 더하면 다시 읽는다.
  그 파일에는 가맹점 · 참석자 이름이 들어 있어 저장소 · 배포 · CI 에서 뺀다(.gitignore · NEVER_PACK · ci.yml).
- 기록에는 이름 · 금액 같은 값을 남기지 않는다 — 몇 건을 읽었는지 · 무엇을 찾았는지(금액 있음 · 회의록 있음)만.

Qt 없음. 부르는 곳: ui/card_ai_worker.py(뒤 스레드) · ui/pages/claim.py(_load_card — lookup 으로 캐시만 읽는다).
"""
from __future__ import annotations

import datetime as dt
import glob
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import traceback

from .. import settings
from ..minutes.backends.claude_cli import _run_kwargs, claude_command, find_claude
from ..minutes.errors import BackendError, _extract_json, _failure_reason
from ..minutes.logbook import log
from ..minutes.textfile import _read_text
from . import card as card_mod
from . import idnums
from .schema import parse_amount

TIMEOUT_SEC = 900           # 결제 건 하나 — 영수증 몇 장 · 회의록 하나라 회의록 생성(1,800초)보다 짧게
CACHE_NAME = "_카드AI읽기.json"
CACHE_LIMIT = 400           # 남겨 둘 결제 건 수 — 넘으면 오래된 것부터
# AI 가 볼 수 있는 파일 — 엑셀(물품 표)은 card.read_goods 가 읽는다
MEDIA_SUFFIXES = (".pdf", ".jpg", ".jpeg", ".png", ".heic", ".gif", ".bmp", ".webp", ".tif", ".tiff", ".hwpx", ".hwp", ".docx")
MEETING_KEYS = ("start", "end", "place", "agenda", "content", "attendees")


def cache_path():
    return settings.data_dir() / CACHE_NAME


def media_files(files: list[str]) -> list[str]:
    return [p for p in files if p.lower().endswith(MEDIA_SUFFIXES)]


def signature(folder: str, files: list[str]) -> str:
    """결제 건 폴더의 파일 서명 — 이름 · 크기 · 고친 때. 하나라도 바뀌면 다시 읽는다."""
    parts = []
    for path in sorted(files):
        try:
            stat = os.stat(path)
            parts.append(f"{os.path.relpath(path, folder)}|{stat.st_size}|{int(stat.st_mtime)}")
        except OSError:
            parts.append(f"{os.path.relpath(path, folder)}|?")
    return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()


def folder_key(folder: str) -> str:
    return os.path.normcase(os.path.normpath(folder))


def _load() -> dict:
    try:
        data = json.loads(cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    items = data.get("items") if isinstance(data, dict) else None
    return items if isinstance(items, dict) else {}


def lookup(folder: str, files: list[str]) -> dict | None:
    """그 결제 건 폴더를 전에 AI 로 읽었고 파일이 그대로면 그 결과. card.load_job(ai_lookup=…) 이 부른다 — 빠르다(파일 하나 읽기)."""
    entry = _load().get(folder_key(folder))
    if not isinstance(entry, dict) or entry.get("sig") != signature(folder, files):
        return None
    data = entry.get("data")
    if not isinstance(data, dict) or before_numbers(data):
        return None
    return data


def before_numbers(data: dict) -> bool:
    """참석자의 학번 · 사번(no)을 읽기 전 판(2026-11-11 전)의 결과 — 다시 읽는다(담당자 2026-11-11 "학번으로 검색해야 정확합니다":
    그 판으로 읽은 학생 회의록은 참석자 이름만 남아 ERP 에서 이름으로 찾았다). 참석자가 없는 결과는 그대로 쓴다."""
    meeting = data.get("meeting")
    people = meeting.get("attendees") if isinstance(meeting, dict) else None
    return bool(people) and all(isinstance(p, dict) and "no" not in p for p in people)


def remember(folder: str, files: list[str], data: dict) -> None:
    items = _load()
    items[folder_key(folder)] = {"sig": signature(folder, files), "at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "data": data}
    if len(items) > CACHE_LIMIT:
        for old in sorted(items, key=lambda k: str(items[k].get("at", "")))[:len(items) - CACHE_LIMIT]:
            items.pop(old, None)
    path = cache_path()
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"v": 1, "items": items}, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def forget(folder: str) -> None:
    items = _load()
    if items.pop(folder_key(folder), None) is not None:
        path = cache_path()
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps({"v": 1, "items": items}, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)


# ── 어느 결제 건을 ──────────────────────────────────────────────────────
def meeting_gaps(item: card_mod.CardItem) -> list[str]:
    """회의비 — ERP 회의록등록 창에 넣을 것 중 회의록에서 못 읽은 것."""
    m = item.meeting
    if m is None:
        return list(MEETING_KEYS)
    return [key for key in MEETING_KEYS if not getattr(m, key)]


def needs(item: card_mod.CardItem) -> list[str]:
    """AI 로 읽을 까닭 — 비면 읽지 않는다."""
    if item.status == "saved" or not media_files(item.files):
        return []
    out = []
    if item.amount is None:
        out.append("금액")
    if item.req_div == "17" and meeting_gaps(item):
        out.append("회의 내용")
    return out


def pending(job: card_mod.CardJob) -> list[card_mod.CardItem]:
    """AI 로 읽을 결제 건 — 읽을 까닭이 있고 아직 읽지 않은(캐시에 없는) 것."""
    return [item for item in job.items if not item.ai_read and needs(item)]


# ── 읽기 ───────────────────────────────────────────────────────────────
def build_prompt(folder: str, files: list[str], json_path: str) -> str:
    names = "\n".join("- " + os.path.relpath(p, folder) for p in files)
    return (
        "당신은 대학 사업단의 법인카드 청구를 돕는 도구입니다.\n"
        "카드 사용 1건의 증빙 폴더 '" + folder + "' 에서 아래 파일만 읽으세요. 다른 파일과 '기타' 폴더는 보지 마세요.\n"
        + names + "\n"
        "PDF 와 이미지(영수증 · 카드전표 · 결제 화면 사진)는 직접 읽으세요.\n"
        ".hwpx · .docx 는 ZIP 압축 파일이므로 Bash 도구에서 실제로 동작하는 방법(python, powershell 등)으로 풀어 본문 글"
        "(.hwpx 는 Contents/section0.xml, .docx 는 word/document.xml)을 읽고, 안에 붙은 그림(.hwpx 는 BinData, .docx 는 word/media)에 "
        "영수증이 있으면 그 그림도 읽으세요. .hwp 는 읽지 못하면 notes 에 '한글(.hwp) 파일은 PDF로 저장해 다시 넣어주세요'라고 적으세요.\n"
        "결과를 정확히 '" + json_path + "' 경로에 UTF-8 JSON 파일로 저장하세요(Write 도구 사용).\n"
        "JSON 스키마:\n"
        "{\n"
        '  "receipts": [{"file": "영수증이 든 파일 이름", "amount": 45000, "date": "YYYY-MM-DD", "time": "HH:MM", '
        '"merchant": "가맹점 상호", "address": "가맹점 주소", "cardLast4": "카드번호 끝 4자리", "approvalNo": "승인번호", '
        '"items": "주문 품목 요약(예: 아메리카노 4, 케이크 2)"}],\n'
        '  "meeting": {"file": "회의록 파일 이름", "date": "YYYY-MM-DD", "start": "HH:MM", "end": "HH:MM", "place": "회의장소", '
        '"agenda": "회의 안건(목적) 한 줄", "content": ["회의내용 1문단", "2문단"], "attendees": [{"org": "소속", "name": "이름", "no": "학번 또는 사번"}]},\n'
        '  "snack": true,\n'
        '  "notes": "확인이 필요한 점(없으면 빈 문자열)"\n'
        "}\n"
        "[규칙]\n"
        "- receipts 는 이 결제의 카드 영수증 · 카드매출전표 · 결제 화면만 담으세요. 같은 결제를 찍은 증빙이 여럿이면 하나로 담으세요. "
        "amount 는 실제로 결제된 합계 금액(원, 숫자만)입니다. 보이지 않는 값은 빈 문자열로 두세요. 영수증이 없으면 [] 입니다.\n"
        "- meeting 은 회의록(회의 결과 보고 · 회의 기록)에 적힌 것만 옮기세요. 지어내지 마세요. 회의록이 없으면 null 입니다.\n"
        "  start · end 는 회의 시작 · 끝 시각(24시간 HH:MM)입니다. 회의록에 시각이 하나뿐이면 그것이 start 이고 end 는 빈 문자열로 두세요. place 는 회의를 한 곳입니다(회의록의 회의장소 — 결제한 식당 · 카페가 아닙니다).\n"
        "  content 는 회의록의 논의 내용을 2~4문단으로 정리합니다(합쳐서 공백 빼고 20자 이상). 식사 · 메뉴 · 결제 · 영수증 이야기는 넣지 마세요.\n"
        "  attendees 는 회의록 · 서명부에서 이름을 확인할 수 있는 사람만, 소속은 적힌 그대로(없으면 빈 문자열) 담으세요. "
        "no 는 그 사람의 학번 · 사번(숫자만)입니다 — 이름 옆이 아니어도 같은 줄(표의 다른 열 · 비고 · 서명부)에 적혀 있으면 읽고, "
        "적혀 있지 않거나 누구 것인지 분명하지 않으면 빈 문자열입니다 — 지어내지 마세요.\n"
        "- snack 은 이 결제가 식사가 아니라 다과(커피 · 음료 · 빵 · 과자)면 true, 식사면 false, 모르면 null 입니다.\n"
        "위 JSON 파일 하나만 저장하고 폴더 안의 파일은 고치거나 지우지 마세요. 반드시 한국어로 작성하세요.\n"
    )


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def clean(data: dict) -> dict:
    """AI 결과를 앱이 쓰는 모양으로 — 금액은 정수, 글은 글, 모르는 값은 버린다."""
    out: dict = {"receipts": [], "meeting": None, "snack": None, "notes": _text(data.get("notes"))[:400]}
    for raw in data.get("receipts") or []:
        if not isinstance(raw, dict):
            continue
        amount = parse_amount(raw.get("amount"))
        receipt = {"file": _text(raw.get("file")), "amount": amount if amount and amount > 0 else None}
        for key in ("date", "time", "merchant", "address", "approvalNo", "items"):
            receipt[key] = _text(raw.get(key))[:200]
        last = "".join(ch for ch in _text(raw.get("cardLast4")) if ch.isdigit())
        receipt["cardLast4"] = last[-4:] if len(last) >= 4 else ""
        out["receipts"].append(receipt)
    meeting = data.get("meeting")
    if isinstance(meeting, dict):
        m = {key: _text(meeting.get(key))[:300] for key in ("file", "date", "start", "end", "place", "agenda")}
        content = meeting.get("content")
        content = [content] if isinstance(content, str) else content if isinstance(content, list) else []
        m["content"] = [_text(p)[:1200] for p in content if _text(p)]
        m["attendees"] = []
        for person in meeting.get("attendees") or []:
            if isinstance(person, dict) and _text(person.get("name")):
                m["attendees"].append({"org": _text(person.get("org"))[:80], "name": _text(person.get("name"))[:40],
                                       "no": idnums.clean(person.get("no"))})
        if any(m[key] for key in ("date", "start", "place", "agenda", "content", "attendees")):
            out["meeting"] = m
    snack = data.get("snack")
    out["snack"] = snack if isinstance(snack, bool) else None
    return out


def found_text(data: dict) -> str:
    """기록 · 화면에 남길 한 줄 — 값(이름 · 금액)은 적지 않는다."""
    return card_mod.ai_found_text(data)


def read(folder: str, files: list[str], model: str | None = None) -> dict:
    """결제 건 폴더 하나를 Claude Code 로 읽는다. 실패하면 BackendError(kind 'login' · 'limit' · 'balance' 면 남은 건도 그만)."""
    exe = find_claude()
    if not exe:
        raise BackendError("claude 명령을 찾을 수 없음")
    files = media_files(files)
    if not files:
        raise BackendError("읽을 파일이 없음")
    model = settings.load().minutes_model if model is None else model
    tmp = tempfile.mkdtemp(prefix="card_")
    json_path = os.path.join(tmp, "card.json")
    cli_args = [
        "-p", build_prompt(folder, files, json_path),
        "--output-format", "json",
        "--permission-mode", "acceptEdits",
        "--allowedTools", "Read,Glob,Grep,Write,Edit,Bash,PowerShell",
        "--add-dir", tmp,
    ]
    if model:
        cli_args += ["--model", model]
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
        log("카드 AI 읽기 실행 오류\n" + traceback.format_exc())
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
        # stdout 에는 영수증 · 회의록 글(가맹점 · 참석자 이름)이 섞일 수 있어 남기지 않는다 — 까닭 한 줄과 stderr 앞부분만
        log("카드 AI 읽기 결과 없음: rc=%s · %s\nstderr=%s" % (r.returncode, _failure_reason(r), (r.stderr or "")[:600]))
        raise BackendError(_failure_reason(r))
    return clean(data)
