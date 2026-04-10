/**
 * 決算インパクト分析 + 上方修正先回り JavaScript
 */

document.addEventListener('DOMContentLoaded', () => {
    const today = new Date().toISOString().slice(0, 10);
    document.getElementById('earningsDate').value = today;

    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            btn.classList.add('active');
            document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
        });
    });

    document.getElementById('sRankOnly').addEventListener('change', applyFilter);

    // Slider value display
    const s2q = document.getElementById('revProgress2q');
    const s3q = document.getElementById('revProgress3q');
    if (s2q) s2q.addEventListener('input', () => {
        document.getElementById('revProgress2qVal').textContent = s2q.value + '%';
    });
    if (s3q) s3q.addEventListener('input', () => {
        document.getElementById('revProgress3qVal').textContent = s3q.value + '%';
    });
});

/* ── Utilities ── */

function escHtml(s) {
    if (!s) return '';
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
}

function fmtMarketCap(v) {
    if (!v) return '-';
    if (v >= 1e12) return (v / 1e12).toFixed(1) + '兆';
    if (v >= 1e8) return (v / 1e8).toFixed(0) + '億';
    if (v >= 1e4) return (v / 1e4).toFixed(0) + '万';
    return v.toLocaleString();
}

function fmtPct(v) {
    if (v == null) return '<span class="na">比較不可</span>';
    const cls = v >= 0 ? 'positive' : 'negative';
    const sign = v >= 0 ? '+' : '';
    return `<span class="${cls}">${sign}${v.toFixed(1)}%</span>`;
}

/* ── 決算インパクト分析 ── */

let allStocks = [];

async function loadEarningsImpact() {
    const date = document.getElementById('earningsDate').value;
    if (!date) return;

    const overlay = document.getElementById('loadingOverlay');
    const empty = document.getElementById('earningsEmpty');
    const wrap = document.getElementById('tableWrap');
    const summary = document.getElementById('earningsSummary');

    overlay.style.display = 'flex';
    empty.style.display = 'none';
    wrap.style.display = 'none';
    summary.style.display = 'none';

    try {
        const res = await fetch(`/api/earnings/impact?date=${date}`);
        const data = await res.json();

        overlay.style.display = 'none';

        if (!data.success) {
            empty.textContent = 'エラー: ' + (data.error || '不明');
            empty.style.display = 'block';
            return;
        }

        allStocks = data.stocks || [];

        if (allStocks.length === 0) {
            empty.textContent = `${date} に決算発表はありませんでした。`;
            empty.style.display = 'block';
            return;
        }

        document.getElementById('summaryDate').textContent = `${data.date} 発表`;
        document.getElementById('summaryTotal').textContent = `全 ${data.total} 銘柄`;
        const c = data.counts || {};
        document.getElementById('countS').textContent = `S級: ${c.S || 0}`;
        document.getElementById('countA').textContent = `A級: ${c.A || 0}`;
        document.getElementById('countB').textContent = `B級: ${c.B || 0}`;
        document.getElementById('countC').textContent = `C級: ${c.C || 0}`;
        summary.style.display = 'flex';

        applyFilter();
    } catch (e) {
        overlay.style.display = 'none';
        empty.textContent = '通信エラー: ' + e.message;
        empty.style.display = 'block';
    }
}

function applyFilter() {
    const sOnly = document.getElementById('sRankOnly').checked;
    const stocks = sOnly ? allStocks.filter(s => s.rank === 'S') : allStocks;
    renderTable(stocks);
}

function renderTable(stocks) {
    const wrap = document.getElementById('tableWrap');
    const empty = document.getElementById('earningsEmpty');
    const tbody = document.getElementById('earningsBody');

    if (stocks.length === 0) {
        wrap.style.display = 'none';
        empty.textContent = '条件に合致する銘柄はありません。';
        empty.style.display = 'block';
        return;
    }

    empty.style.display = 'none';
    wrap.style.display = 'block';

    tbody.innerHTML = stocks.map(s => {
        const rowCls = s.rank === 'S' ? 'row-s' : s.rank === 'A' ? 'row-a' : '';
        const rankCls = `rank-cell rank-${s.rank.toLowerCase()}`;
        return `<tr class="${rowCls}">
            <td class="code-cell">${escHtml(s.code)}</td>
            <td class="name-cell">${escHtml(s.name)}</td>
            <td class="${rankCls}">${s.rank}級</td>
            <td class="num-cell">${fmtPct(s.sales_yoy)}</td>
            <td class="num-cell">${fmtPct(s.op_yoy)}</td>
            <td class="num-cell">${s.progress != null ? s.progress.toFixed(1) + '%' : '-'}</td>
            <td class="num-cell">${fmtMarketCap(s.market_cap)}</td>
            <td class="q-cell">${escHtml(s.q_type)}</td>
        </tr>`;
    }).join('');
}

/* ── 上方修正先回りスクリーニング ── */

async function loadRevisionCandidates() {
    const loading = document.getElementById('revLoading');
    const empty = document.getElementById('revEmpty');
    const wrap = document.getElementById('revTableWrap');
    const summary = document.getElementById('revSummary');

    loading.style.display = 'flex';
    empty.style.display = 'none';
    wrap.style.display = 'none';
    summary.style.display = 'none';

    const p2q = document.getElementById('revProgress2q').value;
    const p3q = document.getElementById('revProgress3q').value;
    const minCap = document.getElementById('revMinCap').value;
    const maxCap = document.getElementById('revMaxCap').value;
    const lookback = document.getElementById('revLookback').value;

    const params = new URLSearchParams({
        min_progress_2q: p2q,
        min_progress_3q: p3q,
        min_cap: minCap,
        max_cap: maxCap,
        lookback: lookback,
    });

    try {
        const res = await fetch(`/api/earnings/revision-candidates?${params}`);
        const data = await res.json();

        loading.style.display = 'none';

        if (!data.success) {
            empty.textContent = 'エラー: ' + (data.error || '不明');
            empty.style.display = 'block';
            return;
        }

        const stocks = data.stocks || [];

        if (stocks.length === 0) {
            empty.textContent = '条件に合致する銘柄はありませんでした。条件を緩和してお試しください。';
            empty.style.display = 'block';
            return;
        }

        document.getElementById('revTotal').textContent = `${stocks.length} 銘柄ヒット`;
        summary.style.display = 'flex';

        renderRevisionTable(stocks);
    } catch (e) {
        loading.style.display = 'none';
        empty.textContent = '通信エラー: ' + e.message;
        empty.style.display = 'block';
    }
}

function renderRevisionTable(stocks) {
    const wrap = document.getElementById('revTableWrap');
    const tbody = document.getElementById('revBody');

    wrap.style.display = 'block';

    tbody.innerHTML = stocks.map(s => {
        const progressCls = s.progress >= 90 ? 'progress-hot' : s.progress >= 75 ? 'progress-warm' : '';
        const yahooUrl = `https://finance.yahoo.co.jp/quote/${escHtml(s.code)}.T`;
        const kabutanUrl = `https://kabutan.jp/stock/?code=${escHtml(s.code)}`;
        return `<tr class="${progressCls}">
            <td class="code-cell">${escHtml(s.code)}</td>
            <td class="name-cell">${escHtml(s.name)}</td>
            <td class="q-cell">${escHtml(s.q_type)}</td>
            <td class="num-cell progress-cell">${s.progress.toFixed(1)}%</td>
            <td class="num-cell">${fmtPct(s.sales_yoy)}</td>
            <td class="num-cell">${fmtPct(s.op_yoy)}</td>
            <td class="num-cell">${s.market_cap_oku != null ? s.market_cap_oku.toLocaleString() : '-'}</td>
            <td class="num-cell">${s.ma25_dev != null ? fmtPct(s.ma25_dev) : '-'}</td>
            <td class="link-cell">
                <a href="${yahooUrl}" target="_blank" rel="noopener" class="ext-link" title="Yahoo!ファイナンス">Y!</a>
                <a href="${kabutanUrl}" target="_blank" rel="noopener" class="ext-link kabutan" title="株探">株探</a>
            </td>
        </tr>`;
    }).join('');
}
