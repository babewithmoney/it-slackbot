from sqlalchemy import Column, Integer, String, Enum, Text, ForeignKey, TIMESTAMP, func, Boolean, Float
from sqlalchemy.orm import relationship
from app.db import Base

class Campaign(Base):
    __tablename__ = "campaign"

    id = Column(Integer, primary_key=True, index=True)
    manager_id = Column(String, index=True)  # Slack user_id for IT manager
    google_sheet_link = Column(String(255), nullable=True)
    state = Column(Enum("WAITING_FOR_FILE", "WAITING_FOR_PROMPT", "ONGOING", "COMPLETED", name="state_enum"))
    prompt = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
    crafted_msg = Column(Text, nullable=True)
    notifications_started = Column(Boolean, default=False)  # Track if notifications have been sent
    notification_start_time = Column(TIMESTAMP, nullable=True)  # When notifications started
    
    # Relationship to track individual users within a campaign
    users = relationship("CampaignUser", back_populates="campaign")


class CampaignUser(Base):
    __tablename__ = "campaign_users"

    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(Integer, ForeignKey("campaign.id"))
    user_email = Column(String, nullable=False)
    slack_user_id = Column(String, nullable=True)
    response = Column(String, nullable=True)  # Tracks yes/no/unclear response
    response_confidence = Column(Float, nullable=True)  # ChatGPT confidence in response analysis
    raw_response = Column(Text, nullable=True)  # Store the actual user response
    num_pings = Column(Integer, default=0)
    last_ping = Column(TIMESTAMP, nullable=True)
    response_time = Column(TIMESTAMP, nullable=True)  # When user responded
    response_confirmed = Column(Boolean, default=False)  # If user confirmed their response
    dm_channel_id = Column(String, nullable=True)  # Store DM channel ID to avoid reopening

    # Relationship to link to campaign
    campaign = relationship("Campaign", back_populates="users")