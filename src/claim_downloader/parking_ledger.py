"""공무확인증 관리대장 — 주차등록에 쓰는 공무확인증을 누가 · 무엇에 썼는지 앱에 남긴다. Qt 없음.

담당자 2026-10-21: "학교에서 공무확인증을 구매해서 사용을 하는건데 사용자와 사용내용을 남겨두는게 좋을 것 같습니다. 주차관제시스템에는
없지만 어플에서 작성하고 할인내역을 볼때 공무확인증 관리대장으로 확인하고 엑셀파일로 다운받을 수 있도록" · "이전 공무확인증 관리대장에는
일자, 수량(구입,배부,잔여), 내용, 사용자 항목이 있었습니다" · "할인적용이나 할인링크를 만들어서 사용할때 관리대장에 필요한 내용도 추가적으로
입력해서 기록할 수 있도록".

- 줄 하나 = 구입(산 수) 또는 배부(쓴 수). 잔여는 적은 차례(일자 → 적은 때)대로 '앞 잔여 + 구입 − 배부'.
- 할인 적용은 차량번호 하나 = 배부 1, 할인 링크는 담당자가 적은 배부 수량. 구입 · 이월 · 고침은 화면의 [줄 추가] · 표에서.
- 사이트 할인 내역(parking_screens.read_history)과 맞춰 볼 때는 차량번호 + 일자로 대장의 배부 줄을 찾는다 — 그 화면의 열 이름은
  실측 전이라 머리글 글자(차량 · 일시/일자)로 열을 고르고, 못 고르면 맞춰 보지 않는다(match_site).
- 사용자 이름 · 차량번호가 들어 있어 사용자 폴더(`_공무확인증관리대장.json`)에만 두고 저장소 · 배포 · 기록(_실행로그)에는 남기지 않는다.
  담당자가 구글 시트 연동을 켜면(2026-10-22, parking_sheet.py) 그 시트의 '관리대장' 탭과 맞춘다 — 이 파일은 그때도 이 PC 의 사본이다.
  맞추기(merge)는 줄마다 id 로: 양쪽에 있으면 고친 때(updated)가 늦은 쪽, 한쪽에만 있으면 새로 적은 것 — 단 지난번 맞출 때 있었던 줄이
  시트에서 사라졌으면 시트에서 지운 것, 이 PC 에서 지운 줄(deleted)은 시트에서도 지운다.
"""
from __future__ import annotations

import bisect
import datetime as dt
import json
import re
import threading
import uuid
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from . import settings

BUY, GIVE = "buy", "give"
_LOCK = threading.RLock()       # 화면(고치기)과 구글 시트 맞추기 스레드가 같은 파일을 읽고 쓴다


def now_stamp() -> str:
    """고친 때 — 세계시 ISO(구글 시트 스크립트의 toISOString 과 같은 꼴이라 글자로 견줄 수 있다)."""
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
SOURCES = {"apply": "할인 적용", "link": "할인 링크", "manual": "직접", "site": "사이트 할인 내역", "carry": "처음 수량"}
CARRY = "carry"         # 처음 수량 — 사이트 보유 잔량에서 거꾸로 센 줄(fit_to_site). 앱이 고친다(하나만)
TITLE = "공무확인증 관리대장"


@dataclass
class Entry:
    date: str                     # YYYY-MM-DD
    bought: int = 0               # 구입(이월 포함)
    given: int = 0                # 배부(쓴 수)
    content: str = ""             # 내용(용무)
    user: str = ""                # 사용자
    car: str = ""                 # 차량번호(할인 적용 · 사이트 할인 내역) — 사이트와 맞춰 볼 때
    note: str = ""                # 비고(할인 링크 이름 · 상품 등)
    source: str = "manual"        # apply · link · manual · site
    created: str = field(default_factory=lambda: dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    updated: str = field(default_factory=now_stamp)     # 고친 때 — 구글 시트와 맞출 때 늦은 쪽이 이긴다

    @property
    def kind(self) -> str:
        return BUY if self.bought and not self.given else GIVE

    def remark(self) -> str:
        """엑셀 · 표의 비고 칸 — 차량번호와 비고를 함께."""
        return " · ".join(x for x in (self.car, self.note) if x)


def path() -> Path:
    return settings.parking_ledger_path()


def _read() -> dict:
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _entries_of(rows) -> list[Entry]:
    names = {f.name for f in fields(Entry)}
    out = []
    for row in rows or []:
        if isinstance(row, dict) and row.get("date"):
            values = {k: v for k, v in row.items() if k in names}
            for key in ("bought", "given"):
                values[key] = _int(values.get(key))
            values.setdefault("updated", "")
            out.append(Entry(**values))
    return out


def load() -> list[Entry]:
    """적은 줄 — 파일이 없거나 깨졌으면 빈 목록(깨진 파일은 덮어쓰기 전에 옆에 남긴다, save)."""
    with _LOCK:
        return _entries_of(_read().get("entries"))


def sync_state() -> tuple[set[str], set[str]]:
    """(지난번 구글 시트와 맞춘 줄 id, 이 PC 에서 지웠지만 아직 시트에 알리지 않은 줄 id)."""
    with _LOCK:
        sync = _read().get("sync") or {}
        return set(sync.get("ids") or []), set(sync.get("deleted") or [])


def save(entries: list[Entry], sync: dict | None = None) -> None:
    with _LOCK:
        target = path()
        target.parent.mkdir(parents=True, exist_ok=True)
        old = {}
        if target.exists():
            try:
                old = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                # 손으로 고치다 깨진 파일 — 덮어쓰면 그동안 적은 것이 사라진다. 옆에 남겨 둔다
                target.replace(target.with_name(target.name + ".읽지못함"))
        data = {"entries": [asdict(e) for e in ordered(entries)]}
        keep = sync if sync is not None else (old.get("sync") if isinstance(old, dict) else None)
        if keep:
            data["sync"] = keep
        temp = target.with_name(target.name + ".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        temp.replace(target)


def add(entry: Entry) -> list[Entry]:
    with _LOCK:
        entries = load()
        entries.append(entry)
        save(entries)
        return ordered(entries)


def update(entry_id: str, **changes) -> list[Entry]:
    with _LOCK:
        entries = load()
        for e in entries:
            if e.id == entry_id:
                for key, value in changes.items():
                    if key in ("bought", "given"):
                        value = _int(value)
                    setattr(e, key, value)
                e.updated = now_stamp()
        save(entries)
        return ordered(entries)


def remove(entry_id: str) -> list[Entry]:
    """지운 줄은 구글 시트에도 알린다(deleted) — 시트와 맞추는 중에 지운 줄이 되살아나지 않게 맞춘 적이 없는 줄도 적어 둔다.
    시트에 알리면 목록에서 뺀다(mark_synced). 연동하지 않는 PC 에서 끝없이 쌓이지 않게 최근 500개만."""
    with _LOCK:
        entries = [e for e in load() if e.id != entry_id]
        ids, deleted = sync_state()
        save(entries, {"ids": sorted(ids), "deleted": sorted(deleted | {entry_id})[-500:]})
        return ordered(entries)


def reset_sync() -> int:
    """구글 시트가 바뀌었을 때(새 시트에 연결 · 연동 끊기) — 지난번 시트와 맞춘 줄 id 를 잊는다. 잊지 않으면 merge 가 새(빈) 시트에
    없는 줄을 '시트에서 지운 줄' 로 보고 이 PC 의 대장을 통째로 지운다(2026-10-23, 담당자가 지워진 시트 대신 새 시트로 연결하려던 때 발견).
    이 PC 에서 지웠지만 아직 시트에 알리지 않은 줄 목록은 둔다(새 시트에는 없으니 그냥 알린 셈이 된다). 잊은 id 수를 돌려준다."""
    with _LOCK:
        ids, deleted = sync_state()
        if ids:
            save(load(), {"ids": [], "deleted": sorted(deleted)})
        return len(ids)


def mark_synced(ids: set[str], told: set[str]) -> None:
    """구글 시트에 다 써 넣은 뒤 — 맞춘 줄 id 를 남기고, 시트에 알린 지운 줄은 목록에서 뺀다."""
    with _LOCK:
        _old_ids, deleted = sync_state()
        save(load(), {"ids": sorted(ids), "deleted": sorted(deleted - told)})


def merge(local: list[Entry], remote: list[Entry], synced: set[str], deleted: set[str]) -> list[Entry]:
    """이 PC 의 대장과 구글 시트의 대장을 줄 id 로 맞춘다(위 머리말의 규칙)."""
    mine = {e.id: e for e in local}
    theirs = {e.id: e for e in remote}
    out = []
    for key in list(mine) + [k for k in theirs if k not in mine]:
        if key in deleted:
            continue
        a, b = mine.get(key), theirs.get(key)
        if a and b:
            out.append(b if (b.updated or "") > (a.updated or "") else a)
        elif a:
            if key not in synced:                     # 아직 시트에 올리지 않은 새 줄
                out.append(a)
        else:
            out.append(b)
    return ordered(out)


# ── 구글 시트 '관리대장' 탭의 줄 ──────────────────────────────────────────
SHEET_HEAD = ("일자", "구입", "배부", "잔여", "내용", "사용자", "차량번호", "비고", "적은 곳", "id", "수정시각", "적은 때")
_SOURCE_OF = {label: key for key, label in SOURCES.items()}


def to_sheet(entries: list[Entry]) -> list[list]:
    """시트에 쓸 줄 — 옛 관리대장 차례 + 잔여(앱이 셈) + 맞추기에 쓰는 id · 수정시각."""
    return [[e.date, e.bought or "", e.given or "", left, e.content, e.user, e.car, e.note, SOURCES.get(e.source, e.source), e.id,
             e.updated, e.created] for e, left in with_balance(entries)]


def from_sheet(rows: list[list]) -> list[Entry]:
    """시트의 줄(머리글 빼고, 글자로 읽은 값) → 대장 줄. 일자를 못 읽는 줄은 뺀다. id 가 없는 줄(시트에 손으로 더한 줄)은 새 id."""
    out = []
    for row in rows:
        cell = lambda i: str(row[i]).strip() if i < len(row) and row[i] is not None else ""  # noqa: E731
        date = day_of(cell(0))
        if not date:
            continue
        out.append(Entry(date=date, bought=_int(cell(1)), given=_int(cell(2)), content=cell(4), user=cell(5), car=cell(6),
                         note=cell(7), source=_SOURCE_OF.get(cell(8), "manual"), id=cell(9) or uuid.uuid4().hex,
                         updated=cell(10) or now_stamp(), created=cell(11) or dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    return out


def ordered(entries: list[Entry]) -> list[Entry]:
    """일자 → 적은 때 차례(같은 날은 적은 차례대로)."""
    return sorted(entries, key=lambda e: (e.date, e.created))


def with_balance(entries: list[Entry]) -> list[tuple[Entry, int]]:
    """(줄, 그 줄까지의 잔여). 구입을 적기 전이면 잔여가 0 아래로 내려간다 — 화면이 '구입(또는 이월)부터 적으세요' 로 알린다."""
    left, out = 0, []
    for e in ordered(entries):
        left += e.bought - e.given
        out.append((e, left))
    return out


def totals(entries: list[Entry]) -> tuple[int, int, int]:
    """(구입, 배부, 잔여)."""
    bought = sum(e.bought for e in entries)
    given = sum(e.given for e in entries)
    return bought, given, bought - given


def left_of(text: str) -> int | None:
    """할인권 글자의 남은 수 — '교환공무확인증4시간 (잔량 85)'(실측 ②) · '… 85매' · '… (85)'. 없으면 None."""
    text = str(text or "")
    for pattern in (r"잔량\s*([\d,]+)", r"잔여\s*([\d,]+)", r"보유\s*([\d,]+)", r"([\d,]+)\s*(?:매|장|개)\b", r"\(\s*([\d,]+)\s*\)\s*$"):
        m = re.search(pattern, text)
        if m:
            return int(m.group(1).replace(",", ""))
    return None


def site_count(products) -> int | None:
    """사이트가 보여 준 할인권 상품 보기(줄마다 하나) 중 이름에 '공무확인증' 이 든 것의 남은 수 합. 없으면 None."""
    lines = products.splitlines() if isinstance(products, str) else list(products or [])
    found = [left_of(line) for line in lines if TICKET in _squash(line)]
    found = [n for n in found if n is not None]
    return sum(found) if found else None


@dataclass
class Fit:
    entries: list
    start: int = 0           # 처음 수량
    short: int = 0           # 대장의 구입이 사이트 잔량으로 설명되지 않는 수 — 대장에 없는 사용이 있다
    changed: bool = False


def fit_to_site(entries: list[Entry], count: int, when: str) -> Fit:
    """사이트 보유 잔량(count)에 대장을 맞춘다(담당자 2026-10-22 "보유할인권을 보면 현재 잔여 개수가 있습니다 … 처음에 있었던 수량과 현재
    수량 건별로 잔여 수량 다시 계산"). 처음 수량 = 지금 잔량 + 대장의 배부 − 다른 구입 — 맨 앞 줄(CARRY, 대장의 첫 일자)로 두면 마지막 잔여가
    사이트 잔량과 같고 줄마다 잔여가 다시 셈해진다. 잔량을 **막 읽었을 때만** 부른다 — 오래된 잔량으로 다시 맞추면 그 뒤의 사용이 처음 수량에 묻힌다."""
    others = [e for e in entries if e.source != CARRY]
    old = next((e for e in entries if e.source == CARRY), None)
    start = count + sum(e.given for e in others) - sum(e.bought for e in others)
    short = max(0, -start)
    start = max(start, 0)
    first = min((e.date for e in others), default=dt.date.today().isoformat())
    note = f"사이트 보유 잔량 {count:,}({when})에서 거꾸로 셈"
    carry = old or Entry(date=first, source=CARRY, created="0000-00-00 00:00:00")
    changed = old is None or (old.date, old.bought, old.note) != (first, start, note)
    carry.date, carry.bought, carry.given, carry.content, carry.note = first, start, 0, "처음 수량", note
    if changed:
        carry.updated = now_stamp()
    return Fit(entries=ordered(others + [carry]), start=start, short=short, changed=changed)


# ── 사이트 할인 내역과 맞춰 보기 ───────────────────────────────────────────
# 할인 내역 화면의 열(담당자 PC 에서 읽힌 것 2026-10-22): 할인일시 | 차량번호 | 입차시각 | 할인명 | 바코드 | 할인유형 | 적용방식 | 입주사 | 구분 |
# 할인시간 | 할인율 | 할인금액 | 적용금액 | 절사금액 | 결제금액. 머리글 글자 끝에 정렬 그림 글자('arrow_downward')가 붙어 읽힌다.
# 열은 글자로 찾고(차례에 기대지 않는다), 앞의 낱말이 먼저 — '시간' 만으로 찾으면 '할인시간'(240분)을 일시로 잘못 본다.
DATE_WORDS = ("할인일시", "적용일시", "사용일시", "일시", "일자", "날짜")
CAR_WORDS = ("차량번호", "차량", "차번", "번호판")
PRODUCT_WORDS = ("할인명", "상품", "할인권", "템플릿")
METHOD_WORDS = ("적용방식",)
APPLIED_WORDS = ("적용금액",)      # 할인이 실제로 덮은 주차 요금 — 0 이면 무료 시간 안이었던 것으로 보인다(담당자 2026-10-22 "적용금액이 있는 건만 차감되는지")
TICKET = "공무확인증"
MANUAL = "수동"                # 적용방식 — 사이트 화면에서 직접 적용한 것(할인 적용). 링크 · QR 로 쓴 것은 다른 글자로 보인다(추정)
_ICON = re.compile(r"(arrow_(up|down)ward|arrow_drop_(up|down)|unfold_(more|less)|expand_(more|less)|keyboard_arrow_\w+|swap_vert|sort)\s*$")


def clean_header(text: str) -> str:
    """'할인일시arrow_downward' → '할인일시' — 정렬 단추의 그림 글자를 뗀다."""
    return _ICON.sub("", str(text or "")).strip()


@dataclass
class SiteMatch:
    car_col: int = -1
    date_col: int = -1
    product_col: int = -1
    method_col: int = -1
    applied_col: int = -1
    matched: list[int] = field(default_factory=list)     # 대장에 이미 있는 사이트 줄(같은 날 · 같은 차)
    pairs: list = field(default_factory=list)            # (사이트 줄 번호, 그 줄과 짝지은 대장 줄)
    missing: list[int] = field(default_factory=list)     # 대장에 없는 공무확인증 줄 — 넣는다(사이트에서 직접 적용한 것도 링크 · QR 로 쓴 것도)
    others: list[int] = field(default_factory=list)      # 공무확인증이 아닌 할인 — 대장과 상관없다
    note: str = ""

    @property
    def ok(self) -> bool:
        return self.car_col >= 0 and self.date_col >= 0


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def day_of(text: str) -> str:
    """'2026-10-21 10:03' · '2026.10.21' · '2026/10/21' → '2026-10-21'. 못 읽으면 ''."""
    m = re.search(r"(20\d\d)\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})", str(text or ""))
    if not m:
        return ""
    try:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return ""


def _time_of(text: str) -> str:
    m = re.search(r"(\d{1,2}):(\d{2})", str(text or ""))
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else ""


def _column(headers: list[str], words: tuple[str, ...]) -> int:
    """앞의 낱말부터 — 그 낱말이 든 첫 머리글."""
    names = [_squash(clean_header(h)) for h in headers]
    for word in words:
        for i, name in enumerate(names):
            if word in name:
                return i
    return -1


def match_site(entries: list[Entry], headers: list[str], rows: list[list[str]]) -> SiteMatch:
    """사이트 할인 내역의 줄마다 대장에 같은 날 같은 차량번호의 배부 줄이 있는지. 대장 줄 하나는 사이트 줄 하나에만 맞춘다
    (같은 차가 같은 날 두 번이면 대장에도 두 줄이어야 맞다). 할인명이 공무확인증이 아닌 줄은 대장과 상관없다(할인명 열이 없으면 모두 본다).
    링크 · QR 로 쓴 줄도 사용 한 건씩 넣는다(담당자 2026-10-22 "할인링크나 qr로 사용한 내역도 바로바로 관리대장에 반영") — 그래서 할인 링크를 만들 때는
    배부를 적지 않는다(배부 0 인 기록 줄). 차량 · 일시 열을 못 찾으면 맞춰 보지 않는다."""
    result = SiteMatch(car_col=_column(headers, CAR_WORDS), date_col=_column(headers, DATE_WORDS),
                       product_col=_column(headers, PRODUCT_WORDS), method_col=_column(headers, METHOD_WORDS),
                       applied_col=_column(headers, APPLIED_WORDS))
    if not result.ok:
        result.note = "할인 내역의 차량번호 · 일시 열을 알아보지 못해 대장과 맞춰 보지 못했습니다"
        return result
    pool: dict[tuple[str, str], list] = {}
    for e in entries:
        if e.car and (e.given or is_free(e.note)):              # 적용금액 0 이라 배부 0 으로 둔 줄도 그 사이트 줄의 짝이다
            pool.setdefault((e.date, _squash(e.car)), []).extend([e] * max(e.given, 1))
    cell = lambda row, c: row[c] if 0 <= c < len(row) else ""  # noqa: E731
    for i, row in enumerate(rows):
        if result.product_col >= 0 and TICKET not in _squash(cell(row, result.product_col)):
            result.others.append(i)
            continue
        key = (day_of(cell(row, result.date_col)), _squash(cell(row, result.car_col)))
        if all(key) and pool.get(key):
            result.pairs.append((i, pool[key].pop(0)))
            result.matched.append(i)
        else:
            result.missing.append(i)
    return result


def amount_of(text: str) -> int | None:
    """'6,700' · '0' · '1,000원' → 정수. 빈칸 · '-' 는 None(모름)."""
    digits = re.sub(r"[^\d]", "", str(text or ""))
    return int(digits) if digits else None


def applied_of(row: list[str], match: SiteMatch) -> int | None:
    c = match.applied_col
    return amount_of(row[c]) if 0 <= c < len(row) else None


FREE_NOT_DRAWN = "차감 안 됨"
_FREE = re.compile(r"적용금액 0(?![\d,])")


def is_free(note: str) -> bool:
    """비고에 '적용금액 0' 이 있는 줄 — 적용금액이 0 인 사용(무료 시간 안으로 보임)."""
    return bool(_FREE.search(note or ""))


def from_site(headers: list[str], rows: list[list[str]], indexes: list[int], match: SiteMatch,
              free_drawn: bool = True) -> list[Entry]:
    """사이트 줄 → 관리대장 양식의 배부 1 줄(담당자 2026-10-22 "관리대장 양식에 맞춰서 정보 기입 … 없는 정보는 공란"):
    일자 = 할인일시의 날짜 · 배부 1 · 차량번호 · 비고 = 할인명 · 할인 시각 · (링크 · QR 이면) 적용방식 · 적용금액. 사용자 · 내용은 사이트에 없어 비워 둔다.
    적용금액이 0 인 사용이 공무확인증을 쓰지 않는다고 확인됐으면(free_drawn=False, drain_study) 그 줄은 배부 0."""
    out = []
    for i in indexes:
        row = rows[i]
        cell = lambda c: row[c] if 0 <= c < len(row) else ""  # noqa: E731
        when = cell(match.date_col)
        method = cell(match.method_col).strip()
        applied = applied_of(row, match)
        note = " · ".join(x for x in (cell(match.product_col).strip(), (_time_of(when) + " 할인") if _time_of(when) else "",
                                      method if method and method != MANUAL else "",        # 링크 · QR 로 쓴 것은 그 적용방식을 함께
                                      f"적용금액 {applied:,}" if applied is not None else "",
                                      FREE_NOT_DRAWN if applied == 0 and not free_drawn else "") if x)
        out.append(Entry(date=day_of(when) or dt.date.today().isoformat(), given=0 if applied == 0 and not free_drawn else 1,
                         car=cell(match.car_col).strip(), note=note, source="site"))
    return out


_APPLIED = re.compile(r"적용금액 [\d,]+")


def _unmark(note: str) -> str:
    return note.replace(" · " + FREE_NOT_DRAWN, "").replace(FREE_NOT_DRAWN, "").strip(" ·")


def note_applied(rows: list[list[str]], match: SiteMatch) -> int:
    """이미 대장에 있는 짝(할인 적용 · 전에 가져온 줄)의 비고에 적용금액을 붙이고, 사이트 값이 바뀌었으면 고친다 — 적용금액은 차가 나갈 때
    정해지는 것으로 보여(2026-10-22 실측: 입차 2분 뒤 할인한 줄이 1,000) 주차 중에는 0 이었다가 바뀔 수 있다. 0 이라 '차감 안 됨'(배부 0)으로
    둔 줄에 금액이 생기면 배부 1 로 되돌린다. 고친 줄 수."""
    changed = 0
    for i, e in match.pairs:
        applied = applied_of(rows[i], match)
        if applied is None:
            continue
        text = f"적용금액 {applied:,}"
        old = _APPLIED.search(e.note)
        if old and old.group(0) == text:
            continue
        e.note = _APPLIED.sub(text, e.note, count=1) if old else (e.note + " · " if e.note else "") + text
        if applied and FREE_NOT_DRAWN in e.note:
            e.note = _unmark(e.note)
            e.given = 1
        e.updated = now_stamp()
        changed += 1
    return changed


def apply_free_rule(entries: list[Entry]) -> int:
    """적용금액 0 인 사용이 공무확인증을 쓰지 않는다고 확인된 뒤 — 그 줄(비고 '적용금액 0')의 배부를 0 으로. 고친 줄 수."""
    changed = 0
    for e in entries:
        if e.given == 1 and is_free(e.note):
            e.given = 0
            if FREE_NOT_DRAWN not in e.note:
                e.note += " · " + FREE_NOT_DRAWN
            e.updated = now_stamp()
            changed += 1
    return changed


def restore_free(entries: list[Entry]) -> int:
    """적용금액 0 인 사용도 차감된다고 확인되면(또는 아직 모르면) — '차감 안 됨' 으로 배부 0 이 된 줄을 배부 1 로 되돌린다. 고친 줄 수."""
    changed = 0
    for e in entries:
        if e.given == 0 and is_free(e.note) and FREE_NOT_DRAWN in e.note:
            e.given = 1
            e.note = _unmark(e.note)
            e.updated = now_stamp()
            changed += 1
    return changed


def history_since(entries: list[Entry] | None = None, today: dt.date | None = None) -> str:
    """할인 내역을 읽을 시작일 — 올해 1월 1일과 대장의 가장 이른 일자 중 이른 쪽(해가 바뀌어도 대장에 있는 때부터는 읽는다)."""
    today = today or dt.date.today()
    dates = [e.date for e in (entries if entries is not None else load()) if e.date and e.source != CARRY]
    return min([dt.date(today.year, 1, 1).isoformat()] + dates)


def stamp_of(text: str) -> str:
    """'2026-10-20 17:37:04' · '2026.10.20 17:37' → '2026-10-20 17:37:04'(초가 없으면 00). 날짜가 없으면 ''."""
    text = str(text or "")
    day = day_of(text)
    if not day:
        return ""
    after = text[re.search(r"20\d\d\s*[-./년]\s*\d{1,2}\s*[-./월]\s*\d{1,2}", text).end():]
    m = re.search(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", after)
    return f"{day} {int(m.group(1)):02d}:{m.group(2)}:{m.group(3) or '00'}" if m else f"{day} 00:00:00"


# ── 보유 잔량 기록 · 적용금액 0 인 사용의 차감 ───────────────────────────────
# 담당자 2026-10-22 "적용금액이 있는 건만 공무확인증이 차감되는건지도 확인" · "점차 쌓이는 내역 데이터를 바탕으로 분석". 적용금액은 차가 나갈 때
# 정해지는 것으로 보여 두 번 읽은 잔량을 바로 견주면 주차 중인 차가 섞인다. 그래서 사이트에서 본 잔량을 모두 쌓아 두고(record_reading),
# 앞 QUIET_HOURS 동안 공무확인증 사용이 없던 때에 읽은 잔량끼리만 견준다(drain_study) — 그 사이 사용은 모두 차가 나가 적용금액이 정해졌고,
# 사이트 시각과 이 PC 시각이 조금 달라도 구간 끝에 걸리는 사용이 없다. 날마다 아침 첫 읽기가 대개 그런 때다.
QUIET_HOURS = 12
SURE = 2                  # 한쪽으로만 이만큼 맞고 다른 쪽은 한 번도 안 맞으면 정한다
READINGS_MAX = 3000


def readings_path() -> Path:
    return settings.parking_readings_path()


def load_readings() -> list[tuple[str, int]]:
    """(때 'YYYY-MM-DD HH:MM:SS', 잔량) — 때 차례."""
    try:
        data = json.loads(readings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for item in data.get("readings") or [] if isinstance(data, dict) else []:
        if isinstance(item, dict) and isinstance(item.get("count"), int) and stamp_of(str(item.get("at", ""))):
            out.append((stamp_of(item["at"]), item["count"]))
    return sorted(set(out))


def record_reading(count: int | None, at: str, source: str = "") -> bool:
    """사이트에서 실제로 본 보유 잔량(공무확인증 상품의 합, site_count)과 그 때를 쌓는다. 할인 적용 때 누른 할인권 글자의 수는 그 상품 하나뿐일 수 있어
    넣지 않는다. 같은 때는 한 번만. 쌓았으면 True."""
    at = stamp_of(at)
    if count is None or count < 0 or not at:
        return False
    with _LOCK:
        target = readings_path()
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        items = [x for x in (data.get("readings") or [] if isinstance(data, dict) else []) if isinstance(x, dict)]
        if any(stamp_of(str(x.get("at", ""))) == at for x in items):
            return False
        items.append({"at": at, "count": count, "from": source})
        items.sort(key=lambda x: stamp_of(str(x.get("at", ""))))
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(target.name + ".tmp")
        temp.write_text(json.dumps({"readings": items[-READINGS_MAX:]}, ensure_ascii=False, indent=1), encoding="utf-8")
        temp.replace(target)
    return True


@dataclass
class Window:
    """앞뒤 모두 '조용한 때'(앞 QUIET_HOURS 사용 없음)에 읽은 두 잔량 사이."""
    start: str
    end: str
    before: int
    after: int
    used: int = 0
    free: int = 0            # 그중 적용금액 0

    @property
    def fits(self) -> str:
        """'all'(적용금액 0 도 차감되면 맞음) · 'paid'(적용금액 있는 것만 차감되면 맞음) · 'same'(적용금액 0 사용이 없고 사용 수와 맞음) · ''(안 맞음 — 그 사이 구입 등)."""
        drop = self.before - self.after
        if drop == self.used:
            return "all" if self.free else "same"
        if self.free and drop == self.used - self.free:
            return "paid"
        return ""


@dataclass
class DrainStudy:
    readings: int = 0
    quiet: int = 0
    windows: list[Window] = field(default_factory=list)

    def count(self, fits: str) -> int:
        return sum(1 for w in self.windows if w.fits == fits)

    @property
    def verdict(self) -> str:
        drawn, paid = self.count("all"), self.count("paid")
        if drawn >= SURE and not paid:
            return "all"
        if paid >= SURE and not drawn:
            return "paid"
        return ""

    def text(self) -> str:
        drawn, paid, same, odd = self.count("all"), self.count("paid"), self.count("same"), self.count("")
        tail = " · ".join(x for x in (f"사용 수와 맞은 구간 {same}번" if same else "",
                                      f"그 사이 구입 등으로 맞지 않은 구간 {odd}번" if odd else "") if x)
        tail = f"({tail})" if tail else ""
        if self.verdict == "all":
            return f"적용금액 0 인 사용도 공무확인증이 차감됩니다 — 잔량 변화로 {drawn}번 확인{tail}"
        if self.verdict == "paid":
            return f"적용금액 0 인 사용은 차감되지 않습니다 — 잔량 변화로 {paid}번 확인{tail} · 대장에서 배부 0"
        if drawn and paid:
            return (f"잔량 변화가 엇갈립니다(모두 차감되는 쪽 {drawn}번 · 적용금액 있는 것만 차감되는 쪽 {paid}번){tail} — "
                    "더 쌓이면 다시 봅니다")
        if drawn or paid:
            side = "적용금액 0 인 사용도 차감되는" if drawn else "적용금액 0 인 사용은 차감되지 않는"
            return f"{side} 쪽으로 {drawn or paid}번 맞았습니다{tail} — {SURE}번 맞으면 정합니다"
        return (f"아직 모릅니다 — 보유 잔량 기록 {self.readings}번 중 앞 {QUIET_HOURS}시간 사용이 없던 때 {self.quiet}번{tail}. "
                "그런 때 사이에 적용금액 0 인 사용이 있으면 가릴 수 있습니다(아침에 관리대장을 한 번 열면 빨리 쌓입니다)")


def drain_study(readings: list[tuple[str, int]], rows: list[list[str]], match: SiteMatch, since: str) -> DrainStudy:
    """쌓인 잔량 기록과 할인 내역(since 부터 모든 쪽)의 공무확인증 사용으로 — 조용한 때끼리의 구간마다 줄어든 수가 모든 사용과 맞는지,
    적용금액 있는 사용과 맞는지. since 앞의 기록은 그 사이 사용을 모르니 쓰지 않는다."""
    study = DrainStudy()
    if not match.ok or not day_of(since):
        return study
    begin = day_of(since) + " 00:00:00"
    uses = []
    for i in match.matched + match.missing:
        when = stamp_of(rows[i][match.date_col] if match.date_col < len(rows[i]) else "")
        if when:
            uses.append((when, applied_of(rows[i], match)))
    uses.sort(key=lambda u: u[0])
    stamps = [u[0] for u in uses]
    quiet = []
    for at, count in readings:
        if at < begin:
            continue
        study.readings += 1
        calm = (dt.datetime.strptime(at, "%Y-%m-%d %H:%M:%S") - dt.timedelta(hours=QUIET_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
        if bisect.bisect_right(stamps, at) == bisect.bisect_right(stamps, calm):
            quiet.append((at, count))
    study.quiet = len(quiet)
    for (a, before), (b, after) in zip(quiet, quiet[1:]):
        inside = uses[bisect.bisect_right(stamps, a):bisect.bisect_right(stamps, b)]
        if not inside and before == after:
            continue
        study.windows.append(Window(start=a, end=b, before=before, after=after, used=len(inside),
                                    free=sum(1 for _w, applied in inside if applied == 0)))
    return study


# ── 엑셀 ─────────────────────────────────────────────────────────────────
HEADERS = ("일자", "구입", "배부", "잔여", "내용", "사용자", "비고(차량번호 등)")


def export_xlsx(entries: list[Entry], target: str | Path) -> Path:
    """옛 관리대장 모양 — 제목 · 2줄 머리글(일자 | 수량(구입 · 배부 · 잔여) | 내용 | 사용자 | 비고) · 줄 · 합계."""
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = TITLE
    thin = Side(style="thin", color="999999")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    head_fill = PatternFill("solid", fgColor="EDEBFB")

    sheet.merge_cells("A1:G1")
    sheet["A1"] = TITLE
    sheet["A1"].font = Font(size=16, bold=True)
    sheet["A1"].alignment = Alignment(horizontal="center")
    sheet["A2"] = f"출력일 {dt.date.today().isoformat()}"
    sheet.merge_cells("A2:G2")
    sheet["A2"].alignment = Alignment(horizontal="right")

    # 머리글 두 줄 — 수량 밑에 구입 · 배부 · 잔여
    for col, text in zip("ABCDEFG", ("일자", "수량", "", "", "내용", "사용자", "비고(차량번호 등)")):
        sheet[f"{col}3"] = text
    for col, text in zip("BCD", ("구입", "배부", "잔여")):
        sheet[f"{col}4"] = text
    sheet.merge_cells("B3:D3")
    for col in "AEFG":
        sheet.merge_cells(f"{col}3:{col}4")
    for row in (3, 4):
        for col in "ABCDEFG":
            cell = sheet[f"{col}{row}"]
            cell.font = Font(bold=True)
            cell.alignment = center
            cell.fill = head_fill
            cell.border = box

    r = 5
    for e, left in with_balance(entries):
        values = (e.date, e.bought or None, e.given or None, left, e.content, e.user, e.remark())
        for col, value in zip("ABCDEFG", values):
            cell = sheet[f"{col}{r}"]
            cell.value = value
            cell.border = box
            cell.alignment = Alignment(horizontal="center" if col in "ABCDF" else "left", vertical="center", wrap_text=col in "EG")
        r += 1
    bought, given, left = totals(entries)
    sheet[f"A{r}"] = "합계"
    for col, value in zip("BCD", (bought, given, left)):
        sheet[f"{col}{r}"] = value
    for col in "ABCDEFG":
        cell = sheet[f"{col}{r}"]
        cell.font = Font(bold=True)
        cell.border = box
        if col in "ABCD":
            cell.alignment = center

    # 열 폭 — 그 열에서 가장 긴 글에 맞춘다(한글은 두 칸)
    for col in "ABCDEFG":
        longest = max((_width(sheet[f"{col}{row}"].value) for row in range(3, r + 1)), default=4)
        sheet.column_dimensions[col].width = min(max(longest + 2, 6), 60)
    sheet.freeze_panes = "A5"
    sheet.print_title_rows = "3:4"
    target = Path(target)
    book.save(target)
    return target


def _width(value) -> int:
    text = "" if value is None else str(value)
    return sum(2 if ord(ch) > 0x2E80 else 1 for ch in text)


def _int(value) -> int:
    try:
        return max(int(str(value).replace(",", "").strip() or 0), 0)
    except (TypeError, ValueError):
        return 0
