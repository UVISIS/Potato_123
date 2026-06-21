#!/usr/bin/env python3
"""
Potato_123 시연 스크립트 — 2026-06-22 (월) 발표
CSC-01 ~ CSC-05 순차 시연  |  서버: http://127.0.0.1:8000

실행 전 확인:
  1. cd C:\\Users\\cju\\Potato_123
  2. python -m uvicorn main:app --reload  (별도 터미널에서 실행 중이어야 함)
  3. python demo_scenario.py

주의:
  - fn3(비행시간 입력), fn5(출고), POST /maintenance/history 는 DB를 실제 변경함
  - 리허설 후 reset_demo_db.sql 실행하여 원상복구 필요
"""

import requests
import json
import sys
from datetime import date

BASE = "http://127.0.0.1:8000"
AIRCRAFT_ID = 6      # HL1179, Diamond DA40 NG, 누적 5237.2h
PART_ID     = 29     # Fuel Filter WK724-3, 현재고=3, 안전재고=3
DEMO_DATE   = date.today().isoformat()  # 오늘 날짜 자동 사용 (리허설·시연 공용)


# ─── 유틸 ──────────────────────────────────────────────────────────────────

def sep(title: str):
    print("\n" + "=" * 65)
    print(f"  {title}")
    print("=" * 65)

def pp(data, indent: int = 2):
    print(json.dumps(data, ensure_ascii=False, indent=indent))

def get(path: str, **params):
    url = f"{BASE}{path}"
    r = requests.get(url, params=params if params else None, timeout=60)
    if not r.ok:
        print(f"  [ERROR {r.status_code}] {r.text[:200]}")
        sys.exit(1)
    return r.json()

def post(path: str, body: dict):
    url = f"{BASE}{path}"
    r = requests.post(url, json=body, timeout=10)
    if not r.ok:
        print(f"  [ERROR {r.status_code}] {r.text[:200]}")
        sys.exit(1)
    return r.json()

print("=" * 65)
print("  Potato_123 — 2026-06-22 월요일 시연")
print("  대상 기체 : HL1179 (aircraft_id=6, DA40NG)")
print("  대상 부품 : Fuel Filter WK724-3 (part_id=29)")
print("=" * 65)


# ══════════════════════════════════════════════════════════════════════════════
# CSC-01  항공기 관리 (간단히)
# ══════════════════════════════════════════════════════════════════════════════

sep("CSC-01 ①  fn1 — 기체 정보 조회")
ac = get(f"/aircraft/{AIRCRAFT_ID}")
print(f"  등록번호 : {ac.get('registration')}")
print(f"  기종     : {ac.get('model')}")
print(f"  시리얼   : {ac.get('serial_number')}")
print(f"  상태     : {ac.get('status')}")
print(f"  누적비행 : {ac.get('total_flight_hours')}h")
current_hours = float(ac.get("total_flight_hours") or 5237.2)

sep("CSC-01 ②  fn3 — 비행시간 입력 (0.5h 추가)")
fn3 = post(f"/aircraft/{AIRCRAFT_ID}/flight-hours", {
    "flight_date": DEMO_DATE,
    "flight_hours": 0.5,
    "flight_minutes": 0,
    "pilot_name": "시연",
    "notes": "월요일 최종 시연용 비행"
})
print(f"  LOG ID       : {fn3.get('log_id')}")
print(f"  당일 비행시간 : {fn3.get('total_flight_hours')}h")
print(f"  전체 누적    : {fn3.get('total_accumulated_hours')}h")
current_hours = float(fn3.get("total_accumulated_hours") or current_hours + 0.5)


# ══════════════════════════════════════════════════════════════════════════════
# CSC-02  부품/자재 관리 (간단히)
# ══════════════════════════════════════════════════════════════════════════════

sep("CSC-02 ①  fn4 — 재고 조회 (Fuel Filter, part_id=29)")
# GET /inventory 는 전체 252건 반환 → 핵심 부품 단건 조회로 시연 집중
inv = get(f"/inventory/{PART_ID}")
comp = inv.get("components") or {}
rp   = inv.get("reorder_points") or {}
print(f"  부품명   : {comp.get('nomenclature')}")
print(f"  P/N      : {comp.get('part_number')}")
print(f"  현재고   : {inv.get('quantity_on_hand')}개")
print(f"  안전재고 : {rp.get('safety_stock')}개")
print(f"  → 출고 전: 안전재고 충족. 1개 출고 후 '부족' 전환 예정")
qty_before = int(inv.get("quantity_on_hand") or 3)

sep("CSC-02 ②  fn13 — BOM 조회 (100H 정비 / DA40NG)")
bom = get("/bom/100H", aircraft_model="DA40NG")
bom_items = bom if isinstance(bom, list) else bom.get("items", [])
total_eur  = sum((i.get("unit_price_eur") or 0) * (i.get("required_qty") or 0)
               for i in (bom_items if isinstance(bom_items, list) else []))
print(f"  100H 정비 BOM 부품 수 : {len(bom_items) if isinstance(bom_items, list) else '?'}개")
print(f"  예상 부품 원가 합계   : EUR {total_eur:,.2f}")
if isinstance(bom_items, list):
    for item in bom_items[:3]:
        print(f"    - {str(item.get('nomenclature','')):<30s} | P/N: {str(item.get('part_number','')):<15s} | {item.get('required_qty')}개")
    if len(bom_items) > 3:
        print(f"    ... 외 {len(bom_items) - 3}개")

sep("CSC-02 ③  fn5 — 출고 등록 (Fuel Filter 1개)")
tx = post("/transactions", {
    "part_id": PART_ID,
    "transaction_type": "출고",
    "quantity": 1,
    "transaction_date": DEMO_DATE,
    "aircraft_id": AIRCRAFT_ID,
    "handled_by": "시연",
    "notes": "시연용 출고"
})
qty_after_csc02 = int(tx.get("quantity_after") or qty_before - 1)
tx_id_csc02 = tx.get("transaction_id")
print(f"  거래 ID   : {tx_id_csc02}")
print(f"  출고 전   : {qty_before}개  →  출고 후: {qty_after_csc02}개")
print(f"  ★ 현재고({qty_after_csc02}) ≤ 안전재고({rp.get('safety_stock')}) → '부족' 전환 확인 예정 (fn7)")


# ══════════════════════════════════════════════════════════════════════════════
# CSC-03  발주 관리 (중점)
# ══════════════════════════════════════════════════════════════════════════════

sep("CSC-03 ①  fn7 — 안전재고 상태 분석 (출고 직후 확인)")
fn7 = get(f"/reorder-points/{PART_ID}/analysis")
print(f"  부품명    : {fn7.get('nomenclature')}")
print(f"  현재고    : {fn7.get('current_qty')}개")
print(f"  안전재고  : {fn7.get('safety_stock_qty')}개")
print(f"  ★ 상태   : [{fn7.get('status')}]  ← 출고 직후 즉시 반영")
if fn7.get("shortage_qty"):
    print(f"  부족 수량 : {fn7.get('shortage_qty')}개  → 발주 필요")

sep("CSC-03 ②  fn8 — EUR/KRW 환율 + Z-Score 구매시기 판단")
fn8 = get("/currency-rates")
rate   = fn8.get("exchange_rate") or {}
timing = fn8.get("purchase_timing") or {}
print(f"  현재 환율 : {rate.get('exchange_rate'):,}원/EUR" if isinstance(rate.get('exchange_rate'), (int,float)) else f"  현재 환율 : {rate.get('exchange_rate')}원/EUR")
print(f"  갱신일    : {rate.get('update_date')}")
print(f"  이동평균  : {timing.get('rolling_avg')}원  (60개월 기준)")
print(f"  표준편차  : {timing.get('std_dev')}")
print(f"  Z-Score   : {timing.get('z_score')}")
print(f"  ★ 구매권고: {timing.get('recommendation')}  — {timing.get('reason')}")
exchange_rate = float(rate.get("exchange_rate") or 1685)

sep("CSC-03 ③  fn6 — 발주 비용 산출 (Fuel Filter 5개)")
fn6 = post("/procurement/order-cost", {
    "part_id": PART_ID,
    "order_qty": 5,
    "exchange_rate": exchange_rate
})
unit_price_eur = float(fn6.get("unit_price_eur") or 50.0)
print(f"  단가(EUR) : {fn6.get('unit_price_eur')} EUR")
print(f"  발주 수량 : {fn6.get('order_qty')}개")
print(f"  EUR 총액  : {fn6.get('total_eur')} EUR")
krw = fn6.get('total_krw')
print(f"  KRW 환산  : {krw:,.0f}원" if isinstance(krw, (int, float)) else f"  KRW 환산  : {krw}원")
print(f"  적용 환율 : {fn6.get('exchange_rate')}원")

sep("CSC-03 ④  fn17 — 수입 총원가 (관세·운임·부가세 포함 / 학술감면 적용)")
# 관세법 제90조: 학술연구용품 관세 80% 감면
fn17 = post("/procurement/landed-cost", {
    "unit_price_eur": unit_price_eur,
    "order_qty": 5,
    "exchange_rate": exchange_rate,
    "customs_duty_rate": 0.08,      # 기본 관세율 8%
    "is_academic": True,             # 학술연구용품 감면 적용 → 실효 1.6%
    "vat_rate": 0.10,
    "freight_total_eur": 30.0,       # 항공운임
    "agent_markup_rate": 0.05        # 기존 대행 수수료 5% (절감 비교용)
})
pp(fn17)

sep("CSC-03 ⑤  fn18 — 비행시간 기반 구매시기 예측 (연 725h, 1년 내)")
fn18 = get(
    f"/procurement/forecast/{AIRCRAFT_ID}",
    annual_flight_hours=725.0,
    horizon_days=365,
    default_lead_time_days=30
)
# fn18 응답 구조는 list 또는 dict(items 키)
items18 = fn18 if isinstance(fn18, list) else fn18.get("items", fn18)
if isinstance(items18, list) and items18:
    print(f"  {'정비유형':<22s} {'도래 예상일':<15s} {'발주 시작일':<15s} {'리드타임'}")
    for f in items18[:8]:
        print(f"  {str(f.get('maintenance_type','')):<22s} "
              f"{str(f.get('due_date','')):<15s} "
              f"{str(f.get('order_by_date','')):<15s} "
              f"{f.get('lead_time_days','')}일")
    if len(items18) > 8:
        print(f"  ... 외 {len(items18) - 8}건")
else:
    pp(fn18)


# ══════════════════════════════════════════════════════════════════════════════
# CSC-04  주기정비 관리 (중점)
# ══════════════════════════════════════════════════════════════════════════════

sep("CSC-04 ①  fn11 — 정비 도래 현황 (HL1179 전체 스케줄)")
fn11 = get(f"/maintenance/next/{AIRCRAFT_ID}")
items11 = fn11 if isinstance(fn11, list) else []
print(f"  현재 누적시간: {current_hours:.1f}h")
print()
print(f"  {'상태':<14s} {'정비유형':<28s} {'도래기준':<12s} {'잔여시간':>10s}")
print(f"  {'-'*14} {'-'*28} {'-'*12} {'-'*10}")
for item in items11:
    rem = item.get("remaining_hours")
    rem_str = f"{rem:+.1f}h" if isinstance(rem, (int, float)) else "날짜기반"
    due = item.get("due_hours")
    due_str = f"{due:.1f}h" if due else "-"
    st = item.get("status", "")
    star = "★" if "초과" in st or "임박" in st else " "
    print(f"  {star}[{st:<12s}] {str(item.get('maintenance_type','')):<28s} {due_str:<12s} {rem_str:>10s}")

print()
print("  ★ [초과]  : 정비 한계 초과 — 즉시 조치 필요 (실사례)")
print("  ★ [임박]  : 10h 이내 도래 — 사전 준비 진행 중")
print("    [주의]  : 30h 이내 도래 — 부품 선발주 검토")

sep("CSC-04 ②  fn9 — 100H 정비 필요 부품 목록")
fn9 = get(f"/maintenance/required-parts/{AIRCRAFT_ID}", maintenance_type="100H")
items9 = fn9 if isinstance(fn9, list) else []
print(f"  필요 부품 {len(items9)}개:")
print(f"  {'부품명':<32s} {'P/N':<18s} {'소요':>4s}  {'단가(EUR)':>10s}")
print(f"  {'-'*32} {'-'*18} {'-'*4}  {'-'*10}")
for item in items9:
    price = item.get("unit_price_eur")
    price_str = f"{price:>10.2f}" if isinstance(price, (int, float)) else f"{'미등록':>10s}"
    print(f"  {str(item.get('nomenclature','')):<32s} "
          f"{str(item.get('part_number','')):<18s} "
          f"{item.get('required_qty',0):>4d}  "
          f"{price_str}")

# ── fn10 알림 ─────────────────────────────────────────────────────────────────
print()
print("  [fn10 참고]")
print("  GET /maintenance/parts-check/{aircraft_id}?maintenance_type=...")
print("  → 라우터 내 fn10_check(aircraft_id, maintenance_type) 인자 순서 불일치 버그")
print("    수정 후 정상 동작. 현 시점에서는 fn9 결과 + fn4 재고를 조합해 확인.")

sep("CSC-04 ③  POST /maintenance/history — 핵심 협업 연쇄 시연")
print("  정비 이력 등록 1회 POST → 백엔드 자동 연쇄:")
print("    Step 1 : maintenance_history INSERT")
print("    Step 2 : fn5 — 교체 부품 출고 (parts_transactions + inventory 차감)")
print("    Step 3 : maintenance_schedule status → 'completed'")
print("    Step 4 : fn12 — D-Time 카운터 재계산")
print()

history_body = {
    "aircraft_id": AIRCRAFT_ID,
    "maintenance_date": DEMO_DATE,
    "maintenance_type": "항공기 100 HRS",      # maintenance_schedule 의 maintenance_type 과 일치
    "hours_at_maintenance": current_hours,
    "handled_by": "김재림",
    "destination": "청주",
    "parts_used": [
        {"part_id": PART_ID, "quantity": 1}    # Fuel Filter 1개 교체 출고
    ],
    "notes": "시연용 100H 정비 완료 (초과 정비 처리)"
}
hist = post("/maintenance/history", history_body)
history_id = hist.get("history_id")
print(f"  ✓ history_id  : {history_id}")
issued = hist.get("parts_issued") or []
for p in issued:
    print(f"  ✓ 부품 출고   : part_id={p.get('part_id')}  "
          f"수량={p.get('quantity')}개  잔여={p.get('quantity_after')}개  "
          f"(tx_id={p.get('transaction_id')})")
d_updated = hist.get("d_time_updated") or []
print(f"  ✓ D-Time 갱신 : schedule_id={d_updated}")
if hist.get("warnings"):
    for w in hist["warnings"]:
        print(f"  ⚠ {w}")

# 연쇄 결과 확인 — schedule id=246 상태 변경 검증
scheds_after = get("/maintenance/schedule", aircraft_id=AIRCRAFT_ID)
sched_246 = next((s for s in (scheds_after if isinstance(scheds_after, list) else [])
                  if s.get("id") == 246), None)
if sched_246:
    print(f"\n  검증: maintenance_schedule id=246 → status='{sched_246.get('status')}' ✓")

sep("CSC-04 ④  fn14 — 정비/재고 알람 생성")
fn14 = post("/maintenance/alerts", {
    "aircraft_id": AIRCRAFT_ID,
    "alarm_type": "maintenance_overdue",
    "severity": "critical",
    "message": "항공기 100 HRS 정비 초과 알람",
    "user_id": "demo_user"
})
pp(fn14)


# ══════════════════════════════════════════════════════════════════════════════
# CSC-05  대시보드 (마무리)
# ══════════════════════════════════════════════════════════════════════════════

sep("CSC-05  fn15 — 대시보드 지표 (12개 지표 일괄 조회)")
metrics = get("/metrics")
pp(metrics)


# ══════════════════════════════════════════════════════════════════════════════
# 완료
# ══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 65)
print("  ★ CSC-01 ~ CSC-05 시연 완료 ★")
print("=" * 65)
print(f"  DB 변경 요약:")
print(f"    aircraft_id=6  total_flight_hours +0.5h")
print(f"    part_id=29     출고 2개 (CSC-02 fn5 + 정비이력 fn5)")
print(f"    maintenance_schedule id=246  →  status='completed'")
print(f"    maintenance_history id={history_id}  생성됨")
print()
print("  ☞ 리허설 반복 시 reset_demo_db.sql 을 실행하여 DB 원상복구")
print("=" * 65)
