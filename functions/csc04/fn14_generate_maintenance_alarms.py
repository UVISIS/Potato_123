from __future__ import annotations
from functions.db import get_client
from functions.constants import (
    ALARM_CRITICAL_HOURS as CRITICAL_HOURS,
    ALARM_WARNING_HOURS  as WARNING_HOURS,
    ALARM_WARNING_DAYS   as WARNING_DAYS,
    ALARM_INFO_DAYS      as INFO_DAYS,
)


# 시간 기반 임계값 (잔여 비행시간, h)
# CRITICAL_HOURS = 0   → functions.constants 로 통합
# WARNING_HOURS  = 10  → functions.constants 로 통합
INFO_HOURS     = 25     # ≤ 25h → 예정
# 날짜 기반 임계값 (잔여 일수, day) — hours_remaining 이 None 일 때 사용
# WARNING_DAYS   = 7   → functions.constants 로 통합
# INFO_DAYS      = 30  → functions.constants 로 통합


def generate_maintenance_alarms(
    aircraft_id: int | None = None,
    warning_hours: float = WARNING_HOURS,
    info_hours: float = INFO_HOURS,
    create_notifications: bool = True,
    notify_user_id: str | None = None,
) -> dict:
    """
    d_time_counter 를 평가해 정비 알람을 생성한다. (이미 활성 알람이 있으면 중복 생성하지 않음)

    Parameters
    ----------
    aircraft_id : int | None
        특정 항공기만 평가. None 이면 전체 d_time_counter 대상.
    warning_hours : float
        "임박" 임계값(잔여 비행시간 h). 기본 10.
    info_hours : float
        "예정" 임계값(잔여 비행시간 h). 기본 25.
    create_notifications : bool
        True 면 생성된 알람마다 notification_logs 에 알림 1건 적재.
    notify_user_id : str | None
        알림 수신 user_id (선택).

    Returns
    -------
    dict
        {
            "evaluated"      : int,   # 평가한 d_time_counter 행 수
            "created"        : int,   # 신규 생성된 알람 수
            "skipped_existing": int,  # 활성 알람 중복으로 스킵된 수
            "alarms"         : [
                {
                    "alarm_id"               : int | None,
                    "aircraft_id"            : int,
                    "maintenance_schedule_id": int | None,
                    "alarm_type"             : str,   # "정비초과"|"정비임박"|"정비예정"
                    "severity"               : str,   # "critical"|"warning"|"info"
                    "message"                : str,
                }, ...
            ],
        }

    Raises
    ------
    ValueError
        · warning_hours, info_hours 가 음수이거나 warning_hours > info_hours
    RuntimeError
        · maintenance_alarms INSERT 실패
    """
    if warning_hours < 0 or info_hours < 0:
        raise ValueError("warning_hours, info_hours 는 0 이상이어야 합니다.")
    if warning_hours > info_hours:
        raise ValueError(
            f"warning_hours({warning_hours}) 는 info_hours({info_hours}) 이하여야 합니다."
        )

    client = get_client()

    # ── d_time_counter 조회
    dt_q = client.table("d_time_counter").select(
        "id, aircraft_id, maintenance_schedule_id, hours_remaining, days_remaining"
    )
    if aircraft_id is not None:
        dt_q = dt_q.eq("aircraft_id", aircraft_id)
    dt = dt_q.execute()
    counters = dt.data or []

    # ── maintenance_schedule.maintenance_type 매핑(메시지용)
    sched_ids = [c["maintenance_schedule_id"] for c in counters
                 if c.get("maintenance_schedule_id") is not None]
    sched_map: dict[int, str] = {}
    if sched_ids:
        sch = (
            client.table("maintenance_schedule")
            .select("id, maintenance_type")
            .in_("id", sched_ids)
            .execute()
        )
        sched_map = {s["id"]: s.get("maintenance_type") for s in (sch.data or [])}

    alarms_out: list[dict] = []
    created = 0
    skipped = 0

    for c in counters:
        sev_info = _classify(
            c.get("hours_remaining"), c.get("days_remaining"),
            warning_hours, info_hours,
        )
        if sev_info is None:
            continue  # 임계값 밖 → 알람 불필요

        alarm_type, severity = sev_info
        ac_id    = c.get("aircraft_id")
        sch_id   = c.get("maintenance_schedule_id")
        mtype    = sched_map.get(sch_id, "정비")

        # ── 중복 방지: 동일 (aircraft, schedule, alarm_type) 활성 알람 존재 시 스킵
        dup_q = (
            client.table("maintenance_alarms")
            .select("id")
            .eq("aircraft_id", ac_id)
            .eq("alarm_type", alarm_type)
            .eq("status", "active")
        )
        if sch_id is not None:
            dup_q = dup_q.eq("maintenance_schedule_id", sch_id)
        dup = dup_q.execute()
        if dup.data:
            skipped += 1
            continue

        message = _build_message(mtype, c.get("hours_remaining"), c.get("days_remaining"), alarm_type)

        payload = {
            "aircraft_id":             ac_id,
            "alarm_type":              alarm_type,
            "severity":                severity,
            "message":                 message,
            "maintenance_schedule_id": sch_id,
            "status":                  "active",
        }
        payload = {k: v for k, v in payload.items() if v is not None}

        try:
            res = client.table("maintenance_alarms").insert(payload).execute()
            alarm_id = _extract_id(res.data)
        except Exception as e:
            raise RuntimeError(f"maintenance_alarms 생성 실패: {e}")

        created += 1
        alarms_out.append({
            "alarm_id":                alarm_id,
            "aircraft_id":             ac_id,
            "maintenance_schedule_id": sch_id,
            "alarm_type":              alarm_type,
            "severity":                severity,
            "message":                 message,
        })

        # ── 알림 로그 적재 (선택)
        if create_notifications:
            notif = {
                "notification_type": "maintenance",
                "message":           message,
                "is_read":           False,
            }
            if notify_user_id is not None:
                notif["user_id"] = notify_user_id
            try:
                client.table("notification_logs").insert(notif).execute()
            except Exception:
                # 알림 적재 실패는 알람 생성을 무효화하지 않음(베스트 에포트)
                pass

    return {
        "evaluated":        len(counters),
        "created":          created,
        "skipped_existing": skipped,
        "alarms":           alarms_out,
    }


def _classify(
    hours_remaining, days_remaining, warning_hours: float, info_hours: float
) -> tuple[str, str] | None:
    """잔여시간(우선) 또는 잔여일수로 (alarm_type, severity) 분류. 임계값 밖이면 None."""
    if hours_remaining is not None:
        h = float(hours_remaining)
        if h <= CRITICAL_HOURS:
            return ("정비초과", "critical")
        if h <= warning_hours:
            return ("정비임박", "warning")
        if h <= info_hours:
            return ("정비예정", "info")
        return None

    # hours_remaining 이 None(날짜기반 스케줄) → days_remaining 으로 평가
    if days_remaining is not None:
        d = int(days_remaining)
        if d >= 9999:            # fn12 날짜기반 플레이스홀더 → 미평가
            return None
        if d <= 0:
            return ("정비초과", "critical")
        if d <= WARNING_DAYS:
            return ("정비임박", "warning")
        if d <= INFO_DAYS:
            return ("정비예정", "info")
    return None


def _build_message(mtype: str, hours_remaining, days_remaining, alarm_type: str) -> str:
    if hours_remaining is not None:
        return f"[{alarm_type}] {mtype} — 잔여 비행시간 {float(hours_remaining):.1f}h"
    if days_remaining is not None:
        return f"[{alarm_type}] {mtype} — 잔여 {int(days_remaining)}일"
    return f"[{alarm_type}] {mtype}"


def _extract_id(raw) -> int | None:
    """INSERT 결과(res.data)에서 id 추출. Supabase(list[dict]) / Mock(list|dict|None) 모두 대응."""
    if isinstance(raw, list) and raw:
        return raw[0].get("id")
    if isinstance(raw, dict):
        return raw.get("id")
    return None


# =============================================================================
# 변경 이력 (Change Log)
# =============================================================================
# v1.0  2026-06-10  6월2주차 — 신규 작성
#       · d_time_counter 평가 → maintenance_alarms 생성 + notification_logs 적재
#       · hours_remaining 우선 / None(날짜기반)이면 days_remaining 로 대체 평가
#       · (aircraft, schedule, alarm_type) 활성 알람 중복 생성 방지
#       · 임계값 파라미터화(초과≤0h / 임박≤10h / 예정≤25h), INSERT 결과 방어 헬퍼
#
# 향후 변경 예정
#       · severity 자동 격상(예: 임박 상태로 N일 경과 시 critical) 룰 검토
#       · notification_logs user_id 를 user_roles.assigned_aircraft_ids 기반 자동 타겟팅
#       · maintenance_schedule.status 자동 갱신 트리거 도입 시 알람 해제(acknowledge) 연동
# =============================================================================
