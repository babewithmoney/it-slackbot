from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
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
        if not campaign or not campaign.crafted_msg:
            raise ValueError("Campaign not found or missing message")
            
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
                        # Ensure we have a valid message
                        message = campaign.crafted_msg.strip()
                        if not message:
                            message = "Hi! We're reviewing our software licenses. Could you please confirm if you still need access?"
                        
                        # Send message
                        response = self.client.chat_postMessage(
                            channel=channel["channel"]["id"],
                            text=message,
                            unfurl_links=False,
                            unfurl_media=False
                        )
                        
                        if response["ok"]:
                            # Update user record
                            user.num_pings = 1
                            user.last_ping = datetime.utcnow()
                            stats["success"] += 1
                        else:
                            stats["failed"] += 1
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

    async def check_campaign_completion(self, campaign_id: int, db: Session) -> None:
        """Check if campaign is complete and notify admin"""
        try:
            # Get campaign and its users
            campaign = db.query(Campaign).filter_by(id=campaign_id).first()
            if not campaign or campaign.state != 'ONGOING':
                return

            # Count total and responded users
            total_users = db.query(CampaignUser).filter(
                CampaignUser.campaign_id == campaign_id
            ).count()
            
            responded_users = db.query(CampaignUser).filter(
                and_(
                    CampaignUser.campaign_id == campaign_id,
                    CampaignUser.response_confirmed == True
                )
            ).count()

            # If all users have responded
            if total_users == responded_users and total_users > 0:
                # Get response statistics
                response_stats = db.query(
                    CampaignUser.response,
                    func.count(CampaignUser.id)
                ).filter(
                    CampaignUser.campaign_id == campaign_id,
                    CampaignUser.response_confirmed == True
                ).group_by(CampaignUser.response).all()

                stats = {
                    'yes': 0,
                    'no': 0,
                    'unclear': 0
                }
                
                for response, count in response_stats:
                    if response in stats:
                        stats[response] = count

                # Update campaign status
                campaign.state = 'COMPLETED'
                db.commit()

                # Notify admin
                try:
                    channel = self.client.conversations_open(users=[campaign.manager_id])
                    if channel["ok"]:
                        message = (
                            "🎉 Campaign Completed!\n\n"
                            f"Final Results:\n"
                            f"• Total users contacted: {total_users}\n"
                            f"• Users keeping license: {stats['yes']}\n"
                            f"• Users releasing license: {stats['no']}\n"
                            f"• Unclear responses: {stats['unclear']}\n\n"
                            f"Detailed responses are available in your Google Sheet:\n{campaign.google_sheet_link}"
                        )
                        
                        self.client.chat_postMessage(
                            channel=channel["channel"]["id"],
                            text=message
                        )
                
                except SlackApiError as e:
                    print(f"Error sending completion notification: {str(e)}")

        except Exception as e:
            print(f"Error checking campaign completion: {str(e)}")
            db.rollback()