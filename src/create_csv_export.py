#!/usr/bin/env python3
"""
Create CSV export from RueBaRue JSON data
"""

import json
import csv
from datetime import datetime

JSON_FILE = "/home/admin/Fortress-Prime/data/ruebarue_full_export.json"
CSV_FILE = "/home/admin/Fortress-Prime/data/ruebarue_conversations.csv"
MESSAGES_CSV = "/home/admin/Fortress-Prime/data/ruebarue_messages_detail.csv"

print("="*80)
print("📊 Creating CSV exports from RueBaRue data")
print("="*80)

# Load JSON
with open(JSON_FILE, 'r') as f:
    data = json.load(f)

print(f"\n✅ Loaded {data['total_conversations']} conversations")

# Create conversations CSV
print(f"\n📝 Creating conversations CSV: {CSV_FILE}")

with open(CSV_FILE, 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=[
        'guest_name', 'phone_number', 'property_name', 
        'last_message_preview', 'date', 'status', 'message_count'
    ])
    writer.writeheader()
    
    for conv in data['conversations']:
        writer.writerow({
            'guest_name': conv.get('guest_name', ''),
            'phone_number': conv.get('phone_number', ''),
            'property_name': conv.get('property_name', ''),
            'last_message_preview': conv.get('last_message_preview', ''),
            'date': conv.get('date', ''),
            'status': conv.get('status', ''),
            'message_count': len(conv.get('messages', []))
        })

print(f"✅ Created conversations CSV with {len(data['conversations'])} rows")

# Create detailed messages CSV (for conversations with full threads)
print(f"\n📝 Creating detailed messages CSV: {MESSAGES_CSV}")

message_rows = []
for conv in data['conversations']:
    if conv.get('messages'):
        for i, msg in enumerate(conv['messages']):
            message_rows.append({
                'guest_name': conv.get('guest_name', ''),
                'phone_number': conv.get('phone_number', ''),
                'property_name': conv.get('property_name', ''),
                'conversation_date': conv.get('date', ''),
                'message_number': i + 1,
                'message_text': msg.get('text', ''),
                'direction': msg.get('direction', ''),
                'timestamp': msg.get('timestamp', '')
            })

with open(MESSAGES_CSV, 'w', newline='', encoding='utf-8') as f:
    if message_rows:
        writer = csv.DictWriter(f, fieldnames=[
            'guest_name', 'phone_number', 'property_name', 'conversation_date',
            'message_number', 'message_text', 'direction', 'timestamp'
        ])
        writer.writeheader()
        writer.writerows(message_rows)

print(f"✅ Created messages CSV with {len(message_rows)} message rows")

print(f"\n{'='*80}")
print("✅ CSV EXPORT COMPLETE")
print(f"{'='*80}")
print(f"Conversations CSV: {CSV_FILE}")
print(f"Messages CSV: {MESSAGES_CSV}")
print(f"Total conversations: {len(data['conversations'])}")
print(f"Total messages: {len(message_rows)}")
print(f"{'='*80}")
