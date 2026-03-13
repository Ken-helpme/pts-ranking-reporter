// クオンツ分析ページ

const STEPS = ['data', 'features', 'backtest', 'optimize', 'ml', 'regime', 'report'];
const STEP_LABELS = {
    data: 'データ取得', features: '特徴量計算', backtest: 'バックテスト',
    optimize: '最適化', ml: '機械学習', regime: 'レジーム分析', report: 'レポート生成',
};
let running = false;
let currentPollTimer = null;

function log(msg, type = 'info') {
    const el = document.getElementById('logOutput');
    const line = document.createElement('div');
    line.className = `log-line log-${type}`;
    line.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
    el.appendChild(line);
    el.scrollTop = el.scrollHeight;
}

function clearLog() {
    document.getElementById('logOutput').innerHTML = '';
}

function setCardState(step, state, statusText) {
    const card = document.getElementById(`card-${step}`);
    const status = document.getElementById(`status-${step}`);
    card.className = `step-card ${state}`;
    status.className = `step-status ${state}`;
    status.textContent = statusText || '';
}

function setProgress(pct, label) {
    const section = document.getElementById('progressSection');
    section.style.display = '';
    document.getElementById('progressFill').style.width = pct + '%';
    document.getElementById('progressLabel').textContent = label;
}

function disableAll(disabled) {
    running = disabled;
    document.getElementById('btnRunAll').disabled = disabled;
    document.querySelectorAll('.btn-step').forEach(b => b.disabled = disabled);
}

// 単一ステップ実行
async function runStep(step) {
    if (running) return;
    disableAll(true);
    setCardState(step, 'running', '実行中...');
    log(`STEP: ${STEP_LABELS[step]} 開始`, 'step');

    try {
        const fast = document.getElementById('fastMode').checked;
        const resp = await fetch('/api/quant/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ step, fast }),
        });
        const data = await resp.json();

        if (data.success && data.job_id) {
            await pollJob(data.job_id, step);
        } else {
            throw new Error(data.error || 'Unknown error');
        }
    } catch (e) {
        setCardState(step, 'error', 'エラー');
        log(`ERROR: ${e.message}`, 'error');
    }

    disableAll(false);
}

// 全STEP一括実行
async function runFullPipeline() {
    if (running) return;
    disableAll(true);

    STEPS.forEach(s => setCardState(s, '', ''));
    clearLog();
    log('全パイプライン開始', 'step');

    const fast = document.getElementById('fastMode').checked;

    try {
        const resp = await fetch('/api/quant/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ step: 'all', fast }),
        });
        const data = await resp.json();

        if (data.success && data.job_id) {
            await pollJob(data.job_id, 'all');
        } else {
            throw new Error(data.error || 'Unknown error');
        }
    } catch (e) {
        log(`ERROR: ${e.message}`, 'error');
    }

    disableAll(false);
}

// ジョブポーリング
async function pollJob(jobId, step) {
    return new Promise((resolve) => {
        let lastLogLen = 0;
        let lastStep = '';

        const poll = async () => {
            try {
                const resp = await fetch(`/api/quant/status/${jobId}`);
                const data = await resp.json();

                // ログ更新
                if (data.logs && data.logs.length > lastLogLen) {
                    for (let i = lastLogLen; i < data.logs.length; i++) {
                        const entry = data.logs[i];
                        log(entry.msg, entry.type || 'info');
                    }
                    lastLogLen = data.logs.length;
                }

                // ステップ進捗更新
                if (data.current_step && data.current_step !== lastStep) {
                    if (lastStep) setCardState(lastStep, 'done', '完了');
                    setCardState(data.current_step, 'running', '実行中...');
                    lastStep = data.current_step;
                }

                // 進捗バー更新
                if (data.progress !== undefined) {
                    const pct = Math.round(data.progress * 100);
                    setProgress(pct, data.progress_label || `${pct}%`);
                }

                // 完了チェック
                if (data.status === 'done') {
                    if (lastStep) setCardState(lastStep, 'done', '完了');
                    if (step === 'all') {
                        STEPS.forEach(s => setCardState(s, 'done', '完了'));
                    }
                    setProgress(100, '完了');
                    log('パイプライン完了', 'success');

                    if (data.report) {
                        showResults(data.report);
                    }
                    resolve();
                    return;
                }

                if (data.status === 'error') {
                    if (lastStep) setCardState(lastStep, 'error', 'エラー');
                    log(`ERROR: ${data.error || 'Unknown error'}`, 'error');
                    resolve();
                    return;
                }

                currentPollTimer = setTimeout(poll, 3000);
            } catch (e) {
                log(`Polling error: ${e.message}`, 'error');
                currentPollTimer = setTimeout(poll, 5000);
            }
        };

        poll();
    });
}

// 結果表示
function showResults(report) {
    const section = document.getElementById('resultsSection');
    section.style.display = '';

    // 最適条件カード
    const cards = document.getElementById('resultCards');
    cards.innerHTML = '';

    const strategies = [
        { key: 'best_winrate', title: '最も勝率が高い条件', icon: '🎯' },
        { key: 'best_return', title: '最もリターンが高い条件', icon: '📈' },
        { key: 'best_stable', title: '最も安定している条件', icon: '🛡️' },
    ];

    for (const s of strategies) {
        const d = report[s.key];
        if (!d) continue;
        const m = d.metrics;
        const card = document.createElement('div');
        card.className = 'result-card';
        card.innerHTML = `
            <h4>${s.icon} ${s.title}</h4>
            <div class="metric-row"><span class="metric-label">勝率</span><span class="metric-value positive">${(m.win_rate * 100).toFixed(1)}%</span></div>
            <div class="metric-row"><span class="metric-label">平均リターン</span><span class="metric-value ${m.avg_return >= 0 ? 'positive' : 'negative'}">${(m.avg_return * 100).toFixed(2)}%</span></div>
            <div class="metric-row"><span class="metric-label">シャープレシオ</span><span class="metric-value">${m.sharpe_ratio.toFixed(2)}</span></div>
            <div class="metric-row"><span class="metric-label">最大DD</span><span class="metric-value negative">${(m.max_drawdown * 100).toFixed(1)}%</span></div>
            <div class="metric-row"><span class="metric-label">PF</span><span class="metric-value">${m.profit_factor.toFixed(2)}</span></div>
            <div class="metric-row"><span class="metric-label">トレード数</span><span class="metric-value">${m.n_trades.toLocaleString()}</span></div>
            <div class="condition-text">${d.condition_str}</div>
        `;
        cards.appendChild(card);
    }

    // シグナル銘柄
    const signals = report.current_signals || [];
    if (signals.length > 0) {
        const ss = document.getElementById('signalsSection');
        ss.style.display = '';
        const tbody = document.getElementById('signalsBody');
        tbody.innerHTML = signals.map(s => `
            <tr>
                <td><strong>${s.code}</strong></td>
                <td>${s.name}</td>
                <td>${Number(s.close).toLocaleString()}</td>
                <td><strong>${s.vol_ratio}x</strong></td>
                <td>${s.vol_zscore}</td>
                <td>${(s.turnover / 1e8).toFixed(1)}億</td>
                <td>${s.sector}</td>
                <td><span style="font-size:11px;color:#64748b">${s.signal_type}</span></td>
            </tr>
        `).join('');
    }

    // 売買ルール
    if (report.trading_rules) {
        const rs = document.getElementById('rulesSection');
        rs.style.display = '';
        rs.innerHTML = '<h3>売買ルール</h3>';
        for (const [key, rule] of Object.entries(report.trading_rules)) {
            const card = document.createElement('div');
            card.className = 'rule-card';
            card.innerHTML = `
                <h4>${rule.name}</h4>
                <div class="rule-row"><span class="rule-label">エントリー</span><span class="rule-value">${rule.entry}</span></div>
                <div class="rule-row"><span class="rule-label">条件</span><span class="rule-value">${rule.conditions}</span></div>
                <div class="rule-row"><span class="rule-label">決済</span><span class="rule-value">${rule.exit}</span></div>
                <div class="rule-row"><span class="rule-label">期待勝率</span><span class="rule-value">${rule.expected_winrate}</span></div>
                <div class="rule-row"><span class="rule-label">期待リターン</span><span class="rule-value">${rule.expected_return}</span></div>
                <div class="rule-row"><span class="rule-label">リスク管理</span><span class="rule-value">${rule.risk_management}</span></div>
            `;
            rs.appendChild(card);
        }
    }

    // 改善提案
    if (report.suggestions && report.suggestions.length > 0) {
        const ss = document.getElementById('suggestionsSection');
        ss.style.display = '';
        ss.innerHTML = '<h3>改善提案</h3>';
        report.suggestions.forEach((s, i) => {
            const item = document.createElement('div');
            item.className = 'suggestion-item';
            item.textContent = `${i + 1}. ${s}`;
            ss.appendChild(item);
        });
    }

    // チャート画像
    if (report.charts && report.charts.length > 0) {
        const cs = document.getElementById('chartsSection');
        cs.style.display = '';
        const grid = document.getElementById('chartsGrid');
        grid.innerHTML = report.charts.map(c =>
            `<img class="chart-img" src="/api/quant/chart/${c}" alt="${c}">`
        ).join('');
    }
}
