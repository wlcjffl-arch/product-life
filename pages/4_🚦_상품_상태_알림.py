"""상품 상태 / 알림 페이지 — 판매 파일만으로, 카테고리별 탭으로 봅니다."""
import streamlit as st

from core import analytics, db
from core.ui import setup_page, sidebar_filters, cached

setup_page("상품 상태 / 알림", "🚦")
st.title("🚦 상품 상태 / 알림")
st.caption("판매 분석 파일로 만들어집니다. ※ 반품수·반품율은 판매 파일의 **취소수량** 기준입니다.")

channel, start, end = sidebar_filters("all")
settings = cached(("settings",), db.load_settings)
sales = cached(("sales", channel, start, end),
               lambda: db.load_sales_daily(channel, start, end))
snapshot = cached(("snapshot", channel), lambda: db.load_snapshot(channel))
restock = cached(("restock",), db.load_restock_settings)

if snapshot.empty:
    st.info("상품 데이터가 없습니다. 먼저 **📥 데이터 업로드 → 판매 분석 파일**을 올려주세요.")
    st.stop()

overview = analytics.alert_overview(sales, None, snapshot, restock, end, settings)
if overview.empty:
    st.info("표시할 상품이 없습니다.")
    st.stop()

# ── 요약 ──
c1, c2, c3, c4 = st.columns(4)
c1.metric("🔴 반품율 초과", int(overview["high_return"].sum()))
c2.metric("🟠 저판매·고반품", int(overview["low_sales_high_return"].sum()))
c3.metric("🟡 무판매", int(overview["no_sale_flag"].sum()))
c4.metric("🔵 재고부족", int(overview["shortage_flag"].sum()))

SHOW_COLS = {
    "channel": "판매처", "product_code": "상품코드", "product_name": "상품명",
    "option_name": "옵션", "stock": "현재재고", "period_sold": "기간판매",
    "ret_qty": "반품수(취소)", "return_rate": "반품율", "days_since_sale": "무판매일수",
    "lead_time_days": "입고기간", "need_qty": "필요수량", "알림": "알림",
}


def show_table(df, fname, drop_alert=False):
    """필터된 알림 표 + 건수 + CSV 다운로드."""
    if df.empty:
        st.caption("해당하는 상품이 없습니다. 👍")
        return
    cols = [c for c in SHOW_COLS if c in df.columns and not (drop_alert and c == "알림")]
    disp = df[cols].rename(columns=SHOW_COLS)
    if "반품율" in disp.columns:
        disp["반품율"] = disp["반품율"].apply(
            lambda x: f"{x*100:.0f}%" if x == x and x is not None else "-")
    st.caption(f"{len(disp):,}건")
    st.dataframe(disp, width='stretch', hide_index=True)
    st.download_button("⬇️ 엑셀(CSV)로 내려받기", disp.to_csv(index=False).encode("utf-8-sig"),
                       file_name=fname, mime="text/csv", key=f"dl_{fname}")


tabs = st.tabs(["📋 전체", "🔴 반품율 높음", "🟠 저판매·고반품", "🟡 무판매", "🔵 재고부족"])
with tabs[0]:
    show_table(overview[overview["알림"] != ""], "상품상태_전체.csv")
with tabs[1]:
    show_table(overview[overview["high_return"]], "반품율높음.csv", drop_alert=True)
with tabs[2]:
    show_table(overview[overview["low_sales_high_return"]], "저판매_고반품.csv", drop_alert=True)
with tabs[3]:
    show_table(overview[overview["no_sale_flag"]], "무판매.csv", drop_alert=True)
with tabs[4]:
    show_table(overview[overview["shortage_flag"]], "재고부족.csv", drop_alert=True)
