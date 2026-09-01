"""
ربات تجمیع اخبار هوش مصنوعی - نسخه ساده (بدون my.telegram.org)
-----------------------------------------------------------------
روش کار:
  1. برای هر کانال منبع، صفحه‌ی وب عمومی‌اش رو می‌خونیم: https://t.me/s/<channel>
     (این صفحه بدون نیاز به لاگین یا API در دسترسه، پس هیچ VPN یا api_id لازم نیست)
  2. پست‌های جدید (بعد از آخرین پستی که دیدیم) رو استخراج می‌کنیم: متن + عکس‌ها + ویدیو
  3. اگه مرتبط با AI بود، متن رو به فارسی ترجمه می‌کنیم
  4. عکس/ویدیو رو خودمون دانلود و مستقیم آپلود می‌کنیم (نه لینک‌دادن به تلگرام،
     چون لینک‌های CDN تلگرام پشت محافظت آنتی‌هاتلینک هستن و تلگرام خودش
     نمی‌تونه بگیرتشون)
  5. با یک بات معمولی تلگرام (که از @BotFather گرفتیم) توی کانال خودمون پست می‌کنیم

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
SOURCE_CHANNELS = list(dict.fromkeys(SOURCE_CHANNELS))  # حذف تکراری

TRANSLATE_API_KEY = os.environ["TRANSLATE_API_KEY"]
TRANSLATE_BASE_URL = os.environ.get("TRANSLATE_BASE_URL", "https://api.deepseek.com/v1")
TRANSLATE_MODEL = os.environ.get("TRANSLATE_MODEL", "deepseek-chat")

FILTER_AI_ONLY = os.environ.get("FILTER_AI_ONLY", "True").lower() == "true"

# در اولین اجرای هر کانال، چند تا از آخرین پست‌ها بک‌فیل بشن.
# نسخه‌ی وب کانال (t.me/s) خودش حداکثر ~۲۰ پست آخر رو نشون میده، پس عدد ۲۰
# یعنی «هر چی هست بیار» (سقف واقعی رو خود صفحه‌ی تلگرام تعیین می‌کنه، نه ما).
BACKFILL_ON_FIRST_RUN = int(os.environ.get("BACKFILL_ON_FIRST_RUN", "20"))

# حداکثر چند پست جدید از هر کانال در هر اجرا پردازش بشه (تا کانال‌های پرکار
# سهمیه‌ی کانال‌های دیگه رو نخورن). عدد بالا یعنی عملاً محدودیتی نیست.
MAX_POSTS_PER_CHANNEL = int(os.environ.get("MAX_POSTS_PER_CHANNEL", "20"))

# محدودیت‌های تلگرام برای طول متن
MAX_CAPTION_LEN = 1024   # کپشن عکس/ویدیو
MAX_MESSAGE_LEN = 4096   # پیام متنی خالی

# امضای ثابتی که زیر هر پست اضافه میشه (از Secrets قابل تغییره، وگرنه این پیش‌فرضه)
SIGNATURE = os.environ.get(
    "SIGNATURE",
    "AI mind | saharnaz\nInstagram: saharnaz.astronomy\nTelegram & Bale: @saharnazAILearning",
)

STATE_PATH = "state.json"
BOT_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("ai_news_bot")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://t.me/",
}


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


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def with_signature(text: str, limit: int) -> str:
    """متن رو کوتاه می‌کنه (در صورت لزوم) تا امضا زیرش جا بشه، بعد امضا رو اضافه می‌کنه."""
    footer = f"\n\n{SIGNATURE}" if SIGNATURE.strip() else ""
    body_limit = max(limit - len(footer), 0)
    body = truncate(text, body_limit) if text.strip() else text
    combined = f"{body}{footer}" if body.strip() else SIGNATURE
    return combined[:limit]


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
                            "تو یک مترجم و ویراستار خبری حرفه‌ای هستی که برای یک کانال خبری "
                            "هوش مصنوعی در تلگرام کار می‌کنی. متن انگلیسی زیر رو به فارسیِ "
                            "کاملاً روان، طبیعی و روزنامه‌نگارانه بازنویسی کن — نه ترجمه‌ی "
                            "کلمه‌به‌کلمه. یعنی:\n"
                            "- ساختار جمله رو کاملاً بر اساس دستور زبان فارسی بازچینی کن، "
                            "همون ترتیب کلمات جمله‌ی انگلیسی رو حفظ نکن.\n"
                            "- جمله‌های خیلی بلند رو در صورت نیاز به چند جمله‌ی کوتاه‌تر و "
                            "روان‌تر فارسی تبدیل کن.\n"
                            "- اسم شرکت‌ها، محصولات، و اصطلاحات رایج تخصصی (مثل ChatGPT، "
                            "OpenAI، مدل زبانی، API، LLM) رو به همون شکلی که در فارسی رایج و "
                            "قابل‌فهمه بنویس؛ لازم نیست همه‌چیز رو فارسی‌سازی کنی.\n"
                            "- اعداد، تاریخ‌ها و اسم‌های خاص رو دقیق و بدون تغییر منتقل کن.\n"
                            "- لحن خبری، مستقیم، و بدون اضافه‌گویی یا نظر شخصی باشه.\n"
                            "- هیچ توضیح، مقدمه، یا علامت نقل‌قول اضافه نکن؛ فقط و فقط متن "
                            "نهایی فارسی رو برگردون."
                        ),
                    },
                    {"role": "user", "content": text[:3000]},
                ],
                "temperature": 0.4,
            },
            timeout=15,
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
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    posts = []
    for msg_div in soup.select("div.tgme_widget_message"):
        data_post = msg_div.get("data-post")
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
            {"id": msg_id, "text": text, "photo_urls": photo_urls, "video_url": video_url}
        )

    posts.sort(key=lambda p: p["id"])
    return posts


# ---------------------------------------------------------------------------
# دانلود مدیا (چون تلگرام خودش نمی‌تونه لینک‌های محافظت‌شده رو fetch کنه)
# ---------------------------------------------------------------------------
def download_media(url: str, max_bytes: int = 20 * 1024 * 1024):
    r = requests.get(url, headers=HEADERS, timeout=20, stream=True)
    r.raise_for_status()
    content = r.content
    if len(content) > max_bytes:
        raise ValueError("فایل خیلی بزرگه")
    return content


# ---------------------------------------------------------------------------
# پست کردن در کانال مقصد با Bot API (آپلود مستقیم فایل، نه لینک)
# ---------------------------------------------------------------------------
def send_to_channel(post: dict, caption: str):
    photo_urls = post["photo_urls"]
    video_url = post["video_url"]

    try:
        if len(photo_urls) > 1:
            media = []
            files = {}
            for i, u in enumerate(photo_urls[:10]):  # سقف تلگرام برای آلبوم: ۱۰ تا
                content = download_media(u)
                field = f"photo{i}"
                files[field] = (f"{field}.jpg", content, "image/jpeg")
                item = {"type": "photo", "media": f"attach://{field}"}
                if i == 0:
                    item["caption"] = with_signature(caption, MAX_CAPTION_LEN)
                media.append(item)
            data = {"chat_id": TARGET_CHANNEL, "media": json.dumps(media)}
            r = requests.post(f"{BOT_API}/sendMediaGroup", data=data, files=files, timeout=60)

        elif len(photo_urls) == 1:
            content = download_media(photo_urls[0])
            files = {"photo": ("photo.jpg", content, "image/jpeg")}
            data = {"chat_id": TARGET_CHANNEL, "caption": with_signature(caption, MAX_CAPTION_LEN)}
            r = requests.post(f"{BOT_API}/sendPhoto", data=data, files=files, timeout=60)

        elif video_url:
            content = download_media(video_url)
            files = {"video": ("video.mp4", content, "video/mp4")}
            data = {"chat_id": TARGET_CHANNEL, "caption": with_signature(caption, MAX_CAPTION_LEN)}
            r = requests.post(f"{BOT_API}/sendVideo", data=data, files=files, timeout=60)

        elif caption.strip():
            r = requests.post(
                f"{BOT_API}/sendMessage",
                json={"chat_id": TARGET_CHANNEL, "text": with_signature(caption, MAX_MESSAGE_LEN)},
                timeout=30,
            )
        else:
            return True  # چیزی برای پست کردن نبود

        ok = r.json().get("ok", False)
        if not ok:
            log.error(f"تلگرام خطا داد: {r.text}")
        return ok

    except Exception as e:
        log.error(f"خطا در ارسال به کانال، تلاش با متن‌تنها: {e}")
        if caption.strip():
            try:
                r = requests.post(
                    f"{BOT_API}/sendMessage",
                    json={
                        "chat_id": TARGET_CHANNEL,
                        "text": with_signature(caption, MAX_MESSAGE_LEN),
                    },
                    timeout=30,
                )
                return r.json().get("ok", False)
            except Exception as e2:
                log.error(f"خطا در ارسال متن جایگزین: {e2}")
        return False


# ---------------------------------------------------------------------------
# اجرای اصلی
# ---------------------------------------------------------------------------
def main():
    state = load_state()
    total_processed = 0
    summary = []

    for channel in SOURCE_CHANNELS:
        try:
            posts = fetch_channel_posts(channel)
        except Exception as e:
            log.error(f"خطا در خوندن کانال {channel}: {e}")
            summary.append(f"{channel}: خطا در خوندن ({e})")
            continue

        is_first_run_for_channel = channel not in state["last_ids"]
        last_id = state["last_ids"].get(channel, 0)
        new_last_id = last_id

        candidates = [p for p in posts if p["id"] > last_id]
        if is_first_run_for_channel:
            candidates = candidates[-BACKFILL_ON_FIRST_RUN:] if BACKFILL_ON_FIRST_RUN > 0 else []

        # سهمیه‌ی این کانال در همین اجرا - بقیه‌ی پست‌های احتمالی برای اجرای بعدی می‌مونن
        to_process = candidates[:MAX_POSTS_PER_CHANNEL]
        remaining = len(candidates) - len(to_process)

        posted_count = 0
        for post in to_process:
            new_last_id = max(new_last_id, post["id"])
            total_processed += 1

            if not is_ai_related(post["text"]):
                continue

            translated = translate_to_persian(post["text"])
            ok = send_to_channel(post, translated)
            if ok:
                posted_count += 1
                log.info(f"پست شد: {channel}/{post['id']}")
            time.sleep(0.5)

        state["last_ids"][channel] = new_last_id
        note = f"{channel}: {posted_count} پست منتشر شد"
        if remaining > 0:
            note += f" ({remaining} پست دیگه برای اجرای بعدی مونده)"
        summary.append(note)

    save_state(state)
    log.info("خلاصه‌ی این اجرا:")
    for line in summary:
        log.info(f"  - {line}")
    log.info(f"اجرای این دور تمام شد. (مجموعاً {total_processed} پست بررسی شد)")


if __name__ == "__main__":
    main()
