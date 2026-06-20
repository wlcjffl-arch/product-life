"""모든 페이지가 함께 쓰는 사이드바 필터(판매처 + 날짜범위).

kind 로 '판매흐름용/반품용/전체용'을 구분합니다. 각 데이터의 실제 기간에 맞춰
기본값·달력 범위가 정해지고, '전체 기간 보기'가 기본 켜져 있어 처음부터 데이터가 보입니다.
"""
import datetime as dt

import streamlit as st

from . import db

_LABEL = {"sales": "📦 판매 데이터", "returns": "🔁 반품 데이터", "all": "📊 전체 데이터"}

_CSS = """
<style>
.block-container {padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1240px;}
footer {visibility: hidden;}
[data-testid="stMetric"] {
  background: linear-gradient(180deg, #FAFAFE 0%, #F3F3FB 100%);
  border: 1px solid #ECECF6;
  border-radius: 14px;
  padding: 14px 18px;
  box-shadow: 0 1px 3px rgba(20, 20, 60, 0.04);
}
[data-testid="stMetricLabel"] p {font-size: 0.85rem; opacity: 0.6;}
[data-testid="stMetricValue"] {font-weight: 700;}
h1 {font-weight: 800; letter-spacing: -0.6px;}
h2, h3 {font-weight: 700; letter-spacing: -0.3px;}
.stButton > button, .stDownloadButton > button {
  border-radius: 10px; font-weight: 600; border: 1px solid #E3E3EF;
}
[data-testid="stSidebar"] {border-right: 1px solid #EEEEF4;}
div[data-testid="stDataFrame"] {border-radius: 12px; overflow: hidden; border: 1px solid #ECECF4;}
[data-testid="stExpander"] {border-radius: 12px; border: 1px solid #ECECF4;}
hr {margin: 1.1rem 0;}
</style>
"""


def setup_page(title, icon):
    """모든 페이지 공통: 페이지 설정 + 디자인 적용. (Streamlit 첫 호출이어야 함)"""
    st.set_page_config(page_title=title, page_icon=icon, layout="wide")
    st.markdown(_CSS, unsafe_allow_html=True)


def sidebar_filters(kind="all"):
    db.init_db()
    st.sidebar.header("🔎 조회 조건")

    channels = ["전체"] + db.list_channels()
    channel = st.sidebar.selectbox("판매처", channels, key="flt_channel")

    label = _LABEL.get(kind, "데이터")
    lo, hi = db.date_bounds(kind)
    if not lo:
        st.sidebar.caption(f"{label}: 아직 없음")
        return channel, None, None

    st.sidebar.caption(f"{label} 보유 기간\n\n**{lo} ~ {hi}**")
    show_all = st.sidebar.checkbox("전체 기간 보기", value=True, key=f"flt_all_{kind}")
    if show_all:
        return channel, lo, hi

    lo_d, hi_d = dt.date.fromisoformat(lo), dt.date.fromisoformat(hi)
    rng = st.sidebar.date_input(
        "날짜 범위", value=(lo_d, hi_d), min_value=lo_d, max_value=hi_d,
        key=f"flt_dates_{kind}",
        help="이 데이터가 들어 있는 기간 안에서만 고를 수 있습니다.")
    if isinstance(rng, (tuple, list)) and len(rng) == 2:
        start, end = rng
    else:
        start, end = lo_d, hi_d
    return channel, str(start), str(end)
