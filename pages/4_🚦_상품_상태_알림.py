"""상품 상태 / 알림 페이지 — 상품 단위로 보고, 상품을 누르면 옵션을 봅니다."""
import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, JsCode

from core import analytics, db
from core.ui import setup_page, sidebar_filters, cached, mall_link

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

products = analytics.product_rollup(overview, settings)
products["홈페이지"] = products["product_name"].map(mall_link)

# 주간 판매 지표(주평균 + 최근 1~4주차)를 상품·옵션 표에 붙임
WEEK_COLS = ["주평균", "1주차", "2주차", "3주차", "4주차"]
prod_week = analytics.weekly_sales(sales, end, ["channel", "product_code"])
products = products.merge(prod_week, on=["channel", "product_code"], how="left")
opt_week = analytics.weekly_sales(sales, end, ["channel", "product_code", "option_name"])
overview = overview.merge(opt_week, on=["channel", "product_code", "option_name"], how="left")
for _df in (products, overview):
    for _c in WEEK_COLS:
        if _c in _df.columns:
            _df[_c] = _df[_c].fillna(0)

# 흐름(추세)·정리 추천 판정 (asof=조회 끝날, 신상·표본 게이트 포함)
products = analytics.product_trend(products, end, settings)
overview = analytics.product_trend(overview, end, settings)

# ── 검색 (상품명·상품코드·추천·추세·알림) — 모든 탭에 적용 ──
SEARCH_COLS = ["product_name", "product_code", "추천", "추세", "알림"]
query = st.text_input("🔎 검색", placeholder="상품명·상품코드·추천·추세로 검색 (예: 삭스, 재입고, 하락)").strip()
if query:
    q = query.lower()
    mask = False
    for c in SEARCH_COLS:
        if c in products.columns:
            mask = mask | products[c].fillna("").astype(str).str.lower().str.contains(q)
    products = products[mask]
    st.caption(f"🔎 '{query}' 검색 결과 {len(products):,}개")


def _verdict(rec):
    """추천 문구 → 한 줄 결론(제목, 설명, 박스색)."""
    table = [
        ("⛔", "⛔ 이제 그만 — 정리 검토", "할인·단종 또는 공급처 교체를 고려하세요.", "error"),
        ("⚠️", "⚠️ 정리 후보", "조금 더 보되, 반등이 없으면 정리하세요.", "warning"),
        ("🌱", "🌱 더 지켜보기", "신상이거나 표본이 적어 아직 판단하기 이릅니다.", "info"),
        ("🔁", "🚀 계속 진행 + 재입고", "잘 나갑니다. 품절 전에 재입고하세요.", "success"),
        ("🔎", "🔎 계속 팔되 점검", "판매는 유지되나 반품 원인을 확인하세요.", "warning"),
        ("✅", "✅ 계속 진행", "성장 중입니다. 그대로 유지하세요.", "success"),
        ("👀", "👀 계속 진행(주의)", "하락세이니 추이를 지켜보세요.", "warning"),
    ]
    for pre, title, desc, box in table:
        if rec.startswith(pre):
            return title, desc, box
    return "· 유지", "특이사항 없이 판매를 유지하세요.", "info"


def _val(row, col, default=0):
    v = row.get(col, default)
    return default if v is None or (isinstance(v, float) and v != v) else v


def show_analysis(row):
    """선택한 상품 한 개에 대한 상세 분석·의견."""
    title, desc, box = _verdict(str(row.get("추천", "")))
    st.markdown(f"### {row['product_name']}  `[{row['product_code']}]`")
    link = row.get("홈페이지") or mall_link(row.get("product_name"))
    if link:
        st.link_button("🔗 쇼핑몰에서 이 상품 보기", link)
    getattr(st, box)(f"**{title}** — {desc}")

    wk = [int(_val(row, c)) for c in ["1주차", "2주차", "3주차", "4주차"]]
    recent, prev = wk[0] + wk[1], wk[2] + wk[3]
    avg = float(_val(row, "주평균"))
    stock = int(_val(row, "stock"))
    rr = _val(row, "return_rate", None)
    chg = _val(row, "변화율", None)
    sell_weeks = round(stock / avg, 1) if avg > 0 else None

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("추세", str(row.get("추세", "-")),
              f"{chg*100:+.0f}%" if chg is not None else None)
    m2.metric("주평균 판매", f"{avg:g}개")
    m3.metric("현재재고", f"{stock}개",
              f"소진 ~{sell_weeks}주" if sell_weeks is not None else "판매 정체")
    m4.metric("반품율", f"{rr*100:.0f}%" if rr is not None else "-")

    lines = [
        f"- **흐름**: 최근 2주 {recent}개 vs 그 전 2주 {prev}개 "
        f"(주간 최근→과거: {wk[0]}·{wk[1]}·{wk[2]}·{wk[3]})",
        f"- **판매**: 누적 {int(_val(row,'total_sold'))}개 · 주평균 {avg:g}개",
        f"- **재고**: {stock}개" + (f" · 지금 속도로 약 {sell_weeks}주면 소진"
                                  if sell_weeks is not None else " · 최근 판매 정체"),
        f"- **마지막 판매**: {int(_val(row,'days_since_sale'))}일 전",
    ]
    if row.get("reg_date"):
        lines.append(f"- **등록일**: {row['reg_date']}")
    if int(_val(row, "option_count")):
        lines.append(f"- **옵션수**: {int(_val(row,'option_count'))}개 "
                     "(상품을 표에서 클릭하면 옵션별로 볼 수 있어요)")
    st.markdown("\n".join(lines))

    todo = []
    if row.get("shortage_flag"):
        todo.append(f"🔁 재입고 검토 (필요수량 약 {_val(row,'need_qty')})")
    if row.get("high_return"):
        todo.append("🔎 반품 사유 확인 → '🔁 반품 분석' 페이지에서 사유 보기")
    if row.get("no_sale_flag"):
        todo.append("📦 재고는 있는데 안 팔림 — 노출/가격/시즌 점검 또는 정리")
    if row.get("정리후보"):
        todo.append("⛔ 정리(할인·단종) 후보 — 이월 손실 전에 결정")
    if todo:
        st.markdown("**할 일**\n" + "\n".join(f"- {t}" for t in todo))


# ── 요약 (상품 개수 기준) ──
c1, c2, c3, c4 = st.columns(4)
c1.metric("🔴 반품율 초과", int(products["high_return"].sum()))
c2.metric("🟠 저판매·고반품", int(products["low_sales_high_return"].sum()))
c3.metric("🟡 무판매", int(products["no_sale_flag"].sum()))
c4.metric("🔵 재고부족", int(products["shortage_flag"].sum()))

# ── 알림 설명 & 판단 기준 (현재 설정값 반영) ──
r = analytics.resolve_settings(settings)
with st.expander("ℹ️ 알림 설명과 판단 기준 보기"):
    st.markdown(
        f"""
| 알림 | 뜻 | 판단 기준 (현재 설정) |
|---|---|---|
| 🔴 **반품율 높음** | 반품(취소)이 많은 상품 | **반품율 ≥ {r['return_rate_flag']*100:.0f}%** (반품율 = 취소수량 ÷ 전체판매수량) |
| 🟠 **저판매·고반품** | 적게 팔리는데 반품까지 잦은 상품 | **기간 판매수 ≤ {r['low_sales_qty']}개** 이면서 **반품율 ≥ {r['low_sales_return_rate']*100:.0f}%** |
| 🟡 **무판매** | 재고는 있는데 한동안 안 팔리는 상품 | 재고 > 0 이면서 **최근 {r['no_sales_days']}일 이상 판매 0** |
| 🔵 **재고부족** | 입고 전에 품절 위험이 있는 상품 | 최근 **{r['velocity_window_days']}일** 평균 판매속도 × **입고기간(기본 {r['default_lead_time_days']}일)** 만큼 필요한 수량이 **현재 재고보다 많을 때** (또는 최소재고 미만) |

- **반품수·반품율**은 판매 파일의 **취소수량** 기준입니다. (반품 파일은 '🔁 반품 분석' 페이지 전용)
- **상품 단위 판정**: 🔴·🟠는 그 상품 합계로 다시 계산하고, 🟡·🔵는 옵션 중 하나라도 해당하면 표시합니다.
- 이 기준값들은 **⚙️ 설정** 페이지에서 바꿀 수 있습니다.

---

#### 📈 흐름(추세)·정리 추천은 이렇게 봅니다
**추세** = 최근 2주(1+2주차)와 그 전 2주(3+4주차)를 비교합니다.

| 표시 | 뜻 |
|---|---|
| 📈 상승 | 최근 2주가 그 전보다 **+20% 이상** 늘었어요 |
| 📉 하락 | 최근 2주가 그 전보다 **-20% 이상** 줄었어요 |
| 〰️ 유지 | 큰 변화 없이 비슷하게 팔려요 |
| 🆕 신규유입 | 예전엔 안 팔리다 최근에 팔리기 시작했어요 |
| ⏸ 판매없음 | 최근 4주간 판매가 없어요 |

**추천(지금 할 일)** — 흐름에 재고·반품을 더해 제안합니다.

| 표시 | 언제 | 의미 |
|---|---|---|
| ⛔ 정리 — 반품율 높음 | **신상 아님 + 누적 {r['reliable_sold_qty']}개↑ 팔림 + 반품율 ≥ {r['discontinue_return_rate']*100:.0f}%** | 그만 팔기(할인·단종·공급처 교체) |
| ⛔ 정리 — 재고 있는데 안 팔림 | 재고 있는데 거의 안 팔림 | 재고 소진·단종 검토 |
| ⚠️ 정리 후보 | 판매 적고(≤{r['low_sales_qty']}개) 하락세 | 정리 고려 |
| 🌱 관찰 중 | **신상(등록 {r['new_product_days']}일 이내)** 또는 **누적 판매 {r['reliable_sold_qty']}개 미만** | 아직 판정 보류, 더 지켜봄 |
| 🔎 반품 점검 | 반품율 경고({r['return_rate_flag']*100:.0f}%↑)지만 정리 기준은 아직 | 사유 확인 |
| 🔁 재입고 | 잘 나가는데(상승) 재고 부족 | 추가 발주 |
| ✅ 성장 중 / 👀 하락 주의 / · 유지 | 그 외 | 모니터링 |

> **왜 신상·표본 보호?** 적게 팔린 상품의 반품율(예: 3개 중 1개=33%)은 우연일 수 있고,
> 갓 올린 상품은 초반 교환이 몰립니다. 그래서 **신상 {r['new_product_days']}일·누적 {r['reliable_sold_qty']}개**를
> 넘긴 상품만 '반품율로 정리' 판정을 합니다. (기준값은 ⚙️ 설정에서 변경)
>
> **🛟 롱테일 보호:** 최근 1주 판매가 **{r['keep_weekly_sold']}장 이상**이면 정리 대상에서 빼서
> 매출에 기여하는 상품을 지킵니다. (반품이 많으면 정리 대신 '🔎 반품 점검'으로 표시)
>
> **🌙 시즌 정리:** 시즌 말엔 목표가 '재고 비우기'로 바뀝니다. **소진주수 = 현재재고 ÷ 최근4주평균**으로,
> 남은 시즌 안에 다 못 팔 상품을 ⚠️할인/⛔떨이로 골라냅니다. ('🌙 시즌 정리' 탭에서 남은 주수 입력)
        """
    )

st.caption("👇 상품 행을 클릭하면 아래에 **옵션별 상세**가 펼쳐지고, "
           "**🔗 보기**를 누르면 쇼핑몰에서 그 상품을 검색합니다.  \n"
           "📅 **1주차**=최근 7일, **2~4주차**=그 직전 주들, "
           "**주평균**=그 상품이 처음 팔린 날부터의 한 주당 평균 판매수입니다.")

PROD_COLS = {
    "channel": "판매처", "product_code": "상품코드", "product_name": "상품명",
    "홈페이지": "홈페이지", "추세": "추세", "변화율": "변화율", "추천": "추천",
    "option_count": "옵션수", "stock": "현재재고",
    "period_sold": "판매수", "period_inbound": "입고수",
    "주평균": "주평균", "1주차": "1주차", "2주차": "2주차", "3주차": "3주차", "4주차": "4주차",
    "최근4주평균": "최근4주평균", "소진주수": "소진주수(주)", "시즌판단": "시즌판단",
    "ret_qty": "반품수(취소)", "return_rate": "반품율", "total_sold": "누적판매",
    "reg_date": "등록일자", "days_since_sale": "무판매일수",
    "lead_time_days": "입고기간", "need_qty": "필요수량", "알림": "알림",
}
OPT_COLS = {
    "option_name": "옵션", "추세": "추세", "변화율": "변화율", "추천": "추천",
    "stock": "현재재고", "period_sold": "판매수", "period_inbound": "입고수",
    "주평균": "주평균", "1주차": "1주차", "2주차": "2주차", "3주차": "3주차", "4주차": "4주차",
    "ret_qty": "반품수(취소)", "return_rate": "반품율", "total_sold": "누적판매",
    "reg_date": "등록일자", "days_since_sale": "무판매일수",
    "lead_time_days": "입고기간", "need_qty": "필요수량", "알림": "알림",
}

# 기본으로 보일 열(나머지는 ⋮ '열' 메뉴에서 켤 수 있음) — 화면을 깔끔하게
CORE_COLS = ["상품명", "홈페이지", "추천", "추세", "변화율",
             "판매수", "주평균", "현재재고", "반품율", "알림"]
SEASON_COLS = ["상품명", "홈페이지", "시즌판단", "소진주수(주)", "최근4주평균",
               "현재재고", "추천"]
# 열 너비(px). 없으면 기본값.
COL_WIDTH = {
    "상품명": 230, "홈페이지": 80, "추천": 220, "추세": 95, "변화율": 80,
    "판매수": 80, "입고수": 80, "주평균": 80, "현재재고": 85, "반품율": 80,
    "알림": 150, "시즌판단": 200, "소진주수(주)": 100, "최근4주평균": 100,
    "1주차": 70, "2주차": 70, "3주차": 70, "4주차": 70, "누적판매": 85,
    "반품수(취소)": 95, "무판매일수": 90, "옵션수": 70, "필요수량": 85,
    "등록일자": 105, "입고기간": 85, "판매처": 90, "상품코드": 90,
}


def _fmt_rate(disp):
    if "반품율" in disp.columns:
        disp["반품율"] = disp["반품율"].apply(
            lambda x: f"{x*100:.0f}%" if x == x and x is not None else "-")
    if "변화율" in disp.columns:
        disp["변화율"] = disp["변화율"].apply(
            lambda x: f"{x*100:+.0f}%" if x == x and x is not None else "-")
    return disp


def show_options_for(channel_v, code, name):
    """선택한 상품의 옵션별 상세 표."""
    opts = overview[(overview["channel"] == channel_v)
                    & (overview["product_code"] == code)]
    st.markdown(f"#### 🧩 {name} · 옵션별 상세 ({len(opts):,}개)")
    cols = [c for c in OPT_COLS if c in opts.columns]
    disp = _fmt_rate(opts[cols].rename(columns=OPT_COLS).copy())
    st.dataframe(disp, width='stretch', hide_index=True)
    st.download_button(
        "⬇️ 이 상품 옵션 내려받기(CSV)", disp.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"옵션_{code}.csv", mime="text/csv", key=f"dlopt_{code}_{channel_v}")


# 홈페이지 링크: 앵커 DOM을 직접 만들어 확실히 클릭되게(행 선택은 막음)
_LINK_RENDERER = JsCode("""
class UrlCellRenderer {
  init(params) {
    const a = document.createElement('a');
    if (params.value) {
      a.innerText = '🔗 보기';
      a.setAttribute('href', params.value);
      a.setAttribute('target', '_blank');
      a.setAttribute('rel', 'noopener');
      a.style.textDecoration = 'underline';
      a.addEventListener('click', e => e.stopPropagation());
    } else {
      a.innerText = '';
    }
    this.eGui = a;
  }
  getGui() { return this.eGui; }
}
""")

# 메뉴/필터 팝업 밖을 클릭하면 닫히게(Esc 전달) — iframe 안에서 동작
_ON_GRID_READY = JsCode("""
function(params){
  document.addEventListener('mousedown', function(ev){
    var t = ev.target;
    var inside = t && t.closest && t.closest(
      '.ag-popup, .ag-menu, .ag-filter, .ag-column-menu, .ag-popup-child, .ag-floating-filter');
    if(!inside){
      document.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape', bubbles:true}));
    }
  }, true);
}
""")

# AgGrid 화면 글자 한글화 (메뉴·필터·페이지네이션)
AG_LOCALE_KR = {
    "contains": "포함", "notContains": "포함 안 함", "equals": "같음",
    "notEqual": "같지 않음", "startsWith": "시작 문자", "endsWith": "끝 문자",
    "blank": "빈 값", "notBlank": "빈 값 아님",
    "lessThan": "작음", "greaterThan": "큼", "lessThanOrEqual": "이하",
    "greaterThanOrEqual": "이상", "inRange": "범위", "inRangeStart": "부터",
    "inRangeEnd": "까지", "filterOoo": "필터…", "searchOoo": "검색…",
    "applyFilter": "적용", "resetFilter": "초기화", "clearFilter": "지우기",
    "cancelFilter": "취소", "andCondition": "그리고", "orCondition": "또는",
    "pinColumn": "열 고정", "pinLeft": "왼쪽 고정", "pinRight": "오른쪽 고정",
    "noPin": "고정 해제", "autosizeThisColumn": "이 열 너비 맞춤",
    "autosizeAllColumns": "모든 열 너비 맞춤", "resetColumns": "열 초기화",
    "sortAscending": "오름차순 정렬", "sortDescending": "내림차순 정렬",
    "sortUnSort": "정렬 해제", "columns": "열", "filters": "필터",
    "noRowsToShow": "표시할 데이터가 없습니다", "loadingOoo": "불러오는 중…",
    "selectAll": "(모두 선택)", "selectAllSearchResults": "(검색결과 모두 선택)",
    "noMatches": "일치 항목 없음", "blanks": "(빈 값)",
    "page": "페이지", "to": "~", "of": "/", "nextPage": "다음", "lastPage": "마지막",
    "firstPage": "처음", "previousPage": "이전", "pageSizeSelectorLabel": "페이지당:",
}


def show_products(pdf, fname, key, drop_alert=False, primary=None):
    """상품 단위 표(엑셀형 정렬·필터 + 행 클릭 시 옵션 펼침) + CSV 다운로드."""
    if pdf.empty:
        st.caption("해당하는 상품이 없습니다. 👍")
        return
    pdf = pdf.reset_index(drop=True)
    cols = [c for c in PROD_COLS if c in pdf.columns and not (drop_alert and c == "알림")]
    disp = _fmt_rate(pdf[cols].rename(columns=PROD_COLS).copy())
    primary = primary or CORE_COLS
    st.caption(f"{len(disp):,}개 상품 · 열 제목 **⋮**로 필터/정렬, **‘열’** 메뉴로 숨은 항목 켜기. "
               "왼쪽 **체크박스**로 고르면 그것만 다운로드되고, **하나만 체크**하면 옵션이 펼쳐집니다.")

    gb = GridOptionsBuilder.from_dataframe(disp)
    # 엑셀식 체크박스 목록 필터(Set Filter) + 제목 줄바꿈으로 안 잘리게
    gb.configure_default_column(
        filter="agSetColumnFilter", sortable=True, resizable=True,
        floatingFilter=True, width=95, wrapHeaderText=True, autoHeaderHeight=True,
        filterParams={"buttons": ["reset"], "excelMode": "windows"},
        menuTabs=["filterMenuTab", "generalMenuTab", "columnsMenuTab"])
    gb.configure_selection("multiple", use_checkbox=False,
                           suppressRowClickSelection=True)
    gb.configure_pagination(enabled=True, paginationAutoPageSize=False,
                            paginationPageSize=25)
    gb.configure_grid_options(localeText=AG_LOCALE_KR, onGridReady=_ON_GRID_READY)
    for c in disp.columns:
        if c == "홈페이지":
            continue
        gb.configure_column(c, filter="agSetColumnFilter", floatingFilter=True,
                            width=COL_WIDTH.get(c, 95),
                            hide=(c not in primary))
    if "상품명" in disp.columns:
        gb.configure_column("상품명", pinned="left", width=COL_WIDTH["상품명"] + 40,
                            hide=False, filter="agSetColumnFilter", floatingFilter=True,
                            checkboxSelection=True, headerCheckboxSelection=True,
                            headerCheckboxSelectionFilteredOnly=True)
    if "홈페이지" in disp.columns:
        gb.configure_column("홈페이지", cellRenderer=_LINK_RENDERER, filter=False,
                            floatingFilter=False, sortable=False, suppressMenu=True,
                            width=COL_WIDTH["홈페이지"], hide=("홈페이지" not in primary))
    grid = AgGrid(
        disp, gridOptions=gb.build(), height=500, theme="streamlit",
        update_mode=GridUpdateMode.SELECTION_CHANGED, allow_unsafe_jscode=True,
        fit_columns_on_grid_load=False, enable_enterprise_modules=True, key=key)

    # 체크된 행만 다운로드(없으면 전체)
    sel = grid.get("selected_rows")
    sel_df = None
    if sel is not None:
        if hasattr(sel, "empty"):
            sel_df = sel if not sel.empty else None
        elif len(sel):
            sel_df = pd.DataFrame(sel)
    if sel_df is not None and len(sel_df):
        out = sel_df[[c for c in disp.columns if c in sel_df.columns]]
        st.download_button(f"⬇️ 체크한 {len(out):,}개만 내려받기(CSV)",
                           out.to_csv(index=False).encode("utf-8-sig"),
                           file_name=fname, mime="text/csv", key=f"dl_{key}")
    else:
        st.download_button(f"⬇️ 전체 {len(disp):,}개 내려받기(CSV) · 체크하면 그것만 받아요",
                           disp.to_csv(index=False).encode("utf-8-sig"),
                           file_name=fname, mime="text/csv", key=f"dl_{key}")

    # 한 개만 체크하면 → 아래 '분석할 상품 선택'을 그 상품으로 바꾸고 옵션 펼침
    if sel_df is not None and len(sel_df) == 1:
        row = sel_df.iloc[0]
        nm = row["상품명"] if isinstance(row["상품명"], str) and row["상품명"] else "(이름없음)"
        st.session_state["analyze_box"] = f"{nm}  [{row['상품코드']}]"
        show_options_for(row["판매처"], row["상품코드"], row["상품명"])


# ── 보기 선택 (탭 대신 단일 표 — 숨은 탭의 0너비로 표가 잘리는 문제 방지) ──
VIEW_LABELS = ["📋 전체", "📈 흐름·추세", "⛔ 정리 추천", "🌱 관찰 중", "🌙 시즌 정리",
               "🔴 반품율 높음", "🟠 저판매·고반품", "🟡 무판매", "🔵 재고부족"]
view = st.radio("보기 선택", VIEW_LABELS, horizontal=True,
                label_visibility="collapsed", key="view_sel") or VIEW_LABELS[0]
key = f"grid_{VIEW_LABELS.index(view)}"

if view == "📋 전체":
    show_products(products[products["알림"] != ""], "상품상태_전체.csv", key)
elif view == "📈 흐름·추세":
    st.caption("📈 상승부터 📉 하락까지 — **변화율(최근 2주 vs 그 전 2주)** 높은 순으로 모든 상품을 봅니다.")
    flow = products.sort_values("변화율", ascending=False, na_position="last")
    show_products(flow, "상품흐름.csv", key)
elif view == "⛔ 정리 추천":
    st.caption("⛔/⚠️ **그만 팔지(할인·단종) 검토** 후보입니다. 반품 많은 상품은 "
               "**신상 보호기간·표본수**를 통과한 것만 여기 올라옵니다.")
    show_products(products[products["정리후보"]], "정리추천.csv", key)
elif view == "🌱 관찰 중":
    st.caption("🌱 아직 판정하기 이른 상품 — **신상(등록 후 보호기간 이내)**이거나 "
               "**누적 판매가 적어 반품율을 믿기 어려운** 상품입니다. 좀 더 지켜보세요.")
    show_products(products[products["관찰중"]], "관찰중.csv", key)
elif view == "🌙 시즌 정리":
    st.caption("🌙 시즌 말 재고 비우기용 — **지금 판매 속도로 재고를 몇 주면 비우나(소진주수)**로 판단합니다. "
               "안 비우면 이월(죽은 재고)될 상품을 찾습니다.")
    sc1, sc2 = st.columns([1, 2])
    weeks_left = sc1.number_input("남은 시즌 주수", 1, 52, 4, key="season_weeks")
    only_risk = sc2.checkbox("정리·할인 대상만 보기(✅ 소진 가능 숨기기)", value=True,
                             key="season_only_risk")
    season = analytics.season_clearance(products, weeks_left, settings)
    if only_risk:
        season = season[season["시즌정리후보"]]
    season = season.sort_values("소진주수", ascending=False, na_position="first")
    show_products(season, "시즌정리.csv", key, primary=SEASON_COLS)
elif view == "🔴 반품율 높음":
    show_products(products[products["high_return"]], "반품율높음.csv", key, drop_alert=True)
elif view == "🟠 저판매·고반품":
    show_products(products[products["low_sales_high_return"]], "저판매_고반품.csv",
                  key, drop_alert=True)
elif view == "🟡 무판매":
    show_products(products[products["no_sale_flag"]], "무판매.csv", key, drop_alert=True)
elif view == "🔵 재고부족":
    show_products(products[products["shortage_flag"]], "재고부족.csv", key, drop_alert=True)

# ── 🔬 상품 상세 분석 (표에서 체크하면 자동 선택됨) ──
st.divider()
st.subheader("🔬 상품 상세 분석")
if products.empty:
    st.caption("검색 결과가 없습니다. 다른 검색어를 넣어보세요.")
else:
    opts = products.copy()
    opts["_label"] = (opts["product_name"].fillna("(이름없음)")
                      + "  [" + opts["product_code"].astype(str) + "]")
    labels = opts["_label"].tolist()
    # 저장된 선택이 현재 목록에 없으면(검색/필터 변경) 초기화 → selectbox 오류 방지
    if st.session_state.get("analyze_box") not in labels:
        st.session_state.pop("analyze_box", None)
    sel = st.selectbox("분석할 상품 선택 (위 표에서 체크해도 바뀝니다)", labels,
                       key="analyze_box")
    if sel:
        show_analysis(opts[opts["_label"] == sel].iloc[0])
