from slack_sdk import WebClient
from typing import Tuple

class UserVerification:
    def __init__(self, slack_token: str):
        self.client = WebClient(token=slack_token)
    
    async def is_it_member(self, user_id: str) -> Tuple[bool, str]:
        """
        Check if user is an IT member based on their profile
        Returns: (is_it_member, error_message)
        """
        try:
            # Get user info from Slack
            result = self.client.users_info(user=user_id)
            
            if result["ok"]:
                user = result["user"]
                # Check title or role in profile
                profile = user.get("profile", {})
                title = profile.get("title", "").lower()
                
                # List of keywords that indicate IT role
                it_keywords = ["it", "information technology", "systems", "tech", "technical"]
                
                # Check if any IT keyword is in the title
                is_it = any(keyword in title for keyword in it_keywords)
                
                if is_it:
                    return True, ""
                else:
                    return False, "Only IT team members can create campaigns."
            
            return False, "Could not verify user role."
            
        except Exception as e:
            return False, f"Error verifying user role: {str(e)}"