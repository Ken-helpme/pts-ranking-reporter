"""
PTSデータを取得して詳細分析を適用
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'dashboard'))

from datetime import datetime
from scraper import KabutanScraper
from analyzer import PTSAnalyzer
from news_fetcher import NewsFetcher
from stock_analyzer import StockAnalyzer
from disclosure_fetcher import DisclosureFetcher
from earnings_analyzer import EarningsAnalyzer
from stock_evaluator import StockEvaluator
from pdf_analyzer import PDFAnalyzer
from models import save_pts_data
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    """PTSデータを取得して分析"""
    logger.info("=== PTSデータ取得開始 ===\n")

    # Get API key from environment
    api_key = os.getenv('ANTHROPIC_API_KEY')
    if api_key:
        logger.info("✓ Claude API Key found")
    else:
        logger.warning("⚠ Claude API Key not found - using fallback analysis")

    # Initialize components
    scraper = KabutanScraper()
    analyzer = PTSAnalyzer(min_volume=1000, top_n=15)
    news_fetcher = NewsFetcher(max_news=15)
    stock_analyzer = StockAnalyzer()
    disclosure_fetcher = DisclosureFetcher()
    earnings_analyzer = EarningsAnalyzer(api_key=api_key)  # Pass API key explicitly
    pdf_analyzer = PDFAnalyzer()  # PDF分析機能
    stock_evaluator = StockEvaluator()

    # Fetch PTS ranking
    logger.info("📊 PTSランキングを取得中...")
    stocks = scraper.fetch_pts_ranking()

    if not stocks:
        logger.error("❌ PTSデータの取得に失敗しました")
        return

    logger.info(f"✅ {len(stocks)}件のPTSデータを取得\n")

    # Filter and rank
    filtered_stocks = analyzer.filter_and_rank(stocks)
    logger.info(f"📈 フィルター後: {len(filtered_stocks)}件\n")

    # Save with same timestamp
    timestamp = datetime.now().isoformat()
    saved_count = 0

    for i, stock in enumerate(filtered_stocks, 1):
        code = stock['code']
        name = stock.get('name', '')

        logger.info(f"[{i}/{len(filtered_stocks)}] {code} {name} ({stock['change_rate']:+.1f}%)")

        # Fetch stock name if missing
        if not name:
            name = scraper.fetch_stock_name(code)
            stock['name'] = name
            logger.info(f"  → 銘柄名取得: {name}")

        # Fetch news and company info
        logger.info("  → ニュース取得中...")
        news = news_fetcher.fetch_stock_news(code)
        company = news_fetcher.get_company_info(code) or {}

        # Fetch disclosure info
        logger.info("  → 開示情報確認中...")
        disclosure_info = disclosure_fetcher.fetch_disclosure_info(code)
        earnings_detail = None

        # Deep earnings analysis with Claude API
        if disclosure_info.get('has_earnings'):
            logger.info("  → 💡 決算発表あり！")

            disclosure_title = disclosure_info['disclosures'][0]['title'] if disclosure_info['disclosures'] else disclosure_info['earnings_summary']
            pdf_url = disclosure_info['disclosures'][0].get('pdf_url') if disclosure_info['disclosures'] else None

            # STEP 1-3: PDFがあればダウンロード＆テキスト抽出
            pdf_text = None
            if pdf_url:
                logger.info(f"  → 📄 PDF発見！ダウンロード中...")
                logger.info(f"     URL: {pdf_url}")
                pdf_text = pdf_analyzer.download_and_extract_pdf(pdf_url)

                if pdf_text:
                    logger.info(f"  ✓ PDFテキスト抽出完了 ({len(pdf_text)}文字)")

                    # STEP 4-5: 重要な財務数値を抽出
                    logger.info("  → 💰 財務数値を抽出中...")
                    financials = pdf_analyzer.extract_key_financials(pdf_text)
                    if financials['revenue']:
                        logger.info(f"     売上高: {financials['revenue']}")
                    if financials['profit']:
                        logger.info(f"     利益: {financials['profit']}")
                    if financials['key_sentences']:
                        logger.info(f"     重要文: {len(financials['key_sentences'])}件抽出")
                else:
                    logger.warning("  ⚠ PDF抽出失敗 - タイトルのみで分析")

            # STEP 6: Claude APIで分析（PDF → ニュース記事 → タイトルのみ の順でフォールバック）
            earnings_detail = None

            if pdf_text and api_key:
                logger.info("  → 🧠 Claude APIでPDF全文を分析中...")
                earnings_detail = earnings_analyzer.analyze_with_pdf_text(pdf_text, stock)

            # PDF分析が「原文に記載なし」や空の場合もフォールバック
            def _is_empty_result(result):
                if not result:
                    return True
                reason = result.get('earnings_reason', '')
                return not reason or '記載なし' in reason or reason == 'PDFテキスト分析エラー'

            # PDF分析失敗 or PDFなし or 内容なし → ニュース記事本文を取得して分析
            if _is_empty_result(earnings_detail) and api_key:
                logger.info("  → 📰 ニュース記事を取得して分析中...")
                news_content = news_fetcher.fetch_relevant_articles(news, max_articles=3)
                if news_content:
                    earnings_detail = earnings_analyzer.analyze_with_news_content(news_content, stock)

            # ニュース記事も失敗 or 内容なし → タイトルのみで分析
            if _is_empty_result(earnings_detail):
                logger.info("  → 🧠 Claude APIでタイトルを分析中...")
                earnings_detail = earnings_analyzer.analyze_earnings_detail(
                    disclosure_title,
                    news,
                    stock
                )

            if earnings_detail and earnings_detail.get('earnings_reason'):
                logger.info(f"  ✓ 決算分析完了: {earnings_detail['earnings_reason'][:60]}...")

                # Add earnings info to news
                earnings_news = {
                    'title': f"【決算】{disclosure_info['earnings_summary']} - {earnings_detail['earnings_reason'][:80]}",
                    'date': disclosure_info['disclosures'][0]['date'] if disclosure_info['disclosures'] else '',
                    'url': disclosure_info['disclosures'][0]['url'] if disclosure_info['disclosures'] else '',
                    'source': '開示情報',
                    'has_pdf_analysis': pdf_text is not None  # PDFから分析したかフラグ
                }
                news.insert(0, earnings_news)

        # Analyze price increase reason
        logger.info("  → 上昇理由を分析中...")
        analysis = stock_analyzer.analyze_price_increase_reason(news, stock)

        # Add earnings detail to analysis
        if earnings_detail:
            analysis['earnings_detail'] = earnings_detail

        # Evaluate stock and add rating
        logger.info("  → 総合評価を算出中...")
        evaluation = stock_evaluator.evaluate_stock(stock, company, analysis)
        analysis['evaluation'] = evaluation
        logger.info(f"  ✓ 総合評価: {evaluation['overall_rating']} (スコア: {evaluation['score']}/100)")

        # Save to database
        save_pts_data(stock, news, company, timestamp, analysis)
        saved_count += 1

        logger.info(f"  ✅ 保存完了\n")

    # Cleanup
    disclosure_fetcher.close()

    logger.info(f"\n=== 完了 ===")
    logger.info(f"保存件数: {saved_count}件")
    logger.info(f"\nダッシュボードで確認:")
    logger.info(f"  http://localhost:5001\n")


if __name__ == '__main__':
    main()
