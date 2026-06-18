#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
public/digest.json を読み、Slack の Incoming Webhook に「今日の営業候補ニュース」を投稿する。
環境変数 SLACK_WEBHOOK_URL が無い場合は何もしない（ローカル実行で誤爆しないように）。
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
DIGEST = ROOT / "public" / "digest.json"


def _item_text(it):
    score = it.get("ai_score")
    score_txt = f"  _営業度{int(score)}/5_" if score else ""
    meta = " / ".join(t for t in ([it.get("region")] + it.get("cats", [])) if t)
    line = f"• <{it['link']}|{it['title']}>{score_txt}\n  {meta} ・ {it.get('source','')}"
    if it.get("ai_hook"):
        line += f"\n  提案: {it['ai_hook']}"
    return line


def build_blocks(d):
    site = d.get("site_url", "")
    local = d.get("local", [])
    national = d.get("national", [])
    counts = d.get("counts", {})

    blocks = [
        {"type": "header",
         "text": {"type": "plain_text", "text": f"今日の営業候補ニュース  {d.get('date','')}",
                  "emoji": False}},
        {"type": "context",
         "elements": [{"type": "mrkdwn",
                       "text": f"九州・関東の地場ネタ中心 ／ 更新 {d.get('generated_at','')}"}]},
        {"type": "divider"},
        {"type": "section",
         "text": {"type": "mrkdwn", "text": "*地場の新店・開業・動き（九州・関東）*"}},
    ]

    if not local:
        blocks.append({"type": "section",
                       "text": {"type": "mrkdwn", "text": "直近の地場ネタはありません。"}})
    else:
        for it in local:
            blocks.append({"type": "section",
                           "text": {"type": "mrkdwn", "text": _item_text(it)}})

    if national:
        blocks.append({"type": "divider"})
        blocks.append({"type": "section",
                       "text": {"type": "mrkdwn", "text": "*全国の資金調達・M&A（参考）*"}})
        for it in national:
            blocks.append({"type": "section",
                           "text": {"type": "mrkdwn", "text": _item_text(it)}})

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn",
                      "text": f"全フィード一覧: {site}/  ・  統合RSS: {site}/feed.xml"}]
    })
    return blocks


def main():
    webhook = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if not webhook:
        print("INFO  SLACK_WEBHOOK_URL 未設定のためSlack投稿をスキップ", file=sys.stderr)
        return
    if not DIGEST.exists():
        print("WARN  digest.json が無い。先に aggregator.py を実行してください", file=sys.stderr)
        return

    d = json.loads(DIGEST.read_text(encoding="utf-8"))
    payload = {"blocks": build_blocks(d)}

    req = urllib.request.Request(
        webhook,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8", "ignore")
        print(f"INFO  Slack投稿 status={resp.status} body={body}", file=sys.stderr)


if __name__ == "__main__":
    main()
