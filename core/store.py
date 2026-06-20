"""DB 읽기 캐싱 계층.

화면을 누를 때마다 DB를 다시 읽고 다시 계산하면 (특히 무료 서버에서) 느립니다.
같은 조건의 결과는 캐시에 기억해 두고, 데이터가 바뀌면(업로드·설정저장) clear()로 비웁니다.
"""
import streamlit as st

from . import db


@st.cache_resource(show_spinner=False)
def ready():
    """테이블 생성(init)은 프로세스당 한 번만."""
    db.init_db()
    return True


@st.cache_data(ttl=600, show_spinner=False)
def list_channels():
    return db.list_channels()


@st.cache_data(ttl=600, show_spinner=False)
def date_bounds(kind="all"):
    return db.date_bounds(kind)


@st.cache_data(ttl=600, show_spinner=False)
def load_sales(channel, start, end):
    return db.load_sales_daily(channel, start, end)


@st.cache_data(ttl=600, show_spinner=False)
def load_returns(channel, start, end):
    return db.load_returns(channel, start, end)


@st.cache_data(ttl=600, show_spinner=False)
def load_snapshot(channel):
    return db.load_snapshot(channel)


@st.cache_data(ttl=600, show_spinner=False)
def load_settings():
    return db.load_settings()


@st.cache_data(ttl=600, show_spinner=False)
def load_restock_settings():
    return db.load_restock_settings()


def clear():
    """데이터/설정이 바뀐 뒤 호출 — 캐시 비우기."""
    st.cache_data.clear()
