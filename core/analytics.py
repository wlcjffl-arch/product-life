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
    "reliable_sold_qty": "RELIABLE_SOLD_QTY",
    "new_product_days": "NEW_PRODUCT_DAYS",
    "discontinue_return_rate": "DISCONTINUE_RETURN_RATE",
    "keep_weekly_sold": "KEEP_WEEKLY_SOLD",
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
    """상품 상태 알림 통합 표 (옵션 단위). 판매 파일만으로 계산.

    반품수 = 판매 파일의 '취소수량', 반품율 = 취소수량 / 판매합계수량.
    (returns_df 는 사용하지 않음 — 반품 파일은 반품 분석 페이지 전용)"""
    stk = stock_alerts(sales_df, snapshot_df, restock_df, asof_date, settings)
    if stk.empty:
        return pd.DataFrame()
    df = stk.copy()
    s = resolve_settings(settings)

    sold_total = (sales_df.groupby(["channel", "product_code", "option_name"], as_index=False)
                          .agg(period_sold=("sold_qty", "sum"),
                               period_inbound=("inbound_qty", "sum"))) if not sales_df.empty \
        else pd.DataFrame(columns=["channel", "product_code", "option_name",
                                   "period_sold", "period_inbound"])
    df = df.merge(sold_total, on=["channel", "product_code", "option_name"], how="left")
    df["period_sold"] = df["period_sold"].fillna(0).astype(int)
    df["period_inbound"] = df["period_inbound"].fillna(0).astype(int)

    # 반품수 = 취소수량(판매 파일), 반품율 = 취소수량 / 판매합계수량
    canceled = (pd.to_numeric(df["canceled"], errors="coerce")
                if "canceled" in df.columns else pd.Series(0, index=df.index))
    df["ret_qty"] = canceled.fillna(0).astype(int)
    total_sold = (pd.to_numeric(df["total_sold"], errors="coerce")
                  if "total_sold" in df.columns else pd.Series(0, index=df.index)).fillna(0)
    df["return_rate"] = [(q / d) if d > 0 else None
                         for q, d in zip(df["ret_qty"], total_sold)]
    df["high_return"] = df["return_rate"].apply(
        lambda x: x is not None and x >= s["return_rate_flag"])
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
    df["total_sold"] = total_sold.astype(int)
    cols = ["channel", "product_code", "product_name", "option_name", "category",
            "stock", "period_sold", "period_inbound", "ret_qty", "return_rate",
            "total_sold", "reg_date", "days_since_sale", "lead_time_days",
            "need_qty", "알림",
            "high_return", "low_sales_high_return", "no_sale_flag", "shortage_flag"]
    df = df[[c for c in cols if c in df.columns]]
    return df.sort_values("알림", ascending=False)


def product_rollup(overview_df, settings=None):
    """옵션 단위 알림표(alert_overview 결과)를 상품 단위로 집계한다.

    - 재고/판매/반품수/필요수량 = 옵션 합계
    - 반품율 = 반품수 합계 / 전체판매(total_sold) 합계
    - 🔴반품율·🟠저판매·고반품 = 상품 합계 기준으로 재판정
    - 🟡무판매·🔵재고부족 = 옵션 중 하나라도 해당하면 표시(any)
    """
    if overview_df.empty:
        return pd.DataFrame()
    s = resolve_settings(settings)
    df = overview_df.copy()
    keys = ["channel", "product_code", "product_name"]

    agg = {
        "option_count": ("option_name", "nunique"),
        "stock": ("stock", "sum"),
        "period_sold": ("period_sold", "sum"),
        "ret_qty": ("ret_qty", "sum"),
        "need_qty": ("need_qty", "sum"),
        "shortage_flag": ("shortage_flag", "any"),
        "lead_time_days": ("lead_time_days", "first"),
    }
    if "period_inbound" in df.columns:
        agg["period_inbound"] = ("period_inbound", "sum")
    if "total_sold" in df.columns:
        agg["total_sold"] = ("total_sold", "sum")
    if "days_since_sale" in df.columns:
        agg["days_since_sale"] = ("days_since_sale", "min")
    g = df.groupby(keys, as_index=False).agg(**agg)
    g["need_qty"] = g["need_qty"].round(1)

    # 무판매는 '상품 전체'가 안 팔렸을 때만(옵션 any 집계는 잘 팔리는 상품을
    # 죽은 옵션 하나 때문에 무판매로 오탐). days_since_sale=상품 최근 판매(min).
    if "days_since_sale" in g.columns:
        ds = pd.to_numeric(g["days_since_sale"], errors="coerce")
        g["no_sale_flag"] = (g["stock"] > 0) & (ds.isna() | (ds >= s["no_sales_days"]))
    else:
        g["no_sale_flag"] = False

    # 등록일자: None과 문자열 비교 에러 방지 위해 따로 최솟값 계산 후 합침
    if "reg_date" in df.columns:
        reg = (df.dropna(subset=["reg_date"]).groupby(keys, as_index=False)
                 .agg(reg_date=("reg_date", "min")))
        g = g.merge(reg, on=keys, how="left")

    base = g["total_sold"] if "total_sold" in g.columns else g["period_sold"]
    g["return_rate"] = [(q / d) if d and d > 0 else None
                        for q, d in zip(g["ret_qty"], base)]
    g["high_return"] = g["return_rate"].apply(
        lambda x: x is not None and x >= s["return_rate_flag"])
    g["low_sales_high_return"] = g.apply(
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

    g["알림"] = g.apply(badges, axis=1)
    return g.sort_values("알림", ascending=False).reset_index(drop=True)


def weekly_sales(sales_df, asof_date, keys):
    """최근일(asof) 기준 주간 판매 지표 표.

    - 1주차 = 최근 7일(asof 포함), 2주차 = 그 직전 7일 … 4주차까지
    - 주평균 = 그 상품이 '처음 팔린 날 ~ asof' 기간의 한 주당 평균 판매수.
      (전체 데이터 기간으로 나누면 신상품 평균이 과소평가되므로 상품별 판매기간 사용)
    keys 로 상품단위(channel,product_code)·옵션단위 모두 계산할 수 있다.
    """
    cols = list(keys) + ["주평균", "1주차", "2주차", "3주차", "4주차"]
    if sales_df.empty:
        return pd.DataFrame(columns=cols)
    df = sales_df.copy()
    d = pd.to_datetime(df["sale_date"], errors="coerce")
    asof = pd.to_datetime(asof_date)

    out = None
    for w in range(1, 5):
        hi = asof - pd.Timedelta(days=7 * (w - 1))
        lo = asof - pd.Timedelta(days=7 * w - 1)
        mask = (d >= lo) & (d <= hi)
        g = (df[mask].groupby(keys, as_index=False)
                     .agg(**{f"{w}주차": ("sold_qty", "sum")}))
        out = g if out is None else out.merge(g, on=keys, how="outer")

    # 주평균: 상품별 '첫 판매일 ~ asof' 기간으로 나눔(신상품 과소평가 방지)
    df["_d"] = d
    sold = df[df["sold_qty"] > 0]
    first = (sold.groupby(keys, as_index=False).agg(_first=("_d", "min"))
             if not sold.empty
             else pd.DataFrame(columns=list(keys) + ["_first"]))
    avg = df.groupby(keys, as_index=False).agg(_tot=("sold_qty", "sum"))
    avg = avg.merge(first, on=keys, how="left")

    def _wavg(tot, fdate):
        if pd.isna(fdate):
            return 0.0
        weeks = max(1.0, ((asof - fdate).days + 1) / 7.0)
        return round(tot / weeks, 1)

    avg["주평균"] = [_wavg(t, f) for t, f in zip(avg["_tot"], avg["_first"])]
    out = avg[list(keys) + ["주평균"]].merge(out, on=keys, how="outer")

    for c in ["1주차", "2주차", "3주차", "4주차"]:
        out[c] = out[c].fillna(0).astype(int)
    out["주평균"] = out["주평균"].fillna(0)
    return out[cols]


def product_trend(df, asof_date=None, settings=None):
    """주차별 판매(1~4주차)로 상품 흐름(추세)·정리 추천을 규칙기반으로 판정.

    - 추세 = 최근 2주(1+2주차) vs 그 전 2주(3+4주차) 비교
      📈 상승(+20%↑) / 📉 하락(-20%↓) / 〰️ 유지 / 🆕 신규유입 / ⏸ 판매없음
    - 변화율 = (최근2주 - 그전2주) / 그전2주
    - 추천 = 흐름 + 재고·반품 + 보호게이트를 합쳐 '지금 할 일' 한 줄 제안

    정리 판정 전 2개의 게이트(asof_date·reg_date·total_sold 가 있을 때):
    - 🌱 신상 보호: 등록 후 new_product_days 이내면 판정 보류(관찰)
    - 🔢 표본 게이트: 누적 판매가 reliable_sold_qty 미만이면 반품율 신뢰 못 함(관찰)
    반품으로 정리는 두 게이트 통과 + 반품율 ≥ discontinue_return_rate 일 때만.

    df 는 weekly_sales 의 1~4주차 컬럼을 가진 표(상품 또는 옵션) 여야 한다.
    """
    s = resolve_settings(settings)
    out = df.copy()
    if out.empty:
        for c in ["추세", "변화율", "추천", "정리후보", "관찰중"]:
            out[c] = pd.Series(dtype="object")
        return out
    for c in ["1주차", "2주차", "3주차", "4주차"]:
        if c not in out.columns:
            out[c] = 0
    recent = out["1주차"] + out["2주차"]
    prev = out["3주차"] + out["4주차"]
    four = recent + prev

    out["변화율"] = [((rc - pv) / pv) if pv else None for rc, pv in zip(recent, prev)]

    def trend(rc, pv, ch):
        if rc == 0 and pv == 0:
            return "⏸ 판매없음"
        if pv == 0 and rc > 0:
            return "🆕 신규유입"
        if ch is not None and ch >= 0.2:
            return "📈 상승"
        if ch is not None and ch <= -0.2:
            return "📉 하락"
        return "〰️ 유지"

    out["추세"] = [trend(rc, pv, ch) for rc, pv, ch in zip(recent, prev, out["변화율"])]

    def col(name, default):
        return out[name] if name in out.columns else pd.Series(default, index=out.index)

    stock = col("stock", 0)
    high_ret = col("high_return", False)
    short = col("shortage_flag", False)
    ret_rate = col("return_rate", None)
    cum_sold = col("total_sold", None)
    period_sold = col("period_sold", 0)
    days_since = col("days_since_sale", None)

    def no_recent_sale(i):
        # 상품(또는 옵션) 전체가 최근에 안 팔렸는가. days_since_sale=상품은 옵션 중
        # 가장 최근 판매 기준(min)이라, 한 옵션만 죽어도 오탐하지 않는다.
        ds = days_since.iloc[i]
        if ds is None or (isinstance(ds, float) and ds != ds):
            return True
        return ds >= s["no_sales_days"]

    # 등록 후 경과일 (reg_date·asof 있을 때만)
    asof = pd.to_datetime(asof_date) if asof_date is not None else None
    if "reg_date" in out.columns and asof is not None:
        reg = pd.to_datetime(out["reg_date"], errors="coerce")
        age_days = (asof - reg).dt.days
    else:
        age_days = pd.Series([None] * len(out), index=out.index)

    def cum(i):
        v = cum_sold.iloc[i]
        if v is None or (isinstance(v, float) and v != v):
            return float(period_sold.iloc[i])
        return float(v)

    def is_new(i):
        a = age_days.iloc[i]
        return a is not None and a == a and a < s["new_product_days"]

    def reliable(i):
        return cum(i) >= s["reliable_sold_qty"]

    def rrate(i):
        v = ret_rate.iloc[i]
        return v if (v is not None and v == v) else None

    week1 = out["1주차"]

    def decide(i):
        tr, f = out["추세"].iloc[i], four.iloc[i]
        rr = rrate(i)
        new, rel = is_new(i), reliable(i)

        # 1) 신상 보호기간 — 판정 보류
        if new:
            a = int(age_days.iloc[i])
            note = " · 반품율 높음" if rr is not None and rr >= s["return_rate_flag"] else ""
            return f"🌱 관찰 중 — 신상(등록 {a}일){note}"
        # 2) 반품 많아 정리 (표본 충분할 때만)
        if rel and rr is not None and rr >= s["discontinue_return_rate"]:
            return f"⛔ 정리 — 반품율 높음 ({rr*100:.0f}%)"
        # 3) 재고만 있고 안 팔림 → 정리 (상품 전체 최근 판매 기준)
        if stock.iloc[i] > 0 and (no_recent_sale(i) or f == 0):
            return "⛔ 정리 — 재고 있는데 안 팔림"
        # 4) 저판매 + 하락 → 정리 후보
        if f <= s["low_sales_qty"] and tr in ("📉 하락", "⏸ 판매없음"):
            return "⚠️ 정리 후보 — 판매 적고 하락세"
        # 5) 반품 신호는 있으나 표본 부족 → 관찰
        if rr is not None and rr >= s["return_rate_flag"] and not rel:
            return "🌱 관찰 중 — 반품율 높지만 표본 적음"
        # 6) 반품율 경고 수준 (정리까진 아님)
        if bool(high_ret.iloc[i]):
            return "🔎 반품 점검 — 반품율 높음"
        if tr == "📈 상승" and bool(short.iloc[i]):
            return "🔁 재입고 — 잘 나가는데 재고 부족"
        if tr == "📈 상승":
            return "✅ 성장 중"
        if tr == "📉 하락":
            return "👀 하락 주의"
        return "· 유지"

    def action(i):
        res = decide(i)
        # 롱테일 보호: 최근 1주 OR 최근 4주 평균이 기준 이상이면 정리 제외.
        # (양말 등 몰아 팔리는 스테디셀러는 한 주 비어도 4주 평균으로 지켜진다)
        recent4_avg = four.iloc[i] / 4.0
        still = (week1.iloc[i] >= s["keep_weekly_sold"]
                 or recent4_avg >= s["keep_weekly_sold"])
        if res.startswith(("⛔", "⚠️")) and still:
            rr = rrate(i)
            if rr is not None and rr >= s["return_rate_flag"]:
                return "🔎 반품 점검 — 반품 많지만 최근 판매 유지중"
            return f"· 유지 — 최근 4주 {int(four.iloc[i])}장 판매"
        return res

    out["추천"] = [action(i) for i in range(len(out))]
    out["정리후보"] = [a.startswith(("⛔", "⚠️")) for a in out["추천"]]
    out["관찰중"] = [a.startswith("🌱") for a in out["추천"]]
    return out


def season_clearance(df, weeks_left, settings=None):
    """시즌 말 재고 소진 판단. (평상시 롱테일 보호와 별개)

    - 최근4주평균 = (1+2+3+4주차) ÷ 4  (현재 판매 속도)
    - 소진주수 = 현재재고 ÷ 최근4주평균  (지금 속도로 재고 비우는 데 걸리는 주)
    - weeks_left = 남은 시즌 주수
      소진주수 ≤ 남은주수 → ✅ 시즌내 소진 / ~2배 → ⚠️ 할인 가속 / 2배↑·정체 → ⛔ 떨이·단종
    df 는 weekly_sales 의 1~4주차·stock 컬럼을 가진 상품 표여야 한다.
    """
    out = df.copy()
    if out.empty:
        for c in ["최근4주평균", "소진주수", "시즌판단", "시즌정리후보"]:
            out[c] = pd.Series(dtype="object")
        return out
    for c in ["1주차", "2주차", "3주차", "4주차"]:
        if c not in out.columns:
            out[c] = 0
    recent4 = (out["1주차"] + out["2주차"] + out["3주차"] + out["4주차"]) / 4.0
    stock = out["stock"] if "stock" in out.columns else pd.Series(0, index=out.index)
    out["최근4주평균"] = recent4.round(1)
    out["소진주수"] = [round(stock.iloc[i] / v, 1) if v and v > 0 else None
                    for i, v in enumerate(recent4)]

    rng = max(1, int(weeks_left))

    def verdict(i):
        s_ = stock.iloc[i]
        if s_ <= 0:
            return "✅ 재고 없음"
        w = out["소진주수"].iloc[i]
        if w is None:
            return "⛔ 재고 과다 — 안 팔림(정체)"
        if w <= rng:
            return "✅ 시즌내 소진 가능"
        if w <= 2 * rng:
            return "⚠️ 할인 가속 — 시즌내 못 비울 수도"
        return "⛔ 재고 과다 — 떨이·단종 검토"

    out["시즌판단"] = [verdict(i) for i in range(len(out))]
    out["시즌정리후보"] = [v.startswith(("⛔", "⚠️")) for v in out["시즌판단"]]
    return out
