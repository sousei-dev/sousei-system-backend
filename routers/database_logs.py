from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from typing import Optional, List
from database import SessionLocal
from models import DatabaseLog
from datetime import datetime, date
import uuid

router = APIRouter(prefix="/database-logs", tags=["데이터베이스 로그"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/")
def get_database_logs(
    table_name: Optional[str] = Query(None, description="테이블명으로 필터링"),
    action: Optional[str] = Query(None, description="액션으로 필터링"),
    user_id: Optional[str] = Query(None, description="사용자 ID로 필터링"),
    start_date: Optional[date] = Query(None, description="시작 날짜"),
    end_date: Optional[date] = Query(None, description="종료 날짜"),
    page: int = Query(1, description="페이지 번호", ge=1),
    page_size: int = Query(10, description="페이지당 항목 수", ge=1, le=100),
    db: Session = Depends(get_db)
):
    """데이터베이스 로그 목록 조회"""
    try:
        query = db.query(DatabaseLog)
        
        # 필터링 적용
        if table_name:
            query = query.filter(DatabaseLog.table_name == table_name)
        if action:
            query = query.filter(DatabaseLog.action == action)
        if user_id:
            query = query.filter(DatabaseLog.user_id == user_id)
        if start_date:
            query = query.filter(DatabaseLog.created_at >= start_date)
        if end_date:
            query = query.filter(DatabaseLog.created_at <= end_date)
        
        # 최신순으로 정렬
        query = query.order_by(DatabaseLog.created_at.desc())
        
        # 전체 항목 수 계산
        total_count = query.count()
        
        # 페이지네이션 적용
        logs = query.offset((page - 1) * page_size).limit(page_size).all()
        
        # 전체 페이지 수 계산
        total_pages = (total_count + page_size - 1) // page_size
        
        # 응답 데이터 준비
        result = []
        for log in logs:
            log_data = {
                "id": str(log.id),
                "table_name": log.table_name,
                "record_id": log.record_id,
                "action": log.action,
                "user_id": log.user_id,
                "old_values": log.old_values,
                "new_values": log.new_values,
                "changed_fields": log.changed_fields,
                "ip_address": log.ip_address,
                "user_agent": log.user_agent,
                "note": log.note,
                "created_at": log.created_at
            }
            result.append(log_data)
        
        return {
            "items": result,
            "total": total_count,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_previous": page > 1
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"데이터베이스 로그 조회 중 오류가 발생했습니다: {str(e)}")

@router.get("/tables")
def get_logged_tables(db: Session = Depends(get_db)):
    """로그가 기록된 테이블 목록 조회"""
    try:
        tables = db.query(DatabaseLog.table_name).distinct().all()
        table_list = [table[0] for table in tables if table[0]]
        
        return {
            "logged_tables": table_list,
            "total_tables": len(table_list)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"테이블 목록 조회 중 오류가 발생했습니다: {str(e)}")

@router.get("/actions")
def get_logged_actions(db: Session = Depends(get_db)):
    """로그에 기록된 액션 목록 조회"""
    try:
        actions = db.query(DatabaseLog.action).distinct().all()
        action_list = [action[0] for action in actions if action[0]]
        
        return {
            "logged_actions": action_list,
            "total_actions": len(action_list)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"액션 목록 조회 중 오류가 발생했습니다: {str(e)}")

@router.get("/users")
def get_logged_users(db: Session = Depends(get_db)):
    """로그를 생성한 사용자 목록 조회"""
    try:
        users = db.query(DatabaseLog.user_id).distinct().all()
        user_list = [user[0] for user in users if user[0]]
        
        return {
            "logged_users": user_list,
            "total_users": len(user_list)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"사용자 목록 조회 중 오류가 발생했습니다: {str(e)}")

@router.get("/summary")
def get_log_summary(
    start_date: Optional[date] = Query(None, description="시작 날짜"),
    end_date: Optional[date] = Query(None, description="종료 날짜"),
    db: Session = Depends(get_db)
):
    """데이터베이스 로그 요약 정보 조회"""
    try:
        query = db.query(DatabaseLog)
        
        # 날짜 필터링
        if start_date:
            query = query.filter(DatabaseLog.created_at >= start_date)
        if end_date:
            query = query.filter(DatabaseLog.created_at <= end_date)
        
        # 전체 로그 수
        total_logs = query.count()
        
        # 액션별 통계
        action_stats = db.query(
            DatabaseLog.action,
            db.func.count(DatabaseLog.id).label('count')
        ).group_by(DatabaseLog.action).all()
        
        action_summary = [
            {
                "action": stat.action,
                "count": stat.count,
                "percentage": round((stat.count / total_logs * 100), 2) if total_logs > 0 else 0
            }
            for stat in action_stats
        ]
        
        # 테이블별 통계
        table_stats = db.query(
            DatabaseLog.table_name,
            db.func.count(DatabaseLog.id).label('count')
        ).group_by(DatabaseLog.table_name).all()
        
        table_summary = [
            {
                "table_name": stat.table_name,
                "count": stat.count,
                "percentage": round((stat.count / total_logs * 100), 2) if total_logs > 0 else 0
            }
            for stat in table_stats
        ]
        
        # 일별 통계 (최근 30일)
        today = datetime.now().date()
        daily_stats = []
        for i in range(30):
            target_date = today - datetime.timedelta(days=i)
            daily_count = query.filter(
                db.func.date(DatabaseLog.created_at) == target_date
            ).count()
            
            daily_stats.append({
                "date": target_date.isoformat(),
                "count": daily_count
            })
        
        daily_stats.reverse()  # 최신순으로 정렬
        
        return {
            "summary_period": {
                "start_date": start_date.isoformat() if start_date else None,
                "end_date": end_date.isoformat() if end_date else None
            },
            "total_logs": total_logs,
            "action_summary": action_summary,
            "table_summary": table_summary,
            "daily_stats": daily_stats
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"로그 요약 정보 조회 중 오류가 발생했습니다: {str(e)}")

@router.get("/{log_id}")
def get_database_log(log_id: str, db: Session = Depends(get_db)):
    """특정 데이터베이스 로그 상세 정보 조회"""
    try:
        log = db.query(DatabaseLog).filter(DatabaseLog.id == log_id).first()
        
        if not log:
            raise HTTPException(status_code=404, detail="데이터베이스 로그를 찾을 수 없습니다")
        
        log_data = {
            "id": str(log.id),
            "table_name": log.table_name,
            "record_id": log.record_id,
            "action": log.action,
            "user_id": log.user_id,
            "old_values": log.old_values,
            "new_values": log.new_values,
            "changed_fields": log.changed_fields,
            "ip_address": log.ip_address,
            "user_agent": log.user_agent,
            "note": log.note,
            "created_at": log.created_at
        }
        
        return log_data
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"데이터베이스 로그 상세 정보 조회 중 오류가 발생했습니다: {str(e)}") 