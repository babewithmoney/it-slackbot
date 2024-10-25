from fastapi import FastAPI
from fastapi_utils.tasks import repeat_every
from sqlalchemy.orm import Session
from app.db import get_db
from app.notification_handler import NotificationHandler
import os

class NotificationScheduler:
    def __init__(self, app: FastAPI):
        self.app = app
        self.notification_handler = NotificationHandler(os.getenv("SLACK_BOT_TOKEN"))

    def init_scheduler(self):
        @self.app.on_event("startup")
        @repeat_every(seconds=60 * 60 * 24)  # Run every 24 hours
        async def check_and_send_notifications():
            """Check for pending notifications and send reminders"""
            try:
                # Get DB session
                db: Session = next(get_db())
                
                # Check and resend notifications
                await self.notification_handler.check_and_resend_notifications(db)
                
            except Exception as e:
                print(f"Error in notification scheduler: {str(e)}")
            finally:
                db.close()