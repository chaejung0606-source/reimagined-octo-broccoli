"""명령줄 실행 — 데스크톱 앱과 같은 흐름을 콘솔에서.

    python -m claim_downloader              전체 (받기 전에 y/N 확인)
    python -m claim_downloader --limit 1    앞 1건만 시험
    python -m claim_downloader --structure  진단 모드: 원하는 ERP 화면을 띄운 뒤 구조를 _화면구조.txt 로 (읽기만)

앱이 뜨지 않는 PC 에서 쓰거나, 문제를 재현할 때 쓴다.
"""
from __future__ import annotations

import argparse
import time

from . import settings
from .session import BrowserClosed, ErpSession, ListNotFound, file_logger
from .targets import volume_warning


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="claim-downloader", description="ERP 청구서 PDF 자동 다운로드")
    parser.add_argument("--limit", type=int, default=0, help="앞 N건만 받기 (흐름 시험용). 0 이면 전체")
    parser.add_argument("--structure", action="store_true",
                        help="진단 모드: 브라우저를 열어 두고 원하는 화면을 띄운 뒤 구조를 파일로 저장 (읽기만)")
    args = parser.parse_args(argv)

    log = file_logger(print)
    log("════ %s 명령줄 실행 ════" % time.strftime("%Y-%m-%d"))
    if args.structure:
        return _capture_structure(log)
    cfg = settings.load()
    if not cfg.out_root:
        log("저장 폴더가 지정되지 않았습니다. 앱의 [설정] 에서 지정하거나 %s 에 out_root 를 적으세요."
            % settings.config_path())
        return 1

    def ask_relogin(message: str) -> bool:
        print("\n  [멈춤 감지] " + message)
        input("  준비되면 Enter… ")
        return True

    session = ErpSession(log, ask_relogin)
    report = session.prepare()
    if not report.ok:
        if input("\n  보관 폴더를 읽지 못했습니다. 그래도 계속할까요? (y/N): ").strip().lower() != "y":
            return 1
    try:
        session.open_browser()
        print("\n" + "=" * 60)
        print(" 1) 브라우저에서 ERP에 로그인하세요.")
        print(" 2) [과제관리 → 과제정보 → 청구서] 에서 '결의서내역' 목록을 띄우세요.")
        print(" 3) 목록이 보이면 이 창으로 돌아와 Enter 를 누르세요.")
        print("=" * 60)
        input(" 준비되면 Enter… ")
        try:
            sel = session.read_list()
        except (ListNotFound, BrowserClosed) as error:
            log(str(error))
            log("※ 앱이 새로 연 '이 브라우저 창'에서 로그인·목록을 띄웠는지 확인하세요.")
            input("Enter로 종료…")
            return 1

        targets = sel.targets
        if not targets:
            log("새로 받을 건이 없습니다.")
            input("Enter로 종료…")
            return 0
        if args.limit > 0:
            targets = targets[:args.limit]
            log("※ 시험: 앞 %d건만 받습니다." % len(targets))
        else:
            for r in targets[:10]:
                log("   · No %s  %s  (%s)" % (r.get("no"), (r.get("cont") or "")[:42], r.get("amt")))
            if len(targets) > 10:
                log("   · … 외 %d건" % (len(targets) - 10))
            warning = volume_warning(sel)
            if warning:
                log(warning)
            ans = input("\n  위 %d건을 전부 받을까요? (y 입력 후 Enter = 진행 / 그냥 Enter = 취소): "
                        % len(targets)).strip().lower()
            if ans != "y":
                log("취소됨.")
                return 0

        session.download(targets)
        print("\n완료. 로그: %s" % settings.log_path())
        input("Enter로 브라우저를 닫습니다… ")
        return 0
    finally:
        session.close()


def _capture_structure(log) -> int:
    """진단 모드 — 받기 흐름과 무관하게 화면 구조만 남긴다. 저장 폴더 설정이 없어도 된다."""
    session = ErpSession(log, lambda _m: True)
    try:
        session.open_browser()
        print("\n" + "=" * 60)
        print(" 브라우저에서 로그인한 뒤, 구조를 남기고 싶은 화면(예: 일반청구 작성)을 띄우세요.")
        print(" 값은 넣지 않은 빈 화면이 좋습니다. 화면이 보이면 이 창으로 돌아와 Enter 를 누르세요.")
        print("=" * 60)
        input(" 준비되면 Enter… ")
        try:
            path = session.capture_structure()
        except BrowserClosed as error:
            log(str(error))
            return 1
        print("\n저장했습니다: %s" % path)
        input("Enter로 브라우저를 닫습니다… ")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
