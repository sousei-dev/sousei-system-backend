from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from database import SessionLocal
from models import Building, UserBuildingPermission, Room, Student, Resident
from utils.dependencies import get_current_user
from database_log import create_database_log
import os
from supabase import create_client
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/buildings", tags=["빌딩 권한 관리"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ===== 빌딩 권한 관리 API =====

@router.post("/{building_id}/permissions/{user_id}")
def grant_building_permission(
    building_id: str,
    user_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """특정 사용자에게 빌딩 접근 권한 부여 (관리자 전용)"""
    try:
        # 관리자 권한 확인
        if current_user.get("role") not in ["admin", "manager"]:
            raise HTTPException(
                status_code=403,
                detail="管理者権限が必要です"
            )
        
        # 빌딩 존재 여부 확인
        building = db.query(Building).filter(Building.id == building_id).first()
        if not building:
            raise HTTPException(status_code=404, detail="建物が見つかりません")
        
        # 이미 권한이 있는지 확인
        existing_permission = db.query(UserBuildingPermission).filter(
            UserBuildingPermission.user_id == user_id,
            UserBuildingPermission.building_id == building_id
        ).first()
        
        if existing_permission:
            return {
                "message": "既に権限が付与されています",
                "user_id": user_id,
                "building_id": building_id,
                "building_name": building.name
            }
        
        # 권한 부여
        new_permission = UserBuildingPermission(
            user_id=user_id,
            building_id=building_id,
            created_by=current_user["id"]
        )
        db.add(new_permission)
        db.commit()
        
        # 로그 생성
        create_database_log(
            db=db,
            table_name="user_building_permissions",
            record_id=f"{user_id}_{building_id}",
            action="CREATE",
            user_id=current_user["id"],
            new_values={
                "user_id": user_id,
                "building_id": building_id,
                "building_name": building.name
            },
            note=f"建物アクセス権限付与 - {building.name}"
        )
        
        logger.info(f"빌딩 권한 부여 완료 - 사용자: {user_id}, 빌딩: {building.name}")
        
        return {
            "message": "建物アクセス権限が正常に付与されました",
            "user_id": user_id,
            "building_id": building_id,
            "building_name": building.name
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"権限付与中にエラーが発生しました: {str(e)}"
        )

@router.delete("/{building_id}/permissions/{user_id}")
def revoke_building_permission(
    building_id: str,
    user_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """특정 사용자의 빌딩 접근 권한 제거 (관리자 전용)"""
    try:
        # 관리자 권한 확인
        if current_user.get("role") not in ["admin", "manager"]:
            raise HTTPException(
                status_code=403,
                detail="管理者権限が必要です"
            )
        
        # 권한 존재 여부 확인
        permission = db.query(UserBuildingPermission).filter(
            UserBuildingPermission.user_id == user_id,
            UserBuildingPermission.building_id == building_id
        ).first()
        
        if not permission:
            raise HTTPException(
                status_code=404,
                detail="該当の権限が見つかりません"
            )
        
        # 빌딩 정보 조회
        building = db.query(Building).filter(Building.id == building_id).first()
        building_name = building.name if building else "Unknown"
        
        # 권한 제거
        db.delete(permission)
        db.commit()
        
        # 로그 생성
        create_database_log(
            db=db,
            table_name="user_building_permissions",
            record_id=f"{user_id}_{building_id}",
            action="DELETE",
            user_id=current_user["id"],
            old_values={
                "user_id": user_id,
                "building_id": building_id,
                "building_name": building_name
            },
            note=f"建物アクセス権限削除 - {building_name}"
        )
        
        logger.info(f"빌딩 권한 제거 완료 - 사용자: {user_id}, 빌딩: {building_name}")
        
        return {
            "message": "建物アクセス権限が正常に削除されました",
            "user_id": user_id,
            "building_id": building_id,
            "building_name": building_name
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"権限削除中にエラーが発生しました: {str(e)}"
        )

@router.get("/permissions/user/{user_id}")
def get_user_building_permissions(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """특정 사용자의 빌딩 접근 권한 목록 조회"""
    try:
        # 본인 또는 관리자만 조회 가능
        if user_id != current_user["id"] and current_user.get("role") not in ["admin", "manager"]:
            raise HTTPException(
                status_code=403,
                detail="権限がありません"
            )
        
        # 사용자의 권한 목록 조회
        permissions = db.query(UserBuildingPermission).filter(
            UserBuildingPermission.user_id == user_id
        ).options(
            joinedload(UserBuildingPermission.building)
        ).all()
        
        # 빌딩 정보 포함
        buildings_list = []
        for perm in permissions:
            if perm.building:
                buildings_list.append({
                    "building_id": str(perm.building.id),
                    "building_name": perm.building.name,
                    "address": perm.building.address,
                    "building_type": perm.building.building_type,
                    "resident_type": perm.building.resident_type,
                    "granted_at": perm.created_at,
                    "granted_by": perm.created_by
                })
        
        return {
            "user_id": user_id,
            "total_buildings": len(buildings_list),
            "buildings": buildings_list
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"権限リストの取得中にエラーが発生しました: {str(e)}"
        )

@router.get("/{building_id}/permissions/users")
def get_building_permitted_users(
    building_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """특정 빌딩에 접근 권한이 있는 사용자 목록 조회 (관리자 전용)"""
    try:
        # 관리자 권한 확인
        if current_user.get("role") not in ["admin", "manager"]:
            raise HTTPException(
                status_code=403,
                detail="管理者権限が必要です"
            )
        
        # 빌딩 존재 여부 확인
        building = db.query(Building).filter(Building.id == building_id).first()
        if not building:
            raise HTTPException(status_code=404, detail="建物が見つかりません")
        
        # 권한이 있는 사용자 목록 조회
        permissions = db.query(UserBuildingPermission).filter(
            UserBuildingPermission.building_id == building_id
        ).all()
        
        # Supabase에서 사용자 정보 조회
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_ANON_KEY")
        supabase = create_client(supabase_url, supabase_key)
        
        users_list = []
        if permissions:
            user_ids = [perm.user_id for perm in permissions]
            
            try:
                # Supabase profiles에서 사용자 정보 조회
                profiles_result = supabase.table('profiles').select('*').in_('id', user_ids).execute()
                profiles_data = {profile['id']: profile for profile in profiles_result.data} if profiles_result.data else {}
                
                for perm in permissions:
                    profile = profiles_data.get(perm.user_id, {})
                    users_list.append({
                        "user_id": perm.user_id,
                        "user_name": profile.get('name', '사용자'),
                        "user_email": profile.get('email', ''),
                        "user_role": profile.get('role', ''),
                        "user_department": profile.get('department', ''),
                        "granted_at": perm.created_at,
                        "granted_by": perm.created_by
                    })
            except Exception as profile_error:
                logger.error(f"프로필 조회 실패: {profile_error}")
                # 프로필 조회 실패 시 기본 정보만
                for perm in permissions:
                    users_list.append({
                        "user_id": perm.user_id,
                        "user_name": "사용자",
                        "granted_at": perm.created_at,
                        "granted_by": perm.created_by
                    })
        
        return {
            "building_id": building_id,
            "building_name": building.name,
            "total_users": len(users_list),
            "users": users_list
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"権限ユーザーリストの取得中にエラーが発生しました: {str(e)}"
        )

@router.get("/my-buildings")
def get_my_accessible_buildings(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """현재 로그인한 사용자가 관리 가능한 빌딩 목록 조회"""
    try:
        # admin, manager는 모든 빌딩 조회
        if current_user.get("role") in ["admin", "manager"]:
            buildings = db.query(Building).order_by(Building.name.asc()).all()
            
            buildings_list = []
            for building in buildings:
                # 각 빌딩의 현재 거주자 수 계산
                active_residents_count = db.query(Resident).join(
                    Room, Resident.room_id == Room.id
                ).filter(
                    Room.building_id == building.id,
                    Resident.is_active == True,
                    Resident.check_out_date.is_(None)
                ).count()
                
                # 총 방 수
                total_rooms = db.query(Room).filter(Room.building_id == building.id).count()
                
                buildings_list.append({
                    "building_id": str(building.id),
                    "building_name": building.name,
                    "address": building.address,
                    "building_type": building.building_type,
                    "resident_type": building.resident_type,
                    "total_rooms": total_rooms,
                    "active_residents_count": active_residents_count,
                    "has_full_access": True  # 관리자는 전체 접근 권한
                })
            
            return {
                "user_id": current_user["id"],
                "user_role": current_user.get("role"),
                "has_full_access": True,
                "total_buildings": len(buildings_list),
                "buildings": buildings_list
            }
        
        # 일반 사용자는 권한이 있는 빌딩만 조회
        permissions = db.query(UserBuildingPermission).filter(
            UserBuildingPermission.user_id == current_user["id"]
        ).options(
            joinedload(UserBuildingPermission.building)
        ).all()
        
        buildings_list = []
        for perm in permissions:
            if perm.building:
                # 각 빌딩의 현재 거주자 수 계산
                active_residents_count = db.query(Resident).join(
                    Room, Resident.room_id == Room.id
                ).filter(
                    Room.building_id == perm.building.id,
                    Resident.is_active == True,
                    Resident.check_out_date.is_(None)
                ).count()
                
                # 총 방 수
                total_rooms = db.query(Room).filter(Room.building_id == perm.building.id).count()
                
                buildings_list.append({
                    "building_id": str(perm.building.id),
                    "building_name": perm.building.name,
                    "address": perm.building.address,
                    "building_type": perm.building.building_type,
                    "resident_type": perm.building.resident_type,
                    "total_rooms": total_rooms,
                    "active_residents_count": active_residents_count,
                    "granted_at": perm.created_at,
                    "granted_by": perm.created_by,
                    "has_full_access": False  # 일반 사용자는 제한된 접근
                })
        
        return {
            "user_id": current_user["id"],
            "user_role": current_user.get("role"),
            "has_full_access": False,
            "total_buildings": len(buildings_list),
            "buildings": buildings_list
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"내 빌딩 목록 조회 실패: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"建物リストの取得中にエラーが発生しました: {str(e)}"
        )

@router.get("/{building_id}/residents")
def get_building_residents(
    building_id: str,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """특정 빌딩의 거주자 목록 조회 (활성 거주자만) - 권한 체크"""
    try:
        # 권한 체크
        if current_user.get("role") not in ["admin", "manager"]:
            # 해당 빌딩에 대한 권한 확인
            has_permission = db.query(UserBuildingPermission).filter(
                UserBuildingPermission.user_id == current_user["id"],
                UserBuildingPermission.building_id == building_id
            ).first()
            
            if not has_permission:
                raise HTTPException(
                    status_code=403,
                    detail="この建物へのアクセス権限がありません"
                )
        
        # 빌딩 존재 여부 확인
        building = db.query(Building).filter(Building.id == building_id).first()
        if not building:
            raise HTTPException(status_code=404, detail="建物が見つかりません")
        
        # 해당 빌딩의 활성 거주자 조회
        query = db.query(Resident).options(
            joinedload(Resident.room),
            joinedload(Resident.resident)  # Student 정보
        ).join(
            Room, Resident.room_id == Room.id
        ).filter(
            Room.building_id == building_id,
            Resident.is_active == True,
            Resident.check_out_date.is_(None)
        ).order_by(Room.room_number.asc())
        
        # 전체 항목 수
        total_count = query.count()
        
        # 페이지네이션
        residents = query.offset((page - 1) * page_size).limit(page_size).all()
        
        # 전체 페이지 수
        total_pages = (total_count + page_size - 1) // page_size
        
        # 거주자 데이터 구성
        residents_list = []
        for resident in residents:
            # Student 정보 조회
            student = db.query(Student).filter(Student.id == resident.resident_id).first()
            
            resident_data = {
                "resident_id": str(resident.id),
                "student_id": str(resident.resident_id) if resident.resident_id else None,
                "student_name": student.name if student else "Unknown",
                "student_email": student.email if student else None,
                "student_phone": student.phone if student else None,
                "student_type": student.student_type if student else None,
                "nationality": student.nationality if student else None,
                "residence_card_expiry": student.residence_card_expiry if student else None,
                "company_name": student.company.name if student and student.company else None,
                "grade_name": student.grade.name if student and student.grade else None,
                "room_id": str(resident.room.id) if resident.room else None,
                "room_number": resident.room.room_number if resident.room else None,
                "floor": resident.room.floor if resident.room else None,
                "check_in_date": resident.check_in_date,
                "is_active": resident.is_active,
                "status": student.status if student else None
            }
            residents_list.append(resident_data)
        
        return {
            "building_id": building_id,
            "building_name": building.name,
            "building_address": building.address,
            "total_residents": total_count,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "residents": residents_list
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"빌딩 거주자 조회 실패: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"建物の居住者リストの取得中にエラーが発生しました: {str(e)}"
        )

