# app/nlp.py
import os
import openai
from dotenv import load_dotenv

load_dotenv()

openai.api_key = os.getenv("OPENAI_API_KEY")

def interpret_response(message: str) -> str:
    """Simple NLP to interpret yes/no response using OpenAI API."""
    prompt = f"Classify this response as 'yes', 'no', or 'unclear': {message}"
    response = openai.Completion.create(
        model="text-davinci-003",
        prompt=prompt,
        max_tokens=5
    )
    return response.choices[0].text.strip().lower()
