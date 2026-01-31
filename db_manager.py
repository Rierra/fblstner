# Database/Storage Manager for tracking seen posts

import json
import os
from datetime import datetime, timedelta
from typing import Set, Optional

class SeenPostsDB:
    """Tracks seen post IDs to prevent duplicate Telegram notifications."""
    
    def __init__(self, filepath: str, expiry_days: int = 7):
        self.filepath = filepath
        self.expiry_days = expiry_days
        self.data = self._load()
    
    def _load(self) -> dict:
        """Load seen posts from JSON file."""
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"[WARNING] Could not load {self.filepath}: {e}")
                return {"posts": {}}
        return {"posts": {}}
    
    def _save(self):
        """Save seen posts to JSON file."""
        try:
            with open(self.filepath, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2)
        except IOError as e:
            print(f"[ERROR] Could not save {self.filepath}: {e}")
    
    def is_seen(self, post_id: str) -> bool:
        """Check if a post ID has already been seen."""
        return post_id in self.data["posts"]
    
    def mark_seen(self, post_id: str):
        """Mark a post ID as seen with current timestamp."""
        self.data["posts"][post_id] = datetime.now().isoformat()
        self._save()
    
    def mark_multiple_seen(self, post_ids: list):
        """Mark multiple post IDs as seen (batch operation)."""
        timestamp = datetime.now().isoformat()
        for post_id in post_ids:
            self.data["posts"][post_id] = timestamp
        self._save()
    
    def cleanup_expired(self):
        """Remove entries older than expiry_days."""
        if not self.data["posts"]:
            return
        
        cutoff = datetime.now() - timedelta(days=self.expiry_days)
        expired = []
        
        for post_id, timestamp_str in self.data["posts"].items():
            try:
                timestamp = datetime.fromisoformat(timestamp_str)
                if timestamp < cutoff:
                    expired.append(post_id)
            except ValueError:
                expired.append(post_id)  # Remove invalid entries
        
        for post_id in expired:
            del self.data["posts"][post_id]
        
        if expired:
            print(f"[INFO] Cleaned up {len(expired)} expired entries")
            self._save()
    
    def get_seen_count(self) -> int:
        """Return the number of seen posts."""
        return len(self.data["posts"])


if __name__ == "__main__":
    # Quick test
    db = SeenPostsDB("test_seen_posts.json", expiry_days=1)
    
    test_id = "test_post_123"
    print(f"Is '{test_id}' seen? {db.is_seen(test_id)}")
    
    db.mark_seen(test_id)
    print(f"Is '{test_id}' seen after marking? {db.is_seen(test_id)}")
    
    print(f"Total seen posts: {db.get_seen_count()}")
    
    # Cleanup test file
    if os.path.exists("test_seen_posts.json"):
        os.remove("test_seen_posts.json")
    print("Test passed!")
