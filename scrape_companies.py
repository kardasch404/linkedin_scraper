#!/usr/bin/env python3
"""
LinkedIn Company Scraper - All-in-One
Single script with scraper + web interface + database
"""
import asyncio
import json
import os
import random
from datetime import datetime
from playwright.async_api import async_playwright
import getpass
import mysql.connector
import sys
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import html
import re
import signal
import urllib.request


# ============================================================================
# CONFIGURATION OBJECT
# ============================================================================
class Config:
    """Central configuration"""
    
    # MySQL Settings (will be set at runtime)
    MYSQL_HOST = None
    MYSQL_USER = None
    MYSQL_PASSWORD = None
    MYSQL_DATABASE = "linkedin"
    
    # Scraper Settings
    DEFAULT_LOCATION = "106186529"  # Morocco
    DELAY_BETWEEN_PAGES = (5, 10)  # Random delay range
    DELAY_BETWEEN_COMPANIES = (3, 7)  # Random delay range
    PAGE_LOAD_TIMEOUT = 60000  # 60 seconds
    ELEMENT_TIMEOUT = 10000  # 10 seconds
    
    # Web Server Settings
    WEB_PORT = 8080
    
    # Colors
    class Colors:
        HEADER = '\033[95m'
        BLUE = '\033[94m'
        CYAN = '\033[96m'
        GREEN = '\033[92m'
        YELLOW = '\033[93m'
        RED = '\033[91m'
        BOLD = '\033[1m'
        END = '\033[0m'
        DIM = '\033[2m'


# ============================================================================
# LOGGER
# ============================================================================
class Logger:
    """Beautiful terminal logger"""
    
    @staticmethod
    def header(text):
        c = Config.Colors
        print(f"\n{c.BOLD}{c.CYAN}{'='*70}{c.END}")
        print(f"{c.BOLD}{c.CYAN}{text.center(70)}{c.END}")
        print(f"{c.BOLD}{c.CYAN}{'='*70}{c.END}\n")
    
    @staticmethod
    def success(text):
        print(f"{Config.Colors.GREEN}✓{Config.Colors.END} {text}")
    
    @staticmethod
    def error(text):
        print(f"{Config.Colors.RED}✗{Config.Colors.END} {text}")
    
    @staticmethod
    def info(text):
        print(f"{Config.Colors.BLUE}ℹ{Config.Colors.END} {text}")
    
    @staticmethod
    def warning(text):
        print(f"{Config.Colors.YELLOW}⚠{Config.Colors.END} {text}")
    
    @staticmethod
    def progress(text):
        print(f"{Config.Colors.CYAN}▶{Config.Colors.END} {text}")
    
    @staticmethod
    def data(label, value):
        c = Config.Colors
        print(f"{c.DIM}{label}:{c.END} {c.BOLD}{value}{c.END}")
    
    @staticmethod
    def section(text):
        print(f"\n{Config.Colors.BOLD}{Config.Colors.BLUE}┌─ {text}{Config.Colors.END}")
    
    @staticmethod
    def item(text):
        print(f"{Config.Colors.BLUE}│{Config.Colors.END} {text}")
    
    @staticmethod
    def end_section():
        print(f"{Config.Colors.BLUE}└{'─'*68}{Config.Colors.END}")


# ============================================================================
# DATABASE MANAGER
# ============================================================================
class DatabaseManager:
    """Handle all database operations"""
    
    def __init__(self, config):
        self.config = config
        self.logger = Logger()
    
    def get_connection(self, with_db=True):
        """Get MySQL connection"""
        params = {
            'host': self.config.MYSQL_HOST,
            'user': self.config.MYSQL_USER,
            'password': self.config.MYSQL_PASSWORD
        }
        if with_db:
            params['database'] = self.config.MYSQL_DATABASE
        return mysql.connector.connect(**params)
    
    def setup(self):
        """Create database and table"""
        self.logger.progress("Connecting to MySQL...")
        
        try:
            conn = self.get_connection(with_db=False)
            cursor = conn.cursor()
            
            self.logger.success("Connected to MySQL")
            
            # Create database
            self.logger.progress(f"Checking database '{self.config.MYSQL_DATABASE}'...")
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {self.config.MYSQL_DATABASE}")
            cursor.execute(f"USE {self.config.MYSQL_DATABASE}")
            self.logger.success(f"Database '{self.config.MYSQL_DATABASE}' ready")
            
            # Create table
            self.logger.progress("Checking table 'company'...")
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS company (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    company_name VARCHAR(255),
                    company_url VARCHAR(500) UNIQUE,
                    company_industry VARCHAR(255),
                    company_location VARCHAR(255),
                    company_followers VARCHAR(100),
                    company_about LONGTEXT,
                    company_jobs INT DEFAULT 0,
                    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_name (company_name),
                    INDEX idx_location (company_location)
                )
            ''')
            self.logger.success("Table 'company' ready")
            
            conn.commit()
            cursor.close()
            conn.close()
            
        except mysql.connector.Error as e:
            self.logger.error(f"MySQL Error: {e}")
            self.logger.warning("Please check MySQL credentials in Config class")
            sys.exit(1)
    
    def url_exists(self, url):
        """Check if company URL already exists in database"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM company WHERE company_url = %s", (url,))
            exists = cursor.fetchone() is not None
            cursor.close()
            conn.close()
            return exists
        except Exception as e:
            self.logger.error(f"Error checking URL: {e}")
            return False
    
    def save_company(self, company):
        """Save single company to database with URL validation"""
        try:
            # Check if URL exists
            if self.url_exists(company.get('url')):
                return False, "exists"
            
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO company (company_name, company_url, company_industry, company_location, company_followers, company_about, company_jobs)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            ''', (
                company.get('name'),
                company.get('url'),
                company.get('industry'),
                company.get('location'),
                company.get('followers'),
                company.get('about'),
                company.get('jobs', 0)
            ))
            
            conn.commit()
            cursor.close()
            conn.close()
            return True, "saved"
            
        except Exception as e:
            self.logger.error(f"Error saving company: {e}")
            return False, str(e)
    
    def get_all_companies(self):
        """Get all companies from database"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM company ORDER BY scraped_at DESC")
            companies = cursor.fetchall()
            cursor.close()
            conn.close()
            return companies
        except Exception as e:
            self.logger.error(f"Error fetching companies: {e}")
            return []
    
    def get_stats(self):
        """Get database statistics"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor(dictionary=True)
            
            cursor.execute("SELECT COUNT(*) as total FROM company")
            total = cursor.fetchone()['total']
            
            cursor.execute("SELECT COUNT(DISTINCT company_location) as count FROM company WHERE company_location IS NOT NULL")
            locations = cursor.fetchone()['count']
            
            cursor.execute("SELECT COUNT(DISTINCT company_industry) as count FROM company WHERE company_industry IS NOT NULL")
            industries = cursor.fetchone()['count']
            
            cursor.execute("SELECT MAX(scraped_at) as last_update FROM company")
            last = cursor.fetchone()['last_update']
            last_update = last.strftime('%b %d, %H:%M') if last else 'Never'
            
            cursor.close()
            conn.close()
            
            return {
                'total': total,
                'locations': locations,
                'industries': industries,
                'lastUpdate': last_update
            }
        except Exception as e:
            self.logger.error(f"Error fetching stats: {e}")
            return {'total': 0, 'locations': 0, 'industries': 0, 'lastUpdate': 'Error'}


# ============================================================================
# SCRAPER
# ============================================================================
class LinkedInScraper:
    """LinkedIn company scraper with anti-detection"""
    
    def __init__(self, config, db_manager):
        self.config = config
        self.db = db_manager
        self.logger = Logger()
        self.stop_scraping = False
        self.request_count = 0
        self.start_time = time.time()
    
    def check_network(self):
        """Check internet connectivity"""
        try:
            urllib.request.urlopen('https://www.google.com', timeout=5)
            return True
        except:
            return False
    
    def get_random_delay(self, delay_range):
        """Get random delay from range"""
        return random.uniform(delay_range[0], delay_range[1])
    
    async def simulate_human_behavior(self, page):
        """Simulate human-like behavior: scrolling, mouse movements"""
        try:
            # Random scroll
            scroll_amount = random.randint(300, 800)
            await page.evaluate(f"window.scrollBy(0, {scroll_amount})")
            await asyncio.sleep(random.uniform(0.5, 1.5))
            
            # Random mouse movement
            viewport = page.viewport_size
            if viewport:
                x = random.randint(100, viewport['width'] - 100)
                y = random.randint(100, viewport['height'] - 100)
                await page.mouse.move(x, y)
            
            # Random small scroll back
            if random.random() > 0.5:
                await page.evaluate(f"window.scrollBy(0, -{random.randint(50, 150)})")
                await asyncio.sleep(random.uniform(0.3, 0.8))
        except Exception as e:
            pass
    
    def rate_limit_check(self):
        """Advanced rate limiting"""
        self.request_count += 1
        elapsed = time.time() - self.start_time
        
        # Calculate requests per minute
        if elapsed > 0:
            rpm = (self.request_count / elapsed) * 60
            
            # If too fast, add extra delay
            if rpm > 30:  # Max 30 requests per minute
                extra_delay = random.uniform(2, 5)
                self.logger.warning(f"Rate limit: {rpm:.1f} req/min. Adding {extra_delay:.1f}s delay")
                return extra_delay
        return 0
    
    def clean_text(self, text):
        """Clean HTML entities and normalize text"""
        if not text:
            return None
        # Decode HTML entities: &#39; -> ', &amp; -> &, etc.
        text = html.unescape(text)
        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        return text if text else None
    
    async def login(self, page):
        """Login to LinkedIn with session support and anti-detection"""
        self.logger.section("LinkedIn Login")
        
        # Check network
        if not self.check_network():
            self.logger.error("No internet connection!")
            raise Exception("Network error")
        
        # Check for existing session
        session_file = "linkedin_session.json"
        if os.path.exists(session_file):
            self.logger.info("Found existing session file")
            use_session = input(f"{Config.Colors.CYAN}│{Config.Colors.END} Use saved session? (y/n): ").strip().lower()
            
            if use_session == 'y':
                try:
                    await self.load_session(page, session_file)
                    self.logger.success("Session loaded successfully!")
                    self.logger.end_section()
                    return
                except Exception as e:
                    self.logger.warning(f"Failed to load session: {e}")
                    self.logger.info("Proceeding with manual login...")
        
        # Manual login
        email = input(f"{Config.Colors.CYAN}│{Config.Colors.END} Email: ")
        password = getpass.getpass(f"{Config.Colors.CYAN}│{Config.Colors.END} Password: ")
        
        self.logger.end_section()
        self.logger.progress("Logging in...")
        
        try:
            await page.goto("https://www.linkedin.com/login", timeout=self.config.PAGE_LOAD_TIMEOUT, wait_until="domcontentloaded")
            await asyncio.sleep(random.uniform(1, 2))
            
            # Type like human
            await page.fill("#username", "")
            for char in email:
                await page.type("#username", char, delay=random.randint(50, 150))
            
            await asyncio.sleep(random.uniform(0.5, 1))
            
            await page.fill("#password", "")
            for char in password:
                await page.type("#password", char, delay=random.randint(50, 150))
            
            await asyncio.sleep(random.uniform(0.5, 1))
            await page.click('button[type="submit"]')
            await asyncio.sleep(5)
            
            # Check for email verification
            if "checkpoint/challenge" in page.url:
                self.logger.warning("Email verification required!")
                pin = input(f"{Config.Colors.YELLOW}Enter verification code from your email:{Config.Colors.END} ")
                
                await page.fill('input[name="pin"]', pin)
                await page.click('button[type="submit"]')
                await asyncio.sleep(3)
            
            # Wait for feed
            try:
                await page.wait_for_url("**/feed/**", timeout=30000)
                self.logger.success("Login successful!")
            except:
                self.logger.warning("Waiting for manual completion...")
                await page.wait_for_url("**/feed/**", timeout=120000)
                self.logger.success("Login completed!")
            
            # Save session
            self.logger.progress("Saving session...")
            await self.save_session(page, session_file)
            self.logger.success(f"Session saved to {session_file}")
            
        except Exception as e:
            self.logger.error(f"Login error: {e}")
            raise
    
    async def save_session(self, page, filename):
        """Save browser session to file"""
        import json
        
        # Get cookies
        cookies = await page.context.cookies()
        
        # Get localStorage for all origins
        origins_data = []
        for origin in ["https://www.linkedin.com", "https://li.protechts.net", "https://www.google.com"]:
            try:
                await page.goto(origin)
                local_storage = await page.evaluate("() => Object.entries(localStorage)")
                origins_data.append({
                    "origin": origin,
                    "localStorage": [{"name": k, "value": v} for k, v in local_storage]
                })
            except:
                pass
        
        session_data = {
            "cookies": cookies,
            "origins": origins_data
        }
        
        with open(filename, 'w') as f:
            json.dump(session_data, f, indent=2)
    
    async def load_session(self, page, filename):
        """Load browser session from file"""
        import json
        
        with open(filename, 'r') as f:
            session_data = json.load(f)
        
        # Add cookies
        await page.context.add_cookies(session_data['cookies'])
        
        # Restore localStorage
        for origin_data in session_data.get('origins', []):
            try:
                await page.goto(origin_data['origin'], timeout=self.config.PAGE_LOAD_TIMEOUT, wait_until="domcontentloaded")
                for item in origin_data.get('localStorage', []):
                    await page.evaluate(f"localStorage.setItem('{item['name']}', '{item['value']}')")
            except:
                pass
        
        # Navigate to feed
        await page.goto("https://www.linkedin.com/feed", timeout=self.config.PAGE_LOAD_TIMEOUT, wait_until="domcontentloaded")
        await asyncio.sleep(3)
    
    async def scrape_page(self, page, page_num):
        """Extract company URLs from search page"""
        self.logger.progress(f"Extracting URLs from page {page_num}...")
        
        try:
            await asyncio.sleep(3)
            
            company_urls = []
            links = await page.locator('a[href*="/company/"]').all()
            processed = set()
            
            for link in links:
                try:
                    href = await link.get_attribute('href')
                    if not href or '/company/' not in href:
                        continue
                    
                    url = href.split('?')[0].split('/about')[0].split('/posts')[0].split('/jobs')[0]
                    if not url.startswith('http'):
                        url = f"https://www.linkedin.com{url}"
                    
                    if url in processed or url.count('/company/') != 1:
                        continue
                    
                    processed.add(url)
                    company_urls.append(url)
                    self.logger.item(f"[{len(company_urls)}] {url}")
                    
                except Exception as e:
                    continue
            
            return company_urls
        except Exception as e:
            self.logger.error(f"Error scraping page: {e}")
            return []
    
    async def scrape_company_details(self, page, url):
        """Visit company /about/ page and extract details with dynamic HTML handling"""
        try:
            # Rate limiting
            extra_delay = self.rate_limit_check()
            if extra_delay > 0:
                await asyncio.sleep(extra_delay)
            
            about_url = f"{url}/about/"
            await page.goto(about_url, timeout=self.config.PAGE_LOAD_TIMEOUT, wait_until="domcontentloaded")
            
            # Simulate human behavior
            await self.simulate_human_behavior(page)
            await asyncio.sleep(random.uniform(2, 4))
            
            company = {'url': url}
            
            # Extract company name - try multiple selectors
            try:
                selectors = [
                    'h1.org-top-card-summary__title',
                    'h1[class*="org-top-card"]',
                    '.org-top-card-summary__title',
                    'h1.t-24'
                ]
                for selector in selectors:
                    try:
                        name_elem = await page.locator(selector).first.text_content(timeout=self.config.ELEMENT_TIMEOUT)
                        if name_elem:
                            company['name'] = self.clean_text(name_elem)
                            break
                    except:
                        continue
            except:
                pass
            
            # Extract industry, location, followers - dynamic approach
            try:
                info_selectors = [
                    '.org-top-card-summary-info-list__info-item',
                    '.org-page-details__definition-text',
                    'div[class*="info-item"]'
                ]
                
                for selector in info_selectors:
                    try:
                        info_items = await page.locator(selector).all()
                        if not info_items:
                            continue
                            
                        for item in info_items:
                            text = await item.text_content()
                            text = self.clean_text(text)
                            if not text:
                                continue
                            
                            # Detect followers
                            if 'follower' in text.lower() or 'abonné' in text.lower():
                                company['followers'] = text
                            # Detect location (has comma or country)
                            elif ',' in text and not company.get('location'):
                                company['location'] = text
                            # Detect industry (first non-follower text)
                            elif not company.get('industry') and 3 < len(text) < 100:
                                company['industry'] = text
                        
                        if company.get('industry'):
                            break
                    except:
                        continue
            except:
                pass
            
            # Extract about/summary - try multiple selectors and get HTML
            try:
                about_selectors = [
                    'section.org-about-module',
                    'section[class*="about"]',
                    '.org-about-us-organization-description',
                    'p.break-words'
                ]
                
                for selector in about_selectors:
                    try:
                        # Get the entire section HTML
                        about_section = await page.locator(selector).first.inner_html(timeout=self.config.ELEMENT_TIMEOUT)
                        if about_section:
                            # Clean and unescape HTML
                            company['about'] = html.unescape(about_section)
                            break
                    except:
                        continue
                
                # If no section found, try to get just the paragraph
                if not company.get('about'):
                    try:
                        about_elem = await page.locator('p.break-words').first.inner_html(timeout=self.config.ELEMENT_TIMEOUT)
                        if about_elem:
                            company['about'] = f'<p>{html.unescape(about_elem)}</p>'
                    except:
                        pass
            except:
                pass
            
            # Extract jobs count - dynamic extraction
            try:
                jobs_selectors = [
                    'a[href*="/jobs/"]',
                    'a[href*="/jobs"]',
                    'button[aria-label*="job"]'
                ]
                for selector in jobs_selectors:
                    try:
                        jobs_link = await page.locator(selector).first.text_content(timeout=self.config.ELEMENT_TIMEOUT)
                        if jobs_link and ('job' in jobs_link.lower() or 'emploi' in jobs_link.lower()):
                            numbers = re.findall(r'\d+', jobs_link.replace(',', '').replace('.', '').replace(' ', ''))
                            if numbers:
                                company['jobs'] = int(numbers[0])
                                break
                    except:
                        continue
            except:
                pass
            
            if not company.get('jobs'):
                company['jobs'] = 0
            
            return company
            
        except Exception as e:
            self.logger.error(f"Error scraping {url}: {e}")
            return {'url': url, 'name': 'Error', 'jobs': 0}
    
    async def run(self, location_id):
        """Main scraping function - infinite until Ctrl+C"""
        self.logger.header("LINKEDIN COMPANY SCRAPER - INFINITE MODE")
        
        self.logger.data("Location ID", location_id)
        self.logger.warning("Press Ctrl+C to stop and save progress")
        
        all_companies = []
        saved_count = 0
        skipped_count = 0
        start_time = time.time()
        page_num = 1
        
        try:
            async with async_playwright() as p:
                self.logger.progress("Launching browser...")
                browser = await p.chromium.launch(headless=False)
                page = await browser.new_page()
                
                try:
                    await self.login(page)
                except Exception as e:
                    self.logger.error(f"Login failed: {e}")
                    await browser.close()
                    return []
                
                # Infinite loop until Ctrl+C
                while not self.stop_scraping:
                    self.logger.section(f"Search Page {page_num}")
                    
                    try:
                        url = f"https://www.linkedin.com/search/results/companies/?companyHqGeo=%5B%22{location_id}%22%5D&origin=FACETED_SEARCH"
                        if page_num > 1:
                            url += f"&page={page_num}"
                        
                        await page.goto(url, timeout=self.config.PAGE_LOAD_TIMEOUT, wait_until="domcontentloaded")
                        await self.simulate_human_behavior(page)
                        company_urls = await self.scrape_page(page, page_num)
                        
                        if not company_urls:
                            self.logger.warning("No more companies found. Ending...")
                            break
                        
                        self.logger.end_section()
                        self.logger.success(f"Page {page_num}: {len(company_urls)} URLs collected")
                        
                        # Visit each company immediately
                        for idx, company_url in enumerate(company_urls, 1):
                            if self.stop_scraping:
                                break
                            
                            # Check if URL exists in DB first
                            if self.db.url_exists(company_url):
                                skipped_count += 1
                                self.logger.warning(f"[{idx}/{len(company_urls)}] Skipped (exists): {company_url}")
                                continue
                            
                            self.logger.progress(f"[{idx}/{len(company_urls)}] Visiting {company_url}")
                            
                            try:
                                company = await self.scrape_company_details(page, company_url)
                                all_companies.append(company)
                                
                                # Save to DB immediately
                                success, status = self.db.save_company(company)
                                if success:
                                    saved_count += 1
                                    self.logger.success(f"✓ Saved: {company.get('name', 'Unknown')[:40]} | Jobs: {company.get('jobs', 0)}")
                                else:
                                    skipped_count += 1
                                    self.logger.warning(f"✗ Skipped: {status}")
                                
                                # Save JSON backup every 10 companies
                                if len(all_companies) % 10 == 0:
                                    with open('all_companies.json', 'w', encoding='utf-8') as f:
                                        json.dump(all_companies, f, indent=2, ensure_ascii=False)
                                
                                # Random delay with rate limiting
                                delay = self.get_random_delay(self.config.DELAY_BETWEEN_COMPANIES)
                                await asyncio.sleep(delay)
                            except Exception as e:
                                self.logger.error(f"Failed: {e}")
                        
                        page_num += 1
                        delay = self.get_random_delay(self.config.DELAY_BETWEEN_PAGES)
                        self.logger.info(f"Waiting {delay:.1f}s before next page...")
                        await asyncio.sleep(delay)
                        
                    except Exception as e:
                        self.logger.error(f"Error on page {page_num}: {e}")
                        self.logger.end_section()
                        page_num += 1
                
                await browser.close()
                
        except Exception as e:
            self.logger.error(f"Critical error: {e}")
        
        # Save final JSON
        try:
            with open('all_companies.json', 'w', encoding='utf-8') as f:
                json.dump(all_companies, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"Error saving JSON: {e}")
        
        # Summary
        elapsed = time.time() - start_time
        self.logger.header("SCRAPING STOPPED")
        self.logger.data("Pages scraped", page_num - 1)
        self.logger.data("Companies found", len(all_companies))
        self.logger.data("Saved to DB", saved_count)
        self.logger.data("Skipped", skipped_count)
        self.logger.data("Time", f"{elapsed:.1f}s")
        
        return all_companies


# ============================================================================
# WEB SERVER
# ============================================================================
class WebHandler(BaseHTTPRequestHandler):
    """HTTP request handler for web interface"""
    
    db_manager = None
    
    def log_message(self, format, *args):
        """Suppress default logging"""
        pass
    
    def do_GET(self):
        """Handle GET requests"""
        if self.path == '/' or self.path == '/index.html':
            self.serve_index()
        elif self.path == '/api/companies':
            self.serve_api()
        else:
            self.send_error(404)
    
    def serve_index(self):
        """Serve main HTML page"""
        html = '''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LinkedIn Companies - Elite Dashboard</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
        
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        @keyframes gradientShift { 0%, 100% { background-position: 0% 50%; } 50% { background-position: 100% 50%; } }
        @keyframes float { 0%, 100% { transform: translateY(0px); } 50% { transform: translateY(-20px); } }
        @keyframes pulse { 0%, 100% { transform: scale(1); opacity: 1; } 50% { transform: scale(1.05); opacity: 0.8; } }
        @keyframes slideIn { from { opacity: 0; transform: translateY(30px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes shimmer { 0% { background-position: -1000px 0; } 100% { background-position: 1000px 0; } }
        @keyframes glow { 0%, 100% { box-shadow: 0 0 20px rgba(102, 126, 234, 0.4), 0 0 40px rgba(118, 75, 162, 0.2); } 50% { box-shadow: 0 0 40px rgba(102, 126, 234, 0.6), 0 0 80px rgba(118, 75, 162, 0.4); } }
        @keyframes rotate { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
        
        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background: linear-gradient(-45deg, #667eea, #764ba2, #f093fb, #4facfe);
            background-size: 400% 400%;
            animation: gradientShift 15s ease infinite;
            min-height: 100vh;
            padding: 20px;
            position: relative;
            overflow-x: hidden;
        }
        
        body::before {
            content: '';
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: radial-gradient(circle at 20% 50%, rgba(255,255,255,0.1) 0%, transparent 50%),
                        radial-gradient(circle at 80% 80%, rgba(255,255,255,0.1) 0%, transparent 50%);
            pointer-events: none;
            z-index: 1;
        }
        
        .particles { position: fixed; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none; z-index: 0; }
        .particle { position: absolute; width: 4px; height: 4px; background: rgba(255,255,255,0.6); border-radius: 50%; animation: float 6s infinite ease-in-out; }
        .particle:nth-child(1) { left: 10%; top: 20%; animation-delay: 0s; animation-duration: 8s; }
        .particle:nth-child(2) { left: 30%; top: 60%; animation-delay: 1s; animation-duration: 6s; }
        .particle:nth-child(3) { left: 50%; top: 40%; animation-delay: 2s; animation-duration: 7s; }
        .particle:nth-child(4) { left: 70%; top: 70%; animation-delay: 1.5s; animation-duration: 9s; }
        .particle:nth-child(5) { left: 90%; top: 30%; animation-delay: 0.5s; animation-duration: 5s; }
        .particle:nth-child(6) { left: 20%; top: 80%; animation-delay: 2.5s; animation-duration: 6.5s; }
        
        .container { max-width: 1600px; margin: 0 auto; position: relative; z-index: 2; }
        
        .header {
            background: rgba(255, 255, 255, 0.15);
            backdrop-filter: blur(20px) saturate(180%);
            -webkit-backdrop-filter: blur(20px) saturate(180%);
            border: 1px solid rgba(255, 255, 255, 0.3);
            padding: 40px;
            border-radius: 24px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3), inset 0 1px 0 rgba(255,255,255,0.4);
            margin-bottom: 30px;
            animation: slideIn 0.6s ease-out, glow 3s infinite;
            position: relative;
            overflow: hidden;
        }
        
        .header::before {
            content: '';
            position: absolute;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: linear-gradient(45deg, transparent, rgba(255,255,255,0.1), transparent);
            animation: rotate 6s linear infinite;
        }
        
        .header h1 {
            color: #fff;
            font-size: 42px;
            font-weight: 800;
            margin-bottom: 10px;
            text-shadow: 0 2px 20px rgba(0,0,0,0.3);
            letter-spacing: -1px;
            position: relative;
            z-index: 1;
        }
        
        .header p {
            color: rgba(255,255,255,0.9);
            font-size: 16px;
            font-weight: 400;
            position: relative;
            z-index: 1;
        }
        
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        
        .stat-card {
            background: rgba(255, 255, 255, 0.12);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border: 1px solid rgba(255, 255, 255, 0.25);
            padding: 30px;
            border-radius: 20px;
            box-shadow: 0 15px 40px rgba(0,0,0,0.2);
            text-align: center;
            transition: all 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275);
            animation: slideIn 0.6s ease-out;
            position: relative;
            overflow: hidden;
            cursor: pointer;
        }
        
        .stat-card::before {
            content: '';
            position: absolute;
            top: 0;
            left: -100%;
            width: 100%;
            height: 100%;
            background: linear-gradient(90deg, transparent, rgba(255,255,255,0.2), transparent);
            transition: left 0.5s;
        }
        
        .stat-card:hover::before { left: 100%; }
        
        .stat-card:hover {
            transform: translateY(-10px) scale(1.02);
            box-shadow: 0 25px 60px rgba(0,0,0,0.3);
            border-color: rgba(255, 255, 255, 0.5);
        }
        
        .stat-card:nth-child(1) { animation-delay: 0.1s; }
        .stat-card:nth-child(2) { animation-delay: 0.2s; }
        .stat-card:nth-child(3) { animation-delay: 0.3s; }
        .stat-card:nth-child(4) { animation-delay: 0.4s; }
        
        .stat-card .number {
            font-size: 48px;
            font-weight: 800;
            background: linear-gradient(135deg, #fff, #f0f0f0);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            margin-bottom: 8px;
            animation: pulse 2s infinite;
        }
        
        .stat-card .label {
            color: rgba(255,255,255,0.8);
            font-size: 13px;
            text-transform: uppercase;
            letter-spacing: 2px;
            font-weight: 600;
        }
        
        .table-container {
            background: rgba(255, 255, 255, 0.1);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border: 1px solid rgba(255, 255, 255, 0.25);
            border-radius: 24px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            overflow: hidden;
            animation: slideIn 0.8s ease-out 0.3s both;
        }
        
        .table-header {
            padding: 30px 40px;
            background: linear-gradient(135deg, rgba(102, 126, 234, 0.9), rgba(118, 75, 162, 0.9));
            color: white;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 20px;
        }
        
        .table-header h2 {
            font-size: 28px;
            font-weight: 700;
            text-shadow: 0 2px 10px rgba(0,0,0,0.2);
        }
        
        .search-box {
            padding: 12px 24px;
            border: 2px solid rgba(255,255,255,0.3);
            border-radius: 50px;
            width: 320px;
            background: rgba(255,255,255,0.15);
            backdrop-filter: blur(10px);
            color: white;
            font-size: 15px;
            transition: all 0.3s ease;
            outline: none;
        }
        
        .search-box::placeholder { color: rgba(255,255,255,0.7); }
        
        .search-box:focus {
            background: rgba(255,255,255,0.25);
            border-color: rgba(255,255,255,0.6);
            box-shadow: 0 0 20px rgba(255,255,255,0.3);
            transform: scale(1.02);
        }
        
        table { width: 100%; border-collapse: collapse; }
        
        thead {
            background: rgba(255,255,255,0.08);
            backdrop-filter: blur(10px);
        }
        
        th {
            padding: 20px 24px;
            text-align: left;
            font-weight: 700;
            color: rgba(255,255,255,0.95);
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 1.5px;
            border-bottom: 2px solid rgba(255,255,255,0.15);
        }
        
        td {
            padding: 20px 24px;
            border-bottom: 1px solid rgba(255,255,255,0.08);
            color: rgba(255,255,255,0.9);
            font-size: 14px;
            transition: all 0.3s ease;
        }
        
        tbody tr {
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            animation: fadeIn 0.5s ease-out;
        }
        
        tbody tr:hover {
            background: rgba(255,255,255,0.12);
            transform: scale(1.01);
            box-shadow: 0 4px 20px rgba(0,0,0,0.1);
        }
        
        .company-name {
            font-weight: 700;
            color: #fff;
            font-size: 15px;
            margin-bottom: 4px;
        }
        
        .company-url {
            color: rgba(255,255,255,0.6);
            text-decoration: none;
            font-size: 12px;
            transition: all 0.3s ease;
            display: inline-block;
        }
        
        .company-url:hover {
            color: #fff;
            transform: translateX(5px);
        }
        
        .badge {
            display: inline-block;
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
            transition: all 0.3s ease;
            cursor: default;
        }
        
        .badge:hover { transform: scale(1.1); }
        
        .badge-industry {
            background: linear-gradient(135deg, rgba(16, 185, 129, 0.3), rgba(5, 150, 105, 0.3));
            color: #6ee7b7;
            border: 1px solid rgba(16, 185, 129, 0.4);
        }
        
        .badge-location {
            background: linear-gradient(135deg, rgba(251, 191, 36, 0.3), rgba(245, 158, 11, 0.3));
            color: #fcd34d;
            border: 1px solid rgba(251, 191, 36, 0.4);
        }
        
        .badge-followers {
            background: linear-gradient(135deg, rgba(59, 130, 246, 0.3), rgba(37, 99, 235, 0.3));
            color: #93c5fd;
            border: 1px solid rgba(59, 130, 246, 0.4);
        }
        
        .loading {
            text-align: center;
            padding: 60px;
            color: rgba(255,255,255,0.8);
            font-size: 18px;
            font-weight: 500;
        }
        
        .loading::after {
            content: '';
            display: inline-block;
            width: 20px;
            height: 20px;
            border: 3px solid rgba(255,255,255,0.3);
            border-top-color: #fff;
            border-radius: 50%;
            animation: rotate 1s linear infinite;
            margin-left: 10px;
            vertical-align: middle;
        }
        
        .jobs-count {
            font-weight: 700;
            color: #a78bfa;
            font-size: 15px;
        }
        
        @media (max-width: 768px) {
            .header h1 { font-size: 28px; }
            .stat-card .number { font-size: 36px; }
            .search-box { width: 100%; }
            table { font-size: 12px; }
            th, td { padding: 12px; }
        }
    </style>
</head>
<body>
    <div class="particles">
        <div class="particle"></div>
        <div class="particle"></div>
        <div class="particle"></div>
        <div class="particle"></div>
        <div class="particle"></div>
        <div class="particle"></div>
    </div>
    
    <div class="container">
        <div class="header">
            <h1>🚀 LinkedIn Companies - Elite Dashboard</h1>
            <p>Real-time intelligence • Advanced analytics • Infinite possibilities</p>
        </div>
        
        <div class="stats">
            <div class="stat-card">
                <div class="number" id="total">-</div>
                <div class="label">Total Companies</div>
            </div>
            <div class="stat-card">
                <div class="number" id="locations">-</div>
                <div class="label">Locations</div>
            </div>
            <div class="stat-card">
                <div class="number" id="industries">-</div>
                <div class="label">Industries</div>
            </div>
            <div class="stat-card">
                <div class="number" id="lastUpdate">-</div>
                <div class="label">Last Update</div>
            </div>
        </div>
        
        <div class="table-container">
            <div class="table-header">
                <h2>📊 Company Database</h2>
                <input type="text" class="search-box" id="search" placeholder="🔍 Search companies, locations...">
            </div>
            <div id="content"><div class="loading">Loading data</div></div>
        </div>
    </div>
    
    <script>
        let data = [];
        
        async function load() {
            try {
                const res = await fetch('/api/companies');
                const json = await res.json();
                data = json.companies;
                
                animateNumber('total', json.stats.total);
                animateNumber('locations', json.stats.locations);
                animateNumber('industries', json.stats.industries);
                document.getElementById('lastUpdate').textContent = json.stats.lastUpdate;
                
                render(data);
            } catch(e) {
                document.getElementById('content').innerHTML = '<div class="loading">Error loading data</div>';
            }
        }
        
        function animateNumber(id, target) {
            const el = document.getElementById(id);
            const duration = 1000;
            const start = parseInt(el.textContent) || 0;
            const increment = (target - start) / (duration / 16);
            let current = start;
            
            const timer = setInterval(() => {
                current += increment;
                if ((increment > 0 && current >= target) || (increment < 0 && current <= target)) {
                    el.textContent = target;
                    clearInterval(timer);
                } else {
                    el.textContent = Math.floor(current);
                }
            }, 16);
        }
        
        function render(items) {
            if (!items.length) {
                document.getElementById('content').innerHTML = '<div class="loading">No companies found</div>';
                return;
            }
            
            const html = `<table>
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Company</th>
                        <th>Industry</th>
                        <th>Location</th>
                        <th>Followers</th>
                        <th>Jobs</th>
                    </tr>
                </thead>
                <tbody>${items.map((c, i) => `
                    <tr style="animation-delay: ${i * 0.02}s">
                        <td><strong>${c.id}</strong></td>
                        <td>
                            <div class="company-name">${c.company_name || 'N/A'}</div>
                            <a href="${c.company_url}" target="_blank" class="company-url">→ View Profile</a>
                        </td>
                        <td>${c.company_industry ? `<span class="badge badge-industry">${c.company_industry}</span>` : '<span style="opacity:0.5">N/A</span>'}</td>
                        <td>${c.company_location ? `<span class="badge badge-location">${c.company_location}</span>` : '<span style="opacity:0.5">N/A</span>'}</td>
                        <td>${c.company_followers ? `<span class="badge badge-followers">${c.company_followers}</span>` : '<span style="opacity:0.5">N/A</span>'}</td>
                        <td><span class="jobs-count">${c.company_jobs || 0}</span></td>
                    </tr>
                `).join('')}</tbody>
            </table>`;
            
            document.getElementById('content').innerHTML = html;
        }
        
        document.getElementById('search').addEventListener('input', e => {
            const q = e.target.value.toLowerCase();
            const filtered = data.filter(c => 
                (c.company_name && c.company_name.toLowerCase().includes(q)) || 
                (c.company_location && c.company_location.toLowerCase().includes(q)) ||
                (c.company_industry && c.company_industry.toLowerCase().includes(q))
            );
            render(filtered);
        });
        
        load();
        setInterval(load, 30000);
    </script>
</body>
</html>'''
        
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(html.encode())
    
    def serve_api(self):
        """Serve API data"""
        try:
            stats = self.db_manager.get_stats()
            companies = self.db_manager.get_all_companies()
            
            # Convert datetime to string
            for c in companies:
                if c.get('scraped_at'):
                    c['scraped_at'] = str(c['scraped_at'])
            
            data = {
                'success': True,
                'stats': stats,
                'companies': companies
            }
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())
            
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode())


def start_web_server(db_manager, port):
    """Start web server in background"""
    WebHandler.db_manager = db_manager
    server = HTTPServer(('localhost', port), WebHandler)
    Logger.success(f"Web server started: http://localhost:{port}")
    server.serve_forever()


# ============================================================================
# MAIN
# ============================================================================
# Global scraper instance for signal handler
scraper_instance = None

def signal_handler(sig, frame):
    """Handle Ctrl+C gracefully"""
    global scraper_instance
    Logger.warning("\n\n⚠ Ctrl+C detected! Stopping gracefully...")
    if scraper_instance:
        scraper_instance.stop_scraping = True

async def main():
    """Main entry point"""
    global scraper_instance
    
    config = Config()
    logger = Logger()
    
    # Setup Ctrl+C handler
    signal.signal(signal.SIGINT, signal_handler)
    
    logger.header("LINKEDIN SCRAPER - ALL-IN-ONE")
    
    # Get MySQL credentials
    logger.section("MySQL Configuration")
    config.MYSQL_HOST = input(f"{Config.Colors.CYAN}│{Config.Colors.END} Host (default: localhost): ").strip() or "localhost"
    config.MYSQL_USER = input(f"{Config.Colors.CYAN}│{Config.Colors.END} User (default: root): ").strip() or "root"
    config.MYSQL_PASSWORD = getpass.getpass(f"{Config.Colors.CYAN}│{Config.Colors.END} Password: ")
    logger.end_section()
    
    # Setup database
    db = DatabaseManager(config)
    db.setup()
    
    # Ask what to do
    logger.section("What do you want to do?")
    logger.item("1. Scrape companies (infinite until Ctrl+C)")
    logger.item("2. Start web interface")
    logger.item("3. Both (scrape then web)")
    logger.end_section()
    
    choice = input(f"{Config.Colors.CYAN}Choice (1/2/3):{Config.Colors.END} ").strip()
    
    if choice in ['1', '3']:
        # Scraping
        logger.section("Scraper Configuration")
        location = input(f"{Config.Colors.CYAN}│{Config.Colors.END} Location ID (default: {config.DEFAULT_LOCATION}): ").strip() or config.DEFAULT_LOCATION
        logger.end_section()
        
        scraper = LinkedInScraper(config, db)
        scraper_instance = scraper
        await scraper.run(location)
    
    if choice in ['2', '3']:
        # Web server
        logger.info(f"Starting web server on port {config.WEB_PORT}...")
        logger.success(f"Open: http://localhost:{config.WEB_PORT}")
        logger.warning("Press Ctrl+C to stop")
        
        try:
            start_web_server(db, config.WEB_PORT)
        except KeyboardInterrupt:
            logger.info("\nServer stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        Logger.info("\nExiting...")
        sys.exit(0)
