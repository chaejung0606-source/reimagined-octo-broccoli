"""ERP 자동 로그아웃 — 담당자 요청 2026-10-21: "erp 브라우저 켜놓고 30분이상 활동이 없거나 로그아웃 없이 창을 닫으면 자동 로그아웃".

누르는 것은 ERP 틀(rderp_layoutMain.act, 창 0 프레임 0) 위쪽의 '로그아웃' 하나다 — 실측(2026-10-19 [화면 구조 저장] 1 · 2 · 4 · 5 · 6번,
2026-10-20): `<a id="layoutMain_btn_logout" class="logout" href="javascript:">로그아웃</a>`. id 와 글자가 둘 다 맞고 화면에 보일 때만 누른다.
누른 뒤 뜨는 ERP 확인 창(무엇이 뜨는지 미실측)은 이때만 앱이 [확인] 한다(session.logout 의 처리기).

활동은 ERP 창(팝업 포함)에서의 마우스 · 키보드 · 휠 — ACTIVITY_JS 가 브라우저 쪽에서 알리고(15초에 한 번까지), 앱이 브라우저로 하는
일(명령)도 활동으로 본다(ui/worker.py). 로그인됐는지도 같은 알림으로 안다 — ERP 틀에 [로그아웃] 이 있으면 로그인된 것.
창을 닫은 뒤에는 화면이 없으므로 같은 브라우저 묶음(쿠키가 메모리에 남아 있다)에 ERP 를 다시 열어 [로그아웃] 을 누른다.
이 모듈은 Playwright 를 부르지 않는다(브라우저를 띄우는 곳은 session.py 하나 — test_safety).
"""
from __future__ import annotations

import json

LOGOUT_ID = "layoutMain_btn_logout"
LOGOUT_TEXT = "로그아웃"
BINDING = "__cossErp"                 # 브라우저 쪽이 부르는 앱 함수 이름(context.expose_binding)
DEFAULT_MINUTES = 30
REPORT_EVERY_MS = 15000               # 활동 알림 간격 — 마우스를 움직일 때마다 알리지 않게

# 로그인됐는지 — 맨 위 문서(ERP 틀)에 [로그아웃] 이 있으면 'in', 다 읽힌 문서에 없으면 'out'(로그인 화면 · 로그아웃 뒤 화면), 읽는 중이면 '?'.
# 로그인 화면의 모양은 보지 않는다(미실측 — 칸 이름에 기대지 않는다). 팝업(window.opener 가 있는 창)은 '?' — 팝업에는 [로그아웃] 이 없어
# 'out' 으로 읽히면 ERP 창을 닫았을 때 로그인 상태를 잃는다. 앱도 팝업의 알림으로는 로그인 상태를 바꾸지 않는다(session.erp_logged_in)
_STATE = ("var d; try { if (window.top.opener) return '?'; d = window.top.document; } catch (e) { return '?'; }"
          "if (d.getElementById('" + LOGOUT_ID + "')) return 'in';"
          "return d.readyState === 'complete' ? 'out' : '?';")

STATE_JS = "() => { " + _STATE + " }"


def activity_script(host: str) -> str:
    """모든 창 · 프레임에 미리 넣는 스크립트(context.add_init_script). ERP 주소의 문서에서만 — 주차등록 사이트 등은 건드리지 않는다.
    누르거나 값을 넣지 않는다. 알리기만 한다."""
    return """(() => {
  if (window.__cossWatch) return;
  window.__cossWatch = 1;
  if (String(location.host).toLowerCase() !== %s) return;
  const state = () => { %s };
  const say = (kind) => { try { if (window.%s) window.%s(kind + ':' + state()); } catch (e) {} };
  let last = 0;
  const touch = () => { const now = Date.now(); if (now - last >= %d) { last = now; say('active'); } };
  for (const type of ['mousedown', 'keydown', 'wheel', 'touchstart']) addEventListener(type, touch, {capture: true, passive: true});
  addEventListener('load', () => { say('load'); setTimeout(() => say('load'), 3000); });
})();""" % (json.dumps(host.lower()), _STATE, BINDING, BINDING, REPORT_EVERY_MS)


def parse_signal(value) -> tuple[str, str]:
    """'active:in' → ('active', 'in'). 모르는 값은 ('', '?')."""
    kind, _, state = str(value or "").partition(":")
    kind = kind if kind in ("active", "load") else ""
    return kind, state if state in ("in", "out") else "?"


# 누르는 곳은 여기 하나. 누르기는 setTimeout 으로 미뤄 evaluate 가 먼저 돌아오게 한다 — 확인 창이 뜨는 동안 evaluate 가 묶이지 않게
CLICK_LOGOUT_JS = """() => {
  const a = document.getElementById('%s');
  if (!a) return 'none';
  if ((a.textContent || '').trim() !== '%s') return 'text';
  const r = a.getBoundingClientRect();
  if (!(r.width > 0 && r.height > 0)) return 'hidden';
  setTimeout(() => a.click(), 0);
  return 'clicked';
}""" % (LOGOUT_ID, LOGOUT_TEXT)


REASONS = {
    "idle": "%d분 동안 ERP 를 쓰지 않아",
    "closed": "ERP 창을 로그아웃 없이 닫아",
    "app": "앱을 닫으면서",
    "reopen": "브라우저를 다시 열기 전에",
}


def reason_text(reason: str, minutes: int = DEFAULT_MINUTES) -> str:
    text = REASONS.get(reason, "")
    return text % minutes if "%d" in text else text
