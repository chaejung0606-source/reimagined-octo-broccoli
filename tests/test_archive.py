"""보관 폴더 스캔.

스캔이 조용히 실패하면 이미 받은 것까지 전부 다시 받는다. 실패는 반드시
드러나야 한다.
"""
from __future__ import annotations

from claim_downloader import archive


def _pdf(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4")
    return path


def test_missing_folder_is_reported(tmp_path):
    report = archive.scan_archive(str(tmp_path / "없음"), tmp_path / "c.json", set(),
                                  reader=lambda p: "")
    assert not report.ok
    assert "⚠⚠" in report.warning


def test_unset_folder_is_reported(tmp_path):
    report = archive.scan_archive("", tmp_path / "c.json", set(), reader=lambda p: "")
    assert not report.ok


def test_reads_upload_folder_too_and_caches(tmp_path):
    root = tmp_path / "root"
    _pdf(root / "02. 장학금" / "a.pdf")
    _pdf(root / "02. 장학금" / "업로드" / "9월" / "b.pdf")
    _pdf(root / "09. 그 밖의사업운영경비" / "깨짐.pdf")
    numbers = {"a.pdf": "산학-20261001-0001", "b.pdf": "산학-20260901-0002"}

    def reader(path):
        if path.name == "깨짐.pdf":
            raise ValueError("깨진 PDF")
        return numbers[path.name]

    done: set[str] = set()
    cache = tmp_path / "cache.json"
    report = archive.scan_archive(str(root), cache, done, reader=reader)
    assert report.ok
    assert report.total_pdfs == 3 and report.scanned == 3 and report.added == 2
    assert done == set(numbers.values())

    def must_not_read(path):
        raise AssertionError("캐시가 있으면 다시 읽지 않는다")

    again: set[str] = set()
    report = archive.scan_archive(str(root), cache, again, reader=must_not_read)
    assert report.scanned == 0 and again == done


def test_doc_no_pattern():
    text = "지출요구 및 결의서 문서번호 : 산학협력단-20261008-0012 작성일"
    assert archive.DOC_NO_PATTERN.search(text).group(1) == "산학협력단-20261008-0012"


def test_done_roundtrip(tmp_path):
    path = tmp_path / "done.json"
    archive.save_done(path, {"B", "A"})
    assert archive.load_done(path) == {"A", "B"}
    path.write_text("깨짐", encoding="utf-8")
    assert archive.load_done(path) == set()


def test_folder_status(tmp_path):
    _pdf(tmp_path / "01. 인건비" / "a.pdf")
    _pdf(tmp_path / "01. 인건비" / "b.pdf")
    _pdf(tmp_path / "01. 인건비" / "업로드" / "c.pdf")
    (tmp_path / "청구서다운내역").mkdir()
    status = archive.folder_status(str(tmp_path))
    assert [(f.name, f.waiting, f.uploaded) for f in status] == [("01. 인건비", 2, 1)]
