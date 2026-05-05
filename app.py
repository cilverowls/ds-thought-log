import base64
import json
import re
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

DEFAULT_FILE = "structured_output.json"
FLOW_FILE    = "thought_flow.md"

PHASES = ["EDA", "特徴量選択", "モデル作成", "モデル改善"]
TYPES  = ["ドメイン知識", "仮説", "検証", "結果", "Tips"]

SCORE_LABEL = {
    "ドメイン知識": "重要度",
    "仮説":         "ひらめき度",
    "検証":         "工夫度",
    "結果":         "発見度",
    "Tips":         "汎用性",
}
HIGHLIGHT_THRESHOLD = 80

CATEGORY_COLOR = {
    "ドメイン知識": "#3b82f6",
    "仮説":         "#eab308",
    "検証":         "#22c55e",
    "結果":         "#ec4899",
    "Tips":         "#a855f7",
}
CATEGORY_STYLE_MERMAID = {
    "ドメイン知識": "fill:#dbeafe,stroke:#3b82f6,color:#1e3a5f",
    "仮説":         "fill:#fef9c3,stroke:#eab308,color:#713f12",
    "検証":         "fill:#dcfce7,stroke:#22c55e,color:#14532d",
    "結果":         "fill:#fce7f3,stroke:#ec4899,color:#831843",
    "Tips":         "fill:#f3e8ff,stroke:#a855f7,color:#4a044e",
}
HIGH_SCORE_STYLE = "fill:#ff6b35,stroke:#c0392b,color:#fff,font-weight:bold"
PHASE_SAFE = {p: f"P{i+1}" for i, p in enumerate(PHASES)}


# ─── プロジェクトファイル管理 ──────────────────────────────────

def get_project_files() -> list[str]:
    return sorted(str(p) for p in Path(".").glob("*.json"))

def get_current_file() -> str:
    return st.session_state.get("current_file", DEFAULT_FILE)

def project_name(filepath: str | None = None) -> str:
    return Path(filepath or get_current_file()).stem


# ─── データ管理 ────────────────────────────────────────────────

def load_data(filepath: str | None = None) -> dict:
    fp = filepath or get_current_file()
    p = Path(fp)
    if p.exists():
        with open(fp, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if "entries" not in raw:
            old_items = raw.get("全アイテム", [])
            entries = []
            for item in old_items:
                t = item.get("分類", "Tips")
                entries.append({
                    "id": item.get("思考順序", len(entries) + 1),
                    "phase": "EDA",
                    "type": t,
                    "label_name": SCORE_LABEL.get(t, "スコア"),
                    "score": item.get("ひらめき度", 0),
                    "content": item.get("内容", ""),
                    "timestamp": raw.get("metadata", {}).get("created_at", datetime.now().isoformat()),
                    "related_ids": [],
                })
            raw = {"metadata": raw.get("metadata", {}), "entries": entries}
        return raw
    return {
        "metadata": {
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "total_entries": 0,
        },
        "entries": [],
    }

def save_data(data: dict, filepath: str | None = None):
    fp = filepath or get_current_file()
    data["metadata"]["updated_at"] = datetime.now().isoformat()
    data["metadata"]["total_entries"] = len(data["entries"])
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def next_id(data: dict) -> int:
    return max((e["id"] for e in data["entries"]), default=0) + 1


# ─── Mermaid ──────────────────────────────────────────────────

def build_mermaid_code(data: dict) -> str:
    entries = data["entries"]
    if not entries:
        return 'flowchart TD\n    A["まだ記録がありません"]'
    lines = ["flowchart TD"]
    phase_groups: dict[str, list] = defaultdict(list)
    for e in entries:
        phase_groups[e["phase"]].append(e)
    for phase in PHASES:
        group = phase_groups.get(phase)
        if not group:
            continue
        safe = PHASE_SAFE[phase]
        lines.append(f'    subgraph {safe}["{phase}"]')
        for e in group:
            label_name = e.get("label_name", "スコア")
            star = "★" if e["score"] >= HIGHLIGHT_THRESHOLD else ""
            content_s = e["content"].replace('"', "'")
            label = f'ID:{e["id"]} {star}\\n{content_s}\\n[{e["type"]}] {label_name}:{e["score"]}'
            lines.append(f'        N{e["id"]}["{label}"]')
        lines.append("    end")
        lines.append("")
    for e in entries:
        for rid in e.get("related_ids", []):
            lines.append(f"    N{e['id']} --> N{rid}")
    lines.append("")
    for cat, style in CATEGORY_STYLE_MERMAID.items():
        lines.append(f"    classDef {cat.replace(' ','_')} {style}")
    lines.append(f"    classDef highlight {HIGH_SCORE_STYLE}")
    lines.append("")
    type_nodes: dict[str, list[str]] = defaultdict(list)
    high_nodes: list[str] = []
    for e in entries:
        type_nodes[e["type"]].append(f"N{e['id']}")
        if e["score"] >= HIGHLIGHT_THRESHOLD:
            high_nodes.append(f"N{e['id']}")
    for t, nids in type_nodes.items():
        lines.append(f"    class {','.join(nids)} {t.replace(' ','_')}")
    if high_nodes:
        lines.append(f"    class {','.join(high_nodes)} highlight")
    return "\n".join(lines)


@st.cache_data(ttl=300, show_spinner=False)
def get_mermaid_svg(code: str) -> str:
    import requests as _req
    dark_code = "%%{init: {'theme': 'dark'}}%%\n" + code
    try:
        resp = _req.post(
            "https://kroki.io/mermaid/svg",
            data=dark_code.encode("utf-8"),
            headers={"Content-Type": "text/plain"},
            timeout=10,
        )
        resp.raise_for_status()
        svg = resp.text
        svg = re.sub(r'\bwidth="[^"]*"',  'width="100%"',  svg, count=1)
        svg = re.sub(r'\bheight="[^"]*"', 'height="auto"', svg, count=1)
        return svg
    except Exception as e:
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="60">'
            f'<text x="10" y="30" fill="#f87171" font-size="13">SVG取得エラー: {e}</text></svg>'
        )


def save_flow_md(data: dict):
    mermaid_code = build_mermaid_code(data)
    entries = data["entries"]
    phase_groups: dict[str, list] = defaultdict(list)
    for e in entries:
        phase_groups[e["phase"]].append(e)
    density = [
        "\n## フェーズ別思考密度\n",
        "| フェーズ | 件数 | 平均スコア | ★ハイライト | 最多の型 |",
        "|---|---|---|---|---|",
    ]
    for phase in PHASES:
        group = phase_groups.get(phase, [])
        if not group:
            continue
        avg  = sum(e["score"] for e in group) / len(group)
        highs = sum(1 for e in group if e["score"] >= HIGHLIGHT_THRESHOLD)
        top_type = Counter(e["type"] for e in group).most_common(1)[0][0]
        density.append(f"| {phase} | {len(group)} | {avg:.1f} | {highs} | {top_type} |")
    md = (
        f"# 思考フロー — {project_name()}\n\n"
        f"> 生成日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"> 総記録数: {len(entries)}件 | ★ = {HIGHLIGHT_THRESHOLD}点以上\n\n"
        f"```mermaid\n{mermaid_code}\n```\n"
        + "\n".join(density)
        + "\n\n## カテゴリ凡例\n\n"
        "| カテゴリ | スコアラベル |\n|---|---|\n"
        + "\n".join(f"| {t} | {SCORE_LABEL[t]} |" for t in TYPES)
        + f"\n| ★ハイライト ({HIGHLIGHT_THRESHOLD}点以上) | — |\n"
    )
    with open(FLOW_FILE, "w", encoding="utf-8") as f:
        f.write(md)


# ─── ページ設定 ───────────────────────────────────────────────

st.set_page_config(
    page_title="思考記録システム",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown("""
<style>
.badge {
    display: inline-block; padding: 2px 10px; border-radius: 12px;
    font-size: 0.78em; font-weight: 600; color: white;
}
</style>
""", unsafe_allow_html=True)

# ─── セッション初期化 ──────────────────────────────────────────

if "input_reset_count" not in st.session_state:
    st.session_state["input_reset_count"] = 0

if "current_file" not in st.session_state:
    files = get_project_files()
    st.session_state["current_file"] = files[0] if files else DEFAULT_FILE


# ─── サイドバー ───────────────────────────────────────────────

with st.sidebar:

    # ── プロジェクト管理 ────────────────────────────────────────
    st.header("📁 プロジェクト")

    project_files = get_project_files()
    cur = get_current_file()

    if project_files:
        idx = project_files.index(cur) if cur in project_files else 0
        selected = st.selectbox(
            "切り替え",
            project_files,
            index=idx,
            format_func=lambda f: Path(f).stem,
            key="project_selector",
        )
        if selected != cur:
            st.session_state["current_file"] = selected
            st.session_state["input_reset_count"] += 1
            st.cache_data.clear()
            st.rerun()
    else:
        st.caption("JSONファイルがありません")

    st.write("**新規プロジェクト作成**")
    new_name = st.text_input("プロジェクト名", placeholder="例: Jリーグ第2回", key="new_project_name", label_visibility="collapsed")
    if st.button("＋ 作成", use_container_width=True):
        name = new_name.strip()
        if not name:
            st.error("プロジェクト名を入力してください。")
        else:
            new_fp = f"{name}.json"
            if Path(new_fp).exists():
                st.error(f"「{name}」は既に存在します。")
            else:
                empty = {
                    "metadata": {
                        "created_at": datetime.now().isoformat(),
                        "updated_at": datetime.now().isoformat(),
                        "total_entries": 0,
                    },
                    "entries": [],
                }
                with open(new_fp, "w", encoding="utf-8") as f:
                    json.dump(empty, f, ensure_ascii=False, indent=2)
                st.session_state["current_file"] = new_fp
                st.session_state["input_reset_count"] += 1
                st.cache_data.clear()
                st.rerun()

    st.divider()

    # ── フェーズ ────────────────────────────────────────────────
    st.header("⚙️ フェーズ")
    phase = st.selectbox("分析フェーズを選択", PHASES, key="sidebar_phase")

    st.divider()

    # ── 統計 ────────────────────────────────────────────────────
    st.header("📊 統計")
    _data_stat = load_data()
    st.metric("総記録数", f"{len(_data_stat['entries'])} 件")
    phase_cnt = Counter(e["phase"] for e in _data_stat["entries"])
    for p in PHASES:
        if p in phase_cnt:
            st.write(f"**{p}**: {phase_cnt[p]}件")
    st.divider()
    if _data_stat["entries"]:
        highs = [e for e in _data_stat["entries"] if e["score"] >= HIGHLIGHT_THRESHOLD]
        st.metric(f"★ ハイライト ({HIGHLIGHT_THRESHOLD}点以上)", f"{len(highs)} 件")


# ─── タイトル（プロジェクト名を大きく表示） ───────────────────

st.title(f"🧠 {project_name()}")
st.caption(f"ファイル: `{get_current_file()}`")

# ─── タブ ─────────────────────────────────────────────────────

tab_input, tab_list, tab_graph = st.tabs(["✏️ 記録入力", "📋 一覧・削除", "🕸️ 思考の系譜"])


# ══ タブ1: 入力 ════════════════════════════════════════════════

with tab_input:
    st.subheader(f"【{phase}】 への記録")
    col_left, col_right = st.columns([3, 2])

    with col_left:
        type_sel = st.selectbox("思考の型", TYPES, key="input_type")
        label = SCORE_LABEL[type_sel]
        content = st.text_area(
            f"[{type_sel}] を入力",
            height=140,
            placeholder="ここに思考・発見・仮説などを入力...",
            key=f"input_content_{st.session_state['input_reset_count']}",
        )

    with col_right:
        st.write(f"**{label}**")
        score = st.slider("", 0, 100, 50, key="input_score", label_visibility="collapsed")
        filled = score // 10
        bar_html = (
            '<span style="font-family:monospace;font-size:1.3em;">'
            + '<span style="color:#ff6b35">' + "█" * filled + "</span>"
            + '<span style="color:#444">' + "░" * (10 - filled) + "</span>"
            + f' <b>{score}</b>点'
            + ("  <b>★</b>" if score >= HIGHLIGHT_THRESHOLD else "")
            + "</span>"
        )
        st.markdown(bar_html, unsafe_allow_html=True)
        st.write("")
        st.write("🔗 **関連ID**")
        _data_for_link = load_data()
        id_options = {
            f"ID:{e['id']}  [{e['phase']}/{e['type']}]  {e['content'][:22]}": e["id"]
            for e in _data_for_link["entries"]
        }
        related_labels = st.multiselect("過去の記録と紐付ける", list(id_options.keys()), key="input_related")
        related_ids = [id_options[lbl] for lbl in related_labels]

    if st.button("💾 保存する", type="primary", use_container_width=True):
        if not content.strip():
            st.error("内容を入力してください。")
        else:
            d = load_data()
            entry = {
                "id": next_id(d),
                "phase": phase,
                "type": type_sel,
                "label_name": label,
                "score": score,
                "content": content.strip(),
                "timestamp": datetime.now().isoformat(),
                "related_ids": related_ids,
            }
            d["entries"].append(entry)
            save_data(d)
            link_str = f"　リンク: {related_ids}" if related_ids else ""
            st.success(f"✓ 保存しました　ID:{entry['id']}{link_str}")
            st.session_state["input_reset_count"] += 1
            st.rerun()


# ══ タブ2: 一覧・削除 ══════════════════════════════════════════

with tab_list:
    d_list  = load_data()
    entries = d_list["entries"]

    if not entries:
        st.info("まだ記録がありません。")
    else:
        fc1, fc2, fc3 = st.columns(3)
        with fc1:
            f_phase = st.selectbox("フェーズ", ["すべて"] + PHASES, key="f_phase")
        with fc2:
            f_type = st.selectbox("型", ["すべて"] + TYPES, key="f_type")
        with fc3:
            f_highlight = st.checkbox(f"★ {HIGHLIGHT_THRESHOLD}点以上のみ", key="f_highlight")

        filtered = entries[:]
        if f_phase != "すべて":
            filtered = [e for e in filtered if e["phase"] == f_phase]
        if f_type != "すべて":
            filtered = [e for e in filtered if e["type"] == f_type]
        if f_highlight:
            filtered = [e for e in filtered if e["score"] >= HIGHLIGHT_THRESHOLD]

        st.caption(f"{len(filtered)} 件表示中（全 {len(entries)} 件）")
        st.divider()

        for e in reversed(filtered):
            color = CATEGORY_COLOR.get(e["type"], "#666")
            star  = "★ " if e["score"] >= HIGHLIGHT_THRESHOLD else ""
            ts    = e["timestamp"][:16].replace("T", " ")
            with st.container():
                c1, c2, c3, c4 = st.columns([1, 1.5, 5, 1])
                with c1:
                    st.markdown(f"### {star}ID:{e['id']}")
                    st.caption(ts)
                with c2:
                    st.markdown(
                        f'<span class="badge" style="background:{color}">{e["type"]}</span>',
                        unsafe_allow_html=True,
                    )
                    st.caption(e["phase"])
                with c3:
                    st.write(e["content"])
                    lname = e.get("label_name", "スコア")
                    bar   = "█" * (e["score"] // 10) + "░" * (10 - e["score"] // 10)
                    st.caption(f"{lname}: {e['score']}点  {bar}")
                    if e.get("related_ids"):
                        st.caption(f"🔗 リンク: {e['related_ids']}")
                with c4:
                    if st.button("🗑️ 削除", key=f"del_{e['id']}"):
                        d_list["entries"] = [x for x in d_list["entries"] if x["id"] != e["id"]]
                        save_data(d_list)
                        st.rerun()
                st.divider()


# ══ タブ3: Mermaid グラフ ══════════════════════════════════════

with tab_graph:
    d_graph = load_data()

    if d_graph["entries"]:
        pg: dict[str, list] = defaultdict(list)
        for e in d_graph["entries"]:
            pg[e["phase"]].append(e)
        active_phases = [p for p in PHASES if p in pg]
        if active_phases:
            cols = st.columns(len(active_phases))
            for i, p in enumerate(active_phases):
                grp   = pg[p]
                avg   = sum(e["score"] for e in grp) / len(grp)
                highs = sum(1 for e in grp if e["score"] >= HIGHLIGHT_THRESHOLD)
                cols[i].metric(p, f"{len(grp)} 件", f"平均 {avg:.0f}点 / ★{highs}件")
        st.divider()

    mermaid_code = build_mermaid_code(d_graph)
    svg_content  = get_mermaid_svg(mermaid_code)

    mermaid_html = f"""<!DOCTYPE html>
<html>
<head>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ background: #0e1117; width: 100vw; height: 100vh; overflow: hidden; }}
    #viewport {{ width: 100%; height: 100%; overflow: hidden; cursor: grab; user-select: none; }}
    #viewport.dragging {{ cursor: grabbing; }}
    #scene {{ transform-origin: 0 0; display: inline-block; padding: 20px; }}
    #controls {{
      position: fixed; top: 8px; right: 8px; z-index: 100; display: flex; gap: 4px;
    }}
    #controls button {{
      background: #1f2937; color: #fafafa; border: 1px solid #374151;
      border-radius: 6px; width: 32px; height: 32px; font-size: 1.1em; cursor: pointer;
    }}
    #controls button:hover {{ background: #374151; }}
  </style>
</head>
<body>
  <div id="controls">
    <button id="btn-in"    title="拡大">＋</button>
    <button id="btn-out"   title="縮小">－</button>
    <button id="btn-reset" title="リセット">⟳</button>
    <button id="btn-fit"   title="全体表示">⊡</button>
  </div>
  <div id="viewport">
    <div id="scene">{svg_content}</div>
  </div>
  <script>
    var scale=1,tx=0,ty=0;
    var vp=document.getElementById('viewport'),sc=document.getElementById('scene');
    function apply(){{sc.style.transform='translate('+tx+'px,'+ty+'px) scale('+scale+')';}}
    vp.addEventListener('wheel',function(e){{
      e.preventDefault();
      var r=vp.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top;
      var f=e.deltaY<0?1.15:1/1.15,ns=Math.max(0.05,Math.min(50,scale*f));
      tx=mx-(mx-tx)*(ns/scale);ty=my-(my-ty)*(ns/scale);scale=ns;apply();
    }},{{passive:false}});
    var drag=false,dx,dy;
    vp.addEventListener('mousedown',function(e){{drag=true;dx=e.clientX-tx;dy=e.clientY-ty;vp.classList.add('dragging');}});
    window.addEventListener('mousemove',function(e){{if(!drag)return;tx=e.clientX-dx;ty=e.clientY-dy;apply();}});
    window.addEventListener('mouseup',function(){{drag=false;vp.classList.remove('dragging');}});
    document.getElementById('btn-in').onclick    =function(){{scale=Math.min(50,scale*1.3);apply();}};
    document.getElementById('btn-out').onclick   =function(){{scale=Math.max(0.05,scale/1.3);apply();}};
    document.getElementById('btn-reset').onclick =function(){{scale=1;tx=0;ty=0;apply();}};
    document.getElementById('btn-fit').onclick   =function(){{
      var sw=sc.scrollWidth,sh=sc.scrollHeight,vw=vp.clientWidth,vh=vp.clientHeight;
      scale=Math.min(vw/sw,vh/sh)*0.9;tx=(vw-sw*scale)/2;ty=(vh-sh*scale)/2;apply();
    }};
  </script>
</body>
</html>"""

    components.html(mermaid_html, height=680, scrolling=False)

    col_a, col_b = st.columns(2)
    with col_a:
        with st.expander("📄 Mermaid コードを表示"):
            st.code(mermaid_code, language="text")
    with col_b:
        if st.button("💾 thought_flow.md に書き出す", use_container_width=True):
            save_flow_md(d_graph)
            st.success(f"thought_flow.md を保存しました。({len(d_graph['entries'])}件)")
