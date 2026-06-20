#!/bin/bash
# 맥에서 더블클릭하면 실행됩니다.
# 처음 한 번은 가상환경(.venv)을 만들고 필요한 프로그램을 설치하느라 몇 분 걸릴 수 있어요.

cd "$(dirname "$0")" || exit 1

PY=python3
if ! command -v $PY >/dev/null 2>&1; then
  echo "❌ python3 가 설치되어 있지 않습니다. https://www.python.org 에서 설치 후 다시 실행하세요."
  read -r -p "엔터를 누르면 닫힙니다..." _
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "📦 처음 실행: 가상환경을 만들고 프로그램을 설치합니다 (몇 분 소요)..."
  $PY -m venv .venv
  ./.venv/bin/python -m pip install --upgrade pip
  ./.venv/bin/python -m pip install -r requirements.txt
fi

echo "🚀 대시보드를 켭니다. 브라우저가 자동으로 열립니다."
echo "   (끄려면 이 검은 창에서 Control(^) + C 를 누르세요.)"
./.venv/bin/python -m streamlit run app.py
