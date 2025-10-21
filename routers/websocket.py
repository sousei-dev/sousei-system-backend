from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException
from fastapi.security import HTTPBearer
from typing import Optional, Dict, List
import json
import base64
import logging
from datetime import datetime
from utils.websocket_manager import manager
from database import SessionLocal
from models import Conversation, ConversationMember, Message, Attachment, MessageRead
from routers.chat import supabase
from sqlalchemy.orm import Session

router = APIRouter(tags=["WebSocket"])

logger = logging.getLogger(__name__)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

async def get_unread_message_counts(user_id: str, db: Session) -> Dict[str, int]:
    """사용자의 미확인 메시지 수를 조회합니다. (chat.py의 로직과 동일 - message_reads 테이블 활용)"""
    try:
        # 사용자가 참여한 대화방 목록 조회
        user_conversations = db.query(ConversationMember).filter(
            ConversationMember.user_id == user_id
        ).all()
        
        unread_counts = {}
        
        # 각 대화방별로 미확인 메시지 수 계산
        for member in user_conversations:
            conversation_id = str(member.conversation_id)
            
            # 해당 대화방의 모든 메시지 조회
            messages = db.query(Message).filter(
                Message.conversation_id == conversation_id,
                Message.deleted_at.is_(None)  # 삭제되지 않은 메시지만
            ).all()
            
            if not messages:
                unread_counts[conversation_id] = 0
                continue
            
            # 해당 대화방의 모든 메시지 ID 수집
            message_ids = [str(msg.id) for msg in messages]
            
            # 한 번에 모든 읽음 상태 조회 (배치 쿼리)
            read_status_data = {}
            if message_ids:
                try:
                    read_statuses = db.query(MessageRead).filter(
                        MessageRead.message_id.in_(message_ids),
                        MessageRead.user_id == user_id
                    ).all()
                    
                    for read_status in read_statuses:
                        read_status_data[str(read_status.message_id)] = True
                        
                except Exception as e:
                    logger.warning(f"대화방 {conversation_id} 읽음 상태 배치 조회 실패: {e}")
            
            # 읽지 않은 메시지 수 계산 (chat.py와 동일한 로직)
            unread_count = 0
            for msg in messages:
                msg_id_str = str(msg.id)
                if (str(msg.sender_id) != user_id and 
                    msg_id_str not in read_status_data):
                    unread_count += 1
            
            unread_counts[conversation_id] = unread_count
        
        return unread_counts
        
    except Exception as e:
        logger.error(f"미확인 메시지 수 조회 중 오류: {e}")
        return {}

async def get_unread_notification_counts(user_id: str, db: Session) -> Dict[str, int]:
    """사용자의 미확인 알림 수를 조회합니다."""
    try:
        # 여기서는 예시로 구현
        # 실제로는 알림 테이블이 있다면 해당 테이블에서 조회
        # 예: Notification 테이블에서 is_read = false인 알림 수 조회
        
        # 현재는 빈 딕셔너리 반환 (나중에 알림 시스템이 구현되면 확장)
        return {
            "hospitalization": 0,  # 입원/퇴원 알림
            "contact": 0,         # 리포트 알림
            "system": 0           # 시스템 알림
        }
        
    except Exception as e:
        logger.error(f"미확인 알림 수 조회 중 오류: {e}")
        return {}

async def update_unread_counts_for_conversation(conversation_id: str, db: Session):
    """특정 대화방의 모든 멤버들에게 미확인 메시지 수를 업데이트합니다."""
    try:
        # 대화방의 모든 멤버 조회
        members = db.query(ConversationMember).filter(
            ConversationMember.conversation_id == conversation_id
        ).all()
        
        for member in members:
            user_id = member.user_id
            
            # 해당 사용자의 미확인 메시지 수 조회
            unread_message_counts = await get_unread_message_counts(user_id, db)
            unread_notification_counts = await get_unread_notification_counts(user_id, db)
            
            # 미확인 메시지 수 업데이트 전송
            await manager.send_personal_message({
                "type": "unread_counts_updated",
                "user_id": user_id,
                "timestamp": datetime.utcnow().isoformat(),
                "data": {
                    "messages": unread_message_counts,
                    "notifications": unread_notification_counts,
                    "total_unread_messages": sum(unread_message_counts.values()),
                    "total_unread_notifications": sum(unread_notification_counts.values())
                }
            }, user_id)
            
    except Exception as e:
        logger.error(f"미확인 메시지 수 업데이트 중 오류: {e}")

async def mark_messages_as_read(user_id: str, conversation_id: str, db: Session):
    """사용자가 특정 대화방의 메시지를 읽음 처리합니다. (chat.py의 mark_conversation_as_read 로직과 동일)"""
    try:
        # 대화방 존재 여부 및 참여 권한 확인
        conversation = db.query(Conversation).join(ConversationMember).filter(
            Conversation.id == conversation_id,
            ConversationMember.user_id == user_id
        ).first()
        
        if not conversation:
            logger.warning(f"대화방 {conversation_id}에 대한 접근 권한이 없습니다 (사용자: {user_id})")
            return
        
        # 읽지 않은 메시지들 조회
        unread_messages = db.query(Message).filter(
            Message.conversation_id == conversation_id,
            Message.sender_id != user_id,
            Message.deleted_at.is_(None)
        ).all()
        
        if not unread_messages:
            logger.info(f"대화방 {conversation_id}에 읽지 않은 메시지가 없습니다")
            return
        
        # 배치로 읽음 처리
        read_records = []
        for msg in unread_messages:
            # 이미 읽음 처리되었는지 확인
            existing_read = db.query(MessageRead).filter(
                MessageRead.message_id == msg.id,
                MessageRead.user_id == user_id
            ).first()
            
            if not existing_read:
                read_records.append(MessageRead(
                    message_id=msg.id,
                    user_id=user_id,
                    read_at=datetime.utcnow()
                ))
        
        if read_records:
            db.add_all(read_records)
            db.commit()
            
            logger.info(f"대화방 {conversation_id}에서 {len(read_records)}개 메시지를 읽음 처리했습니다")
            
            # 미확인 메시지 수 업데이트
            await update_unread_counts_for_conversation(conversation_id, db)
        else:
            logger.info(f"대화방 {conversation_id}에서 이미 모든 메시지가 읽음 처리되어 있습니다")
            
    except Exception as e:
        logger.error(f"메시지 읽음 처리 중 오류: {e}")

async def authenticate_websocket(websocket: WebSocket) -> Optional[str]:
    """WebSocket 연결 인증"""
    try:
        # 쿼리 파라미터에서 토큰 추출
        token = websocket.query_params.get("token")
        if not token:
            await websocket.close(code=4001, reason="토큰이 필요합니다")
            return None
        
        try:
            # JWT 토큰에서 사용자 ID 추출
            # JWT는 header.payload.signature 형식
            if '.' not in token or token.count('.') != 2:
                await websocket.close(code=4001, reason="유효하지 않은 JWT 형식입니다")
                return None
            
            # payload 부분 추출 (두 번째 부분)
            payload_part = token.split('.')[1]
            
            # Base64 디코딩 (패딩 추가)
            padding = 4 - len(payload_part) % 4
            if padding != 4:
                payload_part += '=' * padding
            
            try:
                payload_bytes = base64.urlsafe_b64decode(payload_part)
                payload = json.loads(payload_bytes.decode('utf-8'))
                
                # 사용자 ID 추출 (Supabase JWT의 'sub' 필드)
                user_id = payload.get('sub')
                if not user_id:
                    await websocket.close(code=4001, reason="토큰에 사용자 ID가 없습니다")
                    return None
                
                logger.info(f"WebSocket 인증 성공: 사용자 {user_id}")
                return user_id
                
            except (base64.binascii.Error, json.JSONDecodeError, UnicodeDecodeError) as decode_error:
                logger.error(f"JWT payload 디코딩 실패: {decode_error}")
                await websocket.close(code=4001, reason="토큰 디코딩에 실패했습니다")
                return None
            
        except Exception as e:
            logger.error(f"토큰 검증 실패: {e}")
            await websocket.close(code=4001, reason="토큰 검증에 실패했습니다")
            return None
            
    except Exception as e:
        logger.error(f"WebSocket 인증 실패: {e}")
        await websocket.close(code=4001, reason="인증에 실패했습니다")
        return None

@router.websocket("/ws/chat")
async def websocket_endpoint(websocket: WebSocket):
    """채팅 WebSocket 엔드포인트 (전역 연결)"""
    user_id = None
    
    try:
        # 인증
        user_id = await authenticate_websocket(websocket)
        if not user_id:
            return
        
        # WebSocket 연결
        await manager.connect(websocket, user_id)
        
        # 연결 성공 메시지
        await websocket.send_text(json.dumps({
            "type": "connection_established",
            "user_id": user_id,
            "timestamp": datetime.utcnow().isoformat(),
            "message": "WebSocket 연결이 성공적으로 설정되었습니다"
        }))
        
        # 사용자가 참여 중인 대화방들에 참여 및 미확인 메시지 수 조회
        db = SessionLocal()
        try:
            user_conversations = db.query(ConversationMember).filter(
                ConversationMember.user_id == user_id
            ).all()
            
            for conv_member in user_conversations:
                manager.join_conversation(user_id, str(conv_member.conversation_id))
            
            # 미확인 메시지 수 조회
            unread_message_counts = await get_unread_message_counts(user_id, db)
            unread_notification_counts = await get_unread_notification_counts(user_id, db)
            
            # 미확인 메시지 수 전송
            await websocket.send_text(json.dumps({
                "type": "unread_counts",
                "user_id": user_id,
                "timestamp": datetime.utcnow().isoformat(),
                "data": {
                    "messages": unread_message_counts,
                    "notifications": unread_notification_counts,
                    "total_unread_messages": sum(unread_message_counts.values()),
                    "total_unread_notifications": sum(unread_notification_counts.values())
                }
            }))
                
        except Exception as e:
            logger.error(f"사용자 대화방 정보 조회 실패: {e}")
        finally:
            db.close()
        
        # 메시지 처리 루프
        try:
            while True:
                data = await websocket.receive_text()
                message = json.loads(data)
                
                await handle_websocket_message(user_id, message)
                
        except WebSocketDisconnect:
            logger.info(f"사용자 {user_id} WebSocket 연결 해제")
        except Exception as e:
            logger.error(f"WebSocket 메시지 처리 중 오류: {e}")
        finally:
            manager.disconnect(user_id)
            
    except Exception as e:
        logger.error(f"WebSocket 연결 처리 중 오류: {e}")
        if user_id:
            manager.disconnect(user_id)

@router.websocket("/ws/chat/{conversation_id}")
async def websocket_room_endpoint(websocket: WebSocket, conversation_id: str):
    """채팅방별 WebSocket 엔드포인트 (채팅방별 연결)"""
    user_id = None
    
    try:
        # 인증
        user_id = await authenticate_websocket(websocket)
        if not user_id:
            return
        
        # 대화방 참여 권한 확인
        db = SessionLocal()
        try:
            conversation_member = db.query(ConversationMember).filter(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.user_id == user_id
            ).first()
            
            if not conversation_member:
                await websocket.close(code=4003, reason="대화방에 참여할 권한이 없습니다")
                return
                
        except Exception as e:
            logger.error(f"대화방 권한 확인 실패: {e}")
            await websocket.close(code=4004, reason="대화방 권한 확인에 실패했습니다")
            return
        finally:
            db.close()
        
        # 채팅방에 연결
        await manager.connect_to_room(websocket, user_id, conversation_id)
        
        # 연결 성공 메시지
        await websocket.send_text(json.dumps({
            "type": "room_connection_established",
            "conversation_id": conversation_id,
            "user_id": user_id,
            "timestamp": datetime.utcnow().isoformat(),
            "message": f"채팅방 {conversation_id}에 성공적으로 연결되었습니다"
        }))
        
        # 미확인 메시지 수 조회 및 전송
        try:
            unread_message_counts = await get_unread_message_counts(user_id, db)
            unread_notification_counts = await get_unread_notification_counts(user_id, db)
            
            # 미확인 메시지 수 전송
            await websocket.send_text(json.dumps({
                "type": "unread_counts",
                "user_id": user_id,
                "conversation_id": conversation_id,
                "timestamp": datetime.utcnow().isoformat(),
                "data": {
                    "messages": unread_message_counts,
                    "notifications": unread_notification_counts,
                    "total_unread_messages": sum(unread_message_counts.values()),
                    "total_unread_notifications": sum(unread_notification_counts.values())
                }
            }))
        except Exception as e:
            logger.error(f"미확인 메시지 수 조회 실패: {e}")
        
        # 메시지 처리 루프
        try:
            while True:
                data = await websocket.receive_text()
                message = json.loads(data)
                
                # 채팅방 관련 메시지만 처리
                if message.get("type") in ["send_message", "typing_start", "typing_stop", "mark_as_read"]:
                    await handle_room_websocket_message(websocket, user_id, conversation_id, message)
                else:
                    # 지원하지 않는 메시지 타입
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "message": f"지원하지 않는 메시지 타입: {message.get('type')}",
                        "timestamp": datetime.utcnow().isoformat()
                    }))
                
        except WebSocketDisconnect:
            logger.info(f"사용자 {user_id}가 채팅방 {conversation_id}에서 연결 해제")
        except Exception as e:
            logger.error(f"채팅방 WebSocket 메시지 처리 중 오류: {e}")
        finally:
            logger.info(f"=== 채팅방 {conversation_id}에서 사용자 {user_id} 연결 해제 처리 시작 ===")
            logger.info(f"  - 연결 해제 전 채팅방별 연결 상태: {conversation_id in manager.room_connections}")
            if conversation_id in manager.room_connections:
                logger.info(f"  - 연결 해제 전 채팅방에 연결된 사용자: {list(manager.room_connections[conversation_id].keys())}")
            
            manager.disconnect_from_room(user_id, conversation_id)
            
            logger.info(f"  - 연결 해제 후 채팅방별 연결 상태: {conversation_id in manager.room_connections}")
            if conversation_id in manager.room_connections:
                logger.info(f"  - 연결 해제 후 채팅방에 연결된 사용자: {list(manager.room_connections[conversation_id].keys())}")
            else:
                logger.info(f"  - 채팅방이 완전히 제거됨")
            
    except Exception as e:
        logger.error(f"채팅방 WebSocket 연결 처리 중 오류: {e}")
        if user_id:
            logger.info(f"=== 예외 발생으로 인한 사용자 {user_id} 연결 해제 처리 ===")
            manager.disconnect_from_room(user_id, conversation_id)

async def handle_websocket_message(user_id: str, message_data: dict):
    """WebSocket 메시지 처리 (전역 연결)"""
    message_type = message_data.get("type")
    
    if message_type == "join_conversation":
        conversation_id = message_data.get("conversation_id")
        if conversation_id:
            manager.join_conversation(user_id, conversation_id)
            await manager.send_personal_message({
                "type": "conversation_joined",
                "conversation_id": conversation_id,
                "timestamp": datetime.utcnow().isoformat()
            }, user_id)
    
    elif message_type == "leave_conversation":
        conversation_id = message_data.get("conversation_id")
        if conversation_id:
            manager.leave_conversation(user_id, conversation_id)
            await manager.send_personal_message({
                "type": "conversation_left",
                "conversation_id": conversation_id,
                "timestamp": datetime.utcnow().isoformat()
            }, user_id)
    
    elif message_type == "typing_start":
        conversation_id = message_data.get("conversation_id")
        if conversation_id:
            await manager.send_to_conversation({
                "type": "typing_start",
                "user_id": user_id,
                "conversation_id": conversation_id,
                "timestamp": datetime.utcnow().isoformat()
            }, conversation_id, exclude_user=user_id)
    
    elif message_type == "typing_stop":
        conversation_id = message_data.get("conversation_id")
        if conversation_id:
            await manager.send_to_conversation({
                "type": "typing_stop",
                "user_id": user_id,
                "conversation_id": conversation_id,
                "timestamp": datetime.utcnow().isoformat()
            }, conversation_id, exclude_user=user_id)
    
    elif message_type == "send_message":
        # 전역 연결에서는 메시지 전송 처리하지 않음
        # 채팅방별 연결에서만 처리
        pass

async def handle_room_websocket_message(websocket: WebSocket, user_id: str, conversation_id: str, message_data: dict):
    """채팅방별 WebSocket 메시지 처리"""
    message_type = message_data.get("type")
    
    if message_type == "send_message":
        # 메시지 전송 요청 (WebSocket을 통한 직접 메시지 전송)
        message_body = message_data.get("body")
        
        if message_body:
            db = SessionLocal()
            try:
                # 메시지 생성
                new_message = Message(
                    conversation_id=conversation_id,
                    sender_id=user_id,
                    body=message_body,
                    parent_id=message_data.get("parent_id")
                )
                
                db.add(new_message)
                db.commit()
                db.refresh(new_message)
                
                # 첨부파일 처리 (있는 경우)
                attachments = message_data.get("attachments", [])
                if attachments:
                    for attachment_data in attachments:
                        attachment = Attachment(
                            message_id=new_message.id,
                            bucket=attachment_data.get("bucket", "chat-attachments"),
                            path=attachment_data.get("path"),
                            mime_type=attachment_data.get("mime_type"),
                            size_bytes=attachment_data.get("size_bytes", 0)
                        )
                        db.add(attachment)
                    
                    db.commit()
                
                # 발신자 프로필 정보 조회
                sender_info = None
                try:
                    if supabase:
                        profile_result = supabase.table('profiles').select('*').eq('id', user_id).execute()
                        if profile_result.data:
                            profile = profile_result.data[0]
                            sender_info = {
                                "id": user_id,
                                "name": profile.get('name', '사용자'),
                                "avatar": profile.get('avatar_url', ''),
                                "role": profile.get('role', 'user'),
                                "department": profile.get('department', '')
                            }
                except Exception as profile_error:
                    logger.warning(f"발신자 {user_id}의 프로필 정보 조회 실패: {profile_error}")
                
                # 완전한 메시지 데이터 준비
                complete_message_data = {
                    "id": str(new_message.id),
                    "conversation_id": conversation_id,
                    "sender_id": user_id,
                    "body": message_body,
                    "parent_id": message_data.get("parent_id"),
                    "created_at": new_message.created_at.isoformat(),
                    "edited_at": None,
                    "deleted_at": None,
                    "is_own_message": False,  # 수신자용
                    "message_type": "other",
                    "alignment": "left",
                    "sender_info": sender_info,
                    "sender_name": sender_info["name"] if sender_info else "사용자",
                    "sender_avatar": sender_info["avatar"] if sender_info else "",
                    "sender_role": sender_info["role"] if sender_info else "user",
                    "attachments": attachments,
                    "reactions": [],
                    "is_read": False,
                    "show_avatar": True,
                    "show_name": True,
                    "css_class": "message-other message-left"
                }
                
                websocket_message = {
                    "type": "new_message",
                    "message": complete_message_data,
                    "conversation_id": conversation_id,
                    "sender_id": user_id,
                    "timestamp": datetime.utcnow().isoformat()
                }
                
                # 채팅방의 다른 멤버들에게 메시지 전송
                await manager.send_room_message(
                    websocket_message, conversation_id, exclude_user=user_id
                )
                
                # 발신자에게 전송 확인 메시지
                await manager.send_room_personal_message({
                    "type": "message_sent",
                    "message": complete_message_data,
                    "conversation_id": conversation_id,
                    "timestamp": datetime.utcnow().isoformat()
                }, user_id, conversation_id)
                
                # 미확인 메시지 수 업데이트 (비동기로 처리)
                try:
                    await update_unread_counts_for_conversation(conversation_id, db)
                except Exception as update_error:
                    logger.error(f"미확인 메시지 수 업데이트 실패: {update_error}")
                
                logger.info(f"채팅방 {conversation_id}에서 메시지 {new_message.id} 전송 완료")
                
            except Exception as e:
                logger.error(f"채팅방 메시지 전송 중 오류: {e}")
                await manager.send_room_personal_message({
                    "type": "error",
                    "message": f"메시지 전송 중 오류가 발생했습니다: {str(e)}",
                    "timestamp": datetime.utcnow().isoformat()
                }, user_id, conversation_id)
            finally:
                db.close()
        else:
            await manager.send_room_personal_message({
                "type": "error",
                "message": "메시지 내용이 필요합니다",
                "timestamp": datetime.utcnow().isoformat()
            }, user_id, conversation_id)
    
    elif message_type == "typing_start":
        # 타이핑 시작 알림
        await manager.send_room_message({
            "type": "typing_start",
            "user_id": user_id,
            "conversation_id": conversation_id,
            "timestamp": datetime.utcnow().isoformat()
        }, conversation_id, exclude_user=user_id)
    
    elif message_type == "typing_stop":
        # 타이핑 중지 알림
        await manager.send_room_message({
            "type": "typing_stop",
            "user_id": user_id,
            "conversation_id": conversation_id,
            "timestamp": datetime.utcnow().isoformat()
        }, conversation_id, exclude_user=user_id)
    
    elif message_type == "mark_as_read":
        # 메시지 읽음 처리
        db = SessionLocal()
        try:
            await mark_messages_as_read(user_id, conversation_id, db)
            
            # 읽음 처리 완료 알림
            await manager.send_room_personal_message({
                "type": "messages_marked_as_read",
                "user_id": user_id,
                "conversation_id": conversation_id,
                "timestamp": datetime.utcnow().isoformat()
            }, user_id, conversation_id)
            
        except Exception as e:
            logger.error(f"메시지 읽음 처리 중 오류: {e}")
            await manager.send_room_personal_message({
                "type": "error",
                "message": f"메시지 읽음 처리 중 오류가 발생했습니다: {str(e)}",
                "timestamp": datetime.utcnow().isoformat()
            }, user_id, conversation_id)
        finally:
            db.close()
    
    else:
        # 지원하지 않는 메시지 타입
        await manager.send_room_personal_message({
            "type": "error",
            "message": f"지원하지 않는 메시지 타입: {message_type}",
            "timestamp": datetime.utcnow().isoformat()
        }, user_id, conversation_id)

# ===== WebSocket 상태 조회 API =====

@router.get("/ws/status")
async def get_websocket_status():
    """WebSocket 연결 상태 조회"""
    return {
        "online_users_count": manager.get_online_users_count(),
        "active_conversations_count": manager.get_active_conversations_count(),
        "timestamp": datetime.utcnow().isoformat()
    }

@router.get("/ws/users/{user_id}/status")
async def get_user_websocket_status(user_id: str):
    """특정 사용자의 WebSocket 연결 상태 조회"""
    is_online = manager.get_connection_status(user_id)
    user_conversations = list(manager.get_user_conversations(user_id))
    
    return {
        "user_id": user_id,
        "is_online": is_online,
        "conversations": user_conversations,
        "timestamp": datetime.utcnow().isoformat()
    }

@router.get("/ws/debug")
async def get_websocket_debug_info():
    """WebSocket 디버깅 정보 조회"""
    return {
        "total_connections": len(manager.active_connections),
        "active_connections": list(manager.active_connections.keys()),
        "room_connections": {
            conv_id: {
                "user_count": len(users),
                "users": list(users.keys())
            }
            for conv_id, users in manager.room_connections.items()
        },
        "conversation_members": {
            conv_id: list(members) 
            for conv_id, members in manager.conversation_members.items()
        },
        "user_conversations": {
            user_id: list(conversations) 
            for user_id, conversations in manager.user_conversations.items()
        },
        "user_room_status": {
            user_id: list(rooms) 
            for user_id, rooms in manager.user_room_status.items()
        },
        "timestamp": datetime.utcnow().isoformat()
    }

@router.get("/ws/conversations/{conversation_id}/online-status")
async def get_conversation_online_status(conversation_id: str):
    """특정 대화방의 온라인 상태 조회"""
    return {
        "conversation_id": conversation_id,
        "total_members": len(manager.get_conversation_members(conversation_id)),
        "connected_users": manager.get_room_connections_count(conversation_id),
        "connection_info": manager.get_room_connection_info(conversation_id),
        "timestamp": datetime.utcnow().isoformat()
    }

@router.get("/ws/rooms/{conversation_id}/status")
async def get_room_status(conversation_id: str):
    """특정 채팅방의 상세 연결 상태 조회"""
    return {
        "conversation_id": conversation_id,
        "room_connections": {
            "total_users": manager.get_room_connections_count(conversation_id),
            "connected_users": list(manager.room_connections.get(conversation_id, {}).keys()),
            "conversation_members": list(manager.get_conversation_members(conversation_id))
        },
        "timestamp": datetime.utcnow().isoformat()
    }

@router.get("/ws/test/connection-status")
async def test_connection_status():
    """전체 WebSocket 연결 상태 테스트"""
    return {
        "total_global_connections": len(manager.active_connections),
        "global_connections": list(manager.active_connections.keys()),
        "total_room_connections": sum(len(users) for users in manager.room_connections.values()),
        "room_connections": {
            conv_id: {
                "user_count": len(users),
                "users": list(users.keys())
            }
            for conv_id, users in manager.room_connections.items()
        },
        "conversation_members": {
            conv_id: list(members) 
            for conv_id, members in manager.conversation_members.items()
        },
        "user_room_status": {
            user_id: list(rooms) 
            for user_id, rooms in manager.user_room_status.items()
        },
        "timestamp": datetime.utcnow().isoformat()
    }
