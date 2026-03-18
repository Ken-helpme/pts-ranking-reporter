"""
ファンダメンタル分析モジュール

決算サマリーデータからファンダメンタル指標を計算し、
スクリーニングフィルター・ヒットカウント分析を提供する。
"""
import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def compute_fundamental_features(
    df_prices: pd.DataFrame,
    df_fins: pd.DataFrame,
) -> pd.DataFrame:
    """
    決算サマリーデータからファンダメンタル指標を算出し、価格DataFrameにマージ。

    計算指標:
        revenue_growth  : YoY売上成長率
        eps_growth      : YoY EPS成長率
        op_growth       : YoY営業利益成長率
        roe             : 自己資本利益率
        op_margin       : 営業利益率
        per             : 株価収益率
        pbr             : 株価純資産倍率
        equity_ratio    : 自己資本比率
        debt_ratio      : 負債比率
    """
    if df_fins is None or df_fins.empty:
        logger.warning("No financial summary data available, skipping fundamental features")
        for col in ["revenue_growth", "eps_growth", "op_growth", "roe",
                     "op_margin", "per", "pbr", "equity_ratio", "debt_ratio"]:
            df_prices[col] = np.nan
        return df_prices

    df_f = df_fins.copy()

    code_col = "Code" if "Code" in df_f.columns else "LocalCode"
    df_f = df_f.rename(columns={code_col: "Code"})
    df_f["Code"] = df_f["Code"].astype(str).str[:4]

    date_col = None
    for c in ["DisclosedDate", "DisclosedUnixDate", "ReportDate"]:
        if c in df_f.columns:
            date_col = c
            break
    if date_col:
        df_f[date_col] = pd.to_datetime(df_f[date_col], errors="coerce")
        df_f = df_f.sort_values([code_col if code_col == "Code" else "Code", date_col])

    col_map = {
        "Sales": ["NetSales", "Revenue", "Sales"],
        "OP": ["OperatingProfit", "OperatingIncome", "OP"],
        "NP": ["Profit", "NetIncome", "NP"],
        "Eq": ["Equity", "ShareholdersEquity", "Eq"],
        "TA": ["TotalAssets", "TA"],
        "EPS": ["EarningsPerShare", "EPS"],
        "BPS": ["BookValuePerShare", "BPS"],
        "EqAR": ["EquityToAssetRatio", "EqAR"],
        "ShOutFY": ["NumberOfIssuedAndOutstandingSharesAtTheEndOfFiscalYearIncludingTreasuryStock",
                     "IssuedShares", "ShOutFY", "Shares"],
    }

    resolved = {}
    for target, candidates in col_map.items():
        for c in candidates:
            if c in df_f.columns:
                resolved[target] = c
                break

    fundamentals_rows = []
    for code, grp in df_f.groupby("Code"):
        grp = grp.sort_values(date_col) if date_col else grp
        if len(grp) == 0:
            continue

        latest = grp.iloc[-1]
        row = {"Code": code}

        sales = _safe_numeric(latest, resolved.get("Sales"))
        op = _safe_numeric(latest, resolved.get("OP"))
        np_val = _safe_numeric(latest, resolved.get("NP"))
        eq = _safe_numeric(latest, resolved.get("Eq"))
        ta = _safe_numeric(latest, resolved.get("TA"))
        eps = _safe_numeric(latest, resolved.get("EPS"))
        bps = _safe_numeric(latest, resolved.get("BPS"))
        eq_ar = _safe_numeric(latest, resolved.get("EqAR"))

        if len(grp) >= 2:
            prev = grp.iloc[-2]
            prev_sales = _safe_numeric(prev, resolved.get("Sales"))
            prev_eps = _safe_numeric(prev, resolved.get("EPS"))
            prev_op = _safe_numeric(prev, resolved.get("OP"))

            row["revenue_growth"] = _safe_growth(sales, prev_sales)
            row["eps_growth"] = _safe_growth(eps, prev_eps)
            row["op_growth"] = _safe_growth(op, prev_op)
        else:
            row["revenue_growth"] = np.nan
            row["eps_growth"] = np.nan
            row["op_growth"] = np.nan

        row["roe"] = (np_val / eq) if eq and eq > 0 and np_val is not None else np.nan
        row["op_margin"] = (op / sales) if sales and sales > 0 and op is not None else np.nan
        row["f_eps"] = eps
        row["f_bps"] = bps
        row["equity_ratio"] = eq_ar if eq_ar is not None else (
            (eq / ta) if ta and ta > 0 and eq is not None else np.nan
        )
        row["debt_ratio"] = ((ta - eq) / ta) if ta and ta > 0 and eq is not None else np.nan

        fundamentals_rows.append(row)

    if not fundamentals_rows:
        logger.warning("No fundamental rows computed")
        for col in ["revenue_growth", "eps_growth", "op_growth", "roe",
                     "op_margin", "per", "pbr", "equity_ratio", "debt_ratio"]:
            df_prices[col] = np.nan
        return df_prices

    df_fund = pd.DataFrame(fundamentals_rows)
    df_fund["Code"] = df_fund["Code"].astype(str)

    df_prices["Code"] = df_prices["Code"].astype(str)
    code_prefix = df_prices["Code"].str[:4]

    merge_key = "__merge_code__"
    df_prices[merge_key] = code_prefix
    df_fund[merge_key] = df_fund["Code"].astype(str).str[:4]

    fund_cols = [c for c in df_fund.columns if c not in ("Code",)]
    df_prices = df_prices.merge(df_fund[fund_cols], on=merge_key, how="left")

    if "f_eps" in df_prices.columns and "Close" in df_prices.columns:
        f_eps = pd.to_numeric(df_prices["f_eps"], errors="coerce")
        df_prices["per"] = df_prices["Close"] / f_eps.replace(0, np.nan)
    else:
        df_prices["per"] = np.nan

    if "f_bps" in df_prices.columns and "Close" in df_prices.columns:
        f_bps = pd.to_numeric(df_prices["f_bps"], errors="coerce")
        df_prices["pbr"] = df_prices["Close"] / f_bps.replace(0, np.nan)
    else:
        df_prices["pbr"] = np.nan

    df_prices.drop(columns=[merge_key, "f_eps", "f_bps"], errors="ignore", inplace=True)

    n_valid = df_prices["roe"].notna().sum()
    logger.info(f"Fundamental features merged: {n_valid:,}/{len(df_prices):,} rows have ROE data")

    return df_prices


def apply_fundamental_filter(df: pd.DataFrame, cond: dict) -> pd.Series:
    """
    ファンダメンタル条件をブールマスクとして適用。

    cond にファンダメンタルキーが存在する場合のみフィルタリング。
    存在しない列はスキップ（True扱い）。
    """
    mask = pd.Series(True, index=df.index)

    min_filters = {
        "revenue_growth_min": "revenue_growth",
        "eps_growth_min": "eps_growth",
        "roe_min": "roe",
        "op_margin_min": "op_margin",
        "equity_ratio_min": "equity_ratio",
    }
    max_filters = {
        "per_max": "per",
        "pbr_max": "pbr",
    }

    for cond_key, col_name in min_filters.items():
        if cond_key in cond and col_name in df.columns:
            val = cond[cond_key]
            if val is not None:
                mask &= (df[col_name] >= val) | df[col_name].isna()

    for cond_key, col_name in max_filters.items():
        if cond_key in cond and col_name in df.columns:
            val = cond[cond_key]
            if val is not None:
                mask &= (df[col_name] <= val) | df[col_name].isna()

    return mask


def analyze_hit_counts(
    df: pd.DataFrame,
    signal_mask: pd.Series,
) -> dict:
    """
    シグナルのヒット数を日・月・年単位で分析。

    Returns:
        dict with avg_daily_hits, avg_monthly_hits, avg_yearly_hits, monthly_median
    """
    hits = df.loc[signal_mask].copy()

    if hits.empty or "Date" not in hits.columns:
        return {
            "avg_daily_hits": 0.0,
            "avg_monthly_hits": 0.0,
            "avg_yearly_hits": 0.0,
            "monthly_median": 0.0,
        }

    hits["Date"] = pd.to_datetime(hits["Date"], errors="coerce")

    daily = hits.groupby(hits["Date"].dt.date).size()
    monthly = hits.groupby(hits["Date"].dt.to_period("M")).size()
    yearly = hits.groupby(hits["Date"].dt.year).size()

    return {
        "avg_daily_hits": float(daily.mean()) if len(daily) > 0 else 0.0,
        "avg_monthly_hits": float(monthly.mean()) if len(monthly) > 0 else 0.0,
        "avg_yearly_hits": float(yearly.mean()) if len(yearly) > 0 else 0.0,
        "monthly_median": float(monthly.median()) if len(monthly) > 0 else 0.0,
    }


def tighten_conditions(
    condition: dict,
    df: pd.DataFrame,
    target_monthly: float = 10.0,
) -> dict:
    """
    月間ヒット数が多すぎる場合、条件を自動強化。
    vol_ratio_min を段階的に引き上げ、ファンダメンタルフィルターを追加。
    """
    from .screener import apply_condition
    cond = condition.copy()

    for _ in range(20):
        mask = apply_condition(df, cond)
        fund_mask = apply_fundamental_filter(df, cond)
        combined = mask & fund_mask
        stats = analyze_hit_counts(df, combined)

        if stats["avg_monthly_hits"] <= target_monthly:
            break

        if cond.get("volume_ratio_min", 1.5) < 8.0:
            cond["volume_ratio_min"] = cond.get("volume_ratio_min", 1.5) * 1.2
        elif "roe_min" not in cond:
            cond["roe_min"] = 0.10
        elif "revenue_growth_min" not in cond:
            cond["revenue_growth_min"] = 0.10
        else:
            cond["volume_ratio_min"] = cond.get("volume_ratio_min", 1.5) * 1.1
            if "roe_min" in cond:
                cond["roe_min"] = min(cond["roe_min"] + 0.02, 0.30)

    return cond


def _safe_numeric(row, col_name):
    if col_name is None:
        return None
    try:
        v = row[col_name]
        if pd.isna(v):
            return None
        return float(v)
    except (KeyError, TypeError, ValueError):
        return None


def _safe_growth(current, previous):
    if current is None or previous is None or previous == 0:
        return np.nan
    return (current - previous) / abs(previous)
