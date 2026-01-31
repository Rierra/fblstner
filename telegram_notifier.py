# Telegram Notifier - Send keyword match alerts to Telegram group

import requests
import time
from typing import Dict, List, Optional
import html
from url_cleaner import clean_facebook_url, clean_html_entities

class TelegramNotifier:
    """Sends formatted alerts to a Telegram group."""
    
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self.last_send_time = 0
        self.min_interval = 1.0  # Min seconds between messages (rate limiting)
    
    def _rate_limit(self):
        """Ensure we don't exceed Telegram rate limits."""
        elapsed = time.time() - self.last_send_time
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_send_time = time.time()
    
    def send_message(self, text: str, parse_mode: str = "HTML", disable_preview: bool = True) -> bool:
        """Send a message to the configured chat."""
        self._rate_limit()
        
        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_preview
        }
        
        try:
            response = requests.post(url, json=payload, timeout=30)
            response.raise_for_status()
            result = response.json()
            
            if result.get("ok"):
                print(f"[TELEGRAM] Message sent successfully")
                return True
            else:
                print(f"[TELEGRAM] API Error: {result.get('description', 'Unknown error')}")
                return False
                
        except requests.exceptions.RequestException as e:
            print(f"[TELEGRAM] Request failed: {e}")
            return False
    
    def send_keyword_alert(self, post: Dict, matched_keywords: List[str]) -> bool:
        """
        Send a formatted alert for a Facebook post with matched keywords.
        
        Expected post dict keys:
        - text: str (the post content)
        - post_url: str (link to the post, may be None)
        - timestamp: str (when the post was made, may be None)
        """
        # Escape HTML entities - handle None values
        raw_text = post.get("text") or "No text available"
        text = html.escape(clean_html_entities(str(raw_text))[:800])
        keywords_str = ", ".join(matched_keywords)
        
        # Build the message (no author, no emojis)
        message_lines = [
            f"<b>KEYWORD ALERT</b>",
            f"",
            f"<b>Keyword:</b> <code>{keywords_str}</code>",
            f"",
            f"<b>Post:</b>",
            f"<i>{text}</i>",
        ]
        
        # Add post URL if available
        post_url = clean_facebook_url(post.get("post_url")) if post.get("post_url") else None
        if post_url:
            message_lines.append(f"")
            message_lines.append(f"<a href=\"{post_url}\">View Post</a>")
        
        # Add timestamp if available
        timestamp = post.get("timestamp")
        if timestamp:
            message_lines.append(f"Time: {html.escape(str(timestamp))}")
        
        message = "\n".join(message_lines)
        return self.send_message(message)
    
    def send_startup_notification(self, pages_count: int, keywords_count: int):
        """Send a notification when the monitor starts."""
        message = (
            f"🚀 <b>Facebook Monitor Started</b>\n\n"
            f"📊 Monitoring <b>{pages_count}</b> page(s)\n"
            f"🔑 Watching <b>{keywords_count}</b> keyword(s)\n\n"
            f"Alerts will be sent when keywords are detected."
        )
        return self.send_message(message)
    
    def send_error_notification(self, error_message: str):
        """Send an error notification."""
        message = f"⚠️ <b>Facebook Monitor Error</b>\n\n<code>{html.escape(error_message)}</code>"
        return self.send_message(message)
    
    def test_connection(self) -> bool:
        """Test if the bot can send messages to the chat."""
        return self.send_message("🧪 Facebook Monitor - Connection Test Successful!")


if __name__ == "__main__":
    # Test the notifier
    from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
    
    notifier = TelegramNotifier(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    
    # Test connection
    print("Testing Telegram connection...")
    if notifier.test_connection():
        print("✓ Connection successful!")
        
        # Test keyword alert
        test_post = {
            "text": "This is a test post mentioning Bitcoin and cryptocurrency trends for 2024.",
            "page_name": "Test Page",
            "post_url": "https://www.facebook.com/testpage/posts/123",
            "timestamp": "2 hours ago"
        }
        
        if notifier.send_keyword_alert(test_post, ["bitcoin", "cryptocurrency"]):
            print("✓ Test alert sent!")
        else:
            print("✗ Failed to send test alert")
    else:
        print("✗ Connection failed. Check your bot token and chat ID.")
