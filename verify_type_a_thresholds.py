#!/usr/bin/env python3
"""
Type A "Quiet Accumulation" 閾値検証スクリプト

ロールモデル銘柄（Type A: ベースからの初動型）の理想検知日における
各テクニカル指標のactual値を抽出し、最適な閾値を特定する。

Usage:
    python verify_type_a_thresholds.py

Environment:
    JQUANTS_REFRESH_TOKEN or JQUANTS_API_KEY
"""

import os
import sys
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple


# ============================================================
# Configuration
# ============================================================

ROLE_MODELS = [
    {"name": "JX金属",  "code": "50160", "target_date": "2025-08-14"},
    {"name": "サンリオ", "code": "81360", "target_date": "2024-07-29"},
    {"name": "バイセル", "code": "76850", "target_date": "2024-08-20"},
    {"name": "FFRI",    "code": "36920", "target_date": "2025-03-14"},
]

VOL_WINDOWS: List[Tuple[int, int]] = [
    (3, 7), (5, 5), (5, 10), (7, 7), (7, 14), (10, 10),
]

WINDOW_DAYS = 3

TEMP_THRESHOLDS = {
    "vol_ratio_min": 1.15,
    "vol_ratio_max": 2.0,
    "max_daily_ret_5d": 0.07,
    "cum_ret_5d": 0.20,
    "bw_prior_percentile_max": 0.30,
}

BASE_URL = "https://api.jquants.com/v2"


# ============================================================
# J-Quants API
# ============================================================

def get_api_key() -> str:
    """環境変数からJ-Quants APIキーを取得"""
    key = os.getenv("JQUANTS_REFRESH_TOKEN") or os.getenv("JQUANTS_API_KEY")
    if not key:
        print("ERROR: JQUANTS_REFRESH_TOKEN または JQUANTS_API_KEY を設定してください")
        sys.exit(1)
    return key


def _api_get(session: requests.Session, path: str, params: dict) -> dict:
    """J-Quants APIへのGETリクエスト（429リトライ付き）"""
    url = f"{BASE_URL}{path}"
    for attempt in range(3):
        try:
            resp = session.get(url, params=params, timeout=30)
            if resp.status_code == 429:
                wait = (attempt + 1) * 5
                print(f"  Rate limit (429), {wait}秒待機...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            print(f"  API error (attempt {attempt + 1}/3): {e}")
            if attempt < 2:
                time.sleep(3)
    return {}


def fetch_daily_bars(code: str, from_date: str, to_date: str,
                     api_key: str) -> pd.DataFrame:
    """J-Quants APIから日足OHLCVを取得し、正規化されたDataFrameで返す"""
    session = requests.Session()
    session.headers.update({"x-api-key": api_key})

    all_records: list = []
    params: dict = {"code": code, "from": from_date, "to": to_date}

    while True:
        result = _api_get(session, "/equities/bars/daily", params)
        records = result.get("data", result.get("daily_quotes", []))
        all_records.extend(records)
        pkey = result.get("pagination_key")
        if not pkey:
            break
        params["pagination_key"] = pkey

    if not all_records:
        return pd.DataFrame()

    df = pd.DataFrame(all_records)
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").reset_index(drop=True)

    def _pick(frame: pd.DataFrame, candidates: list) -> pd.Series:
        for c in candidates:
            if c in frame.columns and frame[c].notna().any():
                return pd.to_numeric(frame[c], errors="coerce")
        return pd.Series(np.nan, index=frame.index)

    df["Close"]  = _pick(df, ["AdjC", "AdjustmentClose", "C", "Close"])
    df["Volume"] = _pick(df, ["AdjVo", "AdjustmentVolume", "Vo", "Volume"])

    return (
        df[["Date", "Close", "Volume"]]
        .dropna(subset=["Close"])
        .reset_index(drop=True)
    )


# ============================================================
# Indicator computation
# ============================================================

def _rolling_pct_rank(arr: np.ndarray) -> float:
    """ウィンドウ末尾値のパーセンタイル順位（0〜1）を返す"""
    if len(arr) < 2 or np.isnan(arr[-1]):
        return np.nan
    valid = ~np.isnan(arr)
    n_valid = np.sum(valid)
    if n_valid < 2:
        return np.nan
    return float(np.nansum(arr <= arr[-1])) / n_valid


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """全5条件に必要なテクニカル指標を計算して列を追加する"""
    close = df["Close"]
    volume = df["Volume"]

    for p in [5, 25, 75]:
        df[f"ma{p}"] = close.rolling(p, min_periods=p).mean()

    # Condition 1: Volume ratios (6 window patterns)
    for n1, n2 in VOL_WINDOWS:
        recent = volume.rolling(n1, min_periods=n1).mean()
        prior = volume.shift(n1).rolling(n2, min_periods=n2).mean()
        df[f"vol_ratio_{n1}_{n2}"] = recent / prior.replace(0, np.nan)

    # Condition 2: Price position
    df["price_vs_ma25"] = close / df["ma25"]
    df["price_vs_ma75"] = close / df["ma75"]
    df["ma5_gt_ma25"] = df["ma5"] > df["ma25"]

    # Condition 3: Surge exclusion
    daily_ret = close.pct_change()
    df["max_daily_ret_5d"] = daily_ret.rolling(5, min_periods=1).max()
    df["cum_ret_5d"] = close / close.shift(5) - 1

    # Condition 4: Bollinger Band squeeze → expansion (period=25, σ=2)
    bb_mid = close.rolling(25, min_periods=25).mean()
    bb_std = close.rolling(25, min_periods=25).std(ddof=0)
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std
    df["bb_width"] = (bb_upper - bb_lower) / bb_mid.replace(0, np.nan)

    df["bw_recent"] = df["bb_width"].rolling(5, min_periods=5).mean()
    df["bw_prior"] = df["bb_width"].shift(5).rolling(5, min_periods=5).mean()
    df["bw_expanding"] = df["bw_recent"] > df["bw_prior"]

    # ⚠ Percentile uses the value from 5 days ago, not today
    shifted_bw = df["bb_width"].shift(5)
    df["bw_prior_percentile"] = shifted_bw.rolling(
        60, min_periods=30
    ).apply(_rolling_pct_rank, raw=True)

    # Condition 5: MA25 slope
    df["slope_25"] = df["ma25"] - df["ma25"].shift(5)

    return df


# ============================================================
# Window extraction & best-day selection
# ============================================================

def extract_window(df: pd.DataFrame, target_date_str: str,
                   window: int = WINDOW_DAYS) -> Tuple[pd.DataFrame, str]:
    """ターゲット日を中心に±window営業日を抽出する。休場日は直近営業日にフォールバック"""
    target = pd.Timestamp(target_date_str)
    dates = df["Date"].values

    diffs = np.abs(dates - np.datetime64(target))
    nearest_idx = int(np.argmin(diffs))
    actual_target = pd.Timestamp(dates[nearest_idx])
    if actual_target != target:
        print(f"  ターゲット日 {target_date_str} → "
              f"{actual_target.strftime('%Y-%m-%d')} にフォールバック")

    start = max(0, nearest_idx - window)
    end = min(len(df) - 1, nearest_idx + window)
    window_df = df.iloc[start:end + 1].copy().reset_index(drop=True)
    return window_df, actual_target.strftime("%Y-%m-%d")


def evaluate_conditions(row: pd.Series,
                        vol_col: str) -> Dict[str, bool]:
    """仮閾値で5条件のpass/failを判定"""
    vr = row.get(vol_col, np.nan)
    c1 = bool(
        pd.notna(vr)
        and TEMP_THRESHOLDS["vol_ratio_min"] <= vr <= TEMP_THRESHOLDS["vol_ratio_max"]
    )

    c2 = bool(
        row.get("price_vs_ma25", 0) > 1.0
        and row.get("price_vs_ma75", 0) > 0.97
        and row.get("ma5_gt_ma25", False)
    )

    mdr = row.get("max_daily_ret_5d", np.nan)
    cr = row.get("cum_ret_5d", np.nan)
    c3 = bool(
        pd.notna(mdr)
        and mdr <= TEMP_THRESHOLDS["max_daily_ret_5d"]
        and pd.notna(cr)
        and cr <= TEMP_THRESHOLDS["cum_ret_5d"]
    )

    bwp = row.get("bw_prior_percentile", np.nan)
    c4 = bool(
        row.get("bw_expanding", False)
        and pd.notna(bwp)
        and bwp <= TEMP_THRESHOLDS["bw_prior_percentile_max"]
    )

    c5 = bool(pd.notna(row.get("slope_25")) and row["slope_25"] > 0)

    return {
        "cond1_vol": c1,
        "cond2_price": c2,
        "cond3_surge": c3,
        "cond4_bb": c4,
        "cond5_slope": c5,
    }


def find_best_day(window_df: pd.DataFrame, actual_target: str,
                  vol_col: str) -> pd.Series:
    """ウィンドウ内で最も多くの条件を満たす日を返す。同スコアならターゲット日に近い方を優先"""
    target_ts = pd.Timestamp(actual_target)
    best_row: Optional[pd.Series] = None
    best_score, best_dist = -1, float("inf")

    for _, row in window_df.iterrows():
        score = sum(evaluate_conditions(row, vol_col).values())
        dist = abs((row["Date"] - target_ts).days)
        if score > best_score or (score == best_score and dist < best_dist):
            best_row = row.copy()
            best_score = score
            best_dist = dist

    return best_row  # type: ignore[return-value]


def find_recommended_vol_window(
    best_days: List[pd.Series],
) -> Tuple[str, float]:
    """ベスト日データから変動係数(CV)が最小の出来高ウィンドウを推奨する"""
    best_cv: float = float("inf")
    best_col: Optional[str] = None

    for n1, n2 in VOL_WINDOWS:
        col = f"vol_ratio_{n1}_{n2}"
        vals = [float(d[col]) for d in best_days if pd.notna(d.get(col))]
        if len(vals) < 2:
            continue
        mean_v = np.mean(vals)
        cv = float(np.std(vals, ddof=1) / mean_v) if mean_v > 0 else float("inf")
        if cv < best_cv:
            best_cv, best_col = cv, col

    return (best_col or "vol_ratio_5_10"), best_cv


# ============================================================
# Output builders
# ============================================================

def build_output_a(stock_windows: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """出力A: 各銘柄×各日のactual値一覧テーブル"""
    rows: list = []
    for name, wdf in stock_windows.items():
        for _, r in wdf.iterrows():
            row: dict = {
                "銘柄名": name,
                "日付": r["Date"].strftime("%Y-%m-%d"),
                "終値": r["Close"],
            }
            for n1, n2 in VOL_WINDOWS:
                row[f"vol_ratio_{n1}_{n2}"] = r.get(f"vol_ratio_{n1}_{n2}")
            for col in [
                "price_vs_ma25", "price_vs_ma75", "ma5_gt_ma25",
                "max_daily_ret_5d", "cum_ret_5d",
                "bw_recent", "bw_prior", "bw_expanding", "bw_prior_percentile",
                "slope_25",
            ]:
                row[col] = r.get(col)
            rows.append(row)
    return pd.DataFrame(rows)


def build_output_b(best_days: Dict[str, pd.Series],
                   rec_vol_col: str, rec_cv: float) -> pd.DataFrame:
    """出力B: 閾値サマリー（全ウィンドウ比較 + 各指標統計）"""
    rows: list = []

    # Vol window comparison
    for n1, n2 in VOL_WINDOWS:
        col = f"vol_ratio_{n1}_{n2}"
        vals = [float(d[col]) for d in best_days.values() if pd.notna(d.get(col))]
        if len(vals) < 2:
            continue
        mean_v = np.mean(vals)
        cv = float(np.std(vals, ddof=1) / mean_v) if mean_v > 0 else np.nan
        is_rec = (col == rec_vol_col)
        rows.append({
            "指標": col,
            "min": round(np.min(vals), 4),
            "max": round(np.max(vals), 4),
            "mean": round(mean_v, 4),
            "CV": round(cv, 4) if pd.notna(cv) else "",
            "推奨値": (f">={round(min(vals) * 0.95, 3)} & "
                     f"<={round(max(vals) * 1.05, 3)}")
                     if is_rec else "",
            "備考": "★推奨ウィンドウ" if is_rec else "",
        })

    # Other indicators
    indicator_defs = [
        ("price_vs_ma25",    ">=1.0",  "下限"),
        ("price_vs_ma75",    ">=0.97", "下限"),
        ("max_daily_ret_5d", None,     "上限"),
        ("cum_ret_5d",       None,     "上限"),
        ("bw_prior_percentile", None,  "上限"),
        ("slope_25",         ">0",     "下限"),
        ("bw_recent",        "",       ""),
        ("bw_prior",         "",       ""),
    ]
    for col, fixed_rec, bound_type in indicator_defs:
        vals = [float(d[col]) for d in best_days.values() if pd.notna(d.get(col))]
        if not vals:
            continue
        row: dict = {
            "指標": col,
            "min": round(np.min(vals), 4),
            "max": round(np.max(vals), 4),
            "mean": round(np.mean(vals), 4),
            "CV": "",
        }
        if fixed_rec:
            row["推奨値"] = fixed_rec
            row["備考"] = f"全銘柄min={min(vals):.4f}"
        elif col == "max_daily_ret_5d":
            row["推奨値"] = f"<={round(max(vals) + 0.005, 3)}"
            row["備考"] = f"全銘柄max={max(vals):.4f}"
        elif col == "cum_ret_5d":
            row["推奨値"] = f"<={round(max(vals) + 0.01, 3)}"
            row["備考"] = f"全銘柄max={max(vals):.4f}"
        elif col == "bw_prior_percentile":
            row["推奨値"] = f"<={round(max(vals), 3)}"
            row["備考"] = f"全銘柄max={max(vals):.4f} (この値以下で全銘柄パス)"
        else:
            row["推奨値"] = ""
            row["備考"] = ""
        rows.append(row)

    return pd.DataFrame(rows)


def build_output_c(best_days: Dict[str, pd.Series],
                   rec_vol_col: str) -> pd.DataFrame:
    """出力C: 条件パス/フェイル判定マトリクス"""
    rows: list = []
    for name, day in best_days.items():
        conds = evaluate_conditions(day, rec_vol_col)
        row = {
            "銘柄名": name,
            "ベスト日": day["Date"].strftime("%Y-%m-%d"),
            "終値": round(float(day["Close"]), 1),
            rec_vol_col: round(float(day[rec_vol_col]), 4)
                         if pd.notna(day.get(rec_vol_col)) else "",
        }
        for k, v in conds.items():
            row[k] = "PASS" if v else "FAIL"
        row["合計PASS"] = sum(conds.values())
        rows.append(row)
    return pd.DataFrame(rows)


# ============================================================
# Main
# ============================================================

def main() -> None:
    api_key = get_api_key()

    print("=" * 70)
    print("  Type A 'Quiet Accumulation' 閾値検証スクリプト")
    print("=" * 70)

    stock_windows: Dict[str, pd.DataFrame] = {}
    stock_targets: Dict[str, str] = {}

    for m in ROLE_MODELS:
        name, code, target = m["name"], m["code"], m["target_date"]
        print(f"\n{'─' * 60}")
        print(f"  {name} ({code})  ターゲット: {target}")
        print(f"{'─' * 60}")

        target_dt = datetime.strptime(target, "%Y-%m-%d")
        from_dt = target_dt - timedelta(days=400)
        to_dt = target_dt + timedelta(days=10)

        print(f"  データ取得: {from_dt:%Y-%m-%d} → {to_dt:%Y-%m-%d}")
        df = fetch_daily_bars(
            code, from_dt.strftime("%Y-%m-%d"),
            to_dt.strftime("%Y-%m-%d"), api_key,
        )
        if df.empty:
            print("  ⚠ データ取得失敗 — スキップ")
            continue
        print(f"  取得: {len(df)}日分")

        df = compute_indicators(df)

        wdf, actual = extract_window(df, target)
        if wdf.empty:
            print("  ⚠ ウィンドウ抽出失敗 — スキップ")
            continue
        print(f"  ウィンドウ: {wdf['Date'].iloc[0]:%Y-%m-%d} → "
              f"{wdf['Date'].iloc[-1]:%Y-%m-%d} ({len(wdf)}日)")

        stock_windows[name] = wdf
        stock_targets[name] = actual

    if not stock_windows:
        print("\nERROR: データを取得できた銘柄がありません")
        sys.exit(1)

    # --- Recommended vol window ---
    init_best = [
        find_best_day(w, stock_targets[n], "vol_ratio_5_10")
        for n, w in stock_windows.items()
    ]
    rec_vol_col, rec_cv = find_recommended_vol_window(init_best)
    print(f"\n推奨出来高ウィンドウ: {rec_vol_col}  (CV = {rec_cv:.4f})")

    # Re-select best days with recommended vol window
    best_days: Dict[str, pd.Series] = {
        n: find_best_day(w, stock_targets[n], rec_vol_col)
        for n, w in stock_windows.items()
    }

    # --- Generate & save outputs ---
    print(f"\n{'=' * 70}")
    print("  出力生成")
    print(f"{'=' * 70}")

    out_a = build_output_a(stock_windows)
    out_a.to_csv("output_a.csv", index=False, encoding="utf-8-sig")
    print(f"\n  ✔ output_a.csv ({len(out_a)}行)")

    out_b = build_output_b(best_days, rec_vol_col, rec_cv)
    out_b.to_csv("output_b.csv", index=False, encoding="utf-8-sig")
    print(f"  ✔ output_b.csv ({len(out_b)}行)")

    out_c = build_output_c(best_days, rec_vol_col)
    out_c.to_csv("output_c.csv", index=False, encoding="utf-8-sig")
    print(f"  ✔ output_c.csv ({len(out_c)}行)")

    # --- Terminal summary ---
    print(f"\n{'=' * 70}")
    print("  サマリー")
    print(f"{'=' * 70}")

    print(f"\n▸ 推奨出来高ウィンドウ: {rec_vol_col} (CV={rec_cv:.4f})")

    print("\n▸ ベスト日一覧:")
    for name, day in best_days.items():
        conds = evaluate_conditions(day, rec_vol_col)
        score = sum(conds.values())
        print(f"  {name:8s}  {day['Date']:%Y-%m-%d}  "
              f"終値={day['Close']:.0f}  PASS={score}/5")

    print("\n▸ 閾値サマリー:")
    print(out_b.to_string(index=False))

    print("\n▸ 条件パス/フェイル:")
    print(out_c.to_string(index=False))

    print("\n完了!")


if __name__ == "__main__":
    main()
