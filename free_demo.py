#!/usr/bin/env python3
"""
Potato_123 — 자유 선택 시연 도구 (free_demo.py)

demo_scenario.py 가 HL1179(aircraft_id=6) 1대로 고정된 시나리오였다면,
이 스크립트는 그 자리에서 "1번 기체 3시간 비행", "5번 기체 200시간 주기정비" 처럼
기체와 정비유형을 자유롭게 골라가며 보여줄 수 있는 메뉴 방식 도구입니다.

실행 전 확인:
  1. cd C:\\Users\\cju\\Potato_123
  2. python -m uvicorn main:app --reload  (별도 터미널)
  3. python free_demo.py

DB 변경 / 원상복구:
  - "비행시간 입력", "정비이력 등록"만 DB를 변경합니다 (조회 메뉴는 100% 안전).
  - 시연 시작 시점 audit_log 체크포인트: id = 831
  - 끝난 뒤 원상복구는 rollback_from_checkpoint.sql 사용 (Supabase SQL Editor 또는 MCP).
"""

import sys
from datetime import date

import requests

BASE = "http://127.0.0.1:8000"

# constants.py 와 동일한 정비유형 정규화 — BOM이 실제로 연결된 유형만 "✓BOM"으로 표시하기 위함
MAINTENANCE_TYPE_BOM_MAP = {
    "항공기 100 HRS": "100H",
    "항공기 200 HRS": "200H",
    "ENG' 100 HRS":  "Engine_100H",
    "ENG' 300 HRS":  "Engine_300H",
}
BOM_BACKED_TYPES = set(MAINTENANCE_TYPE_BOM_MAP.values()) | {
    "500H", "Annual", "Engine_200H", "TRP_100H",
    "Governor(2400시간&72개월)", "Propeller(2600시간&72개월)",
}


def normalize_mt(mt: str) -> str:
    return MAINTENANCE_TYPE_BOM_MAP.get(mt, mt)


# ── HTTP 유틸 ────────────────────────────────────────────────────────────

def get(path: str, **params):
    try:
        r = requests.get(f"{BASE}{path}", params=params or None, timeout=10)
    except requests.exceptions.ConnectionError:
        print("  [연결 실패] 서버가 켜져 있는지 확인하세요 (uvicorn main:app --reload)")
        return None
    if not r.ok:
        print(f"  [ERROR {r.status_code}] {r.text[:300]}")
        return None
    return r.json()


def post(path: str, body: dict):
    try:
        r = requests.post(f"{BASE}{path}", json=body, timeout=10)
    except requests.exceptions.ConnectionError:
        print("  [연결 실패] 서버가 켜져 있는지 확인하세요 (uvicorn main:app --reload)")
        return None
    if not r.ok:
        print(f"  [ERROR {r.status_code}] {r.text[:300]}")
        return None
    return r.json()


def pp(data, indent=2):
    import json
    print(json.dumps(data, ensure_ascii=False, indent=indent))


def pick(options: list[dict], prompt: str):
    """번호로 항목 선택. 'q' 입력 시 None 반환."""
    for i, o in enumerate(options, 1):
        print(f"  {i}) {o['label']}")
    while True:
        raw = input(f"{prompt} (번호 입력, q=취소) > ").strip()
        if raw.lower() in ("q", "quit", "exit"):
            return None
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        print("  잘못된 입력입니다.")


# ── 기체 선택 ────────────────────────────────────────────────────────────

def choose_aircraft():
    aircraft = get("/aircraft")
    if not aircraft:
        return None
    options = [
        {"label": f"{a['registration']} ({a['model']}, 누적 {a['total_flight_hours']}h)", "id": a["id"]}
        for a in sorted(aircraft, key=lambda x: x["id"])
    ]
    chosen = pick(options, "기체 선택")
    return chosen["id"] if chosen else None


def show_aircraft_summary(aircraft_id: int):
    ac = get(f"/aircraft/{aircraft_id}")
    if ac:
        print(f"\n  ▶ {ac.get('registration')}  |  {ac.get('model')}  |  누적비행 {ac.get('total_flight_hours')}h\n")
    return ac


# ── 정비 스케줄 목록 (BOM 연결 여부 표시) ──────────────────────────────────

def list_schedules(aircraft_id: int):
    scheds = get(f"/maintenance/next/{aircraft_id}") or []
    options = []
    for s in scheds:
        mt = s.get("maintenance_type", "")
        tag = "✓BOM" if normalize_mt(mt) in BOM_BACKED_TYPES else "   -"
        rem = s.get("remaining_hours")
        rem_str = f"{rem:+.1f}h" if isinstance(rem, (int, float)) else "날짜기반"
        st = s.get("status", "")
        options.append({
            "label": f"[{tag}] {mt:<28s} 상태:{st:<8s} 잔여:{rem_str}",
            "maintenance_type": mt,
        })
    return options


# ── 메뉴 ① 조회 (완전 읽기전용, 안전) ──────────────────────────────────────

def action_inquiry(aircraft_id: int):
    print("\n  -- 부품 재고 빠른 조회 --")
    pid = input("  조회할 part_id (모르면 엔터로 건너뛰기): ").strip()
    if pid.isdigit():
        pp(get(f"/inventory/{pid}"))

    scheds = list_schedules(aircraft_id)
    if not scheds:
        print("  이 기체엔 정비 스케줄이 없습니다.")
        return
    chosen = pick(scheds, "정비유형 선택 (✓BOM = 부품 데이터 있음)")
    if not chosen:
        return
    mt = chosen["maintenance_type"]

    print("\n  -- 정비 도래현황(fn11) 중 해당 항목 --")
    for s in (get(f"/maintenance/next/{aircraft_id}") or []):
        if s.get("maintenance_type") == mt:
            pp(s)

    print("\n  -- 필요부품(fn9) --")
    pp(get(f"/maintenance/required-parts/{aircraft_id}", maintenance_type=mt))

    print("\n  -- 부품 가용성 판정(fn10) --")
    pp(get(f"/maintenance/parts-check/{aircraft_id}", maintenance_type=mt))

    pass


# ── 메뉴 ② 구매시기 예측 (fn18, 읽기전용) ──────────────────────────────────

def action_forecast(aircraft_id: int):
    print("\n  -- 비행시간 기반 구매시기 예측 (fn18) --")
    ac = get(f"/aircraft/{aircraft_id}")
    if not ac:
        return

    total_hours = float(ac.get("total_flight_hours") or ac.get("accumulated_hours") or 0)
    manufacture_year = ac.get("manufacture_year")
    current_year = date.today().year

    if manufacture_year and current_year > int(manufacture_year):
        years = current_year - int(manufacture_year)
        annual = round(total_hours / years, 1)
        print(f"  ▶ 연간 비행시간 자동 계산: {total_hours}h ÷ {years}년 ({manufacture_year}~{current_year}) = {annual}h/년")
    else:
        annual = 800.0
        print(f"  ▶ 연간 비행시간: {annual}h/년 (함대 기준값 — 제조연도 미등록)")

    result = get(f"/procurement/forecast/{aircraft_id}", annual_flight_hours=annual)
    if not result:
        return
    items = result if isinstance(result, list) else result.get("forecasts") or result.get("items") or [result]
    rf = result.get("rate_forecast", {}) if isinstance(result, dict) else {}

    # 환율 저점 예측 요약 출력
    if rf:
        cur  = rf.get("current_rate", "-")
        h2d  = rf.get("h2_low_date", "-")
        h2r  = rf.get("h2_low_rate", "-")
        h1d  = rf.get("h1_low_date", "-")
        h1r  = rf.get("h1_low_rate", "-")
        trnd = rf.get("trend_per_month", 0)
        print(f"\n  [환율 저점 예측]  현재 {cur}원  |  추세 {trnd:+.1f}원/월")
        print(f"  하반기 저점 예상: {h2d} ({h2r}원)  |  상반기 저점 예상: {h1d} ({h1r}원)")

    # 정비유형 기준으로 중복 제거 — 같은 유형의 BOM 부품이 여러 행이어도 1행으로 표시
    # schedule_count(스케줄 중복 수) + 부품 수를 합산하여 ×N 표기
    seen: dict[str, dict] = {}
    for f in items:
        mt = str(f.get("maintenance_type", ""))
        if mt not in seen:
            seen[mt] = {**f, "_part_count": 1}
        else:
            seen[mt]["_part_count"] += 1
            # 더 이른 발주 기준일로 갱신
            if f.get("order_by_date", "") < seen[mt].get("order_by_date", ""):
                seen[mt].update({k: v for k, v in f.items() if k != "_part_count"})
    grouped = list(seen.values())

    print(f"\n  {'정비유형':<30s}  {'도래 예상일':<12s}  {'발주 시작일':<12s}  {'권고':<12s}  {'환율 시기'}")
    print("  " + "-" * 90)
    for f in grouped:
        sched_cnt = f.get("schedule_count", 1)   # 동일 정비유형 스케줄 수
        part_cnt  = f.get("_part_count", 1)       # 해당 유형 BOM 부품 수
        n = max(sched_cnt, part_cnt)
        mt = str(f.get("maintenance_type", ""))
        mt_label = (f"{mt} ×{n}" if n > 1 else mt)[:29]
        due  = str(f.get("due_date", ""))[:11]
        obd  = str(f.get("order_by_date", ""))[:11]
        rec  = str(f.get("recommendation", ""))[:11]
        rtag = str(f.get("rate_timing", "-"))
        print(f"  {mt_label:<30s}  {due:<12s}  {obd:<12s}  {rec:<12s}  {rtag}")
    print(f"\n  총 {len(grouped)}건  (부품 {len(items)}종)")


# ── 환율 서브메뉴 ─────────────────────────────────────────────────────────────

def action_rate_submenu():
    """환율 탭 — 현황 조회 및 오늘자 환율 입력 서브메뉴."""
    from functions.csc03.fn_rate_forecast import _load_eur_rates, predict_low_rate_dates
    from functions.db import get_client

    while True:
        sub = [
            {"key": "status",   "label": "환율 현황 (EUR/KRW 최근 6개월)"},
            {"key": "input",    "label": "오늘자 환율 입력                  (DB 변경)"},
            {"key": "back",     "label": "돌아가기"},
        ]
        choice = pick(sub, "\n[환율 메뉴]")
        if choice is None or choice["key"] == "back":
            return

        # ── 환율 현황
        if choice["key"] == "status":
            rates = _load_eur_rates()
            if not rates:
                print("  환율 데이터를 불러올 수 없습니다.")
                continue

            print("\n  [EUR/KRW 현황]")
            recent = rates[-6:]
            min_v = min(v for _, v in recent)
            max_v = max(v for _, v in recent)
            for d, v in recent:
                bar_len = int((v - min_v) / max(max_v - min_v, 1) * 20)
                bar = "█" * bar_len
                print(f"  {d.strftime('%Y-%m')}  {v:>8,.1f}원  {bar}")

            cur  = rates[-1][1]
            prev = rates[-7][1] if len(rates) >= 7 else rates[0][1]
            diff = cur - prev
            sign = "▲" if diff > 0 else "▼" if diff < 0 else "━"
            print(f"\n  현재: {cur:,.1f}원  |  6개월 전: {prev:,.1f}원  |  변동 {sign}{abs(diff):.1f}원")

            fc = predict_low_rate_dates()
            if fc:
                trnd = fc.get("trend_per_month", 0)
                tdesc = "상승세" if trnd > 2 else "하락세" if trnd < -2 else "보합세"
                print(f"  최근 추세: {trnd:+.1f}원/월 ({tdesc})")
                print(f"\n  저점 예측 ▶ 하반기(H2): {fc.get('h2_low_date')} {fc.get('h2_low_rate'):,.1f}원")
                print(f"             상반기(H1): {fc.get('h1_low_date')} {fc.get('h1_low_rate'):,.1f}원")

        # ── 오늘자 환율 입력
        elif choice["key"] == "input":
            today_str = date.today().isoformat()
            today_ym  = date.today().strftime("%Y-%m")
            rates = _load_eur_rates()
            cur   = rates[-1][1] if rates else None
            if cur:
                print(f"\n  현재 DB 최신 환율: {cur:,.1f}원 ({rates[-1][0].strftime('%Y-%m')})")

            raw = input(f"  오늘({today_str}) EUR/KRW 환율 입력 (엔터=취소): ").strip()
            if not raw:
                print("  취소되었습니다.")
                continue
            try:
                new_rate = float(raw)
                if new_rate < 100 or new_rate > 5000:
                    raise ValueError
            except ValueError:
                print("  유효하지 않은 환율값입니다 (100~5000 사이 숫자).")
                continue

            print(f"\n  ⚠ DB에 저장됩니다: EUR/KRW = {new_rate:,.1f}원 ({today_ym})")
            if input("  계속할까요? (y/n): ").strip().lower() != "y":
                print("  취소되었습니다.")
                continue

            try:
                client = get_client()
                # 같은 달 데이터가 있으면 update, 없으면 insert (upsert)
                client.table("currency_rates").upsert({
                    "currency_code": "EUR",
                    "exchange_rate": new_rate,
                    "base_currency": "KRW",
                    "update_date":   today_str,
                }, on_conflict="currency_code,update_date").execute()
                print(f"  ✓ 저장 완료: EUR/KRW = {new_rate:,.1f}원 ({today_str})")
            except Exception as e:
                print(f"  ✗ 저장 실패: {e}")


# ── 메뉴 ③ 비행시간 입력 (DB 변경) ─────────────────────────────────────────

def action_flight_hours(aircraft_id: int):
    today_str = date.today().isoformat()
    h_raw = input("  추가할 비행시간(h, 예: 3): ").strip()
    try:
        hours = float(h_raw)
        if hours <= 0:
            raise ValueError
    except ValueError:
        print("  0보다 큰 숫자를 입력하세요.")
        return
    flight_date = input(f"  비행일자 (엔터={today_str}): ").strip() or today_str
    pilot = input("  조종사명 (엔터=시연): ").strip() or "시연"

    res = post(f"/aircraft/{aircraft_id}/flight-hours", {
        "flight_date": flight_date,
        "flight_hours": hours,
        "flight_minutes": 0,
        "pilot_name": pilot,
        "notes": "자유시연 — 비행시간 입력",
    })
    if res:
        print(f"  ✓ 입력 완료 — 당일 비행 {res.get('total_flight_hours')}h"
              f" / 전체 누적 {res.get('total_accumulated_hours')}h")


# ── 메뉴 ③ 정비이력 등록 (DB 변경: 출고+스케줄완료+D-Time+선택적 알람) ──────

def action_complete_maintenance(aircraft_id: int):
    scheds = list_schedules(aircraft_id)
    bom_only = [s for s in scheds if normalize_mt(s["maintenance_type"]) in BOM_BACKED_TYPES]
    if not bom_only:
        print("  이 기체엔 BOM이 연결된(부품 출고 가능한) 정비유형이 없습니다.")
        return
    chosen = pick(bom_only, "완료 처리할 정비유형 선택 (✓BOM만 표시됨)")
    if not chosen:
        return
    mt = chosen["maintenance_type"]

    required = get(f"/maintenance/required-parts/{aircraft_id}", maintenance_type=mt) or []
    if not required:
        print("  필요부품 목록이 비어 있습니다 (BOM 매칭 안 됨 — 다른 유형을 선택하세요).")
        return

    print(f"\n  {mt} 정비 필요부품 {len(required)}개 (앞 5개만 표시):")
    show_n = min(5, len(required))
    for i, r in enumerate(required[:show_n], 1):
        print(f"    {i}) {r.get('nomenclature')}  (part_id={r.get('part_id')}, 필요수량={r.get('required_qty')})")
    idx_raw = input(f"  시연용으로 출고할 부품 번호 (1~{show_n}, 엔터=1번): ").strip()
    idx = int(idx_raw) - 1 if idx_raw.isdigit() and 1 <= int(idx_raw) <= show_n else 0
    part = required[idx]

    ac = get(f"/aircraft/{aircraft_id}")
    if not ac:
        return

    print(f"\n  ⚠ 아래 작업은 DB를 변경합니다:")
    print(f"     - maintenance_history 1건 생성 ({mt})")
    print(f"     - {part.get('nomenclature')} 1개 출고")
    print(f"     - maintenance_schedule 상태 → completed")
    print(f"     - d_time_counter 재계산")
    if input("  계속할까요? (y/n): ").strip().lower() != "y":
        print("  취소되었습니다.")
        return

    today_str = date.today().isoformat()
    maint_date = input(f"  정비일자 (엔터={today_str}): ").strip() or today_str
    handler = input("  정비사명 (엔터=시연): ").strip() or "시연"

    res = post("/maintenance/history", {
        "aircraft_id": aircraft_id,
        "maintenance_date": maint_date,
        "maintenance_type": mt,
        "hours_at_maintenance": float(ac.get("total_flight_hours") or 0),
        "handled_by": handler,
        "destination": "청주",
        "parts_used": [{"part_id": part["part_id"], "quantity": 1}],
        "notes": "자유시연 — 정비이력 등록",
    })
    if not res:
        return
    print(f"\n  ✓ history_id={res.get('history_id')}")
    for p in (res.get("parts_issued") or []):
        print(f"  ✓ 출고: part_id={p.get('part_id')}  잔여={p.get('quantity_after')}개")
    print(f"  ✓ D-Time 갱신: schedule_id={res.get('d_time_updated')}")
    if res.get("warnings"):
        for w in res["warnings"]:
            print(f"  ⚠ {w}")

    if input("\n  바로 알람 생성(fn14)도 보여줄까요? (y/n): ").strip().lower() == "y":
        alarm = post("/maintenance/alerts", {
            "aircraft_id": aircraft_id,
            "alarm_type": "maintenance_overdue",
            "severity": "critical",
            "message": f"{mt} 정비초과 알람 (자유시연)",
            "user_id": "demo_user",
        })
        if alarm:
            pp(alarm)


# ── 메인 루프 ────────────────────────────────────────────────────────────

def main():
    print("=" * 64)
    print("  Potato_123 — 자유 선택 시연 도구")
    print("  기체와 정비유형을 그 자리에서 골라가며 보여줄 수 있습니다.")
    print("  (시연 시작 audit_log 체크포인트: id = 831)")
    print("=" * 64)

    while True:
        aircraft_id = choose_aircraft()
        if aircraft_id is None:
            print("\n  종료합니다.")
            return
        ac = show_aircraft_summary(aircraft_id)
        if not ac:
            continue

        while True:
            menu = [
                {"key": "inquiry",  "label": "재고 / BOM / 필요부품 조회             (읽기전용, 안전)"},
                {"key": "forecast", "label": "구매시기 예측 (fn18)                   (읽기전용, 안전)"},
                {"key": "rate",     "label": "환율 (현황 조회 / 오늘자 입력)"},
                {"key": "flight",   "label": "비행시간 입력                           (DB 변경)"},
                {"key": "complete", "label": "정비이력 등록 (출고+스케줄완료+D-Time+알람) (DB 변경)"},
                {"key": "switch",   "label": "다른 기체 선택"},
                {"key": "quit",     "label": "종료"},
            ]
            choice = pick(menu, "\n작업 선택")
            if choice is None or choice["key"] == "quit":
                print("\n  종료합니다. DB를 변경했다면 rollback_from_checkpoint.sql 로 복구하세요.")
                return
            if choice["key"] == "inquiry":
                action_inquiry(aircraft_id)
            elif choice["key"] == "forecast":
                action_forecast(aircraft_id)
            elif choice["key"] == "rate":
                action_rate_submenu()
            elif choice["key"] == "flight":
                action_flight_hours(aircraft_id)
                ac = show_aircraft_summary(aircraft_id)
            elif choice["key"] == "complete":
                action_complete_maintenance(aircraft_id)
            elif choice["key"] == "switch":
                break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n  중단되었습니다.")
        sys.exit(0)
