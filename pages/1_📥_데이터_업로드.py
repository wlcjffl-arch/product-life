"""데이터 업로드 페이지 — 판매 파일 / 반품 파일 업로드 자리를 따로 분리."""
import streamlit as st

from core import config, db, ingest
from core.ui import setup_page, ensure_db, cached, clear_cache

setup_page("데이터 업로드", "📥")
ensure_db()
st.title("📥 데이터 업로드")
st.caption("판매 분석 파일과 반품 파일을 각각 올립니다. 같은 날짜·주문은 자동으로 합쳐집니다.")

FIELD_LABELS = {
    "product_code": "상품코드", "product_name": "상품명", "barcode": "바코드번호",
    "buy_name": "사입상품명", "category": "상품분류명", "origin": "제조국(메모2)",
    "supplier": "공급처명", "supplier_tel": "공급처연락처", "option_name": "옵션명",
    "reg_date": "등록일자", "cost": "원가", "sale_price": "판매단가", "amount": "금액",
    "total_sold": "판매합계수량", "total_inbound": "입고합계수량", "stock": "현재재고",
    "unshipped": "미발송수", "canceled": "취소수량",
    "channel": "판매처명", "qty": "반품수량", "return_date": "반품(회수)일",
    "order_no": "주문번호", "reason": "반품사유", "cs_type": "CS유형",
    "channel_name": "판매처상품명",
}


def read_uploaded(up):
    """업로드 파일 → (정제된 DataFrame, 오류메시지). 실패 시 (None, msg)."""
    try:
        raw = ingest.read_raw(up.getvalue(), up.name)
    except Exception as e:
        return None, f"파일을 읽지 못했습니다: {e}"
    raw.columns = [str(c).strip() for c in raw.columns]
    return raw, None


def mapping_ui(raw, aliases, saved, key_prefix):
    """컬럼 자동매핑 + 수정 UI. 표준필드→실제컬럼 dict 반환."""
    auto = ingest.auto_map(raw.columns, aliases, saved)
    st.markdown("**컬럼 연결 확인** — 자동 연결했습니다. 틀린 항목만 바꿔주세요. "
                "(날짜별 판매/입고 열은 자동 처리)")
    options = ["(없음)"] + list(raw.columns)
    mapping = {}
    cols = st.columns(3)
    for i, field in enumerate(aliases):
        cur = auto.get(field)
        idx = options.index(cur) if cur in options else 0
        mapping[field] = cols[i % 3].selectbox(
            FIELD_LABELS.get(field, field), options, index=idx,
            key=f"{key_prefix}_map_{field}")
    mapping = {k: (v if v != "(없음)" else None) for k, v in mapping.items()}
    with st.expander("원본 미리보기 (상위 5행)"):
        st.dataframe(raw.head(), width='stretch')
    return mapping


tab_sales, tab_returns = st.tabs(["📦 판매 분석 파일", "🔁 반품 파일"])

# ─────────────────────────── 판매 파일 ───────────────────────────
with tab_sales:
    st.caption("일자별 판매·입고·재고가 들어 있는 파일. **판매 흐름**과 **상품 상태/알림**의 데이터가 됩니다.")
    existing = cached(("channels",), db.list_channels)
    pick = st.selectbox("판매처 선택", ["+ 새로 입력"] + existing, key="s_pick")
    channel = st.text_input("판매처 이름",
                            value="" if pick == "+ 새로 입력" else pick, key="s_chan").strip()
    st.caption("💡 반품율이 정확히 연결되려면 판매처 이름을 **반품 파일의 '판매처명'과 똑같이** 맞춰주세요. (예: 퀸잇, 카페24)")

    up = st.file_uploader("판매 분석 파일 선택", type=["xlsx", "xls", "csv"], key="s_up")
    if up is not None:
        raw, err = read_uploaded(up)
        if err:
            st.error(err)
        else:
            st.metric("읽은 행 수", f"{len(raw):,}")
            saved = db.load_column_map(channel, "sales") if channel else {}
            mapping = mapping_ui(raw, config.SALES_FIELD_ALIASES, saved, "s")
            if not channel:
                st.warning("판매처 이름을 입력하세요.")
            if st.button("💾 판매 데이터 저장 (누적)", type="primary",
                         disabled=not channel, key="s_save"):
                sales_long, snap = ingest.build_sales(raw, mapping, channel)
                ins, upd = db.upsert_sales_daily(sales_long)
                db.save_snapshot(snap)
                db.save_column_map(channel, "sales", mapping)
                dmin = sales_long["sale_date"].min() if not sales_long.empty else "-"
                dmax = sales_long["sale_date"].max() if not sales_long.empty else "-"
                clear_cache()
                st.success(f"✅ 저장 완료 — 추가 {ins:,}건 / 갱신 {upd:,}건 "
                           f"(기간 {dmin} ~ {dmax}), 상품 {len(snap):,}건")
                st.balloons()

# ─────────────────────────── 반품 파일 ───────────────────────────
with tab_returns:
    st.caption("반품 내역이 들어 있는 파일. **반품 분석**의 데이터가 됩니다. (판매처는 파일 안의 '판매처명' 사용)")
    up = st.file_uploader("반품 파일 선택", type=["xlsx", "xls", "csv"], key="r_up")
    if up is not None:
        raw, err = read_uploaded(up)
        if err:
            st.error(err)
        else:
            st.metric("읽은 행 수", f"{len(raw):,}")
            saved = db.load_column_map("_returns_", "returns")
            mapping = mapping_ui(raw, config.RETURNS_FIELD_ALIASES, saved, "r")
            if st.button("💾 반품 데이터 저장 (누적)", type="primary", key="r_save"):
                rdf = ingest.build_returns(raw, mapping)
                ins, upd = db.upsert_returns(rdf)
                db.save_column_map("_returns_", "returns", mapping)
                dmin = rdf["return_date"].dropna().min() if not rdf.empty else "-"
                dmax = rdf["return_date"].dropna().max() if not rdf.empty else "-"
                chans = ", ".join(sorted(rdf["channel"].dropna().unique())[:8])
                clear_cache()
                st.success(f"✅ 저장 완료 — 추가 {ins:,}건 / 갱신 {upd:,}건 "
                           f"(기간 {dmin} ~ {dmax})\n\n판매처: {chans}")
                st.balloons()
