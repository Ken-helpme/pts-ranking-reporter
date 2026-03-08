/**
 * 銘柄スクリーニング JavaScript
 */

// 初期化
document.addEventListener('DOMContentLoaded', () => {
    loadSectors();
    loadTopPicks();
});

/**
 * 今買うべき10銘柄を自動ロード
 */
async function loadTopPicks() {
    const grid    = document.getElementById('picksGrid');
    const loading = document.getElementById('picksLoading');
    const errEl   = document.getElementById('picksError');
    const errMsg  = document.getElementById('picksErrorMsg');
    const dateEl  = document.getElementById('topPicksDate');

    loading.style.display = 'flex';
    grid.style.display    = 'none';
    errEl.style.display   = 'none';

    try {
        const res  = await fetch('/api/screening/top_picks?n=10');
        const data = await res.json();

        if (data.success && data.picks && data.picks.length > 0) {
            dateEl.textContent = data.date ? `📅 ${data.date} 終値ベース` : '';
            renderPickCards(data.picks);
            grid.style.display = 'grid';
        } else {
            const msg = data.error || '銘柄データが取得できませんでした';
            errMsg.textContent = msg;
            errEl.style.display = 'block';
        }
    } catch (e) {
        errMsg.textContent = '通信エラー: ' + e.message;
        errEl.style.display = 'block';
    } finally {
        loading.style.display = 'none';
    }
}

function renderPickCards(picks) {
    const grid = document.getElementById('picksGrid');
    grid.innerHTML = '';

    const tagClasses = {
        '急騰':   'tag-surge',
        '上昇':   'tag-rising',
        '堅調':   'tag-steady',
        'プライム': 'tag-prime',
        'グロース': 'tag-growth',
        '超大型': 'tag-mega',
        '大商い': 'tag-liquid',
        '高流動性': 'tag-liquid',
    };

    picks.forEach((s, idx) => {
        const rank    = idx + 1;
        const isTop3  = rank <= 3;
        const cr      = s.change_rate;
        const crSign  = cr > 0 ? '+' : '';
        const crClass = cr > 0 ? 'up' : cr < 0 ? 'down' : 'flat';

        const mktClass = s.market === 'プライム' ? 'market-prime'
                       : s.market === 'スタンダード' ? 'market-standard'
                       : s.market === 'グロース' ? 'market-growth' : '';

        const tagsHtml = (s.tags || []).map(tag => {
            const cls = tagClasses[tag] || 'tag-default';
            return `<span class="pick-tag ${cls}">${escHtml(tag)}</span>`;
        }).join('');

        const card = document.createElement('div');
        card.className = `pick-card${isTop3 ? ' rank-top' : ''}`;
        card.innerHTML = `
            <div class="pick-rank-badge">${rank}</div>
            <div class="pick-code-row">
                <a href="https://kabutan.jp/stock/?code=${escHtml(s.code)}"
                   target="_blank" rel="noopener" class="pick-code-link">${escHtml(s.code)}</a>
                <span class="pick-market-badge ${mktClass}">${escHtml(s.market)}</span>
            </div>
            <div class="pick-name" title="${escHtml(s.name)}">${escHtml(s.name)}</div>
            <div class="pick-price-row">
                <span class="pick-price">¥${formatNumber(s.close)}</span>
                <span class="pick-change ${crClass}">${crSign}${cr.toFixed(2)}%</span>
            </div>
            <div class="pick-turnover">売買代金 ${formatTurnover(s.turnover)}</div>
            <div class="pick-tags">${tagsHtml}</div>
        `;
        grid.appendChild(card);
    });
}

/**
 * 業種セレクトボックスにオプションを追加
 */
async function loadSectors() {
    try {
        const res = await fetch('/api/screening/sectors');
        const data = await res.json();
        if (data.success && data.sectors && data.sectors.length > 0) {
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
    tableWrapper.style.display = 'none';
    resultSummary.style.display = 'none';

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

        if (data.success && data.results && data.results.length > 0) {
            renderResults(data.results);
            document.getElementById('summaryDate').textContent = `📅 ${data.date || ''}`;
            document.getElementById('summaryCount').textContent = `${data.total}件 ヒット`;
            document.getElementById('summaryTime').textContent = `⏱ ${elapsed}秒`;
            resultSummary.style.display = 'block';
            tableWrapper.style.display = 'block';
            setTimeout(() => {
                resultSummary.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }, 100);
        } else if (data.success && data.results && data.results.length === 0) {
            showEmptyState('該当する銘柄が見つかりませんでした', '条件を緩めて再度お試しください');
        } else {
            const errMsg = data.error || 'スクリーニングに失敗しました';
            // API未設定の場合は分かりやすいメッセージ
            if (errMsg.includes('api key') || errMsg.includes('Forbidden') || errMsg.includes('403')) {
                showEmptyState('J-Quants API キーが未設定です', 'JQUANTS_API_KEY 環境変数を設定してください', true);
            } else {
                showEmptyState('エラーが発生しました', errMsg, true);
            }
        }
    } catch (e) {
        showEmptyState('通信エラーが発生しました', e.message, true);
    } finally {
        loading.style.display = 'none';
        btn.disabled = false;
        btn.textContent = '🔍 スクリーニング実行';
    }
}

function showEmptyState(title, sub, isError = false) {
    const el = document.getElementById('emptyState');
    el.className = isError ? 'empty-state error-state' : 'empty-state';
    el.innerHTML = `
        <div class="empty-icon">${isError ? '⚠️' : '🔍'}</div>
        <h2>${title}</h2>
        <p class="sub">${sub}</p>
    `;
    el.style.display = 'block';
    document.getElementById('tableWrapper').style.display = 'none';
    document.getElementById('resultSummary').style.display = 'none';
}

/**
 * フィルター値取得
 */
function getFilterValues() {
    const sortVal = document.getElementById('sortBy').value;
    let sortBy = 'turnover';
    let sortDesc = true;

    if (sortVal === 'turnover')         { sortBy = 'turnover';     sortDesc = true; }
    else if (sortVal === 'volume')      { sortBy = 'volume';       sortDesc = true; }
    else if (sortVal === 'change_rate_desc') { sortBy = 'change_rate'; sortDesc = true; }
    else if (sortVal === 'change_rate_asc')  { sortBy = 'change_rate'; sortDesc = false; }
    else if (sortVal === 'close_desc')  { sortBy = 'close';        sortDesc = true; }
    else if (sortVal === 'close_asc')   { sortBy = 'close';        sortDesc = false; }

    const volumeMinVal = document.getElementById('volumeMin').value;
    const turnoverMinVal = document.getElementById('turnoverMin').value;

    return {
        market:           document.getElementById('marketFilter').value,
        sector:           document.getElementById('sectorFilter').value,
        price_min:        parseFloat(document.getElementById('priceMin').value) || null,
        price_max:        parseFloat(document.getElementById('priceMax').value) || null,
        volume_min:       volumeMinVal ? parseFloat(volumeMinVal) : null,
        turnover_min:     turnoverMinVal ? parseFloat(turnoverMinVal) : null,
        change_rate_min:  parseFloat(document.getElementById('changeMin').value) || null,
        change_rate_max:  parseFloat(document.getElementById('changeMax').value) || null,
        sort_by:          sortBy,
        sort_desc:        sortDesc,
        limit:            parseInt(document.getElementById('limitFilter').value) || 100,
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

        // 株探リンク用（末尾0除去済み）
        const code4 = stock.code;

        tr.innerHTML = `
            <td class="col-rank">${idx + 1}</td>
            <td class="col-code">
                <a href="https://kabutan.jp/stock/?code=${code4}" target="_blank" rel="noopener">${code4}</a>
            </td>
            <td class="col-name" title="${escHtml(stock.name)}">${escHtml(stock.name)}</td>
            <td class="col-market">
                <span class="market-badge ${marketClass}">${escHtml(stock.market)}</span>
            </td>
            <td class="col-sector" title="${escHtml(stock.sector)}">${escHtml(stock.sector)}</td>
            <td class="col-price">¥${formatNumber(stock.close)}</td>
            <td class="col-change ${changeClass}">
                ${changeSign}${stock.change_rate.toFixed(2)}%
                <br><small style="font-weight:400;color:inherit;">${changeSign}${formatNumber(stock.change_amount)}</small>
            </td>
            <td class="col-volume">${formatVolume(stock.volume)}</td>
            <td class="col-turnover">${formatTurnover(stock.turnover)}</td>
            <td class="col-range" style="font-size:11px;">
                ¥${formatNumber(stock.low)}<span style="color:#cbd5e1;margin:0 3px;">─</span>¥${formatNumber(stock.high)}
            </td>
        `;
        tbody.appendChild(tr);
    });
}

/**
 * プリセット適用
 */
function applyPreset(preset) {
    resetFilters(false);

    switch (preset) {
        case 'surge':
            document.getElementById('changeMin').value = '5';
            document.getElementById('sortBy').value = 'change_rate_desc';
            break;
        case 'active':
            document.getElementById('turnoverMin').value = '1000000000';  // 10億
            document.getElementById('sortBy').value = 'turnover';
            break;
        case 'prime_large':
            document.getElementById('marketFilter').value = 'プライム';
            document.getElementById('turnoverMin').value = '1000000000';  // 10億
            document.getElementById('sortBy').value = 'turnover';
            break;
        case 'growth_small':
            document.getElementById('marketFilter').value = 'グロース';
            document.getElementById('priceMax').value = '1000';
            document.getElementById('sortBy').value = 'change_rate_desc';
            break;
        case 'low_price':
            document.getElementById('priceMax').value = '500';
            document.getElementById('volumeMin').value = '100000';  // 10万株
            document.getElementById('sortBy').value = 'volume';
            break;
        case 'decline':
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
    document.getElementById('turnoverMin').value = '';
    document.getElementById('changeMin').value = '';
    document.getElementById('changeMax').value = '';
    document.getElementById('sortBy').value = 'turnover';
    document.getElementById('limitFilter').value = '100';

    if (clearResults) {
        document.getElementById('resultBody').innerHTML = '';
        document.getElementById('tableWrapper').style.display = 'none';
        document.getElementById('resultSummary').style.display = 'none';
        const el = document.getElementById('emptyState');
        el.className = 'empty-state';
        el.innerHTML = `
            <div class="empty-icon">🔍</div>
            <h2>銘柄スクリーニング</h2>
            <p>条件を設定して「スクリーニング実行」をクリックしてください</p>
            <p class="sub">J-Quants API で東証上場 約4,000銘柄を検索</p>
        `;
        el.style.display = 'block';
    }
}

/* ── フォーマットヘルパー ── */

function escHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function formatNumber(num) {
    if (num == null) return '--';
    return Number(num).toLocaleString('ja-JP');
}

function formatVolume(vol) {
    if (vol == null || vol === 0) return '--';
    if (vol >= 100000000) return (vol / 100000000).toFixed(1) + '億株';
    if (vol >= 10000) return Math.round(vol / 10000) + '万株';
    return vol.toLocaleString('ja-JP') + '株';
}

function formatTurnover(val) {
    if (val == null || val === 0) return '--';
    if (val >= 100000000) return (val / 100000000).toFixed(1) + '億円';
    if (val >= 10000) return Math.round(val / 10000) + '万円';
    return val.toLocaleString('ja-JP') + '円';
}
