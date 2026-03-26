"""
戦略グリッドサーチ: エントリー/イグジット条件の網羅的探索

- エントリー: VB倍率, 株価変動, RSI, MA乖離, EPS成長, 時価総額
- イグジット: 保有日数, 利確/損切, トレーリングストップ
- 過学習対策: Train/Test分割, 最低30トレード, テスト勝率55%以上
- 評価: 勝率, PF, 平均利益/損失比, 最大DD
"""
import logging
import itertools
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class StrategyResult:
    params: Dict
    n_trades: int
    win_rate: float
    profit_factor: float
    avg_win_loss_ratio: float
    max_drawdown: float
    total_return: float
    avg_return: float
    sharpe: float

    @property
    def score(self) -> float:
        return (self.win_rate * 0.35
                + min(self.profit_factor / 3.0, 1.0) * 0.25
                + min(self.avg_win_loss_ratio / 2.0, 1.0) * 0.15
                + min(self.sharpe / 2.0, 1.0) * 0.15
                - min(abs(self.max_drawdown) / 0.2, 1.0) * 0.10)

    def to_dict(self) -> Dict:
        return {
            "params": self.params,
            "n_trades": self.n_trades,
            "win_rate": round(self.win_rate, 4),
            "profit_factor": round(self.profit_factor, 2),
            "avg_win_loss_ratio": round(self.avg_win_loss_ratio, 2),
            "max_drawdown": round(self.max_drawdown, 4),
            "total_return": round(self.total_return, 4),
            "avg_return": round(self.avg_return, 4),
            "sharpe": round(self.sharpe, 2),
            "score": round(self.score, 4),
        }


# ---------------------------------------------------------------------------
# Entry condition grid
# ---------------------------------------------------------------------------

ENTRY_GRID = {
    "vb_min": [1.3, 1.5, 1.8, 2.0, 2.5, 3.0],
    "vb_max": [2.0, 2.5, 3.0, 5.0, 999],
    "price_chg_min": [-0.05, -0.02, 0.0],
    "price_chg_max": [0.05, 0.10, 0.15],
    "rsi_min": [30, 40, 50],
    "rsi_max": [60, 65, 70],
    "ma25_dev_min": [-0.05, -0.03, 0.0],
    "ma25_dev_max": [0.05, 0.08, 0.10],
    "eps_growth_min": [0.0, 0.10, 0.20],
    "mcap_min": [5e9, 10e9, 50e9],
    "mcap_max": [50e9, 100e9, 500e9, 1e12],
}

# ---------------------------------------------------------------------------
# Exit condition grid
# ---------------------------------------------------------------------------

EXIT_GRID = {
    "holding_days": [3, 5, 10, 15, 20],
    "take_profit": [0.05, 0.08, 0.10, 0.15, None],
    "stop_loss": [-0.03, -0.05, -0.07, None],
    "trailing_stop": [-0.05, -0.07, None],
}


def _apply_entry(df: pd.DataFrame, params: Dict) -> pd.Series:
    """Apply entry conditions and return boolean mask."""
    mask = pd.Series(True, index=df.index)

    if "vol_base_ratio" in df.columns:
        vb = df["vol_base_ratio"] if "vol_base_ratio" in df.columns else df.get("vol_ratio", pd.Series(1, index=df.index))
    else:
        vb = df.get("vol_ratio", pd.Series(1, index=df.index))

    mask &= vb >= params.get("vb_min", 0)
    if params.get("vb_max", 999) < 999:
        mask &= vb <= params["vb_max"]

    if "pct_from_50d_high" in df.columns:
        mask &= df["pct_from_50d_high"] >= params.get("price_chg_min", -1)
        mask &= df["pct_from_50d_high"] <= params.get("price_chg_max", 1)

    if "rsi" in df.columns:
        mask &= df["rsi"] >= params.get("rsi_min", 0)
        mask &= df["rsi"] <= params.get("rsi_max", 100)

    if "ma25_dev" in df.columns:
        mask &= df["ma25_dev"] >= params.get("ma25_dev_min", -1)
        mask &= df["ma25_dev"] <= params.get("ma25_dev_max", 1)

    if "eps_growth" in df.columns:
        eg_min = params.get("eps_growth_min", 0)
        if eg_min > 0:
            mask &= df["eps_growth"].fillna(0) >= eg_min

    if "market_cap" in df.columns:
        mask &= df["market_cap"].fillna(0) >= params.get("mcap_min", 0)
        mask &= df["market_cap"].fillna(1e15) <= params.get("mcap_max", 1e15)

    return mask


def _simulate_exit(df: pd.DataFrame, entry_mask: pd.Series, params: Dict) -> pd.DataFrame:
    """
    Vectorized exit simulation with take-profit, stop-loss, and trailing stop.
    Returns per-trade results (return, holding_days).
    """
    holding = params.get("holding_days", 5)
    tp = params.get("take_profit")
    sl = params.get("stop_loss")
    ts = params.get("trailing_stop")

    ret_col = f"fwd_{holding}d_return"
    if ret_col not in df.columns:
        # Fall back to closest available
        for hd in [3, 5, 10, 20, 60]:
            if f"fwd_{hd}d_return" in df.columns:
                ret_col = f"fwd_{hd}d_return"
                break

    entries = df[entry_mask].copy()
    if entries.empty:
        return pd.DataFrame()

    base_returns = entries[ret_col].values if ret_col in entries.columns else np.zeros(len(entries))

    # Simple TP/SL clipping (vectorized approximation)
    returns = base_returns.copy()
    if tp is not None:
        returns = np.where(returns > tp, tp, returns)
    if sl is not None:
        returns = np.where(returns < sl, sl, returns)

    # Trailing stop approximation: reduce gains that exceed threshold from peak
    if ts is not None and tp is not None:
        peak = np.maximum(returns, 0)
        trail_exit = peak + ts
        returns = np.where((returns > 0) & (returns < trail_exit), trail_exit, returns)

    result = pd.DataFrame({
        "Date": entries["Date"].values,
        "Code": entries["Code"].values if "Code" in entries.columns else entries.get("CodeStr", pd.Series()).values,
        "return": returns,
    })
    return result


def evaluate_trades(trades: pd.DataFrame, min_trades: int = 30) -> Optional[StrategyResult]:
    """Compute strategy metrics from trade results."""
    if len(trades) < min_trades:
        return None

    rets = trades["return"].values
    n = len(rets)
    wins = rets[rets > 0]
    losses = rets[rets <= 0]

    win_rate = len(wins) / n
    total_profit = wins.sum() if len(wins) > 0 else 0
    total_loss = abs(losses.sum()) if len(losses) > 0 else 1e-10
    pf = total_profit / total_loss

    avg_win = wins.mean() if len(wins) > 0 else 0
    avg_loss = abs(losses.mean()) if len(losses) > 0 else 1e-10
    wl_ratio = avg_win / avg_loss

    cumret = np.cumsum(rets)
    running_max = np.maximum.accumulate(cumret)
    dd = cumret - running_max
    max_dd = float(dd.min()) if len(dd) > 0 else 0

    daily_ret_std = np.std(rets) if len(rets) > 1 else 1e-10
    sharpe = (np.mean(rets) / daily_ret_std) * np.sqrt(252 / max(1, n)) if daily_ret_std > 0 else 0

    return StrategyResult(
        params={},
        n_trades=n,
        win_rate=win_rate,
        profit_factor=pf,
        avg_win_loss_ratio=wl_ratio,
        max_drawdown=max_dd,
        total_return=float(cumret[-1]) if len(cumret) > 0 else 0,
        avg_return=float(np.mean(rets)),
        sharpe=sharpe,
    )


# ---------------------------------------------------------------------------
# Grid search
# ---------------------------------------------------------------------------

def _generate_param_combos(grid: Dict, max_combos: int = 50000) -> List[Dict]:
    """Generate parameter combinations from grid, limited to max_combos."""
    keys = list(grid.keys())
    values = [grid[k] for k in keys]
    combos = []
    for vals in itertools.product(*values):
        combo = dict(zip(keys, vals))
        # Skip invalid combos
        if combo.get("vb_min", 0) >= combo.get("vb_max", 999):
            continue
        if combo.get("rsi_min", 0) >= combo.get("rsi_max", 100):
            continue
        if combo.get("ma25_dev_min", -1) >= combo.get("ma25_dev_max", 1):
            continue
        if combo.get("mcap_min", 0) >= combo.get("mcap_max", 1e15):
            continue
        combos.append(combo)
        if len(combos) >= max_combos:
            break
    return combos


def run_strategy_search(df: pd.DataFrame,
                        train_end: str = "2023-12-31",
                        min_trades: int = 30,
                        min_test_winrate: float = 0.55,
                        max_entry_combos: int = 20000,
                        top_n: int = 50) -> Dict:
    """
    Run exhaustive strategy search:
    1. Generate entry + exit parameter combinations
    2. Evaluate on train period
    3. Filter top strategies
    4. Validate on test period
    5. Return strategies that pass both train and test criteria
    """
    logger.info("=" * 60)
    logger.info("STRATEGY SEARCH START")
    logger.info("=" * 60)

    train_end_ts = pd.Timestamp(train_end)
    df_train = df[df["Date"] <= train_end_ts].copy()
    df_test = df[df["Date"] > train_end_ts].copy()

    logger.info(f"Train: {len(df_train):,} rows | Test: {len(df_test):,} rows")

    # Generate entry combos
    entry_combos = _generate_param_combos(ENTRY_GRID, max_entry_combos)
    exit_combos = _generate_param_combos(EXIT_GRID, 500)
    logger.info(f"Entry combos: {len(entry_combos):,} | Exit combos: {len(exit_combos):,}")

    # Phase 1: Train evaluation
    logger.info("\nPhase 1: Training period evaluation...")
    train_results = []
    total = len(entry_combos) * len(exit_combos)
    checked = 0

    for entry_params in entry_combos:
        entry_mask = _apply_entry(df_train, entry_params)
        n_entries = entry_mask.sum()
        if n_entries < min_trades:
            checked += len(exit_combos)
            continue

        for exit_params in exit_combos:
            checked += 1
            if checked % 10000 == 0:
                logger.info(f"  Progress: {checked:,}/{total:,} ({checked/total:.1%})")

            full_params = {**entry_params, **exit_params}
            trades = _simulate_exit(df_train, entry_mask, exit_params)
            result = evaluate_trades(trades, min_trades)
            if result is None:
                continue

            result.params = full_params
            if result.win_rate >= 0.50 and result.profit_factor >= 1.0:
                train_results.append(result)

    logger.info(f"  Passing strategies (train): {len(train_results):,}")

    if not train_results:
        return {"error": "No strategies passed training criteria", "train_checked": checked}

    # Sort by composite score
    train_results.sort(key=lambda r: r.score, reverse=True)
    top_train = train_results[:top_n]

    # Phase 2: Test validation
    logger.info(f"\nPhase 2: Test period validation (top {len(top_train)})...")
    final_results = []

    for train_r in top_train:
        params = train_r.params
        entry_params = {k: v for k, v in params.items() if k in ENTRY_GRID}
        exit_params = {k: v for k, v in params.items() if k in EXIT_GRID}

        entry_mask = _apply_entry(df_test, entry_params)
        trades = _simulate_exit(df_test, entry_mask, exit_params)
        test_r = evaluate_trades(trades, min_trades=10)

        if test_r is None:
            continue

        if test_r.win_rate >= min_test_winrate:
            final_results.append({
                "params": params,
                "train": train_r.to_dict(),
                "test": test_r.to_dict(),
                "train_score": round(train_r.score, 4),
                "test_score": round(test_r.score, 4),
                "robust": abs(train_r.win_rate - test_r.win_rate) < 0.10,
            })

    final_results.sort(key=lambda r: r["test_score"], reverse=True)

    logger.info(f"\nFinal strategies passing test: {len(final_results)}")
    for i, r in enumerate(final_results[:10]):
        p = r["params"]
        logger.info(f"  #{i+1}: VB={p.get('vb_min',0)}-{p.get('vb_max',999)}x | "
                    f"Hold={p.get('holding_days',5)}d | "
                    f"Train WR={r['train']['win_rate']:.1%} PF={r['train']['profit_factor']:.2f} | "
                    f"Test WR={r['test']['win_rate']:.1%} PF={r['test']['profit_factor']:.2f} | "
                    f"Robust={'✓' if r['robust'] else '✗'}")

    summary = {
        "total_combos_checked": checked,
        "train_passing": len(train_results),
        "test_passing": len(final_results),
        "top_strategies": final_results[:20],
        "best_strategy": final_results[0] if final_results else None,
    }

    logger.info("\n" + "=" * 60)
    logger.info("STRATEGY SEARCH COMPLETE")
    logger.info("=" * 60)

    return summary
