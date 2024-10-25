from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import List, Dict
from app.models import Campaign, CampaignUser

class NotificationHandler:
    def __init__(self, slack_token: str):
        self.client = WebClient(token=slack_token)
    
    async def send_initial_notifications(self, campaign_id: int, db: Session) -> Dict[str, int]:
        """
        Send initial notifications to all users in the campaign
        Returns: Dict with success and failure counts
        """
        stats = {"success": 0, "failed": 0}
        
        # Get campaign and users
        campaign = db.query(Campaign).filter_by(id=campaign_id).first()
        if not campaign:
            raise ValueError("Campaign not found")
            
        users = db.query(CampaignUser).filter_by(campaign_id=campaign_id).all()
        
        for user in users:
            try:
                # Try to find Slack user by email
                user_info = self.client.users_lookupByEmail(email=user.user_email)
                if user_info["ok"]:
                    slack_user_id = user_info["user"]["id"]
                    user.slack_user_id = slack_user_id
                    
                    # Open DM channel
                    channel = self.client.conversations_open(users=[slack_user_id])
                    if channel["ok"]:
                        # Send message
                        self.client.chat_postMessage(
                            channel=channel["channel"]["id"],
                            text=campaign.crafted_msg
                        )
                        
                        # Update user record
                        user.num_pings = 1
                        user.last_ping = datetime.utcnow()
                        stats["success"] += 1
                    else:
                        stats["failed"] += 1
                else:
                    stats["failed"] += 1
                    
            except SlackApiError as e:
                stats["failed"] += 1
                print(f"Error sending notification to {user.user_email}: {str(e)}")
                
        db.commit()
        return stats
    
    async def check_and_resend_notifications(self, db: Session):
        """
        Check for users who haven't responded and resend notifications if needed
        """
        # Get users who haven't responded and were last pinged > 24 hours ago
        users = db.query(CampaignUser).filter(
            CampaignUser.response.is_(None),
            CampaignUser.num_pings < 3,
            CampaignUser.last_ping < datetime.utcnow() - timedelta(hours=24)
        ).all()
        
        for user in users:
            try:
                if user.slack_user_id:
                    # Get campaign for message
                    campaign = db.query(Campaign).filter_by(id=user.campaign_id).first()
                    
                    # Open DM channel
                    channel = self.client.conversations_open(users=[user.slack_user_id])
                    if channel["ok"]:
                        # Send reminder message
                        self.client.chat_postMessage(
                            channel=channel["channel"]["id"],
                            text=f"Reminder: {campaign.crafted_msg}"
                        )
                        
                        # Update ping count and timestamp
                        user.num_pings += 1
                        user.last_ping = datetime.utcnow()
                        
            except SlackApiError as e:
                print(f"Error resending notification to {user.user_email}: {str(e)}")
                
        db.commit()