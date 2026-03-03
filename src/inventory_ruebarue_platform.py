#!/usr/bin/env python3
"""
Complete RueBaRue Platform Inventory
Explore every section and document all available data
"""

import asyncio
import json
import os
import sys
import re
from datetime import datetime
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# Credentials
RUEBARUE_EMAIL = os.getenv("RUEBARUE_EMAIL", "")
RUEBARUE_PASSWORD = os.getenv("RUEBARUE_PASSWORD", "")
RUEBARUE_URL = "https://app.ruebarue.com/"

OUTPUT_DIR = "/home/admin/Fortress-Prime/data/ruebarue_inventory"
os.makedirs(OUTPUT_DIR, exist_ok=True)

inventory = {
    'extracted_at': datetime.now().isoformat(),
    'account': RUEBARUE_EMAIL,
    'sections': []
}

async def take_screenshot(page, name):
    """Take a screenshot"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(OUTPUT_DIR, f"{timestamp}_{name}.png")
    await page.screenshot(path=filepath, full_page=True)
    return filepath

async def save_html(page, name):
    """Save page HTML"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(OUTPUT_DIR, f"{timestamp}_{name}.html")
    html = await page.content()
    with open(filepath, 'w') as f:
        f.write(html)
    return filepath

async def login(page):
    """Login to RueBaRue"""
    if not RUEBARUE_EMAIL or not RUEBARUE_PASSWORD:
        raise RuntimeError("Missing RUEBARUE_EMAIL or RUEBARUE_PASSWORD environment variables.")
    print("🔐 Logging in...", flush=True)
    
    await page.goto(RUEBARUE_URL, wait_until="networkidle", timeout=30000)
    await asyncio.sleep(2)
    
    # Fill email
    email_input = await page.query_selector('input.uk-input:not([type="password"])')
    if email_input:
        await email_input.fill(RUEBARUE_EMAIL)
    
    # Fill password
    password_input = await page.query_selector('input[type="password"].uk-input')
    if password_input:
        await password_input.fill(RUEBARUE_PASSWORD)
    
    # Click login
    login_button = await page.query_selector('button:has-text("LOGIN")')
    if login_button:
        await login_button.click()
    
    await asyncio.sleep(5)
    
    if 'login' not in page.url.lower():
        print("✅ Login successful", flush=True)
        return True
    else:
        print("❌ Login failed", flush=True)
        return False

async def extract_record_count(page):
    """Try to extract record count from page"""
    try:
        # Look for pagination text like "1 - 20 of 168"
        pagination_text = await page.query_selector('.hms-total-pagination, [class*="pagination"], [class*="total"]')
        if pagination_text:
            text = (await pagination_text.inner_text()).strip()
            match = re.search(r'of\s+(\d+)', text, re.I)
            if match:
                return int(match.group(1))
            
            match = re.search(r'(\d+)\s+total', text, re.I)
            if match:
                return int(match.group(1))
        
        # Look for table rows
        rows = await page.query_selector_all('tbody tr, .list-item, [class*="card"]')
        if len(rows) > 0:
            return f"{len(rows)} visible"
        
    except:
        pass
    
    return "Unknown"

async def check_export_option(page):
    """Check if export option exists"""
    try:
        export_buttons = await page.query_selector_all('button:has-text("Export"), button:has-text("Download"), a:has-text("Export"), a:has-text("Download")')
        return len(export_buttons) > 0
    except:
        return False

async def explore_section(page, section_name, url_path):
    """Explore a specific section"""
    print(f"\n{'='*80}", flush=True)
    print(f"📂 EXPLORING: {section_name}", flush=True)
    print(f"{'='*80}", flush=True)
    
    section_data = {
        'name': section_name,
        'url': f"https://app.ruebarue.com{url_path}",
        'screenshot': None,
        'html': None,
        'record_count': None,
        'has_export': False,
        'subsections': [],
        'notes': []
    }
    
    try:
        # Navigate to section
        await page.goto(f"https://app.ruebarue.com{url_path}")
        await asyncio.sleep(3)
        
        section_data['url'] = page.url
        
        # Take screenshot
        screenshot = await take_screenshot(page, f"{section_name.replace(' ', '_').lower()}")
        section_data['screenshot'] = screenshot
        print(f"   📸 Screenshot: {screenshot}", flush=True)
        
        # Save HTML
        html = await save_html(page, f"{section_name.replace(' ', '_').lower()}")
        section_data['html'] = html
        
        # Get page title
        title = await page.title()
        print(f"   📄 Title: {title}", flush=True)
        print(f"   🔗 URL: {page.url}", flush=True)
        
        # Extract record count
        count = await extract_record_count(page)
        section_data['record_count'] = count
        print(f"   📊 Records: {count}", flush=True)
        
        # Check for export
        has_export = await check_export_option(page)
        section_data['has_export'] = has_export
        print(f"   📥 Export option: {'Yes' if has_export else 'No'}", flush=True)
        
        # Look for tabs or subsections
        tabs = await page.query_selector_all('[role="tab"], .uk-tab li a, .nav-tabs a')
        if tabs:
            print(f"   📑 Found {len(tabs)} tabs/subsections", flush=True)
            for tab in tabs[:10]:  # Limit to first 10 tabs
                try:
                    tab_text = (await tab.inner_text()).strip()
                    if tab_text:
                        print(f"      - {tab_text}", flush=True)
                        section_data['subsections'].append(tab_text)
                except:
                    pass
        
        # Get page content summary
        page_text = await page.inner_text('body')
        
        # Look for key indicators
        if 'no records' in page_text.lower() or 'no data' in page_text.lower():
            section_data['notes'].append('No records found')
        
        if 'survey' in page_text.lower():
            survey_matches = re.findall(r'(\d+)\s+survey', page_text.lower())
            if survey_matches:
                section_data['notes'].append(f"Contains {survey_matches[0]} surveys")
        
        # Look for tables
        tables = await page.query_selector_all('table')
        if tables:
            print(f"   📋 Tables found: {len(tables)}", flush=True)
            for i, table in enumerate(tables):
                headers = []
                header_cells = await table.query_selector_all('thead th')
                for cell in header_cells:
                    headers.append((await cell.inner_text()).strip())
                if headers:
                    print(f"      Table {i+1} columns: {', '.join(headers[:5])}", flush=True)
                    section_data['notes'].append(f"Table {i+1}: {', '.join(headers)}")
        
    except Exception as e:
        print(f"   ⚠️  Error exploring section: {e}", flush=True)
        section_data['notes'].append(f"Error: {str(e)}")
    
    return section_data

async def inventory_platform():
    """Main inventory function"""
    
    async with async_playwright() as p:
        print("="*80, flush=True)
        print("🏰 FORTRESS PRIME - Complete RueBaRue Platform Inventory", flush=True)
        print("="*80, flush=True)
        
        browser = await p.firefox.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1920, "height": 1080})
        
        try:
            # Login
            if not await login(page):
                print("❌ Login failed, aborting", flush=True)
                return
            
            # Take dashboard screenshot
            print(f"\n{'='*80}", flush=True)
            print("📸 DASHBOARD", flush=True)
            print(f"{'='*80}", flush=True)
            
            dashboard_screenshot = await take_screenshot(page, "dashboard")
            dashboard_html = await save_html(page, "dashboard")
            print(f"   Screenshot: {dashboard_screenshot}", flush=True)
            print(f"   URL: {page.url}", flush=True)
            
            # Define sections to explore
            sections = [
                # Main sections
                ("Messages", "/messages"),
                ("Guests", "/guests"),
                ("Contacts", "/contacts"),
                ("Orders", "/orders"),
                
                # Messaging submenu
                ("Scheduler", "/scheduler"),
                ("Extend Stays", "/extend-guest-stay"),
                ("Alerts", "/alerts"),
                ("Surveys", "/surveys"),
                ("Saved Responses", "/saved-responses"),
                ("Message Templates", "/message-templates"),
                
                # Operations submenu
                ("Operations Dashboard", "/operations"),
                ("Work Orders", "/work-orders"),
                ("Checklists", "/operations/checklists"),
                
                # Guest Guides submenu
                ("Master Home Guide", "/master-home-guide"),
                ("Home Guides", "/properties"),
                ("Extras Guide", "/extras"),
                ("Area Guides", "/areas"),
                ("Subscriptions", "/subscriptions"),
                
                # Settings/Management
                ("Units", "/units"),
                ("Macros", "/macros"),
                ("AI Chatbot FAQs", "/chatbot-faqs"),
                ("AI Chatbot Unanswered Questions", "/unanswered-questions"),
                ("Settings", "/settings"),
                ("Profile", "/profile"),
                ("Reports", "/reports"),
            ]
            
            # Explore each section
            for section_name, url_path in sections:
                section_data = await explore_section(page, section_name, url_path)
                inventory['sections'].append(section_data)
                
                # Small delay between sections
                await asyncio.sleep(2)
            
            # Save inventory
            inventory_file = os.path.join(OUTPUT_DIR, f"platform_inventory_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
            with open(inventory_file, 'w') as f:
                json.dump(inventory, f, indent=2)
            
            print(f"\n{'='*80}", flush=True)
            print("💾 INVENTORY COMPLETE", flush=True)
            print(f"{'='*80}", flush=True)
            print(f"Inventory saved to: {inventory_file}", flush=True)
            print(f"Total sections explored: {len(inventory['sections'])}", flush=True)
            print(f"Screenshots saved to: {OUTPUT_DIR}", flush=True)
            
            # Print summary
            print(f"\n{'='*80}", flush=True)
            print("📊 INVENTORY SUMMARY", flush=True)
            print(f"{'='*80}", flush=True)
            
            for section in inventory['sections']:
                print(f"\n{section['name']}")
                print(f"   URL: {section['url']}")
                print(f"   Records: {section['record_count']}")
                print(f"   Export: {'Yes' if section['has_export'] else 'No'}")
                if section['subsections']:
                    print(f"   Subsections: {', '.join(section['subsections'][:5])}")
                if section['notes']:
                    for note in section['notes'][:3]:
                        print(f"   Note: {note}")
            
        except Exception as e:
            print(f"\n❌ Error during inventory: {str(e)}", flush=True)
            import traceback
            traceback.print_exc()
        
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(inventory_platform())
