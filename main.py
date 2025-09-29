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
from pywebpush import webpush, WebPushException
from models import PushSubscription  # PushSubscription 모델 import 추가
from datetime import datetime  # datetime import 추가
import json

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
app.include_router(companies.router)  # 간단한 버전으로 대체
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

# @app.get("/companies/{company_id}")
# def get_company(company_id: str, db: Session = Depends(get_db)):
#     company = db.query(Company).filter(Company.id == company_id).first()
#     if company is None:
#         raise HTTPException(status_code=404, detail="회사를 찾을 수 없습니다")
#     return company

# @app.get("/companies/search/{keyword}")
# def search_companies(keyword: str, db: Session = Depends(get_db)):
#     companies = db.query(Company).filter(
#         Company.name.ilike(f"%{keyword}%")
#     ).all()
#     return companies

# @app.post("/companies")
# def create_company(
#     company: dict, 
#     db: Session = Depends(get_db),
#     current_user: dict = Depends(get_current_user)
# ):
#     new_company = Company(**company)
#     db.add(new_company)
    
#     try:
#         db.commit()
#         db.refresh(new_company)
#         return new_company
#     except Exception as e:
#         db.rollback()
#         raise HTTPException(
#             status_code=500,
#             detail=f"회사 생성 중 오류가 발생했습니다: {str(e)}"
#         )

# 등급 관련 엔드포인트들 (main_newnew.py와 동일한 로직)
@app.get("/grades")
def get_grades(db: Session = Depends(get_db)):
    grades = db.query(Grade).all()
    return grades

# PDF 생성 관련 엔드포인트들
@app.get("/generate-company-invoice-pdf")
async def generate_company_invoice_pdf():
    return {"message": "Company Invoice PDF Generation Endpoint"}



VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY")
VAPID_CLAIMS = {"sub": "mailto:dev@sousei-group.com"}
subscriptions = []  # 실제 운영에서는 Supabase 같은 DB에 저장

@app.post("/push/save-subscription")
async def save_subscription(request: Request, db: Session = Depends(get_db)):
    try:
        data = await request.json()
        
        # 데이터 구조에 맞게 파싱
        user_id = data.get("userId")
        subscription_data = data.get("subscription", {})
        
        if not user_id or not subscription_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="userId와 subscription 데이터가 필요합니다"
            )
        
        endpoint = subscription_data.get("endpoint")
        keys = subscription_data.get("keys", {})
        expiration_time = subscription_data.get("expirationTime")
        
        if not endpoint or not keys.get("p256dh") or not keys.get("auth"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="subscription에 endpoint, p256dh, auth가 필요합니다"
            )
        
        # 기존 구독이 있는지 확인
        existing_subscription = db.query(PushSubscription).filter(
            PushSubscription.user_id == user_id,
            PushSubscription.endpoint == endpoint
        ).first()
        
        if existing_subscription:
            # 기존 구독 업데이트
            existing_subscription.p256dh = keys["p256dh"]
            existing_subscription.auth = keys["auth"]
            existing_subscription.expiration_time = expiration_time
            existing_subscription.updated_at = datetime.utcnow()
            db.commit()
            
            logger.info(f"기존 푸시 구독 업데이트: {user_id}")
            return {"status": "updated", "subscription_id": str(existing_subscription.id)}
        else:
            # 새 구독 생성
            new_subscription = PushSubscription(
                user_id=user_id,
                endpoint=endpoint,
                p256dh=keys["p256dh"],
                auth=keys["auth"],
                expiration_time=expiration_time
            )
            
            db.add(new_subscription)
            db.commit()
            db.refresh(new_subscription)
            
            logger.info(f"새 푸시 구독 등록: {user_id}")
            return {"status": "saved", "subscription_id": str(new_subscription.id)}
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"푸시 구독 저장 실패: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="푸시 구독 저장에 실패했습니다"
        )

async def send_push_notification_to_conversation(
    conversation_id: str, 
    sender_name: str, 
    message_body: str, 
    conversation_title: Optional[str] = None,
    exclude_user_id: Optional[str] = None
):
    """대화방의 모든 참여자에게 푸시 알림 전송"""
    try:
        db = SessionLocal()
        try:
            # 대화방 참여자 조회
            from models import ConversationMember
            members = db.query(ConversationMember).filter(
                ConversationMember.conversation_id == conversation_id
            ).all()
            
            # 메시지 본문이 너무 길면 잘라내기
            if len(message_body) > 100:
                message_body = message_body[:100] + "..."
            
            # 제목 설정
            if conversation_title:
                title = f"{conversation_title} - {sender_name}"
            else:
                title = f"{sender_name}님의 메시지"
            
            # 푸시 알림 전송
            for member in members:
                if exclude_user_id and member.user_id == exclude_user_id:
                    continue
                
                # 사용자의 활성 구독 조회
                subscriptions = db.query(PushSubscription).filter(
                    PushSubscription.user_id == member.user_id
                ).all()
                
                for subscription in subscriptions:
                    try:
                        subscription_info = {
                            "endpoint": subscription.endpoint,
                            "keys": {
                                "p256dh": subscription.p256dh,
                                "auth": subscription.auth
                            }
                        }
                        
                        payload = {
                            "title": title,
                            "body": message_body,
                            "icon": "/static/icons/icon-192x192.png",
                            "badge": "/static/icons/badge-72x72.png",
                            "url": f"/chat/{conversation_id}",
                            "data": {
                                "type": "chat_message",
                                "conversation_id": conversation_id,
                                "sender_name": sender_name
                            }
                        }
                        
                        webpush(
                            subscription_info=subscription_info,
                            data=json.dumps(payload),
                            vapid_private_key=VAPID_PRIVATE_KEY,
                            vapid_claims=VAPID_CLAIMS
                        )
                        
                    except WebPushException as ex:
                        logger.error(f"푸시 알림 전송 실패 (구독 ID: {subscription.id}): {ex}")
                        if ex.response and ex.response.status_code == 410:
                            subscription.is_active = False
                            db.commit()
                            logger.info(f"만료된 구독 비활성화: {subscription.id}")
                    except Exception as e:
                        logger.error(f"푸시 알림 전송 중 오류: {e}")
            
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"대화방 푸시 알림 전송 중 오류: {e}")

@app.post("/push/send-push")
async def send_push(request: Request):
    body = await request.json()
    message = body.get("message", "새 메시지가 도착했습니다!")

    for sub in subscriptions:
        try:
            webpush(
                subscription_info=sub,
                data='{"title":"알림","body":"' + message + '"}',
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=VAPID_CLAIMS
            )
        except WebPushException as ex:
            print("푸시 전송 실패:", ex)

    return {"status": "sent"}

# 기타 필요한 엔드포인트들...
# (필요에 따라 추가)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 
    