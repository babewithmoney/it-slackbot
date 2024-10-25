# # app/db.py
# from sqlalchemy import create_engine
# from sqlalchemy.ext.declarative import declarative_base
# from sqlalchemy.orm import sessionmaker
# import os
from app.config import settings

DATABASE_URL = settings.DATABASE_URL.replace("mysql://", "mysql+pymysql://")

# engine = create_engine(DATABASE_URL)
# SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
# Base = declarative_base()

# def get_db():
#     db = SessionLocal()
#     try:
#         yield db
#     finally:
#         db.close()

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
import os

engine = create_engine(
    DATABASE_URL,
    pool_size=20,  # Increased for background tasks
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=3600  # Recycle connections after 1 hour
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        if db:
            db.close()

@contextmanager
def get_db_context() -> Session:
    """Context manager for database sessions in background tasks"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Use this in background tasks:
# with get_db_context() as db:
#     # your code here
