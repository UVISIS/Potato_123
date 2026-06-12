# DB 수정 요청서 — component_aircraft 매핑 테이블 신설

- 작성: 박세은 (백엔드 A담당)
- 작성일: 2026-06-12
- 우선순위: **P1 (월요일 통합테스트 전 필수)**
- 배경: 공용 부품 처리 방식을 `components.aircraft_id` 단일 컬럼 → **매핑 테이블(N:M)** 방식으로 팀 확정

---

## 1. 변경 이유

기존 방식(`components.aircraft_id`, NULL=공용)은 **한 부품이 복수 기체에 적용되는 케이스를 표현할 수 없음**.
예: 어떤 필터가 DA-40NG 전용도, 전 기체 공용도 아닌 "DA-40NG + DA-42NG 두 기종에만 적용"인 경우.
매핑 테이블로 전환하면 부품↔기체 N:M 관계를 정확히 표현 가능.

## 2. 적용 규칙 (백엔드 fn4에 이미 구현 완료)

| 매핑 상태 | 의미 |
|----------|------|
| 매핑 행 0개 | **전 기체 공용** (모든 기체 조회에 포함) |
| 매핑 행 1개 이상 | **매핑된 기체에서만** 조회에 포함 |

> 신규 기체 추가 시 공용 부품은 자동으로 적용되므로 별도 행 추가 불필요.

## 3. 실행 SQL (순서대로)

### ① 테이블 생성

```sql
CREATE TABLE component_aircraft (
    id            bigserial PRIMARY KEY,
    component_id  bigint NOT NULL REFERENCES components(id) ON DELETE CASCADE,
    aircraft_id   bigint NOT NULL REFERENCES aircraft(id)   ON DELETE CASCADE,
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (component_id, aircraft_id)
);

CREATE INDEX idx_component_aircraft_component ON component_aircraft (component_id);
CREATE INDEX idx_component_aircraft_aircraft  ON component_aircraft (aircraft_id);
```

### ② 기존 데이터 이관 (aircraft_id가 지정된 부품만)

```sql
INSERT INTO component_aircraft (component_id, aircraft_id)
SELECT id, aircraft_id
FROM components
WHERE aircraft_id IS NOT NULL
ON CONFLICT (component_id, aircraft_id) DO NOTHING;
```

### ③ 이관 검증

```sql
-- 두 수치가 일치해야 함
SELECT count(*) AS src FROM components WHERE aircraft_id IS NOT NULL;
SELECT count(*) AS dst FROM component_aircraft;
```

### ④ 기존 컬럼 폐기 (③ 검증 후 실행 — 통합테스트 통과 전까지 보류 권장)

```sql
ALTER TABLE components DROP COLUMN aircraft_id;
```

> ④는 월요일 통합테스트가 끝난 뒤 실행해도 무방. 백엔드 코드는 이미 해당 컬럼을 참조하지 않음.

### ⑤ RLS

신규 테이블이므로 6/15 RLS 정책 적용 대상에 `component_aircraft` 추가 필요 (총 5개 테이블).

## 4. 영향 범위

| 항목 | 내용 | 상태 |
|------|------|------|
| 백엔드 fn4 `get_inventory()` | 매핑 테이블 조회 방식으로 수정 | ✅ 완료 (v1.1, 테스트 8개 통과) |
| 기타 함수 (fn1~15) | `components.aircraft_id` 미사용 — 영향 없음 | ✅ 확인 완료 |
| API 라우터 | 함수 시그니처 변경 없음 — 영향 없음 | ✅ |
| 프론트엔드 | 응답 형식 동일 — 영향 없음. 단, "신규 부품 등록" 팝업의 적용기종 입력을 다중 선택(체크박스)으로 변경 권장 | C담당 전달 필요 |
