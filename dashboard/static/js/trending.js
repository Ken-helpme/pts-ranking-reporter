// 話題株ピックアップ JavaScript

document.addEventListener('DOMContentLoaded', function () {
    loadTrendingStocks();
    loadDateOptions();
});

// 話題株データを読み込み
async function loadTrendingStocks(date = null) {
    const loading = document.getElementById('loadingIndicator');
    const table = document.getElementById('trendingTable');
    const empty = document.getElementById('emptyState');

    loading.style.display = 'block';
    table.style.display = 'none';
    empty.style.display = 'none';

    try {
        let url = '/api/trending/latest';
        if (date) url += `?date=${date}`;

        const response = await fetch(url);
        const result = await response.json();

        loading.style.display = 'none';

        if (result.success && result.data && result.data.length > 0) {
            displayTrendingTable(result.data);
            table.style.display = 'block';

            // Update header info
            document.getElementById('fetchDate').textContent = result.data[0].fetch_date || '--';
            document.getElementById('stockCount').textContent = `${result.data.length}銘柄`;
        } else {
            empty.style.display = 'block';
        }
    } catch (error) {
        loading.style.display = 'none';
        empty.style.display = 'block';
        console.error('Error loading trending stocks:', error);
    }
}

// 日付セレクターを読み込み
async function loadDateOptions() {
    try {
        const response = await fetch('/api/trending/dates');
        const result = await response.json();
        if (result.success && result.dates) {
            const selector = document.getElementById('dateSelector');
            result.dates.forEach(date => {
                const option = document.createElement('option');
                option.value = date;
                option.textContent = formatDateJP(date);
                selector.appendChild(option);
            });
        }
    } catch (error) {
        console.error('Error loading dates:', error);
    }
}

// 日付変更時
function loadTrendingByDate() {
    const date = document.getElementById('dateSelector').value;
    loadTrendingStocks(date || null);
}

// テーブル表示
function displayTrendingTable(data) {
    const tbody = document.getElementById('trendingTableBody');
    tbody.innerHTML = '';

    data.forEach((stock, index) => {
        const row = document.createElement('tr');
        row.className = 'trending-row';

        const changeClass = (stock.change_rate || 0) >= 0 ? 'change-positive' : 'change-negative';
        const changeSign = (stock.change_rate || 0) >= 0 ? '+' : '';

        // ミニチャート用のcanvas ID
        const chartId = `chart-${stock.code}`;

        row.innerHTML = `
            <td class="col-rank">
                <div class="rank-number ${index < 3 ? 'rank-top' : ''}">${index + 1}</div>
            </td>
            <td class="col-stock">
                <div class="stock-info">
                    <a href="https://kabutan.jp/stock/?code=${stock.code}" target="_blank" class="stock-name-link">
                        ${escapeHtml(stock.name)}
                    </a>
                    <div class="stock-meta">
                        <span class="stock-code">&lt;${stock.code}&gt;</span>
                        <span class="stock-market">${escapeHtml(stock.market || '')}</span>
                    </div>
                </div>
            </td>
            <td class="col-cap">
                <div class="market-cap-value">${escapeHtml(stock.market_cap || '--')}</div>
            </td>
            <td class="col-synopsis">
                <div class="synopsis-text">${escapeHtml(stock.synopsis || '--')}</div>
            </td>
            <td class="col-price">
                <div class="price-grid">
                    <div class="price-current ${changeClass}">
                        ${stock.price ? formatNumber(stock.price) : '--'}
                        <span class="price-unit">円</span>
                    </div>
                    <div class="price-change ${changeClass}">
                        ${changeSign}${stock.change_amount || 0} (${changeSign}${(stock.change_rate || 0).toFixed(1)}%)
                    </div>
                    <div class="price-range">
                        <span class="price-label">高</span>
                        <span class="price-val">${stock.price_high ? formatNumber(stock.price_high) : '--'}</span>
                    </div>
                    <div class="price-range">
                        <span class="price-label">安</span>
                        <span class="price-val">${stock.price_low ? formatNumber(stock.price_low) : '--'}</span>
                    </div>
                </div>
            </td>
            <td class="col-metrics">
                <div class="metrics-grid">
                    <div class="metric-item">
                        <span class="metric-label">PER</span>
                        <span class="metric-value">${stock.per ? stock.per.toFixed(1) : '--'}</span>
                    </div>
                    <div class="metric-item">
                        <span class="metric-label">PBR</span>
                        <span class="metric-value">${stock.pbr ? stock.pbr.toFixed(2) : '--'}</span>
                    </div>
                    ${stock.volume ? `
                    <div class="metric-item">
                        <span class="metric-label">出来高</span>
                        <span class="metric-value metric-small">${escapeHtml(stock.volume)}</span>
                    </div>` : ''}
                </div>
            </td>
            <td class="col-chart">
                <div class="mini-chart-container">
                    <canvas id="${chartId}" width="160" height="80"></canvas>
                </div>
            </td>
        `;

        tbody.appendChild(row);

        // ミニチャートを描画
        if (stock.chart_data && stock.chart_data.length > 0) {
            setTimeout(() => renderMiniChart(chartId, stock.chart_data), 50);
        }
    });
}

// ミニチャート描画
function renderMiniChart(canvasId, chartData) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    const closes = chartData.map(d => d.close).filter(v => v != null);

    if (closes.length < 2) return;

    // 上昇/下降で色を変える
    const isUp = closes[closes.length - 1] >= closes[0];
    const lineColor = isUp ? '#16a34a' : '#dc2626';
    const bgColor = isUp ? 'rgba(22, 163, 74, 0.1)' : 'rgba(220, 38, 38, 0.1)';

    new Chart(ctx, {
        type: 'line',
        data: {
            labels: chartData.map(d => d.date || ''),
            datasets: [{
                data: closes,
                borderColor: lineColor,
                backgroundColor: bgColor,
                borderWidth: 2,
                fill: true,
                tension: 0.3,
                pointRadius: 0,
                pointHoverRadius: 3,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    enabled: true,
                    mode: 'index',
                    intersect: false,
                    callbacks: {
                        label: function (ctx) {
                            return `${ctx.parsed.y.toLocaleString()}円`;
                        }
                    }
                }
            },
            scales: {
                x: { display: false },
                y: { display: false }
            },
            interaction: {
                mode: 'nearest',
                axis: 'x',
                intersect: false
            }
        }
    });
}

// 新規データ取得
async function fetchTrendingData() {
    const btn = document.getElementById('fetchBtn');
    btn.disabled = true;
    btn.innerHTML = '<span class="btn-icon">⏳</span> 取得中...';

    showToast('話題株データを取得中...最大2分程度かかります', 'info');

    try {
        const response = await fetch('/api/trending/fetch');
        const result = await response.json();

        if (result.success) {
            showToast(`${result.count}銘柄の話題株データを取得しました`, 'success');
            loadTrendingStocks();
            loadDateOptions();
        } else {
            showToast(`エラー: ${result.error}`, 'error');
        }
    } catch (error) {
        showToast('データ取得に失敗しました', 'error');
        console.error('Fetch error:', error);
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<span class="btn-icon">🔄</span> データ取得';
    }
}

// ユーティリティ
function formatNumber(num) {
    if (num == null) return '--';
    return Number(num).toLocaleString();
}

function formatDateJP(dateStr) {
    if (!dateStr) return '--';
    const parts = dateStr.split('-');
    if (parts.length === 3) {
        return `${parts[1]}/${parts[2]}`;
    }
    return dateStr;
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function showToast(message, type = 'info') {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = `toast show ${type}`;
    setTimeout(() => {
        toast.className = 'toast';
    }, 5000);
}
