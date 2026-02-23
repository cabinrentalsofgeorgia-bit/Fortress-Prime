/**
 * Fortress Guest Platform — Dashboard Application
 * Main application controller
 */
const FGP = {
    currentPage: 'dashboard',
    refreshInterval: null,
    data: {
        properties: [],
        guests: [],
        reservations: [],
        messages: [],
        workOrders: [],
        guides: [],
    },

    // ================================================================
    // INITIALIZATION
    // ================================================================
    init() {
        this.bindNavigation();
        this.bindActions();
        this.loadDashboard();

        // Auto-refresh every 30s
        this.refreshInterval = setInterval(() => {
            if (this.currentPage === 'dashboard') this.loadDashboard();
        }, 30000);

        // Check system health
        this.checkHealth();
    },

    // ================================================================
    // NAVIGATION
    // ================================================================
    bindNavigation() {
        document.querySelectorAll('.nav-item[data-page]').forEach(item => {
            item.addEventListener('click', (e) => {
                e.preventDefault();
                this.navigateTo(item.dataset.page);
            });
        });

        document.getElementById('sidebar-toggle')?.addEventListener('click', () => {
            document.getElementById('sidebar').classList.toggle('open');
        });
    },

    navigateTo(page) {
        // Update nav
        document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
        const navItem = document.querySelector(`.nav-item[data-page="${page}"]`);
        if (navItem) navItem.classList.add('active');

        // Switch page
        document.querySelectorAll('.page').forEach(el => el.classList.remove('active'));
        const pageEl = document.getElementById(`page-${page}`);
        if (pageEl) pageEl.classList.add('active');

        // Update title
        const titles = {
            dashboard: ['Command Center', 'Real-time operations overview'],
            messages: ['Messages', 'Guest conversations & SMS'],
            guests: ['Guests', 'Guest directory & management'],
            reservations: ['Reservations', 'Booking management'],
            properties: ['Properties', 'Cabin & property management'],
            workorders: ['Work Orders', 'Maintenance & issue tracking'],
            guestbook: ['Digital Guestbook', 'Guides & content management'],
            analytics: ['Analytics', 'Performance metrics & insights'],
            ai: ['AI Engine', 'Intelligent response management'],
            automation: ['Automation', 'Workflows & scheduled messages'],
            'review-queue': ['Review Queue', 'AI response approval & human-in-the-loop'],
            'damage-claims': ['Damage Claims', 'Post-checkout damage reporting & legal response'],
            integrations: ['Integrations', 'PMS connections & data sync'],
        };

        const [title, subtitle] = titles[page] || ['', ''];
        document.getElementById('page-heading').textContent = title;
        document.getElementById('page-subtitle').textContent = subtitle;

        this.currentPage = page;
        this.loadPageData(page);
    },

    loadPageData(page) {
        const loaders = {
            dashboard: () => this.loadDashboard(),
            messages: () => this.loadMessages(),
            guests: () => this.loadGuests(),
            reservations: () => this.loadReservations(),
            properties: () => this.loadProperties(),
            workorders: () => this.loadWorkOrders(),
            guestbook: () => this.loadGuestbook(),
            analytics: () => this.loadAnalytics(),
            'review-queue': () => loadReviewQueue(),
            'damage-claims': () => loadDamageClaims(),
            integrations: () => this.loadIntegrations(),
        };
        if (loaders[page]) loaders[page]();
    },

    // ================================================================
    // ACTIONS
    // ================================================================
    bindActions() {
        document.getElementById('refresh-btn')?.addEventListener('click', () => {
            this.loadPageData(this.currentPage);
            this.toast('Data refreshed', 'success');
        });

        document.getElementById('send-message-btn')?.addEventListener('click', () => this.handleSendMessage());
        document.getElementById('add-guest-btn')?.addEventListener('click', () => this.showAddGuestModal());
        document.getElementById('add-property-btn')?.addEventListener('click', () => this.showAddPropertyModal());
        document.getElementById('add-wo-btn')?.addEventListener('click', () => this.showAddWorkOrderModal());
        document.getElementById('add-res-btn')?.addEventListener('click', () => this.showAddReservationModal());

        // Confidence slider
        const slider = document.getElementById('ctrl-confidence');
        if (slider) {
            slider.addEventListener('input', (e) => {
                document.getElementById('ctrl-confidence-val').textContent = e.target.value + '%';
            });
        }
    },

    // ================================================================
    // DASHBOARD
    // ================================================================
    async loadDashboard() {
        try {
            // Load stats, properties, and messages in parallel
            const [properties, messages, workOrders] = await Promise.allSettled([
                api.getProperties(),
                api.getMessages({ limit: 20 }),
                api.getWorkOrders({ limit: 10 }),
            ]);

            if (properties.status === 'fulfilled') {
                this.data.properties = properties.value;
                this.renderPropertiesOverview(properties.value);
            }

            if (messages.status === 'fulfilled') {
                this.data.messages = messages.value;
                this.renderRecentMessages(messages.value);
                document.getElementById('stat-messages').textContent = messages.value.length || '0';
            }

            if (workOrders.status === 'fulfilled') {
                this.data.workOrders = workOrders.value;
                this.renderOpenWorkOrders(workOrders.value);
                const openCount = (workOrders.value || []).filter(w => w.status === 'open').length;
                document.getElementById('stat-open-workorders').textContent = openCount;
                document.getElementById('workorder-badge').textContent = openCount;
            }

            // Set stat defaults for demo
            this.updateDashboardStats();

        } catch (error) {
            console.error('Dashboard load error:', error);
        }
    },

    updateDashboardStats() {
        const stats = {
            'stat-arriving': '0',
            'stat-staying': this.data.properties.length.toString(),
            'stat-departing': '0',
            'stat-ai-responses': '0',
        };

        Object.entries(stats).forEach(([id, value]) => {
            const el = document.getElementById(id);
            if (el && el.textContent === '-') el.textContent = value;
        });
    },

    renderRecentMessages(messages) {
        const container = document.getElementById('recent-messages');
        if (!messages || messages.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <i data-lucide="message-square"></i>
                    <p>No messages yet. Send your first message!</p>
                </div>`;
            lucide.createIcons({ nameAttr: 'data-lucide' });
            return;
        }

        container.innerHTML = messages.slice(0, 10).map(msg => `
            <div class="conversation-item" onclick="FGP.navigateTo('messages')">
                <div class="conv-avatar">${this.getInitials(msg.phone_from)}</div>
                <div class="conv-info">
                    <span class="conv-name">${msg.phone_from || 'Unknown'}</span>
                    <span class="conv-preview">${this.truncate(msg.body, 50)}</span>
                </div>
                <div class="conv-meta">
                    <span class="conv-time">${this.timeAgo(msg.created_at)}</span>
                    ${msg.direction === 'inbound' ? '<span class="status-badge status-confirmed">IN</span>' : '<span class="status-badge status-completed">OUT</span>'}
                </div>
            </div>
        `).join('');
    },

    renderPropertiesOverview(properties) {
        const container = document.getElementById('properties-overview');
        if (!properties || properties.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <i data-lucide="home"></i>
                    <p>No properties found</p>
                </div>`;
            lucide.createIcons({ nameAttr: 'data-lucide' });
            return;
        }

        container.innerHTML = properties.map(p => `
            <div class="conversation-item" onclick="FGP.navigateTo('properties')">
                <div class="conv-avatar" style="background: rgba(16, 185, 129, 0.15); color: var(--brand-primary);">
                    ${p.property_type === 'cabin' ? '🏔️' : '🏠'}
                </div>
                <div class="conv-info">
                    <span class="conv-name">${p.name}</span>
                    <span class="conv-preview">${p.bedrooms}BR / ${p.bathrooms}BA / ${p.max_guests} guests</span>
                </div>
                <span class="status-badge ${p.is_active ? 'status-checked_in' : 'status-cancelled'}">${p.is_active ? 'Active' : 'Inactive'}</span>
            </div>
        `).join('');
    },

    renderOpenWorkOrders(workOrders) {
        const container = document.getElementById('open-workorders');
        const open = (workOrders || []).filter(w => w.status !== 'completed');

        if (open.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <i data-lucide="check-circle"></i>
                    <p>No open work orders</p>
                </div>`;
            lucide.createIcons({ nameAttr: 'data-lucide' });
            return;
        }

        container.innerHTML = open.map(wo => `
            <div class="conversation-item">
                <div class="conv-avatar" style="background: rgba(245, 158, 11, 0.15); color: var(--status-warning);">!</div>
                <div class="conv-info">
                    <span class="conv-name">${wo.title}</span>
                    <span class="conv-preview">${wo.category} - ${wo.priority}</span>
                </div>
                <span class="status-badge status-${wo.status}">${wo.status}</span>
            </div>
        `).join('');
    },

    // ================================================================
    // MESSAGES
    // ================================================================
    async loadMessages() {
        try {
            const messages = await api.getMessages({ limit: 50 });
            this.data.messages = messages;
            this.renderConversationList(messages);
        } catch (error) {
            console.error('Messages load error:', error);
            document.getElementById('conversation-list').innerHTML =
                '<div class="empty-state"><p>Could not load messages</p></div>';
        }
    },

    renderConversationList(messages) {
        const container = document.getElementById('conversation-list');
        if (!messages || messages.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <i data-lucide="message-square"></i>
                    <p>No conversations yet</p>
                </div>`;
            lucide.createIcons({ nameAttr: 'data-lucide' });
            return;
        }

        // Group by phone number (conversation threads)
        const threads = {};
        messages.forEach(msg => {
            const phone = msg.direction === 'inbound' ? msg.phone_from : msg.phone_to;
            if (!threads[phone]) threads[phone] = [];
            threads[phone].push(msg);
        });

        container.innerHTML = Object.entries(threads).map(([phone, msgs]) => {
            const last = msgs[0];
            const unread = msgs.filter(m => m.direction === 'inbound' && !m.read_at).length;
            return `
                <div class="conversation-item" onclick="FGP.openConversation('${phone}', this)">
                    <div class="conv-avatar">${this.getInitials(phone)}</div>
                    <div class="conv-info">
                        <span class="conv-name">${phone}</span>
                        <span class="conv-preview">${this.truncate(last.body, 40)}</span>
                    </div>
                    <div class="conv-meta">
                        <span class="conv-time">${this.timeAgo(last.created_at)}</span>
                        ${unread > 0 ? `<span class="conv-unread">${unread}</span>` : ''}
                    </div>
                </div>`;
        }).join('');
    },

    openConversation(phone, element) {
        // Highlight selected
        document.querySelectorAll('.conversation-item').forEach(el => el.classList.remove('active'));
        if (element) element.classList.add('active');

        // Show compose area
        document.getElementById('thread-compose').style.display = 'block';

        // Update header
        document.getElementById('thread-header').innerHTML = `
            <div class="thread-guest-info">
                <span class="thread-guest-name">${phone}</span>
            </div>`;

        // Filter messages for this conversation
        const msgs = this.data.messages.filter(m =>
            m.phone_from === phone || m.phone_to === phone
        ).reverse();

        const threadContainer = document.getElementById('thread-messages');
        if (msgs.length === 0) {
            threadContainer.innerHTML = '<div class="empty-state"><p>No messages</p></div>';
            return;
        }

        threadContainer.innerHTML = msgs.map(msg => `
            <div class="message-bubble message-${msg.direction}${msg.is_auto_response ? ' ai-reply' : ''}">
                <div>${msg.body}</div>
                <div class="message-time">${this.formatDate(msg.created_at)}</div>
                ${msg.is_auto_response ? '<div class="message-ai-badge">AI Generated</div>' : ''}
            </div>
        `).join('');

        // Scroll to bottom
        threadContainer.scrollTop = threadContainer.scrollHeight;

        // Update guest details panel
        this.updateGuestDetails(phone);
    },

    updateGuestDetails(phone) {
        const container = document.getElementById('guest-detail-content');
        const guest = this.data.guests.find(g => g.phone_number === phone);
        const msgs = this.data.messages.filter(m => m.phone_from === phone || m.phone_to === phone);

        container.innerHTML = `
            <div class="detail-section">
                <div class="detail-section-title">Contact</div>
                <div class="detail-row">
                    <span class="detail-label">Phone</span>
                    <span class="detail-value">${phone}</span>
                </div>
                ${guest ? `
                <div class="detail-row">
                    <span class="detail-label">Name</span>
                    <span class="detail-value">${guest.first_name || ''} ${guest.last_name || ''}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">Email</span>
                    <span class="detail-value">${guest.email || 'N/A'}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">Total Stays</span>
                    <span class="detail-value">${guest.total_stays || 0}</span>
                </div>
                ` : ''}
            </div>
            <div class="detail-section">
                <div class="detail-section-title">Statistics</div>
                <div class="detail-row">
                    <span class="detail-label">Total Messages</span>
                    <span class="detail-value">${msgs.length}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">Inbound</span>
                    <span class="detail-value">${msgs.filter(m => m.direction === 'inbound').length}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">Outbound</span>
                    <span class="detail-value">${msgs.filter(m => m.direction === 'outbound').length}</span>
                </div>
            </div>
            <div class="detail-section">
                <button class="btn btn-primary" style="width:100%" onclick="FGP.navigateTo('guests')">
                    View Full Profile
                </button>
            </div>`;
    },

    async handleSendMessage() {
        const textarea = document.getElementById('compose-message');
        const body = textarea.value.trim();
        if (!body) return;

        const activeConv = document.querySelector('.conversation-item.active .conv-name');
        if (!activeConv) {
            this.toast('Select a conversation first', 'warning');
            return;
        }

        const phone = activeConv.textContent;

        try {
            await api.sendMessage({ to_phone: phone, body });
            textarea.value = '';
            this.toast('Message sent', 'success');
            this.loadMessages();
        } catch (error) {
            this.toast('Failed to send message: ' + error.message, 'error');
        }
    },

    // ================================================================
    // GUESTS (Enterprise Guest Management)
    // ================================================================
    async loadGuests() {
        try {
            // Load analytics and guests in parallel
            const [analytics, guests] = await Promise.all([
                api.getGuestAnalytics(30).catch(() => null),
                api.getGuests({ limit: 200, sort_by: this._guestSort || 'created_at', sort_dir: 'desc' }),
            ]);
            this.data.guests = guests;
            this.renderGuestAnalytics(analytics);
            this.renderGuestsTable(guests);
            this.bindGuestFilters();
        } catch (error) {
            console.error('Guests load error:', error);
        }
    },

    renderGuestAnalytics(a) {
        if (!a) return;
        const el = (id, val) => { const e = document.getElementById(id); if (e) e.textContent = val; };
        el('ga-total', a.total_guests || 0);
        el('ga-repeat', a.repeat_guests || 0);
        el('ga-vip', a.vip_count || 0);
        el('ga-repeat-rate', (a.repeat_rate || 0) + '%');
        el('ga-avg-ltv', '$' + (a.avg_lifetime_value || 0).toLocaleString());
        el('ga-avg-value', (a.avg_value_score || 0) + '/100');
    },

    bindGuestFilters() {
        const search = document.getElementById('guest-search');
        const filter = document.getElementById('guest-filter');
        const tierFilter = document.getElementById('guest-tier-filter');
        const sort = document.getElementById('guest-sort');

        const applyFilters = () => {
            let guests = [...this.data.guests];
            const term = (search?.value || '').toLowerCase();
            const flt = filter?.value || 'all';
            const tier = tierFilter?.value || '';

            if (term) {
                guests = guests.filter(g =>
                    (g.full_name || '').toLowerCase().includes(term) ||
                    (g.phone_number || '').includes(term) ||
                    (g.email || '').toLowerCase().includes(term)
                );
            }
            if (flt === 'vip') guests = guests.filter(g => g.is_vip);
            if (flt === 'repeat') guests = guests.filter(g => g.is_repeat_guest);
            if (flt === 'blacklisted') guests = guests.filter(g => g.is_blacklisted);
            if (flt === 'verified') guests = guests.filter(g => g.verification_status === 'verified');
            if (flt === 'unverified') guests = guests.filter(g => g.verification_status === 'unverified');
            if (tier) guests = guests.filter(g => g.loyalty_tier === tier);

            this.renderGuestsTable(guests);
        };

        if (search) search.oninput = applyFilters;
        if (filter) filter.onchange = applyFilters;
        if (tierFilter) tierFilter.onchange = applyFilters;
        if (sort) sort.onchange = () => { this._guestSort = sort.value; this.loadGuests(); };
    },

    renderGuestsTable(guests) {
        const tbody = document.getElementById('guests-tbody');
        if (!guests || guests.length === 0) {
            tbody.innerHTML = '<tr><td colspan="10" class="empty-state">No guests found. Add your first guest!</td></tr>';
            return;
        }

        const tierColors = { diamond: '#a855f7', platinum: '#6366f1', gold: '#f59e0b', silver: '#94a3b8', bronze: '#d97706' };
        const tierIcons = { diamond: '💎', platinum: '🏆', gold: '🥇', silver: '🥈', bronze: '🥉' };

        tbody.innerHTML = guests.map(g => {
            const tier = g.loyalty_tier || 'bronze';
            const flags = [];
            if (g.is_vip) flags.push('<span class="guest-flag flag-vip">VIP</span>');
            if (g.is_blacklisted) flags.push('<span class="guest-flag flag-blacklist">BLOCKED</span>');
            if (g.is_verified) flags.push('<span class="guest-flag flag-verified">✓</span>');
            if (g.is_repeat_guest) flags.push('<span class="guest-flag flag-repeat">REPEAT</span>');

            const valueColor = (g.value_score || 50) >= 70 ? '#10b981' : (g.value_score || 50) >= 40 ? '#f59e0b' : '#ef4444';
            const riskColor = (g.risk_score || 10) <= 30 ? '#10b981' : (g.risk_score || 10) <= 60 ? '#f59e0b' : '#ef4444';

            return `<tr class="${g.is_blacklisted ? 'row-blacklisted' : ''}">
                <td>
                    <div style="display:flex;align-items:center;gap:10px;">
                        <div class="avatar avatar-tier-${tier}" style="width:32px;height:32px;font-size:11px;">${this.getInitials(g.full_name || 'G')}</div>
                        <div>
                            <div style="font-weight:600;">${g.full_name || 'Unknown'} ${flags.join(' ')}</div>
                            <div style="font-size:11px;color:var(--text-muted);">${g.email || ''}</div>
                        </div>
                    </div>
                </td>
                <td style="font-family:monospace;font-size:12px;">${g.phone_number}</td>
                <td><span class="tier-badge tier-${tier}">${tierIcons[tier] || ''} ${tier}</span></td>
                <td style="font-weight:600;">${g.total_stays || 0}</td>
                <td>$${(g.lifetime_revenue || 0).toLocaleString()}</td>
                <td><span class="score-pill" style="background:${valueColor}20;color:${valueColor};">${g.value_score || 50}</span></td>
                <td><span class="score-pill" style="background:${riskColor}20;color:${riskColor};">${g.risk_score || 10}</span></td>
                <td style="font-size:11px;">${g.guest_source || '-'}</td>
                <td><span class="status-badge status-${g.verification_status || 'unverified'}">${g.verification_status || 'unverified'}</span></td>
                <td>
                    <div style="display:flex;gap:4px;">
                        <button class="btn btn-sm" onclick="FGP.viewGuest360('${g.id}')" title="360° Profile">360°</button>
                        <button class="btn btn-sm btn-outline" onclick="FGP.toggleGuestVIP('${g.id}', ${!g.is_vip})" title="${g.is_vip ? 'Remove VIP' : 'Make VIP'}">${g.is_vip ? '⭐' : '☆'}</button>
                    </div>
                </td>
            </tr>`;
        }).join('');
    },

    async viewGuest360(guestId) {
        try {
            const data = await api.getGuest360(guestId);
            if (!data) return this.toast('Guest not found', 'error');
            const p = data.profile;
            const l = data.loyalty;
            const s = data.scoring;
            const st = data.stats;
            const flags = data.flags;

            const tierColors = { diamond: '#a855f7', platinum: '#6366f1', gold: '#f59e0b', silver: '#94a3b8', bronze: '#d97706' };
            const tc = tierColors[l.tier] || '#d97706';

            const activityHtml = (data.recent_activity || []).slice(0, 10).map(a =>
                `<div class="timeline-item">
                    <div class="timeline-dot" style="background:${a.importance === 'critical' ? '#ef4444' : a.importance === 'high' ? '#f59e0b' : '#10b981'}"></div>
                    <div class="timeline-content">
                        <div class="timeline-title">${a.title}</div>
                        <div class="timeline-meta">${a.category} &middot; ${new Date(a.created_at).toLocaleDateString()}</div>
                    </div>
                </div>`
            ).join('') || '<div class="empty-state">No activity yet</div>';

            const reservationsHtml = (data.reservations || []).slice(0, 5).map(r =>
                `<div class="mini-card">
                    <strong>${r.confirmation_code}</strong>
                    <span class="status-badge status-${r.status}">${r.status}</span>
                    <span>${r.check_in} → ${r.check_out}</span>
                    <span>$${(r.total_amount || 0).toLocaleString()}</span>
                </div>`
            ).join('') || '<div class="empty-state">No reservations</div>';

            this.showModal('360° Guest Profile', `
                <div class="guest-360-modal">
                    <div class="g360-header" style="border-left: 4px solid ${tc};">
                        <div class="g360-avatar avatar-tier-${l.tier}">${this.getInitials(p.full_name || 'G')}</div>
                        <div class="g360-info">
                            <h2>${p.full_name} ${flags.is_vip ? '<span class="guest-flag flag-vip">VIP</span>' : ''} ${flags.is_blacklisted ? '<span class="guest-flag flag-blacklist">BLOCKED</span>' : ''}</h2>
                            <div>${p.phone_number} &middot; ${p.email || 'No email'}</div>
                            <div>${p.address || 'No address'}</div>
                            <div class="tier-badge tier-${l.tier}" style="margin-top:6px;">${l.display_tier} Tier &middot; ${l.loyalty_points} pts</div>
                        </div>
                        <div class="g360-scores">
                            <div class="score-circle" style="border-color:${(s.value_score || 50) >= 70 ? '#10b981' : '#f59e0b'}">
                                <span>${s.value_score || 50}</span>
                                <small>Value</small>
                            </div>
                            <div class="score-circle" style="border-color:${(s.risk_score || 10) <= 30 ? '#10b981' : '#ef4444'}">
                                <span>${s.risk_score || 10}</span>
                                <small>Risk</small>
                            </div>
                        </div>
                    </div>

                    <div class="g360-stats">
                        <div class="stat"><span>${st.total_reservations || 0}</span><small>Reservations</small></div>
                        <div class="stat"><span>${st.total_nights || 0}</span><small>Nights</small></div>
                        <div class="stat"><span>$${(st.total_revenue || 0).toLocaleString()}</span><small>Revenue</small></div>
                        <div class="stat"><span>${st.avg_stay_length || 0}</span><small>Avg Nights</small></div>
                        <div class="stat"><span>${data.messages?.total_messages || 0}</span><small>Messages</small></div>
                        <div class="stat"><span>${l.lifetime_stays || 0}</span><small>Stays</small></div>
                    </div>

                    <div class="g360-sections">
                        <div class="g360-section">
                            <h3>Reservations</h3>
                            ${reservationsHtml}
                        </div>
                        <div class="g360-section">
                            <h3>Activity Timeline</h3>
                            <div class="timeline">${activityHtml}</div>
                        </div>
                    </div>

                    ${data.vehicle?.description ? `<div class="g360-detail"><strong>Vehicle:</strong> ${data.vehicle.description}</div>` : ''}
                    ${data.emergency_contact?.name ? `<div class="g360-detail"><strong>Emergency:</strong> ${data.emergency_contact.name} (${data.emergency_contact.phone})</div>` : ''}
                    ${p.special_requests ? `<div class="g360-detail"><strong>Special Requests:</strong> ${p.special_requests}</div>` : ''}
                </div>
            `, 'modal-xl');
        } catch (error) {
            this.toast('Error loading guest profile: ' + error.message, 'error');
        }
    },

    async toggleGuestVIP(guestId, isVip) {
        try {
            await api.toggleVIP(guestId, isVip);
            this.toast(isVip ? 'Guest marked as VIP' : 'VIP status removed', 'success');
            this.loadGuests();
        } catch (error) {
            this.toast('Error: ' + error.message, 'error');
        }
    },

    // ================================================================
    // RESERVATIONS
    // ================================================================
    async loadReservations() {
        try {
            const reservations = await api.getReservations({ limit: 100 });
            this.data.reservations = reservations;
            this.renderReservationsTable(reservations);
        } catch (error) {
            console.error('Reservations load error:', error);
        }
    },

    renderReservationsTable(reservations) {
        const tbody = document.getElementById('reservations-tbody');
        if (!reservations || reservations.length === 0) {
            tbody.innerHTML = '<tr><td colspan="8" class="empty-state">No reservations found</td></tr>';
            return;
        }

        tbody.innerHTML = reservations.map(r => `
            <tr>
                <td><strong>${r.confirmation_code}</strong></td>
                <td>${r.guest_id ? r.guest_id.substring(0, 8) + '...' : 'Unknown'}</td>
                <td>${r.property_id ? r.property_id.substring(0, 8) + '...' : 'Unknown'}</td>
                <td>${r.check_in_date}</td>
                <td>${r.check_out_date}</td>
                <td><span class="status-badge status-${r.status}">${r.status}</span></td>
                <td>
                    ${r.pre_arrival_sent ? '✅' : '⬜'} Pre
                    ${r.access_info_sent ? '✅' : '⬜'} Access
                    ${r.mid_stay_checkin_sent ? '✅' : '⬜'} Mid
                </td>
                <td>
                    <button class="btn btn-sm" onclick="FGP.viewReservation('${r.id}')">View</button>
                </td>
            </tr>
        `).join('');
    },

    // ================================================================
    // PROPERTIES
    // ================================================================
    async loadProperties() {
        try {
            const properties = await api.getProperties();
            this.data.properties = properties;
            this.renderPropertiesGrid(properties);
        } catch (error) {
            console.error('Properties load error:', error);
        }
    },

    renderPropertiesGrid(properties) {
        const container = document.getElementById('properties-grid');
        if (!properties || properties.length === 0) {
            container.innerHTML = '<div class="empty-state"><p>No properties found</p></div>';
            return;
        }

        container.innerHTML = properties.map(p => `
            <div class="property-card">
                <div class="property-header">
                    <span class="property-name">${p.name}</span>
                    <span class="property-type">${p.property_type}</span>
                </div>
                <div style="color:var(--text-muted);font-size:12px;">
                    ${p.wifi_ssid ? '📶 WiFi: ' + p.wifi_ssid : ''}<br>
                    ${p.access_code_type ? '🔑 ' + p.access_code_type : ''}
                </div>
                <div class="property-stats">
                    <div class="property-stat">
                        <div class="property-stat-value">${p.bedrooms}</div>
                        <div class="property-stat-label">Bedrooms</div>
                    </div>
                    <div class="property-stat">
                        <div class="property-stat-value">${p.bathrooms}</div>
                        <div class="property-stat-label">Bathrooms</div>
                    </div>
                    <div class="property-stat">
                        <div class="property-stat-value">${p.max_guests}</div>
                        <div class="property-stat-label">Max Guests</div>
                    </div>
                </div>
            </div>
        `).join('');
    },

    // ================================================================
    // WORK ORDERS
    // ================================================================
    async loadWorkOrders() {
        try {
            const workOrders = await api.getWorkOrders({ limit: 50 });
            this.data.workOrders = workOrders;
            this.renderWorkOrdersBoard(workOrders);
        } catch (error) {
            console.error('Work orders load error:', error);
        }
    },

    renderWorkOrdersBoard(workOrders) {
        const container = document.getElementById('workorders-board');
        const columns = {
            open: { title: 'Open', color: 'var(--status-warning)', items: [] },
            in_progress: { title: 'In Progress', color: 'var(--status-info)', items: [] },
            waiting_parts: { title: 'Waiting', color: 'var(--status-purple)', items: [] },
            completed: { title: 'Completed', color: 'var(--status-success)', items: [] },
        };

        (workOrders || []).forEach(wo => {
            if (columns[wo.status]) columns[wo.status].items.push(wo);
        });

        container.innerHTML = Object.entries(columns).map(([status, col]) => `
            <div class="wo-column">
                <div class="wo-column-header">
                    <span class="wo-column-title" style="color:${col.color}">${col.title}</span>
                    <span class="wo-column-count">${col.items.length}</span>
                </div>
                <div class="wo-column-body">
                    ${col.items.length === 0
                        ? '<div class="empty-state" style="padding:20px;"><p style="font-size:11px;">No items</p></div>'
                        : col.items.map(wo => `
                            <div class="wo-card" onclick="FGP.viewWorkOrder('${wo.id}')">
                                <div class="wo-card-title">${wo.title}</div>
                                <div class="wo-card-meta">
                                    <span class="priority-${wo.priority}">${wo.priority}</span>
                                    <span>${wo.category}</span>
                                </div>
                            </div>
                        `).join('')
                    }
                </div>
            </div>
        `).join('');
    },

    // ================================================================
    // GUESTBOOK
    // ================================================================
    async loadGuestbook() {
        try {
            const guides = await api.getGuides();
            this.data.guides = guides;
            this.renderGuidesGrid(guides);
        } catch (error) {
            console.error('Guestbook load error:', error);
        }
    },

    renderGuidesGrid(guides) {
        const container = document.getElementById('guides-grid');
        if (!guides || guides.length === 0) {
            container.innerHTML = `
                <div class="empty-state" style="grid-column:1/-1;">
                    <i data-lucide="book-open"></i>
                    <p>No guides yet. Create your first digital guide!</p>
                    <button class="btn btn-primary" onclick="FGP.showAddGuideModal()">Create Guide</button>
                </div>`;
            lucide.createIcons({ nameAttr: 'data-lucide' });
            return;
        }

        const icons = { wifi: '📶', rules: '📋', amenities: '🏊', restaurants: '🍽️', emergency: '🚨', activities: '🎣', default: '📄' };

        container.innerHTML = guides.map(g => `
            <div class="guide-card">
                <div class="guide-icon">${icons[g.category] || icons.default}</div>
                <div class="guide-title">${g.title}</div>
                <div class="guide-type">${g.guide_type} ${g.category ? '/ ' + g.category : ''}</div>
                <div class="guide-views">
                    <i data-lucide="eye" style="width:12px;height:12px;"></i>
                    ${g.view_count || 0} views
                </div>
            </div>
        `).join('');
        lucide.createIcons({ nameAttr: 'data-lucide' });
    },

    // ================================================================
    // ANALYTICS
    // ================================================================
    async loadAnalytics() {
        // Analytics data is rendered statically for now
        // Will be enhanced with real chart data
    },

    // ================================================================
    // MODALS
    // ================================================================
    showModal(title, bodyHTML, footerHTML = '') {
        document.getElementById('modal-title').textContent = title;
        document.getElementById('modal-body').innerHTML = bodyHTML;
        document.getElementById('modal-footer').innerHTML = footerHTML;
        document.getElementById('modal-overlay').style.display = 'flex';
        lucide.createIcons({ nameAttr: 'data-lucide' });
    },

    closeModal() {
        document.getElementById('modal-overlay').style.display = 'none';
    },

    showAddGuestModal() {
        this.showModal('Add New Guest', `
            <div class="form-group">
                <label class="form-label">First Name</label>
                <input class="form-input" id="m-guest-first" placeholder="First name">
            </div>
            <div class="form-group">
                <label class="form-label">Last Name</label>
                <input class="form-input" id="m-guest-last" placeholder="Last name">
            </div>
            <div class="form-group">
                <label class="form-label">Phone Number (E.164)</label>
                <input class="form-input" id="m-guest-phone" placeholder="+17065551234">
            </div>
            <div class="form-group">
                <label class="form-label">Email</label>
                <input class="form-input" id="m-guest-email" placeholder="guest@example.com">
            </div>
        `, `
            <button class="btn" onclick="FGP.closeModal()">Cancel</button>
            <button class="btn btn-primary" onclick="FGP.saveGuest()">Save Guest</button>
        `);
    },

    async saveGuest() {
        const data = {
            first_name: document.getElementById('m-guest-first').value,
            last_name: document.getElementById('m-guest-last').value,
            phone_number: document.getElementById('m-guest-phone').value,
            email: document.getElementById('m-guest-email').value,
        };

        if (!data.phone_number) {
            this.toast('Phone number is required', 'error');
            return;
        }

        try {
            await api.createGuest(data);
            this.closeModal();
            this.toast('Guest created successfully', 'success');
            this.loadGuests();
        } catch (error) {
            this.toast('Error: ' + error.message, 'error');
        }
    },

    showAddPropertyModal() {
        this.showModal('Add New Property', `
            <div class="form-group">
                <label class="form-label">Property Name</label>
                <input class="form-input" id="m-prop-name" placeholder="Cabin name">
            </div>
            <div class="form-group">
                <label class="form-label">Property Type</label>
                <select class="form-select" id="m-prop-type">
                    <option value="cabin">Cabin</option>
                    <option value="cottage">Cottage</option>
                    <option value="house">House</option>
                </select>
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;">
                <div class="form-group">
                    <label class="form-label">Bedrooms</label>
                    <input class="form-input" id="m-prop-bed" type="number" value="2">
                </div>
                <div class="form-group">
                    <label class="form-label">Bathrooms</label>
                    <input class="form-input" id="m-prop-bath" type="number" step="0.5" value="1.5">
                </div>
                <div class="form-group">
                    <label class="form-label">Max Guests</label>
                    <input class="form-input" id="m-prop-guests" type="number" value="6">
                </div>
            </div>
            <div class="form-group">
                <label class="form-label">WiFi SSID</label>
                <input class="form-input" id="m-prop-wifi" placeholder="WiFi network name">
            </div>
            <div class="form-group">
                <label class="form-label">WiFi Password</label>
                <input class="form-input" id="m-prop-wifipass" placeholder="WiFi password">
            </div>
        `, `
            <button class="btn" onclick="FGP.closeModal()">Cancel</button>
            <button class="btn btn-primary" onclick="FGP.saveProperty()">Save Property</button>
        `);
    },

    async saveProperty() {
        const name = document.getElementById('m-prop-name').value;
        if (!name) { this.toast('Property name required', 'error'); return; }

        const data = {
            name,
            slug: name.toLowerCase().replace(/[^a-z0-9]+/g, '-'),
            property_type: document.getElementById('m-prop-type').value,
            bedrooms: parseInt(document.getElementById('m-prop-bed').value),
            bathrooms: parseFloat(document.getElementById('m-prop-bath').value),
            max_guests: parseInt(document.getElementById('m-prop-guests').value),
            wifi_ssid: document.getElementById('m-prop-wifi').value,
            wifi_password: document.getElementById('m-prop-wifipass').value,
        };

        try {
            await api.createProperty(data);
            this.closeModal();
            this.toast('Property created', 'success');
            this.loadProperties();
        } catch (error) {
            this.toast('Error: ' + error.message, 'error');
        }
    },

    showAddWorkOrderModal() {
        this.createWorkOrder();
    },

    createWorkOrder() {
        const propertyOptions = this.data.properties.map(p =>
            `<option value="${p.id}">${p.name}</option>`
        ).join('');

        this.showModal('New Work Order', `
            <div class="form-group">
                <label class="form-label">Title</label>
                <input class="form-input" id="m-wo-title" placeholder="Brief description of the issue">
            </div>
            <div class="form-group">
                <label class="form-label">Property</label>
                <select class="form-select" id="m-wo-property">${propertyOptions}</select>
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
                <div class="form-group">
                    <label class="form-label">Category</label>
                    <select class="form-select" id="m-wo-category">
                        <option value="hvac">HVAC</option>
                        <option value="plumbing">Plumbing</option>
                        <option value="electrical">Electrical</option>
                        <option value="hot_tub">Hot Tub</option>
                        <option value="appliance">Appliance</option>
                        <option value="other">Other</option>
                    </select>
                </div>
                <div class="form-group">
                    <label class="form-label">Priority</label>
                    <select class="form-select" id="m-wo-priority">
                        <option value="low">Low</option>
                        <option value="medium" selected>Medium</option>
                        <option value="high">High</option>
                        <option value="urgent">Urgent</option>
                    </select>
                </div>
            </div>
            <div class="form-group">
                <label class="form-label">Description</label>
                <textarea class="form-textarea" id="m-wo-desc" placeholder="Detailed description..."></textarea>
            </div>
        `, `
            <button class="btn" onclick="FGP.closeModal()">Cancel</button>
            <button class="btn btn-primary" onclick="FGP.saveWorkOrder()">Create Work Order</button>
        `);
    },

    async saveWorkOrder() {
        const title = document.getElementById('m-wo-title').value;
        if (!title) { this.toast('Title required', 'error'); return; }

        const data = {
            title,
            property_id: document.getElementById('m-wo-property').value,
            category: document.getElementById('m-wo-category').value,
            priority: document.getElementById('m-wo-priority').value,
            description: document.getElementById('m-wo-desc').value || title,
        };

        try {
            await api.createWorkOrder(data);
            this.closeModal();
            this.toast('Work order created', 'success');
            this.loadWorkOrders();
        } catch (error) {
            this.toast('Error: ' + error.message, 'error');
        }
    },

    showAddReservationModal() {
        this.toast('Reservation form coming soon', 'info');
    },

    // ================================================================
    // INTEGRATIONS
    // ================================================================
    async loadIntegrations() {
        const container = document.getElementById('page-integrations');
        if (!container) return;

        container.innerHTML = `
            <div class="page-content">
                <div class="integration-grid">
                    <!-- Streamline VRS Card -->
                    <div class="card integration-card" id="streamline-card">
                        <div class="card-header">
                            <div style="display:flex;align-items:center;gap:12px;">
                                <div class="integration-icon streamline-icon">
                                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                        <path d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/>
                                    </svg>
                                </div>
                                <div>
                                    <h3 style="margin:0;color:var(--text-primary)">Streamline VRS</h3>
                                    <span style="font-size:0.8rem;color:var(--text-tertiary)">Property Management System</span>
                                </div>
                            </div>
                            <span class="badge" id="sl-status-badge">Checking...</span>
                        </div>
                        <div class="card-body">
                            <div class="integration-info" id="sl-info">
                                <div class="info-row"><span>Status</span><span id="sl-conn-status">Checking...</span></div>
                                <div class="info-row"><span>Last Sync</span><span id="sl-last-sync">Never</span></div>
                                <div class="info-row"><span>Sync Interval</span><span id="sl-interval">--</span></div>
                                <div class="info-row"><span>Latency</span><span id="sl-latency">--</span></div>
                            </div>
                            <div style="margin-top:16px;display:flex;gap:8px;">
                                <button class="btn btn-primary" onclick="FGP.triggerSync()">
                                    <i data-lucide="refresh-cw" style="width:14px;height:14px;margin-right:4px"></i> Sync Now
                                </button>
                                <button class="btn" onclick="FGP.checkStreamlineHealth()">
                                    <i data-lucide="heart-pulse" style="width:14px;height:14px;margin-right:4px"></i> Health Check
                                </button>
                            </div>
                        </div>
                    </div>

                    <!-- Twilio Card -->
                    <div class="card integration-card">
                        <div class="card-header">
                            <div style="display:flex;align-items:center;gap:12px;">
                                <div class="integration-icon twilio-icon">
                                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                        <path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07 19.5 19.5 0 01-6-6 19.79 19.79 0 01-3.07-8.67A2 2 0 014.11 2h3a2 2 0 012 1.72c.127.96.361 1.903.7 2.81a2 2 0 01-.45 2.11L8.09 9.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0122 16.92z"/>
                                    </svg>
                                </div>
                                <div>
                                    <h3 style="margin:0;color:var(--text-primary)">Twilio</h3>
                                    <span style="font-size:0.8rem;color:var(--text-tertiary)">SMS & Voice Platform</span>
                                </div>
                            </div>
                            <span class="badge badge-success">Connected</span>
                        </div>
                        <div class="card-body">
                            <div class="integration-info">
                                <div class="info-row"><span>Phone</span><span>+1 (706) 471-1479</span></div>
                                <div class="info-row"><span>A2P Service</span><span style="color:var(--green)">Active</span></div>
                                <div class="info-row"><span>Webhook</span><span style="color:var(--green)">crog-ai.com/webhooks/sms/incoming</span></div>
                                <div class="info-row"><span>Status</span><span style="color:var(--green)">Operational</span></div>
                            </div>
                        </div>
                    </div>

                    <!-- OpenAI Card -->
                    <div class="card integration-card">
                        <div class="card-header">
                            <div style="display:flex;align-items:center;gap:12px;">
                                <div class="integration-icon openai-icon">
                                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                        <path d="M12 2a10 10 0 100 20 10 10 0 000-20z"/><circle cx="12" cy="12" r="3"/>
                                    </svg>
                                </div>
                                <div>
                                    <h3 style="margin:0;color:var(--text-primary)">OpenAI GPT-4</h3>
                                    <span style="font-size:0.8rem;color:var(--text-tertiary)">AI Response Engine</span>
                                </div>
                            </div>
                            <span class="badge badge-warning">API Key Needed</span>
                        </div>
                        <div class="card-body">
                            <div class="integration-info">
                                <div class="info-row"><span>Model</span><span>gpt-4-turbo-preview</span></div>
                                <div class="info-row"><span>Confidence Threshold</span><span>0.75</span></div>
                                <div class="info-row"><span>Auto-reply</span><span style="color:var(--amber)">Disabled (review mode)</span></div>
                            </div>
                        </div>
                    </div>

                    <!-- Qdrant Card -->
                    <div class="card integration-card">
                        <div class="card-header">
                            <div style="display:flex;align-items:center;gap:12px;">
                                <div class="integration-icon qdrant-icon">
                                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                        <polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/>
                                    </svg>
                                </div>
                                <div>
                                    <h3 style="margin:0;color:var(--text-primary)">Qdrant Vector DB</h3>
                                    <span style="font-size:0.8rem;color:var(--text-tertiary)">Knowledge Base & RAG</span>
                                </div>
                            </div>
                            <span class="badge">Standby</span>
                        </div>
                        <div class="card-body">
                            <div class="integration-info">
                                <div class="info-row"><span>Collection</span><span>fgp_knowledge</span></div>
                                <div class="info-row"><span>Vectors</span><span>Pending population</span></div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Sync History -->
                <div class="card" style="margin-top:20px;">
                    <div class="card-header">
                        <h3 style="margin:0;color:var(--text-primary)">Sync History</h3>
                    </div>
                    <div class="card-body" id="sync-history">
                        <div class="empty-state">
                            <p>Sync history will appear here once Streamline VRS is connected.</p>
                            <p style="color:var(--text-tertiary);font-size:0.85rem;margin-top:8px;">
                                To connect: Add your Streamline API key to Settings > Integrations
                            </p>
                        </div>
                    </div>
                </div>
            </div>
        `;

        // Render Lucide icons in the new content
        if (window.lucide) lucide.createIcons();

        // Check Streamline status
        this.checkStreamlineHealth();
    },

    async checkStreamlineHealth() {
        try {
            const data = await api.getStreamlineStatus();
            const badge = document.getElementById('sl-status-badge');
            const status = document.getElementById('sl-conn-status');
            const lastSync = document.getElementById('sl-last-sync');
            const interval = document.getElementById('sl-interval');
            const latency = document.getElementById('sl-latency');

            if (!badge) return;

            const h = data.health || {};
            const s = data.sync || {};

            if (h.status === 'connected') {
                badge.textContent = 'Connected';
                badge.className = 'badge badge-success';
                status.innerHTML = '<span style="color:var(--green)">Connected</span>';
                latency.textContent = h.latency_ms ? h.latency_ms + 'ms' : '--';
            } else if (h.status === 'not_configured') {
                badge.textContent = 'Not Configured';
                badge.className = 'badge badge-warning';
                status.innerHTML = '<span style="color:var(--amber)">Needs API Key</span>';
            } else {
                badge.textContent = h.status || 'Unknown';
                badge.className = 'badge badge-error';
                status.innerHTML = '<span style="color:var(--red)">' + (h.message || h.status) + '</span>';
            }

            interval.textContent = s.sync_interval_seconds ? s.sync_interval_seconds + 's' : '--';

            if (s.last_sync && Object.keys(s.last_sync).length > 0) {
                const latest = Object.values(s.last_sync).sort().pop();
                lastSync.textContent = this.timeAgo(latest);
            } else {
                lastSync.textContent = 'Never';
            }
        } catch (e) {
            const badge = document.getElementById('sl-status-badge');
            if (badge) {
                badge.textContent = 'Error';
                badge.className = 'badge badge-error';
            }
        }
    },

    async triggerSync() {
        this.toast('Starting Streamline VRS sync...', 'info');
        try {
            const result = await api.triggerStreamlineSync();
            if (result.status === 'ok') {
                const s = result.summary;
                const msg = [
                    `Properties: ${s.properties.created} new, ${s.properties.updated} updated`,
                    `Reservations: ${s.reservations.created} new, ${s.reservations.updated} updated`,
                    `Guests: ${s.guests.created} new, ${s.guests.updated} updated`,
                ].join(' | ');
                this.toast(msg, 'success');
            } else {
                this.toast('Sync issue: ' + (result.message || 'Check API key'), 'error');
            }
            this.checkStreamlineHealth();
        } catch (e) {
            this.toast('Sync failed: ' + e.message, 'error');
        }
    },

    // ================================================================
    // SYSTEM
    // ================================================================
    async checkHealth() {
        try {
            const health = await api.getHealth();
            if (health.status === 'healthy') {
                document.querySelector('.status-dot').classList.remove('status-offline');
                document.querySelector('.status-dot').classList.add('status-online');
            }
        } catch {
            document.querySelector('.status-dot').classList.add('status-offline');
            document.querySelector('.system-status span').textContent = 'API Unreachable';
        }
    },

    viewGuest(id) { this.viewGuest360(id); },
    viewReservation(id) { this.toast('Reservation detail view: ' + id.substring(0, 8), 'info'); },
    viewWorkOrder(id) { this.toast('Work order detail view: ' + id.substring(0, 8), 'info'); },

    // ================================================================
    // UTILITIES
    // ================================================================
    toast(message, type = 'info') {
        const container = document.getElementById('toast-container');
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.innerHTML = `<span>${message}</span>`;
        container.appendChild(toast);
        setTimeout(() => toast.remove(), 4000);
    },

    truncate(text, maxLen) {
        if (!text) return '';
        return text.length > maxLen ? text.substring(0, maxLen) + '...' : text;
    },

    getInitials(name) {
        if (!name) return '?';
        if (name.startsWith('+')) return name.slice(-2);
        return name.split(' ').filter(Boolean).map(w => w[0]).join('').toUpperCase().slice(0, 2) || '?';
    },

    timeAgo(dateStr) {
        if (!dateStr) return '';
        const now = new Date();
        const date = new Date(dateStr);
        const diff = Math.floor((now - date) / 1000);

        if (diff < 60) return 'now';
        if (diff < 3600) return Math.floor(diff / 60) + 'm';
        if (diff < 86400) return Math.floor(diff / 3600) + 'h';
        if (diff < 604800) return Math.floor(diff / 86400) + 'd';
        return date.toLocaleDateString();
    },

    formatDate(dateStr) {
        if (!dateStr) return '';
        return new Date(dateStr).toLocaleString('en-US', {
            month: 'short', day: 'numeric',
            hour: 'numeric', minute: '2-digit',
            hour12: true
        });
    },
};

// ================================================================
// REVIEW QUEUE (global functions referenced from HTML)
// ================================================================

async function loadReviewQueue() {
    const status = document.getElementById('rq-status-filter')?.value || 'pending';

    // Load stats
    try {
        const stats = await FGP.api('/api/review/queue/stats');
        const statsEl = document.getElementById('rq-stats');
        if (statsEl) {
            statsEl.innerHTML = `
                <div class="stat-card"><div class="stat-value">${stats.pending}</div><div class="stat-label">Pending</div></div>
                <div class="stat-card"><div class="stat-value">${stats.approved + stats.edited}</div><div class="stat-label">Approved</div></div>
                <div class="stat-card"><div class="stat-value">${stats.rejected}</div><div class="stat-label">Rejected</div></div>
                <div class="stat-card"><div class="stat-value">${stats.avg_pending_confidence ? (stats.avg_pending_confidence * 100).toFixed(0) + '%' : '—'}</div><div class="stat-label">Avg Confidence</div></div>
            `;
        }
        const badge = document.getElementById('review-badge');
        if (badge) badge.textContent = stats.pending || 0;
    } catch (e) { console.warn('review stats error', e); }

    // Load queue items
    try {
        const data = await FGP.api(`/api/review/queue?status=${status}&limit=50`);
        const listEl = document.getElementById('rq-list');
        if (!listEl) return;

        if (!data.items || data.items.length === 0) {
            listEl.innerHTML = `<div class="empty-state" style="text-align:center;padding:48px;opacity:0.6">
                <p style="font-size:1.5rem;margin-bottom:8px">No ${status} items</p>
                <p>AI responses needing review will appear here</p>
            </div>`;
            return;
        }

        listEl.innerHTML = data.items.map(item => `
            <div class="card" style="padding:16px;border-left:4px solid ${item.confidence >= 0.8 ? '#10b981' : item.confidence >= 0.5 ? '#f59e0b' : '#ef4444'}">
                <div style="display:flex;justify-content:space-between;align-items:start;margin-bottom:12px">
                    <div>
                        <strong>${item.guest_name || item.from_phone || 'Unknown Guest'}</strong>
                        <span style="opacity:0.6;margin-left:8px">${FGP.timeAgo(item.inbound_time)}</span>
                        ${item.intent ? `<span class="badge" style="margin-left:8px">${item.intent}</span>` : ''}
                        ${item.urgency > 0 ? `<span class="badge badge-warning">Urgent</span>` : ''}
                    </div>
                    <div style="display:flex;gap:8px;align-items:center">
                        <span style="font-size:0.85rem;opacity:0.7">Confidence: <strong>${(item.confidence * 100).toFixed(0)}%</strong></span>
                    </div>
                </div>
                <div style="background:var(--bg-secondary);padding:12px;border-radius:8px;margin-bottom:8px">
                    <div style="font-size:0.8rem;opacity:0.5;margin-bottom:4px">INBOUND MESSAGE</div>
                    <div>${item.inbound_body || '(no body)'}</div>
                </div>
                <div style="background:var(--bg-tertiary, #f0fdf4);padding:12px;border-radius:8px;margin-bottom:12px;border:1px solid rgba(16,185,129,0.2)">
                    <div style="font-size:0.8rem;opacity:0.5;margin-bottom:4px">AI PROPOSED RESPONSE</div>
                    <div id="rq-response-${item.id}" contenteditable="${item.status === 'pending'}" style="outline:none;min-height:40px">${item.proposed_response}</div>
                </div>
                ${item.escalation_reason ? `<div style="font-size:0.85rem;color:#f59e0b;margin-bottom:8px">Escalation: ${item.escalation_reason}</div>` : ''}
                ${item.status === 'pending' ? `
                <div style="display:flex;gap:8px;justify-content:flex-end">
                    <button class="btn btn-secondary" style="background:#ef4444;color:white;border:none" onclick="rejectResponse('${item.id}')">Reject</button>
                    <button class="btn btn-secondary" onclick="editAndSend('${item.id}')">Edit & Send</button>
                    <button class="btn btn-primary" onclick="approveResponse('${item.id}')">Approve & Send</button>
                </div>` : `
                <div style="font-size:0.85rem;opacity:0.6">
                    ${item.status.toUpperCase()} by ${item.reviewed_by || 'system'} ${item.reviewed_at ? '@ ' + FGP.formatDate(item.reviewed_at) : ''}
                    ${item.final_response && item.final_response !== item.proposed_response ? '<br><em>Modified before sending</em>' : ''}
                </div>`}
            </div>
        `).join('');
    } catch (e) {
        console.error('review queue error', e);
    }
}

async function approveResponse(id) {
    try {
        await FGP.api(`/api/review/queue/${id}/approve`, {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({reviewed_by: 'admin'})
        });
        FGP.toast('Response approved and sent', 'success');
        loadReviewQueue();
    } catch(e) { FGP.toast('Failed to approve: ' + e.message, 'error'); }
}

async function editAndSend(id) {
    const el = document.getElementById(`rq-response-${id}`);
    const text = el?.innerText?.trim();
    if (!text) { FGP.toast('Response cannot be empty', 'error'); return; }
    try {
        await FGP.api(`/api/review/queue/${id}/edit`, {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({final_response: text, reviewed_by: 'admin'})
        });
        FGP.toast('Edited response sent', 'success');
        loadReviewQueue();
    } catch(e) { FGP.toast('Failed to send: ' + e.message, 'error'); }
}

async function rejectResponse(id) {
    try {
        await FGP.api(`/api/review/queue/${id}/reject`, {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({reviewed_by: 'admin', reason: 'Manual rejection'})
        });
        FGP.toast('Response rejected', 'success');
        loadReviewQueue();
    } catch(e) { FGP.toast('Failed to reject: ' + e.message, 'error'); }
}

// Auto-refresh review badge on dashboard load
setInterval(async () => {
    try {
        const stats = await FGP.api('/api/review/queue/stats');
        const badge = document.getElementById('review-badge');
        if (badge) badge.textContent = stats.pending || 0;
    } catch(e) {}
}, 30000);

// ================================================================
// DAMAGE CLAIMS
// ================================================================

async function loadDamageClaims() {
    const status = document.getElementById('dc-status-filter')?.value || 'all';
    try {
        const [claims, stats] = await Promise.all([
            FGP.api(`/api/damage-claims/?status=${status}&limit=50`),
            FGP.api('/api/damage-claims/stats'),
        ]);

        const statsEl = document.getElementById('dc-stats');
        if (statsEl) {
            const bs = stats.by_status || {};
            statsEl.innerHTML = `
                <div class="stat-card" style="border-left:4px solid #ef4444"><div class="stat-value">${bs.reported||0}</div><div class="stat-label">Reported</div></div>
                <div class="stat-card" style="border-left:4px solid #f59e0b"><div class="stat-value">${bs.draft_ready||0}</div><div class="stat-label">Draft Ready</div></div>
                <div class="stat-card" style="border-left:4px solid #3b82f6"><div class="stat-value">${(bs.approved||0)+(bs.sent||0)}</div><div class="stat-label">Sent/Approved</div></div>
                <div class="stat-card" style="border-left:4px solid #10b981"><div class="stat-value">${bs.resolved||0}</div><div class="stat-label">Resolved</div></div>`;
        }

        const badge = document.getElementById('damage-badge');
        if (badge) badge.textContent = (stats.by_status?.reported||0) + (stats.by_status?.draft_ready||0);

        const listEl = document.getElementById('dc-list');
        if (!listEl) return;

        if (!claims.length) {
            listEl.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text-muted)">No damage claims found</div>';
            return;
        }

        listEl.innerHTML = claims.map(c => {
            const statusColors = {reported:'#ef4444',draft_ready:'#f59e0b',legal_review:'#8b5cf6',approved:'#3b82f6',sent:'#06b6d4',resolved:'#10b981',closed:'#6b7280'};
            const color = statusColors[c.status] || '#6b7280';
            const cost = c.estimated_cost ? `$${Number(c.estimated_cost).toLocaleString()}` : 'TBD';
            return `
            <div class="card" style="padding:20px;border-left:4px solid ${color}">
                <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px">
                    <div>
                        <h3 style="margin:0;font-size:16px">${c.claim_number} — ${c.property_name||'Unknown Property'}</h3>
                        <div style="color:var(--text-muted);font-size:13px;margin-top:4px">
                            Guest: <strong>${c.guest_name||'Unknown'}</strong> &bull;
                            Confirmation: ${c.confirmation_code||'N/A'} &bull;
                            Stay: ${c.check_in_date||'?'} to ${c.check_out_date||'?'}
                        </div>
                    </div>
                    <div style="display:flex;gap:8px;align-items:center">
                        <span style="background:${color}22;color:${color};padding:4px 12px;border-radius:12px;font-size:12px;font-weight:600">${c.status.replace('_',' ').toUpperCase()}</span>
                        <span style="font-weight:700;font-size:15px">${cost}</span>
                    </div>
                </div>
                <div style="background:var(--bg-secondary);padding:12px;border-radius:8px;margin-bottom:12px">
                    <div style="font-weight:600;font-size:13px;margin-bottom:4px;color:var(--text-muted)">Damage Report</div>
                    <div style="white-space:pre-wrap;font-size:14px">${FGP.truncate(c.damage_description, 400)}</div>
                    ${c.policy_violations ? `<div style="margin-top:8px;color:#ef4444;font-size:13px"><strong>Policy Violations:</strong> ${c.policy_violations}</div>` : ''}
                    ${c.damage_areas?.length ? `<div style="margin-top:6px;font-size:12px;color:var(--text-muted)">Areas: ${c.damage_areas.join(', ')}</div>` : ''}
                </div>
                ${c.legal_draft ? `
                <details style="margin-bottom:12px">
                    <summary style="cursor:pointer;font-weight:600;font-size:13px;color:#8b5cf6">View Legal Draft (${c.legal_draft_model||'AI'})</summary>
                    <div style="background:#f5f3ff;padding:12px;border-radius:8px;margin-top:8px;white-space:pre-wrap;font-size:13px;border:1px solid #ddd6fe">${c.legal_draft}</div>
                </details>` : ''}
                ${c.final_response ? `
                <details style="margin-bottom:12px">
                    <summary style="cursor:pointer;font-weight:600;font-size:13px;color:#3b82f6">View Final Response</summary>
                    <div style="background:#eff6ff;padding:12px;border-radius:8px;margin-top:8px;white-space:pre-wrap;font-size:13px;border:1px solid #bfdbfe">${c.final_response}</div>
                </details>` : ''}
                <div style="display:flex;gap:8px;flex-wrap:wrap">
                    ${c.status === 'reported' ? `<button class="btn btn-primary" onclick="generateLegalDraft('${c.id}')"><i data-lucide="scale"></i> Generate Legal Draft</button>` : ''}
                    ${c.status === 'draft_ready' ? `
                        <button class="btn btn-primary" onclick="approveClaim('${c.id}')"><i data-lucide="check"></i> Approve Draft</button>
                        <button class="btn btn-secondary" onclick="editClaimDraft('${c.id}', \`${(c.legal_draft||'').replace(/`/g,"'").replace(/\\/g,"\\\\")}\`)"><i data-lucide="edit"></i> Edit & Approve</button>
                        <button class="btn btn-primary" onclick="generateLegalDraft('${c.id}')" style="background:#8b5cf6"><i data-lucide="refresh-cw"></i> Regenerate Draft</button>
                    ` : ''}
                    ${c.status === 'approved' ? `
                        <button class="btn btn-primary" onclick="sendClaimResponse('${c.id}','email')"><i data-lucide="mail"></i> Send via Email</button>
                        <button class="btn btn-secondary" onclick="sendClaimResponse('${c.id}','sms')"><i data-lucide="message-square"></i> Send via SMS</button>
                    ` : ''}
                    ${['reported','draft_ready'].includes(c.status) ? `<button class="btn btn-secondary" onclick="editClaimDetails('${c.id}')"><i data-lucide="file-edit"></i> Edit Report</button>` : ''}
                </div>
            </div>`;
        }).join('');
        lucide.createIcons({nameAttr:'data-lucide'});
    } catch(e) {
        console.error('loadDamageClaims error', e);
    }
}

async function showNewClaimModal() {
    let reservations = [];
    try {
        reservations = await FGP.api('/api/damage-claims/reservation-options?limit=200');
    } catch(e) {}

    const opts = reservations.map(r =>
        `<option value="${r.id}">${r.confirmation_code} — ${r.guest_name||'Guest'} @ ${r.property_name||'Property'} (${r.check_in_date} to ${r.check_out_date})</option>`
    ).join('');

    const speechSupported = 'webkitSpeechRecognition' in window || 'SpeechRecognition' in window;

    document.getElementById('modal-title').textContent = 'File Damage Claim';
    document.getElementById('modal-body').innerHTML = `
        <form id="new-claim-form" style="display:flex;flex-direction:column;gap:16px">
            <div>
                <label style="display:block;font-weight:600;margin-bottom:6px">Reservation</label>
                <select id="nc-reservation" class="input-field" style="width:100%" required>${opts}</select>
            </div>
            <div>
                <label style="display:block;font-weight:600;margin-bottom:6px">
                    Damage Description
                    ${speechSupported ? '<button type="button" class="btn btn-secondary" id="voice-btn" onclick="toggleVoiceInput(\'nc-damage\')" style="float:right;padding:4px 10px;font-size:12px"><i data-lucide="mic"></i> Voice Input</button>' : ''}
                </label>
                <textarea id="nc-damage" class="input-field" rows="5" style="width:100%" required placeholder="Describe the damage found during post-checkout inspection..."></textarea>
                <div id="voice-status" style="display:none;color:#ef4444;font-size:12px;margin-top:4px"></div>
            </div>
            <div>
                <label style="display:block;font-weight:600;margin-bottom:6px">
                    Policy Violations
                    ${speechSupported ? '<button type="button" class="btn btn-secondary" onclick="toggleVoiceInput(\'nc-violations\')" style="float:right;padding:4px 10px;font-size:12px"><i data-lucide="mic"></i> Voice</button>' : ''}
                </label>
                <textarea id="nc-violations" class="input-field" rows="3" style="width:100%" placeholder="Smoking, unauthorized pets, exceeding occupancy, etc."></textarea>
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
                <div>
                    <label style="display:block;font-weight:600;margin-bottom:6px">Estimated Cost ($)</label>
                    <input type="number" id="nc-cost" class="input-field" style="width:100%" step="0.01" placeholder="0.00">
                </div>
                <div>
                    <label style="display:block;font-weight:600;margin-bottom:6px">Inspection Date</label>
                    <input type="date" id="nc-date" class="input-field" style="width:100%" value="${new Date().toISOString().split('T')[0]}">
                </div>
            </div>
            <div>
                <label style="display:block;font-weight:600;margin-bottom:6px">Affected Areas</label>
                <input type="text" id="nc-areas" class="input-field" style="width:100%" placeholder="hot tub, deck, living room (comma separated)">
            </div>
            <div>
                <label style="display:block;font-weight:600;margin-bottom:6px">
                    Inspection Notes
                    ${speechSupported ? '<button type="button" class="btn btn-secondary" onclick="toggleVoiceInput(\'nc-notes\')" style="float:right;padding:4px 10px;font-size:12px"><i data-lucide="mic"></i> Voice</button>' : ''}
                </label>
                <textarea id="nc-notes" class="input-field" rows="3" style="width:100%" placeholder="Additional observations, photos taken, cleaning team notes..."></textarea>
            </div>
        </form>`;
    document.getElementById('modal-footer').innerHTML = `
        <button class="btn btn-secondary" onclick="FGP.closeModal()">Cancel</button>
        <button class="btn btn-primary" onclick="submitNewClaim()"><i data-lucide="shield-alert"></i> File Claim & Generate Legal Draft</button>`;
    document.getElementById('modal-overlay').style.display = 'flex';
    lucide.createIcons({nameAttr:'data-lucide'});
}

let activeRecognition = null;
function toggleVoiceInput(targetId) {
    if (activeRecognition) { activeRecognition.stop(); activeRecognition = null; return; }
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) { FGP.toast('Speech recognition not supported in this browser','error'); return; }

    const recognition = new SpeechRecognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = 'en-US';
    activeRecognition = recognition;

    const target = document.getElementById(targetId);
    const statusEl = document.getElementById('voice-status');
    if (statusEl) { statusEl.style.display = 'block'; statusEl.textContent = 'Listening... speak now'; statusEl.style.color = '#ef4444'; }

    recognition.onresult = (event) => {
        let finalTranscript = '';
        for (let i = event.resultIndex; i < event.results.length; i++) {
            if (event.results[i].isFinal) finalTranscript += event.results[i][0].transcript;
        }
        if (finalTranscript && target) {
            target.value += (target.value ? ' ' : '') + finalTranscript;
        }
    };
    recognition.onerror = () => { if (statusEl) { statusEl.textContent = 'Voice input stopped'; } activeRecognition = null; };
    recognition.onend = () => { if (statusEl) { statusEl.textContent = 'Voice input complete'; statusEl.style.color = '#10b981'; } activeRecognition = null; };
    recognition.start();
}

async function submitNewClaim() {
    const reservationId = document.getElementById('nc-reservation')?.value;
    const damage = document.getElementById('nc-damage')?.value?.trim();
    if (!reservationId || !damage) { FGP.toast('Reservation and damage description required','error'); return; }

    const body = {
        reservation_id: reservationId,
        damage_description: damage,
        policy_violations: document.getElementById('nc-violations')?.value?.trim() || null,
        estimated_cost: parseFloat(document.getElementById('nc-cost')?.value) || null,
        inspection_date: document.getElementById('nc-date')?.value || null,
        damage_areas: (document.getElementById('nc-areas')?.value||'').split(',').map(s=>s.trim()).filter(Boolean),
        inspection_notes: document.getElementById('nc-notes')?.value?.trim() || null,
        reported_by: 'management',
    };

    try {
        FGP.toast('Filing claim...','info');
        const claim = await FGP.api('/api/damage-claims/', {
            method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)
        });
        FGP.toast(`Claim ${claim.claim_number} filed — generating legal draft...`,'success');
        FGP.closeModal();

        await generateLegalDraft(claim.id);
    } catch(e) { FGP.toast('Failed: ' + e.message,'error'); }
}

async function generateLegalDraft(claimId) {
    try {
        FGP.toast('HYDRA generating legal response draft...','info');
        await FGP.api(`/api/damage-claims/${claimId}/generate-legal-draft`, {method:'POST'});
        FGP.toast('Legal draft ready for review','success');
        loadDamageClaims();
    } catch(e) { FGP.toast('Draft generation failed: ' + e.message,'error'); }
}

async function approveClaim(claimId) {
    try {
        await FGP.api(`/api/damage-claims/${claimId}/approve`, {method:'POST'});
        FGP.toast('Claim approved — ready to send','success');
        loadDamageClaims();
    } catch(e) { FGP.toast('Approval failed: ' + e.message,'error'); }
}

async function editClaimDraft(claimId, currentDraft) {
    document.getElementById('modal-title').textContent = 'Edit Legal Response';
    document.getElementById('modal-body').innerHTML = `
        <textarea id="edit-draft-text" class="input-field" rows="15" style="width:100%;font-size:14px">${currentDraft}</textarea>`;
    document.getElementById('modal-footer').innerHTML = `
        <button class="btn btn-secondary" onclick="FGP.closeModal()">Cancel</button>
        <button class="btn btn-primary" onclick="saveEditedDraft('${claimId}')">Save & Approve</button>`;
    document.getElementById('modal-overlay').style.display = 'flex';
}

async function saveEditedDraft(claimId) {
    const text = document.getElementById('edit-draft-text')?.value;
    if (!text) return;
    try {
        await FGP.api(`/api/damage-claims/${claimId}`, {
            method:'PATCH', headers:{'Content-Type':'application/json'},
            body:JSON.stringify({final_response: text, status: 'approved'})
        });
        FGP.closeModal();
        FGP.toast('Response approved','success');
        loadDamageClaims();
    } catch(e) { FGP.toast('Save failed: ' + e.message,'error'); }
}

async function editClaimDetails(claimId) {
    try {
        const claim = await FGP.api(`/api/damage-claims/${claimId}`);
        document.getElementById('modal-title').textContent = `Edit ${claim.claim_number}`;
        document.getElementById('modal-body').innerHTML = `
            <form style="display:flex;flex-direction:column;gap:12px">
                <div><label style="font-weight:600;display:block;margin-bottom:4px">Damage Description</label>
                <textarea id="edit-damage" class="input-field" rows="4" style="width:100%">${claim.damage_description||''}</textarea></div>
                <div><label style="font-weight:600;display:block;margin-bottom:4px">Policy Violations</label>
                <textarea id="edit-violations" class="input-field" rows="2" style="width:100%">${claim.policy_violations||''}</textarea></div>
                <div><label style="font-weight:600;display:block;margin-bottom:4px">Estimated Cost ($)</label>
                <input id="edit-cost" type="number" class="input-field" style="width:100%" step="0.01" value="${claim.estimated_cost||''}"></div>
                <div><label style="font-weight:600;display:block;margin-bottom:4px">Inspection Notes</label>
                <textarea id="edit-notes" class="input-field" rows="2" style="width:100%">${claim.inspection_notes||''}</textarea></div>
            </form>`;
        document.getElementById('modal-footer').innerHTML = `
            <button class="btn btn-secondary" onclick="FGP.closeModal()">Cancel</button>
            <button class="btn btn-primary" onclick="saveClaimDetails('${claimId}')">Save Changes</button>`;
        document.getElementById('modal-overlay').style.display = 'flex';
    } catch(e) { FGP.toast('Load failed','error'); }
}

async function saveClaimDetails(claimId) {
    try {
        await FGP.api(`/api/damage-claims/${claimId}`, {
            method:'PATCH', headers:{'Content-Type':'application/json'},
            body:JSON.stringify({
                damage_description: document.getElementById('edit-damage')?.value,
                policy_violations: document.getElementById('edit-violations')?.value || null,
                estimated_cost: parseFloat(document.getElementById('edit-cost')?.value) || null,
                inspection_notes: document.getElementById('edit-notes')?.value || null,
            })
        });
        FGP.closeModal();
        FGP.toast('Claim updated','success');
        loadDamageClaims();
    } catch(e) { FGP.toast('Save failed','error'); }
}

async function sendClaimResponse(claimId, via) {
    if (!confirm(`Send the approved response via ${via.toUpperCase()}?`)) return;
    try {
        await FGP.api(`/api/damage-claims/${claimId}/send?via=${via}`, {method:'POST'});
        FGP.toast(`Response sent via ${via}`,'success');
        loadDamageClaims();
    } catch(e) { FGP.toast('Send failed: ' + e.message,'error'); }
}

// Refresh damage badge periodically
setInterval(async () => {
    try {
        const stats = await FGP.api('/api/damage-claims/stats');
        const badge = document.getElementById('damage-badge');
        if (badge) badge.textContent = (stats.by_status?.reported||0) + (stats.by_status?.draft_ready||0);
    } catch(e) {}
}, 30000);

// Boot
document.addEventListener('DOMContentLoaded', () => FGP.init());
