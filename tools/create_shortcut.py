"""바탕화면 바로가기 만들기.

이 저장소 폴더에서 한 번 실행하면, 바탕화면과 시작 메뉴에 아이콘이 붙은
'COSS 업무데스크' 바로가기가 생긴다. 더블클릭하면 앱이 뜬다.

    python tools/create_shortcut.py

윈도우는 .lnk, 리눅스는 .desktop 을 만든다. macOS 는 안내만 출력한다.

윈도우에서는 PowerShell 을 쓰지 않고 ctypes 로 셸 링크(COM)를 직접 다룬다. 전에는 PowerShell 에 C# 을
컴파일시켜(Add-Type) 작업 표시줄 이름을 적었는데, 담당자 PC 에서 그 단계가 조용히 실패해 바로가기에
이름이 안 붙은 채 단추가 둘로 남았다(2026-10-13). ctypes 는 파이썬에 들어 있어 컴파일·따옴표·
인코딩 문제가 없고, 적은 뒤 다시 읽어 확인까지 한다.
"""
from __future__ import annotations

import ctypes
import sys
from pathlib import Path

APP_NAME = "COSS 업무데스크"
# 작업 표시줄이 바로가기와 실행 중인 창을 한 단추로 묶는 이름. 앱과 같은 값을 써야 하므로 한 곳(settings)에서만
# 읽는다 — 여기 따로 적어 두면 둘이 어긋나는 순간 단추가 둘로 갈라진다(2026-10-13 담당자 보고).
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from claim_downloader.settings import APP_USER_MODEL_ID as APP_ID  # noqa: E402
# 이 저장소가 이전 이름이던 시절의 바로가기들. 남겨 두면 아이콘이 여럿이 돼
# 어느 쪽을 눌러야 할지 헷갈린다. 새 바로가기를 만들 때 함께 치운다.
OLD_APP_NAMES = ("지출 서류 검토", "ERP 청구서 다운로더", "업무 도구함")
MODULE = "claim_downloader.ui.app"
REPO_ROOT = Path(__file__).resolve().parents[1]
ASSETS = REPO_ROOT / "src" / "claim_downloader" / "ui" / "assets"


def _pythonw() -> Path:
    """콘솔 창 없이 띄울 실행 파일.

    '앱 실행.bat' 이 만든 .venv 를 먼저 찾는다. 거기에 앱 의존성이 들어 있다.
    없으면 지금 이 스크립트를 돌리는 파이썬으로 돌아간다.
    """
    for base in (REPO_ROOT / ".venv" / "Scripts", Path(sys.executable).parent):
        for name in ("pythonw.exe", "python.exe", "python3", "python"):
            candidate = base / name
            if candidate.exists():
                return candidate
    return Path(sys.executable)


# ── 윈도우 셸 링크(COM) ───────────────────────────────────────────────────────
# 인터페이스 번호(가상 함수 표 순서)와 GUID 는 shobjidl.h · propkey.h 의 것. 윈도우 밖에서는 아래 클래스들을
# 만들 수만 있고(테스트가 구조체 크기를 본다) 부르지는 못한다.

_CLSID_SHELL_LINK = "{00021401-0000-0000-C000-000000000046}"
_IID_SHELL_LINK_W = "{000214F9-0000-0000-C000-000000000046}"
_IID_PERSIST_FILE = "{0000010B-0000-0000-C000-000000000046}"
_IID_PROPERTY_STORE = "{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}"
PKEY_APP_ID_FMTID = "{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}"      # PKEY_AppUserModel_ID (System.AppUserModel.ID)
PKEY_APP_ID_PID = 5
_KNOWN_FOLDERS = {
    "Desktop": "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",
    "Programs": "{A77F5D77-2E2B-44C3-A6A2-ABA601054A51}",         # 시작 메뉴 > 프로그램 (사용자)
    "RoamingAppData": "{3EB685DB-65F9-4CF6-A03A-E3EF65729F3D}",
}
_VT_LPWSTR = 31
_CLSCTX_INPROC_SERVER = 1
_TEXT_BUFFER = 2048


class _Guid(ctypes.Structure):
    _fields_ = [("data1", ctypes.c_uint32), ("data2", ctypes.c_uint16), ("data3", ctypes.c_uint16),
                ("data4", ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, text: str) -> "_Guid":
        guid = cls()
        ctypes.oledll.ole32.CLSIDFromString(text, ctypes.byref(guid))
        return guid


class _PropertyKey(ctypes.Structure):
    _fields_ = [("fmtid", _Guid), ("pid", ctypes.c_uint32)]


class _PropVariant(ctypes.Structure):
    # PROPVARIANT: vt(2) + 예약 3×2 = 8바이트, 그 뒤 값(여기서는 문자열 포인터). 전체는 64비트 24 / 32비트 16바이트.
    _fields_ = [("vt", ctypes.c_uint16), ("reserved1", ctypes.c_uint16), ("reserved2", ctypes.c_uint16),
                ("reserved3", ctypes.c_uint16), ("pointer", ctypes.c_void_p), ("padding", ctypes.c_void_p)]


class _Com:
    """COM 인터페이스 포인터 하나. 가상 함수 표에서 번호로 메서드를 꺼내 부른다. 실패(HRESULT<0)는 OSError."""

    def __init__(self, pointer: ctypes.c_void_p) -> None:
        self.pointer = pointer

    def call(self, index: int, argtypes: tuple, *args, restype=None):
        vtable = ctypes.cast(self.pointer, ctypes.POINTER(ctypes.c_void_p))[0]
        function = ctypes.cast(ctypes.c_void_p(vtable), ctypes.POINTER(ctypes.c_void_p))[index]
        prototype = ctypes.WINFUNCTYPE(restype or ctypes.HRESULT, ctypes.c_void_p, *argtypes)
        return prototype(function)(self.pointer, *args)

    def query(self, iid: str) -> "_Com":
        out = ctypes.c_void_p()
        self.call(0, (ctypes.POINTER(_Guid), ctypes.POINTER(ctypes.c_void_p)),
                  ctypes.byref(_Guid.parse(iid)), ctypes.byref(out))
        return _Com(out)

    def release(self) -> None:
        self.call(2, (), restype=ctypes.c_ulong)


class _ShellLink:
    """.lnk 하나 — IShellLinkW · IPersistFile · IPropertyStore 를 같은 객체에서 꺼내 쓴다."""

    def __init__(self) -> None:
        ctypes.windll.ole32.CoInitialize(None)
        pointer = ctypes.c_void_p()
        ctypes.oledll.ole32.CoCreateInstance(ctypes.byref(_Guid.parse(_CLSID_SHELL_LINK)), None, _CLSCTX_INPROC_SERVER,
                                             ctypes.byref(_Guid.parse(_IID_SHELL_LINK_W)), ctypes.byref(pointer))
        self._link = _Com(pointer)
        self._file = self._link.query(_IID_PERSIST_FILE)
        self._store = self._link.query(_IID_PROPERTY_STORE)

    def close(self) -> None:
        for com in (self._store, self._file, self._link):
            com.release()

    # IPersistFile
    def load(self, path: Path) -> None:
        self._file.call(5, (ctypes.c_wchar_p, ctypes.c_uint32), str(path), 0)

    def save(self, path: Path) -> None:
        self._file.call(6, (ctypes.c_wchar_p, ctypes.c_int), str(path), 1)

    # IShellLinkW
    def _text(self, index: int, *extra) -> str:
        buffer = ctypes.create_unicode_buffer(_TEXT_BUFFER)
        argtypes = (ctypes.c_wchar_p, ctypes.c_int) + tuple(type(value) for value in extra)
        self._link.call(index, argtypes, buffer, _TEXT_BUFFER, *extra)
        return buffer.value

    def target(self) -> str:
        return self._text(3, ctypes.c_void_p(None), ctypes.c_uint32(0))    # GetPath(…, pfd=NULL, flags=0)

    def working_dir(self) -> str:
        return self._text(8)

    def arguments(self) -> str:
        return self._text(10)

    def set_target(self, path: Path) -> None:
        self._link.call(20, (ctypes.c_wchar_p,), str(path))

    def set_description(self, text: str) -> None:
        self._link.call(7, (ctypes.c_wchar_p,), text)

    def set_working_dir(self, path: Path) -> None:
        self._link.call(9, (ctypes.c_wchar_p,), str(path))

    def set_arguments(self, text: str) -> None:
        self._link.call(11, (ctypes.c_wchar_p,), text)

    def set_icon(self, path: Path) -> None:
        self._link.call(17, (ctypes.c_wchar_p, ctypes.c_int), str(path), 0)

    # IPropertyStore — 작업 표시줄 이름
    @staticmethod
    def _key() -> _PropertyKey:
        return _PropertyKey(_Guid.parse(PKEY_APP_ID_FMTID), PKEY_APP_ID_PID)

    def app_id(self) -> str:
        key = self._key()
        value = _PropVariant()
        self._store.call(5, (ctypes.POINTER(_PropertyKey), ctypes.POINTER(_PropVariant)),
                         ctypes.byref(key), ctypes.byref(value))
        try:
            if value.vt != _VT_LPWSTR or not value.pointer:
                return ""
            return ctypes.wstring_at(value.pointer)
        finally:
            ctypes.windll.ole32.PropVariantClear(ctypes.byref(value))

    def set_app_id(self, app_id: str) -> None:
        key = self._key()
        text = ctypes.create_unicode_buffer(app_id)      # SetValue 가 복사해 가므로 호출 동안만 살아 있으면 된다
        value = _PropVariant(vt=_VT_LPWSTR, pointer=ctypes.addressof(text))
        self._store.call(6, (ctypes.POINTER(_PropertyKey), ctypes.POINTER(_PropVariant)),
                         ctypes.byref(key), ctypes.byref(value))
        self._store.call(7, ())                           # Commit


def _known_folder(name: str) -> Path:
    """바탕화면·시작 메뉴 위치. OneDrive 로 옮겨진 바탕화면도 이 API 가 맞게 준다."""
    out = ctypes.c_wchar_p()
    ctypes.oledll.shell32.SHGetKnownFolderPath(ctypes.byref(_Guid.parse(_KNOWN_FOLDERS[name])), 0, None, ctypes.byref(out))
    try:
        return Path(out.value)
    finally:
        ctypes.windll.ole32.CoTaskMemFree(out)


def _write_link(link: Path) -> None:
    """바로가기를 새로 만들면서 작업 표시줄 이름까지 함께 적는다."""
    shortcut = _ShellLink()
    try:
        shortcut.set_target(_pythonw())
        shortcut.set_arguments(f"-m {MODULE}")
        shortcut.set_working_dir(REPO_ROOT)
        shortcut.set_icon(ASSETS / "icon.ico")
        shortcut.set_description("청구서 받기 등 업무를 한곳에서 시작합니다")
        shortcut.set_app_id(APP_ID)
        shortcut.save(link)
    finally:
        shortcut.close()


def _tag_link(link: Path) -> None:
    """이미 있는 바로가기(고정된 복사본)에 작업 표시줄 이름을 적는다."""
    shortcut = _ShellLink()
    try:
        shortcut.load(link)
        shortcut.set_app_id(APP_ID)
        shortcut.save(link)
    finally:
        shortcut.close()


def _read_app_id(link: Path) -> str:
    shortcut = _ShellLink()
    try:
        shortcut.load(link)
        return shortcut.app_id()
    finally:
        shortcut.close()


def points_here(target: str, arguments: str, working_dir: str, root: Path = REPO_ROOT) -> bool:
    """바로가기가 이 저장소의 앱을 가리키는지 — 대상·인수·작업 폴더 어디든 저장소 경로가 들어 있으면."""
    needle = str(root).lower()
    return any(needle in (part or "").lower() for part in (target, arguments, working_dir))


def _pinned_links() -> list[Path]:
    """작업 표시줄에 고정해 둔 이 앱의 바로가기.

    고정할 때 윈도우가 .lnk 를 복사해 두므로, 새로 만든 바로가기에 이름을 적어도 고정된 복사본은 옛것이다.
    그 복사본에도 같은 이름을 적어야 단추가 하나로 합쳐진다. 못 찾으면 담당자가 고정을 풀고 다시 고정한다.
    """
    pinned = _known_folder("RoamingAppData") / "Microsoft" / "Internet Explorer" / "Quick Launch" / "User Pinned" / "TaskBar"
    if not pinned.is_dir():
        print("고정된 바로가기 폴더가 없습니다:", pinned)
        return []
    found: list[Path] = []
    seen = 0
    for path in sorted(pinned.glob("*.lnk")):
        shortcut = _ShellLink()
        try:
            shortcut.load(path)
            fields = (shortcut.target(), shortcut.arguments(), shortcut.working_dir())
        except OSError as error:
            print(f"고정된 바로가기를 읽지 못했습니다: {path.name} ({error})")
            continue
        finally:
            shortcut.close()
        seen += 1
        if points_here(*fields):
            found.append(path)
    print(f"고정된 바로가기 {seen}개 중 이 앱 것 {len(found)}개: " + (", ".join(p.name for p in found) or "(없음)"))
    return found


def make_windows() -> Path:
    """바탕화면과 시작 메뉴에 하나씩, 그리고 이미 고정해 둔 것까지 같은 작업 표시줄 이름으로.

    시작 메뉴 것이 있어야 실행 중인 창을 작업 표시줄에 고정할 때 윈도우가 알아본다.
    """
    desktop = _known_folder("Desktop")
    programs = _known_folder("Programs")
    links = [desktop / f"{APP_NAME}.lnk", programs / f"{APP_NAME}.lnk"]
    for link in links:
        link.parent.mkdir(parents=True, exist_ok=True)
        _write_link(link)
    print("만든 바로가기:", ", ".join(str(p) for p in links))
    pinned = _pinned_links()
    for link in pinned:
        try:
            _tag_link(link)
        except OSError as error:
            print(f"고정된 바로가기에 이름을 적지 못했습니다: {link.name} ({error})")
    for folder in (desktop, programs):
        for old in OLD_APP_NAMES:
            (folder / f"{old}.lnk").unlink(missing_ok=True)
    # 적은 이름을 다시 읽어 확인한다. 이름 없는 바로가기는 단추가 둘로 갈라지므로 하나라도 빠지면 실패로 알린다 —
    # 앱(shortcuts.refresh)은 실패면 표시를 남기지 않아 다음에 켤 때 다시 해 본다.
    wrong = []
    for link in links + pinned:
        try:
            got = _read_app_id(link)
        except OSError as error:
            got = f"읽기 실패 ({error})"
        if got != APP_ID:
            wrong.append(f"{link.name}: {got or '(비어 있음)'}")
    if wrong:
        print("작업 표시줄 이름이 적히지 않은 바로가기:", "; ".join(wrong))
        raise SystemExit(2)
    print(f"작업 표시줄 이름 확인: {APP_ID} — " + ", ".join(p.name for p in links + pinned))
    return links[0]


def make_linux() -> Path:
    desktop_dir = Path.home() / "Desktop"
    if not desktop_dir.exists():
        desktop_dir = Path.home()
    entry = desktop_dir / "claim-downloader.desktop"
    entry.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_NAME}\n"
        f"Exec={_pythonw()} -m {MODULE}\n"
        f"Path={REPO_ROOT}\n"
        f"Icon={ASSETS / 'icon.png'}\n"
        "Terminal=false\n",
        encoding="utf-8",
    )
    entry.chmod(0o755)
    (desktop_dir / "expense-review.desktop").unlink(missing_ok=True)
    return entry


def main() -> None:
    if sys.platform.startswith("win"):
        link = make_windows()
    elif sys.platform.startswith("linux"):
        link = make_linux()
    else:
        print("macOS 는 자동 생성을 지원하지 않습니다.\n"
              "Automator 로 '응용 프로그램'을 만들어 아래 명령을 넣고,\n"
              f"아이콘은 {ASSETS / 'icon.png'} 를 지정하세요:\n"
              f"  cd {REPO_ROOT} && {sys.executable} -m {MODULE}")
        return
    print(f"바로가기를 만들었습니다: {link}")


if __name__ == "__main__":
    main()
