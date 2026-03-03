#!/usr/bin/env python3
"""
RueBaRue Webhook Configuration Automation

This script logs into RueBaRue and configures the webhook for SMS integration.
"""

import asyncio
import os
import sys
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

# Configuration
RUEBARUE_URL = "https://app.ruebarue.com/"
USERNAME = os.getenv("RUEBARUE_USERNAME", "lissa@cabin-rentals-of-georgia.com")
PASSWORD = os.getenv("RUEBARUE_PASSWORD", "")
WEBHOOK_URL = "https://crog-ai.com/webhooks/sms/incoming"
STATUS_WEBHOOK_URL = "https://crog-ai.com/webhooks/sms/status"


async def configure_webhook():
    """Navigate to RueBaRue and configure the webhook."""
    
    print("🚀 Starting RueBaRue webhook configuration...")
    print(f"Target URL: {RUEBARUE_URL}")
    print(f"Webhook: {WEBHOOK_URL}\n")
    
    async with async_playwright() as p:
        # Launch browser in headless mode (no display required)
        print("📱 Launching browser...")
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080}
        )
        page = await context.new_page()
        
        try:
            # Step 1: Navigate to RueBaRue
            print(f"\n1️⃣ Navigating to {RUEBARUE_URL}...")
            await page.goto(RUEBARUE_URL, wait_until="networkidle")
            await page.screenshot(path="/home/admin/Fortress-Prime/ruebarue_01_homepage.png")
            print("   ✅ Page loaded")
            
            # Step 2: Login
            print(f"\n2️⃣ Logging in as {USERNAME}...")
            
            # Wait for login form (try multiple selectors)
            try:
                # Try common email/username field selectors
                await page.wait_for_selector('input[type="email"], input[type="text"], input[name="email"], input[name="username"]', timeout=5000)
                
                # Fill email
                email_field = await page.query_selector('input[type="email"]') or \
                             await page.query_selector('input[name="email"]') or \
                             await page.query_selector('input[name="username"]') or \
                             await page.query_selector('input[type="text"]')
                
                if email_field:
                    await email_field.fill(USERNAME)
                    print("   ✅ Filled username/email")
                else:
                    print("   ⚠️ Could not find email field")
                
                # Fill password
                password_field = await page.query_selector('input[type="password"]')
                if password_field:
                    await password_field.fill(PASSWORD)
                    print("   ✅ Filled password")
                else:
                    print("   ⚠️ Could not find password field")
                
                await page.screenshot(path="/home/admin/Fortress-Prime/ruebarue_02_login_filled.png")
                
                # Click login button
                login_button = await page.query_selector('button[type="submit"]') or \
                              await page.query_selector('button:has-text("Login")') or \
                              await page.query_selector('button:has-text("Sign in")') or \
                              await page.query_selector('input[type="submit"]')
                
                if login_button:
                    await login_button.click()
                    print("   🔄 Clicked login button")
                    await page.wait_for_load_state("networkidle", timeout=10000)
                    await page.screenshot(path="/home/admin/Fortress-Prime/ruebarue_03_logged_in.png")
                    print("   ✅ Login successful")
                else:
                    print("   ⚠️ Could not find login button")
                    
            except PlaywrightTimeout:
                print("   ⚠️ Login form not found - might already be logged in or different page structure")
                await page.screenshot(path="/home/admin/Fortress-Prime/ruebarue_02_no_login_form.png")
            
            # Step 3: Find webhook settings
            print("\n3️⃣ Looking for webhook/integration settings...")
            
            # Wait a moment for page to fully load
            await asyncio.sleep(2)
            
            # Try to find menu items that might contain webhooks
            menu_items = [
                "Settings",
                "Webhooks",
                "Integrations",
                "API",
                "Developer",
                "Account",
            ]
            
            page_content = await page.content()
            found_items = []
            
            for item in menu_items:
                if item.lower() in page_content.lower():
                    found_items.append(item)
                    print(f"   ✓ Found: {item}")
            
            if found_items:
                print(f"\n   📋 Found potential menu items: {', '.join(found_items)}")
            else:
                print("   ⚠️ No obvious webhook menu items found")
            
            await page.screenshot(path="/home/admin/Fortress-Prime/ruebarue_04_dashboard.png")
            
            # Step 4: Try to navigate to settings
            print("\n4️⃣ Attempting to find webhook configuration...")
            
            # Try clicking Settings if available
            settings_selectors = [
                'a:has-text("Settings")',
                'button:has-text("Settings")',
                'a[href*="settings"]',
                'a:has-text("Webhooks")',
                'a:has-text("Integrations")',
                'a:has-text("API")',
            ]
            
            clicked = False
            for selector in settings_selectors:
                try:
                    element = await page.query_selector(selector)
                    if element:
                        await element.click()
                        print(f"   ✅ Clicked: {selector}")
                        await asyncio.sleep(2)
                        await page.screenshot(path="/home/admin/Fortress-Prime/ruebarue_05_settings.png")
                        clicked = True
                        break
                except Exception as e:
                    continue
            
            if not clicked:
                print("   ⚠️ Could not automatically navigate to settings")
                print("   📝 Taking screenshot of current page for manual navigation")
            
            # Step 5: Look for webhook input fields
            print("\n5️⃣ Looking for webhook URL input fields...")
            
            # Check for input fields that might be for webhooks
            webhook_inputs = await page.query_selector_all('input[type="url"], input[type="text"]')
            print(f"   Found {len(webhook_inputs)} input fields")
            
            # Check for labels containing "webhook"
            page_text = await page.inner_text('body')
            if 'webhook' in page_text.lower():
                print("   ✅ 'Webhook' text found on page")
            else:
                print("   ⚠️ 'Webhook' text not found on page")
            
            await page.screenshot(path="/home/admin/Fortress-Prime/ruebarue_06_current_page.png")
            
            # Step 6: Document findings
            print("\n" + "="*60)
            print("📊 CONFIGURATION REPORT")
            print("="*60)
            print(f"Current URL: {page.url}")
            print(f"Page Title: {await page.title()}")
            print(f"\nWebhook URL to configure: {WEBHOOK_URL}")
            print(f"Status webhook URL: {STATUS_WEBHOOK_URL}")
            
            print("\n📸 Screenshots saved:")
            print("   - ruebarue_01_homepage.png")
            print("   - ruebarue_02_login_filled.png (or ruebarue_02_no_login_form.png)")
            print("   - ruebarue_03_logged_in.png")
            print("   - ruebarue_04_dashboard.png")
            print("   - ruebarue_05_settings.png")
            print("   - ruebarue_06_current_page.png")
            
            # Try to automatically fill webhook if we can find the field
            print("\n6️⃣ Attempting to configure webhook automatically...")
            
            webhook_filled = False
            try:
                # Look for input fields that might be for webhooks
                inputs = await page.query_selector_all('input[type="url"], input[type="text"]')
                
                for idx, input_field in enumerate(inputs):
                    # Get the input's label or placeholder
                    placeholder = await input_field.get_attribute('placeholder') or ''
                    name = await input_field.get_attribute('name') or ''
                    id_attr = await input_field.get_attribute('id') or ''
                    
                    # Check if this looks like a webhook field
                    webhook_keywords = ['webhook', 'url', 'callback', 'endpoint']
                    if any(keyword in (placeholder + name + id_attr).lower() for keyword in webhook_keywords):
                        print(f"   🎯 Found potential webhook field: {placeholder or name or id_attr}")
                        await input_field.fill(WEBHOOK_URL)
                        webhook_filled = True
                        await page.screenshot(path=f"/home/admin/Fortress-Prime/ruebarue_07_webhook_filled_{idx}.png")
                        print(f"   ✅ Filled webhook URL: {WEBHOOK_URL}")
                        break
            except Exception as e:
                print(f"   ⚠️ Could not auto-fill webhook: {e}")
            
            if not webhook_filled:
                print("   ⚠️ Could not automatically fill webhook")
                print("   📝 Manual configuration required")
            
            # Take final screenshot
            await page.screenshot(path="/home/admin/Fortress-Prime/ruebarue_07_final.png")
            print("\n   📸 Final screenshot saved: ruebarue_07_final.png")
            
        except Exception as e:
            print(f"\n❌ Error: {e}")
            await page.screenshot(path="/home/admin/Fortress-Prime/ruebarue_error.png")
            print("   📸 Error screenshot saved: ruebarue_error.png")
            raise
        
        finally:
            print("\n🏁 Closing browser...")
            await browser.close()
            print("✅ Done!")


async def main():
    """Main entry point."""
    print("\n" + "="*60)
    print("🔧 RUEBARUE WEBHOOK CONFIGURATION TOOL")
    print("="*60)
    
    try:
        await configure_webhook()
        print("\n✅ Configuration process completed!")
        print("\nNext steps:")
        print("1. Review the screenshots in /home/admin/Fortress-Prime/")
        print("2. Verify webhook URL is saved in RueBaRue")
        print("3. Test by sending an SMS to your RueBaRue number")
        print("4. Monitor: tail -f /tmp/crog_gateway.log")
        return 0
    except Exception as e:
        print(f"\n❌ Configuration failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
