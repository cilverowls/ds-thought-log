import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

OUTPUT_FILE = "structured_output.json"
FLOW_FILE = "thought_flow.md"
INPUT_FILE = "＜＜初回コンペでの進捗＞＞.txt"
MODEL = "claude-sonnet-4-6"

PHASES = ["EDA", "特徴量選択", "モデル作成", "モデル改善"]
TYPES = ["ドメイン知識", "仮説", "検証", "結果", "Tips"]

SCORE_LABEL = {
    "ドメイン知識": "重要度",
    "仮説":         "ひらめき度",
    "検証":         "工夫度",
    "結果":         "発見度",
    "Tips":         "汎用性",
}

HIGHLIGHT_THRESHOLD = 80

CATEGORY_STYLE = {
    "ドメイン知識": "fill:#dbeafe,stroke:#3b82f6,color:#1e3a5f",
    "仮説":         "fill:#fef9c3,stroke:#eab308,color:#713f12",
    "検証":         "fill:#dcfce7,stroke:#22c55e,color:#14532d",
    "結果":         "fill:#fce7f3,stroke:#ec4899,color:#831843",
    "Tips":         "fill:#f3e8ff,stroke:#a855f7,color:#4a044e",
}
HIGH_SCORE_STYLE = "fill:#ff6b35,stroke:#c0392b,color:#fff,font-weight:bold"

PHASE_SAFE = {p: f"P{i+1}" for i, p in enumerate(PHASES)}


# ─── データ管理 ────────────────────────────────────────────────

def load_data() -> dict:
    p = Path(OUTPUT_FILE)
    if p.exists():
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        # 旧フォーマット（全アイテム/分類別）からマイグレーション
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
            raw = {
                "metadata": raw.get("metadata", {
                    "created_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat(),
                    "total_entries": 0,
                }),
                "entries": entries,
            }
            print(f"  [マイグレーション] 旧フォーマットから {len(entries)} 件を変換しました。")
        return raw
    return {
        "metadata": {
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "total_entries": 0,
        },
        "entries": [],
    }


def save_data(data: dict):
    data["metadata"]["updated_at"] = datetime.now().isoformat()
    data["metadata"]["total_entries"] = len(data["entries"])
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def next_id(data: dict) -> int:
    return max((e["id"] for e in data["entries"]), default=0) + 1


# ─── UI ヘルパー ───────────────────────────────────────────────

def hr(char="─", width=58):
    print(char * width)


def select_phase(current: str | None = None) -> str:
    hr()
    print("  フェーズを選択してください:")
    for i, p in enumerate(PHASES, 1):
        mark = "  ◀ 現在" if p == current else ""
        print(f"    {i}. {p}{mark}")
    while True:
        try:
            n = int(input("  番号 > ").strip())
            if 1 <= n <= len(PHASES):
                return PHASES[n - 1]
        except (ValueError, EOFError):
            pass
        print("  ※ 1〜4を入力してください。")


def select_type() -> str | None:
    """'SWITCH' / type文字列 / None(終了)"""
    print("\n  思考の型を選択 (s=フェーズ切替 / q=終了):")
    for i, t in enumerate(TYPES, 1):
        print(f"    {i}. {t:<8}  [{SCORE_LABEL[t]}]")
    while True:
        raw = input("  番号 > ").strip().lower()
        if raw == "q":
            return None
        if raw == "s":
            return "SWITCH"
        try:
            n = int(raw)
            if 1 <= n <= len(TYPES):
                return TYPES[n - 1]
        except ValueError:
            pass
        print("  ※ 1〜5 / s / q を入力してください。")


def show_recent(data: dict, n: int = 5):
    entries = data["entries"]
    if not entries:
        print("  (まだ記録がありません)\n")
        return
    recent = entries[-n:]
    hr("─")
    print(f"  直近 {len(recent)} 件")
    hr("─")
    for e in recent:
        ts = e["timestamp"][:16].replace("T", " ")
        links = f"  →{e['related_ids']}" if e.get("related_ids") else ""
        star = "★" if e["score"] >= HIGHLIGHT_THRESHOLD else " "
        label = e.get("label_name", "スコア")
        preview = e["content"][:28] + ("..." if len(e["content"]) > 28 else "")
        print(f"  {star}ID:{e['id']:>3}  [{e['phase']}/{e['type']:<6}]  {label}:{e['score']:>3}  {preview}{links}  ({ts})")
    print()


def input_int(prompt: str, lo: int = 0, hi: int = 100) -> int:
    while True:
        try:
            v = int(input(prompt).strip())
            if lo <= v <= hi:
                return v
        except (ValueError, EOFError):
            pass
        print(f"  ※ {lo}〜{hi} の整数を入力してください。")


def input_related_ids(data: dict) -> list[int]:
    existing = {e["id"] for e in data["entries"]}
    raw = input("  [関連付け] 関連するIDをカンマ区切りで (なければ空欄): ").strip()
    if not raw:
        return []
    result = []
    for tok in raw.split(","):
        try:
            id_ = int(tok.strip())
            if id_ in existing:
                result.append(id_)
            else:
                print(f"  ※ ID:{id_} は存在しません。スキップします。")
        except ValueError:
            pass
    return result


# ─── 対話セッション ────────────────────────────────────────────

def run_session():
    data = load_data()
    hr("=")
    print("  思考記録システム")
    print(f"  現在の記録数: {len(data['entries'])}件  |  保存先: {OUTPUT_FILE}")
    hr("=")

    phase = select_phase()

    while True:
        print(f"\n  ── フェーズ: 【{phase}】 ──")
        show_recent(data)

        t = select_type()
        if t is None:
            print("\n  セッションを終了します。")
            break
        if t == "SWITCH":
            phase = select_phase(current=phase)
            continue

        label = SCORE_LABEL[t]

        content = input(f"\n  [{t}] を入力してください\n  >> ").strip()
        if not content:
            print("  ※ 内容を入力してください。")
            continue

        score = input_int(f"  [{label}] を教えてください (0-100):\n  >> ")
        related = input_related_ids(data)

        entry = {
            "id": next_id(data),
            "phase": phase,
            "type": t,
            "label_name": label,
            "score": score,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "related_ids": related,
        }
        data["entries"].append(entry)
        save_data(data)

        link_str = f"  リンク: {related}" if related else ""
        print(f"\n  ✓ 保存しました  ID:{entry['id']}{link_str}")

    show_highlights_from_data(data)
    generate_mermaid_from_data(data)


# ─── ハイライト ────────────────────────────────────────────────

def show_highlights_from_data(data: dict, threshold: int = HIGHLIGHT_THRESHOLD):
    hits = sorted(
        [e for e in data["entries"] if e["score"] >= threshold],
        key=lambda x: x["score"], reverse=True,
    )
    hr("=")
    print(f"  ★ ハイライト: {threshold}点以上  ({len(hits)}件)")
    hr("=")
    if not hits:
        print("  (該当なし)\n")
        return
    for e in hits:
        bar = "█" * (e["score"] // 10)
        label = e.get("label_name", "スコア")
        print(f"  ID:{e['id']:>3}  [{e['phase']}/{e['type']:<6}]  {label}:{e['score']:>3}  {bar}")
        print(f"         {e['content']}")
    print()


def show_highlights(threshold: int = HIGHLIGHT_THRESHOLD):
    show_highlights_from_data(load_data(), threshold)


# ─── 全件表示 ──────────────────────────────────────────────────

def show_all(phase_filter: str | None = None):
    data = load_data()
    entries = data["entries"]
    if phase_filter:
        entries = [e for e in entries if e["phase"] == phase_filter]
    if not entries:
        print("記録がありません。")
        return
    hr("=")
    title = f"フェーズ: {phase_filter}" if phase_filter else "全記録"
    print(f"  {title}  ({len(entries)}件)")
    hr("=")
    for e in entries:
        ts = e["timestamp"][:16].replace("T", " ")
        links = f"  →{e['related_ids']}" if e.get("related_ids") else ""
        star = "★" if e["score"] >= HIGHLIGHT_THRESHOLD else " "
        label = e.get("label_name", "スコア")
        print(f"  {star}ID:{e['id']:>3}  [{e['phase']}/{e['type']:<6}]  {label}:{e['score']:>3}  {e['content'][:35]}  ({ts}){links}")
    print()


# ─── リンク専用コマンド ────────────────────────────────────────

def link_ids(id_a: int, id_b: int):
    data = load_data()
    existing = {e["id"] for e in data["entries"]}
    if id_a not in existing:
        print(f"ID:{id_a} が見つかりません。")
        return
    if id_b not in existing:
        print(f"ID:{id_b} が見つかりません。")
        return
    for e in data["entries"]:
        if e["id"] == id_a and id_b not in e["related_ids"]:
            e["related_ids"].append(id_b)
    save_data(data)
    print(f"ID:{id_a} → ID:{id_b} のリンクを追加しました。")


# ─── Mermaid フローチャート ────────────────────────────────────

def generate_mermaid_from_data(data: dict, output_file: str = FLOW_FILE):
    entries = data["entries"]
    if not entries:
        print("記録がありません。Mermaid 出力をスキップします。")
        return

    lines = ["```mermaid", "flowchart TD"]

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
            content_short = e["content"].replace('"', "'")
            label = f'ID:{e["id"]} {star}\\n{content_short}\\n[{e["type"]}] {label_name}:{e["score"]}'
            lines.append(f'        N{e["id"]}["{label}"]')
        lines.append("    end")
        lines.append("")

    # related_ids → 矢印
    for e in entries:
        for rid in e.get("related_ids", []):
            lines.append(f"    N{e['id']} --> N{rid}")

    lines.append("")

    # classDef
    for cat, style in CATEGORY_STYLE.items():
        safe = cat.replace(" ", "_")
        lines.append(f"    classDef {safe} {style}")
    lines.append(f"    classDef highlight {HIGH_SCORE_STYLE}")
    lines.append("")

    # class assignments
    type_nodes: dict[str, list[str]] = defaultdict(list)
    high_nodes: list[str] = []
    for e in entries:
        type_nodes[e["type"]].append(f"N{e['id']}")
        if e["score"] >= HIGHLIGHT_THRESHOLD:
            high_nodes.append(f"N{e['id']}")

    for t, nids in type_nodes.items():
        safe = t.replace(" ", "_")
        lines.append(f"    class {','.join(nids)} {safe}")
    if high_nodes:
        lines.append(f"    class {','.join(high_nodes)} highlight")

    lines.append("```")

    # フェーズ別密度テーブル
    density = [
        "\n## フェーズ別思考密度\n",
        "| フェーズ | 件数 | 平均スコア | ★ハイライト | 最多の型 |",
        "|---|---|---|---|---|",
    ]
    for phase in PHASES:
        group = phase_groups.get(phase, [])
        if not group:
            continue
        avg = sum(e["score"] for e in group) / len(group)
        highs = sum(1 for e in group if e["score"] >= HIGHLIGHT_THRESHOLD)
        top_type = Counter(e["type"] for e in group).most_common(1)[0][0]
        density.append(f"| {phase} | {len(group)} | {avg:.1f} | {highs} | {top_type} |")

    md = (
        f"# 思考フロー\n\n"
        f"> 生成日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"> 総記録数: {len(entries)}件 | ★ = {HIGHLIGHT_THRESHOLD}点以上\n\n"
        + "\n".join(lines)
        + "\n"
        + "\n".join(density)
        + "\n\n## カテゴリ凡例\n\n"
        "| カテゴリ | スコアラベル |\n|---|---|\n"
        + "\n".join(f"| {t} | {SCORE_LABEL[t]} |" for t in TYPES)
        + f"\n| ★ハイライト ({HIGHLIGHT_THRESHOLD}点以上) | — |\n"
    )

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(md)

    link_count = sum(len(e.get("related_ids", [])) for e in entries)
    print(f"Mermaid を {output_file} に保存しました。({len(entries)}ノード / ★{len(high_nodes)}件 / リンク{link_count}本)")


def generate_mermaid():
    generate_mermaid_from_data(load_data())


# ─── Claude 分類インポート ─────────────────────────────────────

SYSTEM_PROMPT = """あなたはデータ分析の思考プロセスを構造化するアシスタントです。
各項目を以下の5つのカテゴリに分類してください。

- ドメイン知識: 対象領域に関する背景知識や事実
- 仮説: 「〜ではないか」などの推測・仮定
- 検証: 実際に試した実験、モデル学習・評価
- 結果: 数値スコア、精度など具体的なアウトカム
- Tips: 実装のコツ、ツール活用法

返答はJSONのみ（```jsonブロック不要）:
[{"番号":"①","分類":"ドメイン知識","内容":"要約（50文字以内）"},...]"""


def classify_and_import():
    import anthropic

    try:
        with open(INPUT_FILE, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        print(f"[エラー] {INPUT_FILE} が見つかりません。")
        return

    client = anthropic.Anthropic()
    print("Claude に分類を依頼中...")
    response = client.messages.create(
        model=MODEL,
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [{
                "type": "text",
                "text": f"以下のデータ分析ノートを分類してください:\n\n{content}",
                "cache_control": {"type": "ephemeral"},
            }],
        }],
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        parts = raw.split("\n")
        raw = "\n".join(parts[1:-1] if parts[-1].strip() == "```" else parts[1:])

    classified = json.loads(raw)
    print(f"分類完了: {len(classified)}件\n")

    data = load_data()
    phase = select_phase()

    for item in classified:
        t = item["分類"]
        label = SCORE_LABEL.get(t, "スコア")
        print(f"\n  [{t}] {item['番号']}  {item['内容']}")
        score = input_int(f"  [{label}] (0-100): ")
        related = input_related_ids(data)

        entry = {
            "id": next_id(data),
            "phase": phase,
            "type": t,
            "label_name": label,
            "score": score,
            "content": item["内容"],
            "timestamp": datetime.now().isoformat(),
            "related_ids": related,
        }
        data["entries"].append(entry)
        save_data(data)
        print(f"  ✓ ID:{entry['id']} 保存")

    print(f"\n{len(classified)}件のインポートが完了しました。")
    generate_mermaid_from_data(data)


# ─── エントリポイント ──────────────────────────────────────────

def print_usage():
    print("""
使い方:
  python main.py                    対話セッション開始
  python main.py classify           テキストファイルをClaudeで分類・インポート
  python main.py show [phase]       記録一覧を表示
  python main.py highlight [N]      N点以上をハイライト表示 (default: 80)
  python main.py flowchart          thought_flow.md を再生成
  python main.py link <A> <B>       ID:A → ID:B のリンクを後付け追加
""")


def main():
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "classify":
            classify_and_import()
        elif cmd == "show":
            phase_filter = sys.argv[2] if len(sys.argv) > 2 else None
            show_all(phase_filter)
        elif cmd == "highlight":
            t = int(sys.argv[2]) if len(sys.argv) > 2 else HIGHLIGHT_THRESHOLD
            show_highlights(t)
        elif cmd == "flowchart":
            generate_mermaid()
        elif cmd == "link":
            if len(sys.argv) < 4:
                print("使い方: python main.py link <ID_A> <ID_B>")
                return
            link_ids(int(sys.argv[2]), int(sys.argv[3]))
        else:
            print_usage()
        return

    run_session()


if __name__ == "__main__":
    main()
