from fastapi import FastAPI, Depends, HTTPException, Query, status, UploadFile, File, Response
from fastapi.security import OAuth2PasswordRequestForm, HTTPBearer
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from jose import JWTError, jwt
from datetime import datetime, timedelta, date
from typing import Optional, List
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from database import SessionLocal, engine
from models import Base, User, Company, Student, Grade, Invoice, InvoiceItem, BillingItem, Building, Room, Resident, RoomLog, RoomCharge, ChargeItem, ChargeItemAllocation, RoomUtility
from schemas import UserCreate, UserLogin, StudentUpdate, StudentResponse, InvoiceCreate, InvoiceResponse, StudentCreate, InvoiceUpdate, BuildingCreate, BuildingUpdate, BuildingResponse, RoomCreate, RoomUpdate, RoomResponse, ChangeResidenceRequest, CheckInRequest, CheckOutRequest, AssignRoomRequest, NewResidenceRequest, RoomLogResponse, ResidentResponse, RoomCapacityStatus, EmptyRoomOption, BuildingOption, AvailableRoom, RoomChargeCreate, RoomChargeUpdate, RoomChargeResponse, ChargeItemCreate, ChargeItemUpdate, ChargeItemResponse, ChargeItemAllocationCreate, ChargeItemAllocationUpdate, ChargeItemAllocationResponse, RoomUtilityCreate, RoomUtilityUpdate, RoomUtilityResponse
import uuid
from uuid import UUID
from passlib.hash import bcrypt
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import os
from supabase import create_client
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib import colors
from io import BytesIO
from weasyprint import HTML
from pydantic import BaseModel

templates = Jinja2Templates(directory="templates")

# .env 파일 로드
load_dotenv()

# JWT 설정
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 7  # 7일로 변경

# .env 파일에서 Supabase 설정 로드
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")  # service_role key 사용

app = FastAPI()
Base.metadata.create_all(bind=engine)

# CORS 설정
origins = [
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:5175",    
    "http://localhost:8000",     
    "http://127.0.0.1:3000",
    "http://127.0.0.1:8000",
    "http://127.0.0.1:8080",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # 위에서 정의한 origins 리스트
    allow_credentials=True,  # 쿠키를 포함한 요청을 허용
    allow_methods=["*"],    # 모든 HTTP 메서드 허용
    allow_headers=["*"],    # 모든 HTTP 헤더 허용
)

# Supabase 클라이언트 초기화
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 토큰 생성 함수
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# OAuth2 설정
def get_token_header(token: str = Depends(HTTPBearer())):
    return token.credentials

# 현재 사용자 가져오기
async def get_current_user(token: str = Depends(get_token_header), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise credentials_exception
    return user

# 로그인 엔드포인트
@app.post("/login")
def login(user: UserLogin, db: Session = Depends(get_db)):
    # 이메일로 사용자 찾기
    db_user = db.query(User).filter(User.email == user.email).first()
    
    # 이메일이 존재하지 않는 경우
    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="존재하지 않는 이메일입니다."
        )
    
    # 비밀번호가 틀린 경우
    if not bcrypt.verify(user.password, db_user.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="비밀번호가 일치하지 않습니다."
        )
    
    # 로그인 성공
    access_token_expires = timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    access_token = create_access_token(
        data={"sub": str(db_user.id)}, expires_delta=access_token_expires  # UUID를 문자열로 변환
    )
    
    return {
        "message": "로그인 성공",
        "user_id": str(db_user.id),  # UUID를 문자열로 변환
        "access_token": access_token,
        "token_type": "bearer"
    }

# 회원가입 엔드포인트
@app.post("/signup")
def signup(user: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == user.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="이미 가입된 이메일입니다.")

    hashed_pw = bcrypt.hash(user.password)
    new_user = User(id=str(uuid.uuid4()), email=user.email, password=hashed_pw)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"message": "회원가입 성공", "user_id": new_user.id}

# 학생 목록 조회 (인증 필요)
@app.get("/students")
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
    page: int = Query(1, description="페이지 번호", ge=1),  # 1 이상의 정수
    page_size: int = Query(10, description="페이지당 항목 수", ge=1, le=100),  # 1~100 사이의 정수
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)  # 인증 추가
):
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
            "email": student.email,
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

@app.get("/students/{student_id}")
def get_student(student_id: str, db: Session = Depends(get_db)):
    student = db.query(Student).options(
        joinedload(Student.company), 
        joinedload(Student.grade),
        joinedload(Student.current_room).joinedload(Room.building)
    ).filter(Student.id == student_id).first()
    
    if student is None:
        raise HTTPException(status_code=404, detail="학생을 찾을 수 없습니다")
    
    # 응답 데이터 준비
    student_data = {
        "id": str(student.id),
        "name": student.name,
        "email": student.email,
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

@app.post("/students", status_code=201)
def create_student(
    student: StudentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
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
                return str(value) if isinstance(value, UUID) else value
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

        # 학생 생성
        new_student = Student(
            id=str(uuid.uuid4()),
            name=student.name,
            company_id=parse_uuid(student.company_id),
            consultant=student.consultant,
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
            phone=clean_value(student.phone),
            address=clean_value(student.address),
            arrival_type=clean_value(student.arrival_type),
            residence_card_number=clean_value(student.residence_card_number),
            residence_card_start=parse_date(student.residence_card_start),
            residence_card_expiry=parse_date(student.residence_card_expiry),
            experience_over_2_years=student.experience_over_2_years,
            entry_date=parse_date(student.entry_date),
            local_address=clean_value(student.local_address),
            interview_date=parse_date(student.interview_date),
            pre_guidance_date=parse_date(student.pre_guidance_date),
            orientation_date=parse_date(student.orientation_date),
            certification_application_date=parse_date(student.certification_application_date),
            visa_application_date=parse_date(student.visa_application_date),
            passport_expiration_date=parse_date(student.passport_expiration_date),
            student_type=clean_value(student.student_type),
            current_room_id=parse_uuid(student.current_room_id),
        )
        db.add(new_student)
        db.flush()  # ID 생성을 위해 flush

        # 방 배정 및 입주 처리
        room_info = None
        if student.room_id:
            try:
                print(f"DEBUG: 방 배정 시작 - room_id: {student.room_id}")
                
                # 방 존재 여부 확인
                room = db.query(Room).filter(Room.id == student.room_id).first()
                if not room:
                    raise HTTPException(status_code=404, detail="지정된 방을 찾을 수 없습니다")

                print(f"DEBUG: 방 확인 완료 - room_number: {room.room_number}")

                # 방이 사용 가능한지 확인
                if not room.is_available:
                    raise HTTPException(status_code=400, detail="해당 방은 현재 사용할 수 없습니다")

                # 방의 정원 확인
                current_residents = db.query(Resident).filter(
                    Resident.room_id == student.room_id,
                    Resident.is_active == True,
                    Resident.check_out_date.is_(None)
                ).count()
                
                print(f"DEBUG: 현재 거주자 수: {current_residents}, 정원: {room.capacity}")
                
                if room.capacity and current_residents >= room.capacity:
                    raise HTTPException(status_code=400, detail="해당 방은 정원이 초과되어 입주할 수 없습니다")

                # 입주일 설정 (기본값: 오늘)
                check_in_date = datetime.now().date()
                if student.check_in_date:
                    check_in_date = datetime.strptime(student.check_in_date, "%Y-%m-%d").date()

                print(f"DEBUG: 입주일 설정: {check_in_date}")

                # 학생의 current_room_id 설정
                new_student.current_room_id = student.room_id

                # 입주 기록 생성 (Resident 테이블)
                new_resident = Resident(
                    id=str(uuid.uuid4()),
                    room_id=student.room_id,
                    student_id=new_student.id,
                    check_in_date=check_in_date,
                    note=clean_value(student.room_note)
                )
                db.add(new_resident)
                print(f"DEBUG: Resident 레코드 생성 완료 - id: {new_resident.id}")

                # 방 로그 기록 (RoomLog 테이블)
                room_log = RoomLog(
                    id=str(uuid.uuid4()),
                    room_id=student.room_id,
                    student_id=new_student.id,
                    action="CHECK_IN",
                    action_date=check_in_date,
                    note=f"신규 학생 입주 - {clean_value(student.room_note)}" if clean_value(student.room_note) else "신규 학생 입주"
                )
                db.add(room_log)
                print(f"DEBUG: RoomLog 레코드 생성 완료 - id: {room_log.id}")

                room_info = {
                    "room_id": str(room.id),
                    "room_number": room.room_number,
                    "building_name": room.building.name if room.building else None,
                    "check_in_date": check_in_date.strftime("%Y-%m-%d")
                }
                
                print(f"DEBUG: 방 배정 완료 - 학생: {new_student.id}, 방: {student.room_id}")
                
            except Exception as e:
                print(f"DEBUG: 방 배정 중 오류 - {str(e)}")
                db.rollback()
                raise HTTPException(
                    status_code=500,
                    detail=f"방 배정 중 오류가 발생했습니다: {str(e)}"
                )

        try:
            db.commit()
            print(f"DEBUG: 데이터베이스 커밋 완료")
            db.refresh(new_student)
        except Exception as e:
            print(f"DEBUG: 커밋 중 오류 - {str(e)}")
            db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"데이터베이스 저장 중 오류가 발생했습니다: {str(e)}"
            )

        return {
            "message": "학생이 성공적으로 생성되었습니다",
            "student": {
                "id": str(new_student.id),
                "name": new_student.name,
                "company_id": str(new_student.company_id) if new_student.company_id else None,
                "consultant": new_student.consultant,
                "grade_id": str(new_student.grade_id) if new_student.grade_id else None,
                "current_room_id": str(new_student.current_room_id) if new_student.current_room_id else None,
                "created_at": new_student.created_at
            },
            "room_assignment": room_info
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"학생 생성 중 오류가 발생했습니다: {str(e)}"
        )

@app.put("/students/{student_id}", response_model=StudentResponse)
def update_student(
    student_id: str,
    student_update: StudentUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # 학생 존재 여부 확인
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(
            status_code=404,
            detail="학생을 찾을 수 없습니다."
        )

    # 이메일 중복 검사 (이메일이 변경되는 경우)
    if student_update.email and student_update.email != student.email:
        existing_student = db.query(Student).filter(Student.email == student_update.email).first()
        if existing_student:
            raise HTTPException(
                status_code=400,
                detail="이미 사용 중인 이메일입니다."
            )

    # 회사 존재 여부 확인 (회사가 변경되는 경우)
    if student_update.company_id:
        company = db.query(Company).filter(Company.id == student_update.company_id).first()
        if not company:
            raise HTTPException(
                status_code=404,
                detail="존재하지 않는 회사입니다."
            )

    # 학생 정보 업데이트
    update_data = student_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(student, field, value)

    try:
        db.commit()
        db.refresh(student)
        # UUID를 문자열로 변환
        student_dict = {
            "id": str(student.id),
            "name": student.name,
            "email": student.email,
            "company_id": str(student.company_id),
            "consultant": student.consultant,
            "avatar": student.avatar,
            "created_at": student.created_at
        }
        return student_dict
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"학생 정보 수정 중 오류가 발생했습니다: {str(e)}"
        )

@app.get("/users")
def read_users(db: Session = Depends(get_db)):
    return db.query(User).all()

@app.post("/users")
def create_user(user: dict, db: Session = Depends(get_db)):
    new_user = User(**user)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user

# 모든 회사 목록 조회
@app.get("/companies")
def get_companies(db: Session = Depends(get_db)):
    companies = db.query(Company).all()
    return companies

# 특정 회사 조회
@app.get("/companies/{company_id}")
def get_company(company_id: str, db: Session = Depends(get_db)):
    company = db.query(Company).filter(Company.id == company_id).first()
    if company is None:
        raise HTTPException(status_code=404, detail="회사를 찾을 수 없습니다")
    return company

# 회사 검색
@app.get("/companies/search/{keyword}")
def search_companies(keyword: str, db: Session = Depends(get_db)):
    companies = db.query(Company).filter(
        Company.name.ilike(f"%{keyword}%")
    ).all()
    return companies

# 새 회사 생성
@app.post("/companies")
def create_company(company: dict, db: Session = Depends(get_db)):
    new_company = Company(**company)
    db.add(new_company)
    db.commit()
    db.refresh(new_company)
    return new_company

# 파일 업로드 엔드포인트
@app.post("/upload-avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
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

        # Supabase Storage에 파일 업로드
        file_path = f"avatars/{current_user.id}/{file.filename}"
        file_content = await file.read()
        
        # Storage에 파일 업로드
        result = supabase.storage.from_("avatars").upload(
            file_path,
            file_content,
            {"content-type": file.content_type}
        )

        # 파일 URL 가져오기
        file_url = supabase.storage.from_("avatars").get_public_url(file_path)

        # 데이터베이스에 URL 저장
        current_user.avatar = file_url
        db.commit()

        return {
            "message": "프로필 이미지가 성공적으로 업로드되었습니다.",
            "avatar_url": file_url
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"파일 업로드 중 오류가 발생했습니다: {str(e)}"
        )

@app.post("/students/{student_id}/changeAvatar")
async def upload_student_avatar(
    student_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
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

        # Supabase Storage에 파일 업로드
        file_path = f"student_avatars/{student_id}/{file.filename}"
        file_content = await file.read()
        
        # Storage에 파일 업로드
        result = supabase.storage.from_("avatars").upload(
            file_path,
            file_content,
            {"content-type": file.content_type}
        )

        # 파일 URL 가져오기
        file_url = supabase.storage.from_("avatars").get_public_url(file_path)
        return {
            "message": "학생 프로필 이미지가 성공적으로 업로드되었습니다.",
            "avatar_url": file_url
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"파일 업로드 중 오류가 발생했습니다: {str(e)}"
        )

# 모든 등급 목록 조회
@app.get("/grades")
def get_grades(db: Session = Depends(get_db)):
    grades = db.query(Grade).all()
    return grades

@app.post("/invoices", response_model=InvoiceResponse)
async def create_invoice(
    invoice: InvoiceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 학생 존재 여부 확인
    student = db.query(Student).filter(Student.id == invoice.student_id).first()
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="학생을 찾을 수 없습니다."
        )

    # 해당 월의 청구서가 이미 존재하는지 확인
    existing_invoice = db.query(Invoice).filter(
        Invoice.student_id == invoice.student_id,
        Invoice.year == invoice.year,
        Invoice.month == invoice.month
    ).first()
    
    if existing_invoice:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="해당 월의 청구서가 이미 존재합니다."
        )

    try:
        # 청구서 항목들의 amount 합계 계산
        total_amount = sum(item.amount for item in invoice.items)

        # 해당 월의 마지막 invoice 번호 조회
        last_invoice_count = db.query(Invoice).filter(
            Invoice.year == invoice.year,
            Invoice.month == invoice.month
        ).count()
        
        # 청구서 생성
        new_invoice = Invoice(
            student_id=invoice.student_id,
            year=invoice.year,
            month=invoice.month,
            total_amount=total_amount,  # 계산된 총액 사용
            invoice_number=generate_invoice_number(datetime(invoice.year, invoice.month, 1), last_invoice_count),
            status="SAVED"
        )
        db.add(new_invoice)
        db.flush()  # ID 생성을 위해 flush

        # 청구서 항목 생성
        for item in invoice.items:
            new_item = InvoiceItem(
                invoice_id=new_invoice.id,
                name=item.name,
                unit_price=item.unit_price,
                quantity=item.quantity,  # quantity 필드 추가
                amount=item.amount,
                sort_order=item.sort_order,
                memo=item.memo,
                type=item.type
            )
            db.add(new_item)
        
        db.commit()
        db.refresh(new_invoice)
        
        return new_invoice

    except IntegrityError as e:
      db.rollback()
      print("DEBUG: IntegrityError:", e)
      raise HTTPException(
          status_code=status.HTTP_400_BAD_REQUEST,
          detail=f"청구서 생성 중 오류: {str(e.orig)}"  # 실제 DB에서 온 메시지
      )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    
@app.get("/invoices/{invoice_id}/pdf")
def download_invoice_pdf(invoice_id: str, db: Session = Depends(get_db)):
    # 1. DB에서 invoice, invoice_items 조회 (이전 답변 참고)
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="해당 청구서를 찾을 수 없습니다.")
    invoice_items = db.query(InvoiceItem).filter(InvoiceItem.invoice_id == invoice_id).order_by(InvoiceItem.sort_order).all()

    invoice_dict = {
        "customer_name": '테스트',
        "date": invoice.created_at.strftime("%Y年%m月%d日"),
        "total": invoice.total_amount,
        "note": getattr(invoice, "note", "")
    }
    items_list = [
        {
            "name": item.name,
            "unit_price": item.unit_price,
            "quantity": item.quantity,
            "amount": item.amount
        }
        for item in invoice_items
    ]
    issue_date = datetime.now().strftime("%Y年%m月%d日 %H:%M")
    # 2. HTML 렌더링
    html_content = templates.get_template("invoice.html").render(invoice=invoice_dict, items=items_list, issue_date=issue_date)

    # 3. HTML → PDF 변환
    pdf_bytes = html_to_pdf_bytes(html_content)

    # 4. PDF 파일로 다운로드
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=invoice_{invoice_id}.pdf"}
    )

def html_to_pdf_bytes(html_content: str) -> bytes:
    pdf = HTML(string=html_content).write_pdf()
    return pdf

@app.get("/billing-options")
def billing_options(db: Session = Depends(get_db)):
    return get_billing_options(db)

def get_billing_options(db: Session):
    # 데이터 조회
    res = db.query(BillingItem).all()

    # groupOptions, individualItems 분리
    groupOptions = {}
    individualItems = []

    for row in res:
        item = {
            "name": row.name,
            "unit": row.unit,
            "qna": row.qna,
            "billing_type": row.billing_type
        }
        # value 필드 있으면 추가
        if row.value:
            item["value"] = row.value
        if row.group_type:
            group = row.group_type.lower()
            if group not in groupOptions:
                groupOptions[group] = []
            groupOptions[group].append(item)
        else:
            # individual 항목은 amount 필드 추가
            item["amount"] = row.unit
            individualItems.append(item)
    return {
        "groupOptions": groupOptions,
        "individualItems": individualItems
    }

def generate_invoice_number(date, last_num):
    # date: 2024-06-16, last_num: 7 (이번 달 마지막 번호)
    ym = date.strftime("%Y%m")
    return f"{ym}-{last_num+1:03d}"

# 예) 2024년 6월 8번째 발급이면: 202406-008

@app.get("/invoices")
def get_invoices(
    student_id: Optional[str] = Query(None, description="학생 ID로 검색"),
    page: int = Query(1, description="페이지 번호", ge=1),
    page_size: int = Query(10, description="페이지당 항목 수", ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 기본 쿼리 생성
    query = db.query(Invoice).options(
        joinedload(Invoice.student)
    )

    # student_id가 제공된 경우 해당 학생의 청구서만 필터링
    if student_id:
        query = query.filter(Invoice.student_id == student_id)

    # 전체 항목 수 계산
    total_count = query.count()

    # 페이지네이션 적용
    invoices = query.order_by(Invoice.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    # 전체 페이지 수 계산
    total_pages = (total_count + page_size - 1) // page_size

    return {
        "items": invoices,
        "total": total_count,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_previous": page > 1
    }

@app.get("/company-invoice-pdf/{company_id}/{year}/{month}")
def generate_company_invoice_pdf(
    company_id: str,
    year: int,
    month: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 회사 정보 조회
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="회사를 찾을 수 없습니다")

    # 해당 회사 소속 학생들의 청구서 조회
    invoices = db.query(Invoice).join(Student).options(
        joinedload(Invoice.student),
        joinedload(Invoice.items)  # InvoiceItem 정보도 함께 로드
    ).filter(
        Student.company_id == company_id,
        Invoice.year == year,
        Invoice.month == month
    ).all()

    if not invoices:
        raise HTTPException(status_code=404, detail="해당 월의 청구서가 없습니다")

    # 총 금액 계산
    total_amount = sum(invoice.total_amount for invoice in invoices)

    # 청구서 데이터 준비
    invoice_data = {
        "company_name": company.name,
        "year": year,
        "month": month,
        "total_amount": total_amount,
        "vat_total_amount": int(total_amount + total_amount * 0.1),
        "vat": int(total_amount * 0.1),
        "issue_date": datetime.now().strftime("%Y年%m月%d日"),
        "invoice_list": [{
            "student_name": invoice.student.name,
            "amount": invoice.total_amount,
            "invoice_number": invoice.invoice_number,
            "invoice_items": [{
                "name": item.name,
                "unit_price": item.unit_price,
                "amount": item.amount,
                "memo": item.memo,
                "type": item.type
            } for item in sorted(invoice.items, key=lambda x: x.sort_order)]
        } for invoice in invoices]
    }

    # HTML 템플릿 렌더링
    html_content = templates.get_template("company_invoice.html").render(
        data=invoice_data
    )

    # PDF 생성
    pdf_bytes = html_to_pdf_bytes(html_content)

    # PDF 파일 반환
    filename = f"company_invoice_{company_id}_{year}{month:02d}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "application/pdf"
        }
    )

@app.get("/invoice/{student_id}/{year}/{month}")
def get_student_invoice_by_year_month(
    student_id: str,
    year: int,
    month: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 학생 존재 여부 확인
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="학생을 찾을 수 없습니다")

    # 청구서 조회
    invoice = db.query(Invoice).options(
        joinedload(Invoice.student).joinedload(Student.company),
        joinedload(Invoice.items)
    ).filter(
        Invoice.student_id == student_id,
        Invoice.year == year,
        Invoice.month == month
    ).first()

    if not invoice:
        result = {
            "is_data": False
        }
    else:
        # 응답 데이터 준비
        result = {
          "id": str(invoice.id),
          "is_data": True,
          "invoice_number": invoice.invoice_number,
          "year": invoice.year,
          "month": invoice.month,
          "total_amount": invoice.total_amount,
          "created_at": invoice.created_at,
          "student": {
              "id": str(invoice.student.id),
              "name": invoice.student.name,
              "company": {
                  "id": str(invoice.student.company.id),
                  "name": invoice.student.company.name
              } if invoice.student.company else None
          },
          "items": [{
              "name": item.name,
              "unit_price": item.unit_price,
              "amount": item.amount,
              "quantity": item.quantity,
              "memo": item.memo,
              "type": item.type
          } for item in sorted(invoice.items, key=lambda x: x.sort_order)]
      }

    return result

@app.get("/invoice/{invoice_id}")
def get_invoice_by_id(
    invoice_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
   
    # 청구서 조회
    invoice = db.query(Invoice).options(
        joinedload(Invoice.student).joinedload(Student.company),
        joinedload(Invoice.items)
    ).filter(
        Invoice.id == invoice_id,
    ).first()

    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="청구서를 찾을 수 없습니다."
        )
    else:
        # 응답 데이터 준비
        result = {
          "id": str(invoice.id),
          "is_data": True,
          "invoice_number": invoice.invoice_number,
          "year": invoice.year,
          "month": invoice.month,
          "total_amount": invoice.total_amount,
          "created_at": invoice.created_at,
          "student": {
              "id": str(invoice.student.id),
              "name": invoice.student.name,
              "company": {
                  "id": str(invoice.student.company.id),
                  "name": invoice.student.company.name
              } if invoice.student.company else None
          },
          "items": [{
              "name": item.name,
              "unit_price": item.unit_price,
              "amount": item.amount,
              "quantity": item.quantity,
              "memo": item.memo,
              "type": item.type
          } for item in sorted(invoice.items, key=lambda x: x.sort_order)]
      }

    return result

@app.put("/invoice")
async def update_invoice(
    invoice_update: InvoiceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 청구서 존재 여부 확인
    existing_invoice = db.query(Invoice).filter(Invoice.id == invoice_update.invoice_id).first()
    if not existing_invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="청구서를 찾을 수 없습니다."
        )

    try:
        # 청구서 항목들의 amount 합계 계산
        total_amount = sum(item.amount for item in invoice_update.items)

        # 기존 invoice_items 삭제
        db.query(InvoiceItem).filter(InvoiceItem.invoice_id == invoice_update.invoice_id).delete()

        # 청구서 정보 업데이트
        existing_invoice.year = invoice_update.year
        existing_invoice.month = invoice_update.month
        existing_invoice.total_amount = total_amount

        # 새로운 청구서 항목 생성
        for item in invoice_update.items:
            new_item = InvoiceItem(
                invoice_id=invoice_update.invoice_id,
                name=item.name,
                unit_price=item.unit_price,
                quantity=item.quantity,
                amount=item.amount,
                sort_order=item.sort_order,
                memo=item.memo,
                type=item.type
            )
            db.add(new_item)
        
        db.commit()
        db.refresh(existing_invoice)
        
        return existing_invoice

    except IntegrityError as e:
        db.rollback()
        print("DEBUG: IntegrityError:", e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"청구서 수정 중 오류: {str(e.orig)}"
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

@app.get("/buildings")
def get_buildings(
    name: Optional[str] = Query(None, description="빌딩 이름으로 검색"),
    address: Optional[str] = Query(None, description="주소로 검색"),
    page: int = Query(1, description="페이지 번호", ge=1),
    size: int = Query(10, description="페이지당 항목 수", ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 기본 쿼리 생성
    query = db.query(Building)

    # 필터 조건 추가
    if name:
        query = query.filter(Building.name.ilike(f"%{name}%"))
    if address:
        query = query.filter(Building.address.ilike(f"%{address}%"))

    # 전체 항목 수 계산
    total_count = query.count()

    # 페이지네이션 적용
    buildings = query.offset((page - 1) * size).limit(size).all()

    # 전체 페이지 수 계산
    total_pages = (total_count + size - 1) // size

    return {
        "items": buildings,
        "total": total_count,
        "total_pages": total_pages,
        "current_page": page
    }

@app.get("/buildings/options")
def get_building_options(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """빌딩 목록을 셀렉트 옵션용으로 조회"""
    buildings = db.query(Building).order_by(Building.name).all()
    
    options = []
    for building in buildings:
        # 각 빌딩의 빈 호실 수 계산
        empty_rooms_count = db.query(Room).filter(
            Room.building_id == building.id,
            Room.is_available == True
        ).count()
        
        building_option = {
            "value": str(building.id),
            "label": building.name,
            "address": building.address,
            "empty_rooms_count": empty_rooms_count
        }
        options.append(building_option)
    
    return {
        "options": options,
        "total": len(options)
    }

@app.get("/buildings/{building_id}")
def get_building(
    building_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    building = db.query(Building).filter(Building.id == building_id).first()
    if not building:
        raise HTTPException(status_code=404, detail="빌딩을 찾을 수 없습니다")
    return building

@app.post("/buildings", response_model=BuildingResponse)
def create_building(
    building: BuildingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    new_building = Building(
        id=str(uuid.uuid4()),
        name=building.name,
        address=building.address,
        total_rooms=building.total_rooms,
        note=building.note
    )
    db.add(new_building)
    db.commit()
    db.refresh(new_building)
    return new_building

@app.put("/buildings/{building_id}", response_model=BuildingResponse)
def update_building(
    building_id: str,
    building_update: BuildingUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 빌딩 존재 여부 확인
    building = db.query(Building).filter(Building.id == building_id).first()
    if not building:
        raise HTTPException(status_code=404, detail="빌딩을 찾을 수 없습니다")

    # 빌딩 정보 업데이트
    update_data = building_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(building, field, value)

    try:
        db.commit()
        db.refresh(building)
        return building
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"빌딩 정보 수정 중 오류가 발생했습니다: {str(e)}"
        )

@app.delete("/buildings/{building_id}")
def delete_building(
    building_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 빌딩 존재 여부 확인
    building = db.query(Building).filter(Building.id == building_id).first()
    if not building:
        raise HTTPException(status_code=404, detail="빌딩을 찾을 수 없습니다")

    try:
        db.delete(building)
        db.commit()
        return {"message": "빌딩이 성공적으로 삭제되었습니다"}
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"빌딩 삭제 중 오류가 발생했습니다: {str(e)}"
        )

@app.get("/buildings/{building_id}/rooms")
def get_rooms_by_building(
    building_id: str,
    room_number: Optional[str] = Query(None, description="방 번호로 검색"),
    is_available: Optional[bool] = Query(None, description="사용 가능 여부로 필터링"),
    page: int = Query(1, description="페이지 번호", ge=1),
    size: int = Query(100, description="페이지당 항목 수", ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 빌딩 존재 여부 확인
    building = db.query(Building).filter(Building.id == building_id).first()
    if not building:
        raise HTTPException(status_code=404, detail="빌딩을 찾을 수 없습니다")

    # 기본 쿼리 생성
    query = db.query(Room).filter(Room.building_id == building_id)

    # 필터 조건 추가
    if room_number:
        query = query.filter(Room.room_number.ilike(f"%{room_number}%"))
    if is_available is not None:
        query = query.filter(Room.is_available == is_available)

    # 전체 항목 수 계산
    total_count = query.count()

    # 페이지네이션 적용
    rooms = query.offset((page - 1) * size).limit(size).all()

    # 전체 페이지 수 계산
    total_pages = (total_count + size - 1) // size

    return {
        "items": rooms,
        "total": total_count,
        "total_pages": total_pages,
        "current_page": page
    }

@app.get("/rooms/{room_id}")
def get_room(
    room_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="방을 찾을 수 없습니다")
    return room

@app.post("/rooms", response_model=RoomResponse)
def create_room(
    room: RoomCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 빌딩 존재 여부 확인
    building = db.query(Building).filter(Building.id == room.building_id).first()
    if not building:
        raise HTTPException(status_code=404, detail="빌딩을 찾을 수 없습니다")

    # 같은 빌딩 내에서 방 번호 중복 확인
    existing_room = db.query(Room).filter(
        Room.building_id == room.building_id,
        Room.room_number == room.room_number
    ).first()
    
    if existing_room:
        raise HTTPException(status_code=400, detail="해당 빌딩에 같은 방 번호가 이미 존재합니다")

    # 정원 유효성 검사
    if room.capacity is not None and room.capacity <= 0:
        raise HTTPException(status_code=400, detail="정원은 1명 이상이어야 합니다")

    new_room = Room(
        id=str(uuid.uuid4()),
        building_id=room.building_id,
        room_number=room.room_number,
        rent=room.rent,
        floor=room.floor,
        capacity=room.capacity,
        is_available=room.is_available,
        note=room.note
    )
    db.add(new_room)
    db.commit()
    db.refresh(new_room)
    return new_room

@app.put("/rooms/{room_id}", response_model=RoomResponse)
def update_room(
    room_id: str,
    room_update: RoomUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 방 존재 여부 확인
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="방을 찾을 수 없습니다")

    # 방 번호가 변경되는 경우 중복 확인
    if room_update.room_number and room_update.room_number != room.room_number:
        existing_room = db.query(Room).filter(
            Room.building_id == room.building_id,
            Room.room_number == room_update.room_number,
            Room.id != room_id
        ).first()
        
        if existing_room:
            raise HTTPException(status_code=400, detail="해당 빌딩에 같은 방 번호가 이미 존재합니다")

    # 정원 유효성 검사
    if room_update.capacity is not None and room_update.capacity <= 0:
        raise HTTPException(status_code=400, detail="정원은 1명 이상이어야 합니다")

    # 방 정보 업데이트
    update_data = room_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(room, field, value)

    try:
        db.commit()
        db.refresh(room)
        return room
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"방 정보 수정 중 오류가 발생했습니다: {str(e)}"
        )

@app.delete("/rooms/{room_id}")
def delete_room(
    room_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 방 존재 여부 확인
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="방을 찾을 수 없습니다")

    try:
        db.delete(room)
        db.commit()
        return {"message": "방이 성공적으로 삭제되었습니다"}
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"방 삭제 중 오류가 발생했습니다: {str(e)}"
        )

@app.get("/rooms/{room_id}/residents")
def get_room_residents(
    room_id: str,
    page: int = Query(1, description="페이지 번호", ge=1),
    size: int = Query(10, description="페이지당 항목 수", ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 방 존재 여부 확인
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="방을 찾을 수 없습니다")

    # 해당 방에 실제 입주 중인 학생들 조회 (Resident 테이블 기준)
    query = db.query(Student).options(
        joinedload(Student.company),
        joinedload(Student.grade)
    ).join(Resident).filter(
        Resident.room_id == room_id,
        Resident.is_active == True,
        Resident.check_out_date.is_(None)  # 퇴실일이 없는 경우 (현재 입주 중)
    )

    # 전체 항목 수 계산
    total_count = query.count()

    # 페이지네이션 적용
    residents = query.offset((page - 1) * size).limit(size).all()

    # 전체 페이지 수 계산
    total_pages = (total_count + size - 1) // size

    # 응답 데이터 준비
    result = []
    for student in residents:
        # 해당 학생의 입주 정보 가져오기
        resident_info = db.query(Resident).filter(
            Resident.student_id == student.id,
            Resident.room_id == room_id,
            Resident.is_active == True
        ).first()
        
        resident_data = {
            "id": str(resident_info.id),
            "room_id": str(resident_info.room_id),
            "student_id": str(resident_info.student_id),
            "check_in_date": resident_info.check_in_date.strftime("%Y-%m-%d"),
            "check_out_date": resident_info.check_out_date.strftime("%Y-%m-%d") if resident_info.check_out_date else None,
            "is_active": resident_info.is_active,
            "note": resident_info.note,
            "created_at": resident_info.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": resident_info.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
            "room": {
                "id": str(room.id),
                "room_number": room.room_number,
                "building_id": str(room.building_id)
            },
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
        "items": result,
        "total": total_count,
        "total_pages": total_pages,
        "current_page": page
    }

@app.get("/rooms/{room_id}/residents/count")
def get_room_residents_count(
    room_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 방 존재 여부 확인
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="방을 찾을 수 없습니다")

    # 해당 방에 실제 입주 중인 학생 수 조회 (Resident 테이블 기준)
    resident_count = db.query(Resident).filter(
        Resident.room_id == room_id,
        Resident.is_active == True,
        Resident.check_out_date.is_(None)  # 퇴실일이 없는 경우 (현재 입주 중)
    ).count()

    return {
        "room_id": room_id,
        "resident_count": resident_count
    }

@app.get("/rooms/{room_id}/residence-history")
def get_room_residence_history(
    room_id: str,
    page: int = Query(1, description="페이지 번호", ge=1),
    size: int = Query(10, description="페이지당 항목 수", ge=1, le=100),
    is_active: Optional[bool] = Query(None, description="활성 상태로 필터링"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 방 존재 여부 확인
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="방을 찾을 수 없습니다")

    # 해당 방의 모든 입주 기록 조회
    query = db.query(Resident).options(
        joinedload(Resident.student)
    ).filter(Resident.room_id == room_id)

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
            "student_id": str(resident.student_id),
            "check_in_date": resident.check_in_date.strftime("%Y-%m-%d"),
            "check_out_date": resident.check_out_date.strftime("%Y-%m-%d") if resident.check_out_date else None,
            "is_active": resident.is_active,
            "note": resident.note,
            "created_at": resident.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": resident.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
            "room": {
                "id": str(room.id),
                "room_number": room.room_number,
                "building_id": str(room.building_id)
            },
            "student": {
                "id": str(resident.student.id),
                "name": resident.student.name,
                "name_katakana": resident.student.name_katakana,
                "nationality": resident.student.nationality,
                "phone": resident.student.phone,
                "email": resident.student.email,
                "avatar": resident.student.avatar,
                "gender": resident.student.gender,
                "birth_date": resident.student.birth_date.strftime("%Y-%m-%d") if resident.student.birth_date else None,
                "japanese_level": resident.student.japanese_level,
                "local_address": resident.student.local_address
            }
        }
        result.append(resident_data)

    return {
        "items": result,
        "total": total_count,
        "total_pages": total_pages,
        "current_page": page
    }

@app.put("/students/{student_id}/assign-room")
def assign_student_to_room(
    student_id: str,
    request: AssignRoomRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 학생 존재 여부 확인
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="학생을 찾을 수 없습니다")

    # 방 배정 해제인 경우
    if request.room_id is None:
        student.current_room_id = None
        db.commit()
        return {"message": "학생의 방 배정이 해제되었습니다"}

    # 방 존재 여부 확인
    room = db.query(Room).filter(Room.id == request.room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="방을 찾을 수 없습니다")

    # 방이 사용 가능한지 확인
    if not room.is_available:
        raise HTTPException(status_code=400, detail="해당 방은 현재 사용할 수 없습니다")

    # 학생의 방 배정 업데이트
    student.current_room_id = request.room_id
    db.commit()
    db.refresh(student)

    return {
        "message": "학생이 성공적으로 방에 배정되었습니다",
        "student_id": str(student.id),
        "room_id": str(request.room_id)
    }

@app.post("/rooms/{room_id}/check-in")
def check_in_student(
    room_id: str,
    request: CheckInRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 방 존재 여부 확인
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="방을 찾을 수 없습니다")

    # 학생 존재 여부 확인
    student = db.query(Student).filter(Student.id == request.student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="학생을 찾을 수 없습니다")

    # 방이 사용 가능한지 확인
    if not room.is_available:
        raise HTTPException(status_code=400, detail="해당 방은 현재 사용할 수 없습니다")

    # 이미 해당 방에 입주 중인지 확인
    existing_resident = db.query(Resident).filter(
        Resident.student_id == request.student_id,
        Resident.room_id == room_id,
        Resident.is_active == True,
        Resident.check_out_date.is_(None)
    ).first()
    
    if existing_resident:
        raise HTTPException(status_code=400, detail="해당 학생은 이미 이 방에 입주 중입니다")

    try:
        # 입주 기록 생성
        new_resident = Resident(
            id=str(uuid.uuid4()),
            room_id=room_id,
            student_id=request.student_id,
            check_in_date=datetime.strptime(request.check_in_date, "%Y-%m-%d").date(),
            note=request.note
        )
        db.add(new_resident)

        # 학생의 current_room_id 업데이트
        student.current_room_id = room_id
        
        # 방 로그 기록
        room_log = RoomLog(
            id=str(uuid.uuid4()),
            room_id=room_id,
            student_id=request.student_id,
            action="CHECK_IN",
            action_date=datetime.strptime(request.check_in_date, "%Y-%m-%d").date(),
            note=f"입주 - {request.note}" if request.note else "입주"
        )
        db.add(room_log)
        
        db.commit()
        
        return {
            "message": "학생이 성공적으로 입주했습니다",
            "student_id": str(request.student_id),
            "room_id": str(room_id),
            "check_in_date": request.check_in_date
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"입주 처리 중 오류가 발생했습니다: {str(e)}"
        )

@app.post("/rooms/{room_id}/check-out")
def check_out_student(
    room_id: str,
    request: CheckOutRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 방 존재 여부 확인
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="방을 찾을 수 없습니다")

    # 학생 존재 여부 확인
    student = db.query(Student).filter(Student.id == request.student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="학생을 찾을 수 없습니다")

    # 해당 방에 입주 중인지 확인
    resident = db.query(Resident).filter(
        Resident.student_id == request.student_id,
        Resident.room_id == room_id,
        Resident.is_active == True,
        Resident.check_out_date.is_(None)
    ).first()
    
    if not resident:
        raise HTTPException(status_code=400, detail="해당 학생은 이 방에 입주 중이 아닙니다")

    try:
        # 퇴실 처리
        resident.check_out_date = datetime.strptime(request.check_out_date, "%Y-%m-%d").date()
        resident.is_active = False
        if request.note:
            resident.note = request.note

        # 학생의 current_room_id 초기화
        if student.current_room_id == room_id:
            student.current_room_id = None
        
        # 방 로그 기록
        room_log = RoomLog(
            id=str(uuid.uuid4()),
            room_id=room_id,
            student_id=request.student_id,
            action="CHECK_OUT",
            action_date=datetime.strptime(request.check_out_date, "%Y-%m-%d").date(),
            note=f"퇴실 - {request.note}" if request.note else "퇴실"
        )
        db.add(room_log)
        
        db.commit()
        
        return {
            "message": "학생이 성공적으로 퇴실했습니다",
            "student_id": str(request.student_id),
            "room_id": str(room_id),
            "check_out_date": request.check_out_date
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"퇴실 처리 중 오류가 발생했습니다: {str(e)}"
        )

@app.get("/rooms/{room_id}/capacity-status")
def get_room_capacity_status(
    room_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 방 존재 여부 확인
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="방을 찾을 수 없습니다")

    # 현재 거주자 수 조회
    current_residents = db.query(Resident).filter(
        Resident.room_id == room_id,
        Resident.is_active == True,
        Resident.check_out_date.is_(None)
    ).count()

    # 정원 대비 사용률 계산
    capacity_usage = {
        "room_id": str(room_id),
        "room_number": room.room_number,
        "capacity": room.capacity,
        "current_residents": current_residents,
        "available_spots": room.capacity - current_residents if room.capacity else None,
        "usage_percentage": round((current_residents / room.capacity) * 100, 1) if room.capacity else None,
        "is_full": room.capacity and current_residents >= room.capacity,
        "can_accept_more": room.capacity and current_residents < room.capacity
    }

    return capacity_usage

@app.get("/buildings/{building_id}/empty-rooms")
def get_empty_rooms_by_building(
    building_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """특정 빌딩의 빈 호실 목록을 조회"""
    # 빌딩 존재 여부 확인
    building = db.query(Building).filter(Building.id == building_id).first()
    if not building:
        raise HTTPException(status_code=404, detail="빌딩을 찾을 수 없습니다")

    # 빈 호실 조회 (사용 가능하고 정원이 남은 방들)
    empty_rooms = db.query(Room).filter(
        Room.building_id == building_id,
        Room.is_available == True
    ).order_by(Room.room_number).all()
    
    options = []
    for room in empty_rooms:
        # 현재 거주자 수 조회
        current_residents = db.query(Resident).filter(
            Resident.room_id == room.id,
            Resident.is_active == True,
            Resident.check_out_date.is_(None)
        ).count()
        
        # 정원 대비 사용 가능 여부 확인
        is_available_for_checkin = room.capacity is None or current_residents < room.capacity
        
        if is_available_for_checkin:
            room_option = {
                "value": str(room.id),
                "label": f"{room.room_number}",
                "room_number": room.room_number,
                "floor": room.floor,
                "capacity": room.capacity,
                "current_residents": current_residents,
                "available_spots": room.capacity - current_residents if room.capacity else None,
                "rent": room.rent,
                "note": room.note
            }
            options.append(room_option)
    
    return {
        "building": {
            "id": str(building.id),
            "name": building.name,
            "address": building.address
        },
        "options": options,
        "total": len(options)
    }

@app.get("/rooms/available")
def get_all_available_rooms(
    building_id: Optional[str] = Query(None, description="특정 빌딩으로 필터링"),
    page: int = Query(1, description="페이지 번호", ge=1),
    size: int = Query(10, description="페이지당 항목 수", ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """모든 빈 호실 목록을 조회 (페이지네이션 포함)"""
    # 기본 쿼리 생성
    query = db.query(Room).options(
        joinedload(Room.building)
    ).filter(Room.is_available == True)
    
    # 빌딩 필터링
    if building_id:
        query = query.filter(Room.building_id == building_id)
    
    # 전체 항목 수 계산
    total_count = query.count()
    
    # 페이지네이션 적용
    rooms = query.order_by(Room.building_id, Room.room_number).offset((page - 1) * size).limit(size).all()
    
    # 응답 데이터 준비
    result = []
    for room in rooms:
        # 현재 거주자 수 조회
        current_residents = db.query(Resident).filter(
            Resident.room_id == room.id,
            Resident.is_active == True,
            Resident.check_out_date.is_(None)
        ).count()
        
        # 정원 대비 사용 가능 여부 확인
        is_available_for_checkin = room.capacity is None or current_residents < room.capacity
        
        room_data = {
            "id": str(room.id),
            "room_number": room.room_number,
            "floor": room.floor,
            "capacity": room.capacity,
            "current_residents": current_residents,
            "available_spots": room.capacity - current_residents if room.capacity else None,
            "rent": room.rent,
            "note": room.note,
            "is_available_for_checkin": is_available_for_checkin,
            "building": {
                "id": str(room.building.id),
                "name": room.building.name,
                "address": room.building.address
            }
        }
        result.append(room_data)
    
    # 전체 페이지 수 계산
    total_pages = (total_count + size - 1) // size
    
    return {
        "items": result,
        "total": total_count,
        "total_pages": total_pages,
        "current_page": page
    }

@app.get("/students/{student_id}/residence-history")
def get_student_residence_history(
    student_id: str,
    page: int = Query(1, description="페이지 번호", ge=1),
    size: int = Query(10, description="페이지당 항목 수", ge=1, le=100),
    is_active: Optional[bool] = Query(None, description="활성 상태로 필터링"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 학생 존재 여부 확인
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="학생을 찾을 수 없습니다")

    # 해당 학생의 모든 거주 기록 조회
    query = db.query(Resident).options(
        joinedload(Resident.room).joinedload(Room.building)
    ).filter(Resident.student_id == student_id)

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
            "student_id": str(resident.student_id),
            "check_in_date": resident.check_in_date.strftime("%Y-%m-%d"),
            "check_out_date": resident.check_out_date.strftime("%Y-%m-%d") if resident.check_out_date else None,
            "is_active": resident.is_active,
            "note": resident.note,
            "created_at": resident.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": resident.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
            "room": {
                "id": str(resident.room.id),
                "room_number": resident.room.room_number,
                "building_id": str(resident.room.building_id),
                "floor": resident.room.floor,
                "rent": resident.room.rent
            },
            "building": {
                "id": str(resident.room.building.id),
                "name": resident.room.building.name,
                "address": resident.room.building.address
            },
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

@app.get("/students/{student_id}/residence-history/monthly")
def get_student_residence_history_monthly(
    student_id: str,
    year: int = Query(..., description="조회할 년도"),
    month: int = Query(..., description="조회할 월 (1-12)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """학생의 특정 월 거주 이력을 조회"""
    # 학생 존재 여부 확인
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="학생을 찾을 수 없습니다")

    # 월 유효성 검사
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="월은 1-12 사이의 값이어야 합니다")

    # 해당 월의 시작일과 종료일 계산
    from datetime import date
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
        Resident.student_id == student_id,
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
                "student_id": str(resident.student_id),
                "check_in_date": resident.check_in_date.strftime("%Y-%m-%d"),
                "check_out_date": resident.check_out_date.strftime("%Y-%m-%d") if resident.check_out_date else None,
                "is_active": resident.is_active,
                "note": resident.note,
                "created_at": resident.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                "updated_at": resident.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
                "room": {
                    "id": str(resident.room.id),
                    "room_number": resident.room.room_number,
                    "building_id": str(resident.room.building_id),
                    "floor": resident.room.floor,
                    "rent": resident.room.rent
                },
                "building": {
                    "id": str(resident.room.building.id),
                    "name": resident.room.building.name,
                    "address": resident.room.building.address
                },
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
            monthly_history.append(resident_data)

    return {
        "student": {
            "id": str(student.id),
            "name": student.name,
            "current_room_id": str(student.current_room_id) if student.current_room_id else None
        },
        "items": monthly_history,
        "total": len(monthly_history),
        "total_pages": 1,
        "current_page": 1
    }

@app.post("/students/{student_id}/change-residence")
def change_student_residence(
    student_id: str,
    request: ChangeResidenceRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 학생 존재 여부 확인
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="학생을 찾을 수 없습니다")

    # 현재 거주 중인 방 확인
    current_residence = db.query(Resident).filter(
        Resident.student_id == student_id,
        Resident.is_active == True,
        Resident.check_out_date.is_(None)
    ).first()

    if not current_residence:
        raise HTTPException(status_code=400, detail="해당 학생은 현재 거주 중인 방이 없습니다")

    try:
        # 퇴실만 처리하는 경우 (new_room_id가 None)
        if request.new_room_id is None:
            # 현재 거주지에서 퇴실 처리
            current_residence.check_out_date = datetime.strptime(request.change_date, "%Y-%m-%d").date()
            current_residence.is_active = False
            if request.note:
                current_residence.note = f"퇴실 - {request.note}"
            else:
                current_residence.note = "퇴실"

            # 학생의 current_room_id 초기화
            student.current_room_id = None
            
            # 방 로그 기록
            room_log = RoomLog(
                id=str(uuid.uuid4()),
                room_id=current_residence.room_id,
                student_id=student_id,
                action="CHECK_OUT",
                action_date=datetime.strptime(request.change_date, "%Y-%m-%d").date(),
                note=f"퇴실 - {request.note}" if request.note else "퇴실"
            )
            db.add(room_log)
            
            db.commit()
            
            return {
                "message": "학생이 성공적으로 퇴실했습니다",
                "student_id": str(student_id),
                "old_room_id": str(current_residence.room_id),
                "new_room_id": None,
                "change_date": request.change_date,
                "action": "CHECK_OUT"
            }

        # 이사 처리하는 경우 (new_room_id가 제공됨)
        else:
            # 새로운 방 존재 여부 확인
            new_room = db.query(Room).filter(Room.id == request.new_room_id).first()
            if not new_room:
                raise HTTPException(status_code=404, detail="새로운 방을 찾을 수 없습니다")

            # 새로운 방이 사용 가능한지 확인
            if not new_room.is_available:
                raise HTTPException(status_code=400, detail="해당 방은 현재 사용할 수 없습니다")

            # 새로운 방의 정원 확인
            current_residents_in_new_room = db.query(Resident).filter(
                Resident.room_id == request.new_room_id,
                Resident.is_active == True,
                Resident.check_out_date.is_(None)
            ).count()
            
            if new_room.capacity and current_residents_in_new_room >= new_room.capacity:
                raise HTTPException(status_code=400, detail="해당 방은 정원이 초과되어 입주할 수 없습니다")

            # 1. 현재 거주지에서 퇴실 처리
            current_residence.check_out_date = datetime.strptime(request.change_date, "%Y-%m-%d").date()
            current_residence.is_active = False
            if request.note:
                current_residence.note = f"이사로 인한 퇴실 - {request.note}"

            # 2. 새로운 방에 입주 기록 생성
            change_date_obj = datetime.strptime(request.change_date, "%Y-%m-%d").date()
            check_in_date = change_date_obj + timedelta(days=1)  # 다음날로 설정
            
            new_residence = Resident(
                id=str(uuid.uuid4()),
                room_id=request.new_room_id,
                student_id=student_id,
                check_in_date=check_in_date,
                note=f"이사로 인한 입주 - {request.note}" if request.note else "이사로 인한 입주"
            )
            db.add(new_residence)

            # 3. 학생의 current_room_id 업데이트
            student.current_room_id = request.new_room_id
            
            # 4. 방 로그 기록
            room_log = RoomLog(
                id=str(uuid.uuid4()),
                room_id=request.new_room_id,
                student_id=student_id,
                action="MOVE",
                action_date=datetime.strptime(request.change_date, "%Y-%m-%d").date(),
                note=f"거주지 변경 - {request.note}" if request.note else "거주지 변경"
            )
            db.add(room_log)
            
            db.commit()
            
            return {
                "message": "학생의 거주지가 성공적으로 변경되었습니다",
                "student_id": str(student_id),
                "old_room_id": str(current_residence.room_id),
                "new_room_id": str(request.new_room_id),
                "change_date": request.change_date,
                "action": "MOVE"
            }

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"거주지 변경 중 오류가 발생했습니다: {str(e)}"
        )

@app.get("/rooms")
def get_all_rooms(
    page: int = Query(1, description="페이지 번호", ge=1),
    size: int = Query(10, description="페이지당 항목 수", ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """모든 방 목록을 조회"""
    # 기본 쿼리 생성
    query = db.query(Room).options(
        joinedload(Room.building)
    )
    
    # 전체 항목 수 계산
    total_count = query.count()
    
    # 페이지네이션 적용
    rooms = query.order_by(Room.building_id, Room.room_number).offset((page - 1) * size).limit(size).all()
    
    # 응답 데이터 준비
    result = []
    for room in rooms:
        # 현재 거주자 수 조회
        current_residents = db.query(Resident).filter(
            Resident.room_id == room.id,
            Resident.is_active == True,
            Resident.check_out_date.is_(None)
        ).count()
        
        room_data = {
            "id": str(room.id),
            "room_number": room.room_number,
            "floor": room.floor,
            "capacity": room.capacity,
            "current_residents": current_residents,
            "available_spots": room.capacity - current_residents if room.capacity else None,
            "rent": room.rent,
            "note": room.note,
            "is_available": room.is_available,
            "building": {
                "id": str(room.building.id),
                "name": room.building.name,
                "address": room.building.address
            }
        }
        result.append(room_data)
    
    # 전체 페이지 수 계산
    total_pages = (total_count + size - 1) // size
    
    return {
        "items": result,
        "total": total_count,
        "total_pages": total_pages,
        "current_page": page
    }

@app.post("/students/{student_id}/new-residence")
def create_new_residence(
    student_id: str,
    request: NewResidenceRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """학생에게 새로운 거주 기록을 추가"""
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

    try:
        # 거주 기록 생성
        new_residence = Resident(
            id=str(uuid.uuid4()),
            room_id=request.new_room_id,
            student_id=student_id,
            check_in_date=check_in_date,
            check_out_date=check_out_date,
            is_active=is_currently_residing,
            note=request.note
        )
        db.add(new_residence)

        # 현재 거주 중인 경우 학생의 current_room_id 업데이트
        if is_currently_residing:
            student.current_room_id = request.new_room_id
        
        # 방 로그 기록
        action = "CHECK_IN" if is_currently_residing else "HISTORICAL_ENTRY"
        room_log = RoomLog(
            id=str(uuid.uuid4()),
            room_id=request.new_room_id,
            student_id=student_id,
            action=action,
            action_date=check_in_date,
            note=f"신규 거주 기록 추가 - {request.note}" if request.note else "신규 거주 기록 추가"
        )
        db.add(room_log)
        
        db.commit()
        
        return {
            "message": "새로운 거주 기록이 성공적으로 추가되었습니다",
            "student_id": str(student_id),
            "room_id": str(request.new_room_id),
            "check_in_date": request.change_date,
            "check_out_date": request.check_out_date,
            "is_currently_residing": is_currently_residing,
            "residence_id": str(new_residence.id)
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"거주 기록 추가 중 오류가 발생했습니다: {str(e)}"
        )

# 광열비 관련 API들
@app.post("/room-charges", response_model=RoomChargeResponse)
def create_room_charge(
    charge: RoomChargeCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """광열비 등록 (새로운 구조)"""
    # 학생 존재 여부 확인
    student = db.query(Student).filter(Student.id == charge.student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="학생을 찾을 수 없습니다")

    # 방 존재 여부 확인
    room = db.query(Room).filter(Room.id == charge.room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="방을 찾을 수 없습니다")

    # 날짜 형식 검증
    try:
        charge_month = datetime.strptime(charge.charge_month, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="날짜 형식이 올바르지 않습니다 (YYYY-MM-DD)")

    # 해당 월에 이미 광열비가 등록되어 있는지 확인
    existing_charge = db.query(RoomCharge).filter(
        RoomCharge.student_id == charge.student_id,
        RoomCharge.room_id == charge.room_id,
        RoomCharge.charge_month == charge_month
    ).first()
    
    if existing_charge:
        raise HTTPException(status_code=400, detail="해당 월에 이미 광열비가 등록되어 있습니다")

    try:
        # 광열비 등록
        new_charge = RoomCharge(
            id=str(uuid.uuid4()),
            student_id=charge.student_id,
            room_id=charge.room_id,
            charge_month=charge_month,
            total_amount=charge.total_amount,
            note=charge.note
        )
        db.add(new_charge)
        db.flush()  # ID 생성을 위해 flush

        # 청구 항목들 생성
        if charge.charge_items:
            for item_data in charge.charge_items:
                # 날짜 변환
                period_start = None
                period_end = None
                if item_data.period_start:
                    period_start = datetime.strptime(item_data.period_start, "%Y-%m-%d").date()
                if item_data.period_end:
                    period_end = datetime.strptime(item_data.period_end, "%Y-%m-%d").date()

                charge_item = ChargeItem(
                    id=str(uuid.uuid4()),
                    room_charge_id=new_charge.id,
                    charge_type=item_data.charge_type,
                    period_start=period_start,
                    period_end=period_end,
                    amount=item_data.amount,
                    unit_price=item_data.unit_price,
                    quantity=item_data.quantity,
                    memo=item_data.memo
                )
                db.add(charge_item)

        db.commit()
        db.refresh(new_charge)

        # 응답 데이터 준비
        response_data = {
            "id": str(new_charge.id),
            "student_id": str(new_charge.student_id),
            "room_id": str(new_charge.room_id),
            "charge_month": new_charge.charge_month,
            "total_amount": float(new_charge.total_amount) if new_charge.total_amount else None,
            "created_at": new_charge.created_at,
            "note": new_charge.note,
            "student": {
                "id": str(student.id),
                "name": student.name,
                "name_katakana": student.name_katakana
            },
            "room": {
                "id": str(room.id),
                "room_number": room.room_number,
                "building_name": room.building.name if room.building else None
            },
            "charge_items": []
        }

        # 청구 항목 정보 추가
        if new_charge.charge_items:
            for item in new_charge.charge_items:
                item_data = {
                    "id": str(item.id),
                    "room_charge_id": str(item.room_charge_id),
                    "charge_type": item.charge_type,
                    "period_start": item.period_start.strftime("%Y-%m-%d") if item.period_start else None,
                    "period_end": item.period_end.strftime("%Y-%m-%d") if item.period_end else None,
                    "amount": float(item.amount) if item.amount else None,
                    "unit_price": float(item.unit_price) if item.unit_price else None,
                    "quantity": float(item.quantity) if item.quantity else None,
                    "memo": item.memo,
                    "allocations": []
                }
                response_data["charge_items"].append(item_data)

        return response_data

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"광열비 등록 중 오류가 발생했습니다: {str(e)}"
        )

@app.post("/charge-items/{charge_item_id}/allocations")
def create_charge_item_allocation(
    charge_item_id: str,
    allocation: ChargeItemAllocationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """청구 항목 배분 등록"""
    # 청구 항목 존재 여부 확인
    charge_item = db.query(ChargeItem).filter(ChargeItem.id == charge_item_id).first()
    if not charge_item:
        raise HTTPException(status_code=404, detail="청구 항목을 찾을 수 없습니다")

    # 학생 존재 여부 확인
    student = db.query(Student).filter(Student.id == allocation.student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="학생을 찾을 수 없습니다")

    # 이미 배분이 등록되어 있는지 확인
    existing_allocation = db.query(ChargeItemAllocation).filter(
        ChargeItemAllocation.charge_item_id == charge_item_id,
        ChargeItemAllocation.student_id == allocation.student_id
    ).first()
    
    if existing_allocation:
        raise HTTPException(status_code=400, detail="해당 학생에게 이미 배분이 등록되어 있습니다")

    try:
        # 배분 등록
        new_allocation = ChargeItemAllocation(
            id=str(uuid.uuid4()),
            charge_item_id=charge_item_id,
            student_id=allocation.student_id,
            amount=allocation.amount,
            days_used=allocation.days_used,
            memo=allocation.memo
        )
        db.add(new_allocation)
        db.commit()
        db.refresh(new_allocation)

        return {
            "message": "청구 항목 배분이 성공적으로 등록되었습니다",
            "id": str(new_allocation.id),
            "charge_item_id": str(charge_item_id),
            "student_id": str(allocation.student_id),
            "amount": float(new_allocation.amount),
            "days_used": new_allocation.days_used,
            "memo": new_allocation.memo
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"청구 항목 배분 등록 중 오류가 발생했습니다: {str(e)}"
        )

@app.get("/charge-items/{charge_item_id}/allocations")
def get_charge_item_allocations(
    charge_item_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """청구 항목의 배분 목록 조회"""
    # 청구 항목 존재 여부 확인
    charge_item = db.query(ChargeItem).filter(ChargeItem.id == charge_item_id).first()
    if not charge_item:
        raise HTTPException(status_code=404, detail="청구 항목을 찾을 수 없습니다")

    # 배분 목록 조회
    allocations = db.query(ChargeItemAllocation).options(
        joinedload(ChargeItemAllocation.student)
    ).filter(ChargeItemAllocation.charge_item_id == charge_item_id).all()

    result = []
    for allocation in allocations:
        allocation_data = {
            "id": str(allocation.id),
            "charge_item_id": str(allocation.charge_item_id),
            "student_id": str(allocation.student_id),
            "amount": float(allocation.amount),
            "days_used": allocation.days_used,
            "memo": allocation.memo,
            "student": {
                "id": str(allocation.student.id),
                "name": allocation.student.name,
                "name_katakana": allocation.student.name_katakana
            }
        }
        result.append(allocation_data)

    return {
        "charge_item": {
            "id": str(charge_item.id),
            "charge_type": charge_item.charge_type,
            "amount": float(charge_item.amount) if charge_item.amount else None
        },
        "allocations": result,
        "total": len(result)
    }

@app.put("/charge-items/{charge_item_id}/allocations/{allocation_id}")
def update_charge_item_allocation(
    charge_item_id: str,
    allocation_id: str,
    allocation_update: ChargeItemAllocationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """청구 항목 배분 수정"""
    # 배분 존재 여부 확인
    allocation = db.query(ChargeItemAllocation).filter(
        ChargeItemAllocation.id == allocation_id,
        ChargeItemAllocation.charge_item_id == charge_item_id
    ).first()
    
    if not allocation:
        raise HTTPException(status_code=404, detail="배분을 찾을 수 없습니다")

    try:
        # 업데이트할 데이터 준비
        update_data = allocation_update.dict(exclude_unset=True)
        
        # 금액이 제공된 경우 float로 변환
        if "amount" in update_data and update_data["amount"] is not None:
            update_data["amount"] = float(update_data["amount"])

        # 데이터 업데이트
        for field, value in update_data.items():
            setattr(allocation, field, value)

        db.commit()
        db.refresh(allocation)

        return {
            "message": "청구 항목 배분이 성공적으로 수정되었습니다",
            "id": str(allocation.id),
            "amount": float(allocation.amount),
            "days_used": allocation.days_used,
            "memo": allocation.memo
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"청구 항목 배분 수정 중 오류가 발생했습니다: {str(e)}"
        )

@app.delete("/charge-items/{charge_item_id}/allocations/{allocation_id}")
def delete_charge_item_allocation(
    charge_item_id: str,
    allocation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """청구 항목 배분 삭제"""
    # 배분 존재 여부 확인
    allocation = db.query(ChargeItemAllocation).filter(
        ChargeItemAllocation.id == allocation_id,
        ChargeItemAllocation.charge_item_id == charge_item_id
    ).first()
    
    if not allocation:
        raise HTTPException(status_code=404, detail="배분을 찾을 수 없습니다")

    try:
        db.delete(allocation)
        db.commit()
        return {"message": "청구 항목 배분이 성공적으로 삭제되었습니다"}

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"청구 항목 배분 삭제 중 오류가 발생했습니다: {str(e)}"
        )

@app.get("/students/{student_id}/room-charges")
def get_student_room_charges(
    student_id: str,
    page: int = Query(1, description="페이지 번호", ge=1),
    size: int = Query(10, description="페이지당 항목 수", ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """특정 학생의 광열비 목록 조회"""
    # 학생 존재 여부 확인
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="학생을 찾을 수 없습니다")

    # 해당 학생의 광열비 조회
    query = db.query(RoomCharge).options(
        joinedload(RoomCharge.room).joinedload(Room.building)
    ).filter(RoomCharge.student_id == student_id)

    # 전체 항목 수 계산
    total_count = query.count()

    # 페이지네이션 적용 (최신순)
    charges = query.order_by(RoomCharge.charge_month.desc()).offset((page - 1) * size).limit(size).all()

    # 전체 페이지 수 계산
    total_pages = (total_count + size - 1) // size

    # 응답 데이터 준비
    result = []
    for charge in charges:
        charge_data = {
            "id": str(charge.id),
            "room_id": str(charge.room_id),
            "charge_month": charge.charge_month.strftime("%Y-%m-%d"),
            "total_amount": float(charge.total_amount) if charge.total_amount else None,
            "created_at": charge.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "note": charge.note,
            "room": {
                "id": str(charge.room.id),
                "room_number": charge.room.room_number,
                "building_name": charge.room.building.name if charge.room.building else None
            }
        }
        result.append(charge_data)

    return {
        "student": {
            "id": str(student.id),
            "name": student.name,
            "name_katakana": student.name_katakana
        },
        "items": result,
        "total": total_count,
        "total_pages": total_pages,
        "current_page": page
    }

@app.get("/room-charges")
def get_room_charges(
    student_id: Optional[str] = Query(None, description="학생 ID로 필터링"),
    room_id: Optional[str] = Query(None, description="방 ID로 필터링"),
    charge_month: Optional[str] = Query(None, description="청구 월로 필터링 (YYYY-MM)"),
    page: int = Query(1, description="페이지 번호", ge=1),
    size: int = Query(10, description="페이지당 항목 수", ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """광열비 목록 조회 (새로운 구조)"""
    # 기본 쿼리 생성
    query = db.query(RoomCharge).options(
        joinedload(RoomCharge.student),
        joinedload(RoomCharge.room).joinedload(Room.building),
        joinedload(RoomCharge.charge_items)
    )

    # 필터 조건 추가
    if student_id:
        query = query.filter(RoomCharge.student_id == student_id)
    if room_id:
        query = query.filter(RoomCharge.room_id == room_id)
    if charge_month:
        try:
            # YYYY-MM 형식으로 받아서 해당 월의 첫날로 변환
            year, month = charge_month.split("-")
            start_date = datetime(int(year), int(month), 1).date()
            if int(month) == 12:
                end_date = datetime(int(year) + 1, 1, 1).date() - timedelta(days=1)
            else:
                end_date = datetime(int(year), int(month) + 1, 1).date() - timedelta(days=1)
            
            query = query.filter(
                RoomCharge.charge_month >= start_date,
                RoomCharge.charge_month <= end_date
            )
        except ValueError:
            raise HTTPException(status_code=400, detail="청구 월 형식이 올바르지 않습니다 (YYYY-MM)")

    # 전체 항목 수 계산
    total_count = query.count()

    # 페이지네이션 적용 (최신순)
    charges = query.order_by(RoomCharge.charge_month.desc()).offset((page - 1) * size).limit(size).all()

    # 전체 페이지 수 계산
    total_pages = (total_count + size - 1) // size

    # 응답 데이터 준비
    result = []
    for charge in charges:
        charge_data = {
            "id": str(charge.id),
            "student_id": str(charge.student_id),
            "room_id": str(charge.room_id),
            "charge_month": charge.charge_month.strftime("%Y-%m-%d"),
            "total_amount": float(charge.total_amount) if charge.total_amount else None,
            "created_at": charge.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "note": charge.note,
            "student": {
                "id": str(charge.student.id),
                "name": charge.student.name,
                "name_katakana": charge.student.name_katakana
            },
            "room": {
                "id": str(charge.room.id),
                "room_number": charge.room.room_number,
                "building_name": charge.room.building.name if charge.room.building else None
            },
            "charge_items": []
        }

        # 청구 항목 정보 추가
        for item in charge.charge_items:
            item_data = {
                "id": str(item.id),
                "charge_type": item.charge_type,
                "period_start": item.period_start.strftime("%Y-%m-%d") if item.period_start else None,
                "period_end": item.period_end.strftime("%Y-%m-%d") if item.period_end else None,
                "amount": float(item.amount) if item.amount else None,
                "unit_price": float(item.unit_price) if item.unit_price else None,
                "quantity": float(item.quantity) if item.quantity else None,
                "memo": item.memo
            }
            charge_data["charge_items"].append(item_data)

        result.append(charge_data)

    return {
        "items": result,
        "total": total_count,
        "total_pages": total_pages,
        "current_page": page
    }

@app.get("/room-charges/{charge_id}")
def get_room_charge(
    charge_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """특정 광열비 조회 (새로운 구조)"""
    charge = db.query(RoomCharge).options(
        joinedload(RoomCharge.student),
        joinedload(RoomCharge.room).joinedload(Room.building),
        joinedload(RoomCharge.charge_items).joinedload(ChargeItem.allocations).joinedload(ChargeItemAllocation.student)
    ).filter(RoomCharge.id == charge_id).first()
    
    if not charge:
        raise HTTPException(status_code=404, detail="광열비를 찾을 수 없습니다")

    # 청구 항목 정보 준비
    charge_items = []
    for item in charge.charge_items:
        # 배분 정보 준비
        allocations = []
        for allocation in item.allocations:
            allocation_data = {
                "id": str(allocation.id),
                "student_id": str(allocation.student_id),
                "amount": float(allocation.amount),
                "days_used": allocation.days_used,
                "memo": allocation.memo,
                "student": {
                    "id": str(allocation.student.id),
                    "name": allocation.student.name,
                    "name_katakana": allocation.student.name_katakana
                }
            }
            allocations.append(allocation_data)

        item_data = {
            "id": str(item.id),
            "charge_type": item.charge_type,
            "period_start": item.period_start.strftime("%Y-%m-%d") if item.period_start else None,
            "period_end": item.period_end.strftime("%Y-%m-%d") if item.period_end else None,
            "amount": float(item.amount) if item.amount else None,
            "unit_price": float(item.unit_price) if item.unit_price else None,
            "quantity": float(item.quantity) if item.quantity else None,
            "memo": item.memo,
            "allocations": allocations
        }
        charge_items.append(item_data)

    return {
        "id": str(charge.id),
        "student_id": str(charge.student_id),
        "room_id": str(charge.room_id),
        "charge_month": charge.charge_month.strftime("%Y-%m-%d"),
        "total_amount": float(charge.total_amount) if charge.total_amount else None,
        "created_at": charge.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        "note": charge.note,
        "student": {
            "id": str(charge.student.id),
            "name": charge.student.name,
            "name_katakana": charge.student.name_katakana
        },
        "room": {
            "id": str(charge.room.id),
            "room_number": charge.room.room_number,
            "building_name": charge.room.building.name if charge.room.building else None
        },
        "charge_items": charge_items
    }

@app.put("/room-charges/{charge_id}")
def update_room_charge(
    charge_id: str,
    charge_update: RoomChargeUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """광열비 수정"""
    # 광열비 존재 여부 확인
    charge = db.query(RoomCharge).filter(RoomCharge.id == charge_id).first()
    if not charge:
        raise HTTPException(status_code=404, detail="광열비를 찾을 수 없습니다")

    try:
        # 업데이트할 데이터 준비
        update_data = charge_update.dict(exclude_unset=True)
        
        # 금액이 제공된 경우 float로 변환
        if "total_amount" in update_data and update_data["total_amount"] is not None:
            update_data["total_amount"] = float(update_data["total_amount"])

        # 데이터 업데이트
        for field, value in update_data.items():
            setattr(charge, field, value)

        db.commit()
        db.refresh(charge)

        return {
            "message": "광열비가 성공적으로 수정되었습니다",
            "id": str(charge.id),
            "total_amount": float(charge.total_amount) if charge.total_amount else None,
            "note": charge.note
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"광열비 수정 중 오류가 발생했습니다: {str(e)}"
        )

@app.delete("/room-charges/{charge_id}")
def delete_room_charge(
    charge_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """광열비 삭제"""
    # 광열비 존재 여부 확인
    charge = db.query(RoomCharge).filter(RoomCharge.id == charge_id).first()
    if not charge:
        raise HTTPException(status_code=404, detail="광열비를 찾을 수 없습니다")

    try:
        db.delete(charge)
        db.commit()
        return {"message": "광열비가 성공적으로 삭제되었습니다"}

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"광열비 삭제 중 오류가 발생했습니다: {str(e)}"
        )

@app.post("/room-charges/{charge_id}/charge-items")
def create_charge_item(
    charge_id: str,
    charge_item: ChargeItemCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """청구 항목 추가"""
    # 광열비 존재 여부 확인
    room_charge = db.query(RoomCharge).filter(RoomCharge.id == charge_id).first()
    if not room_charge:
        raise HTTPException(status_code=404, detail="광열비를 찾을 수 없습니다")

    # 날짜 변환
    period_start = None
    period_end = None
    if charge_item.period_start:
        try:
            period_start = datetime.strptime(charge_item.period_start, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="기간 시작일 형식이 올바르지 않습니다 (YYYY-MM-DD)")
    
    if charge_item.period_end:
        try:
            period_end = datetime.strptime(charge_item.period_end, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="기간 종료일 형식이 올바르지 않습니다 (YYYY-MM-DD)")

    try:
        # 청구 항목 생성
        new_charge_item = ChargeItem(
            id=str(uuid.uuid4()),
            room_charge_id=charge_id,
            charge_type=charge_item.charge_type,
            period_start=period_start,
            period_end=period_end,
            amount=charge_item.amount,
            unit_price=charge_item.unit_price,
            quantity=charge_item.quantity,
            memo=charge_item.memo
        )
        db.add(new_charge_item)
        db.commit()
        db.refresh(new_charge_item)

        return {
            "message": "청구 항목이 성공적으로 추가되었습니다",
            "id": str(new_charge_item.id),
            "charge_type": new_charge_item.charge_type,
            "amount": float(new_charge_item.amount) if new_charge_item.amount else None
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"청구 항목 추가 중 오류가 발생했습니다: {str(e)}"
        )

@app.put("/charge-items/{charge_item_id}")
def update_charge_item(
    charge_item_id: str,
    charge_item_update: ChargeItemUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """청구 항목 수정"""
    # 청구 항목 존재 여부 확인
    charge_item = db.query(ChargeItem).filter(ChargeItem.id == charge_item_id).first()
    if not charge_item:
        raise HTTPException(status_code=404, detail="청구 항목을 찾을 수 없습니다")

    try:
        # 업데이트할 데이터 준비
        update_data = charge_item_update.dict(exclude_unset=True)
        
        # 날짜 변환
        if "period_start" in update_data and update_data["period_start"]:
            try:
                update_data["period_start"] = datetime.strptime(update_data["period_start"], "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(status_code=400, detail="기간 시작일 형식이 올바르지 않습니다 (YYYY-MM-DD)")
        
        if "period_end" in update_data and update_data["period_end"]:
            try:
                update_data["period_end"] = datetime.strptime(update_data["period_end"], "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(status_code=400, detail="기간 종료일 형식이 올바르지 않습니다 (YYYY-MM-DD)")

        # 데이터 업데이트
        for field, value in update_data.items():
            setattr(charge_item, field, value)

        db.commit()
        db.refresh(charge_item)

        return {
            "message": "청구 항목이 성공적으로 수정되었습니다",
            "id": str(charge_item.id),
            "charge_type": charge_item.charge_type,
            "amount": float(charge_item.amount) if charge_item.amount else None
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"청구 항목 수정 중 오류가 발생했습니다: {str(e)}"
        )

@app.delete("/charge-items/{charge_item_id}")
def delete_charge_item(
    charge_item_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """청구 항목 삭제"""
    # 청구 항목 존재 여부 확인
    charge_item = db.query(ChargeItem).filter(ChargeItem.id == charge_item_id).first()
    if not charge_item:
        raise HTTPException(status_code=404, detail="청구 항목을 찾을 수 없습니다")

    try:
        db.delete(charge_item)
        db.commit()
        return {"message": "청구 항목이 성공적으로 삭제되었습니다"}

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"청구 항목 삭제 중 오류가 발생했습니다: {str(e)}"
        )

# 방 공과금 관련 API들
@app.post("/room-utilities", response_model=RoomUtilityResponse)
def create_room_utility(
    utility: RoomUtilityCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """방 공과금 등록"""
    # 방 존재 여부 확인
    room = db.query(Room).filter(Room.id == utility.room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="방을 찾을 수 없습니다")

    # 날짜 형식 검증
    try:
        period_start = datetime.strptime(utility.period_start, "%Y-%m-%d").date()
        period_end = datetime.strptime(utility.period_end, "%Y-%m-%d").date()
        charge_month = datetime.strptime(utility.charge_month, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="날짜 형식이 올바르지 않습니다 (YYYY-MM-DD)")

    # 기간 유효성 검사
    if period_end <= period_start:
        raise HTTPException(status_code=400, detail="검침 종료일은 시작일보다 늦어야 합니다")

    # 해당 방의 같은 유형, 같은 청구 월에 이미 등록되어 있는지 확인하고 덮어쓰기
    existing_utility = db.query(RoomUtility).filter(
        RoomUtility.room_id == utility.room_id,
        RoomUtility.utility_type == utility.utility_type,
        RoomUtility.charge_month == charge_month
    ).first()
    
    if existing_utility:
        # 기존 데이터 업데이트
        existing_utility.period_start = period_start
        existing_utility.period_end = period_end
        existing_utility.usage = utility.usage
        existing_utility.unit_price = utility.unit_price
        existing_utility.total_amount = utility.total_amount
        existing_utility.memo = utility.memo
        
        db.commit()
        db.refresh(existing_utility)
        
        # 응답 데이터 준비
        response_data = {
            "id": str(existing_utility.id),
            "room_id": str(existing_utility.room_id),
            "utility_type": existing_utility.utility_type,
            "period_start": existing_utility.period_start,
            "period_end": existing_utility.period_end,
            "usage": float(existing_utility.usage) if existing_utility.usage else None,
            "unit_price": float(existing_utility.unit_price) if existing_utility.unit_price else None,
            "total_amount": float(existing_utility.total_amount) if existing_utility.total_amount else None,
            "charge_month": existing_utility.charge_month,
            "memo": existing_utility.memo,
            "created_at": existing_utility.created_at,
            "room": {
                "id": str(room.id),
                "room_number": room.room_number,
                "building_name": room.building.name if room.building else None
            }
        }
        
        return response_data

    try:
        # 공과금 등록
        new_utility = RoomUtility(
            id=str(uuid.uuid4()),
            room_id=utility.room_id,
            utility_type=utility.utility_type,
            period_start=period_start,
            period_end=period_end,
            usage=utility.usage,
            unit_price=utility.unit_price,
            total_amount=utility.total_amount,
            charge_month=charge_month,
            memo=utility.memo
        )
        db.add(new_utility)
        db.commit()
        db.refresh(new_utility)

        # 응답 데이터 준비
        response_data = {
            "id": str(new_utility.id),
            "room_id": str(new_utility.room_id),
            "utility_type": new_utility.utility_type,
            "period_start": new_utility.period_start,
            "period_end": new_utility.period_end,
            "usage": float(new_utility.usage) if new_utility.usage else None,
            "unit_price": float(new_utility.unit_price) if new_utility.unit_price else None,
            "total_amount": float(new_utility.total_amount) if new_utility.total_amount else None,
            "charge_month": new_utility.charge_month,
            "memo": new_utility.memo,
            "created_at": new_utility.created_at,
            "room": {
                "id": str(room.id),
                "room_number": room.room_number,
                "building_name": room.building.name if room.building else None
            }
        }

        return response_data

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"공과금 등록 중 오류가 발생했습니다: {str(e)}"
        )

@app.get("/room-utilities")
def get_room_utilities(
    room_id: Optional[str] = Query(None, description="방 ID로 필터링"),
    utility_type: Optional[str] = Query(None, description="공과금 유형으로 필터링"),
    charge_month: Optional[str] = Query(None, description="청구 월로 필터링 (YYYY-MM)"),
    page: int = Query(1, description="페이지 번호", ge=1),
    size: int = Query(10, description="페이지당 항목 수", ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """방 공과금 목록 조회"""
    # 기본 쿼리 생성
    query = db.query(RoomUtility).options(
        joinedload(RoomUtility.room).joinedload(Room.building)
    )

    # 필터 조건 추가
    if room_id:
        query = query.filter(RoomUtility.room_id == room_id)
    if utility_type:
        query = query.filter(RoomUtility.utility_type == utility_type)
    if charge_month:
        try:
            # YYYY-MM 형식으로 받아서 해당 월의 첫날로 변환
            year, month = charge_month.split("-")
            start_date = datetime(int(year), int(month), 1).date()
            if int(month) == 12:
                end_date = datetime(int(year) + 1, 1, 1).date() - timedelta(days=1)
            else:
                end_date = datetime(int(year), int(month) + 1, 1).date() - timedelta(days=1)
            
            query = query.filter(
                RoomUtility.charge_month >= start_date,
                RoomUtility.charge_month <= end_date
            )
        except ValueError:
            raise HTTPException(status_code=400, detail="청구 월 형식이 올바르지 않습니다 (YYYY-MM)")

    # 전체 항목 수 계산
    total_count = query.count()

    # 페이지네이션 적용 (최신순)
    utilities = query.order_by(RoomUtility.charge_month.desc(), RoomUtility.created_at.desc()).offset((page - 1) * size).limit(size).all()

    # 전체 페이지 수 계산
    total_pages = (total_count + size - 1) // size

    # 응답 데이터 준비
    result = []
    for utility in utilities:
        utility_data = {
            "id": str(utility.id),
            "room_id": str(utility.room_id),
            "utility_type": utility.utility_type,
            "period_start": utility.period_start.strftime("%Y-%m-%d"),
            "period_end": utility.period_end.strftime("%Y-%m-%d"),
            "usage": float(utility.usage) if utility.usage else None,
            "unit_price": float(utility.unit_price) if utility.unit_price else None,
            "total_amount": float(utility.total_amount) if utility.total_amount else None,
            "charge_month": utility.charge_month.strftime("%Y-%m-%d"),
            "memo": utility.memo,
            "created_at": utility.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "room": {
                "id": str(utility.room.id),
                "room_number": utility.room.room_number,
                "building_name": utility.room.building.name if utility.room.building else None
            }
        }
        result.append(utility_data)

    return {
        "items": result,
        "total": total_count,
        "total_pages": total_pages,
        "current_page": page
    }

@app.get("/room-utilities/{utility_id}")
def get_room_utility(
    utility_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """특정 방 공과금 조회"""
    utility = db.query(RoomUtility).options(
        joinedload(RoomUtility.room).joinedload(Room.building)
    ).filter(RoomUtility.id == utility_id).first()
    
    if not utility:
        raise HTTPException(status_code=404, detail="공과금을 찾을 수 없습니다")

    return {
        "id": str(utility.id),
        "room_id": str(utility.room_id),
        "utility_type": utility.utility_type,
        "period_start": utility.period_start.strftime("%Y-%m-%d"),
        "period_end": utility.period_end.strftime("%Y-%m-%d"),
        "usage": float(utility.usage) if utility.usage else None,
        "unit_price": float(utility.unit_price) if utility.unit_price else None,
        "total_amount": float(utility.total_amount) if utility.total_amount else None,
        "charge_month": utility.charge_month.strftime("%Y-%m-%d"),
        "memo": utility.memo,
        "created_at": utility.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        "room": {
            "id": str(utility.room.id),
            "room_number": utility.room.room_number,
            "building_name": utility.room.building.name if utility.room.building else None
        }
    }

@app.put("/room-utilities/{utility_id}")
def update_room_utility(
    utility_id: str,
    utility_update: RoomUtilityUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """방 공과금 수정"""
    # 공과금 존재 여부 확인
    utility = db.query(RoomUtility).filter(RoomUtility.id == utility_id).first()
    if not utility:
        raise HTTPException(status_code=404, detail="공과금을 찾을 수 없습니다")

    try:
        # 업데이트할 데이터 준비
        update_data = utility_update.dict(exclude_unset=True)
        
        # 날짜 변환
        if "period_start" in update_data and update_data["period_start"]:
            try:
                update_data["period_start"] = datetime.strptime(update_data["period_start"], "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(status_code=400, detail="검침 시작일 형식이 올바르지 않습니다 (YYYY-MM-DD)")
        
        if "period_end" in update_data and update_data["period_end"]:
            try:
                update_data["period_end"] = datetime.strptime(update_data["period_end"], "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(status_code=400, detail="검침 종료일 형식이 올바르지 않습니다 (YYYY-MM-DD)")

        if "charge_month" in update_data and update_data["charge_month"]:
            try:
                update_data["charge_month"] = datetime.strptime(update_data["charge_month"], "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(status_code=400, detail="청구 월 형식이 올바르지 않습니다 (YYYY-MM-DD)")

        # 기간 유효성 검사
        period_start = update_data.get("period_start", utility.period_start)
        period_end = update_data.get("period_end", utility.period_end)
        if period_end <= period_start:
            raise HTTPException(status_code=400, detail="검침 종료일은 시작일보다 늦어야 합니다")

        # 데이터 업데이트
        for field, value in update_data.items():
            setattr(utility, field, value)

        db.commit()
        db.refresh(utility)

        return {
            "message": "공과금이 성공적으로 수정되었습니다",
            "id": str(utility.id),
            "utility_type": utility.utility_type,
            "total_amount": float(utility.total_amount) if utility.total_amount else None
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"공과금 수정 중 오류가 발생했습니다: {str(e)}"
        )

@app.delete("/room-utilities/{utility_id}")
def delete_room_utility(
    utility_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """방 공과금 삭제"""
    # 공과금 존재 여부 확인
    utility = db.query(RoomUtility).filter(RoomUtility.id == utility_id).first()
    if not utility:
        raise HTTPException(status_code=404, detail="공과금을 찾을 수 없습니다")

    try:
        db.delete(utility)
        db.commit()
        return {"message": "공과금이 성공적으로 삭제되었습니다"}

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"공과금 삭제 중 오류가 발생했습니다: {str(e)}"
        )

@app.get("/rooms/{room_id}/utilities")
def get_room_utilities_by_room(
    room_id: str,
    utility_type: Optional[str] = Query(None, description="공과금 유형으로 필터링"),
    page: int = Query(1, description="페이지 번호", ge=1),
    size: int = Query(10, description="페이지당 항목 수", ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """특정 방의 공과금 목록 조회"""
    # 방 존재 여부 확인
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="방을 찾을 수 없습니다")

    # 해당 방의 공과금 조회
    query = db.query(RoomUtility).filter(RoomUtility.room_id == room_id)

    # 공과금 유형 필터링
    if utility_type:
        query = query.filter(RoomUtility.utility_type == utility_type)

    # 전체 항목 수 계산
    total_count = query.count()

    # 페이지네이션 적용 (최신순)
    utilities = query.order_by(RoomUtility.charge_month.desc(), RoomUtility.created_at.desc()).offset((page - 1) * size).limit(size).all()

    # 전체 페이지 수 계산
    total_pages = (total_count + size - 1) // size

    # 응답 데이터 준비
    result = []
    for utility in utilities:
        utility_data = {
            "id": str(utility.id),
            "utility_type": utility.utility_type,
            "period_start": utility.period_start.strftime("%Y-%m-%d"),
            "period_end": utility.period_end.strftime("%Y-%m-%d"),
            "usage": float(utility.usage) if utility.usage else None,
            "unit_price": float(utility.unit_price) if utility.unit_price else None,
            "total_amount": float(utility.total_amount) if utility.total_amount else None,
            "charge_month": utility.charge_month.strftime("%Y-%m-%d"),
            "memo": utility.memo,
            "created_at": utility.created_at.strftime("%Y-%m-%d %H:%M:%S")
        }
        result.append(utility_data)

    return {
        "room": {
            "id": str(room.id),
            "room_number": room.room_number,
            "building_name": room.building.name if room.building else None
        },
        "items": result,
        "total": total_count,
        "total_pages": total_pages,
        "current_page": page
    }

@app.get("/room-utilities/{utility_id}/residents-during-period")
def get_residents_during_utility_period(
    utility_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """공과금 기간 동안의 거주자 정보 조회"""
    # 공과금 정보 조회
    utility = db.query(RoomUtility).filter(RoomUtility.id == utility_id).first()
    if not utility:
        raise HTTPException(status_code=404, detail="공과금을 찾을 수 없습니다")

    # 해당 방의 모든 거주 기록 조회
    residents = db.query(Resident).filter(
        Resident.room_id == utility.room_id
    ).all()

    # 공과금 기간 동안의 거주자 정보 계산
    residents_during_period = []
    total_days_in_period = (utility.period_end - utility.period_start).days + 1

    for resident in residents:
        # 거주 기간과 공과금 기간의 겹치는 부분 계산
        resident_start = resident.check_in_date
        resident_end = resident.check_out_date if resident.check_out_date else utility.period_end

        # 겹치는 기간 계산
        overlap_start = max(resident_start, utility.period_start)
        overlap_end = min(resident_end, utility.period_end)

        if overlap_start <= overlap_end:
            # 겹치는 일수 계산
            overlap_days = (overlap_end - overlap_start).days + 1
            
            # 비율 계산
            ratio = overlap_days / total_days_in_period if total_days_in_period > 0 else 0
            
            # 예상 부담금액 계산
            if utility.total_amount:
                estimated_amount = float(utility.total_amount) * ratio
            else:
                estimated_amount = 0

            resident_info = {
                "student_id": str(resident.student_id),
                "student_name": resident.student.name,
                "check_in_date": resident.check_in_date.strftime("%Y-%m-%d"),
                "check_out_date": resident.check_out_date.strftime("%Y-%m-%d") if resident.check_out_date else None,
                "is_active": resident.is_active,
                "overlap_start": overlap_start.strftime("%Y-%m-%d"),
                "overlap_end": overlap_end.strftime("%Y-%m-%d"),
                "overlap_days": overlap_days,
                "ratio": round(ratio * 100, 2),  # 퍼센트로 표시
                "estimated_amount": round(estimated_amount, 2)
            }
            residents_during_period.append(resident_info)

    # 일수 기준으로 정렬 (많은 일수부터)
    residents_during_period.sort(key=lambda x: x["overlap_days"], reverse=True)

    return {
        "utility": {
            "id": str(utility.id),
            "utility_type": utility.utility_type,
            "period_start": utility.period_start.strftime("%Y-%m-%d"),
            "period_end": utility.period_end.strftime("%Y-%m-%d"),
            "total_amount": float(utility.total_amount) if utility.total_amount else 0,
            "total_days": total_days_in_period
        },
        "residents": residents_during_period,
        "summary": {
            "total_residents": len(residents_during_period),
            "total_ratio": sum(r["ratio"] for r in residents_during_period),
            "total_estimated_amount": sum(r["estimated_amount"] for r in residents_during_period)
        }
    }

@app.post("/room-utilities/{utility_id}/calculate-allocation")
def calculate_utility_allocation(
    utility_id: str,
    allocation_method: str = Query("days_based", description="배분 방법 (days_based 또는 usage_based)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """공과금 배분 계산"""
    # 공과금 정보 조회
    utility = db.query(RoomUtility).filter(RoomUtility.id == utility_id).first()
    if not utility:
        raise HTTPException(status_code=404, detail="공과금을 찾을 수 없습니다")

    # 해당 방의 모든 거주 기록 조회
    residents = db.query(Resident).filter(
        Resident.room_id == utility.room_id
    ).all()

    # 공과금 기간 동안의 거주자 정보 계산
    allocations = []
    total_days_in_period = (utility.period_end - utility.period_start).days + 1
    total_overlap_days = 0

    # 1단계: 각 거주자의 겹치는 일수 계산
    resident_overlaps = []
    for resident in residents:
        resident_start = resident.check_in_date
        resident_end = resident.check_out_date if resident.check_out_date else utility.period_end

        overlap_start = max(resident_start, utility.period_start)
        overlap_end = min(resident_end, utility.period_end)

        if overlap_start <= overlap_end:
            overlap_days = (overlap_end - overlap_start).days + 1
            total_overlap_days += overlap_days
            
            resident_overlaps.append({
                "resident": resident,
                "overlap_days": overlap_days,
                "overlap_start": overlap_start,
                "overlap_end": overlap_end
            })

    # 2단계: 배분 계산
    if allocation_method == "days_based":
        # 일수 기준 배분
        for overlap_info in resident_overlaps:
            resident = overlap_info["resident"]
            overlap_days = overlap_info["overlap_days"]
            
            # 비율 계산
            ratio = overlap_days / total_overlap_days if total_overlap_days > 0 else 0
            
            # 부담금액 계산
            amount = float(utility.total_amount) * ratio if utility.total_amount else 0

            allocation = {
                "student_id": str(resident.student_id),
                "student_name": resident.student.name,
                "days_used": overlap_days,
                "ratio": round(ratio * 100, 2),
                "amount": round(amount, 2),
                "check_in_date": resident.check_in_date.strftime("%Y-%m-%d"),
                "check_out_date": resident.check_out_date.strftime("%Y-%m-%d") if resident.check_out_date else None,
                "is_active": resident.is_active
            }
            allocations.append(allocation)

    elif allocation_method == "usage_based":
        # 사용량 기준 배분 (현재는 일수 기준과 동일하게 처리)
        # 향후 실제 사용량 데이터가 있으면 여기서 계산 로직 수정
        for overlap_info in resident_overlaps:
            resident = overlap_info["resident"]
            overlap_days = overlap_info["overlap_days"]
            
            ratio = overlap_days / total_overlap_days if total_overlap_days > 0 else 0
            amount = float(utility.total_amount) * ratio if utility.total_amount else 0

            allocation = {
                "student_id": str(resident.student_id),
                "student_name": resident.student.name,
                "days_used": overlap_days,
                "ratio": round(ratio * 100, 2),
                "amount": round(amount, 2),
                "check_in_date": resident.check_in_date.strftime("%Y-%m-%d"),
                "check_out_date": resident.check_out_date.strftime("%Y-%m-%d") if resident.check_out_date else None,
                "is_active": resident.is_active
            }
            allocations.append(allocation)

    else:
        raise HTTPException(status_code=400, detail="지원하지 않는 배분 방법입니다")

    # 일수 기준으로 정렬
    allocations.sort(key=lambda x: x["days_used"], reverse=True)

    return {
        "utility": {
            "id": str(utility.id),
            "utility_type": utility.utility_type,
            "period_start": utility.period_start.strftime("%Y-%m-%d"),
            "period_end": utility.period_end.strftime("%Y-%m-%d"),
            "total_amount": float(utility.total_amount) if utility.total_amount else 0,
            "total_days": total_days_in_period
        },
        "allocation_method": allocation_method,
        "allocations": allocations,
        "summary": {
            "total_residents": len(allocations),
            "total_days": total_overlap_days,
            "total_amount": sum(a["amount"] for a in allocations),
            "total_ratio": sum(a["ratio"] for a in allocations)
        }
    }

@app.get("/rooms/{room_id}/utilities/monthly-allocation/{year}/{month}")
def get_monthly_utility_allocation(
    room_id: str,
    year: int,
    month: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """특정 방의 월별 공과금 배분 계산"""
    # 방 존재 여부 확인
    room = db.query(Room).options(
        joinedload(Room.building)
    ).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="방을 찾을 수 없습니다")

    # 월 유효성 검사
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="월은 1-12 사이의 값이어야 합니다")

    # 해당 월의 시작일과 종료일 계산
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end_date = date(year, month + 1, 1) - timedelta(days=1)

    # 해당 월의 모든 공과금 조회
    utilities = db.query(RoomUtility).filter(
        RoomUtility.room_id == room_id,
        RoomUtility.charge_month >= start_date,
        RoomUtility.charge_month <= end_date
    ).order_by(RoomUtility.utility_type, RoomUtility.period_start).all()

    if not utilities:
        return {
            "room": {
                "id": str(room.id),
                "room_number": room.room_number,
                "building_name": room.building.name if room.building else None
            },
            "year": year,
            "month": month,
            "utilities": [],
            "summary": {
                "total_utilities": 0,
                "total_amount": 0,
                "total_residents": 0
            }
        }

    # 해당 방의 모든 거주 기록 조회
    residents = db.query(Resident).options(
        joinedload(Resident.student)
    ).filter(Resident.room_id == room_id).all()

    # 각 공과금별 배분 계산
    utility_allocations = []
    total_monthly_amount = 0

    for utility in utilities:
        # 공과금 기간 동안의 거주자 정보 계산
        allocations = []
        total_days_in_period = (utility.period_end - utility.period_start).days + 1
        total_overlap_days = 0

        # 각 거주자의 겹치는 일수 계산
        resident_overlaps = []
        for resident in residents:
            resident_start = resident.check_in_date
            resident_end = resident.check_out_date if resident.check_out_date else utility.period_end

            overlap_start = max(resident_start, utility.period_start)
            overlap_end = min(resident_end, utility.period_end)

            if overlap_start <= overlap_end:
                overlap_days = (overlap_end - overlap_start).days + 1
                total_overlap_days += overlap_days
                
                resident_overlaps.append({
                    "resident": resident,
                    "overlap_days": overlap_days,
                    "overlap_start": overlap_start,
                    "overlap_end": overlap_end
                })

        # 배분 계산 (일수 기준)
        for overlap_info in resident_overlaps:
            resident = overlap_info["resident"]
            overlap_days = overlap_info["overlap_days"]
            
            # 비율 계산
            ratio = overlap_days / total_overlap_days if total_overlap_days > 0 else 0
            
            # 부담금액 계산
            amount = float(utility.total_amount) * ratio if utility.total_amount else 0

            allocation = {
                "student_id": str(resident.student_id),
                "student_name": resident.student.name,
                "days_used": overlap_days,
                "ratio": round(ratio * 100, 2),
                "amount": round(amount, 2),
                "check_in_date": resident.check_in_date.strftime("%Y-%m-%d"),
                "check_out_date": resident.check_out_date.strftime("%Y-%m-%d") if resident.check_out_date else None,
                "is_active": resident.is_active,
                "overlap_start": overlap_info["overlap_start"].strftime("%Y-%m-%d"),
                "overlap_end": overlap_info["overlap_end"].strftime("%Y-%m-%d")
            }
            allocations.append(allocation)

        # 일수 기준으로 정렬
        allocations.sort(key=lambda x: x["days_used"], reverse=True)

        utility_allocation = {
            "utility_id": str(utility.id),
            "utility_type": utility.utility_type,
            "period_start": utility.period_start.strftime("%Y-%m-%d"),
            "period_end": utility.period_end.strftime("%Y-%m-%d"),
            "total_amount": float(utility.total_amount) if utility.total_amount else 0,
            "total_days": total_days_in_period,
            "charge_month": utility.charge_month.strftime("%Y-%m-%d"),
            "memo": utility.memo,
            "allocations": allocations,
            "summary": {
                "total_residents": len(allocations),
                "total_days": total_overlap_days,
                "total_amount": sum(a["amount"] for a in allocations),
                "total_ratio": sum(a["ratio"] for a in allocations)
            }
        }
        
        utility_allocations.append(utility_allocation)
        total_monthly_amount += float(utility.total_amount) if utility.total_amount else 0

    # 전체 월 요약
    all_students = set()
    for utility in utility_allocations:
        for allocation in utility["allocations"]:
            all_students.add(allocation["student_id"])

    return {
        "room": {
            "id": str(room.id),
            "room_number": room.room_number,
            "building_name": room.building.name if room.building else None
        },
        "year": year,
        "month": month,
        "utilities": utility_allocations,
        "summary": {
            "total_utilities": len(utility_allocations),
            "total_amount": total_monthly_amount,
            "total_residents": len(all_students),
            "utility_types": list(set(u["utility_type"] for u in utility_allocations))
        }
    }

@app.get("/rooms/{room_id}/utilities/monthly-summary/{year}/{month}")
def get_monthly_utility_summary(
    room_id: str,
    year: int,
    month: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """특정 방의 월별 공과금 요약 정보"""
    # 방 존재 여부 확인
    room = db.query(Room).options(
        joinedload(Room.building)
    ).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="방을 찾을 수 없습니다")

    # 월 유효성 검사
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="월은 1-12 사이의 값이어야 합니다")

    # 해당 월의 시작일과 종료일 계산
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end_date = date(year, month + 1, 1) - timedelta(days=1)

    # 해당 월의 모든 공과금 조회
    utilities = db.query(RoomUtility).filter(
        RoomUtility.room_id == room_id,
        RoomUtility.charge_month >= start_date,
        RoomUtility.charge_month <= end_date
    ).all()

    # 해당 방의 모든 거주 기록 조회
    residents = db.query(Resident).options(
        joinedload(Resident.student)
    ).filter(Resident.room_id == room_id).all()

    # 공과금별 요약 정보
    utility_summaries = []
    total_monthly_amount = 0

    for utility in utilities:
        # 공과금 기간 동안의 거주자 수와 일수 계산
        total_days_in_period = (utility.period_end - utility.period_start).days + 1
        total_overlap_days = 0
        resident_count = 0

        for resident in residents:
            resident_start = resident.check_in_date
            resident_end = resident.check_out_date if resident.check_out_date else utility.period_end

            overlap_start = max(resident_start, utility.period_start)
            overlap_end = min(resident_end, utility.period_end)

            if overlap_start <= overlap_end:
                overlap_days = (overlap_end - overlap_start).days + 1
                total_overlap_days += overlap_days
                resident_count += 1

        # 평균 일수 계산
        avg_days_per_resident = total_overlap_days / resident_count if resident_count > 0 else 0

        utility_summary = {
            "utility_id": str(utility.id),
            "utility_type": utility.utility_type,
            "period_start": utility.period_start.strftime("%Y-%m-%d"),
            "period_end": utility.period_end.strftime("%Y-%m-%d"),
            "total_amount": float(utility.total_amount) if utility.total_amount else 0,
            "total_days": total_days_in_period,
            "resident_count": resident_count,
            "total_resident_days": total_overlap_days,
            "avg_days_per_resident": round(avg_days_per_resident, 1),
            "amount_per_day": round(float(utility.total_amount) / total_overlap_days, 2) if total_overlap_days > 0 else 0,
            "amount_per_resident": round(float(utility.total_amount) / resident_count, 2) if resident_count > 0 else 0,
            "memo": utility.memo
        }
        
        utility_summaries.append(utility_summary)
        total_monthly_amount += float(utility.total_amount) if utility.total_amount else 0

    return {
        "room": {
            "id": str(room.id),
            "room_number": room.room_number,
            "building_name": room.building.name if room.building else None
        },
        "year": year,
        "month": month,
        "utilities": utility_summaries,
        "summary": {
            "total_utilities": len(utility_summaries),
            "total_amount": total_monthly_amount,
            "utility_types": list(set(u["utility_type"] for u in utility_summaries))
        }
    }

@app.get("/rooms/{room_id}/utilities/monthly-by-students/{year}/{month}")
def get_student_monthly_utility_allocation(
    room_id: str,
    student_id: str,
    year: int,
    month: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """특정 방, 특정 학생, 특정 월의 공과금 분배 정보 반환 (전달 기준)"""
    # 1. 방/학생 존재 체크
    room = db.query(Room).options(joinedload(Room.building)).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="방을 찾을 수 없습니다")
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="학생을 찾을 수 없습니다")

    # 2. 전달 기준으로 시작/종료일 계산 (예: 7월 조회 시 6월 1일~6월 30일)
    if month == 1:
        prev_year = year - 1
        prev_month = 12
    else:
        prev_year = year
        prev_month = month - 1
    
    start_date = date(prev_year, prev_month, 1)
    if prev_month == 12:
        end_date = date(prev_year + 1, 1, 1) - timedelta(days=1)
    else:
        end_date = date(prev_year, prev_month + 1, 1) - timedelta(days=1)

    # 3. 전달의 모든 공과금 조회

    target_charge_month = date(year, month, 1)
    utilities = db.query(RoomUtility).filter(
        RoomUtility.room_id == room_id,
        RoomUtility.charge_month == target_charge_month
    ).all()

    if not utilities:
        return {
            "student_id": student_id,
            "student_name": student.name,
            "utilities": [],
            "total_amount": 0,
            "detail": f"{year}년 {month}월 조회 시 전달({prev_year}년 {prev_month}월)의 공과금 내역이 없습니다."
        }

    # 4. 학생의 해당 방에 대한 거주 이력 (입주~퇴실)
    resident = db.query(Resident).filter(
        Resident.room_id == room_id,
        Resident.student_id == student_id,
        Resident.check_in_date <= end_date,
        (Resident.check_out_date.is_(None) | (Resident.check_out_date >= start_date))
    ).first()
    print(f"DEBUG: 날짜!!! - 시작: {end_date}, 종료: {start_date}")
    if not resident:
        return {
            "student_id": student_id,
            "student_name": student.name,
            "utilities": [],
            "total_amount": 0,
            "detail": f"{year}년 {month}월 조회 시 전달({prev_year}년 {prev_month}월)에 거주 이력이 없습니다."
        }

    # 5. 각 공과금별 배분 계산
    utilities_result = []
    total_amount = 0

    for utility in utilities:
        print(f"DEBUG: 공과금 처리 시작 - ID: {utility.id}, 유형: {utility.utility_type}, 총액: {utility.total_amount}")
        print(f"DEBUG: 공과금 기간 - 시작: {utility.period_start}, 종료: {utility.period_end}")
        
        # 해당 유틸리티 기간 내 방 거주자 전체 쿼리
        all_residents = db.query(Resident).filter(
            Resident.room_id == room_id,
            Resident.check_in_date <= utility.period_end,
            (Resident.check_out_date.is_(None) | (Resident.check_out_date >= utility.period_start))
        ).all()

        print(f"DEBUG: 해당 공과금 기간 내 거주자 수: {len(all_residents)}")

        # 이 학생이 실제로 해당 공과금 기간 내에 며칠 있었는지 계산
        stu_in = max(resident.check_in_date, utility.period_start)
        stu_out = min(resident.check_out_date or utility.period_end, utility.period_end)
        days = (stu_out - stu_in).days + 1 if stu_in <= stu_out else 0

        print(f"DEBUG: 학생 {student.name} - 거주기간: {resident.check_in_date}~{resident.check_out_date}")
        print(f"DEBUG: 학생 {student.name} - 겹치는 기간: {stu_in}~{stu_out}, 겹치는 일수: {days}")

        # 전체 person-day 계산
        total_person_days = 0
        for r in all_residents:
            overlap_in = max(r.check_in_date, utility.period_start)
            overlap_out = min(r.check_out_date or utility.period_end, utility.period_end)
            overlap_days = (overlap_out - overlap_in).days + 1 if overlap_in <= overlap_out else 0
            total_person_days += overlap_days
            
            print(f"DEBUG: 거주자 {r.student.name if r.student else 'Unknown'} - 겹치는 일수: {overlap_days}")

        print(f"DEBUG: 전체 person-days: {total_person_days}")

        # 1일당 요금 계산 및 본인 부담액 계산
        per_day = float(utility.total_amount) / total_person_days if total_person_days > 0 else 0
        my_amount = round(per_day * days, 2)

        print(f"DEBUG: 1일당 요금: {per_day:.2f}, 학생 부담액: {my_amount:.2f}")

        utilities_result.append({
            "utility_id": str(utility.id),
            "utility_type": utility.utility_type,
            "period_start": utility.period_start.strftime("%Y-%m-%d"),
            "period_end": utility.period_end.strftime("%Y-%m-%d"),
            "charge_month": utility.charge_month.strftime("%Y-%m-%d"),
            "my_days": days,
            "total_person_days": total_person_days,
            "amount_per_day": round(per_day, 2),
            "my_amount": my_amount,
            "memo": utility.memo
        })
        total_amount += my_amount

    print(f"DEBUG: 총 부담액: {total_amount:.2f}")

    return {
        "student_id": student_id,
        "student_name": student.name,
        "query_month": f"{year}년 {month}월",
        "billing_period": f"{prev_year}년 {prev_month}월",
        "utilities": utilities_result,
        "total_amount": round(total_amount, 2)
    }
