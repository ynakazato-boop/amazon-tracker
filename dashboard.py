"""
Amazon Keyword Rank Tracker - Streamlit Dashboard (All-in-one)

起動: streamlit run dashboard.py
スケジューラはStreamlit起動と同時に内蔵で自動スタートします。
"""

import io
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.database import (
    init_db,
    get_latest_rankings,
    get_ranking_history,
    get_all_asin_kw_pairs,
    get_recent_run_logs,
)

TARGETS_CSV = Path("config/targets.csv")
RANK_DROP_THRESHOLD = 10

st.set_page_config(
    page_title="Amazon Rank Tracker",
    page_icon="📊",
    layout="wide",
)

init_db()


# ─── スケジューラをStreamlitプロセスに内蔵（1回だけ起動）────────────────────────
@st.cache_resource
def get_scheduler():
    from src.scheduler import start_scheduler
    return start_scheduler()

get_scheduler()


# ─── CSV ヘルパー ──────────────────────────────────────────────────────────────
def load_targets_csv() -> pd.DataFrame:
    if TARGETS_CSV.exists():
        df = pd.read_csv(TARGETS_CSV, dtype=str)
        # 不要な行を除外
        df = df.dropna(subset=["asin", "keyword"])
        df = df[df["asin"].str.strip() != ""]
        return df.reset_index(drop=True)
    return pd.DataFrame(columns=["asin", "keyword", "frequency", "note"])


def save_targets_csv(df: pd.DataFrame):
    TARGETS_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(TARGETS_CSV, index=False, encoding="utf-8")


def add_targets(asin: str, keywords: list[str], frequency: str, note: str):
    df = load_targets_csv()
    new_rows = pd.DataFrame([
        {"asin": asin, "keyword": kw, "frequency": frequency, "note": note}
        for kw in keywords
    ])
    df = pd.concat([df, new_rows], ignore_index=True)
    save_targets_csv(df)


# ─── サイドバー ────────────────────────────────────────────────────────────────
page = st.sidebar.radio(
    "ページ",
    ["ダッシュボード", "推移グラフ", "ASIN登録", "実行ログ", "使い方ガイド"],
)

freq_label = {
    "daily": "毎日",
    "twice_daily": "1日2回（8時・20時）",
    "weekly": "毎週月曜",
    "biweekly": "隔週月曜",
    "monthly": "毎月1日",
}

# ─── Page 1: Dashboard ────────────────────────────────────────────────────────
if page == "ダッシュボード":
    st.title("📊 最新順位ダッシュボード")

    if st.button("🔄 更新"):
        st.rerun()

    df_t = load_targets_csv()
    if not df_t.empty:
        target_options = [f"{r['asin']} / {r['keyword']}" for _, r in df_t.iterrows()]
        selected_targets = st.multiselect(
            "今すぐ計測するキーワードを選択（複数可）",
            target_options,
            default=[],
            placeholder="計測したいキーワードを選んでください...",
        )
        if st.button("▶️ 選択した件を今すぐ計測", type="primary", disabled=not selected_targets):
            targets = []
            for sel in selected_targets:
                for _, r in df_t.iterrows():
                    if f"{r['asin']} / {r['keyword']}" == sel:
                        targets.append({"asin": r["asin"], "keyword": r["keyword"], "note": r.get("note", "")})
                        break
            from src.scraper import run_checks_sync
            from src.database import insert_ranking, start_run_log, finish_run_log
            with st.spinner(f"{len(targets)}件を計測中... (1件あたり約60秒かかります)"):
                log_id = start_run_log()
                results = run_checks_sync(targets)
                success = 0
                for result, target in zip(results, targets):
                    insert_ranking(result.asin, result.keyword, result.rank, result.page, target.get("note", ""))
                    success += 1
                finish_run_log(log_id, len(targets), success, 0)
            st.success("完了！")
            st.rerun()

    rows = get_latest_rankings()
    if not rows:
        st.info("データがありません。「ASIN登録」でASINとキーワードを登録してください。")
        st.stop()

    df = pd.DataFrame(rows)
    df["rank"] = df["rank"].fillna(999).astype(int)
    df["checked_at"] = pd.to_datetime(df["checked_at"])

    # 急落アラート
    alerts = []
    for _, row in df.iterrows():
        history = get_ranking_history(row["asin"], row["keyword"], days=7)
        if len(history) >= 2:
            prev_rank = history[-2]["rank"]
            curr_rank = history[-1]["rank"]
            if prev_rank and curr_rank and (curr_rank - prev_rank) >= RANK_DROP_THRESHOLD:
                alerts.append(
                    f"⚠️ **{row['asin']}** / `{row['keyword']}` : {prev_rank}位 → {curr_rank}位 (▼{curr_rank - prev_rank})"
                )

    if alerts:
        st.error("**順位急落アラート**\n\n" + "\n".join(alerts))

    display_df = df[["note", "asin", "keyword", "rank", "page", "checked_at"]].copy()
    display_df.columns = ["備考", "ASIN", "キーワード", "順位", "ページ", "計測日時"]
    display_df["順位"] = display_df["順位"].apply(
        lambda x: "圏外(144位以降)" if x == 999 else str(x)
    )
    st.dataframe(display_df, use_container_width=True, hide_index=True)
    st.caption(f"計 {len(df)} 件")

# ─── Page 2: Trend Chart ──────────────────────────────────────────────────────
elif page == "推移グラフ":
    st.title("📈 順位推移グラフ")

    pairs = get_all_asin_kw_pairs()
    if not pairs:
        st.info("データがありません。")
        st.stop()

    options = [f"{p['asin']} / {p['keyword']}" for p in pairs]
    selected = st.multiselect("ASIN / キーワードを選択", options, default=options[:3])
    days = st.slider("表示期間（日）", min_value=7, max_value=90, value=30)

    fig = go.Figure()
    for sel in selected:
        asin, kw = sel.split(" / ", 1)
        history = get_ranking_history(asin, kw, days=days)
        if not history:
            continue
        df_h = pd.DataFrame(history)
        df_h["checked_at"] = pd.to_datetime(df_h["checked_at"])
        df_h["rank"] = df_h["rank"].fillna(145)

        fig.add_trace(go.Scatter(
            x=df_h["checked_at"],
            y=df_h["rank"],
            mode="lines+markers",
            name=sel,
            hovertemplate="%{x}<br>順位: %{y}<extra></extra>",
        ))

    fig.update_layout(
        yaxis=dict(autorange="reversed", title="順位（小さいほど上位）"),
        xaxis_title="日時",
        hovermode="x unified",
        height=500,
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption("145 = 144位圏外")

    st.subheader("数値データ")
    for sel in selected:
        asin, kw = sel.split(" / ", 1)
        history = get_ranking_history(asin, kw, days=days)
        if not history:
            continue
        df_h = pd.DataFrame(history)
        df_h["checked_at"] = pd.to_datetime(df_h["checked_at"])
        df_h["rank"] = df_h["rank"].fillna(145).astype(int)
        df_h["rank"] = df_h["rank"].apply(lambda x: "圏外(144位以降)" if x == 145 else str(x))
        df_h = df_h[["checked_at", "rank", "page"]].rename(columns={"checked_at": "計測日時", "rank": "順位", "page": "ページ"})
        st.markdown(f"**{sel}**")
        st.dataframe(df_h.sort_values("計測日時", ascending=False), use_container_width=True, hide_index=True)

# ─── Page 3: ASIN Registration ────────────────────────────────────────────────
elif page == "ASIN登録":
    st.title("➕ ASIN / キーワード登録")

    with st.form("register_form", clear_on_submit=True):
        asin_input = st.text_input("ASIN", placeholder="例: B0B3RMP7J3")
        keywords_input = st.text_area(
            "キーワード（1行に1つ）",
            placeholder="ファンデーション\nファンデーション リキッド\nファンデーション カバー力",
            height=200,
        )
        col1, col2 = st.columns(2)
        with col1:
            frequency_input = st.selectbox(
                "計測頻度",
                ["daily", "twice_daily", "weekly", "biweekly", "monthly"],
                format_func=lambda x: freq_label[x],
            )
        with col2:
            note_input = st.text_input("備考（任意）", placeholder="商品名など")

        submitted = st.form_submit_button("登録する", type="primary", use_container_width=True)

    if submitted:
        asin_clean = asin_input.strip()
        keywords = [k.strip() for k in keywords_input.strip().split("\n") if k.strip()]

        if not asin_clean:
            st.error("ASINを入力してください。")
        elif len(asin_clean) != 10:
            st.error("ASINは10文字です。確認してください。")
        elif not keywords:
            st.error("キーワードを1つ以上入力してください。")
        else:
            add_targets(asin_clean, keywords, frequency_input, note_input)
            st.success(f"✅ {len(keywords)}件のキーワードを登録しました。次回の計測スケジュール（{freq_label[frequency_input]}）から自動取得が始まります。")

    # 現在の登録一覧
    st.divider()
    st.subheader("現在の登録一覧")
    df_targets = load_targets_csv()

    if df_targets.empty:
        st.info("登録されているASIN/キーワードはありません。")
    else:
        header = st.columns([2, 4, 2, 2, 1])
        for col, label in zip(header, ["ASIN", "キーワード", "頻度", "備考", ""]):
            col.markdown(f"**{label}**")

        for i, row in df_targets.iterrows():
            c1, c2, c3, c4, c5 = st.columns([2, 4, 2, 2, 1])
            c1.text(row.get("asin", ""))
            c2.text(row.get("keyword", ""))
            c3.text(freq_label.get(row.get("frequency", ""), row.get("frequency", "")))
            c4.text(row.get("note", ""))
            if c5.button("削除", key=f"del_{i}"):
                df_targets = df_targets.drop(i).reset_index(drop=True)
                save_targets_csv(df_targets)
                st.rerun()

# ─── Page 4: Run Logs ─────────────────────────────────────────────────────────
elif page == "実行ログ":

    st.title("📋 実行ログ")

    if st.button("🔄 更新"):
        st.rerun()

    logs = get_recent_run_logs(limit=50)
    if not logs:
        st.info("実行ログがありません。")
        st.stop()

    df_logs = pd.DataFrame(logs)
    df_logs["started_at"] = pd.to_datetime(df_logs["started_at"])
    df_logs["finished_at"] = pd.to_datetime(df_logs["finished_at"])

    status_icon = {"success": "✅", "partial": "⚠️", "failed": "❌", "running": "🔄"}
    df_logs["status"] = df_logs["status"].apply(lambda s: f"{status_icon.get(s, '')} {s}")

    display = df_logs[["started_at", "finished_at", "total", "success", "failed", "status"]].copy()
    display.columns = ["開始", "終了", "合計", "成功", "失敗", "ステータス"]
    st.dataframe(display, use_container_width=True, hide_index=True)

# ─── Page 5: Guide ────────────────────────────────────────────────────────────
elif page == "使い方ガイド":
    st.title("📖 使い方ガイド")

    st.header("このツールとは？")
    st.markdown("""
Amazon.co.jpで指定したASIN（商品）が、特定キーワードの検索結果で何位に表示されるかを自動で追跡するSEO計測ツールです。
日本のサーバー（東京）から検索するため、実際の日本ユーザーに近い順位が取得できます。
    """)

    st.divider()
    st.header("各ページの説明")

    with st.expander("ダッシュボード", expanded=False):
        st.markdown("""
- 登録した全ASIN・キーワードの**最新順位**を一覧表示します
- **今すぐ計測したいキーワードを選んで即時実行**することもできます（1件あたり約60秒かかります）
- 直近7日間で10位以上急落した場合は**赤いアラート**が表示されます
- 「圏外(144位以降)」は1〜3ページ目（最大144件）に商品が見つからなかった場合です
        """)

    with st.expander("推移グラフ", expanded=False):
        st.markdown("""
- ASIN・キーワードを選択して、**順位の時系列グラフ**を確認できます
- 表示期間は7〜90日で調整可能
- グラフはY軸が逆順（上に行くほど上位 = 良い順位）です
- 「145」は圏外（144位以降）を表します
        """)

    with st.expander("ASIN登録", expanded=False):
        st.markdown("""
**登録方法：**
1. ASINを入力（10文字の英数字。例：B0D66SCPCZ）
2. キーワードを1行に1つ入力（複数可）
3. 計測頻度を選択
4. 備考（商品名など）を入力（任意）
5. 「登録する」をクリック

**計測頻度の選択基準：**

| 頻度 | 実行タイミング | 推奨用途 |
|------|--------------|---------|
| 毎日 | 毎日 02:00 JST | 主力商品・重要キーワード |
| 1日2回 | 08:00 と 20:00 JST | 特に注視したい商品 |
| 毎週月曜 | 月曜 02:00 JST | サブキーワード |
| 隔週月曜 | 2週間ごと | 参考程度に見たいキーワード |
| 毎月1日 | 1日 02:00 JST | 月次レポート用 |

**登録数の目安（サーバー負荷上限）：**
- 毎日：50件以内
- 1日2回：20件以内
- これを超えると実行が重なり遅延する場合があります

**頻度・備考を変更したい場合：**
一度「削除」して同じASIN・キーワードで再登録してください。
        """)

    with st.expander("実行ログ", expanded=False):
        st.markdown("""
- 自動・手動を問わず、すべての計測実行履歴が記録されます
- ステータスの見方：
  - ✅ success：全件成功
  - ⚠️ partial：一部失敗
  - ❌ failed：全件失敗
  - 🔄 running：実行中
- 失敗が続く場合はAmazonのボット検知やサーバー負荷が原因の場合があります
        """)

    st.divider()
    st.header("注意事項")
    st.markdown("""
**計測精度について**
- 順位はAmazonの検索アルゴリズムにより変動します。同じタイミングでも完全に一致しない場合があります
- Amazonがボット検知を強化した場合、計測がタイムアウトして圏外と表示されることがあります
- 「圏外」が続く場合は実行ログを確認し、失敗が多ければ管理者に連絡してください

**Settingsダイアログについて**
- 右上のメニューから開ける「Settings」はStreamlit（表示フレームワーク）の画面設定です
- テーマ・ワイドモードの切替のみで、ツールの動作には影響しません。基本的に触る必要はありません

**セキュリティ・利用上の注意**
- このツールはAmazonの公開検索結果を取得するものです
- Seller Centralへのログインは行いません
- URLを知っている人は誰でもアクセスできます。社外共有の際は注意してください

**サーバーについて**
- Oracle Cloud東京サーバー（無料枠）で24時間稼働しています
- サーバーが落ちた場合：管理者（ツール構築担当者）に連絡してください
- URL：`http://161.33.154.41:8501`
    """)

    st.divider()
    st.header("困ったときは？")
    st.markdown("""
| 症状 | 原因と対処 |
|------|-----------|
| 計測が「圏外」になる | Amazonのボット検知 or タイムアウト。時間をおいて再計測 |
| 計測に時間がかかる | 1件あたり約60秒は正常。複数件は順番に処理されます |
| ページが開かない | サーバーが停止している可能性。管理者に連絡 |
| グラフにデータが出ない | 計測データがない。まず計測を実行してください |
    """)
