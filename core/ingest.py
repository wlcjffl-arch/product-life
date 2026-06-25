"""
업로드한 엑셀/CSV 파일을 읽어서 표준 형태로 바꾸는 모듈.

처리하는 일:
- CSV 인코딩 자동 감지 (CP949 / UTF-8)
- 엑셀 텍스트수식  ="9579"  →  9579  로 풀기
- 콤마 숫자  8,000  →  8000
- 컬럼 이름 자동 매핑 (채널마다 달라도 별칭 사전으로 대응)
- 판매 파일의 날짜별 '판매'/'입고' 열을 한 줄씩(long)으로 펼치기
- 옵션 표기 정규화 (반품↔판매 옵션 매칭용)
"""
import io
import re
from datetime import datetime

import pandas as pd

from . import config

DATE_RE = re.compile(r"(\d{4})[-./](\d{2})[-./](\d{2})")

# 옵션에서 색상/사이즈를 뽑아내기 위한 패턴들
_LABEL_COLOR = re.compile(r"(?:색상|색깔|컬러|칼라|color|colour)\s*[=:]\s*([^/,，、;|]+)", re.I)
_LABEL_SIZE = re.compile(r"(?:사이즈|싸이즈|size)\s*[=:]\s*([^/,，、;|]+)", re.I)
_OPT_JUNK = re.compile(r"\[[^\]]*\]|\(\s*\d+\s*개\s*\)|\d+\s*개")   # [1], (1개), 1개
_OPT_SPLIT = re.compile(r"[\/,，、;|:]")
# 사이즈로 인정하는 토큰: 영문사이즈 / 숫자(44~110 등) / FREE류 / XL(66)·D0 등
_SIZE_TOKEN = re.compile(
    r"^(?:XS|S|M|L|XL|XXL|XXXL|XXXXL|[2-9]XL|"
    r"FREE|FR|F|프리|프리사이즈|원사이즈|onesize|one ?size|"
    r"\d{1,3}|[A-Z]{1,4}\(\d+\)|\d{1,3}\([A-Za-z0-9]+\)|[A-Z]\d{1,2}|\d{1,3}호)$", re.I)


# ─────────────────────────── 파일 읽기 ───────────────────────────

def read_raw(data: bytes, filename: str) -> pd.DataFrame:
    """업로드 바이트 + 파일명 → 모든 값을 문자열로 읽은 DataFrame.

    실제 엑셀이 아닌데 .xls/.xlsx 로 저장된 파일(탭구분 텍스트·HTML 표)도 처리.
    한국 쇼핑몰 취소/반품 내역에 흔함."""
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xls")):
        try:
            return pd.read_excel(io.BytesIO(data), dtype=str)   # 진짜 엑셀
        except Exception:
            pass   # 가짜 엑셀 → 아래 텍스트 처리로

    text = _decode(data)
    head = text[:3000].lower()
    if "<table" in head or "<html" in head:        # HTML 표를 .xls로 저장한 경우
        try:
            tables = pd.read_html(io.StringIO(text))
            if tables:
                return tables[0].astype(str)
        except Exception:
            pass
    # 구분자 자동 감지 (탭 vs 쉼표)
    first = text.split("\n", 1)[0]
    sep = "\t" if first.count("\t") > first.count(",") else ","
    return pd.read_csv(io.StringIO(text), sep=sep, dtype=str, keep_default_na=False)


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp949", "euc-kr", "utf-8"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    try:
        from charset_normalizer import from_bytes
        best = from_bytes(data).best()
        if best is not None:
            return str(best)
    except Exception:
        pass
    return data.decode("utf-8", errors="replace")


# ─────────────────────── 파일 종류 / 컬럼 매핑 ───────────────────────

def detect_file_type(df: pd.DataFrame):
    cols = set(df.columns)
    if all(c in cols for c in config.RETURNS_SIGNATURE):
        return "returns"
    if all(c in cols for c in config.SALES_SIGNATURE):
        return "sales"
    return None


def auto_map(columns, aliases, saved_map=None):
    """표준필드 → 실제컬럼 매핑을 자동 추정. 저장된 맵을 우선 사용."""
    saved_map = saved_map or {}
    cols = list(columns)
    mapping = {}
    for field, candidates in aliases.items():
        chosen = None
        if saved_map.get(field) in cols:
            chosen = saved_map[field]
        else:
            for cand in candidates:
                if cand in cols:
                    chosen = cand
                    break
        mapping[field] = chosen
    return mapping


# ─────────────────────────── 값 정제 ───────────────────────────

def clean_text(v):
    if v is None:
        return None
    s = str(v).strip()
    if s == "" or s.lower() == "nan":
        return None
    m = re.match(r'^="?(.*?)"?$', s)   # ="9579" → 9579
    if m:
        s = m.group(1).strip()
    return s or None


def to_number(v):
    s = clean_text(v)
    if s is None:
        return 0
    s = s.replace(",", "").replace("%", "")
    try:
        f = float(s)
        return int(f) if f == int(f) else f
    except ValueError:
        return 0


def parse_date(v):
    """다양한 날짜 표기 → 'YYYY-MM-DD' 문자열. 실패 시 None."""
    if v is None:
        return None
    if isinstance(v, (datetime, pd.Timestamp)):
        return v.strftime("%Y-%m-%d")
    s = str(v).strip()
    m = DATE_RE.search(s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


def _norm_size(sz):
    sz = (sz or "").strip()
    if re.fullmatch(r"[a-zA-Z]+(?:\(\d+\))?", sz):   # 영문 사이즈는 대문자로
        sz = sz.upper()
    if sz.upper() in ("F", "FR", "프리", "프리사이즈", "원사이즈", "ONESIZE", "ONE SIZE"):
        sz = "FREE"
    return sz


_PAREN_EN = re.compile(r"\(\s*[A-Za-z][^)]*\)")   # 영문 괄호 (Black), (Ivory) …
_NUM_PREFIX = re.compile(r"^\s*\d+\s*[.)]\s*")     # 앞 번호  "2." "1)"
_QTY_PAREN = re.compile(r"\(\s*\d+\s*개?\s*\)|\d+\s*개")  # (5개), 3개


def _clean_color(c):
    """색상명 정제: 영문 번역괄호·앞번호·수량 제거 → 같은 색끼리 묶이게.
    (한글 세부 괄호 '베이지(살구)' 는 다른 색이라 유지)"""
    c = _PAREN_EN.sub("", str(c))
    c = _QTY_PAREN.sub("", c)
    c = _NUM_PREFIX.sub("", c)
    return re.sub(r"\s+", " ", c).strip()


def parse_option(s):
    """옵션 표기에서 (색상, 사이즈)를 뽑아낸다. 형태가 달라도 통일.

    '색상=블랙, 사이즈=L' / '블랙 / L' / '블랙,L' / '블랙 L' → ('블랙', 'L').
    잡음('[1]', '1개')은 무시. 색상/사이즈는 항상 함께 있다고 가정하되,
    한쪽만 잡히면 그대로 둔다."""
    if s is None:
        return ("", "")
    s = str(s).strip()
    if not s:
        return ("", "")
    s = _NUM_PREFIX.sub("", s).strip()   # 맨 앞 번호 "0006)" "2." 등 제거(공백 무관)

    # 1) 라벨이 있으면 그대로 신뢰 (수량 잡음만 제거)
    mc, ms = _LABEL_COLOR.search(s), _LABEL_SIZE.search(s)
    if mc or ms:
        color = _clean_color(_OPT_JUNK.sub("", mc.group(1))) if mc else ""
        size = _norm_size(ms.group(1)) if ms else ""
        if not (color and size):
            # 라벨 붙은 부분 떼고 남은 토큰에서 빠진 쪽(색상/사이즈) 보충
            rest = s
            for m in (mc, ms):
                if m:
                    rest = rest.replace(m.group(0), " ")
            for t in (x.strip() for x in _OPT_SPLIT.split(_OPT_JUNK.sub(" ", rest)) if x.strip()):
                if not size and _SIZE_TOKEN.match(t):
                    size = _norm_size(t)
                elif not color and not _SIZE_TOKEN.match(t):
                    color = _clean_color(t)
        return (color, size)

    # 2) 라벨 없음 → 잡음 제거 후 토큰화
    s2 = _OPT_JUNK.sub(" ", s)
    parts = [p.strip() for p in _OPT_SPLIT.split(s2) if p.strip()]
    if len(parts) == 1:                      # 구분자 없이 공백으로만 나뉜 경우
        parts = parts[0].split()
    if not parts:
        return ("", "")

    size_idx = None
    for i, p in enumerate(parts):
        if _SIZE_TOKEN.match(p):
            size_idx = i                     # 사이즈 토큰은 보통 뒤쪽 → 마지막 매치 사용
    if size_idx is not None:
        size = parts[size_idx]
        color = " ".join(p for i, p in enumerate(parts) if i != size_idx)
    elif len(parts) >= 2:                    # 사이즈 패턴 못 찾으면 순서(색상, 사이즈)로 가정
        color, size = parts[0], parts[-1]
    else:
        color, size = parts[0], ""
    return (_clean_color(color), _norm_size(size))


def normalize_option(s):
    """옵션 표기를 하나로 통일(비교·표시 공용). '색상 / 사이즈' 형태로 반환.

    '색상=검정' = '검정', '흰색/66' = '색상=흰색,사이즈=66' = '흰색 / 66'."""
    color, size = parse_option(s)
    if color and size:
        return f"{color} / {size}"
    return color or size or ""


# ─────────────────── 판매 파일 → sales_daily + snapshot ───────────────────

def find_date_cols(columns):
    """날짜별 열 찾기. ('YYYY-MM-DD', '판매'/'입고', 원본컬럼명) 리스트."""
    out = []
    for c in columns:
        m = DATE_RE.search(str(c))
        if not m:
            continue
        date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        if config.DATE_COL_SOLD_SUFFIX in str(c):
            out.append((date, "sold", c))
        elif config.DATE_COL_INBOUND_SUFFIX in str(c):
            out.append((date, "inbound", c))
    return out


def build_sales(df: pd.DataFrame, mapping: dict, channel: str):
    """판매 원본 df → (sales_long_df, snapshot_df)."""
    df = df.reset_index(drop=True).copy()

    def col(field):
        c = mapping.get(field)
        return df[c] if c and c in df.columns else pd.Series([None] * len(df))

    base = pd.DataFrame({
        "product_code": col("product_code").map(clean_text),
        "product_name": col("product_name").map(clean_text),
        "option_name": col("option_name").map(clean_text).fillna(""),
    })
    base["channel"] = channel

    # 날짜별 판매/입고 melt
    date_cols = find_date_cols(df.columns)
    sold_map = {c: d for d, kind, c in date_cols if kind == "sold"}
    inbound_map = {c: d for d, kind, c in date_cols if kind == "inbound"}

    long_parts = []
    if sold_map:
        s = base.join(df[list(sold_map)])
        s = s.melt(id_vars=["channel", "product_code", "product_name", "option_name"],
                   var_name="_col", value_name="sold_qty")
        s["sale_date"] = s["_col"].map(sold_map)
        s["sold_qty"] = s["sold_qty"].map(to_number)
        long_parts.append(s.drop(columns="_col"))
    if inbound_map:
        i = base.join(df[list(inbound_map)])
        i = i.melt(id_vars=["channel", "product_code", "product_name", "option_name"],
                   var_name="_col", value_name="inbound_qty")
        i["sale_date"] = i["_col"].map(inbound_map)
        i["inbound_qty"] = i["inbound_qty"].map(to_number)
        long_parts.append(i.drop(columns="_col"))

    if long_parts:
        sales_long = long_parts[0]
        for extra in long_parts[1:]:
            sales_long = sales_long.merge(
                extra, on=["channel", "product_code", "product_name", "option_name", "sale_date"],
                how="outer")
    else:
        sales_long = pd.DataFrame(columns=config_sales_cols())

    for qcol in ("sold_qty", "inbound_qty"):
        if qcol not in sales_long.columns:
            sales_long[qcol] = 0
        sales_long[qcol] = sales_long[qcol].fillna(0).astype(int)

    sales_long = sales_long.dropna(subset=["product_code", "sale_date"])
    # 같은 키 중복 합산
    sales_long = (sales_long
                  .groupby(["channel", "product_code", "option_name", "sale_date"], as_index=False)
                  .agg({"product_name": "first", "sold_qty": "sum", "inbound_qty": "sum"}))
    # 판매·입고가 모두 0인 날은 저장하지 않음(움직임 없는 날) → 데이터량·속도 대폭 개선.
    # 합계·그래프는 동일(0은 더해도 0), period_series가 빈 날을 0으로 채워 표시.
    sales_long = sales_long[(sales_long["sold_qty"] != 0) | (sales_long["inbound_qty"] != 0)]

    # 스냅샷
    snap = pd.DataFrame({
        "channel": channel,
        "product_code": col("product_code").map(clean_text),
        "option_name": col("option_name").map(clean_text).fillna(""),
        "product_name": col("product_name").map(clean_text),
        "buy_name": col("buy_name").map(clean_text),
        "category": col("category").map(clean_text),
        "origin": col("origin").map(clean_text),
        "supplier": col("supplier").map(clean_text),
        "supplier_tel": col("supplier_tel").map(clean_text),
        "reg_date": col("reg_date").map(parse_date),
        "cost": col("cost").map(to_number),
        "sale_price": col("sale_price").map(to_number),
        "amount": col("amount").map(to_number),
        "total_sold": col("total_sold").map(to_number),
        "total_inbound": col("total_inbound").map(to_number),
        "stock": col("stock").map(to_number),
        "unshipped": col("unshipped").map(to_number),
        "canceled": col("canceled").map(to_number),
    })
    snap = snap.dropna(subset=["product_code"])
    snap["snapshot_date"] = max([d for d, _, _ in date_cols], default=None)
    snap = snap.drop_duplicates(subset=["channel", "product_code", "option_name"], keep="last")

    return sales_long, snap


def config_sales_cols():
    return ["channel", "product_code", "product_name", "option_name",
            "sale_date", "sold_qty", "inbound_qty"]


# ─────────────────────── 반품 파일 → returns ───────────────────────

def build_returns(df: pd.DataFrame, mapping: dict):
    df = df.reset_index(drop=True).copy()

    def col(field):
        c = mapping.get(field)
        return df[c] if c and c in df.columns else pd.Series([None] * len(df))

    out = pd.DataFrame({
        "channel": col("channel").map(clean_text),
        "product_code": col("product_code").map(clean_text),
        "product_name": col("product_name").map(clean_text),
        "option_name": col("option_name").map(clean_text).fillna(""),
        "return_date": col("return_date").map(parse_date),
        "qty": col("qty").map(to_number),
        "reason": col("reason").map(clean_text),
        "cs_type": col("cs_type").map(clean_text),
        "supplier": col("supplier").map(clean_text),
        "amount": col("amount").map(to_number),
        "order_no": col("order_no").map(clean_text),
    })
    out = out.dropna(subset=["product_code"])
    out["channel"] = out["channel"].fillna("미지정")
    out["order_no"] = out["order_no"].fillna("").replace("", "NO_ORDER")
    out.loc[out["qty"] <= 0, "qty"] = 1
    # 같은 (채널,주문,상품,옵션) 중복 합산
    out = (out.groupby(["channel", "order_no", "product_code", "option_name"], as_index=False)
              .agg({"product_name": "first", "return_date": "first", "qty": "sum",
                    "reason": "first", "cs_type": "first", "supplier": "first",
                    "amount": "sum"}))
    return out
