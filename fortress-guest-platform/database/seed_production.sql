-- ============================================================================
-- Fortress Guest Platform — Production Seed Data
-- Cabin Rentals of Georgia
-- ============================================================================
--
-- IMPORTANT: Properties, reservations, and guests are synced from Streamline
-- VRS automatically. Do NOT insert property or reservation data here.
-- This seed contains only business configuration that Streamline does not own:
--   - Staff users
--   - Message templates
--   - Universal guestbook guides (area info, house rules)
--   - AI knowledge base
--   - Extras / upsell marketplace
-- ============================================================================

-- ============================================================================
-- STAFF USERS
-- ============================================================================
INSERT INTO staff_users (email, password_hash, first_name, last_name, role, notification_email, notification_phone, notify_urgent, notify_workorders)
VALUES
    ('lissa@cabin-rentals-of-georgia.com', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyYIeWJ4.daa', 'Lissa', 'Knight', 'admin', 'lissa@cabin-rentals-of-georgia.com', '+17065255482', true, true),
    ('taylor.knight@cabin-rentals-of-georgia.com', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyYIeWJ4.daa', 'Taylor', 'Knight', 'admin', 'taylor.knight@cabin-rentals-of-georgia.com', '+17062588999', true, true)
ON CONFLICT (email) DO NOTHING;

-- ============================================================================
-- MESSAGE TEMPLATES
-- ============================================================================
INSERT INTO message_templates (name, category, body, variables, trigger_type, trigger_offset_days, trigger_time, is_active)
VALUES
    ('Pre-Arrival Welcome', 'pre_arrival',
     'Hi {{first_name}}! Your stay at {{property_name}} is coming up on {{check_in_date}}. Check-in starts at 4 PM. We''ll send your access code 4 hours before. Reply with any questions!',
     ARRAY['first_name', 'property_name', 'check_in_date'],
     'time_based', -1, '10:00:00', true),
    ('Access Code Delivery', 'checkin',
     'Hi {{first_name}}! Your access code for {{property_name}} is {{access_code}}. WiFi: {{wifi_ssid}} / Password: {{wifi_password}}. Check-in is at 4 PM. Enjoy your stay!',
     ARRAY['first_name', 'property_name', 'access_code', 'wifi_ssid', 'wifi_password'],
     'time_based', 0, '12:00:00', true),
    ('Mid-Stay Check-in', 'mid_stay',
     'Hi {{first_name}}! How''s everything at {{property_name}}? We want to make sure you''re having a great time. Let us know if there''s anything we can help with!',
     ARRAY['first_name', 'property_name'],
     'time_based', 2, '10:00:00', true),
    ('Checkout Reminder', 'checkout',
     'Hi {{first_name}}! Just a friendly reminder that checkout is at 11 AM today. Please: lock all doors, turn off lights, set thermostat to 72F, and start dishwasher. We''d love a review! Safe travels!',
     ARRAY['first_name'],
     'time_based', 0, '08:00:00', true),
    ('Post-Stay Review Request', 'post_stay',
     'Hi {{first_name}}! We hope you loved your time at {{property_name}}! Would you mind leaving us a review? It means the world to us. Thank you! {{review_link}}',
     ARRAY['first_name', 'property_name', 'review_link'],
     'time_based', 1, '10:00:00', true),
    ('Maintenance Acknowledgment', 'maintenance',
     'Thank you for letting us know, {{first_name}}! We''ve created a work order and our maintenance team will address this promptly. We apologize for the inconvenience.',
     ARRAY['first_name'],
     'event_based', NULL, NULL, true),
    ('Emergency Contact', 'emergency',
     'Hi {{first_name}}, we received your message and are treating it as urgent. Our emergency line is (706) 525-5482. For immediate danger, call 911. We''re on it!',
     ARRAY['first_name'],
     'event_based', NULL, NULL, true)
ON CONFLICT (name) DO NOTHING;

-- ============================================================================
-- GUESTBOOK GUIDES (universal — not property-specific)
-- ============================================================================
INSERT INTO guestbook_guides (property_id, title, slug, guide_type, category, content, icon, display_order, is_visible)
VALUES
    (NULL, 'Welcome to Blue Ridge', 'welcome-blue-ridge', 'area_guide', 'activities',
     '# Welcome to Blue Ridge, Georgia!\n\nBlue Ridge is a charming mountain town in the North Georgia mountains. Here are some highlights:\n\n## Top Activities\n- **Blue Ridge Scenic Railway** — vintage train ride through the mountains\n- **Mercier Orchards** — apple picking & farm market\n- **Toccoa River fishing** — excellent trout fishing\n- **Downtown Blue Ridge** — shops, restaurants, galleries\n\n## Dining\n- **Harvest on Main** — farm-to-table\n- **Toccoa Riverside Restaurant** — riverside dining\n- **The Dogwood** — craft cocktails & small plates\n\n## Emergency Numbers\n- 911 for emergencies\n- Cabin Rentals of Georgia: (706) 525-5482',
     '🏔️', 0, true),
    (NULL, 'House Rules', 'house-rules', 'home_guide', 'rules',
     '# House Rules\n\nPlease respect these guidelines for a pleasant stay:\n\n1. **Quiet Hours**: 10 PM - 8 AM\n2. **No Smoking**: All cabins are non-smoking (including e-cigarettes)\n3. **Pets**: Service animals only unless noted in listing\n4. **Fires**: Use fire pit only, no open fires. Ensure fire is fully extinguished\n5. **Trash**: Place in bear-proof containers outside\n6. **Hot Tub**: Cover when not in use, no glass near tub\n7. **Checkout**: 11 AM — start dishwasher, lock doors, thermostat to 72F\n\nThank you for being wonderful guests!',
     '📋', 1, true),
    (NULL, 'WiFi & Entertainment', 'wifi-entertainment', 'home_guide', 'wifi',
     '# WiFi & Entertainment\n\n## WiFi\nNetwork name and password are provided in your welcome message.\n\n## Smart TV\nAll cabins feature Smart TVs with:\n- Netflix (logged in)\n- YouTube\n- Disney+\n\nBring your own streaming credentials for other services.\n\n## Board Games\nCheck the living room closet for board games and cards!\n\n## Outdoor Fun\n- Fire pit with firewood (ask about purchasing more)\n- Hot tub (see instructions on tub cover)\n- Rocking chairs on the porch',
     '📶', 2, true),
    (NULL, 'Emergency Information', 'emergency-info', 'home_guide', 'emergency',
     '# Emergency Information\n\n## Immediate Danger: Call 911\n\n## Non-Emergency Contacts\n- **Cabin Rentals of Georgia**: (706) 525-5482 (24/7)\n- **Text Us**: +1 (706) 471-1479\n\n## Medical\n- **Blue Ridge Medical Center**: (706) 632-3711\n- **Fannin Regional Hospital**: 2855 Old Hwy 76, Blue Ridge\n\n## Utilities\n- **Power Outage**: Blue Ridge EMC (706) 632-3114\n- **Water Emergency**: Call property management\n\n## Bear Safety\n- Never leave food outside\n- Use bear-proof trash containers\n- If you see a bear, make noise and slowly back away',
     '🚨', 3, true)
ON CONFLICT DO NOTHING;

-- ============================================================================
-- AI KNOWLEDGE BASE ENTRIES
-- ============================================================================
INSERT INTO knowledge_base_entries (category, question, answer, keywords, is_active, source)
VALUES
    ('property_info', 'What is the WiFi password?',
     'The WiFi network name and password are unique to each cabin and are included in the check-in message sent 4 hours before arrival. If you haven''t received it, please reply to the check-in text.',
     ARRAY['wifi', 'internet', 'password', 'network'], true, 'manual'),
    ('property_info', 'How do I use the hot tub?',
     'The hot tub is pre-heated to 102°F. Remove the cover (fold in half), enjoy, and replace the cover when done. The remote/controls are usually on the tub edge. Never use glass near the hot tub. If the temperature seems off, let us know!',
     ARRAY['hot tub', 'jacuzzi', 'spa', 'temperature'], true, 'manual'),
    ('property_info', 'What is the checkout procedure?',
     'Checkout is at 11 AM. Please: 1) Start the dishwasher, 2) Place all trash in the bear-proof containers outside, 3) Turn off all lights, 4) Set the thermostat to 72°F, 5) Lock all doors, 6) Leave the key/close the lockbox. Thank you!',
     ARRAY['checkout', 'check out', 'leaving', 'depart'], true, 'manual'),
    ('area_info', 'Where is the nearest grocery store?',
     'The nearest grocery store is Ingles Market at 123 Main St, Blue Ridge (about 8 minutes). There''s also a Walmart Supercenter about 15 minutes away. For specialty items, check out the Blue Ridge Community Market on Saturdays!',
     ARRAY['grocery', 'store', 'food', 'supplies', 'walmart', 'ingles'], true, 'manual'),
    ('area_info', 'What restaurants are nearby?',
     'Great dining options near Blue Ridge: Harvest on Main (farm-to-table), Toccoa Riverside Restaurant (river views), The Dogwood (craft cocktails), Fightingtown Tavern (BBQ), and Chester Brunnenmeyer''s Bar & Grill. Most are 10-15 min drive.',
     ARRAY['restaurant', 'food', 'eat', 'dining', 'dinner', 'lunch'], true, 'manual'),
    ('area_info', 'What activities are available?',
     'Popular activities: Blue Ridge Scenic Railway (vintage train), Mercier Orchards (apple picking), hiking at Springer Mountain or Benton MacKaye Trail, tubing/kayaking on the Toccoa River, fishing, zip-lining at Blue Ridge Adventure Park, and browsing downtown shops and galleries.',
     ARRAY['activities', 'things to do', 'hiking', 'attractions', 'fun'], true, 'manual'),
    ('policy', 'What is the cancellation policy?',
     'Our standard cancellation policy: Full refund if cancelled 30+ days before check-in. 50% refund if cancelled 14-29 days before. No refund within 14 days of check-in. Some bookings through Airbnb/VRBO may have different policies — check your booking confirmation.',
     ARRAY['cancel', 'cancellation', 'refund', 'policy'], true, 'manual'),
    ('troubleshooting', 'The power is out',
     'If you experience a power outage: 1) Check if it''s just your cabin (look at neighbors), 2) If widespread, contact Blue Ridge EMC at (706) 632-3114, 3) If just your cabin, check the breaker panel (usually in the utility closet), 4) Text us immediately and we''ll help troubleshoot.',
     ARRAY['power', 'outage', 'electricity', 'dark', 'no power'], true, 'manual'),
    ('troubleshooting', 'Something is broken or not working',
     'Sorry to hear that! Please text us at +1 (706) 471-1479 with: 1) What''s broken or not working, 2) A photo if possible, 3) The urgency level. We''ll create a work order and get someone out as quickly as possible. For emergencies, call (706) 525-5482.',
     ARRAY['broken', 'not working', 'fix', 'repair', 'maintenance', 'issue'], true, 'manual'),
    ('faq', 'Is early check-in available?',
     'Early check-in depends on the previous guest''s checkout and our cleaning schedule. We can sometimes accommodate 2 PM arrivals (standard is 4 PM). Text us the day before your arrival and we''ll do our best!',
     ARRAY['early check-in', 'check in early', 'arrive early'], true, 'manual'),
    ('faq', 'Can we have a pet?',
     'Most of our cabins are pet-free to maintain a clean environment for guests with allergies. Service animals are always welcome. Some properties may allow pets with an additional fee — check your listing or contact us.',
     ARRAY['pet', 'dog', 'cat', 'animal', 'pet friendly'], true, 'manual'),
    ('faq', 'Where do I put the trash?',
     'All trash must go in the bear-proof containers located outside each cabin (usually near the driveway). Please ensure the container lid is fully closed and latched. This is critical — bears are active in the area! Never leave trash bags on the porch or deck.',
     ARRAY['trash', 'garbage', 'recycle', 'bear', 'waste'], true, 'manual')
ON CONFLICT DO NOTHING;

-- ============================================================================
-- EXTRAS (Upsell marketplace)
-- ============================================================================
INSERT INTO extras (name, description, category, price, is_available, display_order)
VALUES
    ('Firewood Bundle', 'Premium seasoned firewood — enough for 2 evenings of fire pit enjoyment', 'firewood', 35.00, true, 1),
    ('Late Checkout (2 PM)', 'Extend your stay until 2 PM instead of 11 AM', 'late_checkout', 75.00, true, 2),
    ('Early Check-in (2 PM)', 'Arrive at 2 PM instead of 4 PM (subject to availability)', 'early_checkin', 50.00, true, 3),
    ('Welcome Basket', 'Local treats, snacks, and a bottle of Georgia wine delivered to your cabin', 'amenity', 65.00, true, 4),
    ('Hot Tub Rose Petal Setup', 'Romantic hot tub setup with rose petals and LED candles', 'amenity', 45.00, true, 5),
    ('Birthday Decoration Pack', 'Happy birthday banner, balloons, and a small cake', 'celebration', 85.00, true, 6),
    ('Anniversary Package', 'Champagne, chocolates, flowers, and romantic cabin decoration', 'celebration', 125.00, true, 7),
    ('Professional Photographer (1hr)', 'Capture your mountain memories with a professional photo session', 'experience', 200.00, true, 8)
ON CONFLICT DO NOTHING;

-- ============================================================================
-- SEED COMPLETE
-- ============================================================================
-- Properties, reservations, and guests are managed by Streamline VRS sync.
-- See: backend/integrations/streamline_vrs.py
-- Sync runs every 5 minutes when STREAMLINE_API_KEY is configured.
-- ============================================================================
