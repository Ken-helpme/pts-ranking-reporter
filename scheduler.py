"""
PTSランキングを毎日17:30に自動更新するスケジューラー
"""
import schedule
import time
import requests
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Dashboard URL
DASHBOARD_URL = "http://localhost:5001"


def fetch_pts_data():
    """PTSデータを取得"""
    try:
        logger.info(f"[{datetime.now()}] Starting PTS data fetch...")

        # ダッシュボードのAPIを呼び出し
        response = requests.get(f"{DASHBOARD_URL}/api/fetch", timeout=300)  # 5分タイムアウト

        if response.status_code == 200:
            result = response.json()
            if result.get('success'):
                logger.info(f"✓ Successfully fetched and saved {result.get('count', 0)} stocks")
            else:
                logger.error(f"✗ API returned error: {result.get('error')}")
        else:
            logger.error(f"✗ HTTP error: {response.status_code}")

    except Exception as e:
        logger.error(f"✗ Error fetching PTS data: {e}")


def run_scheduler():
    """スケジューラーを起動"""
    logger.info("=== PTS Ranking Scheduler Started ===")
    logger.info("Schedule: Every day at 17:30")
    logger.info("========================================\n")

    # 毎日17:30に実行
    schedule.every().day.at("17:30").do(fetch_pts_data)

    # テスト用：今すぐ実行（コメントアウト可能）
    # logger.info("Running immediate test fetch...")
    # fetch_pts_data()

    # スケジュールループ
    while True:
        schedule.run_pending()
        time.sleep(60)  # 1分ごとにチェック


if __name__ == '__main__':
    print("🕐 PTSランキング自動更新スケジューラー")
    print("   毎日17:30にデータを自動取得します")
    print("   停止するには Ctrl+C を押してください\n")

    try:
        run_scheduler()
    except KeyboardInterrupt:
        print("\n\n⏹  スケジューラーを停止しました")
