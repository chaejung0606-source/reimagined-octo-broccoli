# 03. 필드 사전 & 정규화 규칙

> **구현 상태:** 필드는 값·신뢰도에 더해 **상태**(값 있음 / 공란 / 미추출)를 함께 갖습니다.
> `공란`은 판정 대상(🔴)이고 `미추출`만 🔵 로 강등합니다 — [05. 구현 노트](05-implementation.md) §2-1.

규칙(YAML)은 전부 이 필드들 위에서만 동작합니다. **추출기가 바뀌어도 규칙은 그대로**입니다.

---

## 1. 정규화 함수

서류마다 표기가 제각각이라, 비교 전에 반드시 정규화합니다. **이 단계를 빼면 오탐이 대부분입니다.**

| 함수 | 처리 | 예 |
|---|---|---|
| `digits_only` | 숫자만 남김 | `592201-01-565992` → `59220101565992` |
| `strip_spaces` | 공백·전각공백 제거 | `권 석 재` → `권석재` |
| `bank_alias` | 은행 별칭 통일 | `국민` → `국민은행`, `카카오` → `카카오뱅크`, `토스` → `토스뱅크` |
| `money` | 콤마·`원` 제거 후 정수 | `1,200원` → `1200` |
| `date` | 아래 표기 전부 흡수 | `2026.06.29.`, `26/03/9`, `2026년 6월 29일`, `2026. 03. 31.` → `2026-06-29` |
| `datetime` | 날짜+시각 | `2026년07월03일 13시20분` → `2026-07-03T13:20` |
| `hours` | `5`, `5시간`, `5.0` → `5.0` | |
| `hangul_amount` | 숫자 ↔ 한글 금액 | `240000` ↔ `금이십사만원정` |
| `region_of` | 주소 → 시군구 | `강원평창군대관령면대관령로100` → `강원 평창군` |

> **주의:** 날짜 파서에 `26/03/9` 같은 표기가 들어옵니다(연 2자리, 월일 비제로패딩).
> 근무상황부 손글씨에서 특히 흔하므로 파서에 반드시 포함하세요.

---

## 2. 공통 필드

| 필드 | 타입 | 정규화 | 출처 |
|---|---|---|---|
| `person.name` | str | strip_spaces | 전 서류 |
| `person.student_id` | str | digits_only | 신청서·동의서·지급내역 |
| `person.department` | str | strip_spaces | 동의서·보고서·재학증명서 |
| `person.rrn` | str | digits_only | 동의서·신분증 |
| `person.phone` | str | digits_only | 동의서·신청서 |
| `person.email` | str | lower | 신청서 |
| `person.bank` | str | bank_alias | 동의서·신청서·지급내역·통장 |
| `person.account_no` | str | digits_only | 동상 |
| `person.affiliation` | str | strip_spaces | 출장신청서 |
| `person.rank` | str | strip_spaces | 출장신청서 |
| `submission.date` | date | date | 서류 하단 작성일 |
| `period.start` / `period.end` | date | date | 근로기간·활동기간·출장기간 |
| `bankbook.holder` / `.account_no` | str | — | 통장 사본 (Vision) |
| `enrollment_cert.issued_at` | date | date | 재학증명서 (Vision) |
| `roster.*` | — | — | 지급내역 표 (마스터) |

`roster` 하위: `name`, `student_id`, `bank`, `account_no`, `unit_price`, `hours`, `amount`, `course_name`, `club_name`

---

## 3. 근로장학금 필드

```
worklog.program              프로그램/역할        "데이터보안활용융합진로설계 /TA"
worklog.period.start/.end    근로기간             2026-03-03 ~ 2026-03-31
worklog.approver             확인자(교수,담당자)   "손경호"
worklog.applicant            신청인               "권석재"
worklog.total_hours          총 근로시간          15.0
worklog.rows[]               근로일자 및 시간
  ├ .date       근로일자    2026-03-09
  ├ .weekday    요일        "월"
  ├ .start/.end 시작/종료   09:00 / 14:00
  ├ .hours      시간        5.0
  └ .detail     근로상세내역 "강의실 환경 개선"

claim_form.amount            청구금액             300000
claim_form.period            활동기간             2026-04-07 ~ 2026-04-30
claim_form.program           프로그램명           "COSS 서포터즈"

monthly_report.hours         활동 시간            25.0
monthly_report.dates         활동 일자            [2026-04-07 … 2026-04-30]
monthly_report.photos[]      활동사진 개수
monthly_report.achievement   목표 달성 정도(본문)
monthly_report.self_review   자체 평가 및 개선사항

worklog_handwrite.rows[]     근무일지(손글씨)      ※ 신뢰도 낮음 → REVIEW 강등 대상
  ├ .date/.start/.end/.hours
  ├ .content          운영 내용
  ├ .headcount        이용자 수 (명)
  └ .sign_self/.sign_staff/.sign_lead   결재란 서명 유무
worklog_handwrite.total_days / .total_hours / .total_headcount

form1_recommendation.professor          담당교수
form1_recommendation.operating_period   운영일(첫 수업일~종강일)
form1_recommendation.course             과목명
form1_recommendation.credit             학점/구분
```

---

## 4. 혁신인재지원금 필드

```
club.name        소학회명      "AIMPACT"
club.advisor     지도교수      "강경필"
club.field       활동분야      "클라우드"
club.topic       활동주제

form8_application.applicant / .amount / .amount_hangul
form8_application.attachments_checked[]   증빙서류 체크박스
form8_application.consent                 개인정보 동의 (bool)

form7_1_report.president        회장
form7_1_report.field_checked    체크된 활동분야
form7_1_report.members[]        팀원 명단
  └ .role / .name / .department / .student_id / .phone
form7_1_report.outcomes[]       성과표
  └ .category / .plan_goal / .this_month / .cumulative
form7_1_report.highlights[]     대표 성과 (본문)
form7_1_report.activity_dates[] 본문에서 추출한 활동 일자   ← R-INN-012 의 입력
form7_1_report.next_plan        향후 계획
form7_1_report.page_count

attach1_worklog.*               근로장학금 worklog 과 동일 구조 (재사용)
```

> `form7_1_report.activity_dates` 는 **본문 자유서술에서 날짜를 뽑아내야** 합니다
> (`5월 18일 정기 성과공유회 진행` → `2026-05-18`). 정규식 + LLM 병행이 필요한 유일한 필드입니다.

---

## 5. 출장비 필드

```
trip_request.doc_no              문서번호      "HRHFB260626UF0000000002160002101"
trip_request.issued_at           시행일자      2026-06-29
trip_request.department          부서명
trip_request.approvers[]         결재선
trip_request.trips[]             출장 건 (신청서 1장에 복수 가능)
  ├ .name        성명
  ├ .rank        직급
  ├ .purpose     출장내용
  ├ .period      출장기간  2026-06-29T09:00 ~ 2026-07-01T18:00
  ├ .destination 출장지    "강원 평창, 강릉"
  └ .allowance_eligible  여비지급대상여부 (예/아니오)
trip_request.purpose_type        출장목적      업무회의 / 공무 / 기타
trip_request.uses_official_vehicle  공용차량이용 (bool)
trip_request.funding             회계구분·지급기관

trip_evidence.transport_block    교통비 증빙 블록 존재 여부
trip_evidence.transport_amount   교통비 증빙 금액      18000
trip_evidence.route_block        이동경로 블록 존재 여부
trip_evidence.dist_out           출발지→도착지 (km)    211
trip_evidence.dist_back          도착지→출발지 (km)    154
trip_evidence.dist_total         총 이동경로 (km)      365   ← 공란이면 None
trip_evidence.map_distance       지도 캡처에서 읽은 거리 365
trip_evidence.route_note         경유 사유 메모
trip_evidence.stay_dates[]       체류 증빙 페이지의 날짜들

receipts[]                       모든 영수증 (교통·체류 통합)
  ├ .kind          tollgate | fuel | transit | stay | etc
  ├ .datetime      2026-07-03T13:20
  ├ .amount        4350
  ├ .merchant      "GS25횡계점" / "제2영동고속도로 초월영업소"
  ├ .merchant_address
  ├ .biz_no        사업자등록번호
  ├ .card_no       "0140-02**-****-4852"
  ├ .approval_no   승인번호          ← 중복 검출 키
  ├ .tollgate_in / .tollgate_out    입구영업소 / 영업소
  ├ .items[]       .name / .qty / .amount   (편의점 전표)
  └ .stated_total  영수증에 적힌 "총 N건 / 합계"

claim.daily / .meal / .lodging / .nights / .mileage_amount   ← 여비 산정 결과
```

---

## 6. 추출 신뢰도 (confidence)

모든 필드는 값과 함께 `confidence ∈ [0,1]` 를 갖습니다.

| 출처 | 기본 신뢰도 |
|---|---|
| PDF 텍스트 레이어 직접 추출 | 0.98 |
| PDF 표 좌표 재조립 | 0.90 |
| 인쇄물 OCR | 0.85 |
| Vision LLM (인쇄물) | 0.85 |
| Vision LLM (손글씨) | **0.60** |
| 값 없음 / 파싱 실패 | 0.0 |

규칙의 `requires` 필드 중 하나라도 `confidence < 0.85` 면 → 판정 결과와 무관하게 **`REVIEW`(판독 불가)** 로 강등하고, 화면에 원본 이미지 조각(crop)을 나란히 띄워 사람이 직접 확인하게 합니다.

이 장치가 없으면 손글씨 근무일지 때문에 오탐이 쏟아져 앱을 못 씁니다.
