"""
J-Quants API v2 クライアント
銘柄マスター、株価、決算データの取得
"""
import os
import time
import logging
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

class JQuantsClient:
    BASE_URL = "https://api.jquants.com/v2"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv('JQUANTS_API_KEY', '')
        self.session = requests.Session()
        self.session.headers.update({
            'x-api-key': self.api_key,
            'Accept': 'application/json',
        })
        self._master_cache = None
        self._master_cache_time = None

    def _get(self, path: str, params: Optional[Dict] = None) -> Dict:
        """API GETリクエスト"""
        url = f"{self.BASE_URL}{path}"
        try:
            resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            logger.error(f"J-Quants API error: {e} - {resp.text[:200]}")
            return {"data": [], "error": str(e)}
        except Exception as e:
            logger.error(f"J-Quants request failed: {e}")
            return {"data": [], "error": str(e)}

    # ========== マスターデータ ==========

    def get_master(self, code: Optional[str] = None) -> List[Dict]:
        """銘柄マスターデータ取得（キャッシュ: 1時間）"""
        if code:
            result = self._get("/equities/master", {"code": code})
            return result.get("data", [])

        # 全銘柄はキャッシュ
        now = time.time()
        if self._master_cache and self._master_cache_time and (now - self._master_cache_time < 3600):
            return self._master_cache

        result = self._get("/equities/master")
        data = result.get("data", [])
        if data:
            self._master_cache = data
            self._master_cache_time = now
        return data

    def get_sectors(self) -> List[Dict]:
        """業種一覧を取得"""
        master = self.get_master()
        sectors = {}
        for item in master:
            code = item.get("S33", "")
            name = item.get("S33Nm", "")
            if code and name and code not in sectors:
                sectors[code] = name
        return [{"code": k, "name": v} for k, v in sorted(sectors.items())]

    def get_markets(self) -> List[str]:
        """市場区分一覧"""
        master = self.get_master()
        markets = set()
        for item in master:
            mkt = item.get("MktNm", "")
            if mkt:
                markets.add(mkt)
        return sorted(markets)

    # ========== 株価データ ==========

    def get_prices(self, code: str, from_date: Optional[str] = None,
                   to_date: Optional[str] = None) -> List[Dict]:
        """日足株価データ取得"""
        params = {"code": code}
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        result = self._get("/equities/bars/daily", params)
        return result.get("data", [])

    def get_latest_prices(self, code: Optional[str] = None,
                          date: Optional[str] = None) -> List[Dict]:
        """最新株価を取得（全銘柄 or 単一銘柄）"""
        params = {}
        if code:
            params["code"] = code
        if date:
            params["date"] = date
        result = self._get("/equities/bars/daily", params)
        return result.get("data", [])

    # ========== 決算データ ==========

    def get_financial_summary(self, code: str) -> List[Dict]:
        """決算サマリーデータ取得"""
        result = self._get("/fins/summary", {"code": code})
        return result.get("data", [])

    def get_financial_statements(self, code: str) -> List[Dict]:
        """詳細決算データ取得"""
        result = self._get("/fins/statements", {"code": code})
        return result.get("data", [])

    # ========== スクリーニング ==========

    def screen_stocks(self, filters: Dict) -> List[Dict]:
        """
        銘柄スクリーニング

        filters:
            market: 市場区分（プライム, スタンダード, グロース）
            sector: 業種コード（S33）
            price_min / price_max: 株価範囲
            volume_min: 最低出来高
            change_rate_min / change_rate_max: 前日比(%)範囲
        """
        # 1. マスターデータで市場・業種フィルタ
        master = self.get_master()
        if not master:
            return []

        # マスターをコードで辞書化
        master_dict = {item["Code"]: item for item in master}

        market_filter = filters.get("market", "")
        sector_filter = filters.get("sector", "")

        # 対象銘柄を絞る
        target_codes = []
        for item in master:
            if market_filter and item.get("MktNm", "") != market_filter:
                continue
            if sector_filter and item.get("S33", "") != sector_filter:
                continue
            # TOKYO PRO MARKETは除外（流動性低い）
            if item.get("MktNm") == "TOKYO PRO MARKET":
                continue
            target_codes.append(item["Code"])

        logger.info(f"スクリーニング対象: {len(target_codes)}銘柄")

        # 2. 直近の株価データを取得
        # 全銘柄の株価を日付指定で一括取得
        today = datetime.now()
        prices_data = []
        # 直近5営業日を試行
        for days_back in range(0, 7):
            check_date = (today - timedelta(days=days_back)).strftime("%Y-%m-%d")
            result = self._get("/equities/bars/daily", {"date": check_date})
            data = result.get("data", [])
            if data and len(data) > 100:
                prices_data = data
                logger.info(f"株価データ取得: {check_date} ({len(data)}銘柄)")
                break
            time.sleep(0.3)

        if not prices_data:
            logger.warning("株価データが取得できませんでした")
            return []

        # 株価辞書化
        price_dict = {}
        for p in prices_data:
            price_dict[p["Code"]] = p

        # 前日の株価も取得（前日比計算用）
        prev_prices = {}
        if prices_data:
            price_date = prices_data[0].get("Date", "")
            if price_date:
                dt = datetime.strptime(price_date, "%Y-%m-%d")
                for days_back in range(1, 7):
                    prev_date = (dt - timedelta(days=days_back)).strftime("%Y-%m-%d")
                    result = self._get("/equities/bars/daily", {"date": prev_date})
                    data = result.get("data", [])
                    if data and len(data) > 100:
                        for p in data:
                            prev_prices[p["Code"]] = p
                        break
                    time.sleep(0.3)

        # 3. フィルター適用
        price_min = filters.get("price_min")
        price_max = filters.get("price_max")
        volume_min = filters.get("volume_min")
        change_rate_min = filters.get("change_rate_min")
        change_rate_max = filters.get("change_rate_max")

        results = []
        for code in target_codes:
            if code not in price_dict:
                continue

            price = price_dict[code]
            close = price.get("AdjC") or price.get("C")
            volume = price.get("AdjVo") or price.get("Vo") or 0

            if close is None or close == 0:
                continue

            # 株価フィルター
            if price_min is not None and close < price_min:
                continue
            if price_max is not None and close > price_max:
                continue

            # 出来高フィルター
            if volume_min is not None and volume < volume_min:
                continue

            # 前日比計算
            change_rate = 0.0
            change_amount = 0.0
            prev = prev_prices.get(code)
            if prev:
                prev_close = prev.get("AdjC") or prev.get("C") or 0
                if prev_close > 0:
                    change_amount = close - prev_close
                    change_rate = (change_amount / prev_close) * 100

            # 前日比フィルター
            if change_rate_min is not None and change_rate < change_rate_min:
                continue
            if change_rate_max is not None and change_rate > change_rate_max:
                continue

            # マスター情報を結合
            m = master_dict.get(code, {})
            results.append({
                "code": code.rstrip("0"),  # 末尾の0を除去
                "name": m.get("CoName", ""),
                "market": m.get("MktNm", ""),
                "sector": m.get("S33Nm", ""),
                "sector_code": m.get("S33", ""),
                "scale": m.get("ScaleCat", ""),
                "date": price.get("Date", ""),
                "open": price.get("AdjO") or price.get("O"),
                "high": price.get("AdjH") or price.get("H"),
                "low": price.get("AdjL") or price.get("L"),
                "close": close,
                "volume": volume,
                "turnover": price.get("Va", 0),
                "change_amount": round(change_amount, 1),
                "change_rate": round(change_rate, 2),
            })

        # ソート
        sort_by = filters.get("sort_by", "volume")
        sort_desc = filters.get("sort_desc", True)

        if sort_by in ["close", "volume", "turnover", "change_rate", "change_amount"]:
            results.sort(key=lambda x: x.get(sort_by, 0) or 0, reverse=sort_desc)
        elif sort_by == "name":
            results.sort(key=lambda x: x.get("name", ""), reverse=sort_desc)

        # 上限
        limit = filters.get("limit", 100)
        return results[:limit]
