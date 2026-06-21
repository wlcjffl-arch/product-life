"""판매 흐름 페이지."""
import altair as alt
import pandas as pd
import streamlit as st

from core import analytics, db
from core.ui import setup_page, sidebar_filters

setup_page("판매 흐름", "📈")
st.title("📈 판매 흐름")

channel, start, end = sidebar_filters("sales")
settings = db.load_settings()
sales = db.load_sales_daily(channel, start, end)

if sales.empty:
    st.info("선택한 조건에 해당하는 판매 데이터가 없습니다. "
            "사이드바에서 **전체 기간 보기**를 켜거나 판매처를 바꿔보세요.")
    st.stop()

def period_radio(key):
    return st.radio("보기 단위", ["일", "주", "월"], horizontal=True,
                    format_func=lambda x: f"{x}별", key=key)


def period_chart(df, prd, height=320):
    """기간별 판매 시계열 + 급등/급감 + 확대/축소(줌). (차트, 데이터, 가로축이름) 반환."""
    xlabel = {"일": "날짜", "주": "주(월요일 기준)", "월": "월"}[prd]
    xfmt = {"일": "%Y-%m-%d", "주": "%Y-%m-%d", "월": "%Y-%m"}[prd]
    marked = analytics.mark_spikes(analytics.period_series(df, prd),
                                   settings, date_col="bucket")
    x = alt.X("bucket_date:T", title=xlabel, axis=alt.Axis(format=xfmt, labelAngle=-40))
    zoom = alt.selection_interval(bind="scales", encodings=["x"])
    tip = [alt.Tooltip("bucket:N", title=xlabel),
           alt.Tooltip("sold_qty:Q", title="판매"),
           alt.Tooltip("inbound_qty:Q", title="입고"),
           alt.Tooltip("flag:N", title="신호")]
    line = alt.Chart(marked).mark_line(point=True, color="#1f77b4").encode(
        x=x, y=alt.Y("sold_qty:Q", title="판매수량"), tooltip=tip)
    pts = alt.Chart(marked[marked["flag"] != ""]).mark_point(
        size=140, filled=True).encode(
        x=x, y="sold_qty:Q",
        color=alt.Color("flag:N", scale=alt.Scale(
            domain=["급등 ▲", "급감 ▼"], range=["#2ca02c", "#d62728"]), title="신호"),
        tooltip=[alt.Tooltip("bucket:N", title=xlabel), "sold_qty", "flag"])
    return (line + pts).properties(height=height).add_params(zoom), marked, xlabel


# ── 전체 판매 흐름 (검색 없음) ──
st.subheader("전체 판매 흐름")
period = period_radio("period_total")
chart, marked, _ = period_chart(sales, period, height=340)
m1, m2, m3 = st.columns(3)
m1.metric("기간 총 판매수량", f"{int(marked['sold_qty'].sum()):,}")
m2.metric(f"급등 {period}수", int((marked["flag"] == "급등 ▲").sum()))
m3.metric(f"급감 {period}수", int((marked["flag"] == "급감 ▼").sum()))
st.altair_chart(chart, use_container_width=True)
st.caption("🔍 차트 위에서 마우스 휠로 확대/축소, 드래그로 좌우 이동할 수 있어요. "
           "더블클릭하면 원래대로 돌아옵니다."
           + ("\n\nℹ️ 마지막 날은 당일 판매가 덜 반영됐을 수 있습니다." if period == "일" else ""))

st.divider()

# ── 상품별 추세 (검색 + 판매수량 순 + 일/주/월 + 데이터표) ──
st.subheader("상품별 추세")
query = st.text_input("상품 검색 (상품명 또는 상품코드)",
                      placeholder="예: 팬츠, 자켓, 9579").strip()

prod = (sales.groupby(["product_code", "product_name"], as_index=False)
             .agg(sold=("sold_qty", "sum"))
             .sort_values("sold", ascending=False))
if query:
    q = query.lower()
    prod = prod[prod["product_name"].fillna("").str.lower().str.contains(q)
                | prod["product_code"].fillna("").str.lower().str.contains(q)]
    if prod.empty:
        st.info(f"'{query}' 에 해당하는 상품이 없습니다.")
        st.stop()
    st.caption(f"🔎 '{query}' 검색 결과 {len(prod)}개 (판매수량 순)")

prod["label"] = (prod["product_name"].fillna("(이름없음)") + " ["
                 + prod["product_code"] + "] · 판매 " + prod["sold"].astype(str))
sel = st.selectbox("상품 선택 (판매수량 많은 순)", prod["label"].tolist())
period2 = period_radio("period_prod")

if sel:
    code = prod.loc[prod["label"] == sel, "product_code"].iloc[0]
    one = sales[sales["product_code"] == code]
    pchart, pm, xlabel2 = period_chart(one, period2, height=300)
    st.altair_chart(pchart, use_container_width=True)

    # 상품별 기간 판매 데이터 (일/주/월별 표)
    st.markdown(f"**{period2}별 판매 데이터**")
    tbl = pm[["bucket", "sold_qty", "inbound_qty", "pct_change", "flag"]].copy()
    tbl["pct_change"] = tbl["pct_change"].apply(
        lambda x: f"{x * 100:+.0f}%" if pd.notna(x) else "-")
    tbl = (tbl.sort_values("bucket", ascending=False)
              .rename(columns={"bucket": xlabel2, "sold_qty": "판매수량",
                               "inbound_qty": "입고수량", "pct_change": "직전대비",
                               "flag": "신호"}))
    st.dataframe(tbl, width='stretch', hide_index=True)
    st.download_button(
        "⬇️ 이 상품 판매데이터 내려받기(CSV)",
        tbl.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"{code}_{period2}별_판매데이터.csv", mime="text/csv")

st.divider()
st.subheader("상품별 판매 순위")

codes = set(prod["product_code"])
sales_f = sales[sales["product_code"].isin(codes)]

# 선택 기간의 판매·입고 합계
rank = (sales_f.groupby(["product_code", "product_name"], as_index=False)
               .agg(총판매수=("sold_qty", "sum"), 입고수량=("inbound_qty", "sum")))

# 스냅샷에서 상품 속성·현재 상태 (옵션 합산)
snap = db.load_snapshot(channel)
if not snap.empty:
    snap_g = (snap.groupby("product_code", as_index=False)
                  .agg(공급처=("supplier", "first"), 원가=("cost", "mean"),
                       판매단가=("sale_price", "mean"), 매출액=("amount", "sum"),
                       현재재고=("stock", "sum"), 미발송수=("unshipped", "sum"),
                       취소수량=("canceled", "sum")))
    # 등록일자는 빈 값(None) 제외 후 최솟값 (None과 문자열 비교 에러 방지)
    reg = (snap.dropna(subset=["reg_date"])
               .groupby("product_code", as_index=False)
               .agg(등록일자=("reg_date", "min")))
    snap_g = snap_g.merge(reg, on="product_code", how="left")
    rank = rank.merge(snap_g, on="product_code", how="left")

for c in ["공급처", "등록일자", "원가", "판매단가", "매출액", "현재재고", "미발송수", "취소수량"]:
    if c not in rank.columns:
        rank[c] = None

# 파생 지표
rank["수익율"] = ((rank["판매단가"] - rank["원가"]) / rank["판매단가"] * 100).round(1)
denom = rank["총판매수"] + rank["취소수량"].fillna(0)
rank["취소율"] = (rank["취소수량"].fillna(0) / denom.replace(0, pd.NA) * 100).round(1)
for c in ["원가", "판매단가", "매출액"]:
    rank[c] = pd.to_numeric(rank[c], errors="coerce").round(0)

rank = rank.rename(columns={"product_name": "상품명", "product_code": "상품코드"})
# 관련도 순 컬럼 배치: 식별 → 공급처 → 판매/재고 수량 → 금액/수익 → 등록일
order = ["상품명", "상품코드", "공급처", "총판매수", "입고수량", "현재재고", "미발송수",
         "취소수량", "취소율", "원가", "판매단가", "매출액", "수익율", "등록일자"]
rank = rank[[c for c in order if c in rank.columns]].reset_index(drop=True)

# 정렬 컨트롤 (각 컬럼 오름/내림차순)
sortable = ["총판매수", "입고수량", "현재재고", "미발송수", "취소수량", "취소율",
            "원가", "판매단가", "매출액", "수익율", "등록일자"]
sc1, sc2 = st.columns([2, 1])
sort_by = sc1.selectbox("정렬 기준", sortable, index=0)
direction = sc2.radio("정렬 방향", ["내림차순", "오름차순"], horizontal=True)
rank = rank.sort_values(sort_by, ascending=(direction == "오름차순"),
                        na_position="last").reset_index(drop=True)

MONEY_CFG = {
    "원가": st.column_config.NumberColumn(format="%d원"),
    "판매단가": st.column_config.NumberColumn(format="%d원"),
    "매출액": st.column_config.NumberColumn(format="%d원"),
    "수익율": st.column_config.NumberColumn(format="%.1f%%"),
    "취소율": st.column_config.NumberColumn(format="%.1f%%"),
}
event = st.dataframe(rank, width='stretch', hide_index=True, column_config=MONEY_CFG,
                     on_select="rerun", selection_mode="single-row", key="rank_table")
st.caption("💡 **상품 행을 클릭**하면 아래에 그 상품의 **옵션별** 내역이 펼쳐집니다. "
           "(열 제목 클릭으로 정렬도 됩니다.)")

# ── 선택한 상품의 옵션별 펼쳐보기 ──
try:
    sel_rows = list(event.selection.rows)
except Exception:
    sel_rows = []
if sel_rows:
    r = rank.iloc[sel_rows[0]]
    code, name = r["상품코드"], r["상품명"]
    st.markdown(f"#### 🔎 {name} `[{code}]` — 옵션별")
    od = (sales_f[sales_f["product_code"] == code]
          .groupby("option_name", as_index=False)
          .agg(총판매수=("sold_qty", "sum"), 입고수량=("inbound_qty", "sum")))
    if not snap.empty:
        osnap = (snap[snap["product_code"] == code]
                 .groupby("option_name", as_index=False)
                 .agg(판매단가=("sale_price", "mean"), 매출액=("amount", "sum"),
                      현재재고=("stock", "sum"), 미발송수=("unshipped", "sum"),
                      취소수량=("canceled", "sum")))
        od = od.merge(osnap, on="option_name", how="outer")
    for c in ["총판매수", "입고수량", "현재재고", "미발송수", "취소수량"]:
        if c in od.columns:
            od[c] = pd.to_numeric(od[c], errors="coerce").fillna(0).astype(int)
    for c in ["판매단가", "매출액"]:
        if c in od.columns:
            od[c] = pd.to_numeric(od[c], errors="coerce").round(0)
    od = od.rename(columns={"option_name": "옵션"}).sort_values("총판매수", ascending=False)
    st.dataframe(od, width='stretch', hide_index=True,
                 column_config={k: v for k, v in MONEY_CFG.items() if k in od.columns})

