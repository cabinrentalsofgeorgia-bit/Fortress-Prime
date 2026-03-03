#!/usr/bin/env python3
"""
RueBaRue Diagnostic Script - Quick check of login page structure
"""

import asyncio
import os
import sys
from datetime import datetime
from playwright.async_api import async_playwright

# Force unbuffered output
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

RUEBARUE_URL = "https://app.ruebarue.com/"
OUTPUT_DIR = "/home/admin/Fortress-Prime/data/ruebarue_messages"
os.makedirs(OUTPUT_DIR, exist_ok=True)

async def diagnose():
    print("🚀 Starting diagnostic...", flush=True)
    
    async with async_playwright() as p:
        print("📱 Launching browser...", flush=True)
        browser = await p.firefox.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1920, "height": 1080})
        
        try:
            print(f"🌐 Navigating to {RUEBARUE_URL}...", flush=True)
            await page.goto(RUEBARUE_URL, wait_until="networkidle", timeout=30000)
            
            print(f"✅ Page loaded", flush=True)
            print(f"   URL: {page.url}", flush=True)
            print(f"   Title: {await page.title()}", flush=True)
            
            # Save screenshot
            screenshot_path = os.path.join(OUTPUT_DIR, "diagnostic_page.png")
            await page.screenshot(path=screenshot_path, full_page=True)
            print(f"📸 Screenshot: {screenshot_path}", flush=True)
            
            # Save HTML
            html_path = os.path.join(OUTPUT_DIR, "diagnostic_page.html")
            html = await page.content()
            with open(html_path, 'w') as f:
                f.write(html)
            print(f"💾 HTML saved: {html_path}", flush=True)
            print(f"   HTML length: {len(html)} characters", flush=True)
            
            # Find all inputs
            print("\n🔍 Finding input fields...", flush=True)
            inputs = await page.query_selector_all('input')
            print(f"   Found {len(inputs)} input fields:", flush=True)
            
            for i, inp in enumerate(inputs):
                inp_type = await inp.get_attribute('type') or 'text'
                inp_name = await inp.get_attribute('name') or ''
                inp_id = await inp.get_attribute('id') or ''
                inp_placeholder = await inp.get_attribute('placeholder') or ''
                inp_class = await inp.get_attribute('class') or ''
                print(f"   [{i+1}] type={inp_type}, name={inp_name}, id={inp_id}, placeholder={inp_placeholder}, class={inp_class}", flush=True)
            
            # Find all buttons
            print("\n🔍 Finding buttons...", flush=True)
            buttons = await page.query_selector_all('button')
            print(f"   Found {len(buttons)} buttons:", flush=True)
            
            for i, btn in enumerate(buttons):
                btn_text = (await btn.inner_text()).strip()
                btn_type = await btn.get_attribute('type') or ''
                btn_class = await btn.get_attribute('class') or ''
                print(f"   [{i+1}] text='{btn_text}', type={btn_type}, class={btn_class}", flush=True)
            
            # Find all links
            print("\n🔍 Finding links...", flush=True)
            links = await page.query_selector_all('a')
            print(f"   Found {len(links)} links (showing first 20):", flush=True)
            
            for i, link in enumerate(links[:20]):
                link_text = (await link.inner_text()).strip()
                link_href = await link.get_attribute('href') or ''
                if link_text or link_href:
                    print(f"   [{i+1}] text='{link_text}', href={link_href}", flush=True)
            
            # Check for forms
            print("\n🔍 Finding forms...", flush=True)
            forms = await page.query_selector_all('form')
            print(f"   Found {len(forms)} forms", flush=True)
            
            for i, form in enumerate(forms):
                form_action = await form.get_attribute('action') or ''
                form_method = await form.get_attribute('method') or ''
                print(f"   [{i+1}] action={form_action}, method={form_method}", flush=True)
            
            # Get body text to check for keywords
            print("\n🔍 Checking page content...", flush=True)
            body_text = await page.inner_text('body')
            keywords = ['login', 'sign in', 'email', 'password', 'username', 'captcha', '2fa', 'two-factor']
            found_keywords = [kw for kw in keywords if kw.lower() in body_text.lower()]
            print(f"   Keywords found: {', '.join(found_keywords) if found_keywords else 'none'}", flush=True)
            
            # Check for iframes
            print("\n🔍 Checking for iframes...", flush=True)
            iframes = await page.query_selector_all('iframe')
            print(f"   Found {len(iframes)} iframes", flush=True)
            
            for i, iframe in enumerate(iframes):
                iframe_src = await iframe.get_attribute('src') or ''
                iframe_id = await iframe.get_attribute('id') or ''
                print(f"   [{i+1}] src={iframe_src}, id={iframe_id}", flush=True)
            
            print("\n✅ Diagnostic complete!", flush=True)
            print(f"📁 Output directory: {OUTPUT_DIR}", flush=True)
            
        except Exception as e:
            print(f"\n❌ Error: {e}", flush=True)
            import traceback
            traceback.print_exc()
        
        finally:
            await browser.close()
            print("👋 Browser closed", flush=True)

if __name__ == "__main__":
    print("="*80, flush=True)
    print("🏰 FORTRESS PRIME - RueBaRue Diagnostic", flush=True)
    print("="*80, flush=True)
    asyncio.run(diagnose())
