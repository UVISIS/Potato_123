from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import aircraft, components, transactions, maintenance, dashboard, procurement

app = FastAPI(title="항공 정비 관리 API")

# CORS 허용 (frontend/*.html 정적 페이지에서 fetch()로 API 호출 가능하도록)
# 2026-07-26: GUI 1,8페이지(frontend/dashboard.html, frontend/procurement.html) 구현 추가
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(aircraft.router)
app.include_router(components.router)
app.include_router(transactions.router)
app.include_router(maintenance.router)
app.include_router(dashboard.router)
app.include_router(procurement.router)

@app.get("/")
def root():
    return {"message": "항공 정비 관리 API 작동 중"}
