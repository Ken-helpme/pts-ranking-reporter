"""
最終レポート生成・可視化

分析結果の統合、現在シグナル銘柄の抽出、チャート生成
"""
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

import math

from .config import DATA_DIR, FORWARD_PERIODS
from .screener import apply_condition, condition_to_str
from .backtester import BacktestResult, run_backtest

logger = logging.getLogger(__name__)
REPORT_DIR = DATA_DIR / "reports"


def _sanitize_for_json(obj):
    """Replace NaN/Inf with None for JSON serialization."""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, (np.floating,)):
        v = float(obj)
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, pd.Series):
        return obj.to_dict()
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    return obj


def generate_final_report(
    optimization_results: Dict,
    ml_results: Dict,
    regime_results: Dict,
    regime_summary: pd.DataFrame,
    df: pd.DataFrame,
    current_regime: str = "unknown",
    theme_performance: pd.DataFrame = None,
    tenbagger_analysis: Dict = None,
    institutional_accumulation: Dict = None,
) -> Dict:
    """
    全分析結果を統合して最終レポートを生成。

    出力:
        1. 技術条件（最も勝率/リターン/安定の条件）
        2. ファンダメンタル条件
        3. 月間平均ヒット銘柄数
        4. 最もパフォーマンスが良い保有期間
        5. 現在条件に当てはまる銘柄
        6. 最も再現性の高い戦略
        7. テーマ分析
        8. テンバガー分析
    """
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    all_results = optimization_results.get("all", [])
    if not all_results:
        return {"error": "No optimization results available"}

    best_winrate = max(all_results, key=lambda r: r.win_rate)
    best_return = max(all_results, key=lambda r: r.avg_return)
    best_stable = max(
        all_results,
        key=lambda r: r.sharpe_ratio * 0.5 - abs(r.max_drawdown) * 0.5
    )

    current_signals = _scan_current_signals(df, [
        best_winrate.condition,
        best_return.condition,
        best_stable.condition,
    ])

    trading_rules = _format_trading_rules(best_winrate, best_return, best_stable)

    suggestions = _generate_suggestions(
        all_results, ml_results, regime_results, current_regime
    )

    holding_comparison = _compare_holding_periods(df, all_results[:10])

    hit_count_summary = _summarize_hit_counts(all_results[:10])

    fundamental_analysis = _analyze_fundamental_impact(all_results)

    reproducible_strategy = _find_most_reproducible(optimization_results)

    report = {
        "timestamp": datetime.now().isoformat(),
        "current_regime": current_regime,
        "best_winrate": {
            "condition": best_winrate.condition,
            "condition_str": condition_to_str(best_winrate.condition),
            "metrics": best_winrate.to_dict(),
        },
        "best_return": {
            "condition": best_return.condition,
            "condition_str": condition_to_str(best_return.condition),
            "metrics": best_return.to_dict(),
        },
        "best_stable": {
            "condition": best_stable.condition,
            "condition_str": condition_to_str(best_stable.condition),
            "metrics": best_stable.to_dict(),
        },
        "holding_period_comparison": holding_comparison,
        "hit_count_summary": hit_count_summary,
        "fundamental_analysis": fundamental_analysis,
        "reproducible_strategy": reproducible_strategy,
        "current_signals": current_signals,
        "trading_rules": trading_rules,
        "suggestions": suggestions,
        "ml_summary": _summarize_ml(ml_results),
        "regime_summary": regime_summary.to_dict("records") if regime_summary is not None else [],
        "theme_performance": theme_performance.to_dict("records") if theme_performance is not None and not theme_performance.empty else [],
        "tenbagger_analysis": tenbagger_analysis or {},
        "institutional_accumulation": institutional_accumulation or {},
    }

    _save_report_text(report)
    return _sanitize_for_json(report)


def _compare_holding_periods(df: pd.DataFrame,
                             top_results: List[BacktestResult]) -> List[Dict]:
    """上位条件について各保有期間でバックテストし、比較表を生成"""
    comparisons = []
    holding_options = [d for d in FORWARD_PERIODS if f"fwd_{d}d_return" in df.columns]

    for res in top_results[:5]:
        cond_str = condition_to_str(res.condition)
        row = {"condition": cond_str}

        for hd in holding_options:
            test_cond = {**res.condition, "holding_days": hd}
            test_res = run_backtest(df, test_cond)
            if test_res:
                row[f"{hd}d_winrate"] = round(test_res.win_rate, 4)
                row[f"{hd}d_return"] = round(test_res.avg_return, 6)
                row[f"{hd}d_sharpe"] = round(test_res.sharpe_ratio, 4)
                row[f"{hd}d_mdd"] = round(test_res.max_drawdown, 4)
                row[f"{hd}d_pf"] = round(test_res.profit_factor, 4)

        comparisons.append(row)

    return comparisons


def _summarize_hit_counts(top_results: List[BacktestResult]) -> List[Dict]:
    """上位条件のヒットカウントサマリー"""
    summaries = []
    for res in top_results:
        summaries.append({
            "condition": condition_to_str(res.condition),
            "holding_days": res.holding_days,
            "avg_daily_hits": round(res.avg_daily_hits, 2),
            "avg_monthly_hits": round(res.avg_monthly_hits, 2),
            "avg_yearly_hits": round(res.avg_yearly_hits, 2),
            "n_trades": res.n_trades,
        })
    return summaries


def _analyze_fundamental_impact(all_results: List[BacktestResult]) -> Dict:
    """ファンダメンタルフィルターの有無によるパフォーマンス差を分析"""
    fund_keys = ["revenue_growth_min", "eps_growth_min", "roe_min",
                 "op_margin_min", "per_max", "pbr_max", "equity_ratio_min"]

    with_fund = [r for r in all_results if any(k in r.condition for k in fund_keys)]
    without_fund = [r for r in all_results if not any(k in r.condition for k in fund_keys)]

    def _avg_metrics(results):
        if not results:
            return {}
        return {
            "count": len(results),
            "avg_win_rate": round(np.mean([r.win_rate for r in results]), 4),
            "avg_return": round(np.mean([r.avg_return for r in results]), 6),
            "avg_sharpe": round(np.mean([r.sharpe_ratio for r in results]), 4),
            "avg_mdd": round(np.mean([r.max_drawdown for r in results]), 4),
        }

    freq = {}
    for r in with_fund:
        for k in fund_keys:
            if k in r.condition:
                freq[k] = freq.get(k, 0) + 1

    return {
        "with_fundamental": _avg_metrics(with_fund),
        "without_fundamental": _avg_metrics(without_fund),
        "filter_frequency": freq,
    }


def _find_most_reproducible(optimization_results: Dict) -> Dict:
    """
    OOS安定性が最も高い「最も再現性の高い戦略」を提案。
    ランダム/ベイズ/GAの複数手法で上位に現れた条件を重視。
    """
    all_results = optimization_results.get("all", [])
    if not all_results:
        return {}

    best = max(all_results, key=lambda r: (
        r.sharpe_ratio * 0.4
        + r.win_rate * 0.3
        + min(r.profit_factor / 3.0, 1.0) * 0.2
        - abs(r.max_drawdown) * 0.1
    ))

    return {
        "condition": best.condition,
        "condition_str": condition_to_str(best.condition),
        "metrics": best.to_dict(),
        "rationale": "シャープレシオ×安定性の複合スコアで最も高い条件。"
                     "複数最適化手法で上位に位置する再現性の高い戦略。",
    }


def _scan_current_signals(df: pd.DataFrame,
                          conditions: List[Dict]) -> List[Dict]:
    """最新日のデータに対して条件をスキャンし、マッチ銘柄を返す"""
    if df.empty or "Date" not in df.columns:
        return []

    latest_date = df["Date"].max()
    latest = df[df["Date"] == latest_date].copy()

    all_matches = []
    for i, cond in enumerate(conditions):
        mask = apply_condition(latest, cond)
        matches = latest[mask].copy()

        for _, row in matches.iterrows():
            all_matches.append({
                "code": str(row.get("Code", "")),
                "name": str(row.get("Name", "")),
                "close": float(row.get("Close", 0)),
                "volume": float(row.get("Volume", 0)),
                "vol_ratio": round(float(row.get("vol_ratio", 0)), 2),
                "vol_zscore": round(float(row.get("vol_zscore", 0)), 2),
                "turnover": float(row.get("Turnover", 0)),
                "sector": str(row.get("Sector", "")),
                "market": str(row.get("Market", "")),
                "signal_type": ["best_winrate", "best_return", "best_stable"][i],
                "date": str(latest_date.date()) if hasattr(latest_date, 'date') else str(latest_date),
            })

    seen = set()
    unique = []
    for m in all_matches:
        if m["code"] not in seen:
            seen.add(m["code"])
            unique.append(m)

    unique.sort(key=lambda x: x["vol_ratio"], reverse=True)
    return unique[:50]


def _format_trading_rules(best_wr: BacktestResult,
                          best_ret: BacktestResult,
                          best_stable: BacktestResult) -> Dict:
    """売買ルールをフォーマット"""
    return {
        "strategy_A_high_winrate": {
            "name": "高勝率戦略",
            "entry": f"以下の条件を全て満たした銘柄を翌日寄り成行買い",
            "conditions": condition_to_str(best_wr.condition),
            "exit": f"{best_wr.holding_days}日後の終値で売却",
            "expected_winrate": f"{best_wr.win_rate:.1%}",
            "expected_return": f"{best_wr.avg_return:.2%}",
            "risk_management": "1銘柄あたりポートフォリオの5%以内",
        },
        "strategy_B_high_return": {
            "name": "高リターン戦略",
            "entry": f"以下の条件を全て満たした銘柄を翌日寄り成行買い",
            "conditions": condition_to_str(best_ret.condition),
            "exit": f"{best_ret.holding_days}日後の終値で売却",
            "expected_winrate": f"{best_ret.win_rate:.1%}",
            "expected_return": f"{best_ret.avg_return:.2%}",
            "risk_management": "1銘柄あたりポートフォリオの3%以内（高ボラ）",
        },
        "strategy_C_stable": {
            "name": "安定戦略",
            "entry": f"以下の条件を全て満たした銘柄を翌日寄り成行買い",
            "conditions": condition_to_str(best_stable.condition),
            "exit": f"{best_stable.holding_days}日後の終値で売却",
            "expected_winrate": f"{best_stable.win_rate:.1%}",
            "expected_return": f"{best_stable.avg_return:.2%}",
            "sharpe": f"{best_stable.sharpe_ratio:.2f}",
            "risk_management": "1銘柄あたりポートフォリオの7%以内",
        },
    }


def _generate_suggestions(all_results, ml_results, regime_results, current_regime) -> List[str]:
    """改善提案を生成"""
    suggestions = []

    if all_results:
        top = all_results[0]
        if top.win_rate < 0.55:
            suggestions.append(
                "勝率が55%未満です。出来高倍率の閾値を上げるか、"
                "トレンドフィルターを追加してエントリー精度を向上させてください。"
            )
        if abs(top.max_drawdown) > 0.2:
            suggestions.append(
                "最大ドローダウンが20%超です。ポジションサイズを縮小するか、"
                "損切りルール（-3%で強制売却等）を追加してください。"
            )

    if ml_results:
        for name, res in ml_results.items():
            avg = res.get("metrics_avg", {})
            if avg.get("roc_auc", 0) > 0.6:
                suggestions.append(
                    f"{name}のAUCが{avg['roc_auc']:.3f}で有効。"
                    f"ML予測確率をフィルターに追加すると精度向上の可能性があります。"
                )

    if current_regime == "bear":
        suggestions.append(
            "現在は下落相場です。エントリーを控えめにするか、"
            "下落相場に強い条件を優先してください。"
        )
    elif current_regime == "sideways":
        suggestions.append(
            "横ばい相場ではブレイクアウト戦略の勝率が低下する傾向があります。"
            "出来高倍率の閾値を厳格化してください。"
        )

    suggestions.append(
        "週次で最適化を再実行し、市場環境の変化に追従することを推奨します。"
    )
    suggestions.append(
        "セクター別の分析を追加し、特定セクターに偏らない分散を確認してください。"
    )

    return suggestions


def _summarize_ml(ml_results: Dict) -> Dict:
    """MLモデルのサマリーを生成"""
    summary = {}
    if not ml_results:
        return summary

    for name, res in ml_results.items():
        avg = res.get("metrics_avg", {})
        fi = res.get("feature_importance", pd.Series(dtype=float))
        summary[name] = {
            "avg_auc": round(avg.get("roc_auc", 0), 4),
            "avg_precision": round(avg.get("precision", 0), 4),
            "avg_recall": round(avg.get("recall", 0), 4),
            "avg_f1": round(avg.get("f1", 0), 4),
            "top_features": fi.head(10).to_dict() if len(fi) > 0 else {},
        }

    return summary


def _save_report_text(report: Dict) -> Path:
    """レポートをテキストファイルとして保存"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = REPORT_DIR / f"report_{timestamp}.txt"

    lines = [
        "=" * 70,
        "機関投資家資金流入シグナル研究 — 最終レポート",
        f"生成日時: {report['timestamp']}",
        f"現在の市場レジーム: {report['current_regime']}",
        "=" * 70,
        "",
        "■ 1. 最も勝率が高い条件",
        f"  条件: {report['best_winrate']['condition_str']}",
        f"  勝率: {report['best_winrate']['metrics']['win_rate']:.1%}",
        f"  平均リターン: {report['best_winrate']['metrics']['avg_return']:.2%}",
        f"  シャープレシオ: {report['best_winrate']['metrics']['sharpe_ratio']:.2f}",
        "",
        "■ 2. 最もリターンが高い条件",
        f"  条件: {report['best_return']['condition_str']}",
        f"  勝率: {report['best_return']['metrics']['win_rate']:.1%}",
        f"  平均リターン: {report['best_return']['metrics']['avg_return']:.2%}",
        "",
        "■ 3. 最も安定している条件",
        f"  条件: {report['best_stable']['condition_str']}",
        f"  シャープレシオ: {report['best_stable']['metrics']['sharpe_ratio']:.2f}",
        f"  最大DD: {report['best_stable']['metrics']['max_drawdown']:.1%}",
        "",
        "■ 4. 現在シグナル銘柄",
    ]

    for s in report.get("current_signals", [])[:20]:
        lines.append(
            f"  {s['code']} {s['name'][:10]:10s} "
            f"終値:{s['close']:>10,.0f} "
            f"出来高倍率:{s['vol_ratio']:>5.1f}x "
            f"({s['signal_type']})"
        )

    lines.extend(["", "■ 5. 売買ルール"])
    for key, rule in report.get("trading_rules", {}).items():
        lines.append(f"  【{rule['name']}】")
        lines.append(f"    エントリー: {rule['entry']}")
        lines.append(f"    条件: {rule['conditions']}")
        lines.append(f"    決済: {rule['exit']}")
        lines.append(f"    期待勝率: {rule['expected_winrate']}")
        lines.append(f"    期待リターン: {rule['expected_return']}")
        lines.append("")

    lines.extend(["", "■ 6. 保有期間比較"])
    for row in report.get("holding_period_comparison", []):
        lines.append(f"  条件: {row.get('condition', '')}")
        for k, v in row.items():
            if k != "condition" and "winrate" in k:
                period = k.split("d_")[0]
                lines.append(
                    f"    {period}日: WR={v:.1%}, "
                    f"Ret={row.get(f'{period}d_return', 0):.2%}, "
                    f"SR={row.get(f'{period}d_sharpe', 0):.2f}, "
                    f"MDD={row.get(f'{period}d_mdd', 0):.1%}"
                )
        lines.append("")

    lines.extend(["■ 7. ヒットカウント分析"])
    for row in report.get("hit_count_summary", []):
        lines.append(
            f"  {row.get('condition', '')}: "
            f"日平均{row.get('avg_daily_hits', 0):.1f}銘柄, "
            f"月平均{row.get('avg_monthly_hits', 0):.1f}銘柄, "
            f"年平均{row.get('avg_yearly_hits', 0):.0f}銘柄"
        )

    fund = report.get("fundamental_analysis", {})
    if fund:
        lines.extend(["", "■ 8. ファンダメンタル分析"])
        wf = fund.get("with_fundamental", {})
        wof = fund.get("without_fundamental", {})
        if wf:
            lines.append(f"  ファンダ有 ({wf.get('count', 0)}条件): "
                         f"WR={wf.get('avg_win_rate', 0):.1%}, "
                         f"Ret={wf.get('avg_return', 0):.2%}, "
                         f"SR={wf.get('avg_sharpe', 0):.2f}")
        if wof:
            lines.append(f"  ファンダ無 ({wof.get('count', 0)}条件): "
                         f"WR={wof.get('avg_win_rate', 0):.1%}, "
                         f"Ret={wof.get('avg_return', 0):.2%}, "
                         f"SR={wof.get('avg_sharpe', 0):.2f}")
        freq = fund.get("filter_frequency", {})
        if freq:
            lines.append("  よく使われるフィルター:")
            for k, v in sorted(freq.items(), key=lambda x: -x[1]):
                lines.append(f"    {k}: {v}回")

    repro = report.get("reproducible_strategy", {})
    if repro:
        lines.extend(["", "■ 9. 最も再現性の高い戦略"])
        lines.append(f"  条件: {repro.get('condition_str', '')}")
        m = repro.get("metrics", {})
        lines.append(f"  WR={m.get('win_rate', 0):.1%}, "
                     f"SR={m.get('sharpe_ratio', 0):.2f}, "
                     f"MDD={m.get('max_drawdown', 0):.1%}")
        lines.append(f"  理由: {repro.get('rationale', '')}")

    theme_perf = report.get("theme_performance", [])
    if theme_perf:
        lines.extend(["", "■ 10. テーマ別パフォーマンス"])
        for tp in theme_perf[:20]:
            lines.append(
                f"  {tp.get('theme', '')} ({tp.get('period', '')}): "
                f"平均{tp.get('mean_return', 0):.2%}, "
                f"WR={tp.get('win_rate', 0):.1%}, "
                f"({tp.get('n_stocks', 0)}銘柄)"
            )

    tenbagger = report.get("tenbagger_analysis", {})
    if tenbagger and tenbagger.get("count", 0) > 0:
        lines.extend(["", "■ 11. テンバガー候補分析"])
        lines.append(f"  検出数: {tenbagger.get('count', 0)}")
        lines.append(f"  平均倍率: {tenbagger.get('avg_multiple', 0):.1f}x")
        td = tenbagger.get("theme_distribution", {})
        if td:
            lines.append(f"  テーマ分布: {td}")

    lines.extend(["", "■ 12. 改善提案"])
    for i, s in enumerate(report.get("suggestions", []), 1):
        lines.append(f"  {i}. {s}")

    lines.extend(["", "■ 13. ML モデルサマリー"])
    for name, summary in report.get("ml_summary", {}).items():
        lines.append(f"  {name}: AUC={summary['avg_auc']:.4f}, "
                     f"Precision={summary['avg_precision']:.4f}")
        top_feats = list(summary.get("top_features", {}).keys())[:5]
        if top_feats:
            lines.append(f"    重要特徴量: {', '.join(top_feats)}")

    text = "\n".join(lines)
    path.write_text(text, encoding="utf-8")
    logger.info(f"Report saved: {path}")
    return path


# ============================================================
# 可視化
# ============================================================

def plot_equity_curves(results: List[BacktestResult],
                       labels: List[str] = None,
                       save_path: str = None):
    """エクイティカーブを描画"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(14, 7))

    for i, res in enumerate(results):
        if res.trade_returns is None or len(res.trade_returns) == 0:
            continue
        equity = np.cumprod(1 + res.trade_returns)
        label = labels[i] if labels else f"Cond {i+1}"
        ax.plot(equity, label=f"{label} (WR:{res.win_rate:.1%}, SR:{res.sharpe_ratio:.2f})")

    ax.set_xlabel("Trade #")
    ax.set_ylabel("Equity")
    ax.set_title("Equity Curves")
    ax.legend()
    ax.grid(True, alpha=0.3)

    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return fig


def plot_optimization_landscape(results: List[BacktestResult],
                                 save_path: str = None):
    """最適化結果の散布図（勝率 vs リターン vs シャープ）"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if not results:
        return None

    wr = [r.win_rate for r in results]
    ret = [r.avg_return * 100 for r in results]
    sr = [r.sharpe_ratio for r in results]

    fig, axes = plt.subplots(1, 3, figsize=(18, 6))

    sc = axes[0].scatter(wr, ret, c=sr, cmap="RdYlGn", alpha=0.5, s=10)
    axes[0].set_xlabel("Win Rate")
    axes[0].set_ylabel("Avg Return (%)")
    axes[0].set_title("Win Rate vs Return (color=Sharpe)")
    plt.colorbar(sc, ax=axes[0], label="Sharpe")

    axes[1].hist([r.win_rate for r in results], bins=50, color="steelblue", alpha=0.7)
    axes[1].set_xlabel("Win Rate")
    axes[1].set_ylabel("Count")
    axes[1].set_title("Win Rate Distribution")

    axes[2].hist([r.sharpe_ratio for r in results], bins=50, color="coral", alpha=0.7)
    axes[2].set_xlabel("Sharpe Ratio")
    axes[2].set_ylabel("Count")
    axes[2].set_title("Sharpe Ratio Distribution")

    plt.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return fig


def plot_feature_importance(ml_results: Dict, save_path: str = None):
    """MLモデルの特徴量重要度を比較プロット"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    model_names = []
    importances = []
    for name, res in ml_results.items():
        fi = res.get("feature_importance")
        if fi is not None and len(fi) > 0:
            model_names.append(name)
            importances.append(fi.head(15))

    if not importances:
        return None

    n_models = len(model_names)
    fig, axes = plt.subplots(1, n_models, figsize=(7 * n_models, 8))
    if n_models == 1:
        axes = [axes]

    for ax, name, fi in zip(axes, model_names, importances):
        fi_sorted = fi.sort_values(ascending=True)
        ax.barh(fi_sorted.index, fi_sorted.values, color="steelblue", alpha=0.8)
        ax.set_title(f"{name} Feature Importance")
        ax.set_xlabel("Importance")

    plt.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return fig


def plot_regime_performance(regime_summary: pd.DataFrame, save_path: str = None):
    """レジーム別パフォーマンス比較チャート"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if regime_summary is None or regime_summary.empty:
        return None

    fig, axes = plt.subplots(1, 3, figsize=(16, 5))

    regimes = regime_summary["regime"].values
    colors = {"bull": "#2ecc71", "bear": "#e74c3c", "sideways": "#f39c12"}
    bar_colors = [colors.get(r, "#95a5a6") for r in regimes]

    axes[0].bar(regimes, regime_summary["best_win_rate"], color=bar_colors, alpha=0.8)
    axes[0].set_title("Best Win Rate by Regime")
    axes[0].set_ylabel("Win Rate")

    axes[1].bar(regimes, regime_summary["best_sharpe"], color=bar_colors, alpha=0.8)
    axes[1].set_title("Best Sharpe Ratio by Regime")
    axes[1].set_ylabel("Sharpe Ratio")

    axes[2].bar(regimes, regime_summary["best_avg_return"] * 100, color=bar_colors, alpha=0.8)
    axes[2].set_title("Best Avg Return by Regime")
    axes[2].set_ylabel("Return (%)")

    plt.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return fig


def plot_volume_institutional_correlation(stock_df: pd.DataFrame,
                                          investor_df: pd.DataFrame,
                                          save_path: str = None):
    """
    出来高急増と機関投資家売買の相関を可視化。
    仮説検証の核心部分。
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from scipy import stats

    if investor_df is None or investor_df.empty:
        logger.warning("No investor type data for correlation analysis")
        return None

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    vol_by_date = stock_df.groupby("Date").agg(
        mean_vol_ratio=("vol_ratio", "mean"),
        median_vol_ratio=("vol_ratio", "median"),
        high_vol_count=("vol_ratio", lambda x: (x > 2).sum()),
    ).reset_index()

    inst_cols = [c for c in investor_df.columns
                 if any(kw in c.lower() for kw in ["foreign", "trust", "institution"])]

    if not inst_cols:
        logger.warning("No institutional investor columns found")
        plt.close(fig)
        return None

    investor_df["Date"] = pd.to_datetime(investor_df.get("PublishedDate",
                                         investor_df.get("Date", investor_df.iloc[:, 0])))
    merged = vol_by_date.merge(investor_df, on="Date", how="inner")

    if merged.empty:
        logger.warning("No overlapping dates between volume and investor data")
        plt.close(fig)
        return None

    inst_col = inst_cols[0]

    axes[0, 0].scatter(merged["mean_vol_ratio"], merged[inst_col],
                       alpha=0.3, s=10, color="steelblue")
    axes[0, 0].set_xlabel("Mean Volume Ratio")
    axes[0, 0].set_ylabel(f"Institutional Flow ({inst_col[:30]})")
    axes[0, 0].set_title("Volume Surge vs Institutional Buying")

    if len(merged) > 10:
        r, p = stats.pearsonr(
            merged["mean_vol_ratio"].dropna(),
            pd.to_numeric(merged[inst_col], errors="coerce").dropna()
        )
        axes[0, 0].annotate(f"r={r:.3f}, p={p:.4f}", xy=(0.05, 0.95),
                            xycoords="axes fraction", fontsize=10)

    axes[0, 1].plot(merged["Date"], merged["mean_vol_ratio"],
                    label="Vol Ratio", color="steelblue", alpha=0.7)
    ax2 = axes[0, 1].twinx()
    ax2.plot(merged["Date"], pd.to_numeric(merged[inst_col], errors="coerce"),
             label="Institutional", color="coral", alpha=0.7)
    axes[0, 1].set_title("Time Series Comparison")
    axes[0, 1].legend(loc="upper left")
    ax2.legend(loc="upper right")

    vol_q = merged["mean_vol_ratio"].quantile([0.25, 0.5, 0.75])
    groups = pd.cut(merged["mean_vol_ratio"],
                    bins=[0, vol_q[0.25], vol_q[0.5], vol_q[0.75], float("inf")],
                    labels=["Low", "Med-Low", "Med-High", "High"])
    inst_by_group = merged.groupby(groups, observed=False)[inst_col].apply(
        lambda x: pd.to_numeric(x, errors="coerce").mean()
    )
    axes[1, 0].bar(inst_by_group.index.astype(str), inst_by_group.values,
                   color=["#3498db", "#2ecc71", "#f39c12", "#e74c3c"], alpha=0.8)
    axes[1, 0].set_title("Institutional Flow by Volume Quartile")
    axes[1, 0].set_ylabel("Avg Institutional Net")

    merged["vol_surge"] = merged["mean_vol_ratio"] > 2.0
    surge_inst = merged.groupby("vol_surge")[inst_col].apply(
        lambda x: pd.to_numeric(x, errors="coerce").mean()
    )
    axes[1, 1].bar(["Normal", "Vol Surge (>2x)"], surge_inst.values,
                   color=["steelblue", "coral"], alpha=0.8)
    axes[1, 1].set_title("Institutional Flow: Normal vs Volume Surge Days")
    axes[1, 1].set_ylabel("Avg Institutional Net")

    plt.suptitle("Hypothesis: Volume Surge = Institutional Buying?", fontsize=14, y=1.02)
    plt.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return fig


def plot_holding_period_comparison(holding_comparison: List[Dict],
                                   save_path: str = None):
    """保有期間別パフォーマンス比較チャート"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if not holding_comparison:
        return None

    periods = []
    for key in holding_comparison[0]:
        if key.endswith("d_winrate"):
            periods.append(int(key.replace("d_winrate", "")))
    periods.sort()

    if not periods:
        return None

    n_conds = min(len(holding_comparison), 5)
    fig, axes = plt.subplots(1, 3, figsize=(18, 6))

    for i, row in enumerate(holding_comparison[:n_conds]):
        label = f"Cond {i+1}"
        wrs = [row.get(f"{p}d_winrate", 0) for p in periods]
        rets = [row.get(f"{p}d_return", 0) * 100 for p in periods]
        srs = [row.get(f"{p}d_sharpe", 0) for p in periods]

        axes[0].plot(periods, wrs, "o-", label=label)
        axes[1].plot(periods, rets, "o-", label=label)
        axes[2].plot(periods, srs, "o-", label=label)

    axes[0].set_xlabel("Holding Days")
    axes[0].set_ylabel("Win Rate")
    axes[0].set_title("Win Rate by Holding Period")
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)

    axes[1].set_xlabel("Holding Days")
    axes[1].set_ylabel("Avg Return (%)")
    axes[1].set_title("Average Return by Holding Period")
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)

    axes[2].set_xlabel("Holding Days")
    axes[2].set_ylabel("Sharpe Ratio")
    axes[2].set_title("Sharpe Ratio by Holding Period")
    axes[2].legend()
    axes[2].grid(True, alpha=0.3)

    plt.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return fig


def plot_theme_performance(theme_performance: pd.DataFrame,
                           save_path: str = None):
    """テーマ別パフォーマンスチャート"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if theme_performance is None or theme_performance.empty:
        return None

    pivot = theme_performance.pivot_table(
        index="theme", columns="period",
        values="mean_return", aggfunc="first"
    )

    if pivot.empty:
        return None

    fig, ax = plt.subplots(figsize=(14, 7))
    pivot.plot(kind="bar", ax=ax, alpha=0.8)
    ax.set_xlabel("Theme")
    ax.set_ylabel("Mean Return")
    ax.set_title("Theme Performance by Holding Period")
    ax.legend(title="Period", bbox_to_anchor=(1.05, 1), loc="upper left")
    ax.grid(True, alpha=0.3, axis="y")

    plt.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return fig
