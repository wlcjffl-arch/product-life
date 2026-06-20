"""반품 분석 페이지."""
import altair as alt
import pandas as pd
import streamlit as st

from core import ingest, store
from core.ui import setup_page, sidebar_filters

setup_page("반품 분석", "🔁")
st.title("🔁 반품 분석")

channel, start, end = sidebar_filters("returns")
ret = store.load_returns(channel, start, end)

# 옵션에서 색상·사이즈를 파싱해 통일 (형태가 달라도 동일하게)
if not ret.empty:
    parsed = ret["option_name"].map(ingest.parse_option)
    ret["색상"] = parsed.map(lambda t: t[0] or "(미상)")
    ret["사이즈"] = parsed.map(lambda t: t[1] or "(미상)")
    ret["옵션"] = ret["option_name"].map(ingest.normalize_option)

if ret.empty:
    st.info("선택한 조건에 해당하는 반품 데이터가 없습니다. "
            "사이드바에서 **전체 기간 보기**를 켜거나 판매처를 바꿔보세요.")
    st.stop()


def add_pct(df, qty_col):
    """비율(%) 컬럼 추가."""
    total = df[qty_col].sum()
    df = df.copy()
    df["비율"] = df[qty_col].apply(
        lambda v: f"{v / total * 100:.1f}%" if total else "0%")
    return df


total_ret = int(ret["qty"].sum())
c1, c2, c3 = st.columns(3)
c1.metric("총 반품 건수", f"{total_ret:,}")
c2.metric("반품 상품 수", ret["product_code"].nunique())
c3.metric("반품 사유 종류", ret["reason"].nunique())

# ── 사유별 ──
st.subheader("반품 사유별")
by_reason = (ret.groupby("reason", as_index=False).agg(건수=("qty", "sum"))
                .sort_values("건수", ascending=False))
by_reason = add_pct(by_reason, "건수")
cc1, cc2 = st.columns([2, 3])
cc1.dataframe(by_reason.rename(columns={"reason": "사유"}),
              width='stretch', hide_index=True)
chart = alt.Chart(by_reason).mark_bar().encode(
    x=alt.X("건수:Q"), y=alt.Y("reason:N", sort="-x", title="사유"),
    tooltip=["reason", "건수", "비율"])
cc2.altair_chart(chart, use_container_width=True)

st.divider()

# ── 상품별 (옵션·사유 분해) ──
st.subheader("상품별 반품")
by_prod = (ret.groupby(["product_code", "product_name"], as_index=False)
              .agg(반품수량=("qty", "sum"))
              .sort_values("반품수량", ascending=False))
by_prod = add_pct(by_prod, "반품수량")
st.dataframe(by_prod.rename(columns={"product_code": "상품코드", "product_name": "상품명"}),
             width='stretch', hide_index=True)

labels = (by_prod["product_name"].fillna("(이름없음)") + " ["
          + by_prod["product_code"] + "] · 반품 " + by_prod["반품수량"].astype(str)).tolist()
pick = st.selectbox("상품을 골라 옵션·사유를 자세히 보기 (반품 많은 순)", ["(선택)"] + labels)

if pick != "(선택)":
    code = by_prod["product_code"].iloc[labels.index(pick)]
    one = ret[ret["product_code"] == code]

    oc1, oc2 = st.columns(2)
    oc1.markdown("**색상별 반품**")
    by_color = (one.groupby("색상", as_index=False).agg(반품수량=("qty", "sum"))
                   .sort_values("반품수량", ascending=False))
    oc1.dataframe(add_pct(by_color, "반품수량"), width='stretch', hide_index=True)
    oc2.markdown("**사이즈별 반품**")
    by_size = (one.groupby("사이즈", as_index=False).agg(반품수량=("qty", "sum"))
                  .sort_values("반품수량", ascending=False))
    oc2.dataframe(add_pct(by_size, "반품수량"), width='stretch', hide_index=True)

    st.markdown("**옵션별 반품 (색상 × 사이즈)**")
    by_opt = (one.groupby(["색상", "사이즈"], as_index=False).agg(반품수량=("qty", "sum"))
                 .sort_values("반품수량", ascending=False))
    by_opt = add_pct(by_opt, "반품수량")
    st.dataframe(by_opt, width='stretch', hide_index=True)

    st.markdown("**옵션 × 사유** (어떤 옵션이 무슨 사유로 반품됐는지)")
    ct = pd.crosstab(one["옵션"], one["reason"], values=one["qty"],
                     aggfunc="sum", margins=True, margins_name="합계").fillna(0).astype(int)
    ct = ct.sort_values("합계", ascending=False)
    st.dataframe(ct.reset_index(), width='stretch')

st.divider()
with st.expander("반품 원본 내역 보기"):
    st.dataframe(ret[["return_date", "channel", "product_name", "option_name",
                      "reason", "qty", "order_no"]].rename(columns={
                          "return_date": "반품일", "channel": "판매처",
                          "product_name": "상품명", "option_name": "옵션",
                          "reason": "사유", "qty": "수량", "order_no": "주문번호"}),
                 width='stretch', hide_index=True)
