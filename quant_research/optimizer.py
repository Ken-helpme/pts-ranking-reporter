"""
条件最適化エンジン

3つの最適化手法:
  1. ランダムサーチ — 広域探索
  2. ベイズ最適化 (Optuna TPE) — 有望領域の深掘り
  3. 遺伝的アルゴリズム (DEAP) — 条件の進化的発見
"""
import logging
import random as stdlib_random
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .config import (
    RANDOM_SEARCH_TRIALS, BAYESIAN_TRIALS,
    GA_POPULATION, GA_GENERATIONS, MIN_TRADES,
)
from .screener import generate_random_conditions, apply_condition
from .backtester import run_backtest, BacktestResult

logger = logging.getLogger(__name__)


# ============================================================
# 1. ランダムサーチ
# ============================================================

def random_search(df: pd.DataFrame,
                  n_trials: int = RANDOM_SEARCH_TRIALS,
                  min_trades: int = MIN_TRADES,
                  seed: int = 42,
                  show_progress: bool = True) -> List[BacktestResult]:
    """
    ランダム条件生成 → バックテスト → フィルタリング。
    """
    from tqdm import tqdm

    conditions = generate_random_conditions(n=n_trials, seed=seed)
    logger.info(f"Random search: {len(conditions):,} conditions to evaluate")

    results = []
    iterator = tqdm(conditions, desc="Random Search") if show_progress else conditions

    for cond in iterator:
        res = run_backtest(df, cond)
        if res and res.n_trades >= min_trades:
            results.append(res)

    results.sort(key=lambda r: r.composite_score, reverse=True)
    logger.info(f"Random search complete: {len(results):,} valid results")
    return results


# ============================================================
# 2. ベイズ最適化 (Optuna)
# ============================================================

def bayesian_optimization(df: pd.DataFrame,
                          n_trials: int = BAYESIAN_TRIALS,
                          min_trades: int = MIN_TRADES,
                          seed_results: List[BacktestResult] = None,
                          show_progress: bool = True) -> Tuple[List[BacktestResult], object]:
    """
    Optuna TPEサンプラーによるベイズ最適化。

    seed_results: ランダムサーチの上位結果をシード条件として使用。
    """
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    all_results = []

    def objective(trial):
        cond = {
            "vol_ratio_min": trial.suggest_float("vol_ratio_min", 1.5, 10.0, step=0.5),
            "vol_zscore_min": trial.suggest_float("vol_zscore_min", 0.0, 5.0, step=0.5),
            "turnover_min": trial.suggest_float(
                "turnover_min", np.log10(5e7), np.log10(5e9)
            ),
            "market_cap_min": trial.suggest_float(
                "market_cap_min", np.log10(5e9), np.log10(1e12)
            ),
            "market_cap_max": trial.suggest_float(
                "market_cap_max", np.log10(1e10), np.log10(5e12)
            ),
            "trend_condition": trial.suggest_categorical(
                "trend_condition",
                ["none", "ma5_above_ma25", "ma25_above_ma75", "ma5_above_ma25_above_ma75"]
            ),
            "price_position": trial.suggest_categorical(
                "price_position",
                ["none", "near_52w_high", "breakout_50d", "breakout_200d"]
            ),
            "holding_days": trial.suggest_categorical("holding_days", [3, 5, 10]),
            "rsi_min": trial.suggest_int("rsi_min", 0, 60, step=10),
            "rsi_max": trial.suggest_int("rsi_max", 50, 100, step=10),
            "momentum_min": trial.suggest_float("momentum_min", -0.05, 0.15, step=0.01),
            "macd_condition": trial.suggest_categorical(
                "macd_condition", ["none", "positive", "cross_up"]
            ),
            "volatility_max": trial.suggest_float("volatility_max", 0.01, 0.08, step=0.005),
        }

        cond["turnover_min"] = 10 ** cond["turnover_min"]
        cond["market_cap_min"] = 10 ** cond["market_cap_min"]
        cond["market_cap_max"] = 10 ** cond["market_cap_max"]

        if cond["market_cap_min"] > cond["market_cap_max"]:
            cond["market_cap_min"], cond["market_cap_max"] = (
                cond["market_cap_max"], cond["market_cap_min"]
            )
        if cond["rsi_min"] >= cond["rsi_max"]:
            cond["rsi_max"] = min(cond["rsi_min"] + 20, 100)

        res = run_backtest(df, cond)
        if res is None or res.n_trades < min_trades:
            return -1.0

        all_results.append(res)
        return res.composite_score

    sampler = optuna.samplers.TPESampler(seed=42)
    study = optuna.create_study(direction="maximize", sampler=sampler)

    if seed_results:
        for sr in seed_results[:100]:
            params = _condition_to_optuna_params(sr.condition)
            if params:
                try:
                    study.enqueue_trial(params)
                except Exception:
                    pass

    if show_progress:
        from tqdm import tqdm
        with tqdm(total=n_trials, desc="Bayesian Opt") as pbar:
            def callback(study, trial):
                pbar.update(1)
            study.optimize(objective, n_trials=n_trials, callbacks=[callback])
    else:
        study.optimize(objective, n_trials=n_trials)

    all_results.sort(key=lambda r: r.composite_score, reverse=True)
    logger.info(f"Bayesian optimization complete: {len(all_results):,} valid results, "
                f"best score={study.best_value:.4f}")

    return all_results, study


def _condition_to_optuna_params(cond: Dict) -> Optional[Dict]:
    """条件辞書をOptuna enqueue用パラメータに変換"""
    try:
        return {
            "vol_ratio_min": round(cond["vol_ratio_min"] * 2) / 2,
            "vol_zscore_min": round(cond.get("vol_zscore_min", 1.0) * 2) / 2,
            "turnover_min": np.log10(cond["turnover_min"]),
            "market_cap_min": np.log10(cond["market_cap_min"]),
            "market_cap_max": np.log10(cond["market_cap_max"]),
            "trend_condition": cond.get("trend_condition", "none"),
            "price_position": cond.get("price_position", "none"),
            "holding_days": cond.get("holding_days", 5),
            "rsi_min": cond.get("rsi_min", 0),
            "rsi_max": cond.get("rsi_max", 100),
            "momentum_min": round(cond.get("momentum_min", 0.0), 2),
            "macd_condition": cond.get("macd_condition", "none"),
            "volatility_max": round(cond.get("volatility_max", 0.04), 3),
        }
    except (KeyError, TypeError):
        return None


# ============================================================
# 3. 遺伝的アルゴリズム (DEAP)
# ============================================================

def genetic_algorithm(df: pd.DataFrame,
                      population_size: int = GA_POPULATION,
                      n_generations: int = GA_GENERATIONS,
                      min_trades: int = MIN_TRADES,
                      seed_results: List[BacktestResult] = None,
                      show_progress: bool = True) -> List[BacktestResult]:
    """
    遺伝的アルゴリズムで売買条件を進化的に最適化。

    染色体 = 売買条件パラメータの実数ベクトル
    適応度 = composite_score
    """
    from deap import base, creator, tools, algorithms

    GENE_RANGES = [
        ("vol_ratio_min",  1.5, 10.0),
        ("vol_zscore_min", 0.0, 5.0),
        ("turnover_min_log", np.log10(5e7), np.log10(5e9)),
        ("market_cap_min_log", np.log10(5e9), np.log10(1e12)),
        ("market_cap_max_log", np.log10(1e10), np.log10(5e12)),
        ("trend_idx", 0, 3),
        ("price_idx", 0, 3),
        ("holding_idx", 0, 2),
        ("rsi_min", 0, 60),
        ("rsi_max", 50, 100),
        ("momentum_min", -0.05, 0.15),
        ("macd_idx", 0, 2),
        ("volatility_max", 0.01, 0.08),
    ]

    TREND_OPTIONS = ["none", "ma5_above_ma25", "ma25_above_ma75", "ma5_above_ma25_above_ma75"]
    PRICE_OPTIONS = ["none", "near_52w_high", "breakout_50d", "breakout_200d"]
    HOLDING_OPTIONS = [3, 5, 10]
    MACD_OPTIONS = ["none", "positive", "cross_up"]

    if not hasattr(creator, "FitnessMax"):
        creator.create("FitnessMax", base.Fitness, weights=(1.0,))
    if not hasattr(creator, "Individual"):
        creator.create("Individual", list, fitness=creator.FitnessMax)

    toolbox = base.Toolbox()

    def random_gene():
        return [np.random.uniform(lo, hi) for _, lo, hi in GENE_RANGES]

    toolbox.register("individual", tools.initIterate, creator.Individual, random_gene)
    toolbox.register("population", tools.initRepeat, list, toolbox.individual)

    def decode(individual) -> Dict:
        vals = individual
        cap_min_log = vals[3]
        cap_max_log = vals[4]
        if cap_min_log > cap_max_log:
            cap_min_log, cap_max_log = cap_max_log, cap_min_log

        rsi_lo = int(np.clip(vals[8], 0, 60))
        rsi_hi = int(np.clip(vals[9], 50, 100))
        if rsi_lo >= rsi_hi:
            rsi_hi = min(rsi_lo + 20, 100)

        return {
            "vol_ratio_min": round(np.clip(vals[0], 1.5, 10.0), 1),
            "vol_zscore_min": round(np.clip(vals[1], 0.0, 5.0), 1),
            "turnover_min": 10 ** np.clip(vals[2], np.log10(5e7), np.log10(5e9)),
            "market_cap_min": 10 ** np.clip(cap_min_log, np.log10(5e9), np.log10(1e12)),
            "market_cap_max": 10 ** np.clip(cap_max_log, np.log10(1e10), np.log10(5e12)),
            "trend_condition": TREND_OPTIONS[int(np.clip(round(vals[5]), 0, 3))],
            "price_position": PRICE_OPTIONS[int(np.clip(round(vals[6]), 0, 3))],
            "holding_days": HOLDING_OPTIONS[int(np.clip(round(vals[7]), 0, 2))],
            "rsi_min": rsi_lo,
            "rsi_max": rsi_hi,
            "momentum_min": round(np.clip(vals[10], -0.05, 0.15), 3),
            "macd_condition": MACD_OPTIONS[int(np.clip(round(vals[11]), 0, 2))],
            "volatility_max": round(np.clip(vals[12], 0.01, 0.08), 3),
        }

    all_results = []

    def evaluate(individual):
        cond = decode(individual)
        res = run_backtest(df, cond)
        if res is None or res.n_trades < min_trades:
            return (-1.0,)
        all_results.append(res)
        return (res.composite_score,)

    toolbox.register("evaluate", evaluate)
    toolbox.register("mate", tools.cxBlend, alpha=0.3)

    def bounded_mutate(individual, mu=0, sigma=0.2, indpb=0.2):
        for i in range(len(individual)):
            if stdlib_random.random() < indpb:
                lo = GENE_RANGES[i][1]
                hi = GENE_RANGES[i][2]
                individual[i] += stdlib_random.gauss(mu, sigma * (hi - lo))
                individual[i] = np.clip(individual[i], lo, hi)
        return (individual,)

    toolbox.register("mutate", bounded_mutate)
    toolbox.register("select", tools.selTournament, tournsize=3)

    pop = toolbox.population(n=population_size)

    if seed_results:
        for i, sr in enumerate(seed_results[:population_size // 4]):
            try:
                cond = sr.condition
                genes = [
                    cond["vol_ratio_min"],
                    cond.get("vol_zscore_min", 1.0),
                    np.log10(cond["turnover_min"]),
                    np.log10(cond["market_cap_min"]),
                    np.log10(cond["market_cap_max"]),
                    TREND_OPTIONS.index(cond.get("trend_condition", "none")),
                    PRICE_OPTIONS.index(cond.get("price_position", "none")),
                    HOLDING_OPTIONS.index(cond.get("holding_days", 5)),
                    cond.get("rsi_min", 30),
                    cond.get("rsi_max", 80),
                    cond.get("momentum_min", 0.0),
                    MACD_OPTIONS.index(cond.get("macd_condition", "none")),
                    cond.get("volatility_max", 0.04),
                ]
                pop[i] = creator.Individual(genes)
            except (ValueError, KeyError):
                pass

    from tqdm import tqdm

    stats = tools.Statistics(lambda ind: ind.fitness.values[0] if ind.fitness.valid else -1)
    stats.register("max", np.max)
    stats.register("avg", np.mean)

    hof = tools.HallOfFame(50)

    if show_progress:
        for gen in tqdm(range(n_generations), desc="GA Evolution"):
            pop, log = algorithms.eaSimple(
                pop, toolbox,
                cxpb=0.7, mutpb=0.3,
                ngen=1, stats=stats,
                halloffame=hof, verbose=False,
            )
    else:
        pop, log = algorithms.eaSimple(
            pop, toolbox,
            cxpb=0.7, mutpb=0.3,
            ngen=n_generations, stats=stats,
            halloffame=hof, verbose=False,
        )

    best_conditions = [decode(ind) for ind in hof]
    best_results = []
    for cond in best_conditions:
        res = run_backtest(df, cond)
        if res and res.n_trades >= min_trades:
            best_results.append(res)

    best_results.sort(key=lambda r: r.composite_score, reverse=True)
    logger.info(f"GA complete: {len(all_results):,} evaluations, "
                f"{len(best_results)} elite results")

    return best_results


# ============================================================
# 統合最適化パイプライン
# ============================================================

def run_full_optimization(df: pd.DataFrame,
                          random_trials: int = RANDOM_SEARCH_TRIALS,
                          bayesian_trials: int = BAYESIAN_TRIALS,
                          ga_pop: int = GA_POPULATION,
                          ga_gen: int = GA_GENERATIONS,
                          show_progress: bool = True) -> Dict:
    """
    3段階の最適化を順次実行し、結果を統合。

    1. ランダムサーチで広域探索
    2. 上位結果をシードにベイズ最適化で深掘り
    3. 上位結果をシードに遺伝的アルゴリズムで進化探索
    """
    logger.info("=" * 60)
    logger.info("Starting full optimization pipeline")
    logger.info("=" * 60)

    logger.info(f"\n[1/3] Random Search ({random_trials:,} trials)...")
    random_results = random_search(df, n_trials=random_trials, show_progress=show_progress)
    logger.info(f"  Top score: {random_results[0].composite_score:.4f}" if random_results else "  No results")

    logger.info(f"\n[2/3] Bayesian Optimization ({bayesian_trials:,} trials)...")
    bayesian_results, study = bayesian_optimization(
        df, n_trials=bayesian_trials,
        seed_results=random_results[:100],
        show_progress=show_progress,
    )
    logger.info(f"  Top score: {bayesian_results[0].composite_score:.4f}" if bayesian_results else "  No results")

    logger.info(f"\n[3/3] Genetic Algorithm ({ga_pop}pop x {ga_gen}gen)...")
    top_seeds = sorted(
        random_results + bayesian_results,
        key=lambda r: r.composite_score, reverse=True
    )[:50]
    ga_results = genetic_algorithm(
        df,
        population_size=ga_pop,
        n_generations=ga_gen,
        seed_results=top_seeds,
        show_progress=show_progress,
    )
    logger.info(f"  Top score: {ga_results[0].composite_score:.4f}" if ga_results else "  No results")

    all_results = random_results + bayesian_results + ga_results
    seen_keys = set()
    unique_results = []
    for r in sorted(all_results, key=lambda x: x.composite_score, reverse=True):
        key = (
            r.condition.get("vol_ratio_min"),
            r.condition.get("trend_condition"),
            r.condition.get("holding_days"),
        )
        if key not in seen_keys:
            seen_keys.add(key)
            unique_results.append(r)

    logger.info(f"\nOptimization complete: {len(unique_results):,} unique conditions")

    return {
        "random": random_results,
        "bayesian": bayesian_results,
        "ga": ga_results,
        "all": unique_results,
        "optuna_study": study,
        "best": unique_results[0] if unique_results else None,
    }
