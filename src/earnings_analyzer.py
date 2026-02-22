"""
Claude APIを使って決算資料を深掘り分析するモジュール
"""
import os
import json
import re
import time
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
            logger.warning("ANTHROPIC_API_KEY 未設定。決算分析が制限されます。")

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
            prompt = f"""以下の情報を基に、この銘柄の決算内容を分析してください。

【重要なルール】
- 以下に提供されている情報（開示タイトル・ニュース）に書いてある内容だけを使ってください
- 情報に書いていないことは推測・追加しないでください
- 確認できない数値や事実は書かないでください
- 不明な点は「詳細は開示資料を参照」と書いてください

【銘柄情報】
- コード: {stock_info.get('code')}
- 銘柄名: {stock_info.get('name')}
- 変化率: {stock_info.get('change_rate', 0):+.1f}%

【決算開示タイトル】
{disclosure_title}

【関連ニュース】
{news_context}

上記の情報から確認できる内容のみで以下のJSON形式で返してください：
{{
  "earnings_reason": "開示タイトルとニュースから確認できる決算内容（2-3文）",
  "key_factors": ["確認できる要因1", "確認できる要因2", "確認できる要因3"],
  "outlook": "ニュースから確認できる見通し（確認できない場合は詳細は開示資料を参照）"
}}
"""

            logger.info("Claude APIで決算分析中...")
            content = self._call_claude_api(prompt)
            if not content:
                return self._fallback_analysis(disclosure_title, news_list, stock_info)

            analysis = self._parse_json_response(content)
            if analysis:
                logger.info("✓ Claude APIでの決算分析完了")
                return analysis

            # JSONパース失敗時
            return {
                'earnings_reason': content[:200],
                'key_factors': [],
                'outlook': ''
            }

        except Exception as e:
            logger.error(f"Claude API呼び出しエラー: {e}")
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
        PDFテキストから決算を分析

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
            # PDFテキストを最大10000文字まで使用
            pdf_excerpt = pdf_text[:10000]

            prompt = f"""あなたはトップクラスの株式アナリスト・ヘッジファンドリサーチャー・財務諸表分析の専門家です。

以下の決算報告書を分析してください。
銘柄: {stock_info.get('name')}（コード: {stock_info.get('code')}、PTS変化率: {stock_info.get('change_rate', 0):+.1f}%）

【厳守ルール】
- 以下の文書に記載されている事実のみを使用してください。推測や創作は禁止です。
- 文書から具体的な数値や表現を引用してください。
- 文書に記載がない場合は「原文に記載なし」と記入してください。

====================================
決算報告書（原文）:
====================================
{pdf_excerpt}

====================================
分析項目:
====================================

1. 損益計算書: 売上高の成長率（前年比/前期比）、営業利益、純利益、利益率の変化、コスト構造の変化。文書から正確な数値を使用。

2. ガイダンス・見通し: 会社予想、経営陣のコメント、上方修正や据え置きの有無。

3. 株価変動の主要因: なぜこの銘柄が動いたか？ EPSサプライズ、利益率拡大、受注増、ガイダンス上方修正、リストラ、新規契約？

4. 構造的カタリスト: AI・半導体・EV・防衛需要、製品ミックス改善、新市場開拓、コスト削減、業界サイクルの転換点？

5. リスク要因: 収益の集中リスク、為替リスク、コスト上昇、レバレッジ、需要減速。これらは既に株価に織り込み済みか？

6. 投資テーゼ: 文書に基づく強気ポイントを3〜5つ。

以下のJSON形式のみで返してください（マークダウンや余計なテキストは不要）:
{{
  "earnings_reason": "決算内容が変化した理由を具体的な数値付きで2〜4文で要約",
  "financial_summary": "売上高: X、営業利益: Y、純利益: Z、前年比変化を正確な数値で",
  "key_factors": ["具体的データ付きの要因1", "具体的データ付きの要因2", "具体的データ付きの要因3"],
  "catalysts": ["構造的カタリスト1", "構造的カタリスト2"],
  "risks": ["リスク1", "リスク2"],
  "investment_thesis": ["強気ポイント1", "強気ポイント2", "強気ポイント3"],
  "short_term_impact": "High/Medium/Low",
  "long_term_impact": "High/Medium/Low",
  "outlook": "会社予想や将来見通し（記載がない場合は原文に記載なし）"
}}"""

            content = self._call_claude_api(prompt)
            if not content:
                return None  # Noneを返してフォールバックに任せる

            analysis = self._parse_json_response(content)
            if analysis:
                logger.info("✓ Claude APIでのPDF分析完了")
                return analysis

            return {
                'earnings_reason': content[:200] if content else None,
                'key_factors': [],
                'outlook': ''
            }

        except Exception as e:
            logger.error(f"PDFテキスト分析エラー: {e}")
            return None  # Noneを返してフォールバックに任せる

    def _call_claude_api(self, prompt: str, max_retries: int = 2) -> Optional[str]:
        """
        Claude APIを呼び出す（リトライ付き）

        Args:
            prompt: プロンプト
            max_retries: タイムアウト時の最大リトライ回数

        Returns:
            str: レスポンステキスト、失敗時はNone
        """
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        data = {
            "model": "claude-sonnet-4-5-20250929",
            "max_tokens": 2048,
            "messages": [{"role": "user", "content": prompt}]
        }

        for attempt in range(max_retries + 1):
            try:
                response = requests.post(
                    self.api_url, headers=headers, json=data, timeout=60
                )
                response.raise_for_status()
                return response.json().get('content', [{}])[0].get('text', '')
            except requests.exceptions.Timeout:
                if attempt < max_retries:
                    logger.warning(f"APIタイムアウト（{attempt + 1}/{max_retries + 1}回目）、5秒後にリトライ...")
                    time.sleep(5)
                else:
                    logger.error("全リトライ後もAPIタイムアウト")
                    return None
            except Exception as e:
                logger.error(f"API呼び出し失敗: {e}")
                return None

    def _parse_json_response(self, content: str) -> Optional[Dict]:
        """JSONレスポンスをパース（markdownコードブロック対応）"""
        if not content:
            return None
        try:
            json_content = content
            if '```' in content:
                json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', content, re.DOTALL)
                if json_match:
                    json_content = json_match.group(1).strip()
            return json.loads(json_content)
        except json.JSONDecodeError:
            return None

    def analyze_with_news_content(self, news_content: str, stock_info: Dict) -> Optional[Dict[str, str]]:
        """
        株探などのニュース記事本文から株価上昇理由を分析

        Args:
            news_content: ニュース記事の本文テキスト（複数記事をまとめたもの）
            stock_info: 株式情報

        Returns:
            Dict: 分析結果（失敗時はNone）
        """
        if not self.api_key or not news_content:
            return None

        prompt = f"""あなたはトップクラスの株式アナリスト・ヘッジファンドリサーチャー・財務諸表分析の専門家です。

以下のニュース・決算データを分析してください。
銘柄: {stock_info.get('name')}（コード: {stock_info.get('code')}、PTS変化率: {stock_info.get('change_rate', 0):+.1f}%）

【厳守ルール】
- 以下のニュース記事に記載されている事実のみを使用してください。推測や創作は禁止です。
- 記事から具体的な数値や表現を引用してください。
- 記事に記載がない場合は「原文に記載なし」と記入してください。

====================================
ニュース記事（原文）:
====================================
{news_content[:8000]}

====================================
分析項目:
====================================

1. 決算・業績: 売上高の成長率、利益の変化、利益率のトレンド。記事から正確な数値を使用。

2. 株価変動の主要因: なぜこの銘柄が急騰したか？ 決算上振れ、ガイダンス上方修正、新規契約、M&A、提携、規制認可、AI・テクノロジー関連材料？

3. 構造的カタリスト: AI・半導体・EV・防衛需要、製品ミックス改善、新市場開拓、リストラ、業界サイクルの転換点？

4. リスク要因: 何が問題になりうるか？ 記事の内容に基づき、リスクは既に株価に織り込み済みか？

5. 投資テーゼ: 記事の事実のみに基づく強気ポイントを3〜5つ。

以下のJSON形式のみで返してください（マークダウンや余計なテキストは不要）:
{{
  "earnings_reason": "株価が動いた理由を具体的な数値付きで2〜4文で要約",
  "financial_summary": "記事から確認できる主要財務指標と正確な数値",
  "key_factors": ["具体的データ付きの要因1", "具体的データ付きの要因2", "具体的データ付きの要因3"],
  "catalysts": ["構造的カタリスト1", "構造的カタリスト2"],
  "risks": ["リスク1", "リスク2"],
  "investment_thesis": ["強気ポイント1", "強気ポイント2", "強気ポイント3"],
  "short_term_impact": "High/Medium/Low",
  "long_term_impact": "High/Medium/Low",
  "outlook": "会社予想やアナリスト見通し（記載がない場合は原文に記載なし）"
}}"""

        logger.info("  → 🔍 ニュース記事からClaude APIで分析中...")
        content = self._call_claude_api(prompt)
        if not content:
            return None

        result = self._parse_json_response(content)
        if result:
            logger.info("✓ ニュース記事からの分析完了")
        return result


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
