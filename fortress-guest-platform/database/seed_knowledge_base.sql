-- ═══════════════════════════════════════════════════════════════
-- SEED: Knowledge Base - Property-Specific, Granular Information
-- ═══════════════════════════════════════════════════════════════
-- These entries power the Smart Concierge.
-- Property-specific entries (with property_id) override generic ones.
-- This is NOT canned content — it's the operational truth about each cabin.

-- GENERIC ENTRIES (apply to all properties)
-- ─────────────────────────────────────────

INSERT INTO knowledge_base_entries (id, category, question, answer, keywords, property_id, source, is_active)
VALUES
    -- CHECK-IN / CHECK-OUT
    (gen_random_uuid(), 'policy', 'What time is check-in?',
     'Check-in time is 4:00 PM. Your access code will be active starting at that time. If you arrive early, you can explore downtown Blue Ridge — it''s just a 10-15 minute drive from most of our cabins.',
     ARRAY['checkin', 'check-in', 'arrival', 'time', 'early'],
     NULL, 'manual', true),

    (gen_random_uuid(), 'policy', 'What time is checkout?',
     'Checkout time is 11:00 AM. Before leaving: lock all doors, turn off lights and fans, set thermostat to 72°F, start the dishwasher, take trash to the bear-proof container outside, and leave used towels in the bathtub. Please take all personal belongings — we''re happy to ship lost items but there is a handling fee.',
     ARRAY['checkout', 'check-out', 'departure', 'leaving', 'leave'],
     NULL, 'manual', true),

    (gen_random_uuid(), 'policy', 'Can I get late checkout?',
     'Late checkout until 2:00 PM is available for $75, subject to availability. There may not be availability if another guest is checking in the same day. Text or call us to request — we''ll do our best to accommodate you.',
     ARRAY['late', 'checkout', 'extend', 'stay longer'],
     NULL, 'manual', true),

    (gen_random_uuid(), 'policy', 'Can I check in early?',
     'Early check-in starting at 2:00 PM is available for $50, subject to availability. If the cabin is ready earlier, we''ll let you know. Request by texting or calling us at least 24 hours before your arrival.',
     ARRAY['early', 'checkin', 'check-in', 'arrive early'],
     NULL, 'manual', true),

    -- GENERAL CABIN INFO
    (gen_random_uuid(), 'faq', 'Is there cell service?',
     'Cell service in the mountains can be spotty, depending on your carrier. AT&T and Verizon tend to have the best coverage. All our cabins have WiFi, so you can use WiFi calling if needed. Some cabins have cell boosters installed.',
     ARRAY['cell', 'phone', 'service', 'signal', 'reception', 'coverage'],
     NULL, 'manual', true),

    (gen_random_uuid(), 'troubleshooting', 'The WiFi is not working',
     'Try these steps: 1) Make sure you''re connected to the correct network (check your portal for the exact name). 2) Restart the router — it''s usually in the living room area. Unplug it for 30 seconds, then plug back in. Wait 2-3 minutes for it to fully restart. 3) If it''s still not working, text us and we''ll troubleshoot remotely or send someone over.',
     ARRAY['wifi', 'internet', 'not working', 'slow', 'connection', 'router'],
     NULL, 'manual', true),

    (gen_random_uuid(), 'faq', 'Are pets allowed?',
     'Pet policies vary by cabin. Some of our properties are pet-friendly with a pet fee ($75-150). Check your booking confirmation for the pet policy for your specific cabin. If pets are not allowed at your cabin, we cannot make exceptions as it affects guests with allergies.',
     ARRAY['pets', 'dogs', 'animals', 'pet-friendly', 'pet fee'],
     NULL, 'manual', true),

    (gen_random_uuid(), 'faq', 'Where do I put the trash?',
     'All trash must go in the bear-proof container located outside the cabin (usually near the driveway or at the end of the driveway). This is critical — we''re in bear country and leaving trash on the deck or in open bins will attract bears. If you see a bear, do not approach it. Make noise and it will usually leave.',
     ARRAY['trash', 'garbage', 'bear', 'bears', 'recycle', 'disposal', 'waste'],
     NULL, 'manual', true),

    (gen_random_uuid(), 'faq', 'Is smoking allowed?',
     'Smoking is NOT allowed inside any of our cabins. This is strictly enforced — a $500 cleaning fee applies for any evidence of indoor smoking. You may smoke on the deck, but please use an ashtray and be mindful of fire risk, especially during dry seasons.',
     ARRAY['smoking', 'smoke', 'vape', 'cigarette'],
     NULL, 'manual', true),

    (gen_random_uuid(), 'faq', 'What are the quiet hours?',
     'Quiet hours are 10:00 PM to 8:00 AM. Please keep noise levels down during these hours out of respect for neighboring cabins and wildlife. Hot tub use is fine during quiet hours, just keep conversations at a reasonable level.',
     ARRAY['quiet', 'hours', 'noise', 'loud', 'music', 'party'],
     NULL, 'manual', true),

    -- AMENITIES (Generic)
    (gen_random_uuid(), 'property_info', 'How do I use the hot tub?',
     'Most of our hot tubs are pre-heated and ready to use. Remove the cover and fold it over using the cover lifter. The controls are usually on the side of the tub — press the jet button to turn on the jets. Temperature is pre-set to 102°F. After use, please replace the cover to retain heat. Do NOT adjust the temperature. If the hot tub seems cold or the jets aren''t working, text us.',
     ARRAY['hot tub', 'jacuzzi', 'tub', 'jets', 'spa', 'temperature'],
     NULL, 'manual', true),

    (gen_random_uuid(), 'property_info', 'How does the fireplace work?',
     'Fireplace type varies by cabin. Gas fireplaces: look for a wall switch or remote control, usually near the fireplace. Wood-burning fireplaces: firewood should be stocked on the deck. Use the fire starters provided and open the damper before lighting. Electric fireplaces: use the remote or buttons on the unit. Check your cabin''s specific guide for exact instructions.',
     ARRAY['fireplace', 'fire', 'wood', 'gas', 'flame', 'heat'],
     NULL, 'manual', true),

    (gen_random_uuid(), 'property_info', 'Where are extra towels and linens?',
     'Extra towels and linens are typically stored in the hallway closet, linen closet, or in the bedroom closet. Check the closets near the bathrooms first. If you can''t find them or need more, text us and we''ll arrange a delivery.',
     ARRAY['towels', 'linens', 'sheets', 'blankets', 'pillows', 'extra'],
     NULL, 'manual', true),

    (gen_random_uuid(), 'property_info', 'Is there a washer and dryer?',
     'Most of our cabins have a washer and dryer available for guest use. They''re typically located in a utility closet, laundry room, or sometimes in the garage. Detergent is usually provided — check the laundry area. If you can''t find the laundry, check your cabin guide or text us.',
     ARRAY['washer', 'dryer', 'laundry', 'wash', 'clothes', 'detergent'],
     NULL, 'manual', true),

    -- LOCAL AREA
    (gen_random_uuid(), 'area_info', 'Best restaurants in Blue Ridge?',
     'Our local favorites: **Harvest on Main** (upscale Southern, reservations recommended), **Toccoa Riverside Restaurant** (farm-to-table by the river), **The Boat Dock** (best lake views), **Masseria Kitchen** (incredible Italian), **Chester Brunnenmeyer''s Bar & Grill** (great burgers and beer), **Blue Ridge Brewery** (local craft beers). For breakfast: **Southern Charm** or **Blue Jeans Pizza** (yes, they do breakfast too). Most restaurants are 10-20 minutes from the cabins.',
     ARRAY['restaurant', 'food', 'eat', 'dinner', 'lunch', 'breakfast', 'dining'],
     NULL, 'manual', true),

    (gen_random_uuid(), 'area_info', 'What are the best hiking trails?',
     'Top trails near Blue Ridge: **Benton MacKaye Trail** (moderate, beautiful creek views), **Long Creek Falls** (easy 2-mile round trip to a waterfall), **Fall Branch Falls** (short but stunning), **Springer Mountain** (southern start of the Appalachian Trail), **Rich Mountain Wilderness** (challenging, great views). For families: the **Blue Ridge Scenic Railway** trail walk or **Mercier Orchards** has easy walking paths. Download the AllTrails app for navigation.',
     ARRAY['hiking', 'trails', 'hike', 'walk', 'nature', 'waterfalls', 'outdoors'],
     NULL, 'manual', true),

    (gen_random_uuid(), 'area_info', 'Where is the nearest grocery store?',
     'The nearest grocery stores to most of our cabins: **Ingles** in Blue Ridge (full grocery, about 10-15 min), **Dollar General** (usually the closest, 5-10 min for basics), **Walmart** in Blue Ridge (15-20 min). For local/specialty items: **Mercier Orchards** has an incredible farmstand with local produce, jams, and fried pies. **Blue Ridge Olive Oil Company** downtown is worth a visit.',
     ARRAY['grocery', 'store', 'food', 'shop', 'walmart', 'ingles', 'supplies'],
     NULL, 'manual', true),

    (gen_random_uuid(), 'area_info', 'What is there to do in Blue Ridge?',
     'Blue Ridge has something for everyone: **Downtown Blue Ridge** (shops, galleries, restaurants), **Blue Ridge Scenic Railway** (train ride along the river), **Lake Blue Ridge** (swimming, kayaking, fishing), **Toccoa River** (tubing in summer, fly fishing year-round), **Mercier Orchards** (apple picking in fall, wine tasting year-round), **Aska Adventure Area** (hiking, mountain biking), **Ocoee River** (whitewater rafting, 30 min away). In winter: nearby ski resorts are ~2 hours away.',
     ARRAY['things to do', 'activities', 'attractions', 'fun', 'entertainment', 'explore'],
     NULL, 'manual', true),

    (gen_random_uuid(), 'area_info', 'Where can we go swimming?',
     'Best swimming spots: **Lake Blue Ridge** (public beach area), **Toccoa River** (multiple swimming holes along Aska Rd), **Long Creek Falls** area has wade-in spots, **Lake Nottely** (20 min away, less crowded). The rivers are cold even in summer — that''s mountain water! If your cabin has a hot tub, that''s the warmest "swim" you''ll get. 🏊',
     ARRAY['swimming', 'swim', 'lake', 'river', 'water', 'beach', 'pool'],
     NULL, 'manual', true),

    -- SEASONAL (Winter)
    (gen_random_uuid(), 'area_info', 'What to do in Blue Ridge in winter?',
     'Winter in the mountains is magical. **Indoor options**: downtown shops and restaurants, wine tasting at local vineyards, Mercier Orchards cidery. **Outdoor**: winter hiking (the trails are less crowded and stunning), fishing on the Toccoa River. **Cozy cabin activities**: fireplace, hot tub under the stars, game room (if your cabin has one), movie nights. **Nearby skiing**: about 2 hours to resorts in NC. Pack layers — mountain weather can change quickly. Mornings can be in the 20s even when afternoons reach 50s.',
     ARRAY['winter', 'cold', 'snow', 'christmas', 'december', 'january', 'february', 'ski'],
     NULL, 'manual', true),

    -- SEASONAL (Summer)
    (gen_random_uuid(), 'area_info', 'What to do in Blue Ridge in summer?',
     'Summer is peak season! **Must-do**: tubing on the Toccoa River (rent tubes in town), kayaking/paddleboarding on Lake Blue Ridge, whitewater rafting on the Ocoee (30 min away), hiking to waterfalls (go early to beat the heat). **Family favorites**: Mercier Orchards (peach/blueberry picking), Blue Ridge Scenic Railway, swimming at the lake. **Pro tip**: make dinner reservations ahead — restaurants fill up fast in summer. Wear sunscreen and bug spray for outdoor activities.',
     ARRAY['summer', 'hot', 'june', 'july', 'august', 'tubing', 'swimming'],
     NULL, 'manual', true),

    -- TROUBLESHOOTING
    (gen_random_uuid(), 'troubleshooting', 'The power went out',
     'Power outages happen occasionally in the mountains, usually during storms. Here''s what to do: 1) Check if it''s just your cabin or the whole area (look at neighbors). 2) Do NOT open the fridge/freezer to keep food cold longer. 3) Use the flashlights in the kitchen drawer. 4) Text or call us — we''ll check with the power company and update you. Most outages are restored within 1-3 hours. The hot tub and any gas appliances may still work.',
     ARRAY['power', 'outage', 'electricity', 'lights', 'dark', 'generator'],
     NULL, 'manual', true),

    (gen_random_uuid(), 'troubleshooting', 'The hot tub is not hot',
     'If the hot tub seems cold: 1) Check if the cover was left off — it can lose heat quickly, especially in winter. 2) Make sure the breaker isn''t tripped — the hot tub breaker is usually on the deck or near the electrical panel. It''s a GFCI outlet that may have a red RESET button. 3) Replace the cover and give it 4-6 hours to reheat. 4) If it''s still cold after that, text us and we''ll send a technician. Do NOT adjust the temperature controls.',
     ARRAY['hot tub', 'cold', 'not hot', 'temperature', 'heat', 'broken'],
     NULL, 'manual', true),

    (gen_random_uuid(), 'troubleshooting', 'There is no hot water',
     'If you''re not getting hot water: 1) Check if the hot water heater needs a minute — if multiple showers/faucets were running, the tank may need to recover (wait 15-20 min). 2) Some cabins have tankless heaters — make sure the gas is on (check the propane gauge near the heater). 3) If only one bathroom has no hot water, the mixing valve may need adjustment — text us. 4) If none of the faucets have hot water, text us immediately and we''ll send someone.',
     ARRAY['hot water', 'no hot water', 'cold water', 'shower', 'water heater'],
     NULL, 'manual', true),

    (gen_random_uuid(), 'troubleshooting', 'I see a bear',
     'Bears are common in the North Georgia mountains. DO NOT approach, feed, or photograph them up close. Make noise (clap, yell "hey bear") and they usually leave. Make sure all food is inside and trash is in the bear-proof container. If a bear is on the deck or trying to get inside, call us immediately. Never run from a bear — back away slowly while facing it.',
     ARRAY['bear', 'bears', 'wildlife', 'animal', 'dangerous'],
     NULL, 'manual', true)

ON CONFLICT DO NOTHING;

-- Done
SELECT 'Knowledge base seeded with ' || count(*) || ' entries' FROM knowledge_base_entries WHERE is_active = true;
