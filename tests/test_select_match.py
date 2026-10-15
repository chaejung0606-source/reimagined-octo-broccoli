"""ERP 고르기 칸(select)에 보기 글자로 값을 넣는 JS(`form.SET_SELECT_JS`)를 실제 브라우저에서 시험한다.

CI 에는 브라우저가 없어 건너뛴다(개발 PC · 컨테이너에서만 돈다). 보기 목록은 실측한 은행 칸(14절 ②) 앞 12개에
뒤쪽 보기(실측 목록이 12개에서 잘렸다)를 가정해 덧붙였다.
"""

import os

import pytest

from claim_downloader.claims import form

sync_api = pytest.importorskip("playwright.sync_api")

REAL = ["해당없음", "신한은행", "산업은행", "기업은행", "국민은행", "외환은행", "수협중앙회", "수출입은행", "농협은행",
        "우리은행", "스탠다드차타드은행", "한국씨티은행", "하나은행", "카카오뱅크", "토스뱅크", "새마을금고"]


@pytest.fixture(scope="module")
def page():
    executable = os.environ.get("CHROMIUM_PATH", "/opt/pw-browsers/chromium")
    try:
        with sync_api.sync_playwright() as p:
            browser = p.chromium.launch(executable_path=executable if os.path.exists(executable) else None)
            yield browser.new_page()
            browser.close()
    except Exception as error:  # noqa: BLE001 — 브라우저가 없는 곳(CI)
        pytest.skip(f"브라우저 없음: {str(error).splitlines()[0][:80]}")


def pick(page, options, wanted):
    page.set_content("<select id='S'>" + "".join(f"<option value='{i}'>{o}</option>" for i, o in enumerate(options)) + "</select>")
    return page.evaluate(form.SET_SELECT_JS, ["S", wanted])


@pytest.mark.parametrize("wanted, expected", [
    ("국민", "국민은행"), ("KB국민은행", "국민은행"), ("신한", "신한은행"), ("토스", "토스뱅크"), ("카카오", "카카오뱅크"),
    ("하나", "하나은행"), ("KEB하나은행", "하나은행"), ("SC제일", "스탠다드차타드은행"), ("IBK기업은행", "기업은행"),
    ("새마을", "새마을금고"), ("농협", "농협은행"), ("NH농협", "농협은행"),
])
def test_short_bank_names(page, wanted, expected):
    result = pick(page, REAL, wanted)
    assert result["ok"] and result["now"] == expected, result


def test_nonghyup_and_suhyup_are_not_guessed_when_both_kinds_exist(page):
    # 명단의 '농협' · '수협' 은 은행인지 지역 조합인지 모른다 — 둘 다 있으면 첫 보기를 고르지 않고 사람에게
    both = REAL + ["지역농축협", "수협은행"]
    for wanted in ("농협", "NH농협", "수협"):
        result = pick(page, both, wanted)
        assert not result["ok"] and "보기가 여럿" in result["why"], (wanted, result)
    assert pick(page, both, "NH농협은행")["now"] == "농협은행"
    assert pick(page, both, "수협은행")["now"] == "수협은행"
    assert not pick(page, REAL, "없는은행")["ok"]


def test_other_selects_still_match(page):
    assert pick(page, ["기타소득", "근로소득", "비거주자사업/기타소득", "장학금"], "기타소득")["now"] == "기타소득"
    assert pick(page, ["세금계산서", "계산서", "기타"], "계산서")["now"] == "계산서"
    assert pick(page, ["선택", "장학금", "교육·연구프로그램개발·운영비"], "교육연구프로그램개발운영비")["now"] == "교육·연구프로그램개발·운영비"
    assert pick(page, ["공급자(거래처)사업자등록번호", "(공급받는자)사업자번호"], "공급자")["now"].startswith("공급자")
    # 여럿이 같은 정도로 맞으면 고르지 않는다(전에는 첫 보기)
    result = pick(page, ["현금/지로", "현금영수증"], "현금")
    assert not result["ok"] and "보기가 여럿" in result["why"]
