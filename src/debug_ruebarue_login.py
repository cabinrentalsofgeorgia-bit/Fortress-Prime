#!/usr/bin/env python3
"""
Debug RueBaRue Login - See exactly what's happening
"""

import asyncio
import os
import sys
from datetime import datetime
from playwright.async_api import async_playwright

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

RUEBARUE_EMAIL = os.getenv("RUEBARUE_EMAIL", "")
RUEBARUE_PASSWORD = os.getenv("RUEBARUE_PASSWORD", "")
RUEBARUE_URL = "https://app.ruebarue.com/"
OUTPUT_DIR = "/home/admin/Fortress-Prime/data/ruebarue_messages"

async def debug_login():
    if not RUEBARUE_EMAIL or not RUEBARUE_PASSWORD:
        raise RuntimeError("Missing RUEBARUE_EMAIL or RUEBARUE_PASSWORD environment variables.")
    async with async_playwright() as p:
        print("🚀 Launching browser...", flush=True)
        browser = await p.firefox.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1920, "height": 1080})
        
        try:
            print(f"🌐 Navigating to {RUEBARUE_URL}...", flush=True)
            await page.goto(RUEBARUE_URL, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)
            
            print(f"✅ Page loaded: {page.url}", flush=True)
            
            # Find inputs
            print("\n🔍 Finding input fields...", flush=True)
            inputs = await page.query_selector_all('input.uk-input')
            print(f"   Found {len(inputs)} inputs with class 'uk-input'", flush=True)
            
            for i, inp in enumerate(inputs):
                inp_type = await inp.get_attribute('type')
                inp_value = await inp.get_attribute('value')
                inp_placeholder = await inp.get_attribute('placeholder')
                print(f"   Input {i+1}: type={inp_type}, value='{inp_value}', placeholder='{inp_placeholder}'", flush=True)
            
            # Fill email
            print(f"\n✍️  Filling email field...", flush=True)
            email_input = inputs[0] if len(inputs) > 0 else None
            if email_input:
                await email_input.click()
                await asyncio.sleep(0.5)
                await email_input.fill(RUEBARUE_EMAIL)
                await asyncio.sleep(0.5)
                
                # Check if it was filled
                filled_value = await email_input.get_attribute('value')
                print(f"   Email field value after fill: '{filled_value}'", flush=True)
                
                if filled_value != RUEBARUE_EMAIL:
                    print(f"   ⚠️  Value mismatch! Expected '{RUEBARUE_EMAIL}', got '{filled_value}'", flush=True)
            
            # Fill password
            print(f"\n🔐 Filling password field...", flush=True)
            password_input = inputs[1] if len(inputs) > 1 else None
            if password_input:
                await password_input.click()
                await asyncio.sleep(0.5)
                await password_input.fill(RUEBARUE_PASSWORD)
                await asyncio.sleep(0.5)
                
                # Check if it was filled (value will be hidden for password)
                filled_value = await password_input.get_attribute('value')
                print(f"   Password field has value: {len(filled_value) > 0}", flush=True)
            
            # Take screenshot before login
            screenshot_path = os.path.join(OUTPUT_DIR, f"debug_before_login_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
            await page.screenshot(path=screenshot_path, full_page=True)
            print(f"\n📸 Screenshot before login: {screenshot_path}", flush=True)
            
            # Check for any existing error messages
            print(f"\n🔍 Checking for error messages before login...", flush=True)
            error_selectors = ['.error', '.alert', '[role="alert"]', '.uk-alert', '.uk-alert-danger', '.uk-text-danger']
            for selector in error_selectors:
                errors = await page.query_selector_all(selector)
                if errors:
                    for error in errors:
                        error_text = (await error.inner_text()).strip()
                        if error_text:
                            print(f"   Error found ({selector}): {error_text}", flush=True)
            
            # Click login button
            print(f"\n🔘 Clicking LOGIN button...", flush=True)
            login_button = await page.query_selector('button:has-text("LOGIN")')
            if login_button:
                await login_button.click()
                print("   Button clicked", flush=True)
            
            # Wait a bit
            await asyncio.sleep(3)
            
            # Check URL
            print(f"\n🔍 After login attempt:", flush=True)
            print(f"   URL: {page.url}", flush=True)
            print(f"   Title: {await page.title()}", flush=True)
            
            # Take screenshot after login
            screenshot_path = os.path.join(OUTPUT_DIR, f"debug_after_login_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
            await page.screenshot(path=screenshot_path, full_page=True)
            print(f"\n📸 Screenshot after login: {screenshot_path}", flush=True)
            
            # Check for error messages
            print(f"\n🔍 Checking for error messages after login...", flush=True)
            for selector in error_selectors:
                errors = await page.query_selector_all(selector)
                if errors:
                    for error in errors:
                        error_text = (await error.inner_text()).strip()
                        if error_text:
                            print(f"   Error found ({selector}): {error_text}", flush=True)
            
            # Check all visible text for errors
            page_text = await page.inner_text('body')
            error_keywords = ['error', 'invalid', 'incorrect', 'failed', 'wrong']
            found_errors = []
            for line in page_text.split('\n'):
                line = line.strip()
                if any(keyword in line.lower() for keyword in error_keywords):
                    found_errors.append(line)
            
            if found_errors:
                print(f"\n⚠️  Lines containing error keywords:", flush=True)
                for err in found_errors[:10]:
                    print(f"   - {err}", flush=True)
            
            # Check input field values again
            print(f"\n🔍 Input field values after login attempt:", flush=True)
            inputs_after = await page.query_selector_all('input.uk-input')
            for i, inp in enumerate(inputs_after):
                inp_type = await inp.get_attribute('type')
                inp_value = await inp.get_attribute('value')
                print(f"   Input {i+1}: type={inp_type}, value='{inp_value}'", flush=True)
            
            # Save HTML
            html_path = os.path.join(OUTPUT_DIR, f"debug_after_login_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html")
            html = await page.content()
            with open(html_path, 'w') as f:
                f.write(html)
            print(f"\n💾 HTML saved: {html_path}", flush=True)
            
        except Exception as e:
            print(f"\n❌ Error: {e}", flush=True)
            import traceback
            traceback.print_exc()
        
        finally:
            await browser.close()
            print("\n✅ Done", flush=True)

if __name__ == "__main__":
    print("="*80, flush=True)
    print("🐛 RueBaRue Login Debug", flush=True)
    print("="*80, flush=True)
    asyncio.run(debug_login())
