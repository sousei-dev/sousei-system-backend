from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from typing import Optional, List
from database import SessionLocal
from models import CareItem, CareMealPrice, CareUtilityPrice
from schemas import CareItemResponse, CareMealPriceCreate, CareMealPriceUpdate, CareMealPriceResponse, CareUtilityPriceCreate, CareUtilityPriceUpdate, CareUtilityPriceResponse
from datetime import datetime
import uuid

router = APIRouter(prefix="/elderly-care", tags=["고령자 케어 관리"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/care-items", response_model=List[CareItemResponse])
def get_care_items(db: Session = Depends(get_db)):
    """케어 항목 목록 조회"""
    try:
        care_items = db.query(CareItem).all()
        
        result = []
        for item in care_items:
            item_data = {
                "id": str(item.id),
                "item_name": item.item_name,
                "description": item.description,
                "category": item.category,
                "is_active": item.is_active,
                "created_at": item.created_at
            }
            result.append(item_data)
        
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"케어 항목 조회 중 오류가 발생했습니다: {str(e)}")

@router.get("/care-meal-prices", response_model=List[CareMealPriceResponse])
def get_care_meal_prices(db: Session = Depends(get_db)):
    """케어 식사 가격 목록 조회"""
    try:
        meal_prices = db.query(CareMealPrice).all()
        
        result = []
        for price in meal_prices:
            price_data = {
                "id": str(price.id),
                "meal_type": price.meal_type,
                "price": price.price,
                "description": price.description,
                "is_active": price.is_active,
                "created_at": price.created_at
            }
            result.append(price_data)
        
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"케어 식사 가격 조회 중 오류가 발생했습니다: {str(e)}")

@router.post("/care-meal-prices", response_model=CareMealPriceResponse)
def create_care_meal_price(
    meal_price_data: CareMealPriceCreate,
    db: Session = Depends(get_db)
):
    """새로운 케어 식사 가격 생성"""
    try:
        # 중복 확인
        existing_price = db.query(CareMealPrice).filter(
            CareMealPrice.meal_type == meal_price_data.meal_type
        ).first()
        
        if existing_price:
            raise HTTPException(status_code=400, detail="이미 존재하는 식사 타입입니다")
        
        # 새 케어 식사 가격 생성
        new_meal_price = CareMealPrice(
            id=str(uuid.uuid4()),
            meal_type=meal_price_data.meal_type,
            price=meal_price_data.price,
            description=meal_price_data.description,
            is_active=meal_price_data.is_active or True
        )
        
        db.add(new_meal_price)
        db.commit()
        db.refresh(new_meal_price)
        
        return {
            "id": str(new_meal_price.id),
            "meal_type": new_meal_price.meal_type,
            "price": new_meal_price.price,
            "description": new_meal_price.description,
            "is_active": new_meal_price.is_active,
            "created_at": new_meal_price.created_at
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"케어 식사 가격 생성 중 오류가 발생했습니다: {str(e)}")

@router.put("/care-meal-prices/{price_id}", response_model=CareMealPriceResponse)
def update_care_meal_price(
    price_id: str,
    meal_price_update: CareMealPriceUpdate,
    db: Session = Depends(get_db)
):
    """케어 식사 가격 수정"""
    try:
        meal_price = db.query(CareMealPrice).filter(CareMealPrice.id == price_id).first()
        if not meal_price:
            raise HTTPException(status_code=404, detail="케어 식사 가격을 찾을 수 없습니다")
        
        # 업데이트할 필드들
        update_data = meal_price_update.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(meal_price, field, value)
        
        db.commit()
        db.refresh(meal_price)
        
        return {
            "id": str(meal_price.id),
            "meal_type": meal_price.meal_type,
            "price": meal_price.price,
            "description": meal_price.description,
            "is_active": meal_price.is_active,
            "created_at": meal_price.created_at
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"케어 식사 가격 수정 중 오류가 발생했습니다: {str(e)}")

@router.delete("/care-meal-prices/{price_id}")
def delete_care_meal_price(price_id: str, db: Session = Depends(get_db)):
    """케어 식사 가격 삭제"""
    try:
        meal_price = db.query(CareMealPrice).filter(CareMealPrice.id == price_id).first()
        if not meal_price:
            raise HTTPException(status_code=404, detail="케어 식사 가격을 찾을 수 없습니다")
        
        db.delete(meal_price)
        db.commit()
        
        return {
            "message": "케어 식사 가격이 성공적으로 삭제되었습니다",
            "deleted_price_id": price_id
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"케어 식사 가격 삭제 중 오류가 발생했습니다: {str(e)}")

@router.get("/care-utility-prices", response_model=List[CareUtilityPriceResponse])
def get_care_utility_prices(db: Session = Depends(get_db)):
    """케어 유틸리티 가격 목록 조회"""
    try:
        utility_prices = db.query(CareUtilityPrice).all()
        
        result = []
        for price in utility_prices:
            price_data = {
                "id": str(price.id),
                "utility_type": price.utility_type,
                "price": price.price,
                "description": price.description,
                "is_active": price.is_active,
                "created_at": price.created_at
            }
            result.append(price_data)
        
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"케어 유틸리티 가격 조회 중 오류가 발생했습니다: {str(e)}")

@router.post("/care-utility-prices", response_model=CareUtilityPriceResponse)
def create_care_utility_price(
    utility_price_data: CareUtilityPriceCreate,
    db: Session = Depends(get_db)
):
    """새로운 케어 유틸리티 가격 생성"""
    try:
        # 중복 확인
        existing_price = db.query(CareUtilityPrice).filter(
            CareUtilityPrice.utility_type == utility_price_data.utility_type
        ).first()
        
        if existing_price:
            raise HTTPException(status_code=400, detail="이미 존재하는 유틸리티 타입입니다")
        
        # 새 케어 유틸리티 가격 생성
        new_utility_price = CareUtilityPrice(
            id=str(uuid.uuid4()),
            utility_type=utility_price_data.utility_type,
            price=utility_price_data.price,
            description=utility_price_data.description,
            is_active=utility_price_data.is_active or True
        )
        
        db.add(new_utility_price)
        db.commit()
        db.refresh(new_utility_price)
        
        return {
            "id": str(new_utility_price.id),
            "utility_type": new_utility_price.utility_type,
            "price": new_utility_price.price,
            "description": new_utility_price.description,
            "is_active": new_utility_price.is_active,
            "created_at": new_utility_price.created_at
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"케어 유틸리티 가격 생성 중 오류가 발생했습니다: {str(e)}")

@router.put("/care-utility-prices/{price_id}", response_model=CareUtilityPriceResponse)
def update_care_utility_price(
    price_id: str,
    utility_price_update: CareUtilityPriceUpdate,
    db: Session = Depends(get_db)
):
    """케어 유틸리티 가격 수정"""
    try:
        utility_price = db.query(CareUtilityPrice).filter(CareUtilityPrice.id == price_id).first()
        if not utility_price:
            raise HTTPException(status_code=404, detail="케어 유틸리티 가격을 찾을 수 없습니다")
        
        # 업데이트할 필드들
        update_data = utility_price_update.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(utility_price, field, value)
        
        db.commit()
        db.refresh(utility_price)
        
        return {
            "id": str(utility_price.id),
            "utility_type": utility_price.utility_type,
            "price": utility_price.price,
            "description": utility_price.description,
            "is_active": utility_price.is_active,
            "created_at": utility_price.created_at
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"케어 유틸리티 가격 수정 중 오류가 발생했습니다: {str(e)}")

@router.delete("/care-utility-prices/{price_id}")
def delete_care_utility_price(price_id: str, db: Session = Depends(get_db)):
    """케어 유틸리티 가격 삭제"""
    try:
        utility_price = db.query(CareUtilityPrice).filter(CareUtilityPrice.id == price_id).first()
        if not utility_price:
            raise HTTPException(status_code=404, detail="케어 유틸리티 가격을 찾을 수 없습니다")
        
        db.delete(utility_price)
        db.commit()
        
        return {
            "message": "케어 유틸리티 가격이 성공적으로 삭제되었습니다",
            "deleted_price_id": price_id
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"케어 유틸리티 가격 삭제 중 오류가 발생했습니다: {str(e)}") 