/**
 * 銘柄スクリーニング JavaScript
 */

// 初期化
document.addEventListener('DOMContentLoaded', () => {
    loadSectors();
});

/**
 * 業種セレクトボックスにオプションを追加
 */
async function loadSectors() {
    try {
        const res = await fetch('/api/screening/sectors');
        const data = await res.json();
        if (data.success && data.sectors) {
            const select = document.getElementById('sectorFilter');
            data.sectors.forEach(s => {
                const opt = document.createElement('option');
                opt.value = s.code;
                opt.textContent = s.name;
                select.appendChild(opt);
            });
        }
    } catch (e) {
        console.warn('業種データ取得失敗:', e);
    }
}

/**
 * スクリーニング実行
 */
async function runScreening() {
    const btn = document.getElementById('searchBtn');
    const loading = document.getElementById('loadingOverlay');
    const emptyState = document.getElementById('emptyState');
    const tableWrapper = document.getElementById('tableWrapper');
    const resultSummary = document.getElementById('resultSummary');

    btn.disabled = true;
    btn.textContent = '⏳ 検索中...';
    loading.style.display = 'flex';
    emptyState.style.display = 'none';

    // フィルター値を取得
    const filters = getFilterValues();

    try {
        const startTime = performance.now();
        const res = await fetch('/api/screening/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(filters),
        });

        const data = await res.json();
        const elapsed = ((performance.now() - startTime) / 1000).toFixed(1);

        if (data.success) {
            renderResults(data.results);
            // サマリー表示
            document.getElementById('summaryDate').textContent = `📅 ${data.date || ''}`;
            document.getElementById('summaryCount').textContent = `${data.total}件 ヒット`;
            document.getElementById('summaryTime').textContent = `⏱ ${elapsed}秒`;
            resultSummary.style.display = 'block';
            tableWrapper.style.display = 'block';
            // 結果まで自動スクロール
            setTimeout(() => {
                resultSummary.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }, 100);
        } else {
            showToast(data.error || 'スクリーニングに失敗しました', 'error');
            emptyState.style.display = 'block';
            tableWrapper.style.display = 'none';
            resultSummary.style.display = 'none';
        }
    } catch (e) {
        showToast('通信エラーが発生しました', 'error');
        emptyState.style.display = 'block';
        tableWrapper.style.display = 'none';
        resultSummary.style.display = 'none';
    } finally {
        loading.style.display = 'none';
        btn.disabled = false;
        btn.textContent = '🔍 スクリーニング実行';
    }
}

/**
 * フィルター値取得
 */
function getFilterValues() {
    const sortVal = document.getElementById('sortBy').value;
    let sortBy = 'volume';
    let sortDesc = true;

    if (sortVal === 'volume') { sortBy = 'volume'; sortDesc = true; }
    else if (sortVal === 'turnover') { sortBy = 'turnover'; sortDesc = true; }
    else if (sortVal === 'change_rate_desc') { sortBy = 'change_rate'; sortDesc = true; }
    else if (sortVal === 'change_rate_asc') { sortBy = 'change_rate'; sortDesc = false; }
    else if (sortVal === 'close_desc') { sortBy = 'close'; sortDesc = true; }
    else if (sortVal === 'close_asc') { sortBy = 'close'; sortDesc = false; }

    return {
        market: document.getElementById('marketFilter').value,
        sector: document.getElementById('sectorFilter').value,
        price_min: parseFloat(document.getElementById('priceMin').value) || null,
        price_max: parseFloat(document.getElementById('priceMax').value) || null,
        volume_min: parseFloat(document.getElementById('volumeMin').value) || null,
        change_rate_min: parseFloat(document.getElementById('changeMin').value) || null,
        change_rate_max: parseFloat(document.getElementById('changeMax').value) || null,
        sort_by: sortBy,
        sort_desc: sortDesc,
        limit: parseInt(document.getElementById('limitFilter').value) || 100,
    };
}

/**
 * 結果テーブルを描画
 */
function renderResults(results) {
    const tbody = document.getElementById('resultBody');
    tbody.innerHTML = '';

    results.forEach((stock, idx) => {
        const tr = document.createElement('tr');
        const changeClass = stock.change_rate > 0 ? 'change-positive'
            : stock.change_rate < 0 ? 'change-negative'
                : 'change-zero';
        const changeSign = stock.change_rate > 0 ? '+' : '';
        const marketClass = stock.market === 'プライム' ? 'market-prime'
            : stock.market === 'スタンダード' ? 'market-standard'
                : stock.market === 'グロース' ? 'market-growth'
                    : '';

        const code4 = stock.code.replace(/0$/, '');

        tr.innerHTML = `
            <td class="col-rank">${idx + 1}</td>
            <td class="col-code">
                <a href="https://kabutan.jp/stock/?code=${code4}" target="_blank" rel="noopener">${code4}</a>
            </td>
            <td class="col-name" title="${stock.name}">${stock.name}</td>
            <td class="col-market">
                <span class="market-badge ${marketClass}">${stock.market}</span>
            </td>
            <td class="col-sector" title="${stock.sector}">${stock.sector}</td>
            <td class="col-price">${formatNumber(stock.close)}</td>
            <td class="col-change ${changeClass}">
                ${changeSign}${stock.change_rate.toFixed(2)}%
                <br><small>${changeSign}${formatNumber(stock.change_amount)}</small>
            </td>
            <td class="col-volume">${formatVolume(stock.volume)}</td>
            <td class="col-turnover">${formatTurnover(stock.turnover)}</td>
            <td class="col-range">${formatNumber(stock.low)} - ${formatNumber(stock.high)}</td>
        `;
        tbody.appendChild(tr);
    });
}

/**
 * プリセットを適用
 */
function applyPreset(preset) {
    resetFilters(false);

    switch (preset) {
        case 'value':
            // 割安株: プライム、株価1000円以下
            document.getElementById('marketFilter').value = 'プライム';
            document.getElementById('priceMax').value = '1000';
            document.getElementById('sortBy').value = 'volume';
            break;
        case 'growth':
            // 急騰株: 前日比+5%以上
            document.getElementById('changeMin').value = '5';
            document.getElementById('sortBy').value = 'change_rate_desc';
            break;
        case 'large_cap':
            // 大型株: プライム、株価5000円以上
            document.getElementById('marketFilter').value = 'プライム';
            document.getElementById('priceMin').value = '5000';
            document.getElementById('sortBy').value = 'turnover';
            break;
        case 'small_cap':
            // 小型株: グロース、株価500円以下
            document.getElementById('marketFilter').value = 'グロース';
            document.getElementById('priceMax').value = '500';
            document.getElementById('volumeMin').value = '100000';
            document.getElementById('sortBy').value = 'volume';
            break;
        case 'high_volume':
            // 高出来高
            document.getElementById('volumeMin').value = '5000000';
            document.getElementById('sortBy').value = 'volume';
            break;
        case 'decline':
            // 下落株
            document.getElementById('changeMax').value = '-5';
            document.getElementById('sortBy').value = 'change_rate_asc';
            break;
    }

    runScreening();
}

/**
 * フィルターリセット
 */
function resetFilters(clearResults = true) {
    document.getElementById('marketFilter').value = '';
    document.getElementById('sectorFilter').value = '';
    document.getElementById('priceMin').value = '';
    document.getElementById('priceMax').value = '';
    document.getElementById('volumeMin').value = '';
    document.getElementById('changeMin').value = '';
    document.getElementById('changeMax').value = '';
    document.getElementById('sortBy').value = 'volume';
    document.getElementById('limitFilter').value = '100';

    if (clearResults) {
        document.getElementById('resultBody').innerHTML = '';
        document.getElementById('tableWrapper').style.display = 'none';
        document.getElementById('resultSummary').style.display = 'none';
        document.getElementById('emptyState').style.display = 'block';
    }
}

/**
 * 数値フォーマット（カンマ区切り）
 */
function formatNumber(num) {
    if (num == null) return '--';
    return Number(num).toLocaleString('ja-JP');
}

/**
 * 出来高フォーマット
 */
function formatVolume(vol) {
    if (vol == null || vol === 0) return '--';
    if (vol >= 100000000) return (vol / 100000000).toFixed(1) + '億';
    if (vol >= 10000) return (vol / 10000).toFixed(0) + '万';
    return vol.toLocaleString('ja-JP');
}

/**
 * 売買代金フォーマット
 */
function formatTurnover(val) {
    if (val == null || val === 0) return '--';
    if (val >= 100000000) return (val / 100000000).toFixed(0) + '億';
    if (val >= 10000) return (val / 10000).toFixed(0) + '万';
    return val.toLocaleString('ja-JP');
}

/**
 * トースト通知
 */
function showToast(msg, type = 'info') {
    const existing = document.querySelector('.toast');
    if (existing) existing.remove();

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = msg;
    toast.style.cssText = `
        position: fixed;
        bottom: 20px;
        right: 20px;
        padding: 12px 20px;
        border-radius: 8px;
        color: #fff;
        font-size: 13px;
        z-index: 9999;
        animation: toastIn 0.3s ease;
        background: ${type === 'error' ? '#ef4444' : type === 'success' ? '#22c55e' : '#5b8dee'};
        box-shadow: 0 4px 12px rgba(0,0,0,0.3);
    `;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 4000);
}
