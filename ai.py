#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AIエンリッチ層（任意）— DeepSeek（OpenAI互換API）を使用。
環境変数 DEEPSEEK_API_KEY がある時だけ動作し、営業候補の精度を上げる：
  - 周年/グッズ/コラボ/キャンペーンだけの記事を除外（is_keep=False）
  - 1行要約・営業提案フック・営業価値スコア(1-5) を付与

キーが無ければ何もしない（＝キーワードモードのまま）。
セキュリティ:
  - APIキーは os.environ からのみ取得。ファイル/標準出力/ログには絶対に出さない。
  - 失敗してもパイプラインは止めない（フォールバックでキーワード結果を使う）。
"""
import json
import os
import sys
import urllib.request
import urllib.error

API_URL = os.environ.get("AI_BASE_URL", "https://api.deepseek.com") + "/chat/completions"
MODEL = os.environ.get("AI_MODEL", "deepseek-chat")
KEY_ENV = "DEEPSEEK_API_KEY"
BATCH = 10          # 1リクエストあたりの記事数
LOCAL_WINDOW = 5 * 86400   # 地場(全国以外)は更新が遅いので5日分を対象
NAT_WINDOW = 2 * 86400     # 全国(PR TIMES)は量が多いので直近2日に絞る


def _is_target(it, now):
    if "eigyo" not in it["cats"] or not it.get("dated"):
        return False
    win = NAT_WINDOW if it["region"] == "全国" else LOCAL_WINDOW
    return (now - it["ts"]) <= win

SYSTEM = (
    "あなたは日本のBtoBマーケティング会社の営業アシスタント。"
    "与えたニュース記事それぞれについて、提案アプローチに値する"
    "『本当の新規出店/開業』または『資金調達/新会社設立/M&A/業務提携』かを判定する。"
    "周年イベント・グッズ販売・コラボ商品・単なるキャンペーン告知は keep=false。"
    "必ず指定のJSONのみを返す。説明文やコードフェンスは書かない。"
)


def _has_key():
    return bool(os.environ.get(KEY_ENV, "").strip())


def _call(items_batch):
    """items_batch: [{idx,title,source,region}] -> {idx: enrichment}"""
    listing = "\n".join(
        f'{it["idx"]}. [{it["region"]}/{it["source"]}] {it["title"]}'
        for it in items_batch
    )
    prompt = (
        "次の記事を判定し、キー \"results\" に配列を持つJSONオブジェクトのみを返す。\n"
        "配列の各要素のキー: idx(整数), keep(boolean), "
        "cat(\"新規出店\"|\"資金調達\"|\"その他\"), "
        "summary(40字以内の要約), hook(40字以内の営業提案フック), "
        "score(1-5の整数:営業価値)\n\n"
        f"記事:\n{listing}"
    )
    body = json.dumps({
        "model": MODEL,
        "max_tokens": 2000,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": prompt},
        ],
    }).encode("utf-8")

    req = urllib.request.Request(
        API_URL, data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + os.environ[KEY_ENV],  # ヘッダーにのみ使用
        },
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    text = data["choices"][0]["message"]["content"].strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):]
    obj = json.loads(text[text.find("{"): text.rfind("}") + 1])
    arr = obj.get("results", obj.get("items", []))
    return {int(o["idx"]): o for o in arr if "idx" in o}


def enrich(items, now_epoch):
    """items を破壊的に更新。ai_keep / ai_summary / ai_hook / ai_score を付与。"""
    if not _has_key():
        print(f"INFO  {KEY_ENV} 未設定 → AIエンリッチをスキップ（キーワードモード）",
              file=sys.stderr)
        return

    targets = [it for it in items if _is_target(it, now_epoch)]
    if not targets:
        print("INFO  AI対象の新着営業候補なし", file=sys.stderr)
        return

    print(f"INFO  AIエンリッチ対象 {len(targets)}件 (model={MODEL})", file=sys.stderr)
    enriched = 0
    for i in range(0, len(targets), BATCH):
        chunk = targets[i:i + BATCH]
        payload = [{"idx": idx, "title": it["title"],
                    "source": it["source"], "region": it["region"]}
                   for idx, it in enumerate(chunk, start=i)]
        try:
            result = _call(payload)
        except (urllib.error.URLError, urllib.error.HTTPError,
                ValueError, KeyError) as e:
            # キー文字列は例外に含めない。安全なメッセージのみ。
            print(f"WARN  AI呼び出し失敗（この分はキーワード結果で継続）: {type(e).__name__}",
                  file=sys.stderr)
            continue
        for idx, it in enumerate(chunk, start=i):
            o = result.get(idx)
            if not o:
                continue
            it["ai_keep"] = bool(o.get("keep", True))
            it["ai_summary"] = str(o.get("summary", ""))[:60]
            it["ai_hook"] = str(o.get("hook", ""))[:60]
            try:
                it["ai_score"] = int(o.get("score", 3))
            except (TypeError, ValueError):
                it["ai_score"] = 3
            enriched += 1

    # AIが「営業候補ではない」と判定したものは eigyo から除外
    dropped = 0
    for it in targets:
        if it.get("ai_keep") is False and "eigyo" in it["cats"]:
            it["cats"] = [c for c in it["cats"] if c != "eigyo"]
            dropped += 1
    print(f"INFO  AIエンリッチ完了 付与{enriched}件 / 営業候補から除外{dropped}件",
          file=sys.stderr)
