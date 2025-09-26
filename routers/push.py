from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel
import logging

from database import SessionLocal
from models import PushSubscription
from utils.dependencies import get_current_user
from utils.webpush_service import webpush_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/push", tags=["웹 푸시"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class PushSubscriptionCreate(BaseModel):
    endpoint: str
    p256dh_key: str
    auth_key: str

class PushSubscriptionResponse(BaseModel):
    id: str
    endpoint: str
    is_active: bool
    created_at: str

@router.post("/subscribe", status_code=201)
async def subscribe_push(
    subscription: PushSubscriptionCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """웹 푸시 구독 등록"""
    try:
        # 기존 구독이 있는지 확인
        existing_subscription = db.query(PushSubscription).filter(
            PushSubscription.user_id == current_user["id"],
            PushSubscription.endpoint == subscription.endpoint
        ).first()
        
        if existing_subscription:
            # 기존 구독 업데이트
            existing_subscription.p256dh_key = subscription.p256dh_key
            existing_subscription.auth_key = subscription.auth_key
            existing_subscription.is_active = True
            db.commit()
            
            logger.info(f"기존 푸시 구독 업데이트: {current_user['id']}")
            return {
                "message": "푸시 구독이 업데이트되었습니다",
                "subscription_id": str(existing_subscription.id)
            }
        else:
            # 새 구독 생성
            new_subscription = PushSubscription(
                user_id=current_user["id"],
                endpoint=subscription.endpoint,
                p256dh_key=subscription.p256dh_key,
                auth_key=subscription.auth_key
            )
            
            db.add(new_subscription)
            db.commit()
            db.refresh(new_subscription)
            
            logger.info(f"새 푸시 구독 등록: {current_user['id']}")
            return {
                "message": "푸시 구독이 등록되었습니다",
                "subscription_id": str(new_subscription.id)
            }
            
    except Exception as e:
        logger.error(f"푸시 구독 등록 실패: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="푸시 구독 등록에 실패했습니다"
        )

@router.delete("/unsubscribe")
async def unsubscribe_push(
    endpoint: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """웹 푸시 구독 해제"""
    try:
        subscription = db.query(PushSubscription).filter(
            PushSubscription.user_id == current_user["id"],
            PushSubscription.endpoint == endpoint
        ).first()
        
        if not subscription:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="구독을 찾을 수 없습니다"
            )
        
        subscription.is_active = False
        db.commit()
        
        logger.info(f"푸시 구독 해제: {current_user['id']}")
        return {"message": "푸시 구독이 해제되었습니다"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"푸시 구독 해제 실패: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="푸시 구독 해제에 실패했습니다"
        )

@router.get("/subscriptions")
async def get_user_subscriptions(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """사용자의 푸시 구독 목록 조회"""
    try:
        subscriptions = db.query(PushSubscription).filter(
            PushSubscription.user_id == current_user["id"],
            PushSubscription.is_active == True
        ).all()
        
        return [
            PushSubscriptionResponse(
                id=str(sub.id),
                endpoint=sub.endpoint,
                is_active=sub.is_active,
                created_at=sub.created_at.isoformat()
            )
            for sub in subscriptions
        ]
        
    except Exception as e:
        logger.error(f"구독 목록 조회 실패: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="구독 목록 조회에 실패했습니다"
        )

@router.get("/vapid-public-key")
async def get_vapid_public_key():
    """VAPID 공개 키 조회 (클라이언트에서 사용)"""
    public_key = webpush_service.get_vapid_public_key()
    if not public_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="VAPID 공개 키가 설정되지 않았습니다"
        )
    
    return {"public_key": public_key}

@router.post("/test")
async def test_push_notification(
    title: str = "테스트 알림",
    body: str = "이것은 테스트 푸시 알림입니다",
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """푸시 알림 테스트 (개발용)"""
    try:
        sent_count = await webpush_service.send_to_user(
            user_id=current_user["id"],
            title=title,
            body=body,
            data={"type": "test"}
        )
        
        return {
            "message": f"테스트 푸시 알림을 {sent_count}개의 구독에 전송했습니다",
            "sent_count": sent_count
        }
        
    except Exception as e:
        logger.error(f"테스트 푸시 알림 전송 실패: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="테스트 푸시 알림 전송에 실패했습니다"
        ) 