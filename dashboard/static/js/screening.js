/**
 * 銘柄スクリーニング JavaScript
 */

// ブレイクアウトスクリーナーの現在のフィルターパラメータ
let currentBreakoutParams = {
    vol_ratio_min:    1.5,
    price_5d_chg_min: 0.0,
    turnover_min:     50_000_000,
    market:           '',
    top_n:            20,   // 上位何銘柄を選ぶか（少ないほど高シグナル）
};

// 初期化
document.addEventListener('DOMContentLoaded', () => {
    loadSectors();
    loadTopPicks();
    loadOptimizedParams();  // まずDBから最良パラメータを取得してからブレイクアウトをロード
    loadAutoOptHistory();   // 自動最適化の改善履歴グラフを読み込む
});

/**
 * 起動時にDBから最良パラメータを取得して自動適用
 */
async function loadOptimizedParams() {
    try {
        const res  = await fetch('/api/screening/best_params');
        const data = await res.json();

        if (data.success && data.best_params) {
            const p = data.best_params;
            currentBreakoutParams = {
                vol_ratio_min:    p.vol_ratio_min    ?? 1.5,
                price_5d_chg_min: p.price_5d_chg_min ?? 0.0,
                turnover_min:     p.turnover_min      ?? 50_000_000,
                market:           p.market            ?? '',
                top_n:            p.top_n             ?? 20,
            };
            showAutoOptimizedBadge(data);
        }
    } catch (e) {
        // エラー時はデフォルトパラメータで継続
    }
    loadBreakoutStocks();
}

/**
 * 🤖 AI最適化済みバッジを表示
 */
function showAutoOptimizedBadge(data) {
    const label = document.getElementById('appliedParamsLabel');
    if (!label) return;
    const p   = data.best_params;
    const wr  = data.win_rate_20d  != null ? `勝率${data.win_rate_20d}%` : '';
    const ret = data.avg_return_20d != null ? `平均+${data.avg_return_20d}%` : '';
    const dt  = data.created_at ? data.created_at.slice(0, 10) : '';
    const tn = p.top_n ? ` 上位${p.top_n}銘柄` : '';
    label.innerHTML = `🤖 AI自動最適化済み（${dt}）${wr} ${ret} ／ 出来高比×${p.vol_ratio_min} 5日変化>${p.price_5d_chg_min}% 売買代金>${(p.turnover_min/1e8).toFixed(0)}億円${p.market ? ' ' + p.market : ''}${tn}`;
    label.style.display = 'block';
    label.classList.add('auto-optimized');
}

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

/* ============================================================
   出来高急増×上昇トレンド
   ============================================================ */

async function loadBreakoutStocks() {
    const grid         = document.getElementById('breakoutGrid');
    const loading      = document.getElementById('breakoutLoading');
    const errEl        = document.getElementById('breakoutError');
    const errMsg       = document.getElementById('breakoutErrorMsg');
    const dateEl       = document.getElementById('breakoutDateBadge');
    const btn          = document.getElementById('breakoutRefreshBtn');
    const targetDateEl = document.getElementById('breakoutTargetDate');

    loading.style.display = 'flex';
    grid.style.display    = 'none';
    errEl.style.display   = 'none';
    const btStats = document.getElementById('backtestStats');
    if (btStats) btStats.style.display = 'none';
    if (btn) btn.disabled = true;

    try {
        const targetDate = targetDateEl ? targetDateEl.value : '';
        const tn = currentBreakoutParams.top_n ?? 20;
        let url = `/api/screening/volume_breakout?days=20&n=${tn}`;
        url += `&vol_ratio_min=${currentBreakoutParams.vol_ratio_min}`;
        url += `&price_5d_chg_min=${currentBreakoutParams.price_5d_chg_min}`;
        url += `&turnover_min=${currentBreakoutParams.turnover_min}`;
        if (currentBreakoutParams.market) url += `&market=${encodeURIComponent(currentBreakoutParams.market)}`;
        if (targetDate) url += `&date=${encodeURIComponent(targetDate)}`;

        const res  = await fetch(url);
        const data = await res.json();

        if (data.success && data.stocks && data.stocks.length > 0) {
            const label = targetDate
                ? `📅 ${targetDate} 基準`
                : (data.date ? `📅 ${data.date} 終値ベース` : '');
            dateEl.textContent = label;
            renderWinStats(data.win_stats);
            renderBreakoutCards(data.stocks);
            grid.style.display = 'grid';
        } else {
            errMsg.textContent = data.error || 'データが取得できませんでした';
            errEl.style.display = 'block';
        }
    } catch (e) {
        errMsg.textContent = '通信エラー: ' + e.message;
        errEl.style.display = 'block';
    } finally {
        loading.style.display = 'none';
        if (btn) btn.disabled = false;
    }
}

/**
 * バックテスト勝率サマリーを描画
 */
function renderWinStats(ws) {
    const el = document.getElementById('backtestStats');
    if (!el) return;

    if (!ws || Object.keys(ws).length === 0) {
        el.style.display = 'none';
        return;
    }

    const fmtCard = (period, label) => {
        const rate = ws[`win_rate_${period}`];
        const avg  = ws[`avg_return_${period}`];
        const cnt  = ws[`count_${period}`];
        if (rate == null) return '';
        const cls   = rate >= 60 ? 'good' : rate >= 50 ? 'neutral' : 'poor';
        const avgSgn = avg > 0 ? '+' : '';
        return `
            <div class="bt-stat-card ${cls}">
                <div class="bt-stat-label">${label}後 勝率</div>
                <div class="bt-stat-value">${rate}%</div>
                <div class="bt-stat-sub">平均 ${avgSgn}${avg}%（${cnt}件）</div>
            </div>`;
    };

    el.innerHTML = `
        <div class="backtest-title">📊 バックテスト</div>
        <div class="bt-stat-cards">
            ${fmtCard('5d',  '5日')}
            ${fmtCard('10d', '10日')}
            ${fmtCard('20d', '20日')}
        </div>`;
    el.style.display = 'flex';
}

function clearDateAndReload() {
    const el = document.getElementById('breakoutTargetDate');
    if (el) el.value = '';
    currentBreakoutParams = { vol_ratio_min: 1.5, price_5d_chg_min: 0.0, turnover_min: 50_000_000, market: '' };
    const lbl = document.getElementById('appliedParamsLabel');
    if (lbl) lbl.style.display = 'none';
    loadBreakoutStocks();
}

/* ============================================================
   自動最適化
   ============================================================ */

async function runAutoImprove() {
    const btn     = document.getElementById('autoImproveBtn');
    const panel   = document.getElementById('autoImprovePanel');
    const loading = document.getElementById('autoImproveLoading');
    const result  = document.getElementById('autoImproveResult');
    const msgEl   = document.getElementById('autoImproveMsg');

    const lookback    = parseInt(document.getElementById('lookbackSelect')?.value || '52');
    const step        = lookback >= 52 ? 4 : 2;
    const periodLabel = {12:'3ヶ月', 26:'6ヶ月', 52:'1年', 104:'2年', 156:'3年'}[lookback] || `${lookback}週`;

    btn.disabled = true;
    panel.style.display = 'block';
    loading.style.display = 'flex';
    result.innerHTML = '';
    if (msgEl) msgEl.textContent =
        `現在のベスト条件を起点に過去${periodLabel}（${step === 4 ? '月次' : '隔週'}）で探索中...`;

    try {
        const res  = await fetch('/api/screening/run_auto_optimize', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ lookback, n: 5000 }),
        });
        const data = await res.json();

        if (!data.success) {
            result.innerHTML = `<div class="optimize-error">エラー: ${escHtml(data.error || '不明')}</div>`;
            return;
        }

        const improved = data.improved;
        const arrow    = improved ? '⬆️' : '➡️';
        const clr      = improved ? '#4ade80' : '#a0aec0';
        const msg      = improved
            ? `改善！ 勝率 ${data.prev_win_rate}% → <strong style="color:#4ade80">${data.new_win_rate}%</strong>（スコア ${data.prev_score?.toFixed(1)} → ${data.new_score?.toFixed(1)}）`
            : `変化なし（現状維持）　勝率 ${data.prev_win_rate}%　スコア ${data.prev_score?.toFixed(1)}`;

        result.innerHTML = `
            <div style="padding:10px 16px;font-size:13px;color:${clr};">
                ${arrow} ${msg}　（所要時間: ${data.total_time}秒）
            </div>`;

        if (improved) {
            await loadAutoOptHistory();
            await loadOptimizedParams();
        }
    } catch (e) {
        result.innerHTML = `<div class="optimize-error">通信エラー: ${escHtml(e.message)}</div>`;
    } finally {
        loading.style.display = 'none';
        btn.disabled = false;
    }
}

async function loadAutoOptHistory() {
    try {
        const res  = await fetch('/api/screening/optimization_history');
        const data = await res.json();
        if (!data.success || !data.history?.length) return;

        const section = document.getElementById('autoOptHistorySection');
        const countEl = document.getElementById('autoOptHistoryCount');
        section.style.display = 'block';

        const hist     = [...data.history].reverse();   // 古い順に
        const improved = hist.filter(h => h.improved);
        countEl.textContent = `実行${hist.length}回 / 改善${improved.length}回`;

        // Canvas スパークライン
        const canvas = document.getElementById('autoOptHistoryChart');
        const ctx    = canvas.getContext('2d');
        const dpr    = window.devicePixelRatio || 1;
        const W      = canvas.parentElement.clientWidth || 600;
        const H      = 60;
        canvas.width  = W * dpr;
        canvas.height = H * dpr;
        canvas.style.width  = W + 'px';
        canvas.style.height = H + 'px';
        ctx.scale(dpr, dpr);

        const scores   = hist.map(h => h.new_score ?? h.prev_score ?? 0);
        const winRates = hist.map(h => h.new_win_rate ?? 0);
        const maxScore = Math.max(...scores, 1);
        const minScore = Math.min(...scores, 0);
        const range    = maxScore - minScore || 1;
        const pad      = 8;
        const xStep    = (W - pad * 2) / Math.max(scores.length - 1, 1);

        ctx.clearRect(0, 0, W, H);

        // ライン（スコア推移）
        ctx.beginPath();
        ctx.strokeStyle = '#7c3aed';
        ctx.lineWidth   = 2;
        scores.forEach((s, i) => {
            const x = pad + i * xStep;
            const y = H - pad - ((s - minScore) / range) * (H - pad * 2);
            i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        });
        ctx.stroke();

        // 点（改善=緑、変化なし=グレー）
        hist.forEach((h, i) => {
            const s = scores[i];
            const x = pad + i * xStep;
            const y = H - pad - ((s - minScore) / range) * (H - pad * 2);
            ctx.beginPath();
            ctx.arc(x, y, 3, 0, Math.PI * 2);
            ctx.fillStyle = h.improved ? '#4ade80' : '#4a5568';
            ctx.fill();
        });

        // 最新値ラベル
        if (scores.length > 0) {
            const lastScore = scores[scores.length - 1];
            const lastWr    = winRates[winRates.length - 1];
            const lx        = pad + (scores.length - 1) * xStep;
            const ly        = H - pad - ((lastScore - minScore) / range) * (H - pad * 2);
            ctx.fillStyle   = '#e2e8f0';
            ctx.font        = '10px Inter, sans-serif';
            ctx.fillText(`勝率${lastWr}%`, lx - 28, Math.max(12, ly - 6));
        }
    } catch (_) {
        // 履歴グラフは非クリティカルなので無視
    }
}

async function runHistoryValidation() {
    const params = currentBreakoutParams;
    if (!params || !params.vol_ratio_min) {
        alert('先に条件を適用してください（🤖 自動最適化 → 適用）');
        return;
    }

    const btn     = document.getElementById('validateHistoryBtn');
    const panel   = document.getElementById('historyValidatePanel');
    const loading = document.getElementById('historyValidateLoading');
    const results = document.getElementById('historyValidateResults');
    const labels  = ['3ヶ月前', '6ヶ月前', '1年前', '2年前', '3年前'];

    btn.disabled = true;
    panel.style.display = 'block';
    loading.style.display = 'flex';
    results.innerHTML = '';

    try {
        // ① バックグラウンドジョブを開始
        const startRes  = await fetch('/api/screening/validate_history', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ params }),
        });
        const startData = await startRes.json();
        if (!startData.success) throw new Error(startData.error || '開始失敗');

        const jobId = startData.job_id;

        // ② ポーリングで進捗表示（最大15分タイムアウト）
        const loadingSpan = document.querySelector('#historyValidateLoading span');
        let done = false;
        const deadline = Date.now() + 15 * 60 * 1000;

        while (!done) {
            await new Promise(r => setTimeout(r, 3000));

            if (Date.now() > deadline) {
                results.innerHTML = `<div class="optimize-error">タイムアウト（15分）。もう一度お試しください。</div>`;
                break;
            }

            const pollRes  = await fetch(`/api/screening/validate_history_poll/${jobId}`);
            const pollData = await pollRes.json();

            // サーバーリロードでjobが消えた場合
            if (!pollData.success && !pollData.status) {
                results.innerHTML = `<div class="optimize-error" style="color:#facc15">
                    サーバーが再起動しました。もう一度ボタンを押してください。
                </div>`;
                done = true;
                break;
            }

            // 進捗メッセージ更新
            const progress = pollData.progress || [];
            if (loadingSpan && progress.length > 0) {
                loadingSpan.textContent = `(${progress.length}/5) ${progress[progress.length - 1]}`;
            }

            if (pollData.status === 'done' || pollData.status === 'error') {
                done = true;
                if (pollData.result) {
                    renderHistoryValidation(pollData.result);
                } else {
                    results.innerHTML = `<div class="optimize-error">エラー: 結果なし</div>`;
                }
            }
        }
    } catch (e) {
        results.innerHTML = `<div class="optimize-error">通信エラー: ${escHtml(e.message)}</div>`;
    } finally {
        loading.style.display = 'none';
        btn.disabled = false;
    }
}

function renderHistoryValidation(data) {
    const el = document.getElementById('historyValidateResults');
    if (!data.success) {
        el.innerHTML = `<div class="optimize-error">エラー: ${escHtml(data.error || '不明')}</div>`;
        return;
    }

    const labels = ['3ヶ月前', '6ヶ月前', '1年前', '2年前', '3年前'];
    const p      = data.params;
    const pLabel = `vol≥${p.vol_ratio_min}× ｜ 5日≥${p.price_5d_chg_min}% ｜ 代金≥${fmtTurnoverLabel(p.turnover_min || p.min_turnover || 0)} ｜ ${p.market || '全市場'} ｜ 上位${p.top_n}銘柄`;

    let rows = '';
    data.results.forEach((r, i) => {
        const label = labels[i] || r.date;
        if (r.error) {
            rows += `<tr>
                <td>${label}</td><td>${r.date}</td>
                <td colspan="5" style="color:#888;font-size:11px;">${escHtml(r.error)}</td>
            </tr>`;
            return;
        }
        const wr   = r.win_rate_20d;
        const ar   = r.avg_return_20d;
        const noStocks = r.n_stocks === 0;
        const noFwd    = r.no_fwd_data;

        const wrCl = wr === null ? '' : wr >= 80 ? 'style="color:#4ade80;font-weight:700"'
                                      : wr >= 60 ? 'style="color:#facc15"'
                                      : 'style="color:#f87171"';
        const arCl = ar === null ? '' : ar >= 0 ? 'style="color:#4ade80"' : 'style="color:#f87171"';

        const wrTxt = noStocks ? '<span style="color:#888">該当なし</span>'
                    : noFwd   ? '<span style="color:#888">20日未経過</span>'
                    : wr !== null ? `${wr}%` : '–';
        const arTxt = noStocks || noFwd ? '–'
                    : ar !== null ? `${ar > 0 ? '+' : ''}${ar}%` : '–';
        const wr5txt  = r.win_rate_5d  !== null ? r.win_rate_5d  + '%' : '–';
        const wr10txt = r.win_rate_10d !== null ? r.win_rate_10d + '%' : '–';

        rows += `<tr>
            <td style="font-weight:600">${label}</td>
            <td style="font-size:11px;color:#888">${r.actual_date || r.date}</td>
            <td>${r.n_stocks}銘柄</td>
            <td ${wrCl}>${wrTxt}</td>
            <td ${arCl}>${arTxt}</td>
            <td style="font-size:11px;color:#888">${wr5txt} / ${wr10txt} / ${noStocks || noFwd ? '–' : (wr !== null ? wr + '%' : '–')}</td>
        </tr>`;
    });

    el.innerHTML = `
        <div style="padding:12px 16px 4px;font-size:12px;color:#a0aec0;">
            検証条件: ${escHtml(pLabel)} &nbsp;（所要時間: ${data.total_time}秒）
        </div>
        <table class="optimize-table" style="width:100%">
            <thead><tr>
                <th>時点</th><th>実際の日付</th><th>銘柄数</th>
                <th>20日勝率</th><th>20日平均</th><th>5日/10日/20日 勝率</th>
            </tr></thead>
            <tbody>${rows}</tbody>
        </table>`;
}

async function runOptimization() {
    const btn     = document.getElementById('optimizeBtn');
    const panel   = document.getElementById('optimizePanel');
    const loading = document.getElementById('optimizeLoading');
    const results = document.getElementById('optimizeResults');
    const msgEl   = document.getElementById('optimizeLoadingMsg');

    const lookback    = parseInt(document.getElementById('lookbackSelect')?.value || '52');
    const step        = lookback >= 52 ? 4 : 2;   // 1年以上は月次(4週)刻み
    const base        = window._optimizeBestParams || null;   // 前回最良条件（近傍探索に使用）
    const periodLabel = {12:'3ヶ月', 26:'6ヶ月', 52:'1年', 104:'2年', 156:'3年'}[lookback] || `${lookback}週`;
    const modeLabel   = base ? '現在の最良条件を起点に近傍探索+全体探索' : '全体ランダム探索';

    btn.disabled = true;
    panel.style.display = 'block';
    loading.style.display = 'flex';
    results.innerHTML = '';
    if (msgEl) msgEl.textContent =
        `5,000条件 × 過去${periodLabel}（${step === 4 ? '月次' : '隔週'}）で最適化中... ${modeLabel}`;

    try {
        const res  = await fetch('/api/screening/optimize', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ n: 5000, lookback, step, base_params: base }),
        });
        const data = await res.json();
        renderOptimizeResults(data);
    } catch (e) {
        results.innerHTML = `<div class="optimize-error">通信エラー: ${escHtml(e.message)}</div>`;
    } finally {
        loading.style.display = 'none';
        btn.disabled = false;
    }
}

function fmtTurnoverLabel(val) {
    if (val >= 1_000_000_000) return (val / 100_000_000).toFixed(0) + '億円';
    if (val >= 100_000_000)   return (val / 100_000_000).toFixed(1) + '億円';
    if (val >= 10_000_000)    return (val / 10_000_000).toFixed(0) + '000万円';
    return (val / 10_000).toFixed(0) + '万円';
}

function fmtParamsSummary(c) {
    const mkt = c.market ? ` ${c.market}` : '';
    const tn  = c.top_n  ? ` ｜ 上位${c.top_n}銘柄` : '';
    return `週比≥${c.vol_ratio_min}× ｜ 5日≥${c.price_5d_chg_min}% ｜ 代金≥${fmtTurnoverLabel(c.min_turnover)}${mkt}${tn}`;
}

function renderOptimizeResults(data) {
    const el = document.getElementById('optimizeResults');
    if (!el) return;

    if (!data.success) {
        el.innerHTML = `<div class="optimize-error">⚠️ ${escHtml(data.error || '最適化に失敗しました')}</div>`;
        return;
    }

    // 後で applyOptimizeParams から参照できるよう保持
    window._lastOptimizeData = data;

    const combos = data.combinations || [];
    const best   = data.best_20d;

    let html = `<div class="optimize-summary">
        ✅ ${data.test_dates.length}日間 × ${data.total_combinations}条件テスト完了
        <span class="optimize-time">${data.total_time}s</span>
        <span style="font-size:11px;color:#64748b;font-weight:400;">（${data.test_dates[0] || ''}〜${data.test_dates[data.test_dates.length-1] || ''}）</span>
    </div>`;

    if (best) {
        // window._bestParams に格納してボタン onclick から参照
        window._optimizeBestParams = best;
        html += `<div class="optimize-best">
            <span class="optimize-best-label">🏆 推薦条件</span>
            <span class="optimize-best-params">${escHtml(fmtParamsSummary(best))}</span>
            <span style="font-size:11px;color:#64748b;">20日勝率 ${best.win_rate_20d != null ? best.win_rate_20d + '%' : '--'} / 平均 ${best.avg_return_20d != null ? (best.avg_return_20d > 0 ? '+' : '') + best.avg_return_20d + '%' : '--'}</span>
            <button class="optimize-apply-best-btn" onclick="applyOptimizeParams(window._optimizeBestParams)">この条件を適用</button>
        </div>`;
    }

    html += `<div class="optimize-table-wrap"><table class="optimize-table">
        <thead><tr>
            <th>#</th>
            <th>条件</th>
            <th>銘柄数</th>
            <th>5日勝率</th>
            <th>10日勝率</th>
            <th>20日勝率</th>
            <th>20日平均</th>
            <th></th>
        </tr></thead>
        <tbody>`;

    combos.slice(0, 15).forEach((c, i) => {
        const wr20cls = (c.win_rate_20d || 0) >= 60 ? 'opt-wr-good'
                      : (c.win_rate_20d || 0) >= 50 ? 'opt-wr-mid' : 'opt-wr-poor';
        const ar20 = c.avg_return_20d != null
            ? `${c.avg_return_20d > 0 ? '+' : ''}${c.avg_return_20d}%` : '--';
        const rowCls = i === 0 ? ' class="opt-best-row"' : '';
        const paramsSafe = JSON.stringify(c).replace(/'/g, "\\'");
        html += `<tr${rowCls}>
            <td>${i + 1}</td>
            <td class="opt-params">${escHtml(fmtParamsSummary(c))}</td>
            <td>${c.avg_picks}</td>
            <td>${c.win_rate_5d  != null ? c.win_rate_5d  + '%' : '--'}</td>
            <td>${c.win_rate_10d != null ? c.win_rate_10d + '%' : '--'}</td>
            <td class="${wr20cls}">${c.win_rate_20d != null ? c.win_rate_20d + '%' : '--'}</td>
            <td>${ar20}</td>
            <td><button class="opt-apply-btn" onclick='applyOptimizeParams(${paramsSafe})'>適用</button></td>
        </tr>`;
    });

    html += '</tbody></table></div>';
    el.innerHTML = html;
}

function applyOptimizeParams(params) {
    currentBreakoutParams = {
        vol_ratio_min:    params.vol_ratio_min,
        price_5d_chg_min: params.price_5d_chg_min,
        turnover_min:     params.min_turnover,
        market:           params.market || '',
        top_n:            params.top_n  ?? 20,
    };

    // DBに保存（次回ページを開いたとき自動ロード）
    const lastOptData = window._lastOptimizeData || {};
    fetch('/api/screening/save_best_params', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            vol_ratio_min:    params.vol_ratio_min,
            price_5d_chg_min: params.price_5d_chg_min,
            turnover_min:     params.min_turnover,
            market:           params.market || '',
            top_n:            params.top_n ?? 20,
            win_rate_20d:     params.win_rate_20d,
            avg_return_20d:   params.avg_return_20d,
            win_rate_10d:     params.win_rate_10d,
            avg_return_10d:   params.avg_return_10d,
            total_combinations: lastOptData.total_combinations,
            center_date:      lastOptData.test_dates ? lastOptData.test_dates[0] : '',
            test_dates:       lastOptData.test_dates || [],
        }),
    });

    // 適用中ラベル更新（緑バッジ）
    const lbl = document.getElementById('appliedParamsLabel');
    if (lbl) {
        const wr  = params.win_rate_20d  != null ? ` 勝率${params.win_rate_20d}%` : '';
        const ret = params.avg_return_20d != null ? ` 平均+${params.avg_return_20d}%` : '';
        const tn  = params.top_n ? ` 上位${params.top_n}銘柄` : '';
        const today = new Date().toISOString().slice(0, 10);
        lbl.innerHTML = `🤖 AI最適化済み（${today}）${wr}${ret} ／ ${fmtParamsSummary(params)}${tn}`;
        lbl.style.display = 'block';
        lbl.classList.add('auto-optimized');
    }

    // 最適化パネルを閉じる
    const panel = document.getElementById('optimizePanel');
    if (panel) panel.style.display = 'none';

    // 新しい条件でリロード
    loadBreakoutStocks();

    // ブレイクアウトセクションへスクロール
    setTimeout(() => {
        document.getElementById('breakoutSection')
            .scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 200);
}

function renderBreakoutCards(stocks) {
    const grid = document.getElementById('breakoutGrid');
    grid.innerHTML = '';

    const tagMap = {
        '週次×4↑':  'btag-vol5',  '週次×3↑':  'btag-vol3',
        '週次×2↑':  'btag-vol2',  '週次増加':  'btag-volinc',
        '急騰':      'btag-surge', '上昇':      'btag-rising',
        '堅調':      'btag-steady','5日+20%↑':  'btag-p20',
        '5日+10%↑': 'btag-p10',  '超大型':    'btag-mega',
        '大商い':    'btag-large', 'プライム':  'btag-prime',
        'グロース':  'btag-growth',
    };

    stocks.forEach((s, idx) => {
        const rank   = idx + 1;
        const isTop1 = rank === 1;
        const isTop3 = rank <= 3;
        const cr     = s.change_rate;
        const crSign = cr > 0 ? '+' : '';
        const crCls  = cr > 0 ? 'up' : cr < 0 ? 'down' : '';

        const mktCls = s.market === 'プライム'   ? 'market-prime'
                     : s.market === 'スタンダード' ? 'market-standard'
                     : s.market === 'グロース'    ? 'market-growth' : '';

        const tagsHtml = (s.tags || []).map(t =>
            `<span class="bo-tag ${tagMap[t] || 'btag-def'}">${escHtml(t)}</span>`
        ).join('');

        // 週次出来高比率バー（最大4倍 → 100%）
        const volPct = Math.min((s.vol_ratio_5d / 4) * 100, 100).toFixed(0);

        // フォワードリターンバッジ
        const fmtFwd = (v, label) => {
            if (v == null) return `<span class="fwd-badge fwd-na">${label}: --</span>`;
            const cls  = v > 0 ? 'fwd-win' : 'fwd-lose';
            const sign = v > 0 ? '+' : '';
            return `<span class="fwd-badge ${cls}">${label}: ${sign}${v.toFixed(1)}%</span>`;
        };
        const hasFwd = s.fwd_5d != null || s.fwd_10d != null || s.fwd_20d != null;
        const fwdHtml = hasFwd
            ? `<div class="bo-fwd-returns">
                ${fmtFwd(s.fwd_5d,  '5日後')}
                ${fmtFwd(s.fwd_10d, '10日後')}
                ${fmtFwd(s.fwd_20d, '20日後')}
               </div>`
            : '';

        // 6ヶ月チャート SVG（シグナル日に縦線）
        const svg = buildChartSVG(
            s.chart_dates  || [],
            s.chart_prices || [],
            s.chart_volumes || [],
            s.signal_idx != null ? s.signal_idx : -1
        );

        const cardCls = isTop1 ? 'breakout-card rank-top1'
                      : isTop3 ? 'breakout-card rank-top3'
                      : 'breakout-card';

        const card = document.createElement('div');
        card.className = cardCls;
        card.innerHTML = `
            <div class="bo-rank">${rank}</div>
            <div class="bo-code-row">
                <a href="https://kabutan.jp/stock/?code=${escHtml(s.code)}"
                   target="_blank" rel="noopener" class="bo-code-link">${escHtml(s.code)}</a>
                <span class="pick-market-badge ${mktCls}" style="font-size:9px;">${escHtml(s.market)}</span>
            </div>
            <div class="bo-name" title="${escHtml(s.name)}">${escHtml(s.name)}</div>
            <div class="bo-price-row">
                <span class="bo-price">¥${formatNumber(s.close)}</span>
                <span class="bo-change ${crCls}">${crSign}${cr.toFixed(2)}%</span>
            </div>
            <div class="bo-vol-row">
                <span class="bo-vol-label">週次比</span>
                <div class="bo-vol-bar-wrap">
                    <div class="bo-vol-bar" style="width:${volPct}%"></div>
                </div>
                <span class="bo-vol-ratio">×${s.vol_ratio_5d.toFixed(1)}</span>
            </div>
            <div class="bo-chart">${svg}</div>
            ${fwdHtml}
            <div class="bo-tags">${tagsHtml}</div>
        `;
        grid.appendChild(card);
    });
}

/**
 * 6ヶ月日足チャート SVG を生成（価格ライン + MA25/75 + 出来高バー + 月ラベル）
 * @param {string[]} dates   - 日付配列 (YYYY-MM-DD、古い順)
 * @param {number[]} prices  - 終値配列 (古い順)
 * @param {number[]} volumes - 出来高配列 (古い順)
 */
/**
 * @param {number} signalIdx  - シグナル日のインデックス（-1 なら表示しない）
 */
function buildChartSVG(dates, prices, volumes, signalIdx = -1) {
    if (!prices || prices.length < 5) {
        return '<div class="bo-chart-nodata">チャートデータなし</div>';
    }

    // ── レイアウト定数 ──
    const W    = 300;   // SVG 全幅
    const PH   = 115;   // 価格エリア高さ
    const VH   = 36;    // 出来高エリア高さ
    const GAP  = 4;     // 価格↔出来高 隙間
    const ML   = 14;    // 月ラベル高さ
    const H    = PH + GAP + VH + GAP + ML;
    const PL   = 4;     // 左パディング
    const PR   = 50;    // 右パディング（価格ラベル用）
    const cW   = W - PL - PR;  // チャート描画幅

    const n     = prices.length;
    const maxP  = Math.max(...prices);
    const minP  = Math.min(...prices);
    const rangeP = maxP - minP || maxP * 0.05 || 1;
    const maxV  = Math.max(...volumes) || 1;

    const xOf  = i => PL + (i / Math.max(n - 1, 1)) * cW;
    const yOfP = p => 2 + (PH - 4) * (1 - (p - minP) / rangeP);

    // ── MA計算 ──
    const ma25 = calcMA(prices, 25);
    const ma75 = calcMA(prices, 75);

    // ── 価格ライン ──
    const pts     = prices.map((p, i) => `${xOf(i).toFixed(1)},${yOfP(p).toFixed(1)}`).join(' ');
    const fillPts = `${PL},${PH - 2} ` + pts + ` ${(PL + cW).toFixed(1)},${PH - 2}`;

    const rising    = prices[n - 1] >= prices[0];
    const lineColor = rising ? '#2563eb' : '#dc2626';
    const fillColor = rising ? '#dbeafe' : '#fee2e2';

    // ── 出来高バー ──
    const vBaseY = PH + GAP + VH;
    const bw     = Math.max((cW / n) * 0.82, 0.8);
    const bars   = volumes.map((v, i) => {
        const bh   = Math.max((v / maxV) * (VH - 1), 0.8);
        const bx   = xOf(i) - bw / 2;
        const by   = vBaseY - bh;
        const fill = i === n - 1 ? '#3b82f6' : '#c7d8ed';
        return `<rect x="${bx.toFixed(1)}" y="${by.toFixed(1)}" width="${bw.toFixed(1)}" height="${bh.toFixed(1)}" fill="${fill}"/>`;
    }).join('');

    // ── 水平グリッド ──
    const grid = [0.25, 0.5, 0.75].map(f => {
        const y = yOfP(minP + rangeP * f).toFixed(1);
        return `<line x1="${PL}" y1="${y}" x2="${(PL + cW).toFixed(1)}" y2="${y}" stroke="#f0f4f8" stroke-width="0.8"/>`;
    }).join('');

    // ── MA ポリライン ──
    const ma25svg = buildMAPolyline(ma25, xOf, yOfP, '#f97316', 0.85);
    const ma75svg = buildMAPolyline(ma75, xOf, yOfP, '#60a5fa', 0.85);

    // ── 価格ラベル（右端） ──
    const labelX    = (PL + cW + 4).toFixed(1);
    const yMaxLabel = Math.max(yOfP(maxP), 8).toFixed(1);
    const yMinLabel = Math.min(yOfP(minP), PH - 4).toFixed(1);

    // ── 最新価格ドット ──
    const lx = xOf(n - 1).toFixed(1);
    const ly = yOfP(prices[n - 1]).toFixed(1);

    // ── MA凡例 ──
    const legendY = (PH + GAP + VH + GAP + ML - 1).toFixed(1);

    // ── 月ラベル ──
    const monthLabels = buildMonthLabels(dates, n, xOf, vBaseY + GAP + 10);

    // ── シグナル日の縦線（過去日付バックテスト用） ──
    let signalLine = '';
    if (signalIdx >= 0 && signalIdx < n) {
        const sx = xOf(signalIdx).toFixed(1);
        signalLine = `
            <line x1="${sx}" y1="2" x2="${sx}" y2="${PH}" stroke="#f59e0b" stroke-width="1.3" stroke-dasharray="3,2" opacity="0.9"/>
            <line x1="${sx}" y1="${PH + GAP}" x2="${sx}" y2="${vBaseY}" stroke="#f59e0b" stroke-width="1.3" stroke-dasharray="3,2" opacity="0.5"/>
            <text x="${sx}" y="${(PH - 2).toFixed(1)}" font-size="6.5" fill="#f59e0b" text-anchor="middle" font-weight="700">▼</text>`;
    }

    return `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" style="display:block;width:100%;height:auto">
        ${grid}
        <polygon points="${fillPts}" fill="${fillColor}" opacity="0.2"/>
        ${bars}
        ${ma75svg}
        ${ma25svg}
        <polyline points="${pts}" fill="none" stroke="${lineColor}" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>
        ${signalLine}
        <circle cx="${lx}" cy="${ly}" r="2.5" fill="${lineColor}"/>
        <text x="${labelX}" y="${yMaxLabel}" font-size="7.5" fill="#64748b" dominant-baseline="middle">${fmtChartPrice(maxP)}</text>
        <text x="${labelX}" y="${yMinLabel}" font-size="7.5" fill="#64748b" dominant-baseline="middle">${fmtChartPrice(minP)}</text>
        <rect x="${PL}" y="${PH + GAP - 0.5}" width="${cW}" height="0.5" fill="#e2e8f0"/>
        ${monthLabels}
        <line x1="${(PL + cW + 2).toFixed(1)}" y1="7" x2="${(PL + cW + 7).toFixed(1)}" y2="7" stroke="#f97316" stroke-width="1.5"/>
        <text x="${(PL + cW + 9).toFixed(1)}" y="7" font-size="6.5" fill="#f97316" dominant-baseline="middle">25</text>
        <line x1="${(PL + cW + 2).toFixed(1)}" y1="16" x2="${(PL + cW + 7).toFixed(1)}" y2="16" stroke="#60a5fa" stroke-width="1.5"/>
        <text x="${(PL + cW + 9).toFixed(1)}" y="16" font-size="6.5" fill="#60a5fa" dominant-baseline="middle">75</text>
    </svg>`;
}

/** 移動平均を計算 */
function calcMA(prices, period) {
    return prices.map((_, i) => {
        if (i < period - 1) return null;
        let sum = 0;
        for (let j = i - period + 1; j <= i; j++) sum += prices[j];
        return sum / period;
    });
}

/** MA用ポリライン SVG（null で分断） */
function buildMAPolyline(ma, xOf, yOfP, color, opacity) {
    const segs = [];
    let pts    = [];
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
        `<polyline points="${p}" fill="none" stroke="${color}" stroke-width="1" opacity="${opacity}" stroke-linejoin="round"/>`
    ).join('');
}

/** 価格ラベルフォーマット */
function fmtChartPrice(p) {
    if (p >= 100000) return (p / 10000).toFixed(0) + '万';
    if (p >= 10000)  return (p / 1000).toFixed(1) + 'k';
    return Number(p).toFixed(0);
}

/** X軸の月ラベル SVG */
function buildMonthLabels(dates, n, xOf, labelY) {
    if (!dates || dates.length !== n) return '';
    let labels  = '';
    let lastYM  = '';
    dates.forEach((d, i) => {
        if (!d) return;
        const ym = d.substring(0, 7);
        if (ym !== lastYM) {
            const x  = xOf(i).toFixed(1);
            const mm = parseInt(d.substring(5, 7), 10);
            const yy = d.substring(2, 4);
            const label = mm === 1 ? `'${yy}年` : `${mm}月`;
            labels += `<text x="${x}" y="${labelY.toFixed ? labelY.toFixed(1) : labelY}" font-size="7.5" fill="#94a3b8" text-anchor="middle">${label}</text>`;
            lastYM = ym;
        }
    });
    return labels;
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
