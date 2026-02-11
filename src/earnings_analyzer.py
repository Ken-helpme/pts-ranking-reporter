"""
Claude APIを使って決算資料を深掘り分析するモジュール
"""
import os
import requests
from typing import Dict, Optional
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class EarningsAnalyzer:
    """Claude APIで決算内容を分析するクラス"""

    def __init__(self, api_key: Optional[str] = None):
        """
        Args:
            api_key: Claude API Key (環境変数 ANTHROPIC_API_KEY からも取得可能)
        """
        self.api_key = api_key or os.getenv('ANTHROPIC_API_KEY')
        if not self.api_key:
            logger.warning("ANTHROPIC_API_KEY not set. Earnings analysis will be limited.")

        self.api_url = "https://api.anthropic.com/v1/messages"

    def analyze_earnings_detail(
        self,
        disclosure_title: str,
        news_list: list,
        stock_info: Dict
    ) -> Dict[str, str]:
        """
        決算内容を深掘り分析

        Args:
            disclosure_title: 開示資料のタイトル
            news_list: 関連ニュースリスト
            stock_info: 株式情報

        Returns:
            Dict: 分析結果
                - earnings_reason: なぜ好決算/上方修正になったか
                - key_factors: 主要な要因（箇条書き）
                - outlook: 今後の見通し
        """
        if not self.api_key:
            return self._fallback_analysis(disclosure_title, news_list, stock_info)

        try:
            # ニュースからコンテキストを作成
            news_context = "\n".join([
                f"- {news.get('title', '')} ({news.get('date', '')})"
                for news in news_list[:5]
            ])

            # Claude APIに送るプロンプト
            prompt = f"""以下の情報を基に、この銘柄の決算内容と株価上昇理由を分析してください。

【銘柄情報】
- コード: {stock_info.get('code')}
- 銘柄名: {stock_info.get('name')}
- 変化率: {stock_info.get('change_rate', 0):+.1f}%

【決算開示】
{disclosure_title}

【関連ニュース】
{news_context}

以下の3つの観点で分析してください：

1. **決算の内容**: なぜ好決算/上方修正になったのか？（売上増加の理由、利益改善の要因など）

2. **主要な要因**: 具体的な要因を3つ箇条書きで

3. **今後の見通し**: この決算を受けて、今後の業績や株価はどうなりそうか？

回答は以下のJSON形式で返してください：
{{
  "earnings_reason": "決算内容の説明（2-3文）",
  "key_factors": ["要因1", "要因2", "要因3"],
  "outlook": "今後の見通し（2-3文）"
}}
"""

            # Claude API呼び出し
            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            }

            data = {
                "model": "claude-3-5-sonnet-20241022",
                "max_tokens": 1024,
                "messages": [
                    {"role": "user", "content": prompt}
                ]
            }

            logger.info(f"Calling Claude API for earnings analysis...")
            response = requests.post(self.api_url, headers=headers, json=data, timeout=30)
            response.raise_for_status()

            result = response.json()
            content = result.get('content', [{}])[0].get('text', '{}')

            # JSONをパース
            import json
            try:
                analysis = json.loads(content)
                logger.info("✓ Successfully analyzed earnings with Claude API")
                return analysis
            except json.JSONDecodeError:
                # JSONパースに失敗した場合はテキストをそのまま返す
                return {
                    'earnings_reason': content[:200],
                    'key_factors': [],
                    'outlook': ''
                }

        except Exception as e:
            logger.error(f"Error calling Claude API: {e}")
            return self._fallback_analysis(disclosure_title, news_list, stock_info)

    def _fallback_analysis(
        self,
        disclosure_title: str,
        news_list: list,
        stock_info: Dict
    ) -> Dict[str, str]:
        """API未設定時のフォールバック分析"""

        # キーワードベースの簡易分析
        reason = ""
        factors = []

        if '上方修正' in disclosure_title:
            reason = "業績予想を上方修正。"
            factors.append("業績が当初予想を上回る")

        if '増益' in disclosure_title or '好調' in disclosure_title:
            reason += "増益決算を発表。"
            factors.append("利益が増加")

        # ニュースから要因を抽出
        for news in news_list[:3]:
            title = news.get('title', '')
            if '受注' in title or '契約' in title:
                factors.append("大型受注や契約獲得")
            if '需要' in title or '拡大' in title:
                factors.append("需要拡大による売上増")
            if 'コスト' in title or '効率' in title:
                factors.append("コスト削減や効率化")

        if not factors:
            factors = ["具体的な要因は開示資料を参照", "市場環境の改善", "業績好調"]

        return {
            'earnings_reason': reason or "決算発表により株価が反応。",
            'key_factors': factors[:3],
            'outlook': "詳細は開示資料をご確認ください。Claude API設定で自動分析可能です。"
        }

    def analyze_with_pdf_text(self, pdf_text: str, stock_info: Dict) -> Dict[str, str]:
        """
        PDFテキストから決算を分析（将来の拡張用）

        Args:
            pdf_text: PDFから抽出したテキスト
            stock_info: 株式情報

        Returns:
            Dict: 分析結果
        """
        if not self.api_key:
            return {
                'earnings_reason': 'API未設定',
                'key_factors': [],
                'outlook': ''
            }

        try:
            prompt = f"""以下の決算資料から、重要なポイントを抽出して分析してください。

【銘柄】
{stock_info.get('code')} - {stock_info.get('name')}

【決算資料抜粋】
{pdf_text[:3000]}  # 最初の3000文字

以下の形式で分析してください：
1. 決算のサマリー（売上・利益の状況）
2. 好決算/上方修正の主な理由（3つ）
3. 今後の見通し

JSON形式で返してください。
"""

            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            }

            data = {
                "model": "claude-3-5-sonnet-20241022",
                "max_tokens": 1024,
                "messages": [
                    {"role": "user", "content": prompt}
                ]
            }

            response = requests.post(self.api_url, headers=headers, json=data, timeout=30)
            response.raise_for_status()

            result = response.json()
            content = result.get('content', [{}])[0].get('text', '')

            import json
            return json.loads(content)

        except Exception as e:
            logger.error(f"Error analyzing PDF text: {e}")
            return {
                'earnings_reason': 'PDFテキスト分析エラー',
                'key_factors': [],
                'outlook': ''
            }


if __name__ == '__main__':
    # テスト実行
    analyzer = EarningsAnalyzer()

    # テストデータ
    test_disclosure = "2025年3月期 第3四半期決算短信〔日本基準〕(連結)を発表、業績予想の上方修正"

    test_news = [
        {'title': '【材料】好決算で株価急騰、売上高が過去最高を更新', 'date': '2026/02/10'},
        {'title': '【開示】業績予想の修正に関するお知らせ', 'date': '2026/02/09'},
    ]

    test_stock = {
        'code': '6072',
        'name': '地盤ネットホールディングス',
        'change_rate': 32.3
    }

    print("=== 決算分析テスト ===\n")
    result = analyzer.analyze_earnings_detail(test_disclosure, test_news, test_stock)

    print(f"【決算内容】\n{result['earnings_reason']}\n")
    print(f"【主要な要因】")
    for i, factor in enumerate(result['key_factors'], 1):
        print(f"{i}. {factor}")
    print(f"\n【今後の見通し】\n{result['outlook']}")

    if not analyzer.api_key:
        print("\n💡 Tip: ANTHROPIC_API_KEY環境変数を設定すると、Claude APIで自動分析します")
