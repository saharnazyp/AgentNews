"""
ربات تجمیع اخبار هوش مصنوعی - نسخه ساده (بدون my.telegram.org)
-----------------------------------------------------------------
روش کار:
  1. برای هر کانال منبع، صفحه‌ی وب عمومی‌اش رو می‌خونیم: https://t.me/s/<channel>
     (این صفحه بدون نیاز به لاگین یا API در دسترسه، پس هیچ VPN یا api_id لازم نیست)
  2. پست‌های جدید (بعد از آخرین پستی که دیدیم) رو استخراج می‌کنیم: متن + عکس‌ها + ویدیو
  3. اگه مرتبط با AI بود، متن رو به فارسی ترجمه می‌کنیم
  4. با یک بات معمولی تلگرام (که از @BotFather گرفتیم) توی کانال خودمون پست می‌کنیم

هیچ‌کدوم از مراحل بالا نیاز به my.telegram.org یا Telethon نداره.
"""

import json
import logging
import os
import re
import time

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# تنظیمات
# ---------------------------------------------------------------------------
BOT_TOKEN = os.environ["BOT_TOKEN"]
TARGET_CHANNEL = os.environ["TARGET_CHANNEL"]  # مثلا @my_output_channel

SOURCE_CHANNELS = [
    c.strip().rstrip("/").split("/")[-1]  # هم یوزرنیم خام و هم لینک کامل رو قبول می‌کنه
    for c in os.environ["SOURCE_CHANNELS"].split(",")
    if c.strip()
]
# حذف تکراری‌ها با حفظ ترتیب
SOURCE_CHANNELS = list(dict.fromkeys(SOURCE_CHANNELS))

TRANSLATE_API_KEY = os.environ["TRANSLATE_API_KEY"]
TRANSLATE_BASE_URL = os.environ.get("TRANSLATE_BASE_URL", "https://api.deepseek.com/v1")
TRANSLATE_MODEL = os.environ.get("TRANSLATE_MODEL", "deepseek-chat")

FILTER_AI_ONLY = os.environ.get("FILTER_AI_ONLY", "True").lower() == "true"

STATE_PATH = "state.json"
BOT_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("ai_news_bot")

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# ---------------------------------------------------------------------------
# وضعیت (state) بین اجراها
# ---------------------------------------------------------------------------
def load_state():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"last_ids": {}}


def save_state(state):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# فیلتر موضوعی
# ---------------------------------------------------------------------------
AI_KEYWORDS = [
    "ai", "a.i.", "artificial intelligence", "machine learning", "llm",
    "gpt", "chatgpt", "openai", "claude", "anthropic", "gemini", "deepseek",
    "neural network", "deep learning", "هوش مصنوعی", "یادگیری ماشین",
    "مدل زبانی", "چت‌جی‌پی‌تی",
]


def is_ai_related(text: str) -> bool:
    if not FILTER_AI_ONLY:
        return True
    if not text:
        return False
    lowered = text.lower()
    return any(kw in lowered for kw in AI_KEYWORDS)


# ---------------------------------------------------------------------------
# ترجمه
# ---------------------------------------------------------------------------
def translate_to_persian(text: str) -> str:
    if not text or not text.strip():
        return ""
    try:
        resp = requests.post(
            f"{TRANSLATE_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {TRANSLATE_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": TRANSLATE_MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "متن ورودی رو به فارسیِ روان، طبیعی و خبری ترجمه کن. "
                            "فقط متن ترجمه‌شده رو برگردون، بدون هیچ توضیح یا مقدمه اضافه. "
                            "اصطلاحات تخصصی هوش مصنوعی رو به شکل رایج و قابل‌فهم فارسی بنویس."
                        ),
                    },
                    {"role": "user", "content": text},
                ],
                "temperature": 0.3,
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.error(f"خطا در ترجمه: {e}")
        return text


# ---------------------------------------------------------------------------
# خوندن پست‌های جدید یک کانال از نسخه‌ی وبِ عمومی‌اش
# ---------------------------------------------------------------------------
def fetch_channel_posts(channel: str):
    url = f"https://t.me/s/{channel}"
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    posts = []
    for msg_div in soup.select("div.tgme_widget_message"):
        data_post = msg_div.get("data-post")  # فرمت: "channel/123"
        if not data_post:
            continue
        try:
            msg_id = int(data_post.split("/")[-1])
        except ValueError:
            continue

        text_div = msg_div.select_one(".tgme_widget_message_text")
        text = text_div.get_text("\n").strip() if text_div else ""

        photo_urls = []
        for photo_wrap in msg_div.select(".tgme_widget_message_photo_wrap"):
            style = photo_wrap.get("style", "")
            m = re.search(r"url\('(.+?)'\)", style)
            if m:
                photo_urls.append(m.group(1))

        video_url = None
        video_tag = msg_div.select_one("video.tgme_widget_message_video")
        if video_tag and video_tag.get("src"):
            video_url = video_tag["src"]

        posts.append(
            {
                "id": msg_id,
                "text": text,
                "photo_urls": photo_urls,
                "video_url": video_url,
            }
        )

    posts.sort(key=lambda p: p["id"])  # قدیمی‌ترین اول
    return posts


# ---------------------------------------------------------------------------
# پست کردن در کانال مقصد با Bot API
# ---------------------------------------------------------------------------
def send_to_channel(post: dict, caption: str):
    photo_urls = post["photo_urls"]
    video_url = post["video_url"]

    try:
        if len(photo_urls) > 1:
            media = [{"type": "photo", "media": u} for u in photo_urls]
            media[0]["caption"] = caption
            media[0]["parse_mode"] = "HTML"
            r = requests.post(
                f"{BOT_API}/sendMediaGroup",
                json={"chat_id": TARGET_CHANNEL, "media": media},
                timeout=30,
            )
        elif len(photo_urls) == 1:
            r = requests.post(
                f"{BOT_API}/sendPhoto",
                json={"chat_id": TARGET_CHANNEL, "photo": photo_urls[0], "caption": caption},
                timeout=30,
            )
        elif video_url:
            r = requests.post(
                f"{BOT_API}/sendVideo",
                json={"chat_id": TARGET_CHANNEL, "video": video_url, "caption": caption},
                timeout=30,
            )
        elif caption.strip():
            r = requests.post(
                f"{BOT_API}/sendMessage",
                json={"chat_id": TARGET_CHANNEL, "text": caption},
                timeout=30,
            )
        else:
            return True  # چیزی برای پست کردن نبود

        ok = r.json().get("ok", False)
        if not ok:
            log.error(f"تلگرام خطا داد: {r.text}")
        return ok
    except Exception as e:
        log.error(f"خطا در ارسال به کانال: {e}")
        return False


# ---------------------------------------------------------------------------
# اجرای اصلی
# ---------------------------------------------------------------------------
def main():
    state = load_state()

    for channel in SOURCE_CHANNELS:
        try:
            posts = fetch_channel_posts(channel)
        except Exception as e:
            log.error(f"خطا در خوندن کانال {channel}: {e}")
            continue

        last_id = state["last_ids"].get(channel, 0)
        new_last_id = last_id

        for post in posts:
            if post["id"] <= last_id:
                continue
            new_last_id = max(new_last_id, post["id"])

            if not is_ai_related(post["text"]):
                continue

            translated = translate_to_persian(post["text"])
            ok = send_to_channel(post, translated)
            if ok:
                log.info(f"پست شد: {channel}/{post['id']}")
            time.sleep(1)  # جلوگیری از rate limit تلگرام

        state["last_ids"][channel] = new_last_id

    save_state(state)
    log.info("اجرای این دور تمام شد.")


if __name__ == "__main__":
    main()
