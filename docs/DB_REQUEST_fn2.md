# 🛠️ DB 담당 요청 — fn2 `get_component_status()` 작성 선행 조건

> 작성: 백엔드(A담당) · 수신: DB담당(B담당) · 갱신일: 2026-06-10
> 위치: 이 문서는 리포에 함께 커밋되어 fn2 미작성 사유와 필요한 DB 조치를 공유합니다.

## fn2 개요
- **함수**: `get_component_status(aircraft_id)` — 기체 장착 부품의 TBO 잔여시간 조회
- **CSC/CSU**: CSC-01 / CSU-01-02
- **사용 테이블**: `aircraft_components`, `aircraft`
- **반환(예정)**: `[{component_name, component_type, installed_date, tbo_hours, remaining_tbo, status}, ...]`
- **핵심 계산**: `remaining_tbo = (install_hours + tbo_hours) − aircraft.total_flight_hours`

## 현재 상태: ⏳ 미작성 (선행 조치 2건 대기)

### ✅ 이미 해결된 항목
- `aircraft_components.install_hours` 컬럼 — **라이브 스키마에 이미 존재** (P2 No.16 반영 완료). 추가 조치 불필요.

### ⛔ 막고 있는 항목 2건

**① `aircraft_components` 데이터 0행 — 6/9 요청서에 투입 항목 누락**
- fn2 가 읽는 핵심 테이블이나 현재 0행 → 호출 시 빈 결과.
- 6/9 요청서 3번(데이터 투입)에 `parts_inventory`/`reorder_points`/`bom`/`suppliers`만 있고 `aircraft_components` 누락.
- **조치**: 기체별 주요 장착품 몇 개 INSERT (수량/시간 임의값 가능 — 시연 목적).

```sql
-- aircraft_id 는 aircraft 테이블 실제 id 로 교체 (예: HL1252=1, HL1254=2)
-- install_hours = 장착 시점 누적 비행시간, tbo_hours = 오버홀 주기
INSERT INTO aircraft_components
  (aircraft_id, component_name, component_type, installed_date, status, install_hours)
VALUES
  (1, 'Austro AE300 Engine', 'engine',    '2023-03-01', 'serviceable',  800.0),
  (1, 'MTV-6 Propeller',     'propeller', '2023-03-01', 'serviceable',  800.0),
  (2, 'Austro AE300 Engine', 'engine',    '2022-06-01', 'serviceable', 1500.0),
  (2, 'MTV-6 Propeller',     'propeller', '2022-06-01', 'serviceable', 1500.0);
```

**② `tbo_hours` 출처 없음 — 컬럼 신설 또는 하드코딩 결정 필요**
- 반환값에 `tbo_hours` 가 필요하나 `aircraft_components`/`components` 어디에도 TBO 컬럼이 없음.
- 두 가지 선택지:
  - **(권장) `aircraft_components.tbo_hours` 컬럼 신설** — 부품별 TBO를 DB가 보유. 정석.
  - (대안) 백엔드에서 `component_type`별 TBO 하드코딩 맵으로 임시 처리 (fn7 `avg_daily_usage` 방식). DB 조치 없이 fn2 즉시 작성 가능하나 데이터 정합성은 약함.

```sql
-- 선택지 ① 채택 시 (권장)
ALTER TABLE aircraft_components ADD COLUMN tbo_hours numeric;

-- 위 INSERT 에 tbo_hours 동봉 예시 (엔진 1800h / 프로펠러 2400h — 정비매뉴얼 확인 후 확정)
-- UPDATE aircraft_components SET tbo_hours = 1800 WHERE component_type = 'engine';
-- UPDATE aircraft_components SET tbo_hours = 2400 WHERE component_type = 'propeller';
```

## B 담당 결정 요청
1. 위 `aircraft_components` 샘플 INSERT 실행 여부/값 확정
2. `tbo_hours` — **컬럼 신설(①)** vs **백엔드 하드코딩(②)** 중 택1
3. 결정되면 백엔드가 fn2 본 작성 + 단위 테스트 추가 (소요 1~2시간)

> 참고: TBO 실제 수치(엔진/프로펠러)는 DA40NG/DA42NG 정비매뉴얼 기준으로 확정 필요. 위 값은 시연용 임의값.
