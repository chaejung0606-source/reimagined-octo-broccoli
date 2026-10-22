"""구매요청(계약) 서류 받기 — ERP 구매·자산 메뉴에서 구매요청 때 올린 첨부 · 검사처리 때 올린 첨부 · 물품 사진을 받아 과제별 폴더에 둔다.

담당자(2026-10-22): "구매요청시 업로드한 서류와 검사처리시 업로드한 서류" 둘을, "상태 상관없이 첨부문서가 있다면", 물품 사진도("물품등록할 경우 물품사진을
다운받을 수 있습니다"), ERP 에서 과제를 고르지 않고 구매·자산 메뉴로 바로 들어가 **앱에서 고른 과제의 과제기간**으로 일자 범위를 두고(2년씩 —
"구매요청일자는 최대2년까지 가능함" · 실제 [검색] 처리기 `fn_validation` 이 730일을 넘으면 알림), 받은 것은 **과제별로** `구매요청(계약) 서류\\` 아래에.
실측은 CLAUDE.md 23절(2026-10-22 1 · 2 · 9~12 · 14 · 15 · 18 · 19번) — 값의 이름은 거기서 가져왔다:

- 구매진행관리 목록 `rexpe_0155_01.act`(IBSheet 8 — TreeGrid 바탕): 줄은 `IBSheet[0].getDataRows()`, 값은 `getValue(줄, 열)`, 열은 `PURCH_REQ_NO` 구매요구번호 ·
  `PRJ_NO` 대표과제번호 · `REQ_DT` 요청일자 · `PURCH_CONT` 내용(대표건명) · `PURCH_PROG_STS_NM` 진행상태 · `PURCH_KIND_NM` 구분 · `PURCH_AMT` 구매요구액 ·
  `CONT_NO` · `CONT_PROG_STS_NM` · `chk` 선택. [상세조회/변경](`#btnDetail`)의 처리기는 `sheet.getRowsByChecked("chk")` 가 **하나**일 때 그 건의 상세
  (구매요구서작성 `rexpe_0156_01.act`, `#PROC_TYP_CD`=C10)를 **같은 프레임 자리**에 띄운다(19번 실측) — 그래서 그 줄의 `chk` 만 1 로 두고 단추를 누른다.
  상세의 증빙문서는 `a[href*="comm0008_01.act"][href*="ATTFILE_SEQ_NO"]` 링크(글자 = 파일 이름, PDF · xlsx …). `#btnList` 로 목록으로 돌아온다.
- 검사처리 `rexpe_0201_01.act`(JGM 그리드): 줄마다 `k_PURCH_REQ_NO` · `k_CONT_NM` · `k_CONT_DT` · 행 라디오. 줄을 고르면 아래 숨은 `#PURCH_REQ_NO` ·
  `#PRJ_NO` 가 채워지고 첨부 표의 `a.btn_lnk` 링크(같은 주소 모양) · 물품정보 표(`k_CONT_ITEM_NM_KR`)가 보인다. 물품정보 줄을 **더블클릭**하면
  물품내역팝업(`rexpe_0054_t01_02.act`, 별도 창) — 숨은 `#IMGFILE_SEQ_NO` · `#IMGFILE_SEQ_NO2` 와 `<img id="USER_PICTURE" src="/comm0008_01.act?…&PROC_CD=preview">`
  (둘째 사진이 없으면 `img_noimage.png`). 사진은 그 주소를 같은 묶음의 쿠키로 바로 받는다(오른쪽 클릭 저장 대신).
- 파일은 `page.request.get(주소)`(같은 브라우저 묶음의 쿠키)로 받아 **이름 그대로** 둔다. 같은 이름이 이미 있으면 받지 않는다(이것이 중복 방지 —
  문서번호 같은 열쇠가 없다). 출력물([구매요청서])은 받지 않는다(담당자).

**누르는 것**(tests/test_safety.py): 위 메뉴 `#menu_id_3` '구매·자산' · 왼쪽 메뉴 글자 '구매진행관리' · '검사처리' · 위쪽 탭 '구매진행관리' · '검사처리' ·
목록 [검색](`#btnSearch`) · 줄의 `chk`(IBSheet setValue — 선택 칸뿐) · [상세조회/변경](`#btnDetail`) · [진행관리목록](`#btnList`) · 검사처리 줄의 라디오 ·
물품정보 줄 더블클릭. 값을 넣는 칸은 조회 조건의 일자(`#START_DATE` · `#END_DATE`)뿐. 등록 · 삭제 · 저장 · 구매요청 · 취소 · 검사처리(취소) · 완료 ·
첨부 추가/삭제 · 사진등록/삭제 · [구매진행상세] · [구매요청서] 는 누르지 않는다. Playwright 를 들여오지 않는다(브라우저를 띄우는 곳은 session.py 하나) —
프레임 · 창 객체의 evaluate · dblclick · request 만 쓴다. Qt 없음.
"""
from __future__ import annotations

import datetime as dt
import errno
import mimetypes
import os
import json
import re
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin

from . import naming, navigate, project_folders, settings

KIND = "purchase"                      # 받기 표의 줄 종류 — 청구서 줄과 섞여 들어간다(session.download 가 가른다)
FOLDER_NAME = "구매요청(계약) 서류"     # 저장 폴더 바로 아래, 과제 폴더 옆(담당자가 만들어 둔 이름)
INSPECT_DIR = "검사처리"               # 건 폴더 안 — 검사처리 때 올린 첨부 · 물품 사진
MAX_DAYS = 730                         # 구매요청일자 조회 한도(실측 19번 fn_validation: dayLimit = 730)
LIST_TRIES = 40                        # 0.5초씩 — 메뉴를 누른 뒤 목록 · 상세 · 검사처리 화면이 뜨기를 기다리는 횟수
SETTLE_TRIES = 30                      # [검색] 뒤 줄 수가 두 번 연달아 같을 때까지
POPUP_TIMEOUT_MS = 8000
# 상세(구매요구서작성)의 증빙문서 표는 화면이 뜬 뒤 따로 그려진다 — 2026-10-22 실제: 같은 건이 19:28 에는 '증빙문서 0개', 20:05 에는 7개.
# 링크 수가 DETAIL_STABLE 번 연달아 같아야 읽은 것으로 보고, 0개면 DETAIL_MIN_EMPTY 번(0.5초씩)은 더 기다린다.
DETAIL_STABLE = 3
DETAIL_MIN_EMPTY = 8
DETAIL_MAX_TRIES = 20
# 끝까지 받은 건 기록의 판 — 증빙문서를 일찍 읽어 '0개' 로 끝난 건이 '다 받음' 으로 남았을 수 있어(위) 판 2 부터 새로 쌓는다
DONE_VERSION = 2
MIN_FREE = 1 << 30                     # 1GB — 한 건에 수십 MB 파일이 여럿이라 이보다 적게 남은 곳에서는 받지 않는다
SYSTEM_RESERVE = 10 << 30              # 윈도우가 깔린 드라이브(C:)는 10GB 를 남긴다 — 전체 과제(담당자 추정 200GB)를 기본 위치에 받다가 C: 가 차지 않게
NAME_ROOM = 120                        # 파일 이름 · 건 폴더 이름의 글자 한도(경로 260 안에 들게)

# ── 날짜 · 폴더 (Qt · 브라우저 없이) ─────────────────────────────────────────


def _date(text: str) -> dt.date | None:
    digits = re.sub(r"\D", "", str(text or ""))
    if len(digits) < 8:
        return None
    try:
        return dt.date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
    except ValueError:
        return None


def iso(text: str) -> str:
    """'20260617' · '2026-06-17' · '2026.06.17' → '2026-06-17'. 못 읽으면 ''."""
    d = _date(text)
    return d.isoformat() if d else ""


def req_date(req_no: str) -> str:
    """구매요구번호 앞 8자리는 요청일(실측 10번: 202606170005 ↔ REQ_DT 2026-06-17)."""
    return iso(str(req_no or "")[:8]) if re.match(r"\d{8}", str(req_no or "")) else ""


def span(projects: list, today: dt.date | None = None) -> tuple[str, str] | None:
    """고른 과제들의 과제기간을 합친 범위 — 가장 이른 시작일 ~ 가장 늦은 종료일(오늘을 넘지 않게). 기간을 아는 과제가 없으면 None."""
    today = today or dt.date.today()
    starts = [d for d in (_date(getattr(p, "start", "")) for p in projects) if d]
    ends = [d for d in (_date(getattr(p, "end", "")) for p in projects) if d]
    if not starts or not ends:
        return None
    end = min(max(ends), today)
    start = min(starts)
    if start > end:
        return None
    return start.isoformat(), end.isoformat()


def windows(start: str, end: str, max_days: int = MAX_DAYS) -> list[tuple[str, str]]:
    """범위를 max_days 일 이하 창으로 나눈다 — 구매요청일자는 한 번에 2년까지만 조회된다."""
    a, b = _date(start), _date(end)
    if not a or not b or a > b:
        return []
    out = []
    while a <= b:
        e = min(a + dt.timedelta(days=max_days - 1), b)
        out.append((a.isoformat(), e.isoformat()))
        a = e + dt.timedelta(days=1)
    return out


def widen(start: str, end: str, days: int = 180, today: dt.date | None = None) -> tuple[str, str]:
    """받을 건이 적을 때(한 건 다시 받기) 조회 범위를 앞뒤 days 일씩 넓힌다 — 하루 범위 조회는 ERP 목록에 그 줄이 안 나왔다
    (2026-10-22 18:52 실제; 요청일자 칸과 목록의 일자 기준이 다를 수 있다). 끝은 오늘을 넘기지 않고, 창 한도(730일) 안."""
    a, b = _date(start), _date(end)
    if not a or not b:
        return start, end
    today = today or dt.date.today()
    a2 = a - dt.timedelta(days=days)
    b2 = min(b + dt.timedelta(days=days), max(today, b))
    if (b2 - a2).days + 1 > MAX_DAYS:
        a2 = max(a2, b2 - dt.timedelta(days=MAX_DAYS - 1)) if (b - a).days + 1 <= MAX_DAYS else a
    return a2.isoformat(), b2.isoformat()


def window_for(day: str, start: str, end: str) -> tuple[str, str] | None:
    """그 날이 든 창(없으면 None)."""
    d = _date(day)
    for s, e in windows(start, end):
        if d and _date(s) <= d <= _date(e):
            return s, e
    return None


def _trim(text: str, room: int) -> str:
    text = naming.safe_name(text)
    return text if len(text) <= room else text[: max(room - 1, 1)].rstrip() + "…"


def case_dir_name(req_no: str, title: str, req_dt: str = "") -> str:
    """건 폴더 이름 `(YYMMDD) 대표건명_(구매요구번호)`. 날짜는 요청일자, 없으면 구매요구번호 앞 8자리."""
    day = iso(req_dt) or req_date(req_no)
    stamp = day[2:4] + day[5:7] + day[8:10] if day else "날짜모름"
    tail = f"_({req_no})"
    return f"({stamp}) " + _trim(title or "제목 없음", NAME_ROOM - len(tail) - 9) + tail


def _drive_labels() -> list[tuple[str, str]]:
    """윈도우 고정 · 네트워크 드라이브의 (뿌리, 이름) — 탐색기의 'MYBOX (N:)' 이면 ('N:\\', 'MYBOX'). 빈 CD 같은 드라이브는 묻지 않는다."""
    if os.name != "nt":
        return []
    import ctypes
    kernel32 = ctypes.windll.kernel32
    found = []
    mask = kernel32.GetLogicalDrives()
    for n in range(26):
        if not mask & (1 << n):
            continue
        root = f"{chr(65 + n)}:\\"
        if kernel32.GetDriveTypeW(ctypes.c_wchar_p(root)) not in (3, 4):      # 3 고정 · 4 네트워크
            continue
        buf = ctypes.create_unicode_buffer(261)
        if kernel32.GetVolumeInformationW(ctypes.c_wchar_p(root), buf, len(buf), None, None, None, None, 0):
            found.append((root, buf.value))
    return found


def on_google_drive(path: str | Path, labels: Callable[[], list[tuple[str, str]]] = _drive_labels) -> bool:
    """구글 드라이브 데스크톱 폴더인지 — 'G:\\내 드라이브\\…' · 'My Drive' · 사용자 폴더의 'Google Drive', 또는 이름이 'Google Drive' 인 드라이브.
    구글 드라이브 저장은 없앴다(담당자 2026-10-22 "구글드라이브 연동해서 업로드한건 삭제해주고 기능도 없애줘" — 무료 15GB 가 다 차서)."""
    text = str(path or "").strip()
    if not text:
        return False
    if any(part.lower() in ("내 드라이브", "my drive", "google drive") for part in re.split(r"[\\/]+", text)):
        return True
    letter = _drive_letter(text)
    return bool(letter) and any(_drive_letter(root) == letter and "googledrive" in (label or "").replace(" ", "").lower()
                                for root, label in labels())


def _drive_letter(path: str | Path) -> str:
    """'N:\\…' → 'n' — 윈도우 경로를 리눅스(테스트)에서도 같게 읽으려고 글자로 본다."""
    found = re.match(r"\s*([A-Za-z]):", str(path))
    return found.group(1).lower() if found else ""


def mybox_folders(labels: Callable[[], list[tuple[str, str]]] = _drive_labels) -> list[Path]:
    """네이버 MYBOX 탐색기가 붙인 드라이브 — 이름에 MYBOX 가 든 드라이브 글자(담당자 PC 2026-10-22: 'MYBOX (N:)', 2.02TB 중 1.83TB 남음).
    구글 드라이브 무료 15GB 가 다 차서 구매 서류를 MYBOX 에 두기로 했다(전체 과제면 200GB 가까이 될 것으로 담당자가 봄)."""
    found = []
    for root, label in labels():
        if "mybox" in (label or "").replace(" ", "").lower():
            found.append(Path(root))
    return found


def purchase_home(out_root: str | Path) -> Path:
    """구매 서류의 맨 위 폴더 — 설정 purchase_root 가 있으면 그것, 없으면 저장 폴더 아래 '구매요청(계약) 서류'."""
    chosen = (getattr(settings.load(), "purchase_root", "") or "").strip()
    if chosen:
        return Path(chosen)
    root = Path(out_root)
    return (root.parent if project_folders.project_of(root) else root) / FOLDER_NAME


def project_base(out_root: str | Path, project_no: str) -> tuple[Path | None, str]:
    """그 과제의 구매 서류를 둘 과제 폴더 — `<저장 폴더>/구매요청(계약) 서류/<과제 폴더 이름 그대로>`. 과제 폴더가 없으면 (None, 까닭).
    저장 폴더 자체가 과제 폴더면 그 위에 둔다. 과제 폴더를 새로 만들지는 않는다(22절과 같은 규칙 — 담당자가 만든 과제만)."""
    project = re.sub(r"\D", "", str(project_no or ""))
    root = Path(out_root)
    if not project:
        return None, "어느 과제의 건인지 몰라(대표과제번호 없음) 받지 않았습니다"
    own = project_folders.project_of(root)
    if own:
        if project != own:
            return None, f"저장 폴더가 다른 과제({own})의 폴더라 과제 {project} 의 서류는 받지 않았습니다"
        return purchase_home(root) / root.name, ""
    mine = project_folders.by_project(root).get(project, [])
    if len(mine) == 1:
        return purchase_home(root) / mine[0].path.name, ""
    if mine:
        return None, f"과제 {project} 의 폴더가 {len(mine)}개라 받지 않았습니다 — 하나만 남기세요"
    return None, f"저장 폴더에 과제 {project} 의 폴더가 없어 받지 않았습니다 — 받으려면 '({project})_…' 폴더를 만드세요"


def case_dir(out_root: str | Path, project_no: str, req_no: str, title: str, req_dt: str = "") -> tuple[Path | None, str]:
    """건 폴더 — 이미 같은 구매요구번호로 끝나는 폴더가 있으면(대표건명이 바뀌었어도) 그것을 쓴다."""
    base, why = project_base(out_root, project_no)
    if base is None:
        return None, why
    if base.is_dir():
        for child in sorted(base.iterdir()):
            if child.is_dir() and child.name.endswith(f"_({req_no})"):
                return child, ""
    return base / case_dir_name(req_no, title, req_dt), ""


class DiskFull(Exception):
    """저장 위치에 공간이 없다 — 남은 건도 같은 곳에 받으므로 거기서 받기를 멈춘다."""


_FULL_WORDS = ("enospc", "no space left", "not enough space", "disk full", "디스크 공간이 부족", "디스크가 꽉")


def _full(error: BaseException) -> bool:
    """디스크가 찼다는 오류인지 — OSError(errno 28 · 윈도우 112 · 39) 또는 Playwright 가 옮긴 글."""
    if isinstance(error, OSError) and (error.errno == errno.ENOSPC or getattr(error, "winerror", None) in (39, 112)):
        return True
    return any(w in str(error).lower() for w in _FULL_WORDS)


def free_space(path: str | Path) -> int | None:
    """그 경로(없으면 있는 가장 가까운 위 폴더)가 있는 드라이브에 남은 바이트. 모르면 None."""
    for p in (Path(path), *Path(path).parents):
        try:
            if p.exists():
                return shutil.disk_usage(p).free
        except OSError:
            return None
    return None


def system_root() -> str:
    """윈도우가 깔린 드라이브의 뿌리('C:\\'). 윈도우가 아니면 ''."""
    return (os.environ.get("SystemDrive", "C:") + "\\") if os.name == "nt" else ""


def reserve_for(path: str | Path, system: str | None = None) -> int:
    """그 위치에 남겨 둘 공간 — 윈도우가 깔린 드라이브면 SYSTEM_RESERVE, 아니면 MIN_FREE."""
    if system is None:
        system = os.environ.get("SystemDrive", "C:") if os.name == "nt" else ""
    drive = _drive_letter(system or "")
    return SYSTEM_RESERVE if drive and _drive_letter(path) == drive else MIN_FREE


def size_text(n: int) -> str:
    for unit, step in (("TB", 1 << 40), ("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if n >= step:
            return f"{n / step:.1f} {unit}"
    return f"{n} B"


def _write(dest: Path, body: bytes) -> None:
    """'.part' 로 쓰고 바꿔치기 — 덮어쓰지 않는다. 디스크가 차면 반쯤 쓴 파일을 지우고 DiskFull."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp = dest.with_name(dest.name + ".part")
    try:
        temp.write_bytes(body)
        temp.replace(dest)
    except OSError as error:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        if _full(error):
            raise DiskFull(f"저장 위치에 공간이 없습니다({error})") from error
        raise


def done_path() -> Path:
    return settings.data_dir() / "_구매받은기록.json"


def load_done(home: str | Path | None = None) -> dict:
    """끝까지 받은 건(구매요구번호 → 받은 때 · 파일 수). 다음 목록 읽기에서 그 건은 빼서 58건을 매번 다시 열지 않는다(담당자 2026-10-22 "너무 시간 낭비").
    판(DONE_VERSION)이 다른 옛 기록은 없는 것으로 본다 — 한 번 더 열어 빠진 서류를 받는다(있는 파일은 건너뛴다)."""
    try:
        data = json.loads(done_path().read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    if not isinstance(data, dict):
        return {}
    done = {k: v for k, v in data.items() if isinstance(v, dict) and v.get("v") == DONE_VERSION}
    if home is not None:
        # 받은 곳이 다른(저장 위치를 바꾼 — 구글 드라이브 → MYBOX, 2026-10-22) 기록은 그 위치에 없으므로 다시 받는다
        done = {k: v for k, v in done.items() if v.get("home") == str(home)}
    return done


def remember_done(results: list["CaseResult"], home: str | Path = "") -> None:
    """못 받은 파일이 하나도 없는 건만 적는다 — 실패가 남은 건은 다음에 다시 연다."""
    done = load_done()
    for r in results:
        if r.ok and r.req_no:
            done[r.req_no] = {"at": time.strftime("%Y-%m-%d %H:%M"), "files": len(r.saved) + r.existed, "title": r.title, "v": DONE_VERSION,
                          "home": str(home)}
    tmp = done_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(done_path())


def forget_done() -> None:
    done_path().unlink(missing_ok=True)


def fix_photo_names(root: Path) -> list[Path]:
    """잘못된 확장자(.html 등)로 받아 둔 물품 사진을 매직 바이트대로 바꾼다 — 2026-10-22 18:35 실제: 사진 6장이 '.html' 로 저장돼 Edge 로 열렸다.
    덮어쓰지 않는다(바른 이름이 이미 있으면 그대로 둔다). 바꾼 경로 목록을 돌려준다."""
    fixed: list[Path] = []
    if root is None or not root.is_dir():
        return fixed
    for path in root.rglob("물품사진_*"):
        if not path.is_file() or path.suffix.lower() in (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif"):
            continue
        try:
            ext = image_ext(path.read_bytes()[:12])
        except OSError:
            continue
        if not ext:
            continue
        stem = path.name if path.suffix.lower() not in (".html", ".htm", ".bin", ".txt") else path.stem
        target = path.with_name(stem + ext)
        if target.exists():
            continue
        try:
            path.rename(target)
            fixed.append(target)
        except OSError:
            continue
    return fixed


def existing_files(folder: Path | None) -> int:
    """건 폴더(검사처리 하위 포함)에 이미 있는 파일 수 — 표의 '폴더 있음' 표시용."""
    if folder is None or not folder.is_dir():
        return 0
    return sum(1 for p in folder.rglob("*") if p.is_file())


def file_name(name: str, fallback: str = "파일") -> str:
    """링크 글자를 파일 이름으로 — 금지문자는 공백, 너무 길면 줄인다(확장자는 남김)."""
    clean = naming.safe_name(name) or fallback
    if len(clean) <= NAME_ROOM:
        return clean
    stem, dot, ext = clean.rpartition(".")
    if dot and len(ext) <= 5:
        return stem[: NAME_ROOM - len(ext) - 2].rstrip() + "…." + ext
    return clean[: NAME_ROOM - 1].rstrip() + "…"


IMAGE_MAGIC = ((b"\xff\xd8\xff", ".jpg"), (b"\x89PNG", ".png"), (b"GIF8", ".gif"), (b"BM", ".bmp"), (b"RIFF", ".webp"), (b"II*\x00", ".tif"), (b"MM\x00*", ".tif"))


def image_ext(body: bytes) -> str:
    """그림 파일의 앞글자(매직 바이트)로 확장자 — ERP 가 사진에도 Content-Type 을 text/html 로 붙여(2026-10-22 실제) 이름으로는 못 정한다."""
    head = (body or b"")[:12]
    for magic, ext in IMAGE_MAGIC:
        if head.startswith(magic):
            return ext
    return ""


def photo_name(item: str, index: int, content_type: str, body: bytes = b"") -> str:
    ext = image_ext(body) or mimetypes.guess_extension((content_type or "").split(";")[0].strip()) or ".jpg"
    if ext in (".html", ".htm", ".bin"):
        ext = ".jpg"
    ext = {".jpe": ".jpg", ".jpeg": ".jpg"}.get(ext, ext)
    return f"물품사진_{_trim(item or '물품', 60)}_{index}{ext}"


# ── 화면 스크립트(읽기 · 허용된 누르기만) ─────────────────────────────────────

# 프레임 알아보기 — 주소가 아니라 내용으로(6절). 구매진행관리 목록 · 구매요구서작성(상세) · 검사처리.
LIST_PROBE_JS = """() => !!document.getElementById('btnDetail') && !!document.getElementById('START_DATE')
  && !!document.getElementById('SEARCH_PURCH_REQ_NO') && !!document.querySelector('.SheetMain')"""
DETAIL_PROBE_JS = """() => { const p = document.getElementById('PROC_TYP_CD');
  return !!p && String(p.value) === 'C10' && !!document.getElementById('PURCH_REQ_NO') && !!document.getElementById('btnList'); }"""
INSPECT_PROBE_JS = """() => !!document.getElementById('btnPunch') && !!document.getElementById('DLVR_DT') && !!document.getElementById('START_DATE')"""
VISIBLE_JS = """() => { try { const f = window.frameElement; if (!f) return true;
  const r = f.getBoundingClientRect(); return r.width > 0 && r.height > 0; } catch (e) { return true; } }"""

# 위 메뉴 '구매·자산'(틀 프레임 #menu_id_3 — 실측 1번 · 10:54). 메인화면에서 바로 들어간다(담당자: 과제를 고르지 않는다).
MENU_JS = """() => {
  const m = document.getElementById('menu_id_3');
  const t = m ? (m.innerText || m.textContent || '').replace(/[\\s·ㆍ]/g, '') : '';
  if (!m || t !== '구매자산') return {ok: false, why: "위 메뉴 '구매·자산' 을 찾지 못함"};
  m.click();
  return {ok: true};
}"""
# 구매 화면 안의 왼쪽 메뉴 글자('구매진행관리' · '검사처리' — a, href=javascript:, id 없음). 보이는 것이 하나일 때만.
LEFT_MENU_JS = """(text) => {
  const txt = e => (e.innerText || e.textContent || '').replace(/\\s+/g, ' ').trim();
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const hits = Array.from(document.querySelectorAll('a')).filter(a => txt(a) === text && vis(a));
  if (hits.length !== 1) return {ok: false, why: hits.length ? `왼쪽 메뉴 '${text}' 가 여럿` : `왼쪽 메뉴 '${text}' 가 보이지 않음`};
  hits[0].click();
  return {ok: true};
}"""
# 위쪽 탭(a.mul_txt)을 앞으로 — 숨은 탭의 JGM 그리드는 줄이 안 그려진다(7절 11번). 글자가 정확히 같은 보이는 탭 하나만.
TOP_TAB_JS = """(text) => {
  const txt = e => (e.innerText || e.textContent || '').replace(/\\s+/g, ' ').trim();
  const shown = Array.from(document.querySelectorAll('a.mul_txt')).filter(a => {
    const r = a.getBoundingClientRect(); return txt(a) === text && r.width > 0 && r.height > 0; });
  if (shown.length !== 1) return {ok: false, why: `위쪽 '${text}' 탭이 하나가 아님`};
  shown[0].click();
  return {ok: true};
}"""
# 조회 조건의 일자 둘(구매진행관리 구매요청일자 · 검사처리 계약일자 — 둘 다 #START_DATE · #END_DATE). 값을 넣는 칸은 이 둘뿐.
SET_RANGE_JS = """([start, end]) => {
  const a = document.getElementById('START_DATE'), b = document.getElementById('END_DATE');
  if (!a || !b) return {ok: false, why: '일자 칸이 없음'};
  for (const [el, v] of [[a, start], [b, end]]) {
    el.value = v;
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
  }
  return {ok: true, start: String(a.value || ''), end: String(b.value || '')};
}"""
RANGE_JS = """() => { const v = id => { const e = document.getElementById(id); return e ? String(e.value || '') : ''; };
  return {start: v('START_DATE'), end: v('END_DATE')}; }"""
SEARCH_JS = """() => {
  const b = document.getElementById('btnSearch');
  if (!b) return {ok: false, why: '[검색] 단추가 없음'};
  b.click();
  return {ok: true};
}"""
# IBSheet 8 목록 읽기(읽기만) — getDataRows · getValue · getText(실측 19번: 이 둘로 25줄 · 30열이 읽혔다)
SHEET_ROWS_JS = """() => {
  const s = window.IBSheet && window.IBSheet[0];
  if (!s || typeof s.getDataRows !== 'function') return null;
  let rows; try { rows = s.getDataRows(); } catch (e) { return null; }
  if (!Array.isArray(rows)) return null;
  const get = (r, c) => { try { const v = s.getValue(r, c); return v === null || v === undefined ? '' : String(v); } catch (e) { return ''; } };
  const txt = (r, c) => { try { if (typeof s.getText === 'function') { const v = s.getText(r, c); if (v !== null && v !== undefined && String(v)) return String(v); } }
                          catch (e) {} return get(r, c); };
  return rows.map(r => ({req_no: get(r, 'PURCH_REQ_NO'), prj_no: get(r, 'PRJ_NO'), req_dt: txt(r, 'REQ_DT'), title: get(r, 'PURCH_CONT'),
                         state: get(r, 'PURCH_PROG_STS_NM'), kind: get(r, 'PURCH_KIND_NM'), amount: get(r, 'PURCH_AMT'),
                         cont_no: get(r, 'CONT_NO'), cont_state: get(r, 'CONT_PROG_STS_NM'), seq: get(r, 'ROW_SEQ'), prj_nm: get(r, 'PRJ_NM')}));
}"""
SHEET_SIGNATURE_JS = """() => {
  const s = window.IBSheet && window.IBSheet[0];
  if (!s || typeof s.getDataRows !== 'function') return '';
  try { const rows = s.getDataRows(); if (!Array.isArray(rows)) return '';
        const no = r => { try { return String(s.getValue(r, 'PURCH_REQ_NO') || ''); } catch (e) { return ''; } };
        return rows.length + '|' + (rows.length ? no(rows[0]) + '|' + no(rows[rows.length - 1]) : ''); } catch (e) { return ''; }
}"""
# 그 구매요구번호 줄의 선택 칸(chk)만 체크하고 [상세조회/변경] — 단추의 처리기가 체크된 줄 하나를 상세로 띄운다(실측 19번 btnDetail_click).
PICK_DETAIL_JS = """(no) => {
  const s = window.IBSheet && window.IBSheet[0];
  if (!s || typeof s.getDataRows !== 'function' || typeof s.setValue !== 'function') return {ok: false, why: 'IBSheet 목록을 읽지 못함'};
  const rows = s.getDataRows();
  const hit = rows.filter(r => String(s.getValue(r, 'PURCH_REQ_NO') || '') === String(no));
  if (hit.length !== 1) return {ok: false, why: hit.length ? '같은 구매요구번호 줄이 여럿' : '목록에 그 구매요구번호 줄이 없음'};
  rows.forEach(r => { if (r !== hit[0] && Number(s.getValue(r, 'chk')) === 1) s.setValue(r, 'chk', 0, 1); });
  s.setValue(hit[0], 'chk', 1, 1);
  const checked = typeof s.getRowsByChecked === 'function' ? s.getRowsByChecked('chk') : [hit[0]];
  if (!Array.isArray(checked) || checked.length !== 1 || checked[0] !== hit[0]) return {ok: false, why: '선택 칸이 체크되지 않음'};
  const b = document.getElementById('btnDetail');
  const t = b ? (b.innerText || b.textContent || '').replace(/\\s+/g, '') : '';
  if (!b || !t.startsWith('상세조회')) return {ok: false, why: '[상세조회/변경] 단추를 찾지 못함'};
  b.click();
  return {ok: true};
}"""
# 구매요구서작성(상세) — 숨은 값과 증빙문서 링크(글자 = 파일 이름). 읽기만.
DETAIL_JS = """() => {
  const v = id => { const e = document.getElementById(id); return e ? String(e.value || '') : ''; };
  const txt = e => (e.innerText || e.textContent || '').replace(/\\s+/g, ' ').trim();
  const files = [];
  document.querySelectorAll('a[href*="comm0008_01.act"][href*="ATTFILE_SEQ_NO"]').forEach(a => {
    const name = txt(a); const href = a.getAttribute('href') || '';
    if (name && href && !files.some(f => f.href === href)) files.push({name, href});
  });
  return {req_no: v('PURCH_REQ_NO'), prj_no: v('PRJ_NO'), req_dt: v('REQ_DT'), title: v('PURCH_CONT'), state: v('PURCH_PROG_STS_NM'), files};
}"""
LIST_BACK_JS = """() => {
  const b = document.getElementById('btnList');
  const t = b ? (b.innerText || b.textContent || '').replace(/\\s+/g, '') : '';
  if (!b || !t.includes('목록')) return {ok: false, why: '[진행관리목록] 단추를 찾지 못함'};
  b.click();
  return {ok: true};
}"""
# 검사처리 계약 건 목록(JGM) — 구매요구번호 칸이 있는 줄만(재원 · 첨부 · 물품정보 표는 없다). 가상 스크롤이라 보이는 줄만 그려진다.
INSPECT_ROWS_JS = """() => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const out = [];
  document.querySelectorAll('.jgrid-row').forEach(el => {
    if (!el.querySelector('.k_PURCH_REQ_NO') || !vis(el)) return;
    const c = k => { const d = el.querySelector('.k_' + k); if (!d) return '';
      const t = d.getAttribute('title'); return (t && t.trim()) ? t.trim() : (d.textContent || '').trim(); };
    out.push({r: el.getAttribute('r'), req_no: c('PURCH_REQ_NO').replace(/\\D/g, ''), cont_nm: c('CONT_NM'), cont_dt: c('CONT_DT'),
              cont_no: c('CONT_NO'), state: c('CONT_PROG_STS_NM'), prj_nm: c('PRJ_NM'), seq: c('ROW_SEQ'), kind: c('CONT_KIND_NM')});
  });
  return out;
}"""
INSPECT_SCROLL_JS = """(how) => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const v = Array.from(document.querySelectorAll('.jgrid-viewport')).find(e => vis(e) && e.querySelector('.k_PURCH_REQ_NO'));
  if (!v) return null;
  if (how === 'top') v.scrollTop = 0;
  else if (how === 'next') v.scrollTop = Math.min(v.scrollHeight, v.scrollTop + Math.max(40, v.clientHeight - 60));
  return {top: v.scrollTop, h: v.clientHeight, sh: v.scrollHeight};
}"""
# 검사처리 줄 고르기 — 그 줄(r)의 라디오(이름은 그리드를 다시 그리면 바뀐다 — radioJGM5 로 고정하지 않는다)
INSPECT_PICK_JS = """(r) => {
  const vis = e => { const b = e.getBoundingClientRect(); return b.width > 0 && b.height > 0; };
  const row = Array.from(document.querySelectorAll('.jgrid-row')).find(e => vis(e) && e.querySelector('.k_PURCH_REQ_NO') && String(e.getAttribute('r')) === String(r));
  if (!row) return {ok: false, why: '그 줄이 화면에 없음'};
  const box = row.querySelector('input[type=radio]');
  if (!box) return {ok: false, why: '줄에 선택 칸이 없음'};
  box.click();
  return {ok: true};
}"""
INSPECT_SELECTED_JS = """() => { const v = id => { const e = document.getElementById(id); return e ? String(e.value || '') : ''; };
  return {req_no: v('PURCH_REQ_NO').replace(/\\D/g, ''), prj_no: v('PRJ_NO').replace(/\\D/g, ''), cont_seq: v('CONT_SEQ_NO')}; }"""
# 고른 건의 첨부 표 링크(a.btn_lnk, 실측 11번) — 줄의 증빙구분(select)도 함께. 읽기만.
INSPECT_FILES_JS = """() => {
  const txt = e => (e.innerText || e.textContent || '').replace(/\\s+/g, ' ').trim();
  const files = [];
  document.querySelectorAll('a[href*="comm0008_01.act"][href*="ATTFILE_SEQ_NO"]').forEach(a => {
    const name = txt(a); const href = a.getAttribute('href') || '';
    if (!name || !href || files.some(f => f.href === href)) return;
    const row = a.closest('.jgrid-row, tr');
    const sel = row ? row.querySelector('select') : null;
    const kind = sel && sel.options[sel.selectedIndex] ? txt(sel.options[sel.selectedIndex]) : '';
    files.push({name, href, kind});
  });
  return files;
}"""
# 고른 건의 물품정보 표 줄(JGM, k_CONT_ITEM_NM_KR) — 더블클릭해 물품내역팝업을 연다(담당자 2026-10-22). 읽기만.
ITEMS_JS = """() => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const out = [];
  document.querySelectorAll('.jgrid-row').forEach(el => {
    const d = el.querySelector('.k_CONT_ITEM_NM_KR'); if (!d || !vis(el)) return;
    const t = d.getAttribute('title'); const name = (t && t.trim()) ? t.trim() : (d.textContent || '').trim();
    const no = el.querySelector('.k_ITEM_VIEW_NO');
    out.push({r: el.getAttribute('r'), name, view_no: no ? (no.textContent || '').trim() : ''});
  });
  return out;
}"""
ITEM_ROW_SELECTOR = '.jgrid-row[r="{r}"] .k_CONT_ITEM_NM_KR'
# 물품내역팝업 — 사진 번호 · 그림 주소(실측 12 · 15번). 읽기만.
POPUP_JS = """() => {
  const v = id => { const e = document.getElementById(id); return e ? String(e.value || '') : ''; };
  const src = id => { const e = document.getElementById(id); return e ? String(e.getAttribute('src') || '') : ''; };
  if (!document.getElementById('IMGFILE_SEQ_NO') && !document.getElementById('USER_PICTURE')) return null;
  return {item: v('ITEM_NM') || v('CONT_ITEM_NM_KR'), seq1: v('IMGFILE_SEQ_NO'), seq2: v('IMGFILE_SEQ_NO2'),
          src1: src('USER_PICTURE'), src2: src('USER_PICTURE2')};
}"""


# ── 결과 ───────────────────────────────────────────────────────────────────


@dataclass
class CaseResult:
    req_no: str
    title: str = ""
    project: str = ""
    folder: str = ""
    saved: list[str] = field(default_factory=list)       # 이번에 받은 파일 이름(검사처리 것은 '검사처리/…')
    existed: int = 0                                      # 이미 있어 받지 않은 파일 수
    failed: list[str] = field(default_factory=list)      # 못 받은 파일 — '이름: 까닭'
    photos: int = 0
    size: int = 0                                         # 이번에 받은 바이트
    inspected: bool = False                               # 검사처리 화면에서 이 건을 봤는지
    note: str = ""                                        # 건 전체의 까닭(과제 폴더 없음 · 상세를 못 띄움 …)
    ok: bool = True

    def summary(self) -> str:
        parts = []
        if self.saved:
            parts.append(f"새 파일 {len(self.saved)}개")
        if self.existed:
            parts.append(f"이미 있음 {self.existed}개")
        if self.photos:
            parts.append(f"물품 사진 {self.photos}장")
        if not self.saved and not self.existed and not self.failed and self.ok:
            parts.append("첨부 없음")
        if self.failed:
            parts.append(f"못 받음 {len(self.failed)}개")
        if self.note:
            parts.append(self.note)
        return " · ".join(parts)


@dataclass
class PurchaseSummary:
    cases: list[CaseResult] = field(default_factory=list)
    inspected_rows: int = 0            # 검사처리에서 본 계약 건 수(고른 과제 밖 포함)
    stopped: bool = False
    note: str = ""                     # 검사처리를 못 연 까닭 등

    @property
    def ok(self) -> int:
        return sum(1 for c in self.cases if c.ok)

    @property
    def failed(self) -> list[CaseResult]:
        return [c for c in self.cases if not c.ok]

    @property
    def files(self) -> int:
        return sum(len(c.saved) for c in self.cases)

    @property
    def size(self) -> int:
        return sum(c.size for c in self.cases)


def as_target(row: dict, folder: Path | None = None) -> dict:
    """목록 줄 → 받기 표의 줄(청구서 줄과 같은 칸 이름을 쓴다: no · expDt · cont · amt · gubun · project)."""
    req_dt = iso(row.get("req_dt", "")) or req_date(row.get("req_no", ""))
    state = row.get("state") or ""
    gubun = "구매요청" + (f"({row['kind']})" if row.get("kind") else "") + (f" · {state}" if state else "")
    return {"kind": KIND, "req_no": str(row.get("req_no") or ""), "project": re.sub(r"\D", "", str(row.get("prj_no") or "")),
            "no": str(row.get("seq") or ""), "expDt": req_dt, "cont": str(row.get("title") or ""),
            "amt": re.sub(r"[^0-9\-]", "", str(row.get("amount") or "")), "gubun": gubun, "state": state,
            "cont_state": str(row.get("cont_state") or ""), "docNo": "", "existing": existing_files(folder)}


# ── 브라우저 쪽(프레임 · 창 객체는 받아서만 쓴다) ────────────────────────────


def _frames(context):
    for page in list(getattr(context, "pages", []) or []):
        try:
            if page.is_closed():
                continue
        except Exception:  # noqa: BLE001
            pass
        for frame in list(getattr(page, "frames", []) or []):
            yield page, frame


def _eval(frame, js, *args):
    try:
        return frame.evaluate(js, *args)
    except Exception:  # noqa: BLE001 — 그리는 중 · 바뀌는 중
        return None


def _find(context, probe_js: str):
    """probe 가 참인 프레임 — 보이는 것 먼저. 없으면 None."""
    found = []
    for _page, frame in _frames(context):
        if _eval(frame, probe_js) is True:
            found.append((0 if _eval(frame, VISIBLE_JS) is True else 1, frame))
    return sorted(found, key=lambda pair: pair[0])[0][1] if found else None


def list_frame(context):
    return _find(context, LIST_PROBE_JS)


def detail_frame(context):
    return _find(context, DETAIL_PROBE_JS)


def inspect_frame(context):
    return _find(context, INSPECT_PROBE_JS)


def _wait_for(check: Callable[[], object], wait: Callable[[float], None], tries: int, step: float = 0.5):
    for _ in range(tries):
        got = check()
        if got:
            return got
        wait(step)
    return check()


def _click_any(context, js: str, *args) -> tuple[bool, str]:
    why = ""
    for _page, frame in _frames(context):
        got = _eval(frame, js, *args) or {}
        if got.get("ok"):
            return True, ""
        why = got.get("why") or why
    return False, why or "그 단추를 찾지 못함"


def show_tab(context, text: str, log: Callable[[str], None]) -> None:
    ok, _why = _click_any(context, TOP_TAB_JS, text)
    if ok:
        log(f"위쪽 '{text}' 탭을 앞으로 가져옵니다")


def open_list(context, log: Callable[[str], None], wait: Callable[[float], None]):
    """구매진행관리 목록 프레임 — 이미 있으면 그대로(상세가 떠 있으면 [진행관리목록] 으로), 없으면 위 메뉴 '구매·자산' 으로 연다."""
    frame = list_frame(context)
    if frame is not None:
        return frame, ""
    detail = detail_frame(context)
    if detail is not None:
        frame = back_to_list(context, detail, log, wait)
        if frame is not None:
            return frame, ""
    ok, why = _click_any(context, LEFT_MENU_JS, "구매진행관리")      # 검사처리 화면이 떠 있으면 그 왼쪽 메뉴로
    if ok:
        log("왼쪽 메뉴 '구매진행관리' 를 눌렀습니다")
    else:
        ok, why = _click_any(context, MENU_JS)
        if not ok:
            if navigate.logged_out(context):
                return None, "ERP 에 로그인돼 있지 않습니다 — 브라우저에서 로그인한 뒤 다시 하세요"
            return None, f"구매·자산 메뉴로 들어가지 못했습니다({why}) — 로그인했는지 보고, 메인화면이 보이게 한 뒤 다시 하세요"
        log("위 메뉴 '구매·자산' 을 눌렀습니다 (과제는 고르지 않습니다 — 담당자 2026-10-22)")
    frame = _wait_for(lambda: list_frame(context), wait, LIST_TRIES)
    if frame is None:
        return None, "구매·자산 메뉴를 눌렀지만 구매진행관리 목록이 뜨지 않았습니다 — 브라우저에서 구매진행관리를 띄운 뒤 다시 하세요"
    return frame, ""


def current_range(frame) -> tuple[str, str]:
    got = _eval(frame, RANGE_JS) or {}
    return iso(got.get("start", "")), iso(got.get("end", ""))


def search(frame, start: str, end: str, log: Callable[[str], None], wait: Callable[[float], None], what: str = "구매요청일자") -> tuple[bool, str]:
    """일자 범위를 넣고 [검색] — 목록이 다시 그려져 줄 수가 두 번 연달아 같을 때까지 기다린다. (됐는지, 까닭)."""
    before = _eval(frame, SHEET_SIGNATURE_JS) or ""
    got = _eval(frame, SET_RANGE_JS, [start, end]) or {}
    if not got.get("ok"):
        return False, got.get("why") or "일자 칸을 넣지 못함"
    if iso(got.get("start", "")) != start or iso(got.get("end", "")) != end:
        return False, f"일자 칸에 값이 남지 않음({got.get('start')} ~ {got.get('end')})"
    got = _eval(frame, SEARCH_JS) or {}
    if not got.get("ok"):
        return False, got.get("why") or "[검색] 을 누르지 못함"
    log(f"{what} {start} ~ {end} 로 [검색]")
    wait(1.0)
    last, same = None, 0
    for _ in range(SETTLE_TRIES):
        now = _eval(frame, SHEET_SIGNATURE_JS) if what == "구매요청일자" else str(len(_eval(frame, INSPECT_ROWS_JS) or []))
        if now == last and (now != before or same >= 2):
            same += 1
            if same >= 2:
                break
        else:
            same = 0
        last = now
        wait(0.5)
    return True, ""


def read_rows(frame) -> list[dict] | None:
    rows = _eval(frame, SHEET_ROWS_JS)
    return rows if isinstance(rows, list) else None


def open_detail(context, frame, req_no: str, log: Callable[[str], None], wait: Callable[[float], None]):
    """그 건의 상세(구매요구서작성) 프레임 또는 (None, 까닭)."""
    got = _eval(frame, PICK_DETAIL_JS, req_no) or {}
    if not got.get("ok"):
        return None, got.get("why") or "상세를 띄우지 못함"

    def ready():
        d = detail_frame(context)
        if d is None:
            return None
        info = _eval(d, DETAIL_JS) or {}
        return d if re.sub(r"\D", "", str(info.get("req_no") or "")) == re.sub(r"\D", "", req_no) else None

    detail = _wait_for(ready, wait, LIST_TRIES)
    if detail is None:
        other = detail_frame(context)
        if other is not None:
            info = _eval(other, DETAIL_JS) or {}
            return None, f"다른 건({info.get('req_no') or '?'})의 상세가 떴습니다"
        return None, "[상세조회/변경] 을 눌렀지만 구매요구서작성 화면이 뜨지 않았습니다"
    return detail, ""


def back_to_list(context, detail, log: Callable[[str], None], wait: Callable[[float], None]):
    got = _eval(detail, LIST_BACK_JS) or {}
    if not got.get("ok"):
        log("⚠ " + (got.get("why") or "[진행관리목록] 을 누르지 못함"))
        return None
    return _wait_for(lambda: list_frame(context), wait, LIST_TRIES)


def looks_like_html(body: bytes) -> bool:
    """몸통이 HTML 문서인지 — 앞글자가 <!doctype · <html 일 때만(BOM · 공백은 뗀다). 응답 종류(Content-Type)는 믿지 않는다."""
    head = (body or b"")[:40].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    return head.startswith((b"<!doctype", b"<html"))


def fetch(page, url: str):
    """같은 브라우저 묶음의 쿠키로 파일을 받는다 → (bytes, content_type, 까닭). 로그인 화면(HTML)이 오면 받지 않는다."""
    try:
        resp = page.request.get(url, timeout=60000)
    except Exception as error:  # noqa: BLE001
        return None, "", str(error).splitlines()[0][:120] if str(error) else type(error).__name__
    try:
        ctype = str((resp.headers or {}).get("content-type", "")).lower()
        if not resp.ok:
            return None, ctype, f"HTTP {resp.status}"
        body = resp.body()
    except Exception as error:  # noqa: BLE001
        return None, "", str(error).splitlines()[0][:120] if str(error) else type(error).__name__
    # 2026-10-22 18:35 실제: ERP 가 진짜 파일(%PDF · HWP · OLE)에도 Content-Type 을 text/html 로 붙여 보낸다 — 응답 종류가 아니라 몸통 앞글자로만 가린다
    if looks_like_html(body):
        return None, ctype, "HTML 이 왔습니다(로그인이 풀렸거나 파일이 아님)"
    if not body:
        return None, ctype, "빈 파일"
    return body, ctype, ""


# 실제 ERP(2026-10-22 17:41)에서 page.request.get 이 파일마다 HTML 을 받았다 — 쿠키만으로는 안 되고
# 화면 안에서 부른 요청(같은 출처 · Referer)이어야 주는 것으로 본다. 그래서 그 프레임 안에서 fetch 해 받는다.
FRAME_FETCH_JS = r"""
async (href) => {
  try {
    const r = await fetch(href, {credentials: 'include'});
    const ctype = (r.headers.get('content-type') || '').toLowerCase();
    const buf = new Uint8Array(await r.arrayBuffer());
    // 응답 종류(text/html)는 믿지 않는다 — 실제 ERP 가 진짜 파일에도 text/html 을 붙인다(2026-10-22 18:35). 몸통 앞글자로만.
    const head = String.fromCharCode.apply(null, buf.slice(0, 40)).replace(/^\uFEFF|^[\s\u00EF\u00BB\u00BF]+/, '').trim().toLowerCase();
    if (head.startsWith('<!doctype') || head.startsWith('<html')) {
      const text = new TextDecoder().decode(buf.slice(0, 4000));
      const m = text.match(/<title[^>]*>([^<]{0,60})/i);
      // 무엇이 왔는지 보려고 form action · 스크립트의 주소 꼴 · 글자 앞부분만 (값은 적지 않는다)
      const act = (text.match(/action=["']([^"'?]{0,60})/i) || [])[1] || '';
      const go = (text.match(/(location[.\w]*\s*=|\.submit\(|window\.open|alert\()/) || [])[1] || '';
      const body = text.replace(/<script[\s\S]*?<\/script>/gi, ' ').replace(/<[^>]+>/g, ' ')
        .replace(/[\u0000-\u001f\u007f\ufffd]/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 60);   // 제어 글자는 기록 · 클립보드를 끊는다
      return {ok: false, why: 'HTML 이 왔습니다' + (m ? " (제목 '" + m[1].trim() + "')" : '') + ' · HTTP ' + r.status
        + (act ? ' · form ' + act : '') + (go ? ' · ' + go : '') + (body ? " · 글 '" + body + "'" : '')};
    }
    if (!r.ok) return {ok: false, why: 'HTTP ' + r.status};
    if (!buf.length) return {ok: false, why: '빈 파일'};
    let bin = '';
    for (let i = 0; i < buf.length; i += 32768) bin += String.fromCharCode.apply(null, buf.subarray(i, i + 32768));
    return {ok: true, ctype, data: btoa(bin)};
  } catch (e) { return {ok: false, why: String(e).slice(0, 120)}; }
}
"""


def fetch_in(frame, page, url: str):
    """그 화면 안에서 받기 → 안 되면 page.request 로. (bytes, content_type, 까닭)."""
    why_frame = ""
    if frame is not None:
        try:
            got = frame.evaluate(FRAME_FETCH_JS, url) or {}
        except Exception as error:  # noqa: BLE001
            got = {"why": str(error).splitlines()[0][:120] if str(error) else type(error).__name__}
        if got.get("ok"):
            import base64
            return base64.b64decode(got.get("data") or ""), str(got.get("ctype") or ""), ""
        why_frame = str(got.get("why") or "")
    body, ctype, why = fetch(page, url)
    if body is None and why_frame:
        why = f"화면 안에서: {why_frame} · 직접: {why}"
    return body, ctype, why


CLICK_TIMEOUT_MS = 30000


def click_download(frame, page, href: str, dest: Path):
    """주소로 받으면 HTML 이 오는 ERP(2026-10-22 실제) — 사람이 하듯 그 링크를 눌러 내려받는다.
    링크에 붙은 ERP 처리기가 진짜 받기 요청을 만드는 것으로 본다. → (bytes 크기, 까닭)."""
    if frame is None or not href:
        return None, "링크를 누를 화면이 없음"
    link = frame.locator(f'a[href="{href}"]').first
    before = list(page.context.pages)
    temp = dest.with_name(dest.name + ".part")
    download = None
    try:
        if not link.count():
            return None, "화면에 그 링크가 없음"
        try:
            link.scroll_into_view_if_needed(timeout=3000)
        except Exception:  # noqa: BLE001
            pass
        with page.expect_download(timeout=CLICK_TIMEOUT_MS) as got:
            # 5초에서 시간 초과가 잦았다(2026-10-22 18:35 실제, 긴 목록 아래 링크) — 15초, 가려져 있으면 그대로 누른다
            link.click(timeout=15000, force=True)
        download = got.value
        fail = download.failure()
        if fail:
            return None, f"내려받기 실패({fail})"
        dest.parent.mkdir(parents=True, exist_ok=True)
        download.save_as(str(temp))
        if looks_like_html(temp.read_bytes()[:40]) or temp.stat().st_size == 0:
            temp.unlink(missing_ok=True)
            return None, "눌러 받아도 HTML 이 왔습니다"
        size = temp.stat().st_size
        temp.replace(dest)
        return size, ""
    except Exception as error:  # noqa: BLE001
        if _full(error):
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
            raise DiskFull(f"저장 위치에 공간이 없습니다({str(error).splitlines()[0][:100]})") from error
        return None, "링크 누르기: " + (str(error).splitlines()[0][:100] if str(error) else type(error).__name__)
    finally:
        # Playwright 는 받은 파일을 브라우저를 닫을 때까지 C: 임시 폴더에 들고 있다 — 저장 위치(MYBOX)로 옮긴 뒤 바로 지운다
        # (담당자 2026-10-22 "데스크톱 용량에는 영향이 가지 않게" — 한 번 받기에서 339개 · 1GB 가 이 길이었다)
        if download is not None:
            try:
                download.delete()
            except Exception:  # noqa: BLE001
                pass
        # 눌러서 새 창(파일 보기)이 떴으면 닫는다 — ERP 단추가 아니라 창 닫기
        try:
            for extra in page.context.pages:
                if extra not in before and extra is not page:
                    extra.close()
        except Exception:  # noqa: BLE001
            pass


def _save(page, base_url: str, href: str, dest: Path, log: Callable[[str], None], frame=None) -> tuple[str, int]:
    """파일 하나 — ('saved' · 'exists' · 'failed: 까닭', 받은 바이트). 덮어쓰지 않는다. 디스크가 차면 DiskFull."""
    if dest.exists():
        return "exists", 0
    body, _ctype, why = fetch_in(frame, page, urljoin(base_url, href))
    if body is None:
        size, click_why = click_download(frame, page, href, dest)
        if size is not None:
            log(f"      ✓ {dest.name} ({size:,} B · 링크를 눌러 받음)")
            return "saved", size
        why = f"{why} · {click_why}"
        log(f"      ✖ {dest.name} — {why}")
        return "failed: " + why, 0
    try:
        _write(dest, body)
    except DiskFull:
        raise
    except OSError as error:
        why = f"저장하지 못함({error})"
        log(f"      ✖ {dest.name} — {why}")
        return "failed: " + why, 0
    log(f"      ✓ {dest.relative_to(dest.parents[1]) if len(dest.parents) > 1 else dest.name} ({len(body):,} B)")
    return "saved", len(body)


def _save_files(page, base_url: str, files: list[dict], folder: Path, result: CaseResult, log: Callable[[str], None],
                prefix: str = "", frame=None) -> None:
    for f in files:
        name = file_name(f.get("name", ""))
        dest = folder / name
        got, size = _save(page, base_url, f.get("href", ""), dest, log, frame)
        if got == "saved":
            result.saved.append(prefix + name)
            result.size += size
        elif got == "exists":
            result.existed += 1
        else:
            result.failed.append(f"{prefix}{name}: {got[8:]}")
            result.ok = False


def _frame_url(frame) -> str:
    try:
        return str(frame.url or "")
    except Exception:  # noqa: BLE001
        return ""


def settled_detail(frame, wait: Callable[[float], None]) -> dict:
    """상세의 값 · 증빙문서 링크 — 링크 수가 DETAIL_STABLE 번 연달아 같을 때까지, 0개면 적어도 DETAIL_MIN_EMPTY 번 본다."""
    info: dict = {}
    last, same = None, 0
    for tries in range(DETAIL_MAX_TRIES):
        info = _eval(frame, DETAIL_JS) or {}
        count = len(info.get("files") or [])
        same = same + 1 if count == last else 1
        last = count
        if same >= DETAIL_STABLE and (count > 0 or tries + 1 >= DETAIL_MIN_EMPTY):
            break
        wait(0.5)
    return info


def receive_case(context, page, frame, target: dict, out_root: str, log: Callable[[str], None],
                 wait: Callable[[float], None]) -> tuple[CaseResult, object]:
    """구매진행관리 목록에서 한 건 — chk → [상세조회/변경] → 증빙문서 링크 받기 → [진행관리목록]. (결과, 다시 뜬 목록 프레임 또는 None)."""
    req_no = str(target.get("req_no") or "")
    result = CaseResult(req_no, target.get("cont", ""), target.get("project", ""))
    detail, why = open_detail(context, frame, req_no, log, wait)
    if detail is None:
        result.ok, result.note = False, why
        return result, list_frame(context)
    info = settled_detail(detail, wait)
    project = re.sub(r"\D", "", str(info.get("prj_no") or "")) or result.project
    result.project = project
    result.title = info.get("title") or result.title
    folder, why = case_dir(out_root, project, req_no, result.title, info.get("req_dt") or target.get("expDt", ""))
    if folder is None:
        result.ok, result.note = False, why
        log("      ⚠ " + why)
    else:
        result.folder = str(folder)
        files = info.get("files") or []
        log(f"      구매요구서작성 — 증빙문서 {len(files)}개 → {folder.name}")
        _save_files(page, _frame_url(detail), files, folder, result, log, frame=detail)
    return result, back_to_list(context, detail, log, wait)


def _has_row(frame, req_no: str) -> bool:
    return any(str(r.get("req_no") or "") == str(req_no) for r in (read_rows(frame) or []))


def ensure_range(frame, start: str, end: str, log: Callable[[str], None], wait: Callable[[float], None], req_no: str = "") -> tuple[bool, str]:
    """목록의 일자 범위가 이 범위이고 그 건의 줄이 보일 때까지 — [진행관리목록] 으로 돌아온 목록은 조회 조건을 지닌 채 다시 그려지는 동안 줄이 비어 있다.
    범위가 다르거나 기다려도 줄이 안 보이면 범위를 넣고 [검색]."""
    if current_range(frame) == (start, end):
        if not req_no or _wait_for(lambda: _has_row(frame, req_no), wait, 16):
            return True, ""
    elif req_no and _has_row(frame, req_no):
        # 지금 목록(범위가 달라도 — 목록 읽기 때의 넓은 범위)에 그 줄이 이미 보이면 다시 [검색] 하지 않는다
        # (2026-10-22 18:52 실제: 한 건만 다시 받으며 하루 범위로 조회하자 줄이 안 보여 실패)
        return True, ""
    ok, why = search(frame, start, end, log, wait)
    if not ok:
        return False, why
    # [검색] 뒤 목록이 늦게 다시 그려질 수 있다(2026-10-22 18:31 실제: 하루 범위 조회 직후 줄을 못 봄)
    if req_no and not _wait_for(lambda: _has_row(frame, req_no), wait, 16):
        return False, f"{start} ~ {end} 로 조회한 목록에 구매요구 {req_no} 줄이 없음"
    return True, ""


def collect_inspection(frame, wait: Callable[[float], None]) -> list[dict]:
    """검사처리 계약 건 목록을 가상 스크롤을 내리며 전부(구매요구번호 + 줄 번호로 중복 제거)."""
    seen, out = set(), []

    def grab():
        for r in _eval(frame, INSPECT_ROWS_JS) or []:
            key = (r.get("req_no"), r.get("cont_no"), r.get("r"))
            if r.get("req_no") and key not in seen:
                seen.add(key)
                out.append(r)

    _eval(frame, INSPECT_SCROLL_JS, "top")
    grab()
    last = -1
    for _ in range(400):
        info = _eval(frame, INSPECT_SCROLL_JS, "info")
        if not info:
            break
        if info["top"] + info["h"] >= info["sh"] - 5 and info["top"] == last:
            break
        last = info["top"]
        _eval(frame, INSPECT_SCROLL_JS, "next")
        wait(0.25)
        grab()
    return out


def _scroll_to_row(frame, r: str, wait: Callable[[float], None]) -> bool:
    """가상 스크롤 목록에서 줄 r 이 그려질 때까지 내린다."""
    if any(str(x.get("r")) == str(r) for x in (_eval(frame, INSPECT_ROWS_JS) or [])):
        return True
    _eval(frame, INSPECT_SCROLL_JS, "top")
    last = -1
    for _ in range(400):
        if any(str(x.get("r")) == str(r) for x in (_eval(frame, INSPECT_ROWS_JS) or [])):
            return True
        info = _eval(frame, INSPECT_SCROLL_JS, "info")
        if not info or (info["top"] + info["h"] >= info["sh"] - 5 and info["top"] == last):
            break
        last = info["top"]
        _eval(frame, INSPECT_SCROLL_JS, "next")
        wait(0.2)
    return False


def select_inspection(frame, row: dict, wait: Callable[[float], None]) -> tuple[bool, str]:
    if not _scroll_to_row(frame, row.get("r", ""), wait):
        return False, "그 줄을 화면에 못 그림"
    got = _eval(frame, INSPECT_PICK_JS, row.get("r", "")) or {}
    if not got.get("ok"):
        return False, got.get("why") or "줄을 고르지 못함"
    want = re.sub(r"\D", "", str(row.get("req_no") or ""))
    chosen = _wait_for(lambda: (_eval(frame, INSPECT_SELECTED_JS) or {}).get("req_no") == want, wait, 20)
    return (True, "") if chosen else (False, "줄을 골랐지만 아래 칸에 그 건이 채워지지 않음")


def _photo_urls(info: dict) -> list[tuple[int, str]]:
    out = []
    for index, (seq, src) in enumerate(((info.get("seq1"), info.get("src1")), (info.get("seq2"), info.get("src2"))), 1):
        seq = str(seq or "").strip()
        src = str(src or "")
        if not src or "noimage" in src.lower() or not re.search(r"ATTFILE_SEQ_NO=\d+", src, re.I):
            continue
        if seq in ("", "0") and "ATTFILE_SEQ_NO=0" in src:
            continue
        out.append((index, src))
    return out


def no_photo_contract(row: dict) -> bool:
    """용역 · 공사 계약 — 물품정보 줄이 있어도 물품 사진이 없다(2026-10-22 실제: 이런 건 22건이 모두 사진 칸에서 '못 받음' 이 됐다)."""
    kind = re.sub(r"\s", "", str(row.get("kind") or ""))
    name = str(row.get("cont_nm") or "").lstrip()
    return any(k in kind for k in ("용역", "공사")) or name.startswith(("[용역]", "[공사]"))


def _photo_problem(result: CaseResult, why: str, optional: bool, log: Callable[[str], None]) -> None:
    if optional:
        log(f"      · {why} — 용역 · 공사 계약이라 사진 없이 넘어갑니다")
        return
    log(f"      ✖ {why}")
    result.failed.append(why)
    result.ok = False


def item_photos(context, page, frame, item: dict, folder: Path, result: CaseResult, log: Callable[[str], None],
                wait: Callable[[float], None], optional: bool = False) -> None:
    """물품정보 줄을 더블클릭해 물품내역팝업을 열고 사진을 받은 뒤 그 창을 닫는다. optional(용역 · 공사)이면 사진이 없어도 실패가 아니다."""
    popup = None
    try:
        with context.expect_page(timeout=POPUP_TIMEOUT_MS) as opened:
            frame.dblclick(ITEM_ROW_SELECTOR.format(r=item.get("r", "")), timeout=5000)
        popup = opened.value
        try:
            popup.wait_for_load_state("domcontentloaded", timeout=POPUP_TIMEOUT_MS)
        except Exception:  # noqa: BLE001
            pass
        info = _wait_for(lambda: _eval(popup.main_frame, POPUP_JS), wait, 16)
    except Exception as error:  # noqa: BLE001
        why = str(error).splitlines()[0][:100] if str(error) else type(error).__name__
        _photo_problem(result, f"물품 '{item.get('name', '')}' 사진: 팝업이 뜨지 않음({why})", optional, log)
        info = None
    if info:
        name = info.get("item") or item.get("name") or "물품"
        for index, src in _photo_urls(info):
            body, ctype, why = fetch_in(popup.main_frame, page, urljoin(str(popup.url or ""), src))
            if body is None:
                _photo_problem(result, f"물품사진 {name} {index}: {why}", optional, log)
                continue
            dest = folder / INSPECT_DIR / photo_name(name, index, ctype, body)
            if dest.exists():
                result.existed += 1
                continue
            try:
                _write(dest, body)
            except DiskFull:
                try:
                    popup.close()
                except Exception:  # noqa: BLE001
                    pass
                raise
            except OSError as error:
                _photo_problem(result, f"물품사진 {name} {index}: 저장하지 못함({error})", optional, log)
                continue
            result.saved.append(f"{INSPECT_DIR}/{dest.name}")
            result.photos += 1
            result.size += len(body)
            log(f"      ✓ {INSPECT_DIR}/{dest.name} ({len(body):,} B)")
    elif popup is not None:
        _photo_problem(result, f"물품 '{item.get('name', '')}' 사진: 팝업에 사진 칸이 없음", optional, log)
    if popup is not None:
        try:
            popup.close()
        except Exception:  # noqa: BLE001
            pass


def open_inspection(context, log: Callable[[str], None], wait: Callable[[float], None]):
    frame = inspect_frame(context)
    if frame is None:
        ok, why = _click_any(context, LEFT_MENU_JS, "검사처리")
        if not ok:
            return None, f"왼쪽 메뉴 '검사처리' 를 누르지 못했습니다({why})"
        log("왼쪽 메뉴 '검사처리' 를 눌렀습니다")
        frame = _wait_for(lambda: inspect_frame(context), wait, LIST_TRIES)
        if frame is None:
            return None, "'검사처리' 를 눌렀지만 그 화면이 뜨지 않았습니다"
    if _eval(frame, VISIBLE_JS) is not True:
        show_tab(context, "검사처리", log)
        _wait_for(lambda: _eval(frame, VISIBLE_JS) is True, wait, 10)
    return frame, ""


def inspect_cases(context, page, cases: dict[str, CaseResult], folders: dict[str, Path], start: str, end: str,
                  log: Callable[[str], None], wait: Callable[[float], None], should_stop: Callable[[], bool],
                  summary: PurchaseSummary) -> None:
    """검사처리 화면 — 계약일자 범위마다 목록을 읽고, 받은 건(구매요구번호)의 줄을 골라 첨부 · 물품 사진을 그 건 폴더의 '검사처리' 에."""
    frame, why = open_inspection(context, log, wait)
    if frame is None:
        summary.note = why
        log("⚠ 검사처리 서류는 받지 못했습니다 — " + why)
        return
    for s, e in windows(start, end):
        if should_stop():
            summary.stopped = True
            return
        ok, why = search(frame, s, e, log, wait, what="계약일자")
        if not ok:
            summary.note = f"검사처리 조회 실패: {why}"
            log("⚠ " + summary.note)
            return
        rows = collect_inspection(frame, wait)
        mine = [r for r in rows if r.get("req_no") in cases]
        summary.inspected_rows += len(rows)
        log(f"검사처리 계약 건 {len(rows)}줄 — 그중 받은 건의 것 {len(mine)}줄")
        for row in mine:
            if should_stop():
                summary.stopped = True
                return
            result = cases[row["req_no"]]
            folder = folders.get(row["req_no"])
            if folder is None:
                continue
            ok, why = select_inspection(frame, row, wait)
            if not ok:
                result.failed.append(f"검사처리 줄({row.get('cont_nm', '')[:20]}): {why}")
                result.ok = False
                log(f"      ✖ {result.failed[-1]}")
                continue
            result.inspected = True
            files = _eval(frame, INSPECT_FILES_JS) or []
            items = _eval(frame, ITEMS_JS) or []
            log(f"      검사처리 '{row.get('cont_nm', '')[:30]}' — 첨부 {len(files)}개 · 물품 {len(items)}개")
            _save_files(page, _frame_url(frame), files, folder / INSPECT_DIR, result, log, prefix=INSPECT_DIR + "/", frame=frame)
            optional = no_photo_contract(row)
            for item in items:
                item_photos(context, page, frame, item, folder, result, log, wait, optional=optional)


def run(context, page, targets: list[dict], out_root: str, log: Callable[[str], None], wait: Callable[[float], None],
        notify: Callable[[int, str, str], None], should_stop: Callable[[], bool] = lambda: False) -> PurchaseSummary:
    """받기 표의 구매 줄들(as_target 모양)을 받는다. notify(표 번호, 상태, 글)는 청구서 받기와 같은 신호."""
    summary = PurchaseSummary()
    if not targets:
        return summary
    home = purchase_home(out_root)
    need = reserve_for(home)
    free = free_space(home)
    if free is not None:
        log(f"구매요청(계약) 서류 저장 위치 {home} — 남은 공간 {size_text(free)}")
        if free < need:
            # 구글 드라이브 무료 15GB 가 다 차 '0바이트 사용 가능' 이던 것(담당자 2026-10-22) — 쓰다 말고 수백 개 실패로 끝나지 않게 시작 전에 멈춘다
            why = (f"저장 위치에 남은 공간이 {size_text(free)} 뿐이라 받지 않았습니다(남겨 둘 공간 {size_text(need)}) — "
                   "설정 → '구매요청(계약) 서류 저장 위치' 를 공간이 넉넉한 드라이브(네이버 MYBOX 등)로 바꾸세요")
            log("⚠ " + why)
            summary.note = why
            summary.stopped = True
            for i, t in enumerate(targets):
                summary.cases.append(CaseResult(str(t.get("req_no") or ""), t.get("cont", ""), t.get("project", ""), note=why, ok=False))
                notify(i, "failed", why)
            return summary
    # 저장 위치가 MYBOX 처럼 C: 밖이어도 그 프로그램이 C: 에 사본(캐시 · 1:1 동기화)을 둘 수 있다 — 담당자 2026-10-22
    # "데스크톱 용량에는 영향이 가지 않게". C: 남은 공간을 시작 · 끝에 적고, 받는 동안 줄어 10GB 아래가 되면 멈춘다
    pc = system_root()
    pc_start = free_space(pc) if pc and _drive_letter(pc) != _drive_letter(home) else None
    if pc_start is not None:
        log(f"PC({pc.rstrip(chr(92))}) 남은 공간 {size_text(pc_start)} — 받는 동안 줄어 {size_text(SYSTEM_RESERVE)} 아래가 되면 멈춥니다")
    fixed = fix_photo_names(home)
    if fixed:
        log(f"물품 사진 {len(fixed)}장의 확장자를 그림 파일대로 바꿨습니다(.html 로 저장돼 있던 것)")
    days = [t.get("expDt") or req_date(t.get("req_no", "")) for t in targets]
    days = [d for d in days if d]
    start, end = widen(min(days), max(days)) if days else ("", "")
    frame, why = open_list(context, log, wait)
    if frame is None:
        log("⚠ " + why)
        for i, t in enumerate(targets):
            summary.cases.append(CaseResult(str(t.get("req_no") or ""), t.get("cont", ""), t.get("project", ""), note=why, ok=False))
            notify(i, "failed", why)
        return summary
    cases: dict[str, CaseResult] = {}
    folders: dict[str, Path] = {}
    order = sorted(range(len(targets)), key=lambda i: (targets[i].get("expDt") or "", i))
    for n, i in enumerate(order, 1):
        target = targets[i]
        if should_stop():
            summary.stopped = True
            log("멈춤 요청 — 여기서 그만 받습니다.")
            break
        left = free_space(home)
        pc_left = free_space(pc) if pc_start is not None else None
        why = ""
        if left is not None and left < need:
            why = (f"저장 위치에 남은 공간이 {size_text(left)} 로 줄어 여기서 멈춥니다(남겨 둘 공간 {size_text(need)}) — "
                   "설정 → '구매요청(계약) 서류 저장 위치' 를 공간이 넉넉한 드라이브(네이버 MYBOX 등)로 바꾸세요")
        elif pc_left is not None and pc_left < SYSTEM_RESERVE and pc_left < pc_start:
            why = (f"PC({pc.rstrip(chr(92))}) 남은 공간이 {size_text(pc_left)} 로 줄어 여기서 멈춥니다(받기 전 {size_text(pc_start)}) — "
                   f"저장 위치({home})를 올려 주는 프로그램(MYBOX 등)이 C: 에 사본을 두는지 그 프로그램 설정을 확인하세요")
        if why:
            log("⚠ " + why)
            summary.note = why
            summary.stopped = True
            break
        notify(i, "running", "")
        log("[%d/%d] 구매요구 %s · %s" % (n, len(targets), target.get("req_no"), (target.get("cont") or "")[:30]))
        day = target.get("expDt") or req_date(target.get("req_no", ""))
        window = window_for(day, start, end) if day else None
        if window is None:
            window = windows(start, end)[0] if windows(start, end) else None
        if frame is None or window is None:
            frame, why = open_list(context, log, wait)
            if frame is None:
                result = CaseResult(str(target.get("req_no") or ""), target.get("cont", ""), target.get("project", ""), note=why, ok=False)
                summary.cases.append(result)
                notify(i, "failed", why)
                continue
        if window is not None:
            ok, why = ensure_range(frame, window[0], window[1], log, wait, str(target.get("req_no") or ""))
            if not ok:
                log("      ✖ " + why)
                result = CaseResult(str(target.get("req_no") or ""), target.get("cont", ""), target.get("project", ""), note=why, ok=False)
                summary.cases.append(result)
                notify(i, "failed", why)
                continue
        try:
            result, frame = receive_case(context, page, frame, target, out_root, log, wait)
        except DiskFull as error:
            why = f"{error} — 설정 → '구매요청(계약) 서류 저장 위치' 를 공간이 넉넉한 드라이브(네이버 MYBOX 등)로 바꾸세요"
            log("⚠ " + why)
            summary.note = why
            summary.stopped = True
            summary.cases.append(CaseResult(str(target.get("req_no") or ""), target.get("cont", ""), target.get("project", ""), note=why, ok=False))
            notify(i, "failed", why)
            break
        summary.cases.append(result)
        cases[result.req_no] = result
        if result.folder:
            folders[result.req_no] = Path(result.folder)
        notify(i, "running" if result.ok else "failed", result.summary() + ("" if not result.ok else " · 검사처리 확인 중"))
    if folders and not summary.stopped and start:
        try:
            inspect_cases(context, page, cases, folders, start, end, log, wait, should_stop, summary)
        except DiskFull as error:
            summary.note = f"{error} — 설정 → '구매요청(계약) 서류 저장 위치' 를 공간이 넉넉한 드라이브(네이버 MYBOX 등)로 바꾸세요"
            summary.stopped = True
            log("⚠ " + summary.note)
    for i in order:
        req_no = str(targets[i].get("req_no") or "")
        result = cases.get(req_no)
        if result is not None:
            notify(i, "done" if result.ok else "failed", result.summary())
    if not summary.stopped:
        try:
            remember_done(summary.cases, home)
        except Exception as error:  # noqa: BLE001
            log(f"⚠ 받은 기록을 남기지 못함: {error}")
    for result in summary.failed:
        # 기록의 '실패: 구매요구 …' 줄만으로는 까닭을 몰랐다(2026-10-22 19:19 · 19:31 실제 — 22건)
        reasons = result.failed[:3] + ([result.note] if result.note else [])
        more = f" 외 {len(result.failed) - 3}개" if len(result.failed) > 3 else ""
        log(f"   ✖ 구매요구 {result.req_no} — {' / '.join(reasons) or '까닭 모름'}{more}")
    log("── 구매요청(계약) 서류 끝: 건 %d · 새 파일 %d개(%s) · 못 받은 건 %d"
        % (len(summary.cases), summary.files, size_text(summary.size), len(summary.failed)))
    after = free_space(home)
    if after is not None:
        log(f"   저장 위치 남은 공간 {size_text(after)}")
    pc_end = free_space(pc) if pc_start is not None else None
    if pc_end is not None:
        used = pc_start - pc_end
        log(f"   PC({pc.rstrip(chr(92))}) 남은 공간 {size_text(pc_end)} — 받기 전보다 "
            + (f"{size_text(used)} 줄었습니다" if used > 0 else "줄지 않았습니다"))
    return summary
