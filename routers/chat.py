from fastapi import APIRouter, Depends, HTTPException, Query, status, UploadFile, File, Form
from fastapi.security import HTTPBearer
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, or_, and_, desc
from typing import Optional, List, Union
import logging
from database import SessionLocal, engine
from models import (
    Conversation, ConversationMember, Message, MessageRead, 
    Attachment, Reaction, Student, Company, Grade
)
from schemas import (
    ConversationCreate, ConversationUpdate, ConversationResponse,
    ConversationMemberCreate, ConversationMemberUpdate, ConversationMemberResponse,
    MessageCreate, MessageUpdate, MessageResponse, MessageReadCreate,
    AttachmentCreate, AttachmentResponse, ReactionCreate, ReactionResponse,
    ConversationListResponse, MessageListResponse
)
from datetime import datetime, date, timedelta
import uuid
from database_log import create_database_log
import os
from supabase import create_client
from utils.dependencies import get_current_user
from utils.websocket_manager import manager

# 로거 설정
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["채팅"])

# Supabase 설정
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
supabase_storage = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY) if SUPABASE_SERVICE_KEY else None

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_token_header(token: str = Depends(HTTPBearer())):
    return token.credentials

# ===== 대화 관련 API =====

@router.post("/conversations", status_code=201)
async def create_conversation(
    conversation: ConversationCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """새로운 대화 생성 (DM 또는 그룹)"""
    try:
        # 1:1 채팅인 경우 이미 존재하는 대화방이 있는지 확인
        if not conversation.is_group and len(conversation.member_ids) == 1:
            # 현재 사용자와 상대방으로 구성된 기존 대화방 찾기
            existing_conversation = db.query(Conversation).join(ConversationMember).filter(
                Conversation.is_group == False,
                ConversationMember.user_id.in_([current_user["id"], conversation.member_ids[0]])
            ).group_by(Conversation.id).having(
                func.count(ConversationMember.user_id) == 2
            ).first()
            
            if existing_conversation:
                # 기존 대화방 정보 반환
                return {
                    "message": "이미 존재하는 1:1 대화방입니다",
                    "id": str(existing_conversation.id),
                    "title": existing_conversation.title,
                    "is_group": existing_conversation.is_group,
                    "existing": True
                }
        
        # 그룹 채팅인 경우 같은 제목과 멤버로 구성된 대화방이 있는지 확인
        elif conversation.is_group and conversation.title:
            # 같은 제목의 그룹 채팅방이 있는지 확인
            existing_group = db.query(Conversation).filter(
                Conversation.is_group == True,
                Conversation.title == conversation.title,
                Conversation.created_by == current_user["id"]
            ).first()
            
            if existing_group:
                # 기존 그룹 채팅방 정보 반환
                return {
                    "message": "이미 존재하는 그룹 채팅방입니다",
                    "id": str(existing_group.id),
                    "title": existing_group.title,
                    "is_group": existing_group.is_group,
                    "existing": True
                }
        
        # 대화 생성
        new_conversation = Conversation(
            id=str(uuid.uuid4()),
            title=conversation.title,
            is_group=conversation.is_group,
            created_by=current_user["id"]
        )
        db.add(new_conversation)
        db.flush()  # ID 생성
        
        # 생성자를 멤버로 추가
        creator_member = ConversationMember(
            conversation_id=new_conversation.id,
            user_id=current_user["id"],
            role="admin"
        )
        db.add(creator_member)
        
        # 다른 멤버들 추가
        for user_id in conversation.member_ids:
            if user_id != current_user["id"]:  # 생성자는 이미 추가됨
                member = ConversationMember(
                    conversation_id=new_conversation.id,
                    user_id=user_id,
                    role="member"
                )
                db.add(member)
        
        db.commit()
        db.refresh(new_conversation)
        
        # WebSocket을 통해 새 채팅방 생성 알림 전송
        try:
            # 새 채팅방 정보를 모든 멤버들에게 전송
            conversation_data = {
                "id": str(new_conversation.id),
                "title": new_conversation.title,
                "is_group": new_conversation.is_group,
                "created_by": str(new_conversation.created_by),
                "created_at": new_conversation.created_at.isoformat(),
                "member_count": len(conversation.member_ids) + 1,
                "participants": []
            }
            
            # 참여자 정보 추가 (프로필 정보 조회)
            participants = []
            all_member_ids = [current_user["id"]] + conversation.member_ids
            
            if supabase and all_member_ids:
                try:
                    profile_result = supabase.table('profiles').select('*').in_('id', all_member_ids).execute()
                    if profile_result.data:
                        profiles_data = {profile['id']: profile for profile in profile_result.data}
                        
                        for member_id in all_member_ids:
                            if str(member_id) != str(current_user["id"]):  # 현재 사용자 제외
                                profile = profiles_data.get(str(member_id), {})
                                participants.append({
                                    "id": str(member_id),
                                    "name": profile.get('name', f'사용자 {str(member_id)[:8]}') if profile else f'사용자 {str(member_id)[:8]}',
                                    "avatar": profile.get('avatar', '') if profile else '',
                                    "role": "admin" if str(member_id) == str(current_user["id"]) else "member"
                                })
                except Exception as profile_error:
                    logger.warning(f"참여자 프로필 정보 조회 실패: {profile_error}")
            
            conversation_data["participants"] = participants
            
            # WebSocket 메시지 데이터
            websocket_message = {
                "type": "conversation_created",
                "conversation": conversation_data,
                "created_by": current_user["id"],
                "timestamp": datetime.utcnow().isoformat()
            }
            
            # 모든 멤버들에게 새 채팅방 생성 알림 전송
            for member_id in all_member_ids:
                try:
                    await manager.send_personal_message(
                        websocket_message, 
                        str(member_id)
                    )
                    print(f"새 채팅방 생성 알림 전송 완료: {member_id}")
                except Exception as member_error:
                    logger.warning(f"멤버 {member_id}에게 알림 전송 실패: {member_error}")
            
            # 채팅 리스트 업데이트 전송 (모든 멤버에게)
            try:
                chat_list_update_data = {
                    "conversation": conversation_data,
                    "action": "created",
                    "timestamp": datetime.utcnow().isoformat()
                }
                
                for member_id in all_member_ids:
                    await manager.send_chat_list_update(
                        str(new_conversation.id),
                        "conversation_created",
                        chat_list_update_data,
                        target_user=str(member_id)
                    )
                
                print(f"채팅 리스트 업데이트 전송 완료: {len(all_member_ids)}명")
                
            except Exception as update_error:
                logger.error(f"채팅 리스트 업데이트 전송 실패: {update_error}")
            
            
        except Exception as ws_error:
            logger.error(f"WebSocket 채팅방 생성 알림 전송 실패: {ws_error}")
            # WebSocket 실패해도 HTTP 응답은 성공
        
        # 데이터베이스 로그 생성
        try:
            create_database_log(
                db=db,
                table_name="conversations",
                record_id=str(new_conversation.id),
                action="CREATE",
                user_id=current_user["id"],
                new_values={
                    "title": conversation.title,
                    "is_group": conversation.is_group,
                    "member_count": len(conversation.member_ids) + 1
                },
                changed_fields=["title", "is_group", "members"],
                note=f"新規会話作成 - {'グループ' if conversation.is_group else 'DM'}: {conversation.title or '無題'}"
            )
        except Exception as log_error:
            print(f"로그 생성 중 오류: {log_error}")
        
        return {
            "message": "대화가 성공적으로 생성되었습니다",
            "id": str(new_conversation.id),
            "title": new_conversation.title,
            "is_group": new_conversation.is_group,
            "member_count": len(conversation.member_ids) + 1
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"대화 생성 중 오류가 발생했습니다: {str(e)}"
        )

@router.get("/conversations")
def get_conversations(
    page: int = Query(1, description="페이지 번호", ge=1),
    page_size: int = Query(20, description="페이지당 항목 수", ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """사용자의 대화 목록 조회"""
    try:
        # 사용자가 참여 중인 대화들 조회
        query = db.query(Conversation).join(ConversationMember).filter(
            ConversationMember.user_id == current_user["id"]
        ).options(
            joinedload(Conversation.members),
            joinedload(Conversation.messages)
        )
        
        # 전체 항목 수 계산
        total_count = query.count()
        
        # 페이지네이션 적용
        conversations = query.offset((page - 1) * page_size).limit(page_size).all()
        
        # 전체 페이지 수 계산
        total_pages = (total_count + page_size - 1) // page_size
        
        # 응답 데이터 준비
        result = []
        
        # 1. 모든 대화방의 고유한 참여자 ID들 수집 (배치 쿼리용)
        all_member_ids = set()
        for conv in conversations:
            for member in conv.members:
                if str(member.user_id) != str(current_user["id"]):  # 현재 사용자 제외
                    all_member_ids.add(str(member.user_id))
        
        # 2. 한 번에 모든 프로필 정보 조회 (배치 쿼리)
        profiles_data = {}
        if supabase and all_member_ids:
            try:
                member_ids_list = list(all_member_ids)
                profile_result = supabase.table('profiles').select('*').in_('id', member_ids_list).execute()
                if profile_result.data:
                    for profile in profile_result.data:
                        profiles_data[profile['id']] = profile
                print(f"대화방 프로필 배치 조회 성공: {len(profiles_data)}개 프로필")
            except Exception as e:
                logger.warning(f"대화방 프로필 배치 조회 실패: {e}")
        
        # 3. 모든 대화방의 메시지 ID 수집 (읽음 상태 배치 조회용)
        all_message_ids = []
        conversation_message_map = {}  # 대화방별 메시지 ID 매핑
        
        for conv in conversations:
            if conv.messages:
                conv_message_ids = [str(msg.id) for msg in conv.messages]
                all_message_ids.extend(conv_message_ids)
                conversation_message_map[str(conv.id)] = conv_message_ids
        
        # 4. 한 번에 모든 읽음 상태 조회 (배치 쿼리)
        read_status_data = {}
        if all_message_ids:
            try:
                read_statuses = db.query(MessageRead).filter(
                    MessageRead.message_id.in_(all_message_ids),
                    MessageRead.user_id == current_user["id"]
                ).all()
                
                for read_status in read_statuses:
                    read_status_data[str(read_status.message_id)] = True
                
                print(f"대화방 읽음 상태 배치 조회 성공: {len(read_status_data)}개 메시지")
            except Exception as e:
                logger.warning(f"대화방 읽음 상태 배치 조회 실패: {e}")
        
        # 5. 각 대화방의 마지막 메시지 시간을 기준으로 정렬
        conversations_with_last_message = []
        for conv in conversations:
            last_message_time = None
            if conv.messages:
                last_msg = max(conv.messages, key=lambda x: x.created_at)
                last_message_time = last_msg.created_at
            else:
                # 메시지가 없는 대화방은 생성 시간으로 정렬
                last_message_time = conv.created_at
            
            conversations_with_last_message.append((conv, last_message_time))
        
        # 마지막 메시지 시간 기준으로 내림차순 정렬 (최신 순)
        conversations_with_last_message.sort(key=lambda x: x[1], reverse=True)
        
        # 정렬된 대화방들로 결과 구성
        for conv, last_message_time in conversations_with_last_message:
            # 대화방 제목 결정
            conversation_title = conv.title
            
            # 그룹 채팅이 아니고 제목이 없는 경우, 상대방 이름으로 설정
            if not conv.is_group and not conv.title:
                # 현재 사용자를 제외한 다른 참여자 찾기
                other_members = [m for m in conv.members if str(m.user_id) != str(current_user["id"])]
                
                if other_members:
                    # 첫 번째 상대방의 이름을 가져오기 (배치 쿼리로 가져온 프로필 정보 사용)
                    other_user_id = str(other_members[0].user_id)
                    profile = profiles_data.get(other_user_id, {})
                    
                    if profile:
                        conversation_title = profile.get('name', f'사용자 {other_user_id[:8]}')
                    else:
                        conversation_title = f'사용자 {other_user_id[:8]}'
                else:
                    conversation_title = "대화방"
            
            # 마지막 메시지 정보
            last_message = None
            if conv.messages:
                last_msg = max(conv.messages, key=lambda x: x.created_at)
                last_message = {
                    "id": str(last_msg.id),
                    "body": last_msg.body,
                    "sender_id": str(last_msg.sender_id),  # UUID를 문자열로 변환
                    "created_at": last_msg.created_at
                }
            
            # 읽지 않은 메시지 수 계산 (message_reads 테이블 활용)
            unread_count = 0
            if conv.messages:
                conv_message_ids = conversation_message_map.get(str(conv.id), [])
                # 현재 사용자가 보낸 메시지가 아닌 메시지 중에서 읽지 않은 메시지 수 계산
                for msg in conv.messages:
                    msg_id_str = str(msg.id)
                    if (str(msg.sender_id) != str(current_user["id"]) and 
                        msg_id_str not in read_status_data):
                        unread_count += 1
            
            # 참여자 정보 (캐시된 프로필 정보 사용)
            participants = []
            for member in conv.members:
                if str(member.user_id) != str(current_user["id"]):  # 현재 사용자 제외
                    member_id_str = str(member.user_id)
                    profile = profiles_data.get(member_id_str, {})
                    
                    participants.append({
                        "id": member_id_str,
                        "name": profile.get('name', f'사용자 {member_id_str[:8]}') if profile else f'사용자 {member_id_str[:8]}',
                        "avatar": profile.get('avatar', '') if profile else '',
                        "role": member.role
                    })
            
            conversation_data = {
                "id": str(conv.id),
                "title": conversation_title,
                "is_group": conv.is_group,
                "created_by": str(conv.created_by),  # UUID를 문자열로 변환
                "created_at": conv.created_at,
                "member_count": len(conv.members),
                "participants": participants,  # 참여자 정보 추가
                "last_message": last_message,
                "unread_count": unread_count
            }
            result.append(conversation_data)
        
        return ConversationListResponse(
            conversations=result,
            total=total_count,
            page=page,
            page_size=page_size,
            total_pages=total_pages
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"대화 목록 조회 중 오류가 발생했습니다: {str(e)}"
        )

@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """특정 대화 정보 조회"""
    try:
        # 대화 존재 여부 및 참여 권한 확인
        conversation = db.query(Conversation).join(ConversationMember).filter(
            Conversation.id == conversation_id,
            ConversationMember.user_id == current_user["id"]
        ).options(
            joinedload(Conversation.members),
            joinedload(Conversation.messages)
        ).first()
        
        if not conversation:
            raise HTTPException(
                status_code=404,
                detail="대화를 찾을 수 없거나 접근 권한이 없습니다"
            )
        
        # 마지막 메시지 정보
        last_message = None
        if conversation.messages:
            last_msg = max(conversation.messages, key=lambda x: x.created_at)
            last_message = {
                "id": str(last_msg.id),
                "body": last_msg.body,
                "sender_id": str(last_msg.sender_id),  # UUID를 문자열로 변환
                "created_at": last_msg.created_at
            }
        
        # 대화방 제목 결정 (title이 없으면 상대방 이름으로 설정)
        conversation_title = conversation.title
        
        # 그룹 채팅이 아니고 제목이 없는 경우, 상대방 이름으로 설정
        if not conversation.is_group and not conversation.title:
            # 현재 사용자를 제외한 다른 참여자 찾기
            other_members = [m for m in conversation.members if str(m.user_id) != str(current_user["id"])]
            
            if other_members:
                # 첫 번째 상대방의 이름을 가져오기 (Supabase profiles에서)
                other_user_id = str(other_members[0].user_id)
                try:
                    if supabase:
                        profile_result = supabase.table('profiles').select('*').eq('id', other_user_id).execute()
                        if profile_result.data:
                            profile = profile_result.data[0]
                            conversation_title = profile.get('name', f'사용자 {other_user_id[:8]}')
                        else:
                            conversation_title = f'사용자 {other_user_id[:8]}'
                    else:
                        conversation_title = f'사용자 {other_user_id[:8]}'
                except Exception as profile_error:
                    logger.warning(f"상대방 프로필 정보 조회 실패: {profile_error}")
                    conversation_title = f'사용자 {other_user_id[:8]}'
            else:
                conversation_title = "대화방"
        
        # 읽지 않은 메시지 수 계산
        unread_count = 0
        user_member = next((m for m in conversation.members if m.user_id == current_user["id"]), None)
        if user_member and user_member.last_read_at:
            unread_count = db.query(Message).filter(
                Message.conversation_id == conversation_id,
                Message.created_at > user_member.last_read_at,
                Message.sender_id != current_user["id"]
            ).count()
        
        return ConversationResponse(
            id=str(conversation.id),
            title=conversation_title,  # 동적으로 설정된 제목 사용
            is_group=conversation.is_group,
            created_by=str(conversation.created_by),  # UUID를 문자열로 변환
            created_at=conversation.created_at,
            member_count=len(conversation.members),
            last_message=last_message,
            unread_count=unread_count
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"대화 정보 조회 중 오류가 발생했습니다: {str(e)}"
        )

@router.put("/conversations/{conversation_id}")
async def update_conversation(
    conversation_id: str,
    conversation_update: ConversationUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """대화 정보 수정 (제목, 그룹 설정 등)"""
    try:
        # 대화 존재 여부 및 관리자 권한 확인
        conversation = db.query(Conversation).join(ConversationMember).filter(
            Conversation.id == conversation_id,
            ConversationMember.user_id == current_user["id"],
            ConversationMember.role == "admin"
        ).first()
        
        if not conversation:
            raise HTTPException(
                status_code=404,
                detail="대화를 찾을 수 없거나 관리자 권한이 없습니다"
            )
        
        # 기존 값 저장 (로그용)
        old_values = {
            "title": conversation.title,
            "is_group": conversation.is_group
        }
        
        # 대화 정보 업데이트
        update_data = conversation_update.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(conversation, field, value)
        
        db.commit()
        db.refresh(conversation)
        
        # WebSocket을 통해 대화방 업데이트 알림 전송
        try:
            conversation_update_data = {
                "title": conversation.title,
                "is_group": conversation.is_group,
                "updated_fields": list(update_data.keys()),
                "updated_by": current_user["id"]
            }
            
            await manager.send_conversation_update(
                conversation_id,
                "conversation_updated",
                conversation_update_data
            )
            print(f"대화방 업데이트 알림 전송 완료: {conversation_id}")
            
        except Exception as ws_error:
            logger.error(f"WebSocket 대화방 업데이트 알림 전송 실패: {ws_error}")
        
        # 데이터베이스 로그 생성
        try:
            create_database_log(
                db=db,
                table_name="conversations",
                record_id=str(conversation.id),
                action="UPDATE",
                user_id=current_user["id"],
                old_values=old_values,
                new_values=update_data,
                changed_fields=list(update_data.keys()),
                note=f"会話情報更新 - {conversation.title or '無題'}"
            )
        except Exception as log_error:
            print(f"로그 생성 중 오류: {log_error}")
        
        return {
            "message": "대화 정보가 성공적으로 업데이트되었습니다",
            "conversation_id": str(conversation.id),
            "title": conversation.title,
            "is_group": conversation.is_group
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"대화 정보 업데이트 중 오류가 발생했습니다: {str(e)}"
        )

# ===== 메시지 관련 API =====

@router.post("/conversations/{conversation_id}/messages", response_model=MessageResponse)
async def create_message(
    conversation_id: str,
    body: Optional[str] = Form(None),
    parent_id: Optional[str] = Form(None),
    attachments: List[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):

    """새 메시지 생성"""
    try:
        # 대화방 존재 여부 및 참여 권한 확인
        conversation = db.query(Conversation).join(ConversationMember).filter(
            Conversation.id == conversation_id,
            ConversationMember.user_id == current_user["id"]
        ).first()
        
        if not conversation:
            raise HTTPException(
                status_code=404,
                detail="대화방을 찾을 수 없거나 접근 권한이 없습니다"
            )
        

        
        # 메시지 본문과 첨부파일 모두 없는 경우 검증
        # body가 None이거나 빈 문자열이거나 공백만 있는 경우를 체크
        body_is_empty = not body or (isinstance(body, str) and body.strip() == "")
        attachments_is_empty = not attachments or len(attachments) == 0
        
        if body_is_empty and attachments_is_empty:
            raise HTTPException(
                status_code=400,
                detail="메시지 본문이나 첨부파일 중 하나는 있어야 합니다"
            )
        
        # 메시지 생성 (body가 공백만 있는 경우 None으로 설정)
        clean_body = body.strip() if body and isinstance(body, str) else body
        new_message = Message(
            conversation_id=conversation_id,
            sender_id=current_user["id"],
            body=clean_body if clean_body else None,
            parent_id=parent_id
        )
        
        db.add(new_message)
        db.flush()  # ID 생성을 위해 flush
        
        # 첨부파일 처리
        attachments_list = []
        if attachments and len(attachments) > 0:
            for attachment_data in attachments:
                try:
                    # 파일 확장자 확인 (이미지, 문서, 압축파일 등 지원)
                    file_extension = attachment_data.filename.split('.')[-1].lower()
                    supported_extensions = [
                        # 이미지 파일
                        'jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'svg', 'ico',
                        # 문서 파일
                        'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'rtf',
                        # 압축 파일
                        'zip', 'rar', '7z', 'tar', 'gz',
                        # 기타 파일
                        'mp3', 'mp4', 'avi', 'mov', 'wmv', 'flv', 'mkv'
                    ]
                    
                    if file_extension not in supported_extensions:
                        raise HTTPException(
                            status_code=400,
                            detail=f"지원하지 않는 파일 형식입니다: {file_extension}. 지원되는 형식: {', '.join(supported_extensions)}"
                        )
                    
                    # 파일 크기 확인 (50MB 제한)
                    file_content = attachment_data.file.read()
                    file_size = len(file_content)
                    attachment_data.file.seek(0)  # 파일 포인터 리셋
                    
                    if file_size > 50 * 1024 * 1024:  # 50MB
                        raise HTTPException(
                            status_code=400,
                            detail="파일 크기는 50MB를 초과할 수 없습니다"
                        )
                    
                    # Supabase Storage에 파일 업로드
                    if supabase:
                        # 고유한 파일명 생성
                        import uuid
                        file_uuid = str(uuid.uuid4())
                        file_path = f"chat-attachments/{conversation_id}/{file_uuid}.{file_extension}"
                        
                        # 파일 업로드
                        upload_result = supabase.storage.from_('chat').upload(
                            path=file_path,
                            file=file_content,
                            file_options={"content-type": attachment_data.content_type}
                        )
                        
                        if upload_result:
                            # 공개 URL 생성
                            file_path = supabase.storage.from_('chat').get_public_url(file_path)
                            
                            # Attachment 모델에 저장 (path에 전체 URL 저장)
                            attachment = Attachment(
                                message_id=new_message.id,
                                bucket='chat-attachments',
                                file_url=file_path,  # 전체 이미지 URL 저장
                                original_filename=attachment_data.filename,  # 원본 파일명 저장
                                mime_type=attachment_data.content_type,
                                size_bytes=file_size
                            )
                            
                            db.add(attachment)
                            attachments_list.append(attachment)
                        else:
                            raise HTTPException(
                                status_code=500,
                                detail="파일 업로드에 실패했습니다"
                            )
                    else:
                        raise HTTPException(
                            status_code=500,
                            detail="Supabase 설정이 되어 있지 않습니다"
                        )
                        
                except Exception as upload_error:
                    logger.error(f"파일 업로드 실패: {upload_error}")
                    raise HTTPException(
                        status_code=500,
                        detail=f"파일 업로드 중 오류가 발생했습니다: {str(upload_error)}"
                    )
        
        # 다른 멤버들의 last_read_at 업데이트 (읽지 않은 상태로)
        db.query(ConversationMember).filter(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id != current_user["id"]
        ).update({
            ConversationMember.last_read_at: None
        })
        
        # 발신자 메시지는 자동으로 읽음 처리
        db.query(ConversationMember).filter(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == current_user["id"]
        ).update({
            ConversationMember.last_read_at: datetime.utcnow()
        })
        
        db.commit()
        db.refresh(new_message)
        
        # WebSocket을 통해 실시간 메시지 전송
        try:
            # 발신자 프로필 정보 조회 (Supabase profiles에서)
            sender_info = None
            try:
                if supabase:
                    profile_result = supabase.table('profiles').select('*').eq('id', current_user["id"]).execute()
                    if profile_result.data:
                        profile = profile_result.data[0]
                        sender_info = {
                            "id": current_user["id"],
                            "name": profile.get('name', '사용자'),
                            "avatar": profile.get('avatar', ''),
                            "role": profile.get('role', 'user'),
                            "department": profile.get('department', '')
                        }
            except Exception as profile_error:
                logger.warning(f"발신자 프로필 정보 조회 실패: {profile_error}")
                sender_info = {
                    "id": current_user["id"],
                    "name": "사용자",
                    "avatar": "",
                    "role": "user",
                    "department": ""
                }
            
            # 첨부파일 정보 준비 (실제 저장된 ID 사용)
            attachment_list = []
            for attachment in attachments_list:
                attachment_list.append({
                    "id": str(attachment.id),
                    "bucket": attachment.bucket,
                    "file_url": attachment.file_url,
                    "original_filename": attachment.original_filename,
                    "mime_type": attachment.mime_type,
                    "size_bytes": attachment.size_bytes
                })
            
            # 메시지 타입 및 정렬 정보
            message_type = "other"  # 받는 사람 입장에서는 "other"
            alignment = "left"      # 받는 사람 입장에서는 "left"
            
            # 완전한 메시지 데이터 준비
            complete_message_data = {
                "id": str(new_message.id),
                "conversation_id": conversation_id,
                "sender_id": current_user["id"],
                "body": clean_body if clean_body else new_message.body,
                "parent_id": str(new_message.parent_id) if new_message.parent_id else None,
                "created_at": new_message.created_at.isoformat(),
                "edited_at": None,
                "deleted_at": None,
                
                # 메시지 구분을 위한 필드들
                "is_own_message": False,  # 받는 사람 입장에서는 False
                "message_type": message_type,
                "alignment": alignment,
                
                # 발신자 정보
                "sender_info": sender_info,
                "sender_name": sender_info["name"] if sender_info else "사용자",
                "sender_avatar": sender_info["avatar"] if sender_info else "",
                "sender_role": sender_info["role"] if sender_info else "user",
                
                # 기타 정보
                "attachments": attachment_list,
                "reactions": [],
                "is_read": True,  # 발신자 메시지는 자동으로 읽음
                
                # 프론트엔드 처리를 위한 추가 필드
                "show_avatar": False,  # 본인 메시지는 아바타 표시 안함
                "show_name": False,    # 본인 메시지는 이름 표시 안함
                "css_class": f"message-{message_type} message-{alignment}"
            }
            
            # WebSocket 메시지 데이터
            websocket_message = {
                "type": "new_message",
                "message": complete_message_data,
                "conversation_id": conversation_id,
                "sender_id": current_user["id"],
                "timestamp": datetime.utcnow().isoformat()
            }
            
            # 대화방의 모든 참여자에게 실시간 메시지 전송
            try:
                # 채팅방별 연결이 있는지 확인
                if conversation_id in manager.room_connections:
                    # 채팅방별 연결에 메시지 전송
                    await manager.send_room_message(
                        websocket_message, 
                        conversation_id, 
                        exclude_user=current_user["id"]
                    )
                else:
                    # 채팅방별 연결이 없으면 전역 연결로 전송 (기존 방식)
                    await manager.send_to_conversation(
                        websocket_message, 
                        conversation_id, 
                        exclude_user=current_user["id"]
                    )
            except Exception as room_error:
                logger.warning(f"채팅방별 연결 전송 실패, 전역 연결로 재시도: {room_error}")
                try:
                    await manager.send_to_conversation(
                        websocket_message, 
                        conversation_id, 
                        exclude_user=current_user["id"]
                    )
                except Exception as fallback_error:
                    logger.error(f"전역 연결 전송도 실패: {fallback_error}")
            
            # 발신자에게도 메시지 전송 (자신의 메시지 확인용)
            try:
                if conversation_id in manager.room_connections and current_user["id"] in manager.room_connections[conversation_id]:
                    # 채팅방별 연결로 발신자에게 전송
                    await manager.send_room_personal_message({
                        "type": "message_sent",
                        "message": complete_message_data,
                        "conversation_id": conversation_id,
                        "timestamp": datetime.utcnow().isoformat()
                    }, current_user["id"], conversation_id)
                else:
                    # 전역 연결로 발신자에게 전송
                    await manager.send_personal_message({
                        "type": "message_sent",
                        "message": complete_message_data,
                        "conversation_id": conversation_id,
                        "timestamp": datetime.utcnow().isoformat()
                    }, current_user["id"])
            except Exception as sender_error:
                logger.error(f"발신자 메시지 전송 실패: {sender_error}")
            
            # 채팅 리스트 업데이트 전송 (모든 참여자에게)
            try:
                # 각 참여자별 읽지 않은 메시지 수 계산
                conversation_members = manager.get_conversation_members(conversation_id)
                unread_counts = {}
                
                for member_id in conversation_members:
                    if member_id != current_user["id"]:  # 발신자 제외
                        # 해당 사용자의 마지막 읽은 시간 확인
                        member_info = db.query(ConversationMember).filter(
                            ConversationMember.conversation_id == conversation_id,
                            ConversationMember.user_id == member_id
                        ).first()
                        
                        if member_info and member_info.last_read_at:
                            # 마지막 읽은 시간 이후의 메시지 수 계산
                            unread_count = db.query(Message).filter(
                                Message.conversation_id == conversation_id,
                                Message.created_at > member_info.last_read_at,
                                Message.sender_id != member_id,  # 본인이 보낸 메시지 제외
                                Message.deleted_at.is_(None)
                            ).count()
                        else:
                            # 읽은 기록이 없으면 모든 메시지가 읽지 않음
                            unread_count = db.query(Message).filter(
                                Message.conversation_id == conversation_id,
                                Message.sender_id != member_id,  # 본인이 보낸 메시지 제외
                                Message.deleted_at.is_(None)
                            ).count()
                        
                        unread_counts[member_id] = unread_count
                    else:
                        # 발신자는 0
                        unread_counts[member_id] = 0
                
                # 마지막 메시지 정보로 채팅 리스트 업데이트
                chat_list_update_data = {
                    "last_message": {
                        "id": str(new_message.id),
                        "body": clean_body if clean_body else new_message.body,
                        "sender_id": current_user["id"],
                        "sender_name": sender_info["name"] if sender_info else "사용자",
                        "created_at": new_message.created_at.isoformat()
                    },
                    "unread_counts": unread_counts,  # 각 참여자별 읽지 않은 메시지 수
                    "timestamp": new_message.created_at.isoformat()
                }
                
                await manager.send_chat_list_update(
                    conversation_id, 
                    "new_message", 
                    chat_list_update_data, 
                    target_user=current_user["id"]
                )
                
            except Exception as update_error:
                logger.error(f"채팅 리스트 업데이트 전송 실패: {update_error}")
                
            # 푸시 알림 전송 (다른 화면에 있는 사용자들을 위해)
            try:
                import asyncio
                from main import send_push_notification_to_conversation
                
                # 백그라운드에서 푸시 알림 전송
                asyncio.create_task(send_push_notification_to_conversation(
                    conversation_id=conversation_id,
                    sender_name=sender_info["name"] if sender_info else "사용자",
                    message_body=clean_body if clean_body else body,
                    conversation_title=conversation.title,
                    exclude_user_id=current_user["id"]
                ))
                logger.info(f"푸시 알림 전송 요청: {conversation_id}")
            except Exception as push_error:
                logger.error(f"푸시 알림 전송 실패: {push_error}")
            
        except Exception as ws_error:
            logger.error(f"WebSocket 메시지 전송 실패: {ws_error}")
            # WebSocket 실패해도 HTTP 응답은 성공
        
        # 데이터베이스 로그 생성
        try:
            create_database_log(
                db=db,
                table_name="messages",
                record_id=str(new_message.id),
                action="CREATE",
                user_id=current_user["id"],
                new_values={
                    "conversation_id": conversation_id,
                    "body": clean_body if clean_body else body,
                    "parent_id": parent_id,
                    "has_attachments": bool(attachments and len(attachments) > 0)
                },
                changed_fields=["conversation_id", "body", "parent_id", "attachments"],
                note=f"新規メッセージ送信 (ファイル添付) - {conversation.title or '無題'}"
            )
        except Exception as log_error:
            logger.error(f"로그 생성 중 오류: {log_error}")
        
        # 첨부파일 정보 준비 (URL 포함)
        attachment_info = []
        for attachment in attachments_list:
            # attachment.file_url에 이미 전체 URL이 저장되어 있음
            attachment_info.append({
                "id": str(attachment.id),
                "file_url": attachment.file_url,  # 이미 저장된 전체 URL 사용
                "bucket": attachment.bucket,
                "original_filename": attachment.original_filename,
                "mime_type": attachment.mime_type,
                "size_bytes": attachment.size_bytes
            })
        
        # 응답 데이터 준비
        response_data = {
            "id": str(new_message.id),
            "conversation_id": conversation_id,
            "sender_id": current_user["id"],
            "body": clean_body if clean_body else new_message.body,
            "parent_id": str(new_message.parent_id) if new_message.parent_id else None,
            "created_at": new_message.created_at,
            "edited_at": None,
            "deleted_at": None,
            
            # 메시지 구분을 위한 필드들
            "is_own_message": False,  # 받는 사람 입장에서는 False
            "message_type": "other",  # 받는 사람 입장에서는 "other"
            "alignment": "left",      # 받는 사람 입장에서는 "left"
            
            # 발신자 정보
            "sender_info": sender_info,
            "sender_name": sender_info["name"] if sender_info else "사용자",
            "sender_avatar": sender_info["avatar"] if sender_info else "",
            "sender_role": sender_info["role"] if sender_info else "user",
            
            # 기타 정보
            "attachments": attachment_info,
            "reactions": [],
            "is_read": True,
            
            # 프론트엔드 처리를 위한 추가 필드
            "show_avatar": False,
            "show_name": False,
            "css_class": "message-other message-left"
        }
        
        return response_data
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"메시지 전송 중 오류가 발생했습니다: {str(e)}"
        )

@router.get("/conversations/{conversation_id}/messages")
def get_messages(
    conversation_id: str,
    page: int = Query(1, description="페이지 번호", ge=1),
    page_size: int = Query(50, description="페이지당 항목 수", ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """대화의 메시지 목록 조회"""
    try:
        # 대화 존재 여부 및 참여 권한 확인
        conversation = db.query(Conversation).join(ConversationMember).filter(
            Conversation.id == conversation_id,
            ConversationMember.user_id == current_user["id"]
        ).first()
        
        if not conversation:
            raise HTTPException(
                status_code=404,
                detail="대화를 찾을 수 없거나 접근 권한이 없습니다"
            )
        
        # 메시지 조회 (최신 메시지부터)
        query = db.query(Message).filter(
            Message.conversation_id == conversation_id,
            Message.deleted_at.is_(None)  # 삭제되지 않은 메시지만
        ).options(
            joinedload(Message.attachments),
            joinedload(Message.reactions)
        ).order_by(desc(Message.created_at))
        
        # 전체 항목 수 계산
        total_count = query.count()
        
        # 페이지네이션 적용
        messages = query.offset((page - 1) * page_size).limit(page_size).all()
        
        # 전체 페이지 수 계산
        total_pages = (total_count + page_size - 1) // page_size
        
        # 응답 데이터 준비
        result = []
        
        # 1. 고유한 발신자 ID들 수집 (배치 쿼리용)
        sender_ids = list(set([str(msg.sender_id) for msg in messages]))
        
        # 2. 한 번에 모든 프로필 정보 조회 (배치 쿼리)
        profiles_data = {}
        if supabase and sender_ids:
            try:
                # IN 쿼리로 배치 조회
                profile_result = supabase.table('profiles').select('*').in_('id', sender_ids).execute()
                if profile_result.data:
                    for profile in profile_result.data:
                        profiles_data[profile['id']] = profile
                print(f"프로필 배치 조회 성공: {len(profiles_data)}개 프로필")
            except Exception as e:
                logger.warning(f"프로필 배치 조회 실패: {e}")
        
        # 3. 한 번에 모든 읽음 여부 조회 (배치 쿼리)
        message_ids = [str(msg.id) for msg in messages]
        read_status_data = {}
        if message_ids:
            try:
                read_statuses = db.query(MessageRead).filter(
                    MessageRead.message_id.in_(message_ids),
                    MessageRead.user_id == current_user["id"]
                ).all()
                
                for read_status in read_statuses:
                    read_status_data[str(read_status.message_id)] = True
                
                print(f"읽음 상태 배치 조회 성공: {len(read_status_data)}개 메시지")
            except Exception as e:
                logger.warning(f"읽음 상태 배치 조회 실패: {e}")
        
        # 4. 메시지 응답 구성 (캐시된 프로필 정보와 읽음 상태 사용)
        for msg in messages:
            sender_id = str(msg.sender_id)
            is_own_message = sender_id == current_user["id"]
            
            # 캐시된 프로필 정보 사용
            profile = profiles_data.get(sender_id, {})
            sender_info = {
                "id": sender_id,
                "name": profile.get('name', '사용자'),
                "avatar": profile.get('avatar', ''),
                "role": profile.get('role', 'user'),
                "department": profile.get('department', '')
            } if profile else {
                "id": sender_id,
                "name": "사용자",
                "avatar": "",
                "role": "user",
                "department": ""
            }
            
            # 첨부파일 정보
            attachments = []
            if msg.attachments:
                for attachment in msg.attachments:
                    attachments.append({
                        "id": str(attachment.id),
                        "bucket": attachment.bucket,
                        "file_url": attachment.file_url,
                        "original_filename": attachment.original_filename,
                        "mime_type": attachment.mime_type,
                        "size_bytes": attachment.size_bytes
                    })
            
            # 이모지 반응 정보
            reactions = []
            if msg.reactions:
                for reaction in msg.reactions:
                    reactions.append({
                        "emoji": reaction.emoji,
                        "user_id": str(reaction.user_id),  # UUID를 문자열로 변환
                        "created_at": reaction.created_at
                    })
            
            # 캐시된 읽음 상태 사용
            is_read = read_status_data.get(str(msg.id), False)
            
            # 메시지 타입 및 정렬 정보
            message_type = "own" if is_own_message else "other"
            alignment = "right" if is_own_message else "left"

            message_data = {
                "id": str(msg.id),
                "conversation_id": str(msg.conversation_id),
                "sender_id": sender_id,
                "body": msg.body,
                "parent_id": str(msg.parent_id) if msg.parent_id else None,
                "created_at": msg.created_at,
                "edited_at": msg.edited_at,
                "deleted_at": msg.deleted_at,
                
                # 메시지 구분을 위한 필드들
                "is_own_message": is_own_message,
                "message_type": message_type,
                "alignment": alignment,
                
                # 발신자 정보
                "sender_info": sender_info,
                "sender_name": sender_info["name"],
                "sender_avatar": sender_info["avatar"],
                "sender_role": sender_info["role"],
                
                # 기타 정보
                "attachments": attachments,
                "reactions": reactions,
                "is_read": is_read,
                
                # 프론트엔드 처리를 위한 추가 필드
                "show_avatar": True,  # 상대방 메시지만 아바타 표시
                "show_name": True,  # 그룹채팅에서만 상대방 이름 표시
                "css_class": f"message-{message_type} message-{alignment}"
            }
            result.append(message_data)
        
        # 메시지 순서를 시간순으로 정렬 (최신 메시지가 마지막에)
        result.reverse()
        
        # 대화방 제목 결정 (title이 없으면 상대방 이름으로 설정)
        conversation_title = conversation.title
        
        # 그룹 채팅이 아니고 제목이 없는 경우, 상대방 이름으로 설정
        if not conversation.is_group and not conversation.title:
            # 현재 사용자를 제외한 다른 참여자 찾기
            other_members = [m for m in conversation.members if str(m.user_id) != str(current_user["id"])]
            
            if other_members:
                # 첫 번째 상대방의 이름을 가져오기 (Supabase profiles에서)
                other_user_id = str(other_members[0].user_id)
                try:
                    if supabase:
                        profile_result = supabase.table('profiles').select('*').eq('id', other_user_id).execute()
                        if profile_result.data:
                            profile = profile_result.data[0]
                            conversation_title = profile.get('name', f'사용자 {other_user_id[:8]}')
                        else:
                            conversation_title = f'사용자 {other_user_id[:8]}'
                    else:
                        conversation_title = f'사용자 {other_user_id[:8]}'
                except Exception as profile_error:
                    logger.warning(f"상대방 프로필 정보 조회 실패: {profile_error}")
                    conversation_title = f'사용자 {other_user_id[:8]}'
            else:
                conversation_title = "대화방"
        
        # 대화 상대방 ID 찾기 (1:1 채팅인 경우)
        other_user_id = None
        if not conversation.is_group:
            # 현재 사용자를 제외한 다른 참여자 찾기
            other_members = [m for m in conversation.members if str(m.user_id) != str(current_user["id"])]
            if other_members:
                other_user_id = str(other_members[0].user_id)
        
        return MessageListResponse(
            messages=result,
            total=total_count,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            conversation_info={
                "id": str(conversation.id),
                "title": conversation_title,  # 동적으로 설정된 제목 사용
                "is_group": conversation.is_group,
                "other_user_id": other_user_id  # 1:1 채팅인 경우 상대방 ID
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"메시지 목록 조회 중 오류가 발생했습니다: {str(e)}"
        )

@router.put("/messages/{message_id}")
async def update_message(
    message_id: str,
    message_update: MessageUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """메시지 수정"""
    try:
        # 메시지 존재 여부 및 작성자 확인
        message = db.query(Message).filter(
            Message.id == message_id,
            Message.sender_id == current_user["id"],
            Message.deleted_at.is_(None)
        ).first()
        
        if not message:
            raise HTTPException(
                status_code=404,
                detail="메시지를 찾을 수 없거나 수정 권한이 없습니다"
            )
        
        # 기존 값 저장 (로그용)
        old_values = {
            "body": message.body
        }
        
        # 메시지 수정
        if message_update.body is not None:
            message.body = message_update.body
            message.edited_at = datetime.utcnow()
        
        db.commit()
        db.refresh(message)
        
        # WebSocket을 통해 메시지 수정 알림 전송
        try:
            websocket_message = {
                "type": "message_updated",
                "message_id": str(message.id),
                "conversation_id": str(message.conversation_id),
                "body": message.body,
                "edited_at": message.edited_at.isoformat(),
                "timestamp": datetime.utcnow().isoformat()
            }
            
            # 채팅방별 연결이 있는지 확인하고 우선적으로 전송
            try:
                if str(message.conversation_id) in manager.room_connections:
                    await manager.send_room_message(
                        websocket_message, 
                        str(message.conversation_id)
                    )
                    print(f"채팅방별 연결로 메시지 수정 알림 전송 완료")
                else:
                    await manager.send_to_conversation(
                        websocket_message, 
                        str(message.conversation_id)
                    )
                    print(f"전역 연결로 메시지 수정 알림 전송 완료")
            except Exception as ws_error:
                logger.error(f"WebSocket 메시지 수정 알림 전송 실패: {ws_error}")
            
            # 채팅 리스트 업데이트 전송
            try:
                # 각 참여자별 읽지 않은 메시지 수 계산
                conversation_members = manager.get_conversation_members(str(message.conversation_id))
                unread_counts = {}
                
                for member_id in conversation_members:
                    # 해당 사용자의 마지막 읽은 시간 확인
                    member_info = db.query(ConversationMember).filter(
                        ConversationMember.conversation_id == message.conversation_id,
                        ConversationMember.user_id == member_id
                    ).first()
                    
                    if member_info and member_info.last_read_at:
                        # 마지막 읽은 시간 이후의 메시지 수 계산
                        unread_count = db.query(Message).filter(
                            Message.conversation_id == message.conversation_id,
                            Message.created_at > member_info.last_read_at,
                            Message.sender_id != member_id,  # 본인이 보낸 메시지 제외
                            Message.deleted_at.is_(None)
                        ).count()
                    else:
                        # 읽은 기록이 없으면 모든 메시지가 읽지 않음
                        unread_count = db.query(Message).filter(
                            Message.conversation_id == message.conversation_id,
                            Message.sender_id != member_id,  # 본인이 보낸 메시지 제외
                            Message.deleted_at.is_(None)
                        ).count()
                    
                    unread_counts[member_id] = unread_count
                
                chat_list_update_data = {
                    "message_id": str(message.id),
                    "body": message.body,
                    "edited_at": message.edited_at.isoformat(),
                    "unread_counts": unread_counts,  # 각 참여자별 읽지 않은 메시지 수
                    "timestamp": datetime.utcnow().isoformat()
                }
                
                await manager.send_chat_list_update(
                    str(message.conversation_id),
                    "message_updated",
                    chat_list_update_data
                )
                print(f"메시지 수정 채팅 리스트 업데이트 전송 완료")
                print(f"읽지 않은 메시지 수: {unread_counts}")
                
            except Exception as update_error:
                logger.error(f"메시지 수정 채팅 리스트 업데이트 전송 실패: {update_error}")
                
        except Exception as ws_error:
            logger.error(f"WebSocket 메시지 수정 알림 준비 실패: {ws_error}")
        
        # 데이터베이스 로그 생성
        try:
            create_database_log(
                db=db,
                table_name="messages",
                record_id=str(message.id),
                action="UPDATE",
                user_id=current_user["id"],
                old_values=old_values,
                new_values={"body": message.body},
                changed_fields=["body"],
                note=f"メッセージ編集 - {message.body[:50] if message.body else '無内容'}..."
            )
        except Exception as log_error:
            print(f"로그 생성 중 오류: {log_error}")
        
        return {
            "message": "메시지가 성공적으로 수정되었습니다",
            "message_id": str(message.id),
            "body": message.body,
            "edited_at": message.edited_at
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"메시지 수정 중 오류가 발생했습니다: {str(e)}"
        )

@router.delete("/messages/{message_id}")
async def delete_message(
    message_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """메시지 삭제 (소프트 삭제)"""
    try:
        # 메시지 존재 여부 및 작성자 확인
        message = db.query(Message).filter(
            Message.id == message_id,
            Message.sender_id == current_user["id"],
            Message.deleted_at.is_(None)
        ).first()
        
        if not message:
            raise HTTPException(
                status_code=404,
                detail="메시지를 찾을 수 없거나 삭제 권한이 없습니다"
            )
        
        # 소프트 삭제 (deleted_at 설정)
        message.deleted_at = datetime.utcnow()
        
        db.commit()
        
        # WebSocket을 통해 메시지 삭제 알림 전송
        try:
            websocket_message = {
                "type": "message_deleted",
                "message_id": str(message.id),
                "conversation_id": str(message.conversation_id),
                "deleted_at": message.deleted_at.isoformat(),
                "timestamp": datetime.utcnow().isoformat()
            }
            
            # 채팅방별 연결이 있는지 확인하고 우선적으로 전송
            try:
                if str(message.conversation_id) in manager.room_connections:
                    await manager.send_room_message(
                        websocket_message, 
                        str(message.conversation_id)
                    )
                    print(f"채팅방별 연결로 메시지 삭제 알림 전송 완료")
                else:
                    await manager.send_to_conversation(
                        websocket_message, 
                        str(message.conversation_id)
                    )
                    print(f"전역 연결로 메시지 삭제 알림 전송 완료")
            except Exception as ws_error:
                logger.error(f"WebSocket 메시지 삭제 알림 전송 실패: {ws_error}")
            
            # 채팅 리스트 업데이트 전송
            try:
                # 각 참여자별 읽지 않은 메시지 수 계산 (삭제된 메시지 제외)
                conversation_members = manager.get_conversation_members(str(message.conversation_id))
                unread_counts = {}
                
                for member_id in conversation_members:
                    # 해당 사용자의 마지막 읽은 시간 확인
                    member_info = db.query(ConversationMember).filter(
                        ConversationMember.conversation_id == message.conversation_id,
                        ConversationMember.user_id == member_id
                    ).first()
                    
                    if member_info and member_info.last_read_at:
                        # 마지막 읽은 시간 이후의 메시지 수 계산 (삭제된 메시지 제외)
                        unread_count = db.query(Message).filter(
                            Message.conversation_id == message.conversation_id,
                            Message.created_at > member_info.last_read_at,
                            Message.sender_id != member_id,  # 본인이 보낸 메시지 제외
                            Message.deleted_at.is_(None)  # 삭제되지 않은 메시지만
                        ).count()
                    else:
                        # 읽은 기록이 없으면 모든 메시지가 읽지 않음 (삭제된 메시지 제외)
                        unread_count = db.query(Message).filter(
                            Message.conversation_id == message.conversation_id,
                            Message.sender_id != member_id,  # 본인이 보낸 메시지 제외
                            Message.deleted_at.is_(None)  # 삭제되지 않은 메시지만
                        ).count()
                    
                    unread_counts[member_id] = unread_count
                
                chat_list_update_data = {
                    "message_id": str(message.id),
                    "deleted_at": message.deleted_at.isoformat(),
                    "unread_counts": unread_counts,  # 각 참여자별 읽지 않은 메시지 수
                    "timestamp": datetime.utcnow().isoformat()
                }
                
                await manager.send_chat_list_update(
                    str(message.conversation_id),
                    "message_deleted",
                    chat_list_update_data
                )
                print(f"메시지 삭제 채팅 리스트 업데이트 전송 완료")
                print(f"읽지 않은 메시지 수: {unread_counts}")
                
            except Exception as update_error:
                logger.error(f"메시지 삭제 채팅 리스트 업데이트 전송 실패: {update_error}")
                
        except Exception as ws_error:
            logger.error(f"WebSocket 메시지 삭제 알림 준비 실패: {ws_error}")
        
        # 데이터베이스 로그 생성
        try:
            create_database_log(
                db=db,
                table_name="messages",
                record_id=str(message.id),
                action="UPDATE",
                user_id=current_user["id"],
                old_values={"deleted_at": None},
                new_values={"deleted_at": message.deleted_at.strftime("%Y-%m-%d %H:%M:%S")},
                changed_fields=["deleted_at"],
                note=f"メッセージ削除 - {message.body[:50] if message.body else '無内容'}..."
            )
        except Exception as log_error:
            print(f"로그 생성 중 오류: {log_error}")
        
        return {
            "message": "메시지가 성공적으로 삭제되었습니다",
            "message_id": str(message.id)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"메시지 삭제 중 오류가 발생했습니다: {str(e)}"
        )

# ===== 메시지 읽음 처리 API =====

@router.post("/messages/{message_id}/read")
async def mark_message_as_read(
    message_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """메시지를 읽음 처리"""
    try:
        # 메시지 존재 여부 및 접근 권한 확인
        message = db.query(Message).join(ConversationMember).filter(
            Message.id == message_id,
            ConversationMember.conversation_id == Message.conversation_id,
            ConversationMember.user_id == current_user["id"]
        ).first()
        
        if not message:
            raise HTTPException(
                status_code=404,
                detail="메시지를 찾을 수 없거나 접근 권한이 없습니다"
            )
        
        # 이미 읽음 처리되었는지 확인
        existing_read = db.query(MessageRead).filter(
            MessageRead.message_id == message_id,
            MessageRead.user_id == current_user["id"]
        ).first()
        
        if existing_read:
            return {
                "message": "이미 읽음 처리된 메시지입니다",
                "message_id": str(message_id),
                "read_at": existing_read.read_at
            }
        
        # 읽음 처리
        new_read = MessageRead(
            message_id=message_id,
            user_id=current_user["id"],
            read_at=datetime.utcnow()
        )
        
        db.add(new_read)
        db.commit()
        db.refresh(new_read)
        
        # 데이터베이스 로그 생성
        try:
            create_database_log(
                db=db,
                table_name="message_reads",
                record_id=f"{message_id}_{current_user['id']}",
                action="INSERT",
                user_id=current_user["id"],
                old_values={},
                new_values={
                    "message_id": str(message_id),
                    "user_id": current_user["id"],
                    "read_at": new_read.read_at.isoformat()
                },
                changed_fields=["message_id", "user_id", "read_at"],
                note=f"メッセージ既読処理 - メッセージID: {message_id}"
            )
        except Exception as log_error:
            logger.warning(f"로그 생성 중 오류: {log_error}")
        
        # WebSocket으로 읽음 상태 업데이트 알림
        try:
            websocket_message = {
                "type": "message_read",
                "message_id": str(message_id),
                "user_id": current_user["id"],
                "conversation_id": str(message.conversation_id),
                "read_at": new_read.read_at.isoformat(),
                "timestamp": datetime.utcnow().isoformat()
            }
            
            # 대화방의 다른 멤버들에게 읽음 상태 업데이트 알림
            await manager.send_to_conversation(
                websocket_message, 
                str(message.conversation_id), 
                exclude_user=current_user["id"]
            )
            
            # 채팅 리스트 업데이트 전송 (읽지 않은 메시지 수 감소)
            chat_list_update_data = {
                "message_id": str(message_id),
                "read_by": current_user["id"],
                "read_at": new_read.read_at.isoformat(),
                "conversation_id": str(message.conversation_id)
            }
            
            # 읽음 처리 후 각 참여자별 읽지 않은 메시지 수 계산
            try:
                conversation_members = manager.get_conversation_members(str(message.conversation_id))
                unread_counts = {}
                
                for member_id in conversation_members:
                    # 해당 사용자의 마지막 읽은 시간 확인
                    member_info = db.query(ConversationMember).filter(
                        ConversationMember.conversation_id == message.conversation_id,
                        ConversationMember.user_id == member_id
                    ).first()
                    
                    if member_info and member_info.last_read_at:
                        # 마지막 읽은 시간 이후의 메시지 수 계산
                        unread_count = db.query(Message).filter(
                            Message.conversation_id == message.conversation_id,
                            Message.created_at > member_info.last_read_at,
                            Message.sender_id != member_id,  # 본인이 보낸 메시지 제외
                            Message.deleted_at.is_(None)
                        ).count()
                    else:
                        # 읽은 기록이 없으면 모든 메시지가 읽지 않음
                        unread_count = db.query(Message).filter(
                            Message.conversation_id == message.conversation_id,
                            Message.sender_id != member_id,  # 본인이 보낸 메시지 제외
                            Message.deleted_at.is_(None)
                        ).count()
                    
                    unread_counts[member_id] = unread_count
                
                chat_list_update_data["unread_counts"] = unread_counts
                print(f"읽음 처리 후 읽지 않은 메시지 수: {unread_counts}")
                
            except Exception as count_error:
                logger.error(f"읽지 않은 메시지 수 계산 실패: {count_error}")
            
            await manager.send_chat_list_update(
                str(message.conversation_id),
                "message_read",
                chat_list_update_data
            )
            print(f"메시지 읽음 채팅 리스트 업데이트 전송 완료")
            
        except Exception as ws_error:
            logger.warning(f"WebSocket 읽음 상태 알림 실패: {ws_error}")
        
        return {
            "message": "메시지가 성공적으로 읽음 처리되었습니다",
            "message_id": str(message_id),
            "read_at": new_read.read_at,
            "websocket_sent": True
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"메시지 읽음 처리 중 오류가 발생했습니다: {str(e)}"
        )

@router.post("/conversations/{conversation_id}/read-all")
async def mark_conversation_as_read(
    conversation_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """대화방의 모든 메시지를 읽음 처리"""
    try:
        # 대화방 존재 여부 및 참여 권한 확인
        conversation = db.query(Conversation).join(ConversationMember).filter(
            Conversation.id == conversation_id,
            ConversationMember.user_id == current_user["id"]
        ).first()
        
        if not conversation:
            raise HTTPException(
                status_code=404,
                detail="대화방을 찾을 수 없거나 접근 권한이 없습니다"
            )
        
        # 읽지 않은 메시지들 조회
        unread_messages = db.query(Message).filter(
            Message.conversation_id == conversation_id,
            Message.sender_id != current_user["id"],
            Message.deleted_at.is_(None)
        ).all()
        
        if not unread_messages:
            return {
                "message": "읽지 않은 메시지가 없습니다",
                "conversation_id": str(conversation_id),
                "read_count": 0
            }
        
        # 배치로 읽음 처리
        read_records = []
        for msg in unread_messages:
            # 이미 읽음 처리되었는지 확인
            existing_read = db.query(MessageRead).filter(
                MessageRead.message_id == msg.id,
                MessageRead.user_id == current_user["id"]
            ).first()
            
            if not existing_read:
                read_records.append(MessageRead(
                    message_id=msg.id,
                    user_id=current_user["id"],
                    read_at=datetime.utcnow()
                ))
        
        if read_records:
            db.add_all(read_records)
            db.commit()
            
            # 데이터베이스 로그 생성
            try:
                create_database_log(
                    db=db,
                    table_name="message_reads",
                    record_id=f"batch_{conversation_id}_{current_user['id']}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
                    action="INSERT",
                    user_id=current_user["id"],
                    old_values={},
                    new_values={
                        "conversation_id": str(conversation_id),
                        "read_count": len(read_records),
                        "message_ids": [str(record.message_id) for record in read_records]
                    },
                    changed_fields=["conversation_id", "read_count"],
                    note=f"会話全体既読処理 - 会話ID: {conversation_id}, 既読数: {len(read_records)}"
                )
            except Exception as log_error:
                logger.warning(f"로그 생성 중 오류: {log_error}")
            
            # WebSocket으로 읽음 상태 업데이트 알림
            try:
                # websocket_message = {
                #     "type": "conversation_read_all",
                #     "conversation_id": str(conversation_id),
                #     "user_id": current_user["id"],
                #     "read_count": len(read_records),
                #     "timestamp": datetime.utcnow().isoformat()
                # }
                
                # # 대화방의 다른 멤버들에게 읽음 상태 업데이트 알림
                # await manager.send_to_conversation(
                #     websocket_message, 
                #     str(conversation_id), 
                #     exclude_user=current_user["id"]
                # )
                
                # 채팅 리스트 업데이트 전송 (읽지 않은 메시지 수 초기화)
                chat_list_update_data = {
                    "read_by": current_user["id"],
                    "read_count": len(read_records),
                    "conversation_id": str(conversation_id),
                    "timestamp": datetime.utcnow().isoformat()
                }
                
                # 전체 읽음 처리 후 각 참여자별 읽지 않은 메시지 수 계산
                try:
                    conversation_members = manager.get_conversation_members(str(conversation_id))
                    unread_counts = {}
                    
                    for member_id in conversation_members:
                        if member_id == current_user["id"]:
                            # 읽음 처리한 사용자는 0
                            unread_counts[member_id] = 0
                        else:
                            # 다른 사용자는 기존 읽지 않은 메시지 수 유지
                            member_info = db.query(ConversationMember).filter(
                                ConversationMember.conversation_id == conversation_id,
                                ConversationMember.user_id == member_id
                            ).first()
                            
                            if member_info and member_info.last_read_at:
                                # 마지막 읽은 시간 이후의 메시지 수 계산
                                unread_count = db.query(Message).filter(
                                    Message.conversation_id == conversation_id,
                                    Message.created_at > member_info.last_read_at,
                                    Message.sender_id != member_id,  # 본인이 보낸 메시지 제외
                                    Message.deleted_at.is_(None)
                                ).count()
                            else:
                                # 읽은 기록이 없으면 모든 메시지가 읽지 않음
                                unread_count = db.query(Message).filter(
                                    Message.conversation_id == conversation_id,
                                    Message.sender_id != member_id,  # 본인이 보낸 메시지 제외
                                    Message.deleted_at.is_(None)
                                ).count()
                            
                            unread_counts[member_id] = unread_count
                    
                    chat_list_update_data["unread_counts"] = unread_counts
                    print(f"전체 읽음 처리 후 읽지 않은 메시지 수: {unread_counts}")
                    
                except Exception as count_error:
                    logger.error(f"읽지 않은 메시지 수 계산 실패: {count_error}")
                
                # await manager.send_chat_list_update(
                #     str(conversation_id),
                #     "conversation_read_all",
                #     chat_list_update_data
                # )
                # print(f"대화방 전체 읽음 채팅 리스트 업데이트 전송 완료")
            except Exception as ws_error:
                logger.warning(f"WebSocket 읽음 상태 알림 실패: {ws_error}")
            
            return {
                "message": f"대화방의 {len(read_records)}개 메시지가 성공적으로 읽음 처리되었습니다",
                "conversation_id": str(conversation_id),
                "read_count": len(read_records),
                "websocket_sent": True
            }
        else:
            return {
                "message": "읽음 처리할 메시지가 없습니다",
                "conversation_id": str(conversation_id),
                "read_count": 0
            }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"대화방 읽음 처리 중 오류가 발생했습니다: {str(e)}"
        )

# ===== 이모지 반응 API =====

@router.post("/messages/{message_id}/reactions")
def add_reaction(
    message_id: str,
    reaction: ReactionCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """메시지에 이모지 반응 추가"""
    try:
        # 메시지 존재 여부 확인
        message = db.query(Message).filter(
            Message.id == message_id,
            Message.deleted_at.is_(None)
        ).first()
        
        if not message:
            raise HTTPException(
                status_code=404,
                detail="메시지를 찾을 수 없습니다"
            )
        
        # 이미 같은 이모지 반응이 있는지 확인
        existing_reaction = db.query(Reaction).filter(
            Reaction.message_id == message_id,
            Reaction.user_id == current_user["id"],
            Reaction.emoji == reaction.emoji
        ).first()
        
        if existing_reaction:
            raise HTTPException(
                status_code=400,
                detail="이미 같은 이모지 반응을 추가했습니다"
            )
        
        # 새 반응 추가
        new_reaction = Reaction(
            message_id=message_id,
            user_id=current_user["id"],
            emoji=reaction.emoji
        )
        db.add(new_reaction)
        db.commit()
        
        return {
            "message": "이모지 반응이 추가되었습니다",
            "message_id": str(message_id),
            "emoji": reaction.emoji,
            "user_id": current_user["id"]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"이모지 반응 추가 중 오류가 발생했습니다: {str(e)}"
        )

@router.delete("/messages/{message_id}/reactions/{emoji}")
def remove_reaction(
    message_id: str,
    emoji: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """메시지의 이모지 반응 제거"""
    try:
        # 반응 존재 여부 및 소유자 확인
        reaction = db.query(Reaction).filter(
            Reaction.message_id == message_id,
            Reaction.user_id == current_user["id"],
            Reaction.emoji == emoji
        ).first()
        
        if not reaction:
            raise HTTPException(
                status_code=404,
                detail="해당 이모지 반응을 찾을 수 없습니다"
            )
        
        # 반응 제거
        db.delete(reaction)
        db.commit()
        
        return {
            "message": "이모지 반응이 제거되었습니다",
            "message_id": str(message_id),
            "emoji": emoji
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"이모지 반응 제거 중 오류가 발생했습니다: {str(e)}"
        )

# ===== 대화방 멤버 관리 API =====

@router.get("/conversations/{conversation_id}/members")
async def get_conversation_members(
    conversation_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """대화방 참여자 기본 정보 조회 (HTTP API)"""
    try:
        # 대화방 존재 여부 및 참여 권한 확인
        conversation = db.query(Conversation).join(ConversationMember).filter(
            Conversation.id == conversation_id,
            ConversationMember.user_id == current_user["id"]
        ).first()
        
        if not conversation:
            raise HTTPException(
                status_code=404,
                detail="대화방을 찾을 수 없거나 접근 권한이 없습니다"
            )
        
        # 대화방 멤버 조회
        conversation_members = db.query(ConversationMember).filter(
            ConversationMember.conversation_id == conversation_id
        ).all()
        
        # 사용자 기본 정보 구성 (실제로는 Supabase에서 조회)
        members_info = []
        for member in conversation_members:
            # 여기서는 간단한 예시로 구성
            # 실제 구현에서는 Supabase auth.users와 profiles 테이블에서 조회
            member_info = {
                "id": member.user_id,
                "name": f"User_{member.user_id[:8]}",  # 실제로는 사용자 테이블에서 조회
                "avatar": "",  # 실제로는 사용자 프로필에서 조회
                "role": member.role,
                "joined_at": member.joined_at.isoformat(),
                "last_read_at": member.last_read_at.isoformat() if member.last_read_at else None
            }
            members_info.append(member_info)
        
        # 역할별로 정렬 (admin 우선)
        members_info.sort(key=lambda x: (x["role"] != "admin", x["name"]))
        
        return {
            "conversation_id": conversation_id,
            "conversation_title": conversation.title,
            "is_group": conversation.is_group,
            "total_members": len(members_info),
            "members": members_info,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"대화방 멤버 정보 조회 중 오류가 발생했습니다: {str(e)}"
        )

@router.post("/conversations/{conversation_id}/members")
async def add_conversation_member(
    conversation_id: str,
    member_data: ConversationMemberCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """대화방에 새 멤버 추가"""
    try:
        # 대화방 존재 여부 및 관리자 권한 확인
        conversation = db.query(Conversation).join(ConversationMember).filter(
            Conversation.id == conversation_id,
            ConversationMember.user_id == current_user["id"],
            ConversationMember.role == "admin"
        ).first()
        
        if not conversation:
            raise HTTPException(
                status_code=404,
                detail="대화방을 찾을 수 없거나 관리자 권한이 없습니다"
            )
        
        # 이미 멤버인지 확인
        existing_member = db.query(ConversationMember).filter(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == member_data.user_id
        ).first()
        
        if existing_member:
            raise HTTPException(
                status_code=400,
                detail="이미 대화방에 참여 중인 사용자입니다"
            )
        
        # 새 멤버 추가
        new_member = ConversationMember(
            conversation_id=conversation_id,
            user_id=member_data.user_id,
            role=member_data.role
        )
        db.add(new_member)
        db.commit()
        
        # WebSocket을 통해 새 멤버 추가 알림
        try:
            await manager.send_to_conversation({
                "type": "member_added",
                "conversation_id": conversation_id,
                "user_id": member_data.user_id,
                "role": member_data.role,
                "timestamp": datetime.utcnow().isoformat()
            }, conversation_id)
            
            # 채팅 리스트 업데이트 전송
            chat_list_update_data = {
                "member_added": {
                    "user_id": member_data.user_id,
                    "role": member_data.role,
                    "timestamp": datetime.utcnow().isoformat()
                },
                "conversation_id": conversation_id
            }
            
            await manager.send_chat_list_update(
                conversation_id,
                "member_added",
                chat_list_update_data
            )
            print(f"멤버 추가 채팅 리스트 업데이트 전송 완료")
            
        except Exception as ws_error:
            logger.error(f"WebSocket 알림 전송 실패: {ws_error}")
        
        return {
            "message": "새 멤버가 대화방에 추가되었습니다",
            "conversation_id": conversation_id,
            "user_id": member_data.user_id,
            "role": member_data.role
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"멤버 추가 중 오류가 발생했습니다: {str(e)}"
        )

@router.delete("/conversations/{conversation_id}/members/{user_id}")
async def remove_conversation_member(
    conversation_id: str,
    user_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """대화방에서 멤버 제거"""
    try:
        # 대화방 존재 여부 및 권한 확인
        conversation = db.query(Conversation).join(ConversationMember).filter(
            Conversation.id == conversation_id,
            ConversationMember.user_id == current_user["id"]
        ).first()
        
        if not conversation:
            raise HTTPException(
                status_code=404,
                detail="대화방을 찾을 수 없거나 접근 권한이 없습니다"
            )
        
        # 제거할 멤버 확인
        target_member = db.query(ConversationMember).filter(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == user_id
        ).first()
        
        if not target_member:
            raise HTTPException(
                status_code=404,
                detail="제거할 멤버를 찾을 수 없습니다"
            )
        
        # 자신을 제거하거나 관리자가 다른 사용자를 제거하는 경우만 허용
        if user_id != current_user["id"]:
            current_member = db.query(ConversationMember).filter(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.user_id == current_user["id"]
            ).first()
            
            if not current_member or current_member.role != "admin":
                raise HTTPException(
                    status_code=403,
                    detail="멤버를 제거할 권한이 없습니다"
                )
        
        # 멤버 제거
        db.delete(target_member)
        db.commit()
        
        # WebSocket을 통해 멤버 제거 알림
        try:
            await manager.send_to_conversation({
                "type": "member_removed",
                "conversation_id": conversation_id,
                "user_id": user_id,
                "timestamp": datetime.utcnow().isoformat()
            }, conversation_id)
            
            # 채팅 리스트 업데이트 전송
            chat_list_update_data = {
                "member_removed": {
                    "user_id": user_id,
                    "timestamp": datetime.utcnow().isoformat()
                },
                "conversation_id": conversation_id
            }
            
            await manager.send_chat_list_update(
                conversation_id,
                "member_removed",
                chat_list_update_data
            )
            print(f"멤버 제거 채팅 리스트 업데이트 전송 완료")
            
        except Exception as ws_error:
            logger.error(f"WebSocket 알림 전송 실패: {ws_error}")
        
        return {
            "message": "멤버가 대화방에서 제거되었습니다",
            "conversation_id": conversation_id,
            "user_id": user_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"멤버 제거 중 오류가 발생했습니다: {str(e)}"
        )

# ===== 전체 사용자 관리 API =====

@router.get("/users")
async def get_all_users(
    page: int = Query(1, description="페이지 번호", ge=1),
    page_size: int = Query(50, description="페이지당 항목 수", ge=1, le=100),
    search: Optional[str] = Query(None, description="사용자 이름으로 검색"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """전체 사용자 목록 조회 (HTTP API)"""
    try:
        if not supabase:
            raise HTTPException(
                status_code=500,
                detail="Supabase 클라이언트가 초기화되지 않았습니다"
            )
        
        # Supabase에서 사용자 정보 조회 (본인 제외)
        # auth.users는 직접 접근할 수 없으므로 profiles 테이블에서 조회
        query = supabase.table('profiles').select('*').neq('id', current_user["id"])
        
        # 검색 필터링 (이름으로 검색)
        if search:
            # Supabase에서는 ilike를 사용하여 대소문자 구분 없이 검색
            query = query.ilike('name', f'%{search}%')
        
        # 전체 항목 수 조회
        count_result = query.execute()
        total_count = len(count_result.data) if count_result.data else 0
        
        # 페이지네이션 적용
        offset = (page - 1) * page_size
        query = query.range(offset, offset + page_size - 1)
        
        # 사용자 데이터 조회
        result = query.execute()
        users_data = result.data if result.data else []
        
        # 응답 데이터 구성
        users = []
        for user in users_data:
            user_id = user.get('id')
            
            # 기본 사용자 정보 구성 (profiles 테이블에서 직접 조회)
            user_info = {
                "id": user_id,
                "email": user.get('email', ''),  # profiles에 email 필드가 있다면
                "name": user.get('name', '사용자'),
                "avatar": user.get('avatar', ''),
                "role": user.get('role', 'user'),
                "department": user.get('department', ''),
                "position": user.get('position', ''),
                "phone": user.get('phone', ''),
                "bio": user.get('bio', ''),
                "location": user.get('location', ''),
                "website": user.get('website', ''),
                "created_at": user.get('created_at'),
                "updated_at": user.get('updated_at')
            }
            users.append(user_info)
        
        # 전체 페이지 수 계산
        total_pages = (total_count + page_size - 1) // page_size
        
        # department 기준으로 그룹화
        users_by_department = {}
        for user in users:
            department = user.get('department', '부서 미지정')
            if department not in users_by_department:
                users_by_department[department] = []
            users_by_department[department].append(user)
        
        # 각 부서별로 사용자 수 계산
        department_stats = {}
        for department, dept_users in users_by_department.items():
            department_stats[department] = {
                "count": len(dept_users),
                "users": dept_users
            }
        
        return {
            "users": users,
            "users_by_department": department_stats,
            "total": total_count,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_previous": page > 1,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"사용자 목록 조회 중 오류: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"사용자 목록 조회 중 오류가 발생했습니다: {str(e)}"
        )

@router.get("/users/online-status")
async def get_users_online_status(
    user_ids: Optional[List[str]] = Query(None, description="특정 사용자 ID 목록 (없으면 전체)"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """사용자들의 온라인 상태 조회 (WebSocket 상태와 결합)"""
    try:
        if not supabase:
            raise HTTPException(
                status_code=500,
                detail="Supabase 클라이언트가 초기화되지 않았습니다"
            )
        
        # Supabase profiles 테이블에서 사용자 목록 조회 (본인 제외)
        if user_ids:
            # 특정 사용자 ID들만 조회 (본인 제외)
            filtered_user_ids = [uid for uid in user_ids if uid != current_user["id"]]
            query = supabase.table('profiles').select('*').in_('id', filtered_user_ids)
        else:
            # 전체 사용자 조회 (본인 제외)
            query = supabase.table('profiles').select('*').neq('id', current_user["id"])
        
        result = query.execute()
        users_data = result.data if result.data else []
        
        # 각 사용자의 온라인 상태 확인
        users_status = []
        for user in users_data:
            user_id = user.get('id')
            is_online = manager.get_connection_status(user_id)
            
            # 사용자 기본 정보 구성 (profiles 테이블에서 직접 조회)
            user_info = {
                "id": user_id,
                "name": user.get('full_name', '사용자'),
                "email": user.get('email', ''),
                "avatar": user.get('avatar'),
                "online": is_online,
                "last_seen": None,  # profiles에는 last_sign_in_at이 없을 수 있음
                "status": "オンライン" if is_online else "オフライン",
                "role": user.get('role', 'user'),
                "department": user.get('department', ''),
                "position": user.get('position', ''),
                "phone": user.get('phone', '')
            }
            users_status.append(user_info)
        
        # 온라인 사용자 순으로 정렬
        users_status.sort(key=lambda x: (not x["online"], x["name"]))
        
        return {
            "total_users": len(users_status),
            "online_count": sum(1 for user in users_status if user["online"]),
            "offline_count": sum(1 for user in users_status if not user["online"]),
            "users": users_status,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"사용자 온라인 상태 조회 중 오류: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"사용자 온라인 상태 조회 중 오류가 발생했습니다: {str(e)}"
        )
