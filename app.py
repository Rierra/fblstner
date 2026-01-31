#!/usr/bin/env python3
"""
Facebook to Telegram Monitor Bot - Multi-Group Version
Monitors Facebook Search for keywords and sends alerts to client groups
Owner controls all groups from main control group via interactive menu
"""

import os
import json
import time
import logging
import asyncio
import threading
from typing import Set, Dict, Optional
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, 
    CommandHandler, 
    ContextTypes, 
    CallbackQueryHandler,
    MessageHandler,
    filters
)
from dotenv import load_dotenv

# Import existing modules
from fb_scraper import FacebookSearchScraper
from db_manager import SeenPostsDB
from url_cleaner import clean_facebook_url, clean_html_entities

# Import configuration
from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_OWNER_CHAT_ID,
    CHECK_INTERVAL,
    COOKIES_FILE,
    DATA_DIR,
    SEEN_POSTS_FILE
)

# Load environment variables (for any overrides)
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


class FacebookTelegramBot:
    def __init__(self):
        # Load configuration from config.py (which reads from env with fallbacks)
        self.telegram_token = TELEGRAM_BOT_TOKEN
        self.owner_chat_id = int(TELEGRAM_OWNER_CHAT_ID)
        
        # Timing settings
        self.check_interval = CHECK_INTERVAL
        self.cookies_file = COOKIES_FILE
        
        # Multi-group data storage
        # group_id -> {name: str, keywords: set, enabled: bool}
        self.groups: Dict[int, Dict] = {}
        self.processed_items: Dict[int, Set[str]] = {}  # group_id -> set of processed post IDs
        
        # Track which keywords have been initialized (sent initial batch)
        # Format: "group_id:keyword" -> True
        self.initialized_keywords: Set[str] = set()
        
        # Number of posts to send on first keyword addition
        self.initial_backfill_count = 10
        
        # Menu state tracking for interactive flows
        self.pending_keyword_add: Dict[int, int] = {}  # user_id -> group_id
        self.pending_keyword_remove: Dict[int, int] = {}  # user_id -> group_id
        self.menu_state: Dict[int, str] = {}  # user_id -> current state
        
        # Data directory
        self.data_dir = DATA_DIR
        os.makedirs(self.data_dir, exist_ok=True)
        self.data_file = os.path.join(self.data_dir, 'bot_data.json')
        self.seen_posts_file = SEEN_POSTS_FILE
        
        # Facebook scraper (initialized in monitoring thread)
        self.scraper: Optional[FacebookSearchScraper] = None
        self.seen_db: Optional[SeenPostsDB] = None
        
        # Control flags
        self.running = False
        self.monitor_thread: Optional[threading.Thread] = None
        
        # Load existing data
        self.load_data()
    
    def load_data(self):
        """Load groups and processed items from file"""
        try:
            if os.path.exists(self.data_file):
                with open(self.data_file, 'r') as f:
                    data = json.load(f)
                
                # Load groups with keywords as sets
                groups_data = data.get('groups', {})
                self.groups = {}
                for group_id_str, group_info in groups_data.items():
                    group_id = int(group_id_str)
                    self.groups[group_id] = {
                        'name': group_info.get('name', f'Group {group_id}'),
                        'keywords': set(group_info.get('keywords', [])),
                        'enabled': group_info.get('enabled', True)
                    }
                
                # Load processed items per group
                processed_data = data.get('processed_items', {})
                self.processed_items = {}
                for group_id_str, items in processed_data.items():
                    self.processed_items[int(group_id_str)] = set(items)
                
                # Load initialized keywords
                self.initialized_keywords = set(data.get('initialized_keywords', []))
                
                total_keywords = sum(len(g['keywords']) for g in self.groups.values())
                logger.info(f"Loaded {len(self.groups)} groups with {total_keywords} total keywords")
            else:
                logger.info("No existing data found, starting fresh")
                self.groups = {}
                self.processed_items = {}
                
        except Exception as e:
            logger.error(f"Error loading data: {e}")
            self.groups = {}
            self.processed_items = {}
    
    def save_data(self):
        """Save groups and processed items to file"""
        try:
            # Trim processed items if too large
            for group_id in list(self.processed_items.keys()):
                if len(self.processed_items[group_id]) > 5000:
                    self.processed_items[group_id] = set(list(self.processed_items[group_id])[-2500:])
            
            # Convert to JSON-serializable format
            groups_data = {}
            for group_id, group_info in self.groups.items():
                groups_data[str(group_id)] = {
                    'name': group_info['name'],
                    'keywords': list(group_info['keywords']),
                    'enabled': group_info['enabled']
                }
            
            processed_data = {}
            for group_id, items in self.processed_items.items():
                processed_data[str(group_id)] = list(items)
            
            data = {
                'groups': groups_data,
                'processed_items': processed_data,
                'initialized_keywords': list(self.initialized_keywords)
            }
            
            with open(self.data_file, 'w') as f:
                json.dump(data, f, indent=2)
            
            logger.debug("Data saved successfully")
            
        except Exception as e:
            logger.error(f"Error saving data: {e}")
    
    def is_owner(self, chat_id: int) -> bool:
        """Check if the chat is the owner's control group"""
        return chat_id == self.owner_chat_id
    
    # =========================================================================
    # COMMAND HANDLERS
    # =========================================================================
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show help message"""
        chat_id = update.effective_chat.id
        
        if not self.is_owner(chat_id):
            await update.message.reply_text("Commands are only available in the control group.")
            return
        
        help_text = """
<b>Facebook Monitor Bot - Commands</b>

<b>Group Management:</b>
/group - Interactive menu to manage groups
/addgroup &lt;group_id&gt; &lt;name&gt; - Add a new client group
/removegroup &lt;group_id&gt; - Remove a group
/listgroups - List all monitored groups

<b>Quick Commands:</b>
/addkeyword &lt;group_id&gt; &lt;keyword&gt; - Add keyword directly
/removekeyword &lt;group_id&gt; &lt;keyword&gt; - Remove keyword directly
/listkeywords &lt;group_id&gt; - List keywords for a group

<b>Status:</b>
/status - Show bot status
/help - Show this help

<b>Note:</b> Use the /group menu for easier management!
"""
        await update.message.reply_text(help_text, parse_mode='HTML')
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show bot status"""
        chat_id = update.effective_chat.id
        
        if not self.is_owner(chat_id):
            await update.message.reply_text("Commands are only available in the control group.")
            return
        
        total_keywords = sum(len(g['keywords']) for g in self.groups.values())
        enabled_groups = sum(1 for g in self.groups.values() if g['enabled'])
        
        status_text = f"""
<b>Facebook Monitor Status</b>

<b>Groups:</b> {len(self.groups)} ({enabled_groups} enabled)
<b>Total Keywords:</b> {total_keywords}
<b>Monitor Running:</b> {'Yes ✓' if self.running else 'No ✗'}
<b>Check Interval:</b> {self.check_interval}s
"""
        await update.message.reply_text(status_text, parse_mode='HTML')
    
    async def addgroup_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Add a new group to monitor"""
        chat_id = update.effective_chat.id
        
        if not self.is_owner(chat_id):
            await update.message.reply_text("Commands are only available in the control group.")
            return
        
        if len(context.args) < 2:
            await update.message.reply_text(
                "Usage: /addgroup <group_id> <name>\n\n"
                "Example: /addgroup -1001234567890 Client Company A\n\n"
                "To get a group ID, add @userinfobot to the group."
            )
            return
        
        try:
            group_id = int(context.args[0])
            group_name = ' '.join(context.args[1:])
            
            if group_id in self.groups:
                await update.message.reply_text(f"Group {group_id} already exists!")
                return
            
            self.groups[group_id] = {
                'name': group_name,
                'keywords': set(),
                'enabled': True
            }
            self.processed_items[group_id] = set()
            self.save_data()
            
            await update.message.reply_text(
                f"✅ Added group: <b>{group_name}</b>\n"
                f"ID: <code>{group_id}</code>\n\n"
                f"Use /group to add keywords.",
                parse_mode='HTML'
            )
            
        except ValueError:
            await update.message.reply_text("Invalid group ID. Must be a number.")
    
    async def removegroup_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Remove a group from monitoring"""
        chat_id = update.effective_chat.id
        
        if not self.is_owner(chat_id):
            await update.message.reply_text("Commands are only available in the control group.")
            return
        
        if not context.args:
            await update.message.reply_text("Usage: /removegroup <group_id>")
            return
        
        try:
            group_id = int(context.args[0])
            
            if group_id not in self.groups:
                await update.message.reply_text("Group not found.")
                return
            
            if group_id == self.owner_chat_id:
                await update.message.reply_text("Cannot remove the control group!")
                return
            
            group_name = self.groups[group_id]['name']
            del self.groups[group_id]
            if group_id in self.processed_items:
                del self.processed_items[group_id]
            self.save_data()
            
            await update.message.reply_text(f"✅ Removed group: {group_name}")
            
        except ValueError:
            await update.message.reply_text("Invalid group ID.")
    
    async def listgroups_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """List all monitored groups"""
        chat_id = update.effective_chat.id
        
        if not self.is_owner(chat_id):
            await update.message.reply_text("Commands are only available in the control group.")
            return
        
        if not self.groups:
            await update.message.reply_text("No groups configured. Use /addgroup to add one.")
            return
        
        msg = "<b>Monitored Groups:</b>\n\n"
        for group_id, info in self.groups.items():
            status = "✓" if info['enabled'] else "✗"
            kw_count = len(info['keywords'])
            msg += f"{status} <b>{info['name']}</b>\n"
            msg += f"   ID: <code>{group_id}</code>\n"
            msg += f"   Keywords: {kw_count}\n\n"
        
        await update.message.reply_text(msg, parse_mode='HTML')
    
    # =========================================================================
    # INTERACTIVE MENU SYSTEM
    # =========================================================================
    
    async def group_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show interactive group selection menu"""
        chat_id = update.effective_chat.id
        
        if not self.is_owner(chat_id):
            await update.message.reply_text("Commands are only available in the control group.")
            return
        
        if not self.groups:
            await update.message.reply_text(
                "No groups configured yet.\n\n"
                "Use /addgroup <group_id> <name> to add a group."
            )
            return
        
        # Create inline keyboard with all groups
        keyboard = []
        for group_id, group_info in self.groups.items():
            keyword_count = len(group_info['keywords'])
            status_icon = "✓" if group_info['enabled'] else "✗"
            button_text = f"{status_icon} {group_info['name']} ({keyword_count} kw)"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"manage_group:{group_id}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Select a group to manage:", reply_markup=reply_markup)
    
    async def group_callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle all menu interactions"""
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        data = query.data
        
        # =====================================================================
        # GROUP MANAGEMENT MENU
        # =====================================================================
        if data.startswith("manage_group:"):
            try:
                group_id = int(data.split(":")[1])
                
                if group_id not in self.groups:
                    await query.edit_message_text("Group not found.")
                    return
                
                group_info = self.groups[group_id]
                keyword_count = len(group_info['keywords'])
                status = "Enabled" if group_info['enabled'] else "Disabled"
                
                # Build management menu
                keyboard = [
                    [InlineKeyboardButton("➕ Add Keywords", callback_data=f"add_kw:{group_id}")],
                    [InlineKeyboardButton("➖ Remove Keywords", callback_data=f"remove_kw:{group_id}")],
                    [InlineKeyboardButton("📋 List Keywords", callback_data=f"list_kw:{group_id}")],
                    [InlineKeyboardButton("🗑️ Clear All Keywords", callback_data=f"clear_kw:{group_id}")],
                    [InlineKeyboardButton(f"🔄 Toggle ({status})", callback_data=f"toggle:{group_id}")],
                    [InlineKeyboardButton("« Back to Groups", callback_data="back_to_groups")]
                ]
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                message = f"<b>Managing: {group_info['name']}</b>\n\n"
                message += f"Status: {status}\n"
                message += f"Keywords: {keyword_count}\n"
                message += f"ID: <code>{group_id}</code>"
                
                await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
                
            except (ValueError, IndexError) as e:
                logger.error(f"Error parsing callback data: {e}")
                await query.edit_message_text("Error processing selection.")
        
        # =====================================================================
        # ADD KEYWORDS FLOW
        # =====================================================================
        elif data.startswith("add_kw:"):
            group_id = int(data.split(":")[1])
            self.pending_keyword_add[user_id] = group_id
            self.menu_state[user_id] = "adding_keywords"
            
            group_name = self.groups[group_id]['name']
            current_keywords = self.groups[group_id]['keywords']
            keywords_text = ", ".join(sorted(current_keywords)) if current_keywords else "None"
            
            keyboard = [[InlineKeyboardButton("« Cancel", callback_data=f"manage_group:{group_id}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                f"<b>Adding keywords to: {group_name}</b>\n\n"
                f"Current keywords:\n<code>{keywords_text}</code>\n\n"
                f"Send keywords separated by commas:\n"
                f"Example: <code>vpn, iphone, tech news</code>",
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
        
        # =====================================================================
        # REMOVE KEYWORDS FLOW
        # =====================================================================
        elif data.startswith("remove_kw:"):
            group_id = int(data.split(":")[1])
            
            if not self.groups[group_id]['keywords']:
                keyboard = [[InlineKeyboardButton("« Back", callback_data=f"manage_group:{group_id}")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(
                    f"No keywords to remove from {self.groups[group_id]['name']}",
                    reply_markup=reply_markup
                )
                return
            
            self.pending_keyword_remove[user_id] = group_id
            self.menu_state[user_id] = "removing_keywords"
            
            group_name = self.groups[group_id]['name']
            current_keywords = sorted(self.groups[group_id]['keywords'])
            keywords_text = ", ".join(current_keywords)
            
            keyboard = [[InlineKeyboardButton("« Cancel", callback_data=f"manage_group:{group_id}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                f"<b>Removing keywords from: {group_name}</b>\n\n"
                f"Current keywords:\n<code>{keywords_text}</code>\n\n"
                f"Send keywords to remove (comma-separated):",
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
        
        # =====================================================================
        # LIST KEYWORDS
        # =====================================================================
        elif data.startswith("list_kw:"):
            group_id = int(data.split(":")[1])
            group_info = self.groups[group_id]
            
            keywords = sorted(group_info['keywords'])
            if keywords:
                keywords_text = "\n".join(f"• {kw}" for kw in keywords)
            else:
                keywords_text = "No keywords configured."
            
            keyboard = [[InlineKeyboardButton("« Back", callback_data=f"manage_group:{group_id}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                f"<b>Keywords for: {group_info['name']}</b>\n\n{keywords_text}",
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
        
        # =====================================================================
        # CLEAR ALL KEYWORDS
        # =====================================================================
        elif data.startswith("clear_kw:"):
            group_id = int(data.split(":")[1])
            
            keyboard = [
                [InlineKeyboardButton("⚠️ Yes, Clear All", callback_data=f"confirm_clear:{group_id}")],
                [InlineKeyboardButton("« Cancel", callback_data=f"manage_group:{group_id}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                f"⚠️ Are you sure you want to clear ALL keywords from {self.groups[group_id]['name']}?",
                reply_markup=reply_markup
            )
        
        elif data.startswith("confirm_clear:"):
            group_id = int(data.split(":")[1])
            group_name = self.groups[group_id]['name']
            count = len(self.groups[group_id]['keywords'])
            
            self.groups[group_id]['keywords'] = set()
            self.save_data()
            
            keyboard = [[InlineKeyboardButton("« Back to Group", callback_data=f"manage_group:{group_id}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                f"✅ Cleared {count} keywords from {group_name}",
                reply_markup=reply_markup
            )
        
        # =====================================================================
        # TOGGLE GROUP
        # =====================================================================
        elif data.startswith("toggle:"):
            group_id = int(data.split(":")[1])
            
            self.groups[group_id]['enabled'] = not self.groups[group_id]['enabled']
            self.save_data()
            
            new_status = "enabled" if self.groups[group_id]['enabled'] else "disabled"
            
            # Refresh the menu
            group_info = self.groups[group_id]
            keyword_count = len(group_info['keywords'])
            status = "Enabled" if group_info['enabled'] else "Disabled"
            
            keyboard = [
                [InlineKeyboardButton("➕ Add Keywords", callback_data=f"add_kw:{group_id}")],
                [InlineKeyboardButton("➖ Remove Keywords", callback_data=f"remove_kw:{group_id}")],
                [InlineKeyboardButton("📋 List Keywords", callback_data=f"list_kw:{group_id}")],
                [InlineKeyboardButton("🗑️ Clear All Keywords", callback_data=f"clear_kw:{group_id}")],
                [InlineKeyboardButton(f"🔄 Toggle ({status})", callback_data=f"toggle:{group_id}")],
                [InlineKeyboardButton("« Back to Groups", callback_data="back_to_groups")]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            message = f"<b>Managing: {group_info['name']}</b>\n\n"
            message += f"Status: {status} ✅\n"
            message += f"Keywords: {keyword_count}\n"
            message += f"ID: <code>{group_id}</code>\n\n"
            message += f"<i>Group {new_status}!</i>"
            
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
        
        # =====================================================================
        # BACK TO GROUPS
        # =====================================================================
        elif data == "back_to_groups":
            # Clear any pending states
            if user_id in self.pending_keyword_add:
                del self.pending_keyword_add[user_id]
            if user_id in self.pending_keyword_remove:
                del self.pending_keyword_remove[user_id]
            if user_id in self.menu_state:
                del self.menu_state[user_id]
            
            if not self.groups:
                await query.edit_message_text("No groups configured.")
                return
            
            keyboard = []
            for group_id, group_info in self.groups.items():
                keyword_count = len(group_info['keywords'])
                status_icon = "✓" if group_info['enabled'] else "✗"
                button_text = f"{status_icon} {group_info['name']} ({keyword_count} kw)"
                keyboard.append([InlineKeyboardButton(button_text, callback_data=f"manage_group:{group_id}")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("Select a group to manage:", reply_markup=reply_markup)
    
    # =========================================================================
    # MESSAGE HANDLER (for keyword input after menu selection)
    # =========================================================================
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text messages for adding/removing keywords"""
        if not update.message or not update.message.text:
            return
        
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        text = update.message.text.strip()
        
        # Only process in owner's control group
        if not self.is_owner(chat_id):
            return
        
        # Ignore commands
        if text.startswith('/'):
            return
        
        # =====================================================================
        # ADDING KEYWORDS
        # =====================================================================
        if user_id in self.pending_keyword_add:
            group_id = self.pending_keyword_add[user_id]
            
            if group_id not in self.groups:
                await update.message.reply_text("Group no longer exists.")
                del self.pending_keyword_add[user_id]
                if user_id in self.menu_state:
                    del self.menu_state[user_id]
                return
            
            # Parse comma-separated keywords
            keywords = [kw.strip().lower() for kw in text.split(',') if kw.strip()]
            
            if not keywords:
                await update.message.reply_text("No valid keywords found. Try again.")
                return
            
            # Add keywords
            added = []
            for kw in keywords:
                if kw not in self.groups[group_id]['keywords']:
                    self.groups[group_id]['keywords'].add(kw)
                    added.append(kw)
            
            self.save_data()
            
            # Clear pending state
            del self.pending_keyword_add[user_id]
            if user_id in self.menu_state:
                del self.menu_state[user_id]
            
            group_name = self.groups[group_id]['name']
            
            if added:
                keyboard = [[InlineKeyboardButton("« Back to Group", callback_data=f"manage_group:{group_id}")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text(
                    f"✅ Added {len(added)} keyword(s) to {group_name}:\n"
                    f"<code>{', '.join(added)}</code>",
                    reply_markup=reply_markup,
                    parse_mode='HTML'
                )
            else:
                keyboard = [[InlineKeyboardButton("« Back to Group", callback_data=f"manage_group:{group_id}")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text(
                    f"All keywords already exist in {group_name}.",
                    reply_markup=reply_markup
                )
        
        # =====================================================================
        # REMOVING KEYWORDS
        # =====================================================================
        elif user_id in self.pending_keyword_remove:
            group_id = self.pending_keyword_remove[user_id]
            
            if group_id not in self.groups:
                await update.message.reply_text("Group no longer exists.")
                del self.pending_keyword_remove[user_id]
                if user_id in self.menu_state:
                    del self.menu_state[user_id]
                return
            
            # Parse comma-separated keywords
            keywords = [kw.strip().lower() for kw in text.split(',') if kw.strip()]
            
            if not keywords:
                await update.message.reply_text("No valid keywords found. Try again.")
                return
            
            # Remove keywords
            removed = []
            for kw in keywords:
                if kw in self.groups[group_id]['keywords']:
                    self.groups[group_id]['keywords'].discard(kw)
                    removed.append(kw)
            
            self.save_data()
            
            # Clear pending state
            del self.pending_keyword_remove[user_id]
            if user_id in self.menu_state:
                del self.menu_state[user_id]
            
            group_name = self.groups[group_id]['name']
            
            if removed:
                keyboard = [[InlineKeyboardButton("« Back to Group", callback_data=f"manage_group:{group_id}")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text(
                    f"✅ Removed {len(removed)} keyword(s) from {group_name}:\n"
                    f"<code>{', '.join(removed)}</code>",
                    reply_markup=reply_markup,
                    parse_mode='HTML'
                )
            else:
                keyboard = [[InlineKeyboardButton("« Back to Group", callback_data=f"manage_group:{group_id}")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text(
                    f"Keywords not found in {group_name}.",
                    reply_markup=reply_markup
                )
    
    # =========================================================================
    # DIRECT KEYWORD COMMANDS
    # =========================================================================
    
    async def addkeyword_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Add keyword to a group directly"""
        chat_id = update.effective_chat.id
        
        if not self.is_owner(chat_id):
            return
        
        if len(context.args) < 2:
            await update.message.reply_text(
                "Usage: /addkeyword <group_id> <keyword>\n"
                "Example: /addkeyword -1001234567890 vpn service"
            )
            return
        
        try:
            group_id = int(context.args[0])
            keyword = ' '.join(context.args[1:]).lower().strip()
            
            if group_id not in self.groups:
                await update.message.reply_text("Group not found.")
                return
            
            if keyword in self.groups[group_id]['keywords']:
                await update.message.reply_text(f"Keyword '{keyword}' already exists.")
                return
            
            self.groups[group_id]['keywords'].add(keyword)
            self.save_data()
            
            await update.message.reply_text(
                f"✅ Added keyword to {self.groups[group_id]['name']}:\n"
                f"<code>{keyword}</code>",
                parse_mode='HTML'
            )
            
        except ValueError:
            await update.message.reply_text("Invalid group ID.")
    
    async def removekeyword_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Remove keyword from a group directly"""
        chat_id = update.effective_chat.id
        
        if not self.is_owner(chat_id):
            return
        
        if len(context.args) < 2:
            await update.message.reply_text(
                "Usage: /removekeyword <group_id> <keyword>\n"
                "Example: /removekeyword -1001234567890 vpn service"
            )
            return
        
        try:
            group_id = int(context.args[0])
            keyword = ' '.join(context.args[1:]).lower().strip()
            
            if group_id not in self.groups:
                await update.message.reply_text("Group not found.")
                return
            
            if keyword not in self.groups[group_id]['keywords']:
                await update.message.reply_text(f"Keyword '{keyword}' not found.")
                return
            
            self.groups[group_id]['keywords'].discard(keyword)
            self.save_data()
            
            await update.message.reply_text(
                f"✅ Removed keyword from {self.groups[group_id]['name']}:\n"
                f"<code>{keyword}</code>",
                parse_mode='HTML'
            )
            
        except ValueError:
            await update.message.reply_text("Invalid group ID.")
    
    async def listkeywords_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """List keywords for a group"""
        chat_id = update.effective_chat.id
        
        if not self.is_owner(chat_id):
            return
        
        if not context.args:
            await update.message.reply_text("Usage: /listkeywords <group_id>")
            return
        
        try:
            group_id = int(context.args[0])
            
            if group_id not in self.groups:
                await update.message.reply_text("Group not found.")
                return
            
            group_info = self.groups[group_id]
            keywords = sorted(group_info['keywords'])
            
            if keywords:
                keywords_text = "\n".join(f"• {kw}" for kw in keywords)
                await update.message.reply_text(
                    f"<b>Keywords for {group_info['name']}:</b>\n\n{keywords_text}",
                    parse_mode='HTML'
                )
            else:
                await update.message.reply_text(f"No keywords configured for {group_info['name']}.")
                
        except ValueError:
            await update.message.reply_text("Invalid group ID.")
    
    # =========================================================================
    # FACEBOOK MONITORING
    # =========================================================================
    
    def _log(self, message: str):
        """Log with timestamp"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] {message}")
    
    async def send_alert_to_group(self, group_id: int, post: dict, keyword: str):
        """Send a Facebook post alert to a specific group"""
        try:
            import html
            
            # Format the message
            text = html.escape(clean_html_entities(str(post.get('text', 'No text'))[:800]))
            
            message = f"<b>🔔 KEYWORD ALERT</b>\n\n"
            message += f"<b>Keyword:</b> <code>{keyword}</code>\n\n"
            message += f"<b>Post:</b>\n<i>{text}</i>\n"
            
            # Add URL if available
            post_url = clean_facebook_url(post.get('post_url')) if post.get('post_url') else None
            if post_url:
                message += f"\n<a href=\"{post_url}\">View Post</a>"
            
            # Send via Telegram API
            import aiohttp
            async with aiohttp.ClientSession() as session:
                url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
                data = {
                    'chat_id': group_id,
                    'text': message,
                    'parse_mode': 'HTML',
                    'disable_web_page_preview': True
                }
                async with session.post(url, data=data) as response:
                    if response.status == 200:
                        logger.info(f"Alert sent to group {group_id} for keyword '{keyword}'")
                    else:
                        resp_text = await response.text()
                        logger.error(f"Failed to send alert: {resp_text}")
                        
        except Exception as e:
            logger.error(f"Error sending alert to group {group_id}: {e}")
    
    def monitoring_loop(self):
        """Main monitoring loop - runs in a separate thread"""
        self._log("=== Facebook Monitor Starting ===")
        
        # Initialize scraper
        self.scraper = FacebookSearchScraper(self.cookies_file)
        if not self.scraper.start_browser():
            self._log("[ERROR] Failed to start browser!")
            return
        
        self.seen_db = SeenPostsDB(self.seen_posts_file, 4)
        self._log("Browser started successfully")
        
        while self.running:
            try:
                self._log("--- Starting check cycle ---")
                
                # Get all unique keywords from enabled groups
                keyword_to_groups: Dict[str, list] = {}
                for group_id, group_info in self.groups.items():
                    if not group_info['enabled']:
                        continue
                    for keyword in group_info['keywords']:
                        if keyword not in keyword_to_groups:
                            keyword_to_groups[keyword] = []
                        keyword_to_groups[keyword].append(group_id)
                
                if not keyword_to_groups:
                    self._log("No keywords configured. Sleeping...")
                else:
                    self._log(f"Searching {len(keyword_to_groups)} unique keywords")
                    
                    for keyword, target_groups in keyword_to_groups.items():
                        if not self.running:
                            break
                        
                        try:
                            posts = self.scraper.search_keyword(keyword)
                            
                            if not posts:
                                self._log(f"No posts for: {keyword}")
                                # Mark keyword as initialized even if no posts found
                                for group_id in target_groups:
                                    init_key = f"{group_id}:{keyword}"
                                    self.initialized_keywords.add(init_key)
                                continue
                            
                            self._log(f"Found {len(posts)} posts for: {keyword}")
                            
                            # Process each group separately (for backfill tracking)
                            for group_id in target_groups:
                                if group_id not in self.processed_items:
                                    self.processed_items[group_id] = set()
                                
                                init_key = f"{group_id}:{keyword}"
                                is_first_time = init_key not in self.initialized_keywords
                                
                                if is_first_time:
                                    # First time seeing this keyword for this group
                                    # Send up to initial_backfill_count posts
                                    self._log(f"  [BACKFILL] New keyword '{keyword}' for group {group_id}, sending up to {self.initial_backfill_count} posts")
                                    posts_to_send = posts[:self.initial_backfill_count]
                                    
                                    for post in posts_to_send:
                                        post_id = post.get('id')
                                        if not post_id:
                                            continue
                                        
                                        # Mark as seen in global DB
                                        self.seen_db.mark_seen(post_id)
                                        
                                        # Send alert
                                        loop = asyncio.new_event_loop()
                                        asyncio.set_event_loop(loop)
                                        try:
                                            loop.run_until_complete(
                                                self.send_alert_to_group(group_id, post, keyword)
                                            )
                                        finally:
                                            loop.close()
                                        
                                        self.processed_items[group_id].add(post_id)
                                        time.sleep(1)  # Rate limiting
                                    
                                    # Mark this keyword as initialized
                                    self.initialized_keywords.add(init_key)
                                    self._log(f"  [BACKFILL] Sent {len(posts_to_send)} posts, keyword initialized")
                                else:
                                    # Regular cycle - only send NEW posts (not seen before)
                                    for post in posts:
                                        post_id = post.get('id')
                                        if not post_id or self.seen_db.is_seen(post_id):
                                            continue
                                        
                                        self.seen_db.mark_seen(post_id)
                                        self._log(f"  New post: {post_id[:30]}...")
                                        
                                        # Send alert
                                        loop = asyncio.new_event_loop()
                                        asyncio.set_event_loop(loop)
                                        try:
                                            loop.run_until_complete(
                                                self.send_alert_to_group(group_id, post, keyword)
                                            )
                                        finally:
                                            loop.close()
                                        
                                        self.processed_items[group_id].add(post_id)
                                        time.sleep(1)  # Rate limiting
                            
                            time.sleep(5)  # Delay between keyword searches
                            
                        except Exception as e:
                            self._log(f"[ERROR] Error searching '{keyword}': {e}")
                    
                    self.save_data()
                
                self._log(f"--- Cycle complete. Sleeping {self.check_interval}s ---")
                
                # Sleep in small chunks so we can stop quickly
                for _ in range(self.check_interval):
                    if not self.running:
                        break
                    time.sleep(1)
                    
            except Exception as e:
                self._log(f"[ERROR] Monitor error: {e}")
                time.sleep(30)
        
        # Cleanup
        if self.scraper:
            self.scraper.close_browser()
        self._log("=== Facebook Monitor Stopped ===")
    
    def start_monitoring(self):
        """Start the monitoring thread"""
        if self.running:
            return
        
        self.running = True
        self.monitor_thread = threading.Thread(target=self.monitoring_loop, daemon=True)
        self.monitor_thread.start()
        logger.info("Monitoring thread started")
    
    def stop_monitoring(self):
        """Stop the monitoring thread"""
        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=10)
        logger.info("Monitoring thread stopped")
    
    # =========================================================================
    # BOT STARTUP
    # =========================================================================
    
    def run(self):
        """Start the bot"""
        logger.info("Starting Facebook Monitor Bot...")
        logger.info(f"Owner chat ID: {self.owner_chat_id}")
        logger.info(f"Groups configured: {len(self.groups)}")
        
        # Build the Telegram application
        app = Application.builder().token(self.telegram_token).build()
        
        # Register command handlers
        app.add_handler(CommandHandler("start", self.help_command))
        app.add_handler(CommandHandler("help", self.help_command))
        app.add_handler(CommandHandler("status", self.status_command))
        app.add_handler(CommandHandler("group", self.group_command))
        app.add_handler(CommandHandler("addgroup", self.addgroup_command))
        app.add_handler(CommandHandler("removegroup", self.removegroup_command))
        app.add_handler(CommandHandler("listgroups", self.listgroups_command))
        app.add_handler(CommandHandler("addkeyword", self.addkeyword_command))
        app.add_handler(CommandHandler("removekeyword", self.removekeyword_command))
        app.add_handler(CommandHandler("listkeywords", self.listkeywords_command))
        
        # Callback handler for inline buttons
        app.add_handler(CallbackQueryHandler(self.group_callback_handler))
        
        # Message handler for keyword input
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
        # Start monitoring in background
        self.start_monitoring()
        
        # Start the Telegram bot
        logger.info("Bot is running. Press Ctrl+C to stop.")
        try:
            app.run_polling(drop_pending_updates=True)
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            self.stop_monitoring()


def ensure_data_files():
    """
    Ensure data files exist in DATA_DIR (for Render persistent disk).
    Copies cookies from Render's secret files location (/etc/secrets/) to /data.
    """
    import shutil
    
    data_dir = os.environ.get("DATA_DIR", ".")
    cookies_file = os.environ.get("COOKIES_FILE", "fb_cookies.json")
    
    # Create data directory if needed
    if data_dir != ".":
        os.makedirs(data_dir, exist_ok=True)
        print(f"[STARTUP] Ensured data directory exists: {data_dir}")
    
    # Check if cookies file needs to be copied
    if not os.path.exists(cookies_file):
        # Render mounts secret files at /etc/secrets/FILENAME
        secret_cookies = "/etc/secrets/fb_cookies.json"
        
        if os.path.exists(secret_cookies):
            shutil.copy(secret_cookies, cookies_file)
            print(f"[STARTUP] Copied cookies from {secret_cookies} to {cookies_file}")
        # Also check repo root as fallback
        elif os.path.exists("fb_cookies.json"):
            shutil.copy("fb_cookies.json", cookies_file)
            print(f"[STARTUP] Copied cookies from repo to {cookies_file}")
        else:
            print(f"[WARNING] No cookies file found! Add fb_cookies.json as a Render Secret File")
    else:
        print(f"[STARTUP] Cookies file already exists at: {cookies_file}")
    
    # Ensure bot_data.json and seen_posts.json exist (empty if not)
    for filename in ["bot_data.json", "seen_posts.json"]:
        filepath = os.path.join(data_dir, filename)
        if not os.path.exists(filepath):
            with open(filepath, 'w') as f:
                if filename == "bot_data.json":
                    json.dump({"groups": {}, "processed_items": {}, "initialized_keywords": []}, f)
                else:
                    json.dump({"posts": {}}, f)
            print(f"[STARTUP] Created empty {filename}")


def main():
    print("""
    ╔═══════════════════════════════════════════════╗
    ║   Facebook Keyword Monitor v4.0               ║
    ║   Multi-Group • Interactive Menu              ║
    ╚═══════════════════════════════════════════════╝
    """)
    
    # Ensure data files are in place (for Render persistent disk)
    ensure_data_files()
    
    bot = FacebookTelegramBot()
    bot.run()


if __name__ == "__main__":
    main()
