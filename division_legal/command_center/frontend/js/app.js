/**
 * Fortress Legal Command Center — Dashboard SPA
 */
const App = {
    currentPage: 'dashboard',
    data: { attorneys: [], matters: [], meetings: [], stats: {} },
    currentMatterId: null,
    currentAttorneyId: null,
    editingId: null,

    // ── Initialization ──────────────────────────────────────────────────────
    async init() {
        this.bindNavigation();
        this.bindSearch();
        await this.navigateTo('dashboard');
    },

    bindNavigation() {
        document.querySelectorAll('.nav-item[data-page]').forEach(el => {
            el.addEventListener('click', () => this.navigateTo(el.dataset.page));
        });
    },

    bindSearch() {
        const input = document.getElementById('global-search');
        if (input) {
            let timeout;
            input.addEventListener('input', () => {
                clearTimeout(timeout);
                timeout = setTimeout(() => this.handleSearch(input.value), 300);
            });
        }
    },

    async navigateTo(page) {
        this.currentPage = page;
        document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
        document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
        const pageEl = document.getElementById(`page-${page}`);
        if (pageEl) pageEl.classList.add('active');
        const navEl = document.querySelector(`.nav-item[data-page="${page}"]`);
        if (navEl) navEl.classList.add('active');

        switch (page) {
            case 'dashboard': await this.loadDashboard(); break;
            case 'matters': await this.loadMatters(); break;
            case 'attorneys': await this.loadAttorneys(); break;
            case 'meetings': await this.loadMeetings(); break;
            case 'timeline': await this.loadTimeline(); break;
        }
    },

    async handleSearch(term) {
        switch (this.currentPage) {
            case 'matters': await this.loadMatters({ search: term }); break;
            case 'attorneys': await this.loadAttorneys({ search: term }); break;
            case 'meetings': await this.loadMeetings({ search: term }); break;
        }
    },

    // ── Dashboard ───────────────────────────────────────────────────────────
    async loadDashboard() {
        try {
            const [stats, matters, meetings, attorneys] = await Promise.all([
                api.getMatterStats(),
                api.getMatters({ limit: 5 }),
                api.getUpcomingMeetings(14),
                api.getAttorneys({ status: 'active' }),
            ]);
            this.data.stats = stats;

            document.getElementById('stat-total-matters').textContent = stats.total || 0;
            document.getElementById('stat-open-matters').textContent = stats.open || 0;
            document.getElementById('stat-critical').textContent = stats.critical || 0;
            document.getElementById('stat-attorneys').textContent = attorneys.length || 0;
            document.getElementById('stat-upcoming').textContent = meetings.length || 0;

            const recentTbody = document.getElementById('recent-matters-tbody');
            if (matters.length === 0) {
                recentTbody.innerHTML = '<tr><td colspan="5" class="table-empty">No matters yet. Create your first matter to get started.</td></tr>';
            } else {
                recentTbody.innerHTML = matters.map(m => `
                    <tr class="clickable" onclick="App.viewMatter('${m.id}')">
                        <td style="color:var(--text-primary);font-weight:600">${esc(m.title)}</td>
                        <td><span class="badge-status ${m.status}">${m.status}</span></td>
                        <td><span class="badge-status ${m.priority}">${m.priority}</span></td>
                        <td>${esc(m.attorney_name || '—')}</td>
                        <td>${formatDate(m.updated_at)}</td>
                    </tr>
                `).join('');
            }

            const upTbody = document.getElementById('upcoming-meetings-tbody');
            if (meetings.length === 0) {
                upTbody.innerHTML = '<tr><td colspan="4" class="table-empty">No upcoming meetings.</td></tr>';
            } else {
                upTbody.innerHTML = meetings.slice(0, 5).map(m => `
                    <tr>
                        <td style="color:var(--text-primary);font-weight:600">${esc(m.title)}</td>
                        <td>${formatDateTime(m.meeting_date)}</td>
                        <td>${esc(m.attorney_name || '—')}</td>
                        <td><span class="badge-type">${m.meeting_type}</span></td>
                    </tr>
                `).join('');
            }

            // Follow-ups due
            try {
                const followUps = await api.getFollowUps();
                const fuCount = document.getElementById('stat-followups');
                if (fuCount) fuCount.textContent = followUps.length || 0;
            } catch (e) { /* non-critical */ }

        } catch (err) {
            toast('Failed to load dashboard: ' + err.message, 'error');
        }
    },

    // ── Matters ─────────────────────────────────────────────────────────────
    async loadMatters(params = {}) {
        try {
            const matters = await api.getMatters(params);
            this.data.matters = matters;
            const tbody = document.getElementById('matters-tbody');
            if (matters.length === 0) {
                tbody.innerHTML = '<tr><td colspan="7" class="table-empty">No matters found.</td></tr>';
                return;
            }
            tbody.innerHTML = matters.map(m => `
                <tr class="clickable" onclick="App.viewMatter('${m.id}')">
                    <td style="color:var(--text-primary);font-weight:600">${esc(m.title)}</td>
                    <td>${esc(m.reference_code || '—')}</td>
                    <td><span class="badge-type">${m.category}</span></td>
                    <td><span class="badge-status ${m.status}">${m.status}</span></td>
                    <td><span class="badge-status ${m.priority}">${m.priority}</span></td>
                    <td>${esc(m.attorney_name || '—')}</td>
                    <td>${formatDate(m.updated_at)}</td>
                </tr>
            `).join('');
        } catch (err) {
            toast('Failed to load matters: ' + err.message, 'error');
        }
    },

    async viewMatter(id) {
        try {
            const m = await api.getMatter(id);
            this.currentMatterId = id;
            document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
            const detailPage = document.getElementById('page-matter-detail');
            detailPage.classList.add('active');

            document.getElementById('md-title').textContent = m.title;
            document.getElementById('md-ref').textContent = m.reference_code || '—';
            document.getElementById('md-status').innerHTML = `<span class="badge-status ${m.status}">${m.status}</span>`;
            document.getElementById('md-priority').innerHTML = `<span class="badge-status ${m.priority}">${m.priority}</span>`;
            document.getElementById('md-category').textContent = m.category;
            document.getElementById('md-attorney').textContent = m.attorney_name || '—';
            document.getElementById('md-opposing').textContent = m.opposing_party || '—';
            document.getElementById('md-amount').textContent = m.amount_at_stake ? '$' + Number(m.amount_at_stake).toLocaleString() : '—';
            document.getElementById('md-description').textContent = m.description || 'No description.';
            document.getElementById('md-next-action').textContent = m.next_action || '—';
            document.getElementById('md-next-date').textContent = m.next_action_date ? formatDate(m.next_action_date) : '—';
            document.getElementById('md-outcome').textContent = m.outcome || '—';

            // Timeline
            const tlContainer = document.getElementById('md-timeline');
            if (m.timeline && m.timeline.length > 0) {
                tlContainer.innerHTML = m.timeline.map(t => `
                    <div class="timeline-item">
                        <div class="timeline-dot ${t.entry_type}"></div>
                        <div class="timeline-content">
                            <div class="title">${esc(t.title)}</div>
                            ${t.body ? `<div class="body">${esc(t.body)}</div>` : ''}
                            <div class="meta">
                                <span>${t.entry_type}</span>
                                <span>${formatDateTime(t.created_at)}</span>
                            </div>
                        </div>
                    </div>
                `).join('');
            } else {
                tlContainer.innerHTML = '<div class="table-empty">No timeline entries yet.</div>';
            }

            // Meetings
            const mtContainer = document.getElementById('md-meetings');
            if (m.meetings && m.meetings.length > 0) {
                mtContainer.innerHTML = m.meetings.map(mt => `
                    <div class="timeline-item">
                        <div class="timeline-dot meeting"></div>
                        <div class="timeline-content">
                            <div class="title">${esc(mt.title)}</div>
                            <div class="body">${esc(mt.summary || '')}</div>
                            <div class="meta">
                                <span>${mt.meeting_type}</span>
                                <span>${formatDateTime(mt.meeting_date)}</span>
                                ${mt.attorney_name ? `<span>${esc(mt.attorney_name)}</span>` : ''}
                                ${mt.duration_minutes ? `<span>${mt.duration_minutes} min</span>` : ''}
                            </div>
                            ${mt.action_items ? `<div class="body" style="margin-top:8px;color:var(--yellow)">Action items: ${esc(mt.action_items)}</div>` : ''}
                        </div>
                    </div>
                `).join('');
            } else {
                mtContainer.innerHTML = '<div class="table-empty">No meetings recorded.</div>';
            }

            // Documents
            const docsContainer = document.getElementById('md-documents');
            if (m.documents && m.documents.length > 0) {
                docsContainer.innerHTML = m.documents.map(d => `
                    <div style="padding:8px 0;border-bottom:1px solid var(--border)">
                        <div style="font-weight:600;font-size:13px">${esc(d.title)}</div>
                        <div style="font-size:12px;color:var(--text-muted)">${d.doc_type || 'general'} &mdash; ${formatDate(d.created_at)}</div>
                        ${d.description ? `<div style="font-size:12px;color:var(--text-secondary);margin-top:4px">${esc(d.description)}</div>` : ''}
                    </div>
                `).join('');
            } else {
                docsContainer.innerHTML = '<div class="table-empty">No documents linked.</div>';
            }

        } catch (err) {
            toast('Failed to load matter: ' + err.message, 'error');
        }
    },

    backToMatters() {
        this.currentMatterId = null;
        this.navigateTo('matters');
    },

    // ── Attorneys ────────────────────────────────────────────────────────────
    async loadAttorneys(params = {}) {
        try {
            const attorneys = await api.getAttorneys(params);
            this.data.attorneys = attorneys;
            const tbody = document.getElementById('attorneys-tbody');
            if (attorneys.length === 0) {
                tbody.innerHTML = '<tr><td colspan="7" class="table-empty">No attorneys on file. Add your first attorney.</td></tr>';
                return;
            }
            tbody.innerHTML = attorneys.map(a => `
                <tr>
                    <td style="color:var(--text-primary);font-weight:600">${esc(a.full_name)}</td>
                    <td>${esc(a.firm_name || '—')}</td>
                    <td><span class="badge-type">${a.specialty || '—'}</span></td>
                    <td>${esc(a.phone || a.email || '—')}</td>
                    <td>${a.hourly_rate ? '$' + Number(a.hourly_rate).toFixed(0) + '/hr' : '—'}</td>
                    <td><span class="badge-status ${a.status}">${a.status}</span></td>
                    <td>
                        <button class="btn btn-sm btn-ghost" onclick="App.editAttorney('${a.id}')">Edit</button>
                    </td>
                </tr>
            `).join('');
        } catch (err) {
            toast('Failed to load attorneys: ' + err.message, 'error');
        }
    },

    // ── Meetings ────────────────────────────────────────────────────────────
    async loadMeetings(params = {}) {
        try {
            const meetings = await api.getMeetings(params);
            this.data.meetings = meetings;
            const tbody = document.getElementById('meetings-tbody');
            if (meetings.length === 0) {
                tbody.innerHTML = '<tr><td colspan="7" class="table-empty">No meetings recorded yet.</td></tr>';
                return;
            }
            tbody.innerHTML = meetings.map(m => `
                <tr>
                    <td style="color:var(--text-primary);font-weight:600">${esc(m.title)}</td>
                    <td>${formatDateTime(m.meeting_date)}</td>
                    <td><span class="badge-type">${m.meeting_type}</span></td>
                    <td>${esc(m.attorney_name || '—')}</td>
                    <td>${esc(m.matter_title || '—')}</td>
                    <td>${m.duration_minutes ? m.duration_minutes + ' min' : '—'}</td>
                    <td>
                        <button class="btn btn-sm btn-ghost" onclick="App.editMeeting('${m.id}')">Edit</button>
                    </td>
                </tr>
            `).join('');
        } catch (err) {
            toast('Failed to load meetings: ' + err.message, 'error');
        }
    },

    // ── Timeline (Global) ───────────────────────────────────────────────────
    async loadTimeline(params = {}) {
        try {
            const entries = await api.getTimeline(params);
            const container = document.getElementById('timeline-list');
            if (entries.length === 0) {
                container.innerHTML = '<div class="table-empty">No timeline entries. Add notes to your matters to build your record.</div>';
                return;
            }
            container.innerHTML = entries.map(t => `
                <div class="timeline-item">
                    <div class="timeline-dot ${t.entry_type}"></div>
                    <div class="timeline-content">
                        <div class="title">${esc(t.title)}</div>
                        ${t.body ? `<div class="body">${esc(t.body)}</div>` : ''}
                        <div class="meta">
                            <span class="badge-type">${t.entry_type}</span>
                            <span>${formatDateTime(t.created_at)}</span>
                            ${t.attorney_name ? `<span>${esc(t.attorney_name)}</span>` : ''}
                            ${t.importance !== 'normal' ? `<span class="badge-status ${t.importance}">${t.importance}</span>` : ''}
                        </div>
                    </div>
                </div>
            `).join('');
        } catch (err) {
            toast('Failed to load timeline: ' + err.message, 'error');
        }
    },

    // ── Modals ──────────────────────────────────────────────────────────────
    showModal(id) {
        document.getElementById(id).classList.add('active');
    },

    closeModal(id) {
        document.getElementById(id).classList.remove('active');
        this.editingId = null;
    },

    async populateAttorneyDropdowns() {
        if (this.data.attorneys.length === 0) {
            try { this.data.attorneys = await api.getAttorneys({ status: 'active' }); } catch (e) {}
        }
        document.querySelectorAll('.attorney-select').forEach(sel => {
            const current = sel.value;
            sel.innerHTML = '<option value="">— None —</option>' +
                this.data.attorneys.map(a => `<option value="${a.id}">${esc(a.full_name)}${a.firm_name ? ' (' + esc(a.firm_name) + ')' : ''}</option>`).join('');
            if (current) sel.value = current;
        });
    },

    async populateMatterDropdowns() {
        if (this.data.matters.length === 0) {
            try { this.data.matters = await api.getMatters(); } catch (e) {}
        }
        document.querySelectorAll('.matter-select').forEach(sel => {
            const current = sel.value;
            sel.innerHTML = '<option value="">— None —</option>' +
                this.data.matters.map(m => `<option value="${m.id}">${esc(m.title)}</option>`).join('');
            if (current) sel.value = current;
        });
    },

    // ── Attorney CRUD ───────────────────────────────────────────────────────
    async showAddAttorney() {
        this.editingId = null;
        document.getElementById('attorney-modal-title').textContent = 'Add Attorney';
        document.getElementById('atty-form').reset();
        this.showModal('attorney-modal');
    },

    async editAttorney(id) {
        try {
            const a = await api.getAttorney(id);
            this.editingId = id;
            document.getElementById('attorney-modal-title').textContent = 'Edit Attorney';
            document.getElementById('atty-first-name').value = a.first_name || '';
            document.getElementById('atty-last-name').value = a.last_name || '';
            document.getElementById('atty-firm').value = a.firm_name || '';
            document.getElementById('atty-specialty').value = a.specialty || '';
            document.getElementById('atty-email').value = a.email || '';
            document.getElementById('atty-phone').value = a.phone || '';
            document.getElementById('atty-bar-number').value = a.bar_number || '';
            document.getElementById('atty-bar-state').value = a.bar_state || '';
            document.getElementById('atty-hourly-rate').value = a.hourly_rate || '';
            document.getElementById('atty-retainer').value = a.retainer_amount || '';
            document.getElementById('atty-retainer-status').value = a.retainer_status || 'none';
            document.getElementById('atty-engagement-date').value = a.engagement_date || '';
            document.getElementById('atty-status').value = a.status || 'active';
            document.getElementById('atty-notes').value = a.notes || '';
            this.showModal('attorney-modal');
        } catch (err) {
            toast('Failed to load attorney: ' + err.message, 'error');
        }
    },

    async saveAttorney() {
        const data = {
            first_name: val('atty-first-name'),
            last_name: val('atty-last-name'),
            firm_name: val('atty-firm') || null,
            specialty: val('atty-specialty') || null,
            email: val('atty-email') || null,
            phone: val('atty-phone') || null,
            bar_number: val('atty-bar-number') || null,
            bar_state: val('atty-bar-state') || null,
            hourly_rate: val('atty-hourly-rate') ? parseFloat(val('atty-hourly-rate')) : null,
            retainer_amount: val('atty-retainer') ? parseFloat(val('atty-retainer')) : null,
            retainer_status: val('atty-retainer-status'),
            engagement_date: val('atty-engagement-date') || null,
            status: val('atty-status'),
            notes: val('atty-notes') || null,
        };
        if (!data.first_name || !data.last_name) { toast('First and last name are required.', 'error'); return; }
        try {
            if (this.editingId) {
                await api.updateAttorney(this.editingId, data);
                toast('Attorney updated.', 'success');
            } else {
                await api.createAttorney(data);
                toast('Attorney added.', 'success');
            }
            this.closeModal('attorney-modal');
            if (this.currentPage === 'attorneys') await this.loadAttorneys();
            if (this.currentPage === 'dashboard') await this.loadDashboard();
        } catch (err) {
            toast('Save failed: ' + err.message, 'error');
        }
    },

    // ── Matter CRUD ─────────────────────────────────────────────────────────
    async showAddMatter() {
        this.editingId = null;
        document.getElementById('matter-modal-title').textContent = 'New Matter';
        document.getElementById('matter-form').reset();
        await this.populateAttorneyDropdowns();
        this.showModal('matter-modal');
    },

    async editMatter(id) {
        try {
            const m = await api.getMatter(id);
            this.editingId = id;
            await this.populateAttorneyDropdowns();
            document.getElementById('matter-modal-title').textContent = 'Edit Matter';
            document.getElementById('mtr-title').value = m.title || '';
            document.getElementById('mtr-ref').value = m.reference_code || '';
            document.getElementById('mtr-category').value = m.category || 'general';
            document.getElementById('mtr-status').value = m.status || 'open';
            document.getElementById('mtr-priority').value = m.priority || 'normal';
            document.getElementById('mtr-attorney').value = m.attorney_id || '';
            document.getElementById('mtr-opposing').value = m.opposing_party || '';
            document.getElementById('mtr-opposing-counsel').value = m.opposing_counsel || '';
            document.getElementById('mtr-amount').value = m.amount_at_stake || '';
            document.getElementById('mtr-next-action').value = m.next_action || '';
            document.getElementById('mtr-next-date').value = m.next_action_date || '';
            document.getElementById('mtr-description').value = m.description || '';
            this.showModal('matter-modal');
        } catch (err) {
            toast('Failed to load matter: ' + err.message, 'error');
        }
    },

    async saveMatter() {
        const data = {
            title: val('mtr-title'),
            reference_code: val('mtr-ref') || null,
            category: val('mtr-category'),
            status: val('mtr-status'),
            priority: val('mtr-priority'),
            attorney_id: val('mtr-attorney') || null,
            opposing_party: val('mtr-opposing') || null,
            opposing_counsel: val('mtr-opposing-counsel') || null,
            amount_at_stake: val('mtr-amount') ? parseFloat(val('mtr-amount')) : null,
            next_action: val('mtr-next-action') || null,
            next_action_date: val('mtr-next-date') || null,
            description: val('mtr-description') || null,
        };
        if (!data.title) { toast('Title is required.', 'error'); return; }
        try {
            if (this.editingId) {
                await api.updateMatter(this.editingId, data);
                toast('Matter updated.', 'success');
            } else {
                await api.createMatter(data);
                toast('Matter created.', 'success');
            }
            this.closeModal('matter-modal');
            if (this.currentPage === 'matters') await this.loadMatters();
            if (this.currentPage === 'dashboard') await this.loadDashboard();
        } catch (err) {
            toast('Save failed: ' + err.message, 'error');
        }
    },

    // ── Meeting CRUD ────────────────────────────────────────────────────────
    async showAddMeeting(matterId = null) {
        this.editingId = null;
        document.getElementById('meeting-modal-title').textContent = 'Log Meeting';
        document.getElementById('meeting-form').reset();
        await Promise.all([this.populateAttorneyDropdowns(), this.populateMatterDropdowns()]);
        if (matterId) document.getElementById('mtg-matter').value = matterId;
        // Default date to now
        const now = new Date();
        now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
        document.getElementById('mtg-date').value = now.toISOString().slice(0, 16);
        this.showModal('meeting-modal');
    },

    async editMeeting(id) {
        try {
            const m = await api.getMeeting(id);
            this.editingId = id;
            await Promise.all([this.populateAttorneyDropdowns(), this.populateMatterDropdowns()]);
            document.getElementById('meeting-modal-title').textContent = 'Edit Meeting';
            document.getElementById('mtg-title').value = m.title || '';
            document.getElementById('mtg-type').value = m.meeting_type || 'in_person';
            document.getElementById('mtg-date').value = m.meeting_date ? m.meeting_date.slice(0, 16) : '';
            document.getElementById('mtg-duration').value = m.duration_minutes || '';
            document.getElementById('mtg-location').value = m.location || '';
            document.getElementById('mtg-attorney').value = m.attorney_id || '';
            document.getElementById('mtg-matter').value = m.matter_id || '';
            document.getElementById('mtg-attendees').value = m.attendees || '';
            document.getElementById('mtg-summary').value = m.summary || '';
            document.getElementById('mtg-action-items').value = m.action_items || '';
            document.getElementById('mtg-decisions').value = m.key_decisions || '';
            document.getElementById('mtg-cost').value = m.cost || '';
            document.getElementById('mtg-followup-date').value = m.follow_up_date || '';
            document.getElementById('mtg-followup-notes').value = m.follow_up_notes || '';
            this.showModal('meeting-modal');
        } catch (err) {
            toast('Failed to load meeting: ' + err.message, 'error');
        }
    },

    async saveMeeting() {
        const data = {
            title: val('mtg-title'),
            meeting_type: val('mtg-type'),
            meeting_date: val('mtg-date') ? new Date(val('mtg-date')).toISOString() : null,
            duration_minutes: val('mtg-duration') ? parseInt(val('mtg-duration')) : null,
            location: val('mtg-location') || null,
            attorney_id: val('mtg-attorney') || null,
            matter_id: val('mtg-matter') || null,
            attendees: val('mtg-attendees') || null,
            summary: val('mtg-summary') || null,
            action_items: val('mtg-action-items') || null,
            key_decisions: val('mtg-decisions') || null,
            cost: val('mtg-cost') ? parseFloat(val('mtg-cost')) : null,
            follow_up_date: val('mtg-followup-date') || null,
            follow_up_notes: val('mtg-followup-notes') || null,
        };
        if (!data.title || !data.meeting_date) { toast('Title and date are required.', 'error'); return; }
        try {
            if (this.editingId) {
                await api.updateMeeting(this.editingId, data);
                toast('Meeting updated.', 'success');
            } else {
                await api.createMeeting(data);
                toast('Meeting logged.', 'success');
            }
            this.closeModal('meeting-modal');
            if (this.currentPage === 'meetings') await this.loadMeetings();
            if (this.currentPage === 'dashboard') await this.loadDashboard();
            if (this.currentMatterId) await this.viewMatter(this.currentMatterId);
        } catch (err) {
            toast('Save failed: ' + err.message, 'error');
        }
    },

    // ── Timeline Entry (Quick Add from Matter Detail) ───────────────────────
    async showAddTimelineEntry(matterId) {
        document.getElementById('tl-matter-id').value = matterId || this.currentMatterId || '';
        document.getElementById('tl-form').reset();
        document.getElementById('tl-matter-id').value = matterId || this.currentMatterId || '';
        await this.populateAttorneyDropdowns();
        this.showModal('timeline-modal');
    },

    async saveTimelineEntry() {
        const data = {
            matter_id: val('tl-matter-id'),
            entry_type: val('tl-type'),
            title: val('tl-title'),
            body: val('tl-body') || null,
            importance: val('tl-importance'),
            related_attorney_id: val('tl-attorney') || null,
            document_ref: val('tl-doc-ref') || null,
        };
        if (!data.matter_id || !data.title) { toast('Matter and title required.', 'error'); return; }
        try {
            await api.createTimelineEntry(data);
            toast('Entry added.', 'success');
            this.closeModal('timeline-modal');
            if (this.currentMatterId) await this.viewMatter(this.currentMatterId);
            if (this.currentPage === 'timeline') await this.loadTimeline();
        } catch (err) {
            toast('Save failed: ' + err.message, 'error');
        }
    },
};

// ── Utilities ───────────────────────────────────────────────────────────────

function val(id) { const el = document.getElementById(id); return el ? el.value.trim() : ''; }

function esc(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function formatDate(iso) {
    if (!iso) return '—';
    try { return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }); }
    catch { return iso; }
}

function formatDateTime(iso) {
    if (!iso) return '—';
    try { return new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' }); }
    catch { return iso; }
}

function toast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = message;
    container.appendChild(el);
    setTimeout(() => el.remove(), 4000);
}

// Boot
document.addEventListener('DOMContentLoaded', () => App.init());
