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
                        choices=["data", "features", "backtest", "optimize", "ml", "regime", "report", "all"],
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

        df = compute_all_features(
            df,
            fins=raw_data.get("fins_summary"),
            forward_periods=[3, 5, 10],
        )

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
        )
        from .config import DATA_DIR

        df = _load_intermediate("df_features")
        opt_results = _load_results("optimization_results")
        ml_results = _load_results("ml_results")
        regime_results = _load_results("regime_results")
        regime_summary = _load_intermediate("regime_summary")
        current_regime = _load_results("current_regime")

        report = generate_final_report(
            optimization_results=opt_results or {},
            ml_results=ml_results or {},
            regime_results=regime_results or {},
            regime_summary=regime_summary,
            df=df,
            current_regime=current_regime or "unknown",
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

        raw_data = _load_raw_data_if_needed()
        if raw_data.get("investor_types") is not None:
            plot_volume_institutional_correlation(
                df, raw_data["investor_types"],
                save_path=str(report_dir / "vol_institutional_correlation.png"),
            )

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
    order = ["data", "features", "backtest", "optimize", "ml", "regime", "report"]
    if step == "all":
        return order
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
    from .data_fetcher import (
        _load_cache,
    )
    return {
        "topix": _load_cache("index_topix"),
        "nikkei": _load_cache("index_nikkei"),
        "investor_types": _load_cache("investor_types"),
        "fins_summary": _load_cache("fins_summary"),
    }


if __name__ == "__main__":
    main()
