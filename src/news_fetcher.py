"""
銘柄ニュース情報を取得するモジュール
"""
import requests
from bs4 import BeautifulSoup
import time
from typing import List, Dict, Optional
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class NewsFetcher:
    """銘柄のニュース情報を取得するクラス"""

    KABUTAN_BASE_URL = "https://kabutan.jp"

    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'ja,en-US;q=0.7,en;q=0.3',
    }

    def __init__(self, max_news: int = 3, request_delay: float = 1.0):
        """
        Args:
            max_news: 取得する最大ニュース数
            request_delay: リクエスト間の待機時間（秒）
        """
        self.max_news = max_news
        self.request_delay = request_delay
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)

    def fetch_stock_news(self, stock_code: str) -> List[Dict[str, str]]:
        """
        指定された銘柄の最新ニュースを取得

        Args:
            stock_code: 銘柄コード

        Returns:
            List[Dict]: ニュース情報のリスト
                - title: ニュースタイトル
                - date: 公開日時
                - url: ニュースURL
                - source: ニュースソース
        """
        try:
            time.sleep(self.request_delay)  # レート制限対策

            news_url = f"{self.KABUTAN_BASE_URL}/stock/news?code={stock_code}"
            logger.info(f"Fetching news for stock {stock_code}")

            response = self.session.get(news_url, timeout=30)
            response.raise_for_status()
            response.encoding = response.apparent_encoding

            soup = BeautifulSoup(response.text, 'lxml')
            news_list = self._parse_news_list(soup)

            logger.info(f"Found {len(news_list)} news items for stock {stock_code}")
            return news_list[:self.max_news]

        except requests.RequestException as e:
            logger.error(f"Error fetching news for stock {stock_code}: {e}")
            return []

    def _parse_news_list(self, soup: BeautifulSoup) -> List[Dict[str, str]]:
        """
        HTMLからニュース一覧をパースする

        Args:
            soup: BeautifulSoupオブジェクト

        Returns:
            List[Dict]: パースされたニュース情報
        """
        news_list = []

        # 株探のニュース一覧を探す
        # 注意: 実際のHTML構造に合わせて調整が必要
        news_items = soup.find_all('div', class_='news_item') or soup.find_all('tr', class_='data')

        if not news_items:
            # 別の構造を試す
            news_table = soup.find('table', class_='stock_table')
            if news_table:
                news_items = news_table.find_all('tr')[1:]  # ヘッダー行をスキップ

        for item in news_items:
            try:
                # タイトルとリンクを取得
                title_link = item.find('a')
                if not title_link:
                    continue

                title = title_link.text.strip()
                url = title_link.get('href', '')

                # 相対URLを絶対URLに変換
                if url and not url.startswith('http'):
                    url = f"{self.KABUTAN_BASE_URL}{url}"

                # 日時を取得
                date_elem = item.find('td', class_='date') or item.find('span', class_='date')
                date = date_elem.text.strip() if date_elem else ""

                # ニュースソースを取得（あれば）
                source_elem = item.find('span', class_='source')
                source = source_elem.text.strip() if source_elem else "株探"

                news_data = {
                    'title': title,
                    'date': date,
                    'url': url,
                    'source': source,
                }

                news_list.append(news_data)

            except Exception as e:
                logger.warning(f"Error parsing news item: {e}")
                continue

        return news_list

    def get_company_info(self, stock_code: str) -> Optional[Dict[str, str]]:
        """
        銘柄の基本情報を取得

        Args:
            stock_code: 銘柄コード

        Returns:
            Dict: 企業情報
                - market: 市場区分
                - industry: 業種
                - market_cap: 時価総額
                - description: 事業内容
        """
        try:
            time.sleep(self.request_delay)

            detail_url = f"{self.KABUTAN_BASE_URL}/stock/?code={stock_code}"
            logger.info(f"Fetching company info for stock {stock_code}")

            response = self.session.get(detail_url, timeout=30)
            response.raise_for_status()
            response.encoding = response.apparent_encoding

            soup = BeautifulSoup(response.text, 'lxml')
            company_info = self._parse_company_info(soup)

            return company_info

        except requests.RequestException as e:
            logger.error(f"Error fetching company info for stock {stock_code}: {e}")
            return None

    def _parse_company_info(self, soup: BeautifulSoup) -> Dict[str, str]:
        """
        HTMLから企業情報をパースする

        Args:
            soup: BeautifulSoupオブジェクト

        Returns:
            Dict: 企業情報
        """
        info = {
            'market': '',
            'industry': '',
            'market_cap': '',
            'description': '',
        }

        try:
            # 市場区分
            market_elem = soup.find('span', class_='market')
            if market_elem:
                info['market'] = market_elem.text.strip()

            # 業種
            industry_elem = soup.find('span', class_='industry')
            if industry_elem:
                info['industry'] = industry_elem.text.strip()

            # 時価総額
            market_cap_elem = soup.find('td', text='時価総額')
            if market_cap_elem:
                market_cap_value = market_cap_elem.find_next('td')
                if market_cap_value:
                    info['market_cap'] = market_cap_value.text.strip()

            # 事業内容
            description_elem = soup.find('div', class_='company_description')
            if description_elem:
                info['description'] = description_elem.text.strip()[:200]  # 最初の200文字

        except Exception as e:
            logger.warning(f"Error parsing company info: {e}")

        return info

    def close(self):
        """セッションをクローズ"""
        self.session.close()


if __name__ == "__main__":
    # テスト実行
    fetcher = NewsFetcher(max_news=3)
    try:
        # テスト用銘柄コード（トヨタ自動車）
        test_code = "7203"

        print(f"\n=== 銘柄 {test_code} のニュース ===")
        news = fetcher.fetch_stock_news(test_code)
        for i, item in enumerate(news, 1):
            print(f"{i}. {item['title']}")
            print(f"   日時: {item['date']}")
            print(f"   URL: {item['url']}\n")

        print(f"\n=== 銘柄 {test_code} の基本情報 ===")
        company_info = fetcher.get_company_info(test_code)
        if company_info:
            print(f"市場: {company_info['market']}")
            print(f"業種: {company_info['industry']}")
            print(f"時価総額: {company_info['market_cap']}")

    finally:
        fetcher.close()
