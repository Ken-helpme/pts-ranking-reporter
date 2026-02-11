"""
GCP Cloud Functions用ハンドラー
"""
import sys
import os
from flask import Request

# srcディレクトリをパスに追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from main import PTSReporter


def pts_reporter_handler(request: Request):
    """
    GCP Cloud Functions HTTPハンドラー

    Args:
        request: Flask Request オブジェクト

    Returns:
        tuple: (レスポンスメッセージ, HTTPステータスコード)
    """
    # 環境変数から設定を取得
    min_volume = int(os.getenv('MIN_VOLUME', '10000'))
    top_n = int(os.getenv('TOP_N', '10'))

    try:
        # レポーターを実行
        reporter = PTSReporter(min_volume=min_volume, top_n=top_n)
        success = reporter.run()

        if success:
            return ('PTS report sent successfully', 200)
        else:
            return ('Failed to send report', 500)

    except Exception as e:
        print(f"Error in pts_reporter_handler: {str(e)}")
        return (f'Error: {str(e)}', 500)
