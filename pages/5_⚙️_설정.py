"""설정 페이지 — 판단 기준 + 상품별 입고기간/최소재고."""
import pandas as pd
import streamlit as st

from core import analytics, config, db

st.set_page_config(page_title="설정", page_icon="⚙️", layout="wide")
db.init_db()
st.title("⚙️ 설정")

saved = db.load_settings()
s = analytics.resolve_settings(saved)

st.subheader("1) 판단 기준값")
st.caption("여기서 바꾼 값이 모든 분석에 바로 적용됩니다.")
with st.form("thresholds"):
    c1, c2, c3 = st.columns(3)
    rr = c1.number_input("반품율 경고 기준 (%)", 0, 100,
                         int(s["return_rate_flag"] * 100), step=5)
    nd = c2.number_input("무판매 경고 일수 (일)", 1, 90, int(s["no_sales_days"]))
    lsq = c3.number_input("저판매 기준 (이하 수량)", 0, 100, int(s["low_sales_qty"]))
    c4, c5, c6 = st.columns(3)
    lsr = c4.number_input("저판매·고반품 반품율 (%)", 0, 100,
                          int(s["low_sales_return_rate"] * 100), step=5)
    sp = c5.number_input("급등 기준 (전일대비 +%)", 10, 1000,
                         int(s["spike_pct"] * 100), step=10)
    dp = c6.number_input("급감 기준 (전일대비 -%)", 10, 100,
                         int(s["drop_pct"] * 100), step=10)
    c7, c8 = st.columns(2)
    lead = c7.number_input("기본 입고기간 (일)", 1, 120, int(s["default_lead_time_days"]))
    vel = c8.number_input("판매속도 계산기간 (최근 N일)", 1, 90, int(s["velocity_window_days"]))
    if st.form_submit_button("💾 기준값 저장", type="primary"):
        db.save_settings({
            "return_rate_flag": rr / 100, "no_sales_days": nd, "low_sales_qty": lsq,
            "low_sales_return_rate": lsr / 100, "spike_pct": sp / 100, "drop_pct": dp / 100,
            "default_lead_time_days": lead, "velocity_window_days": vel,
        })
        st.success("저장했습니다.")

st.divider()
st.subheader("2) 상품별 입고기간 · 최소재고")
st.caption("입고기간(리드타임)을 넣으면 '판매속도 × 입고기간 > 재고'일 때 🔵재고부족으로 표시됩니다. "
           "최소재고를 넣으면 재고가 그 아래로 내려갈 때도 부족으로 표시됩니다. 빈칸은 기본값 사용.")

snap = db.load_snapshot()
if snap.empty:
    st.info("먼저 판매 분석 파일을 업로드하면 상품 목록이 나타납니다.")
    st.stop()

products = (snap.groupby("product_code", as_index=False)
                .agg(product_name=("product_name", "first"),
                     stock=("stock", "sum")))
rs = db.load_restock_settings()
tbl = products.merge(rs, on="product_code", how="left")
tbl = tbl.rename(columns={"product_code": "상품코드", "product_name": "상품명",
                          "stock": "현재재고", "lead_time_days": "입고기간(일)",
                          "min_stock": "최소재고"})

edited = st.data_editor(
    tbl, width='stretch', hide_index=True, num_rows="fixed",
    disabled=["상품코드", "상품명", "현재재고"],
    column_config={
        "입고기간(일)": st.column_config.NumberColumn(min_value=0, step=1),
        "최소재고": st.column_config.NumberColumn(min_value=0, step=1),
    },
    key="restock_editor")

if st.button("💾 입고기간/최소재고 저장", type="primary"):
    out = edited.rename(columns={"상품코드": "product_code", "입고기간(일)": "lead_time_days",
                                 "최소재고": "min_stock"})[
        ["product_code", "lead_time_days", "min_stock"]]
    out = out[out["lead_time_days"].notna() | out["min_stock"].notna()]
    db.save_restock_settings(out)
    st.success(f"{len(out):,}개 상품 설정을 저장했습니다.")
