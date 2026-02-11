"""
株式の上昇理由と将来性を分析するモジュール
"""
import re
from typing import List, Dict, Optional
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class StockAnalyzer:
    """株式の上昇理由と将来性を分析するクラス"""

    # 上昇理由のキーワード
    CATALYST_KEYWORDS = {
        '決算': ['決算', '業績', '四半期', '通期', '上方修正', '増益', '最高益', '過去最高'],
        '新製品・技術': ['新製品', '新技術', '開発', '実用化', '量産', '投入', '発売'],
        '契約・提携': ['契約', '提携', '受注', '獲得', 'M&A', '買収', '提携'],
        '株主還元': ['配当', '増配', '自社株買い', '株主還元', '特別配当'],
        '大株主': ['大株主', 'TOB', '筆頭株主', '持株比率', '株主異動'],
        '相場': ['ストップ高', 'S高', '急騰', '買い気配', '気配値'],
        '政策・規制': ['規制緩和', '政策', '補助金', '認可', '承認'],
        '市場環境': ['需要増', '市況', '価格上昇', '市場拡大'],
    }

    # ポジティブワード
    POSITIVE_WORDS = [
        '好調', '堅調', '順調', '拡大', '増加', '成長', '伸長',
        '改善', '回復', '好転', '上昇', '強い', '好材料',
        '期待', '有望', '注目', '評価', '人気'
    ]

    # ネガティブワード（将来性分析用）
    NEGATIVE_WORDS = [
        '悪化', '減少', '低迷', '減益', '赤字', '下方修正',
        '懸念', '不安', '課題', '問題', 'リスク'
    ]

    def analyze_price_increase_reason(
        self,
        news_list: List[Dict[str, str]],
        stock_info: Dict
    ) -> Dict[str, any]:
        """
        株価上昇理由を分析

        Args:
            news_list: ニュースリスト
            stock_info: 株式基本情報

        Returns:
            Dict: 分析結果
                - main_reason: 主な上昇理由（一段落）
                - catalysts: 抽出されたカタリスト（分類済み）
                - sentiment: センチメント分析
                - future_potential: 将来性評価
        """
        if not news_list:
            return {
                'main_reason': '上昇理由の詳細情報が取得できませんでした。',
                'catalysts': {},
                'sentiment': 'neutral',
                'future_potential': '情報不足のため評価できません。',
            }

        # カタリストを抽出
        catalysts = self._extract_catalysts(news_list)

        # メイン理由を一段落にまとめる
        main_reason = self._consolidate_reasons(news_list, catalysts, stock_info)

        # センチメント分析
        sentiment = self._analyze_sentiment(news_list)

        # 将来性評価
        future_potential = self._evaluate_future_potential(catalysts, sentiment, stock_info)

        return {
            'main_reason': main_reason,
            'catalysts': catalysts,
            'sentiment': sentiment,
            'future_potential': future_potential,
        }

    def _extract_catalysts(self, news_list: List[Dict[str, str]]) -> Dict[str, List[str]]:
        """ニュースからカタリストを抽出"""
        catalysts = {}

        for news in news_list[:5]:  # 最新5件を分析
            title = news.get('title', '')

            for category, keywords in self.CATALYST_KEYWORDS.items():
                for keyword in keywords:
                    if keyword in title:
                        if category not in catalysts:
                            catalysts[category] = []
                        # カテゴリから【】を除去
                        clean_title = re.sub(r'^【[^】]+】', '', title)
                        catalysts[category].append(clean_title)
                        break

        return catalysts

    def _consolidate_reasons(
        self,
        news_list: List[Dict[str, str]],
        catalysts: Dict[str, List[str]],
        stock_info: Dict
    ) -> str:
        """上昇理由を一段落にまとめる"""

        # ニュースタイトルから重要な情報を抽出
        key_info = []

        for news in news_list[:3]:  # 最新3件
            title = news.get('title', '')

            # 【材料】などのカテゴリを抽出
            category_match = re.search(r'^【([^】]+)】', title)
            if category_match:
                category = category_match.group(1)
                content = re.sub(r'^【[^】]+】', '', title).strip()

                # 重要な情報のみ追加
                if any(kw in content for kw in ['ストップ高', 'S高', '大株主', '決算', '上方修正', '受注', '契約']):
                    key_info.append(content)

        # カタリストから主要な理由を特定
        main_catalyst = ""
        if '決算' in catalysts:
            main_catalyst = "決算発表や業績上方修正"
        elif '大株主' in catalysts:
            main_catalyst = "大株主の異動"
        elif '契約・提携' in catalysts:
            main_catalyst = "大型契約の獲得"
        elif '新製品・技術' in catalysts:
            main_catalyst = "新製品・新技術の発表"
        elif '相場' in catalysts:
            main_catalyst = "市場での買い人気"

        # 一段落にまとめる
        stock_name = stock_info.get('name', '本銘柄')
        change_rate = stock_info.get('change_rate', 0)

        if key_info:
            # 具体的な理由がある場合
            reason_text = f"{stock_name}は前日比{change_rate:+.1f}%の大幅高となった。"

            if main_catalyst:
                reason_text += f"主な上昇要因は{main_catalyst}。"

            # 具体的な内容を追加（最大2つ）
            for info in key_info[:2]:
                reason_text += f"具体的には、{info}。"

            # ポジティブワードがあれば追加
            positive_mentions = []
            for news in news_list[:3]:
                title = news.get('title', '')
                for word in self.POSITIVE_WORDS:
                    if word in title:
                        positive_mentions.append(word)
                        break

            if positive_mentions:
                reason_text += f"市場では{', '.join(positive_mentions[:2])}と評価されている。"

            return reason_text
        else:
            # 一般的な理由
            return f"{stock_name}は前日比{change_rate:+.1f}%上昇。材料視された情報により買いが優勢となった模様。"

    def _analyze_sentiment(self, news_list: List[Dict[str, str]]) -> str:
        """センチメント分析"""
        positive_count = 0
        negative_count = 0

        for news in news_list[:5]:
            title = news.get('title', '')

            # ポジティブワードをカウント
            for word in self.POSITIVE_WORDS:
                if word in title:
                    positive_count += 1

            # ネガティブワードをカウント
            for word in self.NEGATIVE_WORDS:
                if word in title:
                    negative_count += 1

        if positive_count > negative_count * 2:
            return 'very_positive'
        elif positive_count > negative_count:
            return 'positive'
        elif negative_count > positive_count:
            return 'negative'
        else:
            return 'neutral'

    def _evaluate_future_potential(
        self,
        catalysts: Dict[str, List[str]],
        sentiment: str,
        stock_info: Dict
    ) -> str:
        """将来性を評価"""

        # 変化率を取得
        change_rate = stock_info.get('change_rate', 0)

        # 評価ポイント
        scores = []
        reasons = []

        # カタリストベースの評価
        if '決算' in catalysts:
            scores.append(2)
            reasons.append("業績好調")

        if '新製品・技術' in catalysts:
            scores.append(2)
            reasons.append("新技術・新製品による成長期待")

        if '契約・提携' in catalysts:
            scores.append(1)
            reasons.append("事業拡大")

        if '株主還元' in catalysts:
            scores.append(1)
            reasons.append("株主還元強化")

        # センチメントベースの評価
        if sentiment == 'very_positive':
            scores.append(2)
        elif sentiment == 'positive':
            scores.append(1)
        elif sentiment == 'negative':
            scores.append(-1)

        # 上昇率ベースの評価（ただし過熱感も考慮）
        if 5 <= change_rate <= 15:
            scores.append(1)
            reasons.append("適度な上昇")
        elif change_rate > 15:
            reasons.append("短期的な過熱感あり")

        # 総合評価
        total_score = sum(scores)

        if total_score >= 4:
            evaluation = "将来性は非常に高いと評価される"
        elif total_score >= 2:
            evaluation = "将来性は期待できる"
        elif total_score >= 0:
            evaluation = "中立的な見方"
        else:
            evaluation = "慎重な判断が必要"

        # 理由を追加
        if reasons:
            evaluation += f"。理由：{', '.join(reasons)}。"
        else:
            evaluation += "。"

        # 注意事項
        if change_rate > 20:
            evaluation += "ただし、急騰後のため短期的な調整リスクに注意。"

        return evaluation


if __name__ == '__main__':
    # テスト
    analyzer = StockAnalyzer()

    test_news = [
        {'title': '【材料】地盤ＨＤはＳ高カイ気配、井村俊哉氏が代表の「Ｋａｉｈｏｕ」大株主浮上', 'date': '26/02/10 14:24'},
        {'title': '【開示】主要株主の異動並びにその他の関係会社の異動に関するお知らせ', 'date': '26/02/09 16:30'},
        {'title': '【テク】地盤ネットHD---気配値で既にストップ高', 'date': '26/02/10 08:54'},
    ]

    test_stock_info = {
        'code': '6072',
        'name': '地盤ネットホールディングス',
        'change_rate': 32.3,
        'pts_price': 328.0,
    }

    result = analyzer.analyze_price_increase_reason(test_news, test_stock_info)

    print("=== 分析結果 ===")
    print(f"\n【上昇理由】\n{result['main_reason']}")
    print(f"\n【カタリスト】")
    for cat, items in result['catalysts'].items():
        print(f"  {cat}: {len(items)}件")
    print(f"\n【センチメント】{result['sentiment']}")
    print(f"\n【将来性評価】\n{result['future_potential']}")
