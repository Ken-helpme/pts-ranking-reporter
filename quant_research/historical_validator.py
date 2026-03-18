"""
過去時点スクリーニング検証モジュール

過去の特定時点でスクリーニングを実行し、
その後のパフォーマンスを分析することで戦略の有効性を検証する。
未来データのリーク（ルックアヘッドバイアス）を防止。
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .screener import apply_condition, condition_to_str
from .fundamental import apply_fundamental_filter

logger = logging.getLogger(__name__)


def run_point_in_time_screening(
    df: pd.DataFrame,
    condition: Dict,
    screening_dates: List[str],
    forward_days: List[int] = None,
) -> Dict:
    """
    過去の特定時点でスクリーニングを実行し、その後のパフォーマンスを追跡。

    Args:
        df: 全特徴量付きDataFrame（Date, Code, Close等を含む）
        condition: スクリーニング条件辞書
        screening_dates: スクリーニングを実行する日付リスト (YYYY-MM-DD)
        forward_days: パフォーマンス追跡日数 [20, 60, 120]

    Returns:
        検証結果辞書（各時点のヒット銘柄とパフォーマンス）
    """
    if forward_days is None:
        forward_days = [20, 60, 120]

    df = df.copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.sort_values(["Code", "Date"])

    results = []

    for screen_date_str in screening_dates:
        screen_date = pd.Timestamp(screen_date_str)

        available_dates = df["Date"].unique()
        past_dates = [d for d in available_dates if d <= screen_date]
        if not past_dates:
            logger.warning(f"No data available for {screen_date_str}")
            results.append({
                "screening_date": screen_date_str,
                "n_hits": 0,
                "stocks": [],
                "error": "No data available",
            })
            continue

        actual_date = max(past_dates)

        df_at_date = df[df["Date"] == actual_date].copy()

        mask = apply_condition(df_at_date, condition)
        fund_mask = apply_fundamental_filter(df_at_date, condition)
        combined_mask = mask & fund_mask.values

        hits = df_at_date[combined_mask].copy()

        if hits.empty:
            results.append({
                "screening_date": screen_date_str,
                "actual_date": str(actual_date.date()) if hasattr(actual_date, 'date') else str(actual_date),
                "n_hits": 0,
                "stocks": [],
            })
            continue

        stock_results = []
        for _, row in hits.iterrows():
            code = row["Code"]
            entry_price = row["Close"]
            vol_ratio = row.get("vol_ratio", np.nan)
            market_cap = row.get("market_cap", np.nan)

            future_data = df[(df["Code"] == code) & (df["Date"] > actual_date)].sort_values("Date")

            stock_perf = {
                "code": str(code),
                "entry_price": float(entry_price),
                "vol_ratio": round(float(vol_ratio), 2) if pd.notna(vol_ratio) else None,
                "market_cap": float(market_cap) if pd.notna(market_cap) else None,
                "roe": round(float(row.get("roe", np.nan)), 4) if pd.notna(row.get("roe")) else None,
                "revenue_growth": round(float(row.get("revenue_growth", np.nan)), 4) if pd.notna(row.get("revenue_growth")) else None,
                "per": round(float(row.get("per", np.nan)), 2) if pd.notna(row.get("per")) else None,
                "pbr": round(float(row.get("pbr", np.nan)), 2) if pd.notna(row.get("pbr")) else None,
                "op_margin": round(float(row.get("op_margin", np.nan)), 4) if pd.notna(row.get("op_margin")) else None,
            }

            for fd in forward_days:
                if len(future_data) >= fd:
                    future_close = future_data.iloc[fd - 1]["Close"]
                    ret = (future_close - entry_price) / entry_price
                    stock_perf[f"return_{fd}d"] = round(float(ret), 4)
                else:
                    stock_perf[f"return_{fd}d"] = None

            if not future_data.empty:
                max_close = future_data["Close"].max()
                min_close = future_data["Close"].min()
                stock_perf["max_upside"] = round(float((max_close - entry_price) / entry_price), 4)
                stock_perf["max_downside"] = round(float((min_close - entry_price) / entry_price), 4)
            else:
                stock_perf["max_upside"] = None
                stock_perf["max_downside"] = None

            stock_results.append(stock_perf)

        results.append({
            "screening_date": screen_date_str,
            "actual_date": str(actual_date.date()) if hasattr(actual_date, 'date') else str(actual_date),
            "n_hits": len(stock_results),
            "stocks": stock_results,
        })

    return {
        "condition": condition,
        "condition_str": condition_to_str(condition),
        "screening_dates": screening_dates,
        "forward_days": forward_days,
        "results": results,
    }


def compute_win_rate_analysis(validation_result: Dict) -> Dict:
    """
    検証結果から勝率分析を実行。

    各保有期間・閾値での勝率を算出。
    """
    forward_days = validation_result.get("forward_days", [20, 60, 120])
    thresholds = [0.0, 0.05, 0.10, 0.20]

    all_stocks = []
    for period_result in validation_result.get("results", []):
        for stock in period_result.get("stocks", []):
            stock["screening_date"] = period_result["screening_date"]
            all_stocks.append(stock)

    if not all_stocks:
        return {"message": "No stocks found across all screening dates", "total_stocks": 0}

    analysis = {
        "total_stocks_screened": len(all_stocks),
        "by_period": {},
    }

    for fd in forward_days:
        ret_key = f"return_{fd}d"
        returns = [s[ret_key] for s in all_stocks if s.get(ret_key) is not None]

        if not returns:
            continue

        returns_arr = np.array(returns)
        period_stats = {
            "n_with_data": len(returns),
            "mean_return": round(float(np.mean(returns_arr)), 4),
            "median_return": round(float(np.median(returns_arr)), 4),
            "std_return": round(float(np.std(returns_arr)), 4),
            "max_return": round(float(np.max(returns_arr)), 4),
            "min_return": round(float(np.min(returns_arr)), 4),
        }

        for thresh in thresholds:
            pct = float(np.sum(returns_arr >= thresh)) / len(returns_arr)
            label = f"win_rate_{int(thresh * 100)}pct" if thresh > 0 else "win_rate_positive"
            period_stats[label] = round(pct, 4)

        analysis["by_period"][f"{fd}d"] = period_stats

    return analysis


def analyze_winners_vs_losers(validation_result: Dict, holding_days: int = 60) -> Dict:
    """
    上昇銘柄 vs 下落銘柄のファンダメンタル比較分析。
    """
    ret_key = f"return_{holding_days}d"

    winners = []
    losers = []

    for period_result in validation_result.get("results", []):
        for stock in period_result.get("stocks", []):
            ret = stock.get(ret_key)
            if ret is None:
                continue
            if ret > 0:
                winners.append(stock)
            else:
                losers.append(stock)

    def _avg_metric(stocks, key):
        vals = [s[key] for s in stocks if s.get(key) is not None]
        return round(float(np.mean(vals)), 4) if vals else None

    fund_keys = ["roe", "revenue_growth", "per", "pbr", "op_margin", "vol_ratio", "market_cap"]

    comparison = {}
    for key in fund_keys:
        comparison[key] = {
            "winners_avg": _avg_metric(winners, key),
            "losers_avg": _avg_metric(losers, key),
        }
        w = _avg_metric(winners, key)
        l = _avg_metric(losers, key)
        if w is not None and l is not None and l != 0:
            comparison[key]["difference"] = round(w - l, 4)

    return {
        "holding_days": holding_days,
        "n_winners": len(winners),
        "n_losers": len(losers),
        "win_rate": round(len(winners) / max(len(winners) + len(losers), 1), 4),
        "comparison": comparison,
    }


def get_top_examples(
    validation_result: Dict,
    holding_days: int = 60,
    n_success: int = 10,
    n_failure: int = 5,
) -> Dict:
    """
    成功例・失敗例を具体的に抽出。
    """
    ret_key = f"return_{holding_days}d"

    all_stocks = []
    for period_result in validation_result.get("results", []):
        for stock in period_result.get("stocks", []):
            stock_copy = stock.copy()
            stock_copy["screening_date"] = period_result.get("screening_date", "")
            stock_copy["actual_date"] = period_result.get("actual_date", "")
            all_stocks.append(stock_copy)

    stocks_with_return = [s for s in all_stocks if s.get(ret_key) is not None]

    if not stocks_with_return:
        return {"success_examples": [], "failure_examples": []}

    sorted_by_return = sorted(stocks_with_return, key=lambda s: s[ret_key], reverse=True)

    success = sorted_by_return[:n_success]
    failure = sorted_by_return[-n_failure:]

    return {
        "holding_days": holding_days,
        "success_examples": success,
        "failure_examples": failure,
    }


def compute_hit_count_stats(validation_result: Dict) -> Dict:
    """
    各時点のヒット銘柄数統計。
    """
    counts = [r["n_hits"] for r in validation_result.get("results", [])]

    if not counts:
        return {"message": "No screening results"}

    return {
        "avg_hits": round(float(np.mean(counts)), 1),
        "median_hits": round(float(np.median(counts)), 1),
        "max_hits": int(np.max(counts)),
        "min_hits": int(np.min(counts)),
        "total_screenings": len(counts),
        "counts_by_date": {
            r["screening_date"]: r["n_hits"]
            for r in validation_result.get("results", [])
        },
    }


def generate_validation_summary(
    validation_result: Dict,
    win_analysis: Dict,
    winners_losers: Dict,
    examples: Dict,
    hit_stats: Dict,
) -> Dict:
    """
    全検証結果を最終結論としてまとめる。
    """
    best_period = None
    best_return = -float("inf")
    for period_key, stats in win_analysis.get("by_period", {}).items():
        mean_ret = stats.get("mean_return", 0)
        if mean_ret > best_return:
            best_return = mean_ret
            best_period = period_key

    return {
        "strategy_condition": validation_result.get("condition_str", ""),
        "total_stocks_screened": win_analysis.get("total_stocks_screened", 0),
        "actual_win_rate": win_analysis.get("by_period", {}).get(
            best_period or "60d", {}
        ).get("win_rate_positive", 0),
        "average_return": best_return if best_return > -float("inf") else 0,
        "best_holding_period": best_period,
        "win_rate_by_period": {
            k: v.get("win_rate_positive", 0)
            for k, v in win_analysis.get("by_period", {}).items()
        },
        "avg_return_by_period": {
            k: v.get("mean_return", 0)
            for k, v in win_analysis.get("by_period", {}).items()
        },
        "hit_count_stats": hit_stats,
        "winner_characteristics": winners_losers.get("comparison", {}),
        "n_success_examples": len(examples.get("success_examples", [])),
        "top_success": examples.get("success_examples", [])[:3],
        "improvements": _suggest_improvements(win_analysis, winners_losers),
    }


def _suggest_improvements(win_analysis: Dict, winners_losers: Dict) -> List[str]:
    """検証結果から改善点を提案"""
    suggestions = []

    for period_key, stats in win_analysis.get("by_period", {}).items():
        wr = stats.get("win_rate_positive", 0)
        if wr < 0.55:
            suggestions.append(
                f"{period_key}の勝率が{wr:.1%}と低い。出来高倍率閾値を上げるか、"
                "トレンドフィルターを厳格化してください。"
            )

    comp = winners_losers.get("comparison", {})
    roe_diff = comp.get("roe", {}).get("difference")
    if roe_diff is not None and roe_diff > 0.03:
        suggestions.append(
            f"上昇銘柄はROEが平均{roe_diff:.1%}ポイント高い。ROEフィルターの追加が有効。"
        )

    rev_diff = comp.get("revenue_growth", {}).get("difference")
    if rev_diff is not None and rev_diff > 0.05:
        suggestions.append(
            f"上昇銘柄は売上成長率が平均{rev_diff:.1%}ポイント高い。成長率フィルターの強化が有効。"
        )

    if not suggestions:
        suggestions.append("現在の条件は概ね有効です。定期的な再最適化を推奨します。")

    return suggestions


def run_full_historical_validation(
    df: pd.DataFrame,
    condition: Dict,
    months_back: List[int] = None,
    forward_days: List[int] = None,
) -> Dict:
    """
    過去検証のフルパイプラインを実行。

    Args:
        df: 全特徴量付きDataFrame
        condition: 検証する条件
        months_back: 何ヶ月前の時点を検証するか [3, 6, 12, 24]
        forward_days: パフォーマンス追跡日数 [20, 60, 120]
    """
    if months_back is None:
        months_back = [3, 6, 12]
    if forward_days is None:
        forward_days = [20, 60, 120]

    now = pd.Timestamp.now()
    screening_dates = []
    for m in months_back:
        dt = now - pd.DateOffset(months=m)
        screening_dates.append(dt.strftime("%Y-%m-%d"))

    logger.info(f"Running historical validation at {len(screening_dates)} time points...")
    logger.info(f"  Dates: {screening_dates}")
    logger.info(f"  Condition: {condition_to_str(condition)}")

    validation = run_point_in_time_screening(
        df, condition, screening_dates, forward_days
    )

    total_hits = sum(r["n_hits"] for r in validation["results"])
    logger.info(f"  Total hits across all dates: {total_hits}")

    win_analysis = compute_win_rate_analysis(validation)
    logger.info(f"  Win rate analysis computed")

    winners_losers = analyze_winners_vs_losers(validation, holding_days=forward_days[1] if len(forward_days) > 1 else forward_days[0])
    logger.info(f"  Winners vs losers: {winners_losers['n_winners']} W / {winners_losers['n_losers']} L")

    examples = get_top_examples(validation, holding_days=forward_days[1] if len(forward_days) > 1 else forward_days[0])

    hit_stats = compute_hit_count_stats(validation)

    summary = generate_validation_summary(
        validation, win_analysis, winners_losers, examples, hit_stats
    )

    logger.info(f"  Best holding period: {summary['best_holding_period']}")
    logger.info(f"  Overall win rate: {summary['actual_win_rate']:.1%}")

    return {
        "validation": validation,
        "win_analysis": win_analysis,
        "winners_vs_losers": winners_losers,
        "examples": examples,
        "hit_stats": hit_stats,
        "summary": summary,
    }
