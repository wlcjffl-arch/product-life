import pandas as pd

from core import analytics


def _sales(rows):
    return pd.DataFrame(rows, columns=["channel", "product_code", "product_name",
                                       "option_name", "sale_date", "sold_qty", "inbound_qty"])


def test_return_rate_product_flags():
    sales = _sales([
        ["퀸잇", "100", "A", "블랙,M", "2026-06-13", 10, 0],
        ["퀸잇", "200", "B", "화이트,L", "2026-06-13", 4, 0],
    ])
    returns = pd.DataFrame([
        ["퀸잇", "100", "A", "블랙 / M", "2026-06-14", 3, "사이즈", "", "", 0, "O1"],
        ["퀸잇", "200", "B", "화이트 / L", "2026-06-14", 1, "색상", "", "", 0, "O2"],
    ], columns=["channel", "product_code", "product_name", "option_name", "return_date",
                "qty", "reason", "cs_type", "supplier", "amount", "order_no"])
    rr = analytics.return_rate_product(sales, returns)
    p100 = rr[rr["product_code"] == "100"].iloc[0]
    assert abs(p100["return_rate"] - 0.3) < 1e-9
    assert bool(p100["high_return"]) is True          # 30% > 20%
    p200 = rr[rr["product_code"] == "200"].iloc[0]
    assert bool(p200["low_sales_high_return"]) is True  # 판매4 ≤5, 반품율25% ≥10%


def test_period_series():
    sales = _sales([
        ["퀸잇", "100", "A", "블랙,M", "2026-06-13", 1, 0],   # 토 → 주 06-08
        ["퀸잇", "100", "A", "블랙,M", "2026-06-15", 2, 0],   # 월 → 주 06-15
        ["퀸잇", "100", "A", "블랙,M", "2026-07-01", 4, 0],   # 7월
    ])
    # 일별: 06-13~07-01 빈 구간까지 채워 연속 표시(19일)
    day = analytics.period_series(sales, "일")
    assert len(day) == 19
    assert day[day["bucket"] == "2026-06-15"]["sold_qty"].iloc[0] == 2
    assert day[day["bucket"] == "2026-06-14"]["sold_qty"].iloc[0] == 0  # 빈 구간=0
    assert "bucket_date" in day.columns
    # 주별: 월요일 기준, 빈 주 포함 연속
    wk = analytics.period_series(sales, "주")
    assert {"2026-06-08", "2026-06-15", "2026-06-22", "2026-06-29"} == set(wk["bucket"])
    assert wk[wk["bucket"] == "2026-06-08"]["sold_qty"].iloc[0] == 1  # 토 06-13
    assert wk[wk["bucket"] == "2026-06-15"]["sold_qty"].iloc[0] == 2  # 월 06-15
    assert wk[wk["bucket"] == "2026-06-22"]["sold_qty"].iloc[0] == 0  # 빈 주
    # 월별
    mo = analytics.period_series(sales, "월")
    assert set(mo["bucket"]) == {"2026-06", "2026-07"}
    assert mo[mo["bucket"] == "2026-06"]["sold_qty"].iloc[0] == 3


def test_mark_spikes():
    series = pd.DataFrame({
        "sale_date": ["2026-06-13", "2026-06-14", "2026-06-15"],
        "sold_qty": [10, 25, 5],
        "inbound_qty": [0, 0, 0],
    })
    m = analytics.mark_spikes(series)
    assert m.iloc[1]["flag"] == "급등 ▲"   # +150%
    assert m.iloc[2]["flag"] == "급감 ▼"   # -80%


def test_stock_alerts_shortage_and_nosale():
    # 최근 14일간 매일 1개씩 판매 → avg 1/day, 마지막 판매는 9일 전
    dates = pd.date_range("2026-06-01", "2026-06-11")
    rows = [["퀸잇", "100", "A", "블랙,M", d.strftime("%Y-%m-%d"), 1, 0] for d in dates]
    sales = _sales(rows)
    snapshot = pd.DataFrame([{
        "channel": "퀸잇", "product_code": "100", "option_name": "블랙,M",
        "product_name": "A", "stock": 2, "category": "상의",
    }])
    restock = pd.DataFrame([{"product_code": "100", "lead_time_days": 7, "min_stock": None}])
    out = analytics.stock_alerts(sales, snapshot, restock, "2026-06-20")
    row = out.iloc[0]
    assert bool(row["shortage_flag"]) is True   # avg1 × 7 = 7 > 재고2
    assert bool(row["no_sale_flag"]) is True     # 마지막판매 06-11, asof 06-20 → 9일


def test_alert_overview_runs():
    sales = _sales([["퀸잇", "100", "A", "블랙,M", "2026-06-13", 10, 0]])
    returns = pd.DataFrame([
        ["퀸잇", "100", "A", "블랙 / M", "2026-06-14", 3, "사이즈", "", "", 0, "O1"]],
        columns=["channel", "product_code", "product_name", "option_name", "return_date",
                 "qty", "reason", "cs_type", "supplier", "amount", "order_no"])
    snapshot = pd.DataFrame([{
        "channel": "퀸잇", "product_code": "100", "option_name": "블랙,M",
        "product_name": "A", "stock": 5, "category": "상의"}])
    ov = analytics.alert_overview(sales, returns, snapshot, pd.DataFrame(), "2026-06-20")
    assert not ov.empty
    assert "🔴반품율" in ov.iloc[0]["알림"]
