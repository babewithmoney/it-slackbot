# app/campaign.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import Campaign, CampaignUser
from app.config import settings
from app.nlp import interpret_response
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import datetime

router = APIRouter()
slack_client = WebClient(token=settings.SLACK_BOT_TOKEN)

@router.post("/campaign/start")
async def start_campaign(campaign_id: int, db: Session = Depends(get_db)):
    """Start the campaign by sending initial messages to all users."""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        return {"error": "Campaign not found."}
    
    for user in db.query(CampaignUser).filter(CampaignUser.campaign_id == campaign_id).all():
        try:
            slack_client.chat_postMessage(
                channel=user.slack_user_id,
                text=f"{campaign.prompt} Please respond with Yes or No."
            )
        except SlackApiError as e:
            print(f"Error sending message to {user.slack_user_id}: {e}")
    
    # Update the campaign state to "ONGOING"
    campaign.state = "ONGOING"
    db.commit()
    return {"message": "Campaign started"}

@router.post("/campaign/follow_up")
async def follow_up_campaign(campaign_id: int, db: Session = Depends(get_db)):
    """Send follow-up messages to users who haven't responded."""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        return {"error": "Campaign not found."}

    for user in db.query(CampaignUser).filter(CampaignUser.campaign_id == campaign_id, CampaignUser.response == None).all():
        if user.num_pings < settings.MAX_PINGS:
            try:
                slack_client.chat_postMessage(
                    channel=user.slack_user_id,
                    text="Friendly reminder to respond to the license check message."
                )
                user.num_pings += 1
                user.last_ping = datetime.datetime.utcnow()
            except SlackApiError as e:
                print(f"Error sending follow-up to {user.slack_user_id}: {e}")
    
    db.commit()
    return {"message": "Follow-ups sent"}

@router.post("/campaign/record_response")
async def record_response(user_id: str, response_text: str, db: Session = Depends(get_db)):
    """Process and record a user's response."""
    response = interpret_response(response_text)
    user = db.query(CampaignUser).filter(CampaignUser.slack_user_id == user_id).first()
    if user:
        user.response = response
        db.commit()
    
    return {"message": f"Response '{response}' recorded for user {user_id}"}
