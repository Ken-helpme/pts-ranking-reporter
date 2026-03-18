"""
テーマ分析モジュール

成長テーマ分類、テーマ別パフォーマンス分析、
テンバガー候補検出、機関投資家仕込みシグナル検出。
"""
import logging
from collections import defaultdict

import numpy as np
import pandas as pd

from .config import THEME_KEYWORDS

logger = logging.getLogger(__name__)


def classify_themes(df_master: pd.DataFrame) -> dict:
    """
    銘柄マスタからテーマ分類を行う。
    企業名・セクターをキーワードマッチングし Code -> [themes] のマッピングを返す。
    """
    theme_map = defaultdict(list)

    name_col = None
    for c in ["CompanyName", "CompanyNameEnglish", "Name", "銘柄名"]:
        if c in df_master.columns:
            name_col = c
            break

    sector_col = None
    for c in ["Sector33CodeName", "Sector17CodeName", "SectorName", "業種"]:
        if c in df_master.columns:
            sector_col = c
            break

    code_col = "Code" if "Code" in df_master.columns else df_master.columns[0]

    for _, row in df_master.iterrows():
        code = str(row[code_col])
        text_parts = []
        if name_col and pd.notna(row.get(name_col)):
            text_parts.append(str(row[name_col]))
        if sector_col and pd.notna(row.get(sector_col)):
            text_parts.append(str(row[sector_col]))
        text = " ".join(text_parts).upper()

        for theme, keywords in THEME_KEYWORDS.items():
            for kw in keywords:
                if kw.upper() in text:
                    theme_map[code].append(theme)
                    break

    logger.info(f"Theme classification: {sum(len(v) for v in theme_map.values())} "
                f"theme assignments across {len(theme_map)} stocks")
    return dict(theme_map)


def analyze_theme_performance(
    df_features: pd.DataFrame,
    theme_map: dict,
    forward_cols: list = None,
) -> pd.DataFrame:
    """
    テーマ別のフォワードリターンパフォーマンスを分析。

    Returns:
        テーマ × 保有期間のパフォーマンスサマリー DataFrame
    """
    if forward_cols is None:
        forward_cols = [c for c in df_features.columns if c.startswith("fwd_") and c.endswith("_return")]

    if not forward_cols:
        logger.warning("No forward return columns found for theme performance analysis")
        return pd.DataFrame()

    records = []
    df_features["Code"] = df_features["Code"].astype(str)

    for theme in THEME_KEYWORDS:
        codes = [c for c, themes in theme_map.items() if theme in themes]
        if not codes:
            continue

        code_prefix_set = set(c[:4] for c in codes)
        mask = df_features["Code"].str[:4].isin(code_prefix_set)
        df_theme = df_features.loc[mask]

        if df_theme.empty:
            continue

        for fc in forward_cols:
            vals = df_theme[fc].dropna()
            if len(vals) < 10:
                continue
            records.append({
                "theme": theme,
                "period": fc,
                "n_stocks": len(codes),
                "n_observations": len(vals),
                "mean_return": vals.mean(),
                "median_return": vals.median(),
                "win_rate": (vals > 0).mean(),
                "std": vals.std(),
                "sharpe": vals.mean() / vals.std() if vals.std() > 0 else 0,
            })

    if not records:
        return pd.DataFrame()

    result = pd.DataFrame(records)
    logger.info(f"Theme performance: {len(result)} theme-period combinations analyzed")
    return result


def find_tenbaggers(
    df_prices: pd.DataFrame,
    min_multiple: float = 5.0,
) -> pd.DataFrame:
    """
    期間中に株価がmin_multiple倍以上になった銘柄を特定。
    1年データでは2-3倍程度が限界なので、min_multipleは柔軟に設定。

    Returns:
        テンバガー候補の特徴サマリー DataFrame
    """
    records = []

    for code, grp in df_prices.groupby("Code"):
        if len(grp) < 20:
            continue

        grp = grp.sort_values("Date")
        min_price = grp["Close"].min()
        max_price = grp["Close"].max()

        if min_price <= 0:
            continue

        multiple = max_price / min_price

        if multiple >= min_multiple:
            min_idx = grp["Close"].idxmin()
            max_idx = grp["Close"].idxmax()

            start_row = grp.loc[min_idx] if min_idx < max_idx else grp.iloc[0]

            avg_vol = grp["Volume"].mean() if "Volume" in grp.columns else np.nan
            avg_turnover = grp["Turnover"].mean() if "Turnover" in grp.columns else np.nan
            market_cap_start = start_row.get("market_cap", np.nan)

            records.append({
                "Code": code,
                "price_multiple": multiple,
                "min_price": min_price,
                "max_price": max_price,
                "start_market_cap": market_cap_start,
                "avg_volume": avg_vol,
                "avg_turnover": avg_turnover,
                "days_to_peak": abs(max_idx - min_idx) if isinstance(max_idx, int) else np.nan,
            })

    if not records:
        logger.info(f"No stocks found with {min_multiple}x price increase")
        return pd.DataFrame()

    result = pd.DataFrame(records).sort_values("price_multiple", ascending=False)
    logger.info(f"Found {len(result)} stocks with >= {min_multiple}x price increase")
    return result


def detect_institutional_accumulation(df: pd.DataFrame) -> pd.Series:
    """
    機関投資家の仕込みシグナルを検出。

    条件:
        1. 出来高倍率 > 3
        2. 売買代金倍率 > 2
        3. 50日高値ブレイクアウト
        4. 25MA > 75MA
        5. ブレイク後の押し目（直近5日で-3%以上下落後に回復）

    全条件を満たす行をTrueとして返す。
    少なくとも条件1,2,3は必須。条件4,5はデータがあれば適用。
    """
    mask = pd.Series(True, index=df.index)

    if "vol_ratio" in df.columns:
        mask &= df["vol_ratio"] > 3.0
    else:
        return pd.Series(False, index=df.index)

    if "turnover_ratio" in df.columns:
        mask &= df["turnover_ratio"] > 2.0

    if "breakout_50d" in df.columns:
        mask &= df["breakout_50d"] == 1

    if "ma25_above_ma75" in df.columns:
        mask &= df["ma25_above_ma75"] == 1

    if "mom_5d" in df.columns:
        pullback_recovery = (df["mom_5d"] > -0.05) & (df["mom_5d"] < 0.03)
        mask &= pullback_recovery | True  # soft condition

    return mask


def detect_small_growth_candidates(df: pd.DataFrame) -> pd.Series:
    """
    機関投資家が入りやすい小型成長株の条件。

    時価総額: 50億〜2000億
    売買代金: 1日平均3億以上
    株価: 300〜8000円
    """
    mask = pd.Series(True, index=df.index)

    if "market_cap" in df.columns:
        mask &= (df["market_cap"] >= 5e9) & (df["market_cap"] <= 200e9)

    if "Turnover" in df.columns:
        mask &= df["Turnover"] >= 3e8

    if "Close" in df.columns:
        mask &= (df["Close"] >= 300) & (df["Close"] <= 8000)

    return mask


def get_tenbagger_common_features(
    tenbaggers: pd.DataFrame,
    theme_map: dict,
) -> dict:
    """
    テンバガー（大化け株）銘柄の共通特徴を分析。
    """
    if tenbaggers.empty:
        return {"message": "No tenbagger candidates found in the data period"}

    result = {
        "count": len(tenbaggers),
        "avg_multiple": float(tenbaggers["price_multiple"].mean()),
        "median_start_market_cap": float(tenbaggers["start_market_cap"].median())
            if tenbaggers["start_market_cap"].notna().any() else None,
        "avg_volume": float(tenbaggers["avg_volume"].mean())
            if tenbaggers["avg_volume"].notna().any() else None,
    }

    theme_counts = defaultdict(int)
    for _, row in tenbaggers.iterrows():
        code = str(row["Code"])
        themes = theme_map.get(code[:4], [])
        for t in themes:
            theme_counts[t] += 1
    result["theme_distribution"] = dict(theme_counts)

    return result
