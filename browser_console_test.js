/**
 * BROWSER CONSOLE TEST SCRIPT
 * 
 * Run this in your browser console (F12) while on localhost:9800
 * to verify the Command Center / VRS Hub split implementation.
 * 
 * Usage:
 * 1. Open http://localhost:9800 in browser
 * 2. Login if needed
 * 3. Press F12 to open DevTools
 * 4. Go to Console tab
 * 5. Copy/paste this entire script and press Enter
 * 6. Review the test results
 */

(async function runQATests() {
    console.clear();
    console.log('═══════════════════════════════════════════════════════════');
    console.log('  QA VERIFICATION: Command Center / VRS Hub Split');
    console.log('═══════════════════════════════════════════════════════════\n');
    
    const results = {
        passed: 0,
        failed: 0,
        warnings: 0,
        tests: []
    };
    
    function pass(test, message) {
        console.log(`✅ PASS - ${test}: ${message}`);
        results.passed++;
        results.tests.push({ test, status: 'PASS', message });
    }
    
    function fail(test, message) {
        console.log(`❌ FAIL - ${test}: ${message}`);
        results.failed++;
        results.tests.push({ test, status: 'FAIL', message });
    }
    
    function warn(test, message) {
        console.log(`⚠️  WARN - ${test}: ${message}`);
        results.warnings++;
        results.tests.push({ test, status: 'WARN', message });
    }
    
    // ─── TEST 1: Current Page Detection ───────────────────────────────────────
    console.log('\n─── TEST 1: Current Page Detection ───');
    
    const currentPath = window.location.pathname;
    const currentUrl = window.location.href;
    
    console.log(`Current URL: ${currentUrl}`);
    console.log(`Current Path: ${currentPath}`);
    
    if (currentPath === '/' || currentPath === '') {
        pass('1.1', 'On Command Center root page');
    } else if (currentPath === '/vrs') {
        pass('1.2', 'On VRS Hub page');
    } else if (currentPath.startsWith('/vrs/')) {
        warn('1.3', `On VRS sub-page: ${currentPath}`);
    } else {
        warn('1.4', `On other page: ${currentPath}`);
    }
    
    // ─── TEST 2: Page Title ───────────────────────────────────────────────────
    console.log('\n─── TEST 2: Page Title ───');
    
    const title = document.title.toLowerCase();
    console.log(`Page Title: "${document.title}"`);
    
    if (currentPath === '/' || currentPath === '') {
        if (title.includes('command center') || title.includes('fortress prime')) {
            pass('2.1', 'Command Center title detected');
        } else {
            fail('2.1', `Unexpected title for root: "${document.title}"`);
        }
    } else if (currentPath === '/vrs') {
        if (title.includes('vrs') || title.includes('vacation') || title.includes('crog')) {
            pass('2.2', 'VRS Hub title detected');
        } else {
            fail('2.2', `Unexpected title for VRS Hub: "${document.title}"`);
        }
    }
    
    // ─── TEST 3: Navigation Bar ───────────────────────────────────────────────
    console.log('\n─── TEST 3: Navigation Bar ───');
    
    const navBar = document.querySelector('.fn-bar');
    if (navBar) {
        pass('3.1', 'Fortress navigation bar found');
    } else {
        fail('3.1', 'Navigation bar not found (.fn-bar)');
    }
    
    const homeLink = document.querySelector('.fn-home, a[href="/"]');
    if (homeLink) {
        pass('3.2', 'Home/Command Center link found');
    } else {
        fail('3.2', 'Home link not found');
    }
    
    const vrsLinks = Array.from(document.querySelectorAll('a[href="/vrs"], a[href*="vrs"]'));
    if (vrsLinks.length > 0) {
        pass('3.3', `VRS navigation links found (${vrsLinks.length} links)`);
    } else {
        fail('3.3', 'No VRS navigation links found');
    }
    
    // ─── TEST 4: Content Analysis ─────────────────────────────────────────────
    console.log('\n─── TEST 4: Content Analysis ───');
    
    const bodyText = document.body.innerText.toLowerCase();
    const headings = Array.from(document.querySelectorAll('h1, h2, h3')).map(h => h.innerText.toLowerCase());
    
    console.log(`Headings found: ${headings.length}`);
    console.log('Sample headings:', headings.slice(0, 5));
    
    if (currentPath === '/' || currentPath === '') {
        // Command Center checks
        const systemIndicators = [
            'command center',
            'system health',
            'core services',
            'cluster',
            'infrastructure',
            'bare metal'
        ];
        
        const foundSystemIndicators = systemIndicators.filter(ind => bodyText.includes(ind));
        
        if (foundSystemIndicators.length > 0) {
            pass('4.1', `System-ops content found: ${foundSystemIndicators.join(', ')}`);
        } else {
            fail('4.1', 'No system-ops indicators found on Command Center');
        }
        
        // Check for VRS business content (should be minimal)
        const vrsBusinessIndicators = [
            'arrivals',
            'departures',
            'check-in',
            'check-out',
            'reservations',
            'properties'
        ];
        
        const foundVrsIndicators = vrsBusinessIndicators.filter(ind => bodyText.includes(ind));
        
        if (foundVrsIndicators.length <= 2) {
            pass('4.2', `Minimal VRS business content on root (${foundVrsIndicators.length} indicators)`);
        } else {
            fail('4.2', `Too much VRS business content on root: ${foundVrsIndicators.join(', ')}`);
        }
        
    } else if (currentPath === '/vrs') {
        // VRS Hub checks
        const vrsIndicators = [
            'crog-vrs',
            'vrs dashboard',
            'vacation rental',
            'properties',
            'reservations',
            'guests'
        ];
        
        const foundVrsIndicators = vrsIndicators.filter(ind => bodyText.includes(ind));
        
        if (foundVrsIndicators.length >= 3) {
            pass('4.3', `VRS content found: ${foundVrsIndicators.join(', ')}`);
        } else {
            fail('4.3', 'Insufficient VRS content on VRS Hub');
        }
        
        // Check for VRS operations panels
        const vrsOperations = [
            'arrival',
            'departure',
            'occupancy',
            'reservation'
        ];
        
        const foundOps = vrsOperations.filter(op => bodyText.includes(op));
        
        if (foundOps.length >= 2) {
            pass('4.4', `VRS operations panels found: ${foundOps.join(', ')}`);
        } else {
            warn('4.4', `Limited VRS operations content: ${foundOps.join(', ')}`);
        }
    }
    
    // ─── TEST 5: Quick Links / Cards ──────────────────────────────────────────
    console.log('\n─── TEST 5: Quick Links / Cards ───');
    
    const cards = document.querySelectorAll('.card, .quick-link, .stat-card, [class*="card"]');
    console.log(`Cards/quick links found: ${cards.length}`);
    
    if (cards.length > 0) {
        pass('5.1', `${cards.length} interactive cards found`);
        
        // Check if cards are clickable
        const clickableCards = Array.from(cards).filter(card => {
            return card.tagName === 'A' || 
                   card.onclick || 
                   card.querySelector('a') ||
                   card.style.cursor === 'pointer';
        });
        
        if (clickableCards.length > 0) {
            pass('5.2', `${clickableCards.length} clickable cards found`);
        } else {
            warn('5.2', 'Cards found but none appear clickable');
        }
    } else {
        warn('5.1', 'No cards/quick links found');
    }
    
    // ─── TEST 6: API Connectivity ─────────────────────────────────────────────
    console.log('\n─── TEST 6: API Connectivity ───');
    
    if (currentPath === '/vrs') {
        try {
            const response = await fetch('/api/vrs/properties', {
                credentials: 'include'
            });
            
            if (response.ok) {
                pass('6.1', `VRS API accessible (HTTP ${response.status})`);
            } else if (response.status === 401 || response.status === 403) {
                warn('6.1', `VRS API requires authentication (HTTP ${response.status})`);
            } else {
                fail('6.1', `VRS API error (HTTP ${response.status})`);
            }
        } catch (error) {
            fail('6.1', `VRS API connection failed: ${error.message}`);
        }
    }
    
    // ─── TEST 7: Console Errors ───────────────────────────────────────────────
    console.log('\n─── TEST 7: JavaScript Errors ───');
    
    // Note: This can't catch errors that happened before this script ran
    warn('7.1', 'Check browser console for any red error messages above');
    
    // ─── FINAL REPORT ─────────────────────────────────────────────────────────
    console.log('\n═══════════════════════════════════════════════════════════');
    console.log('  FINAL REPORT');
    console.log('═══════════════════════════════════════════════════════════\n');
    
    console.log(`✅ Passed: ${results.passed}`);
    console.log(`❌ Failed: ${results.failed}`);
    console.log(`⚠️  Warnings: ${results.warnings}`);
    console.log(`📊 Total Tests: ${results.tests.length}\n`);
    
    const passRate = Math.round((results.passed / results.tests.length) * 100);
    console.log(`Pass Rate: ${passRate}%\n`);
    
    if (results.failed === 0) {
        console.log('🎉 ALL CRITICAL TESTS PASSED!');
    } else {
        console.log(`⚠️  ${results.failed} TESTS FAILED - Review failures above`);
    }
    
    console.log('\n═══════════════════════════════════════════════════════════\n');
    
    // ─── NEXT STEPS ───────────────────────────────────────────────────────────
    console.log('NEXT STEPS:');
    console.log('1. Review any failures or warnings above');
    console.log('2. Test navigation: Click "VRS Hub" link (if on /) or "Command Center" link (if on /vrs)');
    console.log('3. Re-run this script on the other page');
    console.log('4. Click a few quick access cards to verify navigation');
    console.log('5. Check Network tab (F12 → Network) for failed API calls');
    
    return results;
})();
