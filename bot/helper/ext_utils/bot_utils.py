from re import findall as re_findall
from threading import Thread, Event
from time import time
from math import ceil
from html import escape
from psutil import virtual_memory, cpu_percent, disk_usage, net_io_counters
from requests import head as rhead
from urllib.request import urlopen
from telegram import InlineKeyboardMarkup
from telegram.message import Message
from telegram.ext import CallbackQueryHandler

from bot import download_dict, download_dict_lock, STATUS_LIMIT, botStartTime, DOWNLOAD_DIR, WEB_PINCODE, BASE_URL, status_reply_dict, status_reply_dict_lock, dispatcher, bot, OWNER_ID, LOGGER
from bot.helper.telegram_helper.bot_commands import BotCommands
from bot.helper.telegram_helper.button_build import ButtonMaker

MAGNET_REGEX = r"magnet:\?xt=urn:btih:[a-zA-Z0-9]*"

URL_REGEX = r"(?:(?:https?|ftp):\/\/)?[\w/\-?=%.]+\.[\w/\-?=%.]+"

COUNT = 0
PAGE_NO = 1


class MirrorStatus:
    STATUS_UPLOADING = "𝗨𝗽𝗹𝗼𝗮𝗱𝗶𝗻𝗴...📤"
    STATUS_DOWNLOADING = "𝗗𝗼𝘄𝗻𝗹𝗼𝗮𝗱𝗶𝗻𝗴...📥"
    STATUS_CLONING = "𝗖𝗹𝗼𝗻𝗶𝗻𝗴...♻️"
    STATUS_WAITING = "𝗤𝘂𝗲𝘂𝗲𝗱...💤"
    STATUS_PAUSE = "𝗣𝗮𝘂𝘀𝗲𝗱...⛔️"
    STATUS_ARCHIVING = "𝗔𝗿𝗰𝗵𝗶𝘃𝗶𝗻𝗴...🔐"
    STATUS_EXTRACTING = "𝗘𝘅𝘁𝗿𝗮𝗰𝘁𝗶𝗻𝗴...📂"
    STATUS_SPLITTING = "𝗦𝗽𝗹𝗶𝘁𝘁𝗶𝗻𝗴...✂️"
    STATUS_CHECKING = "𝗖𝗵𝗲𝗰𝗸𝗶𝗻𝗴𝗨𝗽...📝"
    STATUS_SEEDING = "𝗦𝗲𝗲𝗱𝗶𝗻𝗴...🌧"

class EngineStatus:
    STATUS_ARIA = "Aria2c📶"
    STATUS_GDRIVE = "Google API♻️"
    STATUS_MEGA = "Mega API⭕️"
    STATUS_QB = "qBittorrent🦠"
    STATUS_TG = "Pyrogram💥"
    STATUS_YT = "Yt-dlp🌟"
    STATUS_EXT = "extract | pextract⚔️"
    STATUS_SPLIT = "FFmpeg✂️"
    STATUS_ZIP = "7z🛠"

PROGRESS_MAX_SIZE = 100 // 10 
PROGRESS_INCOMPLETE = ['◔', '◔', '◑', '◑', '◑', '◕', '◕']

SIZE_UNITS = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']


class setInterval:
    def __init__(self, interval, action):
        self.interval = interval
        self.action = action
        self.stopEvent = Event()
        thread = Thread(target=self.__setInterval)
        thread.start()

    def __setInterval(self):
        nextTime = time() + self.interval
        while not self.stopEvent.wait(nextTime - time()):
            nextTime += self.interval
            self.action()

    def cancel(self):
        self.stopEvent.set()

def get_readable_file_size(size_in_bytes) -> str:
    if size_in_bytes is None:
        return '0B'
    index = 0
    while size_in_bytes >= 1024:
        size_in_bytes /= 1024
        index += 1
    try:
        return f'{round(size_in_bytes, 2)}{SIZE_UNITS[index]}'
    except IndexError:
        return 'File too large'

def getDownloadByGid(gid):
    with download_dict_lock:
        for dl in list(download_dict.values()):
            if dl.gid() == gid:
                return dl
    return None

def getAllDownload(req_status: str):
    with download_dict_lock:
        for dl in list(download_dict.values()):
            status = dl.status()
            if req_status in ['all', status]:
                return dl
    return None

def bt_selection_buttons(id_: str):
    if len(id_) > 20:
        gid = id_[:12]
    else:
        gid = id_

    pincode = ""
    for n in id_:
        if n.isdigit():
            pincode += str(n)
        if len(pincode) == 4:
            break

    buttons = ButtonMaker()
    if WEB_PINCODE:
        buttons.buildbutton("Select Files", f"{BASE_URL}/app/files/{id_}")
        buttons.sbutton("Pincode", f"btsel pin {gid} {pincode}")
    else:
        buttons.buildbutton("Select Files", f"{BASE_URL}/app/files/{id_}?pin_code={pincode}")
    buttons.sbutton("Done Selecting", f"btsel done {gid} {id_}")
    return InlineKeyboardMarkup(buttons.build_menu(2))

def get_progress_bar_string(status):
    completed = status.processed_bytes() / 8
    total = status.size_raw() / 8
    p = 0 if total == 0 else round(completed * 100 / total)
    p = min(max(p, 0), 100)
    cFull = p // 8
    cPart = p % 8 - 1
    p_str = '●' * cFull
    if cPart >= 0:
        p_str += PROGRESS_INCOMPLETE[cPart]
    p_str += '○' * (PROGRESS_MAX_SIZE - cFull)
    p_str = f"「{p_str}」"
    return p_str

def progress_bar(percentage):
    comp = '▓'
    ncomp = '░'
    pr = ""
    if isinstance(percentage, str):
        return "NaN"
    try:
        percentage=int(percentage)
    except:
        percentage = 0
    for i in range(1,11):
        if i <= int(percentage/10):
            pr += comp
        else:
            pr += ncomp
    return pr

def editMessage(text: str, message: Message, reply_markup=None):
    try:
        bot.editMessageText(text=text, message_id=message.message_id,
                              chat_id=message.chat.id,reply_markup=reply_markup,
                              parse_mode='HTMl', disable_web_page_preview=True)
    except RetryAfter as r:
        LOGGER.warning(str(r))
        sleep(r.retry_after * 1.5)
        return editMessage(text, message, reply_markup)
    except Exception as e:
        LOGGER.error(str(e))
        return str(e)

def update_all_messages():
    msg, buttons = get_readable_message()
    with status_reply_dict_lock:
        for chat_id in list(status_reply_dict.keys()):
            if status_reply_dict[chat_id] and msg != status_reply_dict[chat_id].text:
                if buttons == "":
                    editMessage(msg, status_reply_dict[chat_id])
                else:
                    editMessage(msg, status_reply_dict[chat_id], buttons)
                status_reply_dict[chat_id].text = msg

def get_readable_message():
    with download_dict_lock:
        dlspeed_bytes = 0
        uldl_bytes = 0
        START = 0
        num_active = 0
        num_seeding = 0
        num_upload = 0
        for stats in list(download_dict.values()):
            if stats.status() == MirrorStatus.STATUS_DOWNLOADING:
               num_active += 1
            if stats.status() == MirrorStatus.STATUS_UPLOADING:
               num_upload += 1
            if stats.status() == MirrorStatus.STATUS_SEEDING:
               num_seeding += 1
        if STATUS_LIMIT is not None:
            tasks = len(download_dict)
            global pages
            pages = ceil(tasks/STATUS_LIMIT)
            if PAGE_NO > pages and pages != 0:
                globals()['COUNT'] -= STATUS_LIMIT
                globals()['PAGE_NO'] -= 1
        msg = f"<b>| 𝗗𝗼𝘄𝗻𝗹𝗼𝗮𝗱𝗶𝗻𝗴: {num_active} || 𝗨𝗽𝗹𝗼𝗮𝗱𝗶𝗻𝗴: {num_upload} || 𝗦𝗲𝗲𝗱𝗶𝗻𝗴: {num_seeding} |</b>\n\n<b>▬▬▬ @BaashaXclouD ▬▬▬</b>\n"
        for index, download in enumerate(list(download_dict.values())[COUNT:], start=1):
            msg += f"\n𝗙𝗶𝗹𝗲𝗻𝗮𝗺𝗲: <code>{download.name()}</code>"
            msg += f"\n𝗦𝘁𝗮𝘁𝘂𝘀: <i>{download.status()}</i>"
            msg += f"\n𝗘𝗻𝗴𝗶𝗻𝗲: {download.eng()}"
            if download.status() not in [MirrorStatus.STATUS_SPLITTING, MirrorStatus.STATUS_SEEDING]:
                msg += f"\n{get_progress_bar_string(download)} {download.progress()}"
                if download.status() in [MirrorStatus.STATUS_DOWNLOADING,
                                         MirrorStatus.STATUS_WAITING,
                                         MirrorStatus.STATUS_PAUSED]:
                    msg += f"\n𝗗𝗼𝘄𝗻𝗹𝗼𝗮𝗱𝗲𝗱: {get_readable_file_size(download.processed_bytes())} of {download.size()}"
                elif download.status() == MirrorStatus.STATUS_UPLOADING:
                    msg += f"\n𝗨𝗽𝗹𝗼𝗮𝗱𝗲𝗱: {get_readable_file_size(download.processed_bytes())} of {download.size()}"
                elif download.status() == MirrorStatus.STATUS_CLONING:
                    msg += f"\n𝗖𝗹𝗼𝗻𝗲𝗱: {get_readable_file_size(download.processed_bytes())} of {download.size()}"
                elif download.status() == MirrorStatus.STATUS_ARCHIVING:
                    msg += f"\n<b>Archived:</b> {get_readable_file_size(download.processed_bytes())} of {download.size()}"
                elif download.status() == MirrorStatus.STATUS_EXTRACTING:
                    msg += f"\n<b>Extracted:</b> {get_readable_file_size(download.processed_bytes())} of {download.size()}"
                msg += f"\n𝗦𝗽𝗲𝗲𝗱: {download.speed()} | 𝗘𝗧𝗔: {download.eta()}"
                try:
                    msg += f"\n𝗦𝗲𝗲𝗱𝗲𝗿𝘀: {download.aria_download().num_seeders}" \
                           f" | 𝗣𝗲𝗲𝗿𝘀: {download.aria_download().connections}"
                except:
                    pass
                try:
                    msg += f"\n𝗦𝗲𝗲𝗱𝗲𝗿𝘀: {download.torrent_info().num_seeds}" \
                           f" | 𝗟𝗲𝗲𝗰𝗵𝗲𝗿𝘀: {download.torrent_info().num_leechs}"
                except:
                    pass
                if download.message.chat.type != 'private':
                    try:
                        chatid = str(download.message.chat.id)[4:]
                        msg += f'\n𝗦𝗼𝘂𝗿𝗰𝗲 𝗟𝗶𝗻𝗸: <a href="https://t.me/c/{chatid}/{download.message.message_id}">Click Here</a>'
                    except:
                        pass
                msg += f'\n<b>𝗨𝘀𝗲𝗿:</b> ️<code>{download.message.from_user.first_name}</code>️(<code>/warn {download.message.from_user.id}</code>)'
            elif download.status() == MirrorStatus.STATUS_SEEDING:
                msg += f"\n𝗦𝗶𝘇𝗲: {download.size()}"
                msg += f"\n𝗦𝗽𝗲𝗲𝗱: {get_readable_file_size(download.torrent_info().upspeed)}/s"
                msg += f" | 𝗨𝗽𝗹𝗼𝗮𝗱𝗲𝗱: {get_readable_file_size(download.torrent_info().uploaded)}"
                msg += f"\n𝗥𝗮𝘁𝗶𝗼: {round(download.torrent_info().ratio, 3)}"
                msg += f" | 𝗧𝗶𝗺𝗲: {get_readable_time(download.torrent_info().seeding_time)}"
            else:
                msg += f"\n𝗦𝗶𝘇𝗲: {download.size()}"
            msg += f"\n𝗖𝗮𝗻𝗰𝗲𝗹: <code>/{BotCommands.CancelMirror} {download.gid()}</code>\n________________________________"
            msg += "\n"
            if STATUS_LIMIT is not None and index == STATUS_LIMIT:
                break
        if len(msg) == 0:
            return None, None
        currentTime = get_readable_time(time() - botStartTime)
        dlspeed_bytes = 0
        upspeed_bytes = 0
        for download in list(download_dict.values()):
            spd = download.speed()
            if download.status() == MirrorStatus.STATUS_DOWNLOADING:
                if 'K' in spd:
                    dlspeed_bytes += float(spd.split('K')[0]) * 1024
                elif 'M' in spd:
                    dlspeed_bytes += float(spd.split('M')[0]) * 1048576
            elif download.status() == MirrorStatus.STATUS_UPLOADING:
                if 'KB/s' in spd:
                    upspeed_bytes += float(spd.split('K')[0]) * 1024
                elif 'MB/s' in spd:
                    upspeed_bytes += float(spd.split('M')[0]) * 1048576
        msg += f"\n📖 𝗣𝗮𝗴𝗲𝘀: {PAGE_NO}/{pages} | 📝 𝗧𝗮𝘀𝗸𝘀: {tasks}"
        msg += f"\n𝗕𝗢𝗧 𝗨𝗣𝗧𝗜𝗠𝗘⏰: <code>{currentTime}</code>"
        msg += f"\n𝗗𝗹: {get_readable_file_size(dlspeed_bytes)}/s🔻 | 𝗨𝗹: {get_readable_file_size(upspeed_bytes)}/s🔺"
        buttons = ButtonMaker()
        buttons.sbutton("🔄", str(ONE))
        buttons.sbutton("❌", str(TWO))
        buttons.sbutton("📈", str(THREE))
        sbutton = InlineKeyboardMarkup(buttons.build_menu(3))
        if STATUS_LIMIT is not None and tasks > STATUS_LIMIT:
            buttons = ButtonMaker()
            buttons.sbutton("⬅️", "status pre")
            buttons.sbutton("❌", str(TWO))
            buttons.sbutton("➡️", "status nex")
            buttons.sbutton("🔄", str(ONE))
            buttons.sbutton("📈", str(THREE))
            button = InlineKeyboardMarkup(buttons.build_menu(3))
            return msg, button
        return msg, ""

def stats(update, context):
    query = update.callback_query
    stats = bot_sys_stats()
    query.answer(text=stats, show_alert=True)

def bot_sys_stats():
    currentTime = get_readable_time(time() - botStartTime)
    cpu = cpu_percent(interval=0.5)
    memory = virtual_memory()
    mem = memory.percent
    total, used, free, disk= disk_usage('/')
    total = get_readable_file_size(total)
    used = get_readable_file_size(used)
    free = get_readable_file_size(free)
    recv = get_readable_file_size(net_io_counters().bytes_recv)
    sent = get_readable_file_size(net_io_counters().bytes_sent)
    stats = f"""
BOT UPTIME⏰: {currentTime}

CPU: {progress_bar(cpu)} {cpu}%
RAM: {progress_bar(mem)} {mem}%
DISK: {progress_bar(disk)} {disk}%

TOTAL: {total}

USED: {used} || FREE: {free}
SENT: {sent} || RECV: {recv}

#BaashaXclouD
"""
    return stats

def turn(data):
    try:
        with download_dict_lock:
            global COUNT, PAGE_NO
            if data[1] == "nex":
                if PAGE_NO == pages:
                    COUNT = 0
                    PAGE_NO = 1
                else:
                    COUNT += STATUS_LIMIT
                    PAGE_NO += 1
            elif data[1] == "pre":
                if PAGE_NO == 1:
                    COUNT = STATUS_LIMIT * (pages - 1)
                    PAGE_NO = pages
                else:
                    COUNT -= STATUS_LIMIT
                    PAGE_NO -= 1
        return True
    except:
        return False

def get_readable_time(seconds: int) -> str:
    result = ''
    (days, remainder) = divmod(seconds, 86400)
    days = int(days)
    if days != 0:
        result += f'{days}d'
    (hours, remainder) = divmod(remainder, 3600)
    hours = int(hours)
    if hours != 0:
        result += f'{hours}h'
    (minutes, seconds) = divmod(remainder, 60)
    minutes = int(minutes)
    if minutes != 0:
        result += f'{minutes}m'
    seconds = int(seconds)
    result += f'{seconds}s'
    return result

ONE, TWO, THREE = range(3)
                
def refresh(update, context):
    chat_id  = update.effective_chat.id
    query = update.callback_query
    user_id = update.callback_query.from_user.id
    first = update.callback_query.from_user.first_name
    query.edit_message_text(text=f"{first} Refreshing...👻")
    sleep(2)
    update_all_messages()
    query.answer(text="Refreshed", show_alert=False)
    
def close(update, context):  
    chat_id  = update.effective_chat.id
    user_id = update.callback_query.from_user.id
    bot = context.bot
    query = update.callback_query
    admins = bot.get_chat_member(chat_id, user_id).status in ['creator', 'administrator'] or user_id in [OWNER_ID] 
    if admins: 
        query.answer()  
        query.message.delete() 
    else:  
        query.answer(text="Nice Try, Get Lost🥱.\n\nOnly Admins can use this.", show_alert=True)
        
def get_readable_time(seconds: int) -> str:
    result = ''
    (days, remainder) = divmod(seconds, 86400)
    days = int(days)
    if days != 0:
        result += f'{days}d'
    (hours, remainder) = divmod(remainder, 3600)
    hours = int(hours)
    if hours != 0:
        result += f'{hours}h'
    (minutes, seconds) = divmod(remainder, 60)
    minutes = int(minutes)
    if minutes != 0:
        result += f'{minutes}m'
    seconds = int(seconds)
    result += f'{seconds}s'
    return result

def is_url(url: str):
    url = re_findall(URL_REGEX, url)
    return bool(url)

def is_gdrive_link(url: str):
    return "drive.google.com" in url

def is_mega_link(url: str):
    return "mega.nz" in url or "mega.co.nz" in url

def get_mega_link_type(url: str):
    if "folder" in url:
        return "folder"
    elif "file" in url:
        return "file"
    elif "/#F!" in url:
        return "folder"
    return "file"

def is_magnet(url: str):
    magnet = re_findall(MAGNET_REGEX, url)
    return bool(magnet)

def new_thread(fn):
    """To use as decorator to make a function call threaded.
    Needs import
    from threading import Thread"""

    def wrapper(*args, **kwargs):
        thread = Thread(target=fn, args=args, kwargs=kwargs)
        thread.start()
        return thread

    return wrapper

def get_content_type(link: str) -> str:
    try:
        res = rhead(link, allow_redirects=True, timeout=5, headers = {'user-agent': 'Wget/1.12'})
        content_type = res.headers.get('content-type')
    except:
        try:
            res = urlopen(link, timeout=5)
            info = res.info()
            content_type = info.get_content_type()
        except:
            content_type = None
    return content_type

dispatcher.add_handler(CallbackQueryHandler(refresh, pattern='^' + str(ONE) + '$'))
dispatcher.add_handler(CallbackQueryHandler(close, pattern='^' + str(TWO) + '$'))
dispatcher.add_handler(CallbackQueryHandler(stats, pattern='^' + str(THREE) + '$'))
