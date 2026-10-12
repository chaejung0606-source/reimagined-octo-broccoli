"""BOM 이 있어도 안전하게 읽기.

옛 도구가 PyInstaller 로 묶여 있을 때 utf-8-sig 코덱을 뒤늦게 불러오다 실패해, AI 가 정상 저장한
meeting.json 을 '회의록 데이터 없음' 으로 버리는 버그가 있었다. 이 앱은 실행 파일로 묶지 않아 원인은
없지만 나중에 묶게 되면 되살아나므로 같은 방법을 그대로 쓴다. encoding="utf-8-sig" 를 쓰지 않는다.
"""
from __future__ import annotations


def _read_text(path):
    """BOM 이 있어도 안전하게 읽는다.

    utf-8-sig 로 여는 대신 바이트로 읽고 BOM 을 직접 떼어낸다.
    .exe 로 묶인 상태에서 임시 폴더가 사라지면 utf-8-sig 코덱을 뒤늦게
    불러오다 실패하는데, utf-8 은 시작할 때 이미 올라와 있어 안전하다."""
    with open(path, "rb") as f:
        raw = f.read()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    return raw.decode("utf-8", "replace")
