from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
import spacy
from typing import Tuple
import torch
from datetime import datetime

class MessageProcessor:
    def __init__(self):
        """Initialize the message processor with transformers and spaCy"""
        # Check if CUDA is available
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        
        # Load base model and tokenizer for message generation
        model_name = "facebook/bart-large-cnn"
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(model_name).to(self.device)
        
        # Initialize the pipeline
        self.text_generator = pipeline(
            "text2text-generation",
            model=self.model,
            tokenizer=self.tokenizer,
            device=0 if self.device == "cuda" else -1
        )
        
        # Load spaCy for additional text processing
        self.nlp = spacy.load('en_core_web_sm')
        
        # Initialize sentiment pipeline
        self.sentiment_analyzer = pipeline(
            "sentiment-analysis",
            model="distilbert-base-uncased-finetuned-sst-2-english",
            device=0 if self.device == "cuda" else -1
        )

        print("MessageProcessor initialized successfully!")
        print(f"Using device: {self.device}")

    def craft_message(self, task: str) -> str:
        """
        Create a polite and professional message from the task description
        using the language model for natural reformulation
        """
        try:
            # Prepare system context
            context = (
                "Transform the following task into a polite and professional email message. "
                "The message should be about license renewal and should ask the user if they "
                "need their software license. Make it concise, friendly, and clear.\n\n"
            )
            
            # Combine context and task
            input_text = context + f"Task: {task}\n\nPolite message:"
            
            # Generate the message
            output = self.text_generator(
                input_text,
                max_length=150,
                min_length=50,
                num_beams=4,
                temperature=0.7,
                no_repeat_ngram_size=2
            )
            
            message = output[0]['generated_text'].strip()
            
            # Ensure the message ends with a question
            if not any(message.endswith(char) for char in ['?', '.']):
                message += '?'
            
            return message

        except Exception as e:
            print(f"Error in craft_message: {str(e)}")
            # Fallback message
            return ("We're reviewing our software licenses. Could you please confirm "
                   "if you're actively using your license?")

    async def analyze_response(self, message: str) -> Tuple[str, float]:
        """
        Analyze user response using the language model to determine their decision
        Returns: (decision, confidence)
        """
        try:
            # Get sentiment first
            sentiment_result = self.sentiment_analyzer(message)[0]
            sentiment_score = sentiment_result['score']
            sentiment_label = sentiment_result['label']
            
            # Process with language model
            analysis_prompt = (
                "Determine if the following response indicates 'yes' (wants to keep license), "
                "'no' (doesn't want license), or 'unclear'. Only respond with: yes, no, or unclear\n\n"
                f"Response: {message}\n\nDecision:"
            )
            
            decision_output = self.text_generator(
                analysis_prompt,
                max_length=10,
                num_beams=1,
                temperature=0.1
            )
            
            raw_decision = decision_output[0]['generated_text'].strip().lower()
            
            # Extract decision
            if 'yes' in raw_decision:
                decision = 'yes'
            elif 'no' in raw_decision:
                decision = 'no'
            else:
                decision = 'unclear'
            
            # Calculate confidence based on multiple factors
            base_confidence = 0.7  # Base confidence in model's decision
            
            # Adjust confidence based on sentiment
            sentiment_alignment = {
                'yes': sentiment_score if sentiment_label == 'POSITIVE' else 1 - sentiment_score,
                'no': sentiment_score if sentiment_label == 'NEGATIVE' else 1 - sentiment_score,
                'unclear': 0.5
            }
            
            # Final confidence is a weighted combination
            confidence = (base_confidence + sentiment_alignment[decision]) / 2
            
            # Additional spaCy analysis for validation
            doc = self.nlp(message.lower())
            
            # Check for strong indicators
            yes_indicators = ['yes', 'yeah', 'keep', 'need', 'want', 'using']
            no_indicators = ['no', 'nope', 'don\'t need', 'remove', 'cancel']
            
            has_yes = any(token.text in yes_indicators for token in doc)
            has_no = any(token.text in no_indicators for token in doc)
            
            # Adjust confidence based on direct indicators
            if (decision == 'yes' and has_yes) or (decision == 'no' and has_no):
                confidence = min(confidence + 0.2, 1.0)
            elif (decision == 'yes' and has_no) or (decision == 'no' and has_yes):
                confidence = max(confidence - 0.2, 0.0)
            
            return decision, confidence

        except Exception as e:
            print(f"Error in analyze_response: {str(e)}")
            return 'unclear', 0.0

    def is_likely_response(self, message: str) -> bool:
        """Determine if a message is likely a response"""
        try:
            doc = self.nlp(message.lower())
            
            # Response indicators
            response_words = {
                'decision': ['yes', 'no', 'yeah', 'nope', 'keep', 'remove', 'need', 
                           'want', 'using', 'cancel', 'stop', 'continue'],
                'license': ['license', 'software', 'tool', 'access'],
                'verbs': ['use', 'need', 'want', 'keep', 'remove', 'cancel']
            }
            
            # Check for indicators
            has_decision_word = any(word in message.lower() 
                                  for word in response_words['decision'])
            has_license_word = any(word in message.lower() 
                                 for word in response_words['license'])
            has_verb = any(token.pos_ == 'VERB' for token in doc)
            
            # More sophisticated checking
            return (has_decision_word or has_license_word) and has_verb

        except Exception as e:
            print(f"Error in is_likely_response: {str(e)}")
            return False

    def get_confirmation_message(self, decision: str, confidence: float) -> str:
        """Generate appropriate confirmation message based on decision and confidence"""
        if confidence < 0.5:
            return ("I'm not completely sure about your preference. Could you please "
                   "clearly indicate if you want to keep the license with a 'yes' or 'no'?")
            
        if decision == 'yes':
            return ("Based on your response, you want to keep your license. "
                   "Is this correct?\n\nPlease confirm with 'yes' or clarify with 'no'.")
        elif decision == 'no':
            return ("Based on your response, you don't need the license anymore. "
                   "Is this correct?\n\nPlease confirm with 'yes' or clarify with 'no'.")
        else:
            return ("Could you please clarify your response? A simple yes (keep) "
                   "or no (don't need) would be perfect.")