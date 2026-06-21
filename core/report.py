"""반품 분석 Word(.docx) 보고서 생성 — 규칙기반(외부 AI 미사용).

선택한 상품 단위로 2종:
- build_reason_report : 반품 사유별 표 + 진단 + 액션 우선순위
- build_size_report   : 사이즈 × 사유 교차표(10/20건 강조) + 사이즈별 진단 + 5단계 액션
입력 df 컬럼: reason, qty, 사이즈, (product_name)
"""
import io

import pandas as pd
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

# 반품 사유 그룹 → (키워드, 진단 문장, 권장 조치)
GROUPS = {
    "사이즈": (["사이즈", "커요", "작아요", "크다", "작다", "크기"],
             "사이즈 관련 반품이 많습니다.",
             "상세페이지 실측 사이즈표·핏 안내(정사이즈/크게/작게) 보강"),
    "색상/화면": (["색상", "화면", "사진", "컬러"],
               "실물과 화면 색상 차이로 인한 반품이 많습니다.",
               "자연광 실촬영·색보정 점검, 색상별 실물컷 추가"),
    "소재/품질": (["원단", "소재", "비침", "하자", "불량", "얇", "두께"],
               "소재·품질 관련 반품이 많습니다.",
               "입고 검수 강화, 소재(두께·비침) 정보 상세 표기"),
    "디자인/핏": (["디자인", "착용감", "어울", "핏"],
               "디자인·착용감 관련 반품이 많습니다.",
               "착용컷·디테일컷 보강으로 기대치 정렬"),
    "상세설명": (["상세", "상이", "설명"],
              "상세설명과 실제가 다르다는 반품이 있습니다.",
              "상세페이지 정보 정확성 점검"),
    "단순변심": (["변심", "필요", "잘못", "오주문", "다시", "안어울"],
              "단순 변심 반품입니다.",
              "구매 전 정보 제공 강화(직접 개선은 제한적)"),
}
RED, ORANGE, INDIGO = "F8C9C9", "FCE2B5", "4F46E5"


def classify(reason):
    r = str(reason or "")
    for g, (kws, _, _) in GROUPS.items():
        if any(k in r for k in kws):
            return g
    return "기타"


def _shade(cell, color):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), color)
    tcPr.append(shd)


def _set(cell, text, *, header=False, shade=None):
    cell.text = str(text)
    run = cell.paragraphs[0].runs[0] if cell.paragraphs[0].runs else \
        cell.paragraphs[0].add_run("")
    run.font.size = Pt(9)
    if header:
        run.font.bold = True
        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        _shade(cell, INDIGO)
    elif shade:
        _shade(cell, shade)


def _table(doc, headers):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    for i, h in enumerate(headers):
        _set(t.rows[0].cells[i], h, header=True)
    return t


def _save(doc):
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()


def _group_sums(df):
    g = df.copy()
    g["_g"] = g["reason"].map(classify)
    return g.groupby("_g")["qty"].sum().sort_values(ascending=False)


def build_reason_report(product_name, df):
    total = int(df["qty"].sum()) if not df.empty else 0
    doc = Document()
    doc.add_heading("반품 현황 분석 — 상품별", level=0)
    doc.add_heading(str(product_name), level=1)
    doc.add_paragraph(f"총 반품 건수: {total:,}건 · 반품 사유 {df['reason'].nunique()}종")

    doc.add_heading("반품 사유별", level=2)
    by = (df.groupby("reason", as_index=False).agg(건수=("qty", "sum"))
            .sort_values("건수", ascending=False))
    t = _table(doc, ["반품 사유", "건수", "비율"])
    for _, r in by.iterrows():
        cnt = int(r["건수"])
        c = t.add_row().cells
        _set(c[0], r["reason"])
        _set(c[1], f"{cnt:,}", shade=(RED if cnt >= 20 else ORANGE if cnt >= 10 else None))
        _set(c[2], f"{cnt / total * 100:.1f}%" if total else "-")

    doc.add_heading("진단 코멘트", level=2)
    gsum = _group_sums(df)
    for g, cnt in gsum.head(3).items():
        if g in GROUPS:
            _, diag, act = GROUPS[g]
            doc.add_paragraph(f"[{g}] {diag} ({int(cnt):,}건) → {act}", style="List Bullet")
    if (gsum.index == "기타").any():
        doc.add_paragraph("[기타] 분류되지 않은 사유는 개별 검토가 필요합니다.", style="List Bullet")

    doc.add_heading("액션 우선순위", level=2)
    at = _table(doc, ["우선순위", "항목", "권장 조치"])
    for i, (g, _cnt) in enumerate(gsum.head(5).items(), 1):
        act = GROUPS.get(g, (None, None, "개별 모니터링"))[2]
        c = at.add_row().cells
        _set(c[0], i); _set(c[1], g); _set(c[2], act)
    return _save(doc)


def build_size_report(product_name, df):
    doc = Document()
    doc.add_heading("반품 현황 분석 — 사이즈별", level=0)
    doc.add_heading(str(product_name), level=1)

    doc.add_heading("사이즈 × 사유 교차표", level=2)
    ct = (pd.crosstab(df["사이즈"], df["reason"], values=df["qty"], aggfunc="sum",
                      margins=True, margins_name="합계").fillna(0).astype(int)
          .sort_values("합계", ascending=False))
    cols = list(ct.columns)
    t = _table(doc, ["사이즈"] + [str(c) for c in cols])
    for idx, row in ct.iterrows():
        cells = t.add_row().cells
        _set(cells[0], idx, header=(idx == "합계"))
        for i, c in enumerate(cols, 1):
            v = int(row[c])
            _set(cells[i], f"{v:,}" if v else "-",
                 shade=(RED if v >= 20 else ORANGE if v >= 10 else None))
    doc.add_paragraph("※ 10건 이상 주황, 20건 이상 빨강으로 강조했습니다.")

    doc.add_heading("사이즈별 진단", level=2)
    by_size = df.groupby("사이즈")["qty"].sum().sort_values(ascending=False)
    for sz, cnt in by_size.head(8).items():
        sub = df[df["사이즈"] == sz]
        topr = sub.groupby("reason")["qty"].sum().sort_values(ascending=False)
        reason = topr.index[0] if len(topr) else "-"
        act = GROUPS.get(classify(reason), (None, None, "개별 점검"))[2]
        doc.add_paragraph(f"[{sz}] {int(cnt):,}건 · 주요 사유 '{reason}' → {act}",
                          style="List Bullet")

    doc.add_heading("액션 플랜 (5단계)", level=2)
    steps = [
        ("1. 진단", "반품 사유·사이즈 집중 구간 파악 (본 보고서)"),
        ("2. 상세페이지", "실측 사이즈표·핏 안내·실물컷 보강"),
        ("3. 검수", "입고 검수 및 소재(두께·비침) 정보 표기 강화"),
        ("4. CS", "반품 사유 태깅·반복 항목 주간 모니터링"),
        ("5. 재발방지", "상위 사유 개선 후 반품율 추적·검증"),
    ]
    at = _table(doc, ["단계", "내용"])
    for s, d in steps:
        c = at.add_row().cells
        _set(c[0], s); _set(c[1], d)
    return _save(doc)
