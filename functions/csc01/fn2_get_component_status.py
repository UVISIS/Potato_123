from __future__ import annotations
from functions.db import get_client


# ── TBO (Time Between Overhaul) 시간 정의
# 참고: DA40NG_주기검사_항목, DA42NG_주기검사_항목, 052000_Scheduled_Maintenance_Checks.pdf
# 향후 aircraft_components.tbo_hours 컬럼 추가 시 이 맵 제거 (선택지 ①)
TBO_HOURS_MAP = {
    "engine": 1800,           # Austro AE300 (DA-40/42 NG)
    "propeller": 2400,        # MTV-6 (DA-40/42 NG)
    "alternator": 2400,       # 교류 발전기
    "governor": 2400,         # 프로펠러 거버너
    "fuel_pump": 2400,        # 전기 연료 펌프
    "battery": 500,           # 항공용 배터리
    "backup_battery": 1,      # ECU 백업 배터리 (1년 = 교체)
    "elt_battery": 6,         # ELT 배터리 (6년 = 교체)
    "coolant": 500,           # 냉각액 (500시간 또는 2년)
    "brake_fluid": 500,       # 유압 브레이크유 (500시간 또는 3년)
    "safety_harness": 1000,   # 안전 벨트 (12년)
    "harness": 1000,          # 일반 하네스
    "gas_spring": 1000,       # 가스 스프링 (3000시간 또는 6년)
    "fuel_tank_vent": 1000,   # 연료 탱크 통풍구 (8년)
    "fire_extinguisher": 1000, # 소화기 (6년)
    "pushrod": 1000,          # 푸시로드 (5년)
    "accumulator": 2400,      # 어큐뮬레이터 (2400시간)
    "timing_chain": 1000,     # 타이밍 체인 (1000시간)
    "hydraulic_fluid": 500,   # 유압유
    "oil": 100,               # 엔진오일 (100시간)
    "air_filter": 500,        # 공기 필터
    "fuel_filter": 1000,      # 연료 필터 (1000시간)
    "oil_filter": 500,        # 오일 필터 (500시간)
}

# ── TBO 잔여시간 임계값 (상태 판정용)
TBO_CRITICAL_HOURS = 0      # ≤ 0h  → "overdue" (초과)
TBO_WARNING_HOURS = 50      # ≤ 50h → "warning" (경고)
TBO_INFO_HOURS = 200        # ≤ 200h → "upcoming" (예정)
# 이상: "serviceable" (정상)


def get_component_status(
    aircraft_id: int,
    include_unknown: bool = True,
) -> list[dict]:
    """
    특정 항공기에 장착된 부품들의 TBO 잔여시간을 조회한다.

    Parameters
    ----------
    aircraft_id : int
        항공기 ID (aircraft.id)
    include_unknown : bool
        True면 TBO 정의되지 않은 부품도 포함 (기본: True)
        False면 TBO 정의된 부품만 반환

    Returns
    -------
    list[dict]
        부품 TBO 상태 목록
        [
            {
                "component_id"   : int | None,
                "component_name" : str,
                "component_type" : str,
                "installed_date" : str | None,
                "install_hours"  : float | None,
                "tbo_hours"      : int | None,
                "remaining_tbo"  : float | None,
                "status"         : str,  # "overdue" | "warning" | "upcoming" | "serviceable" | "unknown"
                "message"        : str,
            }
        ]

    Raises
    ------
    ValueError
        aircraft_id가 유효하지 않거나 항공기가 존재하지 않을 때
    RuntimeError
        DB 조회 실패 시
    """

    if not isinstance(aircraft_id, int) or aircraft_id <= 0:
        raise ValueError(f"aircraft_id는 양의 정수여야 합니다. 받은 값: {aircraft_id}")

    client = get_client()

    # ── Step 1: 항공기 기본 정보 조회 (total_flight_hours)
    try:
        ac_result = client.table("aircraft").select("id, registration, total_flight_hours").eq("id", aircraft_id).maybe_single().execute()
    except Exception as e:
        raise RuntimeError(f"aircraft 테이블 조회 실패: {e}")

    if ac_result.data is None:
        raise ValueError(f"항공기 ID {aircraft_id}가 존재하지 않습니다.")

    aircraft = ac_result.data
    total_flight_hours = aircraft.get("total_flight_hours", 0)
    aircraft_reg = aircraft.get("registration", f"ID:{aircraft_id}")

    # ── Step 2: 항공기 장착 부품 조회
    try:
        comp_result = (
            client.table("aircraft_components")
            .select("id, component_name, component_type, installed_date, install_hours, status")
            .eq("aircraft_id", aircraft_id)
            .execute()
        )
    except Exception as e:
        raise RuntimeError(f"aircraft_components 테이블 조회 실패: {e}")

    components = comp_result.data if comp_result.data else []

    # ── Step 3: 각 부품의 TBO 계산 및 상태 판정
    result = []

    for comp in components:
        component_id = comp.get("id")
        component_name = comp.get("component_name", "Unknown")
        component_type = comp.get("component_type", "unknown").lower()
        installed_date = comp.get("installed_date")
        install_hours = comp.get("install_hours")

        # TBO 조회
        tbo_hours = TBO_HOURS_MAP.get(component_type)

        # TBO 미정의인 경우
        if tbo_hours is None:
            if not include_unknown:
                continue

            result.append({
                "component_id": component_id,
                "component_name": component_name,
                "component_type": component_type,
                "installed_date": installed_date,
                "install_hours": install_hours,
                "tbo_hours": None,
                "remaining_tbo": None,
                "status": "unknown",
                "message": f"[{component_name}] TBO 정의되지 않음",
            })
            continue

        # TBO 정의된 경우 → 계산
        if install_hours is None:
            # install_hours가 NULL이면 잔여시간 계산 불가
            result.append({
                "component_id": component_id,
                "component_name": component_name,
                "component_type": component_type,
                "installed_date": installed_date,
                "install_hours": None,
                "tbo_hours": tbo_hours,
                "remaining_tbo": None,
                "status": "unknown",
                "message": f"[{component_name}] 장착 시점 시간 정보 없음",
            })
            continue

        # ── 잔여 TBO 계산
        # remaining_tbo = (install_hours + tbo_hours) - total_flight_hours
        remaining_tbo = (float(install_hours) + float(tbo_hours)) - float(total_flight_hours)

        # ── 상태 판정
        if remaining_tbo <= TBO_CRITICAL_HOURS:
            status = "overdue"
            message = f"[초과] {component_name} — 잔여 {remaining_tbo:.1f}h (즉시 정비 필요)"
        elif remaining_tbo <= TBO_WARNING_HOURS:
            status = "warning"
            message = f"[경고] {component_name} — 잔여 {remaining_tbo:.1f}h (조만간 정비 예정)"
        elif remaining_tbo <= TBO_INFO_HOURS:
            status = "upcoming"
            message = f"[예정] {component_name} — 잔여 {remaining_tbo:.1f}h"
        else:
            status = "serviceable"
            message = f"[정상] {component_name} — 잔여 {remaining_tbo:.1f}h"

        result.append({
            "component_id": component_id,
            "component_name": component_name,
            "component_type": component_type,
            "installed_date": installed_date,
            "install_hours": float(install_hours),
            "tbo_hours": tbo_hours,
            "remaining_tbo": remaining_tbo,
            "status": status,
            "message": message,
        })

    return result


# =============================================================================
# 변경 이력 (Change Log)
# =============================================================================
# v1.0  2026-06-12  6월2주차 — 신규 작성
#       · TBO 정의(선택지②: 백엔드 하드코딩)로 즉시 구현
#       · aircraft_components.install_hours + TBO_HOURS_MAP - aircraft.total_flight_hours
#       · 상태: overdue(≤0h) / warning(≤50h) / upcoming(≤200h) / serviceable / unknown
#       · TBO_HOURS_MAP: 30+ 부품 유형 기본값 정의
#       · include_unknown 파라미터로 미정의 부품 필터 가능
#
# 향후 변경 예정
#       · aircraft_components.tbo_hours 컬럼 추가 시 (선택지①) TBO_HOURS_MAP 제거
#       · maintenance_schedule.status와 동기화 (트리거 또는 job)
#       · TBO 임계값 자동 조정 (시간 vs 연도 기준 혼합 처리)
# =============================================================================
