# Sousei System Backend

Sousei System의 백엔드 API 서버입니다.

## 주요 기능

- 학생 관리
- 회사 관리
- 건물 및 방 관리
- 요금 관리
- 고령자 관리
- **채팅 시스템** (신규 추가)

## 채팅 시스템

### 테이블 구조

- `conversations`: 대화방 (DM/그룹)
- `conversation_members`: 대화 참여자
- `messages`: 메시지
- `message_reads`: 메시지 읽음 상태
- `attachments`: 첨부파일 메타데이터
- `reactions`: 이모지 반응

### 실시간 기능 (WebSocket)

- **실시간 메시지 전송/수신**
- **사용자 온라인 상태 추적**
- **타이핑 인디케이터**
- **대화방 참여/나감 알림**
- **연결 상태 모니터링**

### API 엔드포인트

- `POST /chat/conversations`: 새 대화 생성
- `GET /chat/conversations`: 대화 목록 조회
- `GET /chat/conversations/{id}`: 특정 대화 정보
- `PUT /chat/conversations/{id}`: 대화 정보 수정
- `POST /chat/conversations/{id}/messages`: 메시지 전송
- `GET /chat/conversations/{id}/messages`: 메시지 목록
- `PUT /chat/messages/{id}`: 메시지 수정
- `DELETE /chat/messages/{id}`: 메시지 삭제
- `POST /chat/messages/{id}/read`: 메시지 읽음 처리
- `POST /chat/messages/{id}/reactions`: 이모지 반응 추가
- `DELETE /chat/messages/{id}/reactions/{emoji}`: 이모지 반응 제거

### WebSocket 엔드포인트

- `WS /ws/chat`: 실시간 채팅 WebSocket 연결
- `GET /ws/status`: WebSocket 연결 상태 조회
- `GET /ws/users/{user_id}/status`: 사용자별 연결 상태 조회
- `GET /ws/conversations/{conversation_id}/members`: 대화방 온라인 참여자 조회

## 설치 및 실행

1. 의존성 설치
```bash
pip install -r requirements.txt
```

2. 환경 변수 설정
```bash
# .env 파일 생성
DATABASE_URL=your_database_url
SUPABASE_URL=your_supabase_url
SUPABASE_ANON_KEY=your_supabase_anon_key
SUPABASE_SERVICE_ROLE_KEY=your_supabase_service_role_key
```

3. 데이터베이스 테이블 생성
```bash
# 채팅 테이블 생성
psql -d your_database -f chat_tables.sql
```

4. 서버 실행
```bash
uvicorn main:app --reload
```

## 개발 환경

- Python 3.8+
- FastAPI
- SQLAlchemy
- PostgreSQL
- Supabase
