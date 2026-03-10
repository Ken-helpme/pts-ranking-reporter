#!/usr/bin/env python3
"""
自動最適化スクリプト（毎週月曜 cron で実行）

仕組み:
  1. DBから現在のベスト条件を読み込む
  2. ベスト条件を起点に近傍探索 + 全体ランダム探索
  3. スコア（勝率×2 + 平均リターン）が改善した場合のみDBを更新（ラチェット効果）
  4. 実行ログをDBに記録

使い方:
  python3 /Users/ken/pts-ranking-reporter/scripts/auto_optimize.py
  python3 /Users/ken/pts-ranking-reporter/scripts/auto_optimize.py --lookback 52
  python3 /Users/ken/pts-ranking-reporter/scripts/auto_optimize.py --dry-run
"""
import sys
import os
import argparse
from datetime import datetime

# プロジェクトルートをパスに追加
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))
sys.path.insert(0, os.path.join(ROOT, 'dashboard'))

# .env 読み込み（J-Quants API キーなど）
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, '.env'))
except ImportError:
    pass

from jquants_client import JQuantsClient
from models import (
    init_db,
    get_latest_optimization,
    save_optimization_result,
    save_auto_optimization_log,
)


def run(lookback_weeks: int = 52, n_trials: int = 5000, dry_run: bool = False):
    print(f"\n{'='*60}")
    print(f"🤖 自動最適化 開始: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"   lookback={lookback_weeks}週, trials={n_trials}, dry_run={dry_run}")
    print(f"{'='*60}")

    init_db()

    # ── 1. 現在のベスト条件を取得 ──
    current = get_latest_optimization()
    current_score    = current['score']    if current else 0.0
    current_win_rate = current['win_rate_20d'] if current else 0.0
    current_params   = current['best_params']  if current else None

    print(f"\n現在のベスト: 勝率={current_win_rate}% スコア={current_score:.1f}")
    if current_params:
        print(f"  条件: vol≥{current_params.get('vol_ratio_min')}× "
              f"5日≥{current_params.get('price_5d_chg_min')}% "
              f"代金≥{current_params.get('turnover_min', 0)/1e8:.1f}億 "
              f"{current_params.get('market','')} "
              f"top{current_params.get('top_n',20)}")

    # ── 2. 最適化実行 ──
    step = 4 if lookback_weeks >= 52 else 2   # 1年以上は月次
    print(f"\n最適化中... ({lookback_weeks}週, {step}週刻み, {n_trials}試行)")

    client = JQuantsClient()
    result = client.run_large_scale_optimization(
        lookback_weeks=lookback_weeks,
        step_weeks=step,
        n_trials=n_trials,
        base_params=current_params,   # ベスト条件を起点に近傍探索
    )

    if not result.get('success'):
        msg = f"最適化失敗: {result.get('error', '不明')}"
        print(f"❌ {msg}")
        save_auto_optimization_log(
            improved=False,
            prev_score=current_score, new_score=current_score,
            prev_win_rate=current_win_rate, new_win_rate=current_win_rate,
            best_params=current_params or {},
            lookback_weeks=lookback_weeks,
            test_dates=[],
            note=msg,
        )
        return False

    best = result.get('best_20d')
    if not best:
        print("❌ 有効な結果なし")
        return False

    new_win_rate = best.get('win_rate_20d', 0) or 0
    new_avg      = best.get('avg_return_20d', 0) or 0
    new_score    = new_win_rate * 2 + new_avg

    print(f"\n新しいベスト: 勝率={new_win_rate}% 平均={new_avg:+.2f}% スコア={new_score:.1f}")
    print(f"  条件: vol≥{best.get('vol_ratio_min')}× "
          f"5日≥{best.get('price_5d_chg_min')}% "
          f"代金≥{best.get('min_turnover',0)/1e8:.1f}億 "
          f"{best.get('market','')} "
          f"top{best.get('top_n',20)}")

    improved = new_score > current_score

    # ── 3. ラチェット: 改善した場合のみ保存 ──
    if improved and not dry_run:
        new_params = {
            'vol_ratio_min':    best['vol_ratio_min'],
            'price_5d_chg_min': best['price_5d_chg_min'],
            'turnover_min':     best.get('min_turnover', best.get('turnover_min', 50_000_000)),
            'market':           best.get('market', ''),
            'top_n':            best.get('top_n', 20),
        }
        win_stats = {
            'win_rate_20d':    new_win_rate,
            'avg_return_20d':  new_avg,
            'win_rate_10d':    best.get('win_rate_10d'),
            'avg_return_10d':  best.get('avg_return_10d'),
            'total_combinations': result.get('total_combinations', 0),
        }
        test_dates   = result.get('test_dates', [])
        center_date  = test_dates[len(test_dates) // 2] if test_dates else ''
        save_optimization_result(new_params, win_stats, center_date, test_dates)
        print(f"\n✅ 改善を保存しました！ {current_score:.1f} → {new_score:.1f} "
              f"(+{new_score - current_score:.1f})")
    elif improved and dry_run:
        print(f"\n✅ 改善あり（dry-run のため保存スキップ）: {current_score:.1f} → {new_score:.1f}")
    else:
        print(f"\n➡️  改善なし（現状維持）: {current_score:.1f} >= {new_score:.1f}")

    # ── 4. ログ保存 ──
    if not dry_run:
        save_auto_optimization_log(
            improved=improved,
            prev_score=current_score,
            new_score=new_score if improved else current_score,
            prev_win_rate=current_win_rate,
            new_win_rate=new_win_rate if improved else current_win_rate,
            best_params=best if improved else (current_params or {}),
            lookback_weeks=lookback_weeks,
            test_dates=result.get('test_dates', []),
            note='improved' if improved else 'no_change',
        )

    print(f"\n所要時間: {result.get('total_time', '?')}秒")
    print(f"{'='*60}\n")
    return improved


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='自動最適化スクリプト')
    parser.add_argument('--lookback', type=int, default=52,
                        help='バックテスト期間（週数, デフォルト: 52=1年）')
    parser.add_argument('--trials',   type=int, default=5000,
                        help='試行数（デフォルト: 5000）')
    parser.add_argument('--dry-run',  action='store_true',
                        help='保存せずに結果だけ確認')
    args = parser.parse_args()
    run(lookback_weeks=args.lookback, n_trials=args.trials, dry_run=args.dry_run)
