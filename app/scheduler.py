from fastapi import FastAPI
from fastapi_utils.tasks import repeat_every
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.db import get_db
from app.notification_handler import NotificationHandler
from app.models import Campaign, CampaignUser
from datetime import datetime, timedelta
import os

class NotificationScheduler:
    def __init__(self, app: FastAPI):
        self.app = app
        self.notification_handler = NotificationHandler(os.getenv("SLACK_BOT_TOKEN"))

    async def check_stale_campaigns(self, db: Session):
        """Check campaigns that are inactive for too long"""
        try:
            # Find campaigns older than 7 days
            cutoff_date = datetime.utcnow() - timedelta(days=7)
            stale_campaigns = db.query(Campaign).filter(
                and_(
                    Campaign.state == 'ONGOING',
                    Campaign.notification_start_time < cutoff_date
                )
            ).all()

            for campaign in stale_campaigns:
                try:
                    # Notify admin about stale campaign
                    channel = self.notification_handler.client.conversations_open(
                        users=[campaign.manager_id]
                    )
                    if channel["ok"]:
                        message = (
                            "⚠️ Campaign Status Alert\n\n"
                            f"Your campaign started on {campaign.notification_start_time.strftime('%Y-%m-%d')} "
                            "has been running for over 7 days.\n\n"
                            "Please check the Google Sheet for current status and consider:\n"
                            "• Sending final reminders to pending users\n"
                            "• Marking the campaign as completed\n\n"
                            f"Google Sheet: {campaign.google_sheet_link}"
                        )
                        
                        self.notification_handler.client.chat_postMessage(
                            channel=channel["channel"]["id"],
                            text=message
                        )
                
                except Exception as e:
                    print(f"Error notifying about stale campaign {campaign.id}: {str(e)}")
                    
        except Exception as e:
            print(f"Error checking stale campaigns: {str(e)}")

    def init_scheduler(self):
        @self.app.on_event("startup")
        @repeat_every(seconds=60 * 60 * 24)  # Run every 24 hours
        async def scheduled_tasks():
            """Run scheduled tasks"""
            try:
                db: Session = next(get_db())
                
                # 1. Check and resend notifications to users
                await self.notification_handler.check_and_resend_notifications(db)
                
                # 2. Check ongoing campaigns for completion
                ongoing_campaigns = db.query(Campaign).filter(
                    Campaign.state == 'ONGOING'
                ).all()
                
                for campaign in ongoing_campaigns:
                    await self.notification_handler.check_campaign_completion(campaign.id, db)
                
                # 3. Check for stale campaigns
                await self.check_stale_campaigns(db)
                
                print("Scheduled tasks completed successfully")
                
            except Exception as e:
                print(f"Error in scheduler tasks: {str(e)}")
            finally:
                db.close()