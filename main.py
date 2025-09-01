from fastapi import FastAPI, Depends, HTTPException, Query, status, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi import Request
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from typing import Optional, List
import os
import logging
from io import BytesIO
from urllib.parse import quote
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),  # 콘솔 출력
        logging.FileHandler('app.log')  # 파일 출력
    ]
)

# WebSocket 관련 로그 레벨 설정
logging.getLogger('utils.websocket_manager').setLevel(logging.INFO)
logging.getLogger('routers.websocket').setLevel(logging.INFO)
logging.getLogger('routers.chat').setLevel(logging.INFO)

logger = logging.getLogger(__name__)
logger.info("=== Sousei System Backend 시작 ===")

# 데이터베이스 및 모델 임포트
from database import SessionLocal, engine
from models import Base, Company, Student, BillingMonthlyItem, Grade
from utils.dependencies import get_current_user

# 라우터 임포트
from routers import auth, contact, residents, students, billing, elderly, companies, grades, buildings, rooms
from routers import users, upload, room_operations, room_charges, room_utilities, monthly_billing, elderly_care, database_logs
from routers import invoices, monthly_utilities, chat, websocket

# FastAPI 앱 생성
app = FastAPI(
    title="Sousei System Backend",
    description="Sousei System의 백엔드 API",
    version="1.0.0"
)

# CORS 미들웨어 설정
origins = [
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:5175",    
    "http://localhost:8000",     
    "http://127.0.0.1:3000",
    "http://127.0.0.1:8000",
    "http://127.0.0.1:8080",
    "https://system.sousei-group.com",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 정적 파일 및 템플릿 설정
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# 데이터베이스 테이블 생성
Base.metadata.create_all(bind=engine)

# 라우터 등록
app.include_router(auth.router)
app.include_router(students.router)
app.include_router(billing.router)
app.include_router(elderly.router)
# app.include_router(companies.router)  # 간단한 버전으로 대체
# app.include_router(grades.router)  # 간단한 버전으로 대체
app.include_router(buildings.router)
app.include_router(rooms.router)  # 모든 /rooms API가 여기에 통합됨

# 새로 추가된 라우터들
app.include_router(users.router)
app.include_router(upload.router)
# app.include_router(room_operations.router)  # /rooms API가 rooms.py로 이동됨
app.include_router(room_charges.router)
app.include_router(room_utilities.router)  # /rooms API가 rooms.py로 이동됨
app.include_router(monthly_billing.router)
app.include_router(elderly_care.router)
app.include_router(database_logs.router)

# 최종 추가된 라우터들
app.include_router(invoices.router)
app.include_router(residents.router)
app.include_router(contact.router)  # Contact 모델 수정 완료로 다시 활성화
# app.include_router(monthly_utilities.router)  # /rooms API가 rooms.py로 이동됨

# 채팅 라우터 추가
app.include_router(chat.router)

# WebSocket 라우터 추가
app.include_router(websocket.router)

# 루트 엔드포인트
@app.get("/")
async def root():
    return {"message": "Sousei System Backend API"}

# 헬스 체크
@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": "2024-01-01T00:00:00Z"}

# 회사 관련 엔드포인트들 (main_newnew.py와 동일한 로직)
@app.get("/companies")
def get_companies(db: Session = Depends(get_db)):
    companies = db.query(Company).all()
    return companies

@app.get("/companies/{company_id}")
def get_company(company_id: str, db: Session = Depends(get_db)):
    company = db.query(Company).filter(Company.id == company_id).first()
    if company is None:
        raise HTTPException(status_code=404, detail="회사를 찾을 수 없습니다")
    return company

@app.get("/companies/search/{keyword}")
def search_companies(keyword: str, db: Session = Depends(get_db)):
    companies = db.query(Company).filter(
        Company.name.ilike(f"%{keyword}%")
    ).all()
    return companies

@app.post("/companies")
def create_company(
    company: dict, 
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    new_company = Company(**company)
    db.add(new_company)
    
    try:
        db.commit()
        db.refresh(new_company)
        return new_company
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"회사 생성 중 오류가 발생했습니다: {str(e)}"
        )

# 등급 관련 엔드포인트들 (main_newnew.py와 동일한 로직)
@app.get("/grades")
def get_grades(db: Session = Depends(get_db)):
    grades = db.query(Grade).all()
    return grades

# PDF 생성 관련 엔드포인트들
@app.get("/generate-company-invoice-pdf")
async def generate_company_invoice_pdf():
    return {"message": "Company Invoice PDF Generation Endpoint"}

# 기타 필요한 엔드포인트들...
# (필요에 따라 추가)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 