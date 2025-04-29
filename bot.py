import os
import asyncio
import subprocess
import re
import json
from datetime import datetime
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ParseMode, ChatType

API_ID = "29272284"
API_HASH = "d6a6264a583e795b73812dd0549da98b"
BOT_TOKEN = "7891671369:AAGkDRrVj0vLLipMf3qxIB9OGbFYphSLM00"

app = Client("my_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Message templates (styled with HTML, enhanced design)
START_MSG = "<b>🎬 Starting download for</b> <i>{}</i> <b>with duration</b> <i>{}</i> 🎥"
DOWNLOAD_BAR = "<b>📥 Downloading {}...</b>\n<b>[{}]</b> <i>{}%</i> 🚀"
UPLOAD_BAR = "<b>📤 Uploading {}...</b>\n<b>[{}]</b> <i>{}%</i> 🌟"
UPLOAD_DONE = "<b>✅ Upload completed successfully!</b> 🎉"
VIDEO_CAPTION = "<code>{}</code>"
ERROR_MSG = "<b>❌ Error:</b> <i>{}</i> 😔"
INVALID_FORMAT = "<b>⚠️ Usage:</b> /dl m3u8_link hh:mm:ss filename [audio_streams] <b>or</b> /dl channel_name hh:mm:ss"
INVALID_TIME = "<b>⚠️ Invalid time format. Please use hh:mm:ss (max 02:00:00).</b> ⏰"
CHANNEL_NOT_FOUND = "<b>⚠️ Channel not found in channel.json.</b> 🔍"
ID_ADDED = "<b>✅ Chat ID {} added successfully!</b>"
INVALID_ID = "<b>⚠️ Invalid chat ID format or unauthorized user.</b>"
UNAUTHORIZED = "<b>⚠️ You are not authorized to use this command.</b>"
BUSY_MSG = "<b>⚠️ Bot is currently downloading another channel. Please wait.</b>"
CHANNEL_LIST = "<b>📺 Available Channels:</b>\n{}"
HELP_MSG = "<b>ℹ️ Bot Commands:</b>\n" \
           "/dl - Download video (Usage: /dl channel_name hh:mm:ss or /dl m3u8_link hh:mm:ss filename [audio_streams])\n" \
           "/channel - List all available channels\n" \
           "/use - Show bot usage information\n" \
           "/help - Show this help message\n" \
           "/id - Add authorized chat ID (owner only)"
USE_MSG = "<b>📚 Bot Usage:</b>\n" \
          "- Max download duration: 2 hours\n" \
          "- One channel download at a time\n" \
          "- All users in supergroup (-1002515413990) can use the bot\n" \
          "- Use /channel to see available channels\n" \
          "- Contact @Jasssaini98 for support"

# Animation emojis
ANIMATION_EMOJIS = ["🌀", "⚡", "🔥", "🌠", "🚀", "🎥", "🌟", "💫"]
animation_index = 0

# Authorized chat IDs and username storage
ALLOWED_CHAT_IDS_FILE = "allowed_chat_ids.json"
OWNER_CHAT_ID = 5730407948
ALLOWED_USERNAME = "@Jasssaini98"
SPECIAL_SUPERGROUP_ID = -1002515413990
ALLOWED_CHAT_IDS = []

# Download lock
download_lock = asyncio.Lock()
is_downloading = False

def load_allowed_chat_ids():
    try:
        if os.path.exists(ALLOWED_CHAT_IDS_FILE):
            with open(ALLOWED_CHAT_IDS_FILE, "r") as f:
                chat_ids = json.load(f)
                if SPECIAL_SUPERGROUP_ID not in chat_ids:
                    chat_ids.append(SPECIAL_SUPERGROUP_ID)
                return chat_ids
        return [OWNER_CHAT_ID, SPECIAL_SUPERGROUP_ID]
    except Exception as e:
        print(f"Error loading allowed chat IDs: {e}")
        return [OWNER_CHAT_ID, SPECIAL_SUPERGROUP_ID]

def save_allowed_chat_ids(chat_ids):
    try:
        with open(ALLOWED_CHAT_IDS_FILE, "w") as f:
            json.dump(chat_ids, f)
    except Exception as e:
        print(f"Error saving allowed chat IDs: {e}")

ALLOWED_CHAT_IDS = load_allowed_chat_ids()

# Load channels from channel.json
def load_channels():
    try:
        if os.path.exists("channel.json"):
            with open("channel.json", "r") as f:
                data = json.load(f)
                return {channel["name"].lower(): channel["url"] for channel in data.get("channels", [])}
        return {}
    except Exception as e:
        print(f"Error loading channel.json: {e}")
        return {}

channels = load_channels()

async def is_user_admin(client: Client, chat_id: int, user_id: int) -> bool:
    try:
        member = await client.get_chat_member(chat_id, user_id)
        return member.status in ["administrator", "creator"]
    except Exception as e:
        print(f"Error checking admin status: {e}")
        return False

async def update_progress(message: Message, percentage: int, channel_name: str, bar_type: str = "download"):
    global animation_index
    bar_length = 10
    filled = "█" * (percentage // 10)
    empty = "░" * (bar_length - percentage // 10)
    anim_emoji = ANIMATION_EMOJIS[animation_index % len(ANIMATION_EMOJIS)]
    animation_index += 1
    text = DOWNLOAD_BAR if bar_type == "download" else UPLOAD_BAR
    try:
        await message.edit_text(
            text.format(anim_emoji, filled + empty, percentage, channel_name),
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        print(f"Progress update error: {e}")

async def get_stream_info(m3u8_link: str) -> tuple:
    try:
        command = [
            'ffprobe',
            '-v', 'quiet',
            '-print_format', 'json',
            '-show_streams',
            m3u8_link
        ]
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            print(f"ffprobe failed: {stderr.decode()}")
            return [], "Unknown"
        data = json.loads(stdout)
        audio_streams = [
            {
                'index': stream['index'],
                'language': stream.get('tags', {}).get('language', 'unknown')
            }
            for stream in data['streams']
            if stream['codec_type'] == 'audio'
        ]
        video_quality = "Unknown"
        for stream in data['streams']:
            if stream['codec_type'] == 'video':
                height = stream.get('height', 0)
                if height >= 2160:
                    video_quality = "2160p"
                elif height >= 1080:
                    video_quality = "1080p"
                elif height >= 720:
                    video_quality = "720p"
                elif height >= 480:
                    video_quality = "480p"
                elif height >= 360:
                    video_quality = "360p"
                break
        print(f"Audio streams found: {audio_streams}, Video quality: {video_quality}")
        return audio_streams, video_quality
    except Exception as e:
        print(f"ffprobe error: {e}")
        return [], "Unknown"

async def download_m3u8(m3u8_link: str, duration: str, filename: str, audio_langs: list, status_msg: Message, channel_name: str) -> tuple:
    global is_downloading
    try:
        hh, mm, ss = map(int, duration.split(':'))
        total_seconds = hh * 3600 + mm * 60 + ss

        audio_streams, video_quality = await get_stream_info(m3u8_link)
        selected_streams = []
        selected_names = []
        if audio_streams:
            if audio_langs:
                for stream in audio_streams:
                    if stream['language'].lower() in [lang.lower() for lang in audio_langs]:
                        selected_streams.append(stream['index'])
                        selected_names.append(stream['language'])
            else:
                selected_streams = [stream['index'] for stream in audio_streams]
                selected_names = [stream['language'] for stream in audio_streams]
        else:
            print("No audio streams found, downloading video only.")

        command = ['ffmpeg', '-i', m3u8_link, '-t', duration, '-c', 'copy']
        command.extend(['-map', '0:v'])
        for stream_index in selected_streams:
            command.extend(['-map', f'0:{stream_index}'])
        command.append(filename)

        print(f"Running ffmpeg command: {' '.join(command)}")
        process = subprocess.Popen(
            command,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )

        time_regex = re.compile(r"time=(\d{2}):(\d{2}):(\d{2})\.\d+")
        last_percentage = -1
        last_update = 0
        ffmpeg_stderr = []
        while process.poll() is None:
            line = process.stderr.readline()
            ffmpeg_stderr.append(line)
            match = time_regex.search(line)
            if match:
                h, m, s = map(int, match.groups())
                current_seconds = h * 3600 + m * 60 + s
                percentage = min(int((current_seconds / total_seconds) * 100), 100)
                current_time = asyncio.get_event_loop().time()
                if percentage > last_percentage and current_time - last_update >= 1:
                    await update_progress(status_msg, percentage, channel_name, "download")
                    last_percentage = percentage
                    last_update = current_time
            await asyncio.sleep(0.1)

        while True:
            line = process.stderr.readline()
            if not line:
                break
            ffmpeg_stderr.append(line)

        if process.returncode != 0 or not os.path.exists(filename):
            print(f"File {filename} not created! ffmpeg stderr: {''.join(ffmpeg_stderr)}")
            return False, [], video_quality
        print(f"File {filename} created successfully.")
        return True, selected_names, video_quality
    except Exception as e:
        print(f"Download error: {e}")
        return False, [], "Unknown"
    finally:
        is_downloading = False

async def upload_with_progress(client: Client, chat_id: int, filename: str, audio_names: list, status_msg: Message, channel_name: str, duration: str, video_quality: str) -> bool:
    try:
        file_size = os.path.getsize(filename)
        last_percentage = -1
        last_update = 0

        async def progress_callback(current: int, total: int):
            nonlocal last_percentage, last_update
            percentage = min(int((current / file_size) * 100), 100)
            current_time = asyncio.get_event_loop().time()
            if percentage > last_percentage and current_time - last_update >= 1:
                await update_progress(status_msg, percentage, channel_name, "upload")
                last_percentage = percentage
                last_update = current_time

        audio_langs = "-".join([lang.upper() for lang in audio_names]) if audio_names else "NONE"
        duration_formatted = duration.replace(":", ".")
        caption_filename = f"{channel_name.upper()}.[{duration_formatted}].{video_quality}.HQ.TPLAY.WEB-DL.{audio_langs}.AAC2.0.128K.H264-jass.mkv"
        await client.send_video(
            chat_id=chat_id,
            video=filename,
            caption=VIDEO_CAPTION.format(caption_filename),
            parse_mode=ParseMode.HTML,
            progress=progress_callback
        )
        return True
    except Exception as e:
        print(f"Upload error: {e}")
        return False

@app.on_message(filters.command("id") & filters.private)
async def handle_id(client: Client, message: Message):
    global ALLOWED_CHAT_IDS
    try:
        if message.chat.id != OWNER_CHAT_ID:
            await message.reply_text(UNAUTHORIZED, parse_mode=ParseMode.HTML)
            return
        args = message.text.split()
        if len(args) != 2:
            await message.reply_text(INVALID_ID, parse_mode=ParseMode.HTML)
            return
        try:
            new_chat_id = int(args[1])
            if new_chat_id not in ALLOWED_CHAT_IDS:
                ALLOWED_CHAT_IDS.append(new_chat_id)
                save_allowed_chat_ids(ALLOWED_CHAT_IDS)
                await message.reply_text(ID_ADDED.format(new_chat_id), parse_mode=ParseMode.HTML)
            else:
                await message.reply_text(f"<b>⚠️ Chat ID {new_chat_id} already exists.</b>", parse_mode=ParseMode.HTML)
        except ValueError:
            await message.reply_text(INVALID_ID, parse_mode=ParseMode.HTML)
    except Exception as e:
        print(f"ID command error: {e}")
        await message.reply_text(ERROR_MSG.format(str(e)), parse_mode=ParseMode.HTML)

@app.on_message(filters.command("channel"))
async def handle_channel(client: Client, message: Message):
    try:
        if not channels:
            await message.reply_text(CHANNEL_NOT_FOUND, parse_mode=ParseMode.HTML)
            return
        channel_list = "\n".join([f"- {name}" for name in sorted(channels.keys())])
        await message.reply_text(CHANNEL_LIST.format(channel_list), parse_mode=ParseMode.HTML)
    except Exception as e:
        print(f"Channel command error: {e}")
        await message.reply_text(ERROR_MSG.format(str(e)), parse_mode=ParseMode.HTML)

@app.on_message(filters.command("use"))
async def handle_use(client: Client, message: Message):
    try:
        await message.reply_text(USE_MSG, parse_mode=ParseMode.HTML)
    except Exception as e:
        print(f"Use command error: {e}")
        await message.reply_text(ERROR_MSG.format(str(e)), parse_mode=ParseMode.HTML)

@app.on_message(filters.command("help"))
async def handle_help(client: Client, message: Message):
    try:
        await message.reply_text(HELP_MSG, parse_mode=ParseMode.HTML)
    except Exception as e:
        print(f"Help command error: {e}")
        await message.reply_text(ERROR_MSG.format(str(e)), parse_mode=ParseMode.HTML)

@app.on_message(filters.command("dl"))
async def handle_dl(client: Client, message: Message):
    global animation_index, is_downloading
    # Check authorization based on chat type
    if message.chat.type == ChatType.PRIVATE:
        if message.chat.id not in ALLOWED_CHAT_IDS:
            await message.reply_text(UNAUTHORIZED, parse_mode=ParseMode.HTML)
            return
    elif message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        if message.chat.id != SPECIAL_SUPERGROUP_ID:
            if not message.from_user:
                return
            username = message.from_user.username
            user_id = message.from_user.id
            is_admin = await is_user_admin(client, message.chat.id, user_id)
            if username != ALLOWED_USERNAME and not is_admin and user_id != OWNER_CHAT_ID:
                await message.reply_text(UNAUTHORIZED, parse_mode=ParseMode.HTML)
                return
    else:
        return

    async with download_lock:
        if is_downloading:
            await message.reply_text(BUSY_MSG, parse_mode=ParseMode.HTML)
            return
        is_downloading = True

    animation_index = 0
    try:
        args = message.text.split()
        if len(args) < 3:
            await message.reply_text(INVALID_FORMAT, parse_mode=ParseMode.HTML)
            return

        if len(args) == 3:
            channel_name, duration = args[1:3]
            m3u8_link = channels.get(channel_name.lower())
            if not m3u8_link:
                await message.reply_text(CHANNEL_NOT_FOUND, parse_mode=ParseMode.HTML)
                return
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{channel_name}_{timestamp}.mp4"
            audio_langs = []
        else:
            m3u8_link, duration, filename = args[1:4]
            audio_langs = args[4:]
            channel_name = "Custom"
            if not filename.endswith(".mp4"):
                filename += ".mp4"

        try:
            hh, mm, ss = map(int, duration.split(':'))
            total_seconds = hh * 3600 + mm * 60 + ss
            if total_seconds > 7200:  # 2 hours max
                await message.reply_text(INVALID_TIME, parse_mode=ParseMode.HTML)
                return
            if not (0 <= hh <= 2 and 0 <= mm < 60 and 0 <= ss < 60):
                await message.reply_text(INVALID_TIME, parse_mode=ParseMode.HTML)
                return
        except ValueError:
            await message.reply_text(INVALID_TIME, parse_mode=ParseMode.HTML)
            return

        print(f"Processing /dl for link: {m3u8_link}, duration: {duration}, filename: {filename}, audio: {audio_langs}")
        status_msg = await message.reply_text(
            START_MSG.format(channel_name, duration),
            parse_mode=ParseMode.HTML
        )

        success, audio_names, video_quality = await download_m3u8(m3u8_link, duration, filename, audio_langs, status_msg, channel_name)
        if not success:
            await status_msg.edit_text(
                ERROR_MSG.format("Download failed. Please check the link or audio streams."),
                parse_mode=ParseMode.HTML
            )
            return

        if os.path.exists(filename):
            await status_msg.edit_text("<b>📤 Upload started...</b> 🚀", parse_mode=ParseMode.HTML)
            success = await upload_with_progress(client, message.chat.id, filename, audio_names, status_msg, channel_name, duration, video_quality)
            if not success:
                await status_msg.edit_text(
                    ERROR_MSG.format("Upload failed. Check file or Telegram limits."),
                    parse_mode=ParseMode.HTML
                )
                return
            await status_msg.edit_text(UPLOAD_DONE, parse_mode=ParseMode.HTML)
            print(f"Upload successful, deleting {filename}")
            os.remove(filename)
        else:
            await status_msg.edit_text(
                ERROR_MSG.format("Download failed. File not found."),
                parse_mode=ParseMode.HTML
            )

    except Exception as e:
        print(f"Unexpected error: {e}")
        await message.reply_text(ERROR_MSG.format(str(e)), parse_mode=ParseMode.HTML)
    finally:
        is_downloading = False

if __name__ == "__main__":
    print("🚀 BOT STARTED - MADE BY P 🚀")
    app.run()