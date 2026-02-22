// PTS ダッシュボード JavaScript

let topStocksChart = null;
let volumeChart = null;

// ページ読み込み時にダッシュボードを初期化
document.addEventListener('DOMContentLoaded', function () {
    loadDashboard();
    // 5分ごとに自動更新
    setInterval(loadDashboard, 5 * 60 * 1000);
});

// ダッシュボード全体を読み込み
async function loadDashboard() {
    await Promise.all([
        loadStats(),
        loadLatestRanking()
    ]);
}

// 統計情報を読み込み
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
        console.error('統計情報の読み込みエラー:', error);
    }
}

// 最新ランキングを読み込み
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
        console.error('ランキング読み込みエラー:', error);
        loadingIndicator.innerHTML = '<p class="change-negative">データの読み込みに失敗しました</p>';
    }
}

// ランキングテーブルを表示
function displayRankingTable(data) {
    const tbody = document.getElementById('rankingTableBody');
    tbody.innerHTML = '';

    data.forEach((stock, index) => {
        const row = document.createElement('tr');

        const changeClass = stock.change_rate >= 0 ? 'change-positive' : 'change-negative';
        const changeSign = stock.change_rate >= 0 ? '+' : '';

        // 上昇理由を80文字に制限
        const mainReason = stock.main_reason || '分析中...';
        const displayReason = mainReason.length > 80 ? mainReason.substring(0, 80) + '...' : mainReason;

        // 評価バッジ
        let ratingBadge = '-';
        if (stock.analysis && stock.analysis.evaluation) {
            const rating = stock.analysis.evaluation.overall_rating;
            const ratingColors = {
                'SS': '#dc2626',
                'S': '#2563eb',
                'A': '#16a34a',
                'B': '#d97706',
                'C': '#9ca3af'
            };
            const color = ratingColors[rating] || '#ddd';
            ratingBadge = `<span class="rating-badge" style="background: ${color};">${rating}</span>`;
        }

        // PER・PBR
        const per = stock.company_info && stock.company_info.per ? stock.company_info.per : '-';
        const pbr = stock.company_info && stock.company_info.pbr ? stock.company_info.pbr : '-';

        row.innerHTML = `
            <td><span class="rank-badge">${index + 1}</span></td>
            <td>${ratingBadge}</td>
            <td><span class="stock-code">${stock.code}</span></td>
            <td><strong>${stock.name}</strong></td>
            <td>¥${formatNumber(stock.pts_price)}</td>
            <td class="${changeClass}">${changeSign}${stock.change_rate.toFixed(2)}%</td>
            <td><span style="font-size: 12px;">${per}</span></td>
            <td><span style="font-size: 12px;">${pbr}</span></td>
            <td>${formatNumber(stock.volume)}</td>
            <td><span style="font-size: 12px; color: #555;" title="${mainReason}">${displayReason}</span></td>
            <td><button class="btn-detail" onclick="showStockDetail('${stock.code}', '${stock.name}')">詳細</button></td>
        `;

        tbody.appendChild(row);
    });
}

// チャートを更新
function updateCharts(data) {
    const top10 = data.slice(0, 10);

    const chartData = {
        labels: top10.map(s => `${s.code} ${s.name.substring(0, 10)}`),
        datasets: [{
            label: '上昇率 (%)',
            data: top10.map(s => s.change_rate),
            backgroundColor: top10.map(s =>
                s.change_rate >= 0
                    ? 'rgba(37, 99, 235, 0.7)'
                    : 'rgba(220, 38, 38, 0.7)'
            ),
            borderColor: top10.map(s =>
                s.change_rate >= 0
                    ? 'rgba(37, 99, 235, 1)'
                    : 'rgba(220, 38, 38, 1)'
            ),
            borderWidth: 1,
            borderRadius: 4
        }]
    };

    const chartConfig = {
        type: 'bar',
        data: chartData,
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: 'rgba(0, 0, 0, 0.75)',
                    padding: 10,
                    titleFont: { size: 13 },
                    bodyFont: { size: 12 },
                    cornerRadius: 4
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    grid: { color: 'rgba(0, 0, 0, 0.05)' }
                },
                x: {
                    grid: { display: false }
                }
            }
        }
    };

    if (topStocksChart) topStocksChart.destroy();
    topStocksChart = new Chart(document.getElementById('topStocksChart'), chartConfig);

    // 出来高チャート
    const volumeData = {
        labels: top10.map(s => s.code),
        datasets: [{
            label: '出来高',
            data: top10.map(s => s.volume),
            backgroundColor: 'rgba(37, 99, 235, 0.6)',
            borderColor: 'rgba(37, 99, 235, 1)',
            borderWidth: 1
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
                    labels: { font: { size: 12 }, padding: 10 }
                },
                tooltip: {
                    backgroundColor: 'rgba(0, 0, 0, 0.75)',
                    padding: 10,
                    cornerRadius: 4,
                    callbacks: {
                        label: function (context) {
                            return context.label + ': ' + formatNumber(context.parsed) + '株';
                        }
                    }
                }
            }
        }
    };

    if (volumeChart) volumeChart.destroy();
    volumeChart = new Chart(document.getElementById('volumeChart'), volumeConfig);
}

// 新規データを取得
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
        console.error('データ取得エラー:', error);
        showToast('❌ データ取得に失敗しました', 'error');
    }
}

// 銘柄詳細モーダルを表示
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

            // 総合評価
            if (latestData.analysis && latestData.analysis.evaluation) {
                const evaluation = latestData.analysis.evaluation;
                html += `<div class="rating-large">`;
                html += `<div class="rating-value">${evaluation.overall_rating}</div>`;
                html += `<div class="rating-score">総合評価 ${evaluation.score}/100点</div>`;
                html += `</div>`;
            }

            // 企業情報
            if (latestData.company_info && Object.keys(latestData.company_info).length > 0) {
                html += '<div class="company-info">';
                const fields = [
                    { key: 'market', label: '市場' },
                    { key: 'industry', label: '業種' },
                    { key: 'market_cap', label: '時価総額' },
                    { key: 'per', label: 'PER', suffix: '倍' },
                    { key: 'pbr', label: 'PBR', suffix: '倍' },
                    { key: 'dividend_yield', label: '配当利回り', suffix: '%' },
                    { key: 'roe', label: 'ROE', suffix: '%' },
                ];
                fields.forEach(f => {
                    if (latestData.company_info[f.key]) {
                        const val = latestData.company_info[f.key] + (f.suffix || '');
                        html += `<div class="info-item"><div class="info-label">${f.label}</div><div class="info-value">${val}</div></div>`;
                    }
                });
                html += '</div>';
            }

            // 週足チャート（株探 iframe）
            html += '<div class="analysis-section">';
            html += '<h4>📈 週足チャート</h4>';
            html += `<div style="margin-top: 8px; position: relative; overflow: hidden; border-radius: 6px; border: 1px solid var(--border-color); height: 500px;">`;
            html += `<iframe src="https://kabutan.jp/stock/chart?code=${code}&ashi=2" `;
            html += `style="width: 100%; height: 1200px; border: none; margin-top: -380px;" `;
            html += `loading="lazy" referrerpolicy="no-referrer"></iframe>`;
            html += `</div>`;
            html += `<div style="margin-top: 8px; text-align: right;">`;
            html += `<a href="https://kabutan.jp/stock/chart?code=${code}&ashi=2" target="_blank" rel="noopener" `;
            html += `style="color: var(--primary-color); font-size: 13px; text-decoration: none;">`;
            html += `📊 株探で全画面チャートを見る →</a>`;
            html += `</div>`;
            html += '</div>';

            // 決算分析
            if (latestData.analysis && latestData.analysis.earnings_detail) {
                const ed = latestData.analysis.earnings_detail;

                // インパクト評価
                if (ed.short_term_impact || ed.long_term_impact) {
                    html += '<div style="margin-bottom: 12px;">';
                    if (ed.short_term_impact) {
                        const cls = ed.short_term_impact === 'High' ? 'impact-high' : ed.short_term_impact === 'Medium' ? 'impact-medium' : 'impact-low';
                        html += `<span class="impact-badge ${cls}">短期インパクト: ${ed.short_term_impact}</span>`;
                    }
                    if (ed.long_term_impact) {
                        const cls = ed.long_term_impact === 'High' ? 'impact-high' : ed.long_term_impact === 'Medium' ? 'impact-medium' : 'impact-low';
                        html += `<span class="impact-badge ${cls}">長期インパクト: ${ed.long_term_impact}</span>`;
                    }
                    html += '</div>';
                }

                // 決算サマリー
                if (ed.earnings_reason) {
                    html += `<div class="analysis-section earnings">`;
                    html += `<h4>📋 決算サマリー</h4>`;
                    html += `<p>${ed.earnings_reason}</p>`;
                    html += `</div>`;
                }

                // 財務数値
                if (ed.financial_summary && !['Not disclosed', '原文に記載なし'].includes(ed.financial_summary)) {
                    html += `<div class="analysis-section earnings">`;
                    html += `<h4>📊 財務数値</h4>`;
                    html += `<p>${ed.financial_summary}</p>`;
                    html += `</div>`;
                }

                // 株価上昇の主要要因
                if (ed.key_factors && ed.key_factors.length > 0) {
                    html += `<div class="analysis-section reason">`;
                    html += `<h4>⚡ 株価上昇の主要要因</h4>`;
                    html += `<ul>`;
                    ed.key_factors.forEach(f => { html += `<li>${f}</li>`; });
                    html += `</ul></div>`;
                }

                // 構造的カタリスト
                if (ed.catalysts && ed.catalysts.length > 0) {
                    html += `<div class="analysis-section">`;
                    html += `<h4>🚀 構造的カタリスト</h4>`;
                    html += `<ul>`;
                    ed.catalysts.forEach(c => { html += `<li>${c}</li>`; });
                    html += `</ul></div>`;
                }

                // 投資テーゼ
                if (ed.investment_thesis && ed.investment_thesis.length > 0) {
                    html += `<div class="analysis-section">`;
                    html += `<h4>💼 投資テーゼ（ブル）</h4>`;
                    html += `<ul>`;
                    ed.investment_thesis.forEach(t => { html += `<li>${t}</li>`; });
                    html += `</ul></div>`;
                }

                // リスク
                if (ed.risks && ed.risks.length > 0) {
                    html += `<div class="analysis-section risk">`;
                    html += `<h4>⚠️ リスク</h4>`;
                    html += `<ul>`;
                    ed.risks.forEach(r => { html += `<li>${r}</li>`; });
                    html += `</ul></div>`;
                }

                // 見通し
                if (ed.outlook && !['Not disclosed', '原文に記載なし'].includes(ed.outlook)) {
                    html += `<div class="analysis-section future">`;
                    html += `<h4>🔭 会社予想・ガイダンス</h4>`;
                    html += `<p>${ed.outlook}</p>`;
                    html += `</div>`;
                }
            }

            // 評価の内訳
            if (latestData.analysis && latestData.analysis.evaluation && latestData.analysis.evaluation.details) {
                const evaluation = latestData.analysis.evaluation;
                html += '<div class="analysis-section">';
                html += `<h4>📈 評価の内訳</h4>`;
                html += `<div class="eval-grid">`;

                const ratings = [
                    { label: 'PER評価', value: evaluation.per_rating },
                    { label: 'PBR評価', value: evaluation.pbr_rating },
                    { label: '成長性', value: evaluation.growth_rating },
                    { label: '決算', value: evaluation.earnings_rating }
                ];

                ratings.forEach(r => {
                    html += `<div class="eval-item">`;
                    html += `<div class="eval-label">${r.label}</div>`;
                    html += `<div class="eval-value">${r.value}</div>`;
                    html += `</div>`;
                });

                html += `</div>`;
                html += `<ul>`;
                evaluation.details.forEach(detail => {
                    html += `<li>${detail}</li>`;
                });
                html += `</ul></div>`;
            }

            // 上昇理由
            if (latestData.main_reason) {
                html += '<div class="analysis-section reason">';
                html += `<h4>📊 上昇理由</h4>`;
                html += `<p>${latestData.main_reason}</p>`;
                html += '</div>';
            }

            // 将来性評価
            if (latestData.future_potential) {
                html += '<div class="analysis-section future">';
                html += `<h4>🔮 将来性評価</h4>`;
                html += `<p>${latestData.future_potential}</p>`;
                html += '</div>';
            }

            // 現在の情報
            html += '<div class="analysis-section">';
            html += `<h4>💰 現在の情報</h4>`;
            html += `<p><strong>PTS価格:</strong> ¥${formatNumber(latestData.pts_price)}</p>`;
            html += `<p><strong>変化率:</strong> <span class="${latestData.change_rate >= 0 ? 'change-positive' : 'change-negative'}">${latestData.change_rate >= 0 ? '+' : ''}${latestData.change_rate.toFixed(2)}%</span></p>`;
            html += `<p><strong>出来高:</strong> ${formatNumber(latestData.volume)}株</p>`;
            html += '</div>';

            // ニュース
            if (latestData.news && latestData.news.length > 0) {
                html += '<h3 style="margin-bottom: 10px; font-size: 15px;">📰 最新ニュース</h3>';
                latestData.news.forEach(newsItem => {
                    html += '<div class="news-item">';
                    if (newsItem.url) {
                        html += `<div class="news-title"><a href="${newsItem.url}" target="_blank" rel="noopener" style="color: var(--primary-color); text-decoration: none;">${newsItem.title}</a></div>`;
                    } else {
                        html += `<div class="news-title">${newsItem.title}</div>`;
                    }
                    if (newsItem.date) {
                        html += `<div class="news-date">${newsItem.date}</div>`;
                    }
                    html += '</div>';
                });
            }

            // 外部リンク集
            html += '<div class="analysis-section">';
            html += '<h4>🔗 外部リンク</h4>';
            html += '<div style="display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px;">';
            const externalLinks = [
                { label: '株探 企業情報', url: `https://kabutan.jp/stock/?code=${code}`, icon: '🏢' },
                { label: '株探 決算', url: `https://kabutan.jp/stock/finance?code=${code}`, icon: '📊' },
                { label: '株探 ニュース', url: `https://kabutan.jp/stock/news?code=${code}`, icon: '📰' },
                { label: 'Yahoo Finance', url: `https://finance.yahoo.co.jp/quote/${code}.T`, icon: '💹' },
                { label: 'TradingView', url: `https://jp.tradingview.com/chart/?symbol=TSE:${code}`, icon: '📈' },
                { label: 'IRBANK', url: `https://irbank.net/${code}`, icon: '🏦' },
            ];
            externalLinks.forEach(link => {
                html += `<a href="${link.url}" target="_blank" rel="noopener" `;
                html += `style="display: inline-flex; align-items: center; gap: 4px; padding: 6px 12px; `;
                html += `background: var(--primary-light); color: var(--primary-color); border-radius: 6px; `;
                html += `text-decoration: none; font-size: 13px; font-weight: 500; `;
                html += `border: 1px solid #dbeafe; transition: background 0.2s;">`;
                html += `${link.icon} ${link.label}</a>`;
            });
            html += '</div>';
            html += '</div>';

            // 過去データ
            if (result.data.length > 1) {
                html += '<h3 style="margin: 20px 0 10px; font-size: 15px;">📈 過去データ</h3>';
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
        console.error('銘柄詳細の読み込みエラー:', error);
        modalContent.innerHTML = '<p class="change-negative">エラーが発生しました</p>';
    }
}

// モーダルを閉じる
function closeModal() {
    const modal = document.getElementById('stockModal');
    modal.classList.remove('active');
}

// トースト通知を表示
function showToast(message, type = 'info') {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = `toast ${type} show`;

    setTimeout(() => {
        toast.classList.remove('show');
    }, 3000);
}

// 数値をカンマ区切りにフォーマット
function formatNumber(num) {
    if (num === null || num === undefined) return '-';
    return num.toLocaleString('ja-JP');
}

// 日時をフォーマット
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

// モーダル外クリックで閉じる
window.onclick = function (event) {
    const modal = document.getElementById('stockModal');
    if (event.target === modal) {
        closeModal();
    }
}
