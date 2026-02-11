"""
PTSランキングデータの分析・フィルタリングモジュール
"""
import pandas as pd
from typing import List, Dict
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PTSAnalyzer:
    """PTSランキングデータを分析・フィルタリングするクラス"""

    def __init__(self, min_volume: int = 10000, top_n: int = 10):
        """
        Args:
            min_volume: 最小出来高（この値未満は除外）
            top_n: 取得する上位銘柄数
        """
        self.min_volume = min_volume
        self.top_n = top_n

    def filter_and_rank(self, stocks: List[Dict[str, any]]) -> List[Dict[str, any]]:
        """
        銘柄データをフィルタリングし、ランキング順にソート

        Args:
            stocks: 銘柄データのリスト

        Returns:
            List[Dict]: フィルタリング・ソート済みの銘柄リスト
        """
        if not stocks:
            logger.warning("No stock data to analyze")
            return []

        # DataFrameに変換
        df = pd.DataFrame(stocks)

        # 初期データ数
        initial_count = len(df)
        logger.info(f"Initial stock count: {initial_count}")

        # 出来高でフィルタリング
        df = df[df['volume'] >= self.min_volume]
        logger.info(f"After volume filter (>={self.min_volume:,}): {len(df)} stocks")

        # 変化率でソート（降順）
        df = df.sort_values('change_rate', ascending=False)

        # 上位N件を取得
        df = df.head(self.top_n)
        logger.info(f"Top {self.top_n} stocks selected")

        # Dictのリストに変換して返す
        result = df.to_dict('records')

        return result

    def get_statistics(self, stocks: List[Dict[str, any]]) -> Dict[str, any]:
        """
        銘柄データの統計情報を取得

        Args:
            stocks: 銘柄データのリスト

        Returns:
            Dict: 統計情報
                - total_count: 総銘柄数
                - avg_change_rate: 平均変化率
                - max_change_rate: 最大変化率
                - min_change_rate: 最小変化率
                - total_volume: 総出来高
        """
        if not stocks:
            return {
                'total_count': 0,
                'avg_change_rate': 0,
                'max_change_rate': 0,
                'min_change_rate': 0,
                'total_volume': 0,
            }

        df = pd.DataFrame(stocks)

        stats = {
            'total_count': len(df),
            'avg_change_rate': df['change_rate'].mean(),
            'max_change_rate': df['change_rate'].max(),
            'min_change_rate': df['change_rate'].min(),
            'total_volume': df['volume'].sum(),
        }

        return stats

    def format_stock_info(self, stock: Dict[str, any], rank: int) -> str:
        """
        銘柄情報を読みやすい形式にフォーマット

        Args:
            stock: 銘柄データ
            rank: ランキング順位

        Returns:
            str: フォーマット済みの文字列
        """
        change_sign = '+' if stock['change_rate'] > 0 else ''

        info = f"{rank}. [{stock['code']}] {stock['name']}\n"
        info += f"   PTS価格: {stock['pts_price']:,.0f}円 ({change_sign}{stock['change_rate']:.2f}%)\n"
        info += f"   出来高: {stock['volume']:,}株\n"

        if stock.get('market'):
            info += f"   市場: {stock['market']}\n"

        return info


if __name__ == "__main__":
    # テスト実行
    test_data = [
        {
            'code': '1234',
            'name': 'テスト株式会社',
            'pts_price': 1500,
            'change_rate': 10.5,
            'change_amount': 142,
            'volume': 150000,
            'market': '東証プライム'
        },
        {
            'code': '5678',
            'name': 'サンプル株式会社',
            'pts_price': 2500,
            'change_rate': 8.2,
            'change_amount': 190,
            'volume': 5000,  # 出来高が少ない（フィルタされる）
            'market': '東証スタンダード'
        },
        {
            'code': '9012',
            'name': 'デモ株式会社',
            'pts_price': 800,
            'change_rate': 15.3,
            'change_amount': 106,
            'volume': 200000,
            'market': '東証プライム'
        },
    ]

    analyzer = PTSAnalyzer(min_volume=10000, top_n=10)
    filtered = analyzer.filter_and_rank(test_data)

    print("\n=== フィルタリング結果 ===")
    for i, stock in enumerate(filtered, 1):
        print(analyzer.format_stock_info(stock, i))

    stats = analyzer.get_statistics(filtered)
    print("\n=== 統計情報 ===")
    print(f"銘柄数: {stats['total_count']}")
    print(f"平均変化率: {stats['avg_change_rate']:.2f}%")
    print(f"最大変化率: {stats['max_change_rate']:.2f}%")
