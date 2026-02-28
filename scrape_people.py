#!/usr/bin/env python3
import asyncio, json, os, random, re, sys, getpass
from playwright.async_api import async_playwright
import mysql.connector

class Config:
    MYSQL_HOST = MYSQL_USER = MYSQL_PASSWORD = None
    MYSQL_DATABASE = "linkedin"
    
class Logger:
    @staticmethod
    def success(t): print(f"\033[92m✓\033[0m {t}")
    @staticmethod
    def error(t): print(f"\033[91m✗\033[0m {t}")
    @staticmethod
    def progress(t): print(f"\033[96m▶\033[0m {t}")

class DB:
    def __init__(self, c):
        self.c = c
        self.l = Logger()
    
    def conn(self):
        return mysql.connector.connect(host=self.c.MYSQL_HOST, user=self.c.MYSQL_USER, password=self.c.MYSQL_PASSWORD, database=self.c.MYSQL_DATABASE)
    
    def setup(self):
        cn = self.conn()
        cu = cn.cursor()
        cu.execute('''CREATE TABLE IF NOT EXISTS people (id INT AUTO_INCREMENT PRIMARY KEY, company_id INT, person_name VARCHAR(255), person_url VARCHAR(500), person_title VARCHAR(500), person_location VARCHAR(255), person_connections VARCHAR(100), current_company VARCHAR(255), education VARCHAR(500), experience TEXT, scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (company_id) REFERENCES company(id) ON DELETE CASCADE, UNIQUE KEY unique_person_url (person_url(500)), INDEX idx_company (company_id))''')
        cn.commit()
        cu.close()
        cn.close()
        self.l.success("Table ready")
    
    def get_company(self, url):
        cn = self.conn()
        cu = cn.cursor(dictionary=True)
        cu.execute("SELECT id, company_name, company_url FROM company WHERE company_url LIKE %s", (f"%{url.split('/company/')[-1].split('/')[0]}%",))
        r = cu.fetchone()
        cu.close()
        cn.close()
        return r
    
    def exists(self, url):
        try:
            cn = self.conn()
            cu = cn.cursor()
            cu.execute("SELECT id FROM people WHERE person_url = %s", (url,))
            e = cu.fetchone() is not None
            cu.close()
            cn.close()
            return e
        except:
            return False
    
    def save(self, p, cn):
        if self.exists(p.get('url')): return False, "exists"
        c = self.conn()
        cu = c.cursor()
        cu.execute('INSERT INTO people (company_id, person_name, person_url, person_title, person_location, person_connections, current_company, education, experience) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)', (p.get('company_id'), p.get('name'), p.get('url'), p.get('title'), p.get('location'), p.get('connections'), p.get('current_company'), p.get('education'), p.get('experience')))
        c.commit()
        cu.close()
        c.close()
        return True, f"saved [{cn}]"

class Scraper:
    def __init__(self, c, d):
        self.c = c
        self.d = d
        self.l = Logger()
    
    async def load_session(self, p):
        if not os.path.exists("linkedin_session.json"):
            self.l.error("No session!")
            return False
        with open("linkedin_session.json") as f:
            s = json.load(f)
        await p.context.add_cookies(s['cookies'])
        await p.goto("https://www.linkedin.com/feed", timeout=60000, wait_until="domcontentloaded")
        await asyncio.sleep(2)
        self.l.success("Session loaded")
        return True
    
    async def get_urls(self, p):
        await asyncio.sleep(2)
        urls = []
        for sel in ['li.org-people-profile-card__profile-card-spacing', 'li[class*="org-people"]']:
            try:
                cards = await p.locator(sel).all()
                if cards:
                    for c in cards:
                        try:
                            link = await c.locator('a[href*="/in/"]').first.get_attribute('href')
                            if link and '/in/' in link:
                                u = link.split('?')[0]
                                if not u.endswith('/'): u += '/'
                                urls.append(u)
                        except:
                            pass
                    break
            except:
                pass
        return urls
    
    async def scrape_person(self, p, url, cid):
        try:
            await p.goto(url, timeout=60000, wait_until="domcontentloaded")
            await asyncio.sleep(random.uniform(4, 6))
            await p.evaluate("window.scrollTo(0, 500)")
            await asyncio.sleep(1)
            
            person = {'url': url, 'company_id': cid}
            
            # Name - h2 with specific text pattern
            try:
                h2s = await p.locator('h2').all()
                for h in h2s:
                    t = await h.text_content()
                    if t:
                        t = t.strip()
                        if 5 < len(t) < 100 and 'Erfahrung' not in t and 'Ausbildung' not in t and 'notification' not in t.lower() and 'About' not in t:
                            person['name'] = t
                            break
            except:
                pass
            
            # Title - first p tag with class containing job title
            try:
                ps = await p.locator('p').all()
                for pt in ps[:20]:
                    t = await pt.text_content()
                    if t:
                        t = t.strip()
                        if 10 < len(t) < 300 and ' at ' in t or ' · ' in t or 'Engineer' in t or 'Manager' in t or 'Developer' in t:
                            if 'From ' not in t and 'notification' not in t.lower() and 'Kontakte' not in t:
                                person['title'] = t
                                break
            except:
                pass
            
            # Location - p tag with comma and country/city
            try:
                ps = await p.locator('p').all()
                for pt in ps[:30]:
                    t = await pt.text_content()
                    if t and ',' in t:
                        t = t.strip()
                        if any(x in t for x in ['Morocco', 'Marokko', 'France', 'Paris', 'Casablanca', 'Rabat']) and 'Kontakte' not in t:
                            person['location'] = t
                            break
            except:
                pass
            
            # Connections - look for text with 'Kontakte' or 'connections'
            try:
                ps = await p.locator('p, span').all()
                for pt in ps[:40]:
                    t = await pt.text_content()
                    if t and ('Kontakte' in t or 'connection' in t.lower()):
                        person['connections'] = t.strip()
                        break
            except:
                pass
            
            # Education - section with h2 'Ausbildung' or 'Education'
            try:
                edu_section = await p.locator('section:has(h2:has-text("Ausbildung")), section:has(h2:has-text("Education"))').first
                edu_ps = await edu_section.locator('p').all()
                edu_texts = []
                for pt in edu_ps[:10]:
                    t = await pt.text_content()
                    if t:
                        t = t.strip()
                        if 5 < len(t) < 300 and 'Ausbildung' not in t and 'Education' not in t:
                            edu_texts.append(t)
                if edu_texts:
                    person['education'] = ' | '.join(edu_texts[:3])
            except:
                pass
            
            # Experience - section with h2 'Erfahrung' or 'Experience'
            try:
                exp_section = await p.locator('section:has(h2:has-text("Erfahrung")), section:has(h2:has-text("Experience"))').first
                exp_ps = await exp_section.locator('p').all()
                exp_texts = []
                for pt in exp_ps[:20]:
                    t = await pt.text_content()
                    if t:
                        t = t.strip()
                        if 5 < len(t) < 400 and 'Erfahrung' not in t and 'Experience' not in t:
                            exp_texts.append(t)
                if exp_texts:
                    person['experience'] = ' | '.join(exp_texts[:5])
            except:
                pass
            
            return person
        except Exception as e:
            self.l.error(f"Error: {e}")
            return {'url': url, 'company_id': cid}
    
    async def run(self, curl):
        curl = re.sub(r'/(jobs|about|posts|life|people)/?.*$', '/', curl)
        if not curl.endswith('/'): curl += '/'
        
        comp = self.d.get_company(curl)
        if not comp:
            self.l.error("Company not found")
            return
        
        cid = comp['id']
        cname = comp.get('company_name') or 'Unknown'
        
        if not cname or cname == 'None':
            self.l.error(f"NULL company name for ID {cid}")
            return
        
        self.l.success(f"Company: {cname} (ID: {cid})")
        
        saved = skipped = 0
        
        async with async_playwright() as pw:
            self.l.progress("Launching browser...")
            br = await pw.chromium.launch(headless=True)
            pg = await br.new_page()
            
            if not await self.load_session(pg):
                await br.close()
                return
            
            pn = 0
            
            while True:
                self.l.progress(f"Page {pn + 1}")
                
                try:
                    purl = f"{curl}people/"
                    
                    if pn == 0:
                        await pg.goto(purl, timeout=60000, wait_until="domcontentloaded")
                        await asyncio.sleep(4)
                    else:
                        try:
                            btn = pg.locator('button.scaffold-finite-scroll__load-button:has-text("Weitere Ergebnisse"), button.scaffold-finite-scroll__load-button:has-text("Show more")')
                            if await btn.count() > 0:
                                await btn.first.scroll_into_view_if_needed()
                                await asyncio.sleep(2)
                                await btn.first.click()
                                await asyncio.sleep(5)
                            else:
                                self.l.progress("No more pages")
                                break
                        except:
                            self.l.progress("No more pages")
                            break
                    
                    purls = await self.get_urls(pg)
                    
                    if not purls:
                        self.l.progress("No people found")
                        break
                    
                    self.l.success(f"Found {len(purls)} people")
                    
                    for i, purl in enumerate(purls, 1):
                        if self.d.exists(purl):
                            skipped += 1
                            self.l.progress(f"[{i}/{len(purls)}] Skipped")
                            continue
                        
                        self.l.progress(f"[{i}/{len(purls)}] {purl}")
                        
                        try:
                            person = await self.scrape_person(pg, purl, cid)
                            
                            suc, st = self.d.save(person, cname)
                            if suc:
                                saved += 1
                                self.l.success(f"✓ {person.get('name', 'Unknown')[:50]}")
                            else:
                                skipped += 1
                            
                            await asyncio.sleep(random.uniform(1, 3))
                        except Exception as e:
                            self.l.error(f"Failed: {e}")
                    
                    pn += 1
                    await asyncio.sleep(random.uniform(3, 6))
                    
                except Exception as e:
                    self.l.error(f"Page error: {e}")
                    break
            
            await br.close()
        
        print(f"\n\033[96m{'='*70}\033[0m")
        self.l.success(f"Company: {cname}")
        self.l.success(f"Saved: {saved}")
        self.l.success(f"Skipped: {skipped}")

async def main():
    c = Config()
    l = Logger()
    
    c.MYSQL_HOST = input("MySQL Host (localhost): ").strip() or "localhost"
    c.MYSQL_USER = input("MySQL User (root): ").strip() or "root"
    c.MYSQL_PASSWORD = getpass.getpass("MySQL Password: ")
    
    d = DB(c)
    d.setup()
    
    url = input("Company URL: ").strip()
    if not url:
        l.error("URL required!")
        return
    
    s = Scraper(c, d)
    await s.run(url)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(0)
