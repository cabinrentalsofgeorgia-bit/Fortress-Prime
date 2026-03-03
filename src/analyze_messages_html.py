#!/usr/bin/env python3
"""
Analyze RueBaRue Messages HTML
Extract structure and data from captured messages page
"""

from bs4 import BeautifulSoup
import json
import re
from datetime import datetime

HTML_FILE = "/home/admin/Fortress-Prime/data/ruebarue_messages/20260217_101026_error.html"
OUTPUT_FILE = "/home/admin/Fortress-Prime/data/ruebarue_messages/messages_analysis.json"

print("="*80)
print("🔍 RueBaRue Messages HTML Analysis")
print("="*80)
print(f"Input: {HTML_FILE}")
print(f"Output: {OUTPUT_FILE}")
print("="*80)

# Load HTML
with open(HTML_FILE, 'r') as f:
    html = f.read()

soup = BeautifulSoup(html, 'html.parser')

print(f"\n✅ HTML loaded: {len(html)} characters")
print(f"   Title: {soup.title.string if soup.title else 'N/A'}")

# Find tables
tables = soup.find_all('table')
print(f"\n📋 Tables found: {len(tables)}")

analysis = {
    'timestamp': datetime.now().isoformat(),
    'file': HTML_FILE,
    'title': soup.title.string if soup.title else None,
    'tables': [],
    'message_elements': [],
    'pagination': {},
    'export_options': [],
    'total_count': None
}

for i, table in enumerate(tables):
    print(f"\n   Table {i+1}:")
    
    table_info = {
        'index': i+1,
        'headers': [],
        'row_count': 0,
        'sample_rows': []
    }
    
    # Get headers
    headers = []
    header_row = table.find('thead')
    if header_row:
        for th in header_row.find_all(['th', 'td']):
            header_text = th.get_text(strip=True)
            if header_text:
                headers.append(header_text)
    
    table_info['headers'] = headers
    print(f"      Headers: {headers}")
    
    # Get rows
    tbody = table.find('tbody')
    if tbody:
        rows = tbody.find_all('tr')
    else:
        rows = table.find_all('tr')
    
    # Filter out header rows
    data_rows = []
    for row in rows:
        cells = row.find_all('td')
        if cells:
            data_rows.append(row)
    
    table_info['row_count'] = len(data_rows)
    print(f"      Rows: {len(data_rows)}")
    
    # Sample first 5 rows
    for j, row in enumerate(data_rows[:5]):
        cells = row.find_all('td')
        row_data = []
        for cell in cells:
            cell_text = cell.get_text(strip=True)
            # Truncate long text
            if len(cell_text) > 100:
                cell_text = cell_text[:100] + "..."
            row_data.append(cell_text)
        
        table_info['sample_rows'].append(row_data)
        print(f"      Row {j+1}: {row_data}")
    
    analysis['tables'].append(table_info)

# Look for message/conversation elements
message_classes = ['conversation', 'message', 'chat', 'sms', 'text-message']
for cls in message_classes:
    elements = soup.find_all(class_=re.compile(cls, re.I))
    if elements:
        print(f"\n💬 Found {len(elements)} elements with class containing '{cls}'")
        analysis['message_elements'].append({
            'class_pattern': cls,
            'count': len(elements)
        })

# Look for pagination
pagination_keywords = ['pagination', 'pager', 'page', 'next', 'previous', 'prev']
pagination_elements = []

for keyword in pagination_keywords:
    elements = soup.find_all(class_=re.compile(keyword, re.I))
    if elements:
        pagination_elements.extend(elements)

# Also look for pagination in text
page_text = soup.get_text()
page_matches = re.findall(r'page\s+(\d+)\s+of\s+(\d+)', page_text.lower())
if page_matches:
    print(f"\n📄 Pagination found: Page {page_matches[0][0]} of {page_matches[0][1]}")
    analysis['pagination'] = {
        'current_page': int(page_matches[0][0]),
        'total_pages': int(page_matches[0][1])
    }
elif pagination_elements:
    print(f"\n📄 Pagination elements found: {len(pagination_elements)}")
    analysis['pagination'] = {
        'elements_found': len(pagination_elements),
        'has_pagination': True
    }
else:
    print(f"\n📄 No pagination detected")
    analysis['pagination'] = {'has_pagination': False}

# Look for total count
count_patterns = [
    r'(\d+)\s+total',
    r'(\d+)\s+messages?',
    r'(\d+)\s+conversations?',
    r'(\d+)\s+results?',
    r'showing\s+(\d+)',
]

for pattern in count_patterns:
    matches = re.findall(pattern, page_text.lower())
    if matches:
        print(f"\n📊 Count found: {matches[0]} (pattern: {pattern})")
        analysis['total_count'] = int(matches[0])
        break

# Look for export options
export_keywords = ['export', 'download', 'csv', 'excel', 'backup']
export_elements = []

for keyword in export_keywords:
    buttons = soup.find_all(['button', 'a'], text=re.compile(keyword, re.I))
    if buttons:
        for btn in buttons:
            btn_text = btn.get_text(strip=True)
            if btn_text:
                export_elements.append(btn_text)

if export_elements:
    print(f"\n📥 Export options found:")
    for opt in export_elements:
        print(f"   - {opt}")
    analysis['export_options'] = export_elements
else:
    print(f"\n📥 No export options found")

# Look for phone numbers
phone_pattern = r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b|\(\d{3}\)\s*\d{3}[-.]?\d{4}'
phones = re.findall(phone_pattern, page_text)
if phones:
    print(f"\n📱 Phone numbers found: {len(set(phones))} unique")
    print(f"   Sample: {list(set(phones))[:5]}")

# Look for dates
date_patterns = [
    r'\d{1,2}/\d{1,2}/\d{2,4}',
    r'\d{4}-\d{2}-\d{2}',
    r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4}',
]

dates_found = []
for pattern in date_patterns:
    dates = re.findall(pattern, page_text)
    dates_found.extend(dates)

if dates_found:
    print(f"\n📅 Dates found: {len(dates_found)}")
    print(f"   Sample: {dates_found[:5]}")

# Save analysis
with open(OUTPUT_FILE, 'w') as f:
    json.dump(analysis, f, indent=2)

print(f"\n💾 Analysis saved to: {OUTPUT_FILE}")

# Summary
print("\n" + "="*80)
print("📋 SUMMARY")
print("="*80)
print(f"Tables: {len(tables)}")
if tables:
    print(f"   Total rows: {sum(t['row_count'] for t in analysis['tables'])}")
    if analysis['tables'][0]['headers']:
        print(f"   Columns: {analysis['tables'][0]['headers']}")
print(f"Pagination: {analysis['pagination'].get('has_pagination', False)}")
if analysis['pagination'].get('total_pages'):
    print(f"   Total pages: {analysis['pagination']['total_pages']}")
print(f"Export options: {len(export_elements)}")
if analysis['total_count']:
    print(f"Total messages: {analysis['total_count']}")
print("="*80)
