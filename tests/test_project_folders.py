"""과제 폴더(project_folders.py) — 담당자가 2026-10-21 에 저장 폴더를 '(과제번호)_…' 폴더로 나눴다. 폴더 이름은 실제 모양(과제번호 ·
연도 · 사업비)을 따랐고 금액은 공개된 사업비다. PDF 는 가짜로 만든다."""
from __future__ import annotations

from pathlib import Path

from claim_downloader import archive, project_folders as pf

NAMES = ["(202408470001)_2024년도 사업비_4,179,251,000", "(202408470002)_2025년도 사업비(출연금)_4,462,000,000",
         "(202408470003)_2026년도 사업비_4,438,000,000", "(202502320001)_2024년 이월금_349,418,840"]


def make(tmp_path: Path, *extra: str) -> Path:
    root = tmp_path / "지출결의서"
    for name in NAMES + list(extra):
        (root / name).mkdir(parents=True)
    (root / "보조금 집행내역.xlsx").write_text("x")
    return root


def test_folders_are_read_from_names(tmp_path):
    root = make(tmp_path, "e나라도움 부정징후 현장점검 자료(24년도)", "청구서자동화")
    found = pf.folders(root)
    assert [f.no for f in found] == ["202408470001", "202408470002", "202408470003", "202502320001"]
    assert found[1].short() == "202408470002 2025년도 사업비(출연금)"           # 끝의 금액은 뺀다
    assert found[3].title == "2024년 이월금_349,418,840"
    assert pf.project_of("( 202603130001 ) 2025년 이월금") == "202603130001" and pf.project_of("청구서자동화") == ""


def test_save_root_goes_into_the_project_folder_only(tmp_path):
    root = make(tmp_path)
    where, why = pf.save_root(root, "202408470003")
    assert where == root / NAMES[2] and not why
    where, why = pf.save_root(root, "202409710003")                          # 폴더 없는 과제 — 받지 않는다
    assert where is None and "(202409710003)_" in why
    where, why = pf.save_root(root, "")
    assert where is None and "과제를 고르세요" in why
    (root / "(202408470003)_사본").mkdir()
    where, why = pf.save_root(root, "202408470003")
    assert where is None and "2개" in why
    # 저장 폴더를 과제 폴더 하나로 잡은 경우 — 그 과제만
    assert pf.save_root(root / NAMES[0], "202408470001") == (root / NAMES[0], "")
    assert pf.save_root(root / NAMES[0], "202408470003")[0] is None


def test_old_layout_without_project_folders_is_used_as_before(tmp_path):
    old = tmp_path / "2026년도(e나라도움)"
    (old / "09. 그 밖의사업운영경비").mkdir(parents=True)
    assert pf.save_root(old, "202408470003") == (old, "")
    assert pf.save_root(old, "") == (old, "")


def test_missing_old_folder_follows_to_the_parent_with_project_folders(tmp_path):
    root = make(tmp_path)
    assert pf.migrate(str(root / "2026년도(e나라도움)")) == str(root)
    assert pf.migrate(str(root)) == ""                                         # 있는 폴더는 그대로
    assert pf.migrate(str(tmp_path / "없는곳" / "2026년도")) == ""
    assert pf.migrate("") == ""


def test_counts_and_scan_cover_only_project_folders(tmp_path, isolated_home):
    root = make(tmp_path, "e나라도움 부정징후 현장점검 자료(24년도)")
    for name, sub in ((NAMES[2], "09. 그 밖의사업운영경비"), (NAMES[0], "09. 그 밖의사업운영경비/업로드"),
                      ("e나라도움 부정징후 현장점검 자료(24년도)", "")):
        folder = root / name / sub
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{name[:14]}.pdf").write_bytes(b"%PDF-1.4")
    counts = archive.folder_status(str(root))
    assert [(c.name, c.waiting, c.uploaded) for c in counts] == [("09. 그 밖의사업운영경비", 1, 1)]
    done: set[str] = set()
    read = []
    report = archive.scan_archive(str(root), isolated_home / "cache.json", done,
                                  reader=lambda p: read.append(p.name) or "202408470003-20261001-1")
    assert report.ok and report.total_pdfs == 2 and not any("현장" in name for name in read)     # 점검 자료 폴더는 보관본이 아니다


def test_chosen_projects_keep_folder_order_and_drop_missing():
    """여러 과제 고르기(담당자 요청 2026-10-21) — 설정에 남긴 번호 중 지금 폴더가 있는 것만, 폴더 차례대로."""
    found = ["202408470001", "202408470002", "202408470003", "202502320001"]
    assert pf.pick(found, "202502320001,202408470001") == ["202408470001", "202502320001"]
    assert pf.pick(found, "202409710003, 202408470003") == ["202408470003"]              # 폴더 없는 과제는 빠진다
    assert pf.pick(found, "") == [] and pf.pick([], "202408470001") == []


def test_counts_include_matching_fund_folders(tmp_path):
    """대응자금 과제의 비목 폴더는 예산 탭 차례의 'NN. 비목명'(담당자 2026-10-21) — 사업비 이름표에 없어도 대기 · 완료 수에 넣는다."""
    root = make(tmp_path)
    fund = root / "(202409710003)_2026년도 대응자금_254,907,000"
    for sub in ("01. 장학금", "02. 연구시설장비비/업로드"):
        (fund / sub).mkdir(parents=True)
        (fund / sub / "a.pdf").write_bytes(b"%PDF-1.4")
    (fund / "참고자료").mkdir()
    counts = {c.name: (c.waiting, c.uploaded) for c in archive.folder_status(str(root))}
    assert counts == {"01. 장학금": (1, 0), "02. 연구시설장비비": (0, 1)}
