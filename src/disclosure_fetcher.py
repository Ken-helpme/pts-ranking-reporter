"""
TDnet（適時開示情報）から決算資料を取得するモジュール
"""
import requests
from bs4 import BeautifulSoup
import re
from typing import List, Dict, Optional
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DisclosureFetcher:
    """適時開示情報を取得するクラス"""

    KABUTAN_BASE_URL = "https://kabutan.jp"

    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'ja,en-US;q=0.7,en;q=0.3',
    }

    # 決算関連キーワード
    EARNINGS_KEYWORDS = [
        '決算', '業績', '四半期', '本決算', '中間決算',
        '上方修正', '下方修正', '修正', '業績予想',
        '連結', '単独'
    ]

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)

    def fetch_disclosure_info(self, stock_code: str) -> Dict[str, any]:
        """
        指定銘柄の開示情報を取得

        Args:
            stock_code: 銘柄コード

        Returns:
            Dict: 開示情報
                - has_earnings: 決算発表があるか
                - earnings_summary: 決算サマリー
                - disclosures: 開示リスト
        """
        try:
            # 株探の開示情報ページ
            url = f"{self.KABUTAN_BASE_URL}/stock/kabuka?code={stock_code}"
            logger.info(f"Fetching disclosure info for stock {stock_code}")

            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            response.encoding = response.apparent_encoding

            soup = BeautifulSoup(response.text, 'lxml')

            # ニュースから開示情報を探す
            disclosures = self._parse_disclosures_from_news(stock_code)

            # 決算関連の開示があるかチェック
            has_earnings = False
            earnings_summary = ""

            for disclosure in disclosures:
                title = disclosure.get('title', '')
                if any(keyword in title for keyword in self.EARNINGS_KEYWORDS):
                    has_earnings = True
                    earnings_summary = self._summarize_earnings(disclosure)
                    break

            return {
                'has_earnings': has_earnings,
                'earnings_summary': earnings_summary,
                'disclosures': disclosures[:5],  # 最新5件
            }

        except Exception as e:
            logger.error(f"Error fetching disclosure info: {e}")
            return {
                'has_earnings': False,
                'earnings_summary': "",
                'disclosures': [],
            }

    def _parse_disclosures_from_news(self, stock_code: str) -> List[Dict[str, str]]:
        """ニュースから開示情報を抽出"""
        try:
            # 株探のニュースページから開示を取得
            news_url = f"{self.KABUTAN_BASE_URL}/stock/news?code={stock_code}"
            response = self.session.get(news_url, timeout=30)
            response.encoding = response.apparent_encoding

            soup = BeautifulSoup(response.text, 'lxml')
            news_table = soup.find('table', class_='s_news_list')

            if not news_table:
                return []

            disclosures = []
            rows = news_table.find_all('tr')

            for row in rows:
                try:
                    cols = row.find_all('td')
                    if len(cols) < 3:
                        continue

                    # カテゴリをチェック
                    category_td = cols[1]
                    category_elem = category_td.find('div', class_='newslist_ctg')
                    category = category_elem.get_text(strip=True) if category_elem else ""

                    # 開示情報のみ抽出
                    if category != '開示':
                        continue

                    # タイトルとリンク
                    title_td = cols[2]
                    title_link = title_td.find('a')
                    if not title_link:
                        continue

                    title = title_link.get_text(strip=True)
                    url = title_link.get('href', '')

                    if url and not url.startswith('http'):
                        # PDFリンクの場合
                        if '/disclosures/pdf/' in url:
                            url = f"{self.KABUTAN_BASE_URL}{url}"

                    # 日時
                    time_td = cols[0]
                    time_elem = time_td.find('time')
                    date = time_elem.get_text(strip=True) if time_elem else ""

                    disclosures.append({
                        'title': title,
                        'date': date,
                        'url': url,
                        'type': 'earnings' if any(kw in title for kw in self.EARNINGS_KEYWORDS) else 'other'
                    })

                except Exception as e:
                    logger.warning(f"Error parsing disclosure row: {e}")
                    continue

            return disclosures

        except Exception as e:
            logger.error(f"Error parsing disclosures: {e}")
            return []

    def _summarize_earnings(self, disclosure: Dict[str, str]) -> str:
        """決算開示をサマライズ"""
        title = disclosure.get('title', '')

        summary = "決算発表："

        # タイトルから重要情報を抽出
        if '上方修正' in title:
            summary += "業績予想を上方修正。"
        elif '下方修正' in title:
            summary += "業績予想を下方修正。"
        elif '増益' in title:
            summary += "増益決算。"
        elif '減益' in title:
            summary += "減益決算。"
        else:
            summary += f"{title}。"

        # PDFがある場合
        if disclosure.get('url') and 'pdf' in disclosure.get('url', ''):
            summary += "詳細は開示資料を参照。"

        return summary

    def analyze_earnings_impact(self, disclosure_info: Dict) -> str:
        """決算が株価に与える影響を分析"""
        if not disclosure_info.get('has_earnings'):
            return ""

        earnings_summary = disclosure_info.get('earnings_summary', '')

        # ポジティブな決算かどうか判定
        positive_keywords = ['上方修正', '増益', '過去最高', '好調', '増配']
        negative_keywords = ['下方修正', '減益', '赤字', '減配']

        is_positive = any(kw in earnings_summary for kw in positive_keywords)
        is_negative = any(kw in earnings_summary for kw in negative_keywords)

        if is_positive:
            return "決算内容が好感され、買い材料となった模様。業績の上振れや上方修正が評価されている。"
        elif is_negative:
            return "決算内容に対する懸念から売りが先行した可能性。"
        else:
            return "決算発表を受けて材料視された。"

    def close(self):
        """セッションをクローズ"""
        self.session.close()


if __name__ == '__main__':
    # テスト
    fetcher = DisclosureFetcher()

    try:
        # テスト用銘柄コード
        test_code = "6072"

        print(f"\n=== 銘柄 {test_code} の開示情報 ===")
        disclosure_info = fetcher.fetch_disclosure_info(test_code)

        print(f"決算発表あり: {disclosure_info['has_earnings']}")
        if disclosure_info['earnings_summary']:
            print(f"決算サマリー: {disclosure_info['earnings_summary']}")

        print(f"\n開示情報一覧:")
        for i, disc in enumerate(disclosure_info['disclosures'], 1):
            print(f"{i}. [{disc['date']}] {disc['title']}")
            if disc['type'] == 'earnings':
                print(f"   → 決算関連")

        # 影響分析
        impact = fetcher.analyze_earnings_impact(disclosure_info)
        if impact:
            print(f"\n株価への影響:\n{impact}")

    finally:
        fetcher.close()
