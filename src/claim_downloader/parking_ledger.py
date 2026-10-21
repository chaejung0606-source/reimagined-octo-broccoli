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
"""
from __future__ import annotations

import datetime as dt
import json
import re
import uuid
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from . import settings

BUY, GIVE = "buy", "give"
SOURCES = {"apply": "할인 적용", "link": "할인 링크", "manual": "직접", "site": "사이트 할인 내역"}
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

    @property
    def kind(self) -> str:
        return BUY if self.bought and not self.given else GIVE

    def remark(self) -> str:
        """엑셀 · 표의 비고 칸 — 차량번호와 비고를 함께."""
        return " · ".join(x for x in (self.car, self.note) if x)


def path() -> Path:
    return settings.parking_ledger_path()


def load() -> list[Entry]:
    """적은 줄 — 파일이 없거나 깨졌으면 빈 목록(깨진 파일은 덮어쓰기 전에 옆에 남긴다, save)."""
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    names = {f.name for f in fields(Entry)}
    out = []
    for row in data.get("entries", []) if isinstance(data, dict) else []:
        if isinstance(row, dict) and row.get("date"):
            values = {k: v for k, v in row.items() if k in names}
            for key in ("bought", "given"):
                values[key] = _int(values.get(key))
            out.append(Entry(**values))
    return out


def save(entries: list[Entry]) -> None:
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        try:
            json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # 손으로 고치다 깨진 파일 — 덮어쓰면 그동안 적은 것이 사라진다. 옆에 남겨 둔다
            target.replace(target.with_name(target.name + ".읽지못함"))
    temp = target.with_name(target.name + ".tmp")
    temp.write_text(json.dumps({"entries": [asdict(e) for e in ordered(entries)]}, ensure_ascii=False, indent=1), encoding="utf-8")
    temp.replace(target)


def add(entry: Entry) -> list[Entry]:
    entries = load()
    entries.append(entry)
    save(entries)
    return ordered(entries)


def update(entry_id: str, **changes) -> list[Entry]:
    entries = load()
    for e in entries:
        if e.id == entry_id:
            for key, value in changes.items():
                if key in ("bought", "given"):
                    value = _int(value)
                setattr(e, key, value)
    save(entries)
    return ordered(entries)


def remove(entry_id: str) -> list[Entry]:
    entries = [e for e in load() if e.id != entry_id]
    save(entries)
    return ordered(entries)


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


def site_left(products_text: str, product: str = "") -> int | None:
    """사이트가 보여 준 할인권 잔량 — 할인 링크 [새 링크] 창의 상품 보기 '교환공무확인증4시간 (잔량 85)'(실측 ②). 상품을 고르지
    않았으면 보기가 하나일 때만. 마지막으로 [등록] 할 때 읽은 값이라 그 뒤에 쓴 것은 빠져 있을 수 있다."""
    found = []
    for label in (s.strip() for s in products_text.splitlines() if s.strip()):
        m = re.search(r"잔량\s*([\d,]+)", label)
        if m and (not product or label.startswith(product)):
            found.append(int(m.group(1).replace(",", "")))
    return found[0] if len(found) == 1 else None


# ── 사이트 할인 내역과 맞춰 보기 ───────────────────────────────────────────
@dataclass
class SiteMatch:
    car_col: int = -1
    date_col: int = -1
    matched: list[int] = field(default_factory=list)     # 대장에 이미 있는 사이트 줄
    missing: list[int] = field(default_factory=list)     # 대장에 없는 사이트 줄
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


def _column(headers: list[str], words: tuple[str, ...]) -> int:
    for i, head in enumerate(headers):
        if any(w in _squash(head) for w in words):
            return i
    return -1


def match_site(entries: list[Entry], headers: list[str], rows: list[list[str]]) -> SiteMatch:
    """사이트 할인 내역의 줄마다 대장에 같은 날 같은 차량번호의 배부 줄이 있는지. 대장 줄 하나는 사이트 줄 하나에만 맞춘다
    (같은 차가 같은 날 두 번이면 대장에도 두 줄이어야 맞다). 할인 내역 화면의 열 이름은 실측 전 — 차량 · 일시 열을 못 찾으면 맞춰 보지 않는다."""
    result = SiteMatch(car_col=_column(headers, ("차량", "차번", "번호판")),
                       date_col=_column(headers, ("일시", "일자", "날짜", "적용시간", "시간")))
    if not result.ok:
        result.note = "할인 내역의 차량번호 · 일시 열을 알아보지 못해 대장과 맞춰 보지 못했습니다"
        return result
    pool: dict[tuple[str, str], int] = {}
    for e in entries:
        if e.given and e.car:
            key = (e.date, _squash(e.car))
            pool[key] = pool.get(key, 0) + e.given
    for i, row in enumerate(rows):
        car = _squash(row[result.car_col]) if result.car_col < len(row) else ""
        day = day_of(row[result.date_col]) if result.date_col < len(row) else ""
        key = (day, car)
        if car and day and pool.get(key, 0) > 0:
            pool[key] -= 1
            result.matched.append(i)
        else:
            result.missing.append(i)
    return result


def from_site(headers: list[str], rows: list[list[str]], indexes: list[int], match: SiteMatch) -> list[Entry]:
    """대장에 없는 사이트 줄 → 배부 1 줄. 사용자 · 내용은 비어 있다 — 표에서 채운다."""
    product_col = _column(headers, ("상품", "할인권", "템플릿"))
    out = []
    for i in indexes:
        row = rows[i]
        cell = lambda c: row[c] if 0 <= c < len(row) else ""  # noqa: E731
        out.append(Entry(date=day_of(cell(match.date_col)) or dt.date.today().isoformat(), given=1,
                         car=cell(match.car_col).strip(), note=cell(product_col).strip(), source="site"))
    return out


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
