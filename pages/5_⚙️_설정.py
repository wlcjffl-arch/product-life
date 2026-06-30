"""설정 페이지 — 판단 기준 + 상품별 입고기간/최소재고."""
import pandas as pd
import streamlit as st

from core import analytics, config, db
from core.ui import setup_page, ensure_db, cached, clear_cache

setup_page("설정", "⚙️")
ensure_db()
st.title("⚙️ 설정")

saved = cached(("settings",), db.load_settings)
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

    st.markdown("**정리(그만 팔기) 추천 기준**")
    st.caption("반품 많은 상품을 내리되, 신상품과 표본이 적은 상품은 보호(관찰)합니다.")
    c9, c10, c11 = st.columns(3)
    drr = c9.number_input("정리 반품율 기준 (%)", 0, 100,
                          int(s["discontinue_return_rate"] * 100), step=5,
                          help="이 반품율 이상이면 ⛔정리 (단, 아래 두 조건을 통과해야 함)")
    rsq = c10.number_input("신뢰 누적판매 (이상 개수)", 0, 1000,
                           int(s["reliable_sold_qty"]),
                           help="누적 판매가 이 수량 미만이면 반품율을 믿지 않고 '관찰'")
    npd = c11.number_input("신상품 보호기간 (등록 후 일)", 0, 180,
                           int(s["new_product_days"]),
                           help="등록 후 이 기간 이내면 정리 추천을 보류하고 '관찰'")
    kws = st.number_input("최근 1주 판매 보호 (이상 개수)", 0, 100,
                          int(s["keep_weekly_sold"]),
                          help="최근 1주 판매가 이 수량 이상이면 정리 대상에서 제외(롱테일 매출 보호)")
    if st.form_submit_button("💾 기준값 저장", type="primary"):
        db.save_settings({
            "return_rate_flag": rr / 100, "no_sales_days": nd, "low_sales_qty": lsq,
            "low_sales_return_rate": lsr / 100, "spike_pct": sp / 100, "drop_pct": dp / 100,
            "default_lead_time_days": lead, "velocity_window_days": vel,
            "discontinue_return_rate": drr / 100, "reliable_sold_qty": rsq,
            "new_product_days": npd, "keep_weekly_sold": kws,
        })
        clear_cache()
        st.success("저장했습니다.")

st.divider()
st.subheader("2) 데이터 관리")
st.caption("같은 파일을 여러 판매처 이름으로 잘못 올려 중복되면, '전체'에서 합산돼 수치가 부풀려 보입니다. "
           "아래에서 중복된 판매처를 삭제하거나 전체 초기화하세요.")
stats = db.channel_stats()
if stats.empty:
    st.info("저장된 데이터가 없습니다.")
else:
    st.dataframe(stats, width='stretch', hide_index=True)
    chs = stats["판매처"].dropna().tolist()
    if chs:
        d1, d2 = st.columns([3, 1])
        del_ch = d1.selectbox("삭제할 판매처", chs, key="del_ch")
        if d2.button("🗑 이 판매처 삭제", key="del_btn"):
            db.delete_channel(del_ch)
            clear_cache()
            st.success(f"'{del_ch}' 데이터를 삭제했습니다.")
            st.rerun()
    confirm = st.checkbox("⚠️ 모든 판매·반품 데이터를 지우려면 체크하세요", key="reset_confirm")
    if st.button("🧹 전체 초기화", disabled=not confirm, key="reset_btn"):
        db.reset_all_data()
        clear_cache()
        st.success("모든 데이터를 초기화했습니다. 다시 업로드해주세요.")
        st.rerun()

st.divider()
st.subheader("3) 상품별 입고기간 · 최소재고")
st.caption("입고기간(리드타임)을 넣으면 '판매속도 × 입고기간 > 재고'일 때 🔵재고부족으로 표시됩니다. "
           "최소재고를 넣으면 재고가 그 아래로 내려갈 때도 부족으로 표시됩니다. 빈칸은 기본값 사용.")

snap = cached(("snapshot", None), lambda: db.load_snapshot())
if snap.empty:
    st.info("먼저 판매 분석 파일을 업로드하면 상품 목록이 나타납니다.")
    st.stop()

products = (snap.groupby("product_code", as_index=False)
                .agg(product_name=("product_name", "first"),
                     stock=("stock", "sum")))
rs = cached(("restock",), db.load_restock_settings)
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
    clear_cache()
    st.success(f"{len(out):,}개 상품 설정을 저장했습니다.")
