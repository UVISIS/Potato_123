-- ============================================================
-- reset_demo_db.sql
-- Potato_123 시연 DB 리셋 스크립트
-- Supabase project: uwegumjzzdmxsyynqvoa (ap-northeast-2)
-- 용도: 리허설/시연 후 원상복구 (반복 실행 가능)
-- ============================================================

-- ──────────────────────────────────────────────────────────
-- STEP 0.  실행 전 현황 확인 (SELECT — DB 변경 없음)
-- ──────────────────────────────────────────────────────────

-- 현재 Fuel Filter 재고 확인
SELECT part_id, quantity_on_hand
FROM parts_inventory
WHERE part_id = 29;

-- 현재 HL1179 누적시간 확인
SELECT id, registration, total_flight_hours
FROM aircraft
WHERE id = 6;

-- 시연 중 생성된 flight_hours 행 확인
SELECT id, flight_date, flight_hours, notes
FROM flight_hours
WHERE aircraft_id = 6
  AND flight_date = '2026-06-22'
ORDER BY id DESC;

-- 시연 중 생성된 정비이력 확인
SELECT id, maintenance_date, maintenance_type, handled_by
FROM maintenance_history
WHERE aircraft_id = 6
  AND maintenance_date = '2026-06-22'
ORDER BY id DESC;

-- 시연 중 생성된 출고 거래 확인
SELECT id, transaction_date, transaction_type, quantity, notes
FROM parts_transactions
WHERE part_id = 29
  AND transaction_date = '2026-06-22'
ORDER BY id DESC;

-- maintenance_schedule id=246 현재 상태 확인
SELECT id, maintenance_type, status, due_hours
FROM maintenance_schedule
WHERE id = 246;


-- ──────────────────────────────────────────────────────────
-- STEP 1.  Fuel Filter 재고 복구  (part_id=35 → 3개)
-- ──────────────────────────────────────────────────────────
-- 시연 중 출고: CSC-02 fn5(1개) + POST /maintenance/history fn5(1개) = 총 2개 차감
UPDATE parts_inventory
SET quantity_on_hand = 3
WHERE part_id = 29;

-- 확인
SELECT part_id, quantity_on_hand FROM parts_inventory WHERE part_id = 29;


-- ──────────────────────────────────────────────────────────
-- STEP 2.  HL1179 누적 비행시간 복구  (5237.2h)
-- ──────────────────────────────────────────────────────────
-- CSC-01 fn3 에서 0.5h 추가됨 → 5237.2 로 복원
UPDATE aircraft
SET total_flight_hours = 5237.2
WHERE id = 6;

-- 확인
SELECT id, registration, total_flight_hours FROM aircraft WHERE id = 6;


-- ──────────────────────────────────────────────────────────
-- STEP 3.  시연 중 추가된 flight_hours 행 삭제
-- ──────────────────────────────────────────────────────────
DELETE FROM flight_hours
WHERE aircraft_id = 6
  AND flight_date = '2026-06-22'
  AND (notes LIKE '%시연%' OR pilot_name = '시연');

-- 확인
SELECT COUNT(*) AS deleted_count
FROM flight_hours
WHERE aircraft_id = 6 AND flight_date = '2026-06-22';


-- ──────────────────────────────────────────────────────────
-- STEP 4.  maintenance_schedule id=246 상태 복구
-- ──────────────────────────────────────────────────────────
-- POST /maintenance/history 에서 status='completed' 로 변경됨 → 'scheduled' 로 복원
-- (overdue 상태는 fn11 런타임 판정이므로 'scheduled' 로 복원해도 fn11이 '초과'로 표시함)
UPDATE maintenance_schedule
SET status = 'scheduled'
WHERE id = 246;

-- 확인
SELECT id, maintenance_type, status, due_hours FROM maintenance_schedule WHERE id = 246;


-- ──────────────────────────────────────────────────────────
-- STEP 5.  시연 중 생성된 maintenance_history 삭제
-- ──────────────────────────────────────────────────────────
-- 주의: is_deleted soft delete 또는 물리 삭제 선택
-- 물리 삭제 (FK parts_transactions.maintenance_history_id 먼저 NULL 처리 필요)

-- 5-1. parts_transactions 의 maintenance_history_id 참조 해제
UPDATE parts_transactions
SET maintenance_history_id = NULL
WHERE maintenance_history_id IN (
    SELECT id FROM maintenance_history
    WHERE aircraft_id = 6
      AND maintenance_date = '2026-06-22'
);

-- 5-2. 정비이력 삭제
DELETE FROM maintenance_history
WHERE aircraft_id = 6
  AND maintenance_date = '2026-06-22';

-- 확인
SELECT COUNT(*) AS remaining
FROM maintenance_history
WHERE aircraft_id = 6 AND maintenance_date = '2026-06-22';


-- ──────────────────────────────────────────────────────────
-- STEP 6.  시연 중 생성된 parts_transactions 삭제
-- ──────────────────────────────────────────────────────────
-- CSC-02 fn5(출고) + 정비이력 fn5(출고) = 2건
DELETE FROM parts_transactions
WHERE part_id = 29
  AND transaction_date = '2026-06-22'
  AND transaction_type = '출고';

-- 확인
SELECT COUNT(*) AS remaining
FROM parts_transactions
WHERE part_id = 29 AND transaction_date = '2026-06-22';


-- ──────────────────────────────────────────────────────────
-- STEP 7.  d_time_counter 복구 (aircraft_id=6, schedule_id=246)
-- ──────────────────────────────────────────────────────────
-- fn12 재계산으로 값이 바뀌었을 수 있음.
-- 시연 전 기준: current_hours=5237.2, due_hours=5237.5 → hours_remaining=+0.3 (임박)
-- ※ fn3(+0.5h) 입력 후 5237.7h > 5237.5h → 초과 전환 (B 시나리오)
UPDATE maintenance_schedule
SET due_hours = 5237.5
WHERE id = 246;

UPDATE d_time_counter
SET current_hours    = 5237.2,
    hours_remaining  = 5237.5 - 5237.2   -- = +0.3
WHERE aircraft_id = 6
  AND maintenance_schedule_id = 246;

-- 확인
SELECT aircraft_id, maintenance_schedule_id, current_hours, hours_remaining
FROM d_time_counter
WHERE aircraft_id = 6 AND maintenance_schedule_id = 246;


-- ──────────────────────────────────────────────────────────
-- STEP 8.  알람/알림 정리 (시연 중 fn14 생성분)
-- ──────────────────────────────────────────────────────────
-- 선택 사항: 날짜 기준으로 삭제 (시연과 무관한 알람은 보존)
DELETE FROM maintenance_alarms
WHERE aircraft_id = 6
  AND created_at::date = '2026-06-22';

DELETE FROM notification_logs
WHERE created_at::date = '2026-06-22';

-- 확인
SELECT COUNT(*) AS alarm_count FROM maintenance_alarms WHERE aircraft_id = 6;


-- ──────────────────────────────────────────────────────────
-- STEP 9.  inventory_history 정리 (출고 이력 row)
-- ──────────────────────────────────────────────────────────
-- inventory_history 테이블이 있는 경우:
-- (없으면 무시)
DELETE FROM inventory_history
WHERE part_id = 29
  AND created_at::date = '2026-06-22';


-- ──────────────────────────────────────────────────────────
-- 최종 확인: 원상복구 상태 점검
-- ──────────────────────────────────────────────────────────
SELECT '=== 최종 복구 상태 점검 ===' AS check_label;

SELECT
  'Fuel Filter 재고' AS item,
  quantity_on_hand::text AS value,
  CASE WHEN quantity_on_hand = 3 THEN '✓ OK' ELSE '✗ 재확인 필요' END AS status
FROM parts_inventory WHERE part_id = 29

UNION ALL

SELECT
  'HL1179 누적시간' AS item,
  total_flight_hours::text AS value,
  CASE WHEN total_flight_hours = 5237.2 THEN '✓ OK' ELSE '✗ 재확인 필요' END AS status
FROM aircraft WHERE id = 6

UNION ALL

SELECT
  'schedule-246 상태' AS item,
  status AS value,
  CASE WHEN status = 'scheduled' THEN '✓ OK' ELSE '✗ 재확인 필요' END AS status
FROM maintenance_schedule WHERE id = 246;
