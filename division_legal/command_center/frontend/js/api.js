/**
 * Fortress Legal Command Center — API Client
 */
class LegalAPI {
    constructor(baseURL = '') {
        this.baseURL = baseURL || window.location.origin;
        this.apiBase = this.baseURL + '/api';
    }

    async request(endpoint, options = {}) {
        const url = `${this.apiBase}${endpoint}`;
        const headers = {
            'Content-Type': 'application/json',
            ...options.headers,
        };
        try {
            const response = await fetch(url, { ...options, headers });
            if (!response.ok) {
                const error = await response.json().catch(() => ({ detail: response.statusText }));
                throw new Error(error.detail || `HTTP ${response.status}`);
            }
            if (response.status === 204) return null;
            return await response.json();
        } catch (error) {
            console.error(`API Error [${endpoint}]:`, error.message);
            throw error;
        }
    }

    get(endpoint) { return this.request(endpoint); }
    post(endpoint, data) { return this.request(endpoint, { method: 'POST', body: JSON.stringify(data) }); }
    patch(endpoint, data) { return this.request(endpoint, { method: 'PATCH', body: JSON.stringify(data) }); }
    del(endpoint) { return this.request(endpoint, { method: 'DELETE' }); }

    // Attorneys
    getAttorneys(params = {}) { const qs = new URLSearchParams(params).toString(); return this.get(`/attorneys/${qs ? '?' + qs : ''}`); }
    getAttorney(id) { return this.get(`/attorneys/${id}`); }
    createAttorney(data) { return this.post('/attorneys/', data); }
    updateAttorney(id, data) { return this.patch(`/attorneys/${id}`, data); }
    deleteAttorney(id) { return this.del(`/attorneys/${id}`); }

    // Matters
    getMatters(params = {}) { const qs = new URLSearchParams(params).toString(); return this.get(`/matters/${qs ? '?' + qs : ''}`); }
    getMatter(id) { return this.get(`/matters/${id}`); }
    getMatterStats() { return this.get('/matters/stats'); }
    createMatter(data) { return this.post('/matters/', data); }
    updateMatter(id, data) { return this.patch(`/matters/${id}`, data); }
    deleteMatter(id) { return this.del(`/matters/${id}`); }

    // Meetings
    getMeetings(params = {}) { const qs = new URLSearchParams(params).toString(); return this.get(`/meetings/${qs ? '?' + qs : ''}`); }
    getMeeting(id) { return this.get(`/meetings/${id}`); }
    getUpcomingMeetings(days = 30) { return this.get(`/meetings/upcoming?days=${days}`); }
    getFollowUps() { return this.get('/meetings/follow-ups'); }
    createMeeting(data) { return this.post('/meetings/', data); }
    updateMeeting(id, data) { return this.patch(`/meetings/${id}`, data); }
    deleteMeeting(id) { return this.del(`/meetings/${id}`); }

    // Timeline
    getTimeline(params = {}) { const qs = new URLSearchParams(params).toString(); return this.get(`/timeline/${qs ? '?' + qs : ''}`); }
    createTimelineEntry(data) { return this.post('/timeline/', data); }
    updateTimelineEntry(id, data) { return this.patch(`/timeline/${id}`, data); }
    deleteTimelineEntry(id) { return this.del(`/timeline/${id}`); }

    // Documents
    getDocuments(params = {}) { const qs = new URLSearchParams(params).toString(); return this.get(`/documents/${qs ? '?' + qs : ''}`); }
    createDocument(data) { return this.post('/documents/', data); }
    deleteDocument(id) { return this.del(`/documents/${id}`); }
}

const api = new LegalAPI();
