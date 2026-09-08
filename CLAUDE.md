# CLAUDE.md

지출 서류 자동 검토 데스크톱 앱. 새 세션은 이 문서를 먼저 읽고 시작한다.

## 이 앱이 하는 일

담당자가 지출종류(**근로장학금** · **혁신인재지원금** · **출장비**)를 고르고 서류
폴더를 지정하면, 기준에 따라 검토해서 **고쳐야 할 부분을 정리해 준다.**
전 과정이 사용자 컴퓨터 안에서 돌아간다. 서류를 외부로 보내지 않는다.

배경과 설계 근거는 `docs/` 에 있다. 코드를 고치기 전에 최소한
[`docs/02-review-criteria.md`](docs/02-review-criteria.md) 는 훑어야 한다.

## 브랜치

**`claude/expense-document-review-criteria-yzji9p` 가 사실상의 기본 브랜치다.**
`main` 은 없다.

이 이름이 코드에 박혀 있다 — `src/expense_review/updater.py` 의 `BRANCH` 상수.
배포된 앱은 이 브랜치에서만 업데이트를 받는다. 그래서 **다른 브랜치에 푸시하면
사용자의 앱에 아무것도 내려가지 않는다.** 세션마다 다른 개발 브랜치를 배정받더라도,
푸시는 이 브랜치로 해야 한다(사용자 확인을 받고).

`claude/expense-document-review-impl-7v6a8c` 는 초기 구현 시도가 남은 폐기 브랜치다.
그 작업은 `77f2f58` 로 다시 올라와 있다. 참조하지 않는다.

PR 은 쓰지 않는다. 지금까지 전부 이 브랜치에 직접 커밋해 왔다.

## 개발

```bash
pip install -e ".[gui,dev]"

python -m pytest -q              # 80건
python tools/validate_rules.py   # 규칙 YAML 문법·필수항목·ID 중복

python -m expense_review.ui.app  # 데스크톱 앱 (PySide6 필요)
expense-review <폴더> --type 출장비
```

테스트는 PySide6 없이도 전부 돈다. UI 코드를 건드렸으면 실제로 앱을 띄워 확인한다.

## 규칙을 고치는 법 — 여기가 이 코드베이스의 핵심

규칙 하나는 **두 곳**에 나뉘어 있다.

| | 어디에 | 누가 고치나 |
|---|---|---|
| 등급 · 문구 · 조치문 · 한도값 | `rules/*.yaml` | 담당자가 앱의 [검토 기준] 화면에서 |
| 판정 로직 | `src/expense_review/checks/` | 개발자가 |

이렇게 나눈 이유는 지침이 바뀔 때 담당자가 코드를 안 건드리고 등급·문구·한도를
바꿀 수 있게 하려는 것이다. 이 경계를 무너뜨리지 않는다.

판정 함수는 **규칙 ID로** 등록한다. YAML 의 `check:` / `expr:` 필드는 사람이 읽는
설명일 뿐, 엔진은 보지 않는다.

```python
from ..engine import Context, Fail, check

@check("R-TRV-006")
def route_total(ctx: Context):
    total = ctx.require("trip_evidence.dist_total")   # 저신뢰면 NeedsReview
    ...
    return Fail({"expected": ...}) if 틀렸으면 else None
```

`@check` 로 등록되지 않은 규칙은 조용히 통과되지 않는다. 결과에 **'미구현'** 으로
올라간다. 현재 87건 중 64건이 등록되어 있다. 남은 23건은
[`docs/06-backlog.md`](docs/06-backlog.md) 에 목록이 있다.

새 규칙을 추가하면 `tools/validate_rules.py` 를 돌리고 `tests/` 에 케이스를 넣는다.

## 판정은 4단계다. "위반/정상" 2분법을 쓰지 않는다

🔴 수정 필요 · 🟡 확인 요망 · 🔵 **판독 불가** · 🟢 이상 없음

손글씨 근무일지와 회전된 영수증 스캔이 섞여 들어온다. 추출 신뢰도가 낮은데도
판정을 내리면 오탐이 쏟아지고, 담당자가 앱을 못 쓰게 된다. 그래서 `ctx.require()`
가 값을 못 믿겠으면 `NeedsReview` 를 올리고, 엔진이 판정 대신 🔵 를 남긴다.

**이 장치를 우회해서 억지로 판정하게 만들지 않는다.** 모르면 사람에게 넘긴다.

## 사용자가 고친 기준은 배포본과 분리되어 있다

```
rules/*.yaml          ← 배포본. git pull 이 덮어쓴다
~/.expense-review/    ← 사용자가 앱에서 고친 것. 업데이트해도 살아남는다
```

`config.py` 가 이 분리를 담당한다. 담당자가 등급이나 한도를 고쳐 둔 상태에서
업데이트가 오면 충돌하거나 수정 내용이 조용히 날아가기 때문이다.
사용자가 고칠 수 있는 항목은 `EDITABLE_RULE_FIELDS` 로 제한한다 — 판정 로직은
코드에 있으므로 열어 주지 않는다.

테스트는 `EXPENSE_REVIEW_HOME` 환경변수로 이 경로를 갈아끼운다. 사용자 홈을
건드리는 테스트를 쓰지 않는다.

## 개인정보 — 저장소에 서류를 올리지 않는다

검토 대상에는 주민등록번호 · 계좌번호 · 신분증 사본이 들어 있다.

- `.gitignore` 가 `*.pdf` `*.hwp` `*.hwpx` `samples/` `서류/` 를 막는다. **풀지 않는다.**
- `tools/make_bundle.py` 의 `NEVER_PACK` 이 배포 zip 에서 한 번 더 막는다.
- 화면과 수정요청서 출력은 `report.py` 가 마스킹한다.
- 테스트는 실제 PDF 대신 `tests/conftest.py` 의 `make_document()` 로 추출 결과를
  직접 만들어 규칙만 시험한다. **샘플 서류를 커밋해서 테스트를 짜지 않는다.**

## 윈도우 실행 파일 (`.bat` / `.vbs`)

한 번 크게 데인 곳이다. 규칙 두 가지를 지킨다.

1. **CP949 로 저장한다.** UTF-8 로 저장하면 한글 윈도우 cmd 가 못 읽는다.
2. **`chcp` 를 쓰지 않는다.** UTF-8 + `chcp 65001` 조합에서 cmd 가 파일을 읽던
   위치를 잃어버려 `echo.` 이 `cho.` 로 잘려 나갔다.

`tools/make_bundle.py` 의 `check_batch_files()` 가 배포 시점에 이 두 가지를 검사하고,
어기면 중단한다. 이 파일들을 편집할 때는 인코딩을 확인한다.

## 코드 구조

```
src/expense_review/
  normalize.py     표기 정규화 (계좌·날짜·금액·은행·지역)
  pdfio.py         PDF 텍스트 추출 + 손상 헤더 복구 폴백
  tables.py        표 좌표 재조립
  classify.py      서류 종류 판정 (지문 → 파일명)
  extractors/      서류별 필드 추출
  engine.py        규칙 로딩·평가·신뢰도 강등
  checks/          규칙 ID별 판정 로직
  report.py        결과 출력 + 개인정보 마스킹
  review.py        폴더 → 결과 파이프라인
  config.py        사용자 기준 오버라이드
  sheets.py        구글시트 연동
  updater.py       자동 업데이트
  cli.py           명령줄
  ui/
    theme.py       디자인 토큰 · 스타일시트 — 색·라운드·그림자는 전부 여기서
    backgrounds.py 그라데이션 배경 (QPainter)
    icons.py       라인 아이콘 (QPainter)
    widgets.py     카드 · KPI 타일 · 도넛 차트 · 파일 카드
    pages/         검토 · 파일별 보완사항 · 검토 기준 · 설정
```

UI 색상값을 페이지 파일에 직접 쓰지 않는다. `theme.py` 의 토큰을 쓴다.

## 글쓰기

커밋 메시지 · 주석 · 문서 · 화면 문구 전부 **한국어**다. 사용자는 대학 행정 담당자다.

커밋 메시지는 무엇을 왜 바꿨는지 한 줄로 쓴다.
`앱 실행 시 검은 창이 깜빡이던 문제 개선` 처럼.

주석은 **왜** 그렇게 했는지를 남긴다. 무엇을 하는지는 코드가 말한다.
이 저장소의 기존 주석들이 그 본보기다 — 따라간다.

## 다음 작업

[`docs/06-backlog.md`](docs/06-backlog.md) 에 남은 일이 정리되어 있다.
가장 큰 것은 **OCR/Vision (4단계)** 과 **L3 한도 규칙에 넣을 규정값 확보**다.
