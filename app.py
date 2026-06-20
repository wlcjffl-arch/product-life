"""상품 판매·반품 분석 대시보드 — 홈."""
import streamlit as st

from core import db

st.set_page_config(page_title="상품 판매·반품 분석", page_icon="📊", layout="wide")
db.init_db()

st.title("📊 상품 판매·반품 분석 대시보드")

lo, hi = db.date_bounds()
channels = db.list_channels()

c1, c2, c3 = st.columns(3)
c1.metric("등록된 판매처", f"{len(channels)} 곳")
c2.metric("데이터 시작일", lo or "—")
c3.metric("데이터 마지막일", hi or "—")

st.markdown(
    """
### 사용 순서
1. **📥 데이터 업로드** — 판매 분석 파일(판매처 선택)과 반품 파일을 올립니다.
   매번 올려도 같은 날짜·주문은 자동으로 덮어써져 **중복 없이 누적**됩니다.
2. **📈 판매 흐름** — 날짜별 판매량 그래프, 급등/급감을 봅니다.
3. **🔁 반품 분석** — 어떤 상품·옵션이 무슨 사유로 반품됐는지 봅니다.
4. **🚦 상품 상태 / 알림** — 반품율 높음·재고부족·무판매 등 위험 신호를 한 표로 봅니다.
5. **⚙️ 설정** — 판단 기준과 상품별 입고기간(리드타임)·최소재고를 정합니다.

> 왼쪽 사이드바에서 **판매처**와 **날짜 범위**를 고르면 모든 페이지에 함께 적용됩니다.
"""
)

if not channels:
    st.info("아직 데이터가 없습니다. 왼쪽 메뉴의 **📥 데이터 업로드**부터 시작하세요.")
