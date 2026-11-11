"""증빙의 학번 · 사번 — ERP 에서 사람을 찾을 때 번호가 있으면 번호로 먼저, 없으면 이름으로(담당자 2026-11-11:
"erp에서 사람 조회(참여인력, 내부인력, 외부참석자, 입금처 등등)할 때 증빙자료에 사번이나 학번이 있으면 그 번호로 먼저 조회를 하고 없으면 이름으로 조회").

같은 이름이 많다 — 인적정보조회에 한 이름이 12줄(제적 · 졸업한 옛 학생까지) 나온 적이 있다(2026-11-11 실측). 번호는 한 사람이다.
여기는 글자만 본다(Qt · Playwright · pypdf 없음). 파일을 읽는 것은 부르는 쪽(card.py · scholarship.py)이 한다.

번호로 보는 것:
- 이름표가 붙은 번호 — '학번 : 202412345' · '사번 123456' · '직번(123456)' · '교번' · '개인번호' · '학생번호'(6~13자리).
- 학번 꼴 — 20 으로 시작하는 9자리(입학 연도 — 명단 엑셀 학번이 이 꼴, CLAUDE.md 14절).
- 사람 이름과 **같은 줄**에 홀로 선 6~10자리 숫자(서명부 '1 컴퓨터공학과 홍길동 202412345' 꼴) — 날짜 · 금액 · 전화(하이픈 · 쉼표 · 점이 붙은 숫자)는 아니다.
고르는 것은 ERP 다 — 부르는 쪽이 목록의 번호와 **이름까지 같은** 줄 하나만 고른다. 그래서 여기서 엉뚱한 번호를 짝지어도 엉뚱한 사람이 들어가지는 않는다(번호로 못 찾고 이름으로 간다).
"""
from __future__ import annotations

import re

LABELS = ("학번", "사번", "직번", "교번", "개인번호", "학생번호", "교직원번호")
# 이름표 뒤 몇 글자 안의 번호 — '학번 : 202412345' · '사번(123456)' · '학번/사번 202412345'
LABELED_RE = re.compile(r"(?:" + "|".join(LABELS) + r")(?:\s*[/·,]\s*(?:" + "|".join(LABELS) + r"))?\s*[:：)(\]\[]?\s*\(?\s*(\d{6,13})(?![\d,.\-/:])")
STUDENT_RE = re.compile(r"(?<![\d\-.,:/])(20\d{7})(?![\d\-.,:/])")
# 줄 안에 홀로 선 6~10자리 — 앞뒤에 숫자 · 하이픈 · 쉼표 · 점 · 쌍점 · 빗금이 없을 것(날짜 · 금액 · 전화 · 계좌 · 시각이 아님)
BARE_RE = re.compile(r"(?<![\d\-.,:/])(\d{6,10})(?![\d\-.,:/])")


def clean(text) -> str:
    """숫자만 — 6~13자리일 때만(번호로 보지 않는 것은 '')."""
    digits = "".join(ch for ch in str(text or "") if ch.isdigit())
    return digits if 6 <= len(digits) <= 13 else ""


def labeled(text: str) -> list[str]:
    """이름표가 붙은 번호들(나온 차례, 같은 것은 한 번)."""
    out: list[str] = []
    for hit in LABELED_RE.finditer(str(text or "")):
        if hit.group(1) not in out:
            out.append(hit.group(1))
    return out


def student_like(text: str) -> list[str]:
    out: list[str] = []
    for hit in STUDENT_RE.finditer(str(text or "")):
        if hit.group(1) not in out:
            out.append(hit.group(1))
    return out


def ranked(texts, kinds: tuple[str, ...] = ("labeled", "student")) -> list[str]:
    """한 사람의 서류(개별증빙)에서 번호 후보 — 이름표가 붙은 것 먼저, 그다음 학번 꼴. 같은 무리 안에서는 많이 나온 것부터."""
    counts: dict[str, int] = {}
    tier: dict[str, int] = {}
    for text in texts:
        for rank, kind in enumerate(kinds):
            pattern = LABELED_RE if kind == "labeled" else STUDENT_RE if kind == "student" else None
            for no in (pattern.findall(str(text or "")) if pattern else []):      # 나온 만큼 센다
                counts[no] = counts.get(no, 0) + 1
                tier[no] = min(tier.get(no, rank), rank)
    return sorted(counts, key=lambda n: (tier[n], -counts[n], n))


def _phone_like(no: str) -> bool:
    return no.startswith("010") or no.startswith("01") and len(no) >= 10


def split_name(cell: str) -> tuple[str, str]:
    """회의록 이름 칸 '홍길동(202412345)' · '홍길동 202412345' · '202412345 홍길동' → (이름, 번호). 번호가 없으면 (칸 그대로, '')."""
    text = str(cell or "").strip()
    hit = re.search(r"\d[\d\s]{4,}\d", text)
    if not hit:
        return text, ""
    no = clean(hit.group())
    if not no:
        return text, ""
    name = (text[:hit.start()] + " " + text[hit.end():])
    name = re.sub(r"(?:" + "|".join(LABELS) + r")\s*[:：]?", " ", name)
    name = re.sub(r"[()\[\]{}:：/,·]", " ", name)
    return re.sub(r"\s+", " ", name).strip(), no


def _name_re(name: str) -> re.Pattern | None:
    chars = [c for c in str(name or "") if not c.isspace()]
    if len(chars) < 2:
        return None
    # 서명부 PDF 는 '홍 길 동' 처럼 글자 사이를 띄우기도 한다. 앞뒤가 한글이면 다른 낱말의 일부(이름이 '김수' 이고 글이 '김수진')
    return re.compile(r"(?<![가-힣])" + r"\s?".join(re.escape(c) for c in chars) + r"(?![가-힣])")


def _numbers_on(line: str) -> list[tuple[int, str]]:
    found: dict[int, str] = {}
    for hit in LABELED_RE.finditer(line):
        found[hit.start(1)] = hit.group(1)
    for hit in BARE_RE.finditer(line):
        if hit.start(1) not in found and not _phone_like(hit.group(1)):
            found[hit.start(1)] = hit.group(1)
    return sorted(found.items())


def pairs_in_text(text: str, names) -> list[tuple[str, str]]:
    """글에서 (이름, 번호) 짝 — 한 줄에 이름 하나 · 번호 하나면 그 둘, 이름 · 번호가 번갈아 같은 수로 나오면 차례로,
    이름만 있는 줄 바로 다음 줄이 번호 하나뿐이면 그 둘(표 칸이 줄마다 나뉘어 읽힌 PDF · .hwpx 칸 글자)."""
    patterns = [(name, _name_re(name)) for name in dict.fromkeys(n for n in names if n)]
    patterns = [(name, pat) for name, pat in patterns if pat is not None]
    out: list[tuple[str, str]] = []
    lines = str(text or "").splitlines()
    for i, line in enumerate(lines):
        hits: list[tuple[int, str]] = []
        for name, pat in patterns:
            hits += [(m.start(), name) for m in pat.finditer(line)]
        # 한 이름이 다른 이름에 들어 있으면('김수' · '김수진') 긴 것만 — 같은 자리를 두 이름이 잡지 않게
        hits.sort(key=lambda h: (h[0], -len(h[1])))
        names_at: list[tuple[int, str]] = []
        for pos, name in hits:
            if names_at and pos < names_at[-1][0] + len(names_at[-1][1].replace(" ", "")):
                continue
            names_at.append((pos, name))
        if not names_at:
            continue
        numbers = _numbers_on(line)
        if not numbers:
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
            if len(names_at) == 1 and re.fullmatch(r"\(?\d{6,13}\)?", nxt) and not _phone_like(clean(nxt)):
                out.append((names_at[0][1], clean(nxt)))
            continue
        if len(names_at) == 1 and len(numbers) == 1:
            out.append((names_at[0][1], numbers[0][1]))
            continue
        if len(names_at) != len(numbers):
            continue                                   # 한 줄에 이름 · 번호 수가 다르면 짝을 모른다
        marks = sorted([(p, "n", v) for p, v in names_at] + [(p, "d", v) for p, v in numbers])
        kinds = "".join(k for _p, k, _v in marks)
        if kinds == "nd" * len(names_at) or kinds == "dn" * len(names_at):
            for j in range(0, len(marks), 2):
                a, b = marks[j], marks[j + 1]
                out.append((a[2], b[2]) if a[1] == "n" else (b[2], a[2]))
    return out


def numbers_for_names(texts, names) -> dict[str, str]:
    """여러 글에서 이름마다 번호 — 한 이름에 번호가 둘 이상 나오거나 한 번호가 두 이름에 붙으면 그 이름은 뺀다(번호로 찾지 않고 이름으로).
    열쇠는 띄어쓰기를 뺀 이름."""
    by_name: dict[str, set[str]] = {}
    by_no: dict[str, set[str]] = {}
    for text in texts:
        for name, no in pairs_in_text(text, names):
            key = re.sub(r"\s+", "", name)
            by_name.setdefault(key, set()).add(no)
            by_no.setdefault(no, set()).add(key)
    return {key: next(iter(nos)) for key, nos in by_name.items()
            if len(nos) == 1 and len(by_no[next(iter(nos))]) == 1}
