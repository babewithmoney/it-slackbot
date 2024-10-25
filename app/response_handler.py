from fastapi import APIRouter, Depends, Request, BackgroundTasks
from sqlalchemy.orm import Session
from app.db import get_db, get_db_context
from app.models import Campaign, CampaignUser
from app.message_processor import MessageProcessor
from app.sheet_manager import SheetManager
from datetime import datetime
import os
from slack_sdk import WebClient
from typing import Dict, Any
import json

router = APIRouter()
slack_client = WebClient(token=os.getenv("SLACK_BOT_TOKEN"))
message_processor = MessageProcessor(os.getenv("OPENAI_API_KEY"))
sheet_manager = SheetManager(os.getenv("GOOGLE_SHEETS_CREDENTIALS"))

async def handle_user_response(event: Dict[str, Any], db: Session, campaign_user: CampaignUser) -> None:
    """Handle a user's response to the license inquiry"""
    try:
        channel_id = event['channel']
        user_message = event['text']
        
        # If user hasn't responded yet or hasn't confirmed
        if not campaign_user.response or not campaign_user.response_confirmed:
            # Analyze the response using ChatGPT
            decision, confidence = await message_processor.analyze_response(user_message)
            
            # If this is the initial response
            if not campaign_user.response:
                campaign_user.response = decision
                campaign_user.response_confidence = confidence
                campaign_user.raw_response = user_message
                campaign_user.response_time = datetime.utcnow()
                
                # Ask for confirmation
                confirmation_message = (
                    f"Based on your response, I understand that you *{'want' if decision == 'yes' else 'do not want'}* "
                    "to keep your license. Is this correct?\n\n"
                    "Please reply with 'yes' to confirm or 'no' to clarify your response."
                )
                slack_client.chat_postMessage(
                    channel=channel_id,
                    text=confirmation_message
                )
                
            # If this is the confirmation response
            elif not campaign_user.response_confirmed:
                if user_message.lower().strip() == 'yes':
                    campaign_user.response_confirmed = True
                    
                    # Update Google Sheet
                    campaign = db.query(Campaign).filter_by(id=campaign_user.campaign_id).first()
                    if campaign and campaign.google_sheet_link:
                        success, message = sheet_manager.update_user_response(
                            campaign.google_sheet_link,
                            campaign_user.user_email,
                            campaign_user.num_pings,
                            campaign_user.response
                        )
                        if not success:
                            print(f"Error updating sheet: {message}")
                    
                    # Send confirmation message
                    slack_client.chat_postMessage(
                        channel=channel_id,
                        text="Thank you for confirming your response. Your decision has been recorded."
                    )
                    
                elif user_message.lower().strip() == 'no':
                    # Reset response and ask again
                    campaign_user.response = None
                    campaign_user.response_confidence = None
                    campaign_user.raw_response = None
                    campaign_user.response_time = None
                    
                    slack_client.chat_postMessage(
                        channel=channel_id,
                        text="I apologize for the misunderstanding. Could you please clarify your decision about the license?"
                    )
                    
                else:
                    # Invalid confirmation response
                    slack_client.chat_postMessage(
                        channel=channel_id,
                        text="Please respond with 'yes' to confirm or 'no' to clarify your previous response."
                    )
            
            db.commit()
            
        else:
            # User has already confirmed their response
            slack_client.chat_postMessage(
                channel=channel_id,
                text="Your response has already been recorded. If you need any changes, please contact your IT team."
            )
            
    except Exception as e:
        db.rollback()
        print(f"Error handling user response: {str(e)}")
        slack_client.chat_postMessage(
            channel=channel_id,
            text="Sorry, there was an error processing your response. Please try again or contact your IT team."
        )

@router.post("/slack/message_events")
async def handle_dm_events(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Handle DM events from users"""
    try:
        event_data = await request.json()
        
        if event_data.get('type') == 'url_verification':
            return {"challenge": event_data['challenge']}
            
        if event_data.get('type') == 'event_callback':
            event = event_data['event']
            
            # Ignore bot messages
            if event.get('bot_id') or event.get('subtype') == 'bot_message':
                return {"status": "success", "message": "Ignored bot message"}
                
            # Handle DM messages
            if event['type'] == 'message' and event.get('channel_type') == 'im':
                user_id = event['user']
                
                # Process in background
                async def process_response():
                    with get_db_context() as db:
                        # Find the user in an active campaign
                        campaign_user = db.query(CampaignUser)\
                            .join(Campaign)\
                            .filter(
                                CampaignUser.slack_user_id == user_id,
                                Campaign.state == 'ONGOING'
                            ).first()
                            
                        if campaign_user:
                            await handle_user_response(event, db, campaign_user)
                
                background_tasks.add_task(process_response)
                return {"status": "success", "message": "Processing response"}
            
    except Exception as e:
        print(f"Error in handle_dm_events: {str(e)}")
        return {"status": "error", "message": str(e)}
        
    return {"status": "success"}