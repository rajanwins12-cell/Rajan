"""
RajanMusicBot - Combined features
Features included:
 - /song <name>      : search YouTube and send best audio (mp3)
 - /video <name>     : search YouTube and send video
 - /search <name>    : list top 5 YouTube results
 - /yt <link>        : download from YouTube link
 - /tiktok <link>    : download TikTok
 - /reels <link>     : download Instagram Reels
 - /lyrics <query>   : fetch lyrics (lyrics.ovh or fallback)
 - Inline mode       : @YourBot query -> top results
 - Voice chat player : /join, /leave, /play, /pause, /resume, /stop (uses pytgcalls)
Notes:
 - Fill your credentials in .env
 - Requires ffmpeg installed on the system
"""

import os
import asyncio
import traceback
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv

from pyrogram import Client, filters
from pyrogram.types import (
    InlineQueryResultArticle, InputTextMessageContent, InlineKeyboardMarkup, InlineKeyboardButton
)
from yt_dlp import YoutubeDL
import aiohttp

# Optional voice support
try:
    from pytgcalls import PyTgCalls
    from pytgcalls import idle as pytg_idle
    from pytgcalls.types import AudioPiped
    VOICE_AVAILABLE = True
except Exception:
    VOICE_AVAILABLE = False

load_dotenv()

API_ID = int(os.getenv("API_ID") or 0)
API_HASH = os.getenv("API_HASH") or ""
BOT_TOKEN = os.getenv("BOT_TOKEN") or ""
DOWNLOADS_DIR = os.getenv("DOWNLOADS_DIR", "./downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

# initialize client
app = Client("rajanbot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# thread pool for blocking ytdlp
POOL = ThreadPoolExecutor(max_workers=3)

YDL_OPTS_AUDIO = {
    "format": "bestaudio/best",
    "outtmpl": os.path.join(DOWNLOADS_DIR, "%(id)s.%(ext)s"),
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}],
}
YDL_OPTS_VIDEO = {
    "format": "bestvideo+bestaudio/best",
    "outtmpl": os.path.join(DOWNLOADS_DIR, "%(id)s.%(ext)s"),
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
}

async def run_yt(query_or_url, opts, download=True):
    loop = asyncio.get_running_loop()
    def _run():
        with YoutubeDL(opts) as ydl:
            return ydl.extract_info(query_or_url, download=download)
    return await loop.run_in_executor(POOL, _run)

async def search_youtube(query, limit=5):
    loop = asyncio.get_running_loop()
    def _run():
        with YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
            res = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
            return res.get("entries", [])
    return await loop.run_in_executor(POOL, _run)

async def fetch_lyrics(query):
    async with aiohttp.ClientSession() as sess:
        try:
            # lyrics.ovh needs artist/title; try naive approach
            # Try splitting "artist - title" if present
            if " - " in query:
                artist, title = query.split(" - ", 1)
                url = f"https://api.lyrics.ovh/v1/{artist}/{title}"
            else:
                # fallback to direct, might fail
                url = f"https://api.lyrics.ovh/v1/{query}"
            async with sess.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("lyrics")
        except Exception:
            return None
    return None

def find_file_by_id(vid):
    for fname in os.listdir(DOWNLOADS_DIR):
        if fname.startswith(vid):
            return os.path.join(DOWNLOADS_DIR, fname)
    return None

def cleanup_downloads():
    try:
        for f in os.listdir(DOWNLOADS_DIR):
            p = os.path.join(DOWNLOADS_DIR, f)
            if os.path.isfile(p):
                os.remove(p)
    except Exception:
        pass

@app.on_message(filters.command("start"))
async def start_cmd(client, message):
    await message.reply_text(
        "🎵 RajanMusicBot ready!\n\n"
        "Commands:\n"
        "/song <name>\n/video <name>\n/search <name>\n/yt <link>\n/tiktok <link>\n/reels <link>\n/lyrics <artist - title>\n"
        + ("/join /leave /play /pause /resume /stop (voice) " if VOICE_AVAILABLE else "")
    )

@app.on_message(filters.command("help"))
async def help_cmd(_, message):
    await message.reply_text("Use /song, /video, /search, /yt, /tiktok, /reels, /lyrics")

@app.on_message(filters.command("search"))
async def search_cmd(_, message):
    query = " ".join(message.command[1:])
    if not query:
        return await message.reply_text("Usage: /search <query>")
    m = await message.reply_text("🔎 Searching...")
    try:
        entries = await search_youtube(query, limit=5)
        text = []
        for i,e in enumerate(entries,1):
            title = e.get("title")
            dur = e.get("duration")
            url = e.get("webpage_url")
            text.append(f"{i}. {title} — {dur or '?'}s\n{url}")
        await m.edit("\n\n".join(text))
    except Exception as e:
        await m.edit(f"Error: {e}")

@app.on_message(filters.command("song"))
async def song_cmd(_, message):
    query = " ".join(message.command[1:])
    if not query:
        return await message.reply_text("Usage: /song <name>")
    msg = await message.reply_text("Searching & downloading audio...")
    try:
        info = await run_yt(f"ytsearch:{query}", YDL_OPTS_AUDIO, download=True)
        entry = info["entries"][0]
        vid = entry.get("id")
        file_path = find_file_by_id(vid)
        if not file_path:
            return await msg.edit("Download failed.")
        await msg.edit("Uploading audio...")
        await message.reply_audio(audio=file_path, title=entry.get("title"))
        await msg.delete()
    except Exception as e:
        await msg.edit(f"Error: {e}\\n{traceback.format_exc()}")

@app.on_message(filters.command("video"))
async def video_cmd(_, message):
    query = " ".join(message.command[1:])
    if not query:
        return await message.reply_text("Usage: /video <name or link>")
    msg = await message.reply_text("Searching & downloading video...")
    try:
        target = query if query.startswith("http") else f"ytsearch:{query}"
        info = await run_yt(target, YDL_OPTS_VIDEO, download=True)
        entry = info["entries"][0] if "entries" in info else info
        vid = entry.get("id")
        file_path = find_file_by_id(vid)
        if not file_path:
            return await msg.edit("Download failed.")
        await msg.edit("Uploading video...")
        await message.reply_video(video=file_path, caption=entry.get("title"))
        await msg.delete()
    except Exception as e:
        await msg.edit(f"Error: {e}\\n{traceback.format_exc()}")

@app.on_message(filters.command("yt"))
async def yt_cmd(_, message):
    arg = " ".join(message.command[1:])
    if not arg:
        return await message.reply_text("Usage: /yt <youtube link>")
    msg = await message.reply_text("Downloading from link...")
    try:
        info = await run_yt(arg, YDL_OPTS_AUDIO, download=True)
        entry = info["entries"][0] if "entries" in info else info
        vid = entry.get("id")
        file_path = find_file_by_id(vid)
        if not file_path:
            return await msg.edit("Download failed.")
        await msg.edit("Uploading audio...")
        await message.reply_audio(audio=file_path, title=entry.get("title"))
        await msg.delete()
    except Exception as e:
        await msg.edit(f"Error: {e}\\n{traceback.format_exc()}")

@app.on_message(filters.command("tiktok") | filters.command("reels"))
async def tiktok_reels_cmd(_, message):
    arg = " ".join(message.command[1:])
    if not arg:
        return await message.reply_text("Usage: /tiktok <link> or /reels <link>")
    msg = await message.reply_text("Downloading...")
    try:
        info = await run_yt(arg, YDL_OPTS_VIDEO, download=True)
        entry = info["entries"][0] if "entries" in info else info
        vid = entry.get("id")
        file_path = find_file_by_id(vid)
        if not file_path:
            return await msg.edit("Download failed.")
        await msg.edit("Uploading...")
        await message.reply_video(video=file_path, caption=entry.get("title"))
        await msg.delete()
    except Exception as e:
        await msg.edit(f"Error: {e}\\n{traceback.format_exc()}")

@app.on_message(filters.command("lyrics"))
async def lyrics_cmd(_, message):
    query = " ".join(message.command[1:])
    if not query:
        return await message.reply_text("Usage: /lyrics artist - title")
    m = await message.reply_text("Fetching lyrics...")
    lyrics = await fetch_lyrics(query)
    if lyrics:
        if len(lyrics) > 4000:
            await message.reply_text(lyrics[:4000] + "\\n\\n(lyrics truncated)")
        else:
            await message.reply_text(lyrics)
    else:
        await m.edit("Lyrics not found.")

@app.on_inline_query()
async def inline_query_handler(client, inline_query):
    q = inline_query.query.strip()
    if not q:
        await inline_query.answer(results=[], switch_pm_text="Type something", switch_pm_parameter="start")
        return
    try:
        entries = await search_youtube(q, limit=5)
        results = []
        for e in entries:
            title = e.get("title", "No title")
            url = e.get("webpage_url")
            desc = f\"{e.get('duration') or '?'}s • {e.get('uploader') or ''}\"
            content = InputTextMessageContent(f\"{title}\\n{url}\")
            btns = InlineKeyboardMarkup([[InlineKeyboardButton(\"Open YouTube\", url=url)]])
            results.append(InlineQueryResultArticle(title=title[:60], description=desc, input_message_content=content, reply_markup=btns, id=e.get('id')))
        await inline_query.answer(results=results, cache_time=10)
    except Exception:
        await inline_query.answer(results=[], switch_pm_text="Error", switch_pm_parameter="start")

# Voice chat (PyTgCalls) basic controls
VC = None
if VOICE_AVAILABLE:
    vc_client = PyTgCalls(app)
    queue = []
    current = None

    @app.on_message(filters.command("join"))
    async def join_vc(_, message):
        try:
            chat_id = message.chat.id
            await vc_client.join_group_call(chat_id, AudioPiped(os.path.join(DOWNLOADS_DIR, "silence.mp3")))
            await message.reply_text("Joined voice chat (use /play to play).")
        except Exception as e:
            await message.reply_text(f"Error joining VC: {e}")

    @app.on_message(filters.command("leave"))
    async def leave_vc(_, message):
        try:
            chat_id = message.chat.id
            await vc_client.leave_group_call(chat_id)
            await message.reply_text("Left voice chat.")
        except Exception as e:
            await message.reply_text(f"Error leaving VC: {e}")

    async def _play_next(chat_id):
        global current
        if not queue:
            current = None
            return
        src = queue.pop(0)
        current = src
        await vc_client.change_stream(chat_id, AudioPiped(src))

    @app.on_message(filters.command("play"))
    async def play_cmd(_, message):
        query = " ".join(message.command[1:])
        if not query:
            return await message.reply_text("Usage: /play <song name or YouTube link>")
        m = await message.reply_text("Searching & queuing...")
        try:
            info = await run_yt(f"ytsearch:{query}", YDL_OPTS_AUDIO, download=True)
            entry = info["entries"][0]
            vid = entry.get("id")
            file_path = find_file_by_id(vid)
            if not file_path:
                return await m.edit("Download failed.")
            chat_id = message.chat.id
            queue.append(file_path)
            await m.edit("Queued. If not playing, use /join then /play again.")
            # if not playing, start
            if current is None:
                await _play_next(chat_id)
        except Exception as e:
            await m.edit(f"Error: {e}\\n{traceback.format_exc()}")

    @app.on_message(filters.command("skip"))
    async def skip_cmd(_, message):
        try:
            chat_id = message.chat.id
            await _play_next(chat_id)
            await message.reply_text("Skipped.")
        except Exception as e:
            await message.reply_text(f"Error: {e}")

    @app.on_message(filters.command("stop"))
    async def stop_cmd(_, message):
        try:
            chat_id = message.chat.id
            queue.clear()
            await vc_client.change_stream(chat_id, AudioPiped(os.path.join(DOWNLOADS_DIR, "silence.mp3")))
            await message.reply_text("Stopped playback.")
        except Exception as e:
            await message.reply_text(f"Error: {e}")

    @app.on_message(filters.command("pause"))
    async def pause_cmd(_, message):
        await message.reply_text("Pause not implemented in this minimal example.")

    @app.on_message(filters.command("resume"))
    async def resume_cmd(_, message):
        await message.reply_text("Resume not implemented in this minimal example.")

if __name__ == "__main__":
    print("Starting RajanMusicBot...")
    if VOICE_AVAILABLE:
        vc_client.start()
    app.run()
