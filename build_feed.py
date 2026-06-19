#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
בונה פיד RSS + דף אינטרנט (HTML) מערוץ הטלגרם הציבורי של "הפרגוד".

תכונות:
  - ארכיון מצטבר (data.json) -> אפשר לגלול להיסטוריה ארוכה (לא רק 20 האחרונים)
  - סרטונים קצרים שטלגרם חושפת מתנגנים ישירות בתוך הדף (בפוסטים האחרונים)
  - תמונות נטענות "בעצלתיים" (lazy) לגלילה חלקה
  - מייצר feed.xml (RSS) + index.html

מקור: https://t.me/s/Moshepargod
"""

import os
import re
import json
import time
import html
import datetime
import email.utils

import requests
from bs4 import BeautifulSoup

# ----------------------------- הגדרות -----------------------------
CHANNEL = "Moshepargod"
CHANNEL_TITLE = "חדשות הפרגוד"
BASE = f"https://t.me/s/{CHANNEL}"
SITE_TITLE = "הפרגוד — עדכונים (לא רשמי)"
SITE_DESC = "עדכונים מערוץ הטלגרם הציבורי של הפרגוד. דף לא רשמי, נבנה אוטומטית."

DATA_FILE = "data.json"
MAX_ARCHIVE = 1000            # כמה פריטים לשמור ולהציג בדף. ערך גבוה = יותר היסטוריה אבל דף כבד יותר.
MAX_FEED_ITEMS = 80           # כמה פריטים לכלול בקובץ ה-RSS.
BACKFILL_PAGES_PER_RUN = 12   # כמה עמודי היסטוריה ישנים למשוך בכל ריצה (עד שהארכיון מתמלא).

try:
    from zoneinfo import ZoneInfo
    IL_TZ = ZoneInfo("Asia/Jerusalem")
except Exception:
    IL_TZ = datetime.timezone(datetime.timedelta(hours=3))

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


# ----------------------------- שליפה + פענוח -----------------------------
def fetch(url: str) -> str:
    r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    return r.text


def _bg_url(style: str):
    m = re.search(r"url\(['\"]?([^'\")]+)['\"]?\)", style or "")
    return m.group(1) if m else None


def parse_page(page_html: str):
    soup = BeautifulSoup(page_html, "html.parser")
    out = []
    for msg in soup.select(".tgme_widget_message"):
        try:
            post = msg.get("data-post")           # "Moshepargod/58660"
            if not post or "/" not in post:
                continue
            try:
                mid = int(post.split("/")[-1])
            except ValueError:
                continue
            link = "https://t.me/" + post

            # טקסט
            text = ""
            t = msg.select_one(".tgme_widget_message_text")
            if t:
                for br in t.find_all("br"):
                    br.replace_with("\n")
                text = t.get_text().strip()

            # תאריך (ISO)
            date_iso = None
            tm = msg.select_one("time[datetime]")
            if tm and tm.get("datetime"):
                date_iso = tm["datetime"]

            # תמונה
            img = None
            pw = msg.select_one(".tgme_widget_message_photo_wrap")
            if pw and pw.get("style"):
                img = _bg_url(pw["style"])

            # וידאו (קישור mp4 ישיר, אם טלגרם חושפת אותו)
            video_src = None
            vid = msg.select_one("video.tgme_widget_message_video, video.tgme_widget_message_roundvideo")
            if vid and vid.get("src"):
                video_src = vid["src"]

            # תמונת תצוגה של וידאו (אם אין תמונה רגילה)
            vthumb = msg.select_one(".tgme_widget_message_video_thumb")
            if not img and vthumb and vthumb.get("style"):
                img = _bg_url(vthumb["style"])

            has_video = bool(video_src) or bool(
                msg.select_one(".tgme_widget_message_video_player, .tgme_widget_message_video_thumb"))

            if not text and not img and not has_video:
                continue

            out.append({"id": mid, "link": link, "date": date_iso,
                        "text": text, "img": img,
                        "has_video": has_video, "video_src": video_src})
        except Exception:
            continue
    return out


# ----------------------------- ארכיון -----------------------------
def load_archive():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, encoding="utf-8") as f:
                data = json.load(f)
            return {int(it["id"]): it for it in data}
        except Exception:
            return {}
    return {}


def stable(it):
    """שדות יציבים לשמירה בארכיון (בלי ה-token המתחלף של הווידאו)."""
    return {"id": it["id"], "link": it["link"], "date": it.get("date"),
            "text": it.get("text", ""), "img": it.get("img"),
            "has_video": bool(it.get("has_video"))}


def upsert(archive, items):
    for it in items:
        archive[it["id"]] = stable(it)


# ----------------------------- עזרי תאריך/כותרת -----------------------------
def make_title(text: str) -> str:
    if not text:
        return CHANNEL_TITLE
    first = text.strip().split("\n")[0].strip()
    return (first[:90].rstrip() + "…") if len(first) > 90 else (first or CHANNEL_TITLE)


def parse_dt(date_iso):
    if not date_iso:
        return None
    try:
        return datetime.datetime.fromisoformat(date_iso)
    except Exception:
        return None


def to_rfc822(date_iso) -> str:
    dt = parse_dt(date_iso) or datetime.datetime.now(datetime.timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return email.utils.format_datetime(dt)


def fmt_local(date_iso) -> str:
    dt = parse_dt(date_iso)
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(IL_TZ).strftime("%d/%m/%Y %H:%M")


# ----------------------------- RSS -----------------------------
def build_rss(items) -> str:
    now = email.utils.format_datetime(datetime.datetime.now(datetime.timezone.utc))
    out = ['<?xml version="1.0" encoding="UTF-8"?>', '<rss version="2.0">', '<channel>',
           f"<title>{html.escape(SITE_TITLE)}</title>",
           f"<link>{html.escape(BASE)}</link>",
           f"<description>{html.escape(SITE_DESC)}</description>",
           "<language>he</language>", f"<lastBuildDate>{now}</lastBuildDate>"]
    for it in items[:MAX_FEED_ITEMS]:
        body = html.escape(it.get("text", "")).replace("\n", "<br/>")
        desc = (f'<img src="{html.escape(it["img"])}" /><br/>' if it.get("img") else "") + body
        out += ["<item>",
                f"<title>{html.escape(make_title(it.get('text', '')))}</title>",
                f"<link>{html.escape(it['link'])}</link>",
                f'<guid isPermaLink="true">{html.escape(it["link"])}</guid>',
                f"<pubDate>{to_rfc822(it.get('date'))}</pubDate>",
                f"<description>{html.escape(desc)}</description>",
                "</item>"]
    out += ["</channel>", "</rss>"]
    return "\n".join(out)


# ----------------------------- HTML -----------------------------
HTML_HEAD = """<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="300">
<title>הפרגוד — עדכונים</title>
<style>
  :root { --bg:#f4f5f7; --card:#ffffff; --ink:#1b1b1f; --muted:#6b7280; --accent:#0a7cff; --line:#e5e7eb; }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--ink);
         font-family:"Segoe UI",Arial,"Noto Sans Hebrew",sans-serif; line-height:1.6; }
  .wrap { max-width:720px; margin:0 auto; padding:16px; }
  header { background:var(--card); border:1px solid var(--line); border-radius:16px;
           padding:18px 20px; margin-bottom:16px; }
  header h1 { margin:0 0 4px; font-size:22px; }
  header .sub { color:var(--muted); font-size:14px; }
  a { color:var(--accent); }
  .card { background:var(--card); border:1px solid var(--line); border-radius:16px;
          padding:16px 18px; margin-bottom:14px; }
  .card .media { width:100%; max-height:460px; object-fit:cover; border-radius:12px;
                 margin-bottom:10px; background:#000; display:block; }
  .card .body { white-space:normal; word-break:break-word; }
  .card .body a { color:var(--accent); }
  .badge { display:inline-block; font-size:12px; color:var(--accent);
           border:1px solid var(--accent); border-radius:999px; padding:1px 8px; margin-bottom:8px; }
  .card .meta { display:flex; justify-content:space-between; align-items:center;
                margin-top:12px; padding-top:10px; border-top:1px solid var(--line);
                color:var(--muted); font-size:13px; }
  .card .meta a { text-decoration:none; font-weight:600; }
  footer { text-align:center; color:var(--muted); font-size:12px; padding:18px 0 28px; }
</style>
</head>
<body>
<div class="wrap">
"""

HTML_FOOT = """
<footer>דף לא רשמי, נבנה אוטומטית מהעמוד הציבורי של הערוץ &middot; מתעדכן כל כ-5 דקות</footer>
</div>
</body>
</html>
"""


def linkify(escaped_text: str) -> str:
    return re.sub(r"(https?://[^\s<]+)",
                  r'<a href="\1" target="_blank" rel="noopener">\1</a>',
                  escaped_text)


def build_html(items, fresh_video) -> str:
    updated = datetime.datetime.now(datetime.timezone.utc).astimezone(IL_TZ).strftime("%d/%m/%Y %H:%M")
    parts = [HTML_HEAD,
             '<header>'
             '<h1>הפרגוד — עדכונים אחרונים</h1>'
             f'<div class="sub">מקור: <a href="https://t.me/{CHANNEL}" target="_blank" rel="noopener">'
             f'ערוץ הטלגרם של הפרגוד</a> &middot; מציג {len(items)} עדכונים &middot; עודכן: {updated}</div>'
             '</header>']
    for it in items:
        body = linkify(html.escape(it.get("text", ""))).replace("\n", "<br>")

        media = ""
        vid = fresh_video.get(it["id"])
        if vid:  # סרטון טרי שניתן לנגן ישירות בדף
            poster = f' poster="{html.escape(it["img"])}"' if it.get("img") else ""
            media = (f'<video class="media" controls preload="none" playsinline{poster}>'
                     f'<source src="{html.escape(vid)}" type="video/mp4"></video>')
        elif it.get("img"):
            media = f'<img class="media" loading="lazy" src="{html.escape(it["img"])}" alt="">'

        badge = '<div class="badge">🎬 סרטון — צפה בטלגרם</div>' if (it.get("has_video") and not vid) else ""

        parts.append('<article class="card">'
                     f'{media}{badge}'
                     f'<div class="body">{body}</div>'
                     '<div class="meta">'
                     f'<span>{fmt_local(it.get("date"))}</span>'
                     f'<a href="{html.escape(it["link"])}" target="_blank" rel="noopener">צפה בטלגרם ↗</a>'
                     '</div></article>')
    parts.append(HTML_FOOT)
    return "\n".join(parts)


# ----------------------------- ראשי -----------------------------
def main():
    archive = load_archive()

    # 1) העמוד האחרון — הפוסטים החדשים ביותר (כאן ה-token של הווידאו טרי)
    latest = parse_page(fetch(BASE))
    fresh_video = {it["id"]: it["video_src"] for it in latest if it.get("video_src")}
    upsert(archive, latest)

    # 2) השלמת היסטוריה אחורה, עד שהארכיון מתמלא
    pages = 0
    while archive and len(archive) < MAX_ARCHIVE and pages < BACKFILL_PAGES_PER_RUN:
        min_id = min(archive.keys())
        try:
            older = parse_page(fetch(f"{BASE}?before={min_id}"))
        except Exception:
            break
        new_older = [it for it in older if it["id"] not in archive]
        if not new_older:
            break
        upsert(archive, older)
        pages += 1
        time.sleep(0.5)

    # מיון מהחדש לישן + חיתוך לגודל הארכיון
    items = sorted(archive.values(), key=lambda x: x["id"], reverse=True)[:MAX_ARCHIVE]
    archive = {it["id"]: it for it in items}

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(list(archive.values()), f, ensure_ascii=False)
    with open("feed.xml", "w", encoding="utf-8") as f:
        f.write(build_rss(items))
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(build_html(items, fresh_video))

    print(f"ארכיון: {len(items)} פריטים | סרטונים טריים: {len(fresh_video)} | "
          f"עמודי היסטוריה נמשכו בריצה זו: {pages}")


if __name__ == "__main__":
    main()
# (סוף הקובץ)
