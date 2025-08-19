from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from typing import Optional
from database import SessionLocal, engine
from models import ElderlyMealRecord, ElderlyHospitalization, Resident, Room, Building, User, Elderly
from schemas import ElderlyHospitalizationCreate, ElderlyMealRecordCreate, ElderlyMealRecordResponse
from datetime import datetime, date, timedelta
import uuid
from database_log import create_database_log
from utils.dependencies import get_current_user

router = APIRouter(prefix="/elderly", tags=["고령자 관리"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/")
def get_elderly(
    name: Optional[str] = Query(None, description="고령자 이름으로 검색"),
    name_katakana: Optional[str] = Query(None, description="고령자 이름 카타카나로 검색"),
    gender: Optional[str] = Query(None, description="성별로 검색"),
    care_level: Optional[str] = Query(None, description="요양 등급으로 검색"),
    status: Optional[str] = Query(None, description="상태로 검색"),
    building_id: Optional[str] = Query(None, description="건물 아이디로 검색"),
    room_number: Optional[str] = Query(None, description="방 번호로 검색"),
    sort_by: Optional[str] = Query(None, description="정렬 필드 (name 또는 current_room.room_number)"),
    sort_desc: Optional[bool] = Query(False, description="내림차순 정렬 여부 (true: 내림차순, false: 오름차순)"),
    page: int = Query(1, description="페이지 번호", ge=1),
    page_size: int = Query(10, description="페이지당 항목 수", ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    고령자 목록을 조회합니다.
    """
    # 기본 쿼리 생성
    query = db.query(Elderly).options(
        joinedload(Elderly.current_room).joinedload(Room.building),
        joinedload(Elderly.category),
        joinedload(Elderly.hospitalizations)
    )
    
    # 검색 조건 적용
    if name:
        query = query.filter(Elderly.name.ilike(f"%{name}%"))
    
    if name_katakana:
        query = query.filter(Elderly.name_katakana.ilike(f"%{name_katakana}%"))
    
    if gender:
        query = query.filter(Elderly.gender == gender)
    
    if care_level:
        query = query.filter(Elderly.care_level == care_level)
    
    if status:
        query = query.filter(Elderly.status == status)
    
    if building_id:
        query = query.join(Room, Elderly.current_room_id == Room.id).join(Building, Room.building_id == Building.id)
        query = query.filter(Building.id == building_id)
    
    if room_number:
        query = query.join(Room, Elderly.current_room_id == Room.id)
        query = query.filter(Room.room_number.ilike(f"%{room_number}%"))
    
    # 정렬 적용
    if sort_by:
        if sort_by == "name":
            if sort_desc:
                query = query.order_by(Elderly.name.desc())
            else:
                query = query.order_by(Elderly.name.asc())
        elif sort_by == "current_room.room_number":
            # Room 테이블과 조인하여 방번호로 정렬
            query = query.outerjoin(Room, Elderly.current_room_id == Room.id)
            if sort_desc:
                query = query.order_by(Room.room_number.desc())
            else:
                query = query.order_by(Room.room_number.asc())
    else:
        # 기본 정렬: 생성일 기준 내림차순
        query = query.order_by(Elderly.created_at.desc())
    
    # 전체 개수 계산
    total_count = query.count()
    
    # 페이지네이션 적용
    offset = (page - 1) * page_size
    elderly_list = query.offset(offset).limit(page_size).all()
    
    # 응답 데이터 구성
    elderly_data = []
    for elderly in elderly_list:
        # 입원 상태 확인
        hospitalization_status = "正常"
        latest_hospitalization = None
        
        if elderly.hospitalizations:
            # 가장 최근 입원 기록 찾기
            latest_hospitalization = max(elderly.hospitalizations, key=lambda x: x.date)
            
            # 입원 기록이 있고 퇴원 기록이 없으면 입원중
            admission_records = [h for h in elderly.hospitalizations if h.hospitalization_type == 'admission']
            discharge_records = [h for h in elderly.hospitalizations if h.hospitalization_type == 'discharge']
            
            if admission_records and not discharge_records:
                # 입원 기록만 있고 퇴원 기록이 없으면 입원중
                hospitalization_status = "入院中"
            elif admission_records and discharge_records:
                # 입원과 퇴원 기록이 모두 있으면 최신 기록 확인
                latest_admission = max(admission_records, key=lambda x: x.date)
                latest_discharge = max(discharge_records, key=lambda x: x.date)
                
                if latest_admission.date > latest_discharge.date:
                    hospitalization_status = "入院中"
                else:
                    hospitalization_status = "正常"
        
        elderly_dict = {
        "id": str(elderly.id),
        "name": elderly.name,
            "email": elderly.email,
            "created_at": elderly.created_at,
            "phone": elderly.phone,
            "avatar": elderly.avatar,
        "name_katakana": elderly.name_katakana,
        "gender": elderly.gender,
            "birth_date": elderly.birth_date,
            "status": elderly.status,
            "current_room_id": str(elderly.current_room_id) if elderly.current_room_id else None,
            "care_level": elderly.care_level,
            "hospitalization_status": hospitalization_status,
            "latest_hospitalization": {
                "id": str(latest_hospitalization.id),
                "elderly_id": str(latest_hospitalization.elderly_id),
                "hospitalization_type": latest_hospitalization.hospitalization_type,
                "hospital_name": latest_hospitalization.hospital_name,
                "date": latest_hospitalization.date,
                "last_meal_date": latest_hospitalization.last_meal_date,
                "last_meal_type": latest_hospitalization.last_meal_type,
                "meal_resume_date": latest_hospitalization.meal_resume_date,
                "meal_resume_type": latest_hospitalization.meal_resume_type,
                "note": latest_hospitalization.note
            } if latest_hospitalization else None,
            "current_room": None
        }
        
        # 현재 방 정보 추가
        if elderly.current_room:
            elderly_dict["current_room"] = {
                "id": str(elderly.current_room.id),
                "room_number": elderly.current_room.room_number,
                "floor": elderly.current_room.floor,
                "capacity": elderly.current_room.capacity,
                "rent": elderly.current_room.rent,
                "maintenance": elderly.current_room.maintenance,
                "service": elderly.current_room.service,
                "note": elderly.current_room.note,
                "building": {
                    "id": str(elderly.current_room.building.id),
                    "name": elderly.current_room.building.name,
                    "address": elderly.current_room.building.address,
                    "resident_type": elderly.current_room.building.resident_type
                } if elderly.current_room.building else None
            }
        
        elderly_data.append(elderly_dict)
    
    return {
        "items": elderly_data,
        "total": total_count,
        "total_pages": (total_count + page_size - 1) // page_size
    }


@router.get("/meal-records/monthly/{building_id}")
def get_elderly_meal_records_monthly_by_building(
    building_id: str,
    year: int,
    month: int,
    db: Session = Depends(get_db)
):
    """건물별 고령자 식사 기록 월간 조회"""
    try:
        # 건물 존재 여부 확인
        building = db.query(Building).filter(Building.id == building_id).first()
        if not building:
            raise HTTPException(status_code=404, detail="建物が見つかりません")
        
        # 해당 건물의 모든 방 조회
        rooms = db.query(Room).filter(Room.building_id == building_id).all()
        if not rooms:
            return {
                "building_id": building_id,
                "building_name": building.name,
                "year": year,
                "month": month,
                "residents_data": []
            }
        
        # 해당 월의 시작일과 종료일 계산
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = date(year, month + 1, 1) - timedelta(days=1)
        
        # 각 방의 거주자 정보와 식사 기록 조회
        residents_data = []
        for room in rooms:
            # 방에 거주 중인 고령자 조회
            residents = db.query(Resident).filter(
                Resident.room_id == room.id,
                Resident.status == "active"
            ).all()
            
            for resident in residents:
                # 해당 월의 식사 기록 조회
                meal_records = db.query(ElderlyMealRecord).filter(
                    ElderlyMealRecord.elderly_id == resident.id,
                    ElderlyMealRecord.date >= start_date,
                    ElderlyMealRecord.date <= end_date
                ).order_by(ElderlyMealRecord.date.asc()).all()
                
                # 해당 월의 입원 기록 조회
                resident_hospitalizations = db.query(ElderlyHospitalization).filter(
                    ElderlyHospitalization.elderly_id == resident.id,
                    ElderlyHospitalization.date >= start_date,
                    ElderlyHospitalization.date <= end_date
                ).order_by(ElderlyHospitalization.date.asc()).all()
                
                # 거주자 데이터 구성
                resident_data = {
                    "resident_id": str(resident.id),
                    "name": resident.name,
                    "room_number": room.room_number,
                    "daily_records": [], # daily_records는 이제 포함하지 않음
                    "hospitalizations": [
                        {
                            "elderly_id": str(h.elderly_id),
                            "hospitalization_type": h.hospitalization_type,
                            "hospital_name": h.hospital_name,
                            "last_meal_date": h.last_meal_date,
                            "last_meal_type": h.last_meal_type,
                            "meal_resume_date": h.meal_resume_date,
                            "meal_resume_type": h.meal_resume_type,
                            "note": h.note
                        } for h in resident_hospitalizations
                    ]
                }
                
                residents_data.append(resident_data)
        
        return {
            "building_id": building_id,
            "building_name": building.name,
            "year": year,
            "month": month,
            "residents_data": residents_data
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"高齢者食事記録の取得中にエラーが発生しました: {str(e)}")

@router.post("/hospitalization")
def create_elderly_hospitalization(
    hospitalization_data: ElderlyHospitalizationCreate,
    db: Session = Depends(get_db)
):
    """고령자 입원/퇴원 기록 생성"""
    try:
        # 고령자 존재 여부 확인
        resident = db.query(Resident).filter(Resident.id == hospitalization_data.elderly_id).first()
        if not resident:
            raise HTTPException(status_code=404, detail="高齢者が見つかりません")
        
        # 퇴원 기록인 경우 기존 입원 기록 업데이트
        if hospitalization_data.hospitalization_type == "discharge":
            existing_hospitalization = db.query(ElderlyHospitalization).filter(
                ElderlyHospitalization.elderly_id == hospitalization_data.elderly_id,
                ElderlyHospitalization.hospitalization_type == "admission",
                ElderlyHospitalization.meal_resume_date.is_(None)
            ).order_by(ElderlyHospitalization.date.desc()).first()
            
            if existing_hospitalization:
                existing_hospitalization.hospitalization_type = "discharge"
                existing_hospitalization.meal_resume_date = hospitalization_data.meal_resume_date
                existing_hospitalization.meal_resume_type = hospitalization_data.meal_resume_type
                existing_hospitalization.note = hospitalization_data.note
                db.commit()
                db.refresh(existing_hospitalization)
                return {
                    "message": f"退院記録が既存入院記録に更新されました。",
                    "hospitalization": {
                        "id": str(existing_hospitalization.id),
                        "elderly_id": str(existing_hospitalization.elderly_id),
                        "hospitalization_type": existing_hospitalization.hospitalization_type,
                        "hospital_name": existing_hospitalization.hospital_name,
                        "last_meal_date": existing_hospitalization.last_meal_date,
                        "last_meal_type": existing_hospitalization.last_meal_type,
                        "meal_resume_date": existing_hospitalization.meal_resume_date,
                        "meal_resume_type": existing_hospitalization.meal_resume_type,
                        "note": existing_hospitalization.note
                    }
                }
            else:
                raise HTTPException(status_code=404, detail="該当の高齢者の未完了入院記録が見つかりません")
        
        # 새로운 입원 기록 생성
        new_hospitalization = ElderlyHospitalization(
            id=str(uuid.uuid4()),
            elderly_id=hospitalization_data.elderly_id,
            hospitalization_type=hospitalization_data.hospitalization_type,
            hospital_name=hospitalization_data.hospital_name,
            date=hospitalization_data.date,
            last_meal_date=hospitalization_data.last_meal_date,
            last_meal_type=hospitalization_data.last_meal_type,
            meal_resume_date=hospitalization_data.meal_resume_date,
            meal_resume_type=hospitalization_data.meal_resume_type,
            note=hospitalization_data.note
        )
        
        db.add(new_hospitalization)
        db.commit()
        db.refresh(new_hospitalization)
        
        return {
            "message": f"入院記録が正常に作成されました。",
            "hospitalization": {
                "id": str(new_hospitalization.id),
                "elderly_id": str(new_hospitalization.elderly_id),
                "hospitalization_type": new_hospitalization.hospitalization_type,
                "hospital_name": new_hospitalization.hospital_name,
                "date": new_hospitalization.date,
                "last_meal_date": new_hospitalization.last_meal_date,
                "last_meal_type": new_hospitalization.last_meal_type,
                "meal_resume_date": new_hospitalization.meal_resume_date,
                "meal_resume_type": new_hospitalization.meal_resume_type,
                "note": new_hospitalization.note
            }
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"入院記録作成中にエラーが発生しました: {str(e)}")

@router.get("/hospitalization/{elderly_id}")
def get_elderly_hospitalization_history(
    elderly_id: str,
    page: int = Query(1, description="페이지 번호", ge=1),
    page_size: int = Query(10, description="페이지당 항목 수", ge=1, le=100),
    db: Session = Depends(get_db)
):
    """고령자의 입원/퇴원 기록 히스토리 조회"""
    try:
        # 고령자 존재 여부 확인
        resident = db.query(Resident).filter(Resident.id == elderly_id).first()
        if not resident:
            raise HTTPException(status_code=404, detail="高齢者が見つかりません")
        
        # 입원/퇴원 기록 조회
        query = db.query(ElderlyHospitalization).filter(
            ElderlyHospitalization.elderly_id == elderly_id
        ).order_by(ElderlyHospitalization.date.desc())
        
        # 전체 항목 수 계산
        total_count = query.count()
        
        # 페이지네이션 적용
        hospitalizations = query.offset((page - 1) * page_size).limit(page_size).all()
        
        # 전체 페이지 수 계산
        total_pages = (total_count + page_size - 1) // page_size
        
        # 응답 데이터 준비
        result = []
        for hospitalization in hospitalizations:
            hospitalization_data = {
                "id": str(hospitalization.id),
                "elderly_id": str(hospitalization.elderly_id),
                "hospitalization_type": hospitalization.hospitalization_type,
                "hospital_name": hospitalization.hospital_name,
                "date": hospitalization.date,
                "last_meal_date": hospitalization.last_meal_date,
                "last_meal_type": hospitalization.last_meal_type,
                "meal_resume_date": hospitalization.meal_resume_date,
                "meal_resume_type": hospitalization.meal_resume_type,
                "note": hospitalization.note
            }
            result.append(hospitalization_data)
        
        return {
            "elderly_id": elderly_id,
            "elderly_name": resident.name,
            "items": result,
            "total": total_count,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_previous": page > 1
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"入院記録履歴の取得中にエラーが発生しました: {str(e)}") 


@router.post("/hospitalizations")
def create_elderly_hospitalization(
    hospitalization_data: ElderlyHospitalizationCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """거주자 입원/퇴원 기록을 생성합니다."""
    try:
        # 노인 존재 여부 확인
        elderly = db.query(Elderly).filter(Elderly.id == hospitalization_data.elderly_id).first()
        if not elderly:
            raise HTTPException(status_code=404, detail="노인을 찾을 수 없습니다")
        
        # 퇴원 등록인 경우 기존 입원 기록 찾기
        if hospitalization_data.hospitalization_type == "discharge":
            existing_hospitalization = db.query(ElderlyHospitalization).filter(
                ElderlyHospitalization.elderly_id == hospitalization_data.elderly_id,
                ElderlyHospitalization.hospitalization_type == "admission",
                ElderlyHospitalization.meal_resume_date.is_(None)  # 퇴원 기록이 없는 입원 기록
            ).order_by(ElderlyHospitalization.date.desc()).first()
            
            if existing_hospitalization:
                # 기존 입원 기록 업데이트
                existing_hospitalization.hospitalization_type = "discharge"
                existing_hospitalization.meal_resume_date = hospitalization_data.meal_resume_date
                existing_hospitalization.meal_resume_type = hospitalization_data.meal_resume_type
                existing_hospitalization.note = hospitalization_data.note
                
                db.commit()
                db.refresh(existing_hospitalization)
                
                return {
                    "message": f"퇴원 기록이 기존 입원 기록에 업데이트되었습니다.",
                    "item": {
                        "id": str(existing_hospitalization.id),
                        "elderly_id": str(existing_hospitalization.elderly_id),
                        "hospitalization_type": existing_hospitalization.hospitalization_type,
                        "hospital_name": existing_hospitalization.hospital_name,
                        "date": existing_hospitalization.date,
                        "meal_resume_date": existing_hospitalization.meal_resume_date,
                        "meal_resume_type": existing_hospitalization.meal_resume_type
                    }
                }
            else:
                raise HTTPException(status_code=404, detail="해당 노인의 미완료 입원 기록을 찾을 수 없습니다")
        
        # 입원 기록 생성 (기존 로직)
        hospitalization = ElderlyHospitalization(
            elderly_id=hospitalization_data.elderly_id,
            hospitalization_type=hospitalization_data.hospitalization_type,
            hospital_name=hospitalization_data.hospital_name,
            date=hospitalization_data.date,
            last_meal_date=hospitalization_data.last_meal_date,
            last_meal_type=hospitalization_data.last_meal_type,
            meal_resume_date=hospitalization_data.meal_resume_date,
            meal_resume_type=hospitalization_data.meal_resume_type,
            note=hospitalization_data.note,
            created_by=current_user.get("name", "Unknown")
        )
        
        db.add(hospitalization)
        db.commit()
        db.refresh(hospitalization)
        
        return {
            "message": f"입원 기록이 정상적으로 생성되었습니다.",
            "item": {
              "id": str(hospitalization.id),
              "elderly_id": str(hospitalization.elderly_id),
              "hospitalization_type": hospitalization.hospitalization_type,
              "hospital_name": hospitalization.hospital_name,
              "date": hospitalization.date
            }
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"입원/퇴원 기록 생성 중 오류가 발생했습니다: {str(e)}")

@router.get("/hospitalizations/{year}/{month}")
def get_elderly_hospitalizations_by_month(
    year: int,
    month: int,
    elderly_id: Optional[str] = Query(None, description="특정 고령자 ID로 필터링"),
    hospitalization_type: Optional[str] = Query(None, description="입원/퇴원 유형으로 필터링 (admission 또는 discharge)"),
    page: int = Query(1, description="페이지 번호", ge=1),
    page_size: int = Query(10, description="페이지당 항목 수", ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """특정 연도와 달의 병원 입퇴원 기록을 조회합니다."""
    try:
        # 연도와 달 유효성 검사
        if year < 1900 or year > 2100:
            raise HTTPException(status_code=400, detail="유효하지 않은 연도입니다")
        if month < 1 or month > 12:
            raise HTTPException(status_code=400, detail="유효하지 않은 월입니다")
        
        # 해당 월의 시작일과 종료일 계산
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = date(year, month + 1, 1) - timedelta(days=1)
        
        # 기본 쿼리 생성
        query = db.query(ElderlyHospitalization).filter(
            ElderlyHospitalization.date >= start_date,
            ElderlyHospitalization.date <= end_date
        )
        
        # 필터링 조건 추가
        if elderly_id:
            query = query.filter(ElderlyHospitalization.elderly_id == elderly_id)
        
        if hospitalization_type:
            query = query.filter(ElderlyHospitalization.hospitalization_type == hospitalization_type)
        
        # 총 개수 계산
        total_count = query.count()
        
        # 페이지네이션 적용
        offset = (page - 1) * page_size
        hospitalizations = query.order_by(ElderlyHospitalization.date.desc()).offset(offset).limit(page_size).all()
        
        # 응답 데이터 구성
        hospitalization_data = []
        for hospitalization in hospitalizations:
            # 고령자 정보 조회
            elderly = db.query(Elderly).filter(Elderly.id == hospitalization.elderly_id).first()
            
            hospitalization_dict = {
                "id": str(hospitalization.id),
                "elderly_id": str(hospitalization.elderly_id),
                "elderly_name": elderly.name if elderly else "Unknown",
                "elderly_name_katakana": elderly.name_katakana if elderly else None,
                "hospitalization_type": hospitalization.hospitalization_type,
                "hospital_name": hospitalization.hospital_name,
                "date": hospitalization.date,
                "last_meal_date": hospitalization.last_meal_date,
                "last_meal_type": hospitalization.last_meal_type,
                "meal_resume_date": hospitalization.meal_resume_date,
                "meal_resume_type": hospitalization.meal_resume_type,
                "note": hospitalization.note,
                "created_at": hospitalization.created_at,
                "created_by": hospitalization.created_by,
                "elderly": {
                    "id": str(elderly.id),
                    "name": elderly.name,
                    "name_katakana": elderly.name_katakana,
                    "gender": elderly.gender,
                    "care_level": elderly.care_level,
                    "current_room": {
                        "id": str(elderly.current_room.id),
                        "room_number": elderly.current_room.room_number,
                        "building": {
                            "id": str(elderly.current_room.building.id),
                            "name": elderly.current_room.building.name
                        } if elderly.current_room and elderly.current_room.building else None
                    } if elderly.current_room else None
                } if elderly else None
            }
            hospitalization_data.append(hospitalization_dict)
        
        # 월별 통계 계산
        admission_count = len([h for h in hospitalizations if h.hospitalization_type == 'admission'])
        discharge_count = len([h for h in hospitalizations if h.hospitalization_type == 'discharge'])
        unique_elderly_count = len(set(h.elderly_id for h in hospitalizations))
        
        return {
            "year": year,
            "month": month,
            "start_date": str(start_date),
            "end_date": str(end_date),
            "items": hospitalization_data,
            "total": total_count,
            "total_pages": (total_count + page_size - 1) // page_size,
            "current_page": page,
            "page_size": page_size,
            "statistics": {
                "total_hospitalizations": len(hospitalizations),
                "admission_count": admission_count,
                "discharge_count": discharge_count,
                "unique_elderly_count": unique_elderly_count
            }
        }
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"날짜 계산 중 오류가 발생했습니다: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"병원 입퇴원 기록 조회 중 오류가 발생했습니다: {str(e)}")
    
@router.get("/meal-records/monthly-building/{building_id}/{year}/{month}")
def get_elderly_meal_records_monthly_by_building(
    building_id: str,
    year: int,
    month: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """특정 빌딩의 노인 거주자들의 월별 식사 건너뛴 기록 조회"""
    # 빌딩 존재 여부 확인
    building = db.query(Building).filter(Building.id == building_id).first()
    if not building:
        raise HTTPException(status_code=404, detail="빌딩을 찾을 수 없습니다")

    # 년도, 월 유효성 검사
    if year < 1900 or year > 2100:
        raise HTTPException(status_code=400, detail="년도가 올바르지 않습니다")
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="월이 올바르지 않습니다")

    try:
        # 해당 월의 시작일과 종료일 계산
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = date(year, month + 1, 1) - timedelta(days=1)
        
        # 해당 빌딩의 노인 거주자들 조회
        elderly_residents = db.query(Resident).options(
            joinedload(Resident.elderly),
            joinedload(Resident.room).joinedload(Room.building)
        ).filter(
            Resident.resident_type == "elderly",
            Resident.is_active == True,
            Resident.room.has(Room.building_id == building_id)
        ).all()

        if not elderly_residents:
            return {
                "building": {
                    "id": str(building.id),
                    "name": building.name
                },
                "year": year,
                "month": month,
                "start_date": str(start_date),
                "end_date": str(end_date),
                "daily_records": [],
                "residents": [],
                "monthly_statistics": {
                    "total_breakfast_skipped": 0,
                    "total_lunch_skipped": 0,
                    "total_dinner_skipped": 0,
                    "total_meals_skipped": 0,
                    "total_elderly_residents": 0,
                    "total_residents_with_skips": 0,
                    "average_meals_skipped_per_resident": 0
                }
            }

        # 해당 월의 식사 기록 조회 (해당 빌딩의 노인 거주자들만)
        resident_ids = [str(resident.id) for resident in elderly_residents]
        records = db.query(ElderlyMealRecord).options(
            joinedload(ElderlyMealRecord.resident).joinedload(Resident.elderly)
        ).filter(
            ElderlyMealRecord.skip_date >= start_date,
            ElderlyMealRecord.skip_date <= end_date,
            ElderlyMealRecord.resident_id.in_(resident_ids)
        ).order_by(ElderlyMealRecord.skip_date, ElderlyMealRecord.meal_type).all()

        # 1일부터 31일까지의 모든 날짜에 대해 데이터 구성
        monthly_data = {}
        for day in range(1, 32):
            current_date = date(year, month, day)
            # 해당 월에 실제로 존재하는 날짜인지 확인
            if current_date.month == month:
                monthly_data[day] = {
                    "date": current_date,
                    "breakfast": 0,
                    "lunch": 0,
                    "dinner": 0,
                    "total_skipped": 0,
                    "residents_skipped": set()
                }

        # 해당 월의 입원 기록 조회 (해당 빌딩의 노인 거주자들만)
        elderly_ids = [str(resident.elderly.id) for resident in elderly_residents if resident.elderly]
        hospitalization_records = db.query(ElderlyHospitalization).filter(
            ElderlyHospitalization.date >= start_date,
            ElderlyHospitalization.date <= end_date,
            ElderlyHospitalization.elderly_id.in_(elderly_ids)
        ).order_by(ElderlyHospitalization.date).all()

        # 조회된 기록을 월별 데이터에 반영
        for record in records:
            day = record.skip_date.day
            if day in monthly_data:
                monthly_data[day][record.meal_type] += 1
                monthly_data[day]["total_skipped"] += 1
                monthly_data[day]["residents_skipped"].add(str(record.resident_id))

        # 응답 데이터 준비
        daily_records = []
        for day, data in monthly_data.items():
            daily_record = {
                "day": day,
                "date": str(data["date"]),
                "breakfast": data["breakfast"],
                "lunch": data["lunch"],
                "dinner": data["dinner"],
                "total_skipped": data["total_skipped"],
                "residents_skipped_count": len(data["residents_skipped"])
            }
            daily_records.append(daily_record)

        # 거주자별 개별 통계 및 일별 상세 데이터 계산
        residents_data = []
        for resident in elderly_residents:
            resident_records = [r for r in records if str(r.resident_id) == str(resident.id)]
            
            # 거주자별 일별 데이터 구성 (1일~31일)
            resident_daily_data = {}
            for day in range(1, 32):
                current_date = date(year, month, day)
                if current_date.month == month:
                    resident_daily_data[day] = {
                        "day": day,
                        "date": str(current_date),
                        "breakfast": False,
                        "lunch": False,
                        "dinner": False,
                        "total_skipped": 0
                    }
            
            # 해당 거주자의 기록을 일별 데이터에 반영
            for record in resident_records:
                day = record.skip_date.day
                if day in resident_daily_data:
                    resident_daily_data[day][record.meal_type] = True
                    resident_daily_data[day]["total_skipped"] += 1
            
            # 일별 데이터를 배열로 변환
            daily_records_array = []
            for day, data in resident_daily_data.items():
                daily_records_array.append(data)
            
            # 거주자별 통계 계산
            breakfast_skipped = len([r for r in resident_records if r.meal_type == "breakfast"])
            lunch_skipped = len([r for r in resident_records if r.meal_type == "lunch"])
            dinner_skipped = len([r for r in resident_records if r.meal_type == "dinner"])
            total_skipped = breakfast_skipped + lunch_skipped + dinner_skipped
            
            # 해당 거주자의 입원 기록 조회
            resident_hospitalizations = []
            if resident.elderly:
                resident_hospitalizations = [h for h in hospitalization_records if str(h.elderly_id) == str(resident.elderly.id)]
            
            residents_data.append({
                "resident_id": str(resident.id),
                "resident_name": resident.elderly.name if resident.elderly else "Unknown",
                "room_number": resident.room.room_number if resident.room else None,
                "breakfast_skipped": breakfast_skipped,
                "lunch_skipped": lunch_skipped,
                "dinner_skipped": dinner_skipped,
                "total_skipped": total_skipped,
                "days_with_skips": len(set(r.skip_date.day for r in resident_records)),
                "daily_records": daily_records_array,  # 1일~31일 상세 데이터
                "hospitalizations": [
                    {
                        "elderly_id": str(h.elderly_id),
                        "hospitalization_type": h.hospitalization_type,
                        "hospital_name": h.hospital_name,
                        "last_meal_date": h.last_meal_date,
                        "last_meal_type": h.last_meal_type,
                        "meal_resume_date": h.meal_resume_date,
                        "meal_resume_type": h.meal_resume_type,
                        "note": h.note
                    } for h in resident_hospitalizations
                ]
            })

        # 월별 통계 계산
        total_breakfast_skipped = sum(data["breakfast"] for data in monthly_data.values())
        total_lunch_skipped = sum(data["lunch"] for data in monthly_data.values())
        total_dinner_skipped = sum(data["dinner"] for data in monthly_data.values())
        total_meals_skipped = total_breakfast_skipped + total_lunch_skipped + total_dinner_skipped
        
        # 식사를 건너뛴 노인 수 (중복 제거)
        all_residents_with_skips = set()
        for data in monthly_data.values():
            all_residents_with_skips.update(data["residents_skipped"])
        
        total_residents_with_skips = len(all_residents_with_skips)
        total_elderly_residents = len(elderly_residents)

        return {
            "building": {
                "id": str(building.id),
                "name": building.name
            },
            "year": year,
            "month": month,
            "start_date": str(start_date),
            "end_date": str(end_date),
            "daily_records": daily_records,
            "residents": residents_data,
            "monthly_statistics": {
                "total_breakfast_skipped": total_breakfast_skipped,
                "total_lunch_skipped": total_lunch_skipped,
                "total_dinner_skipped": total_dinner_skipped,
                "total_meals_skipped": total_meals_skipped,
                "total_elderly_residents": total_elderly_residents,
                "total_residents_with_skips": total_residents_with_skips,
                "average_meals_skipped_per_resident": round(total_meals_skipped / max(total_elderly_residents, 1), 2)
            }
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"날짜 계산 중 오류가 발생했습니다: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"빌딩별 월별 식사 기록 조회 중 오류가 발생했습니다: {str(e)}")
    

# 노인 식사 기록 관련 API들
@router.post("/meal-records", response_model=ElderlyMealRecordResponse)
def create_elderly_meal_record(
    meal_record: ElderlyMealRecordCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """노인 식사 건너뛴 기록 등록"""
    # 거주자 존재 여부 확인
    resident = db.query(Resident).filter(Resident.id == meal_record.resident_id).first()
    if not resident:
        raise HTTPException(status_code=404, detail="거주자를 찾을 수 없습니다")

    # 날짜 형식 검증
    try:
        if isinstance(meal_record.skip_date, str):
            record_date = datetime.strptime(meal_record.skip_date, "%Y-%m-%d").date()
        else:
            record_date = meal_record.skip_date
    except ValueError:
        raise HTTPException(status_code=400, detail="날짜 형식이 올바르지 않습니다 (YYYY-MM-DD)")

    # 이미 같은 날짜, 같은 식사 유형의 기록이 있는지 확인
    existing_record = db.query(ElderlyMealRecord).filter(
        ElderlyMealRecord.resident_id == meal_record.resident_id,
        ElderlyMealRecord.skip_date == record_date,
        ElderlyMealRecord.meal_type == meal_record.meal_type
    ).first()

    if existing_record:
        # 기존 기록이 있으면 삭제 (토글 기능)
        try:
            # 삭제 전 값 저장 (로그용)
            old_values = {
                "resident_id": str(existing_record.resident_id),
                "date": str(existing_record.skip_date),
                "meal_type": existing_record.meal_type
            }
            
            db.delete(existing_record)
            db.commit()
            
            # 로그 생성
            create_database_log(
                db=db,
                table_name="elderly_meal_records",
                record_id=str(existing_record.id),
                action="DELETE",
                user_id=current_user["id"] if current_user else None,
                old_values=old_values,
                note="노인 식사 기록 토글 삭제 (취소)"
            )
            
            return {
                "message": "식사 기록이 취소되었습니다",
                "action": "cancelled",
                "id": str(existing_record.id),
                "resident_id": str(existing_record.resident_id),
                "skip_date": existing_record.skip_date,
                "meal_type": existing_record.meal_type,
                "created_at": existing_record.created_at,
                "resident": {
                    "id": str(resident.id),
                    "resident_type": resident.resident_type,
                    "elderly": {
                        "id": str(resident.elderly.id),
                        "name": resident.elderly.name
                    } if resident.elderly else None
                }
            }
            
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"식사 기록 취소 중 오류가 발생했습니다: {str(e)}"
            )

    try:
        # 새로운 식사 기록 등록
        new_record = ElderlyMealRecord(
        id=str(uuid.uuid4()),
            resident_id=meal_record.resident_id,
            skip_date=record_date,
            meal_type=meal_record.meal_type
        )
        db.add(new_record)
        db.commit()
        db.refresh(new_record)
        
        # 로그 생성
        create_database_log(
            db=db,
            table_name="elderly_meal_records",
            record_id=str(new_record.id),
            action="CREATE",
            user_id=current_user["id"] if current_user else None,
            new_values={
                "resident_id": str(new_record.resident_id),
                "date": str(new_record.skip_date),
                "meal_type": new_record.meal_type
            },
            note="노인 식사 건너뛴 기록 등록"
        )

        # 응답 데이터 준비
        response_data = {
          "message": "식사 기록이 등록되었습니다",
          "action": "created",
          "id": str(new_record.id),
          "resident_id": str(new_record.resident_id),
          "skip_date": new_record.skip_date,
          "meal_type": new_record.meal_type,
          "created_at": new_record.created_at,
          "resident": {
              "id": str(resident.id),
              "resident_type": resident.resident_type,
              "elderly": {
                  "id": str(resident.elderly.id),
                  "name": resident.elderly.name
              } if resident.elderly else None
          }
        }

        return response_data

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"식사 기록 등록 중 오류가 발생했습니다: {str(e)}"
        )
