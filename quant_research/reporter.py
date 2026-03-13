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

from .config import DATA_DIR
from .screener import apply_condition, condition_to_str
from .backtester import BacktestResult

logger = logging.getLogger(__name__)
REPORT_DIR = DATA_DIR / "reports"


def generate_final_report(
    optimization_results: Dict,
    ml_results: Dict,
    regime_results: Dict,
    regime_summary: pd.DataFrame,
    df: pd.DataFrame,
    current_regime: str = "unknown",
) -> Dict:
    """
    全分析結果を統合して最終レポートを生成。

    出力:
        1. 最も勝率が高い条件
        2. 最もリターンが高い条件
        3. 最も安定している条件
        4. 現在条件に当てはまる銘柄
        5. 売買ルール
        6. 改善提案
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
        "current_signals": current_signals,
        "trading_rules": trading_rules,
        "suggestions": suggestions,
        "ml_summary": _summarize_ml(ml_results),
        "regime_summary": regime_summary.to_dict("records") if regime_summary is not None else [],
    }

    _save_report_text(report)
    return report


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

    lines.extend(["■ 6. 改善提案"])
    for i, s in enumerate(report.get("suggestions", []), 1):
        lines.append(f"  {i}. {s}")

    lines.extend(["", "■ ML モデルサマリー"])
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
