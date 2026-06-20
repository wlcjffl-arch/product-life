# 상품 판매·반품 분석 대시보드

의류몰 운영용 Streamlit 대시보드. 판매 분석 파일과 반품 파일을 올려서
판매 흐름·반품·재고 위험을 한눈에 봅니다.

## 로컬에서 실행
```bash
시작하기.command   # 맥에서 더블클릭
# 또는
python -m venv .venv && ./.venv/bin/pip install -r requirements.txt
./.venv/bin/streamlit run app.py
```
로컬에서는 `data/product_life.db` (SQLite)에 저장됩니다.

## 클라우드 배포 (Streamlit Cloud + Supabase)
1. 이 저장소를 GitHub 에 올립니다.
2. [Supabase](https://supabase.com) 에서 프로젝트를 만들고 Postgres 접속주소(URI)를 복사합니다.
3. [Streamlit Cloud](https://share.streamlit.io) 에서 이 저장소를 연결합니다.
4. 앱 **Settings → Secrets** 에 아래를 넣습니다(`.streamlit/secrets.toml.example` 참고):
   ```toml
   DATABASE_URL = "postgresql://postgres:비밀번호@db.프로젝트.supabase.co:5432/postgres"
   ```
   `DATABASE_URL` 이 있으면 자동으로 Supabase(Postgres)에 저장됩니다.

## 구조
- `app.py`, `pages/` — 화면
- `core/` — 설정·DB·데이터처리·분석·공용 UI
- `tests/` — 테스트 (`./.venv/bin/python -m pytest tests/`)
