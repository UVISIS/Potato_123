-- =====================================================================
-- parts_inventory 단일 중앙창고 단일화
-- 작성: 백엔드(A담당) 2026-06-13 / 실행: B담당 검토 후
-- 목적: 부품(part_id)당 재고 행을 1개로 합산(청주+무안), location=NULL(중앙창고)
-- ⚠️ 운영 DB. 실행 전 백업/스냅샷 권장. 트랜잭션으로 감싸 검증 후 COMMIT.
-- =====================================================================

BEGIN;

-- 1) 각 part_id 합산 수량을 대표행(최소 id)에 반영 + location = NULL
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

-- 3) 검증: 아래가 0행이면 정상 (커밋 전 확인)
--    SELECT part_id, COUNT(*) FROM parts_inventory GROUP BY part_id HAVING COUNT(*) > 1;

COMMIT;

-- 롤백이 필요하면 COMMIT 대신 ROLLBACK;
