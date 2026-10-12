"""회의록 파일 이름 — 정산 시스템에 올릴 수 있는 글자만.

이 앱의 naming.py(청구서)와 규칙이 **다르다.** 청구서는 금지문자를 공백으로 바꾸는 블랙리스트,
회의록은 한글·영문·숫자·공백·하이픈·밑줄만 남기는 화이트리스트다. 올라가는 시스템이 다르므로
합치지 않는다. 중복은 '(2)' 가 아니라 '-2' — 괄호는 정산 시스템이 거부할 수 있다.

업로드 폴더 보호(ensure_not_upload)만 청구서 쪽과 같은 원칙을 따른다 — 회의 자료 폴더가 비목 폴더
아래 있을 수 있다.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from ..naming import UPLOAD_DIR


def ensure_not_upload(path) -> None:
    """`업로드/` 아래에는 절대 쓰지 않는다 — 올리지 않은 것이 올린 것처럼 보이게 된다."""
    if UPLOAD_DIR in Path(path).parts:
        raise RuntimeError(f"'{UPLOAD_DIR}' 폴더 안에는 회의록을 만들지 않습니다: {path}")


def _sanitize(name):
    """정산 시스템에 올릴 수 있도록 안전한 글자만 남긴다.

    한글·영문·숫자·공백·하이픈·밑줄만 두고 나머지(대괄호, 괄호, 그리고
    \\ / : * ? " < > | 같은 문자)는 공백으로 바꾼 뒤 공백을 정리한다."""
    name = re.sub(r"[^0-9A-Za-z가-힣ㄱ-ㅎㅏ-ㅣ \-_]", " ", str(name))
    name = re.sub(r"\s+", " ", name).strip()
    name = name.strip("-_. ")         # 윈도우는 이름 끝의 점/공백을 허용하지 않는다
    return name[:120] or "회의록"


def _unique(path):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    i = 2
    # 괄호는 정산 시스템 업로드에서 거부될 수 있어 '-2' 형태로 붙인다.
    while os.path.exists("%s-%d%s" % (base, i, ext)):
        i += 1
    return "%s-%d%s" % (base, i, ext)
