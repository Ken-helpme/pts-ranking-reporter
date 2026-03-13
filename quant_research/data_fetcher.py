"""
J-Quants API データ取得 + Parquetキャッシュ

Standard plan: 10年ヒストリカル, 120req/min, 指数・投資部門別データ利用可
"""
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
from dateutil import tz

from .config import DATA_DIR, JQUANTS_API_KEY, DATA_YEARS

logger = logging.getLogger(__name__)
JST = tz.gettz("Asia/Tokyo")

CACHE_FILES = {
    "prices": DATA_DIR / "stock_prices.parquet",
    "master": DATA_DIR / "master.parquet",
    "index_topix": DATA_DIR / "index_topix.parquet",
    "index_nikkei": DATA_DIR / "index_nikkei.parquet",
    "investor_types": DATA_DIR / "investor_types.parquet",
    "fins_summary": DATA_DIR / "fins_summary.parquet",
}


def _get_client():
    import jquantsapi
    return jquantsapi.ClientV2(api_key=JQUANTS_API_KEY)


def _cache_path(name: str) -> Path:
    return CACHE_FILES.get(name, DATA_DIR / f"{name}.parquet")


def _load_cache(name: str) -> Optional[pd.DataFrame]:
    path = _cache_path(name)
    if path.exists():
        try:
            df = pd.read_parquet(path)
            logger.info(f"Cache loaded: {name} ({len(df):,} rows)")
            return df
        except Exception as e:
            logger.warning(f"Cache read failed for {name}: {e}")
    return None


def _save_cache(name: str, df: pd.DataFrame) -> None:
    path = _cache_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    logger.info(f"Cache saved: {name} ({len(df):,} rows, {path.stat().st_size / 1e6:.1f}MB)")


# ============================================================
# 銘柄マスター
# ============================================================

def fetch_master(force: bool = False) -> pd.DataFrame:
    """上場銘柄マスターデータを取得（セクター・市場区分含む）"""
    if not force:
        cached = _load_cache("master")
        if cached is not None:
            return cached

    cli = _get_client()
    logger.info("Fetching master data from J-Quants...")
    df = cli.get_eq_master()

    if df is None or df.empty:
        raise RuntimeError("Failed to fetch master data")

    _save_cache("master", df)
    return df


# ============================================================
# 日足株価 (全銘柄 x 10年)
# ============================================================

def fetch_stock_prices(force: bool = False, years: int = DATA_YEARS) -> pd.DataFrame:
    """
    全銘柄の日足OHLCVを取得。

    初回は全期間フェッチ、2回目以降は差分更新。
    Parquetキャッシュ利用で起動が高速。
    """
    cached = None if force else _load_cache("prices")

    end_dt = datetime.now(tz=JST)
    if cached is not None and not cached.empty:
        last_date = pd.to_datetime(cached["Date"]).max()
        start_dt = (last_date + timedelta(days=1)).to_pydatetime().replace(tzinfo=JST)
        if start_dt.date() >= end_dt.date():
            logger.info("Stock prices are up to date")
            return cached
        logger.info(f"Incremental fetch from {start_dt.date()} to {end_dt.date()}")
    else:
        start_dt = datetime(end_dt.year - years, end_dt.month, end_dt.day, tzinfo=JST)
        logger.info(f"Full fetch from {start_dt.date()} to {end_dt.date()} ({years} years)")

    cli = _get_client()
    df_new = cli.get_eq_bars_daily_range(start_dt=start_dt, end_dt=end_dt)

    if df_new is None or df_new.empty:
        logger.warning("No new price data fetched")
        return cached if cached is not None else pd.DataFrame()

    if cached is not None and not cached.empty:
        df = pd.concat([cached, df_new], ignore_index=True)
        df = df.drop_duplicates(subset=["Code", "Date"], keep="last")
        df = df.sort_values(["Code", "Date"]).reset_index(drop=True)
    else:
        df = df_new.sort_values(["Code", "Date"]).reset_index(drop=True)

    _save_cache("prices", df)
    return df


# ============================================================
# 指数データ（TOPIX / 日経225）
# ============================================================

def fetch_index_topix(force: bool = False, years: int = DATA_YEARS) -> pd.DataFrame:
    """TOPIX日足データを取得"""
    if not force:
        cached = _load_cache("index_topix")
        if cached is not None:
            return cached

    cli = _get_client()
    end_dt = datetime.now(tz=JST)
    start_dt = datetime(end_dt.year - years, end_dt.month, end_dt.day, tzinfo=JST)
    logger.info(f"Fetching TOPIX data ({start_dt.date()} to {end_dt.date()})...")
    df = cli.get_idx_bars_daily_topix_range(start_dt=start_dt, end_dt=end_dt)

    if df is None or df.empty:
        logger.warning("No TOPIX data fetched")
        return pd.DataFrame()

    _save_cache("index_topix", df)
    return df


def fetch_index_nikkei(force: bool = False, years: int = DATA_YEARS) -> pd.DataFrame:
    """日経225日足データを取得（Indices endpointから）"""
    if not force:
        cached = _load_cache("index_nikkei")
        if cached is not None:
            return cached

    cli = _get_client()
    end_dt = datetime.now(tz=JST)
    start_dt = datetime(end_dt.year - years, end_dt.month, end_dt.day, tzinfo=JST)
    logger.info(f"Fetching Nikkei 225 data ({start_dt.date()} to {end_dt.date()})...")

    try:
        df = cli.get_idx_bars_daily_range(start_dt=start_dt, end_dt=end_dt)
    except Exception as e:
        logger.warning(f"Indices endpoint failed: {e}, trying TOPIX as fallback")
        return fetch_index_topix(force=force, years=years)

    if df is not None and not df.empty:
        nikkei = df[df["Code"].astype(str).str.contains("0000")].copy()
        if nikkei.empty:
            nikkei = df.copy()
        _save_cache("index_nikkei", nikkei)
        return nikkei

    logger.warning("No Nikkei data fetched")
    return pd.DataFrame()


# ============================================================
# 投資部門別売買状況（機関投資家フロー検証用）
# ============================================================

def fetch_investor_types(force: bool = False, years: int = DATA_YEARS) -> pd.DataFrame:
    """投資部門別売買状況データ（Standard plan以上）"""
    if not force:
        cached = _load_cache("investor_types")
        if cached is not None:
            return cached

    cli = _get_client()
    end_dt = datetime.now(tz=JST)
    start_dt = datetime(end_dt.year - years, end_dt.month, end_dt.day, tzinfo=JST)
    logger.info(f"Fetching investor type data ({start_dt.date()} to {end_dt.date()})...")

    try:
        df = cli.get_eq_investor_types_range(start_dt=start_dt, end_dt=end_dt)
    except Exception as e:
        logger.warning(f"Investor types fetch failed (requires Standard plan): {e}")
        return pd.DataFrame()

    if df is not None and not df.empty:
        _save_cache("investor_types", df)
        return df

    return pd.DataFrame()


# ============================================================
# 決算サマリー（時価総額算出用）
# ============================================================

def fetch_financial_summary(force: bool = False) -> pd.DataFrame:
    """決算サマリーデータ（時価総額・PER・PBR等）"""
    if not force:
        cached = _load_cache("fins_summary")
        if cached is not None:
            return cached

    cli = _get_client()
    logger.info("Fetching financial summary data...")

    try:
        df = cli.get_fin_summary()
    except Exception as e:
        logger.warning(f"Financial summary fetch failed: {e}")
        return pd.DataFrame()

    if df is not None and not df.empty:
        _save_cache("fins_summary", df)
        return df

    return pd.DataFrame()


# ============================================================
# 一括取得
# ============================================================

def fetch_all(force: bool = False, years: int = DATA_YEARS) -> dict:
    """
    全データを一括取得して辞書で返す。
    Parquetキャッシュがあればそこから読み込み、なければAPIからフェッチ。
    """
    logger.info("=" * 60)
    logger.info("Starting data acquisition pipeline")
    logger.info("=" * 60)

    data = {}

    data["master"] = fetch_master(force=force)
    logger.info(f"  Master: {len(data['master']):,} stocks")

    data["prices"] = fetch_stock_prices(force=force, years=years)
    logger.info(f"  Prices: {len(data['prices']):,} rows")

    data["topix"] = fetch_index_topix(force=force, years=years)
    logger.info(f"  TOPIX: {len(data['topix']):,} rows")

    data["nikkei"] = fetch_index_nikkei(force=force, years=years)
    logger.info(f"  Nikkei: {len(data['nikkei']):,} rows")

    data["investor_types"] = fetch_investor_types(force=force, years=years)
    logger.info(f"  Investor types: {len(data['investor_types']):,} rows")

    data["fins_summary"] = fetch_financial_summary(force=force)
    logger.info(f"  Financial summary: {len(data['fins_summary']):,} rows")

    logger.info("=" * 60)
    logger.info("Data acquisition complete")
    logger.info("=" * 60)

    return data


def prepare_price_dataframe(prices: pd.DataFrame, master: pd.DataFrame) -> pd.DataFrame:
    """
    株価データにマスター情報をマージし、分析用にクリーンなDataFrameを構築。

    Returns:
        DataFrame with columns:
            Code, Date, Open, High, Low, Close, Volume, Turnover,
            Sector, SectorCode, Market, Name
    """
    df = prices.copy()

    col_map = {}
    for src, dst in [
        ("AdjOpen", "Open"), ("AdjHigh", "High"), ("AdjLow", "Low"),
        ("AdjClose", "Close"), ("AdjVolume", "Volume"),
    ]:
        if src in df.columns:
            col_map[src] = dst
    if not col_map:
        for src, dst in [
            ("Open", "Open"), ("High", "High"), ("Low", "Low"),
            ("Close", "Close"), ("Volume", "Volume"),
        ]:
            if src in df.columns:
                col_map[src] = dst

    if col_map:
        df = df.rename(columns=col_map)

    if "TurnoverValue" in df.columns:
        df = df.rename(columns={"TurnoverValue": "Turnover"})
    elif "Va" in df.columns:
        df = df.rename(columns={"Va": "Turnover"})
    elif "Turnover" not in df.columns:
        if "Close" in df.columns and "Volume" in df.columns:
            df["Turnover"] = df["Close"] * df["Volume"]

    df["Date"] = pd.to_datetime(df["Date"])

    master_cols = master[["Code"]].copy()
    for col, alias in [
        ("Sector33CodeName", "Sector"), ("Sector33Code", "SectorCode"),
        ("MarketCodeName", "Market"), ("CompanyName", "Name"),
        ("S33Nm", "Sector"), ("S33", "SectorCode"),
        ("MktNm", "Market"), ("CoName", "Name"),
    ]:
        if col in master.columns and alias not in master_cols.columns:
            master_cols[alias] = master[col].values

    df = df.merge(master_cols, on="Code", how="left")

    keep_cols = [c for c in [
        "Code", "Date", "Open", "High", "Low", "Close",
        "Volume", "Turnover", "Sector", "SectorCode", "Market", "Name",
    ] if c in df.columns]

    df = df[keep_cols].copy()

    for col in ["Open", "High", "Low", "Close", "Volume", "Turnover"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["Close"])
    df = df[df["Close"] > 0]
    df = df.sort_values(["Code", "Date"]).reset_index(drop=True)

    return df
