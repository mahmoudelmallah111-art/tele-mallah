import asyncio
import json
import os
import random
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import base64
import urllib.request

from telethon import Button, TelegramClient, events
from telethon.errors import (
    FloodWaitError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
    UserPrivacyRestrictedError,
    UserNotMutualContactError,
    UserChannelsTooMuchError,
)
from telethon.tl.functions.channels import InviteToChannelRequest
from telethon.tl.functions.contacts import AddContactRequest, GetContactsRequest
from telethon.tl.types import User

# =========================================================
# 1) خادم ويب وهمي لإبقاء الخدمة شغالة
# =========================================================
class DummyHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is live and running!")

    def log_message(self, format, *args):
        return

def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), DummyHTTPRequestHandler)
    server.serve_forever()

threading.Thread(target=run_dummy_server, daemon=True).start()

# =========================================================
# 2) إعدادات المكونات وحفظ البيانات على GitHub
# =========================================================
API_ID = 28513802
API_HASH = "fe0ef7e83635cdd89512e833c0ddcb28"
BOT_TOKEN = "8996749859:AAF6WPtVQrBrDw9N84Irf78kIF2GWYdeUYw"

# إعدادات GitHub لحفظ البيانات (اختياري: ضع البيانات لو أحببت الربط الحقيقي)
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "") # ضع Personal Access Token هنا
GITHUB_REPO = os.environ.get("GITHUB_REPO", "")   # مثال: "username/repo_name"

CONFIG_FILE = "bot_config.json"
USERS_FILE = "users_db.json"
HISTORY_FILE = "sent_history.txt"
ADMIN_USERNAME = "m7mallah"

default_config = {
    "target": "@playpoint_rewards",
    "message": (
        "✨ السلام عليكم ياخويا دي قناتي ان شاء الله\n"
        "🎯 هدفها اساعدكم بالنقاط وحل المشاكل وعمل مسابقات\n"
        "❤️ ياريت تدخل فيها وتدعمني وهكون قد الثقة:\n"
        "`@playpoint_rewards`"
    ),
    "old_phone": "",
    "new_phone": "",
    "custom_save_phone": "",
    "extract_source": "",
    "message_limit": 0,
}

extracted_cache = {}
active_tasks = {}
user_states = {}
auth_futures = {}

def sync_to_github(file_path):
    """رفع الملفات إلى GitHub للحفاظ على البيانات بدون فقدان"""
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{file_path}"
        with open(file_path, "rb") as f:
            content = base64.b64encode(f.read()).decode("utf-8")
        
        # جلب الـ sha إذا كان الملف موجوداً
        req = urllib.request.Request(url, headers={"Authorization": f"token {GITHUB_TOKEN}"})
        sha = None
        try:
            with urllib.request.urlopen(req) as response:
                sha = json.loads(response.read().decode())["sha"]
        except Exception:
            pass

        data = {
            "message": f"Auto-update {file_path}",
            "content": content
        }
        if sha:
            data["sha"] = sha

        req = urllib.request.Request(
            url, 
            data=json.dumps(data).encode(), 
            headers={"Authorization": f"token {GITHUB_TOKEN}", "Content-Type": "application/json"},
            method="PUT"
        )
        urllib.request.urlopen(req)
    except Exception as e:
        print(f"GitHub Sync Error: {e}")

def clean_target(raw_input):
    if not raw_input:
        return ""
    raw_input = raw_input.strip()
    if "t.me/" in raw_input:
        parts = raw_input.split("t.me/")[-1].strip("/").split("/")
        return parts[0]
    elif raw_input.startswith("@"):
        return raw_input[1:]
    return raw_input

def load_config():
    cfg = default_config.copy()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception:
            pass
    return cfg

def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=4)
        sync_to_github(CONFIG_FILE)
    except Exception as e:
        print(f"Error saving config: {e}")

def load_users():
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_users(users):
    try:
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(users, f, ensure_ascii=False, indent=4)
        sync_to_github(USERS_FILE)
    except Exception as e:
        print(f"Error saving users: {e}")

bot = TelegramClient("bot_session_main", API_ID, API_HASH)

# =========================================================
# 3) واجهات وأدوات المساعد
# =========================================================
async def safe_edit(msg, text, buttons=None):
    while True:
        try:
            await msg.edit(text, buttons=buttons, parse_mode="markdown")
            break
        except FloodWaitError as e:
            await asyncio.sleep(e.seconds + 2)
        except Exception:
            break

async def send_or_update_wizard(event, sender_id, text, buttons):
    state = user_states.get(sender_id, {})
    last_msg_id = state.get("last_bot_msg_id")
    chat_id = event.chat_id

    sent_msg = None
    if last_msg_id:
        try:
            sent_msg = await bot.edit_message(chat_id, last_msg_id, text, buttons=buttons, parse_mode="markdown")
        except Exception:
            pass

    if not sent_msg:
        try:
            if hasattr(event, "edit") and not isinstance(event, events.NewMessage.Event):
                try:
                    await event.edit(text, buttons=buttons, parse_mode="markdown")
                    sent_msg = event.message
                except Exception:
                    pass
            if not sent_msg:
                sent_msg = await bot.send_message(chat_id, text, buttons=buttons, parse_mode="markdown")
        except Exception:
            pass

    if sent_msg:
        if sender_id not in user_states:
            user_states[sender_id] = {}
        user_states[sender_id]["last_bot_msg_id"] = sent_msg.id

async def render_main_menu(event, is_edit=False, is_adm=False):
    sender = await event.get_sender()
    sender_id = sender.id if sender else None

    buttons = []
    if is_adm:
        users = load_users()
        pending_count = sum(1 for u in users.values() if u.get("status") == "pending")
        buttons.append([Button.inline(f"👥 إدارة طلبات المستخدمين ({pending_count} طلب جديد)", data="admin_requests_panel")])

    buttons.extend([
        [Button.inline("📥 1. معالج استخراج وحفظ الأعضاء", data="menu_extract_save")],
        [Button.inline("🚀 2. معالج الإرسال والإضافة المباشرة (ID / Username)", data="menu_actions_wizard")],
        [Button.inline("💾 3. حفظ جهات الاتصال في رقم محدد", data="manual_save_contacts")],
        [Button.inline("📊 عرض الإعدادات الحالية", data="show_settings")],
    ])

    text = "🌟 **لوحة تحكم البوت الاحترافية الذكية** 🌟\n\nاختر المعالج المطلوب للبدء:"
    if sender_id:
        await send_or_update_wizard(event, sender_id, text, buttons)

async def render_wizard_ext(event, sender_id, step):
    cfg = load_config()
    user_states.setdefault(sender_id, {})["wizard"] = "ext"
    user_states[sender_id]["step"] = step

    if step == 1:
        text = f"🧙‍♂️ **معالج الاستخراج (الخطوة 1 من 3)**\n\n🎯 **جروب الاستخراج:**\nأرسل اليوزر أو الرابط.\n\n🔗 الحالي: `{cfg.get('extract_source') or 'غير محدد'}`"
        buttons = [[Button.inline("التالي ➡️", data="wiz_ext_next_2")], [Button.inline("🔙 إلغاء", data="back_home")]]
    elif step == 2:
        text = f"🧙‍♂️ **معالج الاستخراج (الخطوة 2 من 3)**\n\n📊 **حد الرسائل:**\nأرسل العدد (`0` للكل).\n\n🔗 الحالي: `{cfg.get('message_limit', 0)}`"
        buttons = [[Button.inline("⬅️ السابق", data="wiz_ext_prev_1"), Button.inline("التالي ➡️", data="wiz_ext_next_3")], [Button.inline("🔙 إلغاء", data="back_home")]]
    elif step == 3:
        text = f"🧙‍♂️ **معالج الاستخراج (الخطوة 3 من 3)**\n\n📱 **رقم حساب الاستخراج:**\n\n🔗 الحالي: `{cfg.get('old_phone') or 'غير محدد'}`"
        buttons = [[Button.inline("⬅️ السابق", data="wiz_ext_prev_2"), Button.inline("🔍 مراجعة وتأكيد 🚀", data="wiz_ext_next_4")], [Button.inline("🔙 إلغاء", data="back_home")]]
    elif step == 4:
        text = f"📋 **تأكيد بيانات الاستخراج:**\n\n• المصدر: `{cfg.get('extract_source')}`\n• حد الرسائل: `{cfg.get('message_limit')}`\n• حساب الاستخراج: `{cfg.get('old_phone')}`"
        buttons = [[Button.inline("⬅️ تعديل", data="wiz_ext_prev_3")], [Button.inline("▶️ بدء الاستخراج الآن", data="ext_run_save")], [Button.inline("🔙 إلغاء", data="back_home")]]

    await send_or_update_wizard(event, sender_id, text, buttons)

# =========================================================
# 4) معالجة الأحداث والأزرار
# =========================================================
@bot.on(events.NewMessage(pattern="/start"))
async def start_cmd(event):
    sender = await event.get_sender()
    if not sender: return
    sender_id = str(sender.id)
    is_adm = bool(sender.username and sender.username.lower() == ADMIN_USERNAME.lower())

    try: await event.delete()
    except Exception: pass

    users = load_users()
    if is_adm or (sender_id in users and users[sender_id].get("status") == "approved"):
        await render_main_menu(event, is_adm=is_adm)
    elif sender_id not in users:
        users[sender_id] = {"name": sender.first_name or "مستخدم", "username": sender.username or "لا يوجد", "status": "pending"}
        save_users(users)
        await event.respond("⏳ **تم إرسال طلبك للمالك بانتظار الموافقة.**")

@bot.on(events.CallbackQuery)
async def cb_handler(event):
    try: await event.answer()
    except Exception: pass

    sender = await event.get_sender()
    if not sender: return
    sender_int_id = sender.id
    is_adm = bool(sender.username and sender.username.lower() == ADMIN_USERNAME.lower())

    data = event.data.decode("utf-8")
    cfg = load_config()

    if data == "back_home":
        user_states.get(sender_int_id, {}).pop("wizard", None)
        await render_main_menu(event, is_adm=is_adm)
    elif data == "menu_extract_save":
        await render_wizard_ext(event, sender_int_id, 1)
    elif data == "wiz_ext_next_2": await render_wizard_ext(event, sender_int_id, 2)
    elif data == "wiz_ext_next_3": await render_wizard_ext(event, sender_int_id, 3)
    elif data == "wiz_ext_next_4": await render_wizard_ext(event, sender_int_id, 4)
    elif data == "wiz_ext_prev_1": await render_wizard_ext(event, sender_int_id, 1)
    elif data == "wiz_ext_prev_2": await render_wizard_ext(event, sender_int_id, 2)
    elif data == "wiz_ext_prev_3": await render_wizard_ext(event, sender_int_id, 3)

    elif data == "ext_run_save":
        user_states.pop(sender_int_id, None)
        progress_msg = await event.respond("⏳ جاري استخراج الأعضاء...")
        asyncio.create_task(run_extraction_task(progress_msg, cfg))

    elif data == "manual_save_contacts":
        user_states[sender_int_id] = {"wizard": "manual_phone_input"}
        await event.respond("📱 **أدخل رقم الهاتف المراد حفظ جهات الاتصال فيه الآن (مع رمز الدولة):**\nمثال: `+201012345678`")

    elif data == "show_settings":
        await event.respond(f"📊 **الإعدادات الحالية:**\n\n🎯 الوجهة: `{cfg['target']}`\n🔍 جروب الاستخراج: `{cfg.get('extract_source')}`\n📱 رقم حفظ الحسابات: `{cfg.get('custom_save_phone') or 'غير محدد'}`")

@bot.on(events.NewMessage)
async def message_handler(event):
    sender = await event.get_sender()
    if not sender: return
    sender_id = sender.id

    if sender_id in auth_futures and not auth_futures[sender_id].done():
        auth_futures[sender_id].set_result(event.raw_text.strip())
        try: await event.delete()
        except Exception: pass
        return

    state_info = user_states.get(sender_id)
    if not state_info: return
    cfg = load_config()
    text = event.raw_text.strip()

    try: await event.delete()
    except Exception: pass

    if state_info.get("wizard") == "manual_phone_input":
        user_states.pop(sender_id, None)
        cfg["custom_save_phone"] = text
        save_config(cfg)
        
        users_list = extracted_cache.get(event.chat_id)
        if not users_list:
            await event.respond("⚠️ يرجى إجراء عملية الاستخراج أولاً للحصول على قائمة الاعضاء.")
            return

        progress_msg = await event.respond(f"🔄 جاري حفظ جهات الاتصال في الحساب المحدد (`{text}`)...")
        asyncio.create_task(save_contacts_to_custom_phone(progress_msg, text, users_list))

    elif state_info.get("wizard") == "ext":
        step = state_info["step"]
        if step == 1:
            cfg["extract_source"] = text
            save_config(cfg)
            await render_wizard_ext(event, sender_id, 2)
        elif step == 2 and text.isdigit():
            cfg["message_limit"] = int(text)
            save_config(cfg)
            await render_wizard_ext(event, sender_id, 3)
        elif step == 3:
            cfg["old_phone"] = text
            save_config(cfg)
            await render_wizard_ext(event, sender_id, 4)

# =========================================================
# 5) المهام الأساسية
# =========================================================
async def interactive_login(client, phone, account_label, progress_msg):
    await client.connect()
    if not await client.is_user_authorized():
        chat_id = progress_msg.chat_id
        sent = await client.send_code_request(phone)
        await progress_msg.edit(f"📱 **أدخل كود التفعيل للحساب (`{phone}`):**")
        
        future = asyncio.get_running_loop().create_future()
        auth_futures[chat_id] = future
        code = await future

        try:
            await client.sign_in(phone, code, phone_code_hash=sent.phone_code_hash)
        except Exception as e:
            if "sessionpasswordneeded" in str(e).lower() or isinstance(e, SessionPasswordNeededError):
                await progress_msg.edit(f"🔐 **أدخل كلمة مرور التحقق بخطوتين للحساب (`{phone}`):**")
                future = asyncio.get_running_loop().create_future()
                auth_futures[chat_id] = future
                password = await future
                await client.sign_in(password=password)

async def run_extraction_task(progress_msg, cfg):
    old_phone = cfg["old_phone"].strip()
    extract_source = clean_target(cfg.get("extract_source"))
    session_old = "session_old_" + old_phone.replace("+", "")
    client_old = TelegramClient(session_old, API_ID, API_HASH)
    users_map = {}

    try:
        await interactive_login(client_old, old_phone, "الاستخراج", progress_msg)
        await safe_edit(progress_msg, "🔄 جاري جلب الأعضاء...")

        async for user in client_old.iter_participants(extract_source):
            if isinstance(user, User) and not getattr(user, "bot", False):
                users_map[user.id] = user

        await client_old.disconnect()
    except Exception as e:
        await safe_edit(progress_msg, f"❌ حدث خطأ أثناء الاستخراج: {e}")
        return

    users_list = list(users_map.values())
    extracted_cache[progress_msg.chat_id] = users_list

    # ترتيب الأزرار فور انتهاء الاستخراج مباشرة
    buttons = [
        [Button.inline("💾 حفظ جهات الاتصال في رقم محدد", data="manual_save_contacts")],
        [Button.inline("🚀 الانتقال للإضافة المباشرة", data="menu_actions_wizard")],
        [Button.inline("🔙 القائمة الرئيسية", data="back_home")]
    ]

    await safe_edit(
        progress_msg,
        f"✅ **تم استخراج ({len(users_list)}) عضو بنجاح!**\n\nاختر الخطوة التالية الآن:",
        buttons=buttons
    )

async def save_contacts_to_custom_phone(progress_msg, phone_num, users_list):
    session_name = "session_custom_" + phone_num.replace("+", "")
    try:
        client = TelegramClient(session_name, API_ID, API_HASH)
        await interactive_login(client, phone_num, "حفظ الأرقام", progress_msg)

        added, privacy_blocked = 0, 0
        for idx, u in enumerate(users_list, 1):
            phone_val = getattr(u, "phone", None) or ""
            try:
                await client(AddContactRequest(
                    id=u.id,
                    first_name=u.first_name or "User",
                    last_name=u.last_name or "",
                    phone=phone_val
                ))
                added += 1
            except Exception:
                privacy_blocked += 1

            if idx % 15 == 0 or idx == len(users_list):
                await safe_edit(progress_msg, f"📇 **جاري الحفظ بالحساب (`{phone_num}`)...**\n\n• النجاح: `{added}`\n• المحظورين/الخصوصية: `{privacy_blocked}`\n• التقدم: `({idx}/{len(users_list)})`")
            await asyncio.sleep(0.4)

        await client.disconnect()
        await safe_edit(progress_msg, f"✅ **اكتمل حفظ جهات الاتصال بنجاح!**\n\n• تم حفظ: `{added}`\n• متعذر بسبب الخصوصية: `{privacy_blocked}`", buttons=[[Button.inline("🔙 القائمة الرئيسية", data="back_home")]])
    except Exception as e:
        await safe_edit(progress_msg, f"❌ خطأ: `{str(e)}`", buttons=[[Button.inline("🔙 القائمة الرئيسية", data="back_home")]])

async def main_loop():
    while True:
        try:
            if not bot.is_connected(): await bot.connect()
            if not await bot.is_user_authorized(): await bot.start(bot_token=BOT_TOKEN)
            await bot.run_until_disconnected()
        except Exception:
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main_loop())
