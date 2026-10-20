"""참여연구원 명단 · 회의 참석자 나누기 — 카드청구 회의비(17)의 ERP 회의록등록 창에 참석자를 넣을 때(담당자 2026-10-20).

담당자 규칙: 회의록의 소속이 **비었거나 · 강원대학교 · 학과명**이면 참여인력이나 내부참석자에서 검색하고, **그 밖의 소속은 외부참석자**로 쓴다.
참여인력인지는 ERP '참여연구원 현황표' 출력물(Prn_PrjPartInfo.xlsx · .pdf — 담당자가 보낸 첨부)로 본다. 둘 다 한 사람이 두 줄이다:
윗줄 '이름 소속 역할 …', 아랫줄 '(직번) 참여시작일 …'. 직번은 사번 6자리 · 학번 9자리 · 그 밖 13자리까지 있었다(실측 2026-10-20).
실명 · 직번이 든 파일이라 저장소에 올리지 않는다 — 위치는 설정(participants_file)이나 카드 폴더에서 찾는다.

Qt · Playwright 없음. pypdf · openpyxl 은 쓸 때만 들여온다.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

EMP_LINE_RE = re.compile(r"^\s*\((\d{5,13})\)")
NAME_RE = re.compile(r"^[가-힣]{2,6}$|^[A-Za-z][A-Za-z .'-]{1,40}$")
FILE_WORDS = ("참여연구원", "참여인력", "PrjPartInfo")
SUFFIXES = (".xlsx", ".xlsm", ".pdf")
HOME_ORG_WORDS = ("강원대",)
# 학교 안 조직 — 소속 칸에 학교 이름 없이 이렇게만 적힌 경우(담당자: '학과명이면' 내부)
# 현황표 PDF 는 긴 학과명을 꺾어 '정보보호학' 처럼 끝이 잘리기도 한다 — '…학' 으로 끝나도 학교 안으로 본다
DEPT_RE = re.compile(r"(학과|학부|전공|대학원|사업단|산학협력단|대학|학)$")


@dataclass
class Member:
    name: str
    emp_no: str = ""
    dept: str = ""


@dataclass
class Attendee:
    name: str
    org: str = ""
    kind: str = ""                 # 'part'(참여인력) · 'internal'(내부참석자) · 'external'(외부참석자)
    emp_no: str = ""               # 참여인력이면 명단의 직번
    note: str = ""

    @property
    def kind_name(self) -> str:
        return {"part": "참여인력", "internal": "내부참석자", "external": "외부참석자"}.get(self.kind, "?")

    def label(self) -> str:
        return f"{self.name}" + (f"({self.emp_no})" if self.emp_no else "") + (f" · {self.org}" if self.org else "")


def _squash(text) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def read_pdf_text(text: str) -> list[Member]:
    """현황표 PDF 글자 → 사람들. '(직번)' 줄 앞까지가 그 사람의 윗줄(이름 · 소속 · 역할 …, 소속이 길면 여러 줄로 꺾인다)."""
    out: list[Member] = []
    block: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or re.fullmatch(r"\d+\s*/\s*\d+", line):          # 쪽 번호 '1/4'
            continue
        if "참여시작일" in line or "참여종료일" in line:                 # 첫 쪽 머리글 — 그 앞은 과제 머리
            block = []
            continue
        hit = EMP_LINE_RE.match(line)
        if not hit:
            block.append(line)
            continue
        tokens = block[0].split() if block else []
        if tokens and NAME_RE.match(tokens[0]):
            rest = " ".join(tokens[1:] + block[1:])
            out.append(Member(tokens[0], hit.group(1), rest.split()[0] if rest.split() else ""))
        block = []
    return out


def read_pdf(path: str) -> list[Member]:
    try:
        from pypdf import PdfReader
        reader = PdfReader(path)
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception:  # noqa: BLE001 — 못 읽으면 빈 명단(참여인력 여부는 사람이)
        return []
    return read_pdf_text(text)


def read_xlsx(path: str) -> list[Member]:
    """현황표 엑셀 — A열에 윗줄 이름, 바로 아랫줄 A열이 '(직번)'. B열이 소속."""
    try:
        import openpyxl
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception:  # noqa: BLE001
        return []
    out: list[Member] = []
    try:
        for sheet in workbook.worksheets:
            prev = None
            for row in sheet.iter_rows(values_only=True):
                first = str(row[0]).strip() if row and row[0] is not None else ""
                hit = EMP_LINE_RE.match(first)
                if hit and prev and NAME_RE.match(str(prev[0] or "").strip()):
                    out.append(Member(str(prev[0]).strip(), hit.group(1),
                                      str(prev[1]).strip() if len(prev) > 1 and prev[1] is not None else ""))
                prev = row
    finally:
        workbook.close()
    return out


def read(path: str) -> list[Member]:
    if not path or not os.path.isfile(path):
        return []
    return read_pdf(path) if path.lower().endswith(".pdf") else read_xlsx(path)


def find_file(setting: str, *folders: str) -> str:
    """설정의 파일 → 없으면 카드 폴더 · 그 위 폴더에서 이름에 '참여연구원' · 'PrjPartInfo' 가 든 엑셀 · PDF."""
    if setting and os.path.isfile(setting):
        return setting
    for folder in folders:
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            continue
        for name in names:
            if name.lower().endswith(SUFFIXES) and not name.startswith(("~$", ".")) and any(w.lower() in name.lower() for w in FILE_WORDS):
                return os.path.join(folder, name)
    return ""


def is_internal_org(org: str) -> bool:
    """담당자 규칙 — 소속이 비었거나 · 강원대(학교) · 학과명(학교 이름 없이 학과 · 학부 · 사업단 …)이면 학교 안 사람."""
    text = _squash(org)
    if not text:
        return True
    if any(word in text for word in HOME_ORG_WORDS):
        return True
    if re.search(r"대학교|대학원대학|기업|회사|㈜|\(주\)|재단|협회|공사|공단|연구원$|청$|시청|도청|군청", text):
        return False                   # 다른 학교 · 회사 · 기관
    return bool(DEPT_RE.search(text))


def classify(attendees: list[tuple[str, str]], members: list[Member]) -> list[Attendee]:
    """회의록 참석자 (소속, 이름) → 참여인력 · 내부참석자 · 외부참석자. 참여인력은 명단에 이름이 **하나**만 있을 때만(동명이인이면 내부참석자로 두고 알림)."""
    by_name: dict[str, list[Member]] = {}
    for m in members:
        by_name.setdefault(_squash(m.name), []).append(m)
    out = []
    for org, name in attendees:
        found = by_name.get(_squash(name), [])
        if not is_internal_org(org):
            note = "참여연구원 명단에 같은 이름이 있음 — 소속이 학교 밖이라 외부참석자로" if found else ""
            out.append(Attendee(name, org, "external", note=note))
        elif len(found) == 1:
            out.append(Attendee(name, org, "part", found[0].emp_no))
        elif len(found) > 1:
            out.append(Attendee(name, org, "internal", note=f"참여연구원 명단에 같은 이름이 {len(found)}명 — 직번을 보고 고르세요"))
        else:
            out.append(Attendee(name, org, "internal"))
    return out
