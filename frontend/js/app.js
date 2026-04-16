/**
 * StressForge — Dashboard Application Logic
 * Vanilla JS SPA with tab navigation, API calls, real-time charts.
 */

// ═══════════════════════════════════════
// State
// ═══════════════════════════════════════
const API_BASE = '/api';
let authToken = localStorage.getItem('sf_token');
let currentUser = JSON.parse(localStorage.getItem('sf_user') || 'null');
let currentTab = 'dashboard';
let productsPage = 1;
let metricsInterval = null;
let chartData = [];
const MAX_CHART_POINTS = 60;

// ═══════════════════════════════════════
// Init
// ═══════════════════════════════════════
document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    initAuth();
    checkApiStatus();
    loadDashboard();
    startMetricsPolling();
});

// ═══════════════════════════════════════
// Navigation
// ═══════════════════════════════════════
function initNavigation() {
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const tab = item.dataset.tab;
            switchTab(tab);
        });
    });

    // Mobile menu toggle
    const toggle = document.getElementById('menu-toggle');
    if (toggle) {
        toggle.addEventListener('click', () => {
            document.getElementById('sidebar').classList.toggle('open');
        });
    }

    // Product search
    const searchInput = document.getElementById('product-search');
    if (searchInput) {
        let debounce;
        searchInput.addEventListener('input', () => {
            clearTimeout(debounce);
            debounce = setTimeout(() => {
                productsPage = 1;
                loadProducts();
            }, 400);
        });
    }

    // Category filter
    const catSelect = document.getElementById('product-category');
    if (catSelect) {
        catSelect.addEventListener('change', () => {
            productsPage = 1;
            loadProducts();
        });
    }
}

function switchTab(tab) {
    currentTab = tab;

    // Update nav
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    const navItem = document.querySelector(`[data-tab="${tab}"]`);
    if (navItem) navItem.classList.add('active');

    // Update content
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    const tabContent = document.getElementById(`tab-${tab}`);
    if (tabContent) tabContent.classList.add('active');

    // Update title
    const titles = {
        dashboard: 'Dashboard',
        products: 'Product Catalog',
        orders: 'Order Management',
        stress: 'Stress Testing',
        metrics: 'System Metrics'
    };
    document.getElementById('page-title').textContent = titles[tab] || tab;

    // Load tab data
    if (tab === 'products') loadProducts();
    if (tab === 'orders') loadOrders();
    if (tab === 'metrics') refreshMetrics();

    // Close mobile sidebar
    document.getElementById('sidebar').classList.remove('open');
}

// ═══════════════════════════════════════
// Auth
// ═══════════════════════════════════════
function initAuth() {
    if (authToken && currentUser) {
        showLoggedIn();
    }
}

function showLoggedIn() {
    document.getElementById('auth-section').classList.add('hidden');
    document.getElementById('user-section').classList.remove('hidden');
    document.getElementById('user-display').textContent = currentUser?.username || currentUser?.email;
}

function showLoggedOut() {
    document.getElementById('auth-section').classList.remove('hidden');
    document.getElementById('user-section').classList.add('hidden');
}

function showAuthModal() {
    document.getElementById('auth-modal').classList.remove('hidden');
}

function switchAuthTab(tab) {
    if (tab === 'login') {
        document.getElementById('login-form').classList.remove('hidden');
        document.getElementById('register-form').classList.add('hidden');
        document.getElementById('tab-btn-login').classList.add('active');
        document.getElementById('tab-btn-register').classList.remove('active');
        document.getElementById('auth-modal-title').textContent = 'Sign In';
    } else {
        document.getElementById('login-form').classList.add('hidden');
        document.getElementById('register-form').classList.remove('hidden');
        document.getElementById('tab-btn-login').classList.remove('active');
        document.getElementById('tab-btn-register').classList.add('active');
        document.getElementById('auth-modal-title').textContent = 'Create Account';
    }
}

async function handleLogin(e) {
    e.preventDefault();
    const email = document.getElementById('login-email').value;
    const password = document.getElementById('login-password').value;

    try {
        const data = await apiCall('/auth/login', 'POST', { email, password });
        authToken = data.access_token;
        currentUser = data.user;
        localStorage.setItem('sf_token', authToken);
        localStorage.setItem('sf_user', JSON.stringify(currentUser));
        showLoggedIn();
        closeModal('auth-modal');
        showToast('Signed in successfully!', 'success');
    } catch (err) {
        showFormError('login-error', err.message);
    }
}

async function handleRegister(e) {
    e.preventDefault();
    const username = document.getElementById('reg-username').value;
    const email = document.getElementById('reg-email').value;
    const password = document.getElementById('reg-password').value;

    try {
        const data = await apiCall('/auth/register', 'POST', { username, email, password });
        authToken = data.access_token;
        currentUser = data.user;
        localStorage.setItem('sf_token', authToken);
        localStorage.setItem('sf_user', JSON.stringify(currentUser));
        showLoggedIn();
        closeModal('auth-modal');
        showToast('Account created successfully!', 'success');
    } catch (err) {
        showFormError('register-error', err.message);
    }
}

function logout() {
    authToken = null;
    currentUser = null;
    localStorage.removeItem('sf_token');
    localStorage.removeItem('sf_user');
    showLoggedOut();
    showToast('Signed out', 'info');
}

// ═══════════════════════════════════════
// API Calls
// ═══════════════════════════════════════
async function apiCall(endpoint, method = 'GET', body = null) {
    const headers = { 'Content-Type': 'application/json' };
    if (authToken) {
        headers['Authorization'] = `Bearer ${authToken}`;
    }

    const opts = { method, headers };
    if (body) opts.body = JSON.stringify(body);

    const res = await fetch(`${API_BASE}${endpoint}`, opts);

    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Request failed' }));
        throw new Error(err.detail || `HTTP ${res.status}`);
    }

    return res.json();
}

// ═══════════════════════════════════════
// Dashboard
// ═══════════════════════════════════════
async function loadDashboard() {
    try {
        const metrics = await apiCall('/metrics');

        document.getElementById('stat-products-value').textContent = formatNumber(metrics.database?.products || 0);
        document.getElementById('stat-users-value').textContent = formatNumber(metrics.database?.users || 0);
        document.getElementById('stat-orders-value').textContent = formatNumber(metrics.database?.orders || 0);
        document.getElementById('stat-uptime-value').textContent = formatUptime(metrics.uptime_seconds || 0);

    } catch (err) {
        console.error('Dashboard load error:', err);
    }
}

async function checkApiStatus() {
    const statusDot = document.querySelector('#api-status .status-dot');
    const statusText = document.querySelector('#api-status .status-text');

    try {
        const start = performance.now();
        const health = await apiCall('/health/ready');
        const latency = Math.round(performance.now() - start);

        if (health.status === 'ready') {
            statusDot.className = 'status-dot connected';
            statusText.textContent = `Connected (${latency}ms)`;

            // Update service cards
            updateServiceCard('svc-api', 'healthy', `${latency}ms`);
            updateServiceCard('svc-db', health.database === 'connected' ? 'healthy' : 'unhealthy');
            updateServiceCard('svc-redis', health.redis === 'connected' ? 'healthy' : 'unhealthy');
        } else {
            statusDot.className = 'status-dot error';
            statusText.textContent = 'Degraded';
        }
    } catch (err) {
        statusDot.className = 'status-dot error';
        statusText.textContent = 'Disconnected';
        updateServiceCard('svc-api', 'unhealthy');
    }
}

function updateServiceCard(id, status, latency) {
    const card = document.getElementById(id);
    if (!card) return;
    const dot = card.querySelector('.service-status-dot');
    dot.className = `service-status-dot ${status}`;
    if (latency) {
        const latEl = card.querySelector('.service-latency');
        if (latEl) latEl.textContent = latency;
    }
}

// ═══════════════════════════════════════
// Response Time Chart (Canvas)
// ═══════════════════════════════════════
function drawChart() {
    const canvas = document.getElementById('response-chart');
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    const rect = canvas.parentElement.getBoundingClientRect();
    canvas.width = rect.width * (window.devicePixelRatio || 1);
    canvas.height = rect.height * (window.devicePixelRatio || 1);
    ctx.scale(window.devicePixelRatio || 1, window.devicePixelRatio || 1);

    const w = rect.width;
    const h = rect.height;
    const padding = { top: 20, right: 20, bottom: 40, left: 60 };
    const chartW = w - padding.left - padding.right;
    const chartH = h - padding.top - padding.bottom;

    // Clear
    ctx.clearRect(0, 0, w, h);

    if (chartData.length < 2) {
        ctx.fillStyle = '#6b6b82';
        ctx.font = '14px Inter, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('Collecting data...', w / 2, h / 2);
        return;
    }

    const maxVal = Math.max(...chartData.map(d => d.value), 100);
    const minVal = 0;

    // Grid lines
    ctx.strokeStyle = '#1f1f2e';
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
        const y = padding.top + (chartH / 4) * i;
        ctx.beginPath();
        ctx.moveTo(padding.left, y);
        ctx.lineTo(w - padding.right, y);
        ctx.stroke();

        // Labels
        const val = Math.round(maxVal - (maxVal / 4) * i);
        ctx.fillStyle = '#6b6b82';
        ctx.font = '11px JetBrains Mono, monospace';
        ctx.textAlign = 'right';
        ctx.fillText(`${val}ms`, padding.left - 8, y + 4);
    }

    // Line
    const gradient = ctx.createLinearGradient(0, padding.top, 0, h - padding.bottom);
    gradient.addColorStop(0, 'rgba(129, 140, 248, 0.3)');
    gradient.addColorStop(1, 'rgba(129, 140, 248, 0)');

    ctx.beginPath();
    chartData.forEach((d, i) => {
        const x = padding.left + (chartW / (chartData.length - 1)) * i;
        const y = padding.top + chartH - ((d.value - minVal) / (maxVal - minVal)) * chartH;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    });

    // Fill area
    ctx.strokeStyle = '#818cf8';
    ctx.lineWidth = 2;
    ctx.stroke();

    // Area fill
    const lastX = padding.left + chartW;
    const lastY = padding.top + chartH - ((chartData[chartData.length - 1].value - minVal) / (maxVal - minVal)) * chartH;
    ctx.lineTo(lastX, padding.top + chartH);
    ctx.lineTo(padding.left, padding.top + chartH);
    ctx.closePath();
    ctx.fillStyle = gradient;
    ctx.fill();

    // Dots
    chartData.forEach((d, i) => {
        const x = padding.left + (chartW / (chartData.length - 1)) * i;
        const y = padding.top + chartH - ((d.value - minVal) / (maxVal - minVal)) * chartH;

        ctx.beginPath();
        ctx.arc(x, y, 3, 0, Math.PI * 2);
        ctx.fillStyle = '#818cf8';
        ctx.fill();
    });

    // X-axis label
    ctx.fillStyle = '#6b6b82';
    ctx.font = '11px Inter, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('Time →', w / 2, h - 8);
}

async function collectChartPoint() {
    try {
        const start = performance.now();
        await apiCall('/health');
        const latency = Math.round(performance.now() - start);

        chartData.push({ value: latency, time: Date.now() });
        if (chartData.length > MAX_CHART_POINTS) chartData.shift();

        document.getElementById('svc-api-latency').textContent = `${latency}ms`;
        drawChart();
    } catch (err) {
        // Skip point on error
    }
}

// ═══════════════════════════════════════
// Products
// ═══════════════════════════════════════
async function loadProducts() {
    const grid = document.getElementById('products-grid');
    const search = document.getElementById('product-search')?.value || '';
    const category = document.getElementById('product-category')?.value || '';

    grid.innerHTML = '<div class="loading-skeleton">Loading products...</div>';

    try {
        let endpoint = `/products?page=${productsPage}&per_page=20`;
        if (search) endpoint += `&search=${encodeURIComponent(search)}`;
        if (category) endpoint += `&category=${encodeURIComponent(category)}`;

        const data = await apiCall(endpoint);

        if (data.items.length === 0) {
            grid.innerHTML = '<div class="empty-state">No products found</div>';
            return;
        }

        grid.innerHTML = data.items.map(p => `
            <div class="product-card">
                <div class="product-img">📦</div>
                <div class="product-body">
                    <div class="product-name" title="${escapeHtml(p.name)}">${escapeHtml(p.name)}</div>
                    <div class="product-category">${escapeHtml(p.category || 'Uncategorized')}</div>
                    <div class="product-footer">
                        <span class="product-price">$${p.price.toFixed(2)}</span>
                        <span class="product-stock">${p.stock} in stock</span>
                    </div>
                    <div class="product-sku">SKU: ${escapeHtml(p.sku)}</div>
                </div>
            </div>
        `).join('');

        // Pagination
        renderPagination(data.page, data.pages, data.total);

        // Load categories if empty
        loadCategories();
    } catch (err) {
        grid.innerHTML = `<div class="empty-state">Error: ${escapeHtml(err.message)}</div>`;
    }
}

async function loadCategories() {
    const select = document.getElementById('product-category');
    if (select.options.length > 1) return; // Already loaded

    try {
        const data = await apiCall('/products/categories');
        data.categories.forEach(cat => {
            const opt = document.createElement('option');
            opt.value = cat;
            opt.textContent = cat;
            select.appendChild(opt);
        });
    } catch (err) {
        console.error('Failed to load categories:', err);
    }
}

function renderPagination(current, total, totalItems) {
    const container = document.getElementById('products-pagination');
    if (total <= 1) {
        container.innerHTML = '';
        return;
    }

    let html = '';
    const start = Math.max(1, current - 3);
    const end = Math.min(total, current + 3);

    if (current > 1) {
        html += `<button class="page-btn" onclick="goToPage(${current - 1})">‹</button>`;
    }

    for (let i = start; i <= end; i++) {
        html += `<button class="page-btn ${i === current ? 'active' : ''}" onclick="goToPage(${i})">${i}</button>`;
    }

    if (current < total) {
        html += `<button class="page-btn" onclick="goToPage(${current + 1})">›</button>`;
    }

    container.innerHTML = html;
}

function goToPage(page) {
    productsPage = page;
    loadProducts();
}

// ═══════════════════════════════════════
// Orders
// ═══════════════════════════════════════
async function loadOrders() {
    // Load stats
    try {
        const stats = await apiCall('/orders/stats');
        document.getElementById('os-total').textContent = formatNumber(stats.total_orders);
        document.getElementById('os-revenue').textContent = `$${formatNumber(stats.total_revenue)}`;
        document.getElementById('os-pending').textContent = formatNumber(stats.pending);
        document.getElementById('os-completed').textContent = formatNumber(stats.completed);
    } catch (err) {
        console.error('Order stats error:', err);
    }

    // Load user orders
    if (!authToken) {
        document.getElementById('orders-list').innerHTML = '<div class="empty-state">Sign in to view your orders</div>';
        return;
    }

    try {
        const data = await apiCall('/orders?page=1&per_page=50');
        if (!data.items || data.items.length === 0) {
            document.getElementById('orders-list').innerHTML = '<div class="empty-state">No orders yet. Place your first order!</div>';
            return;
        }

        document.getElementById('orders-list').innerHTML = data.items.map(o => `
            <div class="order-row">
                <span class="order-id">#${o.id}</span>
                <span class="order-status ${o.status}">${o.status}</span>
                <span class="order-items-count">${o.items?.length || 0} items</span>
                <span class="order-total">$${o.total.toFixed(2)}</span>
                <span class="order-date">${formatDate(o.created_at)}</span>
            </div>
        `).join('');
    } catch (err) {
        document.getElementById('orders-list').innerHTML = `<div class="empty-state">Error: ${escapeHtml(err.message)}</div>`;
    }
}

function showOrderModal() {
    if (!authToken) {
        showToast('Please sign in first', 'error');
        showAuthModal();
        return;
    }
    document.getElementById('order-modal').classList.remove('hidden');
}

function showBulkOrderModal() {
    if (!authToken) {
        showToast('Please sign in first', 'error');
        showAuthModal();
        return;
    }
    document.getElementById('bulk-modal').classList.remove('hidden');
    document.getElementById('bulk-result').classList.add('hidden');
}

async function handleOrder(e) {
    e.preventDefault();
    const productId = parseInt(document.getElementById('order-product-id').value);
    const quantity = parseInt(document.getElementById('order-quantity').value);
    const address = document.getElementById('order-address').value;

    try {
        const order = await apiCall('/orders', 'POST', {
            items: [{ product_id: productId, quantity }],
            shipping_address: address || null,
        });
        closeModal('order-modal');
        showToast(`Order #${order.id} placed — $${order.total.toFixed(2)}`, 'success');
        loadOrders();
        loadDashboard();
    } catch (err) {
        showFormError('order-error', err.message);
    }
}

async function handleBulkOrder(e) {
    e.preventDefault();
    const count = parseInt(document.getElementById('bulk-count').value);
    const btn = document.getElementById('btn-submit-bulk');
    const resultDiv = document.getElementById('bulk-result');

    btn.disabled = true;
    btn.textContent = `Creating ${count} orders...`;

    try {
        const result = await apiCall('/orders/bulk', 'POST', { count });
        resultDiv.innerHTML = `
            ✅ Created: <strong>${result.created}</strong> / ${result.total_requested}<br>
            ❌ Errors: ${result.errors}<br>
            ⏱ Duration: ${result.duration_seconds}s<br>
            📊 Rate: ${result.orders_per_second} orders/sec
        `;
        resultDiv.classList.remove('hidden');
        showToast(`${result.created} orders created in ${result.duration_seconds}s`, 'success');
        loadOrders();
        loadDashboard();
    } catch (err) {
        showFormError('bulk-error', err.message);
    } finally {
        btn.disabled = false;
        btn.textContent = 'Create Orders';
    }
}

// ═══════════════════════════════════════
// Stress Testing
// ═══════════════════════════════════════
const stressHistory = [];

async function runStress(type) {
    const intensityMap = {
        cpu: 'cpu-intensity',
        memory: 'mem-intensity',
        io: 'io-intensity',
        mixed: 'mixed-intensity',
    };

    const btnMap = {
        cpu: 'btn-stress-cpu',
        memory: 'btn-stress-mem',
        io: 'btn-stress-io',
        mixed: 'btn-stress-mixed',
    };

    const intensity = parseInt(document.getElementById(intensityMap[type]).value);
    const btn = document.getElementById(btnMap[type]);
    const resultDiv = document.getElementById(`result-${type}`);

    // Show loading
    btn.disabled = true;
    const btnText = btn.querySelector('.btn-text');
    const btnSpinner = btn.querySelector('.btn-spinner');
    if (btnText) btnText.textContent = 'Running...';
    if (btnSpinner) btnSpinner.classList.remove('hidden');

    try {
        const start = performance.now();
        const data = await apiCall(`/stress/${type}`, 'POST', {
            intensity,
            duration_seconds: 5,
        });
        const clientTime = Math.round(performance.now() - start);

        // Show result
        resultDiv.innerHTML = `
            <strong>✅ ${data.type.toUpperCase()} Test Complete</strong><br>
            Server Duration: ${data.duration_ms.toFixed(1)}ms<br>
            Client RTT: ${clientTime}ms<br>
            ${data.result}<br>
            ${data.details ? Object.entries(data.details).map(([k, v]) => `${k}: ${v}`).join('<br>') : ''}
        `;
        resultDiv.classList.add('visible');

        // Add to history
        stressHistory.unshift({
            type,
            intensity,
            duration_ms: data.duration_ms,
            time: new Date(),
        });
        renderStressHistory();

        showToast(`${type.toUpperCase()} stress: ${data.duration_ms.toFixed(0)}ms`, 'success');
    } catch (err) {
        resultDiv.innerHTML = `<strong>❌ Error:</strong> ${escapeHtml(err.message)}`;
        resultDiv.classList.add('visible');
        showToast(`Stress test failed: ${err.message}`, 'error');
    } finally {
        btn.disabled = false;
        if (btnText) btnText.textContent = 'Execute';
        if (btnSpinner) btnSpinner.classList.add('hidden');
    }
}

function renderStressHistory() {
    const container = document.getElementById('stress-history');
    if (stressHistory.length === 0) {
        container.innerHTML = '<div class="empty-state">No tests executed yet</div>';
        return;
    }

    container.innerHTML = stressHistory.slice(0, 50).map(h => `
        <div class="history-entry">
            <span class="history-type ${h.type}">${h.type}</span>
            <span class="history-intensity">×${h.intensity}</span>
            <span class="history-duration">${h.duration_ms.toFixed(1)}ms</span>
            <span class="history-time">${formatTime(h.time)}</span>
        </div>
    `).join('');
}

function clearStressHistory() {
    stressHistory.length = 0;
    renderStressHistory();
    document.querySelectorAll('.stress-result').forEach(el => {
        el.classList.remove('visible');
    });
}

// ═══════════════════════════════════════
// Metrics
// ═══════════════════════════════════════
async function refreshMetrics() {
    const grid = document.getElementById('metrics-grid');
    grid.innerHTML = '<div class="loading-skeleton">Loading metrics...</div>';

    try {
        const data = await apiCall('/metrics');
        const ready = await apiCall('/health/ready');

        grid.innerHTML = `
            <div class="metric-card">
                <h3>Service</h3>
                <div class="metric-rows">
                    <div class="metric-row"><span class="metric-key">Name</span><span class="metric-val">${data.service}</span></div>
                    <div class="metric-row"><span class="metric-key">Version</span><span class="metric-val">${data.version}</span></div>
                    <div class="metric-row"><span class="metric-key">Uptime</span><span class="metric-val">${formatUptime(data.uptime_seconds)}</span></div>
                    <div class="metric-row"><span class="metric-key">Status</span><span class="metric-val" style="color: var(--success)">${ready.status}</span></div>
                </div>
            </div>
            <div class="metric-card">
                <h3>Database</h3>
                <div class="metric-rows">
                    <div class="metric-row"><span class="metric-key">Status</span><span class="metric-val" style="color: ${ready.database === 'connected' ? 'var(--success)' : 'var(--error)'}">${ready.database}</span></div>
                    <div class="metric-row"><span class="metric-key">Users</span><span class="metric-val">${formatNumber(data.database?.users || 0)}</span></div>
                    <div class="metric-row"><span class="metric-key">Products</span><span class="metric-val">${formatNumber(data.database?.products || 0)}</span></div>
                    <div class="metric-row"><span class="metric-key">Orders</span><span class="metric-val">${formatNumber(data.database?.orders || 0)}</span></div>
                </div>
            </div>
            <div class="metric-card">
                <h3>Redis Cache</h3>
                <div class="metric-rows">
                    <div class="metric-row"><span class="metric-key">Status</span><span class="metric-val" style="color: ${ready.redis === 'connected' ? 'var(--success)' : 'var(--error)'}">${ready.redis}</span></div>
                    <div class="metric-row"><span class="metric-key">Memory</span><span class="metric-val">${data.redis?.memory || 'N/A'}</span></div>
                    <div class="metric-row"><span class="metric-key">Keys</span><span class="metric-val">${formatNumber(data.redis?.keys || 0)}</span></div>
                </div>
            </div>
            <div class="metric-card">
                <h3>Response Times (Last ${chartData.length} samples)</h3>
                <div class="metric-rows">
                    <div class="metric-row"><span class="metric-key">Average</span><span class="metric-val">${chartData.length > 0 ? Math.round(chartData.reduce((s, d) => s + d.value, 0) / chartData.length) : '—'}ms</span></div>
                    <div class="metric-row"><span class="metric-key">Min</span><span class="metric-val">${chartData.length > 0 ? Math.min(...chartData.map(d => d.value)) : '—'}ms</span></div>
                    <div class="metric-row"><span class="metric-key">Max</span><span class="metric-val">${chartData.length > 0 ? Math.max(...chartData.map(d => d.value)) : '—'}ms</span></div>
                    <div class="metric-row"><span class="metric-key">Samples</span><span class="metric-val">${chartData.length}</span></div>
                </div>
            </div>
        `;
    } catch (err) {
        grid.innerHTML = `<div class="empty-state">Error loading metrics: ${escapeHtml(err.message)}</div>`;
    }
}

function startMetricsPolling() {
    // Collect chart data every 3 seconds
    collectChartPoint();
    metricsInterval = setInterval(() => {
        collectChartPoint();
        if (currentTab === 'dashboard') {
            loadDashboard();
            checkApiStatus();
        }
    }, 3000);
}

// ═══════════════════════════════════════
// Utilities
// ═══════════════════════════════════════
function closeModal(id) {
    document.getElementById(id).classList.add('hidden');
}

function showFormError(id, message) {
    const el = document.getElementById(id);
    el.textContent = message;
    el.classList.remove('hidden');
    setTimeout(() => el.classList.add('hidden'), 5000);
}

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(20px)';
        toast.style.transition = 'all 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

function formatNumber(n) {
    if (typeof n !== 'number') return n;
    if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
    if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
    return n.toLocaleString();
}

function formatUptime(seconds) {
    if (seconds < 60) return `${Math.round(seconds)}s`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    return `${h}h ${m}m`;
}

function formatDate(dateStr) {
    if (!dateStr) return '—';
    const d = new Date(dateStr);
    return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function formatTime(date) {
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// Close modals on overlay click
document.addEventListener('click', (e) => {
    if (e.target.classList.contains('modal-overlay')) {
        e.target.classList.add('hidden');
    }
});

// Close modals on Escape
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        document.querySelectorAll('.modal-overlay').forEach(m => m.classList.add('hidden'));
    }
});
