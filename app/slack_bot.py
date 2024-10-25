from fastapi import APIRouter, Form, Depends, Request, BackgroundTasks
from starlette.requests import ClientDisconnect
from starlette.responses import JSONResponse
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from sqlalchemy.orm import Session
from app.models import Campaign, CampaignUser
from app.db import get_db, get_db_context
from app.user_verification import UserVerification
from app.notification_handler import NotificationHandler
from app.sheet_manager import SheetManager
from app.message_processor import MessageProcessor
from datetime import datetime
import os
import csv
import io
import json
import requests
import asyncio
from typing import Optional, Dict, Any
import httpx 

router = APIRouter()
slack_client = WebClient(token=os.getenv("SLACK_BOT_TOKEN"))
user_verification = UserVerification(os.getenv("SLACK_BOT_TOKEN"))
notification_handler = NotificationHandler(os.getenv("SLACK_BOT_TOKEN"))
sheet_manager = SheetManager(os.getenv("GOOGLE_SHEETS_CREDENTIALS"))
message_processor = MessageProcessor(os.getenv("OPENAI_API_KEY"))

def get_crafted_message_from_chatgpt(prompt: str) -> str:
    """Get a crafted message from ChatGPT."""
    try:
        api_url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": "gpt-3.5-turbo",
            "messages": [
                {
                    "role": "system",
                    "content": "You are an assistant that helps craft polite and concise messages for license renewal communications."
                },
                {
                    "role": "user",
                    "content": f"Create a polite and concise version of this message while keeping the core information: {prompt}"
                }
            ],
            "temperature": 0.7,
            "max_tokens": 500
        }

        response = requests.post(api_url, headers=headers, json=data, timeout=10)
        response.raise_for_status()
        
        response_json = response.json()
        if "choices" in response_json and len(response_json["choices"]) > 0:
            return response_json["choices"][0]["message"]["content"].strip()
        else:
            raise ValueError("No message content in ChatGPT response")
            
    except Exception as e:
        print(f"Error in get_crafted_message_from_chatgpt: {str(e)}")
        return "Hi, we're reviewing our Figma licenses. Since you haven't used it in 90+ days, could you let us know if you still need access? Releasing unused licenses helps us optimize costs. Please confirm your decision."

async def safe_parse_request(request: Request) -> Optional[Dict[Any, Any]]:
    """Safely parse request body with timeout"""
    try:
        body = await asyncio.wait_for(request.body(), timeout=5.0)
        return json.loads(body)
    except (ClientDisconnect, asyncio.TimeoutError):
        return None
    except Exception as e:
        print(f"Error parsing request: {str(e)}")
        return None

async def process_file_upload(event: dict, db: Session):
    """Handle file upload events"""
    user_id = event['user']
    channel_id = event['channel']

    try:
        # Verify if user is IT member
        is_it_member, error_msg = await user_verification.is_it_member(user_id)
        if not is_it_member:
            slack_client.chat_postMessage(
                channel=channel_id,
                text=error_msg
            )
            return

        # Process the CSV file
        for file in event['files']:
            if file['filetype'] == 'csv':
                file_url = file['url_private']
                headers = {"Authorization": f"Bearer {os.getenv('SLACK_BOT_TOKEN')}"}
                response = requests.get(file_url, headers=headers)
                response.raise_for_status()
                
                csv_content = response.content.decode('utf-8')
                reader = csv.DictReader(io.StringIO(csv_content))
                
                # Get the campaign in WAITING_FOR_FILE state
                campaign = db.query(Campaign)\
                    .filter(
                        Campaign.manager_id == user_id,
                        Campaign.state == 'WAITING_FOR_FILE'
                    ).with_for_update().first()
                
                if campaign:
                    # Add users from CSV
                    for row in reader:
                        email = row.get('email')
                        if email:
                            campaign_user = CampaignUser(
                                campaign_id=campaign.id,
                                user_email=email.strip(),
                                num_pings=0
                            )
                            db.add(campaign_user)
                    
                    # Update campaign state
                    campaign.state = 'WAITING_FOR_PROMPT'
                    db.commit()
                    
                    # Send success message
                    slack_client.chat_postMessage(
                        channel=channel_id,
                        text=(
                            "CSV uploaded successfully! ✅\n"
                            "Please provide the prompt and Google Sheets link in the following format:\n"
                            "task: [Your task description]\n"
                            "google sheet link: [Your Google Sheets URL]"
                        )
                    )
                else:
                    slack_client.chat_postMessage(
                        channel=channel_id,
                        text="No active campaign found in WAITING_FOR_FILE state. Please start a new campaign with /campaign"
                    )

    except Exception as e:
        db.rollback()
        print(f"Error processing file upload: {str(e)}")
        slack_client.chat_postMessage(
            channel=channel_id,
            text=f"Error processing CSV: {str(e)}"
        )

async def process_task_message(event: dict, db: Session):
    """Handle task and Google Sheet link messages"""
    text = event['text'].lower()
    user_id = event['user']
    channel_id = event['channel']
    
    if "task:" in text and "google sheet link:" in text:
        try:
            # Verify if user is IT member
            is_it_member, error_msg = await user_verification.is_it_member(user_id)
            if not is_it_member:
                slack_client.chat_postMessage(
                    channel=channel_id,
                    text=error_msg
                )
                return

            campaign = db.query(Campaign)\
                .filter_by(manager_id=user_id, state="WAITING_FOR_PROMPT")\
                .first()

            if not campaign:
                slack_client.chat_postMessage(
                    channel=channel_id,
                    text="Please upload a CSV file first to start a new campaign."
                )
                return

            # Extract task and Google Sheets link
            lines = event['text'].split("\n")
            google_sheet_link = next((
                line.split("google sheet link:", 1)[1].strip() 
                for line in lines 
                if "google sheet link:" in line.lower()
            ), None)
            task = next((
                line.split("task:", 1)[1].strip() 
                for line in lines 
                if "task:" in line.lower()
            ), None)

            if google_sheet_link and task:
                # Verify and initialize Google Sheet
                try:
                    sheet_success, sheet_message = sheet_manager.verify_sheet_access(google_sheet_link)
                    if not sheet_success:
                        slack_client.chat_postMessage(
                            channel=channel_id,
                            text=f"Error accessing Google Sheet: {sheet_message}"
                        )
                        return

                    success, init_message = sheet_manager.initialize_sheet(
                        google_sheet_link,
                        ["Email", "Number of Pings", "Decision"]
                    )
                    if not success:
                        slack_client.chat_postMessage(
                            channel=channel_id,
                            text=f"Error initializing Google Sheet: {init_message}"
                        )
                        return
                except Exception as e:
                    slack_client.chat_postMessage(
                        channel=channel_id,
                        text=f"Error accessing Google Sheet. Please make sure the sheet is shared with the service account and try again."
                    )
                    return

                # Update campaign
                crafted_message = get_crafted_message_from_chatgpt(task)
                campaign.google_sheet_link = google_sheet_link
                campaign.prompt = task
                campaign.crafted_msg = crafted_message
                campaign.state = "ONGOING"
                campaign.notifications_started = True
                campaign.notification_start_time = datetime.utcnow()
                db.commit()
                
                # Send notifications
                notification_stats = await notification_handler.send_initial_notifications(campaign.id, db)
                
                slack_client.chat_postMessage(
                    channel=channel_id,
                    text=(
                        f"Campaign setup complete! 🎉\n\n"
                        f"Crafted message: {crafted_message}\n\n"
                        f"Google Sheet: {google_sheet_link}\n\n"
                        f"Notifications sent: {notification_stats['success']} successful, {notification_stats['failed']} failed\n\n"
                        f"The campaign is now in progress."
                    )
                )
            else:
                slack_client.chat_postMessage(
                    channel=channel_id,
                    text="Please provide both the task and Google Sheets link in the correct format."
                )

        except Exception as e:
            db.rollback()
            print(f"Error processing task message: {str(e)}")
            slack_client.chat_postMessage(
                channel=channel_id,
                text=f"Error updating campaign: {str(e)}"
            )

async def process_event_background(event_data: dict):
    """Process events in background"""
    try:
        with get_db_context() as db:
            event = event_data['event']
            
            # Ignore bot messages
            if event.get('bot_id') or event.get('subtype') == 'bot_message':
                return

            if event['type'] == 'message' and 'files' in event:
                await process_file_upload(event, db)
            elif event['type'] == 'message' and 'text' in event:
                await process_task_message(event, db)
                
    except Exception as e:
        print(f"Error in background task: {str(e)}")

@router.post("/slack/commands")
async def handle_slash_command(
    background_tasks: BackgroundTasks,
    command: str = Form(...),
    user_id: str = Form(...),
    text: str = Form(...),
    channel_id: str = Form(...),  # Add channel_id
    response_url: str = Form(...),  # Add response_url for delayed responses  # Add background tasks
    db: Session = Depends(get_db)
):
    """Handle the /campaign command"""
    if command == "/campaign":
        # Respond immediately
        background_tasks.add_task(
            setup_campaign,
            user_id=user_id,
            response_url=response_url,
            db=db
        )
        
        return {
            "response_type": "ephemeral",
            "text": "Setting up your campaign... Please wait."
        }
    
    return {
        "response_type": "ephemeral",
        "text": "Unknown command"
    }

async def setup_campaign(user_id: str, response_url: str, db: Session):
    """Setup campaign in background"""
    try:
        # Verify if user is IT member
        is_it_member, error_msg = await user_verification.is_it_member(user_id)
        if not is_it_member:
            await send_delayed_response(response_url, {
                "response_type": "ephemeral",
                "text": error_msg,
                "replace_original": True
            })
            return

        # Check for existing active campaign
        existing_campaign = db.query(Campaign)\
            .filter_by(manager_id=user_id)\
            .filter(Campaign.state.in_(['WAITING_FOR_FILE', 'WAITING_FOR_PROMPT', 'ONGOING']))\
            .first()
        
        if existing_campaign:
            await send_delayed_response(response_url, {
                "response_type": "ephemeral",
                "text": "You already have an active campaign. Please complete it before starting a new one.",
                "replace_original": True
            })
            return

        # Open a DM channel with the user
        try:
            dm_channel = slack_client.conversations_open(users=[user_id])
            dm_channel_id = dm_channel["channel"]["id"]
            
            # Store campaign in database
            new_campaign = Campaign(
                manager_id=user_id,
                google_sheet_link="",
                state="WAITING_FOR_FILE",
                notifications_started=False
            )
            db.add(new_campaign)
            db.commit()
            db.refresh(new_campaign)

            # Send DM to user
            slack_client.chat_postMessage(
                channel=dm_channel_id,
                text=(
                    "Let's set up your license review campaign. "
                    "Please upload a CSV with email addresses and share a Google Sheets link for results tracking."
                )
            )

            # Update slash command response
            await send_delayed_response(response_url, {
                "response_type": "ephemeral",
                "text": "Campaign setup initiated! Check your DM for next steps.",
                "replace_original": True
            })

        except SlackApiError as e:
            error_message = "Could not send DM. Please make sure the bot can message you."
            print(f"Slack API Error: {str(e)}")
            await send_delayed_response(response_url, {
                "response_type": "ephemeral",
                "text": f"Error: {error_message}",
                "replace_original": True
            })

    except Exception as e:
        print(f"Error in setup_campaign: {str(e)}")
        await send_delayed_response(response_url, {
            "response_type": "ephemeral",
            "text": "An error occurred while setting up the campaign. Please try again.",
            "replace_original": True
        })

async def send_delayed_response(response_url: str, message: dict):
    """Send delayed response to Slack"""
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                response_url,
                json=message,
                timeout=5.0
            )
    except Exception as e:
        print(f"Error sending delayed response: {str(e)}")

async def handle_dm_response(event: dict, db: Session):
    """Handle DM responses from users"""
    try:
        user_id = event['user']
        channel_id = event['channel']
        user_message = event['text']

        # Find the user in an active campaign
        campaign_user = db.query(CampaignUser)\
            .join(Campaign)\
            .filter(
                CampaignUser.slack_user_id == user_id,
                Campaign.state == 'ONGOING'
            ).first()

        if campaign_user:
            if not campaign_user.response or not campaign_user.response_confirmed:
                # Check if message is likely a response
                if message_processor.is_likely_response(user_message):
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
        print(f"Error handling DM response: {str(e)}")
        slack_client.chat_postMessage(
            channel=channel_id,
            text="Sorry, there was an error processing your response. Please try again or contact your IT team."
        )

@router.post("/slack/events")
async def handle_slack_events(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Handle all Slack events"""
    try:
        # Parse request body with timeout
        event_data = await safe_parse_request(request)
        if not event_data:
            return JSONResponse({"status": "error", "message": "Could not parse request"})

        # Handle URL verification
        if event_data.get('type') == 'url_verification':
            return {"challenge": event_data['challenge']}
            
        # For other events
        if event_data.get('type') == 'event_callback':
            event = event_data['event']
            
            # Ignore bot messages
            if event.get('bot_id') or event.get('subtype') == 'bot_message':
                return {"status": "success", "message": "Ignored bot message"}

            # Handle different event types
            if event['type'] == 'message':
                user_id = event.get('user')
                channel_type = event.get('channel_type')
                
                try:
                    # First handle file uploads from any message type
                    if 'files' in event:
                        # Check if user is a campaign creator
                        campaign = db.query(Campaign)\
                            .filter(
                                Campaign.manager_id == user_id,
                                Campaign.state.in_(['WAITING_FOR_FILE', 'WAITING_FOR_PROMPT'])
                            ).first()
                        
                        if campaign:
                            background_tasks.add_task(process_file_upload, event, db)
                            return JSONResponse({"status": "success", "message": "Processing file upload"})
                    
                    # Then handle DM responses
                    if channel_type == 'im':
                        if 'text' not in event:
                            return JSONResponse({"status": "success", "message": "Ignored message without text"})

                        text = event.get('text', '').lower()

                        # Check if this is a task/sheet message from campaign creator
                        if "task:" in text and "google sheet link:" in text:
                            campaign = db.query(Campaign)\
                                .filter(
                                    Campaign.manager_id == user_id,
                                    Campaign.state == 'WAITING_FOR_PROMPT'
                                ).first()
                            
                            if campaign:
                                background_tasks.add_task(process_task_message, event, db)
                                return JSONResponse({"status": "success", "message": "Processing campaign setup"})
                        
                        # Check if this is a response from campaign participant
                        campaign_user = db.query(CampaignUser)\
                            .join(Campaign)\
                            .filter(
                                CampaignUser.slack_user_id == user_id,
                                Campaign.state == 'ONGOING'
                            ).first()
                        
                        if campaign_user:
                            background_tasks.add_task(handle_dm_response, event, db)
                            return JSONResponse({"status": "success", "message": "Processing user response"})

                    # Log unhandled messages for debugging
                    print(f"Unhandled message event: User: {user_id}, Channel Type: {channel_type}")
                    
                except Exception as e:
                    print(f"Error processing message: {str(e)}")
                    db.rollback()  # Rollback on error
                    
            return JSONResponse({"status": "success", "message": "Event received"})
            
        return JSONResponse({"status": "success", "message": "Event processed"})
        
    except Exception as e:
        print(f"Error in handle_slack_events: {str(e)}")
        return JSONResponse(
            {"status": "error", "message": "Internal server error"},
            status_code=500
        )