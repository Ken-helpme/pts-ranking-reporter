"""
既存の英語分析データを日本語で強制再分析するスクリプト
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'dashboard'))

import sqlite3
import json
from datetime import datetime, timedelta
from stock_analyzer import StockAnalyzer
from disclosure_fetcher import DisclosureFetcher
from earnings_analyzer import EarningsAnalyzer
from pdf_analyzer import PDFAnalyzer
from stock_evaluator import StockEvaluator
from news_fetcher import NewsFetcher
from models import DB_PATH
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def force_reanalyze_japanese():
    """最新バッチのデータを日本語で強制再分析"""
    logger.info("=== 最新データを日本語で再分析 ===\n")

    api_key = os.getenv('ANTHROPIC_API_KEY')
    if not api_key:
        logger.error("ANTHROPIC_API_KEY が設定されていません")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 最新バッチのタイムスタンプを取得
    cursor.execute('SELECT MAX(created_at) FROM pts_ranking')
    latest_time = cursor.fetchone()[0]

    if not latest_time:
        logger.info("データがありません")
        conn.close()
        return

    # 最新バッチの全レコードを取得
    cursor.execute('''
        SELECT id, stock_code, stock_name, pts_price, change_rate, change_amount,
               volume, market, company_info, news, main_reason, analysis, future_potential, created_at
        FROM pts_ranking
        WHERE datetime(created_at) >= datetime(?, '-1 second')
        ORDER BY change_rate DESC
    ''', (latest_time,))

    records = cursor.fetchall()
    logger.info(f"再分析対象: {len(records)} 件（{latest_time}）\n")

    # Analyzers を初期化
    stock_analyzer = StockAnalyzer()
    disclosure_fetcher = DisclosureFetcher()
    earnings_analyzer = EarningsAnalyzer(api_key=api_key)
    pdf_analyzer = PDFAnalyzer()
    stock_evaluator = StockEvaluator()
    news_fetcher = NewsFetcher(max_news=15)

    analyzed_count = 0

    for row in records:
        record_id = row[0]
        code = row[1]
        name = row[2]

        stock = {
            'code': code,
            'name': name,
            'pts_price': row[3],
            'change_rate': row[4],
            'change_amount': row[5],
            'volume': row[6],
            'market': row[7],
        }

        company = json.loads(row[8]) if row[8] else {}
        news = json.loads(row[9]) if row[9] else []

        logger.info(f"[{analyzed_count+1}/{len(records)}] {code} {name} ({stock['change_rate']:+.1f}%)")

        try:
            # 開示情報を取得
            disclosure_info = disclosure_fetcher.fetch_disclosure_info(code)
            earnings_detail = None

            if disclosure_info.get('has_earnings'):
                logger.info("  → 決算発表あり")
                disclosure_title = disclosure_info['disclosures'][0]['title'] if disclosure_info['disclosures'] else disclosure_info['earnings_summary']
                pdf_url = disclosure_info['disclosures'][0].get('pdf_url') if disclosure_info['disclosures'] else None

                # PDFがあればダウンロード＆分析
                pdf_text = None
                if pdf_url:
                    logger.info(f"  → 📄 PDFダウンロード中...")
                    pdf_text = pdf_analyzer.download_and_extract_pdf(pdf_url)

                # Claude APIで日本語分析
                if pdf_text:
                    logger.info("  → 🧠 Claude APIでPDF全文を日本語分析中...")
                    earnings_detail = earnings_analyzer.analyze_with_pdf_text(pdf_text, stock)

                # PDFが失敗→ニュース記事から分析
                if not earnings_detail or not earnings_detail.get('earnings_reason'):
                    logger.info("  → 📰 ニュース記事から日本語分析中...")
                    news_content = news_fetcher.fetch_relevant_articles(news, max_articles=3)
                    if news_content:
                        earnings_detail = earnings_analyzer.analyze_with_news_content(news_content, stock)

                # ニュースも失敗→タイトルのみで分析
                if not earnings_detail or not earnings_detail.get('earnings_reason'):
                    logger.info("  → 🧠 タイトルから日本語分析中...")
                    earnings_detail = earnings_analyzer.analyze_earnings_detail(
                        disclosure_title, news, stock
                    )

                # 決算ニュースを更新
                if earnings_detail and earnings_detail.get('earnings_reason'):
                    # 既存の決算ニュースを除去
                    news = [n for n in news if not n.get('title', '').startswith('【決算】')]
                    earnings_news = {
                        'title': f"【決算】{disclosure_info['earnings_summary']} - {earnings_detail['earnings_reason'][:80]}",
                        'date': disclosure_info['disclosures'][0]['date'] if disclosure_info['disclosures'] else '',
                        'url': disclosure_info['disclosures'][0]['url'] if disclosure_info['disclosures'] else '',
                        'source': '開示情報',
                        'has_pdf_analysis': pdf_text is not None
                    }
                    news.insert(0, earnings_news)

            # 上昇理由を再分析
            analysis = stock_analyzer.analyze_price_increase_reason(news, stock)

            if earnings_detail:
                analysis['earnings_detail'] = earnings_detail

            # 総合評価
            evaluation = stock_evaluator.evaluate_stock(stock, company, analysis)
            analysis['evaluation'] = evaluation

            # DB更新
            cursor.execute('''
                UPDATE pts_ranking
                SET main_reason = ?,
                    analysis = ?,
                    future_potential = ?,
                    news = ?
                WHERE id = ?
            ''', (
                analysis.get('main_reason', ''),
                json.dumps(analysis, ensure_ascii=False),
                analysis.get('future_potential', ''),
                json.dumps(news, ensure_ascii=False),
                record_id
            ))
            conn.commit()
            analyzed_count += 1

            if earnings_detail and earnings_detail.get('earnings_reason'):
                logger.info(f"  ✅ 日本語分析完了: {earnings_detail['earnings_reason'][:60]}...")
            else:
                logger.info(f"  ✅ 分析更新完了")

        except Exception as e:
            logger.error(f"  ❌ エラー: {e}")
            import traceback
            traceback.print_exc()
            continue

    # Cleanup
    disclosure_fetcher.close()
    news_fetcher.close()

    conn.close()

    logger.info(f"\n=== 完了 ===")
    logger.info(f"日本語再分析: {analyzed_count}/{len(records)} 件")


if __name__ == '__main__':
    force_reanalyze_japanese()
