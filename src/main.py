"""
PTSランキング自動監視・レポート送信システム メインモジュール
"""
import os
import sys
import logging
from datetime import datetime
from typing import List, Dict
import traceback

# 同じディレクトリ内のモジュールをインポート
from scraper import KabutanScraper
from analyzer import PTSAnalyzer
from news_fetcher import NewsFetcher
from chart_generator import ChartGenerator
from line_notifier import LineNotifier

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class PTSReporter:
    """PTSランキングレポーターのメインクラス"""

    def __init__(self, min_volume: int = 10000, top_n: int = 10):
        """
        Args:
            min_volume: 最小出来高（この値未満は除外）
            top_n: 取得する上位銘柄数
        """
        self.min_volume = min_volume
        self.top_n = top_n

        # 各モジュールの初期化
        self.scraper = KabutanScraper()
        self.analyzer = PTSAnalyzer(min_volume=min_volume, top_n=top_n)
        self.news_fetcher = NewsFetcher(max_news=3)
        self.chart_generator = ChartGenerator()
        self.line_notifier = LineNotifier()

    def run(self) -> bool:
        """
        メイン処理を実行

        Returns:
            bool: 処理が正常に完了した場合True
        """
        try:
            logger.info("=" * 60)
            logger.info("PTS Ranking Reporter Started")
            logger.info(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info("=" * 60)

            # 1. PTSランキングを取得
            logger.info("Step 1: Fetching PTS ranking...")
            stocks = self.scraper.fetch_pts_ranking()

            if not stocks:
                error_msg = "Failed to fetch PTS ranking data"
                logger.error(error_msg)
                self.line_notifier.send_error_notification(error_msg)
                return False

            logger.info(f"Fetched {len(stocks)} stocks")

            # 2. データをフィルタリング・ソート
            logger.info("Step 2: Filtering and ranking stocks...")
            filtered_stocks = self.analyzer.filter_and_rank(stocks)

            if not filtered_stocks:
                error_msg = f"No stocks found with volume >= {self.min_volume:,}"
                logger.warning(error_msg)
                self.line_notifier.send_error_notification(error_msg)
                return False

            logger.info(f"Selected top {len(filtered_stocks)} stocks")

            # 3. 各銘柄のニュースと企業情報を取得
            logger.info("Step 3: Fetching news and company info...")
            news_data = {}
            company_info = {}

            for stock in filtered_stocks:
                code = stock['code']
                logger.info(f"Fetching data for {code} - {stock['name']}")

                # ニュース取得
                news = self.news_fetcher.fetch_stock_news(code)
                news_data[code] = news

                # 企業情報取得
                info = self.news_fetcher.get_company_info(code)
                company_info[code] = info or {}

            # 4. チャート画像を取得
            logger.info("Step 4: Fetching chart images...")
            chart_paths = {}

            for stock in filtered_stocks:
                code = stock['code']
                name = stock['name']

                # プレースホルダーチャートを生成
                # 注意: 実際のチャート取得には株探のURL構造確認が必要
                chart_path = self.chart_generator.create_placeholder_chart(code, name)
                chart_paths[code] = chart_path

            # 5. LINEにレポートを送信
            logger.info("Step 5: Sending report to LINE...")
            success = self.line_notifier.send_pts_report(
                filtered_stocks,
                news_data,
                company_info,
                chart_paths
            )

            # 6. サマリーを送信
            if success:
                stats = self.analyzer.get_statistics(filtered_stocks)
                self.line_notifier.send_summary(stats)

            # 7. 古いチャート画像をクリーンアップ
            logger.info("Step 6: Cleaning up old charts...")
            self.chart_generator.cleanup_old_charts(max_age_hours=24)

            logger.info("=" * 60)
            logger.info("PTS Ranking Reporter Completed Successfully")
            logger.info("=" * 60)

            return success

        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            logger.error(error_msg)
            logger.error(traceback.format_exc())

            try:
                self.line_notifier.send_error_notification(error_msg)
            except:
                pass

            return False

        finally:
            self.cleanup()

    def cleanup(self):
        """リソースのクリーンアップ"""
        logger.info("Cleaning up resources...")

        try:
            self.scraper.close()
        except:
            pass

        try:
            self.news_fetcher.close()
        except:
            pass

        try:
            self.chart_generator.close()
        except:
            pass


def main():
    """
    メインエントリポイント
    """
    # 環境変数から設定を取得
    min_volume = int(os.getenv('MIN_VOLUME', '10000'))
    top_n = int(os.getenv('TOP_N', '10'))

    # レポーターを実行
    reporter = PTSReporter(min_volume=min_volume, top_n=top_n)
    success = reporter.run()

    # 終了コード
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
