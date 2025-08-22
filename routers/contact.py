from fastapi import APIRouter, Depends, HTTPException, Query, status, UploadFile, File, Form
from fastapi.security import HTTPBearer
from supabase import create_client
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from typing import Optional, List, Union
from database import SessionLocal, engine
from models import Contact, ContactPhoto, ContactComment, Student, Company, Profiles
from schemas import ContactCreate, ContactUpdate, ContactResponse, ContactCommentCreate, ContactPhotoCreate
from datetime import datetime, date, timedelta
import uuid
from database_log import create_database_log
import os
import random
import string
from supabase import create_client
from utils.dependencies import get_current_user

router = APIRouter(prefix="/contact", tags=["리포트 관리"])

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

# ===== contact 관련 API들 =====

@router.get("")
def get_contact(
    contact_type: Optional[str] = Query(None, description="보고 종류로 필터링 (defect/claim/other)"),
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
        query = db.query(Contact).options(
            joinedload(Contact.photos),
            joinedload(Contact.comments)
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
        if contact_type:
            query = query.filter(Contact.contact_type == contact_type)
        if status:
            query = query.filter(Contact.status == status)
        if occurrence_date_from:
            query = query.filter(Contact.occurrence_date >= occurrence_date_from)
        if occurrence_date_to:
            query = query.filter(Contact.occurrence_date <= occurrence_date_to)
        
        # creator_id 필터 (admin이 아닌 경우에만 적용)
        if not is_admin and current_user:
            # 일반 사용자는 자신의 리포트만 조회
            query = query.filter(Contact.creator_id == current_user["id"])
        # 최신순으로 정렬
        query = query.order_by(Contact.created_at.desc())
        
        # 전체 항목 수 계산
        total_count = query.count()
        
        # 페이지네이션 적용
        contact = query.offset((page - 1) * page_size).limit(page_size).all()
        
        # 전체 페이지 수 계산
        total_pages = (total_count + page_size - 1) // page_size
        
        # 응답 데이터 준비
        result = []
        for contact in contact:
            # creator 정보 조회
            creator = db.query(Profiles).filter(Profiles.id == contact.creator_id).first()
            creator_name = creator.name if creator else None
            
            # comments의 operator 정보 조회
            comments_with_operators = []
            for comment in contact.comments:
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
            
            contact_data = {
                "id": str(contact.id),
                "creator_id": str(contact.creator_id),
                "occurrence_date": contact.occurrence_date.strftime("%Y-%m-%d") if contact.occurrence_date else None,
                "contact_type": contact.contact_type,
                "contact_content": contact.contact_content,
                "status": contact.status,
                "created_at": contact.created_at.strftime("%Y-%m-%d %H:%M:%S") if contact.created_at else None,
                "photos_count": len(contact.photos) if contact.photos else 0,
                "comments_count": len(contact.comments) if contact.comments else 0,
                "photos": [
                    {
                        "id": str(photo.id),
                        "photo_url": photo.photo_url,
                        "filename": photo.photo_url.split("/")[-1] if photo.photo_url else None,
                        "uploaded_at": photo.uploaded_at.isoformat() + "Z" if photo.uploaded_at else None,
                        "thumbnail_url": photo.photo_url,
                        "is_public": True
                    } for photo in contact.photos
                ] if contact.photos else [],
                "comments": comments_with_operators,
                "creator": {
                    "id": str(contact.creator_id),
                    "name": creator_name,
                }
            }
            result.append(contact_data)
        

        
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
        raise HTTPException(status_code=500, detail=f"レポート一覧取得中にエラーが発生しました: {str(e)}")

@router.get("/{contact_id}")
def get_contact(
    contact_id: str,
    db: Session = Depends(get_db)
):
    """특정 리포트 상세 정보 조회"""
    try:
        contact = db.query(Contact).options(
            joinedload(Contact.photos),
            joinedload(Contact.comments)
        ).filter(Contact.id == contact_id).first()
        
        if not contact:
            raise HTTPException(status_code=404, detail="レポートが見つかりません")
        
        # creator 정보 조회
        creator = db.query(Profiles).filter(Profiles.id == contact.creator_id).first()
        creator_name = creator.name if creator else None
        
        # comments의 operator 정보 조회
        comments_with_operators = []
        for comment in contact.comments:
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
        contact_data = {
            "id": str(contact.id),
            "creator_id": str(contact.creator_id),
            "occurrence_date": contact.occurrence_date.strftime("%Y-%m-%d") if contact.occurrence_date else None,
            "contact_type": contact.contact_type,
            "contact_content": contact.contact_content,
            "status": contact.status,
            "created_at": contact.created_at.strftime("%Y-%m-%d %H:%M:%S") if contact.created_at else None,
            "creator": {
                "id": str(contact.creator_id),
                "name": creator_name,
            },
            "photos_count": len(contact.photos) if contact.photos else 0,  # 사진 개수
            "photos": [
                {
                    "id": str(photo.id),
                    "photo_url": photo.photo_url,
                    "filename": photo.photo_url.split("/")[-1] if photo.photo_url else None,  # 파일명 추출
                    "uploaded_at": photo.uploaded_at.isoformat() + "Z" if photo.uploaded_at else None,
                    "file_size": None,  # 필요시 파일 크기 추가 가능
                    "thumbnail_url": photo.photo_url,  # 썸네일 URL (필요시 별도 생성)
                    "is_public": True  # 공개 여부
                } for photo in contact.photos
            ] if contact.photos else [],
            "comments": comments_with_operators
        }
        
        return contact_data
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"レポート詳細取得中にエラーが発生しました: {str(e)}")

@router.post("/", status_code=201)
def create_contact(
    contact: ContactCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """새로운 리포트 생성"""
    try:
        # 새 리포트 객체 생성
        new_contact = Contact(
            id=str(uuid.uuid4()),
            creator_id=current_user["id"],
            occurrence_date=contact.occurrence_date,
            contact_type=contact.contact_type,
            contact_content=contact.contact_content,
            status="pending"
        )
        
        db.add(new_contact)
        db.commit()
        db.refresh(new_contact)
        
        # 데이터베이스 로그 생성
        try:
            create_database_log(
                db=db,
                table_name="contact",
                record_id=str(new_contact.id),
                action="CREATE",
                user_id=current_user["id"] if current_user else None,
                new_values={
                    "creator_id": str(new_contact.creator_id),
                    "occurrence_date": new_contact.occurrence_date.strftime("%Y-%m-%d") if new_contact.occurrence_date else None,
                    "contact_type": new_contact.contact_type,
                    "contact_content": new_contact.contact_content,
                    "status": new_contact.status
                },
                changed_fields=["creator_id", "occurrence_date", "contact_type", "contact_content", "status"],
                note=f"新規レポート作成 - {new_contact.contact_type}: {new_contact.contact_content[:50]}..."
            )
        except Exception as log_error:
            print(f"로그 생성 중 오류: {log_error}")
        
        return {
            "message": "리포트가 성공적으로 생성되었습니다",
            "contact": {
                "id": str(new_contact.id),
                "creator_id": str(new_contact.creator_id),
                "occurrence_date": new_contact.occurrence_date.strftime("%Y-%m-%d") if new_contact.occurrence_date else None,
                "contact_type": new_contact.contact_type,
                "status": new_contact.status
            }
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"리포트 생성 중 오류가 발생했습니다: {str(e)}")

@router.post("/with-photos", status_code=201)
async def create_contact_with_photos(
    occurrence_date: str = Form(...),
    contact_type: str = Form(...),
    contact_content: str = Form(...),
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
        new_contact = Contact(
            id=str(uuid.uuid4()),
            creator_id=current_user["id"],
            occurrence_date=parsed_date,
            contact_type=contact_type,
            contact_content=contact_content,
            status="pending"
        )
        
        db.add(new_contact)
        db.commit()
        db.refresh(new_contact)
        
        # 사진 업로드 처리
        uploaded_photos = []
        
        if photos and len(photos) > 0:
            for photo in photos:
                try:
                    # 파일 확장자 검사
                    file_extension = photo.filename.split(".")[-1].lower()
                    if file_extension not in ["jpg", "jpeg", "png", "gif"]:
                        print(f"サポートされていないファイル形式: {file_extension}")
                        continue
                    
                    # 파일 크기 검사 (5MB)
                    file_size = 0
                    chunk_size = 1024 * 1024  # 1MB
                    while chunk := await photo.read(chunk_size):
                        file_size += len(chunk)
                        if file_size > 5 * 1024 * 1024:  # 5MB
                            print(f"ファイルサイズ超過: {file_size} bytes")
                            break
                    
                    # 파일을 다시 처음으로 되돌림
                    await photo.seek(0)
                    
                    # 랜덤 파일명 생성
                    random_filename = generate_random_filename(photo.filename)
                    
                    # Supabase Storage에 파일 업로드
                    file_path = f"contact_photos/{new_contact.id}/{random_filename}"
                    file_content = await photo.read()
                    
                    try:
                        # Supabase Storage에 파일 업로드
                        result = supabase.storage.from_("contact_photos").upload(
                            file_path,
                            file_content,
                            {"content-type": photo.content_type}
                        )
                        
                        # 파일 URL 생성
                        file_url = supabase.storage.from_("contact_photos").get_public_url(file_path)
                        
                        # 데이터베이스에 사진 정보 저장
                        new_photo = ContactPhoto(
                            id=str(uuid.uuid4()),
                            contact_id=str(new_contact.id),
                            photo_url=file_url
                        )
                        db.add(new_photo)
                        uploaded_photos.append({
                            "id": str(new_photo.id),
                            "photo_url": file_url,
                            "filename": random_filename
                        })
                        
                    except Exception as storage_error:
                        print(f"写真アップロード失敗: {storage_error}")
                        continue
                        
                except Exception as photo_error:
                    print(f"写真処理中にエラー: {photo_error}")
                    continue
            
            # 사진 정보 커밋
            db.commit()
        
        # 데이터베이스 로그 생성
        try:
            create_database_log(
                db=db,
                table_name="contact",
                record_id=str(new_contact.id),
                action="CREATE",
                user_id=current_user["id"] if current_user else None,
                new_values={
                    "creator_id": str(new_contact.creator_id),
                    "occurrence_date": new_contact.occurrence_date.strftime("%Y-%m-%d") if new_contact.occurrence_date else None,
                    "contact_type": new_contact.contact_type,
                    "contact_content": new_contact.contact_content,
                    "status": new_contact.status,
                    "photos_count": len(uploaded_photos)
                },
                changed_fields=["creator_id", "occurrence_date", "contact_type", "contact_content", "status"],
                note=f"사진과 함께 리포트 생성 - {new_contact.contact_type}: {new_contact.contact_content[:50]}... (사진 {len(uploaded_photos)}개)"
            )
        except Exception as log_error:
            print(f"ログ作成中にエラー: {log_error}")
        
        return {
            "message": f"レポートが正常に作成されました。写真{len(uploaded_photos)}枚が添付されました。",
            "contact": {
                "id": str(new_contact.id),
                "creator_id": str(new_contact.creator_id),
                "occurrence_date": new_contact.occurrence_date.strftime("%Y-%m-%d") if new_contact.occurrence_date else None,
                "contact_type": new_contact.contact_type,
                "status": new_contact.status
            },
            "photos": uploaded_photos,
            "total_photos": len(uploaded_photos)
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"리포트 생성 중 오류가 발생했습니다: {str(e)}")

@router.put("/{contact_id}")
def update_contact(
    contact_id: str,
    contact_update: ContactUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """리포트 정보 수정"""
    try:
        # 리포트 존재 여부 확인
        contact = db.query(Contact).filter(Contact.id == contact_id).first()
        if not contact:
            raise HTTPException(status_code=404, detail="レポートが見つかりません")
        
        # 기존 값 저장 (로그용)
        old_values = {
            "occurrence_date": contact.occurrence_date.strftime("%Y-%m-%d") if contact.occurrence_date else None,
            "contact_type": contact.contact_type,
            "contact_content": contact.contact_content,
            "status": contact.status
        }
        
        # 리포트 정보 업데이트
        update_data = contact_update.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(contact, field, value)
        
        db.commit()
        db.refresh(contact)
        
        # 데이터베이스 로그 생성
        try:
            create_database_log(
                db=db,
                table_name="contact",
                record_id=str(contact.id),
                action="UPDATE",
                user_id=current_user["id"] if current_user else None,
                old_values=old_values,
                new_values={
                    "occurrence_date": contact.occurrence_date.strftime("%Y-%m-%d") if contact.occurrence_date else None,
                    "contact_type": contact.contact_type,
                    "contact_content": contact.contact_content,
                    "status": contact.status
                },
                changed_fields=list(update_data.keys()),
                note=f"レポート情報更新 - {contact.contact_type}: {contact.contact_content[:50]}..."
            )
        except Exception as log_error:
            print(f"ログ作成中にエラー: {log_error}")
        
        return {
            "message": "レポートが正常に更新されました",
            "contact": {
                "id": str(contact.id),
                "creator_id": str(contact.creator_id),
                "occurrence_date": contact.occurrence_date.strftime("%Y-%m-%d") if contact.occurrence_date else None,
                "contact_type": contact.contact_type,
                "status": contact.status
            }
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"レポート更新中にエラーが発生しました: {str(e)}")

@router.put("/{contact_id}/cancel")
def cancel_contact(
    contact_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """리포트 취소 (상태를 cancel로 변경)"""
    try:
        # 리포트 존재 여부 확인
        contact = db.query(Contact).filter(Contact.id == contact_id).first()
        if not contact:
            raise HTTPException(status_code=404, detail="レポートが見つかりません")
        
        # 이미 취소된 리포트인지 확인
        if contact.status == "cancel":
            raise HTTPException(status_code=400, detail="既にキャンセルされたレポートです")
        
        # 기존 상태 저장 (로그용)
        old_status = contact.status
        
        # 리포트 상태를 cancel로 변경
        contact.status = "cancel"
        
        db.commit()
        db.refresh(contact)
        
        # 데이터베이스 로그 생성
        try:
            create_database_log(
                db=db,
                table_name="contact",
                record_id=str(contact.id),
                action="UPDATE",
                user_id=current_user["id"] if current_user else None,
                old_values={"status": old_status},
                new_values={"status": "cancel"},
                changed_fields=["status"],
                note=f"レポートキャンセル - {contact.contact_type}: {contact.contact_content[:50]}... (状態: {old_status} → cancel)"
            )
        except Exception as log_error:
            print(f"ログ作成中にエラー: {log_error}")
        
        return {
            "message": "レポートが正常にキャンセルされました",
            "contact": {
                "id": str(contact.id),
                "status": contact.status,
                "cancelled_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"レポートキャンセル中にエラーが発生しました: {str(e)}")


# ===== Contact Comments 관련 API들 =====

@router.post("/{contact_id}/comments")
def create_contact_comment(
    contact_id: str,
    comment: ContactCommentCreate,
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
            contact = db.query(Contact).filter(Contact.id == contact_id).first()
            if not contact:
                raise HTTPException(status_code=404, detail="レポートが見つかりません")
            
            # comment_type이 상태 값인 경우 보고서 상태만 업데이트
            old_status = contact.status
            if comment.comment_type in ["pending", "in_progress", "completed", "rejected"]:
                # comment_type을 직접 상태 값으로 사용
                new_status = comment.comment_type
                
                # 보고서 상태 업데이트
                contact.status = new_status
                
                db.commit()
                db.refresh(contact)
                
                # 상태 변경 로그 (상태가 변경된 경우)
                if old_status != contact.status:
                    try:
                        create_database_log(
                            db=db,
                            table_name="contact",
                            record_id=str(contact.id),
                            action="UPDATE",
                            user_id=current_user["id"] if current_user else None,
                            old_values={"status": old_status},
                            new_values={"status": contact.status},
                            changed_fields=["status"],
                            note=f"レポート状態変更 - {old_status} → {contact.status} (コメントなし)"
                        )
                    except Exception as log_error:
                        print(f"로그 생성 중 오류: {log_error}")
                
                return {
                    "message": "レポート状態が更新されました (コメントなし)",
                    "comment": None,
                    "status_updated": True,
                    "old_status": old_status,
                    "new_status": contact.status,
                    "contact": {
                        "id": str(contact.id),
                        "status": contact.status,
                        "updated_at": contact.updated_at.strftime("%Y-%m-%d %H:%M:%S") if hasattr(contact, 'updated_at') and contact.updated_at else None
                    }
                }
            else:
                # 상태 업데이트도 아닌 경우 아무것도 하지 않음
                return {
                    "message": "コメント内容がないため何も処理されませんでした",
                    "comment": None,
                    "status_updated": False,
                    "old_status": None,
                    "new_status": None,
                    "contact": None
                }
        
        # 리포트 존재 여부 확인
        contact = db.query(Contact).filter(Contact.id == contact_id).first()
        if not contact:
            raise HTTPException(status_code=404, detail="レポートが見つかりません")
        
        # 새 코멘트 객체 생성
        new_comment = ContactComment(
            id=str(uuid.uuid4()),
            contact_id=contact_id,
            operator_id=current_user["id"],
            comment=comment_text,  # 처리된 comment 텍스트 사용
        )
        
        # comment_type이 상태 값인 경우 보고서 상태 업데이트
        old_status = contact.status
        if comment.comment_type in ["pending", "in_progress", "completed", "rejected"]:
            # comment_type을 직접 상태 값으로 사용
            new_status = comment.comment_type
            
            # 보고서 상태 업데이트
            contact.status = new_status
        
        db.add(new_comment)
        db.commit()
        db.refresh(new_comment)
        db.refresh(contact)
        
        # 데이터베이스 로그 생성
        try:
            # 코멘트 로그
            create_database_log(
                db=db,
                table_name="contact_comments",
                record_id=str(new_comment.id),
                action="CREATE",
                user_id=current_user["id"] if current_user else None,
                new_values={
                    "contact_id": contact_id,
                    "operator_id": str(current_user["id"]),
                    "comment": comment_text,
                    "comment_type": comment.comment_type
                },
                changed_fields=["contact_id", "operator_id", "comment", "comment_type"],
                note=f"レポートコメント追加 - {contact.contact_type}: {comment_text[:50] if comment_text else '内容なし'}..."
            )
            
            # 상태 변경 로그 (상태가 변경된 경우)
            if comment.comment_type in ["pending", "in_progress", "completed", "rejected"] and old_status != contact.status:
                create_database_log(
                    db=db,
                    table_name="contact",
                    record_id=str(contact.id),
                    action="UPDATE",
                    user_id=current_user["id"] if current_user else None,
                    old_values={"status": old_status},
                    new_values={"status": contact.status},
                    changed_fields=["status"],
                    note=f"レポート状態変更 - {old_status} → {contact.status} (コメント: {comment_text[:30] if comment_text else '内容なし'}...)"
                )
        except Exception as log_error:
            print(f"로그 생성 중 오류: {log_error}")
        
        return {
            "message": "レポートコメントが正常に追加されました",
            "comment": {
                "id": str(new_comment.id),
                "contact_id": contact_id,
                "operator_id": str(new_comment.operator_id),
                "comment": new_comment.comment,
                "comment_type": comment.comment_type,
                "created_at": new_comment.created_at.isoformat() + "Z" if new_comment.created_at else None
            },
            "status_updated": comment.comment_type in ["pending", "in_progress", "completed", "rejected"] and old_status != contact.status,
            "old_status": old_status if comment.comment_type in ["pending", "in_progress", "completed", "rejected"] else None,
            "new_status": contact.status if comment.comment_type in ["pending", "in_progress", "completed", "rejected"] else None,
            "contact": {
                "id": str(contact.id),
                "status": contact.status,
                "updated_at": contact.updated_at.strftime("%Y-%m-%d %H:%M:%S") if hasattr(contact, 'updated_at') and contact.updated_at else None
            }
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"コメント追加中にエラーが発生しました: {str(e)}")

@router.delete("/comments/{comment_id}")
def delete_contact_comment(
    comment_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """리포트 코멘트 삭제"""
    try:
        # 코멘트 존재 여부 확인
        comment = db.query(ContactComment).filter(ContactComment.id == comment_id).first()
        if not comment:
            raise HTTPException(status_code=404, detail="コメントが見つかりません")
        
        # 삭제 전 데이터 저장 (로그용)
        deleted_data = {
            "id": str(comment.id),
            "contact_id": str(comment.contact_id),
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
                table_name="contact_comments",
                record_id=deleted_data["id"],
                action="DELETE",
                user_id=current_user["id"] if current_user else None,
                old_values=deleted_data,
                note=f"レポートコメント削除 - {deleted_data['comment'][:50]}..."
            )
        except Exception as log_error:
            print(f"로그 생성 중 오류: {log_error}")
        
        return {
            "message": "レポートコメントが正常に削除されました",
            "deleted_comment_id": comment_id
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"コメント削除中にエラーが発生しました: {str(e)}")

# ===== 통계 및 대시보드 API들 =====

@router.get("/statistics/overview")
def get_contact_statistics(
    db: Session = Depends(get_db)
):
    """리포트 통계 개요"""
    try:
        # 전체 리포트 수
        total_contact = db.query(Contact).count()
        
        # 상태별 리포트 수
        status_counts = db.query(
            Contact.status,
            func.count(Contact.id)
        ).group_by(Contact.status).all()
        
        # 타입별 리포트 수
        type_counts = db.query(
            Contact.contact_type,
            func.count(Contact.id)
        ).group_by(Contact.contact_type).all()
        
        # 최근 30일 리포트 수
        thirty_days_ago = datetime.now().date() - timedelta(days=30)
        recent_contact = db.query(Contact).filter(
            Contact.created_at >= thirty_days_ago
        ).count()
        
        return {
            "total_contact": total_contact,
            "recent_contact_30_days": recent_contact,
            "status_distribution": dict(status_counts),
            "type_distribution": dict(type_counts),
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"統計取得中にエラーが発生しました: {str(e)}")

@router.get("/statistics/monthly")
def get_monthly_contact_statistics(
    year: int = Query(..., description="조회할 연도"),
    db: Session = Depends(get_db)
):
    """월별 리포트 통계"""
    try:
        monthly_stats = []
        
        for month in range(1, 13):
            # 해당 월의 리포트 수
            month_contact = db.query(Contact).filter(
                func.extract('year', Contact.created_at) == year,
                func.extract('month', Contact.created_at) == month
            ).count()
            
            # 해당 월의 상태별 리포트 수
            month_status_counts = db.query(
                Contact.status,
                func.count(Contact.id)
            ).filter(
                func.extract('year', Contact.created_at) == year,
                func.extract('month', Contact.created_at) == month
            ).group_by(Contact.status).all()
            
            monthly_stats.append({
                "year": year,
                "month": month,
                "total_contact": month_contact,
                "status_distribution": dict(month_status_counts)
            })
        
        return {
            "year": year,
            "monthly_statistics": monthly_stats
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"月別統計取得中にエラーが発生しました: {str(e)}") 