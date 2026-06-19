#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
בונה פיד RSS ודף אינטרנט (HTML) מערוץ הטלגרם הציבורי של "הפרגוד".
מקור: https://t.me/s/Moshepargod  (עמוד התצוגה הציבורי של הערוץ)

הסקריפט מייצר שני קבצים:
  - feed.xml     : פיד RSS תקני (לחיבור לקוראי RSS)
  - index.html   : דף אינטרנט נקי בעברית (RTL) שמציג את העדכונים האחרונים

אין צורך בשום מפתח/הרשמה. הכול מבוסס על העמוד הציבורי של הערוץ.
"""

import re
import html
import datetime
import email.utils

import requests
from bs4 import BeautifulSoup

# ----------------------------- הגדרות -----------------------------
CHANNEL = "Moshepargod"                       # שם המשתמש של הערוץ בטלגרם
CHANNEL_TITLE = "חדשות הפרגוד"
SOURCE_URL = f"https://t.me/s/{CHANNEL}"
SITE_TITLE = "הפרגוד — עדכונים (לא רשמי)"
SITE_DESC = "עדכונים אחרונים מערוץ הטלגרם הציבורי של הפרגוד. דף לא רשמי, נבנה אוטומטית."
MAX_ITEMS = 40                                # כמה פריטים מקסימום להציג

# אזור זמן ישראל לתצוגת התאריכים
try:
    from zoneinfo import ZoneInfo
    IL_TZ = ZoneInfo("Asia/Jerusalem")
except Exception:  # גיבוי אם אין tzdata
    IL_TZ = datetime.timezone(datetime.timedelta(hours=3))

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


# ----------------------------- שליפה -----------------------------
def fetch_page() -> str:
    resp = requests.get(SOURCE_URL, headers={"User-Agent": UA}, timeout=30)
    resp.raise_for_status()
    return resp.text


# ----------------------------- פענוח -----------------------------
def parse_messages(page_html: str):
    soup = BeautifulSoup(page_html, "html.parser")
    items = []
    for msg in soup.select(".tgme_widget_message"):
        try:
            post = msg.get("data-post")            # לדוגמה: "Moshepargod/53435"
            if not post:
                continue
            link = "https://t.me/" + post

            # טקסט ההודעה (כולל שבירות שורה)
            text = ""
            text_el = msg.select_one(".tgme_widget_message_text")
            if text_el:
                for br in text_el.find_all("br"):
                    br.replace_with("\n")
                text = text_el.get_text()
            text = (text or "").strip()

            # תאריך/שעה
            dt = None
            time_el = msg.select_one("time[datetime]")
            if time_el and time_el.get("datetime"):
                try:
                    dt = datetime.datetime.fromisoformat(time_el["datetime"])
                except Exception:
                    dt = None

            # תמונה (אם יש) — מתוך background-image
            img = None
            photo = msg.select_one(".tgme_widget_message_photo_wrap")
            if photo and photo.get("style"):
                m = re.search(r"url\(['\"]?([^'\")]+)['\"]?\)", photo["style"])
                if m:
                    img = m.group(1)
            if not img:
                vthumb = msg.select_one(".tgme_widget_message_video_thumb")
                if vthumb and vthumb.get("style"):
                    m = re.search(r"url\(['\"]?([^'\")]+)['\"]?\)", vthumb["style"])
                    if m:
                        img = m.group(1)

            if not text and not img:
                continue

            items.append({"link": link, "text": text, "dt": dt, "img": img})
        except Exception:
            # הודעה בעייתית — מדלגים עליה ולא מפילים את הריצה
            continue

    items.reverse()              # החדש ביותר ראשון
    return items[:MAX_ITEMS]


def make_title(text: str) -> str:
    if not text:
        return CHANNEL_TITLE
    first = text.strip().split("\n")[0].strip()
    if len(first) > 90:
        first = first[:90].rstrip() + "…"
    return first or CHANNEL_TITLE


def to_rfc822(dt) -> str:
    if dt is None:
        dt = datetime.datetime.now(datetime.timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return email.utils.format_datetime(dt)


def fmt_local(dt) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(IL_TZ).strftime("%d/%m/%Y %H:%M")


# ----------------------------- RSS -----------------------------
def build_rss(items) -> str:
    now = email.utils.format_datetime(datetime.datetime.now(datetime.timezone.utc))
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<rss version="2.0">', '<channel>',
           f"<title>{html.escape(SITE_TITLE)}</title>",
           f"<link>{html.escape(SOURCE_URL)}</link>",
           f"<description>{html.escape(SITE_DESC)}</description>",
           "<language>he</language>",
           f"<lastBuildDate>{now}</lastBuildDate>"]
    for it in items:
        body = html.escape(it["text"]).replace("\n", "<br/>")
        desc = ""
        if it["img"]:
            desc += f'<img src="{html.escape(it["img"])}" /><br/>'
        desc += body
        out += ["<item>",
                f"<title>{html.escape(make_title(it['text']))}</title>",
                f"<link>{html.escape(it['link'])}</link>",
                f'<guid isPermaLink="true">{html.escape(it["link"])}</guid>',
                f"<pubDate>{to_rfc822(it['dt'])}</pubDate>",
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
<meta http-equiv="refresh" content="600">
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
  header a { color:var(--accent); text-decoration:none; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:16px;
          padding:16px 18px; margin-bottom:14px; }
  .card .thumb { width:100%; max-height:420px; object-fit:cover; border-radius:12px; margin-bottom:10px; }
  .card .body { white-space:normal; word-break:break-word; }
  .card .body a { color:var(--accent); }
  .card .meta { display:flex; justify-content:space-between; align-items:center;
                margin-top:12px; padding-top:10px; border-top:1px solid var(--line);
                color:var(--muted); font-size:13px; }
  .card .meta a { color:var(--accent); text-decoration:none; font-weight:600; }
  footer { text-align:center; color:var(--muted); font-size:12px; padding:18px 0 28px; }
</style>
</head>
<body>
<div class="wrap">
"""

HTML_FOOT = """
<footer>דף לא רשמי, נבנה אוטומטית מהעמוד הציבורי של הערוץ &middot; מתעדכן כל כ-20 דקות</footer>
</div>
</body>
</html>
"""


def linkify(escaped_text: str) -> str:
    return re.sub(r"(https?://[^\s<]+)",
                  r'<a href="\1" target="_blank" rel="noopener">\1</a>',
                  escaped_text)


def build_html(items) -> str:
    updated = datetime.datetime.now(datetime.timezone.utc).astimezone(IL_TZ).strftime("%d/%m/%Y %H:%M")
    parts = [HTML_HEAD]
    parts.append(
        '<header>'
        f'<h1>הפרגוד — עדכונים אחרונים</h1>'
        f'<div class="sub">מקור: <a href="{html.escape("https://t.me/" + CHANNEL)}" target="_blank" rel="noopener">'
        f'ערוץ הטלגרם של הפרגוד</a> &middot; עודכן לאחרונה: {updated}</div>'
        '</header>'
    )
    for it in items:
        body = linkify(html.escape(it["text"])).replace("\n", "<br>")
        thumb = f'<img class="thumb" src="{html.escape(it["img"])}" alt="">' if it["img"] else ""
        date_str = fmt_local(it["dt"])
        parts.append(
            '<article class="card">'
            f'{thumb}'
            f'<div class="body">{body}</div>'
            '<div class="meta">'
            f'<span>{date_str}</span>'
            f'<a href="{html.escape(it["link"])}" target="_blank" rel="noopener">צפה בטלגרם ↗</a>'
            '</div>'
            '</article>'
        )
    parts.append(HTML_FOOT)
    return "\n".join(parts)


# ----------------------------- ראשי -----------------------------
def main():
    page = fetch_page()
    items = parse_messages(page)
    print(f"נמצאו {len(items)} פריטים")

    with open("feed.xml", "w", encoding="utf-8") as f:
        f.write(build_rss(items))
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(build_html(items))
    print("נכתבו feed.xml ו-index.html")


if __name__ == "__main__":
    main()
