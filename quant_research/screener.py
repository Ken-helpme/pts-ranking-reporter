"""
スクリーニング条件のランダム生成

数万パターンの売買条件を自動生成し、バックテストに渡す。
"""
import logging
import random
from typing import Dict, List, Tuple

import numpy as np

from .config import PARAM_SPACE, RANDOM_SEARCH_TRIALS, FUNDAMENTAL_PARAMS

logger = logging.getLogger(__name__)


def generate_random_conditions(n: int = RANDOM_SEARCH_TRIALS,
                               seed: int = None) -> List[Dict]:
    """
    ランダムなスクリーニング条件をn個生成。

    各条件は以下のキーを持つ辞書:
        vol_ratio_min     : 出来高倍率の下限
        vol_zscore_min    : 出来高Zスコアの下限
        turnover_min      : 売買代金の下限
        market_cap_min    : 時価総額の下限
        market_cap_max    : 時価総額の上限
        trend_condition   : トレンド条件
        price_position    : 価格位置条件
        holding_days      : 保持日数
        rsi_min           : RSI下限
        rsi_max           : RSI上限
        momentum_min      : 5日モメンタム下限
        macd_condition    : MACD条件
        volatility_max    : ボラティリティ上限
    """
    if seed is not None:
        random.seed(seed)
        np.random.seed(seed)

    conditions = []
    seen = set()

    attempts = 0
    while len(conditions) < n and attempts < n * 3:
        attempts += 1

        cond = {
            "vol_ratio_min": round(np.random.uniform(1.5, 10.0), 1),
            "vol_zscore_min": round(np.random.uniform(0.5, 5.0), 1),
            "turnover_min": _log_uniform(5e7, 5e9),
            "market_cap_min": _log_uniform(5e9, 1e12),
            "market_cap_max": _log_uniform(1e10, 5e12),
            "trend_condition": random.choice(PARAM_SPACE["trend_condition"]),
            "price_position": random.choice(PARAM_SPACE["price_position"]),
            "holding_days": random.choice(PARAM_SPACE["holding_days"]),
            "rsi_min": random.choice([0, 20, 30, 40, 50]),
            "rsi_max": random.choice([60, 70, 80, 90, 100]),
            "momentum_min": round(np.random.uniform(-0.05, 0.15), 3),
            "macd_condition": random.choice(["none", "positive", "cross_up"]),
            "volatility_max": round(np.random.uniform(0.01, 0.08), 3),
        }

        for fkey, (flo, fhi) in FUNDAMENTAL_PARAMS.items():
            if random.random() < 0.5:
                if fkey.endswith("_max"):
                    cond[fkey] = round(np.random.uniform(flo, fhi), 2)
                else:
                    cond[fkey] = round(np.random.uniform(flo, fhi), 3)

        if cond["market_cap_min"] > cond["market_cap_max"]:
            cond["market_cap_min"], cond["market_cap_max"] = (
                cond["market_cap_max"], cond["market_cap_min"]
            )

        key = _condition_key(cond)
        if key not in seen:
            seen.add(key)
            conditions.append(cond)

    logger.info(f"Generated {len(conditions):,} unique conditions")
    return conditions


def _log_uniform(low: float, high: float) -> float:
    """対数スケールの一様分布からサンプリング"""
    return float(10 ** np.random.uniform(np.log10(low), np.log10(high)))


def _condition_key(cond: Dict) -> tuple:
    """条件の重複排除用ハッシュキー"""
    return (
        cond["vol_ratio_min"],
        cond["turnover_min"],
        cond["trend_condition"],
        cond["price_position"],
        cond["holding_days"],
    )


def apply_condition(df, cond: Dict) -> np.ndarray:
    """
    条件をDataFrameに適用し、シグナルが立つ行のbooleanマスクを返す。

    全条件はAND結合。高速化のためnumpy配列で処理。
    """
    mask = np.ones(len(df), dtype=bool)

    if "vol_ratio" in df.columns:
        mask &= (df["vol_ratio"].values >= cond["vol_ratio_min"])

    if "vol_zscore" in df.columns and cond.get("vol_zscore_min", 0) > 0:
        mask &= (df["vol_zscore"].values >= cond["vol_zscore_min"])

    if "Turnover" in df.columns:
        mask &= (df["Turnover"].values >= cond["turnover_min"])

    if "market_cap" in df.columns:
        mask &= (df["market_cap"].values >= cond["market_cap_min"])
        mask &= (df["market_cap"].values <= cond["market_cap_max"])

    tc = cond.get("trend_condition", "none")
    if tc == "ma5_above_ma25" and "ma5_above_ma25" in df.columns:
        mask &= (df["ma5_above_ma25"].values == 1)
    elif tc == "ma25_above_ma75" and "ma25_above_ma75" in df.columns:
        mask &= (df["ma25_above_ma75"].values == 1)
    elif tc == "ma5_above_ma25_above_ma75" and "full_uptrend" in df.columns:
        mask &= (df["full_uptrend"].values == 1)

    pp = cond.get("price_position", "none")
    if pp == "near_52w_high" and "near_52w_high" in df.columns:
        mask &= (df["near_52w_high"].values == 1)
    elif pp == "breakout_50d" and "breakout_50d" in df.columns:
        mask &= (df["breakout_50d"].values == 1)
    elif pp == "breakout_200d" and "breakout_200d" in df.columns:
        mask &= (df["breakout_200d"].values == 1)

    rsi_min = cond.get("rsi_min", 0)
    rsi_max = cond.get("rsi_max", 100)
    if "rsi" in df.columns and (rsi_min > 0 or rsi_max < 100):
        rsi_vals = df["rsi"].values
        mask &= (rsi_vals >= rsi_min) & (rsi_vals <= rsi_max)

    mom_min = cond.get("momentum_min", None)
    if mom_min is not None and "mom_5d" in df.columns:
        mask &= (df["mom_5d"].values >= mom_min)

    macd_cond = cond.get("macd_condition", "none")
    if macd_cond == "positive" and "macd" in df.columns:
        mask &= (df["macd"].values > 0)
    elif macd_cond == "cross_up" and "macd_hist" in df.columns:
        prev_hist = df.groupby("Code")["macd_hist"].shift(1)
        mask &= (df["macd_hist"].values > 0) & (prev_hist.values <= 0)

    vol_max = cond.get("volatility_max", None)
    if vol_max is not None and "volatility" in df.columns:
        mask &= (df["volatility"].values <= vol_max)

    # Fundamental filters
    _fund_min = {
        "revenue_growth_min": "revenue_growth",
        "eps_growth_min": "eps_growth",
        "roe_min": "roe",
        "op_margin_min": "op_margin",
        "equity_ratio_min": "equity_ratio",
    }
    _fund_max = {
        "per_max": "per",
        "pbr_max": "pbr",
    }
    for fkey, fcol in _fund_min.items():
        fval = cond.get(fkey)
        if fval is not None and fcol in df.columns:
            col_vals = df[fcol].values
            valid = ~np.isnan(col_vals)
            mask &= (~valid) | (col_vals >= fval)

    for fkey, fcol in _fund_max.items():
        fval = cond.get(fkey)
        if fval is not None and fcol in df.columns:
            col_vals = df[fcol].values
            valid = ~np.isnan(col_vals)
            mask &= (~valid) | (col_vals <= fval)

    nan_mask = True
    for col in ["next_open"]:
        if col in df.columns:
            nan_mask &= df[col].notna().values
    mask &= nan_mask

    return mask


def condition_to_str(cond: Dict) -> str:
    """条件を人間が読みやすい文字列に変換"""
    parts = [
        f"出来高倍率≥{cond['vol_ratio_min']}x",
        f"売買代金≥{cond['turnover_min']/1e8:.1f}億",
        f"時価総額:{cond['market_cap_min']/1e9:.0f}億-{cond['market_cap_max']/1e9:.0f}億",
    ]
    if cond.get("trend_condition") != "none":
        parts.append(f"トレンド:{cond['trend_condition']}")
    if cond.get("price_position") != "none":
        parts.append(f"価格位置:{cond['price_position']}")
    parts.append(f"保持:{cond['holding_days']}日")

    fund_labels = {
        "revenue_growth_min": "売上成長率≥",
        "eps_growth_min": "EPS成長率≥",
        "roe_min": "ROE≥",
        "op_margin_min": "営業利益率≥",
        "per_max": "PER≤",
        "pbr_max": "PBR≤",
        "equity_ratio_min": "自己資本比率≥",
    }
    for fkey, label in fund_labels.items():
        fval = cond.get(fkey)
        if fval is not None:
            if fkey in ("per_max", "pbr_max"):
                parts.append(f"{label}{fval:.1f}")
            else:
                parts.append(f"{label}{fval:.1%}")

    return " | ".join(parts)
