#!/usr/bin/env python3
import asyncio
from playwright.async_api import async_playwright
import json
import os

async def test():
    # Check session file
    if not os.path.exists("linkedin_session.json"):
        print("❌ No linkedin_session.json found")
        return
    
    print("✓ Session file exists")
    
    # Test browser and session
    async with async_playwright() as pw:
        print("✓ Launching browser...")
        br = await pw.chromium.launch(headless=False)
        pg = await br.new_page()
        
        # Load session
        with open("linkedin_session.json") as f:
            s = json.load(f)
        await pg.context.add_cookies(s['cookies'])
        
        # Test LinkedIn access
        print("✓ Testing LinkedIn access...")
        await pg.goto("https://www.linkedin.com/feed", timeout=60000)
        await asyncio.sleep(3)
        
        title = await pg.title()
        print(f"✓ Page title: {title}")
        
        # Test company page
        print("✓ Testing company page...")
        await pg.goto("https://www.linkedin.com/company/capgemini/people/", timeout=60000)
        await asyncio.sleep(5)
        
        # Check for profile cards
        cards = await pg.locator('li.org-people-profile-card__profile-card-spacing').count()
        print(f"✓ Found {cards} profile cards")
        
        # Check for links
        links = await pg.locator('a[href*="/in/"]').count()
        print(f"✓ Found {links} profile links")
        
        if links > 0:
            first = await pg.locator('a[href*="/in/"]').first.get_attribute('href')
            print(f"✓ First profile: {first}")
        
        input("Press Enter to close...")
        await br.close()

if __name__ == "__main__":
    asyncio.run(test())
