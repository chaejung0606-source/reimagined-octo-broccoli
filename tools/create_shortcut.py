"""바탕화면 바로가기 만들기.

이 저장소 폴더에서 한 번 실행하면, 바탕화면에 아이콘이 붙은
'ERP 청구서 다운로더' 바로가기가 생긴다. 더블클릭하면 앱이 뜬다.

    python tools/create_shortcut.py

윈도우는 .lnk, 리눅스는 .desktop 을 만든다. macOS 는 안내만 출력한다.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# 창 없는 실행(pythonw) 아래서 powershell 이 검은 창을 띄우지 않게
_HIDDEN = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform.startswith("win") else {}

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


# 바로가기에 작업 표시줄 이름(System.AppUserModel.ID)을 적는다. WScript.Shell 로는 못 적어 셸 링크의
# 속성 저장소(IPropertyStore)를 직접 쓴다. 실패해도 바로가기 자체는 이미 만들어진 뒤다.
_TAG_CODE = r"""
using System;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
namespace CossShortcut {
  [StructLayout(LayoutKind.Sequential, Pack = 4)]
  public struct PropertyKey { public Guid fmtid; public uint pid; public PropertyKey(Guid f, uint p) { fmtid = f; pid = p; } }
  [StructLayout(LayoutKind.Explicit)]
  public struct PropVariant {
    [FieldOffset(0)] public ushort vt;
    [FieldOffset(8)] public IntPtr pointerValue;
    [FieldOffset(16)] public IntPtr padding;
  }
  [ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  public interface IPropertyStore {
    void GetCount(out uint cProps);
    void GetAt(uint iProp, out PropertyKey pkey);
    void GetValue(ref PropertyKey key, out PropVariant pv);
    void SetValue(ref PropertyKey key, ref PropVariant pv);
    void Commit();
  }
  [ComImport, Guid("00021401-0000-0000-C000-000000000046")]
  public class ShellLink { }
  public static class Tagger {
    public static void SetAppId(string lnkPath, string appId) {
      object link = new ShellLink();
      IPersistFile file = (IPersistFile)link;
      file.Load(lnkPath, 0);
      IPropertyStore store = (IPropertyStore)link;
      PropertyKey key = new PropertyKey(new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), 5);
      PropVariant pv = new PropVariant();
      pv.vt = 31;
      pv.pointerValue = Marshal.StringToCoTaskMemUni(appId);
      try { store.SetValue(ref key, ref pv); store.Commit(); }
      finally { Marshal.FreeCoTaskMem(pv.pointerValue); }
      file.Save(lnkPath, true);
    }
  }
}
"""


def _create_link(link: Path) -> None:
    script = f"""
$shell = New-Object -ComObject WScript.Shell
$sc = $shell.CreateShortcut('{link}')
$sc.TargetPath = '{_pythonw()}'
$sc.Arguments = '-m {MODULE}'
$sc.WorkingDirectory = '{REPO_ROOT}'
$sc.IconLocation = '{ASSETS / "icon.ico"}'
$sc.Description = '청구서 받기 등 업무를 한곳에서 시작합니다'
$sc.Save()
"""
    subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True, **_HIDDEN)


def _tag_links(links: list[Path]) -> bool:
    paths = ", ".join(f"'{p}'" for p in links)
    script = "$code = @'\n" + _TAG_CODE.strip() + "\n'@\nAdd-Type -TypeDefinition $code\n" \
             f"foreach ($p in @({paths})) {{ [CossShortcut.Tagger]::SetAppId($p, '{APP_ID}') }}\n"
    done = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", **_HIDDEN)
    if done.returncode != 0 or (done.stderr or "").strip():
        print("작업 표시줄 이름을 바로가기에 적지 못했습니다 (바로가기 자체는 만들어짐):")
        print((done.stderr or done.stdout or "(출력 없음)")[-1200:])
        return False
    print("작업 표시줄 이름을 적었습니다:", ", ".join(p.name for p in links))
    return True


def _folder(name: str) -> Path:
    return Path(subprocess.check_output(
        ["powershell", "-NoProfile", "-Command", f"[Environment]::GetFolderPath('{name}')"],
        text=True, **_HIDDEN).strip())


def _pinned_links() -> list[Path]:
    """작업 표시줄에 고정해 둔 이 앱의 바로가기 — 대상이나 작업 폴더가 이 저장소를 가리키는 것.

    고정할 때 윈도우가 .lnk 를 복사해 두므로, 새로 만든 바로가기에 이름을 적어도 고정된 복사본은 옛것이다.
    그 복사본에도 같은 이름을 적어야 단추가 하나로 합쳐진다. 못 찾으면 담당자가 고정을 풀고 다시 고정한다.
    """
    pinned = Path(_folder("ApplicationData")) / "Microsoft" / "Internet Explorer" / "Quick Launch" / "User Pinned" / "TaskBar"
    if not pinned.is_dir():
        return []
    script = f"""
$shell = New-Object -ComObject WScript.Shell
Get-ChildItem -LiteralPath '{pinned}' -Filter *.lnk | ForEach-Object {{
  $sc = $shell.CreateShortcut($_.FullName)
  Write-Output ($_.FullName + "`t" + $sc.TargetPath + "`t" + $sc.Arguments + "`t" + $sc.WorkingDirectory)
}}
"""
    out = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", **_HIDDEN)
    root = str(REPO_ROOT).lower()
    found = []
    seen = 0
    for line in (out.stdout or "").splitlines():
        parts = line.split("\t")
        if len(parts) != 4:
            continue
        seen += 1
        if any(root in part.lower() for part in parts[1:]):
            found.append(Path(parts[0]))
    print(f"고정된 바로가기 {seen}개 중 이 앱 것 {len(found)}개: " + (", ".join(p.name for p in found) or "(없음)"))
    return found


def make_windows() -> Path:
    """바탕화면과 시작 메뉴에 하나씩, 그리고 이미 고정해 둔 것까지 같은 작업 표시줄 이름으로.

    시작 메뉴 것이 있어야 실행 중인 창을 작업 표시줄에 고정할 때 윈도우가 알아본다.
    """
    desktop = _folder("Desktop")
    programs = _folder("Programs")
    links = [desktop / f"{APP_NAME}.lnk", programs / f"{APP_NAME}.lnk"]
    for link in links:
        link.parent.mkdir(parents=True, exist_ok=True)
        _create_link(link)
    print("만든 바로가기:", ", ".join(str(p) for p in links))
    pinned = _pinned_links()
    tagged = _tag_links(links + pinned)
    for folder in (desktop, programs):
        for old in OLD_APP_NAMES:
            (folder / f"{old}.lnk").unlink(missing_ok=True)
    if not tagged:
        # 이름 없는 바로가기는 단추가 둘로 갈라진다 — 앱이 다음에 켤 때 다시 해 보도록 실패로 알린다
        raise SystemExit(2)
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
