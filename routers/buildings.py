from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from typing import Optional, List
from database import SessionLocal
from models import Building, Room, Student, Resident, BillingMonthlyItem, RoomUtility, BuildingCategoriesRent
from schemas import BuildingResponse, BuildingUpdate
from datetime import datetime, date, timedelta
from database_log import create_database_log
from utils.dependencies import get_current_user

router = APIRouter(prefix="/buildings", tags=["건물 관리"])

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

@router.get("/monthly-invoice-preview/students/{year}/{month}")
def get_monthly_invoice_preview_by_students(
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
    total_wifi_amount = 0

    for student in students:
        print(f"[DEBUG] 학생 처리 중: {student.name}")
        
        # 해당 학생의 전월 거주 정보 조회 (모든 거주 기록)
        resident_records = db.query(Resident).options(
            joinedload(Resident.room).joinedload(Room.building)
        ).filter(
            Resident.resident_id == student.id,
            Resident.check_in_date <= prev_month_end_date,
            (Resident.check_out_date.is_(None) | (Resident.check_out_date >= prev_month_start_date))
        ).all()

        if not resident_records:
            print(f"[DEBUG] {student.name} - 해당 월에 거주 정보 없음")
            continue

        # 모든 거주 기록에 대해 계산
        total_rent_amount_for_student = 0
        total_wifi_amount_for_student = 0
        total_electricity_amount_for_student = 0
        total_water_amount_for_student = 0
        total_gas_amount_for_student = 0
        all_utilities_data = []
        has_utilities_for_student = False

        print(f"[DEBUG] {student.name} - 거주 기록 수: {len(resident_records)}")
        
        for resident_info in resident_records:
            # 전월에 거주한 일수 계산
            # 실제 입주일과 전월 시작일 중 늦은 날짜를 사용
            if resident_info.check_in_date >= prev_month_start_date:
                check_in = resident_info.check_in_date
            else:
                check_in = prev_month_start_date
            
            # 퇴실일이 None이면 전월 전체 거주로 인식
            if resident_info.check_out_date is None:
                check_out = prev_month_end_date
            else:
                # 실제 퇴실일과 전월 종료일 중 이른 날짜를 사용
                if resident_info.check_out_date <= prev_month_end_date:
                    check_out = resident_info.check_out_date
                else:
                    check_out = prev_month_end_date

            # 해당 월에 거주한 일수 계산
            if check_in <= check_out:
                days_in_month = (check_out - check_in).days + 1
            else:
                days_in_month = 0

            if days_in_month <= 0:
                print(f"[DEBUG] {student.name} - 해당 월에 거주하지 않음")
                continue

            print(f"[DEBUG] {student.name} - check_in: {check_in}, check_out: {check_out}, days_in_month: {days_in_month}")
            print(f"[DEBUG] {student.name} - prev_month_start_date: {prev_month_start_date}, prev_month_end_date: {prev_month_end_date}")

            # 야칭 계산
            print(f"[DEBUG] {student.name} - check_in_date: {resident_info.check_in_date}, check_out_date: {resident_info.check_out_date}")
            
            # 퇴실일이 있는 경우와 없는 경우를 구분하여 계산
            if resident_info.check_out_date is not None:
                # 퇴실일이 있는 경우
                check_in_month = resident_info.check_in_date.month
                check_in_year = resident_info.check_in_date.year
                check_out_month = resident_info.check_out_date.month
                check_out_year = resident_info.check_out_date.year
                
                # check_in_date와 check_out_date가 같은 달이 아닌 경우
                if (check_in_year != check_out_year) or (check_in_month != check_out_month):
                    # 퇴실일 달 기준으로 계산
                    rent_amount = min(days_in_month * 1000, 30000)
                    print(f"[DEBUG] {student.name} - 퇴실일 달 기준 계산: {days_in_month}일 × 1,000 = {rent_amount}엔 (최대 30,000엔)")
                else:
                    # 같은 달인 경우 - 퇴실일이 있으면 항상 일별 계산
                    rent_amount = min(days_in_month * 1000, 30000)
                    print(f"[DEBUG] {student.name} - 같은 달, 퇴실일 있음: {days_in_month}일 × 1,000 = {rent_amount}엔 (최대 30,000엔)")
            else:
                # 퇴실일이 없는 경우
                # 입주일이 1일이고 해당 월 전체를 거주하는 경우만 30,000엔
                if resident_info.check_in_date.day == 1 and days_in_month >= 30:
                    rent_amount = 30000
                    print(f"[DEBUG] {student.name} - 퇴실일 없음, 1일 입주, 전체 월 거주: 30,000엔")
                else:
                    # 그 외의 경우는 일별 계산
                    rent_amount = min(days_in_month * 1000, 30000)
                    print(f"[DEBUG] {student.name} - 퇴실일 없음, 일별 계산: {days_in_month}일 × 1,000 = {rent_amount}엔 (최대 30,000엔)")

            # 와이파이 비용 계산
            if resident_info.check_out_date is not None:
                # 퇴실일이 있는 경우
                check_in_month = resident_info.check_in_date.month
                check_in_year = resident_info.check_in_date.year
                check_out_month = resident_info.check_out_date.month
                check_out_year = resident_info.check_out_date.year
                
                # check_in_date와 check_out_date가 같은 달이 아닌 경우
                if (check_in_year != check_out_year) or (check_in_month != check_out_month):
                    # 퇴실일 달 기준으로 계산
                    wifi_amount = min(int(days_in_month * (700 / 30)), 700)
                    print(f"[DEBUG] {student.name} - 와이파이 퇴실일 달 기준 계산: {days_in_month}일 × (700/30) = {wifi_amount}엔 (최대 700엔)")
                else:
                    # 같은 달인 경우 - 퇴실일이 있으면 항상 일별 계산
                    wifi_amount = min(int(days_in_month * (700 / 30)), 700)
                    print(f"[DEBUG] {student.name} - 와이파이 같은 달, 퇴실일 있음: {days_in_month}일 × (700/30) = {wifi_amount}엔 (최대 700엔)")
            else:
                # 퇴실일이 없는 경우
                # 입주일이 1일이고 해당 월 전체를 거주하는 경우만 700엔 고정
                if resident_info.check_in_date.day == 1 and days_in_month >= 30:
                    wifi_amount = 700
                    print(f"[DEBUG] {student.name} - 와이파이 퇴실일 없음, 1일 입주, 전체 월 거주: 700엔")
                else:
                    # 그 외의 경우는 일별 계산
                    wifi_amount = min(int(days_in_month * (700 / 30)), 700)
                    print(f"[DEBUG] {student.name} - 와이파이 퇴실일 없음, 일별 계산: {days_in_month}일 × (700/30) = {wifi_amount}엔 (최대 700엔)")

            # 3. 공과금 조회 및 계산
            utilities_data = []
            room_electricity_amount = 0
            room_water_amount = 0
            room_gas_amount = 0
            
            print(f"[DEBUG] {student.name} - 현재 거주 기록 계산 완료: rent={rent_amount}, wifi={wifi_amount}")
            has_utilities = False

            if resident_info.room:
                # 해당 방의 해당 월 공과금 조회 (7월 계산으로 입력된 공과금)
                utilities = db.query(RoomUtility).filter(
                    RoomUtility.room_id == resident_info.room.id,
                    RoomUtility.charge_month == date(year, month, 1)
                ).all()

                print(f"[DEBUG] {student.name}의 방 {resident_info.room.room_number} 공과금 개수: {len(utilities)}")

                if utilities:
                    has_utilities = True
                    for utility in utilities:
                        # 해당 유틸리티 기간 내 방 거주자 전체 쿼리
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
            print(f"[DEBUG] {student.name} - 거주 기록 누적 전: rent={total_rent_amount_for_student}, wifi={total_wifi_amount_for_student}")
            print(f"[DEBUG] {student.name} - 현재 거주 기록: rent={rent_amount}, wifi={wifi_amount}")
            
            total_rent_amount_for_student += rent_amount
            total_wifi_amount_for_student += wifi_amount
            total_electricity_amount_for_student += room_electricity_amount
            total_water_amount_for_student += room_water_amount
            total_gas_amount_for_student += room_gas_amount
            if has_utilities:
                has_utilities_for_student = True
                all_utilities_data.extend(utilities_data)
            
            print(f"[DEBUG] {student.name} - 거주 기록 누적 후: rent={total_rent_amount_for_student}, wifi={total_wifi_amount_for_student}")
            
            # 방 이동으로 인한 총액 제한 적용
            total_rent_amount_for_student = min(total_rent_amount_for_student, 30000)
            total_wifi_amount_for_student = min(total_wifi_amount_for_student, 700)
            
            print(f"[DEBUG] {student.name} - 제한 적용 후: rent={total_rent_amount_for_student}, wifi={total_wifi_amount_for_student}")

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
            "room_number": room_number,
            "building_name": building_name,
            "days_in_month": sum([((r.check_out_date or prev_month_end_date) - max(r.check_in_date, prev_month_start_date)).days + 1 for r in resident_records if (r.check_out_date or prev_month_end_date) >= max(r.check_in_date, prev_month_start_date)]),
            "rent_amount": total_rent_amount_for_student,
            "wifi_amount": total_wifi_amount_for_student,
            "has_utilities": has_utilities_for_student,
            "utilities": all_utilities_data if has_utilities_for_student else [],
            "electricity_amount": total_electricity_amount_for_student if has_utilities_for_student else 0,
            "water_amount": total_water_amount_for_student if has_utilities_for_student else 0,
            "gas_amount": total_gas_amount_for_student if has_utilities_for_student else 0,
            "total_utilities_amount": (total_electricity_amount_for_student + total_water_amount_for_student + total_gas_amount_for_student) if has_utilities_for_student else 0,
            "rent_wifi_total": total_rent_amount_for_student + total_wifi_amount_for_student,
            "utilities_total": (total_electricity_amount_for_student + total_water_amount_for_student + total_gas_amount_for_student) if has_utilities_for_student else 0,
            "total_amount": total_rent_amount_for_student + total_wifi_amount_for_student + (total_electricity_amount_for_student + total_water_amount_for_student + total_gas_amount_for_student) if has_utilities_for_student else 0
        }

        students_data.append(student_data)
        total_rent_amount += total_rent_amount_for_student
        total_wifi_amount += total_wifi_amount_for_student
        total_electricity_amount += total_electricity_amount_for_student if has_utilities_for_student else 0
        total_water_amount += total_water_amount_for_student if has_utilities_for_student else 0
        total_gas_amount += total_gas_amount_for_student if has_utilities_for_student else 0

        print(f"[DEBUG] {student.name} 데이터 추가 - rent: {total_rent_amount_for_student}, wifi: {total_wifi_amount_for_student}, electricity: {total_electricity_amount_for_student if has_utilities_for_student else 0}, water: {total_water_amount_for_student if has_utilities_for_student else 0}, gas: {total_gas_amount_for_student if has_utilities_for_student else 0}, total: {total_rent_amount_for_student + total_wifi_amount_for_student + (total_electricity_amount_for_student + total_water_amount_for_student + total_gas_amount_for_student) if has_utilities_for_student else 0}")

    print(f"[DEBUG] 최종 결과 - 학생 수: {len(students_data)}, 총 야칭: {total_rent_amount}, 총 와이파이: {total_wifi_amount}, 총 전기: {total_electricity_amount}, 총 수도: {total_water_amount}, 총 가스: {total_gas_amount}")
    
    return {
        "year": year,
        "month": month,
        "billing_period": f"{prev_year}년 {prev_month}월",
        "total_students": len(students_data),
        "students": students_data,
        "summary": {
            "total_electricity_amount": total_electricity_amount,
            "total_water_amount": total_water_amount,
            "total_gas_amount": total_gas_amount,
            "total_utilities_amount": total_electricity_amount + total_water_amount + total_gas_amount,
            "total_rent_amount": total_rent_amount,
            "total_wifi_amount": total_wifi_amount,
            "grand_total": total_rent_amount + total_wifi_amount + total_electricity_amount + total_water_amount + total_gas_amount
        }
    }

@router.get("/download-monthly-invoice/{year}/{month}")
def download_monthly_invoice(
    year: int,
    month: int,
    building_id: Optional[str] = Query(None, description="건물 ID로 필터링"),
    db: Session = Depends(get_db)
):
    """월간 청구서 Excel 다운로드"""
    try:
        # 년월 유효성 검사
        if not (1 <= month <= 12):
            raise HTTPException(status_code=400, detail="월은 1-12 사이여야 합니다")
        
        # 전달 기준으로 시작/종료일 계산 (예: 7월 조회 시 6월 1일~6월 30일)
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
            end_date = date(prev_year + 1, prev_month + 1, 1) - timedelta(days=1)

        target_charge_month = date(year, month, 1)

        # 모든 방의 공과금이 있는 방들 조회
        rooms_with_utilities = db.query(Room).options(
            joinedload(Room.building)
        ).join(RoomUtility).filter(
            RoomUtility.charge_month == target_charge_month
        ).distinct().all()

        if not rooms_with_utilities:
            raise HTTPException(
                status_code=404, 
                detail=f"{year}년 {month}월에 청구되는 공과금이 있는 방이 없습니다."
            )

        # 각 방별 공과금 데이터 수집
        rooms_data = []
        
        for room in rooms_with_utilities:
            # 해당 방의 모든 공과금 조회
            utilities = db.query(RoomUtility).filter(
                RoomUtility.room_id == room.id,
                RoomUtility.charge_month == target_charge_month
            ).all()

            # 해당 방의 전월 거주자 조회 (임대료계산용)
            prev_month_residents = db.query(Resident).options(
                joinedload(Resident.student)
            ).filter(
                Resident.room_id == room.id,
                Resident.check_in_date <= end_date,
                (Resident.check_out_date.is_(None) | (Resident.check_out_date >= start_date))
            ).all()

            if not prev_month_residents:
                continue

            # 각 공과금별 학생별 배분 계산
            utilities_data = []
            
            for resident in prev_month_residents:
                for utility in utilities:
                    # 해당 유틸리티 기간 내 방 거주자 전체 쿼리
                    all_residents = db.query(Resident).filter(
                        Resident.room_id == room.id,
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

                    # 1일당 요금 계산 (소수점 버림)
                    per_day = int(float(utility.total_amount) / total_person_days) if total_person_days > 0 else 0

                    # 각 학생별 부담액 계산
                    resident_overlap_in = max(resident.check_in_date, utility.period_start)
                    resident_overlap_out = min(resident.check_out_date or utility.period_end, utility.period_end)
                    resident_overlap_days = (resident_overlap_out - resident_overlap_in).days + 1 if resident_overlap_in <= resident_overlap_out else 0
                    
                    resident_amount = per_day * resident_overlap_days

                    utility_data = {
                        "utility_type": utility.utility_type,
                        "period_start": utility.period_start.strftime("%Y-%m-%d") if utility.period_start else None,
                        "period_end": utility.period_end.strftime("%Y-%m-%d") if utility.period_end else None,
                        "total_amount": float(utility.total_amount) if utility.total_amount else 0,
                        "resident_overlap_days": resident_overlap_days,
                        "resident_amount": resident_amount,
                        "memo": utility.memo
                    }
                    utilities_data.append(utility_data)

            # 방별 총계
            room_total = sum(u["resident_amount"] for u in utilities_data)
            
            room_data = {
                "room_id": str(room.id),
                "room_number": room.room_number,
                "building_name": room.building.name if room.building else None,
                "residents": [
                    {
                        "student_id": str(r.resident_id),
                        "student_name": r.student.name if r.student else "Unknown",
                        "utilities": utilities_data
                    } for r in prev_month_residents
                ],
                "total_amount": room_total
            }
            rooms_data.append(room_data)

        # 전체 총계
        grand_total = sum(room["total_amount"] for room in rooms_data)
        
        return {
            "billing_period": f"{year}년 {month}월",
            "prev_month": f"{prev_year}년 {prev_month}월",
            "total_rooms": len(rooms_data),
            "rooms": rooms_data,
            "summary": {
                "total_amount": round(grand_total, 2),
                "total_utilities": len([u for r in rooms_data for u in r["residents"] for uu in u["utilities"]])
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"월간 청구서 다운로드 중 오류가 발생했습니다: {str(e)}")

@router.get("/monthly-invoice-preview/rooms/{year}/{month}")
def get_monthly_invoice_preview_by_rooms(
    year: int,
    month: int,
    building_id: Optional[str] = Query(None, description="건물 ID로 필터링"),
    db: Session = Depends(get_db)
):
    """방별 월간 청구서 미리보기"""
    try:
        # 년월 유효성 검사
        if not (1 <= month <= 12):
            raise HTTPException(status_code=400, detail="월은 1-12 사이여야 합니다")
        
        # 전달 기준으로 시작/종료일 계산 (예: 7월 조회 시 6월 1일~6월 30일)
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
            end_date = date(prev_year + 1, prev_month + 1, 1) - timedelta(days=1)

        target_charge_month = date(year, month, 1)

        # 공과금이 있는 방들 조회
        query = db.query(Room).options(
            joinedload(Room.building)
        ).join(RoomUtility).filter(
            RoomUtility.charge_month == target_charge_month
        )
        
        if building_id:
            # 특정 건물의 방들만 필터링
            query = query.filter(Room.building_id == building_id)
        
        rooms_with_utilities = query.distinct().all()

        # rooms_with_utilities가 없어도 임대료 정보는 포함해서 반환
        if not rooms_with_utilities:
            # 해당 월의 총 일수 계산
            if month == 12:
                month_end_date = date(year + 1, 1, 1) - timedelta(days=1)
            else:
                month_end_date = date(year, month + 1, 1) - timedelta(days=1)
            
            month_start_date = date(year, month, 1)
            total_days_in_month = (month_end_date - month_start_date).days + 1

            # 건물에 속한 학생들의 거주 정보 조회
            building_students = db.query(Resident).options(
                joinedload(Resident.student)
            ).join(Room).filter(
                Room.building_id == building_id if building_id else True,
                Resident.check_in_date <= month_end_date,
                (Resident.check_out_date.is_(None) | (Resident.check_out_date >= month_start_date))
            ).all()
            
            # 각 학생별 임대료 계산
            rent_data = []
            total_rent_amount = 0
            
            for resident in building_students:
                student_name = resident.student.name if resident.student else "Unknown"
                
                # 해당 월에 거주한 일수 계산
                check_in = max(resident.check_in_date, month_start_date)
                
                # 퇴실일이 None이면 해당 월 전체 거주로 인식
                if resident.check_out_date is None:
                    check_out = month_end_date
                else:
                    check_out = min(resident.check_out_date, month_end_date)

                # 해당 월에 거주한 일수 계산
                if check_in <= check_out:
                    days_in_month = (check_out - check_in).days + 1
                    
                    # 임대료 계산 (일수 기준)
                    if resident.room and resident.room.rent:
                        daily_rent = float(resident.room.rent) / total_days_in_month
                        rent_amount = daily_rent * days_in_month
                        total_rent_amount += rent_amount
                        
                        rent_data.append({
                            "student_name": student_name,
                            "room_number": resident.room.room_number,
                            "days_in_month": days_in_month,
                            "daily_rent": round(daily_rent, 2),
                            "rent_amount": round(rent_amount, 2)
                        })
            
            return {
                "billing_period": f"{year}년 {month}월",
                "prev_month": f"{prev_year}년 {prev_month}월",
                "total_rooms": 0,
                "rooms": [],
                "rent_summary": {
                    "total_students": len(rent_data),
                    "total_rent_amount": round(total_rent_amount, 2),
                    "rent_details": rent_data
                }
            }

        # 각 방별로 공과금 및 임대료 계산
        result = []
        total_monthly_amount = 0
        
        for room in rooms_with_utilities:
            # 해당 방의 공과금 조회
            utilities = db.query(RoomUtility).filter(
                RoomUtility.room_id == room.id,
                RoomUtility.charge_month == target_charge_month
            ).all()
            
            # 해당 방의 거주자 조회
            residents = db.query(Resident).options(
                joinedload(Resident.student)
            ).filter(
                Resident.room_id == room.id,
                Resident.check_in_date <= end_date,
                (Resident.check_out_date.is_(None) | (Resident.check_out_date >= start_date))
            ).all()
            
            if not residents:
                continue
            
            # 방별 총 요금 계산
            room_total = 0
            residents_data = []
            
            for resident in residents:
                # 해당 월에 거주한 일수 계산
                check_in = max(resident.check_in_date, start_date)
                check_out = min(resident.check_out_date or end_date, end_date)
                
                if check_in <= check_out:
                    days_in_month = (check_out - check_in).days + 1
                    
                    # 임대료 계산 (일수 기준)
                    if resident.room and resident.room.rent:
                        daily_rent = float(resident.room.rent) / total_days_in_month
                        rent_amount = daily_rent * days_in_month
                        room_total += rent_amount
                    
                    # 공과금 계산
                    for utility in utilities:
                        # 공과금 기간과 거주 기간이 겹치는지 확인
                        utility_start = utility.period_start
                        utility_end = utility.period_end
                        
                        overlap_start = max(check_in, utility_start)
                        overlap_end = min(check_out, utility_end)
                        
                        if overlap_start <= overlap_end:
                            overlap_days = (overlap_end - overlap_start).days + 1
                            utility_total_days = (utility_end - utility_start).days + 1
                            
                            # 비율 계산
                            ratio = overlap_days / utility_total_days if utility_total_days > 0 else 0
                            amount = float(utility.total_amount) * ratio if utility.total_amount else 0
                            room_total += amount
                    
                    residents_data.append({
                        "student_id": str(resident.resident_id),
                        "student_name": resident.student.name if resident.student else "Unknown",
                        "grade_name": resident.student.grade.name if resident.student and resident.student.grade else None,
                        "days_in_month": days_in_month,
                        "rent_amount": round(rent_amount, 2) if 'rent_amount' in locals() else 0
                    })
            
            # 방 정보 구성
            room_data = {
                "room_id": str(room.id),
                "room_number": room.room_number,
                "floor": room.floor,
                "capacity": room.capacity,
                "current_residents_count": len(residents),
                "building_name": room.building.name if room.building else None,
                "residents": residents_data,
                "room_total_amount": round(room_total, 2),
                "billing_period": f"{year}년 {month}월"
            }
            
            result.append(room_data)
            total_monthly_amount += room_total
        
        return {
            "billing_period": f"{year}년 {month}월",
            "prev_month": f"{prev_year}년 {prev_month}월",
            "total_rooms": len(result),
            "rooms": result,
            "summary": {
                "total_amount": round(total_monthly_amount, 2),
                "total_utilities": len([u for r in result for u in utilities if u.room_id == r["room_id"]])
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"건물 정보 조회 중 오류가 발생했습니다: {str(e)}") 