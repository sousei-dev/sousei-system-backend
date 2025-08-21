from fastapi import APIRouter, Depends, HTTPException, Query, status, UploadFile, File
from fastapi.security import HTTPBearer
from supabase import create_client
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, or_, and_
from typing import Optional, List
from database import SessionLocal, engine
from models import Student, Company, Grade, Room, Building, ResidenceCardHistory, Resident, BillingMonthlyItem
from schemas import StudentCreate, StudentUpdate, StudentResponse, VisaInfoUpdate, NewResidenceRequest, BillingMonthlyItemCreate, BillingMonthlyItemUpdate, MonthlyItemSortOrderUpdate
from datetime import datetime, date, timedelta
import uuid
from database_log import create_database_log
import os
import random
import string
from supabase import create_client
from utils.dependencies import get_current_user

router = APIRouter(prefix="/students", tags=["학생 관리"])

# Supabase 설정
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")  # anon key 사용 (로그인용)
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

def generate_random_filename(original_filename: str) -> str:
    """원본 파일명을 기반으로 랜덤한 영어 파일명 생성"""
    # 파일 확장자 추출
    file_extension = original_filename.split(".")[-1].lower()
    
    # 랜덤 문자열 생성 (16자리)
    random_string = ''.join(random.choices(string.ascii_lowercase + string.digits, k=16))
    
    # 새로운 파일명 생성: 랜덤문자열.확장자
    new_filename = f"{random_string}.{file_extension}"
    
    return new_filename

@router.get("/")
def get_students(
    name: Optional[str] = Query(None, description="학생 이름으로 검색"),
    name_katakana: Optional[str] = Query(None, description="학생 이름 카타카나로 검색"),
    nationality: Optional[str] = Query(None, description="학생 국적으로 검색"),
    company: Optional[str] = Query(None, description="회사 이름으로 검색"),
    consultant: Optional[int] = Query(None, description="컨설턴트 번호 이상으로 검색"),
    email: Optional[str] = Query(None, description="이메일로 검색"),
    student_type: Optional[str] = Query(None, description="학생 유형으로 검색"),
    building_name: Optional[str] = Query(None, description="건물 이름으로 검색"),
    room_number: Optional[str] = Query(None, description="방 번호로 검색"),
    status: Optional[str] = Query(None, description="상태로 검색"),
    grade: Optional[str] = Query(None, description="등급으로 검색"),
    has_no_building: Optional[bool] = Query(None, description="빌딩이 없는 학생만 검색 (true: 빌딩 없음, false: 빌딩 있음)"),
    sort_by: Optional[str] = Query(None, description="정렬 필드 (nationality 또는 grade)"),
    sort_desc: Optional[bool] = Query(False, description="내림차순 정렬 여부 (true: 내림차순, false: 오름차순)"),
    page: int = Query(1, description="페이지 번호", ge=1),
    page_size: int = Query(10, description="페이지당 항목 수", ge=1, le=100),
    db: Session = Depends(get_db)
):
    """학생 목록 조회 (검색, 필터링, 정렬, 페이지네이션 지원)"""
    # 기본 쿼리 생성
    query = db.query(Student).options(
        joinedload(Student.company),
        joinedload(Student.grade),
        joinedload(Student.current_room).joinedload(Room.building)
    ).outerjoin(Company).outerjoin(Grade)

    # 방 관련 필터링이 있는 경우 Room과 Building 테이블과 조인
    if building_name or room_number:
        query = query.outerjoin(Room, Student.current_room_id == Room.id).outerjoin(Building, Room.building_id == Building.id)

    # 필터 조건 추가
    if student_type and student_type != 'ALL':
        query = query.filter(Student.student_type.ilike(f"%{student_type}%"))
    if name:
        query = query.filter(Student.name.ilike(f"%{name}%"))
    if nationality:
        query = query.filter(Student.nationality.ilike(f"%{nationality}%"))
    if name_katakana:
        query = query.filter(Student.name_katakana.ilike(f"%{name_katakana}%"))
    if company:
        query = query.filter(Company.name.ilike(f"%{company}%"))
    if consultant is not None:
        query = query.filter(Student.consultant >= consultant)
    if email:
        query = query.filter(Student.email.ilike(f"%{email}%"))
    if building_name:
        query = query.filter(Building.name.ilike(f"%{building_name}%"))
    if room_number:
        query = query.filter(Room.room_number.ilike(f"%{room_number}%"))
    if status:
        query = query.filter(Student.status == status)
    if grade:
        query = query.filter(Grade.name.ilike(f"%{grade}%"))
    
    # has_no_building 필터 적용
    if has_no_building is not None:
        if has_no_building:
            # 빌딩이 없는 학생 (current_room_id가 NULL인 경우만)
            query = query.filter(Student.current_room_id.is_(None))
        else:
            # 빌딩이 있는 학생 (current_room_id가 NOT NULL인 경우)
            query = query.filter(Student.current_room_id.isnot(None))
    
    # 정렬 적용
    if sort_by:
        if sort_by == "nationality":
            if sort_desc:
                query = query.order_by(Student.nationality.desc())
            else:
                query = query.order_by(Student.nationality.asc())
        elif sort_by == "grade.name":
            if sort_desc:
                query = query.order_by(Grade.name.desc())
            else:
                query = query.order_by(Grade.name.asc())
        elif sort_by == "student_type":
            if sort_desc:
                query = query.order_by(Student.student_type.desc())
            else:
                query = query.order_by(Student.student_type.asc())
    
    # 전체 항목 수 계산
    total_count = query.count()

    # 페이지네이션 적용
    students = query.offset((page - 1) * page_size).limit(page_size).all()

    # 전체 페이지 수 계산
    total_pages = (total_count + page_size - 1) // page_size

    # 응답 데이터 준비
    result = []
    for student in students:
        student_data = {
            "id": str(student.id),
            "name": student.name,
            "email": student.email if student.email else "",
            "created_at": student.created_at,
            "company_id": str(student.company_id) if student.company_id else None,
            "consultant": student.consultant,
            "phone": student.phone,
            "avatar": student.avatar,
            "grade_id": str(student.grade_id) if student.grade_id else None,
            "cooperation_submitted_date": student.cooperation_submitted_date,
            "cooperation_submitted_place": student.cooperation_submitted_place,
            "assignment_date": student.assignment_date,
            "ward": student.ward,
            "name_katakana": student.name_katakana,
            "gender": student.gender,
            "birth_date": student.birth_date,
            "nationality": student.nationality,
            "has_spouse": student.has_spouse,
            "japanese_level": student.japanese_level,
            "passport_number": student.passport_number,
            "residence_card_number": student.residence_card_number,
            "residence_card_start": student.residence_card_start,
            "residence_card_expiry": student.residence_card_expiry,
            "resignation_date": student.resignation_date,
            "local_address": student.local_address,
            "address": student.address,
            "experience_over_2_years": student.experience_over_2_years,
            "status": student.status,
            "arrival_type": student.arrival_type,
            "student_type": student.student_type,
            "company": {
                "name": student.company.name
            } if student.company else None,
            "grade": {
                "name": student.grade.name
            } if student.grade else None,
            "current_room": {
                "room_number": student.current_room.room_number,
                "building_name": student.current_room.building.name
            } if student.current_room and student.current_room.building else None
        }
        result.append(student_data)

    return {
        "items": result,
        "total": total_count,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_previous": page > 1
    }

@router.get("/expiring-soon")
def get_students_expiring_soon(
    months_ahead: int = Query(4, description="만료 몇 개월 전부터 조회할지 (기본값: 4개월)"),
    page: int = Query(1, description="페이지 번호", ge=1),
    page_size: int = Query(10, description="페이지당 항목 수", ge=1, le=100),
    db: Session = Depends(get_db)
):
    """재류기간 만료가 임박한 학생들을 조회 (기본값: 4개월 전부터)"""
    try:
        # 현재 날짜
        current_date = datetime.now().date()
        
        # 만료 예정 날짜 계산 (현재 날짜 + 지정된 개월 수)
        target_date = current_date + timedelta(days=months_ahead * 30)  # 대략적인 계산
        
        # 재류기간 만료가 임박한 학생들 조회
        query = db.query(Student).options(
            joinedload(Student.grade)
        ).filter(
            Student.residence_card_expiry.isnot(None),  # 재류기간 만료일이 있는 학생만
            Student.residence_card_expiry <= target_date,  # 만료 예정일 이내
            Student.residence_card_expiry >= current_date  # 아직 만료되지 않은 학생
        ).order_by(Student.residence_card_expiry.asc())  # 만료일이 빠른 순으로 정렬
        
        # 전체 항목 수 계산
        total_count = query.count()
        
        # 페이지네이션 적용
        students = query.offset((page - 1) * page_size).limit(page_size).all()
        
        # 전체 페이지 수 계산
        total_pages = (total_count + page_size - 1) // page_size
        
        # 응답 데이터 준비
        result = []
        for student in students:
            # 만료까지 남은 일수 계산
            days_until_expiry = (student.residence_card_expiry - current_date).days
            
            student_data = {
                "id": str(student.id),
                "name": student.name,
                "email": student.email if student.email else "",
                "phone": student.phone,
                "nationality": student.nationality,
                "residence_card_number": student.residence_card_number,
                "residence_card_start": student.residence_card_start,
                "residence_card_expiry": student.residence_card_expiry,
                "days_until_expiry": days_until_expiry,
                "expiry_status": "満了" if days_until_expiry <= 0 else f"{days_until_expiry}日 残り",
            }
            result.append(student_data)
        
        return {
            "items": result,
            "total": total_count,
            "page": page,
            "size": page_size,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_previous": page > 1,
            "current_date": str(current_date),
            "target_date": str(target_date),
            "months_ahead": months_ahead
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"エラーが発生しました: {str(e)}")

@router.get("/{student_id}")
def get_student(student_id: str, db: Session = Depends(get_db)):
    """특정 학생 상세 정보 조회"""
    student = db.query(Student).options(
        joinedload(Student.company), 
        joinedload(Student.grade),
        joinedload(Student.current_room).joinedload(Room.building)
    ).filter(Student.id == student_id).first()
    
    if student is None:
        raise HTTPException(status_code=404, detail="学生が見つかりません")
    
    # 응답 데이터 준비
    student_data = {
        "id": str(student.id),
        "name": student.name,
        "email": student.email if student.email else "",
        "created_at": student.created_at,
        "company_id": str(student.company_id) if student.company_id else None,
        "consultant": student.consultant,
        "phone": student.phone,
        "avatar": student.avatar,
        "grade_id": str(student.grade_id) if student.grade_id else None,
        "cooperation_submitted_date": student.cooperation_submitted_date,
        "cooperation_submitted_place": student.cooperation_submitted_place,
        "assignment_date": student.assignment_date,
        "ward": student.ward,
        "name_katakana": student.name_katakana,
        "gender": student.gender,
        "birth_date": student.birth_date,
        "nationality": student.nationality,
        "has_spouse": student.has_spouse,
        "japanese_level": student.japanese_level,
        "passport_number": student.passport_number,
        "residence_card_number": student.residence_card_number,
        "residence_card_start": student.residence_card_start,
        "residence_card_expiry": student.residence_card_expiry,
        "resignation_date": student.resignation_date,
        "local_address": student.local_address,
        "address": student.address,
        "experience_over_2_years": student.experience_over_2_years,
        "status": student.status,
        "arrival_type": student.arrival_type,
        "entry_date": student.entry_date,
        "interview_date": student.interview_date,
        "pre_guidance_date": student.pre_guidance_date,
        "orientation_date": student.orientation_date,
        "certification_application_date": student.certification_application_date,
        "visa_application_date": student.visa_application_date,
        "passport_expiration_date": student.passport_expiration_date,
        "student_type": student.student_type,
        "current_room_id": str(student.current_room_id) if student.current_room_id else None,
        "facebook_name": student.facebook_name,
        "visa_year": student.visa_year,
        "company": {
            "id": str(student.company.id),
            "name": student.company.name
        } if student.company else None,
        "grade": {
            "id": str(student.grade.id),
            "name": student.grade.name
        } if student.grade else None,
        "current_room": {
          "room_number": student.current_room.room_number,
          "building_name": student.current_room.building.name
        } if student.current_room and student.current_room.building else None
    }
    
    return student_data

@router.post("/", status_code=201)
def create_student(
    student: StudentCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """새로운 학생 생성"""
    try:
        # 빈 문자열을 None으로 변환하는 헬퍼 함수
        def clean_value(value):
            if value == "" or value is None:
                return None
            return value
        
        # UUID 변환 헬퍼 함수
        def parse_uuid(value):
            if value is None or value == "":
                return None
            try:
                return str(value) if isinstance(value, uuid.UUID) else value
            except:
                return None
        
        # 날짜 변환 헬퍼 함수
        def parse_date(value):
            if value is None or value == "":
                return None
            if isinstance(value, date):
                return value
            try:
                return datetime.strptime(value, "%Y-%m-%d").date()
            except:
                return None
        
        # 새 학생 객체 생성
        new_student = Student(
            id=str(uuid.uuid4()),
            name=student.name,
            company_id=parse_uuid(student.company_id) if student.company_id else None,
            consultant=student.consultant,
            grade_id=parse_uuid(student.grade_id) if student.grade_id else None,
            cooperation_submitted_date=parse_date(student.cooperation_submitted_date),
            cooperation_submitted_place=clean_value(student.cooperation_submitted_place),
            assignment_date=parse_date(student.assignment_date),
            ward=clean_value(student.ward),
            name_katakana=clean_value(student.name_katakana),
            gender=clean_value(student.gender),
            birth_date=parse_date(student.birth_date),
            nationality=clean_value(student.nationality),
            has_spouse=student.has_spouse,
            japanese_level=clean_value(student.japanese_level),
            passport_number=clean_value(student.passport_number),
            residence_card_number=clean_value(student.residence_card_number),
            residence_card_start=parse_date(student.residence_card_start),
            residence_card_expiry=parse_date(student.residence_card_expiry),
            local_address=clean_value(student.local_address),
            address=clean_value(student.address),
            phone=clean_value(student.phone),
            experience_over_2_years=student.experience_over_2_years,
            arrival_type=clean_value(student.arrival_type),
            entry_date=parse_date(student.entry_date),
            interview_date=parse_date(student.interview_date),
            pre_guidance_date=parse_date(student.pre_guidance_date),
            orientation_date=parse_date(student.orientation_date),
            certification_application_date=parse_date(student.certification_application_date),
            visa_application_date=parse_date(student.visa_application_date),
            passport_expiration_date=parse_date(student.passport_expiration_date),
            student_type=clean_value(student.student_type),
            current_room_id=parse_uuid(student.room_id) if student.room_id else None,
            facebook_name=clean_value(student.facebook_name),
            visa_year=clean_value(student.visa_year),
            status="ACTIVE"
        )
        
        db.add(new_student)
        db.commit()
        db.refresh(new_student)
        
        # Residence Card 히스토리 저장 (residence card 정보가 있는 경우)
        if (new_student.residence_card_number and 
            new_student.residence_card_start and 
            new_student.residence_card_expiry and
            new_student.visa_year):
            
            # 같은 년차인지 확인
            existing_history = db.query(ResidenceCardHistory).filter(
                ResidenceCardHistory.student_id == new_student.id,
                ResidenceCardHistory.year == new_student.visa_year
            ).first()
            
            if existing_history:
                raise HTTPException(
                    status_code=400,
                    detail=f"{new_student.visa_year}년차의 residence card가 이미 존재합니다. 다른 년차를 입력해주세요."
                )
            
            residence_card_history = ResidenceCardHistory(
                id=str(uuid.uuid4()),
                student_id=new_student.id,
                card_number=new_student.residence_card_number,
                start_date=new_student.residence_card_start,
                expiry_date=new_student.residence_card_expiry,
                year=new_student.visa_year,
                note="新規登録"
            )
            db.add(residence_card_history)
            
            # Residence Card 히스토리 커밋
            db.commit()
        
        # 데이터베이스 로그 생성
        try:
            create_database_log(
                db=db,
                table_name="students",
                record_id=str(new_student.id),
                action="CREATE",
                user_id=current_user["id"] if current_user else None,
                new_values={
                    "name": new_student.name,
                    "company_id": str(new_student.company_id) if new_student.company_id else None,
                    "consultant": new_student.consultant,
                    "grade_id": str(new_student.grade_id) if new_student.grade_id else None,
                    "nationality": new_student.nationality,
                    "student_type": new_student.student_type,
                    "status": new_student.status
                },
                changed_fields=["name", "company_id", "consultant", "grade_id", "nationality", "student_type", "status"],
                note=f"新規学生作成 - {new_student.name}"
            )
        except Exception as log_error:
            print(f"로그 생성 중 오류: {log_error}")
        
        return {
            "message": "学生が正常に作成されました",
            "student": {
                "id": str(new_student.id),
                "name": new_student.name,
                "email": new_student.email,
                "company_id": str(new_student.company_id) if new_student.company_id else None
            }
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"学生作成中にエラーが発生しました: {str(e)}")

@router.put("/{student_id}")
def update_student(
    student_id: str,
    student_update: StudentUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """학생 정보 수정"""
    # 헬퍼 함수
    def parse_date(value):
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return None
    
    # 학생 존재 여부 확인
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(
            status_code=404,
            detail="学生が見つかりません"
        )

    # 회사 존재 여부 확인 (회사가 변경되는 경우)
    if student_update.company_id:
        company = db.query(Company).filter(Company.id == student_update.company_id).first()
        if not company:
            raise HTTPException(
                status_code=404,
                detail="存在しない会社です"
            )

    # Residence Card 정보가 변경되었는지 확인
    residence_card_changed = False
    if (student_update.residence_card_number and 
        student_update.residence_card_start and 
        student_update.residence_card_expiry):
        
        # 기존 정보와 비교
        if (student.residence_card_number != student_update.residence_card_number or
            student.residence_card_start != student_update.residence_card_start or
            student.residence_card_expiry != student_update.residence_card_expiry):
            residence_card_changed = True
            
            # 같은 년차인지 확인
            if student_update.visa_year:
                # 기존 히스토리에서 같은 년차가 있는지 확인
                existing_history = db.query(ResidenceCardHistory).filter(
                    ResidenceCardHistory.student_id == student_id,
                    ResidenceCardHistory.year == student_update.visa_year
                ).first()
                
                if existing_history:
                    raise HTTPException(
                        status_code=400,
                        detail=f"{student_update.visa_year}년차의 residence card가 이미 존재합니다. 다른 년차를 입력해주세요."
                    )

    # 기존 값 저장 (로그용)
    old_values = {
        "name": student.name,
        "company_id": str(student.company_id) if student.company_id else None,
        "consultant": student.consultant,
        "grade_id": str(student.grade_id) if student.grade_id else None,
        "nationality": student.nationality,
        "student_type": student.student_type,
        "status": student.status,
        "phone": student.phone,
        "email": student.email,
        "address": student.address
    }
    
    # 학생 정보 업데이트
    update_data = student_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(student, field, value)

    # Residence Card 히스토리 저장 (변경된 경우)
    if residence_card_changed:
        residence_card_history = ResidenceCardHistory(
            id=str(uuid.uuid4()),
            student_id=student.id,
            card_number=student_update.residence_card_number,
            start_date=parse_date(student_update.residence_card_start),
            expiry_date=parse_date(student_update.residence_card_expiry),
            year=student_update.visa_year,
            note="学生情報更新"
        )
        db.add(residence_card_history)

    try:
        db.commit()
        db.refresh(student)
        
        # 데이터베이스 로그 생성
        try:
            create_database_log(
                db=db,
                table_name="students",
                record_id=str(student.id),
                action="UPDATE",
                user_id=current_user["id"] if current_user else None,
                old_values=old_values,
                new_values={
                    "name": student.name,
                    "company_id": str(student.company_id) if student.company_id else None,
                    "consultant": student.consultant,
                    "grade_id": str(student.grade_id) if student.grade_id else None,
                    "nationality": student.nationality,
                    "student_type": student.student_type,
                    "status": student.status
                },
                changed_fields=list(update_data.keys()),
                note=f"学生情報更新 - {student.name}"
            )
        except Exception as log_error:
            print(f"로그 생성 중 오류: {log_error}")
        
        # UUID를 문자열로 변환
        student_dict = {
            "id": str(student.id),
            "name": student.name,
            "email": student.email if student.email else "",
            "company_id": str(student.company_id) if student.company_id else None,
            "consultant": student.consultant,
            "avatar": student.avatar,
            "created_at": student.created_at
        }
        return student_dict
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"学生情報更新中にエラーが発生しました: {str(e)}"
        )

@router.put("/{student_id}/visa-info")
def update_student_visa_info(
    student_id: str,
    visa_update: VisaInfoUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """비자 정보만 변경하는 API"""
    # 학생 존재 여부 확인
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(
            status_code=404,
            detail="学生が見つかりません"
        )

    # 헬퍼 함수들
    def clean_value(value):
        if value == "" or value is None:
            return None
        return value
    
    def parse_date(value):
        if value is None or value == "":
            return None
        if isinstance(value, date):
            return value
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except:
            return None

    # Residence Card 정보가 변경되었는지 확인
    residence_card_changed = False
    if (visa_update.residence_card_number and 
        visa_update.residence_card_start and 
        visa_update.residence_card_expiry and
        visa_update.visa_application_date):
        
        # 기존 정보와 비교
        if (student.residence_card_number != parse_date(visa_update.residence_card_start) or
            student.residence_card_start != parse_date(visa_update.residence_card_start) or
            student.residence_card_expiry != parse_date(visa_update.residence_card_expiry) or
            student.visa_application_date != parse_date(visa_update.visa_application_date)):
            residence_card_changed = True
            
            # 같은 년차인지 확인
            if visa_update.visa_year:
                # 기존 히스토리에서 같은 년차가 있는지 확인
                existing_history = db.query(ResidenceCardHistory).filter(
                    ResidenceCardHistory.student_id == student_id,
                    ResidenceCardHistory.year == visa_update.visa_year
                ).first()
                
                if existing_history:
                    raise HTTPException(
                        status_code=400,
                        detail=f"{visa_update.visa_year}년차의 residence card가 이미 존재합니다. 다른 년차를 입력해주세요."
                    )

    # 비자 정보 업데이트
    if visa_update.residence_card_number is not None:
        student.residence_card_number = clean_value(visa_update.residence_card_number)
    if visa_update.residence_card_start is not None:
        student.residence_card_start = parse_date(visa_update.residence_card_start)
    if visa_update.residence_card_expiry is not None:
        student.residence_card_expiry = parse_date(visa_update.residence_card_expiry)
    if visa_update.visa_year is not None:
        student.visa_year = clean_value(visa_update.visa_year)
    if visa_update.visa_application_date is not None:
        student.visa_application_date = parse_date(visa_update.visa_application_date)

    # Residence Card 히스토리 저장 (변경된 경우)
    if residence_card_changed:
        residence_card_history = ResidenceCardHistory(
            id=str(uuid.uuid4()),
            student_id=student.id,
            card_number=visa_update.residence_card_number,
            start_date=parse_date(visa_update.residence_card_start),
            expiry_date=parse_date(visa_update.residence_card_expiry),
            application_date=parse_date(visa_update.visa_application_date),
            year=visa_update.visa_year,
            note="ビザ情報更新"
        )
        db.add(residence_card_history)

    try:
        db.commit()
        db.refresh(student)
        
        # 데이터베이스 로그 생성
        try:
            create_database_log(
                db=db,
                table_name="students",
                record_id=str(student.id),
                action="UPDATE",
                user_id=current_user["id"] if current_user else None,
                old_values={
                    "residence_card_number": student.residence_card_number,
                    "residence_card_start": student.residence_card_start,
                    "residence_card_expiry": student.residence_card_expiry,
                    "visa_year": student.visa_year,
                    "visa_application_date": student.visa_application_date
                },
                new_values={
                    "residence_card_number": student.residence_card_number,
                    "residence_card_start": student.residence_card_start,
                    "residence_card_expiry": student.residence_card_expiry,
                    "visa_year": student.visa_year,
                    "visa_application_date": student.visa_application_date
                },
                changed_fields=["residence_card_number", "residence_card_start", "residence_card_expiry", "visa_year", "visa_application_date"],
                note=f"ビザ情報更新 - {student.name}"
            )
        except Exception as log_error:
            print(f"로그 생성 중 오류: {log_error}")
        
        return {
            "message": "ビザ情報が正常に更新されました",
            "student_id": str(student.id),
            "residence_card_number": student.residence_card_number,
            "residence_card_start": student.residence_card_start,
            "residence_card_expiry": student.residence_card_expiry,
            "visa_year": student.visa_year
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"ビザ情報更新中にエラーが発生しました: {str(e)}"
        )

@router.get("/{student_id}/residence-card-history")
def get_student_residence_card_history(
    student_id: str,
    page: int = Query(1, description="페이지 번호", ge=1),
    size: int = Query(10, description="페이지당 항목 수", ge=1, le=100),
    db: Session = Depends(get_db)
):
    """학생의 Residence Card 히스토리 조회"""
    # 학생 존재 여부 확인
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(
            status_code=404,
            detail="学生が見つかりません"
        )

    # Residence Card 히스토리 조회
    query = db.query(ResidenceCardHistory).filter(
        ResidenceCardHistory.student_id == student_id
    ).order_by(ResidenceCardHistory.registered_at.desc())

    # 전체 항목 수 계산
    total_count = query.count()

    # 페이지네이션 적용
    histories = query.offset((page - 1) * size).limit(size).all()

    # 전체 페이지 수 계산
    total_pages = (total_count + size - 1) // size

    # 응답 데이터 준비
    result = []
    for history in histories:
        history_data = {
            "id": str(history.id),
            "student_id": str(history.student_id),
            "residence_card_number": history.card_number,
            "residence_card_start": history.start_date,
            "residence_card_expiry": history.expiry_date,
            "visa_application_date": history.application_date,
            "year": history.year,
            "registered_at": history.registered_at,
            "note": history.note
        }
        result.append(history_data)

    return {
        "items": result,
        "total": total_count,
        "page": page,
        "size": size,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_previous": page > 1
    } 

@router.get("/{student_id}/residence-history")
def get_student_residence_history(
    student_id: str,
    page: int = Query(1, description="페이지 번호", ge=1),
    size: int = Query(10, description="페이지당 항목 수", ge=1, le=100),
    is_active: Optional[bool] = Query(None, description="활성 상태로 필터링"),
    db: Session = Depends(get_db)
):
    """학생 거주 이력 조회"""
    try:
        # 학생 존재 여부 확인
        student = db.query(Student).filter(Student.id == student_id).first()
        if not student:
            raise HTTPException(status_code=404, detail="학생을 찾을 수 없습니다")

        # 해당 학생의 모든 거주 기록 조회
        query = db.query(Resident).options(
            joinedload(Resident.room).joinedload(Room.building)
        ).filter(Resident.resident_id == student_id)

        # 활성 상태 필터링 (선택사항)
        if is_active is not None:
            query = query.filter(Resident.is_active == is_active)

        # 전체 항목 수 계산
        total_count = query.count()

        # 페이지네이션 적용 (최신 기록부터)
        residents = query.order_by(Resident.created_at.desc()).offset((page - 1) * size).limit(size).all()

        # 전체 페이지 수 계산
        total_pages = (total_count + size - 1) // size

        # 응답 데이터 준비
        result = []
        for resident in residents:
            resident_data = {
                "id": str(resident.id),
                "room_id": str(resident.room_id),
                "student_id": str(resident.resident_id),
                "check_in_date": resident.check_in_date.strftime("%Y-%m-%d") if resident.check_in_date else None,
                "check_out_date": resident.check_out_date.strftime("%Y-%m-%d") if resident.check_out_date else None,
                "is_active": resident.is_active,
                "note": resident.check_out_date,
                "created_at": resident.created_at.strftime("%Y-%m-%d %H:%M:%S") if resident.created_at else None,
                "updated_at": resident.updated_at.strftime("%Y-%m-%d %H:%M:%S") if resident.updated_at else None,
                "room": {
                    "id": str(resident.room.id),
                    "room_number": resident.room.room_number,
                    "building_id": str(resident.room.building_id),
                    "floor": resident.room.floor,
                    "rent": resident.room.rent
                } if resident.room else None,
                "building": {
                    "id": str(resident.room.building.id),
                    "name": resident.room.building.name,
                    "address": resident.room.building.address
                } if resident.room and resident.room.building else None,
                "student": {
                    "id": str(student.id),
                    "name": student.name,
                    "name_katakana": student.name_katakana,
                    "nationality": student.nationality,
                    "phone": student.phone,
                    "email": student.email,
                    "avatar": student.avatar,
                    "gender": student.gender,
                    "birth_date": student.birth_date.strftime("%Y-%m-%d") if student.birth_date else None,
                    "japanese_level": student.japanese_level,
                    "local_address": student.local_address
                }
            }
            result.append(resident_data)

        return {
            "student": {
                "id": str(student.id),
                "name": student.name,
                "current_room_id": str(student.current_room_id) if student.current_room_id else None
            },
            "items": result,
            "total": total_count,
            "total_pages": total_pages,
            "current_page": page
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"학생 거주 이력 조회 중 오류가 발생했습니다: {str(e)}")

@router.get("/{student_id}/residence-history/monthly")
def get_student_monthly_residence_history(
    student_id: str,
    year: int,
    month: int,
    db: Session = Depends(get_db)
):
    """학생 월별 거주 이력 조회"""
    try:
        # 학생 존재 여부 확인
        student = db.query(Student).filter(Student.id == student_id).first()
        if not student:
            raise HTTPException(status_code=404, detail="학생을 찾을 수 없습니다")
        
        # 년월 유효성 검사
        if not (1 <= month <= 12):
            raise HTTPException(status_code=400, detail="월은 1-12 사이여야 합니다")
        
        # 해당 월의 시작일과 종료일 계산
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = date(year, month + 1, 1) - timedelta(days=1)

        # 해당 월에 거주 기록이 있는 모든 레코드 조회
        # (입주일이 해당 월에 있거나, 퇴실일이 해당 월에 있거나, 또는 해당 월 전체를 거주한 경우)
        residents = db.query(Resident).options(
            joinedload(Resident.room).joinedload(Room.building)
        ).filter(
            Resident.resident_id == student_id,
            # 입주일이 해당 월에 있거나
            (Resident.check_in_date <= end_date) &
            # 퇴실일이 없거나(현재 거주 중) 퇴실일이 해당 월 이후이거나
            ((Resident.check_out_date.is_(None)) | (Resident.check_out_date >= start_date))
        ).order_by(Resident.check_in_date.desc()).all()

        # 월별 거주 이력 정리
        monthly_history = []
        
        for resident in residents:
            # 해당 월에 실제로 거주했는지 확인
            check_in = resident.check_in_date
            check_out = resident.check_out_date or end_date  # 퇴실일이 없으면 월말까지
            
            # 거주 기간이 해당 월과 겹치는지 확인
            if check_in <= end_date and check_out >= start_date:
                # 실제 거주 시작일과 종료일 계산
                actual_check_in = max(check_in, start_date)
                actual_check_out = min(check_out, end_date)
                
                # 거주 일수 계산
                days_resided = (actual_check_out - actual_check_in).days + 1
                
                resident_data = {
                    "id": str(resident.id),
                    "room_id": str(resident.room_id),
                    "student_id": str(resident.resident_id),
                    "check_in_date": resident.check_in_date.strftime("%Y-%m-%d") if resident.check_in_date else None,
                    "check_out_date": resident.check_out_date.strftime("%Y-%m-%d") if resident.check_out_date else None,
                    "is_active": resident.is_active,
                    "note": resident.note,
                    "created_at": resident.created_at.strftime("%Y-%m-%d %H:%M:%S") if resident.created_at else None,
                    "updated_at": resident.updated_at.strftime("%Y-%m-%d %H:%M:%S") if resident.updated_at else None,
                    "actual_check_in": actual_check_in.strftime("%Y-%m-%d"),
                    "actual_check_out": actual_check_out.strftime("%Y-%m-%d"),
                    "days_resided": days_resided,
                    "room": {
                        "id": str(resident.room.id),
                        "room_number": resident.room.room_number,
                        "building_id": str(resident.room.building_id),
                        "floor": resident.room.floor,
                        "rent": resident.room.rent
                    } if resident.room else None,
                    "building": {
                        "id": str(resident.room.building.id),
                        "name": resident.room.building.name,
                        "address": resident.room.building.address
                    } if resident.room and resident.room.building else None,
                    "student": {
                        "id": str(student.id),
                        "name": student.name,
                        "name_katakana": student.name_katakana,
                        "nationality": student.nationality,
                        "phone": student.phone,
                        "email": student.email if student.email else "",
                        "avatar": student.avatar,
                        "gender": student.gender,
                        "birth_date": student.birth_date.strftime("%Y-%m-%d") if student.birth_date else None,
                        "japanese_level": student.japanese_level,
                        "local_address": student.local_address
                    }
                }
                monthly_history.append(resident_data)

        # 월별 요약 정보
        total_days = calendar.monthrange(year, month)[1]
        total_residences = len(monthly_history)
        
        return {
            "student": {
                "id": str(student.id),
                "name": student.name,
                "current_room_id": str(student.current_room_id) if student.current_room_id else None
            },
            "year": year,
            "month": month,
            "total_days": total_days,
            "total_residences": total_residences,
            "items": monthly_history,
            "summary": {
                "total_rooms_occupied": len(set(r["room_id"] for r in monthly_history if r["room_id"])),
                "total_days_resided": sum(r["days_resided"] for r in monthly_history),
                "average_days_per_room": sum(r["days_resided"] for r in monthly_history) / total_residences if total_residences > 0 else 0
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"학생 월별 거주 이력 조회 중 오류가 발생했습니다: {str(e)}")

@router.post("/{student_id}/change-residence")
def change_student_residence(
    student_id: str,
    request: dict,  # ChangeResidenceRequest 대신 dict 사용
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """학생 거주지 변경"""
    try:
        # 학생 존재 여부 확인
        student = db.query(Student).filter(Student.id == student_id).first()
        if not student:
            raise HTTPException(status_code=404, detail="학생을 찾을 수 없습니다")

        # 현재 거주 중인 방 확인
        current_residence = db.query(Resident).filter(
            Resident.resident_id == student_id,
            Resident.is_active == True,
            Resident.check_out_date.is_(None)
        ).first()

        if not current_residence:
            raise HTTPException(status_code=400, detail="해당 학생은 현재 거주 중인 방이 없습니다")

        # 퇴실만 처리하는 경우 (new_room_id가 None)
        if request.get("new_room_id") is None:
            # 현재 거주지에서 퇴실 처리
            change_date = datetime.strptime(request.get("change_date", datetime.now().strftime("%Y-%m-%d")), "%Y-%m-%d").date()
            current_residence.check_out_date = change_date
            current_residence.is_active = False
            if request.get("note"):
                current_residence.note = f"退去 - {request.get('note')}"
            else:
                current_residence.note = "退去"

            # 학생의 current_room_id 초기화
            student.current_room_id = None
            
            # 방 로그 기록 (RoomLog 모델이 있다면)
            # room_log = RoomLog(
            #     id=str(uuid.uuid4()),
            #     room_id=current_residence.room_id,
            #     student_id=student_id,
            #     action="CHECK_OUT",
            #     action_date=change_date,
            #     note=f"퇴실 - {request.get('note')}" if request.get('note') else "퇴실"
            # )
            # db.add(room_log)
            
            db.commit()
            
            # 데이터베이스 로그 생성
            try:
                create_database_log(
                    db=db,
                    table_name="residents",
                    record_id=str(current_residence.id),
                    action="UPDATE",
                    user_id=current_user["id"] if current_user else None,
                    old_values={"is_active": True, "check_out_date": None},
                    new_values={"is_active": False, "check_out_date": change_date.strftime("%Y-%m-%d")},
                    changed_fields=["is_active", "check_out_date"],
                    note=f"学生退去 - {student.name}: {current_residence.room.room_number if current_residence.room else 'Unknown'}"
                )
            except Exception as log_error:
                print(f"로그 생성 중 오류: {log_error}")
            
            return {
                "message": "학생이 성공적으로 퇴실했습니다",
                "student_id": str(student_id),
                "old_room_id": str(current_residence.room_id),
                "new_room_id": None,
                "change_date": change_date.strftime("%Y-%m-%d"),
                "action": "CHECK_OUT"
            }

        # 이사 처리하는 경우 (new_room_id가 제공됨)
        else:
            # 새로운 방 존재 여부 확인
            new_room = db.query(Room).filter(Room.id == request.get("new_room_id")).first()
            if not new_room:
                raise HTTPException(status_code=404, detail="새로운 방을 찾을 수 없습니다")

            # 새로운 방이 사용 가능한지 확인
            if not new_room.is_available:
                raise HTTPException(status_code=400, detail="해당 방은 현재 사용할 수 없습니다")

            # 새로운 방의 정원 확인
            current_residents_in_new_room = db.query(Resident).filter(
                Resident.room_id == request.get("new_room_id"),
                Resident.is_active == True,
                Resident.check_out_date.is_(None)
            ).count()
            
            if new_room.capacity and current_residents_in_new_room >= new_room.capacity:
                raise HTTPException(status_code=400, detail="해당 방은 정원이 초과되어 입주할 수 없습니다")

            # 1. 현재 거주지에서 퇴실 처리 (이사할 때는 전날에 퇴실)
            change_date_obj = datetime.strptime(request.get("change_date", datetime.now().strftime("%Y-%m-%d")), "%Y-%m-%d").date()
            current_residence.check_out_date = change_date_obj - timedelta(days=1)
            current_residence.is_active = False
            if request.get("note"):
                current_residence.note = f"이사로 인한 퇴실 - {request.get('note')}"

            # 2. 새로운 방에 입주 기록 생성
            check_in_date = change_date_obj  # 변경날짜로 설정
            
            new_residence = Resident(
                id=str(uuid.uuid4()),
                room_id=request.get("new_room_id"),
                resident_id=student_id,
                check_in_date=check_in_date,
                note=f"이사로 인한 입주 - {request.get('note')}" if request.get('note') else "이사로 인한 입주"
            )
            db.add(new_residence)

            # 3. 학생의 current_room_id 업데이트
            student.current_room_id = request.get("new_room_id")
            
            # 4. 방 로그 기록 (RoomLog 모델이 있다면)
            # room_log = RoomLog(
            #     id=str(uuid.uuid4()),
            #     room_id=request.get("new_room_id"),
            #     student_id=student_id,
            #     action="MOVE",
            #     action_date=change_date_obj,
            #     note=f"거주지 변경 - {request.get('note')}" if request.get('note') else "거주지 변경"
            # )
            # db.add(room_log)
            
            db.commit()
            
            # 데이터베이스 로그 생성
            try:
                # 퇴실 로그
                create_database_log(
                    db=db,
                    table_name="residents",
                    record_id=str(current_residence.id),
                    action="UPDATE",
                    user_id=current_user["id"] if current_user else None,
                    old_values={"is_active": True, "check_out_date": None},
                    new_values={"is_active": False, "check_out_date": (change_date_obj - timedelta(days=1)).strftime("%Y-%m-%d")},
                    changed_fields=["is_active", "check_out_date"],
                    note=f"学生引越し退去 - {student.name}: {current_residence.room.room_number if current_residence.room else 'Unknown'}"
                )
                
                # 입주 로그
                create_database_log(
                    db=db,
                    table_name="residents",
                    record_id=str(new_residence.id),
                    action="CREATE",
                    user_id=current_user["id"] if current_user else None,
                    new_values={
                        "room_id": str(request.get("new_room_id")),
                        "resident_id": student_id,
                        "check_in_date": check_in_date.strftime("%Y-%m-%d"),
                        "is_active": True
                    },
                    changed_fields=["room_id", "resident_id", "check_in_date", "is_active"],
                    note=f"学生引越し入居 - {student.name}: {new_room.room_number if new_room else 'Unknown'}"
                )
            except Exception as log_error:
                print(f"로그 생성 중 오류: {log_error}")
            
            return {
                "message": "학생의 거주지가 정상적으로 변경되었습니다",
                "student_id": str(student_id),
                "old_room_id": str(current_residence.room_id),
                "new_room_id": str(request.get("new_room_id")),
                "change_date": change_date_obj.strftime("%Y-%m-%d"),
                "action": "MOVE"
            }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"학생 거주지 변경 중 오류가 발생했습니다: {str(e)}")

@router.post("/{student_id}/new-residence")
def create_new_residence(
    student_id: str,
    request: NewResidenceRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """학생에게 새로운 거주 기록을 추가"""
    try:
        # 학생 존재 여부 확인
        student = db.query(Student).filter(Student.id == student_id).first()
        if not student:
            raise HTTPException(status_code=404, detail="학생을 찾을 수 없습니다")

        # 방 존재 여부 확인
        room = db.query(Room).filter(Room.id == request.new_room_id).first()
        if not room:
            raise HTTPException(status_code=404, detail="방을 찾을 수 없습니다")

        # 방이 사용 가능한지 확인
        if not room.is_available:
            raise HTTPException(status_code=400, detail="해당 방은 현재 사용할 수 없습니다")

        # 입주일과 퇴실일 유효성 검사
        try:
            check_in_date = datetime.strptime(request.change_date, "%Y-%m-%d").date()
            check_out_date = None
            if request.check_out_date:
                check_out_date = datetime.strptime(request.check_out_date, "%Y-%m-%d").date()
                if check_out_date <= check_in_date:
                    raise HTTPException(status_code=400, detail="퇴실일은 입주일보다 늦어야 합니다")
        except ValueError:
            raise HTTPException(status_code=400, detail="날짜 형식이 올바르지 않습니다 (YYYY-MM-DD)")

        # 현재 거주 중인지 확인 (퇴실일이 없는 경우)
        is_currently_residing = check_out_date is None
        
        # 현재 거주 중인 경우, 해당 방의 정원 확인
        if is_currently_residing:
            current_residents = db.query(Resident).filter(
                Resident.room_id == request.new_room_id,
                Resident.is_active == True,
                Resident.check_out_date.is_(None)
            ).count()
            
            # 방에 정원이 설정되어 있고, 현재 거주자 수가 정원에 도달한 경우
            if room.capacity and current_residents >= room.capacity:
                raise HTTPException(status_code=400, detail=f"해당 방은 정원({room.capacity}명)이 초과되어 입주할 수 없습니다. 현재 거주자: {current_residents}명")

        # 거주 기록 생성
        new_residence = Resident(
            id=str(uuid.uuid4()),
            room_id=request.new_room_id,
            resident_id=student_id,
            resident_type="student",  # 명시적으로 student 타입 설정
            check_in_date=check_in_date,
            check_out_date=check_out_date,
            is_active=is_currently_residing,
            note=request.note
        )
        db.add(new_residence)

        # 현재 거주 중인 경우 학생의 current_room_id와 address 업데이트
        if is_currently_residing:
            student.current_room_id = request.new_room_id
            
            # 학생의 주소 업데이트 (빌딩 타입에 따라 다르게 설정)
            building_address = room.building.address if room.building else ""
            building_type = room.building.building_type if room.building else None
            
            if building_type == "mansion":
                # mansion 타입: 빌딩주소 + 방번호
                room_number = room.room_number
                student.address = f"{building_address} {room_number}".strip()
            elif building_type == "house":
                # house 타입: 빌딩주소만
                student.address = building_address.strip()
            else:
                # 기본값: 빌딩주소 + 방번호
                room_number = room.room_number
                student.address = f"{building_address} {room_number}".strip()
        
        # 방 로그 기록 (RoomLog 모델이 있다면)
        # action = "CHECK_IN" if is_currently_residing else "HISTORICAL_ENTRY"
        # room_log = RoomLog(
        #     id=str(uuid.uuid4()),
        #     room_id=request.new_room_id,
        #     student_id=student_id,
        #     action=action,
        #     action_date=check_in_date,
        #     note=f"신규 거주 기록 추가 - {request.note}" if request.note else "신규 거주 기록 추가"
        # )
        # db.add(room_log)
        
        db.commit()
        
        # 데이터베이스 로그 생성
        try:
            create_database_log(
                db=db,
                table_name="residents",
                record_id=str(new_residence.id),
                action="CREATE",
                user_id=current_user["id"] if current_user else None,
                new_values={
                    "room_id": str(request.new_room_id),
                    "resident_id": student_id,
                    "check_in_date": check_in_date.strftime("%Y-%m-%d"),
                    "check_out_date": check_out_date.strftime("%Y-%m-%d") if check_out_date else None,
                    "is_active": is_currently_residing,
                    "note": request.note
                },
                changed_fields=["room_id", "resident_id", "check_in_date", "check_out_date", "is_active", "note"],
                note=f"新規居住記録追加 - {student.name}: {room.room_number} ({room.building.name if room.building else 'Unknown'})"
            )
        except Exception as log_error:
            print(f"로그 생성 중 오류: {log_error}")
        
        return {
            "message": "새로운 거주 기록이 성공적으로 추가되었습니다",
            "student_id": student_id,
            "student_name": student.name,
            "new_room_id": request.new_room_id,
            "room_number": room.room_number,
            "check_in_date": check_in_date.strftime("%Y-%m-%d"),
            "check_out_date": check_out_date.strftime("%Y-%m-%d") if check_out_date else None,
            "is_currently_residing": is_currently_residing,
            "note": request.note
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"새로운 거주 기록 추가 중 오류가 발생했습니다: {str(e)}")

# ===== 월별 관리비 항목 관련 API들 =====

@router.get("/{student_id}/monthly-items")
def get_student_monthly_items(
    student_id: str,
    year: int,
    db: Session = Depends(get_db)
):
    """학생의 월별 관리비 항목 조회"""
    try:
        # 학생 존재 여부 확인
        student = db.query(Student).filter(Student.id == student_id).first()
        if not student:
            raise HTTPException(status_code=404, detail="학생을 찾을 수 없습니다")
        
        # 해당 년도의 월별 관리비 항목 조회
        query = db.query(BillingMonthlyItem).filter(
            BillingMonthlyItem.student_id == student_id,
            BillingMonthlyItem.year == year
        ).order_by(BillingMonthlyItem.sort_order.asc(), BillingMonthlyItem.year, BillingMonthlyItem.month, BillingMonthlyItem.sort_order)
        
        items = query.all()
        
        # 항목별로 그룹화
        grouped_items = {}
        for item in items:
            if item.item_name not in grouped_items:
                grouped_items[item.item_name] = {
                    "item_name": item.item_name,
                    "memo": item.memo,
                    "sort_order": item.sort_order,
                    "months": {}
                }
            
            grouped_items[item.item_name]["months"][item.month] = {
                "id": str(item.id),
                "amount": item.amount,
                "memo": item.memo
            }
        
        # 결과 리스트로 변환
        result_items = []
        for item_name, item_data in grouped_items.items():
            months_list = []
            for month in range(1, 13):
                if month in item_data["months"]:
                    months_list.append({
                        "month": month,
                        "id": item_data["months"][month]["id"],
                        "amount": item_data["months"][month]["amount"],
                        "memo": item_data["months"][month]["memo"]
                    })
                else:
                    months_list.append({
                        "month": month,
                        "id": None,
                        "amount": 0,
                        "memo": ""
                    })
            
            result_items.append({
                "item_name": item_name,
                "memo": item_data["memo"],
                "sort_order": item_data["sort_order"],
                "months": months_list
            })
        
        return {
            "student_id": student_id,
            "student_name": student.name,
            "year": year,
            "items": result_items
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"월별 관리비 항목 조회 중 오류가 발생했습니다: {str(e)}")

@router.post("/{student_id}/monthly-items")
def create_student_monthly_items(
    student_id: str,
    monthly_items: BillingMonthlyItemCreate,
    year: Optional[int] = Query(None, description="생성할 연도 (기본값: 현재 연도)"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """학생의 월별 관리비 항목 생성 (1~12월)"""
    try:
        # 학생 존재 여부 확인
        student = db.query(Student).filter(Student.id == student_id).first()
        if not student:
            raise HTTPException(status_code=404, detail="학생을 찾을 수 없습니다")
        
        target_year = year if year is not None else datetime.now().year
        
        # 기존 항목들 중 가장 큰 sort_order 값 찾기
        max_sort_order = db.query(func.max(BillingMonthlyItem.sort_order)).filter(
            BillingMonthlyItem.student_id == student_id,
            BillingMonthlyItem.year == target_year
        ).scalar()
        
        # 새로운 sort_order 값 설정 (기존 최대값 + 1, 없으면 1)
        new_sort_order = (max_sort_order or 0) + 1
        
        # 1~12월까지 항목 생성
        created_items = []
        for month in range(1, 13):
            item = BillingMonthlyItem(
                id=str(uuid.uuid4()),
                student_id=student_id,
                year=target_year,
                month=month,
                item_name=monthly_items.item_name,
                amount=0,
                memo=monthly_items.memo,
                sort_order=new_sort_order
            )
            db.add(item)
            created_items.append(item)
        
        db.commit()
        
        # 데이터베이스 로그 생성
        try:
            create_database_log(
                db=db,
                table_name="billing_monthly_items",
                record_id=f"batch_create_{student_id}_{target_year}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                action="CREATE",
                user_id=current_user["id"] if current_user else None,
                new_values={
                    "student_id": student_id,
                    "student_name": student.name,
                    "year": target_year,
                    "item_name": monthly_items.item_name,
                    "created_items_count": len(created_items),
                    "sort_order": new_sort_order
                },
                changed_fields=["student_id", "year", "item_name", "sort_order"],
                note=f"月別管理費項目一括作成 - {student.name} ({target_year}年): {monthly_items.item_name} 1~12月"
            )
        except Exception as log_error:
            print(f"로그 생성 중 오류: {log_error}")
        
        return {
            "message": f"{student.name}의 {target_year}년 {monthly_items.item_name} 항목이 1~12월까지 생성되었습니다.",
            "student_id": student_id,
            "student_name": student.name,
            "year": target_year,
            "item_name": monthly_items.item_name,
            "created_items_count": len(created_items)
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"월별 관리비 항목 생성 중 오류가 발생했습니다: {str(e)}")

@router.put("/monthly-items/{item_id}")
def update_student_monthly_item(
    item_id: str,
    monthly_item: BillingMonthlyItemUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """학생의 월별 관리비 항목 수정"""
    try:        
        # 항목 존재 여부 및 해당 학생의 항목인지 확인
        item = db.query(BillingMonthlyItem).filter(
            BillingMonthlyItem.id == item_id
        ).first()
        
        if not item:
            raise HTTPException(status_code=404, detail="해당 항목을 찾을 수 없습니다")
        
        # 수정 전 값 저장 (로그용)
        old_values = {
            "amount": item.amount,
            "memo": item.memo
        }
        
        # 항목 수정
        if monthly_item.amount is not None:
            item.amount = monthly_item.amount
        if monthly_item.memo is not None:
            item.memo = monthly_item.memo
        
        db.commit()
        
        # 데이터베이스 로그 생성
        try:
            create_database_log(
                db=db,
                table_name="billing_monthly_items",
                record_id=str(item.id),
                action="UPDATE",
                user_id=current_user["id"] if current_user else None,
                old_values=old_values,
                new_values={
                    "amount": item.amount,
                    "memo": item.memo
                },
                changed_fields=[k for k, v in monthly_item.dict().items() if v is not None],
                note=f"月別管理費項目更新 - {item.item_name} ({item.year}年{item.month}月)"
            )
        except Exception as log_error:
            print(f"로그 생성 중 오류: {log_error}")
        
        return {
            "message": "월별 관리비 항목이 성공적으로 수정되었습니다",
            "item_id": str(item.id),
            "updated_fields": [k for k, v in monthly_item.dict().items() if v is not None]
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"월별 관리비 항목 수정 중 오류가 발생했습니다: {str(e)}")

@router.put("/monthly-items/sort-order/update")
def update_student_monthly_items_sort_order(
    sort_order_data: MonthlyItemSortOrderUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """월별 관리비 항목의 정렬 순서 업데이트"""
    try:
        year = sort_order_data.year
        items = sort_order_data.items
        student_id = sort_order_data.student_id
        # 학생 존재 여부 확인
        student = db.query(Student).filter(Student.id == student_id).first()
        if not student:
            raise HTTPException(status_code=404, detail="学生が見つかりません")
        
        # 각 항목의 sort_order 업데이트 (해당 학생의 데이터만)
        updated_count = 0
        log_data = []  # 로그 데이터를 저장할 리스트
        
        for item_data in items:
            item_name = item_data["item_name"]
            new_sort_order = item_data["sort_order"]
            
            # 해당 항목의 모든 월 데이터 조회 (학생 ID, 년도, 항목명으로 필터링)
            monthly_items = db.query(BillingMonthlyItem).filter(
                BillingMonthlyItem.item_name == item_name,
                BillingMonthlyItem.student_id == student_id,
                BillingMonthlyItem.year == year
            ).all()
            
            if monthly_items:
                # 각 월의 데이터에 대해 sort_order 업데이트
                for item in monthly_items:
                    # 기존 값 저장 (로그용)
                    old_sort_order = item.sort_order
                    
                    # sort_order 업데이트
                    item.sort_order = new_sort_order
                    
                    # 로그 데이터 수집
                    log_data.append({
                        "record_id": str(item.id),
                        "old_values": {"sort_order": old_sort_order},
                        "new_values": {"sort_order": new_sort_order},
                        "note": f"月別管理費項目の並び順更新 - {item.item_name} ({item.year}年{item.month}月): {old_sort_order} → {new_sort_order}"
                    })
                    
                    updated_count += 1
            else:
                # 해당 항목이 해당 학생의 데이터가 아니거나 존재하지 않는 경우
                raise HTTPException(
                    status_code=404, 
                    detail=f"項目名 '{item_name}'のデータが見つからないか、該当学生のデータではありません"
                )
        
        # 데이터베이스 커밋
        db.commit()
        
        # 모든 업데이트 완료 후 하나의 통합 로그 생성
        try:
            # 통합된 로그 데이터 구성
            consolidated_log = {
                "student_id": student_id,
                "student_name": student.name,
                "year": year,
                "total_items_updated": updated_count,
                "items_details": log_data,
                "summary": {
                    "old_sort_orders": [item["old_values"]["sort_order"] for item in log_data],
                    "new_sort_orders": [item["new_values"]["sort_order"] for item in log_data],
                    "item_names": [item["note"].split(" - ")[1].split(" (")[0] for item in log_data]
                }
            }
            
            # 하나의 통합 로그로 저장
            create_database_log(
                db=db,
                table_name="billing_monthly_items",
                record_id=f"batch_update_{student_id}_{year}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                action="UPDATE",  # BATCH_UPDATE 대신 UPDATE 사용
                user_id=current_user["id"] if current_user else None,
                old_values={"batch_old_data": consolidated_log["summary"]["old_sort_orders"]},
                new_values={"batch_new_data": consolidated_log["summary"]["new_sort_orders"]},
                changed_fields=["sort_order"],
                note=f"月別管理費項目の並び順一括更新 - {student.name} ({year}年): {len(items)}項目の並び順を更新"
            )
            
            print(f"통합 로그 생성 완료: {len(items)}개 항목의 정렬 순서 업데이트")
            
        except Exception as log_error:
            print(f"통합 로그 생성 중 오류: {log_error}")
        
        return {
            "message": f"{student.name}の{year}年の月別管理費項目の並び順が正常に更新されました",
            "student_id": student_id,
            "student_name": student.name,
            "year": year,
            "updated_count": updated_count,
            "total_items": len(items)
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"並び順の更新中にエラーが発生しました: {str(e)}")

@router.delete("/{student_id}/monthly-items/{year}/{item_name}")
def delete_student_monthly_item(
    student_id: str,
    item_name: str,
    year: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """학생의 월별 관리비 항목 삭제"""
    try:
        # 학생 존재 여부 확인
        student = db.query(Student).filter(Student.id == student_id).first()
        if not student:
            raise HTTPException(status_code=404, detail="학생을 찾을 수 없습니다")
        
        # 항목 존재 여부 및 해당 학생의 항목인지 확인
        items = db.query(BillingMonthlyItem).filter(
            BillingMonthlyItem.item_name == item_name,
            BillingMonthlyItem.year == year,
            BillingMonthlyItem.student_id == student_id
        ).all()
        
        if not items:
            raise HTTPException(status_code=404, detail="해당 항목을 찾을 수 없습니다")
        
        # 삭제 전 데이터 저장 (로그용)
        deleted_items_data = []
        for item in items:
            deleted_items_data.append({
                "id": str(item.id),
                "student_id": str(item.student_id),
                "year": item.year,
                "month": item.month,
                "item_name": item.item_name,
                "amount": item.amount,
                "memo": item.memo,
                "sort_order": item.sort_order
            })
        
        # 모든 월 데이터 삭제
        deleted_count = len(items)
        for item in items:
            db.delete(item)
        db.commit()
        
         # 데이터베이스 로그 생성 (각 삭제된 항목별로)
        try:
            for item_data in deleted_items_data:
                create_database_log(
                    db=db,
                    table_name="billing_monthly_items",
                    record_id=item_data["id"],
                    action="DELETE",
                    user_id=current_user["id"] if current_user else None,
                    old_values=item_data,
                    note=f"月別管理費項目削除 - {item_data['item_name']} ({item_data['year']}年{item_data['month']}月)"
                )
        except Exception as log_error:
            print(f"로그 생성 중 오류: {log_error}")
        
        return {
            "message": f"'{item_name}'項目の{deleted_count}ヶ月データが正常に削除されました",
            "student_id": student_id,
            "item_name": item_name,
            "deleted_count": deleted_count
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"항목 삭제 중 오류가 발생했습니다: {str(e)}")

@router.get("/{student_id}/room-charges")
def get_student_room_charges(
    student_id: str,
    page: int = Query(1, description="페이지 번호", ge=1),
    page_size: int = Query(10, description="페이지당 항목 수", ge=1, le=100),
    db: Session = Depends(get_db)
):
    """학생의 방 요금 조회"""
    try:
        # 학생 존재 여부 확인
        student = db.query(Student).filter(Student.id == student_id).first()
        if not student:
            raise HTTPException(status_code=404, detail="학생을 찾을 수 없습니다")
        
        # 학생이 현재 거주 중인 방의 요금 조회
        if not student.current_room_id:
            return {
                "student_id": student_id,
                "student_name": student.name,
                "message": "현재 거주 중인 방이 없습니다",
                "items": [],
                "total": 0
            }
        
        # 학생이 현재 거주 중인 방의 요금 조회
        query = db.query(RoomCharge).filter(RoomCharge.room_id == student.current_room_id)
        
        # 전체 항목 수 계산
        total_count = query.count()
        
        # 페이지네이션 적용
        charges = query.offset((page - 1) * page_size).limit(page_size).all()
        
        # 전체 페이지 수 계산
        total_pages = (total_count + page_size - 1) // page_size
        
        # 응답 데이터 준비
        result = []
        for charge in charges:
            charge_data = {
                "id": str(charge.id),
                "charge_date": charge.charge_date.strftime("%Y-%m-%d") if charge.charge_date else None,
                "total_amount": float(charge.total_amount) if charge.total_amount else 0,
                "description": charge.description,
                "status": charge.status,
                "created_at": charge.created_at.strftime("%Y-%m-%d %H:%M:%S") if charge.created_at else None,
                "updated_at": charge.updated_at.strftime("%Y-%m-%d %H:%M:%S") if charge.updated_at else None
            }
            result.append(charge_data)
        
        return {
            "student_id": student_id,
            "student_name": student.name,
            "current_room_id": str(student.current_room_id),
            "items": result,
            "total": total_count,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_previous": page > 1
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"학생 방 요금 조회 중 오류가 발생했습니다: {str(e)}")

@router.get("/test")
def test_students_endpoint(
    limit: int = Query(10, description="조회할 학생 수", ge=1, le=100),
    db: Session = Depends(get_db)
):
    """학생 테스트 엔드포인트"""
    try:
        # 학생 데이터 조회
        students = db.query(Student).options(
            joinedload(Student.grade),
            joinedload(Student.company)
        ).limit(limit).all()
        
        # 응답 데이터 구성
        students_data = []
        for student in students:
            student_info = {
                "id": str(student.id),
                "name": student.name,
                "email": student.email,
                "grade_name": student.grade.name if student.grade else None,
                "company_name": student.company.name if student.company else None,
                "status": student.status,
                "entry_date": student.entry_date
            }
            students_data.append(student_info)
        
        return {
            "message": "학생 테스트 엔드포인트가 정상적으로 작동합니다",
            "timestamp": datetime.utcnow(),
            "total_students": len(students_data),
            "limit": limit,
            "students": students_data
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"학생 테스트 중 오류가 발생했습니다: {str(e)}")

# ===== 학생 아바타 업로드 관련 API =====

@router.post("/{student_id}/changeAvatar")
async def upload_student_avatar(
    student_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        # 학생 존재 여부 확인
        student = db.query(Student).filter(Student.id == student_id).first()
        if not student:
            raise HTTPException(
                status_code=404,
                detail="학생을 찾을 수 없습니다."
            )

        # 파일 확장자 검사
        file_extension = file.filename.split(".")[-1].lower()
        if file_extension not in ["jpg", "jpeg", "png", "gif"]:
            raise HTTPException(
                status_code=400,
                detail="지원하지 않는 파일 형식입니다. jpg, jpeg, png, gif 파일만 업로드 가능합니다."
            )

        # 파일 크기 검사 (예: 5MB)
        file_size = 0
        chunk_size = 1024 * 1024  # 1MB
        while chunk := await file.read(chunk_size):
            file_size += len(chunk)
            if file_size > 5 * 1024 * 1024:  # 5MB
                raise HTTPException(
                    status_code=400,
                    detail="파일 크기는 5MB를 초과할 수 없습니다."
                )

        # 파일을 다시 처음으로 되돌림
        await file.seek(0)

        # 랜덤 파일명 생성
        random_filename = generate_random_filename(file.filename)
        
        # Supabase Storage에 파일 업로드
        file_path = f"student_avatars/{student_id}/{random_filename}"
        file_content = await file.read()
        
        try:
            print(f"file_path: {file_path}")
            print(f"file_content type: {type(file_content)}, size: {len(file_content)}")
            print(f"file content-type: {file.content_type}")
            
            # service role 클라이언트를 사용하여 Storage 업로드
            result = supabase_storage.storage.from_("avatars").upload(
                file_path,
                file_content,
                {"content-type": file.content_type}
            )
            print(f"Storage upload result: {result}")
            
            # 파일 URL 생성 (anon 클라이언트 사용)
            file_url = supabase.storage.from_("avatars").get_public_url(file_path)
            
            # 학생의 avatar 필드 업데이트
            student.avatar = file_url
            db.commit()
            
            # 데이터베이스 로그 생성
            try:
                create_database_log(
                    db=db,
                    table_name="students",
                    record_id=str(student.id),
                    action="UPDATE",
                    user_id=current_user["id"] if current_user else None,
                    old_values={"avatar": None},  # 기존 아바타 정보
                    new_values={"avatar": file_url},
                    changed_fields=["avatar"],
                    note=f"学生アバター更新 - {student.name}: {random_filename}"
                )
            except Exception as log_error:
                print(f"로그 생성 중 오류: {log_error}")
            
        except Exception as storage_error:
            print(f"Storage 업로드 에러: {storage_error}")
            raise HTTPException(
                status_code=500,
                detail=f"Storage 연결 오류: {str(storage_error)}"
            )
        return {
            "message": "学生のプロフィール画像が正常にアップロードされました。",
            "avatar_url": file_url,
            "original_filename": file.filename,
            "random_filename": random_filename,
            "file_path": file_path
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"파일 업로드 중 오류가 발생했습니다: {str(e)}"
        )

# ===== Residence Card History 적용 관련 API =====

@router.put("/{student_id}/apply-residence-card-history/{history_id}")
def apply_residence_card_history_to_student(
    student_id: str,
    history_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Residence Card History의 데이터를 학생 정보에 적용"""
    try:
        # 학생 존재 여부 확인
        student = db.query(Student).filter(Student.id == student_id).first()
        if not student:
            raise HTTPException(status_code=404, detail="학생을 찾을 수 없습니다")
        
        # Residence Card History 존재 여부 확인
        history = db.query(ResidenceCardHistory).filter(
            ResidenceCardHistory.id == history_id,
            ResidenceCardHistory.student_id == student_id
        ).first()
        
        if not history:
            raise HTTPException(status_code=404, detail="해당 Residence Card History를 찾을 수 없습니다")
        
        # 기존 값 저장 (로그용)
        old_values = {
            "residence_card_number": student.residence_card_number,
            "residence_card_start": student.residence_card_start,
            "residence_card_expiry": student.residence_card_expiry,
            "visa_application_date": student.visa_application_date,
            "visa_year": student.visa_year
        }
        
        # 학생 정보에 Residence Card History 데이터 적용
        student.residence_card_number = history.card_number
        student.residence_card_start = history.start_date
        student.residence_card_expiry = history.expiry_date
        student.visa_application_date = history.application_date
        student.visa_year = history.year
        
        # 데이터베이스 커밋
        db.commit()
        
        # 데이터베이스 로그 생성
        try:
            create_database_log(
                db=db,
                table_name="students",
                record_id=str(student.id),
                action="UPDATE",
                user_id=current_user["id"] if current_user else None,
                old_values=old_values,
                new_values={
                    "residence_card_number": history.card_number,
                    "residence_card_start": history.start_date.strftime("%Y-%m-%d") if history.start_date else None,
                    "residence_card_expiry": history.expiry_date.strftime("%Y-%m-%d") if history.expiry_date else None,
                    "visa_year": history.year
                },
                changed_fields=["residence_card_number", "residence_card_start", "residence_card_expiry", "visa_year"],
                note=f"Residence Card History 적용 - {student.name}: {history.year}년차 데이터 적용 (History ID: {history_id})"
            )
        except Exception as log_error:
            print(f"로그 생성 중 오류: {log_error}")
        
        return {
            "message": f"{student.name}의 Residence Card 정보가 History 데이터로 성공적으로 업데이트되었습니다",
            "student_id": str(student.id),
            "student_name": student.name,
            "history_id": str(history.id),
            "applied_data": {
                "residence_card_number": history.card_number,
                "residence_card_start": history.start_date.strftime("%Y-%m-%d") if history.start_date else None,
                "residence_card_expiry": history.expiry_date.strftime("%Y-%m-%d") if history.expiry_date else None,
                "visa_year": history.year
            },
            "applied_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500, 
            detail=f"Residence Card History 적용 중 오류가 발생했습니다: {str(e)}"
        )

@router.get("/{student_id}/residence-card-histories")
def get_student_residence_card_histories(
    student_id: str,
    page: int = Query(1, description="페이지 번호", ge=1),
    size: int = Query(10, description="페이지당 항목 수", ge=1, le=100),
    db: Session = Depends(get_db)
):
    """학생의 모든 Residence Card History 조회"""
    try:
        # 학생 존재 여부 확인
        student = db.query(Student).filter(Student.id == student_id).first()
        if not student:
            raise HTTPException(status_code=404, detail="학생을 찾을 수 없습니다")
        
        # Residence Card History 조회
        query = db.query(ResidenceCardHistory).filter(
            ResidenceCardHistory.student_id == student_id
        ).order_by(ResidenceCardHistory.year.desc(), ResidenceCardHistory.registered_at.desc())
        
        # 전체 항목 수 계산
        total_count = query.count()
        
        # 페이지네이션 적용
        histories = query.offset((page - 1) * size).limit(size).all()
        
        # 전체 페이지 수 계산
        total_pages = (total_count + size - 1) // size
        
        # 응답 데이터 준비
        result = []
        for history in histories:
            history_data = {
                "id": str(history.id),
                "student_id": str(history.student_id),
                "card_number": history.card_number,
                "start_date": history.start_date.strftime("%Y-%m-%d") if history.start_date else None,
                "expiry_date": history.expiry_date.strftime("%Y-%m-%d") if history.expiry_date else None,
                "year": history.year,
                "registered_at": history.registered_at.strftime("%Y-%m-%d %H:%M:%S") if history.registered_at else None,
                "note": history.note,
                "can_apply": True  # 모든 History는 적용 가능
            }
            result.append(history_data)
        
        return {
            "student": {
                "id": str(student.id),
                "name": student.name,
                "current_residence_card_number": student.residence_card_number,
                "current_residence_card_start": student.residence_card_start.strftime("%Y-%m-%d") if student.residence_card_start else None,
                "current_residence_card_expiry": student.residence_card_expiry.strftime("%Y-%m-%d") if student.residence_card_expiry else None,
                "current_visa_year": student.visa_year
            },
            "items": result,
            "total": total_count,
            "page": page,
            "size": size,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_previous": page > 1
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Residence Card History 조회 중 오류가 발생했습니다: {str(e)}"
        )