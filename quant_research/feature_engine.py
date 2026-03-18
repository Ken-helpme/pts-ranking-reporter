"""
特徴量エンジン: 出来高シグナル、テクニカル指標、ブレイクアウト検出

全計算はgroupby + vectorized operationsで高速処理。
"""
import logging

import numpy as np
import pandas as pd

from .config import (
    VOLUME_LOOKBACK, MA_PERIODS, RSI_PERIOD,
    MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    ATR_PERIOD, VOLATILITY_PERIOD, BREAKOUT_PERIODS,
    FORWARD_PERIODS,
)

logger = logging.getLogger(__name__)


# ============================================================
# 出来高シグナル (STEP2 核心)
# ============================================================

def add_volume_signals(df: pd.DataFrame, lookback: int = VOLUME_LOOKBACK) -> pd.DataFrame:
    """
    出来高ベースの機関資金流入シグナルを追加。

    追加カラム:
        vol_ratio       : 今日出来高 ÷ 過去N日平均出来高
        vol_zscore      : 出来高のZスコア（標準偏差何倍か）
        turnover_ratio  : 売買代金 ÷ 過去N日平均売買代金
        vol_ratio_5d    : 直近5日平均出来高 ÷ 前15日平均（週次比較）
    """
    g = df.groupby("Code")

    vol_mean = g["Volume"].transform(lambda x: x.rolling(lookback, min_periods=5).mean())
    vol_std = g["Volume"].transform(lambda x: x.rolling(lookback, min_periods=5).std())

    df["vol_ratio"] = df["Volume"] / vol_mean.replace(0, np.nan)
    df["vol_zscore"] = (df["Volume"] - vol_mean) / vol_std.replace(0, np.nan)

    if "Turnover" in df.columns:
        to_mean = g["Turnover"].transform(
            lambda x: x.rolling(lookback, min_periods=5).mean()
        )
        df["turnover_ratio"] = df["Turnover"] / to_mean.replace(0, np.nan)
    else:
        df["turnover_ratio"] = df["vol_ratio"]

    vol_5d = g["Volume"].transform(lambda x: x.rolling(5, min_periods=3).mean())
    vol_prev15d = g["Volume"].transform(
        lambda x: x.rolling(20, min_periods=10).mean().shift(5)
    )
    df["vol_ratio_5d"] = vol_5d / vol_prev15d.replace(0, np.nan)

    return df


# ============================================================
# 移動平均・トレンド
# ============================================================

def add_moving_averages(df: pd.DataFrame, periods: list = MA_PERIODS) -> pd.DataFrame:
    """移動平均線と乖離率を追加"""
    g = df.groupby("Code")["Close"]

    for p in periods:
        col = f"ma{p}"
        df[col] = g.transform(lambda x: x.rolling(p, min_periods=p).mean())
        df[f"ma{p}_dev"] = (df["Close"] - df[col]) / df[col].replace(0, np.nan)

    if all(f"ma{p}" in df.columns for p in [5, 25]):
        df["ma5_above_ma25"] = (df["ma5"] > df["ma25"]).astype(int)
    if all(f"ma{p}" in df.columns for p in [25, 75]):
        df["ma25_above_ma75"] = (df["ma25"] > df["ma75"]).astype(int)
    if all(f"ma{p}" in df.columns for p in [5, 25, 75]):
        df["full_uptrend"] = (
            (df["ma5"] > df["ma25"]) & (df["ma25"] > df["ma75"])
        ).astype(int)

    return df


# ============================================================
# モメンタム・RSI・MACD
# ============================================================

def add_momentum(df: pd.DataFrame) -> pd.DataFrame:
    """価格モメンタム（N日リターン）を追加"""
    g = df.groupby("Code")["Close"]
    for n in [5, 10, 20, 60]:
        df[f"mom_{n}d"] = g.transform(lambda x: x.pct_change(n))
    return df


def _rsi_series(series: pd.Series, period: int) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def add_rsi(df: pd.DataFrame, period: int = RSI_PERIOD) -> pd.DataFrame:
    """RSI (Relative Strength Index) を追加"""
    df["rsi"] = df.groupby("Code")["Close"].transform(lambda x: _rsi_series(x, period))
    return df


def add_macd(df: pd.DataFrame,
             fast: int = MACD_FAST, slow: int = MACD_SLOW,
             signal: int = MACD_SIGNAL) -> pd.DataFrame:
    """MACD + シグナルライン + ヒストグラムを追加"""
    g = df.groupby("Code")["Close"]
    ema_fast = g.transform(lambda x: x.ewm(span=fast, min_periods=fast).mean())
    ema_slow = g.transform(lambda x: x.ewm(span=slow, min_periods=slow).mean())

    df["macd"] = ema_fast - ema_slow
    df["macd_signal"] = df.groupby("Code")["macd"].transform(
        lambda x: x.ewm(span=signal, min_periods=signal).mean()
    )
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    return df


# ============================================================
# ボラティリティ・ATR
# ============================================================

def add_volatility(df: pd.DataFrame, period: int = VOLATILITY_PERIOD) -> pd.DataFrame:
    """日次リターンの標準偏差（ヒストリカルボラティリティ）"""
    df["daily_return"] = df.groupby("Code")["Close"].transform(lambda x: x.pct_change())
    df["volatility"] = df.groupby("Code")["daily_return"].transform(
        lambda x: x.rolling(period, min_periods=max(5, period // 2)).std()
    )
    return df


def add_atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.DataFrame:
    """Average True Range を追加"""
    prev_close = df.groupby("Code")["Close"].shift(1)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev_close).abs(),
        (df["Low"] - prev_close).abs(),
    ], axis=1).max(axis=1)

    df["atr"] = tr.groupby(df["Code"]).transform(
        lambda x: x.ewm(span=period, min_periods=period).mean()
    )
    df["atr_pct"] = df["atr"] / df["Close"].replace(0, np.nan)
    return df


# ============================================================
# 価格ブレイクアウト
# ============================================================

def add_breakout_signals(df: pd.DataFrame,
                         periods: list = BREAKOUT_PERIODS) -> pd.DataFrame:
    """N日高値ブレイクアウト検出"""
    g = df.groupby("Code")
    for p in periods:
        rolling_high = g["High"].transform(
            lambda x: x.shift(1).rolling(p, min_periods=max(10, p // 2)).max()
        )
        df[f"breakout_{p}d"] = (df["Close"] > rolling_high).astype(int)
        df[f"pct_from_{p}d_high"] = (
            (df["Close"] - rolling_high) / rolling_high.replace(0, np.nan)
        )

    high_52w = g["High"].transform(
        lambda x: x.shift(1).rolling(250, min_periods=200).max()
    )
    df["near_52w_high"] = (df["Close"] >= high_52w * 0.95).astype(int)
    df["pct_from_52w_high"] = (
        (df["Close"] - high_52w) / high_52w.replace(0, np.nan)
    )

    return df


# ============================================================
# フォワードリターン（バックテスト用ターゲット）
# ============================================================

def add_forward_returns(df: pd.DataFrame, periods: list = None) -> pd.DataFrame:
    """
    N日後のリターンを事前計算。

    翌日寄り買い → N日後終値売りのリターン。
    """
    if periods is None:
        periods = FORWARD_PERIODS

    g = df.groupby("Code")
    next_open = g["Open"].shift(-1)
    df["next_open"] = next_open

    for n in periods:
        future_close = g["Close"].shift(-n)
        df[f"fwd_{n}d_return"] = (future_close - next_open) / next_open.replace(0, np.nan)

    return df


# ============================================================
# 時価総額推定
# ============================================================

def add_market_cap_estimate(df: pd.DataFrame, fins: pd.DataFrame) -> pd.DataFrame:
    """
    決算データから発行済株式数を取得し、時価総額を推定。
    決算データがない場合は売買代金ベースの代替推定。
    """
    if fins is not None and not fins.empty:
        shares_col = None
        for col in ["NumberOfIssuedAndOutstandingSharesAtTheEndOfFiscalYearIncludingTreasuryStock",
                     "IssuedShares", "Shares"]:
            if col in fins.columns:
                shares_col = col
                break

        if shares_col:
            latest_shares = (
                fins.sort_values("DisclosedDate" if "DisclosedDate" in fins.columns else fins.columns[0])
                .groupby("LocalCode" if "LocalCode" in fins.columns else "Code")
                .last()[[shares_col]]
                .rename(columns={shares_col: "shares_outstanding"})
            )
            code_col = "LocalCode" if "LocalCode" in latest_shares.index.name == "LocalCode" else "Code"
            latest_shares.index.name = "Code"
            latest_shares = latest_shares.reset_index()
            latest_shares["Code"] = latest_shares["Code"].astype(str)
            df["Code"] = df["Code"].astype(str)

            df = df.merge(latest_shares, on="Code", how="left")
            df["market_cap"] = df["Close"] * pd.to_numeric(df["shares_outstanding"], errors="coerce")
            df = df.drop(columns=["shares_outstanding"], errors="ignore")

    if "market_cap" not in df.columns:
        avg_turnover = df.groupby("Code")["Turnover"].transform(
            lambda x: x.rolling(20, min_periods=5).mean()
        )
        df["market_cap"] = avg_turnover * 100

    return df


# ============================================================
# 全特徴量一括計算
# ============================================================

def compute_all_features(df: pd.DataFrame,
                         fins: pd.DataFrame = None,
                         forward_periods: list = None) -> pd.DataFrame:
    """
    全特徴量を一括で計算。

    Args:
        df: prepare_price_dataframe()の出力
        fins: 決算サマリーDataFrame（時価総額推定用、Optional）
        forward_periods: フォワードリターンの日数リスト

    Returns:
        全特徴量が追加されたDataFrame
    """
    logger.info(f"Computing features for {df['Code'].nunique():,} stocks, "
                f"{len(df):,} rows...")

    df = add_volume_signals(df)
    logger.info("  Volume signals computed")

    df = add_moving_averages(df)
    logger.info("  Moving averages computed")

    df = add_momentum(df)
    logger.info("  Momentum computed")

    df = add_rsi(df)
    logger.info("  RSI computed")

    df = add_macd(df)
    logger.info("  MACD computed")

    df = add_volatility(df)
    logger.info("  Volatility computed")

    df = add_atr(df)
    logger.info("  ATR computed")

    df = add_breakout_signals(df)
    logger.info("  Breakout signals computed")

    df = add_market_cap_estimate(df, fins)
    logger.info("  Market cap estimated")

    df = add_forward_returns(df, periods=forward_periods)
    logger.info("  Forward returns computed")

    initial_rows = len(df)
    df = df.replace([np.inf, -np.inf], np.nan)

    logger.info(f"Feature computation complete: {len(df.columns)} columns, "
                f"{len(df):,} rows")

    return df
