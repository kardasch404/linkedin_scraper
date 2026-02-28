#!/usr/bin/env python3
"""
LinkedIn Single Company Scraper - Minimal
Scrapes ONE company by URL and saves to database
"""
import asyncio
import json
import os
import random
import re
import html
import sys
import time
import getpass
from playwright.async_api import async_playwright
import mysql.connector


class Config:
    MYSQL_HOST = None
    MYSQL_USER = None
    MYSQL_PASSWORD = None
    MYSQL_DATABASE = "linkedin"
    PAGE_LOAD_TIMEOUT = 60000
    SESSION_FILE = "linkedin_session.json"


class Logger:
    @staticmethod
    def success(text):
        print(f"\033[92m✓\033[0m {text}")
    
    @staticmethod
    def error(text):
        print(f"\033[91m✗\033[0m {text}")
    
    @staticmethod
    def warning(text):
        print(f"\033[93m⚠\033[0m {text}")
    
    @staticmethod
    def progress(text):
        print(f"\033[96m▶\033[0m {text}")


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
    
    def company_exists(self, company_url):
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM company WHERE company_url = %s", (company_url,))
            exists = cursor.fetchone() is not None
            cursor.close()
            conn.close()
            return exists
        except:
            return False
    
    def save_company(self, company):
        try:
            if self.company_exists(company.get('url')):
                return False, "exists"
            
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO company (company_name, company_url, company_industry, 
                                   company_location, company_followers, company_about, company_jobs)
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
            return False, str(e)


class CompanyScraper:
    def __init__(self, config, db_manager):
        self.config = config
        self.db = db_manager
        self.logger = Logger()
    
    def clean_html(self, html_content):
        if not html_content:
            return None
        return html.unescape(html_content)
    
    async def load_session(self, context):
        if not os.path.exists(self.config.SESSION_FILE):
            return False
        
        try:
            with open(self.config.SESSION_FILE, 'r') as f:
                session_data = json.load(f)
            
            await context.add_cookies(session_data.get('cookies', []))
            
            for origin_data in session_data.get('origins', []):
                try:
                    page = await context.new_page()
                    await page.goto(origin_data['origin'])
                    for item in origin_data.get('localStorage', []):
                        await page.evaluate(f"localStorage.setItem('{item['name']}', '{item['value']}')")
                    await page.close()
                except:
                    pass
            
            return True
        except:
            return False
    
    async def save_session(self, context):
        try:
            cookies = await context.cookies()
            
            storage_state = await context.storage_state()
            
            session_data = {
                'cookies': cookies,
                'origins': storage_state.get('origins', [])
            }
            
            with open(self.config.SESSION_FILE, 'w') as f:
                json.dump(session_data, f, indent=2)
            
            return True
        except:
            return False
    
    async def login(self, page):
        self.logger.progress("LinkedIn Login")
        
        email = input("LinkedIn Email: ").strip()
        password = getpass.getpass("LinkedIn Password: ")
        
        await page.fill('input[name="session_key"]', email)
        await page.fill('input[name="session_password"]', password)
        await page.click('button[type="submit"]')
        
        await asyncio.sleep(5)
        
        # Check for PIN verification
        if '/checkpoint/challenge/' in page.url:
            self.logger.warning("Email PIN verification required!")
            pin = input("Enter PIN from email: ").strip()
            
            try:
                await page.fill('input[name="pin"]', pin)
                await page.click('button[type="submit"]')
                await asyncio.sleep(5)
            except:
                pass
        
        if 'feed' in page.url or 'mynetwork' in page.url:
            self.logger.success("Login successful!")
            return True
        else:
            self.logger.error("Login failed!")
            return False
    
    async def scrape_company(self, page, company_url):
        """Visit company /about/ page and extract all details"""
        try:
            about_url = f"{company_url.rstrip('/')}/about/"
            self.logger.progress(f"Scraping: {about_url}")
            
            await page.goto(about_url, timeout=self.config.PAGE_LOAD_TIMEOUT, wait_until='domcontentloaded')
            await asyncio.sleep(random.uniform(3, 5))
            
            company = {'url': company_url}
            
            # Extract company name
            try:
                selectors = ['h1.org-top-card-summary__title', 'h1[class*="org-top-card"]', '.org-top-card-summary__title']
                for selector in selectors:
                    try:
                        name_elem = await page.locator(selector).first.text_content(timeout=5000)
                        if name_elem:
                            company['name'] = name_elem.strip()
                            break
                    except:
                        continue
            except:
                pass
            
            # Extract industry, location, followers
            try:
                info_selectors = ['.org-top-card-summary-info-list__info-item', '.org-page-details__definition-text']
                for selector in info_selectors:
                    try:
                        info_items = await page.locator(selector).all()
                        if not info_items:
                            continue
                        
                        for item in info_items:
                            text = await item.text_content()
                            text = text.strip() if text else ''
                            if not text:
                                continue
                            
                            if 'follower' in text.lower() or 'abonné' in text.lower():
                                company['followers'] = text
                            elif ',' in text and not company.get('location'):
                                company['location'] = text
                            elif not company.get('industry') and 3 < len(text) < 100:
                                company['industry'] = text
                        
                        if company.get('industry'):
                            break
                    except:
                        continue
            except:
                pass
            
            # Extract about section with HTML
            try:
                about_selectors = ['section.org-about-module', 'section[class*="about"]', '.org-about-us-organization-description', 'p.break-words']
                for selector in about_selectors:
                    try:
                        about_section = await page.locator(selector).first.inner_html(timeout=5000)
                        if about_section:
                            company['about'] = html.unescape(about_section)
                            break
                    except:
                        continue
                
                if not company.get('about'):
                    try:
                        about_elem = await page.locator('p.break-words').first.inner_html(timeout=5000)
                        if about_elem:
                            company['about'] = f'<p>{html.unescape(about_elem)}</p>'
                    except:
                        pass
            except:
                pass
            
            # Extract jobs count
            try:
                jobs_selectors = ['a[href*="/jobs/"]', 'a[href*="/jobs"]', 'button[aria-label*="job"]']
                for selector in jobs_selectors:
                    try:
                        jobs_link = await page.locator(selector).first.text_content(timeout=5000)
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
            self.logger.error(f"Error scraping {company_url}: {e}")
            return {'url': company_url, 'name': 'Error', 'jobs': 0}
    
    async def run(self, company_url):
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=False)
                context = await browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
                )
                
                page = await context.new_page()
                page.set_default_timeout(self.config.PAGE_LOAD_TIMEOUT)
                
                # Try to load session
                session_loaded = await self.load_session(context)
                
                if session_loaded:
                    self.logger.success("Using saved session")
                    await page.goto('https://www.linkedin.com/feed/', timeout=self.config.PAGE_LOAD_TIMEOUT)
                    await asyncio.sleep(3)
                    
                    if '/login' in page.url or '/uas/login' in page.url:
                        self.logger.warning("Session expired, logging in...")
                        session_loaded = False
                
                if not session_loaded:
                    await page.goto('https://www.linkedin.com/login')
                    await asyncio.sleep(2)
                    
                    if not await self.login(page):
                        self.logger.error("Login failed!")
                        await browser.close()
                        return False
                    
                    await self.save_session(context)
                
                # Scrape company
                company = await self.scrape_company(page, company_url)
                
                if company.get('name'):
                    success, status = self.db.save_company(company)
                    if success:
                        self.logger.success(f"Saved: {company['name']}")
                        await browser.close()
                        return True
                    else:
                        self.logger.warning(f"Status: {status}")
                        await browser.close()
                        return status == "exists"
                else:
                    self.logger.error("Failed to scrape company")
                    await browser.close()
                    return False
                
        except Exception as e:
            self.logger.error(f"Error: {e}")
            return False


async def main():
    if len(sys.argv) < 2:
        print("Usage: python3 scrape_single_company.py <company_url> [mysql_host] [mysql_user] [mysql_password]")
        print("Example: python3 scrape_single_company.py https://www.linkedin.com/company/capgemini/")
        print("Example: python3 scrape_single_company.py https://www.linkedin.com/company/capgemini/ localhost root mypass")
        sys.exit(1)
    
    company_url = sys.argv[1].strip()
    
    # Normalize URL
    company_url = re.sub(r'/(jobs|about|posts|life|people)/?.*$', '/', company_url)
    if not company_url.endswith('/'):
        company_url += '/'
    
    config = Config()
    logger = Logger()
    
    # MySQL credentials from args or prompt
    if len(sys.argv) >= 5:
        config.MYSQL_HOST = sys.argv[2]
        config.MYSQL_USER = sys.argv[3]
        config.MYSQL_PASSWORD = sys.argv[4]
    else:
        config.MYSQL_HOST = input("MySQL Host (default: localhost): ").strip() or "localhost"
        config.MYSQL_USER = input("MySQL User (default: root): ").strip() or "root"
        config.MYSQL_PASSWORD = getpass.getpass("MySQL Password: ")
    
    db = DatabaseManager(config)
    scraper = CompanyScraper(config, db)
    
    success = await scraper.run(company_url)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
