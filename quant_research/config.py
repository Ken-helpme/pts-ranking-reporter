"""
設定・定数・パラメータ空間の定義
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

JQUANTS_API_KEY = os.getenv("JQUANTS_API_KEY", "")

# --- データ取得設定 ---
DATA_YEARS = 10
FETCH_WORKERS = 4

# --- 特徴量パラメータ ---
VOLUME_LOOKBACK = 20
MA_PERIODS = [5, 25, 75]
RSI_PERIOD = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
ATR_PERIOD = 14
VOLATILITY_PERIOD = 20
BREAKOUT_PERIODS = [50, 200]

# --- スクリーニングパラメータ空間 ---
PARAM_SPACE = {
    "volume_ratio_min": (1.5, 10.0),
    "volume_ratio_max": (2.0, 15.0),
    "turnover_min": (5e7, 5e9),       # 5000万〜50億
    "market_cap_min": (5e9, 1e12),     # 50億〜1兆
    "market_cap_max": (1e10, 5e12),
    "trend_condition": [
        "none",
        "ma5_above_ma25",
        "ma25_above_ma75",
        "ma5_above_ma25_above_ma75",
    ],
    "price_position": [
        "none",
        "near_52w_high",               # 52週高値の95%以上
        "breakout_50d",
        "breakout_200d",
    ],
    "holding_days": [3, 5, 10],
}

# --- バックテスト設定 ---
SLIPPAGE_PCT = 0.1          # 片道0.1%
COMMISSION_PCT = 0.0         # 手数料（ネット証券はほぼ無料）
MIN_TRADES = 100             # 最低トレード数
MIN_FIRE_RATE = 0.4          # 最低発動率 40%
TRAIN_RATIO = 0.7            # 訓練期間比率

# --- 最適化設定 ---
RANDOM_SEARCH_TRIALS = 50_000
BAYESIAN_TRIALS = 2_000
GA_POPULATION = 200
GA_GENERATIONS = 100

# --- ML設定 ---
ML_TARGET_RETURN = 0.03      # 5日後リターン > 3%
ML_TARGET_DAYS = 5
ML_CV_FOLDS = 5

# --- 市場レジーム ---
REGIME_MA_SHORT = 50
REGIME_MA_LONG = 200
REGIME_MOMENTUM_DAYS = 20
