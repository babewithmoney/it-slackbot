import os
import requests
from typing import Tuple
import json

class MessageProcessor:
    def __init__(self, openai_key: str):
        self.openai_key = openai_key
    
    async def analyze_response(self, message: str) -> Tuple[str, float]:
        """
        Analyze user response using ChatGPT
        Returns: (decision, confidence)
        """
        try:
            # Clean and normalize the message
            cleaned_message = message.strip().lower()
            
            # Quick check for common direct responses
            direct_responses = {
                'yes': ['yes', 'yeah', 'yep', 'sure', 'okay', 'ok', 'need it', 'want it', 'keep it'],
                'no': ['no', 'nope', 'don\'t need', 'dont need', 'remove', 'delete', 'remove it', 'delete it']
            }
            
            # Check for direct matches first
            for decision, phrases in direct_responses.items():
                if any(phrase in cleaned_message for phrase in phrases):
                    return decision, 1.0

            # If no direct match, use ChatGPT for analysis
            headers = {
                "Authorization": f"Bearer {self.openai_key}",
                "Content-Type": "application/json"
            }
            
            data = {
                "model": "gpt-3.5-turbo",
                "messages": [
                    {
                        "role": "system",
                        "content": ("You are analyzing user responses to a license renewal request. "
                                  "Categorize the response as 'yes' if they want to keep the license, "
                                  "'no' if they don't need it, or 'unclear' if the response is ambiguous. "
                                  "Respond with only: yes, no, or unclear")
                    },
                    {
                        "role": "user",
                        "content": f"Analyze this response to a license renewal request: {message}"
                    }
                ],
                "temperature": 0.3,
                "max_tokens": 10,  # We only need a short response
                "timeout": 10  # 10 seconds timeout
            }
            
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=data,
                timeout=10
            )
            
            response.raise_for_status()  # Raise exception for HTTP errors
            
            result = response.json()
            if "choices" in result and len(result["choices"]) > 0:
                decision = result["choices"][0]["message"]["content"].lower().strip()
                if decision in ["yes", "no", "unclear"]:
                    # Higher confidence for clear yes/no responses
                    confidence = 1.0 if decision != "unclear" else 0.5
                    
                    # Log the analysis result
                    print(f"Message analyzed - Original: '{message}', Decision: {decision}, Confidence: {confidence}")
                    
                    return decision, confidence
            
            # If we get here, something went wrong with the response format
            print(f"Unexpected ChatGPT response format: {json.dumps(result)}")
            return "unclear", 0.0
            
        except requests.exceptions.Timeout:
            print(f"Timeout while analyzing message: '{message}'")
            return "unclear", 0.0
            
        except requests.exceptions.RequestException as e:
            print(f"API Request Error: {str(e)}")
            return "unclear", 0.0
            
        except json.JSONDecodeError:
            print(f"Error decoding API response for message: '{message}'")
            return "unclear", 0.0
            
        except Exception as e:
            print(f"Unexpected error analyzing response: {str(e)}")
            return "unclear", 0.0
    
    def is_likely_response(self, message: str) -> bool:
        """
        Check if a message is likely to be a response to the license inquiry
        """
        # Keywords that indicate this is probably a response
        response_indicators = [
            'license', 'figma', 'yes', 'no', 'keep', 'remove', 'need', 
            'don\'t need', 'dont need', 'sure', 'okay', 'ok', 'thanks'
        ]
        
        cleaned_message = message.lower().strip()
        return any(indicator in cleaned_message for indicator in response_indicators)
    
    async def get_clarification_prompt(self, message: str) -> str:
        """
        Generate a contextual clarification prompt based on the unclear response
        """
        try:
            headers = {
                "Authorization": f"Bearer {self.openai_key}",
                "Content-Type": "application/json"
            }
            
            data = {
                "model": "gpt-3.5-turbo",
                "messages": [
                    {
                        "role": "system",
                        "content": ("Generate a polite clarification question for an unclear license renewal response. "
                                  "The question should ask if they want to keep or release their license. "
                                  "Keep it short and friendly.")
                    },
                    {
                        "role": "user",
                        "content": f"Create a clarification question for this response: {message}"
                    }
                ],
                "temperature": 0.7,
                "max_tokens": 100
            }
            
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=data,
                timeout=10
            )
            
            if response.status_code == 200:
                result = response.json()
                return result["choices"][0]["message"]["content"].strip()
            
            return "Could you please clarify if you want to keep or release your Figma license?"
            
        except Exception as e:
            print(f"Error generating clarification prompt: {str(e)}")
            return "Could you please clarify if you want to keep or release your Figma license?"