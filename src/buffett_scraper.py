"""
Buffett CodeからPTSランキング情報を取得するモジュール
"""
import requests
from bs4 import BeautifulSoup
import re
import time
from typing import List, Dict, Optional
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BuffettCodeScraper:
    """Buffett CodeからPTSランキングをスクレイピングするクラス"""

    BASE_URL = "https://www.buffett-code.com"
    PTS_URL = f"{BASE_URL}/pts"

    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8',
    }

    def __init__(self, retry_count: int = 3, retry_delay: float = 2.0):
        """
        Args:
            retry_count: リトライ回数
            retry_delay: リトライ時の待機時間（秒）
        """
        self.retry_count = retry_count
        self.retry_delay = retry_delay
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)

    def fetch_pts_ranking(self) -> List[Dict[str, any]]:
        """
        PTSランキング情報を取得

        Returns:
            List[Dict]: 銘柄情報のリスト
                - code: 銘柄コード
                - name: 銘柄名
                - pts_price: PTS価格
                - change_rate: 変化率（%）
                - change_amount: 変化額（円）
                - volume: 出来高
                - market: 市場区分
                - industry: 業種
                - market_cap: 時価総額
                - per: PER
                - pbr: PBR
        """
        for attempt in range(self.retry_count):
            try:
                logger.info(f"Fetching PTS ranking (attempt {attempt + 1}/{self.retry_count})")

                # First access main page to establish session
                self.session.get(self.BASE_URL, timeout=10)
                time.sleep(1)

                # Then access PTS page
                response = self.session.get(self.PTS_URL, timeout=30)
                response.raise_for_status()
                response.encoding = 'utf-8'

                soup = BeautifulSoup(response.text, 'lxml')
                rankings = self._parse_ranking_tables(soup)

                logger.info(f"Successfully fetched {len(rankings)} stocks from PTS ranking")
                return rankings

            except requests.RequestException as e:
                logger.error(f"Error fetching PTS ranking: {e}")
                if attempt < self.retry_count - 1:
                    logger.info(f"Retrying in {self.retry_delay} seconds...")
                    time.sleep(self.retry_delay)
                else:
                    logger.error("Max retry count reached. Giving up.")
                    raise

        return []

    def _parse_ranking_tables(self, soup: BeautifulSoup) -> List[Dict[str, any]]:
        """
        HTMLからランキングテーブルをパースする

        Args:
            soup: BeautifulSoupオブジェクト

        Returns:
            List[Dict]: パースされた銘柄情報
        """
        rankings = []

        # Find all tables with class 'table'
        tables = soup.find_all('table', class_='table')

        for table in tables:
            tbody = table.find('tbody')
            if not tbody:
                continue

            rows = tbody.find_all('tr')

            for row in rows:
                try:
                    stock_data = self._parse_stock_row(row)
                    if stock_data:
                        rankings.append(stock_data)
                except Exception as e:
                    logger.warning(f"Error parsing row: {e}")
                    continue

        return rankings

    def _parse_stock_row(self, row) -> Optional[Dict[str, any]]:
        """
        テーブル行から銘柄データを抽出

        Args:
            row: BeautifulSoupのtr要素

        Returns:
            Dict: 銘柄データ、またはNone
        """
        cols = row.find_all('td')
        if len(cols) < 10:
            return None

        # 会社名から銘柄コードと名前を抽出
        # 例: "6072,東S地盤ネット"
        company_text = cols[1].get_text(strip=True)
        code_match = re.match(r'(\d{4}),(.+)', company_text)
        if not code_match:
            return None

        code = code_match.group(1)
        full_name = code_match.group(2)

        # 市場区分と会社名を分離 (例: "東S地盤ネット" -> 東S, 地盤ネット)
        market_match = re.match(r'(東[SPGM]|名|札|福)', full_name)
        if market_match:
            market = market_match.group(1)
            name = full_name[len(market):]
        else:
            market = ""
            name = full_name

        # 業種
        industry = cols[2].get_text(strip=True)

        # 現在値と変化率
        # 例: "02/10 23:25328.0" or "02/11 06:001,367.0"
        price_text = cols[3].get_text(strip=True)

        # 価格を抽出 (日時の後の数値、カンマも考慮)
        # パターン: "02/10 23:25328.0" -> 328.0 or "02/11 06:001,367.0" -> 1367.0
        price_match = re.search(r':\d{2}([\d,]+\.?\d*)', price_text)
        if price_match:
            price_str = price_match.group(1).replace(',', '')
            pts_price = float(price_str)
        else:
            pts_price = 0.0

        # 変化率を抽出
        # 例: "+80+32.3%" or "+237+21.0%"
        change_rate_text = cols[4].get_text(strip=True)

        # パーセンテージを抽出
        rate_match = re.search(r'([+-]?\d+\.?\d*)%', change_rate_text)
        change_rate = float(rate_match.group(1)) if rate_match else 0.0

        # 変化額を抽出 (最初の+/-付きの数値)
        amount_match = re.search(r'^([+-]\d+)', change_rate_text)
        change_amount = float(amount_match.group(1)) if amount_match else 0.0

        # 出来高
        volume_text = cols[5].get_text(strip=True).replace(',', '')
        volume = self._parse_number(volume_text, is_int=True) or 0

        # 時価総額
        market_cap = cols[7].get_text(strip=True)

        # PER, PBR
        per = cols[8].get_text(strip=True)
        pbr = cols[9].get_text(strip=True)

        return {
            'code': code,
            'name': name,
            'pts_price': pts_price,
            'change_rate': change_rate,
            'change_amount': change_amount,
            'volume': volume,
            'market': market,
            'industry': industry,
            'market_cap': market_cap,
            'per': per,
            'pbr': pbr,
        }

    def _parse_number(self, text: str, is_int: bool = False) -> Optional[float]:
        """
        文字列を数値に変換

        Args:
            text: 変換する文字列
            is_int: 整数として扱うかどうか

        Returns:
            float or int or None: 変換された数値
        """
        try:
            text = text.strip().replace(',', '')
            if not text or text == '--' or text == '-':
                return None

            number = float(text)
            return int(number) if is_int else number
        except ValueError:
            return None

    def close(self):
        """セッションをクローズ"""
        self.session.close()


if __name__ == "__main__":
    # テスト実行
    scraper = BuffettCodeScraper()
    try:
        rankings = scraper.fetch_pts_ranking()
        print(f"取得した銘柄数: {len(rankings)}")
        print("\n=== 上位5銘柄 ===")
        for i, stock in enumerate(rankings[:5], 1):
            print(f"{i}. [{stock['code']}] {stock['name']}")
            print(f"   PTS価格: {stock['pts_price']}円 ({stock['change_rate']:+.1f}%)")
            print(f"   出来高: {stock['volume']:,}株")
            print(f"   業種: {stock['industry']}")
            print()
    finally:
        scraper.close()
