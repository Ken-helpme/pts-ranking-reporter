"""
ベクトル化バックテストエンジン

フォワードリターンを事前計算済みのため、条件のbooleanマスク適用だけで
数万パターンを高速に評価可能。
"""
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .config import SLIPPAGE_PCT, COMMISSION_PCT, MIN_TRADES, MIN_FIRE_RATE, TRAIN_RATIO
from .screener import apply_condition

logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    """バックテスト結果"""
    condition: Dict
    holding_days: int
    n_trades: int
    win_rate: float                   # 勝率 (0-1)
    avg_return: float                 # 平均リターン
    median_return: float              # 中央値リターン
    sharpe_ratio: float               # シャープレシオ（年率換算）
    max_drawdown: float               # 最大ドローダウン
    profit_factor: float              # プロフィットファクター
    total_return: float               # 累積リターン
    avg_trades_per_day: float         # 日当たり平均トレード数
    avg_daily_hits: float = 0.0       # 日平均ヒット数
    avg_monthly_hits: float = 0.0     # 月平均ヒット数
    avg_yearly_hits: float = 0.0      # 年平均ヒット数
    trade_returns: np.ndarray = field(repr=False, default=None)
    trade_dates: np.ndarray = field(repr=False, default=None)

    @property
    def composite_score(self) -> float:
        """最適化用複合スコア"""
        return (
            self.win_rate * 0.4
            + min(self.sharpe_ratio / 3.0, 1.0) * 0.3
            + min(self.profit_factor / 3.0, 1.0) * 0.2
            - min(abs(self.max_drawdown) / 0.3, 1.0) * 0.1
        )

    def to_dict(self) -> Dict:
        return {
            "condition": self.condition,
            "holding_days": self.holding_days,
            "n_trades": self.n_trades,
            "win_rate": round(self.win_rate, 4),
            "avg_return": round(self.avg_return, 6),
            "median_return": round(self.median_return, 6),
            "sharpe_ratio": round(self.sharpe_ratio, 4),
            "max_drawdown": round(self.max_drawdown, 4),
            "profit_factor": round(self.profit_factor, 4),
            "total_return": round(self.total_return, 4),
            "composite_score": round(self.composite_score, 4),
            "avg_daily_hits": round(self.avg_daily_hits, 2),
            "avg_monthly_hits": round(self.avg_monthly_hits, 2),
            "avg_yearly_hits": round(self.avg_yearly_hits, 2),
        }


def run_backtest(df: pd.DataFrame, condition: Dict,
                 cost_pct: float = None) -> Optional[BacktestResult]:
    """
    単一条件でバックテストを実行。

    翌日寄り買い → N日後終値売り。
    フォワードリターンは事前計算済み前提。
    """
    holding = condition.get("holding_days", 5)
    ret_col = f"fwd_{holding}d_return"

    if ret_col not in df.columns:
        return None

    mask = apply_condition(df, condition)
    signals = df.loc[mask].copy()

    if len(signals) < 5:
        return None

    returns = signals[ret_col].dropna().values

    if cost_pct is None:
        cost_pct = (SLIPPAGE_PCT + COMMISSION_PCT) / 100.0 * 2
    returns = returns - cost_pct

    if len(returns) < 5:
        return None

    n_trades = len(returns)
    win_rate = np.sum(returns > 0) / n_trades
    avg_return = np.mean(returns)
    median_return = np.median(returns)

    if np.std(returns) > 0:
        daily_sharpe = np.mean(returns) / np.std(returns)
        annualization = np.sqrt(250 / max(holding, 1))
        sharpe_ratio = daily_sharpe * annualization
    else:
        sharpe_ratio = 0.0

    equity = np.cumprod(1 + returns)
    running_max = np.maximum.accumulate(equity)
    drawdowns = (equity - running_max) / running_max
    max_drawdown = float(np.min(drawdowns)) if len(drawdowns) > 0 else 0.0

    gross_profit = np.sum(returns[returns > 0])
    gross_loss = abs(np.sum(returns[returns < 0]))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (
        float("inf") if gross_profit > 0 else 0.0
    )

    total_return = float(equity[-1] - 1) if len(equity) > 0 else 0.0

    dates = signals["Date"].values if "Date" in signals.columns else None
    unique_dates = pd.Series(dates).nunique() if dates is not None else 1
    avg_per_day = n_trades / max(unique_dates, 1)

    avg_daily_hits = 0.0
    avg_monthly_hits = 0.0
    avg_yearly_hits = 0.0
    if dates is not None and len(dates) > 0:
        date_series = pd.to_datetime(pd.Series(dates), errors="coerce").dropna()
        if not date_series.empty:
            daily_counts = date_series.groupby(date_series.dt.date).count()
            avg_daily_hits = float(daily_counts.mean())

            monthly_counts = date_series.groupby(date_series.dt.to_period("M")).count()
            avg_monthly_hits = float(monthly_counts.mean()) if len(monthly_counts) > 0 else 0.0

            yearly_counts = date_series.groupby(date_series.dt.year).count()
            avg_yearly_hits = float(yearly_counts.mean()) if len(yearly_counts) > 0 else 0.0

    return BacktestResult(
        condition=condition,
        holding_days=holding,
        n_trades=n_trades,
        win_rate=win_rate,
        avg_return=avg_return,
        median_return=median_return,
        sharpe_ratio=sharpe_ratio,
        max_drawdown=max_drawdown,
        profit_factor=profit_factor,
        total_return=total_return,
        avg_trades_per_day=avg_per_day,
        avg_daily_hits=avg_daily_hits,
        avg_monthly_hits=avg_monthly_hits,
        avg_yearly_hits=avg_yearly_hits,
        trade_returns=returns,
        trade_dates=dates,
    )


def run_batch_backtest(df: pd.DataFrame,
                       conditions: List[Dict],
                       min_trades: int = MIN_TRADES,
                       min_fire_rate: float = MIN_FIRE_RATE,
                       show_progress: bool = True) -> List[BacktestResult]:
    """
    複数条件を一括バックテスト。

    ハードフィルター:
        - 最低トレード数以上
        - 最低発動率以上（テスト日数に対するシグナル発生日の比率）
    """
    from tqdm import tqdm

    total_dates = df["Date"].nunique() if "Date" in df.columns else 1

    results = []
    iterator = tqdm(conditions, desc="Backtesting") if show_progress else conditions

    for cond in iterator:
        result = run_backtest(df, cond)
        if result is None:
            continue
        if result.n_trades < min_trades:
            continue

        if result.trade_dates is not None:
            signal_dates = pd.Series(result.trade_dates).nunique()
            fire_rate = signal_dates / max(total_dates, 1)
            if fire_rate < min_fire_rate:
                continue

        results.append(result)

    logger.info(f"Backtest complete: {len(results):,}/{len(conditions):,} "
                f"conditions passed filters")
    return results


def split_train_test(df: pd.DataFrame,
                     train_ratio: float = TRAIN_RATIO) -> tuple:
    """時系列ベースでtrain/test分割"""
    dates = sorted(df["Date"].unique())
    split_idx = int(len(dates) * train_ratio)
    train_end = dates[split_idx]

    train = df[df["Date"] <= train_end].copy()
    test = df[df["Date"] > train_end].copy()

    logger.info(f"Train: {train['Date'].min()} to {train['Date'].max()} "
                f"({len(train):,} rows)")
    logger.info(f"Test:  {test['Date'].min()} to {test['Date'].max()} "
                f"({len(test):,} rows)")

    return train, test


def evaluate_out_of_sample(train_results: List[BacktestResult],
                           df_test: pd.DataFrame,
                           top_n: int = 50) -> List[Dict]:
    """
    訓練期間で上位の条件をテスト期間で再評価。
    過学習チェック用。
    """
    train_results.sort(key=lambda r: r.composite_score, reverse=True)
    top_conditions = train_results[:top_n]

    oos_results = []
    for train_res in top_conditions:
        test_res = run_backtest(df_test, train_res.condition)
        if test_res is None:
            continue

        oos_results.append({
            "condition": train_res.condition,
            "train": train_res.to_dict(),
            "test": test_res.to_dict(),
            "train_score": train_res.composite_score,
            "test_score": test_res.composite_score,
            "score_decay": (
                (test_res.composite_score - train_res.composite_score)
                / max(abs(train_res.composite_score), 1e-9)
            ),
        })

    oos_results.sort(key=lambda x: x["test_score"], reverse=True)
    return oos_results


def results_to_dataframe(results: List[BacktestResult]) -> pd.DataFrame:
    """BacktestResult のリストをDataFrameに変換"""
    rows = [r.to_dict() for r in results]
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("composite_score", ascending=False).reset_index(drop=True)
    return df
