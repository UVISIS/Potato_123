# [DB 작업 요청] B담당 전체 작업 목록

**작성:** 백엔드(A담당) · 2026-06-13 최종
**대상:** B담당 (DB)
**우선순위:** 🔴 필수 → 🟡 중요 → 🟢 선택

---

## 작업 목록 요약

| # | 작업 | 우선순위 | 상태 |
|---|------|----------|------|
| 1 | `parts_inventory` 단일 중앙창고 단일화 | 🔴 | ⏳ 대기 |
| 2 | `components` soft delete 컬럼 추가 | 🔴 | ⏳ 대기 |
| 3 | `maintenance_history` soft delete 컬럼 추가 | 🔴 | ⏳ 대기 |
| 4 | `aircraft_components` 샘플 데이터 입력 | 🟡 | ⏳ 대기 |
| 5 | 더미 기체(id=2) 실 데이터 교체 | ✅ | 완료 (백엔드에서 처리) |

---

## 1. `parts_inventory` 단일 중앙창고 단일화 🔴

### 배경

기존: 부품 재고를 청주/무안 기지별 분리 보관
변경: **중앙 창고 1개**에서 보관, 출고 시 목적지(청주/무안)만 기록

백엔드 `fn5(record_transaction)` 는 이미 단일행 전제로 수정 완료.
**이 작업 전까지 출고/정비 후처리가 라이브에서 동작하지 않음.**

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

나머지 8개 부품은 이미 단일행 — 합산 불필요 (location만 NULL로 표준화).

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

> ⚠️ 실행 전 스냅샷 권장. audit_log 트리거 있으면 변경 64건+ 기록됨.

### 검증 체크리스트

```sql
-- (1) 모든 부품 1행인지 — 0행이어야 정상
SELECT part_id, COUNT(*) FROM parts_inventory GROUP BY part_id HAVING COUNT(*) > 1;

-- (2) 합산 수량 확인
SELECT part_id, quantity_on_hand, location
FROM parts_inventory
WHERE part_id IN (29,31,32,33,35,37,48,50,52,54,56)
ORDER BY part_id;
```

- [ ] (1) 결과 0행
- [ ] (2) 합산 수량이 위 표와 일치
- [ ] location 전부 NULL
- [ ] 출고 테스트: `POST /transactions {transaction_type:"출고", destination:"무안"}` → 재고 차감 + `parts_transactions.location="무안"` 확인

### data quality 확인 사항

- part_id **29/35** 동일 part_number(`WK724-3`), **31/37** 동일(`LN94-40060`)
  → 실제 같은 부품이면 component 행 통합 여부 별도 협의 필요
  (본 SQL은 part_id 기준으로만 처리)

---

## 2. `components` soft delete 컬럼 추가 🔴

### 배경

부품 삭제 방식을 **soft delete**로 결정.
실제 행 삭제 없이 `is_deleted` 플래그만 변경 → FK(bom·parts_inventory·reorder_points·parts_transactions) 보존, 복구 가능.

백엔드 엔드포인트는 구현 완료 — 컬럼 추가 후 즉시 동작.

### SQL

```sql
-- 컬럼 추가
ALTER TABLE components
  ADD COLUMN IF NOT EXISTS is_deleted boolean NOT NULL DEFAULT false;

-- 조회 성능용 인덱스
CREATE INDEX IF NOT EXISTS idx_components_is_deleted
  ON components (is_deleted);
```

### 검증

```sql
-- 기본값 false 확인
SELECT id, is_deleted FROM components LIMIT 5;

-- 삭제 테스트
UPDATE components SET is_deleted = true WHERE id = 999;  -- 테스트용 id
SELECT id, is_deleted FROM components WHERE id = 999;
UPDATE components SET is_deleted = false WHERE id = 999; -- 롤백
```

### 백엔드 엔드포인트 (완료)

| 엔드포인트 | 동작 |
|-----------|------|
| `DELETE /components/{id}` | `is_deleted = true` |
| `PATCH /components/{id}/restore` | `is_deleted = false` |
| `GET /components` | 기본 `is_deleted=false` 행만 반환. `?include_deleted=true` 로 전체 조회 가능 |

---

## 3. `maintenance_history` soft delete 컬럼 추가 🔴

### 배경

정비 이력은 감사·추적 대상 — 실제 행 삭제 없이 soft delete.
`parts_transactions`(출고 이력) FK 보존.

### SQL

```sql
-- 컬럼 추가
ALTER TABLE maintenance_history
  ADD COLUMN IF NOT EXISTS is_deleted boolean NOT NULL DEFAULT false;

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_maintenance_history_is_deleted
  ON maintenance_history (is_deleted);
```

### 검증

```sql
-- 기본값 확인
SELECT id, is_deleted FROM maintenance_history LIMIT 5;
```

### 백엔드 엔드포인트 (완료)

| 엔드포인트 | 동작 |
|-----------|------|
| `DELETE /maintenance/history/{id}` | `is_deleted = true` |
| `PATCH /maintenance/history/{id}/restore` | `is_deleted = false` |
| `GET /maintenance/history` | 기본 `is_deleted=false` 행만 반환 |

---

## 4. `aircraft_components` 샘플 데이터 입력 🟡

### 배경

`fn2(get_component_status)` 가 기체별 장착 부품 TBO 잔여시간을 계산하는 함수.
현재 `aircraft_components` 0행 → fn2가 빈 결과 반환.

### 필요 컬럼

| 컬럼 | 설명 |
|------|------|
| `aircraft_id` | aircraft.id (FK) |
| `component_name` | 부품명 |
| `component_type` | 타입 (engine/propeller/oil 등 — fn2의 TBO_HOURS_MAP 키와 일치) |
| `installed_date` | 장착일 |
| `install_hours` | 장착 시점 누적 비행시간 |
| `tbo_hours` | TBO 시간 (없으면 fn2의 TBO_HOURS_MAP 사용) |
| `status` | serviceable / unserviceable |

### fn2 TBO_HOURS_MAP 참고 (매핑 키)

```
engine(1800h), propeller(2400h), alternator(2400h), governor(2400h),
fuel_pump(2400h), battery(500h), oil(100h), oil_filter(500h), ...
```

### 최소 샘플 (DA42NG-001, aircraft_id=3 기준)

```sql
INSERT INTO aircraft_components
  (aircraft_id, component_name, component_type, installed_date, install_hours, status)
VALUES
  (3, 'Austro AE300 Engine (L)', 'engine',    '2023-01-15', 4800, 'serviceable'),
  (3, 'Austro AE300 Engine (R)', 'engine',    '2023-01-15', 4800, 'serviceable'),
  (3, 'MTV-6 Propeller (L)',     'propeller', '2024-03-10', 5200, 'serviceable'),
  (3, 'MTV-6 Propeller (R)',     'propeller', '2024-03-10', 5200, 'serviceable');
```

> 실제 장착일·누적시간은 기체 정비 기록 기준으로 교체 필요.

---

## 5. 기타 (선택) 🟢

- **HS코드별 관세율 확인**: fn17 `customs_duty_rate` 파라미터 (현재 기본 0%) → 품목별 실 관세율 반영 시 정확도 향상
- **JCA 대행 수수료율 확인**: fn17 `agent_markup_rate` (현재 placeholder 0.12) → 실 계약 데이터로 교체
