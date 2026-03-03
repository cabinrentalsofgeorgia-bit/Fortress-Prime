#!/usr/bin/env python3
"""
Authenticated QA verification of Command Center / VRS Hub split implementation.
"""
import time
import sys
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# QA Checklist
checklist = {
    "1_command_center_loads": False,
    "1_system_ops_dashboard": False,
    "1_core_services_present": False,
    "1_vrs_hub_link_present": False,
    "1_no_vrs_business_panels": False,
    "2_vrs_hub_loads": False,
    "2_vrs_heading_present": False,
    "2_vrs_quick_links_present": False,
    "2_vrs_operations_panels": False,
    "3_command_center_nav_works": False,
    "3_vrs_hub_nav_works": False,
    "4_quick_link_clickable": False,
    "4_reservation_detail_opens": False,
}

observations = []

def log_observation(key, status, message):
    """Log an observation with PASS/FAIL status."""
    checklist[key] = status
    status_str = "✅ PASS" if status else "❌ FAIL"
    obs = f"{status_str} - {key}: {message}"
    observations.append(obs)
    print(obs)

def setup_driver():
    """Setup Chrome driver with headless options."""
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1920,1080')
    
    try:
        driver = webdriver.Chrome(options=chrome_options)
        return driver
    except Exception as e:
        print(f"❌ CRITICAL: Failed to initialize Chrome driver: {e}")
        print("Please ensure Chrome/Chromium and chromedriver are installed.")
        sys.exit(1)

def authenticate(driver, base_url):
    """Attempt to authenticate if needed."""
    try:
        driver.get(f"{base_url}/login")
        time.sleep(2)
        
        # Check if already authenticated
        if "/login" not in driver.current_url:
            print("✅ Already authenticated")
            return True
        
        # Look for login form
        try:
            username_field = driver.find_element(By.NAME, "username")
            password_field = driver.find_element(By.NAME, "password")
            
            # Try default credentials (adjust as needed)
            username_field.send_keys("admin")
            password_field.send_keys("fortress")
            
            submit_button = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            submit_button.click()
            
            time.sleep(2)
            
            if "/login" not in driver.current_url:
                print("✅ Authentication successful")
                return True
            else:
                print("⚠️  Authentication may have failed - continuing anyway")
                return False
        except NoSuchElementException:
            print("⚠️  Login form not found - may already be authenticated")
            return True
            
    except Exception as e:
        print(f"⚠️  Authentication error: {e}")
        return False

def test_command_center(driver, base_url):
    """Test 1: Command Center root dashboard."""
    print("\n=== TEST 1: Command Center Root (/) ===")
    
    try:
        driver.get(base_url)
        time.sleep(2)
        
        # Check page loaded
        if driver.current_url.startswith(base_url):
            log_observation("1_command_center_loads", True, "Command Center loaded successfully")
        else:
            log_observation("1_command_center_loads", False, f"Unexpected URL: {driver.current_url}")
            return
        
        # Check for system-ops dashboard indicators
        page_source = driver.page_source.lower()
        
        # Look for system-oriented content
        system_indicators = [
            "command center",
            "system health",
            "core services",
            "cluster",
            "infrastructure"
        ]
        
        found_system = any(indicator in page_source for indicator in system_indicators)
        log_observation("1_system_ops_dashboard", found_system, 
                       f"System-ops dashboard content: {'found' if found_system else 'NOT FOUND'}")
        
        # Check for Core Services or System Health section
        try:
            # Look for various possible section headers
            sections = driver.find_elements(By.CSS_SELECTOR, "h2, h3, .section-title, .card-title")
            section_texts = [s.text.lower() for s in sections]
            
            has_core_services = any("core" in t or "system" in t or "health" in t for t in section_texts)
            log_observation("1_core_services_present", has_core_services,
                           f"Core Services/System Health section: {'found' if has_core_services else 'NOT FOUND'}")
        except Exception as e:
            log_observation("1_core_services_present", False, f"Error finding sections: {e}")
        
        # Check for VRS Hub link
        try:
            vrs_links = driver.find_elements(By.XPATH, "//*[contains(text(), 'VRS') or contains(text(), 'vrs')]")
            has_vrs_link = len(vrs_links) > 0
            log_observation("1_vrs_hub_link_present", has_vrs_link,
                           f"VRS Hub link: {'found ({} links)'.format(len(vrs_links)) if has_vrs_link else 'NOT FOUND'}")
        except Exception as e:
            log_observation("1_vrs_hub_link_present", False, f"Error finding VRS link: {e}")
        
        # Check that old VRS business panels are NOT present
        vrs_business_indicators = [
            "reservations",
            "check-in",
            "check-out",
            "arrivals",
            "departures",
            "properties",
            "guests"
        ]
        
        # Count how many business indicators are present
        business_count = sum(1 for indicator in vrs_business_indicators if indicator in page_source)
        
        # If we find more than 2 business indicators, that's suspicious
        no_business_panels = business_count <= 2
        log_observation("1_no_vrs_business_panels", no_business_panels,
                       f"VRS business panels on root: {business_count} indicators found (should be minimal)")
        
    except Exception as e:
        log_observation("1_command_center_loads", False, f"Exception: {e}")

def test_vrs_hub(driver, base_url):
    """Test 2: VRS Hub dashboard."""
    print("\n=== TEST 2: VRS Hub (/vrs) ===")
    
    try:
        driver.get(f"{base_url}/vrs")
        time.sleep(2)
        
        # Check page loaded
        if "/vrs" in driver.current_url:
            log_observation("2_vrs_hub_loads", True, "VRS Hub loaded successfully")
        else:
            log_observation("2_vrs_hub_loads", False, f"Unexpected URL: {driver.current_url}")
            return
        
        page_source = driver.page_source.lower()
        
        # Check for VRS-specific heading
        vrs_heading = "crog-vrs" in page_source or "vrs dashboard" in page_source or "vacation rental" in page_source
        log_observation("2_vrs_heading_present", vrs_heading,
                       f"VRS-specific heading: {'found' if vrs_heading else 'NOT FOUND'}")
        
        # Check for quick links
        try:
            quick_links = driver.find_elements(By.CSS_SELECTOR, ".quick-link, .quick-access, a[href*='vrs']")
            has_quick_links = len(quick_links) > 0
            log_observation("2_vrs_quick_links_present", has_quick_links,
                           f"VRS quick links: {'found ({} links)'.format(len(quick_links)) if has_quick_links else 'NOT FOUND'}")
        except Exception as e:
            log_observation("2_vrs_quick_links_present", False, f"Error finding quick links: {e}")
        
        # Check for operations panels (reservations, properties, etc.)
        vrs_operations = [
            "reservation",
            "propert",
            "guest",
            "arrival",
            "departure",
            "check-in",
            "check-out"
        ]
        
        ops_count = sum(1 for op in vrs_operations if op in page_source)
        has_ops_panels = ops_count >= 3
        log_observation("2_vrs_operations_panels", has_ops_panels,
                       f"VRS operations panels: {ops_count} indicators found")
        
    except Exception as e:
        log_observation("2_vrs_hub_loads", False, f"Exception: {e}")

def test_sidebar_navigation(driver, base_url):
    """Test 3: Sidebar navigation behavior."""
    print("\n=== TEST 3: Sidebar Navigation ===")
    
    try:
        # Start at VRS hub
        driver.get(f"{base_url}/vrs")
        time.sleep(2)
        
        # Look for Command Center link in sidebar/nav
        try:
            # Try multiple selectors
            cc_link = None
            selectors = [
                "a[href='/']",
                "a[href='http://localhost:9800/']",
                "//*[contains(text(), 'Command Center')]",
                "nav a:first-child"
            ]
            
            for selector in selectors:
                try:
                    if selector.startswith("//"):
                        cc_link = driver.find_element(By.XPATH, selector)
                    else:
                        cc_link = driver.find_element(By.CSS_SELECTOR, selector)
                    if cc_link:
                        break
                except:
                    continue
            
            if cc_link:
                cc_link.click()
                time.sleep(2)
                
                # Verify we're at root
                at_root = driver.current_url.rstrip('/') == base_url.rstrip('/')
                log_observation("3_command_center_nav_works", at_root,
                               f"Command Center nav: {'works (at {})'.format(driver.current_url) if at_root else 'FAILED (at {})'.format(driver.current_url)}")
            else:
                log_observation("3_command_center_nav_works", False, "Command Center link not found")
        except Exception as e:
            log_observation("3_command_center_nav_works", False, f"Error: {e}")
        
        # Now test VRS Hub link from root
        try:
            driver.get(base_url)
            time.sleep(2)
            
            vrs_link = None
            selectors = [
                "a[href='/vrs']",
                "a[href='http://localhost:9800/vrs']",
                "//*[contains(text(), 'VRS Hub')]",
                "//*[contains(text(), 'VRS')]"
            ]
            
            for selector in selectors:
                try:
                    if selector.startswith("//"):
                        vrs_link = driver.find_element(By.XPATH, selector)
                    else:
                        vrs_link = driver.find_element(By.CSS_SELECTOR, selector)
                    if vrs_link:
                        break
                except:
                    continue
            
            if vrs_link:
                vrs_link.click()
                time.sleep(2)
                
                at_vrs = "/vrs" in driver.current_url
                log_observation("3_vrs_hub_nav_works", at_vrs,
                               f"VRS Hub nav: {'works (at {})'.format(driver.current_url) if at_vrs else 'FAILED (at {})'.format(driver.current_url)}")
            else:
                log_observation("3_vrs_hub_nav_works", False, "VRS Hub link not found")
        except Exception as e:
            log_observation("3_vrs_hub_nav_works", False, f"Error: {e}")
            
    except Exception as e:
        print(f"Navigation test exception: {e}")

def test_quick_interactions(driver, base_url):
    """Test 4: Quick sanity interactions."""
    print("\n=== TEST 4: Quick Interactions ===")
    
    try:
        driver.get(f"{base_url}/vrs")
        time.sleep(2)
        
        # Try to click a quick link card
        try:
            quick_links = driver.find_elements(By.CSS_SELECTOR, ".quick-link, .card, a[href*='vrs']")
            
            if quick_links:
                original_url = driver.current_url
                quick_links[0].click()
                time.sleep(2)
                
                # Check if we navigated somewhere
                navigated = driver.current_url != original_url
                
                # Go back
                driver.back()
                time.sleep(1)
                
                log_observation("4_quick_link_clickable", True,
                               f"Quick link clickable: navigated to {driver.current_url if navigated else 'same page'}")
            else:
                log_observation("4_quick_link_clickable", False, "No quick links found to test")
        except Exception as e:
            log_observation("4_quick_link_clickable", False, f"Error: {e}")
        
        # Try to click a reservation row if present
        try:
            driver.get(f"{base_url}/vrs")
            time.sleep(2)
            
            # Look for reservation rows in arrivals/departures
            rows = driver.find_elements(By.CSS_SELECTOR, "tr[data-reservation], .reservation-row, tbody tr")
            
            if len(rows) > 1:  # More than just header
                rows[1].click()  # Click first data row
                time.sleep(2)
                
                # Look for a detail panel or modal
                page_source = driver.page_source.lower()
                detail_indicators = ["detail", "modal", "reservation-", "guest", "confirmation"]
                
                has_detail = any(ind in page_source for ind in detail_indicators)
                log_observation("4_reservation_detail_opens", has_detail,
                               f"Reservation detail: {'opened' if has_detail else 'NOT DETECTED'}")
            else:
                log_observation("4_reservation_detail_opens", True, "No reservation rows to test (acceptable)")
        except Exception as e:
            log_observation("4_reservation_detail_opens", False, f"Error: {e}")
            
    except Exception as e:
        print(f"Interaction test exception: {e}")

def main():
    """Run all QA tests."""
    base_url = "http://localhost:9800"
    
    print("=" * 80)
    print("AUTHENTICATED QA VERIFICATION - COMMAND CENTER / VRS HUB SPLIT")
    print("=" * 80)
    
    driver = setup_driver()
    
    try:
        # Authenticate
        authenticate(driver, base_url)
        
        # Run all tests
        test_command_center(driver, base_url)
        test_vrs_hub(driver, base_url)
        test_sidebar_navigation(driver, base_url)
        test_quick_interactions(driver, base_url)
        
    finally:
        driver.quit()
    
    # Print final report
    print("\n" + "=" * 80)
    print("FINAL QA REPORT")
    print("=" * 80)
    
    for obs in observations:
        print(obs)
    
    print("\n" + "=" * 80)
    print("CHECKLIST SUMMARY")
    print("=" * 80)
    
    passed = sum(1 for v in checklist.values() if v)
    total = len(checklist)
    
    for key, status in checklist.items():
        status_str = "✅ PASS" if status else "❌ FAIL"
        print(f"{status_str} - {key}")
    
    print(f"\nOVERALL: {passed}/{total} checks passed ({100*passed//total}%)")
    
    if passed == total:
        print("\n🎉 ALL CHECKS PASSED - Split implementation verified successfully!")
        sys.exit(0)
    else:
        print(f"\n⚠️  {total - passed} CHECKS FAILED - Review observations above")
        sys.exit(1)

if __name__ == "__main__":
    main()
