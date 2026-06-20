"""
저장소. 로컬에서는 SQLite 파일을, 클라우드(Supabase)에서는 Postgres를 사용합니다.

DATABASE_URL 환경변수 또는 Streamlit secrets 의 DATABASE_URL 이 있으면 그 DB를,
없으면 로컬 data/product_life.db (SQLite)를 씁니다. 같은 코드로 둘 다 동작.

핵심: UNIQUE 제약 + UPSERT(INSERT ... ON CONFLICT DO UPDATE) 로 날짜·주문번호 기준
중복 없이 누적됩니다. (SQLite·Postgres 모두 지원하는 문법)
"""
import json
import os

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
DB_PATH = os.path.join(DB_DIR, "product_life.db")

_ENGINES = {}


def _db_url():
    """사용할 DB 주소 결정. 환경변수 > Streamlit secrets > 로컬 SQLite."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        try:
            import streamlit as st
            url = st.secrets.get("DATABASE_URL")
        except Exception:
            url = None
    if url:
        url = str(url).strip()
        # Supabase/Heroku 형식 → SQLAlchemy(psycopg2) 형식으로 정규화
        if url.startswith("postgres://"):
            url = "postgresql+psycopg2://" + url[len("postgres://"):]
        elif url.startswith("postgresql://"):
            url = "postgresql+psycopg2://" + url[len("postgresql://"):]
        return url
    os.makedirs(DB_DIR, exist_ok=True)
    return f"sqlite:///{DB_PATH}"


def get_engine():
    url = _db_url()
    if url not in _ENGINES:
        if url.startswith("sqlite"):
            _ENGINES[url] = create_engine(url, connect_args={"check_same_thread": False})
        else:
            _ENGINES[url] = create_engine(url, pool_pre_ping=True)
    return _ENGINES[url]


SCHEMA = """
CREATE TABLE IF NOT EXISTS sales_daily (
    channel       TEXT NOT NULL,
    product_code  TEXT NOT NULL,
    product_name  TEXT,
    option_name   TEXT NOT NULL,
    sale_date     TEXT NOT NULL,
    sold_qty      INTEGER DEFAULT 0,
    inbound_qty   INTEGER DEFAULT 0,
    UNIQUE(channel, product_code, option_name, sale_date)
);
CREATE INDEX IF NOT EXISTS idx_sales_date ON sales_daily(sale_date);
CREATE INDEX IF NOT EXISTS idx_sales_chan ON sales_daily(channel);
CREATE TABLE IF NOT EXISTS product_snapshot (
    channel       TEXT NOT NULL,
    product_code  TEXT NOT NULL,
    option_name   TEXT NOT NULL,
    product_name  TEXT,
    buy_name      TEXT,
    category      TEXT,
    origin        TEXT,
    supplier      TEXT,
    supplier_tel  TEXT,
    reg_date      TEXT,
    cost          REAL,
    sale_price    REAL,
    amount        REAL,
    total_sold    INTEGER,
    total_inbound INTEGER,
    stock         INTEGER,
    unshipped     INTEGER,
    canceled      INTEGER,
    snapshot_date TEXT,
    UNIQUE(channel, product_code, option_name)
);
CREATE TABLE IF NOT EXISTS returns (
    channel       TEXT NOT NULL,
    product_code  TEXT NOT NULL,
    product_name  TEXT,
    option_name   TEXT NOT NULL,
    return_date   TEXT,
    qty           INTEGER DEFAULT 1,
    reason        TEXT,
    cs_type       TEXT,
    supplier      TEXT,
    amount        REAL,
    order_no      TEXT NOT NULL,
    UNIQUE(channel, order_no, product_code, option_name)
);
CREATE INDEX IF NOT EXISTS idx_ret_date ON returns(return_date);
CREATE INDEX IF NOT EXISTS idx_ret_chan ON returns(channel);
CREATE TABLE IF NOT EXISTS restock_settings (
    product_code   TEXT PRIMARY KEY,
    lead_time_days INTEGER,
    min_stock      INTEGER
);
CREATE TABLE IF NOT EXISTS column_maps (
    channel      TEXT NOT NULL,
    file_type    TEXT NOT NULL,
    mapping_json TEXT,
    PRIMARY KEY(channel, file_type)
);
CREATE TABLE IF NOT EXISTS app_settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def init_db():
    with get_engine().begin() as conn:
        for stmt in SCHEMA.split(";"):
            s = stmt.strip()
            if s:
                conn.execute(text(s))


# ─────────────────────────── 공통 ───────────────────────────

def _py(v):
    """numpy/NaN 값을 파이썬 기본형으로 (psycopg2 호환)."""
    if v is None:
        return None
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return None if np.isnan(v) else float(v)
    if isinstance(v, np.bool_):
        return bool(v)
    if isinstance(v, float) and pd.isna(v):
        return None
    return v


def _records(df, cols):
    return [{k: _py(v) for k, v in rec.items()} for rec in df[cols].to_dict("records")]


def _upsert(conn, table, df, key_cols, all_cols):
    """df 행들을 UPSERT. (추가건수, 갱신건수) 반환."""
    if df is None or df.empty:
        return 0, 0
    records = _records(df, all_cols)

    existing = set()
    for r in conn.execute(text(f"SELECT {', '.join(key_cols)} FROM {table}")):
        existing.add(tuple(r))

    inserted = updated = 0
    seen = set()
    for rec in records:
        key = tuple(rec[k] for k in key_cols)
        if key in existing or key in seen:
            updated += 1
        else:
            inserted += 1
        seen.add(key)

    binds = ", ".join(f":{c}" for c in all_cols)
    update_cols = [c for c in all_cols if c not in key_cols]
    set_clause = ", ".join(f"{c}=excluded.{c}" for c in update_cols)
    sql = (f"INSERT INTO {table} ({', '.join(all_cols)}) VALUES ({binds}) "
           f"ON CONFLICT ({', '.join(key_cols)}) DO UPDATE SET {set_clause}")
    conn.execute(text(sql), records)
    return inserted, updated


SALES_COLS = ["channel", "product_code", "product_name", "option_name",
              "sale_date", "sold_qty", "inbound_qty"]
SNAPSHOT_COLS = ["channel", "product_code", "option_name", "product_name", "buy_name",
                 "category", "origin", "supplier", "supplier_tel", "reg_date", "cost",
                 "sale_price", "amount", "total_sold", "total_inbound", "stock",
                 "unshipped", "canceled", "snapshot_date"]
RETURNS_COLS = ["channel", "product_code", "product_name", "option_name", "return_date",
                "qty", "reason", "cs_type", "supplier", "amount", "order_no"]


def upsert_sales_daily(df):
    with get_engine().begin() as conn:
        return _upsert(conn, "sales_daily", df,
                       ["channel", "product_code", "option_name", "sale_date"], SALES_COLS)


def save_snapshot(df):
    with get_engine().begin() as conn:
        return _upsert(conn, "product_snapshot", df,
                       ["channel", "product_code", "option_name"], SNAPSHOT_COLS)


def upsert_returns(df):
    with get_engine().begin() as conn:
        return _upsert(conn, "returns", df,
                       ["channel", "order_no", "product_code", "option_name"], RETURNS_COLS)


# ─────────────────────────── 조회 ───────────────────────────

def _read(q, params):
    with get_engine().connect() as conn:
        return pd.read_sql_query(text(q), conn, params=params)


def load_sales_daily(channel=None, start=None, end=None):
    q = "SELECT * FROM sales_daily WHERE 1=1"
    p = {}
    if channel and channel != "전체":
        q += " AND channel = :channel"; p["channel"] = channel
    if start:
        q += " AND sale_date >= :start"; p["start"] = str(start)
    if end:
        q += " AND sale_date <= :end"; p["end"] = str(end)
    return _read(q, p)


def load_returns(channel=None, start=None, end=None):
    q = "SELECT * FROM returns WHERE 1=1"
    p = {}
    if channel and channel != "전체":
        q += " AND channel = :channel"; p["channel"] = channel
    if start:
        q += " AND return_date >= :start"; p["start"] = str(start)
    if end:
        q += " AND return_date <= :end"; p["end"] = str(end)
    return _read(q, p)


def load_snapshot(channel=None):
    q = "SELECT * FROM product_snapshot WHERE 1=1"
    p = {}
    if channel and channel != "전체":
        q += " AND channel = :channel"; p["channel"] = channel
    return _read(q, p)


def list_channels():
    with get_engine().connect() as conn:
        rows = conn.execute(text(
            "SELECT channel FROM sales_daily UNION SELECT channel FROM returns")).fetchall()
    return sorted({r[0] for r in rows if r[0]})


def date_bounds(kind="all"):
    """저장된 데이터의 (최소날짜, 최대날짜). kind='sales'|'returns'|'all'."""
    if kind == "sales":
        q = "SELECT MIN(sale_date), MAX(sale_date) FROM sales_daily"
    elif kind == "returns":
        q = "SELECT MIN(return_date), MAX(return_date) FROM returns"
    else:
        q = ("SELECT MIN(d), MAX(d) FROM ("
             "  SELECT sale_date d FROM sales_daily "
             "  UNION ALL SELECT return_date d FROM returns) t WHERE d IS NOT NULL")
    with get_engine().connect() as conn:
        r = conn.execute(text(q)).fetchone()
    return (r[0], r[1]) if r else (None, None)


# ─────────────────────── 입고기간/최소재고 설정 ───────────────────────

def load_restock_settings():
    return _read("SELECT * FROM restock_settings", {})


def save_restock_settings(df):
    if df is None or df.empty:
        return
    records = _records(df, ["product_code", "lead_time_days", "min_stock"])
    sql = ("INSERT INTO restock_settings(product_code, lead_time_days, min_stock) "
           "VALUES (:product_code, :lead_time_days, :min_stock) "
           "ON CONFLICT (product_code) DO UPDATE SET "
           "lead_time_days=excluded.lead_time_days, min_stock=excluded.min_stock")
    with get_engine().begin() as conn:
        conn.execute(text(sql), records)


# ─────────────────────── 채널별 컬럼 매핑 기억 ───────────────────────

def load_column_map(channel, file_type):
    with get_engine().connect() as conn:
        r = conn.execute(text(
            "SELECT mapping_json FROM column_maps WHERE channel = :c AND file_type = :t"),
            {"c": channel, "t": file_type}).fetchone()
    return json.loads(r[0]) if r and r[0] else {}


def save_column_map(channel, file_type, mapping):
    sql = ("INSERT INTO column_maps(channel, file_type, mapping_json) "
           "VALUES (:c, :t, :m) "
           "ON CONFLICT (channel, file_type) DO UPDATE SET mapping_json=excluded.mapping_json")
    with get_engine().begin() as conn:
        conn.execute(text(sql), {"c": channel, "t": file_type,
                                 "m": json.dumps(mapping, ensure_ascii=False)})


# ─────────────────────── 분석 기준값(설정) 저장 ───────────────────────

def load_settings():
    with get_engine().connect() as conn:
        rows = conn.execute(text("SELECT key, value FROM app_settings")).fetchall()
    out = {}
    for k, v in rows:
        try:
            out[k] = json.loads(v)
        except (TypeError, ValueError):
            out[k] = v
    return out


def save_settings(settings: dict):
    records = [{"k": k, "v": json.dumps(v)} for k, v in settings.items()]
    if not records:
        return
    sql = ("INSERT INTO app_settings(key, value) VALUES (:k, :v) "
           "ON CONFLICT (key) DO UPDATE SET value=excluded.value")
    with get_engine().begin() as conn:
        conn.execute(text(sql), records)
