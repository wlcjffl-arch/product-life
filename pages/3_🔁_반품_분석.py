"""반품 분석 페이지."""
import altair as alt
import pandas as pd
import streamlit as st

from core import db, ingest, report
from core.ui import setup_page, sidebar_filters, cached

setup_page("반품 분석", "🔁")
st.title("🔁 반품 분석")

channel, start, end = sidebar_filters("returns")
ret = cached(("returns", channel, start, end),
             lambda: db.load_returns(channel, start, end))

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

    st.markdown("**옵션 × 사유 (요약)** — 사유를 6개 그룹으로 묶어 한눈에. 색이 진할수록 반품 많음 "
                "(🟪 1+ · 🟧 10+ · 🟥 20+).")
    one_g = one.assign(사유그룹=one["reason"].map(report.classify))
    ctg = (pd.crosstab(one_g["옵션"], one_g["사유그룹"], values=one_g["qty"], aggfunc="sum",
                       margins=True, margins_name="합계").fillna(0).astype(int)
           .sort_values("합계", ascending=False))

    def _hl(v):
        if v >= 20:
            return "background-color:#F8C9C9"
        if v >= 10:
            return "background-color:#FCE2B5"
        if v >= 1:
            return "background-color:#EFEBFF"
        return ""

    sty = ctg.style
    sty = (sty.map if hasattr(sty, "map") else sty.applymap)(_hl)
    st.dataframe(sty, width='stretch')

    with st.expander("사유 전체(원문) 교차표 보기"):
        ct = (pd.crosstab(one["옵션"], one["reason"], values=one["qty"], aggfunc="sum",
                          margins=True, margins_name="합계").fillna(0).astype(int)
              .sort_values("합계", ascending=False))
        st.dataframe(ct.reset_index(), width='stretch')

    # ── 자동 진단 & 액션 (화면 표시, 규칙기반) ──
    st.divider()
    st.markdown("### 📋 자동 진단 & 액션")
    diag = report.diagnose(one, top=4)
    if diag:
        for g, d, act, cnt in diag:
            st.markdown(f"- **[{g}]** {d} ({cnt:,}건) → {act}")
    else:
        st.caption("진단할 주요 사유가 없습니다.")

    ac1, ac2 = st.columns(2)
    ac1.markdown("**액션 우선순위**")
    ap = pd.DataFrame(report.action_priorities(one),
                      columns=["우선순위", "항목", "권장 조치", "건수"])
    ac1.dataframe(ap, width='stretch', hide_index=True)
    ac2.markdown("**5단계 액션 플랜**")
    ac2.dataframe(pd.DataFrame(report.ACTION_PLAN, columns=["단계", "내용"]),
                  width='stretch', hide_index=True)

    with st.expander("사이즈별 진단 보기"):
        sd = report.size_diagnosis(one)
        if sd:
            for sz, cnt, reason, act in sd:
                st.markdown(f"- **{sz}** {cnt:,}건 · 주요 사유 '{reason}' → {act}")
        else:
            st.caption("사이즈 데이터가 없습니다.")

    # ── Word 보고서 (내부 공유용) ──
    st.markdown("**📄 보고서 내려받기 (Word · 위 내용과 동일)**")
    pname = (one["product_name"].dropna().iloc[0]
             if one["product_name"].notna().any() else pick.split(" [")[0])
    rc1, rc2 = st.columns(2)
    rc1.download_button(
        "📄 상품별 분석 (.docx)", report.build_reason_report(pname, one),
        file_name=f"반품현황분석_상품별_{code}.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        key="rep_reason")
    rc2.download_button(
        "📄 사이즈별 분석 (.docx)", report.build_size_report(pname, one),
        file_name=f"반품현황분석_사이즈별_{code}.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        key="rep_size")

st.divider()
with st.expander("반품 원본 내역 보기"):
    st.dataframe(ret[["return_date", "channel", "product_name", "option_name",
                      "reason", "qty", "order_no"]].rename(columns={
                          "return_date": "반품일", "channel": "판매처",
                          "product_name": "상품명", "option_name": "옵션",
                          "reason": "사유", "qty": "수량", "order_no": "주문번호"}),
                 width='stretch', hide_index=True)
