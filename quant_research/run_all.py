#!/usr/bin/env python3
"""
全パイプライン統合実行スクリプト

STEP 1-8 を順に実行し、最終レポートを生成。

Usage:
    # フルパイプライン
    python -m quant_research.run_all

    # データ取得のみ
    python -m quant_research.run_all --step data

    # 特徴量計算まで
    python -m quant_research.run_all --step features

    # 高速モード（試行回数削減）
    python -m quant_research.run_all --fast
"""
import argparse
import logging
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("quant_research")


def main():
    parser = argparse.ArgumentParser(description="機関投資家資金流入シグナル研究パイプライン")
    parser.add_argument("--step", type=str, default="all",
                        choices=["data", "features", "backtest", "optimize", "ml", "regime", "report",
                                 "ml_v2", "strategy", "all"],
                        help="実行するステップ")
    parser.add_argument("--fast", action="store_true",
                        help="高速モード（試行回数を大幅削減）")
    parser.add_argument("--force-fetch", action="store_true",
                        help="キャッシュを無視してデータを再取得")
    parser.add_argument("--years", type=int, default=10,
                        help="取得するデータの年数")
    args = parser.parse_args()

    t_start = time.time()
    steps = _resolve_steps(args.step)

    if args.fast:
        logger.info("=== FAST MODE: 試行回数を削減して実行 ===")

    # ================================================================
    # STEP 1: データ取得
    # ================================================================
    if "data" in steps:
        logger.info("\n" + "=" * 60)
        logger.info("STEP 1: データ取得")
        logger.info("=" * 60)

        from .data_fetcher import fetch_all, prepare_price_dataframe

        raw_data = fetch_all(force=args.force_fetch, years=args.years)
        df = prepare_price_dataframe(raw_data["prices"], raw_data["master"])
        logger.info(f"準備完了: {df['Code'].nunique():,}銘柄, {len(df):,}行")

        _save_intermediate("df_prepared", df)

    # ================================================================
    # STEP 2: 特徴量計算
    # ================================================================
    if "features" in steps:
        logger.info("\n" + "=" * 60)
        logger.info("STEP 2: 特徴量エンジニアリング")
        logger.info("=" * 60)

        df = _load_intermediate("df_prepared")
        raw_data = _load_raw_data_if_needed()

        from .feature_engine import compute_all_features
        from .config import FORWARD_PERIODS
        from .fundamental import compute_fundamental_features

        df = compute_all_features(
            df,
            fins=raw_data.get("fins_summary"),
            forward_periods=FORWARD_PERIODS,
        )

        fins_data = raw_data.get("fins_summary")
        if fins_data is not None and not fins_data.empty:
            logger.info("Merging fundamental features...")
            df = compute_fundamental_features(df, fins_data)

        logger.info(f"特徴量計算完了: {len(df.columns)}列")
        _save_intermediate("df_features", df)

    # ================================================================
    # STEP 3-4: バックテスト
    # ================================================================
    if "backtest" in steps:
        logger.info("\n" + "=" * 60)
        logger.info("STEP 3-4: スクリーニング条件生成 + バックテスト")
        logger.info("=" * 60)

        df = _load_intermediate("df_features")

        from .backtester import split_train_test, run_batch_backtest, results_to_dataframe
        from .screener import generate_random_conditions

        train_df, test_df = split_train_test(df)

        n_conds = 5_000 if args.fast else 50_000
        conditions = generate_random_conditions(n=n_conds, seed=42)

        results = run_batch_backtest(train_df, conditions)
        results_df = results_to_dataframe(results)

        logger.info(f"\nTop 10 conditions (train):")
        for i, r in enumerate(results[:10]):
            logger.info(f"  {i+1}. WR={r.win_rate:.1%} Ret={r.avg_return:.2%} "
                        f"SR={r.sharpe_ratio:.2f} Score={r.composite_score:.4f}")

        _save_intermediate("train_df", train_df)
        _save_intermediate("test_df", test_df)
        _save_results("backtest_results", results)
        _save_intermediate("backtest_results_df", results_df)

    # ================================================================
    # STEP 5: 最適化
    # ================================================================
    if "optimize" in steps:
        logger.info("\n" + "=" * 60)
        logger.info("STEP 5: 条件最適化 (Random + Bayesian + GA)")
        logger.info("=" * 60)

        train_df = _load_intermediate("train_df")
        test_df = _load_intermediate("test_df")

        from .optimizer import run_full_optimization
        from .backtester import evaluate_out_of_sample

        opt_results = run_full_optimization(
            train_df,
            random_trials=5_000 if args.fast else 50_000,
            bayesian_trials=200 if args.fast else 2_000,
            ga_pop=50 if args.fast else 200,
            ga_gen=20 if args.fast else 100,
        )

        logger.info("\n--- Out-of-Sample 検証 ---")
        oos = evaluate_out_of_sample(opt_results["all"], test_df, top_n=30)
        for i, o in enumerate(oos[:5]):
            logger.info(f"  {i+1}. Train score={o['train_score']:.4f} → "
                        f"Test score={o['test_score']:.4f} "
                        f"(decay={o['score_decay']:.1%})")

        _save_results("optimization_results", opt_results)
        _save_results("oos_results", oos)

    # ================================================================
    # STEP 6: 機械学習
    # ================================================================
    if "ml" in steps:
        logger.info("\n" + "=" * 60)
        logger.info("STEP 6: 機械学習モデル")
        logger.info("=" * 60)

        df = _load_intermediate("df_features")

        from .ml_models import run_walk_forward_cv

        ml_results = run_walk_forward_cv(
            df, optimize=(not args.fast)
        )

        for name, res in ml_results.items():
            avg = res.get("metrics_avg", {})
            logger.info(f"\n{name}:")
            logger.info(f"  AUC={avg.get('roc_auc', 0):.4f} "
                        f"Precision={avg.get('precision', 0):.4f} "
                        f"Recall={avg.get('recall', 0):.4f}")

        _save_results("ml_results", ml_results)

    # ================================================================
    # STEP 6b: 本格MLパイプライン (ml_v2)
    # ================================================================
    if "ml_v2" in steps:
        logger.info("\n" + "=" * 60)
        logger.info("STEP 6b: 本格MLパイプライン (Ensemble + Stacking)")
        logger.info("=" * 60)

        df = _load_intermediate("df_features")
        raw_data = _load_raw_data_if_needed()
        index_df = raw_data.get("topix") or raw_data.get("nikkei")

        from .ml_pipeline import run_full_pipeline

        n_trials = 30 if args.fast else 100
        ml_v2_results = run_full_pipeline(
            df, index_df=index_df,
            n_optuna_trials=n_trials,
            train_end="2023-12-31",
            val_end="2024-06-30",
        )

        _save_results("ml_v2_results", ml_v2_results)

    # ================================================================
    # STEP 6c: 戦略グリッドサーチ (strategy)
    # ================================================================
    if "strategy" in steps:
        logger.info("\n" + "=" * 60)
        logger.info("STEP 6c: 戦略グリッドサーチ")
        logger.info("=" * 60)

        df = _load_intermediate("df_features")

        from .strategy_search import run_strategy_search

        strategy_results = run_strategy_search(
            df,
            train_end="2023-12-31",
            min_trades=30,
            min_test_winrate=0.55,
            max_entry_combos=5000 if args.fast else 20000,
        )

        _save_results("strategy_results", strategy_results)

    # ================================================================
    # STEP 7: 市場レジーム分析
    # ================================================================
    if "regime" in steps:
        logger.info("\n" + "=" * 60)
        logger.info("STEP 7: 市場レジーム分析")
        logger.info("=" * 60)

        df = _load_intermediate("df_features")
        raw_data = _load_raw_data_if_needed()

        from .regime_analyzer import (
            classify_regime, merge_regime, backtest_by_regime,
            regime_performance_summary, get_current_regime,
        )

        index_df = raw_data.get("topix")
        if index_df is None or index_df.empty:
            index_df = raw_data.get("nikkei")

        if index_df is not None and not index_df.empty:
            regime_df = classify_regime(index_df)
            df_with_regime = merge_regime(df, regime_df)

            opt_results = _load_results("optimization_results")
            top_conditions = []
            if opt_results and "all" in opt_results:
                top_conditions = [r.condition for r in opt_results["all"][:20]]

            regime_bt = backtest_by_regime(df_with_regime, top_conditions)
            regime_summary = regime_performance_summary(regime_bt)
            current_regime = get_current_regime(index_df)

            logger.info(f"\n現在の市場レジーム: {current_regime}")
            logger.info(f"\nレジーム別パフォーマンス:")
            for _, row in regime_summary.iterrows():
                logger.info(f"  {row['regime']}: WR={row['best_win_rate']:.1%} "
                            f"SR={row['best_sharpe']:.2f}")

            _save_results("regime_results", regime_bt)
            _save_intermediate("regime_summary", regime_summary)
            _save_results("current_regime", current_regime)
        else:
            logger.warning("指数データなし — レジーム分析をスキップ")
            _save_results("regime_results", {})
            _save_intermediate("regime_summary", pd.DataFrame())
            _save_results("current_regime", "unknown")

    # ================================================================
    # STEP 8: レポート生成
    # ================================================================
    if "report" in steps:
        logger.info("\n" + "=" * 60)
        logger.info("STEP 8: 最終レポート生成")
        logger.info("=" * 60)

        from .reporter import (
            generate_final_report,
            plot_equity_curves, plot_optimization_landscape,
            plot_feature_importance, plot_regime_performance,
            plot_volume_institutional_correlation,
            plot_holding_period_comparison, plot_theme_performance,
        )
        from .theme_analyzer import (
            classify_themes, analyze_theme_performance,
            find_tenbaggers, detect_institutional_accumulation,
            get_tenbagger_common_features,
        )
        from .config import DATA_DIR

        df = _load_intermediate("df_features")
        opt_results = _load_results("optimization_results")
        ml_results = _load_results("ml_results")
        regime_results = _load_results("regime_results")
        regime_summary = _load_intermediate("regime_summary")
        current_regime = _load_results("current_regime")
        raw_data = _load_raw_data_if_needed()

        theme_performance = pd.DataFrame()
        tenbagger_analysis = {}
        institutional_accum = {}
        theme_map = {}

        from .data_fetcher import _load_cache as _lc
        master_data = raw_data.get("master")
        if master_data is None or (hasattr(master_data, 'empty') and master_data.empty):
            master_data = _lc("master")
        if master_data is not None and not master_data.empty:
            logger.info("Running theme classification...")
            theme_map = classify_themes(master_data)
            theme_performance = analyze_theme_performance(df, theme_map)

        logger.info("Running tenbagger analysis...")
        tenbaggers_df = find_tenbaggers(df, min_multiple=2.0)
        tenbagger_analysis = get_tenbagger_common_features(tenbaggers_df, theme_map)

        logger.info("Detecting institutional accumulation signals...")
        accum_mask = detect_institutional_accumulation(df)
        n_accum = accum_mask.sum()
        institutional_accum = {
            "total_signals": int(n_accum),
            "unique_stocks": int(df.loc[accum_mask, "Code"].nunique()) if n_accum > 0 else 0,
        }
        if n_accum > 0:
            latest_date = df["Date"].max()
            latest_accum = df.loc[accum_mask & (df["Date"] == latest_date)]
            institutional_accum["current_candidates"] = latest_accum[["Code", "Close", "vol_ratio"]].to_dict("records") if not latest_accum.empty else []

        report = generate_final_report(
            optimization_results=opt_results or {},
            ml_results=ml_results or {},
            regime_results=regime_results or {},
            regime_summary=regime_summary,
            df=df,
            current_regime=current_regime or "unknown",
            theme_performance=theme_performance,
            tenbagger_analysis=tenbagger_analysis,
            institutional_accumulation=institutional_accum,
        )

        report_dir = DATA_DIR / "reports"
        report_dir.mkdir(exist_ok=True)

        if opt_results and "all" in opt_results:
            top3 = opt_results["all"][:3]
            plot_equity_curves(
                top3,
                labels=["Best WR", "Best Return", "Best Stable"],
                save_path=str(report_dir / "equity_curves.png"),
            )
            plot_optimization_landscape(
                opt_results["all"][:500],
                save_path=str(report_dir / "optimization_landscape.png"),
            )

        if ml_results:
            plot_feature_importance(
                ml_results,
                save_path=str(report_dir / "feature_importance.png"),
            )

        if regime_summary is not None and not regime_summary.empty:
            plot_regime_performance(
                regime_summary,
                save_path=str(report_dir / "regime_performance.png"),
            )

        if raw_data.get("investor_types") is not None:
            plot_volume_institutional_correlation(
                df, raw_data["investor_types"],
                save_path=str(report_dir / "vol_institutional_correlation.png"),
            )

        holding_comp = report.get("holding_period_comparison", [])
        if holding_comp:
            plot_holding_period_comparison(
                holding_comp,
                save_path=str(report_dir / "holding_period_comparison.png"),
            )

        if not theme_performance.empty:
            plot_theme_performance(
                theme_performance,
                save_path=str(report_dir / "theme_performance.png"),
            )

        # Historical validation
        if opt_results and "all" in opt_results and opt_results["all"]:
            from .historical_validator import run_full_historical_validation
            logger.info("\nRunning historical validation on best condition...")
            best_cond = opt_results["all"][0].condition
            hist_validation = run_full_historical_validation(
                df, best_cond,
                months_back=[3, 6, 12],
                forward_days=[20, 60, 120],
            )
            _save_results("historical_validation", hist_validation)
            report["historical_validation"] = hist_validation.get("summary", {})

        logger.info(f"\nレポート出力先: {report_dir}")
        n_signals = len(report.get("current_signals", []))
        logger.info(f"現在シグナル銘柄数: {n_signals}")

    elapsed = time.time() - t_start
    logger.info(f"\n{'=' * 60}")
    logger.info(f"パイプライン完了 (所要時間: {elapsed / 60:.1f}分)")
    logger.info(f"{'=' * 60}")


# ============================================================
# ヘルパー
# ============================================================

def _resolve_steps(step: str) -> list:
    """ステップ名を実行すべきステップのリストに変換"""
    order = ["data", "features", "backtest", "optimize", "ml", "ml_v2", "strategy", "regime", "report"]
    if step == "all":
        return order
    if step in ("ml_v2", "strategy"):
        return ["data", "features", step]
    idx = order.index(step)
    return order[:idx + 1]


def _save_intermediate(name: str, obj):
    """中間結果を保存"""
    from .config import DATA_DIR
    path = DATA_DIR / f"_intermediate_{name}.pkl"
    pd.to_pickle(obj, path)


def _load_intermediate(name: str):
    """中間結果を読み込み"""
    from .config import DATA_DIR
    path = DATA_DIR / f"_intermediate_{name}.pkl"
    if path.exists():
        return pd.read_pickle(path)
    raise FileNotFoundError(f"Intermediate file not found: {path}. Run previous steps first.")


def _save_results(name: str, obj):
    """分析結果を保存"""
    from .config import DATA_DIR
    path = DATA_DIR / f"_results_{name}.pkl"
    pd.to_pickle(obj, path)


def _load_results(name: str):
    """分析結果を読み込み"""
    from .config import DATA_DIR
    path = DATA_DIR / f"_results_{name}.pkl"
    if path.exists():
        return pd.read_pickle(path)
    return None


def _load_raw_data_if_needed() -> dict:
    """キャッシュ済みのParquetから生データを読み込み"""
    from .data_fetcher import _load_cache
    return {
        "master": _load_cache("master"),
        "topix": _load_cache("index_topix"),
        "nikkei": _load_cache("index_nikkei"),
        "investor_types": _load_cache("investor_types"),
        "fins_summary": _load_cache("fins_summary"),
    }


if __name__ == "__main__":
    main()
