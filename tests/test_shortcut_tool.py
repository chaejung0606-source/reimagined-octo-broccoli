"""바로가기 도구(tools/create_shortcut.py) — 윈도우 없이 볼 수 있는 부분.

COM 호출은 윈도우에서만 되지만, 구조체 크기가 틀리면 조용히 엉뚱한 메모리를 쓰므로 여기서 잡는다.
"""
import ctypes
import importlib.util
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1] / "tools" / "create_shortcut.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("create_shortcut", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_imports_without_windows():
    """리눅스(CI)에서도 모듈을 읽을 수 있어야 한다 — 윈도우 전용 ctypes 속성은 함수 안에서만 만진다."""
    module = load_tool()
    assert module.APP_ID and module.APP_NAME == "COSS 업무데스크"


def test_com_struct_sizes_match_windows_headers():
    module = load_tool()
    pointer = ctypes.sizeof(ctypes.c_void_p)
    assert ctypes.sizeof(module._Guid) == 16
    assert ctypes.sizeof(module._PropertyKey) == 20                   # GUID + DWORD pid
    assert ctypes.sizeof(module._PropVariant) == 8 + 2 * pointer      # vt·예약 8바이트 + 16바이트 union
    assert module._PropVariant.pointer.offset == 8                    # 문자열 포인터는 8바이트 자리에서 시작
    assert module.PKEY_APP_ID_PID == 5 and module._VT_LPWSTR == 31


def test_no_powershell_or_csharp_in_tool():
    """담당자 PC 에서 조용히 실패하던 길(PowerShell + Add-Type)로 되돌아가지 않는다."""
    source = TOOL.read_text(encoding="utf-8")
    assert "import subprocess" not in source and '"powershell"' not in source
    assert "ctypes.oledll.ole32.CoCreateInstance" in source


def test_points_here_matches_any_field():
    module = load_tool()
    root = Path("C:/Users/me/AppData/Local/COSS업무데스크/app")
    target = str(root).replace("/", "\\").lower() + "\\.venv\\scripts\\pythonw.exe"
    assert module.points_here(target, "-m claim_downloader.ui.app", "", root=root) or \
        module.points_here("", "", str(root), root=root)
    assert module.points_here("", "", str(root).upper(), root=root)
    assert not module.points_here("C:\\Python311\\pythonw.exe", "-m something", "C:\\Other", root=root)
    assert not module.points_here(None, None, None, root=root)


def test_shortcut_icon_has_its_own_name_with_the_current_picture():
    """윈도우는 아이콘을 경로로 저장해 둔다 — 바로가기는 디자인마다 이름이 다른 파일을 가리키고, 그 파일은 icon.ico 와 같은 그림이다."""
    module = load_tool()
    path = module.icon_path()
    assert path.name == module.SHORTCUT_ICON != "icon.ico"
    assert path.read_bytes() == (module.ASSETS / "icon.ico").read_bytes()
    assert [p.name for p in module.ASSETS.glob("icon-*.ico")] == [module.SHORTCUT_ICON]   # 옛 디자인 파일이 남지 않게
