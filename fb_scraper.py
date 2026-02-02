# Facebook Search Scraper - Headless Chrome + BeautifulSoup
# FIXED: Uses post URLs as boundary markers instead of container guessing

import json
import time
import random
import os
import re
import hashlib
from urllib.parse import quote
from typing import List, Dict, Optional, Tuple
from bs4 import BeautifulSoup, NavigableString

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

# Try to use webdriver_manager, fallback to system chromedriver
try:
    from webdriver_manager.chrome import ChromeDriverManager
    USE_WEBDRIVER_MANAGER = True
except ImportError:
    USE_WEBDRIVER_MANAGER = False

from config import MAX_POSTS_PER_PAGE, MIN_ACTION_DELAY, MAX_ACTION_DELAY
from url_cleaner import clean_facebook_url, clean_html_entities

import sys

def log(msg: str):
    """Print with immediate flush so logs appear in real-time."""
    print(msg, flush=True)
    sys.stdout.flush()


class FacebookSearchScraper:
    """Headless Chrome scraper for Facebook Search - Uses URL boundaries for clean post isolation."""
    
    def __init__(self, cookies_file: str = "fb_cookies.json"):
        self.cookies_file = cookies_file
        self.driver = None
        self.cookies = self._load_cookies()
    
    def _load_cookies(self) -> List[Dict]:
        """Load Facebook cookies from JSON file."""
        if os.path.exists(self.cookies_file):
            with open(self.cookies_file, 'r') as f:
                return json.load(f)
        else:
            raise FileNotFoundError(f"Cookies file not found: {self.cookies_file}")
    
    def _random_delay(self, multiplier: float = 1.0):
        """Random delay for rate limiting."""
        delay = random.uniform(MIN_ACTION_DELAY, MAX_ACTION_DELAY) * multiplier
        time.sleep(delay)
    
    def start_browser(self) -> bool:
        """Start headless Chrome and inject cookies."""
        try:
            log("[BROWSER] Starting headless Chrome...")
            
            chrome_options = Options()
            chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--window-size=1920,1080")
            chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
            
            # Anti-detection
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option('useAutomationExtension', False)
            
            # Create driver
            if USE_WEBDRIVER_MANAGER:
                service = Service(ChromeDriverManager().install())
                self.driver = webdriver.Chrome(service=service, options=chrome_options)
            else:
                # Use system chromedriver (for Render)
                self.driver = webdriver.Chrome(options=chrome_options)
            
            # Navigate to Facebook first (required for cookie domain)
            self.driver.get("https://www.facebook.com")
            time.sleep(2)
            
            # Inject cookies
            log(f"[BROWSER] Injecting {len(self.cookies)} cookies...")
            success_count = 0
            fail_count = 0
            important_cookies = {'c_user': False, 'xs': False, 'datr': False, 'fr': False}
            
            for cookie in self.cookies:
                try:
                    # Track important cookies
                    if cookie['name'] in important_cookies:
                        important_cookies[cookie['name']] = True
                        log(f"[BROWSER] Found key cookie: {cookie['name']}")
                    
                    selenium_cookie = {
                        'name': cookie['name'],
                        'value': cookie['value'],
                        'domain': cookie.get('domain', '.facebook.com'),
                        'path': cookie.get('path', '/'),
                        'secure': cookie.get('secure', True),
                        'httpOnly': cookie.get('httpOnly', False)
                    }
                    self.driver.add_cookie(selenium_cookie)
                    success_count += 1
                except Exception as e:
                    fail_count += 1
                    log(f"[BROWSER] Cookie failed: {cookie.get('name', 'unknown')} - {e}")
            
            log(f"[BROWSER] Cookie injection: {success_count} success, {fail_count} failed")
            
            # Check for critical cookies
            missing_critical = [k for k, v in important_cookies.items() if not v]
            if missing_critical:
                log(f"[BROWSER] WARNING: Missing critical cookies: {missing_critical}")
            else:
                log("[BROWSER] All critical cookies present!")
            
            # Refresh to apply cookies
            self.driver.refresh()
            time.sleep(1)  # Reduced from 3
            
            # Check if we're logged in by looking at the page
            page_title = self.driver.title
            log(f"[BROWSER] After refresh, page title: {page_title}")
            
            # Check if login was successful
            if "log in" in page_title.lower() or "sign up" in page_title.lower():
                log("[BROWSER] Cookie login failed - attempting email/password login...")
                if not self._login_with_credentials():
                    log("[BROWSER] Login failed!")
                    return False
            
            log("[BROWSER] Headless Chrome ready and authenticated!")
            return True
            
        except Exception as e:
            log(f"[BROWSER] Failed to start: {e}")
            return False
    
    def _login_with_credentials(self) -> bool:
        """Login to Facebook using email and password."""
        import os
        
        email = os.environ.get("FB_EMAIL", "")
        password = os.environ.get("FB_PASSWORD", "")
        
        if not email or not password:
            log("[LOGIN] FB_EMAIL or FB_PASSWORD not set in environment!")
            return False
        
        try:
            log("[LOGIN] Navigating to login page...")
            self.driver.get("https://www.facebook.com/login")
            time.sleep(1)
            
            # Find and fill email field
            log("[LOGIN] Entering email...")
            email_field = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "email"))
            )
            email_field.clear()
            email_field.send_keys(email)
            
            # Find and fill password field
            log("[LOGIN] Entering password...")
            password_field = self.driver.find_element(By.ID, "pass")
            password_field.clear()
            password_field.send_keys(password)
            
            # Click login button
            log("[LOGIN] Clicking login button...")
            login_button = self.driver.find_element(By.NAME, "login")
            login_button.click()
            
            # Wait for navigation
            time.sleep(3)
            
            # Check if login succeeded
            page_title = self.driver.title
            current_url = self.driver.current_url
            log(f"[LOGIN] After login - Title: {page_title}")
            log(f"[LOGIN] After login - URL: {current_url}")
            
            # Check for common failure indicators
            if "checkpoint" in current_url.lower():
                log("[LOGIN] WARNING: Security checkpoint detected! May need manual verification.")
                # Save screenshot for debugging
                self.driver.save_screenshot("/var/data/login_checkpoint.png")
                return False
            
            if "login" in current_url.lower() and "two_step_verification" not in current_url.lower():
                log("[LOGIN] Still on login page - credentials may be wrong")
                return False
            
            log("[LOGIN] Login successful!")
            return True
            
        except Exception as e:
            log(f"[LOGIN] Error during login: {e}")
            import traceback
            log(traceback.format_exc())
            return False
    
    def close_browser(self):
        """Close the browser."""
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
            self.driver = None
            log("[BROWSER] Closed.")
    
    def search_keyword(self, keyword: str) -> List[Dict]:
        """
        Search Facebook for a keyword and extract posts.
        Uses URL boundaries to properly isolate individual posts.
        """
        encoded_keyword = quote(keyword)
        recent_filter = "eyJyZWNlbnRfcG9zdHM6MCI6IntcIm5hbWVcIjpcInJlY2VudF9wb3N0c1wiLFwiYXJnc1wiOlwiXCJ9In0%3D"
        search_url = f"https://www.facebook.com/search/posts?q={encoded_keyword}&filters={recent_filter}"
        
        log(f"\n[SEARCH] Keyword: '{keyword}'")
        log(f"[SEARCH] URL: {search_url}")
        
        try:
            self.driver.get(search_url)
            self._random_delay(1.0)  # Reduced from 2.0
            
            # Wait for page load
            try:
                WebDriverWait(self.driver, 10).until(  # Reduced from 20
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
            except TimeoutException:
                print(f"[SEARCH] Timeout loading page")
                return []
            
            # Wait longer for JavaScript/React content to load
            log("[DEBUG] Waiting for content to load...")
            time.sleep(2)  # Reduced from 5
            
            # Try to wait for actual search results container
            try:
                WebDriverWait(self.driver, 5).until(  # Reduced from 10
                    EC.presence_of_element_located((By.CSS_SELECTOR, "[role='feed'], [role='main']"))
                )
                log("[DEBUG] Feed/main container found")
            except TimeoutException:
                log("[DEBUG] No feed container found, continuing anyway...")
            
            # Debug: Log page title to see if we're logged in
            page_title = self.driver.title
            log(f"[DEBUG] Page title: {page_title}")
            
            # Check for login indicators
            current_url = self.driver.current_url
            log(f"[DEBUG] Current URL: {current_url}")
            
            if "login" in current_url.lower() or "checkpoint" in current_url.lower():
                log("[ERROR] Redirected to login/checkpoint page - cookies may be expired!")
                
            # Get page HTML
            html = self.driver.page_source
            
            # Debug: Check if we see "Log In" button (not logged in indicator)
            if 'Log In</span>' in html or 'Log in</span>' in html:
                log("[WARNING] Page contains 'Log In' button - cookies may not be working!")
            
            # Parse with BeautifulSoup - NEW METHOD
            posts = self._extract_posts_by_url_boundaries(html, keyword)
            
            # Debug: If no posts found, save screenshot
            if len(posts) == 0:
                try:
                    screenshot_path = f"/var/data/debug_screenshot_{keyword}.png"
                    self.driver.save_screenshot(screenshot_path)
                    log(f"[DEBUG] Saved screenshot to {screenshot_path}")
                except Exception as e:
                    log(f"[DEBUG] Could not save screenshot: {e}")
            
            log(f"[SEARCH] Found {len(posts)} clean posts for '{keyword}'")
            return posts
            
        except WebDriverException as e:
            print(f"[SEARCH] WebDriver error: {e}")
            return []
        except Exception as e:
            print(f"[SEARCH] Error: {e}")
            return []
    
    def _extract_posts_by_url_boundaries(self, html: str, keyword: str) -> List[Dict]:
        """
        NEW APPROACH: Use post URLs as definitive boundaries.
        Extract all post links, then grab content between consecutive links.
        """
        soup = BeautifulSoup(html, 'html.parser')
        posts = []
        
        # Step 1: Find main content area (skip nav/sidebar)
        main_content = soup.find('div', role='main') or soup.find('div', role='feed') or soup
        
        # Step 2: Extract all post URLs with their positions
        post_anchors = []
        for link in main_content.find_all('a', href=True):
            href = link.get('href', '')
            
            # Only consider actual post URLs
            if any(pattern in href for pattern in ['/posts/', '/videos/', '/photos/', '/photo/', 'story_fbid=', '/permalink/', 'fbid=']):
                # Skip search/hashtag relinks
                if '/search/' in href or '/hashtag/' in href:
                    continue
                
                # Get link text (often timestamp like "1h", "2d")
                link_text = link.get_text(strip=True)
                
                # Clean URL
                full_url = href if href.startswith('http') else f"https://www.facebook.com{href}"
                clean_url = clean_facebook_url(full_url)
                
                # Store link with its BeautifulSoup element for position tracking
                post_anchors.append({
                    'url': clean_url,
                    'element': link,
                    'timestamp': link_text if re.match(r'^\d+[hdmw]', link_text) else None
                })
        
        print(f"[PARSE] Found {len(post_anchors)} post URL anchors")
        
        # Step 3: For each post URL, extract the content BEFORE it (that's the post)
        seen_urls = set()
        seen_texts = set()
        
        for i, anchor in enumerate(post_anchors):
            if len(posts) >= MAX_POSTS_PER_PAGE:
                break
            
            url = anchor['url']
            
            # Skip duplicate URLs
            if url in seen_urls:
                continue
            
            # Find the content block associated with this post
            # Strategy: Walk up from the link to find the containing post div
            post_container = self._find_post_container(anchor['element'])
            
            if not post_container:
                continue
            
            # Extract text from this container
            raw_text = post_container.get_text(separator=' ', strip=True)
            
            # Clean the text
            clean_text = self._clean_post_text(raw_text)
            
            # Skip if too short or doesn't contain keyword
            if len(clean_text) < 50 or keyword.lower() not in clean_text.lower():
                continue
            
            # Skip duplicates
            text_hash = hash(clean_text[:200])
            if text_hash in seen_texts:
                continue
            seen_texts.add(text_hash)
            seen_urls.add(url)
            
            # Extract author from this specific container
            author = self._extract_author(post_container)
            
            # Extract timestamp
            timestamp = anchor['timestamp']
            if not timestamp:
                timestamp = self._extract_timestamp(post_container)
            
            # Create post ID using SHA256 for deterministic hashing across process restarts
            # Python's built-in hash() is randomized per-session, which caused duplicate notifications
            content_to_hash = (clean_text[:150] + url).encode('utf-8')
            post_id = hashlib.sha256(content_to_hash).hexdigest()[:20]
            
            post = {
                "id": post_id,
                "text": clean_text[:1000],
                "keyword": keyword,
                "author": author or "Unknown",
                "post_url": url,
                "timestamp": timestamp
            }
            
            posts.append(post)
            print(f"[PARSE] Extracted post {len(posts)}: {author or 'Unknown'} - {clean_text[:60]}...")
        
        return posts
    
    def _find_post_container(self, link_element) -> Optional[any]:
        """
        Walk up from a post link to find its containing post div.
        Look for divs with role='article' or sufficient content.
        """
        current = link_element
        
        # Walk up max 10 levels
        for _ in range(10):
            current = current.parent
            if not current or current.name == 'body':
                return None
            
            # Check if this is a post container
            if current.name == 'div':
                # Method 1: Has role='article'
                if current.get('role') == 'article':
                    return current
                
                # Method 2: Contains sufficient structure (header + content)
                has_header = current.find(['h3', 'h4']) is not None
                text_length = len(current.get_text(strip=True))
                
                # A post container should have a header and decent content
                if has_header and text_length > 100:
                    return current
        
        return None
    
    def _extract_author(self, container) -> Optional[str]:
        """Extract author name from post container."""
        # Look for h3/h4 (most reliable)
        for header in container.find_all(['h3', 'h4']):
            h_text = header.get_text(strip=True)
            
            if not h_text or len(h_text) < 2:
                continue
            
            # Skip UI noise
            ui_noise = ['notification', 'sophie', 'filters', 'all', 'see', 'new', 'earlier', 
                        'like', 'share', 'comment', 'sponsored', 'search']
            if any(noise in h_text.lower() for noise in ui_noise):
                continue
            
            # Split on middot and take first part
            author = h_text.split('·')[0].strip()
            
            # Remove status patterns
            status_patterns = [
                r'feeling \w+\.?$', r'is at .*$', r'is with .*$',
                r'was live\.?$', r'added \d+ .*$', r'shared a .*$',
                r'Verified account$', r'Verified$', r'Follow$'
            ]
            for pattern in status_patterns:
                author = re.sub(pattern, '', author, flags=re.IGNORECASE).strip()
            
            author = author.rstrip('.')
            
            # Validate length
            if 2 <= len(author) <= 60:
                return clean_html_entities(author)
        
        return None
    
    def _extract_timestamp(self, container) -> Optional[str]:
        """Extract timestamp from post container."""
        text = container.get_text(separator=' ', strip=True)
        
        # Look for patterns like "1h", "2d", "Just now", etc.
        patterns = [r'\b\d+[hdmw]\b', r'\bJust now\b', r'\bYesterday\b', 
                   r'\b\d+ hour', r'\b\d+ min', r'\b\d+ day', r'\b\d+ week']
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group()
        
        return None
    
    def _clean_post_text(self, text: str) -> str:
        """Clean extracted post text by removing UI noise and Facebook's anti-scraping artifacts."""
        # Decode HTML entities first
        text = clean_html_entities(text)
        
        # ===========================================
        # STEP 1: Remove translation UI elements
        # ===========================================
        translation_patterns = [
            r'·?\s*See original\s*·?',
            r'·?\s*Rate this translation\s*·?',
            r'·?\s*Translated by\s*·?',
            r'·?\s*Translate\s*·?',
            r'·?\s*Auto-translated\s*·?',
            r'Automatically translated.*?$',
        ]
        for pattern in translation_patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)
        
        # ===========================================
        # STEP 2: Remove Facebook's obfuscated decoy characters
        # These appear as "e S o d o s p n t r 8 l 3..." - single chars with spaces
        # ===========================================
        # Pattern: sequences of single alphanumeric characters separated by spaces
        # More than 6 of these in a row is definitely obfuscation
        text = re.sub(r'(?:\s[a-zA-Z0-9]\s){6,}', ' ', text)
        text = re.sub(r'(?:^|\s)([a-zA-Z0-9]\s){6,}', ' ', text)
        
        # Also remove patterns like "8 l 3 t 0 7" at the start or scattered around
        text = re.sub(r'\b[0-9]\s+[a-z]\s+[0-9]\s+[a-z]\s+[0-9]\b', '', text, flags=re.IGNORECASE)
        
        # Remove random alphanumeric sequence patterns
        text = re.sub(r'\b[a-z]\s[0-9]\s[a-z]\s[0-9]\s[a-z]\b', '', text, flags=re.IGNORECASE)
        
        # ===========================================
        # STEP 3: Remove other UI noise patterns
        # ===========================================
        noise_patterns = [
            r'Find friends.*?notifications?',
            r'Number of unread.*?notifications?',
            r'Search results',
            r'Filters\s+All\s+People\s+Reels\s+Marketplace\s+Pages\s+Groups\s+Events',
            r'(Facebook\s*){3,}',
            r'Mark as read',
            r'Earlier\s+Unread',
            r'Welcome to Facebook!.*?friends\.',
            r'You might like',
            r'See all\s+Unread',
            r'All\s+Unread\s+New',
            r'Tap here to find people',
            r'Verified account',
            r'Click to expand',
            r'\d+:\d+\s*/\s*\d+:\d+',
            r'Shared with Public',
            r'· Follow',
            r'Notifications\s+',
            r'All reactions:\s*\d+',
            r'\d+\s+comments?\s+\d+\s+shares?',
            r'Like\s+Comment\s+Shar',
            r'\bSophie\b',
            r'\bSophie Burns\b',
            r'Turn on\s+Not now\s+New\s+On Facebook',
            r'All Unread.*?Turn on.*?Not now',
            r'See more',
            r'Fewer bubbles.*?table',  # Part of the garbled example
            r'\.\.\.·',  # Trailing dots with separator
        ]
        
        for pattern in noise_patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)
        
        # ===========================================
        # STEP 4: Clean up and normalize
        # ===========================================
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        
        # Remove author name prefix if it appears at start
        # e.g. "CNN · President announces..." -> "President announces..."
        text = re.sub(r'^[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}\s*·\s*', '', text)
        
        # Remove timestamp prefix
        text = re.sub(r'^\d+[hdmw]\s*·\s*', '', text)
        
        # Remove excessive dots/ellipses
        text = re.sub(r'\.{3,}', '...', text)
        
        # Remove patterns like "1RI4GlF2.com" (random gibberish URLs)
        text = re.sub(r'\b[a-zA-Z0-9]{6,}\.com\b', '', text)
        
        # Final cleanup
        text = re.sub(r'\s+', ' ', text).strip()
        text = re.sub(r'^·\s*', '', text)  # Remove leading separator
        text = re.sub(r'\s*·$', '', text)  # Remove trailing separator
        
        return text.strip()
    
    def search_all_keywords(self, keywords: List[str]) -> List[Dict]:
        """Search all keywords and return combined results."""
        if not keywords:
            return []
        
        all_posts = []
        
        for keyword in keywords:
            posts = self.search_keyword(keyword)
            all_posts.extend(posts)
            
            # Delay between searches
            if keyword != keywords[-1]:
                delay = random.uniform(5, 10)
                print(f"[SEARCH] Waiting {delay:.1f}s before next keyword...")
                time.sleep(delay)
        
        return all_posts


if __name__ == "__main__":
    print("=== Facebook Search Scraper Test (Fixed URL Boundaries) ===\n")
    
    scraper = FacebookSearchScraper()
    
    if not scraper.start_browser():
        print("Failed to start browser!")
        exit(1)
    
    try:
        # Test with a sample keyword
        test_keywords = ["test"]
        print(f"Testing with: {test_keywords}\n")
        
        for keyword in test_keywords:
            posts = scraper.search_keyword(keyword)
            
            print(f"\n--- Posts containing '{keyword}' ---")
            for i, post in enumerate(posts[:5], 1):
                print(f"\nPost {i}:")
                print(f"  Author: {post.get('author', 'Unknown')}")
                print(f"  Time: {post.get('timestamp', 'N/A')}")
                print(f"  Text: {post['text'][:150]}...")
                print(f"  URL: {post.get('post_url', 'N/A')}")
        
    finally:
        scraper.close_browser()
    
    print("\n=== Test Complete ===")
