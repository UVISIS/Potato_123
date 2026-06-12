# 🛠️ DB 담당 요청 — fn2 `get_component_status()` 작성 선행 조건

> **작성**: 백엔드(A담당) · **수신**: DB담당(B담당)  
> **갱신일**: 2026-06-11 (v2.0 — TBO 개념 상세 설명 추가)  
> **마감일**: 2026-06-17 저녁

---

## fn2 개요

- **함수명**: `get_component_status(aircraft_id)`
- **역할**: 기체 장착 부품의 **TBO 잔여시간** 조회
- **CSC/CSU**: CSC-01 / CSU-01-02
- **사용 테이블**: `aircraft_components`, `aircraft`
- **반환 데이터** (예정):
  ```json
  [{
    "component_name": "Austro AE300 Engine",
    "component_type": "engine",
    "installed_date": "2023-03-01",
    "tbo_hours": 1800,
    "remaining_tbo": 450,
    "status": "serviceable"
  }]
  ```
- **핵심 계산 공식**:
  ```
  remaining_tbo = (install_hours + tbo_hours) − aircraft.total_flight_hours
  ```

---

## 📚 TBO란 무엇인가? (DB가 알아야 할 것)

### **TBO = Time Between Overhaul (정기 오버홀 주기)**

항공기 부품은 제조사 정비 매뉴얼에서 **정해진 비행시간마다** 분해 점검 및 부품 교체를 해야 합니다.

#### **fn2 계산 로직**

```
예시 시나리오
───────────────────────────────────────────────────────

HL1252 비행기 (DA-40 NG)
├ 현재 누적 비행시간: 2000시간
│
└─ Austro AE300 엔진 (장착됨)
   ├ 장착 시점 비행시간: 800시간
   ├ TBO: 1800시간  ← DB에서 와야 할 정보
   │
   └ 계산:
      - 장착 후 비행시간: 2000 - 800 = 1200시간
      - 남은 TBO: 1800 - 1200 = 600시간
      
      반환: {
        component_name: "Austro AE300",
        remaining_tbo: 600,
        status: "serviceable"  ← 600시간 남았으니 정상
      }

───────────────────────────────────────────────────────

만약 TBO를 초과했다면?

HL1254 비행기 (같은 모델)
├ 현재 누적 비행시간: 2800시간
│
└─ Austro AE300 엔진
   ├ 장착 시점 비행시간: 500시간
   ├ TBO: 1800시간
   │
   └ 계산:
      - 장착 후 비행시간: 2800 - 500 = 2300시간
      - 남은 TBO: 1800 - 2300 = -500시간 ← 초과!
      
      반환: {
        component_name: "Austro AE300",
        remaining_tbo: -500,
        status: "overdue"  ← 500시간 초과! 즉시 정비 필요
      }
```

---

## ✅ 현황 정리

### ✅ 이미 해결된 항목

| 항목 | 상태 | 비고 |
|------|------|------|
| `aircraft_components.install_hours` | ✅ 완료 | 라이브 스키마에 이미 존재 |
| `components` 테이블 | ✅ 있음 | 252개 부품 마스터 데이터 |
| `maintenance_schedule` 테이블 | ✅ 있음 | 36개 정비 스케줄 데이터 |

### ⛔ 막고 있는 항목: TBO 정보 (1가지만!)

**문제**: `aircraft_components` 테이블에 **TBO 시간 정보가 없음**

```sql
-- 현재 aircraft_components 구조
CREATE TABLE aircraft_components (
  id bigint PRIMARY KEY,
  aircraft_id bigint,
  component_name text,
  component_type text,
  installed_date date,
  status text,
  install_hours numeric
  -- ❌ tbo_hours 컬럼 없음! # 이 부분이 필요한 상황
);
```

**결과**: fn2가 "부품이 언제마다 정비되어야 하는지" 알 수 없음 → 함수 작성 불가

---

## 🎯 B담당의 2가지 선택지

fn2 작성을 위해 TBO 정보 제공 방식을 선택해주세요.

### **선택지 ① (권장): DB 컬럼 신설**

#### 작업 내용

```sql
-- Step 1: 컬럼 추가
ALTER TABLE aircraft_components 
ADD COLUMN tbo_hours numeric;

-- Step 2: 데이터 입력 (DA-40 NG 예시)
UPDATE aircraft_components 
SET tbo_hours = 1800 
WHERE component_type = 'engine';

UPDATE aircraft_components 
SET tbo_hours = 2400 
WHERE component_type = 'propeller';

-- Step 3: NOT NULL 제약 추가 (선택)
ALTER TABLE aircraft_components 
ALTER COLUMN tbo_hours SET NOT NULL;
```

#### 실제 TBO 값 확인 필요

아래 파일들을 참고해 **정확한 TBO 값** 확정 필요:

| 파일 | 내용 |
|------|------|
| `DA40NG_주기검사_항목20260331.pdf` | DA-40 NG 공식 점검 항목 |
| `DA42NG_주기검사_항목_20260408.pdf` | DA-42 NG 공식 점검 항목 |
| `052000_Scheduled_Maintenance_Checks.pdf` | 일반 항공기 정비 기준 |

**확인할 항목**:
- Austro AE300 엔진 TBO → ? 시간
- MTV-6 프로펠러 TBO → ? 시간
- 배터리 TBO → ? 시간 또는 연도
- 기타 부품들 → 정의된 TBO?

#### 장점 ✅

- **정확성**: DB가 부품별 TBO 소유 → 항상 최신 정보
- **확장성**: 부품 추가 시 자동으로 tbo_hours 입력 가능
- **정석**: MRO 시스템의 일반적인 설계
- **유지보수 용이**: 나중에 부품별 TBO 변경 시 DB만 수정

#### 단점 ⚠️

- 정비 매뉴얼 검토해서 정확한 TBO 값 확인 필요 (소요: 1~2시간)
- 현재 aircraft_components 데이터 없으므로, 샘플 INSERT도 함께 필요

---

### **선택지 ② (임시): 백엔드 하드코딩**

#### 작업 내용

fn2.py 에서 TBO를 코드로 정의:

```python
# functions/csc01/fn2_get_component_status.py

TBO_HOURS_MAP = {
    'engine': 1800,           # Austro AE300
    'propeller': 2400,        # MTV-6
    'battery': 500,
    'alternator': 500,
    # ... 기타 부품들
}

def get_component_status(aircraft_id):
    components = db.get_components(aircraft_id)
    result = []
    
    for comp in components:
        # DB에 tbo_hours 없으니 맵에서 꺼내기
        tbo = TBO_HOURS_MAP.get(comp.component_type, None)
        
        if tbo is None:
            # TBO 미정의 부품 처리
            remaining_tbo = None
            status = "unknown"
        else:
            remaining_tbo = (comp.install_hours + tbo) - aircraft.total_flight_hours
            status = "overdue" if remaining_tbo < 0 else "serviceable"
        
        result.append({
            "component_name": comp.component_name,
            "component_type": comp.component_type,
            "tbo_hours": tbo,
            "remaining_tbo": remaining_tbo,
            "status": status
        })
    
    return result
```

#### 장점 ✅

- **즉시 작성 가능**: DB 조치 없이 지금 바로 fn2 구현 가능 (소요: 1~2시간)
- **빠른 완성**: 6월 17일 마감에 여유 있음

#### 단점 ⚠️

- **정확성 낮음**: TBO 값이 코드에 박혀있음 → 잘못된 값 발견 시 코드 수정 필수
- **유지보수 어려움**: 부품 추가 시마다 코드 수정 필요
- **확장성 제한**: 향후 부품별 맞춤 TBO 필요 시 리팩토링 필수
- **정식이 아님**: MRO 시스템 정석과 맞지 않음

---

## 📋 B담당 결정 요청

**다음 중 하나를 선택해주세요:**

```
【질문 1】TBO 정보 제공 방식 선택

  ① DB 컬럼 신설 (권장)
     - ALTER TABLE aircraft_components ADD COLUMN tbo_hours numeric;
     - 정비 매뉴얼 검토 후 정확한 TBO 값 입력
     - 소요 시간: 2~3시간
  
  ② 백엔드 코드 하드코딩 (임시)
     - TBO_HOURS_MAP을 Python 코드로 정의
     - DB 조치 없이 fn2 즉시 작성 가능
     - 소요 시간: 0시간 (백엔드에서 처리)

  선택: [  ]

【질문 2】선택지 ①을 택한 경우 → 정확한 TBO 값 제공

  정비 매뉴얼을 검토하고 다음을 확정해주세요:
  
  - Austro AE300 엔진 TBO: ?
  - MTV-6 프로펠러 TBO: ?
  - 배터리 TBO: ?
  - 기타 부품: ?
  
  참고 파일:
    • DA40NG_주기검사_항목20260331.pdf
    • DA42NG_주기검사_항목_20260408.pdf
    • 052000_Scheduled_Maintenance_Checks.pdf
```

## 📝 추가 참고

### 현재 스키마 (aircraft_components)

```sql
CREATE TABLE aircraft_components (
  id bigint PRIMARY KEY,
  aircraft_id bigint NOT NULL,
  component_name text NOT NULL,
  component_type text,
  installed_date date,
  status text DEFAULT 'serviceable',
  install_hours numeric  -- ✅ 이미 있음
  -- tbo_hours numeric  ← 추가 필요 (선택지 ①)
);
```

### fn2 관련 테이블 상태

| 테이블 | 행 수 | fn2 필요 여부 |
|--------|-------|-------------|
| aircraft | 2 | ✅ (total_flight_hours 조회) |
| aircraft_components | 0 | ✅ (부품 정보 조회) |
| components | 252 | ✗ (마스터, fn2 직접 사용 X) |

---

**작성자**: 백엔드(A담당)  
**최종 갱신**: 2026-06-11  
**상태**: 🔴 B담당의 결정 대기 중
