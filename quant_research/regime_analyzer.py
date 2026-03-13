"""
市場レジーム分析

指数データ（TOPIX/日経225）を用いて相場環境を分類し、
レジームごとに売買戦略の成績を比較する。
"""
import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .config import REGIME_MA_SHORT, REGIME_MA_LONG, REGIME_MOMENTUM_DAYS
from .backtester import run_backtest, BacktestResult

logger = logging.getLogger(__name__)


# ============================================================
# レジーム分類
# ============================================================

def classify_regime(index_df: pd.DataFrame,
                    ma_short: int = REGIME_MA_SHORT,
                    ma_long: int = REGIME_MA_LONG,
                    momentum_days: int = REGIME_MOMENTUM_DAYS,
                    close_col: str = None) -> pd.DataFrame:
    """
    指数データからレジームを判定。

    ルール:
        上昇: 短期MA > 長期MA AND N日モメンタム > 0
        下落: 短期MA < 長期MA AND N日モメンタム < 0
        横ばい: それ以外

    Returns:
        Date, Close, regime ('bull', 'bear', 'sideways') を含むDataFrame
    """
    df = index_df.copy()

    if close_col is None:
        for candidate in ["Close", "AdjClose", "close", "C", "AdjC"]:
            if candidate in df.columns:
                close_col = candidate
                break
    if close_col is None:
        raise ValueError(f"No close price column found. Columns: {list(df.columns)}")

    if "Date" not in df.columns:
        for candidate in ["date", "Date", "TradeDate"]:
            if candidate in df.columns:
                df = df.rename(columns={candidate: "Date"})
                break

    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").reset_index(drop=True)
    df["Close_idx"] = pd.to_numeric(df[close_col], errors="coerce")

    df["ma_short"] = df["Close_idx"].rolling(ma_short, min_periods=ma_short).mean()
    df["ma_long"] = df["Close_idx"].rolling(ma_long, min_periods=ma_long).mean()
    df["momentum"] = df["Close_idx"].pct_change(momentum_days)

    conditions = [
        (df["ma_short"] > df["ma_long"]) & (df["momentum"] > 0),
        (df["ma_short"] < df["ma_long"]) & (df["momentum"] < 0),
    ]
    choices = ["bull", "bear"]
    df["regime"] = np.select(conditions, choices, default="sideways")

    logger.info(f"Regime classification:")
    for regime in ["bull", "bear", "sideways"]:
        count = (df["regime"] == regime).sum()
        pct = count / len(df) * 100
        logger.info(f"  {regime}: {count:,} days ({pct:.1f}%)")

    return df[["Date", "Close_idx", "ma_short", "ma_long", "momentum", "regime"]]


def merge_regime(stock_df: pd.DataFrame, regime_df: pd.DataFrame) -> pd.DataFrame:
    """株価DataFrameにレジーム列を付与"""
    regime_map = regime_df.set_index("Date")["regime"]
    stock_df = stock_df.copy()
    stock_df["regime"] = stock_df["Date"].map(regime_map)
    stock_df["regime"] = stock_df["regime"].fillna("unknown")
    return stock_df


# ============================================================
# レジーム別バックテスト
# ============================================================

def backtest_by_regime(df: pd.DataFrame,
                       conditions: List[Dict],
                       regime_col: str = "regime") -> Dict:
    """
    レジーム別にバックテストを実行し、成績を比較。

    Returns:
        regime -> list of BacktestResult
    """
    regimes = df[regime_col].unique()
    regimes = [r for r in regimes if r != "unknown"]

    results = {}
    for regime in regimes:
        regime_df = df[df[regime_col] == regime].copy()
        logger.info(f"\nBacktesting regime '{regime}': {len(regime_df):,} rows")

        regime_results = []
        for cond in conditions:
            res = run_backtest(regime_df, cond)
            if res and res.n_trades >= 20:
                regime_results.append(res)

        regime_results.sort(key=lambda r: r.composite_score, reverse=True)
        results[regime] = regime_results
        logger.info(f"  {len(regime_results)} valid conditions")

    return results


def regime_performance_summary(regime_results: Dict) -> pd.DataFrame:
    """レジーム別パフォーマンスのサマリーテーブルを生成"""
    rows = []
    for regime, results in regime_results.items():
        if not results:
            continue

        top = results[0]
        all_wr = [r.win_rate for r in results]
        all_sr = [r.sharpe_ratio for r in results]
        all_ret = [r.avg_return for r in results]

        rows.append({
            "regime": regime,
            "n_conditions": len(results),
            "best_win_rate": top.win_rate,
            "best_sharpe": top.sharpe_ratio,
            "best_avg_return": top.avg_return,
            "avg_win_rate": np.mean(all_wr),
            "avg_sharpe": np.mean(all_sr),
            "avg_return": np.mean(all_ret),
            "best_condition": top.condition,
        })

    return pd.DataFrame(rows)


def get_current_regime(index_df: pd.DataFrame, **kwargs) -> str:
    """最新の相場レジームを取得"""
    regime_df = classify_regime(index_df, **kwargs)
    if regime_df.empty:
        return "unknown"
    return regime_df.iloc[-1]["regime"]


def regime_transition_matrix(regime_df: pd.DataFrame) -> pd.DataFrame:
    """レジーム遷移確率行列を計算"""
    regimes = regime_df["regime"].values
    transitions = {}

    for i in range(len(regimes) - 1):
        current = regimes[i]
        next_regime = regimes[i + 1]
        if current not in transitions:
            transitions[current] = {}
        transitions[current][next_regime] = transitions[current].get(next_regime, 0) + 1

    matrix = pd.DataFrame(transitions).T.fillna(0)
    matrix = matrix.div(matrix.sum(axis=1), axis=0)

    return matrix
