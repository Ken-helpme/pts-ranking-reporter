"""
株式の総合評価システム
PER, PBR, 上昇率, 決算分析などから総合評価（SS, S, A, B, C）を算出
"""
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)


class StockEvaluator:
    """株式評価クラス"""

    def __init__(self):
        pass

    def evaluate_stock(
        self,
        stock_info: Dict,
        company_info: Dict,
        analysis: Dict
    ) -> Dict[str, any]:
        """
        株式を総合評価

        Args:
            stock_info: 株価情報（code, name, change_rate, etc.）
            company_info: 企業情報（PER, PBR, etc.）
            analysis: 分析情報（main_reason, earnings_detail, etc.）

        Returns:
            Dict: 評価結果
                - overall_rating: 総合評価 (SS, S, A, B, C)
                - score: スコア (0-100)
                - per_rating: PER評価
                - pbr_rating: PBR評価
                - growth_rating: 成長性評価
                - earnings_rating: 決算評価
                - details: 評価詳細
        """
        scores = []
        details = []

        # 1. PER評価 (20点満点)
        per_score, per_rating, per_detail = self._evaluate_per(company_info.get('per', ''))
        scores.append(per_score)
        details.append(per_detail)

        # 2. PBR評価 (15点満点)
        pbr_score, pbr_rating, pbr_detail = self._evaluate_pbr(company_info.get('pbr', ''))
        scores.append(pbr_score)
        details.append(pbr_detail)

        # 3. 上昇率評価 (25点満点)
        growth_score, growth_rating, growth_detail = self._evaluate_growth(
            stock_info.get('change_rate', 0)
        )
        scores.append(growth_score)
        details.append(growth_detail)

        # 4. 決算分析評価 (30点満点)
        earnings_score, earnings_rating, earnings_detail = self._evaluate_earnings(
            analysis.get('earnings_detail')
        )
        scores.append(earnings_score)
        details.append(earnings_detail)

        # 5. 配当・ROE評価 (10点満点)
        fundamental_score, fundamental_detail = self._evaluate_fundamentals(
            company_info.get('dividend_yield', ''),
            company_info.get('roe', '')
        )
        scores.append(fundamental_score)
        details.append(fundamental_detail)

        # 総合スコア算出
        total_score = sum(scores)

        # 総合評価を決定
        overall_rating = self._get_overall_rating(total_score)

        return {
            'overall_rating': overall_rating,
            'score': round(total_score, 1),
            'per_rating': per_rating,
            'pbr_rating': pbr_rating,
            'growth_rating': growth_rating,
            'earnings_rating': earnings_rating,
            'details': details,
            'breakdown': {
                'per_score': per_score,
                'pbr_score': pbr_score,
                'growth_score': growth_score,
                'earnings_score': earnings_score,
                'fundamental_score': fundamental_score
            }
        }

    def _evaluate_per(self, per_str: str) -> tuple:
        """PER評価 (20点満点)"""
        try:
            if not per_str or per_str == '-' or per_str == '---':
                return 10, 'C', 'PER: データなし'

            per = float(per_str.replace(',', ''))

            if per < 0:
                return 5, 'D', f'PER: {per:.1f}倍（赤字）'
            elif per < 10:
                return 20, 'SS', f'PER: {per:.1f}倍（超割安）'
            elif per < 15:
                return 18, 'S', f'PER: {per:.1f}倍（割安）'
            elif per < 20:
                return 15, 'A', f'PER: {per:.1f}倍（適正）'
            elif per < 30:
                return 12, 'B', f'PER: {per:.1f}倍（やや割高）'
            else:
                return 8, 'C', f'PER: {per:.1f}倍（割高）'

        except (ValueError, AttributeError):
            return 10, 'C', 'PER: 評価不可'

    def _evaluate_pbr(self, pbr_str: str) -> tuple:
        """PBR評価 (15点満点)"""
        try:
            if not pbr_str or pbr_str == '-' or pbr_str == '---':
                return 7, 'C', 'PBR: データなし'

            pbr = float(pbr_str.replace(',', ''))

            if pbr < 0:
                return 3, 'D', f'PBR: {pbr:.2f}倍（債務超過）'
            elif pbr < 0.5:
                return 15, 'SS', f'PBR: {pbr:.2f}倍（超割安）'
            elif pbr < 1.0:
                return 14, 'S', f'PBR: {pbr:.2f}倍（割安）'
            elif pbr < 1.5:
                return 12, 'A', f'PBR: {pbr:.2f}倍（適正）'
            elif pbr < 2.5:
                return 10, 'B', f'PBR: {pbr:.2f}倍（やや割高）'
            else:
                return 7, 'C', f'PBR: {pbr:.2f}倍（割高）'

        except (ValueError, AttributeError):
            return 7, 'C', 'PBR: 評価不可'

    def _evaluate_growth(self, change_rate: float) -> tuple:
        """上昇率評価 (25点満点)"""
        if change_rate >= 30:
            return 25, 'SS', f'上昇率: +{change_rate:.1f}%（急騰）'
        elif change_rate >= 20:
            return 23, 'S', f'上昇率: +{change_rate:.1f}%（大幅高）'
        elif change_rate >= 15:
            return 20, 'A', f'上昇率: +{change_rate:.1f}%（高騰）'
        elif change_rate >= 10:
            return 17, 'B', f'上昇率: +{change_rate:.1f}%（上昇）'
        elif change_rate >= 5:
            return 13, 'C', f'上昇率: +{change_rate:.1f}%（小幅高）'
        else:
            return 8, 'D', f'上昇率: +{change_rate:.1f}%（微増）'

    def _evaluate_earnings(self, earnings_detail: Optional[Dict]) -> tuple:
        """決算分析評価 (30点満点)"""
        if not earnings_detail:
            return 15, 'C', '決算分析: なし'

        score = 15  # ベーススコア
        rating_points = []

        # earnings_reasonの長さと内容
        earnings_reason = earnings_detail.get('earnings_reason', '')
        if len(earnings_reason) > 100:
            score += 7
            rating_points.append('詳細な分析')
        elif len(earnings_reason) > 50:
            score += 5
            rating_points.append('中程度の分析')
        elif earnings_reason:
            score += 3
            rating_points.append('簡易分析')

        # key_factorsの数
        key_factors = earnings_detail.get('key_factors', [])
        if len(key_factors) >= 3:
            score += 5
            rating_points.append(f'{len(key_factors)}個の要因')
        elif len(key_factors) >= 1:
            score += 3
            rating_points.append(f'{len(key_factors)}個の要因')

        # outlookの有無
        outlook = earnings_detail.get('outlook', '')
        if len(outlook) > 50:
            score += 3
            rating_points.append('見通しあり')

        # キーワード分析（ポジティブワード）
        positive_keywords = ['増益', '好調', '上方修正', '拡大', '成長', '最高', '急増']
        negative_keywords = ['減益', '下方修正', '減少', '悪化', '不振']

        text = earnings_reason + ' '.join(key_factors) + outlook
        positive_count = sum(1 for kw in positive_keywords if kw in text)
        negative_count = sum(1 for kw in negative_keywords if kw in text)

        if positive_count >= 2:
            score += 5
            rating_points.append('好材料多数')
        elif positive_count >= 1:
            score += 3

        if negative_count >= 2:
            score -= 3
            rating_points.append('懸念材料あり')

        # レーティング判定
        if score >= 28:
            rating = 'SS'
        elif score >= 25:
            rating = 'S'
        elif score >= 20:
            rating = 'A'
        elif score >= 15:
            rating = 'B'
        else:
            rating = 'C'

        detail = f"決算分析: {rating} ({', '.join(rating_points) if rating_points else '基本情報のみ'})"

        return score, rating, detail

    def _evaluate_fundamentals(self, dividend_yield_str: str, roe_str: str) -> tuple:
        """配当・ROE評価 (10点満点)"""
        score = 0
        details = []

        # 配当利回り評価
        try:
            if dividend_yield_str and dividend_yield_str not in ['-', '---']:
                div_yield = float(dividend_yield_str.replace(',', ''))
                if div_yield >= 4.0:
                    score += 5
                    details.append(f'高配当{div_yield:.1f}%')
                elif div_yield >= 2.5:
                    score += 4
                    details.append(f'配当{div_yield:.1f}%')
                elif div_yield >= 1.0:
                    score += 3
                    details.append(f'配当{div_yield:.1f}%')
                else:
                    score += 1
        except (ValueError, AttributeError):
            pass

        # ROE評価
        try:
            if roe_str and roe_str not in ['-', '---']:
                roe = float(roe_str.replace(',', ''))
                if roe >= 15:
                    score += 5
                    details.append(f'高ROE{roe:.1f}%')
                elif roe >= 10:
                    score += 4
                    details.append(f'ROE{roe:.1f}%')
                elif roe >= 5:
                    score += 3
                    details.append(f'ROE{roe:.1f}%')
                else:
                    score += 1
        except (ValueError, AttributeError):
            pass

        if not details:
            details.append('配当・ROEデータなし')
            score = 5  # デフォルトスコア

        return score, '財務: ' + ', '.join(details)

    def _get_overall_rating(self, score: float) -> str:
        """総合評価を決定"""
        if score >= 85:
            return 'SS'
        elif score >= 70:
            return 'S'
        elif score >= 55:
            return 'A'
        elif score >= 40:
            return 'B'
        else:
            return 'C'


if __name__ == '__main__':
    # テスト
    evaluator = StockEvaluator()

    # テストデータ
    stock_info = {
        'code': '7203',
        'name': 'トヨタ自動車',
        'change_rate': 25.5
    }

    company_info = {
        'per': '12.5',
        'pbr': '0.85',
        'dividend_yield': '3.2',
        'roe': '14.5'
    }

    analysis = {
        'earnings_detail': {
            'earnings_reason': '営業利益が前年同期比30%増加し、過去最高益を更新。主力の半導体事業が好調で、AIチップの需要が急拡大している。',
            'key_factors': [
                'AI向け半導体の需要急増',
                '生産効率の改善によるコスト削減',
                '為替の円安効果'
            ],
            'outlook': '今後も半導体需要は堅調に推移する見込み。次世代製品の投入により、さらなる成長が期待される。'
        }
    }

    result = evaluator.evaluate_stock(stock_info, company_info, analysis)

    print('\n=== 総合評価結果 ===')
    print(f"総合評価: {result['overall_rating']}")
    print(f"総合スコア: {result['score']}/100")
    print(f"\n詳細:")
    for detail in result['details']:
        print(f"  - {detail}")
