"""상품 판매·반품 분석 대시보드 — 홈."""
import streamlit as st

from core import db
from core.ui import setup_page

setup_page("상품 판매·반품 분석", "📊")
db.init_db()

st.markdown(
    '<div class="pl-hero">'
    '<h2>📊 상품 판매·반품 분석</h2>'
    '<p>판매 흐름 · 반품 · 재고를 한눈에 — 의류몰 운영을 위한 분석 대시보드</p>'
    '</div>',
    unsafe_allow_html=True,
)

lo, hi = db.date_bounds()
channels = db.list_channels()

c1, c2, c3 = st.columns(3)
c1.metric("🏬 등록된 판매처", f"{len(channels)} 곳")
c2.metric("📅 데이터 시작일", lo or "—")
c3.metric("📅 데이터 마지막일", hi or "—")

st.write("")
st.subheader("이렇게 쓰세요")

steps = [
    ("📥", "데이터 업로드", "판매·반품 파일 올리기 (중복 없이 누적)"),
    ("📈", "판매 흐름", "날짜별 판매량·급등/급감 그래프"),
    ("🔁", "반품 분석", "어떤 상품·옵션이 왜 반품됐는지"),
    ("🚦", "상품 상태/알림", "반품율↑·재고부족·무판매 한 표로"),
    ("⚙️", "설정", "판단 기준·입고기간 조정"),
]
cards = "".join(
    f'<div class="pl-card"><div class="pl-ico">{e}</div>'
    f'<div class="t">{t}</div><div class="d">{d}</div></div>'
    for e, t, d in steps
)
st.markdown(f'<div class="pl-cards">{cards}</div>', unsafe_allow_html=True)

st.write("")
st.info("💡 왼쪽 사이드바에서 **판매처**와 **날짜 범위**를 고르면 모든 페이지에 함께 적용됩니다.")

if not channels:
    st.warning("아직 데이터가 없습니다. 왼쪽 메뉴의 **📥 데이터 업로드**부터 시작하세요.")
