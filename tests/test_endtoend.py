"""실제 샘플 2파일로 업로드→저장→조회 전체 흐름 검증."""
import os

import pytest

from core import analytics, config, db, ingest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SALES = os.path.join(ROOT, "일자별옵션별매출.csv")
RETURNS = os.path.join(ROOT, "반품데이터.xlsx")

pytestmark = pytest.mark.skipif(
    not (os.path.exists(SALES) and os.path.exists(RETURNS)),
    reason="샘플 파일 없음")


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_DIR", str(tmp_path))
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "t.db"))
    db.init_db()


def test_real_files(temp_db):
    # 판매 파일
    with open(SALES, "rb") as f:
        raw = ingest.read_raw(f.read(), "일자별옵션별매출.csv")
    raw.columns = [str(c).strip() for c in raw.columns]
    assert ingest.detect_file_type(raw) == "sales"
    mapping = ingest.auto_map(raw.columns, config.SALES_FIELD_ALIASES)
    sales_long, snap = ingest.build_sales(raw, mapping, "테스트몰")
    assert not sales_long.empty and not snap.empty
    ins1, _ = db.upsert_sales_daily(sales_long)
    db.save_snapshot(snap)
    assert ins1 > 0

    # 같은 파일 재업로드 → 추가 0, 전부 갱신 (중복 제거 검증)
    ins2, upd2 = db.upsert_sales_daily(sales_long)
    assert ins2 == 0 and upd2 > 0

    # 반품 파일
    with open(RETURNS, "rb") as f:
        rraw = ingest.read_raw(f.read(), "반품데이터.xlsx")
    rraw.columns = [str(c).strip() for c in rraw.columns]
    assert ingest.detect_file_type(rraw) == "returns"
    rmap = ingest.auto_map(rraw.columns, config.RETURNS_FIELD_ALIASES)
    rdf = ingest.build_returns(rraw, rmap)
    assert not rdf.empty
    db.upsert_returns(rdf)

    # 조회 + 분석
    channels = db.list_channels()
    assert "테스트몰" in channels
    s = db.load_sales_daily("테스트몰")
    r = db.load_returns()
    snp = db.load_snapshot("테스트몰")
    assert not s.empty and not r.empty
    lo, hi = db.date_bounds()
    ov = analytics.alert_overview(s, r, snp, db.load_restock_settings(), hi)
    assert ov is not None  # 빈 표여도 예외 없이 동작
