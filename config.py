# Facebook Keyword Monitor - Configuration
# Multi-Group Version with Telegram Bot Control

import os

# =====================================================
# FACEBOOK COOKIES
# =====================================================
# Path to cookies JSON file
# On Render, use disk storage path
COOKIES_FILE = os.environ.get("COOKIES_FILE", "fb_cookies.json")

# =====================================================
# TELEGRAM CONFIGURATION  
# =====================================================
# Bot token for Telegram
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8543209301:AAFu97Z0iQRXiSwp12P-Erkh-VWsx7KPZZM")

# Owner's control group - only this group can execute commands
# Client groups are managed via /addgroup command
TELEGRAM_OWNER_CHAT_ID = os.environ.get("TELEGRAM_OWNER_CHAT_ID", "-5236246086")

# Legacy support (deprecated, use TELEGRAM_OWNER_CHAT_ID)
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", TELEGRAM_OWNER_CHAT_ID)

# =====================================================
# TIMING & BEHAVIOR SETTINGS
# =====================================================
# How often to run a full check cycle (in seconds)
CHECK_INTERVAL = int(os.environ.get("CHECK_INTERVAL", "120"))  # 2 minutes

# Max posts to extract per keyword search
MAX_POSTS_PER_PAGE = 15

# Random delay range between actions (anti-detection)
MIN_ACTION_DELAY = 1.5
MAX_ACTION_DELAY = 4.0

# =====================================================
# STORAGE (Render Disk)
# =====================================================
# On Render, mount a disk at /data
DATA_DIR = os.environ.get("DATA_DIR", ".")
SEEN_POSTS_FILE = os.path.join(DATA_DIR, "seen_posts.json")
BOT_DATA_FILE = os.path.join(DATA_DIR, "bot_data.json")

# How many days to keep seen post IDs
SEEN_POSTS_EXPIRY_DAYS = 4
