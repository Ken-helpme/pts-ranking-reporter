"""
PTS Ranking Dashboard - Flask Web Application
モダンなデザインでPTSランキングを表示・管理
"""
from flask import Flask, render_template, jsonify, request
from datetime import datetime, timedelta
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from models import init_db, save_pts_data, get_latest_ranking, get_historical_data, get_statistics
from scraper import KabutanScraper
from analyzer import PTSAnalyzer
from news_fetcher import NewsFetcher

app = Flask(__name__)
app.config['SECRET_KEY'] = 'pts-ranking-dashboard-secret-key'

# Initialize database
init_db()

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
        # Scrape PTS ranking
        scraper = KabutanScraper()
        analyzer = PTSAnalyzer(min_volume=10000, top_n=20)
        news_fetcher = NewsFetcher(max_news=3)

        stocks = scraper.fetch_pts_ranking()

        if not stocks:
            return jsonify({
                'success': False,
                'error': 'Failed to fetch PTS ranking'
            }), 500

        filtered_stocks = analyzer.filter_and_rank(stocks)

        # Save to database
        saved_count = 0
        for stock in filtered_stocks:
            code = stock['code']

            # Fetch additional info
            news = news_fetcher.fetch_stock_news(code)
            company = news_fetcher.get_company_info(code) or {}

            # Save to DB
            save_pts_data(stock, news, company)
            saved_count += 1

        # Cleanup
        scraper.close()
        news_fetcher.close()

        return jsonify({
            'success': True,
            'message': f'Successfully fetched and saved {saved_count} stocks',
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

        return jsonify({
            'success': True,
            'data': data
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/stats')
def get_stats():
    """統計情報を取得"""
    try:
        stats = get_statistics()
        return jsonify({
            'success': True,
            'data': stats
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/stock/<code>')
def get_stock_detail(code):
    """特定銘柄の詳細情報を取得"""
    try:
        data = get_historical_data(days=30, stock_code=code)
        return jsonify({
            'success': True,
            'data': data
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

if __name__ == '__main__':
    print("=" * 60)
    print("🚀 PTS Ranking Dashboard Starting...")
    print("=" * 60)
    print("\n📊 Dashboard URL: http://localhost:5000")
    print("💡 Press Ctrl+C to stop\n")

    app.run(debug=True, host='0.0.0.0', port=5000)
