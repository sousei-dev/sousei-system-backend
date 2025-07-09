from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = "postgresql://postgres.bbxqerucydvpjlohvcfh:zgkswkrnxo132!@aws-0-ap-northeast-1.pooler.supabase.com:6543/postgres"  # Supabase 접속정보 입력
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)