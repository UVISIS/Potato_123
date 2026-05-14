# Team: Potato_123
# 항공방산후속지원SW설계_프로젝트

# 비행교육원 가동률 극대화를 위한 항공 정비 자재 최적 구매 설정 시스템
---
## 프로젝트 소개
비행교육원의 가동률 극대화를 위한 항공 정비 자재 관리 및 최적 구매 설정 시스템입니다.
기종 2대의 비행시간 및 정비 주기를 관리하고 재고 부족 및 정비 임박 시 자동으로 알람보드를 통해 인지할 수 있도록 합니다.

---
<br>
<br>

## 👥 팀원 및 역할
| 이름 | 역할 | 담당 업무 |
|-----|-----|---------|
| 김재림 | DB | 하이라키 설계 및 구축, 시스템 데이터 연동, 데이터 정합성 관리 등 |
| 박세은 | 백엔드 | 정비 주기 자동 계산 로직, 알림 자동 생성 로직 등  |
| 박소진 | 프론트엔드 | UI/UX 설계 (와이어프레임 → 디자인), 백엔드/DB API 연동 등 |

---
<br>
<br>

## 🛠️ 기술 스택
| 구분 | 활용 언어 |
|------|------|
| Frontend | ![JavaScript](https://img.shields.io/badge/javascript-%23323330.svg?style=for-the-badge&logo=javascript&logoColor=%23F7DF1E) |
| Backend | ![Python](https://img.shields.io/badge/python-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54) |
| Database | ![Python](https://img.shields.io/badge/python-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54) |
| 협업 도구 | ![Git](https://img.shields.io/badge/git-%23F05033.svg?style=for-the-badge&logo=git&logoColor=white) ![GitHub](https://img.shields.io/badge/github-%23121011.svg?style=for-the-badge&logo=github&logoColor=white) |

---
<br>
<br>

## 📱 주요 기능
| 기능 | 설명 |
|------|------|
| 메인 대시보드 | 재고현황 / 주기정비 및 비행시간 / 알림보드 |
| 재고 현황 | 전체 부품 재고 조회 및 상태 확인 |
| 부품 추가 및 삭제 | 신규 부품 추가 및 기존 부품 목록 삭제 |
| 재고 입출고 | 부품 입고 / 출고 처리 및 이력 관리 |
| 기체 관리 | 기종 2대 비행시간 및 정비 주기 확인 |
| 비행시간 입력 | 비행 후 시간 기록 및 정비주기 자동 계산 |
| 알림보드 | 재고 부족 / 정비 임박 자동 알림 생성 |

---
<br>
<br>

# CSCI 기능 구조도

## 전체 구조 테이블

| 컴포넌트 | 서브유닛 | 기능 설명 |
|---|---|---|
| **CSC-01** 운영 관리 | CSU-01-01 | 항공기 관리 |
| | CSU-01-02 | 정비 관리 |
| | CSU-01-03 | 부품/자재 관리 |
| **CSC-02** 스마트 발주 스케줄러 ⭐ | CSU-02-01 | 안전재고 분석 |
| | CSU-02-02 | 환율 분석 & 최적시점 |
| | CSU-02-03 | 장기납기 역산 |
| | CSU-02-04 | 발주 추천 |
| **CSC-03** 주기정비 카운터 ⭐ | CSU-03-01 | 검사 도래시점 판단 |
| | CSU-03-02 | D-Time 카운팅 |
| | CSU-03-03 | BOM & 재고 관리 |
| **CSC-04** MRO 리스크 관리 ⭐ | CSU-04-01 | 지연감지 & 판별 |
| | CSU-04-02 | 52주 리스크 알고리즘 |
| | CSU-04-03 | 알림 & 리포트 |
| **CSC-05** 대시보드 & 모니터링 | CSU-05-01 | 메인 대시보드 |
| | CSU-05-02 | 차트 & 시각화 |
| | CSU-05-03 | 실시간 알림 |
| **CSC-06** 기술 인프라 | CSU-06-01 | REST API |
| | CSU-06-02 | 인증 & 보안 |
| | CSU-06-03 | 데이터베이스 (Supabase) |
| | CSU-06-04 | 검색 엔진 |

---
<br>
<br>

## 계층 구조 다이어그램

```mermaid
graph LR
    ROOT["🛩️ CSCI 시스템"]

    ROOT --> CSC01["📋 CSC-01\n운영 관리"]
    ROOT --> CSC02["⭐ CSC-02\n스마트 발주 스케줄러"]
    ROOT --> CSC03["⭐ CSC-03\n주기정비 카운터"]
    ROOT --> CSC04["⭐ CSC-04\nMRO 리스크 관리"]
    ROOT --> CSC05["📊 CSC-05\n대시보드 & 모니터링"]
    ROOT --> CSC06["🔧 CSC-06\n기술 인프라"]

    CSC01 --> U0101["CSU-01-01\n항공기 관리"]
    CSC01 --> U0102["CSU-01-02\n정비 관리"]
    CSC01 --> U0103["CSU-01-03\n부품/자재 관리"]

    CSC02 --> U0201["CSU-02-01\n안전재고 분석"]
    CSC02 --> U0202["CSU-02-02\n환율 분석 & 최적시점"]
    CSC02 --> U0203["CSU-02-03\n장기납기 역산"]
    CSC02 --> U0204["CSU-02-04\n발주 추천"]

    CSC03 --> U0301["CSU-03-01\n검사 도래시점 판단"]
    CSC03 --> U0302["CSU-03-02\nD-Time 카운팅"]
    CSC03 --> U0303["CSU-03-03\nBOM & 재고 관리"]

    CSC04 --> U0401["CSU-04-01\n지연감지 & 판별"]
    CSC04 --> U0402["CSU-04-02\n52주 리스크 알고리즘"]
    CSC04 --> U0403["CSU-04-03\n알림 & 리포트"]

    CSC05 --> U0501["CSU-05-01\n메인 대시보드"]
    CSC05 --> U0502["CSU-05-02\n차트 & 시각화"]
    CSC05 --> U0503["CSU-05-03\n실시간 알림"]

    CSC06 --> U0601["CSU-06-01\nREST API"]
    CSC06 --> U0602["CSU-06-02\n인증 & 보안"]
    CSC06 --> U0603["CSU-06-03\n데이터베이스 (Supabase)"]
    CSC06 --> U0604["CSU-06-04\n검색 엔진"]

    %% 스타일 정의
    style ROOT fill:#1a2744,color:#ffffff,stroke:#1a2744
    style CSC02 fill:#2563eb,color:#ffffff,stroke:#1d4ed8
    style CSC03 fill:#2563eb,color:#ffffff,stroke:#1d4ed8
    style CSC04 fill:#2563eb,color:#ffffff,stroke:#1d4ed8
    style CSC01 fill:#4b5563,color:#ffffff,stroke:#374151
    style CSC05 fill:#4b5563,color:#ffffff,stroke:#374151
    style CSC06 fill:#4b5563,color:#ffffff,stroke:#374151
```

---

## 모듈별 카드 요약

### 🔵 핵심 비즈니스 모듈 (⭐ 표시)

| | CSC-02 스마트 발주 스케줄러 | CSC-03 주기정비 카운터 | CSC-04 MRO 리스크 관리 |
|---|---|---|---|
| **핵심 기능** | 최적 발주 시점 자동 추천 | 정비 도래 시점 자동 계산 | 납기 지연 리스크 사전 감지 |
| **서브유닛 수** | 4개 | 3개 | 3개 |
| **주요 알고리즘** | 환율 분석, 납기 역산 | D-Time 카운팅 | 52주 리스크 알고리즘 |

### 🟢 운영 지원 모듈

| | CSC-01 운영 관리 | CSC-05 대시보드 | CSC-06 기술 인프라 |
|---|---|---|---|
| **핵심 기능** | 항공기·정비·부품 기초 관리 | 통합 현황 시각화 | API·DB·보안 기반 제공 |
| **서브유닛 수** | 3개 | 3개 | 4개 |
| **특이사항** | 마스터 데이터 관리 | 실시간 알림 포함 | Supabase + 검색엔진 |


...

<img width="461" height="850" alt="image" src="https://github.com/user-attachments/assets/7258ca3a-196e-4011-b38c-f028b406376d" />

...
