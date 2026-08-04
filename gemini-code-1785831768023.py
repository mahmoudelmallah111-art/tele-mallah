import asyncio
import json
import os
import random
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

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
from telethon.tl.types import Channel, User

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
# 2) إعدادات المكونات والمتغيرات
# =========================================================
API_ID = 28513802
API_HASH = "fe0ef7e83635cdd89512e833c0ddcb28"
BOT_TOKEN = "8996749859:AAF6WPtVQrBrDw9N84Irf78kIF2GWYdeUYw"

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
    except Exception as e:
        print(f"Error saving users: {e}")

bot = TelegramClient("bot_session_main", API_ID, API_HASH)

async def show_loading(msg, text):
    for i in range(3):
        dots = "." * ((i % 3) + 1)
        try:
            await msg.edit(f"🔄 {text}{dots}")
        except Exception:
            pass
        await asyncio.sleep(0.3)

async def send_or_update_wizard(event, sender_id, text, buttons):
    state = user_states.get(sender_id, {})
    last_msg_id = state.get("last_bot_msg_id")
    chat_id = event.chat_id

    sent_msg = None
    if last_msg_id:
        try:
            sent_msg = await bot.edit_message(
                chat_id, last_msg_id, text, buttons=buttons, parse_mode="markdown"
            )
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
                sent_msg = await bot.send_message(
                    chat_id, text, buttons=buttons, parse_mode="markdown"
                )
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
        buttons.append([
            Button.inline(
                f"👥 إدارة طلبات المستخدمين ({pending_count} طلب جديد)",
                data="admin_requests_panel",
            )
        ])

    buttons.extend([
        [Button.inline("📥 1. معالج استخراج وحفظ الأعضاء", data="menu_extract_save")],
        [Button.inline("🚀 2. معالج الإرسال والإضافة المباشرة (ID / Username)", data="menu_actions_wizard")],
        [Button.inline("📇 3. حفظ جهات الاتصال في رقم محدد يدويًا", data="manual_save_contacts")],
        [Button.inline("📊 عرض الإعدادات الحالية", data="show_settings")],
    ])

    text = "🌟 **لوحة تحكم البوت الاحترافية الذكية** 🌟\n\nاختر المعالج المطلوب للبدء:"

    if sender_id:
        await send_or_update_wizard(event, sender_id, text, buttons)
    else:
        if is_edit:
            try:
                await event.edit(text, buttons=buttons, parse_mode="markdown")
            except Exception:
                await event.respond(text, buttons=buttons, parse_mode="markdown")
        else:
            await event.respond(text, buttons=buttons, parse_mode="markdown")

async def render_wizard_ext(event, sender_id, step):
    cfg = load_config()
    if sender_id not in user_states:
        user_states[sender_id] = {}
    user_states[sender_id].update({"wizard": "ext", "step": step})

    if step == 1:
        text = (
            "🧙‍♂️ **معالج الاستخراج (الخطوة 1 من 3)**\n\n🎯 **تحديد جروب الاستخراج:**\nأرسل"
            " يوزر أو رابط الجروب المراد الاستخراج منه.\n\n🔗 القيمة"
            f" الحالية: `{cfg.get('extract_source') or 'غير محدد'}`"
        )
        buttons = [
            [Button.inline("التالي ➡️", data="wiz_ext_next_2")],
            [Button.inline("🔙 إلغاء والقائمة الرئيسية", data="back_home")],
        ]
    elif step == 2:
        text = (
            "🧙‍♂️ **معالج الاستخراج (الخطوة 2 من 3)**\n\n📊 **حد الرسائل:**\nأرسل عدد"
            " الرسائل المراد فحصها (اكتب `0` لجلب الأعضاء مباشرة بلا حدود)."
            f"\n\n🔗 القيمة الحالية: `{cfg.get('message_limit', 0)}`"
        )
        buttons = [
            [
                Button.inline("⬅️ السابق", data="wiz_ext_prev_1"),
                Button.inline("التالي ➡️", data="wiz_ext_next_3"),
            ],
            [Button.inline("🔙 إلغاء والقائمة الرئيسية", data="back_home")],
        ]
    elif step == 3:
        text = (
            "🧙‍♂️ **معالج الاستخراج (الخطوة 3 من 3)**\n\n📱 **حساب السحب الاستخراج:**\nأرسل"
            " رقم هاتف الحساب المستخدم في عملية جلب الأعضاء.\n\n🔗 القيمة الحالية:"
            f" `{cfg.get('old_phone') or 'غير محدد'}`"
        )
        buttons = [
            [
                Button.inline("⬅️ السابق", data="wiz_ext_prev_2"),
                Button.inline("🔍 مراجعة وتأكيد التنفيذ 🚀", data="wiz_ext_next_4"),
            ],
            [Button.inline("🔙 إلغاء والقائمة الرئيسية", data="back_home")],
        ]
    elif step == 4:
        text = (
            "📋 **مراجعة بيانات الاستخراج النهائية:**\n\n• جروب الاستخراج:"
            f" `{cfg.get('extract_source', 'غير محدد')}`\n• حد الرسائل:"
            f" `{cfg.get('message_limit', 0)}`\n• حساب الاستخراج:"
            f" `{cfg.get('old_phone', 'غير محدد')}`\n\nهل أنت متأكد من البدء؟"
        )
        buttons = [
            [Button.inline("⬅️ تعديل البيانات", data="wiz_ext_prev_3")],
            [Button.inline("▶️ تأكيد وتنفيذ الاستخراج الآن", data="ext_run_save")],
            [Button.inline("🔙 إلغاء والقائمة الرئيسية", data="back_home")],
        ]

    await send_or_update_wizard(event, sender_id, text, buttons)

async def render_wizard_act(event, sender_id, step):
    cfg = load_config()
    if sender_id not in user_states:
        user_states[sender_id] = {}
    user_states[sender_id].update({"wizard": "act", "step": step})

    if step == 1:
        text = (
            "🚀 **معالج الإرسال والإضافة المباشرة (الخطوة 1 من 4)**\n\n📱 **حساب التنفيذ/الإدارة:**\nأرسل"
            " رقم هاتف الحساب الذي سيقوم بالإضافة بـ (ID/Username).\n\n🔗 القيمة"
            f" الحالية: `{cfg.get('new_phone') or 'غير محدد'}`"
        )
        buttons = [
            [Button.inline("التالي ➡️", data="wiz_act_next_2")],
            [Button.inline("🔙 إلغاء والقائمة الرئيسية", data="back_home")],
        ]
    elif step == 2:
        text = (
            "🚀 **معالج الإرسال والإضافة المباشرة (الخطوة 2 من 4)**\n\n🎯 **الوجهة المستهدفة:**\nأرسل"
            " يوزر أو رابط القناة/الجروب المراد إضافة الأعضاء إليه.\n\n🔗"
            f" القيمة الحالية: `{cfg.get('target', 'غير محدد')}`"
        )
        buttons = [
            [
                Button.inline("⬅️ السابق", data="wiz_act_prev_1"),
                Button.inline("التالي ➡️", data="wiz_act_next_3"),
            ],
            [Button.inline("🔙 إلغاء والقائمة الرئيسية", data="back_home")],
        ]
    elif step == 3:
        text = (
            "🚀 **معالج الإرسال والإضافة المباشرة (الخطوة 3 من 4)**\n\n✏️ **رسالة الدعوة:**\nأرسل"
            " نص الرسالة التي ستصل للخاص إذا تعذرت إضافة العضو بسبب الخصوصية.\n\n🔗 النص"
            f" الحالي:\n`{cfg.get('message', 'غير محدد')}`"
        )
        buttons = [
            [
                Button.inline("⬅️ السابق", data="wiz_act_prev_2"),
                Button.inline("🔍 مراجعة وتأكيد التنفيذ 🚀", data="wiz_act_next_4"),
            ],
            [Button.inline("🔙 إلغاء والقائمة الرئيسية", data="back_home")],
        ]
    elif step == 4:
        text = (
            "📋 **مراجعة البيانات النهائية:**\n\n• حساب التنفيذ والإضافة:"
            f" `{cfg.get('new_phone', 'غير محدد')}`\n• الجروب/القناة المستهدفة:"
            f" `{cfg.get('target', 'غير محدد')}`\n• نص رسالة الخاص عند الخصوصية:\n`{cfg.get('message', 'غير محدد')}`\n\nهل أنت متأكد من البدء؟"
        )
        buttons = [
            [Button.inline("⬅️ تعديل البيانات", data="wiz_act_prev_3")],
            [Button.inline("▶️ تأكيد وبدء التنفيذ الشامل", data="add_run")],
            [Button.inline("🔙 إلغاء والقائمة الرئيسية", data="back_home")],
        ]

    await send_or_update_wizard(event, sender_id, text, buttons)

@bot.on(events.NewMessage(pattern="/start"))
async def start_cmd(event):
    sender = await event.get_sender()
    if not sender:
        return

    sender_id = str(sender.id)
    sender_int_id = sender.id
    is_adm = (sender.username and sender.username.lower() == ADMIN_USERNAME.lower())

    try:
        await event.delete()
    except Exception:
        pass

    if is_adm:
        if sender_int_id in user_states:
            user_states[sender_int_id].pop("wizard", None)
        await render_main_menu(event, is_edit=False, is_adm=True)
        return

    users = load_users()
    if sender_id not in users:
        users[sender_id] = {
            "name": sender.first_name or "مستخدم",
            "username": sender.username or "لا يوجد",
            "status": "pending",
        }
        save_users(users)
        await event.respond("⏳ **تم إرسال طلبك للمالك بانتظار الموافقة.**", parse_mode="markdown")
        return

    status = users[sender_id].get("status")
    if status == "approved":
        if sender_int_id in user_states:
            user_states[sender_int_id].pop("wizard", None)
        await render_main_menu(event, is_edit=False, is_adm=False)

@bot.on(events.CallbackQuery)
async def cb_handler(event):
    sender = await event.get_sender()
    if not sender:
        return

    sender_id = str(sender.id)
    sender_int_id = sender.id
    is_adm = (sender.username and sender.username.lower() == ADMIN_USERNAME.lower())

    if not is_adm:
        users = load_users()
        if sender_id not in users or users[sender_id].get("status") != "approved":
            await event.answer("⛔ غير مصرح لك بالحساب!", alert=True)
            return

    data = event.data.decode("utf-8")
    cfg = load_config()

    if data == "back_home":
        user_states[sender_int_id].pop("wizard", None)
        await render_main_menu(event, is_edit=True, is_adm=is_adm)

    elif data == "menu_extract_save":
        await render_wizard_ext(event, sender_int_id, 1)
    elif data == "wiz_ext_next_2":
        await render_wizard_ext(event, sender_int_id, 2)
    elif data == "wiz_ext_next_3":
        await render_wizard_ext(event, sender_int_id, 3)
    elif data == "wiz_ext_next_4":
        if not cfg.get("extract_source") or not cfg.get("old_phone"):
            await event.answer("⚠️ أدخل البيانات المطلوبة أولاً!", alert=True)
            return
        await render_wizard_ext(event, sender_int_id, 4)
    elif data == "wiz_ext_prev_1":
        await render_wizard_ext(event, sender_int_id, 1)
    elif data == "wiz_ext_prev_2":
        await render_wizard_ext(event, sender_int_id, 2)
    elif data == "wiz_ext_prev_3":
        await render_wizard_ext(event, sender_int_id, 3)

    elif data == "menu_actions_wizard":
        await render_wizard_act(event, sender_int_id, 1)
    elif data == "wiz_act_next_2":
        await render_wizard_act(event, sender_int_id, 2)
    elif data == "wiz_act_next_3":
        if not cfg.get("new_phone"):
            await event.answer("⚠️ أدخل رقم حساب الإضافة والتنفيذ أولاً!", alert=True)
            return
        await render_wizard_act(event, sender_int_id, 3)
    elif data == "wiz_act_next_4":
        if not cfg.get("target"):
            await event.answer("⚠️ حدد الجروب/القناة المستهدفة أولاً!", alert=True)
            return
        await render_wizard_act(event, sender_int_id, 4)

    elif data == "ext_run_save":
        user_states.pop(sender_int_id, None)
        progress_msg = await event.respond("⏳ جاري تحضير واستخراج كافة الأعضاء...")
        task = asyncio.create_task(run_extraction_task(progress_msg, cfg))
        active_tasks[progress_msg.chat_id] = task

    elif data == "manual_save_contacts":
        user_states[sender_int_id] = {"wizard": "manual_phone_input"}
        try:
            await event.edit(
                "📱 **أدخل رقم الهاتف الذي ترغب في حفظ جهات الاتصال فيه يدوياً (مع رمز الدولة):**\nمثال: `+201012345678`"
            )
        except Exception:
            pass

    elif data == "skip_saving":
        extracted_cache.pop(event.chat_id, None)
        await event.edit("✅ تم التخطي بنجاح.", buttons=[[Button.inline("🔙 القائمة الرئيسية", data="back_home")]])

    elif data == "add_run":
        user_states.pop(sender_int_id, None)
        progress_msg = await event.respond("🚀 جاري بدء عملية الإضافة المباشرة بـ (ID / Username)...")
        task = asyncio.create_task(run_direct_add_task(progress_msg, cfg))
        active_tasks[progress_msg.chat_id] = task

    elif data == "show_settings":
        try:
            await event.edit(
                f"📊 **الإعدادات الحالية:**\n\n🎯 الوجهة: `{cfg['target']}`\n🔍 جروب الاستخراج: `{cfg.get('extract_source') or 'غير محدد'}`\n📱 حساب الاستخراج: `{cfg.get('old_phone') or 'غير محدد'}`\n📱 حساب الإضافة المباشرة: `{cfg.get('new_phone') or 'غير محدد'}`",
                buttons=[[Button.inline("🔙 القائمة الرئيسية", data="back_home")]],
                parse_mode="markdown",
            )
        except Exception:
            pass

@bot.on(events.NewMessage)
async def message_handler(event):
    sender = await event.get_sender()
    if not sender:
        return

    sender_id = sender.id
    if sender_id in auth_futures and not auth_futures[sender_id].done():
        auth_futures[sender_id].set_result(event.raw_text.strip())
        try:
            await event.delete()
        except Exception:
            pass
        return

    state_info = user_states.get(sender_id)
    if not state_info:
        return

    cfg = load_config()
    text = event.raw_text.strip()

    try:
        await event.delete()
    except Exception:
        pass

    if state_info.get("wizard") == "manual_phone_input":
        user_states.pop(sender_id, None)
        cfg["custom_save_phone"] = text
        save_config(cfg)
        
        users_list = extracted_cache.get(event.chat_id)
        if not users_list:
            await event.respond("⚠️ يرجى إجراء عملية الاستخراج أولاً للحصول على الأعضاء.")
            return

        progress_msg = await event.respond(f"🔄 جاري حفظ جهات الاتصال في الرقم المحدد (`{text}`)...")
        asyncio.create_task(save_contacts_to_custom_phone(progress_msg, text, users_list))
        return

    if "wizard" in state_info and state_info["wizard"] == "ext":
        current_step = state_info["step"]
        if current_step == 1:
            cfg["extract_source"] = text
            save_config(cfg)
            await render_wizard_ext(event, sender_id, 2)
        elif current_step == 2:
            if text.isdigit():
                cfg["message_limit"] = int(text)
                save_config(cfg)
                await render_wizard_ext(event, sender_id, 3)
        elif current_step == 3:
            cfg["old_phone"] = text
            save_config(cfg)
            await render_wizard_ext(event, sender_id, 4)

    elif "wizard" in state_info and state_info["wizard"] == "act":
        current_step = state_info["step"]
        if current_step == 1:
            cfg["new_phone"] = text
            save_config(cfg)
            await render_wizard_act(event, sender_id, 2)
        elif current_step == 2:
            cfg["target"] = text
            save_config(cfg)
            await render_wizard_act(event, sender_id, 3)
        elif current_step == 3:
            cfg["message"] = text
            save_config(cfg)
            await render_wizard_act(event, sender_id, 4)

async def interactive_login(client, phone, account_label, progress_msg):
    await client.connect()
    if not await client.is_user_authorized():
        chat_id = progress_msg.chat_id
        while True:
            try:
                sent = await client.send_code_request(phone)
                phone_code_hash = sent.phone_code_hash
            except Exception as e:
                await asyncio.sleep(3)
                continue

            try:
                await progress_msg.edit(f"📱 **أدخل كود التفعيل للحساب (`{phone}` - {account_label}):**")
            except Exception:
                pass

            future = asyncio.get_running_loop().create_future()
            auth_futures[chat_id] = future
            code = await future

            try:
                await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
                break
            except (PhoneCodeExpiredError, PhoneCodeInvalidError):
                await asyncio.sleep(2)
                continue
            except Exception as e:
                if "sessionpasswordneeded" in str(e).lower() or isinstance(e, SessionPasswordNeededError):
                    try:
                        await progress_msg.edit(f"🔐 **أدخل كلمة مرور التحقق بخطوتين للحساب (`{phone}`):**")
                    except Exception:
                        pass
                    future = asyncio.get_running_loop().create_future()
                    auth_futures[chat_id] = future
                    password = await future
                    await client.sign_in(password=password)
                    break

async def safe_edit(msg, text, buttons=None):
    while True:
        try:
            await msg.edit(text, buttons=buttons, parse_mode="markdown")
            break
        except FloodWaitError as e:
            await asyncio.sleep(e.seconds + 2)
        except Exception:
            break

async def save_contacts_to_custom_phone(progress_msg, phone_num, users_list):
    session_name = "session_custom_" + phone_num.replace("+", "")
    try:
        client = TelegramClient(session_name, API_ID, API_HASH)
        await interactive_login(client, phone_num, "حفظ الأرقام", progress_msg)

        added = 0
        privacy_blocked = 0

        for idx, u in enumerate(users_list, 1):
            phone_val = getattr(u, "phone", None) or ""
            try:
                # محاولة الحفظ عبر التليفون أو عبر الآيدي مباشرة كجهة اتصال
                await client(AddContactRequest(
                    id=u.id,
                    first_name=u.first_name or "User",
                    last_name=u.last_name or "",
                    phone=phone_val
                ))
                added += 1
            except (UserPrivacyRestrictedError, Exception):
                privacy_blocked += 1

            if idx % 20 == 0 or idx == len(users_list):
                await safe_edit(
                    progress_msg,
                    f"📇 **جاري إضافة الأعضاء لجهات الاتصال بالحساب (`{phone_num}`)...**\n\n"
                    f"• تم الحفظ بنجاح: `{added}`\n"
                    f"• متعذر بسبب الخصوصية: `{privacy_blocked}`\n"
                    f"• التقدم: `({idx}/{len(users_list)})`"
                )
            await asyncio.sleep(0.5)

        await client.disconnect()
        await safe_edit(
            progress_msg,
            f"✅ **اكتملت عملية الحفظ في جهات الاتصال!**\n\n"
            f"• المحفوظين فعلياً: `{added}`\n"
            f"• يوزر قافلين الخصوصية: `{privacy_blocked}`",
            buttons=[[Button.inline("🔙 القائمة الرئيسية", data="back_home")]]
        )
    except Exception as e:
        await safe_edit(progress_msg, f"❌ حدث خطأ أثناء الحفظ: `{str(e)}`", buttons=[[Button.inline("🔙 القائمة الرئيسية", data="back_home")]])

async def run_extraction_task(progress_msg, cfg):
    old_phone = cfg["old_phone"].strip()
    extract_source = clean_target(cfg.get("extract_source"))
    message_limit = cfg.get("message_limit", 0)
    session_old = "session_old_" + old_phone.replace("+", "")
    client_old = None
    users_map = {}

    try:
        await show_loading(progress_msg, "جاري فتح حساب الاستخراج وجلب البيانات")
        client_old = TelegramClient(session_old, API_ID, API_HASH)
        await interactive_login(client_old, old_phone, "الاستخراج", progress_msg)

        await safe_edit(progress_msg, "🔄 جاري استخراج كافة المستخدمين...")
        last_update = time.time()
        count = 0

        if message_limit == 0:
            async for user in client_old.iter_participants(extract_source):
                if isinstance(user, User) and not getattr(user, "bot", False):
                    users_map[user.id] = user
                    if time.time() - last_update >= 3.0:
                        last_update = time.time()
                        await safe_edit(progress_msg, f"🔄 **جاري استخراج الأعضاء...**\n• تم جلب: `({len(users_map)})` مستخدم فريد.")
        else:
            async for msg in client_old.iter_messages(extract_source, limit=message_limit):
                count += 1
                if msg.sender and isinstance(msg.sender, User) and not getattr(msg.sender, "bot", False):
                    users_map[msg.sender.id] = msg.sender
                if time.time() - last_update >= 3.0 or count == message_limit:
                    last_update = time.time()
                    await safe_edit(progress_msg, f"🔄 **جاري فحص الرسائل...**\n• تم فحص: `({count}/{message_limit})` رسالة\n• تم جلب: `({len(users_map)})` مستخدم فريد.")

    except Exception as e:
        print(f"Extraction Error: {e}")
    finally:
        if client_old:
            try:
                await client_old.disconnect()
            except Exception:
                pass
        active_tasks.pop(progress_msg.chat_id, None)

    users_list = list(users_map.values())
    if not users_list:
        await safe_edit(progress_msg, "❌ لم يتم جلب أي نتائج!", buttons=[[Button.inline("🔙 القائمة الرئيسية", data="back_home")]])
        return

    extracted_cache[progress_msg.chat_id] = users_list

    buttons = [
        [Button.inline("📇 تحديد رقم هاتف يدوياً لحفظ جهات الاتصال فيه", data="manual_save_contacts")],
        [Button.inline("🚀 الانتقال للإضافة المباشرة في الجروب فوراً", data="menu_actions_wizard")]
    ]

    await safe_edit(
        progress_msg,
        f"✅ **تم استخراج ({len(users_list)}) مستخدم بنجاح!**\n\nيمكنك الآن إما حفظهم في جهات اتصال أي رقم يدوياً أو البدء في الإضافة المباشرة.",
        buttons=buttons,
    )

async def run_direct_add_task(progress_msg, cfg):
    new_phone = cfg["new_phone"].strip()
    target_group = clean_target(cfg.get("target"))
    invitation_message = cfg["message"]

    session_new = "session_new_" + new_phone.replace("+", "")
    client_new = None

    try:
        await show_loading(progress_msg, "جاري فتح حساب الإضافة المباشرة")
        client_new = TelegramClient(session_new, API_ID, API_HASH)
        await interactive_login(client_new, new_phone, "الإضافة المباشرة", progress_msg)

        users_list = extracted_cache.get(progress_msg.chat_id, [])
        if not users_list:
            contacts_res = await client_new(GetContactsRequest(hash=0))
            users_list = [u for u in contacts_res.users if isinstance(u, User) and not getattr(u, "bot", False)]

        if not users_list:
            await progress_msg.edit("❌ لا يوجد أعضاء جاهزون للإضافة المباشرة في الذاكرة!")
            await client_new.disconnect()
            return

        existing_members_ids = set()
        try:
            async for participant in client_new.iter_participants(target_group):
                if isinstance(participant, User):
                    existing_members_ids.add(participant.id)
        except Exception:
            pass

        sent_users_set = set()
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    for line in f:
                        clean_id = line.strip()
                        if clean_id.isdigit():
                            sent_users_set.add(int(clean_id))
            except Exception:
                pass

        users_to_process = [u for u in users_list if u.id not in existing_members_ids and u.id not in sent_users_set]

        if not users_to_process:
            await progress_msg.edit("🎉 جميع الأعضاء مضافون أو تم معالجتهم بالفعل!")
            await client_new.disconnect()
            return

        added_count = 0
        dm_sent_count = 0
        failed_count = 0
        total_users = len(users_to_process)

        for idx, user in enumerate(users_to_process, 1):
            user_target = user.username if getattr(user, "username", None) else user.id
            try:
                await client_new(InviteToChannelRequest(target_group, [user_target]))
                added_count += 1
            except (UserPrivacyRestrictedError, UserNotMutualContactError):
                try:
                    await client_new.send_message(user.id, invitation_message)
                    dm_sent_count += 1
                except Exception:
                    failed_count += 1
            except UserChannelsTooMuchError:
                failed_count += 1
            except FloodWaitError as e:
                await asyncio.sleep(e.seconds + 5)
            except Exception:
                try:
                    await client_new.send_message(user.id, invitation_message)
                    dm_sent_count += 1
                except Exception:
                    failed_count += 1

            try:
                with open(HISTORY_FILE, "a", encoding="utf-8") as f:
                    f.write(f"{user.id}\n")
            except Exception:
                pass

            if idx % 5 == 0 or idx == total_users:
                await safe_edit(
                    progress_msg,
                    f"🚀 **جارٍ الإضافة والتنفيذ...** ({idx}/{total_users})\n\n"
                    f"• إضافة مباشرة ناجحة: `{added_count}`\n"
                    f"• رسائل خاص (بسبب الخصوصية): `{dm_sent_count}`\n"
                    f"• متعذر التواصل: `{failed_count}`"
                )

            await asyncio.sleep(random.uniform(12, 22))

        await client_new.disconnect()
        await safe_edit(
            progress_msg,
            f"🎉 **تمت عملية الإضافة بنجاح!**\n\n"
            f"• تم إضافتهم للجروب مباشرة: `{added_count}`\n"
            f"• تم إرسال دعوة خاص لهم: `{dm_sent_count}`\n"
            f"• الحسابات المغلقة/المتحفظة: `{failed_count}`",
            buttons=[[Button.inline("🔙 القائمة الرئيسية", data="back_home")]]
        )

    except Exception as e:
        if client_new:
            try:
                await client_new.disconnect()
            except Exception:
                pass
        await safe_edit(progress_msg, f"❌ حدث خطأ: `{str(e)}`")
    finally:
        active_tasks.pop(progress_msg.chat_id, None)

async def main_loop():
    while True:
        try:
            print("🤖 جاري تشغيل البوت...")
            if not bot.is_connected():
                await bot.connect()

            if not await bot.is_user_authorized():
                await bot.start(bot_token=BOT_TOKEN)

            await bot.run_until_disconnected()
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"❌ خطأ غير متوقع: {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        pass
