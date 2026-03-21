# Amazon Keyword Rank Tracker

Amazon.co.jp でのASINキーワード検索順位を自動計測・蓄積・可視化するツール。

## 機能
- 最大144位（3ページ）まで自動計測
- daily / weekly / monthly の3頻度でスケジュール実行
- Streamlitダッシュボードで順位推移を可視化
- Oracle Cloud Free Tier（永久無料VPS）で費用ゼロ運用

---

## ローカルでのテスト（Mac）

### 1. 環境構築

```bash
cd amazon-tracker
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### 2. 計測対象を設定

`config/targets.csv` を編集：

```csv
asin,keyword,frequency,note
B09XXXXXXX,コーヒーメーカー,daily,商品A
```

### 3. テスト実行（1件だけ動かす）

```bash
python main.py --test
```

DBにデータが入ることを確認：

```bash
sqlite3 data/rankings.db "SELECT * FROM rankings;"
```

### 4. ダッシュボード確認

```bash
streamlit run dashboard.py
```

ブラウザで `http://localhost:8501` を開く。

---

## Oracle Cloud デプロイ手順

### 1. Oracle Cloud アカウント作成
- https://www.oracle.com/jp/cloud/free/ でアカウント作成
- クレジットカード登録が必要（課金なし）

### 2. Always Free VM 作成
- コンピュート → インスタンスの作成
- シェイプ：**VM.Standard.A1.Flex**（Ampere A1）
- OCPU: 4、メモリ: 24GB（Always Free 上限）
- OS: Ubuntu 22.04
- SSHキー登録（ローカルの `~/.ssh/id_rsa.pub` を貼り付け）

### 3. セキュリティリスト設定（ポート8501開放）
- VCN → セキュリティ・リスト → イングレス・ルール追加
  - ソースCIDR: `0.0.0.0/0`
  - プロトコル: TCP
  - 宛先ポート: `8501`

### 4. コードをアップロード

```bash
# ローカルから
scp -r amazon-tracker ubuntu@<サーバーIP>:/opt/amazon-tracker

# または
ssh ubuntu@<サーバーIP>
git clone <your-repo> /opt/amazon-tracker
```

### 5. セットアップスクリプト実行

```bash
ssh ubuntu@<サーバーIP>
cd /opt/amazon-tracker
bash setup.sh
```

### 6. ダッシュボードを常時起動（別途 systemd サービス推奨）

```bash
# 手動起動する場合（テスト用）
source venv/bin/activate
streamlit run dashboard.py --server.port 8501 --server.address 0.0.0.0 &
```

本番運用ではダッシュボード用 systemd サービスを別途作成するか、
`tmux` や `screen` を使用してください。

### 7. アクセス確認

```
http://<サーバーIP>:8501
```

---

## ファイル構成

```
amazon-tracker/
├── config/
│   └── targets.csv          # 計測対象（ASIN・KW・頻度）
├── data/
│   └── rankings.db          # SQLiteデータベース（自動生成）
├── src/
│   ├── scraper.py           # Playwrightスクレイパー
│   ├── database.py          # DB操作
│   └── scheduler.py         # APScheduler
├── dashboard.py             # Streamlitダッシュボード
├── main.py                  # エントリーポイント
├── requirements.txt
├── setup.sh                 # Ubuntuセットアップスクリプト
└── amazon-tracker.service   # systemdサービスファイル
```

---

## 注意事項

- 30秒前後のランダム待機でレート制限を実装していますが、Amazonの利用規約に注意してください
- IPブロックされた場合はしばらく待機するか、VPNを検討してください
- 大量のASIN/KWを追加する場合、実行時間が長くなります（1000件 ≈ 8時間）
