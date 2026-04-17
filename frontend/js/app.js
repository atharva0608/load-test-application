/**
 * StressForge v3.0 — Command Center Dashboard
 * SSE-driven real-time monitoring with Chart.js
 */
const StressForge = (() => {
    // ── Configuration ──
    const API = '';  // Same origin
    const MAX_POINTS = 300;  // 5 min @ 1s intervals
    const CHART_COLORS = {
        cyan: '#00d4ff', green: '#00ff9d', orange: '#ff6b35',
        red: '#ff3b3b', yellow: '#ffd93d', purple: '#a855f7',
        cyanAlpha: 'rgba(0,212,255,0.1)', greenAlpha: 'rgba(0,255,157,0.1)',
        orangeAlpha: 'rgba(255,107,53,0.1)', redAlpha: 'rgba(255,59,59,0.1)',
    };

    // ── State ──
    let sseSource = null;
    let paused = false;
    let activeTab = 'overview';
    let charts = {};
    let sparkData = { rps: [], throughput: [], p99: [], errors: [], users: [], replicas: [] };
    let prevValues = { rps: 0, throughput: 0, p99: 0, errors: 0, users: 0, replicas: 1 };
    let timeLabels = [];
    let chartData = {
        rps: [], p50: [], p95: [], p99: [], p999: [],
        errorRate: [], cpu: [], ram: [], poolUsed: [],
        queueDepth: [], replicas: [], throughputIn: [], throughputOut: [],
        costPerHour: [],
    };

    // ══════════════════════════════════════════════════
    // INITIALIZATION
    // ══════════════════════════════════════════════════

    function init() {
        setupNavigation();
        setupControls();
        connectSSE();
        initCharts();
        loadStaticData();
    }

    function setupNavigation() {
        document.querySelectorAll('.nav-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const tab = btn.dataset.tab;
                switchTab(tab);
            });
        });
    }

    function switchTab(tab) {
        activeTab = tab;
        document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
        const btn = document.querySelector(`[data-tab="${tab}"]`);
        const panel = document.getElementById(`tab-${tab}`);
        if (btn) btn.classList.add('active');
        if (panel) panel.classList.add('active');

        // Resize charts for the active tab
        setTimeout(() => {
            Object.values(charts).forEach(c => { try { c.resize(); } catch(e) {} });
        }, 100);
    }

    function setupControls() {
        document.getElementById('btn-pause')?.addEventListener('click', function() {
            paused = !paused;
            this.textContent = paused ? '▶' : '⏸';
            this.classList.toggle('active', paused);
        });
        document.getElementById('btn-export')?.addEventListener('click', exportData);
        document.getElementById('scenario-select')?.addEventListener('change', updateScenarioParams);
    }

    // ══════════════════════════════════════════════════
    // SSE CONNECTION
    // ══════════════════════════════════════════════════

    function connectSSE() {
        if (sseSource) { sseSource.close(); }

        sseSource = new EventSource(`${API}/api/stream`);

        sseSource.onopen = () => {
            const dot = document.querySelector('.conn-dot');
            const status = document.getElementById('sse-status');
            if (dot) dot.classList.add('connected');
            if (status) status.textContent = 'Connected';
            addEvent('info', 'SSE stream connected');
        };

        sseSource.onmessage = (e) => {
            if (paused) return;
            try {
                const data = JSON.parse(e.data);
                processSSEData(data);
            } catch (err) {
                console.error('SSE parse error:', err);
            }
        };

        sseSource.onerror = () => {
            const dot = document.querySelector('.conn-dot');
            const status = document.getElementById('sse-status');
            if (dot) dot.classList.remove('connected');
            if (status) status.textContent = 'Reconnecting…';
        };
    }

    function processSSEData(data) {
        const now = new Date().toLocaleTimeString('en-US', { hour12: false });

        // Push to time series
        timeLabels.push(now);
        if (timeLabels.length > MAX_POINTS) timeLabels.shift();

        // Push data points
        pushPoint('rps', data.rps);
        pushPoint('p50', data.p50);
        pushPoint('p95', data.p95);
        pushPoint('p99', data.p99);
        pushPoint('p999', data.p999);
        pushPoint('errorRate', data.error_rate);
        pushPoint('cpu', data.cpu_percent);
        pushPoint('ram', data.ram_percent);
        pushPoint('poolUsed', data.pool_used);
        pushPoint('queueDepth', data.queue_depth);
        pushPoint('replicas', data.replicas);
        pushPoint('throughputIn', data.throughput_in);
        pushPoint('throughputOut', data.throughput_out);
        pushPoint('costPerHour', data.cost_per_hour);

        // Update KPI tiles
        updateKPI('rps', data.rps, v => v.toFixed(0), v => v > 100 ? 'good' : v > 50 ? 'warn' : '');
        updateKPI('throughput', (data.throughput_out || 0), v => formatBytes(v) + '/s', () => '');
        updateKPI('p99', data.p99, v => v.toFixed(0) + ' ms', v => v < 200 ? 'good' : v < 1000 ? 'warn' : 'bad');
        updateKPI('errors', data.error_rate, v => v.toFixed(2) + '%', v => v < 0.1 ? 'good' : v < 1 ? 'warn' : 'bad');
        updateKPI('users', data.total_requests || 0, v => v.toFixed(0), () => '');
        updateKPI('replicas', data.replicas, v => v.toFixed(0), () => '');

        // Update charts based on active tab
        updateActiveCharts(data);

        // Process events
        if (data.events && data.events.length > 0) {
            data.events.forEach(evt => addEvent(evt.severity, evt.message));
        }
    }

    function pushPoint(key, value) {
        chartData[key].push(value || 0);
        if (chartData[key].length > MAX_POINTS) chartData[key].shift();
    }

    // ══════════════════════════════════════════════════
    // KPI TILES
    // ══════════════════════════════════════════════════

    function updateKPI(id, value, formatter, stateClass) {
        const valEl = document.getElementById(`kpi-${id}-val`);
        const deltaEl = document.getElementById(`kpi-${id}-delta`);
        const tile = document.getElementById(`kpi-${id}`);

        if (valEl) {
            const formatted = formatter(value || 0);
            animateValue(valEl, formatted);
        }

        // Delta
        if (deltaEl && prevValues[id] !== undefined) {
            const prev = prevValues[id];
            const diff = (value || 0) - prev;
            if (prev > 0 && Math.abs(diff) > 0.01) {
                const pct = ((diff / prev) * 100).toFixed(1);
                deltaEl.textContent = diff > 0 ? `↑ ${pct}%` : `↓ ${Math.abs(pct)}%`;
                deltaEl.className = `kpi-delta ${diff > 0 ? 'up' : 'down'}`;
            } else {
                deltaEl.textContent = '—';
                deltaEl.className = 'kpi-delta';
            }
        }
        prevValues[id] = value || 0;

        // State class
        if (tile) {
            tile.className = `kpi-tile ${stateClass(value || 0)}`;
        }

        // Sparkline
        pushSpark(id, value || 0);
    }

    function animateValue(el, newText) {
        if (el.textContent !== newText) {
            el.textContent = newText;
        }
    }

    function pushSpark(id, value) {
        const arr = sparkData[id];
        if (!arr) return;
        arr.push(value);
        if (arr.length > 60) arr.shift();
        drawSparkline(`spark-${id}`, arr, id === 'errors' || id === 'p99' ? CHART_COLORS.red : CHART_COLORS.cyan);
    }

    function drawSparkline(canvasId, data, color) {
        const canvas = document.getElementById(canvasId);
        if (!canvas || data.length < 2) return;
        const ctx = canvas.getContext('2d');
        const w = canvas.width;
        const h = canvas.height;
        ctx.clearRect(0, 0, w, h);

        const max = Math.max(...data, 1);
        const step = w / (data.length - 1);

        ctx.strokeStyle = color;
        ctx.lineWidth = 1;
        ctx.beginPath();
        data.forEach((v, i) => {
            const x = i * step;
            const y = h - (v / max) * (h - 2);
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });
        ctx.stroke();
    }

    // ══════════════════════════════════════════════════
    // CHART.JS INITIALIZATION
    // ══════════════════════════════════════════════════

    const chartDefaults = {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: { legend: { display: true, labels: { color: '#6b7f8e', font: { family: "'JetBrains Mono'", size: 10 }, boxWidth: 8, padding: 8 } } },
        scales: {
            x: { ticks: { color: '#3a4a56', font: { family: "'JetBrains Mono'", size: 9 }, maxTicksLimit: 8 }, grid: { color: 'rgba(255,255,255,0.03)' } },
            y: { beginAtZero: true, suggestedMin: 0, suggestedMax: 10, ticks: { color: '#3a4a56', font: { family: "'JetBrains Mono'", size: 9 } }, grid: { color: 'rgba(255,255,255,0.03)' } },
        },
    };

    function makeLineDS(label, color, fill = false) {
        return { label, data: [], borderColor: color, backgroundColor: fill ? color.replace(')', ',0.1)').replace('rgb', 'rgba') : 'transparent', borderWidth: 1.5, pointRadius: 0, tension: 0.3, fill };
    }

    function initCharts() {
        // Overview tab
        charts.loadRps = createChart('chart-load-rps', 'line', [
            { ...makeLineDS('RPS', CHART_COLORS.cyan), yAxisID: 'y' },
        ], { ...chartDefaults });

        charts.latencyPercentiles = createChart('chart-latency-percentiles', 'line', [
            makeLineDS('p50', CHART_COLORS.green),
            makeLineDS('p95', CHART_COLORS.yellow),
            makeLineDS('p99', CHART_COLORS.orange),
            makeLineDS('p99.9', CHART_COLORS.red),
        ], chartDefaults);

        charts.errors = createChart('chart-errors', 'line', [
            makeLineDS('Error %', CHART_COLORS.red, true),
        ], chartDefaults);

        charts.throughput = createChart('chart-throughput', 'line', [
            makeLineDS('Out', CHART_COLORS.cyan, true),
            makeLineDS('In', CHART_COLORS.purple, true),
        ], chartDefaults);

        // Infrastructure tab
        charts.cpuPod = createChart('chart-cpu-pod', 'line', [
            makeLineDS('Pod 1', CHART_COLORS.cyan),
        ], chartDefaults);

        charts.memPod = createChart('chart-mem-pod', 'line', [
            makeLineDS('Pod 1', CHART_COLORS.purple),
        ], chartDefaults);

        charts.hpa = createChart('chart-hpa', 'line', [
            { ...makeLineDS('Replicas', CHART_COLORS.green), stepped: true },
        ], chartDefaults);

        charts.pool = createChart('chart-pool', 'bar', [
            { label: 'Used', data: [], backgroundColor: CHART_COLORS.orange },
            { label: 'Available', data: [], backgroundColor: 'rgba(0,255,157,0.2)' },
        ], { ...chartDefaults, scales: { ...chartDefaults.scales, x: { ...chartDefaults.scales.x, stacked: true }, y: { ...chartDefaults.scales.y, stacked: true } } });

        // Queue tab
        charts.queueDepth = createChart('chart-queue-depth', 'line', [
            makeLineDS('Total', CHART_COLORS.cyan, true),
        ], chartDefaults);

        charts.workerThroughput = createChart('chart-worker-throughput', 'bar', [
            { label: 'Tasks/10s', data: [], backgroundColor: CHART_COLORS.cyan },
        ], chartDefaults);

        charts.taskDuration = createChart('chart-task-duration', 'bar', [
            { label: 'heavy_computation', data: [0], backgroundColor: CHART_COLORS.red },
            { label: 'process_order', data: [0], backgroundColor: CHART_COLORS.orange },
            { label: 'generate_report', data: [0], backgroundColor: CHART_COLORS.cyan },
        ], { ...chartDefaults, indexAxis: 'y' });

        charts.dlq = createChart('chart-dlq', 'line', [
            makeLineDS('DLQ Size', CHART_COLORS.red, true),
        ], chartDefaults);

        // Latency tab
        charts.latencyHist = createChart('chart-latency-hist', 'bar', [
            { label: 'Requests', data: [0,0,0,0,0,0,0], backgroundColor: CHART_COLORS.cyan },
        ], { ...chartDefaults, scales: { ...chartDefaults.scales, x: { ...chartDefaults.scales.x, type: 'category' } } });

        // Chaos tab
        charts.chaosRecovery = createChart('chart-chaos-recovery', 'line', [
            makeLineDS('Error Rate', CHART_COLORS.red, true),
        ], chartDefaults);

        // Cost tab
        charts.costDonut = createChart('chart-cost-donut', 'doughnut', [
            { data: [40, 25, 15, 10, 10], backgroundColor: [CHART_COLORS.cyan, CHART_COLORS.orange, CHART_COLORS.green, CHART_COLORS.purple, CHART_COLORS.yellow] },
        ], {
            responsive: true, maintainAspectRatio: false, animation: false,
            plugins: { legend: { position: 'right', labels: { color: '#6b7f8e', font: { family: "'JetBrains Mono'", size: 10 }, padding: 6 } } },
        });

        charts.costScatter = createChart('chart-cost-scatter', 'scatter', [
            { label: '$/hr vs Users', data: [], backgroundColor: CHART_COLORS.green, pointRadius: 3 },
        ], chartDefaults);

        // Heatmap (using basic bars as approximation)
        charts.heatmap = createChart('chart-heatmap', 'bar', [
            { label: '0-50ms', data: [], backgroundColor: 'rgba(0,255,157,0.3)' },
            { label: '50-200ms', data: [], backgroundColor: 'rgba(0,212,255,0.3)' },
            { label: '200-500ms', data: [], backgroundColor: 'rgba(255,217,61,0.3)' },
            { label: '500ms-1s', data: [], backgroundColor: 'rgba(255,107,53,0.3)' },
            { label: '1s+', data: [], backgroundColor: 'rgba(255,59,59,0.3)' },
        ], { ...chartDefaults, scales: { ...chartDefaults.scales, x: { stacked: true, ...chartDefaults.scales.x }, y: { stacked: true, ...chartDefaults.scales.y } } });

        // Scenario preview
        charts.scenarioPreview = createChart('chart-scenario-preview', 'line', [
            { ...makeLineDS('Users', CHART_COLORS.cyan, true) },
        ], { ...chartDefaults, plugins: { legend: { display: false } } });

        updateScenarioParams();
    }

    function createChart(canvasId, type, datasets, options) {
        const canvas = document.getElementById(canvasId);
        if (!canvas) return null;

        return new Chart(canvas, {
            type,
            data: { labels: type === 'doughnut' ? ['EC2', 'RDS', 'EBS', 'Transfer', 'Redis'] : [], datasets },
            options,
        });
    }

    // ══════════════════════════════════════════════════
    // CHART UPDATES
    // ══════════════════════════════════════════════════

    function updateActiveCharts(data) {
        const labels = [...timeLabels];

        // Always update overview charts (most critical)
        updateChartData(charts.loadRps, labels, [chartData.rps]);
        updateChartData(charts.latencyPercentiles, labels, [chartData.p50, chartData.p95, chartData.p99, chartData.p999]);
        updateChartData(charts.errors, labels, [chartData.errorRate]);
        updateChartData(charts.throughput, labels, [chartData.throughputOut, chartData.throughputIn]);

        if (activeTab === 'infrastructure') {
            updateChartData(charts.cpuPod, labels, [chartData.cpu]);
            updateChartData(charts.memPod, labels, [chartData.ram]);
            updateChartData(charts.hpa, labels, [chartData.replicas]);

            // Pool bar chart (latest N values)
            const poolLabels = labels.slice(-20);
            const poolUsed = chartData.poolUsed.slice(-20);
            const poolAvail = poolUsed.map(u => Math.max(0, 20 - u));
            if (charts.pool) {
                charts.pool.data.labels = poolLabels;
                charts.pool.data.datasets[0].data = poolUsed;
                charts.pool.data.datasets[1].data = poolAvail;
                charts.pool.update('none');
            }

            setText('infra-pool-used', data.pool_used);
            setText('infra-pool-waiting', data.pool_waiting);
            setText('infra-cpu-avg', data.cpu_percent?.toFixed(1) + '%');
            setText('infra-ram-used', data.ram_used_mb + ' MB');
        }

        if (activeTab === 'queue') {
            updateChartData(charts.queueDepth, labels, [chartData.queueDepth]);
            updateChartData(charts.chaosRecovery, labels, [chartData.errorRate]);
        }

        if (activeTab === 'cost' && data.cost_per_hour !== undefined) {
            setText('cost-per-hour', `$${data.cost_per_hour.toFixed(4)} / hr`);
            setText('cost-projections', `$${(data.cost_per_hour * 730).toFixed(2)}/month | $${(data.cost_per_hour * 8760).toFixed(2)}/year`);

            // Scatter point
            if (charts.costScatter && data.total_requests > 0) {
                charts.costScatter.data.datasets[0].data.push({ x: data.total_requests, y: data.cost_per_hour });
                if (charts.costScatter.data.datasets[0].data.length > 200) {
                    charts.costScatter.data.datasets[0].data.shift();
                }
                charts.costScatter.update('none');
            }

            // Update cost ticker color
            const ticker = document.getElementById('cost-per-hour');
            if (ticker) {
                ticker.style.color = data.cost_per_hour > 1 ? '#ff3b3b' : data.cost_per_hour > 0.1 ? '#ff6b35' : '#00ff9d';
            }
        }
    }

    function updateChartData(chart, labels, dataSets) {
        if (!chart) return;
        chart.data.labels = labels;
        dataSets.forEach((ds, i) => {
            if (chart.data.datasets[i]) {
                chart.data.datasets[i].data = ds;
            }
        });
        chart.update('none');
    }

    // ══════════════════════════════════════════════════
    // EVENT LOG
    // ══════════════════════════════════════════════════

    function addEvent(severity, message) {
        const feed = document.getElementById('event-feed');
        if (!feed) return;

        const time = new Date().toLocaleTimeString('en-US', { hour12: false });
        const icons = { info: '●', warning: '⚠', error: '✗', success: '✓' };
        const icon = icons[severity] || '●';

        const entry = document.createElement('div');
        entry.className = `event-entry ${severity}`;
        entry.innerHTML = `<span class="event-time">[${time}]</span> ${icon} ${escapeHtml(message)}`;
        feed.appendChild(entry);

        // Auto-scroll (only if user hasn't scrolled up)
        if (feed.scrollTop + feed.clientHeight >= feed.scrollHeight - 30) {
            feed.scrollTop = feed.scrollHeight;
        }

        // Cap entries
        while (feed.children.length > 500) feed.removeChild(feed.firstChild);
    }

    function clearEventLog() {
        const feed = document.getElementById('event-feed');
        if (feed) feed.innerHTML = '<div class="event-entry info"><span class="event-time">—</span> Event log cleared</div>';
    }

    // ══════════════════════════════════════════════════
    // STATIC DATA LOADERS (polled, not SSE)
    // ══════════════════════════════════════════════════

    function loadStaticData() {
        // Load data that doesn't come from SSE every 5 seconds
        setInterval(() => {
            if (activeTab === 'latency') loadLatencyData();
            if (activeTab === 'uptime') loadUptimeData();
            if (activeTab === 'chaos') loadChaosData();
            if (activeTab === 'queue') loadDLQData();
            if (activeTab === 'cost') loadCostData();
        }, 5000);

        // Initial loads
        loadUptimeData();
        loadChaosData();
    }

    async function loadLatencyData() {
        try {
            const res = await fetch(`${API}/api/metrics/latency-percentiles`);
            if (!res.ok) return;
            const data = await res.json();

            const tbody = document.getElementById('endpoint-latency-body');
            if (tbody && data.length > 0) {
                tbody.innerHTML = data.map(ep => `
                    <tr>
                        <td>${escapeHtml(ep.endpoint)}</td>
                        <td class="${ep.p50 < 100 ? 'val-good' : 'val-warn'}">${ep.p50.toFixed(1)}</td>
                        <td class="${ep.p95 < 500 ? 'val-good' : 'val-warn'}">${ep.p95.toFixed(1)}</td>
                        <td class="${ep.p99 < 1000 ? 'val-good' : ep.p99 < 2000 ? 'val-warn' : 'val-bad'}">${ep.p99.toFixed(1)}</td>
                        <td>${(ep.count / 300).toFixed(1)}</td>
                        <td>${ep.count}</td>
                    </tr>
                `).join('');
            }

            // Histogram buckets
            if (charts.latencyHist && data.length > 0) {
                const buckets = [0, 0, 0, 0, 0, 0, 0];
                data.forEach(ep => {
                    if (ep.p50 < 50) buckets[0] += ep.count;
                    else if (ep.p50 < 100) buckets[1] += ep.count;
                    else if (ep.p50 < 250) buckets[2] += ep.count;
                    else if (ep.p50 < 500) buckets[3] += ep.count;
                    else if (ep.p50 < 1000) buckets[4] += ep.count;
                    else if (ep.p50 < 2000) buckets[5] += ep.count;
                    else buckets[6] += ep.count;
                });
                charts.latencyHist.data.labels = ['0-50', '50-100', '100-250', '250-500', '500-1k', '1k-2k', '2k+'];
                charts.latencyHist.data.datasets[0].data = buckets;
                charts.latencyHist.update('none');
            }

            // Slow requests
            const slowRes = await fetch(`${API}/api/metrics/slow-requests?limit=20`);
            if (slowRes.ok) {
                const slow = await slowRes.json();
                const feed = document.getElementById('slow-request-feed');
                if (feed && slow.length > 0) {
                    feed.innerHTML = slow.reverse().map(r => `
                        <div class="slow-entry">
                            <span class="slow-time">${new Date(r.timestamp * 1000).toLocaleTimeString()}</span>
                            <span class="slow-endpoint">${escapeHtml(r.endpoint)}</span>
                            <span class="slow-duration">${r.duration_ms.toFixed(0)}ms</span>
                            <span class="slow-method">${r.method}</span>
                        </div>
                    `).join('');
                }
            }
        } catch (e) { /* silent */ }
    }

    async function loadUptimeData() {
        try {
            const res = await fetch(`${API}/api/uptime/summary`);
            if (!res.ok) return;
            const data = await res.json();

            // Status banner
            const banner = document.getElementById('uptime-banner');
            const statusText = document.getElementById('uptime-status-text');
            const since = document.getElementById('uptime-since');

            const status = data.status || 'operational';
            if (banner) banner.className = `uptime-status-banner ${status === 'operational' ? 'ok' : status === 'degraded' ? 'degraded' : 'down'}`;
            if (statusText) statusText.textContent = status.toUpperCase();

            // SLA tiles
            const sla = data.sla || {};
            setSLA('sla-1h', sla['1h_percent']);
            setSLA('sla-24h', sla['24h_percent']);
            setSLA('sla-7d', sla['7d_percent']);
            setSLA('sla-30d', sla['30d_percent']);

            // Timeline bar
            const timeline = document.getElementById('timeline-bar');
            if (timeline) {
                timeline.innerHTML = '';
                for (let i = 0; i < 90; i++) {
                    const day = document.createElement('div');
                    const rand = Math.random();
                    day.className = `timeline-day ${rand > 0.05 ? 'good' : rand > 0.02 ? 'warn' : 'bad'}`;
                    day.title = `Day -${90 - i}`;
                    timeline.appendChild(day);
                }
            }
        } catch (e) { /* silent */ }

        // Endpoints
        try {
            const res = await fetch(`${API}/api/uptime/endpoints`);
            if (!res.ok) return;
            const data = await res.json();
            const endpoints = data.endpoints || [];
            const tbody = document.getElementById('endpoint-health-body');
            if (tbody) {
                tbody.innerHTML = endpoints.map(ep => `
                    <tr>
                        <td>${escapeHtml(ep.endpoint)}</td>
                        <td class="${ep.status === 'healthy' ? 'val-good' : 'val-bad'}">${ep.status}</td>
                        <td>${ep.uptime_1h?.toFixed(2) || '—'}%</td>
                        <td>${ep.avg_latency?.toFixed(1) || '—'}ms</td>
                        <td>${ep.last_check ? new Date(ep.last_check * 1000).toLocaleTimeString() : '—'}</td>
                    </tr>
                `).join('');
            }
        } catch (e) { /* silent */ }

        // Incidents
        try {
            const res = await fetch(`${API}/api/uptime/incidents`);
            if (!res.ok) return;
            const data = await res.json();
            const incidents = [...(data.active || []), ...(data.resolved || [])];
            const tbody = document.getElementById('incident-body');
            if (tbody) {
                tbody.innerHTML = incidents.slice(0, 20).map(inc => `
                    <tr>
                        <td>${inc.started_at ? new Date(inc.started_at * 1000).toLocaleString() : '—'}</td>
                        <td>${inc.duration_seconds ? inc.duration_seconds.toFixed(0) + 's' : 'ongoing'}</td>
                        <td>${escapeHtml(inc.endpoint || '—')}</td>
                        <td>${escapeHtml(inc.cause || '—')}</td>
                        <td class="${inc.resolved_at ? 'val-good' : 'val-bad'}">${inc.resolved_at ? 'Resolved' : 'Active'}</td>
                    </tr>
                `).join('');
            }
        } catch (e) { /* silent */ }
    }

    async function loadChaosData() {
        try {
            // Active chaos
            const activeRes = await fetch(`${API}/api/chaos/active`);
            if (activeRes.ok) {
                const data = await activeRes.json();
                const list = document.getElementById('chaos-active-list');
                if (list) {
                    if (data.active.length === 0) {
                        list.innerHTML = '<div class="chaos-empty">No active chaos injections</div>';
                    } else {
                        list.innerHTML = data.active.map(inj => {
                            const remaining = Math.max(0, inj.expires_at - Date.now()/1000);
                            return `<div class="chaos-active-item">
                                <span class="target">${inj.target} / ${inj.failure_type}</span>
                                <span class="timer">${remaining.toFixed(0)}s remaining</span>
                            </div>`;
                        }).join('');
                    }
                }
            }

            // Chaos log
            const logRes = await fetch(`${API}/api/chaos/log?limit=20`);
            if (logRes.ok) {
                const data = await logRes.json();
                const tbody = document.getElementById('chaos-log-body');
                if (tbody && data.log.length > 0) {
                    tbody.innerHTML = data.log.reverse().map(entry => `
                        <tr>
                            <td>${entry.failure_type}</td>
                            <td>${entry.target}</td>
                            <td>${new Date(entry.injected_at * 1000).toLocaleTimeString()}</td>
                            <td>${entry.recovery_seconds ? entry.recovery_seconds + 's' : '—'}</td>
                            <td class="${(entry.recovery_seconds || 999) <= 30 ? 'val-good' : 'val-bad'}">${(entry.recovery_seconds || 999) <= 30 ? '✓ Met' : '✗ Breach'}</td>
                        </tr>
                    `).join('');
                }
            }

            // Circuit breakers
            const cbRes = await fetch(`${API}/api/circuit-breakers`);
            if (cbRes.ok) {
                const data = await cbRes.json();
                const grid = document.getElementById('cb-grid');
                if (grid) {
                    grid.innerHTML = (data.breakers || []).map(b => `
                        <div class="cb-card">
                            <div class="cb-name">${b.name}</div>
                            <div class="cb-state ${b.state}">${b.state}</div>
                            <div style="font-size:0.6rem;color:#3a4a56;margin-top:2px">${b.fail_count}/${b.fail_max} failures</div>
                        </div>
                    `).join('');
                }
            }
        } catch (e) { /* silent */ }
    }

    async function loadDLQData() {
        try {
            const res = await fetch(`${API}/api/queue/dlq`);
            if (!res.ok) return;
            const data = await res.json();
            const tasks = data.tasks || [];
            const tbody = document.getElementById('dlq-body');
            if (tbody) {
                tbody.innerHTML = tasks.map(t => `
                    <tr>
                        <td>${escapeHtml(t.task_name || '—')}</td>
                        <td class="val-bad">${escapeHtml(t.error || '—')}</td>
                        <td>${t.retries || 0}</td>
                        <td>
                            <button class="action-btn cyan" onclick="StressForge.retryDLQ('${t.id}')" style="padding:2px 6px;font-size:0.6rem">Retry</button>
                            <button class="action-btn red" onclick="StressForge.discardDLQ('${t.id}')" style="padding:2px 6px;font-size:0.6rem">Discard</button>
                        </td>
                    </tr>
                `).join('');
            }
        } catch (e) { /* silent */ }
    }

    async function loadCostData() {
        try {
            const res = await fetch(`${API}/api/metrics/cost-estimate`);
            if (!res.ok) return;
            const data = await res.json();

            setText('cost-per-hour', `$${data.cost_per_hour_usd.toFixed(4)} / hr`);
            setText('cost-projections', `$${data.cost_per_month_usd.toFixed(2)}/month | $${data.cost_per_year_usd.toFixed(2)}/year`);

            // Update donut
            if (charts.costDonut && data.breakdown) {
                const bd = data.breakdown;
                charts.costDonut.data.datasets[0].data = [
                    bd.compute_ec2 || 0, bd.storage_iops || 0, bd.base_infrastructure || 0,
                    bd.data_transfer || 0, bd.celery_workers || 0,
                ];
                charts.costDonut.update('none');
            }

            // Suggestions
            const suggestions = document.getElementById('cost-suggestions');
            if (suggestions) {
                const items = [];
                if (data.total_events.cpu_seconds > 100) {
                    items.push(`⚡ High CPU usage (${data.total_events.cpu_seconds}s). Consider right-sizing pods to save ~$${(data.cost_per_hour_usd * 0.3 * 730).toFixed(0)}/month`);
                }
                if (data.total_events.io_operations > 1000) {
                    items.push(`💾 Heavy I/O (${data.total_events.io_operations} ops). Switch to gp3 volumes with provisioned IOPS`);
                }
                if (data.cost_per_hour_usd > 0.5) {
                    items.push(`💰 Cost is >$0.50/hr. Consider Spot instances for non-critical workloads`);
                }
                if (items.length === 0) items.push('📊 Run a load test to generate cost analysis data');
                suggestions.innerHTML = items.map(i => `<div class="suggestion-item">${i}</div>`).join('');
            }
        } catch (e) { /* silent */ }
    }

    // ══════════════════════════════════════════════════
    // ACTIONS
    // ══════════════════════════════════════════════════

    async function triggerBurst(count, priority) {
        addEvent('info', `Firing burst: ${count} tasks → ${priority}`);
        try {
            const res = await fetch(`${API}/api/queue/burst`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ count, intensity: 30, priority }),
            });
            if (res.ok) {
                const data = await res.json();
                addEvent('success', `Burst complete: ${data.tasks_queued} tasks queued in ${data.duration_ms}ms`);
            }
        } catch (e) { addEvent('error', `Burst failed: ${e.message}`); }
    }

    async function fireChain() {
        addEvent('info', 'Firing Celery chain: preprocess → compute → notify');
        try {
            const res = await fetch(`${API}/api/jobs/chain`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ intensity: 30 }),
            });
            if (res.ok) { addEvent('success', 'Chain dispatched'); }
        } catch (e) { addEvent('error', `Chain failed: ${e.message}`); }
    }

    async function fireChord(n) {
        addEvent('info', `Firing Celery chord: ${n} parallel tasks → aggregate`);
        try {
            const res = await fetch(`${API}/api/jobs/chord`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ parallel_count: n, intensity: 20 }),
            });
            if (res.ok) { addEvent('success', `Chord dispatched: ${n} tasks`); }
        } catch (e) { addEvent('error', `Chord failed: ${e.message}`); }
    }

    async function injectChaos(target, type, latencyMs, duration) {
        addEvent('warning', `Injecting chaos: ${target}/${type}`);
        try {
            const res = await fetch(`${API}/api/chaos/inject?target=${target}&failure_type=${type}&latency_ms=${latencyMs}&duration_seconds=${duration}`, { method: 'POST' });
            if (res.ok) {
                const data = await res.json();
                addEvent('error', `Chaos injected: ${target}/${type} for ${duration}s`);
                loadChaosData();
            }
        } catch (e) { addEvent('error', `Chaos injection failed: ${e.message}`); }
    }

    async function clearChaos() {
        try {
            const res = await fetch(`${API}/api/chaos/clear`, { method: 'DELETE' });
            if (res.ok) {
                addEvent('success', 'All chaos cleared');
                loadChaosData();
            }
        } catch (e) { addEvent('error', `Clear failed: ${e.message}`); }
    }

    async function retryDLQ(taskId) {
        try {
            await fetch(`${API}/api/queue/dlq/retry/${taskId}`, { method: 'POST' });
            addEvent('info', `Retrying DLQ task ${taskId}`);
            loadDLQData();
        } catch (e) { addEvent('error', `Retry failed: ${e.message}`); }
    }

    async function discardDLQ(taskId) {
        try {
            await fetch(`${API}/api/queue/dlq/${taskId}`, { method: 'DELETE' });
            addEvent('info', `Discarded DLQ task ${taskId}`);
            loadDLQData();
        } catch (e) { addEvent('error', `Discard failed: ${e.message}`); }
    }

    async function executeScenario() {
        const shape = document.getElementById('scenario-select')?.value || 'spike';
        const peak = parseInt(document.getElementById('sc-peak')?.value || '100');
        const ramp = parseInt(document.getElementById('sc-ramp')?.value || '30');
        const hold = parseInt(document.getElementById('sc-hold')?.value || '60');

        addEvent('info', `Starting ${shape} scenario: ${peak} users, ramp ${ramp}s, hold ${hold}s`);

        try {
            const res = await fetch(`${API}/api/runs`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    scenario_name: shape,
                    config_json: { shape, peak_users: peak, ramp_duration: ramp, hold_duration: hold },
                }),
            });
            if (res.ok) {
                addEvent('success', `Scenario "${shape}" started`);
                const statusEl = document.getElementById('scenario-active-info');
                if (statusEl) {
                    statusEl.innerHTML = `
                        <div style="text-align:center;padding:10px">
                            <div style="font-size:1.1rem;font-weight:700;color:var(--cyan)">${shape.toUpperCase()}</div>
                            <div style="font-size:0.72rem;color:var(--text-secondary);margin-top:4px">${peak} users | ${ramp}s ramp | ${hold}s hold</div>
                            <div style="font-size:0.65rem;color:var(--green);margin-top:6px">● Running…</div>
                        </div>
                    `;
                }
            }
        } catch (e) { addEvent('error', `Scenario failed: ${e.message}`); }
    }

    function updateScenarioParams() {
        const shape = document.getElementById('scenario-select')?.value || 'spike';
        // Generate preview curve
        if (!charts.scenarioPreview) return;

        const labels = [];
        const values = [];
        for (let t = 0; t <= 120; t += 2) {
            labels.push(t + 's');
            switch(shape) {
                case 'spike': values.push(t < 30 ? 10 : t < 40 ? 100 : t < 70 ? 100 : t < 80 ? 10 : 10); break;
                case 'soak': values.push(30); break;
                case 'burst': values.push(Math.floor(t / 30) % 2 === 0 ? 50 : 0); break;
                case 'ramp': values.push(Math.min(200, t * 1.67)); break;
                case 'flash': values.push(Math.pow(2, t / 20)); break;
                default: values.push(50);
            }
        }
        charts.scenarioPreview.data.labels = labels;
        charts.scenarioPreview.data.datasets[0].data = values;
        charts.scenarioPreview.update('none');
    }

    function exportData() {
        const blob = new Blob([JSON.stringify({ chartData, timeLabels, exported: new Date().toISOString() }, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `stressforge-export-${Date.now()}.json`;
        a.click();
        URL.revokeObjectURL(url);
        addEvent('info', 'Chart data exported');
    }

    // ══════════════════════════════════════════════════
    // UTILITIES
    // ══════════════════════════════════════════════════

    function setText(id, text) {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    }

    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str || '';
        return div.innerHTML;
    }

    function formatBytes(bytes) {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    }

    function setSLA(id, value) {
        const el = document.getElementById(id);
        if (!el) return;
        const v = value || 0;
        el.textContent = v.toFixed(2) + '%';
        el.style.color = v >= 99.9 ? '#00ff9d' : v >= 99 ? '#ffd93d' : '#ff3b3b';
    }

    // Initialize on load
    document.addEventListener('DOMContentLoaded', init);

    // Public API
    return {
        triggerBurst, fireChain, fireChord, injectChaos, clearChaos,
        retryDLQ, discardDLQ, executeScenario, clearEventLog, exportData,
    };
})();
