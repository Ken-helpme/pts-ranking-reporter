"""
PTS ランキング ダッシュボード - Flask ウェブアプリケーション
モダンなデザインでPTSランキングを表示・管理
"""
from flask import Flask, render_template, jsonify, request
from datetime import datetime, timedelta
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from models import init_db, save_pts_data, get_latest_ranking, get_historical_data, get_statistics, save_trending_stocks, get_trending_stocks, get_trending_dates
from trending_stock_fetcher import TrendingStockFetcher
from scraper import KabutanScraper
from analyzer import PTSAnalyzer
from news_fetcher import NewsFetcher
from stock_analyzer import StockAnalyzer
from disclosure_fetcher import DisclosureFetcher
from earnings_analyzer import EarningsAnalyzer
from pdf_analyzer import PDFAnalyzer
from stock_evaluator import StockEvaluator
from jquants_client import JQuantsClient

app = Flask(__name__)
app.config['SECRET_KEY'] = 'pts-ranking-dashboard-secret-key'

# Initialize database
init_db()

# Claude API Key
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')

# J-Quants APIクライアント
jquants = JQuantsClient()

@app.route('/')
def index():
    """メインダッシュボード"""
    return render_template('dashboard.html')

@app.route('/api/latest')
def get_latest():
    """最新のPTSランキングを取得"""
    try:
        data = get_latest_ranking()
        return jsonify({
            'success': True,
            'data': data,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/fetch')
def fetch_new_data():
    """新しいPTSデータをスクレイピングして保存"""
    try:
        api_key = os.getenv('ANTHROPIC_API_KEY')

        # Initialize all components
        scraper = KabutanScraper()
        analyzer = PTSAnalyzer(min_volume=100, top_n=20)
        news_fetcher = NewsFetcher(max_news=3)
        stock_analyzer = StockAnalyzer()
        disclosure_fetcher = DisclosureFetcher()
        earnings_analyzer = EarningsAnalyzer(api_key=api_key)
        pdf_analyzer = PDFAnalyzer()
        stock_evaluator = StockEvaluator()

        stocks = scraper.fetch_pts_ranking()

        if not stocks:
            return jsonify({
                'success': False,
                'error': 'PTSランキングの取得に失敗しました'
            }), 500

        filtered_stocks = analyzer.filter_and_rank(stocks)
        timestamp = datetime.now().isoformat()
        saved_count = 0

        for stock in filtered_stocks:
            code = stock['code']

            if not stock.get('name'):
                stock['name'] = scraper.fetch_stock_name(code)

            # ニュースと会社情報を取得
            news = news_fetcher.fetch_stock_news(code)
            company = news_fetcher.get_company_info(code) or {}

            # 開示情報を取得
            disclosure_info = disclosure_fetcher.fetch_disclosure_info(code)
            earnings_detail = None

            # 決算発表がある場合はPDF分析 + Claude API分析
            if disclosure_info.get('has_earnings'):
                disclosure_title = disclosure_info['disclosures'][0]['title'] if disclosure_info['disclosures'] else disclosure_info['earnings_summary']
                pdf_url = disclosure_info['disclosures'][0].get('pdf_url') if disclosure_info['disclosures'] else None

                # PDFがあればダウンロード＆テキスト抽出
                pdf_text = None
                if pdf_url:
                    pdf_text = pdf_analyzer.download_and_extract_pdf(pdf_url)

                # Claude APIで分析（PDFがあれば全文、なければタイトルのみ）
                if pdf_text and api_key:
                    earnings_detail = earnings_analyzer.analyze_with_pdf_text(pdf_text, stock)
                else:
                    earnings_detail = earnings_analyzer.analyze_earnings_detail(
                        disclosure_title, news, stock
                    )

                # 決算ニュースをリストの先頭に追加
                if earnings_detail and earnings_detail.get('earnings_reason'):
                    earnings_news = {
                        'title': f"【決算】{disclosure_info['earnings_summary']} - {earnings_detail['earnings_reason'][:80]}",
                        'date': disclosure_info['disclosures'][0]['date'] if disclosure_info['disclosures'] else '',
                        'url': disclosure_info['disclosures'][0]['url'] if disclosure_info['disclosures'] else '',
                        'source': '開示情報',
                        'has_pdf_analysis': pdf_text is not None
                    }
                    news.insert(0, earnings_news)

            # 上昇理由を分析
            analysis = stock_analyzer.analyze_price_increase_reason(news, stock)

            # 決算分析を追加
            if earnings_detail:
                analysis['earnings_detail'] = earnings_detail

            # 総合評価を算出
            evaluation = stock_evaluator.evaluate_stock(stock, company, analysis)
            analysis['evaluation'] = evaluation

            save_pts_data(stock, news, company, timestamp, analysis)
            saved_count += 1

        # Cleanup
        scraper.close()
        news_fetcher.close()
        disclosure_fetcher.close()

        return jsonify({
            'success': True,
            'message': f'{saved_count}銘柄のデータを取得・保存しました',
            'count': saved_count
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/history')
def get_history():
    """過去データを取得"""
    try:
        days = request.args.get('days', 7, type=int)
        code = request.args.get('code', None)
        data = get_historical_data(days=days, stock_code=code)
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/stats')
def get_stats():
    """統計情報を取得"""
    try:
        stats = get_statistics()
        return jsonify({'success': True, 'data': stats})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/stock/<code>')
def get_stock_detail(code):
    """特定銘柄の詳細情報を取得"""
    try:
        data = get_historical_data(days=30, stock_code=code)
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ========== 話題株ピックアップ ==========

@app.route('/trending')
def trending():
    """話題株ピックアップページ"""
    return render_template('trending.html')

@app.route('/api/trending/latest')
def get_trending_latest():
    """最新の話題株データを取得"""
    try:
        date = request.args.get('date', None)
        data = get_trending_stocks(date=date)
        return jsonify({
            'success': True,
            'data': data,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/trending/fetch')
def fetch_trending_data():
    """話題株データを新規取得・保存"""
    try:
        fetcher = TrendingStockFetcher()
        try:
            stocks = fetcher.fetch_trending_stocks()
            if not stocks:
                return jsonify({
                    'success': False,
                    'error': '話題株データの取得に失敗しました'
                }), 500

            # 保存
            fetch_date = datetime.now().strftime('%Y-%m-%d')
            save_trending_stocks(stocks, fetch_date)

            return jsonify({
                'success': True,
                'message': f'{len(stocks)}銘柄の話題株データを取得・保存しました',
                'count': len(stocks)
            })
        finally:
            fetcher.close()

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/trending/dates')
def get_trending_date_list():
    """話題株データがある日付リストを取得"""
    try:
        dates = get_trending_dates()
        return jsonify({'success': True, 'dates': dates})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ========== J-Quants PTSランキング ==========

@app.route('/api/jquants/ranking')
def jquants_ranking():
    """J-QuantsデータでPTSランキング（出来高上位）"""
    try:
        market = request.args.get('market', '')
        sort_by = request.args.get('sort', 'volume')
        limit = request.args.get('limit', 20, type=int)

        filters = {
            'market': market,
            'volume_min': 100000,
            'sort_by': sort_by,
            'sort_desc': True,
            'limit': limit,
        }
        results = jquants.screen_stocks(filters)

        return jsonify({
            'success': True,
            'data': results,
            'total': len(results),
            'source': 'J-Quants API'
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/jquants/stock/<code>')
def jquants_stock_detail(code):
    """J-Quantsで個別銘柄の詳細データ取得"""
    try:
        # マスター情報
        master = jquants.get_master(code + '0' if len(code) == 4 else code)
        # 株価データ（直近30日）
        from datetime import timedelta
        to_date = datetime.now().strftime('%Y-%m-%d')
        from_date = (datetime.now() - timedelta(days=40)).strftime('%Y-%m-%d')
        prices = jquants.get_prices(code + '0' if len(code) == 4 else code, from_date, to_date)
        # 決算サマリー
        fins = jquants.get_financial_summary(code + '0' if len(code) == 4 else code)

        return jsonify({
            'success': True,
            'master': master[0] if master else {},
            'prices': prices[-10:] if prices else [],  # 直近10日分
            'financials': fins[-2:] if fins else [],    # 直近2期分
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ========== 銘柄スクリーニング ==========

@app.route('/screening')
def screening_page():
    """銘柄スクリーニングページ"""
    return render_template('screening.html')

@app.route('/api/screening/sectors')
def screening_sectors():
    """業種一覧"""
    try:
        sectors = jquants.get_sectors()
        return jsonify({'success': True, 'sectors': sectors})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/screening/search', methods=['POST'])
def screening_search():
    """スクリーニング実行"""
    try:
        filters = request.get_json() or {}
        results = jquants.screen_stocks(filters)
        date = results[0]['date'] if results else ''
        return jsonify({
            'success': True,
            'results': results,
            'total': len(results),
            'date': date
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/screening/volume_breakout')
def screening_volume_breakout():
    """出来高急増×上昇トレンド銘柄"""
    try:
        days  = request.args.get('days', 10, type=int)
        top_n = request.args.get('n', 20, type=int)
        stocks = jquants.get_volume_breakout_stocks(days=days, top_n=top_n)
        date = stocks[0]['date'] if stocks else ''
        return jsonify({
            'success': True,
            'stocks': stocks,
            'total': len(stocks),
            'date': date,
            'days': days,
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/screening/top_picks')
def screening_top_picks():
    """今買うべき銘柄トップ10"""
    try:
        n = request.args.get('n', 10, type=int)
        picks = jquants.get_top_picks(n=n)
        date = picks[0]['date'] if picks else ''
        return jsonify({
            'success': True,
            'picks': picks,
            'total': len(picks),
            'date': date
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})

if __name__ == '__main__':
    if ANTHROPIC_API_KEY:
        print("✅ Claude API Key: 設定済み")
    else:
        print("⚠️  Claude API Key: 未設定（環境変数 ANTHROPIC_API_KEY を設定してください）")

    print("=" * 60)
    print("🚀 PTSランキング ダッシュボード 起動中...")
    print("=" * 60)
    print("\n📊 Dashboard URL: http://localhost:5001")
    print("💡 Press Ctrl+C to stop\n")

    app.run(debug=True, host='0.0.0.0', port=5001)
