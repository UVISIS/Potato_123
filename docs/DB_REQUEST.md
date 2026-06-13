# [DB 작업 요청] B담당 전체 작업 목록

**작성:** 백엔드(A담당) · 2026-06-13 최종
**대상:** B담당 (DB)
**우선순위:** 🔴 필수(없으면 기능 불가) → 🟡 중요(주요 기능 영향) → 🟢 선택

---

## 작업 목록 요약

| # | 작업 | 우선순위 | 상태 |
|---|------|----------|------|
| 1 | `parts_inventory` 단일 중앙창고 단일화 | 🔴 | ⏳ 대기 |
| 2 | `components` soft delete 컬럼 추가 | 🔴 | ⏳ 대기 |
| 3 | `maintenance_history` soft delete 컬럼 추가 | 🔴 | ⏳ 대기 |
| 4 | `bom` 정비종류 보완 (100H·200H·500H·Engine_200H) | 🟡 | ⏳ 대기 |
| 5 | `aircraft_components` 데이터 입력 | 🟡 | ⏳ 대기 |
| 6 | `components.unit_price_eur` 단가 입력 | 🟡 | ⏳ 대기 |
| 7 | `aircraft` 실 데이터 보완 (serial·제조연도·기지) | 🟡 | ⏳ 대기 |
| 8 | `maintenance_history` 샘플 이력 확인·교체 | 🟡 | ⚠️ A임의입력 |
| 9 | `currency_rates` 2026년 데이터 추가 | 🟢 | ⏳ 대기 |
| 10 | `maintenance_schedule` 신규 7대 due_hours 입력 | 🟡 | ⚠️ A임의입력 |

---

## 1. `parts_inventory` 단일 중앙창고 단일화 🔴

### 배경

기존: 부품 재고를 청주/무안 기지별 분리 보관
변경: **중앙 창고 1개**에서 보관, 출고 시 목적지(청주/무안)만 기록

백엔드 `fn5(record_transaction)`는 이미 단일행 전제로 수정 완료.
**이 작업 전까지 아래 11개 부품의 입고·출고·정비 자동출고가 전부 오류.**

### 단일화 대상 (11개 부품)

| part_id | part_number | 품명 | 청주 | 무안 | 합산 |
|---------|-------------|------|------|------|------|
| 29 | WK724-3 | Fuel Filter | 8 | 3 | **11** |
| 31 | LN94-40060 | Split Pin | 10 | 5 | **15** |
| 32 | DIN985-M6-A2 | Nut | 20 | 10 | **30** |
| 33 | RU-1620 | Air Filter | 4 | 2 | **6** |
| 35 | WK724-3 | Fuel Filter | 3 | 0 | **3** |
| 37 | LN94-40060 | Split Pin | 7 | 3 | **10** |
| 48 | Shell HELIX Ultra(5W-40) | Eng' OIL | 2 | 1 | **3** |
| 50 | E4A-41-300-803 | Ear Clamp | 4 | 2 | **6** |
| 52 | E4A-52-300-KIT | Eng' Oil Filter | 6 | 2 | **8** |
| 54 | Pre-filled envelope | Oil Sampling | 1 | 0 | **1** |
| 56 | Shell Spirax S6 GXME 75W-80 | Eng' Gear box oil | 3 | 1 | **4** |

나머지 19개 부품은 이미 단일행 — 이 SQL 실행 시 합산 처리됨.

### 마이그레이션 SQL

```sql
BEGIN;

-- 1) 각 part_id 합산 수량을 대표행(최소 id)에 반영 + location = NULL (중앙창고)
WITH agg AS (
    SELECT part_id,
           MIN(id)               AS keep_id,
           SUM(quantity_on_hand) AS total_qty
    FROM parts_inventory
    GROUP BY part_id
)
UPDATE parts_inventory pi
SET quantity_on_hand = agg.total_qty,
    location         = NULL,
    last_updated     = now()
FROM agg
WHERE pi.id = agg.keep_id;

-- 2) 대표행이 아닌 중복행 삭제
DELETE FROM parts_inventory pi
USING (
    SELECT part_id, MIN(id) AS keep_id
    FROM parts_inventory
    GROUP BY part_id
) k
WHERE pi.part_id = k.part_id
  AND pi.id <> k.keep_id;

-- 3) 검증 (0행이어야 정상)
-- SELECT part_id, COUNT(*) FROM parts_inventory GROUP BY part_id HAVING COUNT(*) > 1;

COMMIT;
```

> ⚠️ 실행 전 스냅샷 권장. audit_log 트리거 있으면 변경 기록됨.

### 검증 체크리스트

- [ ] `SELECT part_id, COUNT(*) FROM parts_inventory GROUP BY part_id HAVING COUNT(*) > 1;` → 0행
- [ ] 합산 수량이 위 표와 일치
- [ ] location 전부 NULL
- [ ] 출고 테스트: `POST /transactions {transaction_type:"출고", destination:"무안"}` 정상 동작

### data quality 확인

- part_id **29/35** 동일 part_number(`WK724-3`), **31/37** 동일(`LN94-40060`) → 실제 같은 부품이면 component 통합 여부 협의

---

## 2. `components` soft delete 컬럼 추가 🔴

백엔드 엔드포인트 구현 완료. **컬럼만 없어서 부품 삭제 시 오류 발생.**

```sql
ALTER TABLE components
  ADD COLUMN IF NOT EXISTS is_deleted boolean NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS idx_components_is_deleted ON components (is_deleted);
```

### 검증

```sql
SELECT id, is_deleted FROM components LIMIT 3;  -- 전부 false이면 정상
```

### 백엔드 엔드포인트 (완료)

| 엔드포인트 | 동작 |
|-----------|------|
| `DELETE /components/{id}` | `is_deleted = true` |
| `PATCH /components/{id}/restore` | `is_deleted = false` |
| `GET /components` | 기본 `is_deleted=false`만 반환. `?include_deleted=true` → 전체 |

---

## 3. `maintenance_history` soft delete 컬럼 추가 🔴

정비 이력은 감사·추적 대상이므로 실제 삭제 없이 soft delete.
`parts_transactions` FK 보존.

```sql
ALTER TABLE maintenance_history
  ADD COLUMN IF NOT EXISTS is_deleted boolean NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS idx_maintenance_history_is_deleted ON maintenance_history (is_deleted);
```

### 백엔드 엔드포인트 (완료)

| 엔드포인트 | 동작 |
|-----------|------|
| `DELETE /maintenance/history/{id}` | `is_deleted = true` |
| `PATCH /maintenance/history/{id}/restore` | `is_deleted = false` |
| `GET /maintenance/history` | 기본 `is_deleted=false`만 반환 |

---

## 4. `bom` 정비종류 보완 🟡

### 현재 상태

bom 테이블에 아래 4종만 있음:

| 있는 것 | 없는 것 |
|---------|---------|
| Annual | **항공기 100 HRS / 100H** |
| Governor(2400시간&72개월) | **항공기 200 HRS / 200H** |
| Propeller(2600시간&72개월) | **항공기 500 HRS / 500H** |
| TRP_100H | **ENG' 200 HRS / Engine_200H** |
| | **ENG' 100 HRS** |
| | **ENG' 300 HRS** |

### 영향

100H·200H·500H·Engine_200H 정비 등록 시 자동출고 대상 부품이 없어서
`POST /maintenance/history` 후처리에서 BOM 출고 부품이 0건으로 반환됨.

### 요청

`주기검사 항목 PDF(DA40NG/DA42NG)` 및 작업지시서(WORK_ORDER) 기반으로
각 정비종류별 소요 부품(part_id + required_qty)을 bom 테이블에 INSERT.

```sql
-- 예시 형식
INSERT INTO bom (maintenance_type, aircraft_model, part_id, required_qty, unit, notes)
VALUES
  ('항공기 100 HRS', 'Diamond DA40 NG', <part_id>, <qty>, 'pcs', '비고'),
  ...;
```

> 백엔드에서 `maintenance_type` 매핑은 maintenance_schedule의 값과 **정확히 일치**해야 함.
> 현재 DA40NG 스케줄 정비종류: `항공기 100 HRS`, `항공기 200 HRS`, `항공기 500 HRS`, `ENG' 100 HRS`, `ENG' 300 HRS` 등

---

## 5. `aircraft_components` 데이터 입력 🟡

`fn2(get_component_status)`가 기체별 TBO 잔여시간을 계산하는 함수.
현재 **0행 → fn2 전체 불가**.

### 필요 컬럼

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `aircraft_id` | int | aircraft.id (FK) |
| `component_name` | text | 부품명 |
| `component_type` | text | fn2 TBO_HOURS_MAP 키와 일치 필요 |
| `installed_date` | date | 장착일 |
| `install_hours` | numeric | 장착 시점 누적 비행시간 |
| `tbo_hours` | numeric | TBO (없으면 fn2 내부 MAP 사용) |
| `status` | text | serviceable / unserviceable |

### fn2 TBO_HOURS_MAP 키 목록 (component_type 매핑용)

```
engine(1800h), propeller(2400h), alternator(2400h), governor(2400h),
fuel_pump(2400h), battery(500h), backup_battery(1년), elt_battery(6년),
coolant(500h), brake_fluid(500h), safety_harness(1000h),
oil(100h), air_filter(500h), fuel_filter(1000h), oil_filter(500h)
```

### 최소 샘플 (기체별 엔진·프로펠러)

```sql
-- DA42NG HL2046 (aircraft_id=3), DA40NG 기체들은 aircraft_id 2,4~10
INSERT INTO aircraft_components
  (aircraft_id, component_name, component_type, installed_date, install_hours, status)
VALUES
  -- DA42NG (쌍발)
  (3, 'Austro AE300 Engine (L)', 'engine',    '2023-01-15', 900, 'serviceable'),
  (3, 'Austro AE300 Engine (R)', 'engine',    '2023-01-15', 900, 'serviceable'),
  (3, 'MT-Propeller (L)',        'propeller', '2024-03-10', 1200, 'serviceable'),
  (3, 'MT-Propeller (R)',        'propeller', '2024-03-10', 1200, 'serviceable'),
  -- DA40NG HL1176 (단발) — 나머지 기체도 동일 형식으로
  (2, 'Austro AE300 Engine',    'engine',    '2020-06-01', 3800, 'serviceable'),
  (2, 'MT-Propeller',           'propeller', '2022-09-01', 4200, 'serviceable');
```

> `install_hours`는 장착 당시 기체 누적 비행시간. 실 정비 기록 기반으로 교체 필요.

---

## 6. `components.unit_price_eur` 단가 입력 🟡

현재 **252개 전부 NULL** → 아래 기능 전부 불가:

- 발주 비용 계산 (`GET /procurement/order-cost`)
- 수입 총원가 계산 (`POST /procurement/landed-cost`)
- BOM 예상 비용 조회 (`GET /components/bom/{maintenance_type}`)
- Page 4 안전재고 관리 '전 분기 단가' 표시

### 데이터 소스

프로젝트 폴더의 견적서 PDF들에 EUR 단가가 있음:
- `견적서DA40NG_엔진_1종_4점.pdf`
- `붙임1_견적서비행교육원청주_연료펌프_등_20종.pdf`
- `붙임1_견적서비행교육원무안_구리스_등_24종.pdf`
- 기타 견적서 다수

### 업데이트 방식

```sql
UPDATE components SET unit_price_eur = <EUR단가> WHERE part_number = '<P/N>';
-- 또는 bulk UPDATE
UPDATE components SET unit_price_eur = v.price
FROM (VALUES
  ('<part_number>', <price_eur>),
  ...
) AS v(pn, price)
WHERE components.part_number = v.pn;
```

---

## 7. `aircraft` 실 데이터 보완 🟡

### 현재 상태 (A담당이 XLS 기반으로 입력한 것)

| id | registration | model | total_flight_hours | 비고 |
|----|-------------|-------|-------------------|------|
| 2 | HL1176 | Diamond DA40 NG | 6011.4 | XLS 기반 |
| 3 | HL2046 | Diamond DA42 NG | 2059.4 | XLS 기반 |
| 4~10 | HL1177~HL1295 | Diamond DA40 NG | XLS 기반 | 신규 INSERT |

### 추가 입력 필요 컬럼

```sql
-- 예시
UPDATE aircraft SET
  serial_number    = 'xxxxxxx',   -- 기체 S/N
  manufacture_year = 20xx,        -- 제조연도
  last_inspection_date = '20xx-xx-xx'
WHERE registration = 'HL1176';
```

> `category` 컬럼: HL1176~HL1295는 `'DA-40 NG'`, HL2046은 `'DA-42 NG'`로 이미 입력됨.

---

## 8. `maintenance_history` 샘플 이력 확인·교체 🟡

**A담당이 임의로 입력한 데이터** — 실 이력과 다를 수 있음.

### 현재 입력된 임의 샘플 (9건, 모두 aircraft_id=3 DA42NG-HL2046)

| id | 날짜 | 정비종류 | 정비시간 | 담당자 |
|----|------|---------|---------|--------|
| 1 | 2025-08-15 | 100H | 5577.0h | mech_cju_01 |
| 2 | 2025-09-22 | 100H | 5677.0h | mech_cju_02 |
| 3 | 2025-10-18 | 200H | 5700.0h | mech_mua_01 |
| 4 | 2025-11-20 | 100H | 5777.0h | mech_cju_01 |
| 5 | 2025-12-12 | TRP_100H | 5800.0h | mech_mua_02 |
| 6 | 2026-01-16 | 100H | 5877.0h | mech_cju_02 |
| 7 | 2026-02-14 | Engine_200H | 5900.0h | mech_cju_01 |
| 8 | 2026-03-25 | 500H | 5950.0h | mech_mua_01 |
| 9 | 2026-05-10 | 100H | 5977.0h | mech_cju_01 |

> - 실 정비 이력 있으면 `DELETE FROM maintenance_history WHERE id IN (1..9);` 후 실 데이터 INSERT
> - 없으면 그대로 사용 가능 (월별 차트 테스트용으로는 충분)
> - `handled_by`는 user_roles의 user_id와 연결됨 — 실 담당자로 교체 시 함께 수정

---

## 9. `currency_rates` 2026년 데이터 추가 🟢

현재 최신: 2025-12. 2026년 데이터 없어 fn17(수입원가) 환율이 고정값(1685) 사용 중.

```sql
-- 백엔드 fn8.record_exchange_rate() 호출로 추가 가능
-- 또는 직접 INSERT
INSERT INTO currency_rates (currency_code, base_currency, exchange_rate, update_date)
VALUES
  ('EUR', 'KRW', <실환율>, '2026-01-01T00:00:00+00:00'),
  ('EUR', 'KRW', <실환율>, '2026-02-01T00:00:00+00:00'),
  ...;
```

> `POST /currency-rates` API는 없음. fn8 또는 직접 INSERT 사용.

---

## 10. `maintenance_schedule` 신규 7대 due_hours 확인·보완 🟡

### 현재 상태

A담당이 XLS NEXT DUE 기반으로 HL1176·HL2046·일부 기체에만 due_hours를 입력함.
**HL1177~HL1295(id 4~10) 중 상당수 due_hours = NULL** → fn11·fn18 계산 정확도 저하.

### 확인 쿼리

```sql
SELECT a.registration, ms.maintenance_type, ms.due_hours, ms.status
FROM maintenance_schedule ms
JOIN aircraft a ON a.id = ms.aircraft_id
WHERE ms.due_hours IS NULL
ORDER BY a.registration, ms.maintenance_type;
```

### 처리 방식 (협의)

**방안 A** — 실 정비 기록 기반으로 due_hours 직접 입력 (정확)
**방안 B** — 백엔드 fn11 calc_next_maintenance()가 현재 누적시간 + interval_hours로 추정값 자동 계산
→ 방안 B로 진행 시 A담당이 자동 채우는 스크립트 작성 가능

---

## 기타 선택 사항 🟢

| 항목 | 내용 |
|------|------|
| HS코드별 관세율 | fn17 `customs_duty_rate` 파라미터 (현재 기본 0%) → 품목별 실 관세율 반영 |
| JCA 대행 수수료율 | fn17 `agent_markup_rate` (현재 placeholder 0.12) → 실 계약 데이터로 교체 |
| user_roles 실 데이터 교체 | A담당 임의 생성(admin01/mech_cju_01 등) → 실 담당자 ID·이름으로 교체 |
