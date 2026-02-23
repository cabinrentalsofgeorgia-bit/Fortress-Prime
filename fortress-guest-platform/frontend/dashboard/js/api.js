/**
 * Fortress Guest Platform — API Client
 * Handles all communication with the FastAPI backend
 */
class FortressAPI {
    constructor(baseURL = '') {
        this.baseURL = baseURL || window.location.origin;
        this.apiBase = this.baseURL + '/api';
        this.token = localStorage.getItem('fgp_token');
    }

    async request(endpoint, options = {}) {
        const url = endpoint.startsWith('http') ? endpoint : `${this.apiBase}${endpoint}`;
        const headers = {
            'Content-Type': 'application/json',
            ...(this.token ? { 'Authorization': `Bearer ${this.token}` } : {}),
            ...options.headers,
        };

        try {
            const response = await fetch(url, {
                ...options,
                headers,
            });

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
    put(endpoint, data) { return this.request(endpoint, { method: 'PUT', body: JSON.stringify(data) }); }
    patch(endpoint, data) { return this.request(endpoint, { method: 'PATCH', body: JSON.stringify(data) }); }
    delete(endpoint) { return this.request(endpoint, { method: 'DELETE' }); }

    // === Dashboard ===
    async getDashboardStats() {
        return this.get('/analytics/dashboard');
    }

    // === Properties ===
    async getProperties(params = {}) {
        const qs = new URLSearchParams(params).toString();
        return this.get(`/properties/${qs ? '?' + qs : ''}`);
    }

    async getProperty(id) { return this.get(`/properties/${id}`); }

    async createProperty(data) { return this.post('/properties/', data); }

    // === Guests (Enterprise Guest Management) ===
    async getGuests(params = {}) {
        const qs = new URLSearchParams(params).toString();
        return this.get(`/guests/${qs ? '?' + qs : ''}`);
    }
    async getGuest(id) { return this.get(`/guests/${id}`); }
    async getGuest360(id) { return this.get(`/guests/${id}/360`); }
    async createGuest(data) { return this.post('/guests/', data); }
    async updateGuest(id, data) { return this.patch(`/guests/${id}`, data); }
    async getGuestAnalytics(days = 30) { return this.get(`/guests/analytics?days=${days}`); }
    async getGuestByPhone(phone) { return this.get(`/guests/phone/${encodeURIComponent(phone)}`); }
    async getGuestsArrivingToday() { return this.get('/guests/arriving/today'); }
    async getGuestsStayingNow() { return this.get('/guests/staying/now'); }
    async getGuestsDepartingToday() { return this.get('/guests/departing/today'); }
    async recalculateGuestScores(id) { return this.post(`/guests/${id}/recalculate-scores`, {}); }
    async batchRecalculateScores() { return this.post('/guests/batch-recalculate-scores', {}); }
    async segmentGuests(criteria) { return this.post('/guests/segment', criteria); }
    async findDuplicates(id) { return this.get(`/guests/${id}/duplicates`); }
    async mergeGuests(primaryId, secondaryId) { return this.post('/guests/merge', { primary_id: primaryId, secondary_id: secondaryId }); }
    async submitGuestReview(guestId, data) { return this.post(`/guests/${guestId}/reviews`, data); }
    async submitManagerReview(guestId, data) { return this.post(`/guests/${guestId}/manager-review`, data); }
    async respondToReview(reviewId, data) { return this.post(`/guests/reviews/${reviewId}/respond`, data); }
    async getReviewAnalytics(days = 90) { return this.get(`/guests/reviews/analytics?days=${days}`); }
    async sendSurvey(guestId, data) { return this.post(`/guests/${guestId}/surveys/send`, data); }
    async getNPS(days = 90) { return this.get(`/guests/surveys/nps?days=${days}`); }
    async blacklistGuest(id, data) { return this.post(`/guests/${id}/blacklist`, data); }
    async removeBlacklist(id) { return this.delete(`/guests/${id}/blacklist`); }
    async toggleVIP(id, isVip) { return this.post(`/guests/${id}/vip`, { is_vip: isVip }); }
    async getGuestActivity(id) { return this.get(`/guests/${id}/activity`); }

    // === Reservations ===
    async getReservations(params = {}) {
        const qs = new URLSearchParams(params).toString();
        return this.get(`/reservations/${qs ? '?' + qs : ''}`);
    }

    async getReservation(id) { return this.get(`/reservations/${id}`); }
    async createReservation(data) { return this.post('/reservations/', data); }

    // === Messages ===
    async getMessages(params = {}) {
        const qs = new URLSearchParams(params).toString();
        return this.get(`/messages/${qs ? '?' + qs : ''}`);
    }

    async sendMessage(data) { return this.post('/messages/send', data); }

    async getConversation(guestId) {
        return this.get(`/messages/conversation/${guestId}`);
    }

    // === Work Orders ===
    async getWorkOrders(params = {}) {
        const qs = new URLSearchParams(params).toString();
        return this.get(`/workorders/${qs ? '?' + qs : ''}`);
    }

    async createWorkOrder(data) { return this.post('/workorders/', data); }
    async updateWorkOrder(id, data) { return this.patch(`/workorders/${id}`, data); }

    // === Guestbook ===
    async getGuides(params = {}) {
        const qs = new URLSearchParams(params).toString();
        return this.get(`/guestbook/${qs ? '?' + qs : ''}`);
    }

    async createGuide(data) { return this.post('/guestbook/', data); }

    // === Analytics ===
    async getAnalytics(period = '30d') {
        return this.get(`/analytics/?period=${period}`);
    }

    // === Integrations ===
    async getStreamlineStatus() {
        return this.get('/integrations/streamline/status');
    }

    async triggerStreamlineSync() {
        return this.post('/integrations/streamline/sync', {});
    }

    // === Health ===
    async getHealth() {
        const url = this.baseURL + '/health';
        return this.request(url);
    }
}

window.api = new FortressAPI();
