from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
import yt_dlp
import os
import asyncio
import time
from dotenv import load_dotenv

# ---------------- LOAD ENV ----------------
load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

DOWNLOAD_DIR = "downloads"
COOKIES_FILE = "instagram_cookies.txt"
MAX_CONCURRENT_DOWNLOADS = 1

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ---------------- APP ----------------
app = Client("downloader", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

user_links = {}
download_semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
MAIN_LOOP = None
last_progress_time = {}

yt_dlp.utils.std_headers["User-Agent"] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
)

# ---------------- PROGRESS ----------------
async def progress_hook(d, message, user_id):
    if d.get("status") != "downloading":
        return

    now = time.time()
    if now - last_progress_time.get(user_id, 0) < 3:
        return
    last_progress_time[user_id] = now

    downloaded = d.get("downloaded_bytes", 0)
    total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
    percent = (downloaded / total * 100) if total else 0

    bar = "█" * int(percent // 10) + "—" * (10 - int(percent // 10))

    try:
        await message.edit(
            f"⏳ **Downloading...**\n"
            f"`{percent:.1f}%`\n"
            f"[{bar}]"
        )
    except:
        pass

# ---------------- DOWNLOAD ----------------
def blocking_download(url, fmt, status_msg, user_id):
    def hook(d):
        if MAIN_LOOP:
            MAIN_LOOP.call_soon_threadsafe(
                asyncio.create_task,
                progress_hook(d, status_msg, user_id)
            )

    ydl_opts = {
        "format": fmt,
        "cookies": COOKIES_FILE,
        "outtmpl": f"{DOWNLOAD_DIR}/%(title)s.%(ext)s",
        "quiet": True,
        "progress_hooks": [hook],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = ydl.prepare_filename(info)
        return path, info.get("title", "Video")

async def download(url, fmt, status_msg, user_id):
    async with download_semaphore:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            blocking_download,
            url,
            fmt,
            status_msg,
            user_id,
        )

# ---------------- START ----------------
@app.on_message(filters.command("start"))
async def start(_, msg):
    global MAIN_LOOP
    if MAIN_LOOP is None:
        MAIN_LOOP = asyncio.get_running_loop()

    await msg.reply(
        "👋 **Welcome**\nSend YouTube / Instagram / Facebook link"
    )

# ---------------- LINK ----------------
@app.on_message(filters.text)
async def handle_link(_, msg):
    url = msg.text.strip()
    if not any(x in url for x in ("youtu", "instagram", "facebook", "fb.watch", "reel")):
        return

    temp = await msg.reply("🔍 Fetching info...")

    try:
        with yt_dlp.YoutubeDL({"quiet": True, "cookies": COOKIES_FILE}) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        return await temp.edit(f"❌ Error:\n`{e}`")

    user_links[msg.from_user.id] = url

    formats = info.get("formats", [])
    qualities = sorted({f["height"] for f in formats if f.get("height")})

    buttons = [[InlineKeyboardButton("🎵 Audio", callback_data="audio")]]
    for q in qualities:
        buttons.append([InlineKeyboardButton(f"{q}p", callback_data=str(q))])

    await temp.edit(
        "📌 **Select Quality**",
        reply_markup=InlineKeyboardMarkup(buttons),
    )

# ---------------- CALLBACK ----------------
@app.on_callback_query()
async def callback(_, call: CallbackQuery):
    user_id = call.from_user.id
    url = user_links.get(user_id)

    if not url:
        return await call.answer("❌ Link expired", show_alert=True)

    quality = call.data
    fmt = "bestaudio/best" if quality == "audio" else f"bestvideo[height<={quality}]+bestaudio/best"

    status = await call.message.reply("⏳ Starting download...")

    try:
        file_path, title = await download(url, fmt, status, user_id)

        await call.message.reply_video(
            video=file_path,
            caption=f"✅ Done\n🎬 {title}\n📌 {quality}",
        )

        await status.delete()
        os.remove(file_path)

    except Exception as e:
        await status.edit(f"❌ Error:\n`{e}`")

# ---------------- RUN ----------------
app.run()
