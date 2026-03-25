"""
シグナル監視モジュール — ステルス仕込みシグナルの検出・追跡・消失検知

Reads from _vol_base_features.pkl + _intermediate_raw_data.pkl and produces
a structured dict suitable for the Flask /api/signals/* endpoints.
"""
import os
import logging
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"

GCS_BUCKET = "pts-ranking-data"
GCS_PREFIX = "quant_data"
_DATA_FILES = ["_vol_base_features.pkl", "_intermediate_raw_data.pkl"]


def _ensure_data_from_gcs(data_dir: Path) -> bool:
    """Download data files from GCS if they don't exist locally. Returns True if available."""
    missing = [f for f in _DATA_FILES if not (data_dir / f).exists()]
    if not missing:
        return True
    try:
        from google.cloud import storage
        client = storage.Client()
        bucket = client.bucket(GCS_BUCKET)
        data_dir.mkdir(parents=True, exist_ok=True)
        for fname in missing:
            blob = bucket.blob(f"{GCS_PREFIX}/{fname}")
            dest = data_dir / fname
            logger.info("Downloading gs://%s/%s/%s -> %s", GCS_BUCKET, GCS_PREFIX, fname, dest)
            blob.download_to_filename(str(dest))
            logger.info("Downloaded %s (%.1f MB)", fname, dest.stat().st_size / 1e6)
        return True
    except ImportError:
        logger.warning("google-cloud-storage not installed, skipping GCS download")
        return False
    except Exception as e:
        logger.warning("GCS download failed: %s", e)
        return False

# ---------------------------------------------------------------------------
# Earnings-growth helper
# ---------------------------------------------------------------------------

def _compute_growing_codes(fins: pd.DataFrame, min_op_growth: float = 10.0):
    """Return set of CodeStr values whose current-FY operating profit growth >= threshold."""
    fins = fins.copy()
    fins['Code'] = fins['Code'].astype(str)
    fins['DiscDate'] = pd.to_datetime(fins['DiscDate'], errors='coerce')
    for col in ('OP', 'NP', 'Sales', 'FOP', 'FSales', 'FEPS', 'EPS'):
        if col in fins.columns:
            fins[col] = pd.to_numeric(fins[col], errors='coerce')

    fy_actuals = fins[fins['DocType'].str.contains('FYFinancialStatements', na=False)].copy()
    fy_actuals['CurFYEn'] = pd.to_datetime(fy_actuals['CurFYEn'], errors='coerce')

    growth: Dict[str, dict] = {}
    for code, grp in fy_actuals.groupby('Code'):
        grp = grp.sort_values('CurFYEn').drop_duplicates(subset='CurFYEn', keep='last')
        if len(grp) >= 2:
            prev, curr = grp.iloc[-2], grp.iloc[-1]
            growth[code] = {
                'prev_op': prev['OP'], 'fop': curr['FOP'],
                'prev_eps': prev['EPS'], 'feps': curr['FEPS'],
            }

    latest_filings = fins.sort_values('DiscDate').drop_duplicates(subset='Code', keep='last')
    for _, row in latest_filings.iterrows():
        code = row['Code']
        if code in growth:
            if pd.notna(row.get('FOP')):
                growth[code]['latest_fop'] = row['FOP']
            if pd.notna(row.get('FEPS')):
                growth[code]['latest_feps'] = row['FEPS']

    gdf = pd.DataFrame(growth).T
    if gdf.empty:
        return set(), {}, {}

    gdf['fop_final'] = gdf.get('latest_fop', gdf['fop']).fillna(gdf['fop'])
    gdf['feps_final'] = gdf.get('latest_feps', gdf['feps']).fillna(gdf['feps'])
    gdf['op_growth'] = np.where(
        (gdf['prev_op'] > 0) & (gdf['fop_final'] > 0),
        (gdf['fop_final'] - gdf['prev_op']) / gdf['prev_op'] * 100, np.nan)
    gdf['eps_growth'] = np.where(
        (gdf['prev_eps'] > 0) & (gdf['feps_final'] > 0),
        (gdf['feps_final'] - gdf['prev_eps']) / gdf['prev_eps'] * 100, np.nan)

    codes = set(gdf[gdf['op_growth'] >= min_op_growth].index)
    op_map = gdf['op_growth'].to_dict()
    eps_map = gdf['eps_growth'].to_dict()
    return codes, op_map, eps_map


# ---------------------------------------------------------------------------
# Feature computation (idempotent — skips columns already present)
# ---------------------------------------------------------------------------

def _ensure_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add vol-base / slope / deviation columns if missing."""
    if 'vol_avg_20' not in df.columns:
        df['vol_avg_20'] = df.groupby('CodeStr')['Volume'].transform(
            lambda x: x.rolling(20, min_periods=15).mean())
    if 'vol_avg_120' not in df.columns:
        df['vol_avg_120'] = df.groupby('CodeStr')['Volume'].transform(
            lambda x: x.rolling(120, min_periods=80).mean())
    if 'vol_base_ratio' not in df.columns:
        df['vol_base_ratio'] = df['vol_avg_20'] / df['vol_avg_120']

    # Lagged baseline: 120d average shifted by 5 days (excludes recent surge)
    df['vol_avg_120_lagged'] = df.groupby('CodeStr')['Volume'].transform(
        lambda x: x.shift(5).rolling(120, min_periods=80).mean())
    # Recent 5-day average vs lagged 120d baseline
    df['vol_avg_5'] = df.groupby('CodeStr')['Volume'].transform(
        lambda x: x.rolling(5, min_periods=3).mean())
    df['vol_base_ratio_lagged'] = df['vol_avg_5'] / df['vol_avg_120_lagged']

    # Recent 3-day average (for ultra-early gradual increase detection)
    df['vol_avg_3'] = df.groupby('CodeStr')['Volume'].transform(
        lambda x: x.rolling(3, min_periods=2).mean())
    df['vol_3d_vs_120d'] = df['vol_avg_3'] / df['vol_avg_120']

    # Short-term above-baseline count: 5 days out of 5 above 120d avg
    def _count_5d(group):
        vol = group['Volume'].values
        avg120 = group['vol_avg_120'].values
        result = np.full(len(vol), np.nan)
        for i in range(4, len(vol)):
            window = vol[i - 4:i + 1]
            baseline = avg120[i]
            if np.isnan(baseline) or baseline <= 0:
                continue
            result[i] = np.sum(window > baseline)
        return pd.Series(result, index=group.index)
    df['vol_above_count_5d'] = df.groupby('CodeStr').apply(
        _count_5d).reset_index(level=0, drop=True)

    if 'vol_above_count_20d' not in df.columns:
        def _count(group):
            vol = group['Volume'].values
            avg120 = group['vol_avg_120'].values
            result = np.full(len(vol), np.nan)
            for i in range(19, len(vol)):
                window = vol[i - 19:i + 1]
                baseline = avg120[i]
                if np.isnan(baseline) or baseline <= 0:
                    continue
                result[i] = np.sum(window > baseline)
            return pd.Series(result, index=group.index)
        df['vol_above_count_20d'] = df.groupby('CodeStr').apply(
            _count).reset_index(level=0, drop=True)

    if 'high_50d' not in df.columns:
        df['high_50d'] = df.groupby('CodeStr')['Close'].transform(
            lambda x: x.rolling(50, min_periods=40).max())
    if 'breakout_50d' not in df.columns or df['breakout_50d'].dtype == object:
        df['breakout_50d'] = df['Close'] >= df['high_50d']

    if 'turnover_avg_20' not in df.columns:
        if 'Turnover' in df.columns:
            df['turnover_avg_20'] = df.groupby('CodeStr')['Turnover'].transform(
                lambda x: x.rolling(20, min_periods=15).mean())
        else:
            df['turnover_avg_20'] = np.nan

    df['pct_from_50d_high'] = (df['Close'] - df['high_50d']) / df['high_50d']

    if 'ma25_dev' not in df.columns:
        df['ma25_dev'] = (df['Close'] - df['ma25']) / df['ma25'] * 100
    if 'ma25_slope' not in df.columns:
        df['ma25_slope'] = df.groupby('CodeStr')['ma25'].transform(
            lambda x: x.diff(5) / x.shift(5) * 100)

    # TOB detection: price frozen for 3+ of last 5 days
    zero_ret_count = df.groupby('CodeStr')['Close'].transform(
        lambda x: x.pct_change().eq(0).rolling(5, min_periods=3).sum())
    df['price_frozen_5d'] = zero_ret_count >= 3

    # Volume jump features
    df['vol_vs_120d'] = df['Volume'] / df['vol_avg_120']
    df['vol_jump'] = df['Volume'] / df.groupby('CodeStr')['Volume'].shift(1)
    df['daily_ret'] = df.groupby('CodeStr')['Close'].pct_change()

    # Volume acceleration: 3 consecutive days of vol_jump >= 1.3 (前日比+30%)
    df['_vj_ok'] = (df['vol_jump'].fillna(0) >= 1.3).astype(int)
    df['vol_accel_3d'] = df.groupby('CodeStr')['_vj_ok'].transform(
        lambda x: x.rolling(3, min_periods=3).min())
    df.drop(columns=['_vj_ok'], inplace=True)

    return df


# ---------------------------------------------------------------------------
# Core signal detection
# ---------------------------------------------------------------------------

def compute_signals(df: pd.DataFrame, etf_codes: set, growing_codes: set) -> pd.Series:
    """
    Confirmed stealth accumulation.
    Uses lagged 120d baseline (excludes recent 5 days from average)
    and short-term above-count (5 days out of 5 >= 3) for faster detection.
    """
    return (
        (df['vol_base_ratio_lagged'] >= 1.5) &
        (df['vol_above_count_5d'] >= 3) &
        (df['ma25_dev'].abs() <= 10) &
        (df['rsi'] <= 65) &
        (df['pct_from_50d_high'] >= -0.10) &
        (~df['price_frozen_5d']) &
        (df['turnover_avg_20'] >= 3e8) &
        (~df['CodeStr'].isin(etf_codes)) &
        (df['ma25_slope'] >= 0) &
        (df['Close'] >= df['ma75']) &
        (df['CodeStr'].isin(growing_codes))
    )


def compute_ultra_early_signals(df: pd.DataFrame, etf_codes: set,
                                 growing_codes: set) -> pd.Series:
    """
    Ultra-early volume detection (超初動シグナル).
    Two paths: single-day spike OR gradual 3-day buildup.
    """
    common = (
        (df['daily_ret'] >= -0.03) &
        (df['pct_from_50d_high'] >= -0.05) &
        (~df['price_frozen_5d']) &
        (df['turnover_avg_20'] >= 1e8) &
        (~df['CodeStr'].isin(etf_codes)) &
        (df['CodeStr'].isin(growing_codes)) &
        (~df['_signal'])
    )
    # Path A: single-day spike vs 120d avg
    spike = (df['vol_vs_120d'] >= 1.5)
    # Path B: gradual 3-day buildup (じわじわ型)
    gradual = (df['vol_3d_vs_120d'] >= 1.8)
    return common & (spike | gradual)


def compute_accel_signals(df: pd.DataFrame, etf_codes: set,
                          growing_codes: set) -> pd.Series:
    """
    Volume acceleration signal (出来高加速シグナル).
    Fires when volume increases 30%+ day-over-day for 3 consecutive days.
    Catches the 'run-up' before a multiplier threshold is reached.
    """
    return (
        (df['vol_accel_3d'] >= 1) &
        (df['daily_ret'] >= -0.03) &
        (df['pct_from_50d_high'] >= -0.05) &
        (~df['price_frozen_5d']) &
        (df['turnover_avg_20'] >= 1e8) &
        (~df['CodeStr'].isin(etf_codes)) &
        (df['CodeStr'].isin(growing_codes)) &
        (~df['_signal']) & (~df['_ultra_early'])
    )


# ---------------------------------------------------------------------------
# Public entry point — called by Flask
# ---------------------------------------------------------------------------

_cached_result = {'data': None, 'ts': 0}
try:
    _SIGNALS_CACHE_TTL = int(os.environ.get('SIGNALS_CACHE_TTL_SEC', '86400'))
except ValueError:
    _SIGNALS_CACHE_TTL = 86400


def get_signal_stocks(data_dir: Optional[str] = None, force: bool = False) -> dict:
    """
    Compute current signal stocks, categorise by age, detect disappearances,
    and return chart data for each stock.

    Cached for 24h (override with SIGNALS_CACHE_TTL_SEC env var).
    Pass force=True to bypass cache (used by scheduled-refresh endpoint).
    """
    import time as _time
    if not force and _cached_result['data'] and (_time.time() - _cached_result['ts']) < _SIGNALS_CACHE_TTL:
        return _cached_result['data']

    ddir = Path(data_dir) if data_dir else DATA_DIR
    feat_path = ddir / '_vol_base_features.pkl'
    raw_path = ddir / '_intermediate_raw_data.pkl'

    if not feat_path.exists() or not raw_path.exists():
        _ensure_data_from_gcs(ddir)

    if not feat_path.exists() or not raw_path.exists():
        return {'error': 'Data files not found. Run the quant pipeline first.'}

    df = pd.read_pickle(feat_path)
    raw = pd.read_pickle(raw_path)
    master = raw.get('master')
    fins = raw.get('fins_summary', pd.DataFrame())

    # Ensure CodeStr exists
    if 'CodeStr' not in df.columns:
        df['CodeStr'] = df['Code'].astype(str)

    df = _ensure_features(df)

    # Master lookups
    master['Code'] = master['Code'].astype(str)
    name_map = master.set_index('Code')['CoName'].to_dict()
    sector_map = master.set_index('Code')['S33Nm'].to_dict()
    etf_codes = set(master[master['S33Nm'] == 'その他']['Code'].tolist())

    # Earnings growth
    growing_codes, op_map, eps_map = _compute_growing_codes(fins)

    # Signal masks (order matters — later ones exclude earlier)
    df['_signal'] = compute_signals(df, etf_codes, growing_codes)
    df['_ultra_early'] = compute_ultra_early_signals(df, etf_codes, growing_codes)
    df['_accel'] = compute_accel_signals(df, etf_codes, growing_codes)

    all_dates = sorted(df['Date'].unique())
    latest_date = all_dates[-1]
    latest_date_str = pd.Timestamp(latest_date).strftime('%Y-%m-%d')

    # Current signal codes
    current_mask = (df['Date'] == latest_date) & df['_signal']
    current_codes = set(df.loc[current_mask, 'CodeStr'])

    # First signal date per stock (across all history)
    sig_df = df[df['_signal']].copy()
    first_signal = sig_df.groupby('CodeStr')['Date'].min().to_dict()

    # Last-N trading-day sets
    last_5 = set(all_dates[-5:])
    last_10 = set(all_dates[-10:])

    new_5d, recent_10d, continuing = [], [], []
    for code in current_codes:
        fs = first_signal.get(code)
        if fs in last_5:
            new_5d.append(code)
        elif fs in last_10:
            recent_10d.append(code)
        else:
            continuing.append(code)

    # Signal dates per stock (last 10 trading days, for display)
    recent_sigs = df[(df['Date'].isin(last_10)) & df['_signal']]
    stock_signal_dates = recent_sigs.groupby('CodeStr')['Date'].apply(
        lambda x: sorted(x.unique())).to_dict()

    # Disappeared: stocks that had signal in last_10 but NOT on latest_date
    historical_codes = set(
        df[(df['Date'].isin(last_10 - {latest_date})) & df['_signal']]['CodeStr']
    )
    disappeared_codes = historical_codes - current_codes

    # Build stock records
    def _build_records(codes: set, df_latest: pd.DataFrame, chart_source: pd.DataFrame) -> list:
        sub = df_latest[df_latest['CodeStr'].isin(codes)].copy()
        sub = sub.sort_values('vol_base_ratio', ascending=False)
        records = []
        for _, r in sub.iterrows():
            code = r['CodeStr']
            # Trend label
            if r.get('ma5', 0) > r.get('ma25', 0) > r.get('ma75', 0):
                trend = '強↑↑'
            elif r.get('ma5', 0) > r.get('ma25', 0):
                trend = '上昇↑'
            elif r.get('ma25', 0) > r.get('ma75', 0):
                trend = '緩↑'
            else:
                trend = '横→'

            # Chart data — last 120 days
            stock_hist = chart_source[chart_source['CodeStr'] == code].sort_values('Date').tail(120)
            chart_dates = [pd.Timestamp(d).strftime('%Y-%m-%d') for d in stock_hist['Date']]
            chart_prices = stock_hist['Close'].tolist()
            chart_volumes = stock_hist['Volume'].tolist()

            # Signal marker indices (dates in chart_dates where signal was True)
            sig_dates_set = set()
            stock_sigs = sig_df[sig_df['CodeStr'] == code]
            for d in stock_sigs['Date']:
                sig_dates_set.add(pd.Timestamp(d).strftime('%Y-%m-%d'))
            signal_indices = [i for i, d in enumerate(chart_dates) if d in sig_dates_set]

            det_dates = stock_signal_dates.get(code, [])
            det_str = ', '.join(pd.Timestamp(d).strftime('%-m/%-d') for d in det_dates)

            fs = first_signal.get(code)
            fs_str = pd.Timestamp(fs).strftime('%Y-%m-%d') if pd.notna(fs) else ''

            records.append({
                'code': code[:4] if len(code) > 4 else code,
                'code_full': code,
                'name': str(name_map.get(code, code))[:30],
                'sector': str(sector_map.get(code, ''))[:14],
                'close': float(r['Close']) if pd.notna(r['Close']) else 0,
                'vol_base_ratio': round(float(r['vol_base_ratio']), 2) if pd.notna(r['vol_base_ratio']) else 0,
                'vol_above_count': int(r['vol_above_count_20d']) if pd.notna(r['vol_above_count_20d']) else 0,
                'turnover_avg': round(float(r['turnover_avg_20']) / 1e8, 1) if pd.notna(r['turnover_avg_20']) else 0,
                'rsi': round(float(r['rsi']), 1) if pd.notna(r['rsi']) else 0,
                'ma25_dev': round(float(r['ma25_dev']), 1) if pd.notna(r['ma25_dev']) else 0,
                'op_growth': round(float(op_map.get(code, float('nan'))), 0) if pd.notna(op_map.get(code)) else None,
                'eps_growth': round(float(eps_map.get(code, float('nan'))), 0) if pd.notna(eps_map.get(code)) else None,
                'trend': trend,
                'first_detected': fs_str,
                'detection_dates': det_str,
                'chart_dates': chart_dates,
                'chart_prices': [round(p, 1) if pd.notna(p) else 0 for p in chart_prices],
                'chart_volumes': [int(v) if pd.notna(v) else 0 for v in chart_volumes],
                'signal_indices': signal_indices,
            })
        return records

    latest_rows = df[df['Date'] == latest_date]
    new_records = _build_records(set(new_5d), latest_rows, df)
    recent_records = _build_records(set(recent_10d), latest_rows, df)
    cont_records = _build_records(set(continuing), latest_rows, df)

    # Disappeared records — use the most recent row where signal was True
    disap_records = []
    for code in disappeared_codes:
        last_sig_row = sig_df[sig_df['CodeStr'] == code].sort_values('Date').iloc[-1:]
        if last_sig_row.empty:
            continue
        r = last_sig_row.iloc[0]
        last_sig_date = pd.Timestamp(r['Date']).strftime('%Y-%m-%d')

        # Current price from latest date
        cur_row = df[(df['Date'] == latest_date) & (df['CodeStr'] == code)]
        cur_price = float(cur_row['Close'].iloc[0]) if not cur_row.empty else None

        stock_hist = df[df['CodeStr'] == code].sort_values('Date').tail(120)
        chart_dates = [pd.Timestamp(d).strftime('%Y-%m-%d') for d in stock_hist['Date']]
        chart_prices = stock_hist['Close'].tolist()
        chart_volumes = stock_hist['Volume'].tolist()

        sig_dates_set = set(
            pd.Timestamp(d).strftime('%Y-%m-%d')
            for d in sig_df[sig_df['CodeStr'] == code]['Date']
        )
        signal_indices = [i for i, d in enumerate(chart_dates) if d in sig_dates_set]

        disap_records.append({
            'code': code[:4] if len(code) > 4 else code,
            'code_full': code,
            'name': str(name_map.get(code, code))[:30],
            'sector': str(sector_map.get(code, ''))[:14],
            'last_signal_date': last_sig_date,
            'signal_price': round(float(r['Close']), 1) if pd.notna(r['Close']) else 0,
            'current_price': round(cur_price, 1) if cur_price else None,
            'price_change_pct': round((cur_price - float(r['Close'])) / float(r['Close']) * 100, 1) if cur_price and pd.notna(r['Close']) and float(r['Close']) > 0 else None,
            'chart_dates': chart_dates,
            'chart_prices': [round(p, 1) if pd.notna(p) else 0 for p in chart_prices],
            'chart_volumes': [int(v) if pd.notna(v) else 0 for v in chart_volumes],
            'signal_indices': signal_indices,
        })

    disap_records.sort(key=lambda x: x['last_signal_date'], reverse=True)

    # Ultra-early records (latest date only)
    ue_mask = (df['Date'] == latest_date) & df['_ultra_early']
    ue_codes = set(df.loc[ue_mask, 'CodeStr'])
    ue_records = _build_records(ue_codes, latest_rows, df)
    for r in ue_records:
        r['is_ultra_early'] = True

    # Acceleration records (latest date only)
    accel_mask = (df['Date'] == latest_date) & df['_accel']
    accel_codes = set(df.loc[accel_mask, 'CodeStr'])
    accel_records = _build_records(accel_codes, latest_rows, df)
    for r in accel_records:
        r['is_accel'] = True

    all_signals = new_records + recent_records + cont_records
    avg_vb = round(float(np.mean([s['vol_base_ratio'] for s in all_signals])), 2) if all_signals else 0

    result = {
        'latest_date': latest_date_str,
        'summary': {
            'total': len(all_signals),
            'new_5d': len(new_records),
            'recent_10d': len(recent_records),
            'continuing': len(cont_records),
            'disappeared': len(disap_records),
            'ultra_early': len(ue_records),
            'accel': len(accel_records),
            'avg_vb_ratio': avg_vb,
        },
        'ultra_early': ue_records,
        'accel': accel_records,
        'new_5d': new_records,
        'recent_10d': recent_records,
        'continuing': cont_records,
        'disappeared': disap_records,
        'all_signals': all_signals,
    }

    _cached_result['data'] = result
    _cached_result['ts'] = _time.time()
    return result
