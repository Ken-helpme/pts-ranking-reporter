// PTS Dashboard JavaScript

let topStocksChart = null;
let volumeChart = null;

// Initialize dashboard on load
document.addEventListener('DOMContentLoaded', function() {
    loadDashboard();
    // Auto refresh every 5 minutes
    setInterval(loadDashboard, 5 * 60 * 1000);
});

// Load all dashboard data
async function loadDashboard() {
    await Promise.all([
        loadStats(),
        loadLatestRanking()
    ]);
}

// Load statistics
async function loadStats() {
    try {
        const response = await fetch('/api/stats');
        const result = await response.json();

        if (result.success) {
            const stats = result.data;

            document.getElementById('avgChangeRate').textContent = stats.avg_change_rate + '%';
            document.getElementById('maxChangeRate').textContent = stats.max_change_rate + '%';
            document.getElementById('totalVolume').textContent = formatNumber(stats.total_volume);
            document.getElementById('totalStocks').textContent = stats.total_stocks;

            if (stats.last_updated) {
                document.getElementById('lastUpdated').textContent = formatDateTime(stats.last_updated);
            }
        }
    } catch (error) {
        console.error('Error loading stats:', error);
    }
}

// Load latest ranking
async function loadLatestRanking() {
    const loadingIndicator = document.getElementById('loadingIndicator');
    const rankingTable = document.getElementById('rankingTable');

    try {
        loadingIndicator.style.display = 'block';
        rankingTable.style.display = 'none';

        const response = await fetch('/api/latest');
        const result = await response.json();

        if (result.success && result.data.length > 0) {
            displayRankingTable(result.data);
            updateCharts(result.data);

            loadingIndicator.style.display = 'none';
            rankingTable.style.display = 'block';
        } else {
            loadingIndicator.innerHTML = '<p>データがありません。「データ更新」ボタンをクリックしてください。</p>';
        }
    } catch (error) {
        console.error('Error loading ranking:', error);
        loadingIndicator.innerHTML = '<p class="change-negative">データの読み込みに失敗しました</p>';
    }
}

// Display ranking table
function displayRankingTable(data) {
    const tbody = document.getElementById('rankingTableBody');
    tbody.innerHTML = '';

    data.forEach((stock, index) => {
        const row = document.createElement('tr');

        const changeClass = stock.change_rate >= 0 ? 'change-positive' : 'change-negative';
        const changeSign = stock.change_rate >= 0 ? '+' : '';

        row.innerHTML = `
            <td><span class="rank-badge">${index + 1}</span></td>
            <td><span class="stock-code">${stock.code}</span></td>
            <td><strong>${stock.name}</strong></td>
            <td>¥${formatNumber(stock.pts_price)}</td>
            <td class="${changeClass}">${changeSign}${stock.change_rate.toFixed(2)}%</td>
            <td>${formatNumber(stock.volume)}</td>
            <td><span style="font-size: 12px;">${stock.market || '-'}</span></td>
            <td><button class="btn-detail" onclick="showStockDetail('${stock.code}', '${stock.name}')">詳細</button></td>
        `;

        tbody.appendChild(row);
    });
}

// Update charts
function updateCharts(data) {
    // Top 10 stocks chart
    const top10 = data.slice(0, 10);

    const chartData = {
        labels: top10.map(s => `${s.code} ${s.name.substring(0, 10)}`),
        datasets: [{
            label: '上昇率 (%)',
            data: top10.map(s => s.change_rate),
            backgroundColor: top10.map(s =>
                s.change_rate >= 0
                    ? 'rgba(102, 126, 234, 0.8)'
                    : 'rgba(245, 101, 101, 0.8)'
            ),
            borderColor: top10.map(s =>
                s.change_rate >= 0
                    ? 'rgba(102, 126, 234, 1)'
                    : 'rgba(245, 101, 101, 1)'
            ),
            borderWidth: 2,
            borderRadius: 8
        }]
    };

    const chartConfig = {
        type: 'bar',
        data: chartData,
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: {
                    display: false
                },
                tooltip: {
                    backgroundColor: 'rgba(0, 0, 0, 0.8)',
                    padding: 12,
                    titleFont: { size: 14 },
                    bodyFont: { size: 13 },
                    cornerRadius: 8
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    grid: {
                        color: 'rgba(0, 0, 0, 0.05)'
                    }
                },
                x: {
                    grid: {
                        display: false
                    }
                }
            }
        }
    };

    if (topStocksChart) {
        topStocksChart.destroy();
    }
    topStocksChart = new Chart(
        document.getElementById('topStocksChart'),
        chartConfig
    );

    // Volume chart
    const volumeData = {
        labels: top10.map(s => s.code),
        datasets: [{
            label: '出来高',
            data: top10.map(s => s.volume),
            backgroundColor: 'rgba(118, 75, 162, 0.8)',
            borderColor: 'rgba(118, 75, 162, 1)',
            borderWidth: 2
        }]
    };

    const volumeConfig = {
        type: 'doughnut',
        data: volumeData,
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: {
                    position: 'right',
                    labels: {
                        font: { size: 12 },
                        padding: 12
                    }
                },
                tooltip: {
                    backgroundColor: 'rgba(0, 0, 0, 0.8)',
                    padding: 12,
                    cornerRadius: 8,
                    callbacks: {
                        label: function(context) {
                            return context.label + ': ' + formatNumber(context.parsed) + '株';
                        }
                    }
                }
            }
        }
    };

    if (volumeChart) {
        volumeChart.destroy();
    }
    volumeChart = new Chart(
        document.getElementById('volumeChart'),
        volumeConfig
    );
}

// Fetch new data from web
async function fetchNewData() {
    showToast('データを取得中...', 'info');

    try {
        const response = await fetch('/api/fetch');
        const result = await response.json();

        if (result.success) {
            showToast(`✅ ${result.count}銘柄のデータを取得しました`, 'success');
            await loadDashboard();
        } else {
            showToast('❌ データ取得に失敗しました: ' + result.error, 'error');
        }
    } catch (error) {
        console.error('Error fetching data:', error);
        showToast('❌ データ取得に失敗しました', 'error');
    }
}

// Show stock detail modal
async function showStockDetail(code, name) {
    const modal = document.getElementById('stockModal');
    const modalContent = document.getElementById('modalContent');
    const modalStockName = document.getElementById('modalStockName');

    modalStockName.textContent = `${code} - ${name}`;
    modalContent.innerHTML = '<div class="loading"><div class="spinner"></div><p>詳細情報を読み込み中...</p></div>';

    modal.classList.add('active');

    try {
        const response = await fetch(`/api/stock/${code}`);
        const result = await response.json();

        if (result.success && result.data.length > 0) {
            const latestData = result.data[0];

            let html = '';

            // Company info
            if (latestData.company_info && Object.keys(latestData.company_info).length > 0) {
                html += '<div class="company-info">';
                if (latestData.company_info.market) {
                    html += `<div class="info-item"><div class="info-label">市場</div><div class="info-value">${latestData.company_info.market}</div></div>`;
                }
                if (latestData.company_info.industry) {
                    html += `<div class="info-item"><div class="info-label">業種</div><div class="info-value">${latestData.company_info.industry}</div></div>`;
                }
                if (latestData.company_info.market_cap) {
                    html += `<div class="info-item"><div class="info-label">時価総額</div><div class="info-value">${latestData.company_info.market_cap}</div></div>`;
                }
                html += '</div>';
            }

            // Current stats
            html += '<div style="margin-bottom: 24px;">';
            html += `<h3 style="margin-bottom: 12px;">💰 現在の情報</h3>`;
            html += `<p><strong>PTS価格:</strong> ¥${formatNumber(latestData.pts_price)}</p>`;
            html += `<p><strong>変化率:</strong> <span class="${latestData.change_rate >= 0 ? 'change-positive' : 'change-negative'}">${latestData.change_rate >= 0 ? '+' : ''}${latestData.change_rate.toFixed(2)}%</span></p>`;
            html += `<p><strong>出来高:</strong> ${formatNumber(latestData.volume)}株</p>`;
            html += '</div>';

            // News
            if (latestData.news && latestData.news.length > 0) {
                html += '<h3 style="margin-bottom: 12px;">📰 最新ニュース</h3>';
                latestData.news.forEach(newsItem => {
                    html += '<div class="news-item">';
                    html += `<div class="news-title">${newsItem.title}</div>`;
                    if (newsItem.date) {
                        html += `<div class="news-date">${newsItem.date}</div>`;
                    }
                    html += '</div>';
                });
            }

            // Historical data
            if (result.data.length > 1) {
                html += '<h3 style="margin: 24px 0 12px;">📈 過去データ</h3>';
                html += '<table class="ranking-table">';
                html += '<thead><tr><th>日時</th><th>価格</th><th>変化率</th><th>出来高</th></tr></thead>';
                html += '<tbody>';
                result.data.forEach(item => {
                    html += '<tr>';
                    html += `<td>${formatDateTime(item.timestamp)}</td>`;
                    html += `<td>¥${formatNumber(item.pts_price)}</td>`;
                    html += `<td class="${item.change_rate >= 0 ? 'change-positive' : 'change-negative'}">${item.change_rate >= 0 ? '+' : ''}${item.change_rate.toFixed(2)}%</td>`;
                    html += `<td>${formatNumber(item.volume)}</td>`;
                    html += '</tr>';
                });
                html += '</tbody></table>';
            }

            modalContent.innerHTML = html;
        } else {
            modalContent.innerHTML = '<p>詳細情報が見つかりませんでした</p>';
        }
    } catch (error) {
        console.error('Error loading stock detail:', error);
        modalContent.innerHTML = '<p class="change-negative">エラーが発生しました</p>';
    }
}

// Close modal
function closeModal() {
    const modal = document.getElementById('stockModal');
    modal.classList.remove('active');
}

// Show toast notification
function showToast(message, type = 'info') {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = `toast ${type} show`;

    setTimeout(() => {
        toast.classList.remove('show');
    }, 3000);
}

// Format number with commas
function formatNumber(num) {
    if (num === null || num === undefined) return '-';
    return num.toLocaleString('ja-JP');
}

// Format datetime
function formatDateTime(dateStr) {
    if (!dateStr) return '-';
    const date = new Date(dateStr);
    return date.toLocaleString('ja-JP', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
    });
}

// Close modal on outside click
window.onclick = function(event) {
    const modal = document.getElementById('stockModal');
    if (event.target === modal) {
        closeModal();
    }
}
