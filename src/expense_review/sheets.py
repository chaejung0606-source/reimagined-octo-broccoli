"""구글시트 연동 — GitHub 없이 기준값을 관리하고 검토 기록을 남긴다.

두 방향을 지원한다. 둘 다 구글 API 키·OAuth 없이 동작한다.

  읽기 (기준값)
    링크 공유(또는 웹 게시)된 시트를 CSV 로 내려받아 검토 기준 오버라이드로
    쓴다. 담당자는 시트만 고치면 되고, GitHub 커밋이 필요 없다.

  쓰기 (검토 기록)
    사용자가 배포한 Google Apps Script 웹앱 URL 로 요약 행을 POST 한다.
    시트 쪽 스크립트는 대여섯 줄이면 된다(docs/05-app-guide.md 참고).

우선순위는  배포본 rules/*.yaml  <  구글시트  <  앱에서 직접 수정(로컬) 이다.
시트는 팀 공용 기준, 로컬 수정은 개인 조정이라는 뜻이다.

규칙 평가 경로에서는 네트워크를 쓰지 않는다 — 엔진은 캐시 파일만 읽고,
실제 다운로드는 앱 시작 시 백그라운드와 설정 화면의 버튼에서만 일어난다.
"""
from __future__ import annotations

import csv
import io
import json
import re
import urllib.request
from typing import Any

from . import config

FETCH_TIMEOUT = 15
CACHE_FILENAME = "sheet-cache.csv"

# 시트 열 이름(한국어 서식) ↔ 내부 필드
_RULE_FIELD_ALIASES = {
    "등급": "severity", "severity": "severity",
    "사용": "enabled", "사용 여부": "enabled", "enabled": "enabled",
    "검출 문구": "message", "message": "message",
    "조치 문구": "fix", "fix": "fix",
    "제목": "title", "title": "title",
}
_SEVERITY_ALIASES = {
    "수정 필요": "ERROR", "수정필요": "ERROR", "ERROR": "ERROR",
    "확인 요망": "WARN", "확인요망": "WARN", "WARN": "WARN",
    "참고": "INFO", "INFO": "INFO",
}
_TRUE_WORDS = {"예", "사용", "on", "true", "1"}
_FALSE_WORDS = {"아니오", "사용 안 함", "사용안함", "off", "false", "0"}


# ── URL 처리 ──────────────────────────────────────────────────────────────

_SHEET_ID_RE = re.compile(r"docs\.google\.com/spreadsheets/d/([\w-]+)")
_GID_RE = re.compile(r"[#?&]gid=(\d+)")


def to_csv_export_url(url: str) -> str:
    """시트 주소를 CSV 내보내기 주소로 바꾼다.

    담당자는 브라우저 주소창의 URL 을 그대로 붙여넣으면 된다.
    이미 CSV 주소(웹 게시 output=csv 등)면 그대로 둔다.
    """
    url = (url or "").strip()
    if not url:
        return ""
    if "output=csv" in url or "/export" in url:
        return url
    match = _SHEET_ID_RE.search(url)
    if not match:
        return url
    gid_match = _GID_RE.search(url)
    gid = gid_match.group(1) if gid_match else "0"
    return f"https://docs.google.com/spreadsheets/d/{match.group(1)}/export?format=csv&gid={gid}"


def fetch_csv(url: str, timeout: int = FETCH_TIMEOUT) -> str:
    request = urllib.request.Request(
        to_csv_export_url(url), headers={"User-Agent": "expense-review/1.0"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read()
    text = data.decode("utf-8-sig", errors="replace")
    # 권한이 없으면 구글이 로그인 HTML 을 돌려준다 — CSV 가 아니면 실패로 처리
    if text.lstrip().lower().startswith(("<!doctype", "<html")):
        raise PermissionError(
            "시트를 읽지 못했습니다. 공유 설정을 '링크가 있는 모든 사용자(뷰어)'로 바꾸거나 "
            "파일 → 공유 → 웹에 게시(CSV)를 사용하세요."
        )
    return text


# ── CSV → 오버라이드 ──────────────────────────────────────────────────────

def _coerce(text: str) -> Any:
    lowered = text.strip().lower()
    if lowered in _TRUE_WORDS:
        return True
    if lowered in _FALSE_WORDS:
        return False
    try:
        return int(text.replace(",", ""))
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text.strip()


def parse_overrides(csv_text: str) -> dict[str, Any]:
    """시트 내용을 오버라이드로 바꾼다. 서식은 4열이다.

        종류, 대상, 항목, 값
        설정, 출장비, km_rate, 300
        규칙, R-TRV-008, 등급, 수정 필요
        규칙, R-TRV-008, 사용, 아니오

    모르는 행은 조용히 건너뛰되 사유를 issues 로 모아 화면에 보여 준다.
    """
    overrides: dict[str, Any] = {"rules": {}, "settings": {}}
    issues: list[str] = []

    rows = list(csv.reader(io.StringIO(csv_text)))
    for line_no, row in enumerate(rows, start=1):
        cells = [cell.strip() for cell in row]
        if len(cells) < 4 or not cells[0] or cells[0] in ("종류", "kind"):
            continue  # 빈 줄·머리글
        kind, target, field, value = cells[0], cells[1], cells[2], cells[3]

        if kind in ("설정", "setting"):
            if not target or not field:
                issues.append(f"{line_no}행: 지출종류/키가 비어 있습니다")
                continue
            overrides["settings"].setdefault(target, {})[field] = _coerce(value)

        elif kind in ("규칙", "rule"):
            internal = _RULE_FIELD_ALIASES.get(field)
            if internal is None:
                issues.append(f"{line_no}행: 알 수 없는 항목 '{field}'")
                continue
            if internal == "severity":
                mapped = _SEVERITY_ALIASES.get(value.strip().upper() if value.isascii() else value.strip())
                if mapped is None:
                    issues.append(f"{line_no}행: 알 수 없는 등급 '{value}'")
                    continue
                coerced: Any = mapped
            elif internal == "enabled":
                coerced = _coerce(value)
                if not isinstance(coerced, bool):
                    issues.append(f"{line_no}행: 사용 여부는 예/아니오로 적어 주세요")
                    continue
            else:
                coerced = value
            overrides["rules"].setdefault(target, {})[internal] = coerced

        else:
            issues.append(f"{line_no}행: 알 수 없는 종류 '{kind}' (설정/규칙만 가능)")

    overrides["issues"] = issues
    return overrides


# ── 캐시 — 엔진은 이것만 읽는다 (네트워크 없음) ───────────────────────────

def _cache_path():
    return config.config_dir() / CACHE_FILENAME


def save_cache(csv_text: str) -> None:
    _cache_path().write_text(csv_text, encoding="utf-8")


def clear_cache() -> None:
    _cache_path().unlink(missing_ok=True)


def cached_overrides() -> dict[str, Any]:
    """마지막으로 받아 둔 시트 내용. 없으면 빈 오버라이드."""
    path = _cache_path()
    if not path.exists():
        return {"rules": {}, "settings": {}, "issues": []}
    return parse_overrides(path.read_text(encoding="utf-8"))


def refresh(url: str | None = None) -> dict[str, Any]:
    """시트를 실제로 내려받아 캐시를 갱신한다. 설정 화면·앱 시작 시에만 호출."""
    sheet_url = (url or config.load_settings().get("sheet_url") or "").strip()
    if not sheet_url:
        raise ValueError("기준 시트 URL이 설정되어 있지 않습니다.")
    text = fetch_csv(sheet_url)
    save_cache(text)
    return parse_overrides(text)


# ── 검토 기록 쓰기 (Apps Script 웹훅) ─────────────────────────────────────

def post_log(webhook_url: str, rows: list[list[Any]], timeout: int = FETCH_TIMEOUT) -> None:
    """요약 행들을 시트 웹훅으로 보낸다.

    행에는 요약 정보만 담는다 — 주민등록번호·계좌번호 같은 원문은
    호출하는 쪽에서 이미 제외되어 있어야 한다.
    """
    payload = json.dumps({"rows": rows}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        webhook_url.strip(), data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "expense-review/1.0"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        response.read()


def result_rows(results) -> list[list[Any]]:
    """검토 결과 → 기록 행. [일시, 지출종류, 제출자, 수정필요, 확인요망, 판독불가, 규칙ID들]"""
    import datetime as dt

    from .models import Severity

    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    rows: list[list[Any]] = []
    for result in results:
        counts = result.counts
        rule_ids = sorted({
            f.rule_id for f in result.findings
            if f.rule_id != "-" and f.severity in (Severity.ERROR, Severity.WARN)
        })
        rows.append([
            stamp,
            result.expense_type,
            result.owner or "",
            counts[Severity.ERROR],
            counts[Severity.WARN],
            counts[Severity.REVIEW],
            " ".join(rule_ids),
        ])
    return rows
