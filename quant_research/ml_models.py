"""
機械学習モデル: LightGBM / XGBoost / RandomForest

目的変数: 5日後リターン > 3%
特徴量: 出来高・テクニカル指標群
検証: 時系列Walk-Forward CV
"""
import logging
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score, f1_score,
    roc_auc_score, classification_report,
)
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler

from .config import ML_TARGET_RETURN, ML_TARGET_DAYS, ML_CV_FOLDS

logger = logging.getLogger(__name__)

FEATURE_COLUMNS = [
    "vol_ratio", "vol_zscore", "turnover_ratio", "vol_ratio_5d",
    "mom_5d", "mom_10d", "mom_20d",
    "ma5_dev", "ma25_dev", "ma75_dev",
    "ma5_above_ma25", "ma25_above_ma75", "full_uptrend",
    "rsi", "macd", "macd_signal", "macd_hist",
    "volatility", "atr_pct",
    "breakout_50d", "breakout_200d",
    "near_52w_high", "pct_from_52w_high",
]


def prepare_ml_dataset(df: pd.DataFrame,
                       target_days: int = ML_TARGET_DAYS,
                       target_return: float = ML_TARGET_RETURN,
                       features: List[str] = None) -> Tuple[pd.DataFrame, pd.Series]:
    """
    ML用のX, yを構築。

    y = 1 if fwd_{target_days}d_return > target_return else 0
    """
    if features is None:
        features = [f for f in FEATURE_COLUMNS if f in df.columns]

    ret_col = f"fwd_{target_days}d_return"
    if ret_col not in df.columns:
        raise ValueError(f"Column {ret_col} not found. Run add_forward_returns first.")

    valid = df.dropna(subset=[ret_col] + features).copy()

    X = valid[features].copy()
    y = (valid[ret_col] > target_return).astype(int)

    logger.info(f"ML dataset: {len(X):,} samples, {len(features)} features, "
                f"positive rate: {y.mean():.1%}")

    return X, y


def walk_forward_split(df: pd.DataFrame,
                       n_folds: int = ML_CV_FOLDS) -> List[Tuple]:
    """
    時系列Walk-Forward CVの分割を生成。

    各foldで訓練期間を拡大し、テスト期間は固定長。
    未来のデータで訓練しない。
    """
    dates = sorted(df["Date"].unique())
    n_dates = len(dates)
    test_size = n_dates // (n_folds + 1)

    splits = []
    for i in range(n_folds):
        train_end_idx = (i + 1) * test_size + test_size
        test_start_idx = train_end_idx
        test_end_idx = test_start_idx + test_size

        if test_end_idx > n_dates:
            break

        train_end = dates[train_end_idx - 1]
        test_start = dates[test_start_idx]
        test_end = dates[min(test_end_idx - 1, n_dates - 1)]

        train_mask = df["Date"] <= train_end
        test_mask = (df["Date"] >= test_start) & (df["Date"] <= test_end)

        splits.append((train_mask, test_mask, train_end, test_end))

    logger.info(f"Walk-forward CV: {len(splits)} folds")
    return splits


def train_lightgbm(X_train, y_train, X_test, y_test,
                   optimize_params: bool = True) -> Dict:
    """LightGBMモデルの訓練・評価"""
    import lightgbm as lgb

    if optimize_params:
        try:
            params = _optimize_lgbm_params(X_train, y_train)
        except Exception:
            params = {}
    else:
        params = {}

    base_params = {
        "objective": "binary",
        "metric": "auc",
        "boosting_type": "gbdt",
        "num_leaves": 31,
        "learning_rate": 0.05,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 5,
        "verbose": -1,
        "n_jobs": -1,
        "random_state": 42,
    }
    base_params.update(params)

    model = lgb.LGBMClassifier(n_estimators=500, **base_params)
    model.fit(
        X_train, y_train,
        eval_set=[(X_test, y_test)],
        callbacks=[lgb.early_stopping(50, verbose=False)],
    )

    y_pred = model.predict(X_test)
    y_prob = model.predict_proba(X_test)[:, 1]

    importance = pd.Series(
        model.feature_importances_, index=X_train.columns
    ).sort_values(ascending=False)

    return {
        "model": model,
        "name": "LightGBM",
        "y_pred": y_pred,
        "y_prob": y_prob,
        "importance": importance,
        "metrics": _compute_metrics(y_test, y_pred, y_prob),
    }


def _optimize_lgbm_params(X, y, n_trials: int = 50) -> Dict:
    """OptunaでLightGBMハイパーパラメータを最適化"""
    import optuna
    import lightgbm as lgb
    from sklearn.model_selection import cross_val_score

    optuna.logging.set_verbosity(optuna.logging.WARNING)

    def objective(trial):
        params = {
            "num_leaves": trial.suggest_int("num_leaves", 15, 127),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
            "feature_fraction": trial.suggest_float("feature_fraction", 0.5, 1.0),
            "bagging_fraction": trial.suggest_float("bagging_fraction", 0.5, 1.0),
            "min_child_samples": trial.suggest_int("min_child_samples", 5, 100),
            "reg_alpha": trial.suggest_float("reg_alpha", 1e-8, 10.0, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 1e-8, 10.0, log=True),
        }
        model = lgb.LGBMClassifier(
            n_estimators=200, verbose=-1, random_state=42, **params
        )
        scores = cross_val_score(model, X, y, cv=3, scoring="roc_auc", n_jobs=-1)
        return scores.mean()

    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
    return study.best_params


def train_xgboost(X_train, y_train, X_test, y_test,
                  optimize_params: bool = True) -> Dict:
    """XGBoostモデルの訓練・評価"""
    import xgboost as xgb

    if optimize_params:
        try:
            params = _optimize_xgb_params(X_train, y_train)
        except Exception:
            params = {}
    else:
        params = {}

    base_params = {
        "objective": "binary:logistic",
        "eval_metric": "auc",
        "max_depth": 6,
        "learning_rate": 0.05,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "random_state": 42,
        "n_jobs": -1,
        "verbosity": 0,
    }
    base_params.update(params)

    model = xgb.XGBClassifier(n_estimators=500, early_stopping_rounds=50, **base_params)
    model.fit(
        X_train, y_train,
        eval_set=[(X_test, y_test)],
        verbose=False,
    )

    y_pred = model.predict(X_test)
    y_prob = model.predict_proba(X_test)[:, 1]

    importance = pd.Series(
        model.feature_importances_, index=X_train.columns
    ).sort_values(ascending=False)

    return {
        "model": model,
        "name": "XGBoost",
        "y_pred": y_pred,
        "y_prob": y_prob,
        "importance": importance,
        "metrics": _compute_metrics(y_test, y_pred, y_prob),
    }


def _optimize_xgb_params(X, y, n_trials: int = 50) -> Dict:
    """OptunaでXGBoostハイパーパラメータを最適化"""
    import optuna
    import xgboost as xgb
    from sklearn.model_selection import cross_val_score

    optuna.logging.set_verbosity(optuna.logging.WARNING)

    def objective(trial):
        params = {
            "max_depth": trial.suggest_int("max_depth", 3, 10),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
            "subsample": trial.suggest_float("subsample", 0.5, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
            "min_child_weight": trial.suggest_int("min_child_weight", 1, 20),
            "reg_alpha": trial.suggest_float("reg_alpha", 1e-8, 10.0, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 1e-8, 10.0, log=True),
        }
        model = xgb.XGBClassifier(
            n_estimators=200, verbosity=0, random_state=42, **params
        )
        scores = cross_val_score(model, X, y, cv=3, scoring="roc_auc", n_jobs=-1)
        return scores.mean()

    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
    return study.best_params


def train_random_forest(X_train, y_train, X_test, y_test) -> Dict:
    """RandomForestモデルの訓練・評価"""
    model = RandomForestClassifier(
        n_estimators=500,
        max_depth=10,
        min_samples_leaf=20,
        max_features="sqrt",
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    y_prob = model.predict_proba(X_test)[:, 1]

    importance = pd.Series(
        model.feature_importances_, index=X_train.columns
    ).sort_values(ascending=False)

    return {
        "model": model,
        "name": "RandomForest",
        "y_pred": y_pred,
        "y_prob": y_prob,
        "importance": importance,
        "metrics": _compute_metrics(y_test, y_pred, y_prob),
    }


def _compute_metrics(y_true, y_pred, y_prob) -> Dict:
    """分類メトリクスを計算"""
    metrics = {
        "accuracy": accuracy_score(y_true, y_pred),
        "precision": precision_score(y_true, y_pred, zero_division=0),
        "recall": recall_score(y_true, y_pred, zero_division=0),
        "f1": f1_score(y_true, y_pred, zero_division=0),
    }
    try:
        metrics["roc_auc"] = roc_auc_score(y_true, y_prob)
    except ValueError:
        metrics["roc_auc"] = 0.0
    return metrics


# ============================================================
# Walk-Forward CV 統合実行
# ============================================================

def run_walk_forward_cv(df: pd.DataFrame,
                        features: List[str] = None,
                        target_days: int = ML_TARGET_DAYS,
                        target_return: float = ML_TARGET_RETURN,
                        optimize: bool = True) -> Dict:
    """
    全3モデルをWalk-Forward CVで評価。

    Returns:
        各モデルのfold別結果、平均メトリクス、特徴量重要度
    """
    if features is None:
        features = [f for f in FEATURE_COLUMNS if f in df.columns]

    ret_col = f"fwd_{target_days}d_return"
    valid = df.dropna(subset=[ret_col] + features).copy()

    splits = walk_forward_split(valid)
    if not splits:
        raise ValueError("Not enough data for walk-forward CV")

    models_config = [
        ("LightGBM", train_lightgbm),
        ("XGBoost", train_xgboost),
        ("RandomForest", lambda Xtr, ytr, Xte, yte: train_random_forest(Xtr, ytr, Xte, yte)),
    ]

    results = {name: {"folds": [], "metrics_avg": {}} for name, _ in models_config}
    all_importance = {name: [] for name, _ in models_config}

    scaler = StandardScaler()

    for fold_i, (train_mask, test_mask, train_end, test_end) in enumerate(splits):
        logger.info(f"\n--- Fold {fold_i + 1}/{len(splits)} "
                    f"(train to {train_end}, test to {test_end}) ---")

        train_data = valid[train_mask]
        test_data = valid[test_mask]

        X_train_raw = train_data[features]
        X_test_raw = test_data[features]
        y_train = (train_data[ret_col] > target_return).astype(int)
        y_test = (test_data[ret_col] > target_return).astype(int)

        if len(y_train) < 100 or len(y_test) < 50:
            logger.warning(f"  Skipping fold {fold_i + 1}: insufficient data")
            continue

        scaler.fit(X_train_raw)
        X_train = pd.DataFrame(
            scaler.transform(X_train_raw), columns=features, index=X_train_raw.index
        )
        X_test = pd.DataFrame(
            scaler.transform(X_test_raw), columns=features, index=X_test_raw.index
        )

        for name, train_fn in models_config:
            logger.info(f"  Training {name}...")
            try:
                if name == "RandomForest":
                    fold_result = train_fn(X_train, y_train, X_test, y_test)
                else:
                    fold_result = train_fn(
                        X_train, y_train, X_test, y_test,
                        optimize_params=(optimize and fold_i == 0)
                    )
                results[name]["folds"].append(fold_result["metrics"])
                all_importance[name].append(fold_result["importance"])
                logger.info(f"    AUC: {fold_result['metrics']['roc_auc']:.4f}, "
                            f"Precision: {fold_result['metrics']['precision']:.4f}")
            except Exception as e:
                logger.warning(f"    {name} failed: {e}")

    for name in results:
        folds = results[name]["folds"]
        if folds:
            avg = {}
            for key in folds[0]:
                avg[key] = np.mean([f[key] for f in folds])
            results[name]["metrics_avg"] = avg

        imps = all_importance[name]
        if imps:
            combined = pd.concat(imps, axis=1).mean(axis=1).sort_values(ascending=False)
            results[name]["feature_importance"] = combined

    return results


def get_ensemble_predictions(df: pd.DataFrame,
                             models: Dict,
                             features: List[str] = None) -> pd.Series:
    """複数モデルのアンサンブル予測（確率平均）"""
    if features is None:
        features = [f for f in FEATURE_COLUMNS if f in df.columns]

    X = df[features].dropna()

    probs = []
    for name, model_info in models.items():
        if "model" in model_info:
            prob = model_info["model"].predict_proba(X)[:, 1]
            probs.append(prob)

    if not probs:
        return pd.Series(dtype=float)

    ensemble = np.mean(probs, axis=0)
    return pd.Series(ensemble, index=X.index, name="ensemble_prob")
