from datetime import datetime

import pandas as pd

from core import config
from core.ingest import (auto_map, build_returns, build_sales, clean_text,
                         find_date_cols, normalize_option, parse_date, to_number)


def test_clean_text_unwrap():
    assert clean_text('="9579"') == "9579"
    assert clean_text('="핀탁기모나팔"') == "핀탁기모나팔"
    assert clean_text("  브라운  ") == "브라운"
    assert clean_text("") is None
    assert clean_text("nan") is None


def test_to_number():
    assert to_number("8,000") == 8000
    assert to_number("17,700") == 17700
    assert to_number("") == 0
    assert to_number("1.5") == 1.5
    assert to_number(None) == 0


def test_parse_date():
    assert parse_date(datetime(2026, 4, 1, 10, 37)) == "2026-04-01"
    assert parse_date("2026.04.01에 회수") == "2026-04-01"
    assert parse_date("2026-06-13 판매") == "2026-06-13"
    assert parse_date(None) is None


def test_normalize_option():
    # 라벨(색상=/사이즈=)이 있든 없든 같은 값으로 통일
    assert normalize_option("색상=검정") == normalize_option("검정") == "검정"
    assert normalize_option("흰색/66") == normalize_option("색상=흰색,사이즈=66") == "흰색 / 66"
    assert normalize_option("색상=블랙, 사이즈=L") == "블랙 / L"
    assert normalize_option("크림 / M") == "크림 / M"
    assert normalize_option("브라운,66") == "브라운 / 66"
    # 라벨이 아닌 색상명은 보존 (곤색이 사라지지 않아야 함)
    assert "곤색" in normalize_option("곤색:XXL/1개")
    # 영문 번역괄호·앞번호·수량 정제 → 같은 색끼리 묶임
    assert normalize_option("검정(Black)") == normalize_option("검정") == "검정"
    assert normalize_option("2.먹색") == normalize_option("먹색") == "먹색"
    assert normalize_option("색상=베이지(5개)") == "베이지"
    # 한글 세부 괄호는 다른 색으로 유지
    assert normalize_option("베이지(살구)") != normalize_option("베이지")
    # 색상 라벨 + 라벨없는 사이즈 혼합도 보충
    assert normalize_option("색상=흰색(white)/M") == "흰색 / M"


def test_find_date_cols():
    cols = ["상품명", "2026-06-13 입고", "2026-06-13 판매", "입고합계수량"]
    found = find_date_cols(cols)
    kinds = {(d, k) for d, k, _ in found}
    assert ("2026-06-13", "sold") in kinds
    assert ("2026-06-13", "inbound") in kinds


def test_build_sales_melt():
    df = pd.DataFrame({
        "상품명": ["A"], "상품코드": ['="100"'], "옵션명": ["블랙,M"],
        "현재재고": ["5"], "판매합계수량": ["3"], "입고합계수량": ["10"],
        "2026-06-13 판매": ["1"], "2026-06-14 판매": ["2"],
        "2026-06-13 입고": ["0"], "2026-06-14 입고": ["10"],
    })
    mapping = auto_map(df.columns, config.SALES_FIELD_ALIASES)
    sales_long, snap = build_sales(df, mapping, "테스트몰")
    assert len(sales_long) == 2
    assert sales_long["sold_qty"].sum() == 3
    assert sales_long["inbound_qty"].sum() == 10
    assert sales_long["product_code"].iloc[0] == "100"
    assert snap["stock"].iloc[0] == 5
    assert snap["channel"].iloc[0] == "테스트몰"


def test_build_returns_dedup():
    df = pd.DataFrame({
        "재고매칭(1)상품코드": ["100", "100", "100"],
        "상품옵션": ["블랙 / M", "블랙 / M", "화이트 / L"],
        "교환반품회수일": [datetime(2026, 6, 13), datetime(2026, 6, 13), datetime(2026, 6, 14)],
        "판매처명": ["퀸잇", "퀸잇", "퀸잇"],
        "판매처주문번호": ["O1", "O1", "O2"],   # 첫 두 행은 같은 키 → 합산
        "CS종류1": ["사이즈가 커요", "사이즈가 커요", "색상 달라요"],
        "교환반품회수수량": ["1", "1", "1"],
        "옵션상품명": ["A", "A", "A"],
    })
    mapping = auto_map(df.columns, config.RETURNS_FIELD_ALIASES)
    out = build_returns(df, mapping)
    assert len(out) == 2                      # O1/블랙M 합쳐짐
    o1 = out[(out["order_no"] == "O1")]
    assert o1["qty"].iloc[0] == 2
