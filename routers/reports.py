from fastapi import APIRouter, Depends, HTTPException, Query, status, UploadFile, File, Form
from fastapi.security import HTTPBearer
from supabase import create_client
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from typing import Optional, List, Union
from database import SessionLocal, engine
from models import Report, ReportPhoto, ReportComment, Student, Company, Profiles
from schemas import ReportCreate, ReportUpdate, ReportResponse, ReportCommentCreate, ReportPhotoCreate
from datetime import datetime, date, timedelta
import uuid
from database_log import create_database_log
import os
import random
import string
from supabase import create_client
from utils.dependencies import get_current_user

router = APIRouter(prefix="/reports", tags=["리포트 관리"])

# Supabase 설정
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_token_header(token: str = Depends(HTTPBearer())):
    return token.credentials



def generate_random_filename(original_filename: str) -> str:
    """원본 파일명을 기반으로 랜덤한 영어 파일명 생성"""
    file_extension = original_filename.split(".")[-1].lower()
    random_string = ''.join(random.choices(string.ascii_lowercase + string.digits, k=16))
    new_filename = f"{random_string}.{file_extension}"
    return new_filename

# ===== Reports 관련 API들 =====

@router.get("")
def get_reports(
    report_type: Optional[str] = Query(None, description="보고 종류로 필터링 (defect/claim/other)"),
    status: Optional[str] = Query(None, description="상태로 필터링 (pending/in_progress/completed)"),
    occurrence_date_from: Optional[date] = Query(None, description="발생일 시작일"),
    occurrence_date_to: Optional[date] = Query(None, description="발생일 종료일"),
    page: int = Query(1, description="페이지 번호", ge=1),
    page_size: int = Query(10, description="페이지당 항목 수", ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: Optional[dict] = Depends(get_current_user)
):
    """리포트 목록 조회 (필터링, 페이지네이션 지원)"""
    try:
        # 기본 쿼리 생성
        query = db.query(Report).options(
            joinedload(Report.photos),
            joinedload(Report.comments)
        )
        
                # 로그인한 사용자가 있는 경우 권한 체크 (Profiles 테이블에서 확인)
        user_role = "user"
        is_admin = False
        if current_user:
            try:
                # Profiles 테이블에서 사용자 정보 조회
                user_profile = db.query(Profiles).filter(Profiles.id == current_user["id"]).first()
                if user_profile:
                    user_role = user_profile.role if hasattr(user_profile, 'role') else "user"
                    is_admin = user_role in ["admin", "super_admin", "manager"]
            except Exception as e:
                print(f"사용자 권한 확인 중 오류: {e}")
                user_role = "user"
                is_admin = False
        
        # 필터 조건 추가
        if report_type:
            query = query.filter(Report.report_type == report_type)
        if status:
            query = query.filter(Report.status == status)
        if occurrence_date_from:
            query = query.filter(Report.occurrence_date >= occurrence_date_from)
        if occurrence_date_to:
            query = query.filter(Report.occurrence_date <= occurrence_date_to)
        
        # reporter_id 필터 (admin이 아닌 경우에만 적용)
        if not is_admin and current_user:
            # 일반 사용자는 자신의 리포트만 조회
            query = query.filter(Report.reporter_id == current_user["id"])
        # 최신순으로 정렬
        query = query.order_by(Report.created_at.desc())
        
        # 전체 항목 수 계산
        total_count = query.count()
        
        # 페이지네이션 적용
        reports = query.offset((page - 1) * page_size).limit(page_size).all()
        
        # 전체 페이지 수 계산
        total_pages = (total_count + page_size - 1) // page_size
        
        # 응답 데이터 준비
        result = []
        for report in reports:
            # reporter 정보 조회
            reporter = db.query(Profiles).filter(Profiles.id == report.reporter_id).first()
            reporter_name = reporter.name if reporter else None
            
            # comments의 operator 정보 조회
            comments_with_operators = []
            for comment in report.comments:
                operator = db.query(Profiles).filter(Profiles.id == comment.operator_id).first()
                operator_name = operator.name if operator else None
                
                comments_with_operators.append({
                    "id": str(comment.id),
                    "operator_id": str(comment.operator_id),
                    "comment": comment.comment,
                    "created_at": comment.created_at.isoformat() + "Z" if comment.created_at else None,
                    "operator": {
                        "id": str(comment.operator_id),
                        "name": operator_name
                    }
                })
            
            report_data = {
                "id": str(report.id),
                "reporter_id": str(report.reporter_id),
                "occurrence_date": report.occurrence_date.strftime("%Y-%m-%d") if report.occurrence_date else None,
                "report_type": report.report_type,
                "report_content": report.report_content,
                "status": report.status,
                "created_at": report.created_at.strftime("%Y-%m-%d %H:%M:%S") if report.created_at else None,
                "photos_count": len(report.photos) if report.photos else 0,
                "comments_count": len(report.comments) if report.comments else 0,
                "photos": [
                    {
                        "id": str(photo.id),
                        "photo_url": photo.photo_url,
                        "filename": photo.photo_url.split("/")[-1] if photo.photo_url else None,
                        "uploaded_at": photo.uploaded_at.isoformat() + "Z" if photo.uploaded_at else None,
                        "thumbnail_url": photo.photo_url,
                        "is_public": True
                    } for photo in report.photos
                ] if report.photos else [],
                "comments": comments_with_operators,
                "reporter": {
                    "id": str(report.reporter_id),
                    "name": reporter_name,
                }
            }
            result.append(report_data)
        

        
        return {
            "items": result,
            "total": total_count,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_previous": page > 1,
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"리포트 목록 조회 중 오류가 발생했습니다: {str(e)}")

@router.get("/{report_id}")
def get_report(
    report_id: str,
    db: Session = Depends(get_db)
):
    """특정 리포트 상세 정보 조회"""
    try:
        report = db.query(Report).options(
            joinedload(Report.photos),
            joinedload(Report.comments)
        ).filter(Report.id == report_id).first()
        
        if not report:
            raise HTTPException(status_code=404, detail="리포트를 찾을 수 없습니다")
        
        # reporter 정보 조회
        reporter = db.query(Profiles).filter(Profiles.id == report.reporter_id).first()
        reporter_name = reporter.name if reporter else None
        
        # comments의 operator 정보 조회
        comments_with_operators = []
        for comment in report.comments:
            operator = db.query(Profiles).filter(Profiles.id == comment.operator_id).first()
            operator_name = operator.name if operator else None
            
            comments_with_operators.append({
                "id": str(comment.id),
                "operator_id": str(comment.operator_id),
                "comment": comment.comment,
                                    "created_at": comment.created_at.isoformat() + "Z" if comment.created_at else None,
                "operator": {
                    "id": str(comment.operator_id),
                    "name": operator_name
                }
            })
        
        # 응답 데이터 준비
        report_data = {
            "id": str(report.id),
            "reporter_id": str(report.reporter_id),
            "occurrence_date": report.occurrence_date.strftime("%Y-%m-%d") if report.occurrence_date else None,
            "report_type": report.report_type,
            "report_content": report.report_content,
            "status": report.status,
            "created_at": report.created_at.strftime("%Y-%m-%d %H:%M:%S") if report.created_at else None,
            "reporter": {
                "id": str(report.reporter_id),
                "name": reporter_name,
            },
            "photos_count": len(report.photos) if report.photos else 0,  # 사진 개수
            "photos": [
                {
                    "id": str(photo.id),
                    "photo_url": photo.photo_url,
                    "filename": photo.photo_url.split("/")[-1] if photo.photo_url else None,  # 파일명 추출
                    "uploaded_at": photo.uploaded_at.isoformat() + "Z" if photo.uploaded_at else None,
                    "file_size": None,  # 필요시 파일 크기 추가 가능
                    "thumbnail_url": photo.photo_url,  # 썸네일 URL (필요시 별도 생성)
                    "is_public": True  # 공개 여부
                } for photo in report.photos
            ] if report.photos else [],
            "comments": comments_with_operators
        }
        
        return report_data
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"리포트 상세 조회 중 오류가 발생했습니다: {str(e)}")

@router.post("/", status_code=201)
def create_report(
    report: ReportCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """새로운 리포트 생성"""
    try:
        # 새 리포트 객체 생성
        new_report = Report(
            id=str(uuid.uuid4()),
            reporter_id=current_user["id"],
            occurrence_date=report.occurrence_date,
            report_type=report.report_type,
            report_content=report.report_content,
            status="pending"
        )
        
        db.add(new_report)
        db.commit()
        db.refresh(new_report)
        
        # 데이터베이스 로그 생성
        try:
            create_database_log(
                db=db,
                table_name="reports",
                record_id=str(new_report.id),
                action="CREATE",
                user_id=current_user["id"] if current_user else None,
                new_values={
                    "reporter_id": str(new_report.reporter_id),
                    "occurrence_date": new_report.occurrence_date.strftime("%Y-%m-%d") if new_report.occurrence_date else None,
                    "report_type": new_report.report_type,
                    "report_content": new_report.report_content,
                    "status": new_report.status
                },
                changed_fields=["reporter_id", "occurrence_date", "report_type", "report_content", "status"],
                note=f"새로운 리포트 생성 - {new_report.report_type}: {new_report.report_content[:50]}..."
            )
        except Exception as log_error:
            print(f"로그 생성 중 오류: {log_error}")
        
        return {
            "message": "리포트가 성공적으로 생성되었습니다",
            "report": {
                "id": str(new_report.id),
                "reporter_id": str(new_report.reporter_id),
                "occurrence_date": new_report.occurrence_date.strftime("%Y-%m-%d") if new_report.occurrence_date else None,
                "report_type": new_report.report_type,
                "status": new_report.status
            }
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"리포트 생성 중 오류가 발생했습니다: {str(e)}")

@router.post("/with-photos", status_code=201)
async def create_report_with_photos(
    occurrence_date: str = Form(...),
    report_type: str = Form(...),
    report_content: str = Form(...),
    photos: List[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """사진과 함께 새로운 리포트 생성"""
    try:
        # 날짜 파싱
        try:
            parsed_date = datetime.strptime(occurrence_date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="날짜 형식이 올바르지 않습니다 (YYYY-MM-DD)")
        
        # 새 리포트 객체 생성
        new_report = Report(
            id=str(uuid.uuid4()),
            reporter_id=current_user["id"],
            occurrence_date=parsed_date,
            report_type=report_type,
            report_content=report_content,
            status="pending"
        )
        
        db.add(new_report)
        db.commit()
        db.refresh(new_report)
        
        # 사진 업로드 처리
        uploaded_photos = []
        
        if photos and len(photos) > 0:
            for photo in photos:
                try:
                    # 파일 확장자 검사
                    file_extension = photo.filename.split(".")[-1].lower()
                    if file_extension not in ["jpg", "jpeg", "png", "gif"]:
                        print(f"지원하지 않는 파일 형식: {file_extension}")
                        continue
                    
                    # 파일 크기 검사 (5MB)
                    file_size = 0
                    chunk_size = 1024 * 1024  # 1MB
                    while chunk := await photo.read(chunk_size):
                        file_size += len(chunk)
                        if file_size > 5 * 1024 * 1024:  # 5MB
                            print(f"파일 크기 초과: {file_size} bytes")
                            break
                    
                    # 파일을 다시 처음으로 되돌림
                    await photo.seek(0)
                    
                    # 랜덤 파일명 생성
                    random_filename = generate_random_filename(photo.filename)
                    
                    # Supabase Storage에 파일 업로드
                    file_path = f"report_photos/{new_report.id}/{random_filename}"
                    file_content = await photo.read()
                    
                    try:
                        # Supabase Storage에 파일 업로드
                        result = supabase.storage.from_("report_photos").upload(
                            file_path,
                            file_content,
                            {"content-type": photo.content_type}
                        )
                        
                        # 파일 URL 생성
                        file_url = supabase.storage.from_("report_photos").get_public_url(file_path)
                        
                        # 데이터베이스에 사진 정보 저장
                        new_photo = ReportPhoto(
                            id=str(uuid.uuid4()),
                            report_id=str(new_report.id),
                            photo_url=file_url
                        )
                        db.add(new_photo)
                        uploaded_photos.append({
                            "id": str(new_photo.id),
                            "photo_url": file_url,
                            "filename": random_filename
                        })
                        
                    except Exception as storage_error:
                        print(f"사진 업로드 실패: {storage_error}")
                        continue
                        
                except Exception as photo_error:
                    print(f"사진 처리 중 오류: {photo_error}")
                    continue
            
            # 사진 정보 커밋
            db.commit()
        
        # 데이터베이스 로그 생성
        try:
            create_database_log(
                db=db,
                table_name="reports",
                record_id=str(new_report.id),
                action="CREATE",
                user_id=current_user["id"] if current_user else None,
                new_values={
                    "reporter_id": str(new_report.reporter_id),
                    "occurrence_date": new_report.occurrence_date.strftime("%Y-%m-%d") if new_report.occurrence_date else None,
                    "report_type": new_report.report_type,
                    "report_content": new_report.report_content,
                    "status": new_report.status,
                    "photos_count": len(uploaded_photos)
                },
                changed_fields=["reporter_id", "occurrence_date", "report_type", "report_content", "status"],
                note=f"사진과 함께 리포트 생성 - {new_report.report_type}: {new_report.report_content[:50]}... (사진 {len(uploaded_photos)}개)"
            )
        except Exception as log_error:
            print(f"로그 생성 중 오류: {log_error}")
        
        return {
            "message": f"리포트가 성공적으로 생성되었습니다. 사진 {len(uploaded_photos)}개가 첨부되었습니다.",
            "report": {
                "id": str(new_report.id),
                "reporter_id": str(new_report.reporter_id),
                "occurrence_date": new_report.occurrence_date.strftime("%Y-%m-%d") if new_report.occurrence_date else None,
                "report_type": new_report.report_type,
                "status": new_report.status
            },
            "photos": uploaded_photos,
            "total_photos": len(uploaded_photos)
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"리포트 생성 중 오류가 발생했습니다: {str(e)}")

@router.put("/{report_id}")
def update_report(
    report_id: str,
    report_update: ReportUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """리포트 정보 수정"""
    try:
        # 리포트 존재 여부 확인
        report = db.query(Report).filter(Report.id == report_id).first()
        if not report:
            raise HTTPException(status_code=404, detail="리포트를 찾을 수 없습니다")
        
        # 기존 값 저장 (로그용)
        old_values = {
            "occurrence_date": report.occurrence_date.strftime("%Y-%m-%d") if report.occurrence_date else None,
            "report_type": report.report_type,
            "report_content": report.report_content,
            "status": report.status
        }
        
        # 리포트 정보 업데이트
        update_data = report_update.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(report, field, value)
        
        db.commit()
        db.refresh(report)
        
        # 데이터베이스 로그 생성
        try:
            create_database_log(
                db=db,
                table_name="reports",
                record_id=str(report.id),
                action="UPDATE",
                user_id=current_user["id"] if current_user else None,
                old_values=old_values,
                new_values={
                    "occurrence_date": report.occurrence_date.strftime("%Y-%m-%d") if report.occurrence_date else None,
                    "report_type": report.report_type,
                    "report_content": report.report_content,
                    "status": report.status
                },
                changed_fields=list(update_data.keys()),
                note=f"리포트 정보 수정 - {report.report_type}: {report.report_content[:50]}..."
            )
        except Exception as log_error:
            print(f"로그 생성 중 오류: {log_error}")
        
        return {
            "message": "리포트가 성공적으로 수정되었습니다",
            "report": {
                "id": str(report.id),
                "reporter_id": str(report.reporter_id),
                "occurrence_date": report.occurrence_date.strftime("%Y-%m-%d") if report.occurrence_date else None,
                "report_type": report.report_type,
                "status": report.status
            }
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"리포트 수정 중 오류가 발생했습니다: {str(e)}")

@router.delete("/{report_id}")
def delete_report(
    report_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """리포트 삭제"""
    try:
        # 리포트 존재 여부 확인
        report = db.query(Report).filter(Report.id == report_id).first()
        if not report:
            raise HTTPException(status_code=404, detail="리포트를 찾을 수 없습니다")
        
        # 삭제 전 데이터 저장 (로그용)
        deleted_data = {
            "id": str(report.id),
            "reporter_id": str(report.reporter_id),
            "occurrence_date": report.occurrence_date.strftime("%Y-%m-%d") if report.occurrence_date else None,
            "report_type": report.report_type,
            "report_content": report.report_content,
            "status": report.status
        }
        
        # 리포트 삭제 (CASCADE로 인해 관련된 photos와 comments도 자동 삭제)
        db.delete(report)
        db.commit()
        
        # 데이터베이스 로그 생성
        try:
            create_database_log(
                db=db,
                table_name="reports",
                record_id=deleted_data["id"],
                action="DELETE",
                user_id=current_user["id"] if current_user else None,
                old_values=deleted_data,
                note=f"리포트 삭제 - {deleted_data['report_type']}: {deleted_data['report_content'][:50]}..."
            )
        except Exception as log_error:
            print(f"로그 생성 중 오류: {log_error}")
        
        return {
            "message": "리포트가 성공적으로 삭제되었습니다",
            "deleted_report_id": report_id
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"리포트 삭제 중 오류가 발생했습니다: {str(e)}")


# ===== Report Comments 관련 API들 =====

@router.post("/{report_id}/comments")
def create_report_comment(
    report_id: str,
    comment: ReportCommentCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """리포트에 코멘트 추가"""
    try:
                # comment가 None이거나 빈 문자열인 경우 빈 문자열로 설정
        comment_text = comment.comment.strip() if comment.comment else ""
        
        # comment_text가 빈 문자열인 경우 코멘트 생성하지 않고 상태만 업데이트
        if comment_text == "":
            # 리포트 존재 여부 확인
            report = db.query(Report).filter(Report.id == report_id).first()
            if not report:
                raise HTTPException(status_code=404, detail="리포트를 찾을 수 없습니다")
            
            # comment_type이 상태 값인 경우 보고서 상태만 업데이트
            old_status = report.status
            if comment.comment_type in ["pending", "in_progress", "completed", "rejected"]:
                # comment_type을 직접 상태 값으로 사용
                new_status = comment.comment_type
                
                # 보고서 상태 업데이트
                report.status = new_status
                
                db.commit()
                db.refresh(report)
                
                # 상태 변경 로그 (상태가 변경된 경우)
                if old_status != report.status:
                    try:
                        create_database_log(
                            db=db,
                            table_name="reports",
                            record_id=str(report.id),
                            action="UPDATE",
                            user_id=current_user["id"] if current_user else None,
                            old_values={"status": old_status},
                            new_values={"status": report.status},
                            changed_fields=["status"],
                            note=f"리포트 상태 변경 - {old_status} → {report.status} (코멘트 없음)"
                        )
                    except Exception as log_error:
                        print(f"로그 생성 중 오류: {log_error}")
                
                return {
                    "message": "리포트 상태가 업데이트되었습니다 (코멘트 없음)",
                    "comment": None,
                    "status_updated": True,
                    "old_status": old_status,
                    "new_status": report.status,
                    "report": {
                        "id": str(report.id),
                        "status": report.status,
                        "updated_at": report.updated_at.strftime("%Y-%m-%d %H:%M:%S") if hasattr(report, 'updated_at') and report.updated_at else None
                    }
                }
            else:
                # 상태 업데이트도 아닌 경우 아무것도 하지 않음
                return {
                    "message": "코멘트 내용이 없어 아무것도 처리되지 않았습니다",
                    "comment": None,
                    "status_updated": False,
                    "old_status": None,
                    "new_status": None,
                    "report": None
                }
        
        # 리포트 존재 여부 확인
        report = db.query(Report).filter(Report.id == report_id).first()
        if not report:
            raise HTTPException(status_code=404, detail="리포트를 찾을 수 없습니다")
        
        # 새 코멘트 객체 생성
        new_comment = ReportComment(
            id=str(uuid.uuid4()),
            report_id=report_id,
            operator_id=current_user["id"],
            comment=comment_text,  # 처리된 comment 텍스트 사용
        )
        
        # comment_type이 상태 값인 경우 보고서 상태 업데이트
        old_status = report.status
        if comment.comment_type in ["pending", "in_progress", "completed", "rejected"]:
            # comment_type을 직접 상태 값으로 사용
            new_status = comment.comment_type
            
            # 보고서 상태 업데이트
            report.status = new_status
        
        db.add(new_comment)
        db.commit()
        db.refresh(new_comment)
        db.refresh(report)
        
        # 데이터베이스 로그 생성
        try:
            # 코멘트 로그
            create_database_log(
                db=db,
                table_name="report_comments",
                record_id=str(new_comment.id),
                action="CREATE",
                user_id=current_user["id"] if current_user else None,
                new_values={
                    "report_id": report_id,
                    "operator_id": str(current_user["id"]),
                    "comment": comment_text,
                    "comment_type": comment.comment_type
                },
                changed_fields=["report_id", "operator_id", "comment", "comment_type"],
                note=f"리포트 코멘트 추가 - {report.report_type}: {comment_text[:50] if comment_text else '내용 없음'}..."
            )
            
            # 상태 변경 로그 (상태가 변경된 경우)
            if comment.comment_type in ["pending", "in_progress", "completed", "rejected"] and old_status != report.status:
                create_database_log(
                    db=db,
                    table_name="reports",
                    record_id=str(report.id),
                    action="UPDATE",
                    user_id=current_user["id"] if current_user else None,
                    old_values={"status": old_status},
                    new_values={"status": report.status},
                    changed_fields=["status"],
                    note=f"리포트 상태 변경 - {old_status} → {report.status} (코멘트: {comment_text[:30] if comment_text else '내용 없음'}...)"
                )
        except Exception as log_error:
            print(f"로그 생성 중 오류: {log_error}")
        
        return {
            "message": "리포트 코멘트가 성공적으로 추가되었습니다",
            "comment": {
                "id": str(new_comment.id),
                "report_id": report_id,
                "operator_id": str(new_comment.operator_id),
                "comment": new_comment.comment,
                "comment_type": comment.comment_type,
                "created_at": new_comment.created_at.isoformat() + "Z" if new_comment.created_at else None
            },
            "status_updated": comment.comment_type in ["pending", "in_progress", "completed", "rejected"] and old_status != report.status,
            "old_status": old_status if comment.comment_type in ["pending", "in_progress", "completed", "rejected"] else None,
            "new_status": report.status if comment.comment_type in ["pending", "in_progress", "completed", "rejected"] else None,
            "report": {
                "id": str(report.id),
                "status": report.status,
                "updated_at": report.updated_at.strftime("%Y-%m-%d %H:%M:%S") if hasattr(report, 'updated_at') and report.updated_at else None
            }
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"코멘트 추가 중 오류가 발생했습니다: {str(e)}")

@router.delete("/comments/{comment_id}")
def delete_report_comment(
    comment_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """리포트 코멘트 삭제"""
    try:
        # 코멘트 존재 여부 확인
        comment = db.query(ReportComment).filter(ReportComment.id == comment_id).first()
        if not comment:
            raise HTTPException(status_code=404, detail="코멘트를 찾을 수 없습니다")
        
        # 삭제 전 데이터 저장 (로그용)
        deleted_data = {
            "id": str(comment.id),
            "report_id": str(comment.report_id),
            "operator_id": str(comment.operator_id),
            "comment": comment.comment
        }
        
        # 코멘트 삭제
        db.delete(comment)
        db.commit()
        
        # 데이터베이스 로그 생성
        try:
            create_database_log(
                db=db,
                table_name="report_comments",
                record_id=deleted_data["id"],
                action="DELETE",
                user_id=current_user["id"] if current_user else None,
                old_values=deleted_data,
                note=f"리포트 코멘트 삭제 - {deleted_data['comment'][:50]}..."
            )
        except Exception as log_error:
            print(f"로그 생성 중 오류: {log_error}")
        
        return {
            "message": "리포트 코멘트가 성공적으로 삭제되었습니다",
            "deleted_comment_id": comment_id
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"코멘트 삭제 중 오류가 발생했습니다: {str(e)}")

# ===== 통계 및 대시보드 API들 =====

@router.get("/statistics/overview")
def get_reports_statistics(
    db: Session = Depends(get_db)
):
    """리포트 통계 개요"""
    try:
        # 전체 리포트 수
        total_reports = db.query(Report).count()
        
        # 상태별 리포트 수
        status_counts = db.query(
            Report.status,
            func.count(Report.id)
        ).group_by(Report.status).all()
        
        # 타입별 리포트 수
        type_counts = db.query(
            Report.report_type,
            func.count(Report.id)
        ).group_by(Report.report_type).all()
        
        # 최근 30일 리포트 수
        thirty_days_ago = datetime.now().date() - timedelta(days=30)
        recent_reports = db.query(Report).filter(
            Report.created_at >= thirty_days_ago
        ).count()
        
        return {
            "total_reports": total_reports,
            "recent_reports_30_days": recent_reports,
            "status_distribution": dict(status_counts),
            "type_distribution": dict(type_counts),
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"통계 조회 중 오류가 발생했습니다: {str(e)}")

@router.get("/statistics/monthly")
def get_monthly_reports_statistics(
    year: int = Query(..., description="조회할 연도"),
    db: Session = Depends(get_db)
):
    """월별 리포트 통계"""
    try:
        monthly_stats = []
        
        for month in range(1, 13):
            # 해당 월의 리포트 수
            month_reports = db.query(Report).filter(
                func.extract('year', Report.created_at) == year,
                func.extract('month', Report.created_at) == month
            ).count()
            
            # 해당 월의 상태별 리포트 수
            month_status_counts = db.query(
                Report.status,
                func.count(Report.id)
            ).filter(
                func.extract('year', Report.created_at) == year,
                func.extract('month', Report.created_at) == month
            ).group_by(Report.status).all()
            
            monthly_stats.append({
                "year": year,
                "month": month,
                "total_reports": month_reports,
                "status_distribution": dict(month_status_counts)
            })
        
        return {
            "year": year,
            "monthly_statistics": monthly_stats
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"월별 통계 조회 중 오류가 발생했습니다: {str(e)}") 