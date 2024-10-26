from transformers import AutoTokenizer, AutoModelForCausalLM, pipeline
import spacy
from typing import Tuple
import torch
from datetime import datetime
import re

class MessageProcessor:
    def __init__(self):
        """Initialize the message processor"""
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Initializing MessageProcessor on {self.device}")
        
        # Use Zephyr model for better instruction following
        model_name = "HuggingFaceH4/zephyr-7b-beta"
        
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(model_name)
            self.model = AutoModelForCausalLM.from_pretrained(
                model_name,
                torch_dtype=torch.float16,
                device_map="auto"
            )
            
            self.text_generator = pipeline(
                "text-generation",
                model=self.model,
                tokenizer=self.tokenizer,
                device_map="auto"
            )
            
            self.nlp = spacy.load('en_core_web_sm')
            print("MessageProcessor initialized successfully!")
            
        except Exception as e:
            print(f"Error initializing MessageProcessor: {str(e)}")
            raise

    def craft_message(self, task: str) -> Tuple[str, str]:
        """Create a natural and professional message based on admin's task"""
        try:
            # Extract software name from task
            doc = self.nlp(task)
            software_name = "the software"
            for ent in doc.ents:
                if ent.label_ in ['PRODUCT', 'ORG']:
                    software_name = ent.text
                    break
            
            # Search for duration in task
            duration_match = re.search(r'(\d+)\s*(month|months|day|days|week|weeks)', task)
            duration = f"in {duration_match.group(0)}" if duration_match else "recently"

            # Create more specific prompt
            prompt = f"""<|system|>You are crafting direct messages to users about software licenses. Create a brief, friendly message without any meta-text or formatting.

    <|user|>Task from admin: {task}

    Write a message to users about {software_name} license usage. Requirements:
    - Start with "Hi!"
    - Mention {software_name} specifically
    - Reference that it hasn't been used {duration}
    - Ask if they still need access
    - Maximum 2 sentences
    - Don't include any greetings like "Dear user" or signatures
    - Don't include phrases like "here's the message" or "absolutely"
    - Don't mention company name or cost savings

    Just write the exact message to be sent.

    <|assistant|>"""

            output = self.text_generator(
                prompt,
                max_new_tokens=75,
                temperature=0.7,
                top_p=0.9,
                do_sample=True,
                num_return_sequences=1,
                pad_token_id=self.tokenizer.eos_token_id,
                repetition_penalty=1.2
            )
            
            # Extract message and clean thoroughly
            message = output[0]['generated_text']
            message = message.split("<|assistant|>")[-1].strip()
            
            # Remove common unwanted patterns
            unwanted_patterns = [
                r'Here\'s the message:',
                r'Here it is:',
                r'Absolutely!',
                r'Dear \[*\w*\]*,*',
                r'Best regards,*',
                r'Sincerely,*',
                r'Thanks,*',
                r'Message:',
                r'<\|.*?\|>',
                r'\[.*?\]',
                r'^\s*[-_]\s*'
            ]
            
            for pattern in unwanted_patterns:
                message = re.sub(pattern, '', message, flags=re.IGNORECASE)
            
            # Clean up whitespace and formatting
            message = re.sub(r'\s+', ' ', message)
            message = message.strip()
            
            # Ensure it starts with Hi!
            if not message.lower().startswith('hi'):
                message = f"Hi! {message}"
            
            # Final validation
            if (len(message.split()) < 5 or 
                len(message) < 20 or 
                software_name.lower() not in message.lower()):
                return (
                    f"Hi! We noticed you haven't used {software_name} {duration}. Could you please let us know if you still need access?",
                    "Generated message needed fallback"
                )
                
            return message, ""

        except Exception as e:
            error_msg = f"Error in craft_message: {str(e)}"
            print(error_msg)
            return (
                f"Hi! We noticed you haven't used {software_name} {duration}. Could you please let us know if you still need access?",
                error_msg
            )

    async def analyze_response(self, message: str) -> Tuple[str, float]:
        """Analyze user response using NLP"""
        try:
            # First check for direct negative responses
            negative_patterns = [
                r"don\'?t\s+need",
                r"don\'?t\s+want",
                r"no\s+longer\s+need",
                r"not\s+(?:needed|using|required)",
                r"^no\b",
                r"\bno\s+thanks?\b",
                r"remove\s+(?:it|access|license)",
                r"cancel\s+(?:it|access|license)"
            ]
            
            # Check for direct positive responses
            positive_patterns = [
                r"\byes\b",
                r"\byeah\b",
                r"\byep\b",
                r"(?:still|do)\s+need",
                r"want\s+to\s+keep",
                r"keeping\s+it",
                r"using\s+it"
            ]
            
            message_lower = message.lower()
            
            # Check for explicit negatives first
            if any(re.search(pattern, message_lower) for pattern in negative_patterns):
                return 'no', 0.9
                
            # Then check for explicit positives
            if any(re.search(pattern, message_lower) for pattern in positive_patterns):
                return 'yes', 0.9
                
            # If no clear patterns, use the model for analysis
            prompt = f"""<s>[INST] Determine if this response indicates the user wants to keep their license.
            User message: "{message}"
            Consider:
            - "don't need" means they DON'T want to keep it
            - "no longer need" means they DON'T want to keep it
            - Only respond with exactly one word: yes, no, or unclear
            [/INST]</s>"""
            
            output = self.text_generator(
                prompt,
                max_new_tokens=10,
                temperature=0.1,
                do_sample=True,
                top_p=0.9
            )
            
            response = output[0]['generated_text'].lower()
            response = response.split('[/INST]')[-1].strip()
            response = response.split('</s>')[0].strip()
            
            # Additional validation with spaCy
            doc = self.nlp(message_lower)
            
            # Check for negation patterns
            has_negation = any(token.dep_ == 'neg' for token in doc)
            
            # Base decision on model output
            if 'yes' in response and not has_negation:
                decision = 'yes'
                confidence = 0.9
            elif 'no' in response or has_negation:
                decision = 'no'
                confidence = 0.9
            else:
                decision = 'unclear'
                confidence = 0.5
            
            # Additional context check
            need_words = ['need', 'want', 'use', 'using', 'require']
            has_need_word = any(word in message_lower for word in need_words)
            
            if has_need_word and has_negation:
                decision = 'no'
                confidence = 1.0
            
            return decision, confidence

        except Exception as e:
            print(f"Error in analyze_response: {str(e)}")
            return 'unclear', 0.0

    def is_likely_response(self, message: str) -> bool:
        """Check if message is likely a response"""
        try:
            keywords = ['yes', 'no', 'keep', 'need', 'license', 'using', 'remove']
            return any(word in message.lower() for word in keywords)
        except Exception as e:
            print(f"Error in is_likely_response: {str(e)}")
            return False

    def get_confirmation_message(self, decision: str, confidence: float = 0.0) -> str:
        """Get confirmation message"""
        try:
            if confidence < 0.5:
                return "Could you please clarify with a simple yes or no if you need the license?"
                
            if decision.lower() == 'yes':
                return "You want to keep the license, correct? Please confirm with yes or no."
            elif decision.lower() == 'no':
                return "You don't need the license anymore, correct? Please confirm with yes or no."
            else:
                return "Could you please clarify with a simple yes or no?"
        except Exception as e:
            print(f"Error in get_confirmation_message: {str(e)}")
            return "Could you please clarify with a simple yes or no?"