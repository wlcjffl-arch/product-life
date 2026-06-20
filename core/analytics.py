"""
저장된 데이터로 분석 지표를 계산합니다. (규칙기반, 외부 API 없음)

- 일자별 판매 흐름 + 급등/급감 감지
- 반품율 (상품별 / 옵션별)
- 재고 있는데 N일 무판매
- 재고부족 (판매속도×입고기간 / 최소재고)
- 판매 적고 반품율 높은 상품
"""
import pandas as pd

from . import config
from .ingest import normalize_option

SETTING_KEYS = {
    "return_rate_flag": "RETURN_RATE_FLAG",
    "no_sales_days": "NO_SALES_DAYS",
    "low_sales_qty": "LOW_SALES_QTY",
    "low_sales_return_rate": "LOW_SALES_RETURN_RATE",
    "spike_pct": "SPIKE_PCT",
    "drop_pct": "DROP_PCT",
    "min_base_qty": "MIN_BASE_QTY",
    "default_lead_time_days": "DEFAULT_LEAD_TIME_DAYS",
    "velocity_window_days": "VELOCITY_WINDOW_DAYS",
}


def resolve_settings(overrides=None):
    """config 기본값 + 저장된 설정 override 를 합친 dict."""
    overrides = overrides or {}
    out = {}
    for key, const in SETTING_KEYS.items():
        out[key] = overrides.get(key, getattr(config, const))
    return out


# ─────────────────────── 판매 흐름 + 급등/급감 ───────────────────────

def daily_series(sales_df):
    """일자별 총 판매수량 시계열."""
    if sales_df.empty:
        return pd.DataFrame(columns=["sale_date", "sold_qty", "inbound_qty"])
    s = (sales_df.groupby("sale_date", as_index=False)
                 .agg(sold_qty=("sold_qty", "sum"), inbound_qty=("inbound_qty", "sum"))
                 .sort_values("sale_date"))
    return s


def period_series(sales_df, period="일"):
    """일별/주별/월별 총 판매·입고 시계열. period='일'|'주'|'월'.
    'bucket' = 정렬·표시용 라벨(일=YYYY-MM-DD, 주=그 주 월요일, 월=YYYY-MM),
    'bucket_date' = 차트 가로축(시간)용 날짜. 빈 구간은 0으로 채워 끊김 없이 표시."""
    cols = ["bucket", "bucket_date", "sold_qty", "inbound_qty"]
    if sales_df.empty:
        return pd.DataFrame(columns=cols)
    df = sales_df.copy()
    d = pd.to_datetime(df["sale_date"], errors="coerce")
    if period == "주":
        df["bucket"] = (d - pd.to_timedelta(d.dt.weekday, unit="D")).dt.strftime("%Y-%m-%d")
    elif period == "월":
        df["bucket"] = d.dt.strftime("%Y-%m")
    else:
        df["bucket"] = d.dt.strftime("%Y-%m-%d")
    out = (df.dropna(subset=["bucket"])
             .groupby("bucket", as_index=False)
             .agg(sold_qty=("sold_qty", "sum"), inbound_qty=("inbound_qty", "sum")))
    if out.empty:
        return pd.DataFrame(columns=cols)

    # 빈 구간 채우기(연속 표시)
    if period == "월":
        idx = pd.period_range(out["bucket"].min(), out["bucket"].max(), freq="M").astype(str)
    else:
        step = "7D" if period == "주" else "D"
        idx = pd.date_range(out["bucket"].min(), out["bucket"].max(),
                            freq=step).strftime("%Y-%m-%d")
    out = (out.set_index("bucket").reindex(idx, fill_value=0)
              .rename_axis("bucket").reset_index())
    out["bucket_date"] = pd.to_datetime(out["bucket"] + ("-01" if period == "월" else ""))
    return out.sort_values("bucket").reset_index(drop=True)[cols]


def mark_spikes(series_df, settings=None, date_col="sale_date"):
    """시계열에 직전 구간 대비 변화율 + 급등(▲)/급감(▼) 표시."""
    s = resolve_settings(settings)
    df = series_df.copy().sort_values(date_col).reset_index(drop=True)
    if df.empty:
        df["pct_change"] = []
        df["flag"] = []
        return df
    prev = df["sold_qty"].shift(1)
    df["pct_change"] = (df["sold_qty"] - prev) / prev.replace(0, pd.NA)

    def flag(row, prev_q):
        # 판매 0인 날은 신호로 보지 않음(당일 미마감/데이터 미반영로 인한 오탐 방지).
        # 진짜로 0이 이어지는 경우는 '무판매' 알림이 따로 잡아줍니다.
        if row["sold_qty"] == 0:
            return ""
        if pd.isna(row["pct_change"]) or prev_q < s["min_base_qty"]:
            return ""
        if row["pct_change"] >= s["spike_pct"]:
            return "급등 ▲"
        if row["pct_change"] <= -s["drop_pct"]:
            return "급감 ▼"
        return ""

    df["flag"] = [flag(df.iloc[i], prev.iloc[i] if not pd.isna(prev.iloc[i]) else 0)
                  for i in range(len(df))]
    return df


# ─────────────────────────── 반품율 ───────────────────────────

def _sold_sum(sales_df, keys):
    if sales_df.empty:
        return pd.DataFrame(columns=keys + ["sold_qty", "product_name"])
    g = (sales_df.groupby(keys, as_index=False)
                 .agg(sold_qty=("sold_qty", "sum"), product_name=("product_name", "first")))
    return g


def _ret_sum(returns_df, keys):
    if returns_df.empty:
        return pd.DataFrame(columns=keys + ["ret_qty"])
    return returns_df.groupby(keys, as_index=False).agg(ret_qty=("qty", "sum"))


def return_rate_product(sales_df, returns_df, settings=None):
    """상품별(채널+상품코드) 반품율 표."""
    s = resolve_settings(settings)
    keys = ["channel", "product_code"]
    sold = _sold_sum(sales_df, keys)
    ret = _ret_sum(returns_df, keys)
    df = sold.merge(ret, on=keys, how="outer")
    df["sold_qty"] = df["sold_qty"].fillna(0).astype(int)
    df["ret_qty"] = df["ret_qty"].fillna(0).astype(int)
    df["return_rate"] = df.apply(
        lambda r: (r["ret_qty"] / r["sold_qty"]) if r["sold_qty"] > 0 else None, axis=1)
    df["high_return"] = df["return_rate"].apply(
        lambda x: x is not None and x >= s["return_rate_flag"])
    df["low_sales_high_return"] = df.apply(
        lambda r: (r["sold_qty"] <= s["low_sales_qty"] and r["return_rate"] is not None
                   and r["return_rate"] >= s["low_sales_return_rate"]), axis=1)
    return df.sort_values("return_rate", ascending=False, na_position="last")


def return_rate_option(sales_df, returns_df, settings=None):
    """옵션별 반품율 표 (옵션 표기 정규화로 판매↔반품 매칭, best-effort)."""
    s = resolve_settings(settings)
    sdf = sales_df.copy()
    rdf = returns_df.copy()
    if not sdf.empty:
        sdf["opt_key"] = sdf["option_name"].map(normalize_option)
    else:
        sdf["opt_key"] = []
    if not rdf.empty:
        rdf["opt_key"] = rdf["option_name"].map(normalize_option)
    else:
        rdf["opt_key"] = []
    keys = ["channel", "product_code", "opt_key"]
    sold = (sdf.groupby(keys, as_index=False)
               .agg(sold_qty=("sold_qty", "sum"),
                    product_name=("product_name", "first"),
                    option_name=("option_name", "first"))) if not sdf.empty \
        else pd.DataFrame(columns=keys + ["sold_qty", "product_name", "option_name"])
    ret = (rdf.groupby(keys, as_index=False)
              .agg(ret_qty=("qty", "sum"), option_name=("option_name", "first"))) \
        if not rdf.empty else pd.DataFrame(columns=keys + ["ret_qty", "option_name"])
    df = sold.merge(ret, on=keys, how="outer", suffixes=("", "_r"))
    df["option_name"] = df["option_name"].fillna(df.get("option_name_r"))
    df["sold_qty"] = df["sold_qty"].fillna(0).astype(int)
    df["ret_qty"] = df["ret_qty"].fillna(0).astype(int)
    df["return_rate"] = df.apply(
        lambda r: (r["ret_qty"] / r["sold_qty"]) if r["sold_qty"] > 0 else None, axis=1)
    df["high_return"] = df["return_rate"].apply(
        lambda x: x is not None and x >= s["return_rate_flag"])
    cols = ["channel", "product_code", "product_name", "option_name",
            "sold_qty", "ret_qty", "return_rate", "high_return"]
    return df[[c for c in cols if c in df.columns]].sort_values(
        "return_rate", ascending=False, na_position="last")


# ─────────────────── 무판매 / 재고부족 (재고 알림) ───────────────────

def _last_sold(sales_df):
    sold = sales_df[sales_df["sold_qty"] > 0]
    if sold.empty:
        return pd.DataFrame(columns=["channel", "product_code", "option_name", "last_sold"])
    return (sold.groupby(["channel", "product_code", "option_name"], as_index=False)
                .agg(last_sold=("sale_date", "max")))


def stock_alerts(sales_df, snapshot_df, restock_df, asof_date, settings=None):
    """재고 관련 알림 표(옵션 단위): 무판매·재고부족 플래그 포함."""
    s = resolve_settings(settings)
    asof = pd.to_datetime(asof_date)

    snap = snapshot_df.copy()
    if snap.empty:
        return pd.DataFrame()

    # 최근 판매속도 (최근 velocity_window_days 일)
    win_start = (asof - pd.Timedelta(days=s["velocity_window_days"])).strftime("%Y-%m-%d")
    recent = sales_df[sales_df["sale_date"] >= win_start]
    vel = (recent.groupby(["channel", "product_code", "option_name"], as_index=False)
                 .agg(recent_sold=("sold_qty", "sum"))) if not recent.empty \
        else pd.DataFrame(columns=["channel", "product_code", "option_name", "recent_sold"])
    last = _last_sold(sales_df)

    df = snap.merge(vel, on=["channel", "product_code", "option_name"], how="left")
    df = df.merge(last, on=["channel", "product_code", "option_name"], how="left")
    df["recent_sold"] = df["recent_sold"].fillna(0)
    df["avg_daily"] = df["recent_sold"] / s["velocity_window_days"]

    # 입고기간/최소재고
    if restock_df is None or restock_df.empty or "product_code" not in restock_df.columns:
        rs = pd.DataFrame(columns=["product_code", "lead_time_days", "min_stock"])
    else:
        rs = restock_df.copy()
    df = df.merge(rs, on="product_code", how="left")
    df["lead_time_days"] = (pd.to_numeric(df["lead_time_days"], errors="coerce")
                            .fillna(s["default_lead_time_days"]))

    df["need_qty"] = (df["avg_daily"] * df["lead_time_days"]).round(1)
    df["stock"] = df["stock"].fillna(0)

    df["days_since_sale"] = df["last_sold"].apply(
        lambda d: (asof - pd.to_datetime(d)).days if pd.notna(d) else None)

    df["no_sale_flag"] = df.apply(
        lambda r: r["stock"] > 0 and (
            r["days_since_sale"] is None or r["days_since_sale"] >= s["no_sales_days"]),
        axis=1)
    df["shortage_auto"] = df["need_qty"] > df["stock"]
    df["shortage_min"] = df.apply(
        lambda r: pd.notna(r.get("min_stock")) and r["stock"] < r["min_stock"], axis=1)
    df["shortage_flag"] = df["shortage_auto"] | df["shortage_min"]
    return df


# ─────────────────────── 통합 알림 (페이지4) ───────────────────────

def alert_overview(sales_df, returns_df, snapshot_df, restock_df, asof_date, settings=None):
    """상품 상태 알림 통합 표 (옵션 단위)."""
    rr = return_rate_option(sales_df, returns_df, settings)
    st = stock_alerts(sales_df, snapshot_df, restock_df, asof_date, settings)
    if st.empty:
        return pd.DataFrame()

    st = st.copy()
    st["opt_key"] = st["option_name"].map(normalize_option)
    rr = rr.copy()
    if not rr.empty:
        rr["opt_key"] = rr["option_name"].map(normalize_option)
        rr_small = rr[["channel", "product_code", "opt_key", "ret_qty",
                       "return_rate", "high_return"]]
    else:
        rr_small = pd.DataFrame(columns=["channel", "product_code", "opt_key",
                                         "ret_qty", "return_rate", "high_return"])

    df = st.merge(rr_small, on=["channel", "product_code", "opt_key"], how="left")
    df["ret_qty"] = df["ret_qty"].fillna(0).astype(int)
    s = resolve_settings(settings)

    sold_total = (sales_df.groupby(["channel", "product_code", "option_name"], as_index=False)
                          .agg(period_sold=("sold_qty", "sum"))) if not sales_df.empty \
        else pd.DataFrame(columns=["channel", "product_code", "option_name", "period_sold"])
    df = df.merge(sold_total, on=["channel", "product_code", "option_name"], how="left")
    df["period_sold"] = df["period_sold"].fillna(0).astype(int)

    df["low_sales_high_return"] = df.apply(
        lambda r: (r["period_sold"] <= s["low_sales_qty"]
                   and pd.notna(r["return_rate"])
                   and r["return_rate"] >= s["low_sales_return_rate"]), axis=1)

    def badges(r):
        b = []
        if r.get("high_return"):
            b.append("🔴반품율")
        if r.get("low_sales_high_return"):
            b.append("🟠저판매·고반품")
        if r.get("no_sale_flag"):
            b.append("🟡무판매")
        if r.get("shortage_flag"):
            b.append("🔵재고부족")
        return " ".join(b)

    df["알림"] = df.apply(badges, axis=1)
    cols = ["channel", "product_code", "product_name", "option_name", "category",
            "stock", "period_sold", "ret_qty", "return_rate", "days_since_sale",
            "lead_time_days", "need_qty", "알림",
            "high_return", "low_sales_high_return", "no_sale_flag", "shortage_flag"]
    df = df[[c for c in cols if c in df.columns]]
    return df.sort_values("알림", ascending=False)
