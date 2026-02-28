#!/usr/bin/env python3
"""
LinkedIn Jobs Scraper - Elite Architecture
Single script: Scrapes jobs by company with full HTML content
"""
import asyncio
import json
import os
import random
import re
import html
import signal
import sys
import time
import getpass
import urllib.request
from datetime import datetime
from playwright.async_api import async_playwright
import mysql.connector


# ============================================================================
# CONFIGURATION
# ============================================================================
class Config:
    """Central configuration"""
    MYSQL_HOST = None
    MYSQL_USER = None
    MYSQL_PASSWORD = None
    MYSQL_DATABASE = "linkedin"
    
    DELAY_BETWEEN_PAGES = (5, 10)
    DELAY_BETWEEN_JOBS = (2, 5)
    PAGE_LOAD_TIMEOUT = 60000
    JOBS_PER_PAGE = 25
    
    class Colors:
        CYAN = '\033[96m'
        GREEN = '\033[92m'
        YELLOW = '\033[93m'
        RED = '\033[91m'
        BOLD = '\033[1m'
        END = '\033[0m'


# ============================================================================
# LOGGER
# ============================================================================
class Logger:
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
    def warning(text):
        print(f"{Config.Colors.YELLOW}⚠{Config.Colors.END} {text}")
    
    @staticmethod
    def progress(text):
        print(f"{Config.Colors.CYAN}▶{Config.Colors.END} {text}")
    
    @staticmethod
    def data(label, value):
        print(f"{Config.Colors.CYAN}{label}:{Config.Colors.END} {Config.Colors.BOLD}{value}{Config.Colors.END}")


# ============================================================================
# DATABASE MANAGER
# ============================================================================
class DatabaseManager:
    def __init__(self, config):
        self.config = config
        self.logger = Logger()
    
    def get_connection(self):
        return mysql.connector.connect(
            host=self.config.MYSQL_HOST,
            user=self.config.MYSQL_USER,
            password=self.config.MYSQL_PASSWORD,
            database=self.config.MYSQL_DATABASE
        )

    
    def setup(self):
        """Create jobs table with foreign key to company"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS jobs (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    company_id INT,
                    job_title VARCHAR(500),
                    job_url VARCHAR(1000),
                    job_location VARCHAR(255),
                    job_type VARCHAR(100),
                    job_posted_date VARCHAR(100),
                    job_applicants VARCHAR(100),
                    job_description LONGTEXT,
                    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (company_id) REFERENCES company(id) ON DELETE CASCADE,
                    UNIQUE KEY unique_job_url (job_url(500)),
                    INDEX idx_company (company_id),
                    INDEX idx_title (job_title(255))
                )
            ''')
            
            conn.commit()
            cursor.close()
            conn.close()
            self.logger.success("Table 'jobs' ready")
        except Exception as e:
            self.logger.error(f"Database setup error: {e}")
            sys.exit(1)
    
    def get_company_by_url(self, company_url):
        """Get company ID by URL with flexible matching"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor(dictionary=True)
            
            # Try exact match first
            cursor.execute("SELECT id, company_name, company_url FROM company WHERE company_url = %s", (company_url,))
            company = cursor.fetchone()
            
            # If not found, try without trailing slash
            if not company:
                url_without_slash = company_url.rstrip('/')
                cursor.execute("SELECT id, company_name, company_url FROM company WHERE company_url = %s OR company_url = %s", 
                             (url_without_slash, url_without_slash + '/'))
                company = cursor.fetchone()
            
            # If still not found, try LIKE match on company name
            if not company:
                company_name = company_url.split('/company/')[-1].rstrip('/').replace('-', ' ')
                cursor.execute("SELECT id, company_name, company_url FROM company WHERE company_url LIKE %s", 
                             (f"%/company/{company_name.split('/')[0]}%",))
                company = cursor.fetchone()
            
            cursor.close()
            conn.close()
            return company
        except Exception as e:
            self.logger.error(f"Error fetching company: {e}")
            return None
    
    def get_company_by_name(self, company_name):
        """Get company by name with flexible matching"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor(dictionary=True)
            
            # Try exact match
            cursor.execute("SELECT id, company_name, company_url FROM company WHERE company_name = %s", (company_name,))
            company = cursor.fetchone()
            
            # Try case-insensitive match
            if not company:
                cursor.execute("SELECT id, company_name, company_url FROM company WHERE LOWER(company_name) = LOWER(%s)", (company_name,))
                company = cursor.fetchone()
            
            # Try LIKE match
            if not company:
                cursor.execute("SELECT id, company_name, company_url FROM company WHERE company_name LIKE %s", (f"%{company_name}%",))
                company = cursor.fetchone()
            
            cursor.close()
            conn.close()
            return company
        except Exception as e:
            self.logger.error(f"Error fetching company by name: {e}")
            return None
    
    def get_all_companies(self):
        """Get all companies from database"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT id, company_name, company_url FROM company ORDER BY company_name")
            companies = cursor.fetchall()
            cursor.close()
            conn.close()
            return companies
        except Exception as e:
            self.logger.error(f"Error fetching companies: {e}")
            return []
    
    def job_exists(self, job_url):
        """Check if job URL exists"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM jobs WHERE job_url = %s", (job_url,))
            exists = cursor.fetchone() is not None
            cursor.close()
            conn.close()
            return exists
        except:
            return False
    
    def save_job(self, job, company_name=None):
        """Save job to database with validation"""
        try:
            if self.job_exists(job.get('url')):
                return False, "exists"
            
            # Validate required fields
            if not job.get('company_id'):
                return False, "missing company_id"
            
            if not job.get('title'):
                return False, "missing title"
            
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO jobs (company_id, job_title, job_url, job_location, job_type, 
                                 job_posted_date, job_applicants, job_description)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ''', (
                job.get('company_id'),
                job.get('title'),
                job.get('url'),
                job.get('location'),
                job.get('type'),
                job.get('posted_date'),
                job.get('applicants'),
                job.get('description')
            ))
            
            conn.commit()
            cursor.close()
            conn.close()
            
            company_info = f" [{company_name}]" if company_name else ""
            return True, f"saved{company_info}"
        except Exception as e:
            self.logger.error(f"Error saving job: {e}")
            return False, str(e)


# ============================================================================
# JOBS SCRAPER
# ============================================================================
class JobsScraper:
    def __init__(self, config, db_manager):
        self.config = config
        self.db = db_manager
        self.logger = Logger()
        self.stop_scraping = False
        self.request_count = 0
        self.start_time = time.time()
    
    def check_network(self):
        try:
            urllib.request.urlopen('https://www.google.com', timeout=5)
            return True
        except:
            return False
    
    def clean_html(self, html_content):
        """Clean and unescape HTML"""
        if not html_content:
            return None
        return html.unescape(html_content)
    
    async def simulate_human(self, page):
        """Simulate human behavior"""
        try:
            await page.evaluate(f"window.scrollBy(0, {random.randint(300, 800)})")
            await asyncio.sleep(random.uniform(0.5, 1.5))
            
            viewport = page.viewport_size
            if viewport:
                await page.mouse.move(
                    random.randint(100, viewport['width'] - 100),
                    random.randint(100, viewport['height'] - 100)
                )
        except:
            pass
    
    def rate_limit_check(self):
        """Rate limiting"""
        self.request_count += 1
        elapsed = time.time() - self.start_time
        if elapsed > 0:
            rpm = (self.request_count / elapsed) * 60
            if rpm > 30:
                extra_delay = random.uniform(2, 5)
                self.logger.warning(f"Rate limit: {rpm:.1f} req/min. Adding {extra_delay:.1f}s delay")
                return extra_delay
        return 0
    
    async def load_session(self, page):
        """Load saved session"""
        session_file = "linkedin_session.json"
        if not os.path.exists(session_file):
            self.logger.error("No session file found! Run scrape_companies.py first to login.")
            return False
        
        try:
            with open(session_file, 'r') as f:
                session_data = json.load(f)
            
            await page.context.add_cookies(session_data['cookies'])
            
            for origin_data in session_data.get('origins', []):
                try:
                    await page.goto(origin_data['origin'], timeout=self.config.PAGE_LOAD_TIMEOUT, wait_until="domcontentloaded")
                    for item in origin_data.get('localStorage', []):
                        await page.evaluate(f"localStorage.setItem('{item['name']}', '{item['value']}')")
                except:
                    pass
            
            await page.goto("https://www.linkedin.com/feed", timeout=self.config.PAGE_LOAD_TIMEOUT, wait_until="domcontentloaded")
            await asyncio.sleep(2)
            self.logger.success("Session loaded")
            return True
        except Exception as e:
            self.logger.error(f"Session load failed: {e}")
            return False
    
    async def extract_company_linkedin_id(self, page, company_url, max_retries=3):
        """Extract numeric LinkedIn company ID with retry logic"""
        for attempt in range(max_retries):
            try:
                self.logger.progress(f"Extracting LinkedIn ID (attempt {attempt + 1}/{max_retries})...")
                await page.goto(company_url, timeout=self.config.PAGE_LOAD_TIMEOUT, wait_until="domcontentloaded")
                await asyncio.sleep(3)
                
                content = await page.content()
                
                patterns = [
                    r'"company":"urn:li:fsd_company:(\d+)"',
                    r'"entityUrn":"urn:li:fs_normalized_company:(\d+)"',
                    r'"trackingInfo".*?"companyId":(\d+)',
                    r'data-company-id="(\d+)"',
                    r'"companyId":(\d+)',
                ]
                
                for pattern in patterns:
                    match = re.search(pattern, content)
                    if match:
                        company_id = match.group(1)
                        self.logger.success(f"LinkedIn ID: {company_id}")
                        return company_id
                
                try:
                    jobs_link = await page.locator('a[href*="f_C="]').first.get_attribute('href', timeout=5000)
                    if jobs_link:
                        match = re.search(r'f_C=(\d+)', jobs_link)
                        if match:
                            company_id = match.group(1)
                            self.logger.success(f"LinkedIn ID: {company_id}")
                            return company_id
                except:
                    pass
                
                if attempt < max_retries - 1:
                    self.logger.warning(f"Retry in 5s...")
                    await asyncio.sleep(5)
                    
            except Exception as e:
                self.logger.error(f"Attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(5)
        
        self.logger.error("Failed to extract LinkedIn company ID after all retries")
        return None
    
    async def scrape_job_urls_from_page(self, page, company_id, start=0):
        """Extract job URLs from jobs search page"""
        try:
            job_urls = []
            
            # Wait for job cards
            await page.wait_for_selector('.job-card-container', timeout=10000)
            await asyncio.sleep(2)
            
            # Extract job URLs
            job_cards = await page.locator('.job-card-container').all()
            
            for card in job_cards:
                try:
                    link = await card.locator('a[href*="/jobs/view/"]').first.get_attribute('href')
                    if link:
                        # Clean URL
                        job_id = re.search(r'/jobs/view/(\d+)', link)
                        if job_id:
                            job_url = f"https://www.linkedin.com/jobs/view/{job_id.group(1)}/"
                            job_urls.append(job_url)
                except:
                    continue
            
            return job_urls
        except Exception as e:
            self.logger.error(f"Error extracting job URLs: {e}")
            return []
    
    async def scrape_job_details(self, page, job_url, company_id):
        """Visit job page and extract full HTML details with dynamic selectors"""
        try:
            extra_delay = self.rate_limit_check()
            if extra_delay > 0:
                await asyncio.sleep(extra_delay)
            
            await page.goto(job_url, timeout=self.config.PAGE_LOAD_TIMEOUT, wait_until="domcontentloaded")
            await asyncio.sleep(random.uniform(4, 6))
            
            # Scroll to load lazy content
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
            await asyncio.sleep(2)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(2)
            
            await self.simulate_human(page)
            
            job = {'url': job_url, 'company_id': company_id}
            
            # Extract job title - it's in a <p> tag with specific classes, not h1
            try:
                # Method 1: Find p tag with class c9683ce4 (job title class)
                p_elements = await page.locator('p').all()
                for p in p_elements:
                    class_attr = await p.get_attribute('class')
                    if class_attr and 'c9683ce4' in class_attr:
                        text = await p.text_content()
                        if text and 10 < len(text.strip()) < 200:
                            job['title'] = html.unescape(text.strip())
                            break
                
                # Method 2: Find p inside div with data-display-contents
                if not job.get('title'):
                    title_elem = await page.locator('div[data-display-contents="true"] > p').first
                    text = await title_elem.text_content(timeout=5000)
                    if text and 10 < len(text.strip()) < 200:
                        job['title'] = html.unescape(text.strip())
            except Exception as e:
                self.logger.warning(f"Title extraction error: {e}")
            
            # Extract all text from paragraphs and spans for metadata
            try:
                all_text_elements = await page.locator('p, span').all()
                for elem in all_text_elements[:50]:
                    try:
                        text = await elem.text_content()
                        if not text:
                            continue
                        text = text.strip()
                        
                        # Skip very short or very long text
                        if len(text) < 3 or len(text) > 300:
                            continue
                        
                        # Location: has comma and country/city names, not a date
                        if not job.get('location'):
                            if (',' in text and any(country in text for country in ['Morocco', 'France', 'Germany', 'USA', 'UK', 'Spain', 'Italy'])):
                                if not any(word in text for word in ['ago', 'Vor', 'day', 'week', 'month', 'applicant', 'follower']):
                                    job['location'] = html.unescape(text)
                        
                        # Posted date: contains time indicators
                        if not job.get('posted_date'):
                            if any(word in text for word in ['ago', 'Vor', 'day', 'week', 'month']) and len(text) < 50:
                                job['posted_date'] = html.unescape(text)
                        
                        # Applicants: contains number + applicant/people
                        if not job.get('applicants'):
                            if re.search(r'\d+.*(?:applicant|people|Personen|Kandidat)', text, re.IGNORECASE):
                                job['applicants'] = html.unescape(text)
                    except:
                        continue
            except Exception as e:
                self.logger.warning(f"Metadata extraction error: {e}")
            
            # Extract job type from buttons
            try:
                buttons = await page.locator('button, span').all()
                types = []
                job_type_keywords = ['Vollzeit', 'Full-time', 'Teilzeit', 'Part-time', 'Remote', 'Vor Ort', 'On-site', 'Hybrid', 'Contract', 'Internship', 'Freelance']
                
                for btn in buttons[:50]:
                    try:
                        text = await btn.text_content()
                        if text:
                            text = text.strip()
                            if text in job_type_keywords and text not in types:
                                types.append(text)
                                if len(types) >= 3:
                                    break
                    except:
                        continue
                
                if types:
                    job['type'] = ' • '.join(types)
            except Exception as e:
                self.logger.warning(f"Job type extraction error: {e}")
            
            # Extract job description HTML - wait for lazy load
            try:
                await page.wait_for_selector('span[data-testid="expandable-text-box"]', timeout=10000)
                desc_html = await page.locator('span[data-testid="expandable-text-box"]').first.inner_html()
                if desc_html and len(desc_html) > 50:
                    job['description'] = self.clean_html(desc_html)
            except Exception as e:
                self.logger.warning(f"Description extraction error: {e}")
            
            return job
            
        except Exception as e:
            self.logger.error(f"Error scraping job {job_url}: {e}")
            return {'url': job_url, 'company_id': company_id, 'title': 'Error'}
    
    async def run(self, company_url):
        """Main scraping function"""
        self.logger.header("LINKEDIN JOBS SCRAPER")
        
        if not self.check_network():
            self.logger.error("No internet connection!")
            return
        
        # Normalize company URL
        company_url = re.sub(r'/(jobs|about|posts|life|people)/?.*$', '/', company_url)
        if not company_url.endswith('/'):
            company_url += '/'
        
        # Get company from database
        company = self.db.get_company_by_url(company_url)
        if not company:
            self.logger.error(f"Company not found: {company_url}")
            self.logger.warning("Run scrape_companies.py first to add companies")
            return
        
        company_id = company['id']
        company_name = company.get('company_name') or 'Unknown'
        
        if not company_name or company_name == 'None':
            self.logger.warning(f"Company name is NULL for ID {company_id}, skipping...")
            return
        
        self.logger.success(f"Company: {company_name} (DB ID: {company_id})")
        
        all_jobs = []
        saved_count = 0
        skipped_count = 0
        start_time = time.time()
        
        try:
            async with async_playwright() as p:
                self.logger.progress("Launching browser...")
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                
                if not await self.load_session(page):
                    await browser.close()
                    return
                
                company_linkedin_id = await self.extract_company_linkedin_id(page, company_url)
                if not company_linkedin_id:
                    self.logger.error(f"Skipping {company_name} - could not extract LinkedIn ID")
                    await browser.close()
                    return
                
                page_num = 0
                
                while not self.stop_scraping:
                    start = page_num * self.config.JOBS_PER_PAGE
                    
                    self.logger.progress(f"Page {page_num + 1} (jobs {start}-{start + 25})")
                    
                    try:
                        jobs_url = f"https://www.linkedin.com/jobs/search/?f_C={company_linkedin_id}&geoId=92000000&start={start}"
                        
                        await page.goto(jobs_url, timeout=self.config.PAGE_LOAD_TIMEOUT, wait_until="domcontentloaded")
                        await self.simulate_human(page)
                        
                        job_urls = await self.scrape_job_urls_from_page(page, company_id, start)
                        
                        if not job_urls:
                            self.logger.warning("No more jobs found")
                            break
                        
                        self.logger.success(f"Found {len(job_urls)} job URLs")
                        
                        # Scrape each job
                        for idx, job_url in enumerate(job_urls, 1):
                            if self.stop_scraping:
                                break
                            
                            if self.db.job_exists(job_url):
                                skipped_count += 1
                                self.logger.warning(f"[{idx}/{len(job_urls)}] Skipped (exists)")
                                continue
                            
                            self.logger.progress(f"[{idx}/{len(job_urls)}] {job_url}")
                            
                            try:
                                job = await self.scrape_job_details(page, job_url, company_id)
                                all_jobs.append(job)
                                
                                success, status = self.db.save_job(job, company_name)
                                if success:
                                    saved_count += 1
                                    self.logger.success(f"✓ {job.get('title', 'Unknown')[:50]} → {company_name}")
                                else:
                                    skipped_count += 1
                                    self.logger.warning(f"✗ {status}")
                                
                                delay = random.uniform(*self.config.DELAY_BETWEEN_JOBS)
                                await asyncio.sleep(delay)
                            except Exception as e:
                                self.logger.error(f"Job scraping failed: {e}")
                        
                        page_num += 1
                        delay = random.uniform(*self.config.DELAY_BETWEEN_PAGES)
                        self.logger.progress(f"Waiting {delay:.1f}s before next page...")
                        await asyncio.sleep(delay)
                        
                    except Exception as e:
                        self.logger.error(f"Page {page_num + 1} error: {e}")
                        self.logger.warning("Continuing to next page...")
                        page_num += 1
                        await asyncio.sleep(5)
                
                await browser.close()
                
        except Exception as e:
            self.logger.error(f"Critical error for {company_name}: {e}")
            self.logger.warning("Continuing to next company...")
        
        # Summary
        elapsed = time.time() - start_time
        self.logger.header("SCRAPING COMPLETE")
        self.logger.data("Company", company_name)
        self.logger.data("Jobs found", len(all_jobs))
        self.logger.data("Saved", saved_count)
        self.logger.data("Skipped", skipped_count)
        self.logger.data("Time", f"{elapsed:.1f}s")


# ============================================================================
# MAIN
# ============================================================================
scraper_instance = None

def signal_handler(sig, frame):
    global scraper_instance
    Logger.warning("\n\n⚠ Ctrl+C detected! Stopping...")
    if scraper_instance:
        scraper_instance.stop_scraping = True

async def main():
    global scraper_instance
    
    config = Config()
    logger = Logger()
    
    signal.signal(signal.SIGINT, signal_handler)
    
    logger.header("LINKEDIN JOBS SCRAPER")
    
    # MySQL credentials
    config.MYSQL_HOST = input(f"{Config.Colors.CYAN}MySQL Host (default: localhost): {Config.Colors.END}").strip() or "localhost"
    config.MYSQL_USER = input(f"{Config.Colors.CYAN}MySQL User (default: root): {Config.Colors.END}").strip() or "root"
    config.MYSQL_PASSWORD = getpass.getpass(f"{Config.Colors.CYAN}MySQL Password: {Config.Colors.END}")
    
    # Setup database
    db = DatabaseManager(config)
    db.setup()
    
    # Ask user: use DB companies or manual URL
    logger.progress("Choose option:")
    print(f"{Config.Colors.CYAN}1.{Config.Colors.END} Use company from database (by number)")
    print(f"{Config.Colors.CYAN}2.{Config.Colors.END} Search company by name")
    print(f"{Config.Colors.CYAN}3.{Config.Colors.END} Enter company URL manually")
    
    choice = input(f"{Config.Colors.CYAN}Choice (1/2/3): {Config.Colors.END}").strip()
    
    company_url = None
    
    if choice == '1':
        # Show companies from database
        companies = db.get_all_companies()
        
        if not companies:
            logger.error("No companies in database!")
            logger.warning("Run scrape_companies.py first to add companies")
            return
        
        logger.success(f"Found {len(companies)} companies in database:")
        print()
        
        for idx, company in enumerate(companies, 1):
            print(f"{Config.Colors.CYAN}{idx}.{Config.Colors.END} {company['company_name']} ({company['company_url']})")
        
        print(f"{Config.Colors.CYAN}0.{Config.Colors.END} Scrape ALL companies")
        print()
        
        company_choice = input(f"{Config.Colors.CYAN}Select company number (or 0 for all): {Config.Colors.END}").strip()
        
        try:
            company_idx = int(company_choice)
            
            if company_idx == 0:
                # Scrape ALL companies
                logger.success(f"Scraping jobs for ALL {len(companies)} companies")
                logger.warning("Press Ctrl+C to stop")
                
                scraper = JobsScraper(config, db)
                scraper_instance = scraper
                
                for idx, company in enumerate(companies, 1):
                    if scraper.stop_scraping:
                        break
                    
                    logger.header(f"Company {idx}/{len(companies)}: {company['company_name']}")
                    await scraper.run(company['company_url'])
                    
                    if idx < len(companies):
                        delay = random.uniform(10, 20)
                        logger.progress(f"Waiting {delay:.1f}s before next company...")
                        await asyncio.sleep(delay)
                
                logger.header("ALL COMPANIES COMPLETE")
                return
            
            elif 1 <= company_idx <= len(companies):
                company_url = companies[company_idx - 1]['company_url']
                logger.success(f"Selected: {companies[company_idx - 1]['company_name']}")
                
                # Start scraping for single company
                scraper = JobsScraper(config, db)
                scraper_instance = scraper
                await scraper.run(company_url)
            else:
                logger.error("Invalid company number!")
                return
        except ValueError:
            logger.error("Invalid input!")
            return
    
    elif choice == '2':
        # Search by company name
        company_name = input(f"{Config.Colors.CYAN}Enter company name: {Config.Colors.END}").strip()
        
        if not company_name:
            logger.error("Company name required!")
            return
        
        company = db.get_company_by_name(company_name)
        
        if not company:
            logger.error(f"Company '{company_name}' not found in database!")
            logger.warning("Run scrape_companies.py first to add this company")
            return
        
        logger.success(f"Found: {company['company_name']}")
        logger.data("URL", company['company_url'])
        
        # Start scraping
        scraper = JobsScraper(config, db)
        scraper_instance = scraper
        await scraper.run(company['company_url'])
    
    elif choice == '3':
        # Manual URL entry
        logger.progress("Enter company LinkedIn URL:")
        company_url = input(f"{Config.Colors.CYAN}URL: {Config.Colors.END}").strip()
        
        if not company_url:
            logger.error("Company URL required!")
            return
        
        # Validate URL format
        if '/company/' not in company_url:
            logger.error("Invalid LinkedIn company URL format!")
            logger.warning("Expected format: https://www.linkedin.com/company/company-name/")
            return
        
        # Normalize URL - remove /jobs/, /about/, /posts/, etc.
        company_url = re.sub(r'/(jobs|about|posts|life|people)/?.*$', '/', company_url)
        if not company_url.endswith('/'):
            company_url += '/'
        
        logger.progress(f"Normalized URL: {company_url}")
        
        # Check if company exists in database
        company = db.get_company_by_url(company_url)
        if not company:
            logger.warning(f"Company not found in database: {company_url}")
            logger.progress("Do you want to scrape this company first? (y/n)")
            scrape_company = input(f"{Config.Colors.CYAN}Choice: {Config.Colors.END}").strip().lower()
            
            if scrape_company == 'y':
                logger.progress("Running single company scraper...")
                try:
                    import subprocess
                    result = subprocess.run(
                        ['python3', 'scrape_single_company.py', company_url, 
                         config.MYSQL_HOST or 'localhost', 
                         config.MYSQL_USER or 'root', 
                         config.MYSQL_PASSWORD],
                        capture_output=True,
                        text=True
                    )
                    
                    if result.returncode == 0:
                        company = db.get_company_by_url(company_url)
                        if company:
                            logger.success(f"Company added: {company['company_name']}")
                        else:
                            logger.error("Company scraping failed")
                            return
                    else:
                        logger.error("Company scraping failed")
                        if result.stderr:
                            logger.warning(f"Error: {result.stderr}")
                        return
                except Exception as e:
                    logger.error(f"Failed to run company scraper: {e}")
                    return
            else:
                logger.warning("Please run scrape_companies.py first to add this company")
                return
        else:
            logger.success(f"Company found: {company['company_name']}")
        
        # Start scraping for single company
        scraper = JobsScraper(config, db)
        scraper_instance = scraper
        await scraper.run(company_url)
    
    else:
        logger.error("Invalid choice!")
        return

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        Logger.warning("\nExiting...")
        sys.exit(0)
