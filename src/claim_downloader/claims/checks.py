"""확인할 것 한 건 — 무엇이 · 어디서(파일 · 행 · 칸) · 어떻게 하면 되는지와 그 무게(고칠 것 · 확인 · 참고).

담당자 2026-11-11(장학금 미리 보기 그림): "확인필요한 사항을 잘 읽을 수 있게 구별되게 보여주세요 뭘 어디서 어떤걸 확인해야 하는지 모르겠잖아요" ·
"확인필요 세부사항은 목록 위에서만 보여지도록". 전에는 '21행 <이름>: 금액이 없음' · '외국인(UZ) — 국적은 앱이 고름' 같은 글이 한 줄씩이라
어느 파일의 21행인지, 할 일이 있는 것인지(외국인은 앱이 하는 것) 알 수 없었다.

`Note` 는 str 이다 — 글(옛 problems() 의 한 줄)로 쓰던 곳(기록 · 넣기를 막는 검사 · 패널)은 그대로 두고, 화면만 칸을 나눠 그린다.
글자 하나 바뀌지 않게 옛 글을 그대로 text 로 둔다. Qt 없음.
"""
from __future__ import annotations

FIX, CHECK, INFO = "fix", "check", "info"
LEVELS = {FIX: "고칠 것", CHECK: "확인", INFO: "참고"}
ORDER = {FIX: 0, CHECK: 1, INFO: 2}


class Note(str):
    """한 줄 글 + 무엇(what) · 어디서(where) · 할 일(todo) · 무게(level) · 명단의 몇 번째 사람(person, 없으면 None).
    level: fix = 넣기 전에 고쳐야 넣을 수 있음 · check = 사람이 보고 판단(넣기는 막지 않음) · info = 앱이 알아서 함 — 할 일 없음."""

    level: str
    what: str
    where: str
    todo: str
    person: int | None

    def __new__(cls, text: str, *, level: str = CHECK, what: str = "", where: str = "", todo: str = "",
                person: int | None = None) -> "Note":
        self = super().__new__(cls, text)
        self.level = level if level in LEVELS else CHECK
        self.what = what or str(text)
        self.where = where
        self.todo = todo
        self.person = person
        return self

    @property
    def level_name(self) -> str:
        return LEVELS[self.level]


def as_note(text, **defaults) -> Note:
    """Note 면 그대로, 글이면 무게 · 어디서를 기본값으로 — 다른 곳에서 온 알림도 같은 칸으로 그리게."""
    return text if isinstance(text, Note) else Note(str(text), **defaults)


def ordered(notes) -> list[Note]:
    """고칠 것 → 확인 → 참고, 같은 무게는 들어온 차례. 같은 사람의 같은 글은 한 번 — 사람이 다르면 글이 같아도 따로
    (한 학생의 교과목 줄 둘에 같은 알림이 붙는다)."""
    seen: dict[tuple, Note] = {}
    for n in notes:
        note = as_note(n)
        seen.setdefault((str(note), note.person), note)
    return sorted(seen.values(), key=lambda n: ORDER[n.level])


def counts(notes) -> dict[str, int]:
    out = {FIX: 0, CHECK: 0, INFO: 0}
    for n in notes:
        out[as_note(n).level] += 1
    return out


def count_text(notes) -> str:
    """'고칠 것 1 · 확인 2 · 참고 1' — 0 인 것은 빼고."""
    c = counts(notes)
    return " · ".join(f"{LEVELS[k]} {c[k]}" for k in (FIX, CHECK, INFO) if c[k])
