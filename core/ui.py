"""모든 페이지가 함께 쓰는 사이드바 필터(판매처 + 날짜범위).

kind 로 '판매흐름용/반품용/전체용'을 구분합니다. 각 데이터의 실제 기간에 맞춰
기본값·달력 범위가 정해지고, '전체 기간 보기'가 기본 켜져 있어 처음부터 데이터가 보입니다.
"""
import datetime as dt
import os

import streamlit as st

from . import db

_LABEL = {"sales": "📦 판매 데이터", "returns": "🔁 반품 데이터", "all": "📊 전체 데이터"}
_ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")

_CSS = """
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css');
html, body, .stApp, [data-testid="stSidebar"], button, input, textarea, select, .stMarkdown {
  font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, 'Apple SD Gothic Neo', sans-serif !important;
}
.block-container {padding-top: 2rem; padding-bottom: 3rem; max-width: 1240px;}
footer {visibility: hidden;}

/* 글자 마우스로 긁어 복사 가능하게 */
[data-testid="stMarkdownContainer"], [data-testid="stMarkdownContainer"] *,
[data-testid="stHeading"], [data-testid="stHeading"] *,
[data-testid="stMetricValue"], [data-testid="stMetricLabel"],
[data-testid="stCaptionContainer"], table, th, td, .pl-hero, .pl-hero *, .pl-card, .pl-card * {
  -webkit-user-select: text !important;
  user-select: text !important;
}
h1 {font-weight: 800; letter-spacing: -0.8px;}
h2, h3 {font-weight: 700; letter-spacing: -0.4px;}

/* 숫자 지표 카드 */
[data-testid="stMetric"] {
  background: #fff;
  border: 1px solid #ECECF4;
  border-radius: 16px;
  padding: 16px 20px;
  box-shadow: 0 2px 10px rgba(30, 30, 80, 0.05);
}
[data-testid="stMetricLabel"] p {font-size: 0.85rem; opacity: 0.6; font-weight: 600;}
[data-testid="stMetricValue"] {font-weight: 800; color: #2A2A4A;}

/* 버튼 */
.stButton > button, .stDownloadButton > button {
  border-radius: 10px; font-weight: 700; border: 1px solid #E3E3EF;
}
.stButton > button[kind="primary"] {
  background: linear-gradient(135deg, #7C5CFC, #5B5BD6); border: none; color: #fff;
}

/* 사이드바 */
[data-testid="stSidebar"] {border-right: 1px solid #EEEEF4; background: #FAFAFE;}

/* 표·확장 영역 */
div[data-testid="stDataFrame"] {border-radius: 12px; overflow: hidden; border: 1px solid #ECECF4;}
[data-testid="stExpander"] {border-radius: 12px; border: 1px solid #ECECF4;}
hr {margin: 1.1rem 0;}

/* 홈 히어로 배너 */
.pl-hero {
  background: linear-gradient(135deg, #8B6CFF 0%, #6C5CE7 45%, #5145CC 100%);
  border-radius: 20px; padding: 30px 34px; margin-bottom: 22px; color: #fff;
  box-shadow: 0 12px 32px rgba(108, 92, 231, 0.28);
}
.pl-hero h2 {color: #fff; margin: 0; font-size: 1.9rem; font-weight: 800; letter-spacing: -0.8px;}
.pl-hero p {color: rgba(255,255,255,0.92); margin: 8px 0 0; font-size: 1.03rem;}

/* 홈 카드 그리드 */
.pl-cards {display: flex; gap: 14px; flex-wrap: wrap; margin-top: 6px;}
.pl-card {
  flex: 1 1 150px; background: #fff; border: 1px solid #ECECF4; border-radius: 16px;
  padding: 18px 16px; box-shadow: 0 2px 10px rgba(30, 30, 80, 0.05);
  transition: transform .15s ease, box-shadow .15s ease, border-color .15s ease;
}
.pl-card:hover {transform: translateY(-4px); box-shadow: 0 12px 26px rgba(108,92,231,0.16); border-color: #D9D2FF;}
.pl-ico {
  width: 46px; height: 46px; border-radius: 13px; display: flex;
  align-items: center; justify-content: center; font-size: 23px; margin-bottom: 12px;
  background: linear-gradient(135deg, #EFEBFF, #E3DCFF);
}
.pl-card .t {font-weight: 800; font-size: 1rem; color: #2A2A4A;}
.pl-card .d {font-size: 0.82rem; color: #8A8AA3; margin-top: 4px; line-height: 1.45;}
</style>
"""


def setup_page(title, icon):
    """모든 페이지 공통: 페이지 설정 + 디자인 적용. (Streamlit 첫 호출이어야 함)"""
    st.set_page_config(page_title=title, page_icon=icon, layout="wide")
    try:
        st.logo(os.path.join(_ASSETS, "logo.svg"),
                icon_image=os.path.join(_ASSETS, "icon.svg"), size="large")
    except Exception:
        pass
    st.markdown(_CSS, unsafe_allow_html=True)


# ─── 세션 캐시: 같은 조건의 DB 조회 결과를 세션 동안 기억(속도 개선) ───

def ensure_db():
    """테이블 생성(init)은 세션당 한 번만."""
    if not st.session_state.get("_db_ready"):
        db.init_db()
        st.session_state["_db_ready"] = True


def cached(key, loader):
    """key가 처음이면 loader()를 호출해 저장, 이후엔 저장된 값 반환."""
    cache = st.session_state.setdefault("_dcache", {})
    if key not in cache:
        cache[key] = loader()
    return cache[key]


def clear_cache():
    """업로드·설정 저장 후 호출 — 캐시 비우기."""
    st.session_state["_dcache"] = {}


def sidebar_filters(kind="all"):
    ensure_db()
    st.sidebar.header("🔎 조회 조건")

    channels = ["전체"] + cached(("channels",), db.list_channels)
    channel = st.sidebar.selectbox("판매처", channels, key="flt_channel")

    label = _LABEL.get(kind, "데이터")
    lo, hi = cached(("bounds", kind), lambda: db.date_bounds(kind))
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
