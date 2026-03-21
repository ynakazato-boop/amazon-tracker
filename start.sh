#!/bin/bash
set -e

# 永続ボリューム（/app/data）に targets.csv がなければ初期ファイルをコピー
if [ ! -f /app/data/targets.csv ]; then
  if [ -f /app/config/targets.csv ]; then
    cp /app/config/targets.csv /app/data/targets.csv
  else
    echo "asin,keyword,frequency,note" > /app/data/targets.csv
  fi
fi

# config/targets.csv → data/targets.csv へシンボリックリンク
# （コード内のパスを変えずに永続化する）
mkdir -p /app/config
ln -sf /app/data/targets.csv /app/config/targets.csv

exec streamlit run dashboard.py \
  --server.port "${PORT:-8501}" \
  --server.address 0.0.0.0 \
  --server.headless true
