"""
PDFから決算資料を読み込んで分析するモジュール
"""
import requests
import pdfplumber
import io
import logging
from typing import Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PDFAnalyzer:
    """PDFから決算資料のテキストを抽出するクラス"""

    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }

    def download_and_extract_pdf(self, pdf_url: str) -> Optional[str]:
        """
        PDFをダウンロードしてテキストを抽出

        Args:
            pdf_url: PDFのURL

        Returns:
            str: 抽出されたテキスト（最初の10ページまで）
        """
        try:
            logger.info(f"Downloading PDF: {pdf_url}")

            # PDFをダウンロード
            response = requests.get(pdf_url, headers=self.HEADERS, timeout=30)
            response.raise_for_status()

            # メモリ上でPDFを開く
            pdf_file = io.BytesIO(response.content)

            # pdfplumberでテキストを抽出
            text = ""
            page_count = 0
            max_pages = 10  # 最初の10ページのみ（決算短信の重要部分）

            with pdfplumber.open(pdf_file) as pdf:
                total_pages = len(pdf.pages)
                logger.info(f"PDF has {total_pages} pages, extracting first {min(max_pages, total_pages)} pages")

                for page_num, page in enumerate(pdf.pages[:max_pages], 1):
                    page_text = page.extract_text()
                    if page_text:
                        text += f"\n--- Page {page_num} ---\n"
                        text += page_text
                        page_count += 1

            logger.info(f"✓ Extracted text from {page_count} pages ({len(text)} characters)")
            return text

        except requests.RequestException as e:
            logger.error(f"Error downloading PDF: {e}")
            return None
        except Exception as e:
            logger.error(f"Error extracting PDF text: {e}")
            return None

    def extract_key_financials(self, pdf_text: str) -> dict:
        """
        PDFテキストから主要な財務数値を抽出

        Args:
            pdf_text: PDFから抽出したテキスト

        Returns:
            dict: 財務数値
                - revenue: 売上高
                - profit: 利益
                - forecast_change: 予想の変化
        """
        import re

        result = {
            'revenue': None,
            'profit': None,
            'forecast_change': None,
            'key_sentences': []
        }

        # 売上高を探す
        revenue_patterns = [
            r'売上高[：:\s]*([0-9,]+)\s*百万円',
            r'売上高[：:\s]*([0-9,]+)\s*億円',
            r'営業収益[：:\s]*([0-9,]+)',
        ]

        for pattern in revenue_patterns:
            match = re.search(pattern, pdf_text)
            if match:
                result['revenue'] = match.group(0)
                break

        # 利益を探す
        profit_patterns = [
            r'営業利益[：:\s]*([0-9,]+)\s*百万円',
            r'当期純利益[：:\s]*([0-9,]+)\s*百万円',
            r'経常利益[：:\s]*([0-9,]+)',
        ]

        for pattern in profit_patterns:
            match = re.search(pattern, pdf_text)
            if match:
                result['profit'] = match.group(0)
                break

        # 上方修正/下方修正の理由を探す
        reason_keywords = ['上方修正', '下方修正', '好調', '増加', '減少', '要因', '理由']
        lines = pdf_text.split('\n')

        for i, line in enumerate(lines):
            if any(keyword in line for keyword in reason_keywords):
                # 前後の行も含めて文脈を取得
                context_start = max(0, i - 1)
                context_end = min(len(lines), i + 2)
                context = ' '.join(lines[context_start:context_end]).strip()

                if len(context) > 20 and len(context) < 500:
                    result['key_sentences'].append(context)

                # 最大5つまで
                if len(result['key_sentences']) >= 5:
                    break

        return result


if __name__ == '__main__':
    # テスト
    analyzer = PDFAnalyzer()

    # テスト用PDF URL（実際の開示PDFを使用）
    test_url = "https://kabutan.jp/disclosures/pdf/20260209/140120260209552306.pdf"

    print("=== PDF分析テスト ===\n")
    text = analyzer.download_and_extract_pdf(test_url)

    if text:
        print(f"抽出したテキストの長さ: {len(text)} 文字\n")

        # 最初の500文字を表示
        print("=== テキストプレビュー ===")
        print(text[:500])
        print("...\n")

        # 主要な財務数値を抽出
        financials = analyzer.extract_key_financials(text)
        print("=== 主要な財務情報 ===")
        print(f"売上高: {financials['revenue']}")
        print(f"利益: {financials['profit']}")

        if financials['key_sentences']:
            print("\n=== 重要な記述 ===")
            for i, sentence in enumerate(financials['key_sentences'][:3], 1):
                print(f"{i}. {sentence[:200]}...")
    else:
        print("✗ PDF の取得・抽出に失敗しました")
