# app/config.py
import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    DATABASE_URL = os.getenv("DATABASE_URL")

    # Campaign settings
    FOLLOW_UP_INTERVAL_HOURS = 24  # Interval in hours for follow-up messages
    MAX_PINGS = 3  # Maximum number of pings per user

settings = Settings()

# from pydantic_settings import BaseSettings
# from functools import lru_cache

# class Settings(BaseSettings):
#     SLACK_BOT_TOKEN: str
#     OPENAI_API_KEY: str
#     GOOGLE_SHEETS_CREDENTIALS: str
#     DATABASE_URL: str
#     NOTIFICATION_INTERVAL_HOURS: int = 24
#     MAX_NOTIFICATION_ATTEMPTS: int = 3
    
#     class Config:
#         env_file = ".env"

# @lru_cache()
# def get_settings():
#     return Settings()
