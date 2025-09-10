from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from typing import Optional, List
from database import SessionLocal
from models import Building, Room, Student, Resident, BillingMonthlyItem, RoomUtility, BuildingCategoriesRent, Company
from schemas import BuildingResponse, BuildingUpdate, BuildingCreate
from datetime import datetime, date, timedelta
from database_log import create_database_log
from utils.dependencies import get_current_user
from fastapi.responses import HTMLResponse, FileResponse, Response
from fastapi.templating import Jinja2Templates
from weasyprint import HTML, CSS
from weasyprint.text.fonts import FontConfiguration
from urllib.parse import quote
import base64
import os

router = APIRouter(prefix="/buildings", tags=["건물 관리"])

templates = Jinja2Templates(directory="templates")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/")
def get_buildings(
    name: Optional[str] = Query(None, description="빌딩 이름으로 검색"),
    address: Optional[str] = Query(None, description="주소로 검색"),
    resident_type: Optional[str] = Query(None, description="거주자 타입으로 검색"),
    page: int = Query(1, description="페이지 번호", ge=1),
    size: int = Query(10, description="페이지당 항목 수", ge=1, le=100),
    db: Session = Depends(get_db)
):
    # 기본 쿼리 생성
    query = db.query(Building)
        
    # 필터 조건 추가
    if name:
        query = query.filter(Building.name.ilike(f"%{name}%"))
    if address:
        query = query.filter(Building.address.ilike(f"%{address}%"))
    if resident_type:
        query = query.filter(Building.resident_type == resident_type)
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
@router.post("/", response_model=BuildingResponse)
def create_building(
    building: BuildingCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    new_building = Building(
        name=building.name,
        address=building.address,
        building_type=building.building_type,
        total_rooms=building.total_rooms,
        note=building.note,
        resident_type=building.resident_type
    )
    db.add(new_building)
    
    try:
        db.commit()
        db.refresh(new_building)
        
        # 로그 생성
        create_database_log(
            db=db,
            table_name="buildings",
            record_id=str(new_building.id),
            action="CREATE",
            user_id=current_user["id"] if current_user else None,
            new_values={
                "name": new_building.name,
                "address": new_building.address,
                "building_type": new_building.building_type,
                "total_rooms": new_building.total_rooms,
                "note": new_building.note
            },
            note="ビル新規登録"
        )
        
        return new_building
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"빌딩 생성 중 오류가 발생했습니다: {str(e)}"
        )

@router.get("/options")
def get_building_options(db: Session = Depends(get_db)):
    """건물 옵션 목록 (드롭다운용)"""
    try:
        buildings = db.query(Building).order_by(Building.name.asc()).all()
        
        options = [
            {
                "value": str(building.id),
                "label": building.name
            } for building in buildings
        ]
        
        return {"options": options}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"건물 옵션 조회 중 오류가 발생했습니다: {str(e)}")

@router.get("/{building_id}/empty-rooms")
def get_building_empty_rooms(
    building_id: str,
    db: Session = Depends(get_db)
):
    """특정 빌딩의 빈 호실 목록을 조회"""
    try:
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
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"빈 방 조회 중 오류가 발생했습니다: {str(e)}")

@router.get("/{building_id}")
def get_building(
    building_id: str,
    db: Session = Depends(get_db),
):
    building = db.query(Building).filter(Building.id == building_id).first()
    if not building:
        raise HTTPException(status_code=404, detail="빌딩을 찾을 수 없습니다")
    return building

@router.get("/{building_id}/rooms")
def get_rooms_by_building(
    building_id: str,
    room_number: Optional[str] = Query(None, description="방 번호로 검색"),
    is_available: Optional[bool] = Query(None, description="사용 가능 여부로 필터링"),
    page: int = Query(1, description="페이지 번호", ge=1),
    size: int = Query(100, description="페이지당 항목 수", ge=1, le=100),
    db: Session = Depends(get_db)
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

    # room_number 기준으로 정렬 (숫자 정렬을 위해 CAST 사용)
    query = query.order_by(Room.room_number)

    # 전체 항목 수 계산
    total_count = query.count()

    # 페이지네이션 적용
    rooms = query.offset((page - 1) * size).limit(size).all()

    # 전체 페이지 수 계산
    total_pages = (total_count + size - 1) // size

    # 방 정보와 함께 BuildingCategoriesRent 정보 포함
    room_data = []
    for room in rooms:
        room_dict = {
          "id": str(room.id),
          "building_id": str(room.building_id),
          "room_number": room.room_number,
          "rent": room.rent,
          "maintenance": room.maintenance,
          "service": room.service,
          "floor": room.floor,
          "capacity": room.capacity,
          "is_available": room.is_available,
          "note": room.note,
          "security_deposit": room.security_deposit,
          "monthly_rent": None
        }
        
        # 해당 빌딩의 BuildingCategoriesRent 정보 조회
        building_status_rent = db.query(BuildingCategoriesRent).filter(
            BuildingCategoriesRent.building_id == room.building_id,
            BuildingCategoriesRent.categories_id == 1
        ).first()
      
        if building_status_rent:
            room_dict["monthly_rent"] = building_status_rent.monthly_rent
        
        room_data.append(room_dict)

    return {
        "items": room_data,
        "total": total_count,
        "total_pages": total_pages,
        "current_page": page
    }

@router.put("/{building_id}", response_model=BuildingResponse)
def update_building(
    building_id: str,
    building_update: BuildingUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    # 빌딩 존재 여부 확인
    building = db.query(Building).filter(Building.id == building_id).first()
    if not building:
        raise HTTPException(status_code=404, detail="빌딩을 찾을 수 없습니다")

    # 기존 값 저장 (로그용)
    old_values = {
        "name": building.name,
        "address": building.address,
        "building_type": building.building_type,
        "total_rooms": building.total_rooms,
        "note": building.note
    }
    
    # 빌딩 정보 업데이트
    update_data = building_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(building, field, value)

    try:
        db.commit()
        db.refresh(building)
        
        # 로그 생성
        create_database_log(
            db=db,
            table_name="buildings",
            record_id=str(building.id),
            action="UPDATE",
            user_id=current_user["id"] if current_user else None,
            old_values=old_values,
            new_values={
            "name": building.name,
            "address": building.address,
                "building_type": building.building_type,
                "total_rooms": building.total_rooms,
                "note": building.note
            },
            changed_fields=list(update_data.keys()),
            note="ビル情報更新"
        )
        
        return building
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"빌딩 정보 수정 중 오류가 발생했습니다: {str(e)}"
        )

@router.get("/monthly-invoice-preview/students/company/{year}/{month}")
def get_monthly_invoice_preview_by_students_company(
    year: int,
    month: int,
    company_id: Optional[str] = Query(None, description="특정 회사로 필터링"),
    db: Session = Depends(get_db)
):
    """해당 년도 월의 모든 학생별 청구서 미리보기 데이터 조회 (PDF 다운로드 전 프론트 표시용)"""
    print(f"[DEBUG] get_monthly_invoice_preview 시작 - year: {year}, month: {month}, company_id: {company_id}")
    
    # 월 유효성 검사
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="월은 1-12 사이의 값이어야 합니다")

    # 전월의 시작/종료일 계산 (7월 데이터 요청 시 6월 거주 기록 조회)
    if month == 1:
        prev_year = year - 1
        prev_month = 12
    else:
        prev_year = year
        prev_month = month - 1
    
    # 전월의 시작/종료일 계산
    if prev_month == 12:
        prev_month_end_date = date(prev_year + 1, 1, 1) - timedelta(days=1)
    else:
        prev_month_end_date = date(prev_year, prev_month + 1, 1) - timedelta(days=1)
    
    prev_month_start_date = date(prev_year, prev_month, 1)
    total_days_in_month = (prev_month_end_date - prev_month_start_date).days + 1

    # 특정 조건 학생들을 위한 현재 월 데이터 계산 (7월 요청 시 7월 데이터)
    current_month_start_date = date(year, month, 1)
    if month == 12:
        current_month_end_date = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        current_month_end_date = date(year, month + 1, 1) - timedelta(days=1)
    current_total_days_in_month = (current_month_end_date - current_month_start_date).days + 1

    # 1. 회사별 학생 리스트 조회
    print(f"[DEBUG] 회사별 학생 리스트 조회 시작")
    if company_id:
        # 특정 회사 학생들 조회
        students_query = db.query(Student).filter(Student.company_id == company_id)
    else:
        # 모든 학생 조회
        students_query = db.query(Student)
    
    students = students_query.all()
    print(f"[DEBUG] 조회된 학생 수: {len(students)}")

    # 2. 각 학생별로 해당 월에 거주하는지 확인하고 데이터 수집
    students_data = []
    total_electricity_amount = 0
    total_water_amount = 0
    total_gas_amount = 0
    total_rent_amount = 0
    total_management_fee = 0
    total_wifi_amount = 0

    for student in students:
        print(f"[DEBUG] 학생 처리 중: {student.name}")
        
        # 특정 조건 확인: student_type이 general이고 grade_id가 특정 값인 경우
        is_special_case_1 = (
            student.student_type == "GENERAL" and 
            str(student.grade_id) == "74494b21-499f-48d2-96f4-5df6cc1403e6"
        )
        
        is_special_case_2 = (
            student.student_type == "GENERAL" and 
            str(student.grade_id) == "b6e1b114-cc6c-4c12-ad6d-b281f9a1cbce"
        )
        
        is_special_case = is_special_case_1 or is_special_case_2
        
        print(f"[DEBUG] {student.student_type} - is_special_case_1: {student.grade_id} is_special_case_1 {is_special_case_1}")
        print(f"[DEBUG] {student.student_type} - is_special_case_2: {student.grade_id} is_special_case_2 {is_special_case_2}")
        
        # 조건에 따라 사용할 날짜 범위 결정
        if is_special_case_1:
            # 특별 조건 1: 현재 월 데이터 사용 (7월 요청 시 7월 데이터)
            target_start_date = current_month_start_date
            target_end_date = current_month_end_date
            target_total_days = current_total_days_in_month
            print(f"[DEBUG] {student.name} - 특별 조건 1 적용: {year}년 {month}월 데이터 사용")
        elif is_special_case_2:
            # 특별 조건 2: 다음 월 데이터 사용 (7월 요청 시 8월 데이터)
            if month == 12:
                next_year = year + 1
                next_month = 1
            else:
                next_year = year
                next_month = month + 1
            
            target_start_date = date(next_year, next_month, 1)
            if next_month == 12:
                target_end_date = date(next_year + 1, 1, 1) - timedelta(days=1)
            else:
                target_end_date = date(next_year, next_month + 1, 1) - timedelta(days=1)
            target_total_days = (target_end_date - target_start_date).days + 1
            print(f"[DEBUG] {student.name} - 특별 조건 2 적용: {next_year}년 {next_month}월 데이터 사용")
        else:
            # 일반 조건: 전월 데이터 사용 (7월 요청 시 6월 데이터)
            target_start_date = prev_month_start_date
            target_end_date = prev_month_end_date
            target_total_days = total_days_in_month
            print(f"[DEBUG] {student.name} - 일반 조건: {prev_year}년 {prev_month}월 데이터 사용")
        
        # 해당 학생의 거주 정보 조회
        if is_special_case:
            # 특별 조건: 7월 공과금 계산을 위해 6월에 퇴직한 학생들도 포함
            resident_records = db.query(Resident).options(
                joinedload(Resident.room).joinedload(Room.building)
            ).filter(
                Resident.resident_id == student.id,
                Resident.check_in_date <= current_month_end_date
                # check_out_date 조건 제거 - 6월에 퇴직해도 7월 공과금 계산에 포함
            ).all()
        else:
            # 일반 조건: 전월 거주 기록 조회
            resident_records = db.query(Resident).options(
                joinedload(Resident.room).joinedload(Room.building)
            ).filter(
                Resident.resident_id == student.id,
                Resident.check_in_date <= target_end_date,
                (Resident.check_out_date.is_(None) | (Resident.check_out_date >= target_start_date))
            ).all()

        if not resident_records:
            print(f"[DEBUG] {student.name} - 해당 월에 거주 정보 없음")
            continue

        # 모든 거주 기록에 대해 계산
        total_rent_amount_for_student = 0
        total_management_fee_for_student = 0
        total_wifi_amount_for_student = 0
        total_electricity_amount_for_student = 0
        total_water_amount_for_student = 0
        total_gas_amount_for_student = 0
        all_utilities_data = []
        has_utilities_for_student = False

        print(f"[DEBUG] {student.name} - 거주 기록 수: {len(resident_records)}")
        
        for resident_info in resident_records:
            # 거주한 일수 계산
            # 실제 입주일과 대상 월 시작일 중 늦은 날짜를 사용
            if resident_info.check_in_date >= target_start_date:
                check_in = resident_info.check_in_date
            else:
                check_in = target_start_date
            
            # 학생의 퇴직일(resignation_date)과 방 퇴실일(check_out_date) 중 이른 날짜 사용
            effective_check_out_date = None
            
            if student.resignation_date is not None and resident_info.check_out_date is not None:
                # 둘 다 있으면 이른 날짜 사용
                effective_check_out_date = min(student.resignation_date, resident_info.check_out_date)
            elif student.resignation_date is not None:
                # 퇴직일만 있으면 퇴직일 사용
                effective_check_out_date = student.resignation_date
            elif resident_info.check_out_date is not None:
                # 방 퇴실일만 있으면 방 퇴실일 사용
                effective_check_out_date = resident_info.check_out_date
            
            if effective_check_out_date is None:
                check_out = target_end_date
            else:
                # 실제 퇴실일과 대상 월 종료일 중 이른 날짜를 사용
                if effective_check_out_date <= target_end_date:
                    check_out = effective_check_out_date
                else:
                    check_out = target_end_date

            # 해당 월에 거주한 일수 계산
            if check_in <= check_out:
                days_in_month = (check_out - check_in).days + 1
            else:
                days_in_month = 0

            if days_in_month <= 0:
                if is_special_case:
                    # 특별 조건: 6월에 퇴사해도 7월 공과금 계산을 위해 계속 진행
                    print(f"[DEBUG] {student.name} - 특별 조건: 6월에 퇴사했지만 7월 공과금 계산 계속")
                    days_in_month = 0  # 야칭/와이파이는 0이지만 공과금은 계산
                else:
                    print(f"[DEBUG] {student.name} - 해당 월에 거주하지 않음")
                    continue

            print(f"[DEBUG] {student.name} - check_in: {check_in}, check_out: {check_out}, days_in_month: {days_in_month}")
            print(f"[DEBUG] {student.name} - target_start_date: {target_start_date}, target_end_date: {target_end_date}")

            # 야칭 계산
            print(f"[DEBUG] {student.name} - check_in_date: {resident_info.check_in_date}, resignation_date: {student.resignation_date}")
            
            # 퇴직일이 있는 경우와 없는 경우를 구분하여 계산
            if student.resignation_date is not None:
                # 퇴직일이 있는 경우
                check_in_month = resident_info.check_in_date.month
                check_in_year = resident_info.check_in_date.year
                resignation_month = student.resignation_date.month
                resignation_year = student.resignation_date.year
                
                # check_in_date와 resignation_date가 같은 달이 아닌 경우
                if (check_in_year != resignation_year) or (check_in_month != resignation_month):
                    # 퇴직일 달 기준으로 계산
                    if days_in_month >= 30:
                        # 30일 이상이면 무조건 고정 금액
                        rent_amount = 25000
                        management_fee = 5000
                        print(f"[DEBUG] {student.name} - 퇴직일 달 기준, 30일 이상: 월세 25,000엔, 관리비 5,000엔")
                    else:
                        # 29일 이하면 일별 계산 후 관리비 분리
                        total_amount = min(days_in_month * 1000, 30000)
                        management_fee = min(days_in_month * 166, 5000)
                        rent_amount = total_amount - management_fee
                        print(f"[DEBUG] {student.name} - 퇴직일 달 기준, 29일 이하: {days_in_month}일 × 1,000 = {total_amount}엔, 관리비: {management_fee}엔, 월세: {rent_amount}엔")
                else:
                    # 같은 달인 경우 - 퇴직일이 있으면 항상 일별 계산
                    if days_in_month >= 30:
                        # 30일 이상이면 무조건 고정 금액
                        rent_amount = 25000
                        management_fee = 5000
                        print(f"[DEBUG] {student.name} - 같은 달, 퇴직일 있음, 30일 이상: 월세 25,000엔, 관리비 5,000엔")
                    else:
                        # 29일 이하면 일별 계산 후 관리비 분리
                        total_amount = min(days_in_month * 1000, 30000)
                        management_fee = min(days_in_month * 166, 5000)
                        rent_amount = total_amount - management_fee
                        print(f"[DEBUG] {student.name} - 같은 달, 퇴직일 있음, 29일 이하: {days_in_month}일 × 1,000 = {total_amount}엔, 관리비: {management_fee}엔, 월세: {rent_amount}엔")
            else:
                # 퇴직일이 없는 경우
                if days_in_month >= 30:
                    # 30일 이상이면 무조건 고정 금액
                    rent_amount = 25000
                    management_fee = 5000
                    print(f"[DEBUG] {student.name} - 퇴직일 없음, 30일 이상: 월세 25,000엔, 관리비 5,000엔")
                else:
                    # 29일 이하면 일별 계산 후 관리비 분리
                    total_amount = min(days_in_month * 1000, 30000)
                    management_fee = min(days_in_month * 166, 5000)
                    rent_amount = total_amount - management_fee
                    print(f"[DEBUG] {student.name} - 퇴직일 없음, 29일 이하: {days_in_month}일 × 1,000 = {total_amount}엔, 관리비: {management_fee}엔, 월세: {rent_amount}엔")

            # 와이파이 비용 계산
            if student.resignation_date is not None:
                # 퇴직일이 있는 경우
                check_in_month = resident_info.check_in_date.month
                check_in_year = resident_info.check_in_date.year
                resignation_month = student.resignation_date.month
                resignation_year = student.resignation_date.year
                
                # check_in_date와 resignation_date가 같은 달이 아닌 경우
                if (check_in_year != resignation_year) or (check_in_month != resignation_month):
                    # 퇴직일 달 기준으로 계산
                    wifi_amount = min(int(days_in_month * (700 / 30)), 700)
                    print(f"[DEBUG] {student.name} - 와이파이 퇴직일 달 기준 계산: {days_in_month}일 × (700/30) = {wifi_amount}엔 (최대 700엔)")
                else:
                    # 같은 달인 경우 - 퇴직일이 있으면 항상 일별 계산
                    wifi_amount = min(int(days_in_month * (700 / 30)), 700)
                    print(f"[DEBUG] {student.name} - 와이파이 같은 달, 퇴직일 있음: {days_in_month}일 × (700/30) = {wifi_amount}엔 (최대 700엔)")
            else:
                # 퇴직일이 없는 경우
                # 입주일이 1일이고 해당 월 전체를 거주하는 경우만 700엔 고정
                if resident_info.check_in_date.day == 1 and days_in_month >= 30:
                    wifi_amount = 700
                    print(f"[DEBUG] {student.name} - 와이파이 퇴직일 없음, 1일 입주, 전체 월 거주: 700엔")
                else:
                    # 그 외의 경우는 일별 계산
                    wifi_amount = min(int(days_in_month * (700 / 30)), 700)
                    print(f"[DEBUG] {student.name} - 와이파이 퇴직일 없음, 일별 계산: {days_in_month}일 × (700/30) = {wifi_amount}엔 (최대 700엔)")

            # 3. 공과금 조회 및 계산
            utilities_data = []
            room_electricity_amount = 0
            room_water_amount = 0
            room_gas_amount = 0
            
            print(f"[DEBUG] {student.name} - 현재 거주 기록 계산 완료: rent={rent_amount}, wifi={wifi_amount}")
            has_utilities = False

            print(f"[DEBUG] {student.name} - resident_info.room 체크: {resident_info.room is not None}")
            if resident_info.room:
                # 공과금 조회
                if is_special_case_2:
                    # 특별 조건 2: 다음 월 공과금 사용 (7월 요청 시 8월 공과금)
                    if month == 12:
                        next_year = year + 1
                        next_month = 1
                    else:
                        next_year = year
                        next_month = month + 1
                    charge_month = date(next_year, next_month, 1)
                    print(f"[DEBUG] {student.name} - 특별 조건 2: {next_year}년 {next_month}월 공과금 조회")
                else:
                    # 일반 조건 및 특별 조건 1: 현재 월 공과금 사용 (7월 요청 시 7월 공과금)
                    charge_month = date(year, month, 1)
                    print(f"[DEBUG] {student.name} - 일반/특별 조건 1: {year}년 {month}월 공과금 조회")
                
                utilities = db.query(RoomUtility).filter(
                    RoomUtility.room_id == resident_info.room.id,
                    RoomUtility.charge_month == charge_month
                ).all()

                print(f"[DEBUG] {student.name}의 방 {resident_info.room.room_number} 공과금 개수: {len(utilities)} (charge_month: {charge_month})")
                
                # 특별 조건 2인 경우, 다음 월 공과금이 없으면 현재 월 공과금으로 대체
                if is_special_case_2 and len(utilities) == 0:
                    charge_month = date(year, month, 1)
                    utilities = db.query(RoomUtility).filter(
                        RoomUtility.room_id == resident_info.room.id,
                        RoomUtility.charge_month == charge_month
                    ).all()
                    print(f"[DEBUG] {student.name} - 특별 조건 2: 다음 월 공과금 없음, 현재 월 공과금으로 대체 - {len(utilities)}개")

                if utilities:
                    has_utilities = True
                    for utility in utilities:
                        # 해당 유틸리티 기간 내 방 거주자 전체 쿼리
                        if is_special_case:
                            # 특별 조건: 6월에 퇴사한 학생들도 7월 공과금 계산에 포함
                            all_residents = db.query(Resident).filter(
                                Resident.room_id == resident_info.room.id,
                                Resident.check_in_date <= utility.period_end
                                # check_out_date 조건 제거 - 6월에 퇴사해도 7월 공과금 계산에 포함
                            ).all()
                        else:
                            # 일반 조건: 기존 로직 유지
                            all_residents = db.query(Resident).filter(
                                Resident.room_id == resident_info.room.id,
                                Resident.check_in_date <= utility.period_end,
                                (Resident.check_out_date.is_(None) | (Resident.check_out_date >= utility.period_start))
                            ).all()

                        # 전체 person-day 계산
                        total_person_days = 0
                        for r in all_residents:
                            overlap_in = max(r.check_in_date, utility.period_start)
                            overlap_out = min(r.check_out_date or utility.period_end, utility.period_end)
                            overlap_days = (overlap_out - overlap_in).days + 1 if overlap_in <= overlap_out else 0
                            total_person_days += overlap_days

                        # 해당 학생의 공과금 기간 내 거주 일수 계산
                        student_overlap_in = max(resident_info.check_in_date, utility.period_start)
                        student_overlap_out = min(resident_info.check_out_date or utility.period_end, utility.period_end)
                        student_days = (student_overlap_out - student_overlap_in).days + 1 if student_overlap_in <= student_overlap_out else 0

                        # 학생별 부담액 계산
                        if total_person_days > 0 and student_days > 0:
                            # 1일당 요금 계산
                            per_day = float(utility.total_amount) / total_person_days
                            # 학생별 부담액 = 1일당 요금 × 학생 거주 일수
                            student_amount = int(per_day * student_days)
                        else:
                            student_amount = 0

                        utilities_data.append({
                            "utility_type": utility.utility_type,
                            "period_start": utility.period_start.strftime("%Y-%m-%d"),
                            "period_end": utility.period_end.strftime("%Y-%m-%d"),
                            "total_amount": float(utility.total_amount),
                            "student_days": student_days,
                            "total_person_days": total_person_days,
                            "student_amount": student_amount,
                            "room_number": resident_info.room.room_number
                        })
                        
                        # 공과금 유형별로 금액 누적
                        if utility.utility_type == "electricity":
                            room_electricity_amount += student_amount
                        elif utility.utility_type == "water":
                            room_water_amount += student_amount
                        elif utility.utility_type == "gas":
                            room_gas_amount += student_amount
                        
                        print(f"[DEBUG] {student.name} - 방 {resident_info.room.room_number} 유틸리티: {utility.utility_type} = {student_amount}엔")

            # 각 거주 기록별 데이터 누적
            print(f"[DEBUG] {student.name} - 거주 기록 누적 전: rent={total_rent_amount_for_student}, management_fee={total_management_fee_for_student}, wifi={total_wifi_amount_for_student}")
            print(f"[DEBUG] {student.name} - 현재 거주 기록: rent={rent_amount}, management_fee={management_fee}, wifi={wifi_amount}")
            
            total_rent_amount_for_student += rent_amount
            total_management_fee_for_student += management_fee
            total_wifi_amount_for_student += wifi_amount
            total_electricity_amount_for_student += room_electricity_amount
            total_water_amount_for_student += room_water_amount
            total_gas_amount_for_student += room_gas_amount
            if has_utilities:
                has_utilities_for_student = True
                all_utilities_data.extend(utilities_data)
            
            print(f"[DEBUG] {student.name} - 거주 기록 누적 후: rent={total_rent_amount_for_student}, management_fee={total_management_fee_for_student}, wifi={total_wifi_amount_for_student}")
            
            # 방 이동으로 인한 총액 제한 적용
            total_rent_amount_for_student = min(total_rent_amount_for_student, 30000)
            total_management_fee_for_student = min(total_management_fee_for_student, 5000)
            total_wifi_amount_for_student = min(total_wifi_amount_for_student, 700)
            
            print(f"[DEBUG] {student.name} - 제한 적용 후: rent={total_rent_amount_for_student}, management_fee={total_management_fee_for_student}, wifi={total_wifi_amount_for_student}")

        # 방번호와 건물명 처리 (복수 거주인 경우)
        if len(resident_records) > 1:
            room_numbers = [r.room.room_number for r in resident_records]
            building_names = [r.room.building.name for r in resident_records]
            room_number = ",".join(room_numbers)
            # 건물 이름이 같으면 중복 제거
            unique_building_names = list(set(building_names))
            building_name = ",".join(unique_building_names)
        else:
            room_number = resident_records[0].room.room_number
            building_name = resident_records[0].room.building.name
        
        # 학생 데이터 구성 (모든 거주 기록을 합산)
        student_data = {
            "student_id": str(student.id),
            "student_name": student.name,
            "student_type": student.student_type,
            "grade_name": student.grade.name if student.grade else None,
            "company_name": student.company.name if student.company else None,
            "room_number": room_number,
            "building_name": building_name,
            "days_in_month": sum([((student.resignation_date or target_end_date) - max(r.check_in_date, target_start_date)).days + 1 for r in resident_records if (student.resignation_date or target_end_date) >= max(r.check_in_date, target_start_date)]),
            "rent_amount": total_rent_amount_for_student,
            "management_fee": total_management_fee_for_student,
            "wifi_amount": total_wifi_amount_for_student,
            "has_utilities": has_utilities_for_student,
            "utilities": all_utilities_data if has_utilities_for_student else [],
            "electricity_amount": total_electricity_amount_for_student if has_utilities_for_student else 0,
            "water_amount": total_water_amount_for_student if has_utilities_for_student else 0,
            "gas_amount": total_gas_amount_for_student if has_utilities_for_student else 0,
            "total_utilities_amount": (total_electricity_amount_for_student + total_water_amount_for_student + total_gas_amount_for_student) if has_utilities_for_student else 0,
            "rent_management_wifi_total": total_rent_amount_for_student + total_management_fee_for_student + total_wifi_amount_for_student,
            "utilities_total": (total_electricity_amount_for_student + total_water_amount_for_student + total_gas_amount_for_student) if has_utilities_for_student else 0,
            "total_amount": total_rent_amount_for_student + total_management_fee_for_student + total_wifi_amount_for_student + (total_electricity_amount_for_student + total_water_amount_for_student + total_gas_amount_for_student) if has_utilities_for_student else 0,
            "is_special_case": is_special_case  # 디버깅용
        }

        # 모든 금액이 0인 경우 응답에서 제외
        if (total_rent_amount_for_student == 0 and 
            total_management_fee_for_student == 0 and
            total_wifi_amount_for_student == 0 and 
            total_electricity_amount_for_student == 0 and 
            total_water_amount_for_student == 0 and 
            total_gas_amount_for_student == 0):
            print(f"[DEBUG] {student.name} - 모든 금액이 0이므로 응답에서 제외")
            continue

        students_data.append(student_data)
        total_rent_amount += total_rent_amount_for_student
        total_management_fee += total_management_fee_for_student
        total_wifi_amount += total_wifi_amount_for_student
        total_electricity_amount += total_electricity_amount_for_student if has_utilities_for_student else 0
        total_water_amount += total_water_amount_for_student if has_utilities_for_student else 0
        total_gas_amount += total_gas_amount_for_student if has_utilities_for_student else 0

        print(f"[DEBUG] {student.name} 데이터 추가 - rent: {total_rent_amount_for_student}, management_fee: {total_management_fee_for_student}, wifi: {total_wifi_amount_for_student}, electricity: {total_electricity_amount_for_student if has_utilities_for_student else 0}, water: {total_water_amount_for_student if has_utilities_for_student else 0}, gas: {total_gas_amount_for_student if has_utilities_for_student else 0}, total: {total_rent_amount_for_student + total_management_fee_for_student + total_wifi_amount_for_student + (total_electricity_amount_for_student + total_water_amount_for_student + total_gas_amount_for_student) if has_utilities_for_student else 0}")

    print(f"[DEBUG] 최종 결과 - 학생 수: {len(students_data)}, 총 야칭: {total_rent_amount}, 총 관리비: {total_management_fee}, 총 와이파이: {total_wifi_amount}, 총 전기: {total_electricity_amount}, 총 수도: {total_water_amount}, 총 가스: {total_gas_amount}")
    
    # 학생 데이터 정렬: student_type, grade_name 기준
    students_data.sort(key=lambda x: (x.get("student_type", ""), x.get("grade_name", "")))
    
    return {
        "year": year,
        "month": month,
        "billing_period": f"{prev_year}년 {prev_month}월" if not any(s.get("is_special_case", False) for s in students_data) else f"{year}년 {month}월",
        "total_students": len(students_data),
        "students": students_data,
        "summary": {
            "total_electricity_amount": total_electricity_amount,
            "total_water_amount": total_water_amount,
            "total_gas_amount": total_gas_amount,
            "total_utilities_amount": total_electricity_amount + total_water_amount + total_gas_amount,
            "total_rent_amount": total_rent_amount,
            "total_management_fee": total_management_fee,
            "total_wifi_amount": total_wifi_amount,
            "grand_total": total_rent_amount + total_management_fee + total_wifi_amount + total_electricity_amount + total_water_amount + total_gas_amount
        }
    }

@router.get("/monthly-invoice-preview/students/by-building/{year}/{month}")
def get_monthly_invoice_preview_by_students_building(
    year: int,
    month: int,
    building_id: Optional[str] = Query(None, description="특정 건물로 필터링"),
    db: Session = Depends(get_db)
):
    """해당 년도 월의 건물별 학생별 청구서 미리보기 데이터 조회 (PDF 다운로드 전 프론트 표시용)"""
    print(f"[DEBUG] get_monthly_invoice_preview_by_building 시작 - year: {year}, month: {month}, building_id: {building_id}")
    
    # 월 유효성 검사
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="월은 1-12 사이의 값이어야 합니다")

    # 전월의 시작/종료일 계산 (7월 데이터 요청 시 6월 거주 기록 조회)
    if month == 1:
        prev_year = year - 1
        prev_month = 12
    else:
        prev_year = year
        prev_month = month - 1
    
    # 전월의 시작/종료일 계산
    if prev_month == 12:
        prev_month_end_date = date(prev_year + 1, 1, 1) - timedelta(days=1)
    else:
        prev_month_end_date = date(prev_year, prev_month + 1, 1) - timedelta(days=1)
    
    prev_month_start_date = date(prev_year, prev_month, 1)
    total_days_in_month = (prev_month_end_date - prev_month_start_date).days + 1

    # 특정 조건 학생들을 위한 현재 월 데이터 계산 (7월 요청 시 7월 데이터)
    current_month_start_date = date(year, month, 1)
    if month == 12:
        current_month_end_date = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        current_month_end_date = date(year, month + 1, 1) - timedelta(days=1)
    current_total_days_in_month = (current_month_end_date - current_month_start_date).days + 1

    # 1. 건물별 학생 리스트 조회
    print(f"[DEBUG] 건물별 학생 리스트 조회 시작")
    if building_id:
        # 특정 건물의 학생들 조회 - 회사 기준과 동일하게 모든 학생 조회 후 나중에 필터링
        students_query = db.query(Student)
    else:
        # 모든 학생 조회
        students_query = db.query(Student)
    
    students = students_query.all()
    print(f"[DEBUG] 조회된 학생 수: {len(students)}")

    # 2. 각 학생별로 해당 월에 거주하는지 확인하고 데이터 수집
    students_data = []
    total_electricity_amount = 0
    total_water_amount = 0
    total_gas_amount = 0
    total_rent_amount = 0
    total_management_fee = 0
    total_wifi_amount = 0

    for student in students:
        print(f"[DEBUG] 학생 처리 중: {student.name}")
        
        # 특정 조건 확인: student_type이 general이고 grade_id가 특정 값인 경우
        is_special_case_1 = (
            student.student_type == "GENERAL" and 
            str(student.grade_id) == "74494b21-499f-48d2-96f4-5df6cc1403e6"
        )
        
        is_special_case_2 = (
            student.student_type == "GENERAL" and 
            str(student.grade_id) == "b6e1b114-cc6c-4c12-ad6d-b281f9a1cbce"
        )
        
        is_special_case = is_special_case_1 or is_special_case_2
        
        print(f"[DEBUG] {student.student_type} - is_special_case_1: {student.grade_id} is_special_case_1 {is_special_case_1}")
        print(f"[DEBUG] {student.student_type} - is_special_case_2: {student.grade_id} is_special_case_2 {is_special_case_2}")
        
        # 조건에 따라 사용할 날짜 범위 결정
        if is_special_case_1:
            # 특별 조건 1: 현재 월 데이터 사용 (7월 요청 시 7월 데이터)
            target_start_date = current_month_start_date
            target_end_date = current_month_end_date
            target_total_days = current_total_days_in_month
            print(f"[DEBUG] {student.name} - 특별 조건 1 적용: {year}년 {month}월 데이터 사용")
        elif is_special_case_2:
            # 특별 조건 2: 다음 월 데이터 사용 (7월 요청 시 8월 데이터)
            if month == 12:
                next_year = year + 1
                next_month = 1
            else:
                next_year = year
                next_month = month + 1
            
            target_start_date = date(next_year, next_month, 1)
            if next_month == 12:
                target_end_date = date(next_year + 1, 1, 1) - timedelta(days=1)
            else:
                target_end_date = date(next_year, next_month + 1, 1) - timedelta(days=1)
            target_total_days = (target_end_date - target_start_date).days + 1
            print(f"[DEBUG] {student.name} - 특별 조건 2 적용: {next_year}년 {next_month}월 데이터 사용")
        else:
            # 일반 조건: 전월 데이터 사용 (7월 요청 시 6월 데이터)
            target_start_date = prev_month_start_date
            target_end_date = prev_month_end_date
            target_total_days = total_days_in_month
            print(f"[DEBUG] {student.name} - 일반 조건: {prev_year}년 {prev_month}월 데이터 사용")
        
        # 해당 학생의 거주 정보 조회
        resident_query = db.query(Resident).options(
            joinedload(Resident.room).joinedload(Room.building)
        ).filter(
            Resident.resident_id == student.id,
            Resident.check_in_date <= target_end_date,
            (Resident.check_out_date.is_(None) | (Resident.check_out_date >= target_start_date))
        )
        
        # building_id가 지정된 경우 해당 건물의 거주 기록만 조회
        if building_id:
            resident_query = resident_query.join(
                Room, Resident.room_id == Room.id
            ).filter(Room.building_id == building_id)
        
        resident_records = resident_query.all()

        if not resident_records:
            print(f"[DEBUG] {student.name} - 해당 월에 거주 정보 없음")
            continue

        # 모든 거주 기록에 대해 계산
        total_rent_amount_for_student = 0
        total_management_fee_for_student = 0
        total_wifi_amount_for_student = 0
        total_electricity_amount_for_student = 0
        total_water_amount_for_student = 0
        total_gas_amount_for_student = 0
        all_utilities_data = []
        has_utilities_for_student = False

        print(f"[DEBUG] {student.name} - 거주 기록 수: {len(resident_records)}")
        
        for resident_info in resident_records:
            # 거주한 일수 계산
            # 실제 입주일과 대상 월 시작일 중 늦은 날짜를 사용
            if resident_info.check_in_date >= target_start_date:
                check_in = resident_info.check_in_date
            else:
                check_in = target_start_date
            
            # 학생의 퇴직일(resignation_date)과 방 퇴실일(check_out_date) 중 이른 날짜 사용
            effective_check_out_date = None
            
            if student.resignation_date is not None and resident_info.check_out_date is not None:
                # 둘 다 있으면 이른 날짜 사용
                effective_check_out_date = min(student.resignation_date, resident_info.check_out_date)
            elif student.resignation_date is not None:
                # 퇴직일만 있으면 퇴직일 사용
                effective_check_out_date = student.resignation_date
            elif resident_info.check_out_date is not None:
                # 방 퇴실일만 있으면 방 퇴실일 사용
                effective_check_out_date = resident_info.check_out_date
            
            if effective_check_out_date is None:
                check_out = target_end_date
            else:
                # 실제 퇴실일과 대상 월 종료일 중 이른 날짜를 사용
                if effective_check_out_date <= target_end_date:
                    check_out = effective_check_out_date
                else:
                    check_out = target_end_date

            # 해당 월에 거주한 일수 계산
            if check_in <= check_out:
                days_in_month = (check_out - check_in).days + 1
            else:
                days_in_month = 0

            if days_in_month <= 0:
                if is_special_case:
                    # 특별 조건: 6월에 퇴사해도 7월 공과금 계산을 위해 계속 진행
                    print(f"[DEBUG] {student.name} - 특별 조건: 6월에 퇴사했지만 7월 공과금 계산 계속")
                    days_in_month = 0  # 야칭/와이파이는 0이지만 공과금은 계산
                else:
                    print(f"[DEBUG] {student.name} - 해당 월에 거주하지 않음")
                    continue

            print(f"[DEBUG] {student.name} - check_in: {check_in}, check_out: {check_out}, days_in_month: {days_in_month}")
            print(f"[DEBUG] {student.name} - target_start_date: {target_start_date}, target_end_date: {target_end_date}")

            # 야칭 계산
            print(f"[DEBUG] {student.name} - check_in_date: {resident_info.check_in_date}, resignation_date: {student.resignation_date}")
            
            # 퇴직일이 있는 경우와 없는 경우를 구분하여 계산
            if student.resignation_date is not None:
                # 퇴직일이 있는 경우
                check_in_month = resident_info.check_in_date.month
                check_in_year = resident_info.check_in_date.year
                resignation_month = student.resignation_date.month
                resignation_year = student.resignation_date.year
                
                # check_in_date와 resignation_date가 같은 달이 아닌 경우
                if (check_in_year != resignation_year) or (check_in_month != resignation_month):
                    # 퇴직일 달 기준으로 계산
                    if days_in_month >= 30:
                        # 30일 이상이면 무조건 고정 금액
                        rent_amount = 25000
                        management_fee = 5000
                        print(f"[DEBUG] {student.name} - 퇴직일 달 기준, 30일 이상: 월세 25,000엔, 관리비 5,000엔")
                    else:
                        # 29일 이하면 일별 계산 후 관리비 분리
                        total_amount = min(days_in_month * 1000, 30000)
                        management_fee = min(days_in_month * 166, 5000)
                        rent_amount = total_amount - management_fee
                        print(f"[DEBUG] {student.name} - 퇴직일 달 기준, 29일 이하: {days_in_month}일 × 1,000 = {total_amount}엔, 관리비: {management_fee}엔, 월세: {rent_amount}엔")
                else:
                    # 같은 달인 경우 - 퇴직일이 있으면 항상 일별 계산
                    if days_in_month >= 30:
                        # 30일 이상이면 무조건 고정 금액
                        rent_amount = 25000
                        management_fee = 5000
                        print(f"[DEBUG] {student.name} - 같은 달, 퇴직일 있음, 30일 이상: 월세 25,000엔, 관리비 5,000엔")
                    else:
                        # 29일 이하면 일별 계산 후 관리비 분리
                        total_amount = min(days_in_month * 1000, 30000)
                        management_fee = min(days_in_month * 166, 5000)
                        rent_amount = total_amount - management_fee
                        print(f"[DEBUG] {student.name} - 같은 달, 퇴직일 있음, 29일 이하: {days_in_month}일 × 1,000 = {total_amount}엔, 관리비: {management_fee}엔, 월세: {rent_amount}엔")
            else:
                # 퇴직일이 없는 경우
                if days_in_month >= 30:
                    # 30일 이상이면 무조건 고정 금액
                    rent_amount = 25000
                    management_fee = 5000
                    print(f"[DEBUG] {student.name} - 퇴직일 없음, 30일 이상: 월세 25,000엔, 관리비 5,000엔")
                else:
                    # 29일 이하면 일별 계산 후 관리비 분리
                    total_amount = min(days_in_month * 1000, 30000)
                    management_fee = min(days_in_month * 166, 5000)
                    rent_amount = total_amount - management_fee
                    print(f"[DEBUG] {student.name} - 퇴직일 없음, 29일 이하: {days_in_month}일 × 1,000 = {total_amount}엔, 관리비: {management_fee}엔, 월세: {rent_amount}엔")

            # 와이파이 비용 계산
            if student.resignation_date is not None:
                # 퇴직일이 있는 경우
                check_in_month = resident_info.check_in_date.month
                check_in_year = resident_info.check_in_date.year
                resignation_month = student.resignation_date.month
                resignation_year = student.resignation_date.year
                
                # check_in_date와 resignation_date가 같은 달이 아닌 경우
                if (check_in_year != resignation_year) or (check_in_month != resignation_month):
                    # 퇴직일 달 기준으로 계산
                    wifi_amount = min(int(days_in_month * (700 / 30)), 700)
                    print(f"[DEBUG] {student.name} - 와이파이 퇴직일 달 기준 계산: {days_in_month}일 × (700/30) = {wifi_amount}엔 (최대 700엔)")
                else:
                    # 같은 달인 경우 - 퇴직일이 있으면 항상 일별 계산
                    wifi_amount = min(int(days_in_month * (700 / 30)), 700)
                    print(f"[DEBUG] {student.name} - 와이파이 같은 달, 퇴직일 있음: {days_in_month}일 × (700/30) = {wifi_amount}엔 (최대 700엔)")
            else:
                # 퇴직일이 없는 경우
                # 입주일이 1일이고 해당 월 전체를 거주하는 경우만 700엔 고정
                if resident_info.check_in_date.day == 1 and days_in_month >= 30:
                    wifi_amount = 700
                    print(f"[DEBUG] {student.name} - 와이파이 퇴직일 없음, 1일 입주, 전체 월 거주: 700엔")
                else:
                    # 그 외의 경우는 일별 계산
                    wifi_amount = min(int(days_in_month * (700 / 30)), 700)
                    print(f"[DEBUG] {student.name} - 와이파이 퇴직일 없음, 일별 계산: {days_in_month}일 × (700/30) = {wifi_amount}엔 (최대 700엔)")

            # 3. 공과금 조회 및 계산
            utilities_data = []
            room_electricity_amount = 0
            room_water_amount = 0
            room_gas_amount = 0
            
            print(f"[DEBUG] {student.name} - 현재 거주 기록 계산 완료: rent={rent_amount}, wifi={wifi_amount}")
            has_utilities = False

            print(f"[DEBUG] {student.name} - resident_info.room 체크: {resident_info.room is not None}")
            if resident_info.room:
                # 공과금 조회
                if is_special_case_2:
                    # 특별 조건 2: 다음 월 공과금 사용 (7월 요청 시 8월 공과금)
                    if month == 12:
                        next_year = year + 1
                        next_month = 1
                    else:
                        next_year = year
                        next_month = month + 1
                    charge_month = date(next_year, next_month, 1)
                    print(f"[DEBUG] {student.name} - 특별 조건 2: {next_year}년 {next_month}월 공과금 조회")
                else:
                    # 일반 조건 및 특별 조건 1: 현재 월 공과금 사용 (7월 요청 시 7월 공과금)
                    charge_month = date(year, month, 1)
                    print(f"[DEBUG] {student.name} - 일반/특별 조건 1: {year}년 {month}월 공과금 조회")
                
                utilities = db.query(RoomUtility).filter(
                    RoomUtility.room_id == resident_info.room.id,
                    RoomUtility.charge_month == charge_month
                ).all()

                print(f"[DEBUG] {student.name}의 방 {resident_info.room.room_number} 공과금 개수: {len(utilities)} (charge_month: {charge_month})")
                
                # 특별 조건 2인 경우, 다음 월 공과금이 없으면 현재 월 공과금으로 대체
                if is_special_case_2 and len(utilities) == 0:
                    charge_month = date(year, month, 1)
                    utilities = db.query(RoomUtility).filter(
                        RoomUtility.room_id == resident_info.room.id,
                        RoomUtility.charge_month == charge_month
                    ).all()
                    print(f"[DEBUG] {student.name} - 특별 조건 2: 다음 월 공과금 없음, 현재 월 공과금으로 대체 - {len(utilities)}개")

                if utilities:
                    has_utilities = True
                    for utility in utilities:
                        # 해당 유틸리티 기간 내 방 거주자 전체 쿼리
                        if is_special_case:
                            # 특별 조건: 6월에 퇴사한 학생들도 7월 공과금 계산에 포함
                            all_residents = db.query(Resident).filter(
                                Resident.room_id == resident_info.room.id,
                                Resident.check_in_date <= utility.period_end
                                # check_out_date 조건 제거 - 6월에 퇴사해도 7월 공과금 계산에 포함
                            ).all()
                        else:
                            # 일반 조건: 기존 로직 유지
                            all_residents = db.query(Resident).filter(
                                Resident.room_id == resident_info.room.id,
                                Resident.check_in_date <= utility.period_end,
                                (Resident.check_out_date.is_(None) | (Resident.check_out_date >= utility.period_start))
                            ).all()

                        # 전체 person-day 계산
                        total_person_days = 0
                        for r in all_residents:
                            overlap_in = max(r.check_in_date, utility.period_start)
                            overlap_out = min(r.check_out_date or utility.period_end, utility.period_end)
                            overlap_days = (overlap_out - overlap_in).days + 1 if overlap_in <= overlap_out else 0
                            total_person_days += overlap_days

                        # 해당 학생의 공과금 기간 내 거주 일수 계산
                        student_overlap_in = max(resident_info.check_in_date, utility.period_start)
                        student_overlap_out = min(resident_info.check_out_date or utility.period_end, utility.period_end)
                        student_days = (student_overlap_out - student_overlap_in).days + 1 if student_overlap_in <= student_overlap_out else 0

                        # 학생별 부담액 계산
                        if total_person_days > 0 and student_days > 0:
                            # 1일당 요금 계산
                            per_day = float(utility.total_amount) / total_person_days
                            # 학생별 부담액 = 1일당 요금 × 학생 거주 일수
                            student_amount = int(per_day * student_days)
                        else:
                            student_amount = 0

                        utilities_data.append({
                            "utility_type": utility.utility_type,
                            "period_start": utility.period_start.strftime("%Y-%m-%d"),
                            "period_end": utility.period_end.strftime("%Y-%m-%d"),
                            "total_amount": float(utility.total_amount),
                            "student_days": student_days,
                            "total_person_days": total_person_days,
                            "student_amount": student_amount,
                            "room_number": resident_info.room.room_number
                        })
                        
                        # 공과금 유형별로 금액 누적
                        if utility.utility_type == "electricity":
                            room_electricity_amount += student_amount
                        elif utility.utility_type == "water":
                            room_water_amount += student_amount
                        elif utility.utility_type == "gas":
                            room_gas_amount += student_amount
                        
                        print(f"[DEBUG] {student.name} - 방 {resident_info.room.room_number} 유틸리티: {utility.utility_type} = {student_amount}엔")

            # 각 거주 기록별 데이터 누적
            print(f"[DEBUG] {student.name} - 거주 기록 누적 전: rent={total_rent_amount_for_student}, management_fee={total_management_fee_for_student}, wifi={total_wifi_amount_for_student}")
            print(f"[DEBUG] {student.name} - 현재 거주 기록: rent={rent_amount}, management_fee={management_fee}, wifi={wifi_amount}")
            
            total_rent_amount_for_student += rent_amount
            total_management_fee_for_student += management_fee
            total_wifi_amount_for_student += wifi_amount
            total_electricity_amount_for_student += room_electricity_amount
            total_water_amount_for_student += room_water_amount
            total_gas_amount_for_student += room_gas_amount
            if has_utilities:
                has_utilities_for_student = True
                all_utilities_data.extend(utilities_data)
            
            print(f"[DEBUG] {student.name} - 거주 기록 누적 후: rent={total_rent_amount_for_student}, management_fee={total_management_fee_for_student}, wifi={total_wifi_amount_for_student}")
            
            # 방 이동으로 인한 총액 제한 적용
            total_rent_amount_for_student = min(total_rent_amount_for_student, 30000)
            total_management_fee_for_student = min(total_management_fee_for_student, 5000)
            total_wifi_amount_for_student = min(total_wifi_amount_for_student, 700)
            
            print(f"[DEBUG] {student.name} - 제한 적용 후: rent={total_rent_amount_for_student}, management_fee={total_management_fee_for_student}, wifi={total_wifi_amount_for_student}")

        # 방번호와 건물명 처리 (복수 거주인 경우)
        if len(resident_records) > 1:
            room_numbers = [r.room.room_number for r in resident_records]
            building_names = [r.room.building.name for r in resident_records]
            room_number = ",".join(room_numbers)
            # 건물 이름이 같으면 중복 제거
            unique_building_names = list(set(building_names))
            building_name = ",".join(unique_building_names)
        else:
            room_number = resident_records[0].room.room_number
            building_name = resident_records[0].room.building.name
        
        # 학생 데이터 구성 (모든 거주 기록을 합산)
        student_data = {
            "student_id": str(student.id),
            "student_name": student.name,
            "student_type": student.student_type,
            "grade_name": student.grade.name if student.grade else None,
            "company_name": student.company.name if student.company else None,
            "room_number": room_number,
            "building_name": building_name,
            "days_in_month": sum([((student.resignation_date or target_end_date) - max(r.check_in_date, target_start_date)).days + 1 for r in resident_records if (student.resignation_date or target_end_date) >= max(r.check_in_date, target_start_date)]),
            "rent_amount": total_rent_amount_for_student,
            "management_fee": total_management_fee_for_student,
            "wifi_amount": total_wifi_amount_for_student,
            "has_utilities": has_utilities_for_student,
            "utilities": all_utilities_data if has_utilities_for_student else [],
            "electricity_amount": total_electricity_amount_for_student if has_utilities_for_student else 0,
            "water_amount": total_water_amount_for_student if has_utilities_for_student else 0,
            "gas_amount": total_gas_amount_for_student if has_utilities_for_student else 0,
            "total_utilities_amount": (total_electricity_amount_for_student + total_water_amount_for_student + total_gas_amount_for_student) if has_utilities_for_student else 0,
            "rent_management_wifi_total": total_rent_amount_for_student + total_management_fee_for_student + total_wifi_amount_for_student,
            "utilities_total": (total_electricity_amount_for_student + total_water_amount_for_student + total_gas_amount_for_student) if has_utilities_for_student else 0,
            "total_amount": total_rent_amount_for_student + total_management_fee_for_student + total_wifi_amount_for_student + (total_electricity_amount_for_student + total_water_amount_for_student + total_gas_amount_for_student) if has_utilities_for_student else 0,
            "is_special_case": is_special_case  # 디버깅용
        }

        # 모든 금액이 0인 경우 응답에서 제외
        if (total_rent_amount_for_student == 0 and 
            total_management_fee_for_student == 0 and
            total_wifi_amount_for_student == 0 and 
            total_electricity_amount_for_student == 0 and 
            total_water_amount_for_student == 0 and 
            total_gas_amount_for_student == 0):
            print(f"[DEBUG] {student.name} - 모든 금액이 0이므로 응답에서 제외")
            continue

        students_data.append(student_data)
        total_rent_amount += total_rent_amount_for_student
        total_management_fee += total_management_fee_for_student
        total_wifi_amount += total_wifi_amount_for_student
        total_electricity_amount += total_electricity_amount_for_student if has_utilities_for_student else 0
        total_water_amount += total_water_amount_for_student if has_utilities_for_student else 0
        total_gas_amount += total_gas_amount_for_student if has_utilities_for_student else 0

        print(f"[DEBUG] {student.name} 데이터 추가 - rent: {total_rent_amount_for_student}, management_fee: {total_management_fee_for_student}, wifi: {total_wifi_amount_for_student}, electricity: {total_electricity_amount_for_student if has_utilities_for_student else 0}, water: {total_water_amount_for_student if has_utilities_for_student else 0}, gas: {total_gas_amount_for_student if has_utilities_for_student else 0}, total: {total_rent_amount_for_student + total_management_fee_for_student + total_wifi_amount_for_student + (total_electricity_amount_for_student + total_water_amount_for_student + total_gas_amount_for_student) if has_utilities_for_student else 0}")

    print(f"[DEBUG] 최종 결과 - 학생 수: {len(students_data)}, 총 야칭: {total_rent_amount}, 총 관리비: {total_management_fee}, 총 와이파이: {total_wifi_amount}, 총 전기: {total_electricity_amount}, 총 수도: {total_water_amount}, 총 가스: {total_gas_amount}")
    
    # 학생 데이터 정렬: student_type, grade_name 기준
    students_data.sort(key=lambda x: (x.get("student_type", ""), x.get("grade_name", "")))
    
    return {
        "year": year,
        "month": month,
        "billing_period": f"{prev_year}년 {prev_month}월" if not any(s.get("is_special_case", False) for s in students_data) else f"{year}년 {month}월",
        "total_students": len(students_data),
        "students": students_data,
        "summary": {
            "total_electricity_amount": total_electricity_amount,
            "total_water_amount": total_water_amount,
            "total_gas_amount": total_gas_amount,
            "total_utilities_amount": total_electricity_amount + total_water_amount + total_gas_amount,
            "total_rent_amount": total_rent_amount,
            "total_management_fee": total_management_fee,
            "total_wifi_amount": total_wifi_amount,
            "grand_total": total_rent_amount + total_management_fee + total_wifi_amount + total_electricity_amount + total_water_amount + total_gas_amount
        }
    }

def html_to_pdf_bytes(html_content: str) -> bytes:
    """HTML 내용을 PDF로 변환 (weasyprint 사용)"""
    from weasyprint import HTML, CSS
    from weasyprint.text.fonts import FontConfiguration
    import base64
    import os
    
    # Noto Sans JP 폰트 파일을 base64로 인코딩
    font_path = "static/fonts/NotoSansJP-Regular.ttf"
    font_base64 = ""
    
    try:
        if os.path.exists(font_path):
            with open(font_path, "rb") as font_file:
                font_data = font_file.read()
                font_base64 = base64.b64encode(font_data).decode('utf-8')
                print(f"[DEBUG] Noto Sans JP 폰트 로드 성공: {len(font_data)} bytes")
        else:
            print(f"[WARNING] 폰트 파일을 찾을 수 없음: {font_path}")
    except Exception as e:
        print(f"[WARNING] 폰트 로드 실패: {str(e)}")
    
    # CSS with embedded font
    css_content = f"""
    @font-face {{
        font-family: "Noto Sans JP";
        src: url("data:font/ttf;base64,{font_base64}") format("truetype");
        font-weight: normal;
        font-style: normal;
    }}
    
    @page {{
        size: A4;
        margin: 20mm;
    }}
    
    body {{
        font-family: "Noto Sans JP", "Hiragino Sans", "ヒラギノ角ゴシック", "Yu Gothic Medium", "Yu Gothic", "メイリオ", "Meiryo", "MS PGothic", "MS Pゴシック", "Takao Gothic", "IPAexGothic", "IPAPGothic", "VL PGothic", "Noto Sans CJK JP", sans-serif;
        font-size: 8pt;
        line-height: 1.4;
        -webkit-font-smoothing: antialiased;
        -moz-osx-font-smoothing: grayscale;
    }}
    
    * {{
        font-family: "Noto Sans JP", "Hiragino Sans", "ヒラギノ角ゴシック", "Yu Gothic Medium", "Yu Gothic", "メイリオ", "Meiryo", "MS PGothic", "MS Pゴシック", "Takao Gothic", "IPAexGothic", "IPAPGothic", "VL PGothic", "Noto Sans CJK JP", sans-serif !important;
    }}
    """
    
    # FontConfiguration 설정
    font_config = FontConfiguration()
    
    # HTML과 CSS를 함께 렌더링
    html_doc = HTML(string=html_content)
    css_doc = CSS(string=css_content, font_config=font_config)
    
    pdf = html_doc.write_pdf(stylesheets=[css_doc], font_config=font_config)
    return pdf

@router.get("/download-monthly-invoice-pdf/students/company/{year}/{month}")
def download_monthly_invoice_pdf_students_company(
    year: int,
    month: int,
    company_id: Optional[str] = Query(None, description="특정 회사로 필터링"),
    db: Session = Depends(get_db)
):
    """월간 학생별 청구서 PDF 다운로드 (회사 기준)"""
    try:
        # 미리보기 데이터 조회 - 직접 함수 호출
        preview_data = get_monthly_invoice_preview_by_students_company(
            year=year,
            month=month,
            company_id=company_id,
            db=db
        )
        
        # 다음 달 계산 (지급 기한용)
        if month == 12:
            next_year = year + 1
            next_month = 1
        else:
            next_year = year
            next_month = month + 1
        
        # PDF용 데이터 준비 - 2페이지 리스트 포함
        pdf_data = {
            "sender_name": "株式会社 ミシマ",
            "sender_address": "〒546-0003 大阪市東住吉区今川4-5-9-201",
            "sender_tel": "06-6760-7400",
            "sender_fax": "06-6760-7401",
            "registration_number": "T4120001018934",
            "recipient_name": "医療法人聖和錦秀会 阪和いずみ病院 御中",
            "recipient_address": "〒594-1157 大阪府和泉市あゆみ野1-7-1",
            "invoice_date": f"{year}年{month}月10日",
            "billing_period": preview_data.get("billing_period", f"{year}年{month}月"),
            "year": year,
            "month": month,
            "categories": [],
            "subtotal": 0,
            "tax_amount": 0,
            "total_amount": 0,
            "bank_name": "関西みらい銀行",
            "branch_name": "八尾本町支店",
            "account_type": "普通",
            "account_number": "0043448",
            "account_holder": "株式会社ミシマ",
            "payment_deadline": f"{next_year}年{next_month}月31日",
            "students": [],
            "total_rent": 0,
            "total_management": 0,
            "total_wifi": 0
        }
        
        # 학생들을 기능실습생/특정기능실습생으로 분류
        general_students = []
        specific_students = []
        
        for student in preview_data.get("students", []):
            # 특별 케이스 확인 - grade_name으로 비교
            is_special_case_1 = (
                student.get("student_type") == "GENERAL" and 
                student.get("grade_name", "") == "3期生"
            )
            
            is_special_case_2 = (
                student.get("student_type") == "GENERAL" and 
                student.get("grade_name", "") == "2期生"
            )
            
            # 디버깅 로그 추가
            print(f"[DEBUG] PDF 생성 - 학생: {student.get('student_name', '')}")
            print(f"[DEBUG] PDF 생성 - student_type: {student.get('student_type', '')}")
            print(f"[DEBUG] PDF 생성 - grade_name: {student.get('grade_name', '')}")
            print(f"[DEBUG] PDF 생성 - is_special_case_1: {is_special_case_1}")
            print(f"[DEBUG] PDF 생성 - is_special_case_2: {is_special_case_2}")
            
            # 청구기준 월 결정
            if is_special_case_1:
                # 특별 조건 1: 현재 월 (7월 검색 시 7월)
                billing_month = month
                billing_year = year
                print(f"[DEBUG] PDF 생성 - 특별 조건 1 적용: {billing_year}년 {billing_month}월")
            elif is_special_case_2:
                # 특별 조건 2: 다음 월 (7월 검색 시 8월)
                if month == 12:
                    billing_month = 1
                    billing_year = year + 1
                else:
                    billing_month = month + 1
                    billing_year = year
                print(f"[DEBUG] PDF 생성 - 특별 조건 2 적용: {billing_year}년 {billing_month}월")
            else:
                # 일반 조건: 전월 (7월 검색 시 6월)
                if month == 1:
                    billing_month = 12
                    billing_year = year - 1
                else:
                    billing_month = month - 1
                    billing_year = year
                print(f"[DEBUG] PDF 생성 - 일반 조건 적용: {billing_year}년 {billing_month}월")
            
            # 2페이지 리스트용 데이터 추가
            student_data = {
                "student_name": student.get("student_name", ""),
                "building_name": student.get("building_name", ""),
                "room_number": student.get("room_number", ""),
                "company_name": student.get("company_name", ""),
                "rent_amount": student.get("rent_amount", 0),
                "management_fee": student.get("management_fee", 0),
                "wifi_amount": student.get("wifi_amount", 0),
                "total_amount": student.get("total_amount", 0),
                "category": "技能" if student.get("student_type") == "GENERAL" else "特定",
                "generation": student.get("grade_name", "") if student.get("student_type") == "GENERAL" else "",
                "billingMonth": billing_month,
                "billingYear": billing_year
            }
            pdf_data["students"].append(student_data)
            
            # 합계 계산
            pdf_data["total_rent"] += student.get("rent_amount", 0)
            pdf_data["total_management"] += student.get("management_fee", 0)
            pdf_data["total_wifi"] += student.get("wifi_amount", 0)
            
            if student.get("student_type") == "GENERAL":
                general_students.append(student)
            else:
                specific_students.append(student)
        
        # 1페이지 청구서용 카테고리 데이터
        if general_students:
            general_subtotal = sum(s.get("total_amount", 0) for s in general_students)
            pdf_data["categories"].append({
                "name": "機能実習生",
                "students": general_students,
                "subtotal": general_subtotal
            })
            pdf_data["subtotal"] += general_subtotal
        
        if specific_students:
            specific_subtotal = sum(s.get("total_amount", 0) for s in specific_students)
            pdf_data["categories"].append({
                "name": "特定機能実習生",
                "students": specific_students,
                "subtotal": specific_subtotal
            })
            pdf_data["subtotal"] += specific_subtotal
        
        # 세금 계산
        pdf_data["tax_amount"] = int(pdf_data["subtotal"] * 0.1)
        pdf_data["total_amount"] = pdf_data["subtotal"] + pdf_data["tax_amount"]
        
        print(f"[DEBUG] 최종 PDF 데이터: categories 길이 = {len(pdf_data['categories'])}")
        print(f"[DEBUG] 총 학생 수: {len(general_students) + len(specific_students)}")
        print(f"[DEBUG] 소계: {pdf_data['subtotal']}, 세금: {pdf_data['tax_amount']}, 총액: {pdf_data['total_amount']}")
        
        # HTML 템플릿 렌더링
        html_content = templates.get_template("company_invoice.html").render(
            data=pdf_data
        )
        
        # PDF 생성
        pdf_bytes = html_to_pdf_bytes(html_content)
        
        # 파일명 생성 (영문으로 변경)
        company_suffix = f"_{company_id}" if company_id else "_all"
        filename = f"monthly_invoice_{year}_{month:02d}{company_suffix}.pdf"
        
        # PDF 파일 반환
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Type": "application/pdf"
            }
        )
        
    except Exception as e:
        print(f"[ERROR] PDF 생성 중 오류: {str(e)}")
        import traceback
        print(f"[ERROR] Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"PDF 생성 중 오류가 발생했습니다: {str(e)}")

@router.get("/download-monthly-invoice-pdf/students/building/{year}/{month}")
def download_monthly_invoice_pdf_students_building(
    year: int,
    month: int,
    building_id: Optional[str] = Query(None, description="특정 건물로 필터링"),
    db: Session = Depends(get_db)
):
    """월간 학생별 청구서 PDF 다운로드 (건물 기준)"""
    try:
        # 미리보기 데이터 조회 - 직접 함수 호출
        preview_data = get_monthly_invoice_preview_by_students_building(
            year=year,
            month=month,
            building_id=building_id,
            db=db
        )
        
        # PDF용 데이터 준비
        pdf_data = {
            "company_name": "전체 건물" if not building_id else preview_data["students"][0]["building_name"] if preview_data["students"] else "해당 건물",
            "year": preview_data["year"],
            "month": preview_data["month"],
            "billing_period": preview_data["billing_period"],
            "total_amount": preview_data["summary"]["grand_total"],
            "vat_total_amount": int(preview_data["summary"]["grand_total"] + preview_data["summary"]["grand_total"] * 0.1),
            "vat": int(preview_data["summary"]["grand_total"] * 0.1),
            "issue_date": datetime.now().strftime("%Y年%m月%d日"),
            "invoice_list": []
        }
        
        # 학생 데이터 처리
        for student in preview_data["students"]:
            # invoice_items 구성
            invoice_items = []
            
            # 월세
            if student.get("rent_amount", 0) > 0:
                invoice_items.append({
                    "name": "月額賃料",
                    "unit_price": student["rent_amount"],
                    "amount": student["rent_amount"],
                    "memo": "",
                    "type": "rent"
                })
            
            # 관리비
            if student.get("management_fee", 0) > 0:
                invoice_items.append({
                    "name": "管理費",
                    "unit_price": student["management_fee"],
                    "amount": student["management_fee"],
                    "memo": "",
                    "type": "management"
                })
            
            # 와이파이
            if student.get("wifi_amount", 0) > 0:
                invoice_items.append({
                    "name": "Wi-Fi料金",
                    "unit_price": student["wifi_amount"],
                    "amount": student["wifi_amount"],
                    "memo": "",
                    "type": "wifi"
                })
            
            # 전기
            if student.get("electricity_amount", 0) > 0:
                invoice_items.append({
                    "name": "電気代",
                    "unit_price": student["electricity_amount"],
                    "amount": student["electricity_amount"],
                    "memo": "",
                    "type": "electricity"
                })
            
            # 수도
            if student.get("water_amount", 0) > 0:
                invoice_items.append({
                    "name": "水道代",
                    "unit_price": student["water_amount"],
                    "amount": student["water_amount"],
                    "memo": "",
                    "type": "water"
                })
            
            # 가스
            if student.get("gas_amount", 0) > 0:
                invoice_items.append({
                    "name": "ガス代",
                    "unit_price": student["gas_amount"],
                    "amount": student["gas_amount"],
                    "memo": "",
                    "type": "gas"
                })
            
            # 학생 데이터 추가
            pdf_data["invoice_list"].append({
                "student_name": student.get("student_name", "Unknown"),
                "total_amount": student.get("total_amount", 0),  # 이 부분 추가
                "invoice_number": f"INV-{year}{month:02d}-{student.get('student_id', 'unknown')[:8]}",
                "invoice_items": invoice_items
            })
        
        # HTML 템플릿 렌더링
        html_content = templates.get_template("company_invoice.html").render(
            data=pdf_data
        )
        
        # PDF 생성
        pdf_bytes = html_to_pdf_bytes(html_content)
        
        # 파일명 생성
        building_suffix = f"_{building_id}" if building_id else "_전체"
        filename = f"월간청구서_건물_{year}년{month}월{building_suffix}.pdf"
        
        # PDF 파일 반환
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Type": "application/pdf"
            }
        )
        
    except Exception as e:
        print(f"[ERROR] PDF 생성 중 오류: {str(e)}")
        import traceback
        print(f"[ERROR] Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"PDF 생성 중 오류가 발생했습니다: {str(e)}")