"""각 Streamlit 페이지가 예외 없이 실행되는지 스모크 테스트."""
import os

import pytest

from streamlit.testing.v1 import AppTest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES = [
    "app.py",
    "pages/1_📥_데이터_업로드.py",
    "pages/2_📈_판매_흐름.py",
    "pages/3_🔁_반품_분석.py",
    "pages/4_🚦_상품_상태_알림.py",
    "pages/5_⚙️_설정.py",
]


@pytest.mark.parametrize("page", PAGES)
def test_page_runs(page):
    at = AppTest.from_file(os.path.join(ROOT, page), default_timeout=30)
    at.run()
    assert not at.exception, f"{page} 에서 예외 발생"
