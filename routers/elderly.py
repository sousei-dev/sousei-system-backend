from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from typing import Optional, List
from database import SessionLocal, engine
from models import ElderlyMealRecord, ElderlyHospitalization, Resident, Room, Building, User, Elderly, Profiles, PushSubscription, ElderlyCategories, BuildingCategoriesRent, ElderlyContract
from schemas import ElderlyHospitalizationCreate, ElderlyMealRecordCreate, ElderlyMealRecordResponse, NewResidenceRequest, ElderlyCreate, ElderlyUpdate
from datetime import datetime, date, timedelta
import uuid
import calendar
import json
from database_log import create_database_log
from utils.dependencies import get_current_user
from pywebpush import webpush, WebPushException

router = APIRouter(prefix="/elderly", tags=["고령자 관리"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_vapid_private_key():
    """VAPID 개인키를 가져옵니다. (main.py와 동일한 방식)"""
    try:
        import os
        
        # 1. 파일 경로에서 개인키 로드 시도
        vapid_private_key_path = os.getenv("VAPID_PRIVATE_KEY_PATH", "vapid_private_key.pem")
        if os.path.exists(vapid_private_key_path):
            print(f"VAPID 개인키 파일 사용: {vapid_private_key_path}")
            return vapid_private_key_path
        
        # 2. 환경변수에서 직접 가져오기
        vapid_private_key = os.getenv("VAPID_PRIVATE_KEY")
        if vapid_private_key:
            print("환경변수에서 VAPID 개인키 사용")
            return vapid_private_key
        
        print("VAPID 개인키를 찾을 수 없습니다.")
        return None
    except Exception as e:
        print(f"VAPID 개인키 로드 중 오류: {e}")
        return None

def get_vapid_claims(endpoint: str):
    """VAPID 클레임을 생성합니다. (main.py와 동일한 방식)"""
    try:
        from urllib.parse import urlparse
        
        parsed_url = urlparse(endpoint)
        aud = f"{parsed_url.scheme}://{parsed_url.netloc}"
        
        claims = {
            "sub": "mailto:dev@sousei-group.com",
            "aud": aud
        }
        
        print(f"VAPID 클레임 생성: endpoint={endpoint}, claims={claims}")
        return claims
    except Exception as e:
        print(f"VAPID 클레임 생성 중 오류: {e}")
        default_claims = {
            "sub": "mailto:dev@sousei-group.com",
            "aud": "https://fcm.googleapis.com"  # 기본값
        }
        print(f"기본 VAPID 클레임 사용: {default_claims}")
        return default_claims

async def get_admin_and_mishima_users(db: Session) -> List[str]:
    """admin과 mishima_user 역할을 가진 사용자 ID 목록을 반환"""
    try:
        # Profiles 테이블에서 admin과 mishima_user 역할을 가진 사용자 조회
        admin_users = db.query(Profiles.id).filter(
            Profiles.role.in_(["admin", "mishima_user"])
        ).all()
        
        return [str(user.id) for user in admin_users]
    except Exception as e:
        print(f"admin/mishima_user 조회 중 오류: {e}")
        return []

async def send_hospitalization_notification(
    db: Session, 
    elderly_name: str, 
    hospital_name: str, 
    action_type: str,  # "admission" 또는 "discharge"
    elderly_id: str
):
    """입원/퇴원 웹푸시 알림을 admin과 mishima_user에게 전송"""
    try:
        # admin과 mishima_user 조회
        target_users = await get_admin_and_mishima_users(db)
        
        if not target_users:
            print("알림을 받을 사용자가 없습니다.")
            return
        
        # VAPID 개인키 가져오기
        vapid_private_key = get_vapid_private_key()
        if not vapid_private_key:
            print("VAPID 개인키를 가져올 수 없습니다.")
            return
        
        # 알림 메시지 구성
        action_text = "入院" if action_type == "admission" else "退院"
        title = f"高齢者{action_text}通知"
        body = f"{elderly_name}さんが{hospital_name}に{action_text}されました。"
        
        # 각 사용자에게 웹푸시 알림 전송
        sent_count = 0
        for user_id in target_users:
            try:
                # 사용자의 푸시 구독 정보 조회
                subscriptions = db.query(PushSubscription).filter(
                    PushSubscription.user_id == user_id
                ).all()
                
                if not subscriptions:
                    print(f"사용자 {user_id}의 푸시 구독 정보가 없습니다")
                    continue
                
                # 각 구독에 대해 푸시 알림 전송
                for subscription in subscriptions:
                    try:
                        subscription_info = {
                            "endpoint": subscription.endpoint,
                            "keys": {
                                "p256dh": subscription.p256dh,
                                "auth": subscription.auth
                            }
                        }
                        
                        # 푸시 페이로드 생성
                        push_data = {
                            "type": "hospitalization_notification",
                            "elderly_name": elderly_name,
                            "hospital_name": hospital_name,
                            "action_type": action_type,
                            "elderly_id": elderly_id
                        }
                        
                        payload = {
                            "notification": {
                                "title": title,
                                "body": body,
                                "icon": "/static/icons/icon-192x192.png",
                                "badge": "/static/icons/badge-72x72.png",
                                "vibrate": [200, 100, 200],
                                "tag": f"hospitalization-{action_type}-{datetime.utcnow().timestamp()}",
                                "requireInteraction": True,
                                "data": push_data
                            }
                        }
                        
                        # VAPID 클레임 생성
                        vapid_claims = get_vapid_claims(subscription.endpoint)
                        
                        # 웹푸시 전송
                        webpush(
                            subscription_info=subscription_info,
                            data=json.dumps(payload),
                            vapid_private_key=vapid_private_key,
                            vapid_claims=vapid_claims,
                            ttl=86400,  # 24시간
                            headers={
                                "Urgency": "high"
                            }
                        )
                        
                        print(f"웹푸시 알림 전송 성공: 사용자 {user_id}")
                        
                    except WebPushException as ex:
                        print(f"웹푸시 알림 전송 실패 (사용자: {user_id}, 구독 ID: {subscription.id}): {ex}")
                        if ex.response and ex.response.status_code == 410:
                            # 만료된 구독 삭제
                            db.delete(subscription)
                            db.commit()
                            print(f"만료된 구독 삭제: {subscription.id}")
                    except Exception as e:
                        print(f"웹푸시 알림 전송 중 오류 (사용자: {user_id}): {e}")
                
                sent_count += 1
                
            except Exception as e:
                print(f"사용자 {user_id} 웹푸시 알림 전송 중 오류: {e}")
        
        print(f"총 {sent_count}명에게 입원/퇴원 웹푸시 알림 전송 완료")
        
    except Exception as e:
        print(f"입원/퇴원 웹푸시 알림 전송 중 오류: {e}")

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
    
    # building_id 또는 room_number 필터가 있으면 Room 조인 (한 번만)
    needs_room_join = building_id or room_number
    if needs_room_join:
        query = query.join(Room, Elderly.current_room_id == Room.id)
    
    if building_id:
        query = query.join(Building, Room.building_id == Building.id)
        query = query.filter(Building.id == building_id)
    
    if room_number:
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
        # 입원 상태 확인 (새로운 스키마)
        hospitalization_status = "正常"
        latest_hospitalization = None
        
        if elderly.hospitalizations:
            # 가장 최근 입원 기록 찾기
            latest_hospitalization = max(elderly.hospitalizations, key=lambda x: x.admission_date)
            
            # 퇴원일이 없는 기록이 있으면 입원중
            current_hospitalization = [h for h in elderly.hospitalizations if h.discharge_date is None]
            
            if current_hospitalization:
                hospitalization_status = "入院中"
                latest_hospitalization = max(current_hospitalization, key=lambda x: x.admission_date)
        
        # 현재 거주 기록에서 입주일 조회
        current_resident = db.query(Resident).filter(
            Resident.resident_id == elderly.id,
            Resident.resident_type == "elderly",
            Resident.is_active == True,
            Resident.check_out_date.is_(None)
        ).first()
        
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
            "check_in_date": current_resident.check_in_date if current_resident else None,
            "contract_date": elderly.contract_date,
            "hospitalization_status": hospitalization_status,
            "latest_hospitalization": {
                "id": str(latest_hospitalization.id),
                "elderly_id": str(latest_hospitalization.elderly_id),
                "hospital_name": latest_hospitalization.hospital_name,
                "admission_date": latest_hospitalization.admission_date,
                "discharge_date": latest_hospitalization.discharge_date,
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

@router.get("/rent-by-category")
def get_elderly_rent_by_category(
    categories_id: str = Query(..., description="카테고리 ID"),
    building_id: str = Query(..., description="빌딩 ID"),
    room_id: str = Query(..., description="방 ID"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """카테고리 ID와 빌딩 ID로 카테고리별 월세 조회"""
    try:
        # 카테고리 ID 확인
        if not categories_id:
            raise HTTPException(status_code=400, detail="カテゴリIDが設定されていません")
        
        # 빌딩 존재 여부 확인
        building = db.query(Building).filter(Building.id == building_id).first()
        if not building:
            raise HTTPException(status_code=404, detail="建物が見つかりません")
        
        # 방 정보 조회
        room = db.query(Room).filter(
            Room.id == room_id,
            Room.building_id == building_id
        ).first()
        
        if not room:
            raise HTTPException(status_code=404, detail="指定された部屋が見つかりません")
        
        # 기본 rent, maintenance, service 값 설정
        rent_value = room.rent
        maintenance_value = room.maintenance
        service_value = room.service
        deposit_value = room.deposit
        
        # BuildingCategoriesRent에서 추가 조회하여 rent 값 대체
        rent_info = db.query(BuildingCategoriesRent).filter(
            BuildingCategoriesRent.building_id == building_id,
            BuildingCategoriesRent.categories_id == categories_id
        ).first()
        
        # BuildingCategoriesRent에서 데이터가 있으면 rent 값을 monthly_rent로 대체
        if rent_info:
            rent_value = rent_info.monthly_rent
        
        # 응답 데이터 구성
        return {
            "building_id": building_id,
            "building_name": building.name,
            "room_id": room_id,
            "room_number": room.room_number,
            "categories_id": str(categories_id),
            "rent": rent_value,
            "maintenance": maintenance_value,
            "service": service_value,
            "deposit": deposit_value,
            "has_category_rent": rent_info is not None,
            "message": "월세 정보를 성공적으로 조회했습니다"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] 고령자 월세 조회 중 오류: {str(e)}")
        import traceback
        print(f"[ERROR] Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"월세 조회 중 오류가 발생했습니다: {str(e)}")

@router.get("/{elderly_id}")
def get_elderly_detail(
    elderly_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    특정 고령자의 상세 정보를 조회합니다.
    """
    try:
        # 고령자 정보 조회
        elderly = db.query(Elderly).options(
            joinedload(Elderly.current_room).joinedload(Room.building),
            joinedload(Elderly.category),
            joinedload(Elderly.hospitalizations)
        ).filter(Elderly.id == elderly_id).first()
        
        if not elderly:
            raise HTTPException(status_code=404, detail="高齢者が見つかりません")
        
        # 입원 상태 확인
        hospitalization_status = "正常"
        latest_hospitalization = None
        
        if elderly.hospitalizations:
            # 가장 최근 입원 기록 찾기
            latest_hospitalization = max(elderly.hospitalizations, key=lambda x: x.admission_date)
            
            # 퇴원일이 없는 기록이 있으면 입원중
            current_hospitalization = [h for h in elderly.hospitalizations if h.discharge_date is None]
            
            if current_hospitalization:
                hospitalization_status = "入院中"
                latest_hospitalization = max(current_hospitalization, key=lambda x: x.admission_date)
        
        # 입원 이력 (최근 10개)
        hospitalization_history = []
        if elderly.hospitalizations:
            sorted_hospitalizations = sorted(elderly.hospitalizations, key=lambda x: x.admission_date, reverse=True)[:10]
            for h in sorted_hospitalizations:
                hospitalization_history.append({
                    "id": str(h.id),
                    "elderly_id": str(h.elderly_id),
                    "hospital_name": h.hospital_name,
                    "admission_date": h.admission_date,
                    "discharge_date": h.discharge_date,
                    "last_meal_date": h.last_meal_date,
                    "last_meal_type": h.last_meal_type,
                    "meal_resume_date": h.meal_resume_date,
                    "meal_resume_type": h.meal_resume_type,
                    "note": h.note,
                    "created_at": h.created_at,
                    "created_by": h.created_by
                })
        
        # 최근 식사 기록 조회 (최근 30일)
        thirty_days_ago = date.today() - timedelta(days=30)
        
        # Elderly와 연결된 Resident 조회
        resident = db.query(Resident).filter(
            Resident.resident_id == elderly_id,
            Resident.resident_type == "elderly",
            Resident.is_active == True
        ).first()
        
        recent_meal_records = []
        if resident:
            meal_records = db.query(ElderlyMealRecord).filter(
                ElderlyMealRecord.resident_id == resident.id,
                ElderlyMealRecord.skip_date >= thirty_days_ago
            ).order_by(ElderlyMealRecord.skip_date.desc()).limit(30).all()
            
            for record in meal_records:
                recent_meal_records.append({
                    "id": str(record.id),
                    "resident_id": str(record.resident_id),
                    "skip_date": record.skip_date,
                    "meal_type": record.meal_type,
                    "created_at": record.created_at
                })
        
        # 응답 데이터 구성
        elderly_detail = {
            "id": str(elderly.id),
            "name": elderly.name,
            "name_katakana": elderly.name_katakana,
            "email": elderly.email,
            "phone": elderly.phone,
            "avatar": elderly.avatar,
            "gender": elderly.gender,
            "birth_date": elderly.birth_date,
            "age": (date.today() - elderly.birth_date).days // 365 if elderly.birth_date else None,
            "care_level": elderly.care_level,
            "status": elderly.status,
            "note": elderly.note,
            "move_in_date": elderly.move_in_date,
            "contract_date": elderly.contract_date,
            "hospitalization_status": hospitalization_status,
            "current_room_id": str(elderly.current_room_id) if elderly.current_room_id else None,
            "created_at": elderly.created_at,
            "updated_at": elderly.updated_at if hasattr(elderly, 'updated_at') else None,
            "current_room": None,
            "latest_hospitalization": {
                "id": str(latest_hospitalization.id),
                "elderly_id": str(latest_hospitalization.elderly_id),
                "hospital_name": latest_hospitalization.hospital_name,
                "admission_date": latest_hospitalization.admission_date,
                "discharge_date": latest_hospitalization.discharge_date,
                "last_meal_date": latest_hospitalization.last_meal_date,
                "last_meal_type": latest_hospitalization.last_meal_type,
                "meal_resume_date": latest_hospitalization.meal_resume_date,
                "meal_resume_type": latest_hospitalization.meal_resume_type,
                "note": latest_hospitalization.note
            } if latest_hospitalization else None,
            "hospitalization_history": hospitalization_history,
            "recent_meal_records": recent_meal_records,
            "resident_info": {
                "id": str(resident.id),
                "resident_type": resident.resident_type,
                "is_active": resident.is_active
            } if resident else None
        }
        
        # 현재 방 정보 추가
        if elderly.current_room:
            elderly_detail["current_room"] = {
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
        
        return elderly_detail
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"高齢者詳細情報の取得中にエラーが発生しました: {str(e)}")

@router.post("/", status_code=201)
def create_elderly(
    elderly_data: ElderlyCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """새로운 고령자 정보 생성"""
    try:
        # birth_date가 문자열인 경우 date 객체로 변환
        birth_date = elderly_data.birth_date
        if isinstance(birth_date, str):
            birth_date = datetime.strptime(birth_date, "%Y-%m-%d").date()
        
        # move_in_date가 문자열인 경우 date 객체로 변환 (Resident 테이블의 check_in_date로 사용)
        move_in_date = elderly_data.move_in_date
        if isinstance(move_in_date, str):
            move_in_date = datetime.strptime(move_in_date, "%Y-%m-%d").date()
        
        # contract_date가 문자열인 경우 date 객체로 변환
        contract_date = elderly_data.contract_date
        if isinstance(contract_date, str):
            contract_date = datetime.strptime(contract_date, "%Y-%m-%d").date()
        
        # current_room_id가 문자열인 경우 UUID로 변환
        current_room_id = elderly_data.current_room_id
        if isinstance(current_room_id, str) and current_room_id:
            current_room_id = uuid.UUID(current_room_id)
        
        # categories_id가 문자열인 경우 UUID로 변환
        categories_id = elderly_data.category_id
        if isinstance(categories_id, str) and categories_id:
            categories_id = uuid.UUID(categories_id)
        
        # 방이 지정된 경우 방 존재 여부 확인
        if current_room_id:
            room = db.query(Room).filter(Room.id == current_room_id).first()
            if not room:
                raise HTTPException(status_code=404, detail="指定された部屋が見つかりません")
            
            # 방이 사용 가능한지 확인
            if not room.is_available:
                raise HTTPException(status_code=400, detail="該当の部屋は現在使用できません")
        
        # 카테고리가 지정된 경우 카테고리 존재 여부 확인
        if categories_id:
            category = db.query(ElderlyCategories).filter(ElderlyCategories.id == categories_id).first()
            if not category:
                raise HTTPException(status_code=404, detail="指定されたカテゴリが見つかりません")
        
        # 새로운 고령자 객체 생성
        new_elderly = Elderly(
            id=uuid.uuid4(),
            name=elderly_data.name,
            email=elderly_data.email,
            phone=elderly_data.phone,
            avatar=elderly_data.avatar or "/src/assets/images/avatars/avatar-1.png",
            name_katakana=elderly_data.name_katakana,
            gender=elderly_data.gender,
            birth_date=birth_date,
            status=elderly_data.status or "ACTIVE",
            current_room_id=current_room_id,
            care_level=elderly_data.care_level,
            categories_id=categories_id,
            contract_date=contract_date,
            note=elderly_data.note
        )
        
        db.add(new_elderly)
        db.commit()
        db.refresh(new_elderly)
        
        # 방이 지정된 경우 Resident 테이블에 입주 기록 생성
        if current_room_id and move_in_date:
            try:
                new_resident = Resident(
                    id=uuid.uuid4(),
                    room_id=current_room_id,
                    resident_id=new_elderly.id,
                    resident_type="elderly",
                    check_in_date=move_in_date,
                    is_active=True,
                )
                db.add(new_resident)
                db.commit()
                
                # Resident 테이블 로그 생성
                create_database_log(
                    db=db,
                    table_name="residents",
                    record_id=str(new_resident.id),
                    action="CREATE",
                    user_id=current_user["id"] if current_user else None,
                    new_values={
                        "room_id": str(new_resident.room_id),
                        "resident_id": str(new_resident.resident_id),
                        "resident_type": new_resident.resident_type,
                        "check_in_date": new_resident.check_in_date.strftime("%Y-%m-%d"),
                        "is_active": new_resident.is_active,
                        "note": new_resident.note
                    },
                    changed_fields=["room_id", "resident_id", "resident_type", "check_in_date", "is_active", "note"],
                    note=f"고령자 입주 기록 생성 - {new_elderly.name}"
                )
            except Exception as resident_error:
                print(f"Resident 기록 생성 중 오류: {str(resident_error)}")
                # Resident 생성 실패해도 Elderly 생성은 계속 진행
        
        # 계약 정보가 있는 경우 ElderlyContract 테이블에 저장
        if (elderly_data.rent is not None or elderly_data.maintenance is not None or 
            elderly_data.service is not None or elderly_data.deposit is not None):
            try:
                new_contract = ElderlyContract(
                    id=uuid.uuid4(),
                    elderly_id=new_elderly.id,
                    room_id=current_room_id,
                    rent=elderly_data.rent or 0,
                    maintenance=elderly_data.maintenance or 0,
                    service=elderly_data.service or 0,
                    deposit=elderly_data.deposit or 0,
                    contract_start=contract_date,  # contract_date를 contract_start로 사용
                    contract_end=None,  # 계약 종료일은 나중에 설정
                )
                db.add(new_contract)
                db.commit()
                
                # ElderlyContract 테이블 로그 생성
                create_database_log(
                    db=db,
                    table_name="elderly_contracts",
                    record_id=str(new_contract.id),
                    action="CREATE",
                    user_id=current_user["id"] if current_user else None,
                    new_values={
                        "elderly_id": str(new_contract.elderly_id),
                        "room_id": str(new_contract.room_id) if new_contract.room_id else None,
                        "rent": new_contract.rent,
                        "maintenance": new_contract.maintenance,
                        "service": new_contract.service,
                        "deposit": new_contract.deposit,
                        "contract_start": new_contract.contract_start.strftime("%Y-%m-%d") if new_contract.contract_start else None,
                        "is_active": new_contract.is_active
                    },
                    changed_fields=["elderly_id", "room_id", "rent", "maintenance", "service", "deposit", "contract_start", "is_active"],
                    note=f"고령자 계약 정보 생성 - {new_elderly.name}"
                )
            except Exception as contract_error:
                print(f"ElderlyContract 기록 생성 중 오류: {str(contract_error)}")
                # Contract 생성 실패해도 Elderly 생성은 계속 진행
        
        # 데이터베이스 로그 생성
        try:
            create_database_log(
                db=db,
                table_name="elderly",
                record_id=str(new_elderly.id),
                action="CREATE",
                user_id=current_user["id"] if current_user else None,
                new_values={
                    "name": new_elderly.name,
                    "email": new_elderly.email,
                    "phone": new_elderly.phone,
                    "name_katakana": new_elderly.name_katakana,
                    "gender": new_elderly.gender,
                    "birth_date": new_elderly.birth_date.strftime("%Y-%m-%d") if new_elderly.birth_date else None,
                    "status": new_elderly.status,
                    "current_room_id": str(new_elderly.current_room_id) if new_elderly.current_room_id else None,
                    "care_level": new_elderly.care_level,
                    "categories_id": str(new_elderly.categories_id) if new_elderly.categories_id else None,
                    "contract_date": new_elderly.contract_date.strftime("%Y-%m-%d") if new_elderly.contract_date else None
                },
                changed_fields=["name", "email", "phone", "name_katakana", "gender", "birth_date", "status", "current_room_id", "care_level", "categories_id", "contract_date"],
                note=f"新規高齢者登録 - {new_elderly.name}"
            )
        except Exception as log_error:
            print(f"로그 생성 중 오류: {log_error}")
        
        return {
            "message": "高齢者情報が正常に登録されました",
            "elderly": {
                "id": str(new_elderly.id),
                "name": new_elderly.name,
                "email": new_elderly.email,
                "phone": new_elderly.phone,
                "avatar": new_elderly.avatar,
                "name_katakana": new_elderly.name_katakana,
                "gender": new_elderly.gender,
                "birth_date": new_elderly.birth_date.strftime("%Y-%m-%d") if new_elderly.birth_date else None,
                "status": new_elderly.status,
                "current_room_id": str(new_elderly.current_room_id) if new_elderly.current_room_id else None,
                "care_level": new_elderly.care_level,
                "category_id": str(new_elderly.categories_id) if new_elderly.categories_id else None,
                "move_in_date": new_resident.check_in_date.strftime("%Y-%m-%d") if new_resident.check_in_date else None,
                "contract_date": new_elderly.contract_date.strftime("%Y-%m-%d") if new_elderly.contract_date else None,
                "created_at": new_elderly.created_at.strftime("%Y-%m-%d %H:%M:%S") if new_elderly.created_at else None
            }
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"高齢者情報登録中にエラーが発生しました: {str(e)}")

@router.put("/{elderly_id}/update")
def update_elderly(
    elderly_id: str,
    elderly_update: ElderlyUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """고령자 정보 수정"""
    try:
        # 고령자 존재 여부 확인
        elderly = db.query(Elderly).filter(Elderly.id == elderly_id).first()
        if not elderly:
            raise HTTPException(status_code=404, detail="高齢者が見つかりません")
        
        # 기존 값 저장 (로그용)
        old_values = {
            "name": elderly.name,
            "email": elderly.email,
            "phone": elderly.phone,
            "name_katakana": elderly.name_katakana,
            "gender": elderly.gender,
            "birth_date": elderly.birth_date.strftime("%Y-%m-%d") if elderly.birth_date else None,
            "status": elderly.status,
            "current_room_id": str(elderly.current_room_id) if elderly.current_room_id else None,
            "care_level": elderly.care_level,
            "category_id": str(elderly.categories_id) if elderly.categories_id else None,
            "move_in_date": elderly.move_in_date.strftime("%Y-%m-%d") if elderly.move_in_date else None,
            "contract_date": elderly.contract_date.strftime("%Y-%m-%d") if elderly.contract_date else None,
            "note": elderly.note
        }
        
        # 업데이트할 필드만 변경
        update_data = elderly_update.dict(exclude_unset=True)
        changed_fields = []
        
        for field, value in update_data.items():
            if value is not None:
                # current_room_id 검증
                if field == "current_room_id" and value:
                    room = db.query(Room).filter(Room.id == value).first()
                    if not room:
                        raise HTTPException(status_code=404, detail="指定された部屋が見つかりません")
                    if not room.is_available:
                        raise HTTPException(status_code=400, detail="該当の部屋は現在使用できません")
                
                # categories_id 검증
                if field == "categories_id" and value:
                    category = db.query(ElderlyCategories).filter(ElderlyCategories.id == value).first()
                    if not category:
                        raise HTTPException(status_code=404, detail="指定されたカテゴリが見つかりません")
                
                setattr(elderly, field, value)
                changed_fields.append(field)
        
        db.commit()
        db.refresh(elderly)
        
        # 데이터베이스 로그 생성
        if changed_fields:
            try:
                new_values = {
                    field: getattr(elderly, field).strftime("%Y-%m-%d") if isinstance(getattr(elderly, field), date) 
                           else str(getattr(elderly, field)) if getattr(elderly, field) is not None 
                           else None
                    for field in changed_fields
                }
                
                create_database_log(
                    db=db,
                    table_name="elderly",
                    record_id=str(elderly.id),
                    action="UPDATE",
                    user_id=current_user["id"] if current_user else None,
                    old_values={k: v for k, v in old_values.items() if k in changed_fields},
                    new_values=new_values,
                    changed_fields=changed_fields,
                    note=f"高齢者情報更新 - {elderly.name}"
                )
            except Exception as log_error:
                print(f"로그 생성 중 오류: {log_error}")
        
        return {
            "message": "高齢者情報が正常に更新されました",
            "elderly": {
                "id": str(elderly.id),
                "name": elderly.name,
                "email": elderly.email,
                "phone": elderly.phone,
                "avatar": elderly.avatar,
                "name_katakana": elderly.name_katakana,
                "gender": elderly.gender,
                "birth_date": elderly.birth_date.strftime("%Y-%m-%d") if elderly.birth_date else None,
                "status": elderly.status,
                "current_room_id": str(elderly.current_room_id) if elderly.current_room_id else None,
                "care_level": elderly.care_level,
                "created_at": elderly.created_at.strftime("%Y-%m-%d %H:%M:%S") if elderly.created_at else None
            }
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"高齢者情報更新中にエラーが発生しました: {str(e)}")


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
                    (ElderlyHospitalization.admission_date >= start_date) & 
                    (ElderlyHospitalization.admission_date <= end_date)
                ).union(
                    db.query(ElderlyHospitalization).filter(
                        ElderlyHospitalization.elderly_id == resident.id,
                        (ElderlyHospitalization.discharge_date >= start_date) & 
                        (ElderlyHospitalization.discharge_date <= end_date)
                    )
                ).order_by(ElderlyHospitalization.admission_date.asc()).all()
                
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
                
                # 해당 거주자의 식사 기록을 일별 데이터에 반영
                for record in meal_records:
                    day = record.date.day
                    if day in resident_daily_data:
                        resident_daily_data[day][record.meal_type] = True
                        resident_daily_data[day]["total_skipped"] += 1
                
                # 입원 기록을 거주자별 일별 데이터에 반영
                for hospitalization in resident_hospitalizations:
                    # 입원 기간 계산
                    admission_date = hospitalization.admission_date
                    discharge_date = hospitalization.discharge_date
                    
                    # 입원 시작일과 종료일을 해당 월 범위로 제한
                    hospitalization_start = max(admission_date, start_date)
                    # 퇴원일이 없으면 오늘 날짜를 사용, 있으면 해당 월의 마지막 날과 비교하여 더 작은 값 사용
                    if discharge_date:
                        hospitalization_end = min(discharge_date, end_date)
                    else:
                        hospitalization_end = min(datetime.now().date(), end_date)
                    
                    # 입원 중인 날짜들에 대해 식사 건너뛰기 처리
                    current_date = hospitalization_start
                    while current_date <= hospitalization_end:
                        day = current_date.day
                        if day in resident_daily_data:
                            resident_daily_data[day]["breakfast"] = True
                            resident_daily_data[day]["lunch"] = True
                            resident_daily_data[day]["dinner"] = True
                            resident_daily_data[day]["total_skipped"] = 3
                        current_date += timedelta(days=1)
                
                # 일별 데이터를 배열로 변환
                daily_records_array = []
                for day, data in resident_daily_data.items():
                    daily_records_array.append(data)
                
                # 거주자 데이터 구성
                resident_data = {
                    "resident_id": str(resident.id),
                    "name": resident.name,
                    "room_number": room.room_number,
                    "daily_records": daily_records_array,
                    "hospitalizations": [
                        {
                            "elderly_id": str(h.elderly_id),
                            "hospital_name": h.hospital_name,
                            "admission_date": h.admission_date,
                            "discharge_date": h.discharge_date,
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
                ElderlyHospitalization.discharge_date.is_(None)
            ).order_by(ElderlyHospitalization.admission_date.desc()).first()
            
            if existing_hospitalization:
                existing_hospitalization.discharge_date = hospitalization_data.discharge_date
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
        ).order_by(ElderlyHospitalization.admission_date.desc())
        
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
                "hospital_name": hospitalization.hospital_name,
                "admission_date": hospitalization.admission_date,
                "discharge_date": hospitalization.discharge_date,
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
async def create_elderly_hospitalization(
    hospitalization_data: ElderlyHospitalizationCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """거주자 입원 기록을 생성합니다. (새로운 스키마)"""
    try:
        # 노인 존재 여부 확인
        elderly = db.query(Elderly).filter(Elderly.id == hospitalization_data.elderly_id).first()
        if not elderly:
            raise HTTPException(status_code=404, detail="노인을 찾을 수 없습니다")
        
        # 입원 기록 생성
        hospitalization = ElderlyHospitalization(
            elderly_id=hospitalization_data.elderly_id,
            hospital_name=hospitalization_data.hospital_name,
            admission_date=hospitalization_data.admission_date,
            discharge_date=hospitalization_data.discharge_date,  # 퇴원일 (입원 시에는 None)
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
        
        # 웹푸시 알림 전송 (입원 기록 생성 시)
        try:
            await send_hospitalization_notification(
                db=db,
                elderly_name=elderly.name,
                hospital_name=hospitalization_data.hospital_name,
                action_type="admission",
                elderly_id=str(elderly.id)
            )
        except Exception as e:
            print(f"입원 알림 전송 중 오류: {e}")
        
        return {
            "message": "입원 기록이 정상적으로 생성되었습니다.",
            "item": {
                "id": str(hospitalization.id),
                "elderly_id": str(hospitalization.elderly_id),
                "hospital_name": hospitalization.hospital_name,
                "admission_date": hospitalization.admission_date,
                "discharge_date": hospitalization.discharge_date
            }
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"입원 기록 생성 중 오류가 발생했습니다: {str(e)}")

@router.put("/hospitalizations/{hospitalization_id}/discharge")
async def discharge_patient(
    hospitalization_id: str,
    discharge_data: dict,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """환자를 퇴원 처리합니다."""
    try:
        # 입원 기록 조회
        hospitalization = db.query(ElderlyHospitalization).filter(
            ElderlyHospitalization.id == hospitalization_id
        ).first()
        
        if not hospitalization:
            raise HTTPException(status_code=404, detail="입원 기록을 찾을 수 없습니다")
        
        # 퇴원 처리
        hospitalization.discharge_date = discharge_data.get("discharge_date")
        hospitalization.meal_resume_date = discharge_data.get("meal_resume_date")
        hospitalization.meal_resume_type = discharge_data.get("meal_resume_type")
        if discharge_data.get("note"):
            hospitalization.note = discharge_data.get("note")
        
        db.commit()
        db.refresh(hospitalization)
        
        # 웹푸시 알림 전송 (퇴원 처리 시)
        try:
            # 고령자 정보 조회
            elderly = db.query(Elderly).filter(Elderly.id == hospitalization.elderly_id).first()
            if elderly:
                await send_hospitalization_notification(
                    db=db,
                    elderly_name=elderly.name,
                    hospital_name=hospitalization.hospital_name,
                    action_type="discharge",
                    elderly_id=str(elderly.id)
                )
        except Exception as e:
            print(f"퇴원 알림 전송 중 오류: {e}")
        
        return {
            "message": "퇴원 처리가 완료되었습니다.",
            "item": {
                "id": str(hospitalization.id),
                "elderly_id": str(hospitalization.elderly_id),
                "hospital_name": hospitalization.hospital_name,
                "admission_date": hospitalization.admission_date,
                "discharge_date": hospitalization.discharge_date
            }
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"퇴원 처리 중 오류가 발생했습니다: {str(e)}")

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
        
        # 기본 쿼리 생성 (새로운 스키마)
        # 입원일 또는 퇴원일이 해당 월에 포함되는 기록 조회
        query = db.query(ElderlyHospitalization).filter(
            (ElderlyHospitalization.admission_date >= start_date) & 
            (ElderlyHospitalization.admission_date <= end_date)
        ).union(
            db.query(ElderlyHospitalization).filter(
                (ElderlyHospitalization.discharge_date >= start_date) & 
                (ElderlyHospitalization.discharge_date <= end_date)
            )
        )
        
        # 필터링 조건 추가
        if elderly_id:
            query = query.filter(ElderlyHospitalization.elderly_id == elderly_id)
        
        # 총 개수 계산
        total_count = query.count()
        
        # 페이지네이션 적용
        offset = (page - 1) * page_size
        hospitalizations = query.order_by(ElderlyHospitalization.admission_date.desc()).offset(offset).limit(page_size).all()
        
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
                "hospital_name": hospitalization.hospital_name,
                "admission_date": hospitalization.admission_date,
                "discharge_date": hospitalization.discharge_date,
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
        
        # 월별 통계 계산 (새로운 스키마)
        # 해당 월에 입원한 사람 수 (입원일이 해당 월에 있는 경우)
        admission_count = len([h for h in hospitalizations if h.admission_date and start_date <= h.admission_date <= end_date])
        # 해당 월에 퇴원한 사람 수 (퇴원일이 해당 월에 있는 경우)
        discharge_count = len([h for h in hospitalizations if h.discharge_date and start_date <= h.discharge_date <= end_date])
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

@router.get("/hospitalizations/recent")
def get_elderly_hospitalizations_recent(
    elderly_id: Optional[str] = Query(None, description="특정 고령자 ID로 필터링"),
    hospitalization_type: Optional[str] = Query(None, description="입원/퇴원 유형으로 필터링 (admission 또는 discharge)"),
    page: int = Query(1, description="페이지 번호", ge=1),
    page_size: int = Query(10, description="페이지당 항목 수", ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """오늘 기준으로 3개월 이내의 병원 입퇴원 기록을 조회합니다."""
    try:
        # 오늘 기준으로 3개월 이내의 데이터 조회
        today = date.today()
        three_months_ago = today - timedelta(days=90)  # 약 3개월
        
        # 기본 쿼리 생성 (3개월 이내 데이터만)
        # 입원일 또는 퇴원일이 3개월 이내에 포함되는 기록 조회
        query = db.query(ElderlyHospitalization).filter(
            (ElderlyHospitalization.admission_date >= three_months_ago) & 
            (ElderlyHospitalization.admission_date <= today)
        ).union(
            db.query(ElderlyHospitalization).filter(
                (ElderlyHospitalization.discharge_date >= three_months_ago) & 
                (ElderlyHospitalization.discharge_date <= today)
            )
        )
        
        # 필터링 조건 추가
        if elderly_id:
            query = query.filter(ElderlyHospitalization.elderly_id == elderly_id)
        
        # hospitalization_type 필터는 새로운 스키마에서는 사용하지 않음
        
        # 총 개수 계산
        total_count = query.count()
        
        # 페이지네이션 적용
        offset = (page - 1) * page_size
        hospitalizations = query.order_by(ElderlyHospitalization.admission_date.desc()).offset(offset).limit(page_size).all()
        
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
                "hospital_name": hospitalization.hospital_name,
                "admission_date": hospitalization.admission_date,
                "discharge_date": hospitalization.discharge_date,
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
        
        # 통계 계산 (새로운 스키마)
        # 3개월 이내에 입원한 사람 수
        admission_count = len([h for h in hospitalizations if h.admission_date and three_months_ago <= h.admission_date <= today])
        # 3개월 이내에 퇴원한 사람 수
        discharge_count = len([h for h in hospitalizations if h.discharge_date and three_months_ago <= h.discharge_date <= today])
        unique_elderly_count = len(set(h.elderly_id for h in hospitalizations))
        
        return {
            "period": "3개월 이내",
            "start_date": str(three_months_ago),
            "end_date": str(today),
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
        raise HTTPException(status_code=500, detail=f"최근 병원 입퇴원 기록 조회 중 오류가 발생했습니다: {str(e)}")
    
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
        print(f"[DEBUG] 조회할 거주자 ID들: {resident_ids}")
        print(f"[DEBUG] 조회 기간: {start_date} ~ {end_date}")
        
        records = db.query(ElderlyMealRecord).options(
            joinedload(ElderlyMealRecord.resident).joinedload(Resident.elderly)
        ).filter(
            ElderlyMealRecord.skip_date >= start_date,
            ElderlyMealRecord.skip_date <= end_date,
            ElderlyMealRecord.resident_id.in_(resident_ids)
        ).order_by(ElderlyMealRecord.skip_date, ElderlyMealRecord.meal_type).all()
        
        print(f"[DEBUG] 조회된 식사 기록 수: {len(records)}")
        for record in records:
            print(f"[DEBUG] 식사 기록 - 거주자ID: {record.resident_id}, 날짜: {record.skip_date}, 식사타입: {record.meal_type}")

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
        print(f"[DEBUG] 고령자 ID 목록: {elderly_ids}")
        hospitalization_records = db.query(ElderlyHospitalization).filter(
            (ElderlyHospitalization.admission_date >= start_date) & 
            (ElderlyHospitalization.admission_date <= end_date),
            ElderlyHospitalization.elderly_id.in_(elderly_ids)
        ).union(
            db.query(ElderlyHospitalization).filter(
                (ElderlyHospitalization.discharge_date >= start_date) & 
                (ElderlyHospitalization.discharge_date <= end_date),
                ElderlyHospitalization.elderly_id.in_(elderly_ids)
            )
        ).order_by(ElderlyHospitalization.admission_date).all()

        # 조회된 기록을 월별 데이터에 반영
        for record in records:
            day = record.skip_date.day
            if day in monthly_data:
                monthly_data[day][record.meal_type] += 1
                monthly_data[day]["total_skipped"] += 1
                monthly_data[day]["residents_skipped"].add(str(record.resident_id))

        # 입원 기록을 월별 데이터에 반영
        print(f"[DEBUG] 입원 기록 수: {len(hospitalization_records)}")
        for hospitalization in hospitalization_records:
            print(f"[DEBUG] 입원 기록 - 고령자ID: {hospitalization.elderly_id}, 입원일: {hospitalization.admission_date}, 퇴원일: {hospitalization.discharge_date}")
            
            # 입원 기간 계산
            admission_date = hospitalization.admission_date
            discharge_date = hospitalization.discharge_date
            
            # 해당 월의 입원 기간 계산
            hospitalization_start = max(admission_date, start_date)
            # 퇴원일이 없으면 오늘 날짜를 사용, 있으면 해당 월의 마지막 날과 비교하여 더 작은 값 사용
            if discharge_date:
                hospitalization_end = min(discharge_date, end_date)
            else:
                hospitalization_end = min(datetime.now().date(), end_date)
            
            print(f"[DEBUG] 처리할 입원 기간: {hospitalization_start} ~ {hospitalization_end}")
            
            # 입원 중인 날짜들에 대해 식사 건너뛰기 처리
            current_date = hospitalization_start
            while current_date <= hospitalization_end:
                day = current_date.day
                if day in monthly_data:
                    monthly_data[day]["breakfast"] += 1
                    monthly_data[day]["lunch"] += 1
                    monthly_data[day]["dinner"] += 1
                    monthly_data[day]["total_skipped"] += 3
                    monthly_data[day]["residents_skipped"].add(str(hospitalization.elderly_id))
                    print(f"[DEBUG] {current_date} (day {day}) - 식사 건너뛰기 추가")
                current_date += timedelta(days=1)

        # 응답 데이터 준비
        print(f"[DEBUG] monthly_data 최종 상태: {monthly_data}")
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
            print(f"[DEBUG] 거주자 {resident.id} ({resident.elderly.name if resident.elderly else 'Unknown'})의 기록 수: {len(resident_records)}")
            
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
            
            # 입원 기록을 거주자별 일별 데이터에 반영
            if resident.elderly:
                resident_hospitalizations = [h for h in hospitalization_records if str(h.elderly_id) == str(resident.elderly.id)]
                for hospitalization in resident_hospitalizations:
                    # 입원 기간 계산
                    admission_date = hospitalization.admission_date
                    discharge_date = hospitalization.discharge_date
                    
                    # 입원 시작일과 종료일을 해당 월 범위로 제한
                    hospitalization_start = max(admission_date, start_date)
                    # 퇴원일이 없으면 오늘 날짜를 사용, 있으면 해당 월의 마지막 날과 비교하여 더 작은 값 사용
                    if discharge_date:
                        hospitalization_end = min(discharge_date, end_date)
                    else:
                        hospitalization_end = min(datetime.now().date(), end_date)
                    
                    # 입원 중인 날짜들에 대해 식사 건너뛰기 처리
                    current_date = hospitalization_start
                    while current_date <= hospitalization_end:
                        day = current_date.day
                        if day in resident_daily_data:
                            resident_daily_data[day]["breakfast"] = True
                            resident_daily_data[day]["lunch"] = True
                            resident_daily_data[day]["dinner"] = True
                            resident_daily_data[day]["total_skipped"] = 3
                        current_date += timedelta(days=1)
            
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
                        "hospital_name": h.hospital_name,
                        "admission_date": h.admission_date,
                        "discharge_date": h.discharge_date,
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

@router.get("/{elderly_id}/residence-history")
def get_elderly_residence_history(
    elderly_id: str,
    page: int = Query(1, description="페이지 번호", ge=1),
    size: int = Query(10, description="페이지당 항목 수", ge=1, le=100),
    is_active: Optional[bool] = Query(None, description="활성 상태로 필터링"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """고령자 거주 이력 조회"""
    try:
        # 고령자 존재 여부 확인
        elderly = db.query(Elderly).filter(Elderly.id == elderly_id).first()
        if not elderly:
            raise HTTPException(status_code=404, detail="高齢者が見つかりません")

        # 해당 고령자의 모든 거주 기록 조회
        query = db.query(Resident).options(
            joinedload(Resident.room).joinedload(Room.building)
        ).filter(
            Resident.resident_id == elderly_id,
            Resident.resident_type == "elderly"
        )

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
                "elderly_id": str(resident.resident_id),
                "check_in_date": resident.check_in_date.strftime("%Y-%m-%d") if resident.check_in_date else None,
                "check_out_date": resident.check_out_date.strftime("%Y-%m-%d") if resident.check_out_date else None,
                "is_active": resident.is_active,
                "note": resident.note,
                "created_at": resident.created_at.strftime("%Y-%m-%d %H:%M:%S") if resident.created_at else None,
                "updated_at": resident.updated_at.strftime("%Y-%m-%d %H:%M:%S") if resident.updated_at else None,
                "room": {
                    "id": str(resident.room.id),
                    "room_number": resident.room.room_number,
                    "building_id": str(resident.room.building_id),
                    "floor": resident.room.floor,
                    "rent": resident.room.rent,
                    "maintenance": resident.room.maintenance,
                    "service": resident.room.service
                } if resident.room else None,
                "building": {
                    "id": str(resident.room.building.id),
                    "name": resident.room.building.name,
                    "address": resident.room.building.address
                } if resident.room and resident.room.building else None,
                "elderly": {
                    "id": str(elderly.id),
                    "name": elderly.name,
                    "name_katakana": elderly.name_katakana,
                    "phone": elderly.phone,
                    "email": elderly.email,
                    "avatar": elderly.avatar,
                    "gender": elderly.gender,
                    "birth_date": elderly.birth_date.strftime("%Y-%m-%d") if elderly.birth_date else None,
                    "care_level": elderly.care_level
                }
            }
            result.append(resident_data)

        return {
            "elderly": {
                "id": str(elderly.id),
                "name": elderly.name,
                "current_room_id": str(elderly.current_room_id) if elderly.current_room_id else None
            },
            "items": result,
            "total": total_count,
            "total_pages": total_pages,
            "current_page": page
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"高齢者居住履歴の取得中にエラーが発生しました: {str(e)}")

@router.get("/{elderly_id}/residence-history/monthly")
def get_elderly_monthly_residence_history(
    elderly_id: str,
    year: int,
    month: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """고령자 월별 거주 이력 조회"""
    try:
        # 고령자 존재 여부 확인
        elderly = db.query(Elderly).filter(Elderly.id == elderly_id).first()
        if not elderly:
            raise HTTPException(status_code=404, detail="高齢者が見つかりません")
        
        # 년월 유효성 검사
        if not (1 <= month <= 12):
            raise HTTPException(status_code=400, detail="月は1-12の間でなければなりません")
        
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
            Resident.resident_id == elderly_id,
            Resident.resident_type == "elderly",
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
                    "elderly_id": str(resident.resident_id),
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
                        "rent": resident.room.rent,
                        "maintenance": resident.room.maintenance,
                        "service": resident.room.service
                    } if resident.room else None,
                    "building": {
                        "id": str(resident.room.building.id),
                        "name": resident.room.building.name,
                        "address": resident.room.building.address
                    } if resident.room and resident.room.building else None,
                    "elderly": {
                        "id": str(elderly.id),
                        "name": elderly.name,
                        "name_katakana": elderly.name_katakana,
                        "phone": elderly.phone,
                        "email": elderly.email,
                        "avatar": elderly.avatar,
                        "gender": elderly.gender,
                        "birth_date": elderly.birth_date.strftime("%Y-%m-%d") if elderly.birth_date else None,
                        "care_level": elderly.care_level
                    }
                }
                monthly_history.append(resident_data)

        # 월별 요약 정보
        total_days = calendar.monthrange(year, month)[1]
        total_residences = len(monthly_history)
        
        return {
            "elderly": {
                "id": str(elderly.id),
                "name": elderly.name,
                "current_room_id": str(elderly.current_room_id) if elderly.current_room_id else None
            },
            "year": year,
            "month": month,
            "total_days": total_days,
            "total_residences": total_residences,
            "items": monthly_history
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"高齢者月別居住履歴の取得中にエラーが発生しました: {str(e)}")

@router.put("/{elderly_id}/change-residence")
def change_elderly_residence(
    elderly_id: str,
    request: dict,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """고령자 거주지 변경"""
    try:
        # 고령자 존재 여부 확인
        elderly = db.query(Elderly).filter(Elderly.id == elderly_id).first()
        if not elderly:
            raise HTTPException(status_code=404, detail="高齢者が見つかりません")

        # 현재 거주 중인 방 확인
        current_residence = db.query(Resident).filter(
            Resident.resident_id == elderly_id,
            Resident.resident_type == "elderly",
            Resident.is_active == True,
            Resident.check_out_date.is_(None)
        ).first()

        if not current_residence:
            raise HTTPException(status_code=400, detail="該当の高齢者は現在居住中の部屋がありません")

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

            # 고령자의 current_room_id 초기화
            elderly.current_room_id = None
            
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
                    note=f"高齢者退去 - {elderly.name}: {current_residence.room.room_number if current_residence.room else 'Unknown'}"
                )
            except Exception as log_error:
                print(f"로그 생성 중 오류: {log_error}")
            
            return {
                "message": "高齢者が正常に退去しました",
                "elderly_id": str(elderly_id),
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
                raise HTTPException(status_code=404, detail="新しい部屋が見つかりません")

            # 새로운 방이 사용 가능한지 확인
            if not new_room.is_available:
                raise HTTPException(status_code=400, detail="該当の部屋は現在使用できません")

            # 새로운 방의 정원 확인
            current_residents_in_new_room = db.query(Resident).filter(
                Resident.room_id == request.get("new_room_id"),
                Resident.is_active == True,
                Resident.check_out_date.is_(None)
            ).count()
            
            if new_room.capacity and current_residents_in_new_room >= new_room.capacity:
                raise HTTPException(status_code=400, detail="該当の部屋は定員を超えて入居できません")

            # 1. 현재 거주지에서 퇴실 처리 (이사할 때는 전날에 퇴실)
            change_date_obj = datetime.strptime(request.get("change_date", datetime.now().strftime("%Y-%m-%d")), "%Y-%m-%d").date()
            current_residence.check_out_date = change_date_obj - timedelta(days=1)
            current_residence.is_active = False
            if request.get("note"):
                current_residence.note = f"引越しによる退去 - {request.get('note')}"

            # 2. 새로운 방에 입주 기록 생성
            check_in_date = change_date_obj  # 변경날짜로 설정
            
            new_residence = Resident(
                id=str(uuid.uuid4()),
                room_id=request.get("new_room_id"),
                resident_id=elderly_id,
                resident_type="elderly",
                check_in_date=check_in_date,
                note=f"引越しによる入居 - {request.get('note')}" if request.get('note') else "引越しによる入居"
            )
            db.add(new_residence)

            # 3. 고령자의 current_room_id 업데이트
            elderly.current_room_id = request.get("new_room_id")
            
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
                    note=f"高齢者引越し退去 - {elderly.name}: {current_residence.room.room_number if current_residence.room else 'Unknown'}"
                )
                
                # 입주 로그
                create_database_log(
                    db=db,
                    table_name="residents",
                    record_id=str(new_residence.id),
                    action="CREATE",
                    user_id=current_user["id"] if current_user else None,
                    new_values={
                        "room_id": str(new_residence.room_id),
                        "resident_id": str(elderly_id),
                        "resident_type": "elderly",
                        "check_in_date": check_in_date.strftime("%Y-%m-%d"),
                        "is_active": True
                    },
                    changed_fields=["room_id", "resident_id", "resident_type", "check_in_date", "is_active"],
                    note=f"高齢者引越し入居 - {elderly.name}: {new_room.room_number}"
                )
            except Exception as log_error:
                print(f"로그 생성 중 오류: {log_error}")
            
            return {
                "message": "高齢者の居住地が正常に変更されました",
                "elderly_id": str(elderly_id),
                "old_room_id": str(current_residence.room_id),
                "new_room_id": str(request.get("new_room_id")),
                "change_date": change_date_obj.strftime("%Y-%m-%d"),
                "action": "MOVE"
            }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"居住地変更中にエラーが発生しました: {str(e)}")

@router.post("/{elderly_id}/create-residence")
def create_new_elderly_residence(
    elderly_id: str,
    request: NewResidenceRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """고령자에게 새로운 거주 기록을 추가"""
    try:
        # 고령자 존재 여부 확인
        elderly = db.query(Elderly).filter(Elderly.id == elderly_id).first()
        if not elderly:
            raise HTTPException(status_code=404, detail="高齢者が見つかりません")

        # 방 존재 여부 확인
        room = db.query(Room).filter(Room.id == request.new_room_id).first()
        if not room:
            raise HTTPException(status_code=404, detail="部屋が見つかりません")

        # 방이 사용 가능한지 확인
        if not room.is_available:
            raise HTTPException(status_code=400, detail="該当の部屋は現在使用できません")

        # 입주일과 퇴실일 유효성 검사
        try:
            check_in_date = datetime.strptime(request.change_date, "%Y-%m-%d").date()
            check_out_date = None
            if request.check_out_date:
                check_out_date = datetime.strptime(request.check_out_date, "%Y-%m-%d").date()
                if check_out_date <= check_in_date:
                    raise HTTPException(status_code=400, detail="退去日は入居日より後でなければなりません")
        except ValueError:
            raise HTTPException(status_code=400, detail="日付形式が正しくありません (YYYY-MM-DD)")

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
                raise HTTPException(status_code=400, detail=f"該当の部屋は定員({room.capacity}名)を超えて入居できません。現在の居住者: {current_residents}名")

        # 거주 기록 생성
        new_residence = Resident(
            id=str(uuid.uuid4()),
            room_id=request.new_room_id,
            resident_id=elderly_id,
            resident_type="elderly",  # 명시적으로 elderly 타입 설정
            check_in_date=check_in_date,
            check_out_date=check_out_date,
            is_active=is_currently_residing,
            note=request.note
        )
        db.add(new_residence)

        # 현재 거주 중인 경우 고령자의 current_room_id 업데이트
        if is_currently_residing:
            elderly.current_room_id = request.new_room_id
        
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
                    "resident_id": elderly_id,
                    "resident_type": "elderly",
                    "check_in_date": check_in_date.strftime("%Y-%m-%d"),
                    "check_out_date": check_out_date.strftime("%Y-%m-%d") if check_out_date else None,
                    "is_active": is_currently_residing,
                    "note": request.note
                },
                changed_fields=["room_id", "resident_id", "resident_type", "check_in_date", "check_out_date", "is_active", "note"],
                note=f"新規居住記録追加 - {elderly.name}: {room.room_number} ({room.building.name if room.building else 'Unknown'})"
            )
        except Exception as log_error:
            print(f"로그 생성 중 오류: {log_error}")
        
        return {
            "message": "新しい居住記録が正常に追加されました",
            "elderly_id": elderly_id,
            "room_id": str(request.new_room_id),
            "check_in_date": check_in_date.strftime("%Y-%m-%d"),
            "check_out_date": check_out_date.strftime("%Y-%m-%d") if check_out_date else None,
            "is_active": is_currently_residing,
            "residence": {
                "id": str(new_residence.id),
                "room_id": str(new_residence.room_id),
                "elderly_id": str(elderly_id),
                "check_in_date": check_in_date.strftime("%Y-%m-%d"),
                "check_out_date": check_out_date.strftime("%Y-%m-%d") if check_out_date else None,
                "is_active": is_currently_residing,
                "note": request.note
            }
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"居住記録追加中にエラーが発生しました: {str(e)}")

@router.get("/buildings/{building_id}/statistics")
def get_building_elderly_statistics(
    building_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """특정 빌딩의 고령자 통계 조회 (입원자 수 등)"""
    try:
        # 빌딩 존재 여부 확인
        building = db.query(Building).filter(Building.id == building_id).first()
        if not building:
            raise HTTPException(status_code=404, detail="建物が見つかりません")
        
        # 해당 빌딩의 전체 방 수 조회
        total_rooms = db.query(Room).filter(Room.building_id == building_id).count()
        
        # 해당 빌딩의 활성 고령자 거주자 조회 (입주예정자 제외 - 입주일이 오늘 이하인 경우만)
        today = date.today()
        elderly_residents = db.query(Resident).options(
            joinedload(Resident.elderly).joinedload(Elderly.hospitalizations),
            joinedload(Resident.room)
        ).filter(
            Resident.resident_type == "elderly",
            Resident.is_active == True,
            Resident.check_out_date.is_(None),
            Resident.check_in_date <= today,  # 입주예정자 제외
            Resident.room.has(Room.building_id == building_id)
        ).all()
        
        total_residents = len(elderly_residents)
        hospitalized_count = 0
        hospitalized_residents = []
        
        # 통계를 위한 데이터 수집
        care_level_distribution = {}
        age_distribution = {
            "60-69": 0,
            "70-79": 0,
            "80-89": 0,
            "90-99": 0,
            "100+": 0
        }
        gender_distribution = {
            "男": 0,
            "女": 0,
            "その他": 0
        }
        
        # 각 거주자의 입원 상태 확인 및 통계 데이터 수집
        for resident in elderly_residents:
            if not resident.elderly:
                continue
            
            elderly = resident.elderly
            
            # 요양 등급별 분포
            care_level = elderly.care_level or "未設定"
            care_level_distribution[care_level] = care_level_distribution.get(care_level, 0) + 1
            
            # 연령대별 분포
            if elderly.birth_date:
                age = (date.today() - elderly.birth_date).days // 365
                if 60 <= age < 70:
                    age_distribution["60-69"] += 1
                elif 70 <= age < 80:
                    age_distribution["70-79"] += 1
                elif 80 <= age < 90:
                    age_distribution["80-89"] += 1
                elif 90 <= age < 100:
                    age_distribution["90-99"] += 1
                elif age >= 100:
                    age_distribution["100+"] += 1
            
            # 성별 분포
            if elderly.gender == "男":
                gender_distribution["男"] += 1
            elif elderly.gender == "女":
                gender_distribution["女"] += 1
            else:
                gender_distribution["その他"] += 1
            
            # 입원 기록 확인 (새로운 스키마)
            if elderly.hospitalizations:
                # 퇴원일이 없는 기록이 있으면 입원중
                current_hospitalization = [h for h in elderly.hospitalizations if h.discharge_date is None]
                
                if current_hospitalization:
                    # 가장 최근 입원 기록
                    latest_admission = max(current_hospitalization, key=lambda x: x.admission_date)
                    hospitalized_count += 1
                    hospitalized_residents.append({
                        "elderly_id": str(elderly.id),
                        "elderly_name": elderly.name,
                        "elderly_name_katakana": elderly.name_katakana,
                        "room_number": resident.room.room_number if resident.room else None,
                        "care_level": elderly.care_level,
                        "admission_date": latest_admission.admission_date,
                        "hospital_name": latest_admission.hospital_name,
                        "last_meal_date": latest_admission.last_meal_date,
                        "last_meal_type": latest_admission.last_meal_type,
                        "note": latest_admission.note
                    })
        
        # 입주자가 있는 방 수 계산 (중복 제거)
        occupied_room_ids = set()
        for resident in elderly_residents:
            if resident.room_id:
                occupied_room_ids.add(resident.room_id)
        
        occupied_rooms = len(occupied_room_ids)
        vacant_rooms = total_rooms - occupied_rooms
        occupancy_rate = round(occupied_rooms / total_rooms * 100, 2) if total_rooms > 0 else 0
        
        return {
            "building_id": building_id,
            "building_name": building.name,
            "building_address": building.address,
            "statistics": {
                "total_rooms": total_rooms,
                "occupied_rooms": occupied_rooms,
                "vacant_rooms": vacant_rooms,
                "occupancy_rate": occupancy_rate,
                "total_residents": total_residents,
                "hospitalized_count": hospitalized_count,
                "non_hospitalized_count": total_residents - hospitalized_count,
                "hospitalization_rate": round(hospitalized_count / total_residents * 100, 2) if total_residents > 0 else 0,
                "care_level_distribution": care_level_distribution,
                "age_distribution": age_distribution,
                "gender_distribution": gender_distribution
            },
            "hospitalized_residents": hospitalized_residents
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"建物統計の取得中にエラーが発生しました: {str(e)}")

