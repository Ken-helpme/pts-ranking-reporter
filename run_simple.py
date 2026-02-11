"""
Simple PTS Reporter - Display results without sending
"""
import sys
import os
from datetime import datetime

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from scraper import KabutanScraper
from analyzer import PTSAnalyzer
from news_fetcher import NewsFetcher

def format_stock_report(rank, stock, news, company):
    """Format stock report for display"""
    change_sign = '+' if stock['change_rate'] > 0 else ''

    report = f"\n{rank}. [{stock['code']}] {stock['name']}\n"
    report += f"{'='*60}\n"
    report += f"💰 PTS価格: {stock['pts_price']:,.0f}円 ({change_sign}{stock['change_rate']:.2f}%)\n"
    report += f"📊 出来高: {stock['volume']:,}株\n"

    # Company info
    if company:
        report += f"\n📌 基本情報:\n"
        if company.get('market'):
            report += f"  • 市場: {company['market']}\n"
        if company.get('industry'):
            report += f"  • 業種: {company['industry']}\n"
        if company.get('market_cap'):
            report += f"  • 時価総額: {company['market_cap']}\n"

    # News
    if news:
        report += f"\n📰 最新ニュース:\n"
        for i, item in enumerate(news[:3], 1):
            report += f"  {i}. {item['title']}\n"
            if item.get('date'):
                report += f"     ({item['date']})\n"

    return report

def main():
    print("="*60)
    print(f"PTS ランキングレポート - {datetime.now().strftime('%Y/%m/%d %H:%M')}")
    print("="*60)

    try:
        # Initialize
        scraper = KabutanScraper()
        analyzer = PTSAnalyzer(min_volume=10000, top_n=10)
        news_fetcher = NewsFetcher(max_news=3)

        # Fetch PTS ranking
        print("\n🔍 PTSランキングを取得中...")
        stocks = scraper.fetch_pts_ranking()

        if not stocks:
            print("❌ データの取得に失敗しました")
            return

        print(f"✓ {len(stocks)}銘柄を取得")

        # Filter and rank
        print("\n📊 データをフィルタリング中...")
        filtered_stocks = analyzer.filter_and_rank(stocks)

        if not filtered_stocks:
            print("❌ 出来高10,000株以上の銘柄が見つかりませんでした")
            return

        print(f"✓ 上位{len(filtered_stocks)}銘柄を選択")

        # Display results
        print("\n" + "="*60)
        print(f"出来高10,000株以上の上位{len(filtered_stocks)}銘柄")
        print("="*60)

        for i, stock in enumerate(filtered_stocks, 1):
            code = stock['code']

            # Fetch news and company info
            print(f"\n📰 {code}のニュースを取得中...")
            news = news_fetcher.fetch_stock_news(code)
            company = news_fetcher.get_company_info(code) or {}

            # Display report
            report = format_stock_report(i, stock, news, company)
            print(report)

        # Summary
        stats = analyzer.get_statistics(filtered_stocks)
        print("\n" + "="*60)
        print("📈 サマリー")
        print("="*60)
        print(f"対象銘柄数: {stats.get('total_count', 0)}")
        print(f"平均上昇率: {stats.get('avg_change_rate', 0):.2f}%")
        print(f"最大上昇率: {stats.get('max_change_rate', 0):.2f}%")
        print(f"総出来高: {stats.get('total_volume', 0):,.0f}株")
        print("="*60)

        # Cleanup
        scraper.close()
        news_fetcher.close()

        print("\n✅ 完了!")

    except Exception as e:
        print(f"\n❌ エラーが発生しました: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
