from fastapi import HTTPException


# ── 숫자 에러 코드 정의 ────────────────────────
class ErrorCode:
    # CSC-01 항공기 (41XX)
    AIRCRAFT_NOT_FOUND      = (4101, "AIRCRAFT_NOT_FOUND")
    AIRCRAFT_ALREADY_EXISTS = (4102, "AIRCRAFT_ALREADY_EXISTS")

    # CSC-02 부품/재고 (42XX)
    COMPONENT_NOT_FOUND     = (4201, "COMPONENT_NOT_FOUND")
    INVENTORY_NOT_FOUND     = (4202, "INVENTORY_NOT_FOUND")
    INSUFFICIENT_STOCK      = (4203, "INSUFFICIENT_STOCK")
    REORDER_NOT_FOUND       = (4204, "REORDER_NOT_FOUND")

    # CSC-03 발주 (43XX)
    ORDER_NOT_FOUND         = (4301, "ORDER_NOT_FOUND")
    EXCHANGE_RATE_NOT_FOUND = (4302, "EXCHANGE_RATE_NOT_FOUND")
    EXCHANGE_RATE_STALE     = (4303, "EXCHANGE_RATE_STALE")

    # CSC-04 정비 (44XX)
    MAINTENANCE_NOT_FOUND   = (4401, "MAINTENANCE_NOT_FOUND")
    SCHEDULE_NOT_FOUND      = (4402, "SCHEDULE_NOT_FOUND")
    ALARM_NOT_FOUND         = (4403, "ALARM_NOT_FOUND")

    # 공통 (45XX)
    INVALID_INPUT           = (4501, "INVALID_INPUT")
    DB_ERROR                = (4502, "DB_ERROR")


# ── 에러 응답 형식 ──────────────────────────────
def error_response(http_status: int, error_code: tuple, message: str, detail: dict = None):
    status_num, code_str = error_code
    content = {
        "error": {
            "status": status_num,
            "code": code_str,
            "message": message
        }
    }
    if detail:
        content["error"]["detail"] = detail
    raise HTTPException(status_code=http_status, detail=content)


# ── 자주 쓰는 에러 함수들 ───────────────────────

def aircraft_not_found(aircraft_id: int):
    error_response(404, ErrorCode.AIRCRAFT_NOT_FOUND,
        f"기체 ID {aircraft_id}를 찾을 수 없습니다")

def component_not_found(component_id: int):
    error_response(404, ErrorCode.COMPONENT_NOT_FOUND,
        f"부품 ID {component_id}를 찾을 수 없습니다")

def inventory_not_found(part_id: int):
    error_response(404, ErrorCode.INVENTORY_NOT_FOUND,
        f"부품 ID {part_id}의 재고 정보를 찾을 수 없습니다")

def insufficient_stock(part_id: int, current: int, requested: int):
    error_response(400, ErrorCode.INSUFFICIENT_STOCK,
        "재고가 부족합니다",
        {"part_id": part_id, "current_qty": current, "requested_qty": requested})

def reorder_not_found(part_id: int):
    error_response(404, ErrorCode.REORDER_NOT_FOUND,
        f"부품 ID {part_id}의 안전재고 기준을 찾을 수 없습니다")

def maintenance_not_found(history_id: int):
    error_response(404, ErrorCode.MAINTENANCE_NOT_FOUND,
        f"정비 이력 ID {history_id}를 찾을 수 없습니다")

def schedule_not_found(aircraft_id: int):
    error_response(404, ErrorCode.SCHEDULE_NOT_FOUND,
        f"기체 ID {aircraft_id}의 정비 일정을 찾을 수 없습니다")

def exchange_rate_not_found(currency_code: str):
    error_response(404, ErrorCode.EXCHANGE_RATE_NOT_FOUND,
        f"{currency_code} 환율 정보를 찾을 수 없습니다")

def invalid_input(message: str):
    error_response(422, ErrorCode.INVALID_INPUT, message)

def db_error(message: str):
    error_response(500, ErrorCode.DB_ERROR, f"DB 오류: {message}")