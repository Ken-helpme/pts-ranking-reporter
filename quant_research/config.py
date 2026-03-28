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
DATA_YEARS = 1
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
    "holding_days": [3, 5, 10, 20, 60],
}

FORWARD_PERIODS = [3, 5, 10, 20, 60, 120, 250]

# --- ファンダメンタルパラメータ ---
FUNDAMENTAL_PARAMS = {
    "revenue_growth_min": (0.0, 0.3),
    "eps_growth_min": (0.0, 0.5),
    "roe_min": (0.0, 0.25),
    "op_margin_min": (0.0, 0.20),
    "per_max": (5, 100),
    "pbr_max": (0.5, 10.0),
    "equity_ratio_min": (0.1, 0.6),
}

GROWTH_THEMES = [
    "AI", "半導体", "防衛", "宇宙", "データセンター",
    "EV", "再生エネルギー", "ロボット", "医療",
]

THEME_KEYWORDS = {
    "AI": ["AI", "人工知能", "機械学習", "ディープラーニング", "ChatGPT", "生成AI", "LLM"],
    "半導体": ["半導体", "セミコンダクター", "ウエハ", "ファウンドリ", "チップ", "NAND", "DRAM"],
    "防衛": ["防衛", "防空", "ミサイル", "軍事", "安全保障", "自衛"],
    "宇宙": ["宇宙", "衛星", "ロケット", "スペース"],
    "データセンター": ["データセンター", "サーバー", "クラウド", "IDC"],
    "EV": ["EV", "電気自動車", "電動", "バッテリー", "リチウム", "充電"],
    "再生エネルギー": ["太陽光", "風力", "再生可能", "グリーン", "水素", "蓄電"],
    "ロボット": ["ロボット", "自動化", "FA", "産業用ロボ", "協働ロボ"],
    "医療": ["医療", "バイオ", "製薬", "創薬", "ヘルスケア", "医薬", "遺伝子"],
}

# --- バックテスト設定 ---
SLIPPAGE_PCT = 0.1          # 片道0.1%
COMMISSION_PCT = 0.0         # 手数料（ネット証券はほぼ無料）
MIN_TRADES = 30              # 最低トレード数
MIN_FIRE_RATE = 0.1          # 最低発動率 10%
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
