from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from typing import Optional, List
from database import SessionLocal
from models import RoomCharge, ChargeItem, ChargeItemAllocation, Student, Room
from schemas import RoomChargeCreate, RoomChargeUpdate, ChargeItemCreate, ChargeItemUpdate, ChargeItemAllocationCreate, ChargeItemAllocationUpdate
from datetime import datetime
import uuid

router = APIRouter(prefix="/room-charges", tags=["방 요금 관리"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/", response_model=dict)
def create_room_charge(
    charge_data: RoomChargeCreate,
    db: Session = Depends(get_db)
):
    """새로운 방 요금 생성"""
    try:
        # 방 존재 여부 확인
        room = db.query(Room).filter(Room.id == charge_data.room_id).first()
        if not room:
            raise HTTPException(status_code=404, detail="방을 찾을 수 없습니다")
        
        # 새 방 요금 생성
        new_charge = RoomCharge(
            id=str(uuid.uuid4()),
            room_id=charge_data.room_id,
            charge_date=charge_data.charge_date,
            total_amount=charge_data.total_amount,
            description=charge_data.description,
            status=charge_data.status or "pending"
        )
        
        db.add(new_charge)
        db.commit()
        db.refresh(new_charge)
        
        return {
            "message": "방 요금이 성공적으로 생성되었습니다",
            "charge": {
                "id": str(new_charge.id),
                "room_id": str(new_charge.room_id),
                "charge_date": new_charge.charge_date,
                "total_amount": new_charge.total_amount,
                "description": new_charge.description,
                "status": new_charge.status
            }
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"방 요금 생성 중 오류가 발생했습니다: {str(e)}")

@router.get("/")
def get_room_charges(
    room_id: Optional[str] = Query(None, description="방 ID로 필터링"),
    status: Optional[str] = Query(None, description="상태로 필터링"),
    page: int = Query(1, description="페이지 번호", ge=1),
    page_size: int = Query(10, description="페이지당 항목 수", ge=1, le=100),
    db: Session = Depends(get_db)
):
    """방 요금 목록 조회"""
    try:
        query = db.query(RoomCharge).options(joinedload(RoomCharge.room))
        
        # 필터링 적용
        if room_id:
            query = query.filter(RoomCharge.room_id == room_id)
        if status:
            query = query.filter(RoomCharge.status == status)
        
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
                "room_id": str(charge.room_id),
                "room_number": charge.room.room_number if charge.room else None,
                "charge_date": charge.charge_date,
                "total_amount": charge.total_amount,
                "description": charge.description,
                "status": charge.status,
                "created_at": charge.created_at
            }
            result.append(charge_data)
        
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
        raise HTTPException(status_code=500, detail=f"방 요금 목록 조회 중 오류가 발생했습니다: {str(e)}")

@router.get("/{charge_id}")
def get_room_charge(charge_id: str, db: Session = Depends(get_db)):
    """특정 방 요금 상세 정보 조회"""
    try:
        charge = db.query(RoomCharge).options(
            joinedload(RoomCharge.room),
            joinedload(RoomCharge.items)
        ).filter(RoomCharge.id == charge_id).first()
        
        if not charge:
            raise HTTPException(status_code=404, detail="방 요금을 찾을 수 없습니다")
        
        charge_data = {
            "id": str(charge.id),
            "room_id": str(charge.room_id),
            "room_number": charge.room.room_number if charge.room else None,
            "charge_date": charge.charge_date,
            "total_amount": charge.total_amount,
            "description": charge.description,
            "status": charge.status,
            "created_at": charge.created_at,
            "items": [
                {
                    "id": str(item.id),
                    "item_name": item.item_name,
                    "amount": item.amount,
                    "description": item.description
                } for item in charge.items
            ] if charge.items else []
        }
        
        return charge_data
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"방 요금 상세 정보 조회 중 오류가 발생했습니다: {str(e)}")

@router.put("/{charge_id}")
def update_room_charge(
    charge_id: str,
    charge_update: RoomChargeUpdate,
    db: Session = Depends(get_db)
):
    """방 요금 수정"""
    try:
        charge = db.query(RoomCharge).filter(RoomCharge.id == charge_id).first()
        if not charge:
            raise HTTPException(status_code=404, detail="방 요금을 찾을 수 없습니다")
        
        # 업데이트할 필드들
        update_data = charge_update.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(charge, field, value)
        
        db.commit()
        db.refresh(charge)
        
        return {
            "message": "방 요금이 성공적으로 수정되었습니다",
            "charge": {
                "id": str(charge.id),
                "room_id": str(charge.room_id),
                "charge_date": charge.charge_date,
                "total_amount": charge.total_amount,
                "description": charge.description,
                "status": charge.status
            }
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"방 요금 수정 중 오류가 발생했습니다: {str(e)}")

@router.delete("/{charge_id}")
def delete_room_charge(charge_id: str, db: Session = Depends(get_db)):
    """방 요금 삭제"""
    try:
        charge = db.query(RoomCharge).filter(RoomCharge.id == charge_id).first()
        if not charge:
            raise HTTPException(status_code=404, detail="방 요금을 찾을 수 없습니다")
        
        # 관련된 요금 항목들도 삭제
        db.query(ChargeItem).filter(ChargeItem.room_charge_id == charge_id).delete()
        
        # 방 요금 삭제
        db.delete(charge)
        db.commit()
        
        return {
            "message": "방 요금이 성공적으로 삭제되었습니다",
            "deleted_charge_id": charge_id
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"방 요금 삭제 중 오류가 발생했습니다: {str(e)}")

@router.post("/{charge_id}/charge-items")
def add_charge_item(
    charge_id: str,
    item_data: ChargeItemCreate,
    db: Session = Depends(get_db)
):
    """방 요금에 항목 추가"""
    try:
        # 방 요금 존재 여부 확인
        charge = db.query(RoomCharge).filter(RoomCharge.id == charge_id).first()
        if not charge:
            raise HTTPException(status_code=404, detail="방 요금을 찾을 수 없습니다")
        
        # 새 요금 항목 생성
        new_item = ChargeItem(
            id=str(uuid.uuid4()),
            room_charge_id=charge_id,
            item_name=item_data.item_name,
            amount=item_data.amount,
            description=item_data.description
        )
        
        db.add(new_item)
        
        # 총 금액 업데이트
        charge.total_amount += item_data.amount
        
        db.commit()
        db.refresh(new_item)
        
        return {
            "message": "요금 항목이 성공적으로 추가되었습니다",
            "item": {
                "id": str(new_item.id),
                "room_charge_id": str(new_item.room_charge_id),
                "item_name": new_item.item_name,
                "amount": new_item.amount,
                "description": new_item.description
            }
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"요금 항목 추가 중 오류가 발생했습니다: {str(e)}")

# 이 API는 students.py로 이동되었습니다
# @router.get("/students/{student_id}/room-charges") - students.py에 있음 