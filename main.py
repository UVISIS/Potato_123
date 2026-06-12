from fastapi import FastAPI
from routers import aircraft, components, transactions, maintenance, dashboard, procurement

app = FastAPI(title="항공 정비 관리 API")

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