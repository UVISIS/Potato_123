# [DB 작업 요청] parts_inventory 단일 중앙창고 단일화

**작성:** 백엔드(A담당) · 2026-06-13
**대상:** B담당(DB)
**선행 작업:** 백엔드 fn5 디커플링 **완료됨** → 이 문서대로 DB 단일화하면 정상 동작

---

## 1. 배경 (모델 변경)

기존: 부품 재고를 **청주/무안 기지별로 분리** 보관
변경: **중앙 창고 1개**에서 보관하고, 출고 시 **어느 비행교육원으로 가는지(목적지)만 기록**

---

## 2. 백엔드 변경 내용 (완료) — fn5 `record_transaction()`

`location` 한 파라미터가 ① 재고 행 선택 + ② 거래 기록을 겸하던 것을 **분리**했습니다.

| 구분 | 변경 전 | 변경 후 (현재) |
|------|---------|----------------|
| 재고 차감 대상 | `parts_inventory` 에서 `location` 일치 행 | **부품당 중앙 단일행** (location 필터 없음) |
| 출고 목적지 | `location` (재고기지와 혼용) | **`destination`** 파라미터 → `parts_transactions.location` 에 기록 |
| `location` 파라미터 | 재고기지 | `destination` 하위호환 별칭 (유지) |

**fn5 의 새 전제:** **부품(part_id)당 `parts_inventory` 행은 정확히 1개**여야 함.
2개 이상이면 `ValueError`("…단일화 필요…") 발생 → 아래 단일화 작업이 필요한 이유.

> `parts_transactions.location` / `inventory_history.location` 컬럼은 **그대로 사용**(스키마 변경 없음).
> 의미만 "목적지 비행교육원(청주/무안)"으로 바뀝니다. 입고/조정은 보통 NULL.

---

## 3. B담당 작업 — `parts_inventory` 단일화

### 3-1. 현황: 단일화 대상 11개 부품 (청주+무안 → 1행 합산)

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

나머지 8개 부품은 이미 단일행 → 합산 작업 불필요(location만 NULL로 표준화).

### 3-2. 마이그레이션 SQL (검토 후 실행) — `parts_inventory_consolidate.sql`

별도 첨부한 `parts_inventory_consolidate.sql` 참조. 요약:

1. 각 part_id 합산 수량을 **대표행(최소 id)** 에 반영 + `location = NULL`
2. 대표행이 아닌 **중복행 삭제**

> ⚠️ **실행 전 백업/스냅샷 권장.** audit_log 트리거가 있으면 변경 64건+ 기록됩니다.
> 운영 DB라 B담당이 직접 검토 후 실행해주세요 (백엔드에서 임의 실행하지 않았습니다).

### 3-3. 확인 사항 (data quality)

- part_id **29 / 35** 가 동일 part_number(`WK724-3`), **31 / 37** 가 동일(`LN94-40060`)입니다.
  → 동일 부품이 component 행으로 중복 등록된 것인지 확인 필요.
  본 단일화는 **part_id 기준**으로만 합칩니다(서로 다른 part_id는 합치지 않음).
  실제 같은 부품이면 component 통합 여부는 별도 협의.

---

## 4. 검증 체크리스트 (단일화 후)

```sql
-- (1) 모든 부품이 1행인지 — 0행이어야 정상
SELECT part_id, COUNT(*) FROM parts_inventory GROUP BY part_id HAVING COUNT(*) > 1;

-- (2) 합산 수량 보존 확인 (예: part_id=32 → 30)
SELECT part_id, quantity_on_hand, location FROM parts_inventory WHERE part_id IN (29,31,32,33,35,37,48,50,52,54,56) ORDER BY part_id;
```

- [ ] 위 (1) 결과 0행
- [ ] (2) 합산 수량이 표 3-1과 일치
- [ ] location 전부 NULL (중앙창고)
- [ ] 백엔드 출고 테스트: `POST /transactions {transaction_type:"출고", destination:"무안"}` → 정상 차감 + `parts_transactions.location="무안"` 기록 확인

---

## 5. 프론트(C담당) 영향 (참고)

- 출고/정비 등록 화면: 기지(재고 위치) 선택 → **목적지 비행교육원(청주/무안)** 선택으로 의미 변경
- API 필드: `destination` (또는 하위호환 `location`)에 목적지 전달
