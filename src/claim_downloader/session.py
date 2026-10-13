"""한 번의 받기 작업 흐름.

    준비(보관 스캔) → 브라우저 열기 → [사람: 로그인·목록 띄우기] → 목록 읽기
    → [사람: 대상 확인] → 받기 → (엑셀 지정 시) 누락 검토

사람이 끼어드는 자리는 호출부가 정한다. 명령줄은 input() 으로, 데스크톱 앱은
버튼으로 기다린다. 이 모듈은 화면을 모른다.

Playwright 동기 API 는 시작한 스레드에서만 써야 한다. 그래서 이 객체의 메서드는
전부 같은 스레드에서 불러야 한다.
"""
from __future__ import annotations

import time
from pathlib import Path
from collections.abc import Callable
from dataclasses import dataclass, field

from .claims import form as claim_form
from . import archive, diagnose, erp, settings as settings_mod
from .reconcile import reconcile
from .targets import Selection, select_targets

# 건당 멈춤 재시도 횟수. 2026-10-12 11건 실행에서는 한 번도 필요 없었지만
# 매크로 시절에는 큰 보고서 뒤에 상세화면이 자주 멈췄다.
MAX_RETRY = 2


class ListNotFound(RuntimeError):
    """결의서내역 목록을 못 찾음. dump 에 열린 창·프레임 구조가 들어 있다."""

    def __init__(self, dump: str):
        super().__init__("결의서내역 목록(그리드)을 찾지 못했습니다.")
        self.dump = dump


class BrowserClosed(RuntimeError):
    pass


@dataclass
class RunSummary:
    ok: int = 0
    failed: list[dict] = field(default_factory=list)
    stopped: bool = False
    missing: list[dict] = field(default_factory=list)   # 엑셀 대조 누락


# on_item(번호, 상태, 설명) — 상태: 'running' | 'done' | 'retry' | 'failed'
ItemCallback = Callable[[int, str, str], None]


class ErpSession:
    def __init__(self, log: Callable[[str], None],
                 ask_relogin: Callable[[str], bool],
                 should_stop: Callable[[], bool] = lambda: False,
                 process=erp.process_one,
                 load_settings: Callable[[], settings_mod.Settings] = settings_mod.load):
        self.log = log
        self.ask_relogin = ask_relogin
        self.should_stop = should_stop
        self._process = process
        self._load_settings = load_settings
        self.done: set[str] = set()
        self.archive_report: archive.ScanReport | None = None
        self._pw = None
        self.browser = None
        self.page = None

    # ── 준비 ─────────────────────────────────────────────────────────────
    def prepare(self) -> archive.ScanReport:
        """받은 기록을 읽고 보관 폴더를 스캔해 이미 받은 문서번호를 모은다."""
        cfg = self._load_settings()
        self.done = archive.load_done(settings_mod.done_path())
        self.log("보관 폴더 스캔 중… (처음 한 번은 1~2분 걸릴 수 있어요. 다음부터는 바로 됩니다)")
        report = archive.scan_archive(
            cfg.out_root, settings_mod.archive_cache_path(), self.done,
            progress=lambda n: self.log("   … 보관 PDF %d개 읽음" % n))
        if report.ok:
            self.log("보관 폴더 스캔: PDF %d개 중 %d개 새로 읽음 · 이미 보관된 문서번호 %d건을 건너뛰기에 추가"
                     % (report.total_pdfs, report.scanned, report.added))
            archive.save_done(settings_mod.done_path(), self.done)
        else:
            self.log(report.warning)
        self.archive_report = report
        return report

    # ── 브라우저 ─────────────────────────────────────────────────────────
    @property
    def browser_open(self) -> bool:
        try:
            return self.browser is not None and self.browser.is_connected()
        except Exception:      # noqa: BLE001
            return False

    def open_browser(self) -> None:
        """ERP 첫 화면을 띄운다. 로그인은 사람이 이 창에서 직접 한다.

        아이디·비밀번호는 어디에도 저장하지 않는다.
        """
        if self.browser_open:
            return
        from playwright.sync_api import sync_playwright

        if self._pw is None:
            self._pw = sync_playwright().start()
        try:
            self.browser = self._pw.chromium.launch(headless=False)
        except Exception as error:   # noqa: BLE001
            # 학교망에서 크로미움을 못 받은 PC 가 있다. 윈도우에 늘 있는 Edge 로 대신 띄운다.
            self.log("크로미움을 띄우지 못해 Edge 로 엽니다 (%s)" % str(error).splitlines()[0][:120])
            self.browser = self._pw.chromium.launch(headless=False, channel="msedge")
        self.page = self.browser.new_page(accept_downloads=True)
        self.page.goto(settings_mod.ERP_URL, wait_until="domcontentloaded")
        self.log("브라우저를 열었습니다. 로그인 → [과제관리 → 과제정보 → 청구서] → 결의서내역 목록을 띄우세요.")

    def close(self) -> None:
        try:
            if self.browser is not None:
                self.browser.close()
        except Exception:      # noqa: BLE001
            pass
        try:
            if self._pw is not None:
                self._pw.stop()
        except Exception:      # noqa: BLE001
            pass
        self.browser = self._pw = self.page = None

    # ── 진단 ─────────────────────────────────────────────────────────────
    def capture_structure(self) -> Path:
        """지금 열린 ERP 화면의 창·프레임·입력 요소를 _화면구조.txt 로. 읽기만 한다(diagnose.py)."""
        if not self.browser_open:
            raise BrowserClosed("브라우저가 닫혀 있습니다. 브라우저를 다시 여세요.")
        windows = diagnose.capture(self.page.context, frame_kind=erp.frame_kind)
        path = settings_mod.structure_path()
        path.write_text(diagnose.format_report(windows), encoding="utf-8")
        count = sum(len(fr.get("elements", [])) for win in windows for fr in win["frames"])
        self.log("화면 구조 저장: 창 %d · 요소 %d개 → %s" % (len(windows), count, path))
        return path

    # ── 일반청구 ─────────────────────────────────────────────────────────
    def claim_form_open(self) -> bool:
        """지금 브라우저에 일반청구 작성 화면이 떠 있는지."""
        if not self.browser_open:
            return False
        _page, frame = claim_form.find_form(self.page.context)
        return frame is not None

    def fill_claim(self, data: dict, dry_run: bool = True) -> claim_form.FillReport:
        """일반청구 작성 화면에 값을 채운다(claims/form.py). 저장·신청은 사람이."""
        if not self.browser_open:
            raise BrowserClosed("브라우저가 닫혀 있습니다. 브라우저를 다시 여세요.")
        page, frame = claim_form.find_form(self.page.context)
        if frame is None:
            report = claim_form.FillReport(dry_run=dry_run)
            report.blocked = ("일반청구 작성 화면을 찾지 못했습니다. 앱이 연 브라우저에서 결의서내역 → [일반청구] 를 눌러 "
                              "새 청구서 화면을 띄운 뒤 다시 누르세요.")
            self.log(report.blocked)
            return report
        return claim_form.fill(frame, data, self.log, dry_run=dry_run,
                               wait=lambda seconds: page.wait_for_timeout(int(seconds * 1000)))

    # ── 목록 ─────────────────────────────────────────────────────────────
    def read_list(self) -> Selection:
        if not self.browser_open:
            raise BrowserClosed("브라우저가 닫혀 있습니다. 브라우저를 다시 여세요.")
        ctx = self.page.context
        self.log("결의서 목록 찾는 중…")
        page, gfr = erp.wait_for_grid(ctx)
        if not gfr:
            dump = erp.dump_context(ctx)
            self.log("결의서내역 목록(그리드)을 찾지 못했습니다. 지금 열려 있는 창/프레임 구조:")
            self.log("─" * 60)
            self.log(dump)
            self.log("─" * 60)
            raise ListNotFound(dump)
        self.page = page            # 목록이 있는 창을 작업 창으로 쓴다
        self.log("결의서 목록 발견. 수집 중…")
        rows = erp.collect_all(gfr)
        self.log("수집 %d행" % len(rows))
        sel = select_targets(rows, self.done)
        self.log("대상 %d건 (이미 보관된 %d건은 건너뜀)" % (len(sel.targets), sel.skipped))
        return sel

    # ── 받기 ─────────────────────────────────────────────────────────────
    def download(self, targets: list[dict], on_item: ItemCallback | None = None) -> RunSummary:
        cfg = self._load_settings()
        notify = on_item or (lambda *_: None)
        summary = RunSummary()
        retried: dict[str, int] = {}
        i = 0
        while i < len(targets):
            if self.should_stop():
                summary.stopped = True
                self.log("멈춤 요청 — 여기서 그만 받습니다.")
                break
            row = targets[i]
            notify(i, "running", "")
            self.log("[%d/%d] No %s (결의 %s) · %s" % (
                i + 1, len(targets), row.get("no"), row.get("seq"), (row.get("cont") or "")[:30]))
            try:
                _code, dest = self._process(self.page, row, cfg.out_root, cfg.name_date_first,
                                            cfg.wait_sec, self.log)
            except Exception as error:   # noqa: BLE001
                msg = str(error).splitlines()[0] if str(error) else type(error).__name__
                self.log("      ✖ %s" % msg)
                if not self.browser_open:
                    summary.failed.append(row)
                    notify(i, "failed", "브라우저가 닫힘")
                    summary.stopped = True
                    self.log("브라우저가 닫혀 받기를 멈춥니다.")
                    break
                key = row.get("docNo") or str(i)
                if cfg.freeze_reload and retried.get(key, 0) < MAX_RETRY and erp.is_freeze_error(msg):
                    retried[key] = retried.get(key, 0) + 1
                    self.log("      ↻ 새로고침 후 이어받기 (%d/%d)" % (retried[key], MAX_RETRY))
                    notify(i, "retry", "다시 로그인 대기")
                    try:
                        self.page.goto(settings_mod.ERP_URL, wait_until="domcontentloaded")
                    except Exception:   # noqa: BLE001
                        pass
                    if not self.ask_relogin(
                            "상세화면이 멈춰 ERP 를 새로 열었습니다. 다시 로그인하고 "
                            "'결의서내역' 목록을 띄운 뒤 계속하세요."):
                        summary.failed.append(row)
                        notify(i, "failed", msg)
                        summary.stopped = True
                        self.log("사용자가 중단했습니다.")
                        break
                    page, gfr = erp.wait_for_grid(self.page.context)
                    if gfr:
                        self.page = page
                    continue            # 같은 건 재시도
                summary.failed.append(row)
                notify(i, "failed", msg)
            else:
                self.done.add(row["docNo"])
                archive.save_done(settings_mod.done_path(), self.done)
                summary.ok += 1
                notify(i, "done", dest.name)
            i += 1

        self.log("── 끝: 성공 %d건 / 실패 %d건" % (summary.ok, len(summary.failed)))
        for r in summary.failed:
            self.log("   실패: No %s 결의 %s %s" % (r.get("no"), r.get("seq"), (r.get("cont") or "")[:30]))
        summary.missing = reconcile(cfg.excel_path, self.done, self.log)
        return summary


def file_logger(echo: Callable[[str], None] = print) -> Callable[[str], None]:
    """시각을 붙여 화면과 _실행로그.txt 에 함께 남긴다. 디버그는 항상 이 파일부터."""
    path = settings_mod.log_path()

    def log(msg: str) -> None:
        lines = str(msg).splitlines() or [""]
        stamp = time.strftime("%H:%M:%S ")
        text = "\n".join(stamp + line for line in lines)
        echo(text)
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(text + "\n")
        except OSError:
            pass

    return log
