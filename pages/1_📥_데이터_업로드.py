"""데이터 업로드 페이지."""
import streamlit as st

from core import config, db, ingest, store
from core.ui import setup_page

setup_page("데이터 업로드", "📥")
store.ready()
st.title("📥 데이터 업로드")
st.caption("판매 분석 파일(엑셀/CSV)과 반품 파일을 올립니다. 같은 날짜·주문은 자동으로 합쳐집니다.")

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

up = st.file_uploader("파일 선택", type=["xlsx", "xls", "csv"])
if up is None:
    st.info("파일을 끌어다 놓거나 클릭해서 선택하세요.")
    st.stop()

data = up.getvalue()
try:
    raw = ingest.read_raw(data, up.name)
except Exception as e:
    st.error(f"파일을 읽지 못했습니다: {e}")
    st.stop()

raw.columns = [str(c).strip() for c in raw.columns]
ftype = ingest.detect_file_type(raw)

c1, c2 = st.columns(2)
c1.metric("읽은 행 수", f"{len(raw):,}")
c2.metric("자동 인식 종류", {"sales": "판매 분석 파일", "returns": "반품 파일"}.get(ftype, "알 수 없음"))

ftype = st.radio("파일 종류", ["sales", "returns"],
                 index=0 if ftype != "returns" else 1, horizontal=True,
                 format_func=lambda x: "판매 분석 파일" if x == "sales" else "반품 파일")

# ── 판매처 결정 ──
if ftype == "sales":
    existing = store.list_channels()
    pick = st.selectbox("판매처 선택", ["+ 새로 입력"] + existing)
    channel = st.text_input("판매처 이름", value="" if pick == "+ 새로 입력" else pick).strip()
    st.caption("💡 반품율이 정확히 연결되려면 판매처 이름을 **반품 파일의 '판매처명'과 똑같이** "
               "맞춰주세요. (예: 퀸잇, 카페24)")
    aliases = config.SALES_FIELD_ALIASES
else:
    channel = "(파일 안의 판매처명 사용)"
    aliases = config.RETURNS_FIELD_ALIASES

# ── 컬럼 매핑 ──
saved = db.load_column_map(channel if ftype == "sales" else "_returns_", ftype)
auto = ingest.auto_map(raw.columns, aliases, saved)

st.subheader("컬럼 연결 확인")
st.caption("자동으로 연결했습니다. 틀린 항목만 바꿔주세요. (날짜별 판매/입고 열은 자동 처리됩니다.)")
options = ["(없음)"] + list(raw.columns)
mapping = {}
cols = st.columns(3)
for i, field in enumerate(aliases):
    cur = auto.get(field)
    idx = options.index(cur) if cur in options else 0
    mapping[field] = cols[i % 3].selectbox(
        FIELD_LABELS.get(field, field), options, index=idx, key=f"map_{field}")
mapping = {k: (v if v != "(없음)" else None) for k, v in mapping.items()}

with st.expander("원본 미리보기 (상위 5행)"):
    st.dataframe(raw.head(), width='stretch')

# ── 저장 ──
disabled = ftype == "sales" and not channel
if disabled:
    st.warning("판매처 이름을 입력하세요.")

if st.button("💾 저장 (누적)", type="primary", disabled=disabled):
    if ftype == "sales":
        sales_long, snap = ingest.build_sales(raw, mapping, channel)
        ins, upd = db.upsert_sales_daily(sales_long)
        db.save_snapshot(snap)
        db.save_column_map(channel, ftype, mapping)
        dmin = sales_long["sale_date"].min() if not sales_long.empty else "-"
        dmax = sales_long["sale_date"].max() if not sales_long.empty else "-"
        st.success(f"✅ 판매 데이터 저장 완료 — 추가 {ins:,}건 / 갱신 {upd:,}건 "
                   f"(기간 {dmin} ~ {dmax}), 상품 스냅샷 {len(snap):,}건")
    else:
        rdf = ingest.build_returns(raw, mapping)
        ins, upd = db.upsert_returns(rdf)
        db.save_column_map("_returns_", ftype, mapping)
        dmin = rdf["return_date"].dropna().min() if not rdf.empty else "-"
        dmax = rdf["return_date"].dropna().max() if not rdf.empty else "-"
        chans = ", ".join(sorted(rdf["channel"].dropna().unique())[:8])
        st.success(f"✅ 반품 데이터 저장 완료 — 추가 {ins:,}건 / 갱신 {upd:,}건 "
                   f"(기간 {dmin} ~ {dmax})\n\n판매처: {chans}")
    store.clear()   # 캐시 비우기 → 다른 페이지에 새 데이터 즉시 반영
    st.balloons()
