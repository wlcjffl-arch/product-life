"""상품 상태 / 알림 페이지."""
import streamlit as st

from core import analytics, store
from core.ui import setup_page, sidebar_filters

setup_page("상품 상태 / 알림", "🚦")
st.title("🚦 상품 상태 / 알림")
st.caption("🔴 반품율 높음  ·  🟠 판매 적고 반품율 높음  ·  🟡 재고 있는데 무판매  ·  🔵 재고부족")

channel, start, end = sidebar_filters("all")
settings = store.load_settings()

sales = store.load_sales(channel, start, end)
returns = store.load_returns(channel, start, end)
snapshot = store.load_snapshot(channel)
restock = store.load_restock_settings()

if snapshot.empty:
    st.info("상품 스냅샷이 없습니다. 먼저 판매 분석 파일을 업로드하세요.")
    st.stop()

overview = analytics.alert_overview(sales, returns, snapshot, restock, end, settings)
if overview.empty:
    st.info("표시할 상품이 없습니다.")
    st.stop()

# ── 요약 ──
c1, c2, c3, c4 = st.columns(4)
c1.metric("🔴 반품율 초과", int(overview["high_return"].sum()))
c2.metric("🟠 저판매·고반품", int(overview["low_sales_high_return"].sum()))
c3.metric("🟡 무판매", int(overview["no_sale_flag"].sum()))
c4.metric("🔵 재고부족", int(overview["shortage_flag"].sum()))

# ── 필터 ──
only = st.multiselect(
    "이 신호만 보기", ["🔴반품율", "🟠저판매·고반품", "🟡무판매", "🔵재고부족"])
view = overview.copy()
if only:
    mask = view["알림"].apply(lambda a: any(k in a for k in only))
    view = view[mask]
view = view[view["알림"] != ""] if not only else view

show_cols = {
    "channel": "판매처", "product_code": "상품코드", "product_name": "상품명",
    "option_name": "옵션", "stock": "현재재고", "period_sold": "기간판매",
    "ret_qty": "반품수", "return_rate": "반품율", "days_since_sale": "무판매일수",
    "lead_time_days": "입고기간", "need_qty": "필요수량", "알림": "알림",
}
disp = view[[c for c in show_cols if c in view.columns]].rename(columns=show_cols)
if "반품율" in disp.columns:
    disp["반품율"] = disp["반품율"].apply(lambda x: f"{x*100:.0f}%" if x == x and x is not None else "-")

st.dataframe(disp, width='stretch', hide_index=True)

csv = disp.to_csv(index=False).encode("utf-8-sig")
st.download_button("⬇️ 엑셀(CSV)로 내려받기", csv,
                   file_name="상품상태알림.csv", mime="text/csv")

st.divider()
with st.expander("상품별 반품율 (옵션 합산)"):
    rr = analytics.return_rate_product(sales, returns, settings)
    rr["반품율"] = rr["return_rate"].apply(
        lambda x: f"{x*100:.0f}%" if x == x and x is not None else "-")
    st.dataframe(
        rr[["channel", "product_code", "product_name", "sold_qty", "ret_qty",
            "반품율", "high_return", "low_sales_high_return"]].rename(columns={
                "channel": "판매처", "product_code": "상품코드", "product_name": "상품명",
                "sold_qty": "판매수량", "ret_qty": "반품수량",
                "high_return": "반품율초과", "low_sales_high_return": "저판매·고반품"}),
        width='stretch', hide_index=True)
