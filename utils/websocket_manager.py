import json
import asyncio
from typing import Dict, List, Set, Optional, Tuple
from fastapi import WebSocket, WebSocketDisconnect
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class ConnectionManager:
    """WebSocket 연결을 관리하는 클래스 - 채팅방별 동적 연결/해제 지원"""
    
    def __init__(self):
        # 사용자별 WebSocket 연결 저장 (전역 연결)
        self.active_connections: Dict[str, WebSocket] = {}
        # 채팅방별 WebSocket 연결 저장 (채팅방별 연결)
        self.room_connections: Dict[str, Dict[str, WebSocket]] = {}
        # 대화방별 참여자 목록 저장
        self.conversation_members: Dict[str, Set[str]] = {}
        # 사용자별 참여 중인 대화방 목록
        self.user_conversations: Dict[str, Set[str]] = {}
        # 사용자별 채팅방 연결 상태
        self.user_room_status: Dict[str, Set[str]] = {}
    
    async def connect(self, websocket: WebSocket, user_id: str):
        """사용자 전역 WebSocket 연결 (기본 연결)"""
        try:
            await websocket.accept()
            self.active_connections[user_id] = websocket
            self.user_conversations[user_id] = set()
            self.user_room_status[user_id] = set()
            
            logger.info(f"사용자 {user_id} 전역 연결됨")
            
            # 연결 확인 메시지 전송
            await self.send_personal_message({
                "type": "connection_status",
                "status": "connected",
                "user_id": user_id,
                "timestamp": datetime.utcnow().isoformat()
            }, user_id)
            
        except Exception as e:
            logger.error(f"WebSocket 전역 연결 실패: {e}")
            raise
    
    async def connect_to_room(self, websocket: WebSocket, user_id: str, conversation_id: str):
        """사용자를 특정 채팅방에 연결"""
        try:
            logger.info(f"=== 사용자 {user_id}를 채팅방 {conversation_id}에 연결 시작 ===")
            
            # 연결 전 상태 로그
            if conversation_id in self.room_connections:
                logger.info(f"  - 연결 전 채팅방에 연결된 사용자: {list(self.room_connections[conversation_id].keys())}")
            else:
                logger.info(f"  - 연결 전 채팅방 연결 없음")
            
            if user_id in self.user_room_status:
                logger.info(f"  - 연결 전 사용자가 연결된 채팅방: {list(self.user_room_status[user_id])}")
            else:
                logger.info(f"  - 연결 전 사용자 연결 상태 없음")
            
            await websocket.accept()
            logger.info(f"  - WebSocket 연결 수락 완료")
            
            # 채팅방 연결 초기화
            if conversation_id not in self.room_connections:
                self.room_connections[conversation_id] = {}
                logger.info(f"  - 새 채팅방 연결 딕셔너리 생성")
            
            self.room_connections[conversation_id][user_id] = websocket
            logger.info(f"  - 채팅방 연결에 사용자 추가 완료")
            
            # 참여자 목록 업데이트
            if conversation_id not in self.conversation_members:
                self.conversation_members[conversation_id] = set()
                logger.info(f"  - 새 참여자 목록 생성")
            
            self.conversation_members[conversation_id].add(user_id)
            logger.info(f"  - 참여자 목록에 사용자 추가 완료")
            
            # 사용자별 참여 대화방 목록 업데이트
            if user_id not in self.user_conversations:
                self.user_conversations[user_id] = set()
                logger.info(f"  - 새 사용자별 참여 대화방 목록 생성")
            
            self.user_conversations[user_id].add(conversation_id)
            logger.info(f"  - 사용자별 참여 대화방 목록에 추가 완료")
            
            # 사용자별 채팅방 연결 상태 업데이트
            if user_id not in self.user_room_status:
                self.user_room_status[user_id] = set()
                logger.info(f"  - 새 사용자별 채팅방 연결 상태 생성")
            
            self.user_room_status[user_id].add(conversation_id)
            logger.info(f"  - 사용자별 채팅방 연결 상태에 추가 완료")
            
            # 연결 후 상태 로그
            logger.info(f"  - 연결 후 채팅방에 연결된 사용자: {list(self.room_connections[conversation_id].keys())}")
            logger.info(f"  - 연결 후 사용자가 연결된 채팅방: {list(self.user_room_status[user_id])}")
            
            logger.info(f"사용자 {user_id}가 채팅방 {conversation_id}에 연결됨")
            
            # 채팅방 입장 알림 전송
            await self.send_room_message({
                "type": "user_joined_room",
                "user_id": user_id,
                "conversation_id": conversation_id,
                "timestamp": datetime.utcnow().isoformat()
            }, conversation_id, exclude_user=user_id)
            logger.info(f"  - 채팅방 입장 알림 전송 완료")
            
            # 개인 입장 확인 메시지
            await self.send_room_personal_message({
                "type": "room_connected",
                "conversation_id": conversation_id,
                "status": "connected",
                "timestamp": datetime.utcnow().isoformat()
            }, user_id, conversation_id)
            logger.info(f"  - 개인 입장 확인 메시지 전송 완료")
            
        except Exception as e:
            logger.error(f"채팅방 연결 실패 (사용자: {user_id}, 채팅방: {conversation_id}): {e}")
            raise
    
    def disconnect_from_room(self, user_id: str, conversation_id: str):
        """사용자를 특정 채팅방에서 연결 해제"""
        try:
            logger.info(f"=== 채팅방 {conversation_id}에서 사용자 {user_id} 연결 해제 시작 ===")
            
            # 연결 해제 전 상태 로그
            if conversation_id in self.room_connections:
                logger.info(f"  - 해제 전 채팅방 연결된 사용자: {list(self.room_connections[conversation_id].keys())}")
            else:
                logger.info(f"  - 해제 전 채팅방 연결 없음")
            
            # 채팅방 연결 제거
            if (conversation_id in self.room_connections and 
                user_id in self.room_connections[conversation_id]):
                del self.room_connections[conversation_id][user_id]
                logger.info(f"  - 채팅방 연결에서 사용자 제거 완료")
                
                # 채팅방에 연결된 사용자가 없으면 채팅방 제거
                if not self.room_connections[conversation_id]:
                    del self.room_connections[conversation_id]
                    logger.info(f"  - 빈 채팅방 제거 완료")
                else:
                    logger.info(f"  - 채팅방에 남은 사용자: {list(self.room_connections[conversation_id].keys())}")
            else:
                logger.info(f"  - 채팅방 연결에서 사용자를 찾을 수 없음")
            
            # 참여자 목록은 유지 (실제 멤버십이므로 WebSocket 연결과 무관)
            # self.conversation_members는 실제 대화방 멤버십을 나타내므로 제거하지 않음
            logger.info(f"  - 참여자 목록은 유지 (실제 멤버십)")
            
            # 사용자별 참여 대화방 목록은 유지 (실제 멤버십이므로 WebSocket 연결과 무관)
            # self.user_conversations는 실제 참여 대화방을 나타내므로 제거하지 않음
            logger.info(f"  - 사용자별 참여 대화방 목록은 유지 (실제 멤버십)")
            
            # 사용자별 채팅방 연결 상태에서 제거
            if user_id in self.user_room_status:
                self.user_room_status[user_id].discard(conversation_id)
                logger.info(f"  - 사용자별 채팅방 연결 상태에서 제거 완료")
                
                if not self.user_room_status[user_id]:
                    logger.info(f"  - 사용자의 채팅방 연결 상태가 없음")
                else:
                    logger.info(f"  - 사용자가 연결된 채팅방: {list(self.user_room_status[user_id])}")
            else:
                logger.info(f"  - 사용자별 채팅방 연결 상태에서 사용자를 찾을 수 없음")
            
            logger.info(f"사용자 {user_id}가 채팅방 {conversation_id}에서 연결 해제됨")
            
        except Exception as e:
            logger.error(f"채팅방 연결 해제 실패: {e}")
    
    def disconnect(self, user_id: str):
        """사용자 전역 WebSocket 연결 해제"""
        if user_id in self.active_connections:
            del self.active_connections[user_id]
        
        # 사용자가 연결된 모든 채팅방에서 제거
        if user_id in self.user_room_status:
            room_list = list(self.user_room_status[user_id])
            for conversation_id in room_list:
                self.disconnect_from_room(user_id, conversation_id)
            
            del self.user_room_status[user_id]
        
        # user_conversations는 실제 멤버십이므로 WebSocket 연결과 무관하게 유지
        # del self.user_conversations[user_id]  # 제거하지 않음
        
        logger.info(f"사용자 {user_id} 전역 연결 해제됨")
    
    def join_conversation(self, user_id: str, conversation_id: str):
        """사용자를 대화방에 참여시킴 (기존 방식 유지)"""
        if conversation_id not in self.conversation_members:
            self.conversation_members[conversation_id] = set()
        
        self.conversation_members[conversation_id].add(user_id)
        
        if user_id not in self.user_conversations:
            self.user_conversations[user_id] = set()
        
        self.user_conversations[user_id].add(conversation_id)
        
        logger.info(f"사용자 {user_id}가 대화방 {conversation_id}에 참여")
    
    def leave_conversation(self, user_id: str, conversation_id: str):
        """사용자를 대화방에서 제거 (기존 방식 유지)"""
        if conversation_id in self.conversation_members:
            self.conversation_members[conversation_id].discard(user_id)
            
            # 대화방에 참여자가 없으면 대화방 제거
            if not self.conversation_members[conversation_id]:
                del self.conversation_members[conversation_id]
        
        if user_id in self.user_conversations:
            self.user_conversations[user_id].discard(conversation_id)
        
        logger.info(f"사용자 {user_id}가 대화방 {conversation_id}에서 나감")
    
    async def send_personal_message(self, message: dict, user_id: str):
        """특정 사용자에게 개인 메시지 전송 (전역 연결)"""
        if user_id in self.active_connections:
            try:
                await self.active_connections[user_id].send_text(json.dumps(message))
            except Exception as e:
                logger.error(f"개인 메시지 전송 실패 (사용자: {user_id}): {e}")
                # 연결이 끊어진 경우 정리
                self.disconnect(user_id)
    
    async def send_room_personal_message(self, message: dict, user_id: str, conversation_id: str):
        """특정 사용자에게 채팅방 개인 메시지 전송"""
        if (conversation_id in self.room_connections and 
            user_id in self.room_connections[conversation_id]):
            try:
                await self.room_connections[conversation_id][user_id].send_text(json.dumps(message))
            except Exception as e:
                logger.error(f"채팅방 개인 메시지 전송 실패 (사용자: {user_id}, 채팅방: {conversation_id}): {e}")
                # 연결이 끊어진 경우 정리
                self.disconnect_from_room(user_id, conversation_id)
    
    async def send_to_conversation(self, message: dict, conversation_id: str, exclude_user: Optional[str] = None):
        """대화방의 모든 참여자에게 메시지 전송 (기존 방식)"""
        if conversation_id not in self.conversation_members:
            return
        
        disconnected_users = []
        
        for user_id in self.conversation_members[conversation_id]:
            # 특정 사용자 제외
            if exclude_user and user_id == exclude_user:
                continue
            
            if user_id in self.active_connections:
                try:
                    await self.active_connections[user_id].send_text(json.dumps(message))
                except Exception as e:
                    logger.error(f"대화방 메시지 전송 실패 (사용자: {user_id}): {e}")
                    disconnected_users.append(user_id)
            else:
                # 연결이 끊어진 사용자
                disconnected_users.append(user_id)
        
        # 연결이 끊어진 사용자들 정리
        for user_id in disconnected_users:
            self.disconnect(user_id)
    
    async def send_room_message(self, message: dict, conversation_id: str, exclude_user: Optional[str] = None):
        """채팅방의 모든 참여자에게 메시지 전송 (채팅방별 연결)"""
        if conversation_id not in self.room_connections:
            return
        
        disconnected_users = []
        
        for user_id, websocket in self.room_connections[conversation_id].items():
            # 특정 사용자 제외
            if exclude_user and user_id == exclude_user:
                continue
            
            try:
                await websocket.send_text(json.dumps(message))
            except Exception as e:
                logger.error(f"채팅방 메시지 전송 실패 (사용자: {user_id}, 채팅방: {conversation_id}): {e}")
                disconnected_users.append(user_id)
        
        # 연결이 끊어진 사용자들 정리
        for user_id in disconnected_users:
            self.disconnect_from_room(user_id, conversation_id)
    
    async def send_chat_list_update(self, conversation_id: str, update_type: str, update_data: dict, exclude_user: Optional[str] = None):
        """채팅 변경 시 모든 참여자의 채팅 리스트 업데이트"""
        if conversation_id not in self.conversation_members:
            logger.warning(f"대화방 {conversation_id}에 참여자가 없음")
            return
        
        # 채팅 리스트 업데이트 메시지 구성
        update_message = {
            "type": "chat_list_update",
            "conversation_id": conversation_id,
            "update_type": update_type,  # "new_message", "message_updated", "message_deleted", "conversation_updated"
            "update_data": update_data,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        logger.info(f"채팅 리스트 업데이트 전송 시작: {conversation_id}, 타입: {update_type}, 참여자: {len(self.conversation_members[conversation_id])}명")
        logger.info(f"참여자 목록: {list(self.conversation_members[conversation_id])}")
        logger.info(f"현재 연결된 채팅방들: {list(self.room_connections.keys())}")
        for room_id, users in self.room_connections.items():
            logger.info(f"  - 채팅방 {room_id}: {list(users.keys())}")
        
        # 모든 참여자에게 메시지 전송 (연결 방식에 관계없이)
        sent_count = 0
        failed_users = []
        
        for user_id in self.conversation_members[conversation_id]:
            # 특정 사용자 제외
            if exclude_user and user_id == exclude_user:
                continue
            
            message_sent = False
            
            # 1. 채팅방별 연결 시도 (우선순위 1) - 해당 방에 있는 경우
            if (conversation_id in self.room_connections and 
                user_id in self.room_connections[conversation_id]):
                try:
                    await self.room_connections[conversation_id][user_id].send_text(json.dumps(update_message))
                    message_sent = True
                    sent_count += 1
                except Exception as e:
                    logger.error(f"채팅방별 연결로 사용자 {user_id}에게 전송 실패: {e}")
                    failed_users.append(user_id)
            
            # 2. 다른 채팅방에 연결된 경우 (우선순위 2) - 다른 방에 있는 경우
            if not message_sent:
                # 사용자가 다른 채팅방에 연결되어 있는지 확인
                user_connected_rooms = self.get_user_room_status(user_id)
                logger.info(f"사용자 {user_id}의 연결된 채팅방들: {user_connected_rooms}")
                if user_connected_rooms:
                    for room_id in user_connected_rooms:
                        if room_id != conversation_id:  # 다른 방에 연결된 경우
                            logger.info(f"다른 채팅방 {room_id}를 통해 사용자 {user_id}에게 메시지 전송 시도")
                            try:
                                await self.room_connections[room_id][user_id].send_text(json.dumps(update_message))
                                logger.info(f"다른 채팅방 {room_id}를 통해 사용자 {user_id}에게 메시지 전송 성공")
                                message_sent = True
                                sent_count += 1
                                break
                            except Exception as e:
                                logger.error(f"다른 채팅방({room_id}) 연결로 사용자 {user_id}에게 전송 실패: {e}")
                                continue
            
            # 3. 전역 연결 시도 (우선순위 3) - 방에 들어가지 않아도 항상 받을 수 있도록
            if not message_sent and user_id in self.active_connections:
                try:
                    await self.active_connections[user_id].send_text(json.dumps(update_message))
                    message_sent = True
                    sent_count += 1
                except Exception as e:
                    logger.error(f"전역 연결로 사용자 {user_id}에게 전송 실패: {e}")
                    failed_users.append(user_id)
            
            if not message_sent:
                logger.warning(f"사용자 {user_id}에게 메시지 전송 실패 - 모든 연결 방식 시도됨")
                failed_users.append(user_id)
        
        # 연결이 끊어진 사용자들 정리
        for user_id in failed_users:
            # 모든 연결에서 사용자 제거
            if user_id in self.active_connections:
                self.disconnect(user_id)
            else:
                # 개별 채팅방에서 제거
                for room_id in list(self.room_connections.keys()):
                    if user_id in self.room_connections[room_id]:
                        self.disconnect_from_room(user_id, room_id)
        
        logger.info(f"채팅 리스트 업데이트 전송 완료: {conversation_id}, 성공: {sent_count}명, 실패: {len(failed_users)}명")
        
        return {
            "success_count": sent_count,
            "failed_count": len(failed_users),
            "failed_users": failed_users
        }
    
    async def send_conversation_update(self, conversation_id: str, update_type: str, update_data: dict, exclude_user: Optional[str] = None):
        """대화방 정보 변경 시 모든 참여자에게 업데이트 알림"""
        if conversation_id not in self.conversation_members:
            logger.warning(f"대화방 {conversation_id}에 참여자가 없음")
            return
        
        # 대화방 업데이트 메시지 구성
        update_message = {
            "type": "conversation_update",
            "conversation_id": conversation_id,
            "update_type": update_type,  # "title_changed", "member_added", "member_removed", "conversation_deleted"
            "update_data": update_data,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        logger.info(f"=== 대화방 업데이트 전송 시작: {conversation_id} ===")
        logger.info(f"  - 업데이트 타입: {update_type}")
        logger.info(f"  - 참여자 목록: {list(self.conversation_members[conversation_id])}")
        logger.info(f"  - 제외할 사용자: {exclude_user}")
        
        # 모든 참여자에게 메시지 전송 (연결 방식에 관계없이)
        sent_count = 0
        failed_users = []
        
        for user_id in self.conversation_members[conversation_id]:
            # 특정 사용자 제외
            if exclude_user and user_id == exclude_user:
                logger.info(f"  - 사용자 {user_id} 제외됨")
                continue
            
            message_sent = False
            
            # 1. 채팅방별 연결 시도 (우선순위 1)
            if (conversation_id in self.room_connections and 
                user_id in self.room_connections[conversation_id]):
                try:
                    await self.room_connections[conversation_id][user_id].send_text(json.dumps(update_message))
                    logger.info(f"  ✅ 채팅방별 연결로 사용자 {user_id}에게 전송 성공")
                    message_sent = True
                    sent_count += 1
                except Exception as e:
                    logger.error(f"  ❌ 채팅방별 연결로 사용자 {user_id}에게 전송 실패: {e}")
                    failed_users.append(user_id)
            
            # 2. 전역 연결 시도 (우선순위 2)
            if not message_sent and user_id in self.active_connections:
                try:
                    await self.active_connections[user_id].send_text(json.dumps(update_message))
                    logger.info(f"  ✅ 전역 연결로 사용자 {user_id}에게 전송 성공")
                    message_sent = True
                    sent_count += 1
                except Exception as e:
                    logger.error(f"  ❌ 전역 연결로 사용자 {user_id}에게 전송 실패: {e}")
                    failed_users.append(user_id)
            
            # 3. 다른 채팅방에 연결된 경우 (우선순위 3)
            if not message_sent:
                # 사용자가 다른 채팅방에 연결되어 있는지 확인
                user_connected_rooms = self.get_user_room_status(user_id)
                if user_connected_rooms:
                    for room_id in user_connected_rooms:
                        if room_id != conversation_id:  # 다른 방에 연결된 경우
                            try:
                                await self.room_connections[room_id][user_id].send_text(json.dumps(update_message))
                                logger.info(f"  ✅ 다른 채팅방({room_id}) 연결로 사용자 {user_id}에게 전송 성공")
                                message_sent = True
                                sent_count += 1
                                break
                            except Exception as e:
                                logger.error(f"  ❌ 다른 채팅방({room_id}) 연결로 사용자 {user_id}에게 전송 실패: {e}")
                                continue
                
                if not message_sent:
                    logger.warning(f"  ⚠️ 사용자 {user_id}에게 메시지 전송 실패 - 모든 연결 방식 시도됨")
                    failed_users.append(user_id)
        
        # 연결이 끊어진 사용자들 정리
        for user_id in failed_users:
            logger.info(f"  - 연결 끊어진 사용자 {user_id} 정리 시작")
            # 모든 연결에서 사용자 제거
            if user_id in self.active_connections:
                self.disconnect(user_id)
            else:
                # 개별 채팅방에서 제거
                for room_id in list(self.room_connections.keys()):
                    if user_id in self.room_connections[room_id]:
                        self.disconnect_from_room(user_id, room_id)
        
        logger.info(f"=== 대화방 업데이트 전송 완료: {conversation_id} ===")
        logger.info(f"  - 성공: {sent_count}명")
        logger.info(f"  - 실패: {len(failed_users)}명")
        logger.info(f"  - 실패한 사용자: {failed_users}")
        
        return {
            "success_count": sent_count,
            "failed_count": len(failed_users),
            "failed_users": failed_users
        }
    
    async def send_user_status_update(self, user_id: str, status: str, conversation_id: Optional[str] = None):
        """사용자 상태 변경 시 관련 사용자들에게 알림"""
        # 사용자가 참여 중인 모든 대화방에 상태 업데이트 전송
        user_conversations = self.get_user_conversations(user_id)
        
        status_message = {
            "type": "user_status_update",
            "user_id": user_id,
            "status": status,  # "online", "offline", "typing", "away"
            "conversation_id": conversation_id,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        for conv_id in user_conversations:
            # 특정 대화방이 지정된 경우 해당 대화방에만 전송
            if conversation_id and conv_id != conversation_id:
                continue
            
            # 채팅방별 연결이 있는 사용자들에게 전송
            if conv_id in self.room_connections:
                disconnected_users = []
                for uid, websocket in self.room_connections[conv_id].items():
                    if uid != user_id:  # 본인 제외
                        try:
                            await websocket.send_text(json.dumps(status_message))
                        except Exception as e:
                            logger.error(f"사용자 상태 업데이트 전송 실패 (채팅방별 연결): {e}")
                            disconnected_users.append(uid)
                
                # 연결이 끊어진 사용자들 정리
                for uid in disconnected_users:
                    self.disconnect_from_room(uid, conv_id)
            
            # 전역 연결이 있는 사용자들에게도 전송
            disconnected_users = []
            for uid in self.conversation_members.get(conv_id, set()):
                if uid != user_id and uid in self.active_connections:
                    try:
                        await self.active_connections[uid].send_text(json.dumps(status_message))
                    except Exception as e:
                        logger.error(f"사용자 상태 업데이트 전송 실패 (전역 연결): {e}")
                        disconnected_users.append(uid)
            
            # 연결이 끊어진 사용자들 정리
            for uid in disconnected_users:
                self.disconnect(uid)
        
        logger.info(f"사용자 상태 업데이트 전송 완료: {user_id}, 상태: {status}")
    
    async def broadcast(self, message: dict):
        """모든 연결된 사용자에게 메시지 브로드캐스트 (전역 연결)"""
        disconnected_users = []
        
        for user_id, websocket in self.active_connections.items():
            try:
                await websocket.send_text(json.dumps(message))
            except Exception as e:
                logger.error(f"브로드캐스트 메시지 전송 실패 (사용자: {user_id}): {e}")
                disconnected_users.append(user_id)
        
        # 연결이 끊어진 사용자들 정리
        for user_id in disconnected_users:
            self.disconnect(user_id)
    
    def get_connection_status(self, user_id: str) -> bool:
        """사용자의 전역 연결 상태 확인"""
        return user_id in self.active_connections
    
    def get_room_connection_status(self, user_id: str, conversation_id: str) -> bool:
        """사용자의 특정 채팅방 연결 상태 확인"""
        return (conversation_id in self.room_connections and 
                user_id in self.room_connections[conversation_id])
    
    def get_conversation_members(self, conversation_id: str) -> Set[str]:
        """대화방 참여자 목록 반환"""
        return self.conversation_members.get(conversation_id, set())
    
    def get_user_conversations(self, user_id: str) -> Set[str]:
        """사용자가 참여 중인 대화방 목록 반환"""
        return self.user_conversations.get(user_id, set())
    
    def get_online_users_count(self) -> int:
        """온라인 사용자 수 반환 (전역 연결)"""
        return len(self.active_connections)
    
    def get_active_conversations_count(self) -> int:
        """활성 대화방 수 반환"""
        return len(self.conversation_members)
    
    def get_room_connections_count(self, conversation_id: str) -> int:
        """특정 채팅방의 연결된 사용자 수 반환"""
        if conversation_id in self.room_connections:
            return len(self.room_connections[conversation_id])
        return 0
    
    def get_user_room_status(self, user_id: str) -> Set[str]:
        """사용자가 연결된 채팅방 목록 반환"""
        return self.user_room_status.get(user_id, set())
    
    def get_room_connection_info(self, conversation_id: str) -> Dict[str, str]:
        """채팅방의 연결 정보 반환 (사용자별 연결 상태)"""
        if conversation_id in self.room_connections:
            return {
                user_id: "connected" 
                for user_id in self.room_connections[conversation_id]
            }
        return {}

# 전역 WebSocket 매니저 인스턴스
manager = ConnectionManager() 