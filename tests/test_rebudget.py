"""이미 받은 대응자금 파일 정리(rebudget.py) — 가짜 PDF(글자는 reader 가 돌려줌)로 계획 · 옮기기를 본다.

담당자 2026-10-21: 대응자금 과제를 사업비 비목 번호로 다 받은 뒤 "예산비목명이랑 순서만 확인하고 다운받은 파일명만 수정".
문서번호 · 금액은 모양만 같은 가짜.
"""
from __future__ import annotations

import json

from claim_downloader import naming, rebudget

BUDGET = [["A10110002", "장학금"], ["A10110012", "연구시설/장비비"]]
FUND = "(202409710003)_2026년도 대응자금_254,907,000"
BIZ = "(202408470003)_2026년도 사업비_4,438,000,000"


def page1(doc: str, bimok: str, amount: str) -> str:
    return (f"지출요구 및 결의서 (일반)\n문서번호 : {doc}\n적요 대응 테스트\n비목 예산액 금회청구액\n{bimok} {amount}\n"
            f"지급명세서\n1 {bimok} 가나 {amount}")


def build(tmp_path):
    """받기가 사업비 번호로 둔 모양 — 장학금은 '02. 장학금', 연구시설은 '00. 미분류'(사업비 이름표에 없어서)."""
    root = tmp_path / "지출결의서"
    fund = root / FUND
    texts = {}

    def put(rel: str, text: str | None) -> None:
        path = fund / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"%PDF-1.4 fake")
        texts[path.name] = text

    put("02. 장학금/02_(261001) 9월 근로장학금_홍길동 등 3명_(900,000).pdf",
        page1("202409710003-20261001-1", "장학금", "900,000"))
    put("00. 미분류/00_(261002) 연구장비 구입_가나상사_(1,500,000).pdf",
        page1("202409710003-20261002-2", "연구시설/장비비", "1,500,000"))
    put("01. 장학금/01_(261003) 이미 맞음_가나_(100,000).pdf",
        page1("202409710003-20261003-3", "장학금", "100,000"))
    put("02. 장학금/업로드/02_(260901) 올린 것_가나_(200,000).pdf",
        page1("202409710003-20260901-4", "장학금", "200,000"))
    put("02. 장학금/참고자료.pdf", "회의 자료 — 문서번호 없음")
    put("00. 미분류/00_(261004) 다른 과제_가나_(10,000).pdf",
        page1("202408470003-20261004-5", "장학금", "10,000"))
    put("00. 미분류/00_(261005) 알 수 없음_가나_(20,000).pdf",
        "문서번호 : 202409710003-20261005-6\n장학금 안내\n연구시설/장비비 안내")
    put("02. 장학금/(261006) 날짜 이름_가나_(30,000).pdf",          # 설정에서 번호를 끈 이름 — 이름은 그대로, 폴더만
        page1("202409710003-20261006-7", "장학금", "30,000"))
    (root / BIZ / "02. 장학금").mkdir(parents=True)
    (root / BIZ / "02. 장학금" / "02_(261001) 사업비 장학금_가나_(5,000).pdf").write_bytes(b"%PDF")
    return root, fund, (lambda path: texts.get(path.name) or "")


def budgets(no):
    return (BUDGET, "") if no == "202409710003" else ([], "예산 탭에 예산내역(비목코드 · 비목명)이 보이지 않음")


def test_plan_renames_only_fund_files_it_is_sure_of(tmp_path):
    root, fund, reader = build(tmp_path)
    plan = rebudget.plan(root, budgets, reader=reader)
    by = {m.source.name: m for m in plan.moves}
    assert set(plan.budgets) == {"202409710003"} and not plan.blocked
    assert all(m.project == "202409710003" for m in plan.moves)                         # 사업비 과제 폴더는 보지 않는다
    m = by["02_(261001) 9월 근로장학금_홍길동 등 3명_(900,000).pdf"]
    assert m.status == rebudget.CHANGE and m.target == fund / "01. 장학금" / "01_(261001) 9월 근로장학금_홍길동 등 3명_(900,000).pdf"
    m = by["00_(261002) 연구장비 구입_가나상사_(1,500,000).pdf"]
    assert m.status == rebudget.CHANGE and m.target == fund / "02. 연구시설장비비" / "02_(261002) 연구장비 구입_가나상사_(1,500,000).pdf"
    assert by["01_(261003) 이미 맞음_가나_(100,000).pdf"].status == rebudget.SAME
    up = by["02_(260901) 올린 것_가나_(200,000).pdf"]
    assert up.status == rebudget.UPLOADED and up.target.parent.name == "01. 장학금"
    assert by["참고자료.pdf"].status == rebudget.OTHER
    assert by["00_(261004) 다른 과제_가나_(10,000).pdf"].status == rebudget.OTHER
    assert by["00_(261005) 알 수 없음_가나_(20,000).pdf"].status == rebudget.UNSURE      # 두 비목이 다 나오면 추측하지 않는다
    dated = by["(261006) 날짜 이름_가나_(30,000).pdf"]
    assert dated.status == rebudget.CHANGE and dated.target == fund / "01. 장학금" / "(261006) 날짜 이름_가나_(30,000).pdf"
    assert all(path.exists() for path in (m.source for m in plan.moves))                # 계획은 파일을 건드리지 않는다


def test_apply_moves_without_overwriting_and_keeps_upload_folder(tmp_path):
    root, fund, reader = build(tmp_path)
    plan = rebudget.plan(root, budgets, reader=reader)
    changes = plan.changes()
    assert len(changes) == 3
    # 표를 보는 사이 같은 이름의 파일이 생겼다 — 덮어쓰지 않고 못 옮김으로
    blocked = next(m for m in changes if m.source.name.startswith("(261006)"))
    blocked.target.parent.mkdir(parents=True, exist_ok=True)
    blocked.target.write_bytes(b"other")
    cache = tmp_path / "cache.json"
    first = next(m for m in changes if "근로장학금" in m.source.name)
    cache.write_text(json.dumps({str(first.source): "202409710003-20261001-1"}), encoding="utf-8")
    rebudget.apply(changes, cache)
    assert sum(m.done for m in changes) == 2 and not blocked.done and "덮어쓰지" in blocked.why
    assert blocked.source.exists() and blocked.target.read_bytes() == b"other"
    assert (fund / "02. 연구시설장비비" / "02_(261002) 연구장비 구입_가나상사_(1,500,000).pdf").exists()
    assert not first.source.exists() and first.target.exists()
    assert json.loads(cache.read_text(encoding="utf-8")) == {str(first.target): "202409710003-20261001-1"}
    assert (fund / "02. 장학금" / "업로드" / "02_(260901) 올린 것_가나_(200,000).pdf").exists()      # 업로드 폴더는 그대로
    assert rebudget.emptied(changes) == []                    # 옛 폴더에 아직 다른 파일(못 정함 · 다른 과제 · 업로드)이 있다


def test_same_target_twice_gets_a_second_name(tmp_path):
    root = tmp_path / "지출결의서"
    fund = root / FUND
    texts = {}
    for folder in ("02. 장학금", "00. 미분류"):
        path = fund / folder / f"{folder[:2]}_(261001) 같은 적요_가나_(1,000).pdf"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"%PDF")
        texts[str(path)] = page1(f"202409710003-20261001-{folder[:2]}", "장학금", "1,000")
    plan = rebudget.plan(root, budgets, reader=lambda p: texts[str(p)])
    targets = sorted(m.target.name for m in plan.changes())
    assert targets == ["01_(261001) 같은 적요_가나_(1,000).pdf", "01_(261001) 같은 적요_가나_(1,000)_2.pdf"]
    rebudget.apply(plan.changes())
    assert sorted(p.name for p in (fund / "01. 장학금").iterdir()) == targets
    assert rebudget.emptied(plan.changes()) == [fund / "00. 미분류", fund / "02. 장학금"]      # 빈 옛 폴더는 알리기만(지우지 않음)
    assert (fund / "00. 미분류").is_dir()


def test_unreadable_budget_leaves_the_project_alone(tmp_path):
    root, _fund, reader = build(tmp_path)
    plan = rebudget.plan(root, lambda no: ([], "ERP 에 로그인돼 있지 않습니다"), reader=reader)
    assert plan.moves == [] and plan.blocked == [("202409710003", "ERP 에 로그인돼 있지 않습니다")]


def test_fund_folders_by_folder_or_erp_name(tmp_path):
    root = tmp_path / "r"
    for name in (FUND, BIZ, "(202409710002)_2025년도 사업비"):
        (root / name).mkdir(parents=True)
    assert [f.no for f in rebudget.fund_folders(root)] == ["202409710003"]
    names = {"202409710002": "첨단분야 혁신융합대학사업[대응자금-교내] / 2연차"}
    assert [f.no for f in rebudget.fund_folders(root, names)] == ["202409710002", "202409710003"]
    assert naming.budget_folder(root, "01", BUDGET) == root / "01. 장학금"
