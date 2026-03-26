/**
 * シグナル監視 JavaScript
 */

let signalData = null;
let currentTab = 'all';
let sortKey = 'vol_base_ratio';
let sortAsc = true;

document.addEventListener('DOMContentLoaded', () => {
    loadSignals();
});

async function loadSignals() {
    const loading = document.getElementById('loading');
    const errorBox = document.getElementById('errorBox');
    const tabSection = document.getElementById('tabSection');
    loading.style.display = 'flex';
    errorBox.style.display = 'none';
    tabSection.style.display = 'none';

    try {
        const res = await fetch('/api/signals/list');
        const data = await res.json();
        if (!data.success) {
            showError(data.error || 'データ取得に失敗しました');
            return;
        }
        signalData = data;
        renderSummary(data);
        renderDisappeared(data.disappeared || []);
        renderTable();
        loading.style.display = 'none';
        tabSection.style.display = 'block';
    } catch (e) {
        showError('通信エラー: ' + e.message);
    }
}

async function refreshSignals() {
    const btn = document.getElementById('refreshBtn');
    btn.disabled = true;
    btn.textContent = '更新中...';
    try {
        const res = await fetch('/api/signals/refresh', { method: 'POST' });
        const data = await res.json();
        if (!data.success) {
            showToast('更新失敗: ' + (data.error || ''), true);
        } else {
            signalData = data;
            renderSummary(data);
            renderDisappeared(data.disappeared || []);
            renderTable();
            showToast('シグナルを更新しました');
        }
    } catch (e) {
        showToast('通信エラー', true);
    }
    btn.disabled = false;
    btn.innerHTML = '<span class="refresh-icon">↻</span> 更新';
}

function renderSummary(data) {
    const s = data.summary || {};
    document.getElementById('signalDate').textContent = data.latest_date || '';
    document.getElementById('totalCount').textContent = s.total ?? '-';
    document.getElementById('newCount').textContent = s.new_5d ?? '-';
    document.getElementById('ultraEarlyCount').textContent = s.ultra_early ?? '-';
    document.getElementById('accelCount').textContent = s.accel ?? '-';
    document.getElementById('disappearedCount').textContent = s.disappeared ?? '-';
    document.getElementById('avgVB').textContent = s.avg_vb_ratio ?? '-';
    document.getElementById('tabAllCount').textContent = s.total ? `(${s.total})` : '';
    document.getElementById('tabUltraEarlyCount').textContent = s.ultra_early ? `(${s.ultra_early})` : '';
    document.getElementById('tabAccelCount').textContent = s.accel ? `(${s.accel})` : '';
    document.getElementById('tabNewCount').textContent = s.new_5d ? `(${s.new_5d})` : '';
    document.getElementById('tabRecentCount').textContent = s.recent_10d ? `(${s.recent_10d})` : '';
    document.getElementById('tabContCount').textContent = s.continuing ? `(${s.continuing})` : '';
}

function renderDisappeared(disappeared) {
    const alert = document.getElementById('disappearedAlert');
    const body = document.getElementById('disappearedBody');
    if (!disappeared || disappeared.length === 0) {
        alert.style.display = 'none';
        return;
    }
    alert.style.display = 'block';
    let html = '<div class="disappeared-grid">';
    for (const d of disappeared) {
        const chg = d.price_change_pct != null
            ? `<span class="${d.price_change_pct >= 0 ? 'chg-pos' : 'chg-neg'}">${d.price_change_pct >= 0 ? '+' : ''}${d.price_change_pct}%</span>`
            : '';
        const code4 = (d.code || '').substring(0, 4);
        html += `<div class="disappeared-card">
            <div class="dc-top">
                <a href="https://kabutan.jp/stock/?code=${esc(code4)}" target="_blank" class="dc-code">${esc(code4)}</a>
                <span class="dc-name">${esc(d.name || '')}</span>
            </div>
            <div class="dc-bottom">
                <span class="dc-date">最終: ${esc(d.last_signal_date || '')}</span>
                <span class="dc-price">¥${fmtNum(d.signal_price)}</span>
                ${d.current_price != null ? `<span>→ ¥${fmtNum(d.current_price)}</span>` : ''}
                ${chg}
            </div>
            ${d.chart_dates && d.chart_dates.length > 5 ? '<div class="dc-chart">' + buildSignalChart(d.chart_dates, d.chart_prices, d.chart_volumes, d.signal_indices || []) + '</div>' : ''}
        </div>`;
    }
    html += '</div>';
    body.innerHTML = html;
}

function toggleDisappeared() {
    const body = document.getElementById('disappearedBody');
    const btn = document.querySelector('.alert-toggle');
    if (body.style.display === 'none') {
        body.style.display = 'block';
        btn.textContent = '▼';
    } else {
        body.style.display = 'none';
        btn.textContent = '▶';
    }
}

function switchTab(tab) {
    currentTab = tab;
    document.querySelectorAll('.tab-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.tab === tab);
    });
    renderTable();
}

function getVisibleStocks() {
    if (!signalData) return [];
    switch (currentTab) {
        case 'ultra_early': return signalData.ultra_early || [];
        case 'accel': return signalData.accel || [];
        case 'new_5d': return signalData.new_5d || [];
        case 'recent_10d': return signalData.recent_10d || [];
        case 'continuing': return signalData.continuing || [];
        default: return signalData.all_signals || [];
    }
}

function applyFilters(stocks) {
    const hideDone = document.getElementById('filterHideDone')?.checked;
    const maxDays = parseInt(document.getElementById('filterMaxDays')?.value || '999', 10);

    const phaseChecks = document.querySelectorAll('.phase-check input');
    const allowedPhases = new Set();
    phaseChecks.forEach(cb => { if (cb.checked) allowedPhases.add(cb.value); });

    return stocks.filter(s => {
        if (hideDone && s.is_done) return false;
        if (s.price_vs_start != null && s.price_vs_start > 20) return false;
        if (!allowedPhases.has(s.phase || '初動')) return false;
        if ((s.signal_days || 0) > maxDays) return false;
        return true;
    });
}

function renderTable() {
    let stocks = getVisibleStocks();
    stocks = applyFilters(stocks);
    stocks = sortStocks(stocks, sortKey, sortAsc);

    const tbody = document.getElementById('signalBody');
    if (!stocks.length) {
        tbody.innerHTML = '<tr><td colspan="19" class="empty-msg">該当銘柄なし</td></tr>';
        return;
    }

    let html = '';
    for (const s of stocks) {
        const code4 = (s.code || '').substring(0, 4);

        const trendCls = s.trend === '強↑↑' ? 'trend-strong'
            : s.trend === '上昇↑' ? 'trend-up'
            : s.trend === '緩↑' ? 'trend-mild'
            : 'trend-flat';

        const opG = s.op_growth != null ? `${s.op_growth >= 0 ? '+' : ''}${s.op_growth}%` : '-';
        const epsG = s.eps_growth != null ? `${s.eps_growth >= 0 ? '+' : ''}${s.eps_growth}%` : '-';
        const devCls = s.ma25_dev >= 0 ? 'chg-pos' : 'chg-neg';

        const dsd = s.days_since_detected ?? 0;
        const isNew = dsd <= 3;
        const typeBadge = s.is_accel ? '<span class="badge-accel">加速</span>'
            : s.is_ultra_early ? '<span class="badge-ultra-early">超初動</span>'
            : isNew ? '<span class="badge-new">NEW</span>' : '';

        const phaseCls = s.phase === '過熱' ? 'phase-hot'
            : s.phase === '加速中' ? 'phase-accel' : 'phase-early';
        const phaseBadge = `<span class="badge-phase ${phaseCls}">${esc(s.phase || '初動')}</span>`;
        const doneBadge = s.is_done ? ' <span class="badge-done">済</span>' : '';

        const riseStr = s.price_vs_start != null
            ? `<span class="${s.price_vs_start > 20 ? 'chg-neg' : s.price_vs_start > 0 ? 'chg-pos' : ''}">${s.price_vs_start >= 0 ? '+' : ''}${s.price_vs_start}%</span>`
            : '-';

        const dsdStr = `${dsd}日${isNew ? ' <span class="badge-new">NEW</span>' : ''}`;

        const chart = (s.chart_dates && s.chart_dates.length > 5)
            ? buildSignalChart(s.chart_dates, s.chart_prices, s.chart_volumes, s.signal_indices || [])
            : '<span class="no-chart">-</span>';

        const rowCls = s.is_done ? 'row-done' : '';

        const mlScore = s.ml_score != null ? s.ml_score : '-';
        const mlCls = s.ml_score >= 70 ? 'ml-high' : s.ml_score >= 40 ? 'ml-mid' : s.ml_score != null ? 'ml-low' : '';

        html += `<tr class="${rowCls}">
            <td>${phaseBadge}${doneBadge}</td>
            <td class="num">${dsdStr}</td>
            <td><a href="https://kabutan.jp/stock/?code=${esc(code4)}" target="_blank" class="stock-link">${esc(code4)}</a> ${typeBadge}</td>
            <td class="name-cell" title="${esc(s.name || '')}">${esc(s.name || '')}</td>
            <td class="sector-cell">${esc(s.sector || '')}</td>
            <td class="num">¥${fmtNum(s.close)}</td>
            <td class="num">${riseStr}</td>
            <td class="num ${mlCls}">${mlScore}</td>
            <td class="num vb-cell">${s.vol_base_ratio}x</td>
            <td class="num">${s.signal_days ?? s.vol_above_count}日</td>
            <td class="num">${s.turnover_avg}億</td>
            <td class="num">${s.rsi}</td>
            <td class="num ${devCls}">${s.ma25_dev >= 0 ? '+' : ''}${s.ma25_dev}%</td>
            <td class="num">${opG}</td>
            <td class="num">${epsG}</td>
            <td class="${trendCls}">${esc(s.trend || '')}</td>
            <td class="dates-cell">${esc(s.detection_dates || '')}</td>
            <td class="chart-cell">${chart}</td>
        </tr>`;
    }
    tbody.innerHTML = html;

    updateSortHeaders();
}

// NEW badge is now based on days_since_detected <= 3 (computed in renderTable)

function sortStocks(stocks, key, asc) {
    return [...stocks].sort((a, b) => {
        let va = a[key], vb = b[key];
        if (va == null) va = asc ? Infinity : -Infinity;
        if (vb == null) vb = asc ? Infinity : -Infinity;
        if (typeof va === 'string') return asc ? va.localeCompare(vb) : vb.localeCompare(va);
        return asc ? va - vb : vb - va;
    });
}

document.addEventListener('click', (e) => {
    const th = e.target.closest('.sortable');
    if (!th) return;
    const key = th.dataset.sort;
    if (sortKey === key) {
        sortAsc = !sortAsc;
    } else {
        sortKey = key;
        sortAsc = false;
    }
    renderTable();
});

function updateSortHeaders() {
    document.querySelectorAll('.sortable').forEach(th => {
        th.classList.remove('sort-asc', 'sort-desc');
        if (th.dataset.sort === sortKey) {
            th.classList.add(sortAsc ? 'sort-asc' : 'sort-desc');
        }
    });
}

// ---------------------------------------------------------------------------
// Chart rendering (adapted from screening.js buildChartSVG)
// ---------------------------------------------------------------------------

function buildSignalChart(dates, prices, volumes, signalIndices) {
    if (!prices || prices.length < 5) return '<div class="no-chart">-</div>';

    const W = 280, PH = 90, VH = 28, GAP = 3, ML = 12;
    const H = PH + GAP + VH + GAP + ML;
    const PL = 3, PR = 42;
    const cW = W - PL - PR;
    const n = prices.length;

    const maxP = Math.max(...prices);
    const minP = Math.min(...prices);
    const rangeP = maxP - minP || maxP * 0.05 || 1;
    const maxV = Math.max(...volumes) || 1;

    const xOf = i => PL + (i / Math.max(n - 1, 1)) * cW;
    const yOfP = p => 2 + (PH - 4) * (1 - (p - minP) / rangeP);

    const ma25 = calcMA(prices, 25);
    const ma75 = calcMA(prices, 75);

    const pts = prices.map((p, i) => `${xOf(i).toFixed(1)},${yOfP(p).toFixed(1)}`).join(' ');
    const fillPts = `${PL},${PH - 2} ` + pts + ` ${(PL + cW).toFixed(1)},${PH - 2}`;

    const rising = prices[n - 1] >= prices[0];
    const lineColor = rising ? '#2563eb' : '#dc2626';
    const fillColor = rising ? '#dbeafe' : '#fee2e2';

    const vBaseY = PH + GAP + VH;
    const bw = Math.max((cW / n) * 0.82, 0.8);
    const sigSet = new Set(signalIndices || []);
    const bars = volumes.map((v, i) => {
        const bh = Math.max((v / maxV) * (VH - 1), 0.5);
        const bx = xOf(i) - bw / 2;
        const by = vBaseY - bh;
        const fill = sigSet.has(i) ? '#f59e0b' : (i === n - 1 ? '#3b82f6' : '#d1d9e6');
        return `<rect x="${bx.toFixed(1)}" y="${by.toFixed(1)}" width="${bw.toFixed(1)}" height="${bh.toFixed(1)}" fill="${fill}"/>`;
    }).join('');

    const grid = [0.25, 0.5, 0.75].map(f => {
        const y = yOfP(minP + rangeP * f).toFixed(1);
        return `<line x1="${PL}" y1="${y}" x2="${(PL + cW).toFixed(1)}" y2="${y}" stroke="#f0f4f8" stroke-width="0.6"/>`;
    }).join('');

    const ma25svg = buildMALine(ma25, xOf, yOfP, '#f97316', 0.8);
    const ma75svg = buildMALine(ma75, xOf, yOfP, '#60a5fa', 0.8);

    // Signal date markers (vertical dashed lines on price chart)
    let sigLines = '';
    if (signalIndices && signalIndices.length > 0) {
        const step = Math.max(1, Math.floor(signalIndices.length / 15));
        for (let k = 0; k < signalIndices.length; k += step) {
            const idx = signalIndices[k];
            const sx = xOf(idx).toFixed(1);
            sigLines += `<line x1="${sx}" y1="0" x2="${sx}" y2="${PH}" stroke="#f59e0b" stroke-width="0.6" opacity="0.35"/>`;
        }
    }

    const labelX = (PL + cW + 3).toFixed(1);
    const yMaxL = Math.max(yOfP(maxP), 7).toFixed(1);
    const yMinL = Math.min(yOfP(minP), PH - 3).toFixed(1);

    const lx = xOf(n - 1).toFixed(1);
    const ly = yOfP(prices[n - 1]).toFixed(1);

    const monthLabels = buildMonthLabelsLocal(dates, n, xOf, vBaseY + GAP + 9);

    return `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" style="display:block;width:100%;height:auto">
        ${grid}
        ${sigLines}
        <polygon points="${fillPts}" fill="${fillColor}" opacity="0.18"/>
        ${bars}
        ${ma75svg}
        ${ma25svg}
        <polyline points="${pts}" fill="none" stroke="${lineColor}" stroke-width="1.3" stroke-linejoin="round" stroke-linecap="round"/>
        <circle cx="${lx}" cy="${ly}" r="2" fill="${lineColor}"/>
        <text x="${labelX}" y="${yMaxL}" font-size="7" fill="#64748b" dominant-baseline="middle">${fmtPrice(maxP)}</text>
        <text x="${labelX}" y="${yMinL}" font-size="7" fill="#64748b" dominant-baseline="middle">${fmtPrice(minP)}</text>
        <rect x="${PL}" y="${PH + GAP - 0.5}" width="${cW}" height="0.4" fill="#e2e8f0"/>
        ${monthLabels}
    </svg>`;
}

function calcMA(prices, period) {
    return prices.map((_, i) => {
        if (i < period - 1) return null;
        let sum = 0;
        for (let j = i - period + 1; j <= i; j++) sum += prices[j];
        return sum / period;
    });
}

function buildMALine(ma, xOf, yOfP, color, opacity) {
    const segs = [];
    let pts = [];
    ma.forEach((m, i) => {
        if (m != null) {
            pts.push(`${xOf(i).toFixed(1)},${yOfP(m).toFixed(1)}`);
        } else {
            if (pts.length > 1) segs.push(pts.join(' '));
            pts = [];
        }
    });
    if (pts.length > 1) segs.push(pts.join(' '));
    return segs.map(p =>
        `<polyline points="${p}" fill="none" stroke="${color}" stroke-width="0.9" opacity="${opacity}" stroke-linejoin="round"/>`
    ).join('');
}

function fmtPrice(p) {
    if (p >= 100000) return (p / 10000).toFixed(0) + '万';
    if (p >= 10000) return (p / 1000).toFixed(1) + 'k';
    return Number(p).toFixed(0);
}

function buildMonthLabelsLocal(dates, n, xOf, labelY) {
    if (!dates || dates.length !== n) return '';
    let labels = '', lastYM = '';
    dates.forEach((d, i) => {
        if (!d) return;
        const ym = d.substring(0, 7);
        if (ym !== lastYM) {
            const x = xOf(i).toFixed(1);
            const mm = parseInt(d.substring(5, 7), 10);
            const yy = d.substring(2, 4);
            const label = mm === 1 ? `'${yy}年` : `${mm}月`;
            labels += `<text x="${x}" y="${labelY}" font-size="7" fill="#94a3b8" text-anchor="middle">${label}</text>`;
            lastYM = ym;
        }
    });
    return labels;
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

function esc(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
}

function fmtNum(n) {
    if (n == null) return '-';
    return Number(n).toLocaleString('ja-JP');
}

function showError(msg) {
    document.getElementById('loading').style.display = 'none';
    document.getElementById('errorBox').style.display = 'block';
    document.getElementById('errorMsg').textContent = msg;
}

function showToast(msg, isError) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.className = 'toast show' + (isError ? ' toast-error' : '');
    setTimeout(() => { t.className = 'toast'; }, 3000);
}
