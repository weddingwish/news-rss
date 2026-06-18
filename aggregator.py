#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
マーケティング支援向け ニュースアグリゲーター
  PR TIMES ＋ みんなの経済新聞ネットワーク等を収集し、
  「新規出店 / 資金調達 / 業界トレンド / 地域経済 / 営業候補」に自動分類して
  統合RSS と カテゴリ別RSS を public/ に生成する。
"""

import calendar
import html
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import feedparser
import yaml
from feedgen.feed import FeedGenerator

import ai  # AIエンリッチ層（ANTHROPIC_API_KEY がある時だけ動作）

# ---- 設定 ----------------------------------------------------------------
ROOT = Path(__file__).parent
OUT = ROOT / "public"
RETENTION_DAYS = 21        # 何日以内の記事を残すか
MAX_ITEMS_ALL = 300        # 統合フィードの最大件数
MAX_ITEMS_CAT = 150        # カテゴリ別フィードの最大件数
# 公開先URL。GitHub Pages 有効化後の URL に合わせて環境変数 or 下記を編集。
import os
SITE_URL = os.environ.get("SITE_URL", "https://example.github.io/news-rss")

JST = timezone(timedelta(hours=9))


def load_yaml(name):
    with open(ROOT / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


def clean_text(s):
    """HTMLタグ除去・実体参照デコード・空白圧縮"""
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def entry_epoch(entry):
    """記事の公開時刻を UNIX epoch(UTC) で返す。無ければ None。"""
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return calendar.timegm(t)
    return None


def classify(text, categories):
    """本文にキーワードが含まれるカテゴリkeyのリストを返す。"""
    hits = []
    for key, conf in categories.items():
        for kw in conf["keywords"]:
            if kw in text:
                hits.append(key)
                break
    return hits


def collect():
    sources = load_yaml("sources.yaml")["feeds"]
    kw = load_yaml("keywords.yaml")
    categories = kw["categories"]
    exclude = kw.get("exclude", [])
    now = calendar.timegm(datetime.now(timezone.utc).utctimetuple())
    cutoff = now - RETENTION_DAYS * 86400

    items = []
    seen = set()
    ok_sources = 0

    for src in sources:
        try:
            parsed = feedparser.parse(src["url"])
            if parsed.bozo and not parsed.entries:
                print(f"WARN  取得失敗: {src['name']} <{src['url']}> "
                      f"({getattr(parsed, 'bozo_exception', '')})", file=sys.stderr)
                continue
            if not parsed.entries:
                print(f"WARN  記事ゼロ: {src['name']} <{src['url']}>", file=sys.stderr)
                continue
            ok_sources += 1
        except Exception as e:  # noqa
            print(f"WARN  例外: {src['name']} <{src['url']}> ({e})", file=sys.stderr)
            continue

        for e in parsed.entries:
            link = (e.get("link") or "").strip()
            title = clean_text(e.get("title"))
            if not link or not title:
                continue
            if link in seen:
                continue
            seen.add(link)

            ts = entry_epoch(e)
            if ts is not None and ts < cutoff:
                continue  # 古い記事は除外

            summary = clean_text(e.get("summary") or e.get("description"))
            # 分類はタイトル基準（本文の会社概要「○年設立」「東証上場」等での誤分類を防ぐ）。
            cats = classify(title, categories)
            # force 指定のフィード（新店専用メディア等）は全記事をそのカテゴリ扱いに
            forced = src.get("force")
            if forced and forced not in cats:
                cats.append(forced)
            # NGワード（周年・グッズ等）を含む記事は営業候補から外す
            if any(ng in title for ng in exclude):
                cats = [c for c in cats if c not in ("shutten", "shikin")]
            # 営業候補 = 出店 or 資金調達
            if "shutten" in cats or "shikin" in cats:
                cats.append("eigyo")

            items.append({
                "title": title,
                "link": link,
                "summary": summary,
                "ts": ts if ts is not None else now,  # 日付不明は現在時刻扱い
                "dated": ts is not None,
                "source": src["name"],
                "region": src.get("region", ""),
                "cats": cats,
            })

    # 新しい順
    items.sort(key=lambda x: x["ts"], reverse=True)
    print(f"INFO  有効ソース {ok_sources}/{len(sources)} 件、収集記事 {len(items)} 件",
          file=sys.stderr)
    return items, categories


def cat_label(key, categories):
    if key == "eigyo":
        return "営業候補"
    return categories.get(key, {}).get("label", key)


def build_feed(items, categories, *, key, title, desc, filename, limit):
    """key=None なら全件。指定があればそのカテゴリのみ。"""
    fg = FeedGenerator()
    fg.id(f"{SITE_URL}/{filename}")
    fg.title(title)
    fg.link(href=SITE_URL, rel="alternate")
    fg.link(href=f"{SITE_URL}/{filename}", rel="self")
    fg.description(desc)
    fg.language("ja")
    fg.lastBuildDate(datetime.now(JST))

    count = 0
    for it in items:
        if key is not None and key not in it["cats"]:
            continue
        if count >= limit:
            break
        count += 1

        cat_labels = [cat_label(c, categories) for c in it["cats"]]
        tag = f"【{it['region']}/{'・'.join(cat_labels) or 'その他'}】" if it["region"] else \
              f"【{'・'.join(cat_labels) or 'その他'}】"

        fe = fg.add_entry()
        fe.id(it["link"])
        fe.title(tag + it["title"])
        fe.link(href=it["link"])
        body = it["summary"] or ""
        body = f"{body}\n\n— 出典: {it['source']}（{it['region']}）"
        fe.description(body)
        fe.source(title=it["source"])
        for c in it["cats"]:
            fe.category(term=cat_label(c, categories))
        if it["dated"]:
            fe.pubDate(datetime.fromtimestamp(it["ts"], tz=timezone.utc))

    OUT.mkdir(parents=True, exist_ok=True)
    fg.rss_file(str(OUT / filename), pretty=True)
    print(f"INFO  生成: {filename} ({count}件)", file=sys.stderr)
    return count


def build_index(feed_specs):
    rows = "\n".join(
        f'      <li><a href="{f["filename"]}">{f["title"]}</a> '
        f'<span class="c">{c}件</span><br><span class="d">{f["desc"]}</span></li>'
        for f, c in feed_specs
    )
    updated = datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    htmltext = f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>自社ニュースRSS</title>
<style>
 body{{font-family:system-ui,-apple-system,"Hiragino Kaku Gothic ProN",sans-serif;
   max-width:720px;margin:40px auto;padding:0 16px;color:#222;line-height:1.7}}
 h1{{font-size:20px}} ul{{list-style:none;padding:0}}
 li{{border:1px solid #e3e3e3;border-radius:10px;padding:14px 16px;margin:10px 0}}
 a{{font-weight:600;text-decoration:none;color:#0b66c3;font-size:16px}}
 .c{{color:#888;font-size:12px;margin-left:6px}} .d{{color:#666;font-size:13px}}
 .up{{color:#999;font-size:12px}}
</style></head><body>
 <h1>📰 自社ニュースRSS（マーケティング支援用）</h1>
 <p class="up">最終更新: {updated} JST ／ 毎朝9時に自動更新</p>
 <p>各リンクをFeedly・Slack・メール等のRSSリーダーに登録してください。</p>
 <ul>
{rows}
 </ul>
</body></html>"""
    (OUT / "index.html").write_text(htmltext, encoding="utf-8")
    print("INFO  生成: index.html", file=sys.stderr)


def build_digest(items, categories, feed_specs):
    """Slack等への配信用に digest.json を書き出す。
    主役は九州・関東の地場ネタ（PR TIMESに載らない地元の出店・開業・動き）。
    全国(PR TIMES)は『資金調達・M&A』だけを参考として少数添える。"""
    today = datetime.now(JST)
    now = calendar.timegm(datetime.now(timezone.utc).utctimetuple())
    # 「全国」以外はすべて地場扱い（新エリアを足しても自動で地場に入る）
    region_rank = {"九州": 0, "山口・広島": 1, "関東": 2}
    local_cut = now - 5 * 86400   # 地場は5日分
    nat_cut = now - 2 * 86400     # 全国は2日分

    def fmt(it):
        return {
            "title": it["title"],
            "link": it["link"],
            "region": it["region"],
            "source": it["source"],
            "cats": [cat_label(c, categories) for c in it["cats"] if c != "eigyo"],
            "ai_summary": it.get("ai_summary", ""),
            "ai_hook": it.get("ai_hook", ""),
            "ai_score": it.get("ai_score"),
        }

    # 地場（全国以外）の営業候補：直近5日
    local = [it for it in items
             if "eigyo" in it["cats"] and it["dated"]
             and it["region"] != "全国" and it["ts"] >= local_cut]
    local.sort(key=lambda it: (region_rank.get(it["region"], 9),
                               -(it.get("ai_score") or 3), -it["ts"]))
    local = [fmt(it) for it in local][:12]

    # 全国の資金調達・M&Aのみ（見逃せない高価値だけ）：直近2日
    national = [it for it in items
                if "eigyo" in it["cats"] and it["dated"]
                and it["region"] == "全国" and "shikin" in it["cats"]
                and it["ts"] >= nat_cut]
    national.sort(key=lambda it: (-(it.get("ai_score") or 3), -it["ts"]))
    national = [fmt(it) for it in national][:5]

    digest = {
        "date": today.strftime("%Y-%m-%d"),
        "generated_at": today.strftime("%Y-%m-%d %H:%M JST"),
        "site_url": SITE_URL,
        "counts": {s["filename"]: c for s, c in feed_specs},
        "local": local,
        "national": national,
    }
    (OUT / "digest.json").write_text(
        json.dumps(digest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"INFO  生成: digest.json (地場{len(local)}件 / 全国資金調達{len(national)}件)",
          file=sys.stderr)


def main():
    items, categories = collect()

    # AIエンリッチ（キーがあれば精度向上・要約・スコア付与。無ければ素通り）
    now = calendar.timegm(datetime.now(timezone.utc).utctimetuple())
    ai.enrich(items, now)

    specs = [
        {"key": "eigyo",  "title": "営業候補まとめ（新規出店＋資金調達）",
         "desc": "出店・開業・資金調達・新会社設立など、提案アプローチに直結するニュース",
         "filename": "feed-eigyo.xml",  "limit": MAX_ITEMS_CAT},
        {"key": "shutten", "title": "新規出店・開業ニュース",
         "desc": "新店オープン・開業・出店進出の情報",
         "filename": "feed-shutten.xml", "limit": MAX_ITEMS_CAT},
        {"key": "shikin",  "title": "資金調達・新会社設立",
         "desc": "資金調達・出資・上場・M&A・会社設立",
         "filename": "feed-shikin.xml",  "limit": MAX_ITEMS_CAT},
        {"key": "trend",   "title": "業界トレンド・市場ニュース",
         "desc": "市場調査・ランキング・新サービス等の業界動向",
         "filename": "feed-trend.xml",   "limit": MAX_ITEMS_CAT},
        {"key": "chiiki",  "title": "地域経済・自治体情報",
         "desc": "補助金・商店街・イベント・再開発など地場ネタ",
         "filename": "feed-chiiki.xml",  "limit": MAX_ITEMS_CAT},
        {"key": None,      "title": "全ニュース（統合フィード）",
         "desc": "九州・関西・関東＋全国プレスリリースの統合フィード",
         "filename": "feed.xml",         "limit": MAX_ITEMS_ALL},
    ]

    feed_specs = []
    for s in specs:
        c = build_feed(items, categories, key=s["key"], title=s["title"],
                       desc=s["desc"], filename=s["filename"], limit=s["limit"])
        feed_specs.append((s, c))

    build_index(feed_specs)
    build_digest(items, categories, feed_specs)
    print("DONE", file=sys.stderr)


if __name__ == "__main__":
    main()
