"""
CSC-04  |  fn16: 신규 기체 정비 스케줄 시딩

신규 기체 등록 시 maintenance_schedule 행을 만든다. fn11(calc_next_maintenance)은
'조회 전용'이라 일정을 생성하지 못하므로, 등록 후처리용으로 두 가지 경로를 제공한다.

    copy_maintenance_schedule()      — 동일 기종 기존 기체에서 스케줄 복사 (자동)
    register_maintenance_schedule()  — 신규 기종: 작업자가 직접 정의해 등록 (수동)

호출 테이블:
    aircraft             (SELECT) — 기종/존재 확인
    maintenance_schedule (SELECT/INSERT)

설계 메모 (2026-06-13):
    · 복사 시 interval_hours / interval_months / maintenance_type 만 가져오고
      due_hours / due_date 는 초기화(None), status='scheduled' 로 리셋한다.
      (신규 기체는 누적시간 0 기준이므로 직전 기체의 도래시점을 그대로 쓰면 안 됨)
    · 동일 기종 기준 기체가 여러 대면 '스케줄 행이 가장 많은' 기체를 원본으로 택한다.
"""

from __future__ import annotations
from functions.db import get_client


# 복사 대상 컬럼 (도래시점/상태는 제외 → 신규 기체 기준 초기화)
_TEMPLATE_FIELDS = ("maintenance_type", "interval_hours", "interval_months")


def copy_maintenance_schedule(
    target_aircraft_id: int,
    source_aircraft_id: int | None = None,
) -> dict:
    """
    동일 기종 기존 기체의 정비 스케줄을 신규 기체로 복사한다.

    Parameters
    ----------
    target_aircraft_id : int
        스케줄을 생성할 신규 기체 aircraft.id
    source_aircraft_id : int | None
        복사 원본 기체. None 이면 target 과 같은 model 의 스케줄 보유 기체를
        자동 탐색(스케줄 행이 가장 많은 기체 선택).

    Returns
    -------
    dict
        {
            "target_aircraft_id" : int,
            "source_aircraft_id" : int,
            "copied"             : int,        # 생성된 스케줄 행 수
            "schedule_ids"       : list[int],
        }

    Raises
    ------
    ValueError
        · target 기체 미존재
        · source 지정했으나 미존재 / target 과 기종 불일치
    LookupError
        · 동일 기종의 스케줄 보유 기체가 없음 → 수동 등록 필요
          (register_maintenance_schedule 로 처리)
    """
    client = get_client()

    # ── target 기체 확인
    tgt = (
        client.table("aircraft")
        .select("id, model")
        .eq("id", target_aircraft_id)
        .maybe_single()
        .execute()
    )
    if not tgt.data:
        raise ValueError(f"target_aircraft_id {target_aircraft_id} 기체가 없습니다.")
    target_model = tgt.data.get("model")

    # ── source 결정
    if source_aircraft_id is not None:
        src = (
            client.table("aircraft")
            .select("id, model")
            .eq("id", source_aircraft_id)
            .maybe_single()
            .execute()
        )
        if not src.data:
            raise ValueError(f"source_aircraft_id {source_aircraft_id} 기체가 없습니다.")
        if src.data.get("model") != target_model:
            raise ValueError(
                f"기종 불일치: source(model={src.data.get('model')}) "
                f"≠ target(model={target_model})"
            )
        chosen_source = source_aircraft_id
    else:
        # 동일 기종, target 제외, 스케줄 보유 기체 중 행 수 최다 선택
        cands = (
            client.table("aircraft")
            .select("id, model")
            .eq("model", target_model)
            .execute()
        )
        best_id, best_cnt = None, 0
        for ac in (cands.data or []):
            if ac["id"] == target_aircraft_id:
                continue
            cnt = len(
                client.table("maintenance_schedule")
                .select("id")
                .eq("aircraft_id", ac["id"])
                .execute()
                .data
                or []
            )
            if cnt > best_cnt:
                best_id, best_cnt = ac["id"], cnt
        if best_id is None:
            raise LookupError(
                f"기종 '{target_model}' 의 정비 스케줄 보유 기체가 없습니다. "
                f"신규 기종이므로 register_maintenance_schedule() 로 수동 등록하세요."
            )
        chosen_source = best_id

    # ── 원본 스케줄 조회
    src_scheds = (
        client.table("maintenance_schedule")
        .select("maintenance_type, interval_hours, interval_months")
        .eq("aircraft_id", chosen_source)
        .execute()
    ).data or []
    if not src_scheds:
        raise LookupError(
            f"source 기체(id={chosen_source}) 에 복사할 스케줄이 없습니다."
        )

    # ── 복사 INSERT (도래시점 초기화, status='scheduled')
    rows = []
    for s in src_scheds:
        row = {f: s.get(f) for f in _TEMPLATE_FIELDS}
        row["aircraft_id"] = target_aircraft_id
        row["due_hours"] = None
        row["due_date"] = None
        row["status"] = "scheduled"
        rows.append(row)

    res = client.table("maintenance_schedule").insert(rows).execute()
    created = res.data or []
    return {
        "target_aircraft_id": target_aircraft_id,
        "source_aircraft_id": chosen_source,
        "copied": len(created),
        "schedule_ids": [r.get("id") for r in created],
    }


def register_maintenance_schedule(
    aircraft_id: int,
    schedules: list[dict],
) -> dict:
    """
    신규 기종 기체에 정비 스케줄을 작업자가 직접 등록한다.

    Parameters
    ----------
    aircraft_id : int
        대상 기체 aircraft.id
    schedules : list[dict]
        각 항목:
            {
                "maintenance_type" : str,           # 필수
                "interval_hours"   : float,         # 필수 (시간기반 0 가능 = 순수 날짜주기)
                "interval_months"  : int | None,    # 선택
            }

    Returns
    -------
    dict
        {
            "aircraft_id"  : int,
            "registered"   : int,
            "schedule_ids" : list[int],
        }

    Raises
    ------
    ValueError
        · aircraft_id 미존재
        · schedules 비어 있음
        · 항목에 maintenance_type / interval_hours 누락
    """
    if not schedules:
        raise ValueError("schedules 가 비어 있습니다. 최소 1개 이상 필요합니다.")

    client = get_client()

    ac = (
        client.table("aircraft")
        .select("id")
        .eq("id", aircraft_id)
        .maybe_single()
        .execute()
    )
    if not ac.data:
        raise ValueError(f"aircraft_id {aircraft_id} 기체가 없습니다.")

    rows = []
    for i, s in enumerate(schedules):
        if not s.get("maintenance_type"):
            raise ValueError(f"schedules[{i}].maintenance_type 가 필요합니다.")
        if s.get("interval_hours") is None:
            raise ValueError(f"schedules[{i}].interval_hours 가 필요합니다.")
        rows.append({
            "aircraft_id":     aircraft_id,
            "maintenance_type": s["maintenance_type"],
            "interval_hours":   s["interval_hours"],
            "interval_months":  s.get("interval_months"),
            "due_hours":        None,
            "due_date":         None,
            "status":           "scheduled",
        })

    res = client.table("maintenance_schedule").insert(rows).execute()
    created = res.data or []
    return {
        "aircraft_id": aircraft_id,
        "registered": len(created),
        "schedule_ids": [r.get("id") for r in created],
    }


# =============================================================================
# 변경 이력 (Change Log)
# =============================================================================
# v1.0  2026-06-13  신규 작성
#       · fn11(조회 전용) 한계 보완 — 신규 기체 등록 후처리용 스케줄 시딩
#       · copy_maintenance_schedule: 동일 기종 자동 복사 (도래시점 초기화)
#       · register_maintenance_schedule: 신규 기종 수동 등록
# =============================================================================
