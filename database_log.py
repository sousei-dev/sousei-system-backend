from sqlalchemy.orm import Session
from models import DatabaseLog
from datetime import datetime
import uuid
import json

def create_database_log(
    db: Session,
    table_name: str,
    record_id: str,
    action: str,
    user_id: str = None,
    old_values: dict = None,
    new_values: dict = None,
    changed_fields: list = None,
    note: str = None,
    ip_address: str = None,
    user_agent: str = None
):
    """
    데이터베이스 로그 생성
    
    Args:
        db: 데이터베이스 세션
        table_name: 테이블명
        record_id: 레코드 ID
        action: 수행된 액션 (CREATE, UPDATE, DELETE)
        user_id: 사용자 ID (선택사항)
        old_values: 이전 값들 (선택사항)
        new_values: 새로운 값들 (선택사항)
        changed_fields: 변경된 필드들 (선택사항)
        note: 추가 노트 (선택사항)
        ip_address: IP 주소 (선택사항)
        user_agent: User Agent (선택사항)
    """
    try:
        # DatabaseLog 모델이 없는 경우를 대비한 예외 처리
        if not hasattr(db, 'query'):
            print(f"DatabaseLog 생성 실패: 데이터베이스 세션이 올바르지 않습니다.")
            return
        
        # dict와 list를 JSON 문자열로 변환
        old_values_json = json.dumps(old_values, ensure_ascii=False, default=str) if old_values else None
        new_values_json = json.dumps(new_values, ensure_ascii=False, default=str) if new_values else None
        changed_fields_json = json.dumps(changed_fields, ensure_ascii=False, default=str) if changed_fields else None
        
        # 로그 레코드 생성
        log_entry = DatabaseLog(
            id=str(uuid.uuid4()),
            table_name=table_name,
            record_id=record_id,
            action=action,
            user_id=user_id,
            old_values=old_values_json,
            new_values=new_values_json,
            changed_fields=changed_fields_json,
            ip_address=ip_address,
            user_agent=user_agent,
            note=note,
        )
        
        db.add(log_entry)
        db.commit()
        
        print(f"DatabaseLog 생성 완료: {action} on {table_name} - {record_id}")
        
    except Exception as e:
        print(f"DatabaseLog 생성 중 오류 발생: {str(e)}")
        # 로그 생성 실패 시에도 메인 기능은 계속 진행
        try:
            db.rollback()
        except:
            pass 