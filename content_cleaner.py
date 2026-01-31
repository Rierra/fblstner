# Content Cleaner using Groq LLM
# Uses Llama 3 to clean messy Facebook scraped text and extract structured data

import os
import json
import logging
from typing import Dict, Optional, List
from groq import Groq
from config import GROQ_API_KEY, GROQ_MODEL

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ContentCleaner:
    def __init__(self):
        """Initialize Groq client."""
        if not GROQ_API_KEY:
            logger.warning("GROQ_API_KEY not found! Content cleaning will be disabled.")
            self.client = None
        else:
            try:
                self.client = Groq(api_key=GROQ_API_KEY)
                logger.info(f"Groq client initialized with model: {GROQ_MODEL}")
            except Exception as e:
                logger.error(f"Failed to initialize Groq client: {e}")
                self.client = None

    def clean_post(self, raw_text: str, keyword: str) -> Dict:
        """
        Use LLM to clean text and extract structured data.
        Returns a dict with:
        - author: str
        - clean_text: str
        - sentiment: str (Positive/Negative/Neutral)
        - is_relevant: bool (Does it actually mention the keyword contextually?)
        """
        if not self.client:
            # Return None for author so the monitor can use the original scraper author
            return {"clean_text": raw_text, "author": None, "is_relevant": True}

        prompt = f"""
You are an expert data cleaner. I have a raw scraped Facebook posts containing noise, UI elements, and scrambled text.
Your task is to extract the core meaningful content and metadata.

KEYWORD TO LOOK FOR: "{keyword}"

RAW TEXT:
\"\"\"{raw_text[:2000]}\"\"\"

INSTRUCTIONS:
1. Extract the AUTHOR name (usually at the start, like "CNN ·" or "FOX News ·"). If unclear, use "Unknown".
2. Extract the CLEAN POST TEXT. Remove "Like Comment Share", timestamps like "1d ·", UI noise like "Public", and any scrambled text.
3. Determine SENTIMENT (Positive, Negative, Neutral).
4. Check RELEVANCE: Does this post actually discuss the keyword "{keyword}"? (True/False). 
   - False if it's just a random word match in a spam post or navigation menu.

OUTPUT FORMAT:
Return ONLY a valid JSON object with these keys: "author", "clean_text", "sentiment", "is_relevant".
Do not include any explanation or markdown formatting like ```json.
"""

        try:
            completion = self.client.chat.completions.create(
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                model=GROQ_MODEL,
                temperature=0.1, # Low temperature for consistent formatting
                max_tokens=1024,
            )

            response_text = completion.choices[0].message.content.strip()
            
            # Clean up potential markdown code blocks if the model ignores instructions
            if response_text.startswith("```"):
                response_text = response_text.replace("```json", "").replace("```", "").strip()

            data = json.loads(response_text)
            return data

        except Exception as e:
            logger.error(f"Groq processing failed: {e}")
            # Fallback to returning raw text
            # Return None for author so the monitor can use the original scraper author
            return {
                "clean_text": raw_text, 
                "author": None,  # None instead of "Unknown" so monitor can use original author
                "is_relevant": True,
                "error": str(e)
            }

if __name__ == "__main__":
    # Test script
    cleaner = ContentCleaner()
    
    test_text = """
    Facebook . Fox News · President Donald Trump warned Iran is "starting to" cross red lines as protests spread to 190 cities nationwide. The president threatened "strong options" amid civilian deaths. foxnews.com Trump says Iran 'starting to' cross US red lines as protesters die in government crackdown .4K 1.4K e Fox News · BREAKING: The U.S. Attorney’s Office for
    """
    
    print("Testing with sample text...")
    result = cleaner.clean_post(test_text, "trump")
    print(json.dumps(result, indent=2))
