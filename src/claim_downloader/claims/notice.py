"""지급 공문 읽기 — 개인 지급(일반청구 탭 · 증빙 기타) 폴더의 공통증빙에서 내부결재 공문 PDF 를 찾아 비목 · 제목 · 금액을 뽑는다.

담당자 요청(2026-10-19): "자동으로 개별이랑 공통증빙 폴더 파일 탐색해서 지급 공문의 비목이랑 적요 찾고 지급내역이 있으면 지급내역대로".
공문은 전자결재 PDF 라 글자가 있다(청구서 PDF 의 첨부 쪽에서 `1. 관련: …` 으로 시작하는 공문 글자를 pypdf 로 읽었다 — CLAUDE.md 14절).
AI 를 쓰지 않는다 — 글자에서 ERP 비목 이름(표기 여럿)과 '제목' 줄 · '금 …원' 을 찾을 뿐이다. 못 찾으면 비워 두고 화면에서 사람이 고른다.

공문의 실제 글자 배치는 아직 못 봤다(추정: '제목 …' 줄 · '예산과목: …비' 줄 · '금 1,000,000원'). 그래서 여러 꼴을 받아 주고,
찾은 근거를 note 로 남겨 화면 · 로그에 보인다. 이 파일에 실제 공문 글자는 없다.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from ..naming import BIMOK_ALT, BIMOK_NM, normnm
from .schema import _CATEGORY_ALIASES, CATEGORY_CODES

# 파일 이름 점수 — 공문은 '…지급.pdf' · '…공문.pdf' · '내부결재' 같은 이름이다. 명단 · 신청서 · 증빙 사진은 공문이 아니다.
NAME_PLUS = (("공문", 4), ("내부결재", 3), ("결재", 1), ("지급", 2), ("계획", 1), ("시행", 1))
NAME_MINUS = ("지급내역", "지원내역", "명단", "신청서", "영수증", "통장", "신분증", "증명서", "동의서", "사진", "근무일지",
              "견적서", "거래명세", "세금계산서", "이력서", "청구서")
# 비목이 적히는 줄의 말 — 이 줄에서 찾은 비목을 먼저 믿는다
CATEGORY_LINE_WORDS = ("비목", "예산과목", "예산", "과목", "세목", "지출항목", "집행항목", "편성")
AMOUNT_LINE_WORDS = ("금액", "지급액", "지원액", "합계", "총", "금 ", "소요")
TITLE_RE = re.compile(r"^\s*제\s*목\s*[:：]?\s*(.*)$")
AMOUNT_RE = re.compile(r"(?<![\d,])(\d{1,3}(?:,\d{3})+|\d{4,})\s*원")
# 제목 끝의 '지급' · '지급(안)' · '지급 계획' — 대표적요에는 넣지 않는다('…근로장학금 지급' → 대표적요 '02_…근로장학금', 14절)
TITLE_TAIL_RE = re.compile(r"\s*지급\s*(\(안\)|\(案\)|계획\s*(\(안\))?|요청|품의|알림|건)?\s*$")


def _category_names() -> dict[str, set[str]]:
    """비목 번호 → 공문에 적힐 수 있는 이름들(공백 · 가운뎃점 뗀 것). ERP 보기 · 보관 폴더 이름 · 다른 표기."""
    out: dict[str, set[str]] = {}
    for code, name in CATEGORY_CODES.items():
        names = {name, BIMOK_NM.get(code, "")} | set(BIMOK_ALT.get(code, [])) | set(_CATEGORY_ALIASES.get(code, []))
        out[code] = {normnm(n) for n in names if normnm(n)}
    return out


CATEGORY_NAMES = _category_names()


@dataclass
class Notice:
    path: str = ""
    title: str = ""               # 제목 줄 그대로
    category: str = ""            # ERP 비목 보기 글자 — 못 정하면 ''
    code: str = ""                # 비목 번호(01~10)
    amount: int | None = None     # 공문에 적힌 금액(가장 큰 것) — 명단 합계와 맞춰 본다
    notes: list[str] = field(default_factory=list)

    @property
    def clean_title(self) -> str:
        return TITLE_TAIL_RE.sub("", re.sub(r"\s+", " ", self.title)).strip()

    def lines(self) -> list[str]:
        if not self.path:
            return ["지급 공문: 찾지 못함"] + self.notes
        out = [f"지급 공문: {os.path.basename(self.path)}",
               f"  제목: {self.title or '찾지 못함'}",
               f"  비목: {self.category or '찾지 못함'}" + (f" ({self.code})" if self.code else ""),
               f"  금액: {self.amount:,}원" if self.amount else "  금액: 찾지 못함"]
        return out + ["  " + n for n in self.notes]


def _name_score(path: str) -> int:
    name = os.path.basename(path).replace(" ", "")
    if any(word in name for word in NAME_MINUS):
        return -5
    return sum(points for word, points in NAME_PLUS if word in name)


def _text_score(text: str) -> int:
    score = 0
    lines = text.splitlines()
    if any(TITLE_RE.match(line) for line in lines):
        score += 3
    if "수신" in text:
        score += 1
    if "붙임" in text or "끝." in text:
        score += 1
    if categories_in(text):
        score += 2
    return score


def categories_in(text: str) -> list[str]:
    """글에 나온 비목 번호들 — 나온 차례대로, 겹치지 않게."""
    flat = normnm(text)
    found: list[tuple[int, str]] = []
    for code, names in CATEGORY_NAMES.items():
        hits = [flat.find(n) for n in names if n and n in flat]
        if hits:
            found.append((min(hits), code))
    return [code for _pos, code in sorted(found)]


def read_title(text: str) -> str:
    lines = [line.strip() for line in text.splitlines()]
    for i, line in enumerate(lines):
        hit = TITLE_RE.match(line)
        if not hit:
            continue
        title = hit.group(1).strip()
        if not title:                          # '제목' 과 제목이 다른 줄로 뽑힌 PDF
            title = next((x for x in lines[i + 1:] if x), "")
        if title:
            return re.sub(r"\s+", " ", title)
    return ""


def read_category(text: str) -> tuple[str, str]:
    """(비목 번호, 근거). 비목이 적힌 줄(예산과목 · 비목 …)의 이름을 먼저 믿고, 없으면 글 전체에 딱 하나 나온 이름. 여럿이면 ''."""
    keyed: list[str] = []
    for line in text.splitlines():
        if any(word in line.replace(" ", "") for word in CATEGORY_LINE_WORDS):
            for code in categories_in(line):
                if code not in keyed:
                    keyed.append(code)
    if len(keyed) == 1:
        return keyed[0], "비목이 적힌 줄"
    every = categories_in(text)
    if len(keyed) > 1:
        return "", "비목 줄에 비목이 여럿: " + ", ".join(CATEGORY_CODES[c] for c in keyed)
    if len(every) == 1:
        return every[0], "공문에 나온 비목 이름"
    if every:
        return "", "공문에 비목 이름이 여럿: " + ", ".join(CATEGORY_CODES[c] for c in every)
    return "", "공문에서 비목 이름을 찾지 못함"


def read_amount(text: str) -> int | None:
    best = None
    for line in text.splitlines():
        if not any(word in line for word in AMOUNT_LINE_WORDS):
            continue
        for hit in AMOUNT_RE.finditer(line):
            value = int(hit.group(1).replace(",", ""))
            best = value if best is None or value > best else best
    return best


def find(paths: list[str], read_texts=None) -> Notice:
    """paths(공통증빙 · 폴더 바로 아래 파일) 중 지급 공문을 골라 읽는다. read_texts(paths) → 글 목록(테스트가 바꿔 끼운다)."""
    if read_texts is None:
        from .scholarship import _pdf_texts
        read_texts = _pdf_texts
    pdfs = [p for p in paths if str(p).lower().endswith(".pdf") and _name_score(p) > -5]
    best: tuple[int, str, str] | None = None
    for path in sorted(pdfs, key=lambda p: -_name_score(p))[:12]:      # 이름이 공문 같은 것부터 열두 개까지
        texts = read_texts([path])
        text = texts[0] if texts else ""
        if not text.strip():
            continue                                                  # 스캔 PDF — 글자가 없다
        score = _name_score(path) + _text_score(text)
        if best is None or score > best[0]:
            best = (score, path, text)
    notice = Notice()
    if best is None or best[0] < 3:
        notice.notes.append("공통증빙에서 글자가 있는 지급 공문 PDF 를 찾지 못했습니다 — 비목은 직접 고르세요")
        return notice
    _score, notice.path, text = best
    notice.title = read_title(text)
    notice.code, why = read_category(text)
    notice.category = CATEGORY_CODES.get(notice.code, "")
    if not notice.code:
        notice.notes.append(why + " — 비목은 직접 고르세요")
    notice.amount = read_amount(text)
    return notice
