# Potato_123 — 항공 정비 자재 최적 구매 설정 시스템

FastAPI + Supabase 기반 항공기 주기정비 자재 관리 백엔드.  
기체 비행시간 추적 → 정비 도래 감지 → 부품 재고/발주 관리 → 정비 이력 등록의 전 과정을 자동 연쇄 처리합니다.

---

## 빠른 시작 (Quick Start)

### 1. Clone

```bash
git clone https://github.com/UVISIS/Potato_123.git
cd Potato_123
```

### 2. 가상환경 및 패키지 설치

```bash
python -m venv venv

# Windows
.\venv\Scripts\pip install -r requirements.txt
.\venv\Scripts\pip install uvicorn[standard] fastapi requests

# macOS / Linux
./venv/bin/pip install -r requirements.txt
./venv/bin/pip install "uvicorn[standard]" fastapi requests
```

### 3. 환경 변수 설정

`.env.example`을 복사해 `.env` 파일을 만들고 Supabase 값을 채웁니다.

```bash
cp .env.example .env
```

`.env` 내용:

```
SUPABASE_URL=https://<project-id>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<service-role-key>
```

> Supabase 대시보드 → Project Settings → API 에서 확인

### 4. 서버 기동

```bash
# Windows
.\venv\Scripts\python.exe -m uvicorn main:app --reload

# macOS / Linux
./venv/bin/python -m uvicorn main:app --reload
```

서버: `http://127.0.0.1:8000`  
API 문서: `http://127.0.0.1:8000/docs`

---

## 시연 실행

### 자동 시연 (CSC-01 ~ CSC-05 순서 실행)

```bash
# Windows
$env:PYTHONUTF8="1"
.\venv\Scripts\python.exe -X utf8 demo_scenario.py

# macOS / Linux
PYTHONUTF8=1 ./venv/bin/python -X utf8 demo_scenario.py
```

### 자유 시연 (개별 함수 선택 실행)

```bash
# Windows
$env:PYTHONUTF8="1"
.\venv\Scripts\python.exe -X utf8 free_demo.py

# macOS / Linux
PYTHONUTF8=1 ./venv/bin/python -X utf8 free_demo.py
```

기체 선택 후 메뉴:

| 번호 | 항목 | DB 변경 |
|---|---|---|
| 1 | 재고 / BOM / 필요부품 조회 | 없음 |
| 2 | 구매시기 예측 (fn18) — 정비유형별 ×N 묶음, 환율 시기 태그 | 없음 |
| 3 | 환율 (현황 조회 / 오늘자 입력) | ② 선택 시 있음 |
| 4 | 비행시간 입력 | 있음 |
| 5 | 정비이력 등록 | 있음 |
| 6 | 다른 기체 선택 | 없음 |
| 7 | 종료 | — |

---

## 시연 전 DB 리셋

리허설/시연 반복 시 DB를 초기 상태로 되돌립니다.

1. Supabase 대시보드 → **SQL Editor**
2. `reset_demo_db.sql` 전체 내용 붙여넣기 후 실행
3. 최종 확인: 3개 항목 모두 `OK` 여야 함

| 항목 | 기대값 |
|---|---|
| Fuel Filter 재고 (part_id=29) | 3개 |
| HL1179 누적시간 (aircraft_id=6) | 5237.2 h |
| maintenance_schedule id=246 status | scheduled |

자유 시연 후 부분 롤백은 `rollback_from_checkpoint.sql` 사용 (체크포인트 id=831 이후 롤백).

---

## 시연 기준값

| 항목 | 값 |
|---|---|
| 대상 기체 | HL1179 — Diamond DA40 NG (aircraft_id=6) |
| 대상 부품 | Fuel Filter WK724-3 (part_id=29, EUR 112.05) |
| 시작 누적 비행시간 | 5,237.2 h |
| 100H 정비 한계 | 5,237.5 h (잔여 +0.3 h — 임박) |
| Fuel Filter 시작 재고 | 3개 (= 안전재고) |
| BOM 100H DA40NG | 5종, EUR 1,379.24 |

---

## 시연 시나리오 요약

```
CSC-01  항공기 관리
  fn1  기체 정보 조회 — HL1179, 5237.2h 확인
  fn3  비행 0.5h 추가 → 5237.7h (한계 5237.5h 초과 전환)

CSC-02  부품/자재 관리
  fn4   Fuel Filter 재고 조회 — 3개/3개 (안전재고 충족)
  fn13  100H BOM 조회 — 5종, EUR 1,379.24
  fn5   Fuel Filter 1개 출고 → 2개 (안전재고 미달)

CSC-03  발주 관리
  fn7   안전재고 분석 — [부족] 즉시 반영
  fn8   EUR/KRW 환율 + Z-Score — WAIT 권고 (고점 구간)
  fn6   발주 비용 산출 — 5개, EUR 560.25 / 902,002원
  fn17  수입 총원가 — 학술감면 적용, 절감 123,935원
  fn18  구매시기 예측 — 연간 비행시간 자동 계산, 정비유형별 ×N 묶음 표시, 환율 시기 태그

CSC-04  주기정비 관리
  fn11  정비 도래 현황 — [초과] 항공기 100 HRS -0.2h
  fn9   100H 필요 부품 5종 목록
  POST /maintenance/history — 1회 POST로 4단계 자동 연쇄
        history 생성 → fn5 출고 → schedule completed → fn12 D-Time 재계산
  fn14  정비초과 알람 생성 — critical 확인

CSC-05  대시보드
  fn15  12개 지표 일괄 조회
```

---

## 프로젝트 구조

```
Potato_123/
├── main.py                          # FastAPI 앱 진입점
├── database.py                      # Supabase 클라이언트
├── requirements.txt
├── .env.example                     # 환경 변수 템플릿 (.env 는 .gitignore)
├── demo_scenario.py                 # 자동 시연 스크립트 (CSC-01~05)
├── free_demo.py                     # 자유 시연 스크립트
├── reset_demo_db.sql                # 시연 전 DB 리셋 SQL
├── rollback_from_checkpoint.sql     # 자유 시연 후 롤백 SQL
├── routers/
│   ├── aircraft.py
│   ├── components.py                # CSC-02 부품/자재
│   ├── maintenance.py               # CSC-04 주기정비
│   ├── purchase.py                  # CSC-03 발주
│   └── dashboard.py                 # CSC-05 대시보드
└── functions/
    ├── constants.py                 # 공용 상수 (비행시간 가정, 임계치, 기종 정규화)
    ├── csc02/
    │   ├── fn4_get_inventory.py
    │   ├── fn5_issue_part.py
    │   └── fn13_get_maintenance_bom.py
    ├── csc03/
    │   ├── fn6_calculate_order_cost.py
    │   ├── fn7_analyze_safety_stock.py
    │   ├── fn8_get_exchange_rate.py
    │   ├── fn17_calculate_import_cost.py
    │   └── fn18_forecast_purchase_timing.py
    └── csc04/
        ├── fn9_get_required_parts.py
        ├── fn11_get_maintenance_status.py
        ├── fn12_update_d_time_counter.py
        └── fn14_generate_alarm.py
```

---

## 기술 스택

| 구분 | 기술 |
|---|---|
| Backend | Python 3.x, FastAPI |
| Database | Supabase (PostgreSQL), supabase-py 2.31.0 |
| 서버 | uvicorn |
| 협업 | Git, GitHub |
