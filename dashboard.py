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
    ["ダッシュボード", "推移グラフ", "ASIN登録", "実行ログ"],
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
            with st.spinner(f"{len(targets)}件を計測中... (1件あたり約30秒かかります)"):
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

# ─── Page 3: ASIN Registration ────────────────────────────────────────────────
elif page == "ASIN登録":
    st.title("➕ ASIN / キーワード登録")

    with st.form("register_form", clear_on_submit=True):
        asin_input = st.text_input("ASIN", placeholder="例: B0D66SCPCZ")
        keywords_input = st.text_area(
            "キーワード（1行に1つ）",
            placeholder="ローション\nオナホ\nオナホ ローション",
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
