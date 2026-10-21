"""주차등록(parking.py) — 로그인 정보는 이 PC 사용자 폴더에만, 자동 로그인은 한 번만. 브라우저 없이 가짜 창으로 본다."""
from __future__ import annotations

import json

import pytest

from claim_downloader import parking, settings


@pytest.fixture(autouse=True)
def _clean(isolated_home):
    parking.forget_failure()
    yield
    parking.forget_failure()


def test_login_is_kept_outside_config_and_never_in_plain_on_windows(monkeypatch):
    parking.save_login("데이터보안활용사업단", "s3cret!")
    assert parking.load_login() == ("데이터보안활용사업단", "s3cret!")
    assert parking.saved_user() == "데이터보안활용사업단"
    assert "s3cret" not in settings.config_path().read_text(encoding="utf-8") if settings.config_path().exists() else True
    raw = parking.login_path().read_text(encoding="utf-8")
    assert "s3cret!" not in raw                                  # 윈도우 밖(시험)에서도 글자 그대로는 아니다(base64)
    # 윈도우에서는 DPAPI 로 감싼다 — 감싸는 함수를 바꿔 끼워 본다
    calls = []

    def fake_dpapi(data, protect):
        calls.append(protect)
        return bytes(reversed(data))

    monkeypatch.setattr(parking, "IS_WINDOWS", True)
    monkeypatch.setattr(parking, "_dpapi", fake_dpapi)
    parking.save_login("id", "pw-1234")
    assert json.loads(parking.login_path().read_text(encoding="utf-8"))["how"] == "dpapi"
    assert parking.load_login() == ("id", "pw-1234") and calls == [True, False]
    parking.forget_login()
    assert parking.load_login() is None and parking.saved_user() == ""


def test_unreadable_login_file_is_treated_as_none():
    parking.login_path().write_text("{깨진", encoding="utf-8")
    assert parking.load_login() is None
    parking.login_path().write_text(json.dumps({"user": "id", "how": "dpapi", "secret": "!!"}), encoding="utf-8")
    assert parking.load_login() is None                          # 다른 윈도우 계정에서 만든 파일 등 — 못 풀면 직접 로그인


class FakeDialog:
    def __init__(self, message):
        self.message = message
        self.accepted = False

    def accept(self):
        self.accepted = True


class FakeSite:
    """로그인 화면 하나. enter_works=False 면 Enter 로는 안 넘어가고 '로그인' 단추로만. right 가 아니면 알림 창."""

    def __init__(self, right=("id", "pw"), enter_works=True, has_form=True, submit_found=True):
        self.right, self.enter_works, self.submit_found = right, enter_works, submit_found
        self.logged_in = not has_form
        self.values = {}
        self.clicks = 0
        self.handlers = []
        self.frames = [self]

    # page
    def on(self, name, handler):
        self.handlers.append(handler)

    def remove_listener(self, name, handler):
        self.handlers.remove(handler)

    def _submit(self):
        if (self.values.get(parking.ID_SELECTOR), self.values.get(parking.PW_SELECTOR)) == self.right:
            self.logged_in = True
        else:
            for handler in list(self.handlers):
                handler(FakeDialog("아이디 또는 비밀번호가 틀립니다."))

    # frame
    def evaluate(self, js, arg=None):
        if js is parking.LOGIN_FORM_JS:
            return 0 if self.logged_in else 1
        if js is parking.MARK_LOGIN_JS:
            return {"ok": True, "id": "userId", "pw": "userPw"}
        if js is parking.SUBMIT_JS:
            if not self.submit_found:
                return {"ok": False, "why": "'로그인' 단추가 없음"}
            self.clicks += 1
            self._submit()
            return {"ok": True}
        raise AssertionError(js[:40])

    def fill(self, selector, value):
        self.values[selector] = value

    def press(self, selector, key):
        assert selector == parking.PW_SELECTOR and key == "Enter"
        if self.enter_works:
            self._submit()


def _login(site, user="id", secret="pw"):
    logs = []
    report = parking.login(site, user, secret, logs.append, wait=lambda s: None)
    assert all(secret not in line for line in logs), logs          # 비밀번호는 기록에 남지 않는다
    return report, logs


def test_login_with_enter():
    site = FakeSite()
    report, _ = _login(site)
    assert report.logged_in and site.clicks == 0
    assert site.values == {parking.ID_SELECTOR: "id", parking.PW_SELECTOR: "pw"}


def test_login_button_is_pressed_once_when_enter_does_nothing():
    site = FakeSite(enter_works=False)
    report, logs = _login(site)
    assert report.logged_in and site.clicks == 1
    assert any("'로그인' 단추" in line for line in logs)


def test_wrong_login_is_not_retried():
    """틀린 비밀번호 — 사이트 알림을 받고 멈춘다. '로그인' 단추를 더 누르지 않고, 이번 실행에서는 다시 시도하지 않는다(계정 잠김 방지)."""
    site = FakeSite(right=("id", "other"))
    report, _ = _login(site)
    assert not report.logged_in and report.tried_login and site.clicks == 0
    assert "틀립니다" in report.note and parking.failed_before()
    assert "다시 시도하지 않습니다" in report.note
    # 로그인 정보를 고쳐 저장하면 다시 해 본다
    parking.save_login("id", "other")
    assert not parking.failed_before()


def test_no_login_form_means_already_logged_in_or_other_screen():
    site = FakeSite(has_form=False)
    report, _ = _login(site)
    assert not report.tried_login and not report.logged_in and "로그인 칸이 보이지 않습니다" in report.note


def test_site_is_told_apart_by_host():
    assert parking.is_site("https://traffic.kangwon.ac.kr/main?x=1")
    assert not parking.is_site("https://knu-icf.kangwon.ac.kr/rderp_layoutMain.act")
    assert parking.is_site("http://127.0.0.1:8000/login.html", "http://127.0.0.1:8000/login.html")
