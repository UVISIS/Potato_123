-- ============================================================
-- rollback_from_checkpoint.sql
-- free_demo.py 로 자유 시연하며 변경된 DB를 한 번에 원상복구
-- Supabase project: uwegumjzzdmxsyynqvoa (ap-northeast-2)
--
-- 원리: audit_log 테이블은 INSERT/UPDATE/DELETE 가 일어날 때마다
--       트리거로 "되돌리는 SQL"(rollback_sql)을 자동 저장합니다.
--       체크포인트(시연 시작 시점) 이후 발생한 변경분만 최신순(id DESC)으로
--       역재생하면, 어떤 기체/부품을 건드렸든 상관없이 전부 원상복구됩니다.
--
-- 체크포인트: id = 831  (2026-06-21 기준 — 실행 전 STEP 0 으로 최신값 확인 권장)
-- ============================================================

-- ──────────────────────────────────────────────────────────
-- STEP 0.  (선택) 실행 전 체크포인트 재확인
-- ──────────────────────────────────────────────────────────
-- free_demo.py 실행 직전에 아래를 한 번 더 돌려서 831 대신 최신 id를 써도 됩니다.
-- SELECT max(id) AS checkpoint_id FROM audit_log;  -- 시연 시작 "직전"에 실행

-- 되돌릴 대상 미리보기 (실행 전 확인용 — DB 변경 없음)
SELECT id, table_name, operation, changed_at
FROM audit_log
WHERE id > 831 AND (rolled_back IS NOT TRUE)
ORDER BY id DESC;


-- ──────────────────────────────────────────────────────────
-- STEP 1.  체크포인트 이후 변경분을 최신순으로 일괄 롤백
-- ──────────────────────────────────────────────────────────
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN
        SELECT id, rollback_sql
        FROM audit_log
        WHERE id > 831 AND (rolled_back IS NOT TRUE)
        ORDER BY id DESC
    LOOP
        EXECUTE r.rollback_sql;
        UPDATE audit_log SET rolled_back = TRUE, rolled_back_at = now() WHERE id = r.id;
    END LOOP;
END $$;


-- ──────────────────────────────────────────────────────────
-- STEP 2.  복구 확인
-- ──────────────────────────────────────────────────────────
SELECT id, table_name, operation, rolled_back, rolled_back_at
FROM audit_log
WHERE id > 831
ORDER BY id DESC;

-- 위 결과의 rolled_back 이 전부 true 면 정상 복구된 것입니다.


-- ──────────────────────────────────────────────────────────
-- 참고: 기존 reset_demo_db.sql 과의 관계
-- ──────────────────────────────────────────────────────────
-- reset_demo_db.sql 은 "HL1179(aircraft_id=6) 고정 시나리오" 전용 리셋입니다.
-- free_demo.py 로 다른 기체(1~9번 등)도 자유롭게 건드렸다면,
-- 이 파일(rollback_from_checkpoint.sql)이 기체에 상관없이 전부 되돌려주므로
-- 자유시연 이후에는 이 파일을 먼저 실행하고, 그래도 HL1179 베이스라인이
-- 안 맞으면 reset_demo_db.sql을 추가로 실행하세요.
