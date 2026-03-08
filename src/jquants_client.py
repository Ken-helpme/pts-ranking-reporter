"""
J-Quants API v2 クライアント
銘柄マスター、株価、決算データの取得
"""
import os
import math
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
        self._price_cache: Dict[str, list] = {}  # date -> price list
        self._price_cache_time: Dict[str, float] = {}

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

    def _fetch_prices_for_date(self, date: str) -> List[Dict]:
        """指定日の全銘柄株価（キャッシュあり・10分）"""
        now = time.time()
        if date in self._price_cache and (now - self._price_cache_time.get(date, 0) < 600):
            return self._price_cache[date]
        result = self._get("/equities/bars/daily", {"date": date})
        data = result.get("data", [])
        if data and len(data) > 100:
            self._price_cache[date] = data
            self._price_cache_time[date] = now
        return data

    def _find_latest_trading_date(self) -> tuple[str, List[Dict]]:
        """最近の取引日と株価データを返す"""
        today = datetime.now()
        for days_back in range(0, 7):
            check_date = (today - timedelta(days=days_back)).strftime("%Y-%m-%d")
            data = self._fetch_prices_for_date(check_date)
            if data and len(data) > 100:
                return check_date, data
            time.sleep(0.2)
        return "", []

    def _find_prev_trading_date(self, base_date: str) -> List[Dict]:
        """base_dateの前の取引日の株価データを返す"""
        dt = datetime.strptime(base_date, "%Y-%m-%d")
        for days_back in range(1, 7):
            prev_date = (dt - timedelta(days=days_back)).strftime("%Y-%m-%d")
            data = self._fetch_prices_for_date(prev_date)
            if data and len(data) > 100:
                return data
            time.sleep(0.2)
        return []

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

    def _normalize_code(self, code: str) -> str:
        """J-Quants 5桁コードを4桁に変換（末尾0を1文字だけ除去）"""
        if len(code) == 5 and code.endswith("0"):
            return code[:-1]
        return code

    def _build_result(self, code: str, price: Dict, prev_price: Optional[Dict],
                      master_dict: Dict, used_date: str) -> Optional[Dict]:
        """1銘柄の結果Dictを構築"""
        close = price.get("AdjC") or price.get("C")
        volume = price.get("AdjVo") or price.get("Vo") or 0
        turnover = price.get("Va") or 0

        if not close or close == 0:
            return None

        change_rate = 0.0
        change_amount = 0.0
        if prev_price:
            prev_close = prev_price.get("AdjC") or prev_price.get("C") or 0
            if prev_close > 0:
                change_amount = close - prev_close
                change_rate = (change_amount / prev_close) * 100

        m = master_dict.get(code, {})
        return {
            "code": self._normalize_code(code),
            "name": m.get("CoName", ""),
            "market": m.get("MktNm", ""),
            "sector": m.get("S33Nm", ""),
            "sector_code": m.get("S33", ""),
            "scale": m.get("ScaleCat", ""),
            "date": price.get("Date", used_date),
            "open":  price.get("AdjO") or price.get("O"),
            "high":  price.get("AdjH") or price.get("H"),
            "low":   price.get("AdjL") or price.get("L"),
            "close": close,
            "volume": volume,
            "turnover": turnover,
            "change_amount": round(change_amount, 1),
            "change_rate": round(change_rate, 2),
        }

    def screen_stocks(self, filters: Dict) -> List[Dict]:
        """
        銘柄スクリーニング

        filters:
            market, sector, price_min/max, volume_min,
            turnover_min, change_rate_min/max,
            sort_by, sort_desc, limit
        """
        master = self.get_master()
        if not master:
            logger.warning("マスターデータが取得できませんでした")
            return []

        master_dict = {item["Code"]: item for item in master}

        market_filter = filters.get("market", "")
        sector_filter = filters.get("sector", "")

        target_codes = []
        for item in master:
            mkt = item.get("MktNm", "")
            if market_filter and mkt != market_filter:
                continue
            if sector_filter and item.get("S33", "") != sector_filter:
                continue
            if mkt == "TOKYO PRO MARKET":
                continue
            target_codes.append(item["Code"])

        logger.info(f"スクリーニング対象: {len(target_codes)}銘柄")

        used_date, prices_data = self._find_latest_trading_date()
        if not prices_data:
            logger.warning("株価データが取得できませんでした")
            return []

        price_dict = {p["Code"]: p for p in prices_data}
        prev_data = self._find_prev_trading_date(used_date)
        prev_dict = {p["Code"]: p for p in prev_data}

        price_min     = filters.get("price_min")
        price_max     = filters.get("price_max")
        volume_min    = filters.get("volume_min")
        turnover_min  = filters.get("turnover_min")
        cr_min        = filters.get("change_rate_min")
        cr_max        = filters.get("change_rate_max")

        results = []
        for code in target_codes:
            if code not in price_dict:
                continue

            row = self._build_result(code, price_dict[code], prev_dict.get(code), master_dict, used_date)
            if row is None:
                continue

            if price_min   is not None and row["close"]       < price_min:   continue
            if price_max   is not None and row["close"]       > price_max:   continue
            if volume_min  is not None and row["volume"]      < volume_min:  continue
            if turnover_min is not None and row["turnover"]   < turnover_min: continue
            if cr_min      is not None and row["change_rate"] < cr_min:      continue
            if cr_max      is not None and row["change_rate"] > cr_max:      continue

            results.append(row)

        sort_by   = filters.get("sort_by", "turnover")
        sort_desc = filters.get("sort_desc", True)

        if sort_by in ["close", "volume", "turnover", "change_rate", "change_amount"]:
            results.sort(key=lambda x: x.get(sort_by) or 0, reverse=sort_desc)
        elif sort_by == "name":
            results.sort(key=lambda x: x.get("name", ""), reverse=sort_desc)

        limit = filters.get("limit", 100)
        return results[:limit]

    # ========== 今買うべき銘柄 ==========

    def get_top_picks(self, n: int = 10) -> List[Dict]:
        """
        買いシグナルの強い銘柄トップN

        スコアリング:
          - 上昇率（前日比）: 0-15% レンジで正規化 × 0.45
          - 流動性（売買代金）: log スケール正規化 × 0.55
          - 上昇率 > 15% はオーバーエクステンデッド扱いでペナルティ
        """
        master = self.get_master()
        if not master:
            return []

        master_dict = {item["Code"]: item for item in master}

        # TOKYO PRO MARKET 除外
        target_codes = [
            item["Code"] for item in master
            if item.get("MktNm") != "TOKYO PRO MARKET"
        ]

        used_date, prices_data = self._find_latest_trading_date()
        if not prices_data:
            return []

        price_dict = {p["Code"]: p for p in prices_data}
        prev_data  = self._find_prev_trading_date(used_date)
        prev_dict  = {p["Code"]: p for p in prev_data}

        candidates = []
        for code in target_codes:
            if code not in price_dict:
                continue
            row = self._build_result(code, price_dict[code], prev_dict.get(code), master_dict, used_date)
            if row is None:
                continue
            # 最低流動性フィルター（売買代金 1億円以上、前日比プラス）
            if row["turnover"] < 100_000_000:
                continue
            if row["change_rate"] <= 0:
                continue
            candidates.append(row)

        if not candidates:
            return []

        # スコアリング
        max_va = max(s["turnover"] for s in candidates) or 1
        min_va = min(s["turnover"] for s in candidates) or 1

        for s in candidates:
            cr = s["change_rate"]
            # 上昇率スコア: 0〜15%を0〜1、15%超はペナルティ
            if cr <= 15:
                cr_score = cr / 15
            else:
                cr_score = 1.0 - (cr - 15) / 30  # 超騰は減点

            # 流動性スコア: log スケール
            va_score = (math.log10(max(s["turnover"], 1)) - math.log10(min_va)) / \
                       (math.log10(max_va) - math.log10(min_va) + 1e-9)

            s["_score"] = cr_score * 0.45 + va_score * 0.55

        candidates.sort(key=lambda x: x["_score"], reverse=True)
        picks = candidates[:n]

        # タグ付け
        for s in picks:
            tags = []
            cr = s["change_rate"]
            va = s["turnover"]
            mkt = s["market"]
            if cr >= 10:
                tags.append("急騰")
            elif cr >= 5:
                tags.append("上昇")
            else:
                tags.append("堅調")
            if va >= 10_000_000_000:
                tags.append("超大型")
            elif va >= 1_000_000_000:
                tags.append("大商い")
            elif va >= 500_000_000:
                tags.append("高流動性")
            if mkt == "グロース":
                tags.append("グロース")
            elif mkt == "プライム":
                tags.append("プライム")
            s["tags"] = tags

        return picks
