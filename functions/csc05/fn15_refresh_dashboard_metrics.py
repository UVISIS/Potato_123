"""
CSC-05  |  fn15: refresh_dashboard_metrics()

대시보드 집계 지표 갱신 — cron 또는 수동 호출

호출 테이블:
    aircraft            (SELECT) — 기체 현황
    d_time_counter      (SELECT) — 잔여 시간 기준 정비 임박 집계
    maintenance_alarms  (SELECT) — 활성 알람 수
    parts_inventory     (SELECT) — 재고 현황
    reorder_points      (SELECT) — 안전재고 기준
    flight_hours        (SELECT) — 이번 달 비행시간
    maintenance_schedule(SELECT) — 이번 달 완료 정비
    dashboard_metrics   (UPSERT) — 집계 결과 저장

⚠️  DB 변경 영향 없음 — 안정 함수

집계 지표 목록 (metric_name 기준):
    aircraft_total          — 전체 항공기 수
    aircraft_operational    — 운영 중 기체 수
    aircraft_grounded       — 접지 기체 수
    maintenance_overdue     — 정비 초과(hours_remaining < 0) 기체·스케줄 수
    maintenance_critical    — 정비 임박(0 ≤ hours_remaining ≤ 10) 수
    maintenance_warning     — 정비 주의(10 < hours_remaining ≤ 30) 수
    alarm_active            — 활성(미확인) 알람 수
    alarm_critical          — severity='critical' 활성 알람 수
    stock_shortage          — 재고 부족(qty ≤ safety_stock) 품목 수
    stock_warning           — 재고 경고(safety_stock < qty ≤ safety_stock×1.5) 품목 수
    flight_hours_this_month — 이번 달 전체 비행시간 합계
    maintenance_done_this_month — 이번 달 완료된 정비 스케줄 수
"""

from __future__ import annotations
from datetime import datetime, timezone, date


def refresh_dashboard_metrics(force: bool = False) -> dict:
    """
    대시보드 집계 지표를 계산하고 dashboard_metrics 테이블에 UPSERT 한다.

    Parameters
    ----------
    force : bool
        True 이면 마지막 갱신 시각과 무관하게 강제 재계산 (기본: False)
        False 이면 최근 5분 이내 갱신된 경우 스킵하고 캐시 반환

    Returns
    -------
    dict
        {
            "refreshed"   : bool,     # 실제 갱신 여부 (캐시 hit 시 False)
            "metrics"     : dict,     # {metric_name: metric_value} 전체 지표
            "updated_at"  : str,      # 갱신 시각 ISO 8601
            "upsert_count": int,      # 갱신된 행 수
        }

    Raises
    ------
    RuntimeError
        집계 중 DB 조회 또는 UPSERT 실패 시
    """
    from functions.db import get_client

    client   = get_client()
    now      = datetime.now(timezone.utc)
    now_iso  = now.isoformat()
    CACHE_SECONDS = 300  # 5분 캐시

    # ── 캐시 확인 (force=False 일 때만)
    if not force:
        last = (
            client.table("dashboard_metrics")
            .select("update_time")
            .order("update_time", desc=True)
            .limit(1)
            .execute()
        )
        if last.data:
            raw_time = last.data[0]["update_time"]
            # timezone-naive 처리
            if isinstance(raw_time, str):
                last_dt = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
            else:
                last_dt = raw_time
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            elapsed = (now - last_dt).total_seconds()
            if elapsed < CACHE_SECONDS:
                # 캐시 히트 — 저장된 값 그대로 반환
                all_metrics = (
                    client.table("dashboard_metrics")
                    .select("metric_name, metric_value")
                    .execute()
                )
                return {
                    "refreshed":    False,
                    "metrics":      {r["metric_name"]: float(r["metric_value"] or 0)
                                     for r in (all_metrics.data or [])},
                    "updated_at":   last_dt.isoformat(),
                    "upsert_count": 0,
                }

    metrics: dict[str, float] = {}

    # ────────────────────────────────────────────
    # 1. 항공기 현황
    # ────────────────────────────────────────────
    try:
        ac_all = client.table("aircraft").select("id, status").execute()
        ac_data = ac_all.data or []
        metrics["aircraft_total"]       = float(len(ac_data))
        metrics["aircraft_operational"] = float(
            sum(1 for a in ac_data if a.get("status") == "operational")
        )
        metrics["aircraft_grounded"] = float(
            sum(1 for a in ac_data if a.get("status") == "grounded")
        )
    except Exception as e:
        raise RuntimeError(f"aircraft 집계 실패: {e}")

    # ────────────────────────────────────────────
    # 2. 정비 임박/초과 현황 (d_time_counter 기준)
    # ────────────────────────────────────────────
    try:
        dtc = client.table("d_time_counter").select("hours_remaining").execute()
        dtc_data = dtc.data or []

        overdue  = 0
        critical = 0
        warning  = 0
        for row in dtc_data:
            hr = row.get("hours_remaining")
            if hr is None:
                continue
            hr = float(hr)
            if hr < 0:
                overdue += 1
            elif hr <= 10.0:
                critical += 1
            elif hr <= 30.0:
                warning += 1

        metrics["maintenance_overdue"]  = float(overdue)
        metrics["maintenance_critical"] = float(critical)
        metrics["maintenance_warning"]  = float(warning)
    except Exception as e:
        raise RuntimeError(f"d_time_counter 집계 실패: {e}")

    # ────────────────────────────────────────────
    # 3. 알람 현황
    # ────────────────────────────────────────────
    try:
        alarms = (
            client.table("maintenance_alarms")
            .select("severity, status")
            .eq("status", "active")
            .execute()
        )
        alarm_data = alarms.data or []
        metrics["alarm_active"]   = float(len(alarm_data))
        metrics["alarm_critical"] = float(
            sum(1 for a in alarm_data if a.get("severity") == "critical")
        )
    except Exception as e:
        raise RuntimeError(f"maintenance_alarms 집계 실패: {e}")

    # ────────────────────────────────────────────
    # 4. 재고 현황 (parts_inventory × reorder_points 조합)
    # ────────────────────────────────────────────
    try:
        inv = client.table("parts_inventory").select("part_id, quantity_on_hand").execute()
        rp  = client.table("reorder_points").select("part_id, safety_stock").execute()

        # part_id → safety_stock 매핑
        safety_map: dict[int, int] = {
            r["part_id"]: (r["safety_stock"] or 0)
            for r in (rp.data or [])
            if r.get("part_id") is not None
        }

        # part_id 별 재고 합산 (청주+무안 통합)
        qty_map: dict[int, int] = {}
        for row in (inv.data or []):
            pid = row.get("part_id")
            qty = row.get("quantity_on_hand") or 0
            if pid is not None:
                qty_map[pid] = qty_map.get(pid, 0) + qty

        shortage = 0
        warning_stock = 0
        for pid, qty in qty_map.items():
            ss = safety_map.get(pid, 0)
            if qty <= ss:
                shortage += 1
            elif qty <= ss * 1.5:
                warning_stock += 1

        metrics["stock_shortage"] = float(shortage)
        metrics["stock_warning"]  = float(warning_stock)
    except Exception as e:
        raise RuntimeError(f"재고 집계 실패: {e}")

    # ────────────────────────────────────────────
    # 5. 이번 달 비행시간 합계
    # ────────────────────────────────────────────
    try:
        today       = date.today()
        month_start = date(today.year, today.month, 1).isoformat()
        fh = (
            client.table("flight_hours")
            .select("flight_hours")
            .gte("flight_date", month_start)
            .execute()
        )
        total_fh = sum(float(r["flight_hours"]) for r in (fh.data or []))
        metrics["flight_hours_this_month"] = round(total_fh, 1)
    except Exception as e:
        raise RuntimeError(f"flight_hours 집계 실패: {e}")

    # ────────────────────────────────────────────
    # 6. 이번 달 완료된 정비 수
    # ────────────────────────────────────────────
    try:
        today       = date.today()
        month_start = date(today.year, today.month, 1).isoformat()
        ms = (
            client.table("maintenance_schedule")
            .select("id", count="exact")
            .eq("status", "completed")
            .gte("due_date", month_start)
            .execute()
        )
        metrics["maintenance_done_this_month"] = float(ms.count or 0)
    except Exception as e:
        raise RuntimeError(f"maintenance_schedule 집계 실패: {e}")

    # ────────────────────────────────────────────
    # dashboard_metrics UPSERT
    # ────────────────────────────────────────────
    # metric_name 기준으로 행이 있으면 UPDATE, 없으면 INSERT
    # Supabase upsert: on_conflict 로 처리
    upsert_rows = [
        {
            "metric_name":  name,
            "metric_value": value,
            "metric_type":  _metric_type(name),
            "update_time":  now_iso,
        }
        for name, value in metrics.items()
    ]

    try:
        client.table("dashboard_metrics").upsert(
            upsert_rows,
            on_conflict="metric_name"   # metric_name UNIQUE 제약 필요
        ).execute()
    except Exception:
        # UNIQUE 제약 없는 경우 — 기존 행 DELETE 후 INSERT로 폴백
        try:
            client.table("dashboard_metrics").delete().neq("id", 0).execute()
            client.table("dashboard_metrics").insert(upsert_rows).execute()
        except Exception as e2:
            raise RuntimeError(f"dashboard_metrics UPSERT 실패: {e2}")

    return {
        "refreshed":    True,
        "metrics":      metrics,
        "updated_at":   now_iso,
        "upsert_count": len(upsert_rows),
    }


def _metric_type(metric_name: str) -> str:
    """metric_name 으로 metric_type 분류"""
    if metric_name.startswith("aircraft"):
        return "aircraft"
    if metric_name.startswith("maintenance"):
        return "maintenance"
    if metric_name.startswith("alarm"):
        return "alarm"
    if metric_name.startswith("stock"):
        return "inventory"
    if metric_name.startswith("flight"):
        return "flight"
    return "general"


# =============================================================================
# 변경 이력 (Change Log)
# =============================================================================
# v1.0  2026-06-03  최초 작성
#       · 12개 지표 집계 (항공기/정비/알람/재고/비행시간/이달 완료 정비)
#       · force=False 시 5분 캐시 체크 (불필요한 재계산 방지)
#       · force=True 시 캐시 무시하고 강제 재계산
#       · UPSERT: metric_name UNIQUE 제약 기반 (중복 삽입 방지)
#         UNIQUE 제약 없을 시 DELETE 후 INSERT 폴백 처리
#       · dashboard_metrics.metric_name UNIQUE 제약 DB 적용 완료
#         (2026-06-03, constraint: dashboard_metrics_metric_name_unique)
#       · 각 집계 구간을 독립 try/except 로 분리
#         → 한 구간 실패 시 나머지 지표에 영향 없이 RuntimeError 발생
#
# 향후 변경 예정
#       · DB 변경 영향 없음 — 안정 함수
#       · cron 스케줄러 연동 시 force=True 옵션으로 주기 강제 갱신 권장
# =============================================================================
