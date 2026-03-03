"""
Complete RueBaRue data extraction script.
Parses captured HTML from admin + uses Playwright for detail pages and public guides.
"""
import json
import os
import sys
import time
import asyncio
import argparse
from datetime import datetime
from bs4 import BeautifulSoup

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
INVENTORY_DIR = os.path.join(DATA_DIR, 'ruebarue_inventory')
OUTPUT_DIR = os.path.join(DATA_DIR, 'ruebarue')

os.makedirs(OUTPUT_DIR, exist_ok=True)

RUEBARUE_EMAIL = os.getenv("RUEBARUE_EMAIL", "")
RUEBARUE_PASSWORD = os.getenv("RUEBARUE_PASSWORD", "")

GUESTBOOK_IDS = [
    "1898214714979626", "2788198110113965", "3290832346901923",
    "3440960238137066", "3969410795269472", "4382631818510846",
    "4893257250132971", "5615577855219852", "5868479163580915",
    "6811604422293348", "7539058782680381", "8771180713726205",
    "8874301220043101",
]
AREA_GUIDE_ID = "5094097405476864"


def load_html(filename):
    path = os.path.join(INVENTORY_DIR, filename)
    with open(path, 'r', encoding='utf-8') as f:
        return BeautifulSoup(f.read(), 'html.parser')


# ─── 1. AI CHATBOT FAQS ───────────────────────────────────────────────
def extract_faqs():
    print("[1/8] Extracting AI Chatbot FAQs...")
    soup = load_html('20260217_103828_ai_chatbot_faqs.html')
    table = soup.find('table')
    rows = table.find_all('tr') if table else []

    faqs = []
    for row in rows:
        cells = row.find_all('td')
        if len(cells) >= 2:
            question = cells[0].get_text(strip=True)
            answer = cells[1].get_text(strip=True)
            if question.endswith('Template'):
                question = question[:-len('Template')].strip()
            if question and answer:
                faqs.append({"question": question, "answer": answer})

    print(f"  Found {len(faqs)} FAQs")
    return faqs


# ─── 2. SCHEDULER ─────────────────────────────────────────────────────
def extract_scheduler():
    print("[2/8] Extracting Scheduler templates...")
    soup = load_html('20260217_103657_scheduler.html')
    table = soup.find('table')
    rows = table.find_all('tr') if table else []

    items = []
    for row in rows[1:]:  # skip header
        cells = row.find_all('td')
        if len(cells) >= 7:
            active_el = cells[0].find('input')
            is_active = bool(active_el and active_el.get('checked'))
            msg_type = cells[1].get_text(strip=True)
            name = cells[2].get_text(strip=True)
            schedule = cells[3].get_text(strip=True)
            tags = cells[4].get_text(strip=True)
            booking_source = cells[5].get_text(strip=True)
            flags = cells[6].get_text(strip=True)
            items.append({
                "name": name,
                "type": msg_type,
                "active": is_active,
                "schedule": schedule,
                "tags": tags,
                "booking_source": booking_source,
                "flags": flags,
            })

    print(f"  Found {len(items)} scheduler templates")
    return items


# ─── 3. SAVED RESPONSES ───────────────────────────────────────────────
def extract_saved_responses():
    print("[3/8] Extracting Saved Responses...")
    soup = load_html('20260217_103720_saved_responses.html')
    table = soup.find('table')
    rows = table.find_all('tr') if table else []

    items = []
    for row in rows[1:]:
        cells = row.find_all('td')
        if cells:
            name = cells[0].get_text(strip=True)
            if name:
                items.append({"name": name, "text": ""})

    print(f"  Found {len(items)} saved response names (need Playwright for full text)")
    return items


# ─── 4. SURVEYS ───────────────────────────────────────────────────────
def extract_surveys():
    print("[4/8] Extracting Surveys...")
    soup = load_html('20260217_103714_surveys.html')
    table = soup.find('table')
    rows = table.find_all('tr') if table else []

    items = []
    for row in rows[1:]:
        cells = row.find_all('td')
        if len(cells) >= 2:
            name = cells[0].get_text(strip=True)
            responses = cells[1].get_text(strip=True)
            items.append({
                "name": name,
                "response_count": responses,
                "questions": [],
            })

    print(f"  Found {len(items)} surveys (need Playwright for questions & responses)")
    return items


# ─── 5. CONTACTS ──────────────────────────────────────────────────────
def extract_contacts():
    print("[5/8] Extracting Contacts...")
    soup = load_html('20260217_103646_contacts.html')
    table = soup.find('table')
    rows = table.find_all('tr') if table else []

    items = []
    for row in rows[1:]:
        cells = row.find_all('td')
        if len(cells) >= 4:
            raw = cells[1].get_text(separator='|', strip=True)
            parts = raw.split('|')
            name = parts[0] if parts else ''
            phone = ''
            email = ''
            role = ''
            for p in parts[1:]:
                p = p.strip()
                if p.startswith('+'):
                    phone = p
                elif '@' in p:
                    email = p
                else:
                    role = p

            props = cells[2].get_text(strip=True)
            tags = cells[3].get_text(strip=True)
            items.append({
                "name": name,
                "phone": phone,
                "email": email,
                "role": role,
                "properties": props,
                "tags": tags,
            })

    print(f"  Found {len(items)} contacts")
    return items


# ─── 6. MASTER HOME GUIDE ─────────────────────────────────────────────
def extract_master_guide():
    print("[6/8] Extracting Master Home Guide...")
    soup = load_html('20260217_103748_master_home_guide.html')

    # Categories are in master-guide-tab
    tab = soup.find(class_='master-guide-tab')
    categories = []
    if tab:
        for a in tab.find_all('a'):
            categories.append(a.get_text(strip=True))
    print(f"  Categories: {categories}")

    # Items are uk-card elements
    cards = soup.find_all(class_='hms-property-card')
    items = []
    for card in cards:
        title_el = card.find(['h3', 'h4', 'h5', 'strong', 'b'])
        full_text = card.get_text(separator='\n', strip=True)
        lines = [l.strip() for l in full_text.split('\n') if l.strip()]
        title = lines[0] if lines else ''
        content = '\n'.join(lines[1:]) if len(lines) > 1 else ''

        # Check for PDFs or links
        links = []
        for a in card.find_all('a'):
            href = a.get('href', '')
            if href and 'ruebarue' in href:
                links.append(href)

        items.append({
            "title": title,
            "content": content,
            "links": links,
        })

    print(f"  Found {len(items)} master guide items from HTML")
    return {"categories": categories, "items": items}


# ─── 7. EXTRAS GUIDE ──────────────────────────────────────────────────
def extract_extras():
    print("[7/8] Extracting Extras Guide...")
    soup = load_html('20260217_103800_extras_guide.html')
    cards = soup.find_all(class_='hms-property-card')

    items = []
    for card in cards:
        full_text = card.get_text(separator='\n', strip=True)
        lines = [l.strip() for l in full_text.split('\n') if l.strip()]
        if lines:
            items.append({
                "title": lines[0],
                "content": '\n'.join(lines[1:]) if len(lines) > 1 else '',
            })

    # Also try tables
    tables = soup.find_all('table')
    for table in tables:
        for row in table.find_all('tr')[1:]:
            cells = row.find_all('td')
            if cells:
                items.append({
                    "title": cells[0].get_text(strip=True),
                    "content": '|'.join(c.get_text(strip=True) for c in cells[1:]),
                })

    if not items:
        text = soup.get_text(separator='\n', strip=True)
        items.append({"title": "Full Page", "content": text[:5000]})

    print(f"  Found {len(items)} extras items")
    return items


# ─── 8. HOME GUIDES LIST ──────────────────────────────────────────────
def extract_home_guides_list():
    print("[8/8] Extracting Home Guides list...")
    soup = load_html('20260217_103754_home_guides.html')
    table = soup.find('table')
    rows = table.find_all('tr') if table else []

    properties = []
    for row in rows[1:]:
        cells = row.find_all('td')
        if len(cells) >= 2:
            name_raw = cells[1].get_text(separator='|', strip=True)
            parts = name_raw.split('|')
            prop_name = parts[0].strip() if parts else ''
            address = parts[1].strip() if len(parts) > 1 else ''
            # Look for links to guide
            link = ''
            for a in row.find_all('a'):
                href = a.get('href', '')
                if 'guide.ruebarue.com' in href or '/guestbook/' in href:
                    link = href
            properties.append({
                "name": prop_name,
                "address": address,
                "guide_link": link,
            })

    print(f"  Found {len(properties)} properties in guide list")
    return properties


# ─── PLAYWRIGHT: EXTRACT FULL DETAIL DATA ─────────────────────────────
async def extract_with_playwright(static_data):
    """Use Playwright to get data requiring page interaction."""
    from playwright.async_api import async_playwright

    print("\n=== Starting Playwright for detail extraction ===\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = await context.new_page()

        # Login
        print("Logging into RueBaRue...")
        await page.goto('https://app.ruebarue.com/auth/login', timeout=60000)
        await asyncio.sleep(5)
        # Wait for the React app to render
        for attempt in range(10):
            inputs = await page.query_selector_all('input')
            if len(inputs) >= 2:
                break
            print(f"  Waiting for login form... attempt {attempt+1}")
            await asyncio.sleep(2)

        # Fill login form
        inputs = await page.query_selector_all('input')
        print(f"  Found {len(inputs)} input fields")
        if len(inputs) >= 2:
            await inputs[0].fill(RUEBARUE_EMAIL)
            await inputs[1].fill(RUEBARUE_PASSWORD)
        else:
            await page.fill('input', RUEBARUE_EMAIL)

        # Click submit
        buttons = await page.query_selector_all('button')
        for btn in buttons:
            text = await btn.inner_text()
            if 'sign in' in text.lower() or 'log in' in text.lower() or 'submit' in text.lower():
                await btn.click()
                break
        else:
            if buttons:
                await buttons[-1].click()

        await asyncio.sleep(8)
        current_url = page.url
        print(f"  Current URL after login: {current_url}")
        if 'auth/login' not in current_url:
            print("  Logged in successfully")
        else:
            print("  WARNING: May still be on login page, continuing anyway...")

        # ─── SCHEDULER FULL TEXT ───────────────────────────────
        print("\n--- Extracting Scheduler message texts ---")
        await page.goto('https://app.ruebarue.com/scheduler?type=All&active=All&search=&sort=schedule&page=0&tag=-1', timeout=30000)
        await page.wait_for_load_state('domcontentloaded', timeout=15000)
        await asyncio.sleep(2)

        scheduler_items = static_data.get('scheduler', [])
        rows = await page.query_selector_all('table tbody tr')
        print(f"  Found {len(rows)} scheduler rows")

        for i, row in enumerate(rows):
            try:
                name_cell = await row.query_selector('td:nth-child(3)')
                if name_cell:
                    link = await name_cell.query_selector('a')
                    if link:
                        href = await link.get_attribute('href')
                        if href:
                            detail_page = await context.new_page()
                            full_url = href if href.startswith('http') else f'https://app.ruebarue.com{href}'
                            await detail_page.goto(full_url, timeout=20000)
                            await detail_page.wait_for_load_state('domcontentloaded', timeout=10000)
                            await asyncio.sleep(1)

                            # Extract message body
                            body = await detail_page.evaluate('''() => {
                                // Look for textarea or rich text editor
                                let ta = document.querySelector('textarea');
                                if (ta) return ta.value;
                                let editor = document.querySelector('.ql-editor, [contenteditable="true"], .message-body, .tox-edit-area__iframe');
                                if (editor) return editor.innerText;
                                // Get main content
                                let main = document.querySelector('main, .uk-container, #app');
                                return main ? main.innerText : document.body.innerText;
                            }''')

                            if i < len(scheduler_items):
                                scheduler_items[i]['message_text'] = body[:5000] if body else ''
                            else:
                                scheduler_items.append({
                                    'name': await name_cell.inner_text(),
                                    'message_text': body[:5000] if body else '',
                                })

                            await detail_page.close()
                            print(f"  [{i+1}/{len(rows)}] Got message text ({len(body or '')} chars)")
            except Exception as e:
                print(f"  [{i+1}] Error: {e}")

        # ─── SAVED RESPONSES FULL TEXT ────────────────────────
        print("\n--- Extracting Saved Response texts ---")
        await page.goto('https://app.ruebarue.com/saved-responses', timeout=30000)
        await page.wait_for_load_state('domcontentloaded', timeout=15000)
        await asyncio.sleep(2)

        saved_items = static_data.get('saved_responses', [])
        sr_rows = await page.query_selector_all('table tbody tr')
        print(f"  Found {len(sr_rows)} saved response rows")

        for i, row in enumerate(sr_rows):
            try:
                link = await row.query_selector('a')
                if link:
                    href = await link.get_attribute('href')
                    if href:
                        detail_page = await context.new_page()
                        full_url = href if href.startswith('http') else f'https://app.ruebarue.com{href}'
                        await detail_page.goto(full_url, timeout=20000)
                        await detail_page.wait_for_load_state('domcontentloaded', timeout=10000)
                        await asyncio.sleep(1)

                        body = await detail_page.evaluate('''() => {
                            let ta = document.querySelector('textarea');
                            if (ta) return ta.value;
                            let editor = document.querySelector('.ql-editor, [contenteditable="true"]');
                            if (editor) return editor.innerText;
                            let main = document.querySelector('main, .uk-container');
                            return main ? main.innerText : '';
                        }''')

                        if i < len(saved_items):
                            saved_items[i]['text'] = body or ''
                        print(f"  [{i+1}] Got response text ({len(body or '')} chars)")
                        await detail_page.close()
            except Exception as e:
                print(f"  [{i+1}] Error: {e}")

        # ─── SURVEY QUESTIONS & RESPONSES ─────────────────────
        print("\n--- Extracting Survey questions and responses ---")
        await page.goto('https://app.ruebarue.com/surveys', timeout=30000)
        await page.wait_for_load_state('domcontentloaded', timeout=15000)
        await asyncio.sleep(2)

        survey_items = static_data.get('surveys', [])
        survey_rows = await page.query_selector_all('table tbody tr')

        for i, row in enumerate(survey_rows):
            try:
                link = await row.query_selector('a')
                if link:
                    href = await link.get_attribute('href')
                    if href:
                        detail_page = await context.new_page()
                        full_url = href if href.startswith('http') else f'https://app.ruebarue.com{href}'
                        await detail_page.goto(full_url, timeout=20000)
                        await detail_page.wait_for_load_state('domcontentloaded', timeout=10000)
                        await asyncio.sleep(2)

                        survey_data = await detail_page.evaluate('''() => {
                            let result = {questions: [], responses: []};
                            // Questions tab
                            let questions = document.querySelectorAll('.survey-question, .question-item, input[type="text"], label');
                            questions.forEach(q => {
                                let text = q.innerText || q.value;
                                if (text && text.length > 3) result.questions.push(text.trim());
                            });
                            // Get all table rows for responses
                            let tables = document.querySelectorAll('table');
                            tables.forEach(table => {
                                let rows = table.querySelectorAll('tr');
                                rows.forEach(row => {
                                    let cells = row.querySelectorAll('td');
                                    if (cells.length > 0) {
                                        let rowData = {};
                                        cells.forEach((cell, idx) => {
                                            rowData['col_' + idx] = cell.innerText.trim();
                                        });
                                        result.responses.push(rowData);
                                    }
                                });
                            });
                            // Get full page text as fallback
                            result.full_text = document.querySelector('main')?.innerText || '';
                            return result;
                        }''')

                        if i < len(survey_items):
                            survey_items[i]['questions'] = survey_data.get('questions', [])
                            survey_items[i]['responses'] = survey_data.get('responses', [])
                            survey_items[i]['full_text'] = survey_data.get('full_text', '')[:10000]

                        print(f"  Survey: {len(survey_data.get('questions',[]))} questions, {len(survey_data.get('responses',[]))} responses")

                        # Check for pagination / responses tab
                        resp_tab = await detail_page.query_selector('a[href*="responses"], button:has-text("Responses"), [data-tab="responses"]')
                        if resp_tab:
                            await resp_tab.click()
                            await asyncio.sleep(2)
                            responses_data = await detail_page.evaluate('''() => {
                                let rows = document.querySelectorAll('table tbody tr');
                                let data = [];
                                rows.forEach(row => {
                                    let cells = row.querySelectorAll('td');
                                    let rowData = {};
                                    cells.forEach((cell, idx) => {
                                        rowData['col_' + idx] = cell.innerText.trim();
                                    });
                                    if (Object.keys(rowData).length > 0) data.push(rowData);
                                });
                                return data;
                            }''')
                            if i < len(survey_items):
                                survey_items[i]['response_details'] = responses_data
                            print(f"  Survey responses tab: {len(responses_data)} rows")

                        await detail_page.close()
            except Exception as e:
                print(f"  Survey error: {e}")

        # ─── MASTER HOME GUIDE (FULL) ─────────────────────────
        print("\n--- Extracting Master Home Guide (full content) ---")
        await page.goto('https://app.ruebarue.com/master-home-guide', timeout=30000)
        await page.wait_for_load_state('domcontentloaded', timeout=15000)
        await asyncio.sleep(3)

        # Click through each category tab to get all items
        master_data = await page.evaluate('''() => {
            let categories = [];
            let tabs = document.querySelectorAll('.master-guide-tab a, .uk-tab a');
            tabs.forEach(tab => categories.push(tab.innerText.trim()));

            let items = [];
            let cards = document.querySelectorAll('.uk-card, .hms-property-card, [class*="guide-item"]');
            cards.forEach(card => {
                let title = '';
                let h = card.querySelector('h3, h4, h5, strong, b, .uk-card-title');
                if (h) title = h.innerText.trim();
                else {
                    let lines = card.innerText.trim().split('\\n');
                    title = lines[0] || '';
                }
                let content = card.innerText.trim();
                let links = [];
                card.querySelectorAll('a').forEach(a => {
                    if (a.href) links.push(a.href);
                });
                let imgs = [];
                card.querySelectorAll('img').forEach(img => {
                    if (img.src) imgs.push(img.src);
                });
                items.push({title, content, links, images: imgs});
            });

            return {categories, items};
        }''')

        print(f"  Master guide: {len(master_data.get('categories',[]))} categories, {len(master_data.get('items',[]))} items")

        # Click each category tab to get items from all categories
        tabs = await page.query_selector_all('.master-guide-tab a')
        all_master_items = []
        for tab in tabs:
            tab_name = await tab.inner_text()
            try:
                await tab.click()
                await asyncio.sleep(1.5)
                items = await page.evaluate('''() => {
                    let items = [];
                    let cards = document.querySelectorAll('.uk-card.hms-property-card');
                    cards.forEach(card => {
                        let content = card.innerText.trim();
                        let lines = content.split('\\n').filter(l => l.trim());
                        let title = lines[0] || '';
                        let body = lines.slice(1).join('\\n');
                        let links = [];
                        card.querySelectorAll('a').forEach(a => {
                            if (a.href && a.href.includes('ruebarue.com')) links.push(a.href);
                        });
                        items.push({title, content: body, links});
                    });
                    return items;
                }''')
                for item in items:
                    item['category'] = tab_name.strip()
                all_master_items.extend(items)
                print(f"  Category '{tab_name.strip()}': {len(items)} items")
            except Exception as e:
                print(f"  Tab error: {e}")

        static_data['master_guide_full'] = all_master_items

        # ─── EXTRAS GUIDE (FULL) ──────────────────────────────
        print("\n--- Extracting Extras Guide (full) ---")
        await page.goto('https://app.ruebarue.com/extras', timeout=30000)
        await page.wait_for_load_state('domcontentloaded', timeout=15000)
        await asyncio.sleep(2)

        extras = await page.evaluate('''() => {
            let items = [];
            let cards = document.querySelectorAll('.uk-card, .hms-property-card, [class*="extra"]');
            cards.forEach(card => {
                let content = card.innerText.trim();
                let lines = content.split('\\n').filter(l => l.trim());
                items.push({
                    title: lines[0] || '',
                    content: lines.slice(1).join('\\n'),
                });
            });
            // Also grab any tables
            let tables = document.querySelectorAll('table');
            tables.forEach(table => {
                let rows = table.querySelectorAll('tr');
                rows.forEach(row => {
                    let cells = row.querySelectorAll('td');
                    if (cells.length > 0) {
                        items.push({
                            title: cells[0]?.innerText.trim() || '',
                            content: Array.from(cells).slice(1).map(c => c.innerText.trim()).join(' | '),
                        });
                    }
                });
            });
            // Fallback to full page
            if (items.length === 0) {
                items.push({title: 'Full Page', content: document.querySelector('main')?.innerText || ''});
            }
            return items;
        }''')
        static_data['extras_full'] = extras
        print(f"  Extras: {len(extras)} items")

        # ─── GUESTS DATA ──────────────────────────────────────
        print("\n--- Extracting Guest data ---")
        await page.goto('https://app.ruebarue.com/guests?search_term=&filters=all&preset=all&page=0&per_page=100', timeout=30000)
        await page.wait_for_load_state('domcontentloaded', timeout=15000)
        await asyncio.sleep(2)

        guests_data = await page.evaluate('''() => {
            let guests = [];
            let rows = document.querySelectorAll('table tbody tr');
            rows.forEach(row => {
                let cells = row.querySelectorAll('td');
                if (cells.length >= 4) {
                    let guest = {
                        raw: cells[1]?.innerText.trim() || '',
                        property: cells[2]?.innerText.trim() || '',
                        actions: cells.length > 4 ? cells[4]?.innerText.trim() : '',
                    };
                    guests.push(guest);
                }
            });
            // Check pagination
            let pageInfo = document.querySelector('.uk-text-center, [class*="pagination"]');
            return {
                guests,
                total_text: pageInfo ? pageInfo.innerText.trim() : '',
                page_text: document.querySelector('main')?.innerText.substring(0, 2000) || '',
            };
        }''')
        print(f"  Guests: {len(guests_data.get('guests',[]))} rows visible")

        # Try to get all pages
        all_guests = guests_data.get('guests', [])
        page_num = 1
        while True:
            next_url = f'https://app.ruebarue.com/guests?search_term=&filters=all&preset=all&page={page_num}&per_page=100'
            await page.goto(next_url, timeout=20000)
            await page.wait_for_load_state('domcontentloaded', timeout=10000)
            await asyncio.sleep(1)
            more = await page.evaluate('''() => {
                let rows = document.querySelectorAll('table tbody tr');
                let data = [];
                rows.forEach(row => {
                    let cells = row.querySelectorAll('td');
                    if (cells.length >= 4) {
                        data.push({
                            raw: cells[1]?.innerText.trim() || '',
                            property: cells[2]?.innerText.trim() || '',
                        });
                    }
                });
                return data;
            }''')
            if not more:
                break
            all_guests.extend(more)
            page_num += 1
            print(f"  Page {page_num}: {len(more)} guests")
            if page_num > 50:
                break

        static_data['guests'] = all_guests

        # ─── PUBLIC GUIDES (HOME GUIDES) ──────────────────────
        print("\n--- Extracting Public Home Guides ---")
        home_guides = []
        for gid in GUESTBOOK_IDS:
            url = f'https://guide.ruebarue.com/guestbook/{gid}'
            try:
                await page.goto(url, timeout=30000)
                await page.wait_for_load_state('domcontentloaded', timeout=15000)
                await asyncio.sleep(2)

                guide_data = await page.evaluate('''() => {
                    let data = {sections: [], property_name: '', full_text: ''};

                    // Property name from title or header
                    let h1 = document.querySelector('h1, h2, .property-name, .guide-title');
                    data.property_name = h1 ? h1.innerText.trim() : document.title;

                    // Look for section containers
                    let sections = document.querySelectorAll('section, .guide-section, .uk-card, [class*="section"], [class*="item"], [class*="guide"]');
                    sections.forEach(sec => {
                        let heading = sec.querySelector('h2, h3, h4, h5, strong, .title');
                        let content = sec.innerText.trim();
                        if (content.length > 10) {
                            data.sections.push({
                                title: heading ? heading.innerText.trim() : '',
                                content: content,
                            });
                        }
                    });

                    // Also get images
                    let imgs = [];
                    document.querySelectorAll('img').forEach(img => {
                        if (img.src && !img.src.includes('logo')) imgs.push(img.src);
                    });
                    data.images = imgs;

                    // Full text fallback
                    data.full_text = document.body.innerText.substring(0, 50000);

                    return data;
                }''')

                home_guides.append({
                    'guestbook_id': gid,
                    'url': url,
                    'property_name': guide_data.get('property_name', ''),
                    'sections': guide_data.get('sections', []),
                    'images': guide_data.get('images', []),
                    'full_text': guide_data.get('full_text', ''),
                })
                print(f"  [{len(home_guides)}/13] {guide_data.get('property_name','?')}: {len(guide_data.get('sections',[]))} sections, {len(guide_data.get('full_text',''))} chars")
            except Exception as e:
                print(f"  Error on guide {gid}: {e}")
                home_guides.append({'guestbook_id': gid, 'url': url, 'error': str(e)})

        static_data['home_guides'] = home_guides

        # ─── AREA GUIDE ───────────────────────────────────────
        print("\n--- Extracting Area Guide ---")
        area_url = f'https://guide.ruebarue.com/destination/{AREA_GUIDE_ID}'
        await page.goto(area_url, timeout=30000)
        await page.wait_for_load_state('domcontentloaded', timeout=15000)
        await asyncio.sleep(2)

        area_data = await page.evaluate('''() => {
            let data = {sections: [], title: '', full_text: ''};
            let h1 = document.querySelector('h1, h2, .guide-title');
            data.title = h1 ? h1.innerText.trim() : document.title;

            let sections = document.querySelectorAll('section, .guide-section, .uk-card, [class*="section"], [class*="category"]');
            sections.forEach(sec => {
                let heading = sec.querySelector('h2, h3, h4, h5, strong');
                let content = sec.innerText.trim();
                if (content.length > 10) {
                    data.sections.push({
                        title: heading ? heading.innerText.trim() : '',
                        content: content,
                    });
                }
            });

            let imgs = [];
            document.querySelectorAll('img').forEach(img => {
                if (img.src && !img.src.includes('logo')) imgs.push(img.src);
            });
            data.images = imgs;
            data.full_text = document.body.innerText.substring(0, 50000);
            return data;
        }''')

        static_data['area_guide'] = {
            'url': area_url,
            'title': area_data.get('title', ''),
            'sections': area_data.get('sections', []),
            'images': area_data.get('images', []),
            'full_text': area_data.get('full_text', ''),
        }
        print(f"  Area guide: {len(area_data.get('sections',[]))} sections, {len(area_data.get('full_text',''))} chars")

        await browser.close()

    return static_data


def save_results(data):
    """Save all extracted data to JSON files."""
    ts = datetime.now().isoformat()

    # 1. FAQs
    faq_file = os.path.join(OUTPUT_DIR, 'ai_faqs.json')
    with open(faq_file, 'w') as f:
        json.dump({
            'extracted_at': ts,
            'count': len(data['faqs']),
            'faqs': data['faqs'],
        }, f, indent=2)
    print(f"Saved {len(data['faqs'])} FAQs -> {faq_file}")

    # 2. Scheduler
    sched_file = os.path.join(OUTPUT_DIR, 'scheduler.json')
    with open(sched_file, 'w') as f:
        json.dump({
            'extracted_at': ts,
            'count': len(data['scheduler']),
            'templates': data['scheduler'],
        }, f, indent=2)
    print(f"Saved {len(data['scheduler'])} scheduler templates -> {sched_file}")

    # 3. Saved Responses
    sr_file = os.path.join(OUTPUT_DIR, 'saved_responses.json')
    with open(sr_file, 'w') as f:
        json.dump({
            'extracted_at': ts,
            'count': len(data['saved_responses']),
            'responses': data['saved_responses'],
        }, f, indent=2)
    print(f"Saved {len(data['saved_responses'])} saved responses -> {sr_file}")

    # 4. Surveys
    survey_file = os.path.join(OUTPUT_DIR, 'surveys.json')
    with open(survey_file, 'w') as f:
        json.dump({
            'extracted_at': ts,
            'surveys': data['surveys'],
        }, f, indent=2)
    print(f"Saved surveys -> {survey_file}")

    # 5. Contacts
    contacts_file = os.path.join(OUTPUT_DIR, 'contacts.json')
    with open(contacts_file, 'w') as f:
        json.dump({
            'extracted_at': ts,
            'count': len(data['contacts']),
            'contacts': data['contacts'],
        }, f, indent=2)
    print(f"Saved {len(data['contacts'])} contacts -> {contacts_file}")

    # 6. Master Guide
    mg_file = os.path.join(OUTPUT_DIR, 'master_guide.json')
    master_items = data.get('master_guide_full', data['master_guide'].get('items', []))
    with open(mg_file, 'w') as f:
        json.dump({
            'extracted_at': ts,
            'categories': data['master_guide'].get('categories', []),
            'count': len(master_items),
            'items': master_items,
        }, f, indent=2)
    print(f"Saved {len(master_items)} master guide items -> {mg_file}")

    # 7. Extras
    extras_items = data.get('extras_full', data['extras'])
    extras_file = os.path.join(OUTPUT_DIR, 'extras.json')
    with open(extras_file, 'w') as f:
        json.dump({
            'extracted_at': ts,
            'count': len(extras_items),
            'items': extras_items,
        }, f, indent=2)
    print(f"Saved {len(extras_items)} extras -> {extras_file}")

    # 8. Home Guides
    hg_file = os.path.join(OUTPUT_DIR, 'home_guides.json')
    with open(hg_file, 'w') as f:
        json.dump({
            'extracted_at': ts,
            'count': len(data.get('home_guides', [])),
            'guides': data.get('home_guides', []),
        }, f, indent=2)
    print(f"Saved {len(data.get('home_guides',[]))} home guides -> {hg_file}")

    # 9. Area Guide
    ag_file = os.path.join(OUTPUT_DIR, 'area_guide.json')
    with open(ag_file, 'w') as f:
        json.dump({
            'extracted_at': ts,
            'guide': data.get('area_guide', {}),
        }, f, indent=2)
    print(f"Saved area guide -> {ag_file}")

    # 10. Guests
    guests_file = os.path.join(OUTPUT_DIR, 'guests.json')
    with open(guests_file, 'w') as f:
        json.dump({
            'extracted_at': ts,
            'count': len(data.get('guests', [])),
            'guests': data.get('guests', []),
        }, f, indent=2)
    print(f"Saved {len(data.get('guests',[]))} guests -> {guests_file}")


async def main(mode: str):
    start = time.time()
    print("=" * 60)
    print("RueBaRue Complete Data Extraction")
    print("=" * 60)
    print()

    # Phase 1: Parse HTML captures
    data = {}
    data['faqs'] = extract_faqs()
    data['scheduler'] = extract_scheduler()
    data['saved_responses'] = extract_saved_responses()
    data['surveys'] = extract_surveys()
    data['contacts'] = extract_contacts()
    data['master_guide'] = extract_master_guide()
    data['extras'] = extract_extras()
    data['home_guides_list'] = extract_home_guides_list()

    # Phase 2: Playwright for detail pages and public guides
    if mode == "full":
        if not RUEBARUE_EMAIL or not RUEBARUE_PASSWORD:
            raise RuntimeError("Missing RUEBARUE_EMAIL or RUEBARUE_PASSWORD environment variables for full extraction mode.")
        data = await extract_with_playwright(data)
    else:
        print("Skipping Playwright detail extraction (mode=html-only).")

    # Phase 3: Save everything
    print()
    print("=" * 60)
    print("Saving results...")
    print("=" * 60)
    save_results(data)

    elapsed = time.time() - start
    print(f"\nDone! Total time: {elapsed:.1f}s")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Canonical RueBaRue extraction pipeline.")
    parser.add_argument(
        "--mode",
        choices=["full", "html-only"],
        default="full",
        help="full: run HTML parse + Playwright; html-only: parse captured HTML only.",
    )
    args = parser.parse_args()
    asyncio.run(main(args.mode))
