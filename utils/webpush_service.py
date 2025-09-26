import os
import json
import logging
from typing import Dict, List, Optional
from pywebpush import webpush, WebPushException
from database import SessionLocal
from models import User, PushSubscription

logger = logging.getLogger(__name__)

class WebPushService:
    """웹 푸시 알림 서비스"""
    
    def __init__(self):
        # VAPID 키 설정 (환경변수에서 가져오기)
        self.vapid_private_key = os.getenv("VAPID_PRIVATE_KEY")
        self.vapid_public_key = os.getenv("VAPID_PUBLIC_KEY")
        self.vapid_claims = {
            "sub": os.getenv("VAPID_SUBJECT", "mailto:dev@sousei-group.com")
        }
        
        if not self.vapid_private_key or not self.vapid_public_key:
            logger.warning("VAPID 키가 설정되지 않았습니다. 웹 푸시가 작동하지 않을 수 있습니다.")
    
    async def send_notification(
        self, 
        subscription_info: Dict, 
        title: str, 
        body: str, 
        data: Optional[Dict] = None,
        icon: Optional[str] = None,
        badge: Optional[str] = None,
        url: Optional[str] = None
    ) -> bool:
        """단일 구독에 푸시 알림 전송"""
        try:
            # 푸시 페이로드 구성
            payload = {
                "title": title,
                "body": body,
                "icon": icon or "/static/icons/icon-192x192.png",
                "badge": badge or "/static/icons/badge-72x72.png",
                "url": url or "/",
                "data": data or {}
            }
            
            # 웹 푸시 전송
            webpush(
                subscription_info=subscription_info,
                data=json.dumps(payload),
                vapid_private_key=self.vapid_private_key,
                vapid_claims=self.vapid_claims
            )
            
            logger.info(f"푸시 알림 전송 성공: {title}")
            return True
            
        except WebPushException as e:
            logger.error(f"웹 푸시 전송 실패: {e}")
            if e.response and e.response.status_code == 410:
                # 구독이 만료된 경우
                logger.info("구독이 만료되었습니다. 데이터베이스에서 제거해야 합니다.")
                return False
            return False
            
        except Exception as e:
            logger.error(f"푸시 알림 전송 중 오류: {e}")
            return False
    
    async def send_to_user(
        self, 
        user_id: str, 
        title: str, 
        body: str, 
        data: Optional[Dict] = None,
        icon: Optional[str] = None,
        badge: Optional[str] = None,
        url: Optional[str] = None
    ) -> int:
        """특정 사용자의 모든 구독에 푸시 알림 전송"""
        db = SessionLocal()
        try:
            # 사용자의 모든 푸시 구독 조회
            subscriptions = db.query(PushSubscription).filter(
                PushSubscription.user_id == user_id,
                PushSubscription.is_active == True
            ).all()
            
            success_count = 0
            expired_subscriptions = []
            
            for subscription in subscriptions:
                subscription_info = {
                    "endpoint": subscription.endpoint,
                    "keys": {
                        "p256dh": subscription.p256dh_key,
                        "auth": subscription.auth_key
                    }
                }
                
                success = await self.send_notification(
                    subscription_info=subscription_info,
                    title=title,
                    body=body,
                    data=data,
                    icon=icon,
                    badge=badge,
                    url=url
                )
                
                if success:
                    success_count += 1
                else:
                    # 구독이 만료된 것으로 간주
                    expired_subscriptions.append(subscription.id)
            
            # 만료된 구독 제거
            if expired_subscriptions:
                db.query(PushSubscription).filter(
                    PushSubscription.id.in_(expired_subscriptions)
                ).update({"is_active": False})
                db.commit()
                logger.info(f"만료된 구독 {len(expired_subscriptions)}개 비활성화")
            
            return success_count
            
        except Exception as e:
            logger.error(f"사용자 푸시 알림 전송 중 오류: {e}")
            return 0
        finally:
            db.close()
    
    async def send_to_conversation(
        self, 
        conversation_id: str, 
        title: str, 
        body: str, 
        exclude_user_id: Optional[str] = None,
        data: Optional[Dict] = None,
        icon: Optional[str] = None,
        badge: Optional[str] = None,
        url: Optional[str] = None
    ) -> int:
        """대화방의 모든 참여자에게 푸시 알림 전송"""
        db = SessionLocal()
        try:
            # 대화방 참여자 조회
            from models import ConversationMember
            members = db.query(ConversationMember).filter(
                ConversationMember.conversation_id == conversation_id
            ).all()
            
            total_sent = 0
            
            for member in members:
                if exclude_user_id and member.user_id == exclude_user_id:
                    continue
                
                sent_count = await self.send_to_user(
                    user_id=member.user_id,
                    title=title,
                    body=body,
                    data=data,
                    icon=icon,
                    badge=badge,
                    url=url
                )
                total_sent += sent_count
            
            return total_sent
            
        except Exception as e:
            logger.error(f"대화방 푸시 알림 전송 중 오류: {e}")
            return 0
        finally:
            db.close()
    
    async def send_chat_notification(
        self, 
        conversation_id: str, 
        sender_name: str, 
        message_body: str, 
        conversation_title: Optional[str] = None,
        exclude_user_id: Optional[str] = None
    ) -> int:
        """채팅 메시지 푸시 알림 전송"""
        # 메시지 본문이 너무 길면 잘라내기
        if len(message_body) > 100:
            message_body = message_body[:100] + "..."
        
        # 제목 설정
        if conversation_title:
            title = f"{conversation_title} - {sender_name}"
        else:
            title = f"{sender_name}님의 메시지"
        
        # 데이터 설정
        data = {
            "type": "chat_message",
            "conversation_id": conversation_id,
            "sender_name": sender_name
        }
        
        # URL 설정 (채팅방으로 이동)
        url = f"/chat/{conversation_id}"
        
        return await self.send_to_conversation(
            conversation_id=conversation_id,
            title=title,
            body=message_body,
            exclude_user_id=exclude_user_id,
            data=data,
            url=url
        )
    
    def get_vapid_public_key(self) -> str:
        """VAPID 공개 키 반환 (클라이언트에서 사용)"""
        return self.vapid_public_key

# 전역 웹 푸시 서비스 인스턴스
webpush_service = WebPushService() 