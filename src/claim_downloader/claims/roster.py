"""장학금 지급 명단 엑셀 읽기 — 담당자가 달마다 고쳐 쓰는 표(CLAUDE.md 14절 '장학금 지급 명단').

열 위치를 고정하지 않는다. 담당자 양식이라 유형마다 열이 다르다(실측 2026-10-14: (가)형은 연번·이름·학번·은행·계좌·단가·시간·금액,
(나)형 TA 는 강좌명 열이 끼고 연락처·이메일이 더 있다). 그래서 머리글 글자(공백을 뺀 것)로 열을 찾는다. 머리글은 두 줄일 수 있다
(3행 '산출내역' + 4행 '금액(C=A*B)') — 두 줄을 이어 붙여 본다.

(나)형처럼 한 학생이 두 줄(강좌 둘)이면 이름·학번·은행·계좌 칸이 세로 병합돼 둘째 줄이 비어 있다 — 앞 줄 값을 내려 채운다.
마지막 '합계' 행은 건너뛴다. 앱이 쓰는 값은 이름·학번·금액(·강좌명) 뿐이고 계좌는 ERP 가 채운 값과 **대조만** 한다.

이 파일에 실명·학번은 없다. 테스트는 openpyxl 로 가짜 표를 만든다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# 머리글 글자(공백 제거 뒤) → 열 뜻. 앞에 있는 것이 우선.
HEADERS = {
    "name": ("이름", "성명", "성명(한글)"),
    "student_no": ("학번", "사번", "학번/사번", "학번(사번)", "직번"),
    "bank": ("은행", "은행명", "금융기관"),
    "account": ("계좌", "계좌번호"),
    "amount": ("금액(C=A*B)", "지급금액", "지급액", "금액", "청구액"),
    "course": ("강좌명", "강좌", "교과목명", "교과목", "과목명", "과목"),
}
TOTAL_WORDS = ("합계", "총계", "계")
MAX_HEADER_SCAN = 12          # 머리글은 위쪽 열두 줄 안에 있다


@dataclass
class Person:
    name: str
    student_no: str = ""          # 숫자만. 9자리면 학번(인적정보 탭), 6자리면 사번(참여인력 탭)
    amount: int | None = None
    bank: str = ""
    account: str = ""             # 적힌 그대로(하이픈 포함). 대조는 digits() 로
    course: str = ""              # (나)형 TA 의 강좌명(교과목) — 행 적요에 들어간다
    row: int = 0                  # 엑셀 행 번호 (사람에게 알려 줄 때)
    note: str = ""                # 이 사람 줄의 문제 (학번 없음 등)

    @property
    def account_digits(self) -> str:
        return re.sub(r"\D", "", self.account)


@dataclass
class Roster:
    path: str
    title: str = ""               # B2 제목 — 대표적요의 바탕
    kind: str = ""                # 제목의 '(가)형' 같은 유형 글자: '가' '나' …
    people: list[Person] = field(default_factory=list)
    sheet_total: int | None = None    # 표의 '합계' 행에 적힌 금액
    columns: dict = field(default_factory=dict)   # 열 뜻 → 열 번호 (1부터)
    warnings: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(p.amount or 0 for p in self.people)

    def problems(self) -> list[str]:
        """넣기 전에 사람이 봐야 할 것. 비어 있으면 넣어도 된다."""
        out = list(self.warnings)
        if not self.people:
            out.append("명단에 사람이 없습니다")
        if self.sheet_total is not None and self.sheet_total != self.total:
            out.append(f"표의 합계({self.sheet_total:,})와 금액을 더한 값({self.total:,})이 다릅니다")
        out.extend(self.duplicate_problems())
        for p in self.people:
            if p.note:
                out.append(f"{p.row}행 {p.name}: {p.note}")
        return out


    def duplicate_problems(self) -> list[str]:
        """같은 이름 · 같은 학번 줄 — 담당자 규칙(2026-10-14): 학번이 다르면 다른 학생(동명이인)이라 문제없고,
        학번까지 같은데 교과목이 다르면 한 학생이 여러 교과목 TA 를 한 것이라 문제없다. 학번 · 교과목까지 같으면 같은 줄이
        두 번 들어간 것일 수 있어 알린다. 학번이 같은데 이름이 다르면 명단을 잘못 쓴 것일 수 있어 알린다."""
        out: list[str] = []
        seen: dict[tuple[str, str, str], Person] = {}
        names_by_no: dict[str, set[str]] = {}
        for p in self.people:
            if not p.student_no:
                continue                  # 학번 없음은 그 줄의 note 로 따로 알린다
            name = norm(p.name)
            names_by_no.setdefault(p.student_no, set()).add(name)
            key = (name, p.student_no, norm(p.course))
            if key in seen:
                first = seen[key]
                what = f"교과목 '{p.course}' 까지 같은" if p.course else "같은"
                out.append(f"{first.row}행 · {p.row}행 {p.name}(학번 {p.student_no}) — {what} 줄이 둘입니다. 중복인지 확인하세요")
            else:
                seen[key] = p
        for no, names in names_by_no.items():
            if len(names) > 1:
                out.append(f"학번 {no} 인데 이름이 다릅니다: " + " · ".join(sorted(names)))
        return out


def norm(text) -> str:
    """머리글 비교용 — 공백·줄바꿈을 걷어낸다. '이   름' == '이름'."""
    return re.sub(r"\s+", "", str(text if text is not None else ""))


def digits(text) -> str:
    return re.sub(r"\D", "", str(text if text is not None else ""))


def kind_of(title: str) -> str:
    """'2026년도 7월 (가)형 근로장학금 지급내역' → '가'. 없으면 ''."""
    hit = re.search(r"\(([가-힣])\)\s*형", str(title or ""))
    return hit.group(1) if hit else ""


def _to_int(value) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(round(value))
    text = str(value).strip()
    num = re.sub(r"[^\d.\-]", "", text)
    if not num or num in ("-", "."):
        return None
    try:
        return int(round(float(num)))
    except ValueError:
        return None


def _header_key(label: str) -> str | None:
    """두 줄을 이어 붙인 머리글 글자에서 열 뜻을 찾는다. 정확히 같은 것 → 담고 있는 것 순."""
    if not label:
        return None
    for key, words in HEADERS.items():
        if label in words:
            return key
    for key, words in HEADERS.items():
        if key == "amount" and ("단가" in label or "시간" in label):
            continue
        if any(w in label for w in words):
            return key
    return None


def _find_header(ws) -> tuple[int, dict]:
    """(머리글 행 번호, 열 뜻 → 열 번호). 이름 열과 학번 열이 함께 있는 첫 줄을 머리글로 본다."""
    for r in range(1, min(ws.max_row, MAX_HEADER_SCAN) + 1):
        columns: dict[str, int] = {}
        for c in range(1, ws.max_column + 1):
            top = norm(ws.cell(r, c).value)
            below = norm(ws.cell(r + 1, c).value) if r < ws.max_row else ""
            # 윗줄 글자가 먼저. 윗줄이 비었거나(세로 병합 아래 칸) '산출내역' 같은 묶음 머리면 둘째 줄 글자를 본다
            key = _header_key(top) or (_header_key(below) if below else None)
            if key and key not in columns:
                columns[key] = c
        if "name" in columns and "student_no" in columns and _header_key(norm(ws.cell(r, columns["name"]).value)) == "name":
            return r, columns
    return 0, {}


def _is_header_row(ws, r: int, columns: dict) -> bool:
    """머리글 둘째 줄인지 — 이름 칸이 비어 있고 글자 칸이 있으면."""
    name = ws.cell(r, columns["name"]).value
    if name not in (None, ""):
        return False
    return any(isinstance(ws.cell(r, c).value, str) and ws.cell(r, c).value.strip() for c in range(1, ws.max_column + 1))


def _title_above(ws, header_row: int) -> str:
    """머리글 위에서 가장 긴 글자 칸 — B2 제목."""
    best = ""
    for r in range(1, header_row):
        for c in range(1, ws.max_column + 1):
            value = ws.cell(r, c).value
            if isinstance(value, str) and len(value.strip()) > len(best):
                best = value.strip()
    return best


def read(path, sheet: str | None = None) -> Roster:
    """명단 엑셀을 읽는다. 못 읽으면 warnings 에 이유를 적고 사람 없는 Roster 를 돌려준다."""
    roster = Roster(path=str(path))
    try:
        import openpyxl
    except ImportError:
        roster.warnings.append("openpyxl 이 없어 엑셀을 읽지 못합니다 — 앱 준비 단계를 다시 돌리세요")
        return roster
    try:
        wb = openpyxl.load_workbook(str(path), data_only=True, read_only=False)
    except Exception as error:  # noqa: BLE001 — 열려 있는 파일 · 깨진 파일
        roster.warnings.append("엑셀을 열지 못했습니다: " + (str(error).splitlines()[0][:100] if str(error) else "오류"))
        return roster
    try:
        ws = wb[sheet] if sheet else wb[wb.sheetnames[0]]
        header_row, columns = _find_header(ws)
        if not header_row:
            roster.warnings.append("머리글(이름 · 학번)이 있는 줄을 찾지 못했습니다. 첫 시트에 명단 표가 있어야 합니다")
            return roster
        roster.columns = columns
        roster.title = _title_above(ws, header_row)
        roster.kind = kind_of(roster.title)
        start = header_row + 1
        if start <= ws.max_row and _is_header_row(ws, start, columns):
            start += 1
        last: Person | None = None
        for r in range(start, ws.max_row + 1):
            cells = {key: ws.cell(r, c).value for key, c in columns.items()}
            name = str(cells.get("name") or "").strip()
            amount = _to_int(cells.get("amount"))
            if norm(name) in TOTAL_WORDS or (not name and any(norm(ws.cell(r, c).value) in TOTAL_WORDS for c in range(1, columns["name"] + 1))):
                roster.sheet_total = amount
                break
            if not name and amount is None:
                continue                       # 빈 줄
            person = Person(name=name, row=r, amount=amount,
                            student_no=digits(cells.get("student_no")),
                            bank=str(cells.get("bank") or "").strip(),
                            account=str(cells.get("account") or "").strip(),
                            course=str(cells.get("course") or "").strip())
            if not name and last is not None:
                # 병합된 둘째 줄 — 이름·학번·은행·계좌를 앞 줄에서 내려받는다 ((나)형 TA: 한 학생이 두 강좌)
                person.name, person.student_no = last.name, last.student_no
                person.bank, person.account = person.bank or last.bank, person.account or last.account
            if not person.name:
                continue
            if not person.student_no:
                person.note = "학번이 없음 — 소득자는 직접 고르세요"
            elif len(person.student_no) not in (6, 9):
                person.note = f"학번 자릿수가 이상함({len(person.student_no)}자리)"
            if person.amount is None or person.amount <= 0:
                person.note = (person.note + " · " if person.note else "") + "금액이 없음"
            roster.people.append(person)
            last = person
    finally:
        try:
            wb.close()
        except Exception:  # noqa: BLE001
            pass
    if not roster.title:
        roster.warnings.append("표 위에 제목(예: 2026년도 7월 (가)형 근로장학금 지급내역)이 없습니다 — 대표적요를 직접 적으세요")
    return roster


def summary_lines(roster: Roster) -> list[str]:
    out = [f"명단: {Path(roster.path).name}", f"제목: {roster.title or '—'}" + (f"  (유형 {roster.kind})" if roster.kind else ""),
           f"사람 {len(roster.people)}명 · 합계 {roster.total:,}원"]
    return out
