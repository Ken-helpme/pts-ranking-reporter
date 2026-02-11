"""
既存のデータベースレコードに新しい分析を適用するスクリプト
"""
import sys
import os

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'dashboard'))

import sqlite3
import json
from datetime import datetime, timedelta
from stock_analyzer import StockAnalyzer
from disclosure_fetcher import DisclosureFetcher
from earnings_analyzer import EarningsAnalyzer
from models import DB_PATH
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def reanalyze_recent_data(days: int = 7):
    """
    過去N日分のデータを再分析

    Args:
        days: 何日前までのデータを再分析するか
    """
    logger.info(f"=== 過去{days}日分のデータを再分析 ===\n")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 過去N日分のデータを取得（分析がまだのもの、または古い分析のもの）
    start_date = (datetime.now() - timedelta(days=days)).isoformat()

    cursor.execute('''
        SELECT DISTINCT stock_code, stock_name, created_at
        FROM pts_ranking
        WHERE created_at >= ?
        GROUP BY stock_code, created_at
        ORDER BY created_at DESC
    ''', (start_date,))

    records = cursor.fetchall()
    logger.info(f"再分析対象: {len(records)} 件のレコード\n")

    if not records:
        logger.info("再分析するデータがありません")
        conn.close()
        return

    # Analyzers を初期化
    stock_analyzer = StockAnalyzer()
    disclosure_fetcher = DisclosureFetcher()
    earnings_analyzer = EarningsAnalyzer()

    analyzed_count = 0
    skipped_count = 0

    for code, name, timestamp in records:
        try:
            # その時点のデータを取得
            cursor.execute('''
                SELECT stock_code, stock_name, pts_price, change_rate, change_amount,
                       volume, market, company_info, news, main_reason, analysis
                FROM pts_ranking
                WHERE stock_code = ? AND created_at = ?
            ''', (code, timestamp))

            row = cursor.fetchone()
            if not row:
                continue

            # 既に分析済みかチェック
            existing_analysis = json.loads(row[10]) if row[10] and row[10] != '{}' else {}
            if existing_analysis.get('earnings_detail'):
                logger.info(f"[SKIP] {code} {name} - 既に決算分析済み")
                skipped_count += 1
                continue

            logger.info(f"[分析中] {code} {name} ({timestamp[:10]})")

            # 株式情報を再構築
            stock = {
                'code': row[0],
                'name': row[1],
                'pts_price': row[2],
                'change_rate': row[3],
                'change_amount': row[4],
                'volume': row[5],
                'market': row[6],
            }

            # ニュースを取得
            news = json.loads(row[8]) if row[8] else []

            # 開示情報を取得
            disclosure_info = disclosure_fetcher.fetch_disclosure_info(code)
            earnings_detail = None

            # 決算がある場合は詳細分析
            if disclosure_info.get('has_earnings'):
                logger.info(f"  → 決算発表あり、Claude APIで分析中...")
                disclosure_title = disclosure_info['disclosures'][0]['title'] if disclosure_info['disclosures'] else disclosure_info['earnings_summary']

                earnings_detail = earnings_analyzer.analyze_earnings_detail(
                    disclosure_title,
                    news,
                    stock
                )

                # 決算情報をニュースに追加
                if earnings_detail and earnings_detail.get('earnings_reason'):
                    earnings_news = {
                        'title': f"【決算】{disclosure_info['earnings_summary']} - {earnings_detail['earnings_reason']}",
                        'date': disclosure_info['disclosures'][0]['date'] if disclosure_info['disclosures'] else '',
                        'url': disclosure_info['disclosures'][0]['url'] if disclosure_info['disclosures'] else '',
                        'source': '開示情報（再分析）'
                    }
                    news.insert(0, earnings_news)

            # 上昇理由と将来性を再分析
            analysis = stock_analyzer.analyze_price_increase_reason(news, stock)

            # 決算の詳細分析を追加
            if earnings_detail:
                analysis['earnings_detail'] = earnings_detail

            # データベースを更新
            cursor.execute('''
                UPDATE pts_ranking
                SET main_reason = ?,
                    analysis = ?,
                    future_potential = ?,
                    news = ?
                WHERE stock_code = ? AND created_at = ?
            ''', (
                analysis.get('main_reason', ''),
                json.dumps(analysis, ensure_ascii=False),
                analysis.get('future_potential', ''),
                json.dumps(news, ensure_ascii=False),
                code,
                timestamp
            ))

            conn.commit()
            analyzed_count += 1

            if earnings_detail:
                logger.info(f"  ✓ 決算分析を追加: {earnings_detail.get('earnings_reason', '')[:50]}...")
            else:
                logger.info(f"  ✓ 分析を更新")

        except Exception as e:
            logger.error(f"  ✗ エラー: {e}")
            continue

    # Cleanup
    disclosure_fetcher.close()

    conn.close()

    logger.info(f"\n=== 完了 ===")
    logger.info(f"分析済み: {analyzed_count} 件")
    logger.info(f"スキップ: {skipped_count} 件")


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='既存のデータベースレコードを再分析')
    parser.add_argument('--days', type=int, default=7, help='何日前までのデータを再分析するか（デフォルト: 7日）')
    args = parser.parse_args()

    print(f"🔄 過去{args.days}日分のデータを再分析します\n")
    print("⚠️  Claude API設定がない場合は簡易分析のみ行われます")
    print("   詳細は CLAUDE_API_SETUP.md を参照\n")

    confirm = input("続行しますか？ (y/n): ")
    if confirm.lower() == 'y':
        reanalyze_recent_data(args.days)
    else:
        print("キャンセルしました")
