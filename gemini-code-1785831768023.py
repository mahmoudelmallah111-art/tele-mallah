import asyncio
import base64
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import random
import threading
import time
import urllib.request

from telethon import Button, TelegramClient, events
from telethon.errors import (
    FloodWaitError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
    UserChannelsTooMuchError,
    UserNotMutualContactError,
    UserPrivacyRestrictedError,
)
from telethon.tl.functions.channels import InviteToChannelRequest
from telethon.tl.functions.contacts import AddContactRequest, GetContactsRequest
from telethon.tl.types import Channel, User

# =========================================================
# 1) خادم ويب وهمي لإبقاء الخدمة شغالة على Render / Cloud
# =========================================================
class DummyHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot Engine is Live and Persistent!")

    def log_message(self, format, *args):
        return

def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), DummyHTTPRequestHandler)
    server.serve_forever()

threading.Thread(target=run_dummy_server, daemon=True).start()

# =========================================================
# 2) إعدادات المتغيرات الأساسية والمزامنة السحابية
# =========================================================
API_ID = 28513802
API_HASH = "fe0ef7e83635cdd89512e833c0ddcb28"
BOT_TOKEN = "8996749859:AAF6WPtVQrBrDw9N84Irf78kIF2GWYdeUYw"

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "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")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "mahmoudelmallah111-art/data-tele-mallah")

USERS_DB_FILE = "users_db.json"
ADMIN_USERNAME = "m7mallah"
ADMIN_IDS = [790214811]

active_tasks = {}
user_states = {}
auth_futures = {}

def is_admin_user(sender):
    if not sender:
        return False
    if sender.id in ADMIN_IDS:
        return True
    if sender.username and sender.username.lower().replace("@", "") == ADMIN_USERNAME.lower():
        return True
    return False

# ---------------------------------------------------------
# نظام الحفظ الدائم والمزامنة السحابية (GitHub Sync)
# ---------------------------------------------------------
def sync_to_github(file_path):
    if not GITHUB_TOKEN or not GITHUB_REPO or not os.path.exists(file_path):
        return
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{file_path}"
        with open(file_path, "rb") as f:
            content = base64.b64encode(f.read()).decode("utf-8")
        
        req = urllib.request.Request(url, headers={"Authorization": f"token {GITHUB_TOKEN}"})
        sha = None
        try:
            with urllib.request.urlopen(req) as response:
                sha = json.loads(response.read().decode())["sha"]
        except Exception:
            pass

        data = {"message": f"Auto-sync {file_path}", "content": content}
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
        print(f"GitHub Sync Error ({file_path}): {e}")

def restore_from_github(file_path):
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{file_path}"
        req = urllib.request.Request(url, headers={"Authorization": f"token {GITHUB_TOKEN}"})
        with urllib.request.urlopen(req) as response:
            res_data = json.loads(response.read().decode())
            content = base64.b64encode(res_data["content"])
            with open(file_path, "wb") as f:
                f.write(content)
            print(f"✅ تم استرجاع الملف بنجاح: {file_path}")
    except Exception:
        pass

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

# ---------------------------------------------------------
# إدارة قاعدة بيانات المستخدمين المستقلة (Per-User Storage)
# ---------------------------------------------------------
def get_user_file(user_id):
    return f"user_data_{user_id}.json"

def load_users_db():
    restore_from_github(USERS_DB_FILE)
    if os.path.exists(USERS_DB_FILE):
        try:
            with open(USERS_DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_users_db(db):
    try:
        with open(USERS_DB_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=4)
        sync_to_github(USERS_DB_FILE)
    except Exception as e:
        print(f"Error saving users DB: {e}")

def load_user_profile(user_id):
    file_path = get_user_file(user_id)
    restore_from_github(file_path)
    default_profile = {
        "config": {
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
        },
        "extracted_members": {},  # {str(user_id): {"id": int, "username": str, "first_name": str, "phone": str}}
        "history_sent": [],       # [user_id_int, ...]
        "operations_log": []
    }
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                default_profile["config"].update(data.get("config", {}))
                default_profile["extracted_members"].update(data.get("extracted_members", {}))
                default_profile["history_sent"] = list(set(data.get("history_sent", []) + default_profile["history_sent"]))
                default_profile["operations_log"] = data.get("operations_log", [])
                return default_profile
        except Exception:
            pass
    return default_profile

def save_user_profile(user_id, profile):
    file_path = get_user_file(user_id)
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(profile, f, ensure_ascii=False, indent=4)
        sync_to_github(file_path)
    except Exception as e:
        print(f"Error saving profile for {user_id}: {e}")

print("🔄 جاري تهيئة نظام التشغيل والمكونات...")
bot = TelegramClient("bot_session_main", API_ID, API_HASH)

# =========================================================
# 3) الواجهات والأدوات المساعدة
# =========================================================
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
    chat_id = event.chat_id if hasattr(event, "chat_id") else event.chat_id

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
    profile = load_user_profile(sender_id) if sender_id else {}
    saved_count = len(profile.get("extracted_members", {}))

    buttons = []
    if is_adm:
        users = load_users_db()
        pending_count = sum(1 for u in users.values() if u.get("status") == "pending")
        buttons.append([Button.inline(f"👥 إدارة طلبات المستخدمين ({pending_count} معلق)", data="admin_requests_panel")])

    buttons.extend([
        [Button.inline("📥 1. معالج استخراج الأرقام (تصفية التكرار تلقائياً)", data="menu_extract_save")],
        [Button.inline("🚀 2. معالج الإرسال والإضافة التلقائية", data="menu_actions_wizard")],
        [Button.inline(f"📁 3. إدارة الأرقام المحفوظة بالذاكرة ({saved_count} عضو)", data="view_saved_database")],
        [Button.inline("💾 4. تعيين رقم مخصص لحفظ الأرقام", data="manual_save_contacts")],
        [Button.inline("📊 عرض الإعدادات الحالية", data="show_settings")],
    ])

    text = "🌟 **لوحة تحكم البوت الاحترافية الذكية (النظام المطور)** 🌟\n\nاختر المعالج أو الإجراء المطلوب للبدء:"

    if sender_id:
        await send_or_update_wizard(event, sender_id, text, buttons)
    else:
        if is_edit:
            try: await event.edit(text, buttons=buttons, parse_mode="markdown")
            except Exception: await event.respond(text, buttons=buttons, parse_mode="markdown")
        else:
            await event.respond(text, buttons=buttons, parse_mode="markdown")

async def render_wizard_ext(event, sender_id, step):
    profile = load_user_profile(sender_id)
    cfg = profile["config"]
    if sender_id not in user_states:
        user_states[sender_id] = {}
    user_states[sender_id].update({"wizard": "ext", "step": step})

    if step == 1:
        text = f"🧙‍♂️ **معالج الاستخراج (الخطوة 1 من 3)**\n\n🎯 **تحديد جروب الاستخراج:**\nأرسل الآن يوزر أو رابط الجروب المراد الاستخراج منه.\n\n🔗 القيمة الحالية: `{cfg.get('extract_source') or 'غير محدد'}`"
        buttons = [
            [Button.inline("التالي ➡️", data="wiz_ext_next_2")],
            [Button.inline("🔙 إلغاء والقائمة الرئيسية", data="back_home")]
        ]
    elif step == 2:
        text = f"🧙‍♂️ **معالج الاستخراج (الخطوة 2 من 3)**\n\n📊 **حد الرسائل:**\nأرسل عدد الرسائل المراد فحصها (اكتب `0` لاستخراج كامل أعضاء الجروب مباشر).\n\n🔗 القيمة الحالية: `{cfg.get('message_limit', 0)}`"
        buttons = [
            [Button.inline("⬅️ السابق", data="wiz_ext_prev_1"), Button.inline("التالي ➡️", data="wiz_ext_next_3")],
            [Button.inline("🔙 إلغاء والقائمة الرئيسية", data="back_home")]
        ]
    elif step == 3:
        text = f"🧙‍♂️ **معالج الاستخراج (الخطوة 3 من 3)**\n\n📱 **حساب السحب:**\nأرسل رقم هاتف حساب السحب (مع رمز الدولة).\n\n🔗 القيمة الحالية: `{cfg.get('old_phone') or 'غير محدد'}`"
        buttons = [
            [Button.inline("⬅️ السابق", data="wiz_ext_prev_2"), Button.inline("🔍 مراجعة وتأكيد التنفيذ 🚀", data="wiz_ext_next_4")],
            [Button.inline("🔙 إلغاء والقائمة الرئيسية", data="back_home")]
        ]
    elif step == 4:
        saved_db_count = len(profile.get("extracted_members", {}))
        text = (
            f"📋 **مراجعة بيانات الاستخراج والتصفية:**\n\n"
            f"• جروب الاستخراج: `{cfg.get('extract_source', 'غير محدد')}`\n"
            f"• حد الرسائل: `{cfg.get('message_limit', 0)}`\n"
            f"• حساب السحب: `{cfg.get('old_phone', 'غير محدد')}`\n"
            f"• الأرقام المحفوظة سابقاً بذاكرتك: `{saved_db_count}` (سيتم منع تكرارها تلقائياً)\n\n"
            f"هل أنت متأكد من البدء؟"
        )
        buttons = [
            [Button.inline("⬅️ تعديل البيانات", data="wiz_ext_prev_3")],
            [Button.inline("▶️ تأكيد وتنفيذ الاستخراج الآن", data="ext_run_save")],
            [Button.inline("🔙 إلغاء والقائمة الرئيسية", data="back_home")]
        ]

    await send_or_update_wizard(event, sender_id, text, buttons)

async def render_wizard_act(event, sender_id, step):
    profile = load_user_profile(sender_id)
    cfg = profile["config"]
    if sender_id not in user_states:
        user_states[sender_id] = {}
    user_states[sender_id].update({"wizard": "act", "step": step})

    if step == 1:
        text = f"🚀 **معالج الإرسال والإضافة (الخطوة 1 من 4)**\n\n📱 **حساب السحب:**\nأرسل رقم هاتف الحساب القديم (المسحوب منه جهات الاتصال).\n\n🔗 القيمة الحالية: `{cfg.get('old_phone') or 'غير محدد'}`"
        buttons = [
            [Button.inline("التالي ➡️", data="wiz_act_next_2")],
            [Button.inline("🔙 إلغاء والقائمة الرئيسية", data="back_home")]
        ]
    elif step == 2:
        text = f"🚀 **معالج الإرسال والإضافة (الخطوة 2 من 4)**\n\n📱 **حساب الإدارة:**\nأرسل رقم هاتف الحساب الجديد (المسؤول عن الإرسال والإضافة).\n\n🔗 القيمة الحالية: `{cfg.get('new_phone') or 'غير محدد'}`"
        buttons = [
            [Button.inline("⬅️ السابق", data="wiz_act_prev_1"), Button.inline("التالي ➡️", data="wiz_act_next_3")],
            [Button.inline("🔙 إلغاء والقائمة الرئيسية", data="back_home")]
        ]
    elif step == 3:
        text = f"🚀 **معالج الإرسال والإضافة (الخطوة 3 من 4)**\n\n🎯 **الوجهة المستهدفة:**\nأرسل يوزر أو رابط القناة/الجروب المستهدف بالإشهار.\n\n🔗 القيمة الحالية: `{cfg.get('target', 'غير محدد')}`"
        buttons = [
            [Button.inline("⬅️ السابق", data="wiz_act_prev_2"), Button.inline("التالي ➡️", data="wiz_act_next_4")],
            [Button.inline("🔙 إلغاء والقائمة الرئيسية", data="back_home")]
        ]
    elif step == 4:
        text = f"🚀 **معالج الإرسال والإضافة (الخطوة 4 من 4)**\n\n✏️ **رسالة الدعوة:**\nأرسل نص رسالة الدعوة الذي سيتم إرساله للمستخدمين.\n\n🔗 النص الحالي:\n`{cfg.get('message', 'غير محدد')}`"
        buttons = [
            [Button.inline("⬅️ السابق", data="wiz_act_prev_3"), Button.inline("🔍 مراجعة وتأكيد التنفيذ 🚀", data="wiz_act_next_5")],
            [Button.inline("🔙 إلغاء والقائمة الرئيسية", data="back_home")]
        ]
    elif step == 5:
        text = f"📋 **مراجعة بيانات الإرسال والإضافة النهائية:**\n\n• حساب السحب: `{cfg.get('old_phone', 'غير محدد')}`\n• حساب الإدارة: `{cfg.get('new_phone', 'غير محدد')}`\n• الوجهة المستهدفة: `{cfg.get('target', 'غير محدد')}`\n• رسالة الدعوة:\n`{cfg.get('message', 'غير محدد')}`\n\nهل أنت متأكد من بدء عملية الإرسال والإضافة التلقائية؟"
        buttons = [
            [Button.inline("⬅️ تعديل البيانات", data="wiz_act_prev_4")],
            [Button.inline("▶️ تأكيد وبدء التنفيذ الفوري", data="add_run")],
            [Button.inline("🔙 إلغاء والقائمة الرئيسية", data="back_home")]
        ]

    await send_or_update_wizard(event, sender_id, text, buttons)

# =========================================================
# 4) معالجة الأحداث والأزرار والموافقات الفورية
# =========================================================
@bot.on(events.NewMessage(pattern="/start"))
async def start_cmd(event):
    sender = await event.get_sender()
    if not sender: return

    sender_id_str = str(sender.id)
    sender_int_id = sender.id
    is_adm = is_admin_user(sender)

    try: await event.delete()
    except Exception: pass

    if is_adm:
        if sender_int_id in user_states:
            user_states[sender_int_id].pop("wizard", None)
        await render_main_menu(event, is_edit=False, is_adm=True)
        return

    users_db = load_users_db()
    if sender_id_str not in users_db:
        users_db[sender_id_str] = {
            "name": sender.first_name or "مستخدم",
            "username": sender.username or "لا يوجد",
            "status": "pending"
        }
        save_users_db(users_db)

        # إرسال إشعار للمشرف يحتوي على أزرار تفاعلية فورية للموافقة والرفض
        admin_buttons = [
            [
                Button.inline("✅ قبول المستخدم", data=f"fast_approve_{sender_id_str}"),
                Button.inline("❌ رفض الطلب", data=f"fast_reject_{sender_id_str}")
            ]
        ]
        try:
            await bot.send_message(
                f"@{ADMIN_USERNAME}",
                f"🔔 **طلب انضمام جديد للبوت!**\n\n"
                f"👤 **الاسم:** {sender.first_name}\n"
                f"🔗 **اليوزر:** @{sender.username or 'لا يوجد'}\n"
                f"🆔 **الآيدي:** `{sender.id}`\n\n"
                f"👇 **اختر الإجراء المناسب بنقرة واحدة:**",
                buttons=admin_buttons,
                parse_mode="markdown"
            )
        except Exception: pass

        await event.respond("⏳ **تم إرسال طلبك بنجاح إلى مالك البوت (@m7mallah).**\nيرجى الانتظار لحين الموافقة على طلبك...", parse_mode="markdown")
        return

    status = users_db[sender_id_str].get("status")
    if status == "pending":
        await event.respond("⏳ **طلبك قيد الانتظار...**\nلم يتم الموافقة عليه بعد من المالك.", parse_mode="markdown")
    elif status == "rejected":
        await event.respond("❌ **عذراً، تم رفض طلبك لاستخدام البوت.**", parse_mode="markdown")
    elif status == "approved":
        if sender_int_id in user_states:
            user_states[sender_int_id].pop("wizard", None)
        await render_main_menu(event, is_edit=False, is_adm=False)

@bot.on(events.CallbackQuery)
async def cb_handler(event):
    sender = await event.get_sender()
    if not sender: return

    sender_id_str = str(sender.id)
    sender_int_id = sender.id
    is_adm = is_admin_user(sender)

    data = event.data.decode("utf-8")

    # معالجة الموافقة والرفض المباشر من رسائل المشرف
    if is_adm and (data.startswith("fast_approve_") or data.startswith("fast_reject_")):
        parts = data.split("_")
        action = parts[1]
        target_uid = parts[2]
        users_db = load_users_db()

        if target_uid in users_db:
            if action == "approve":
                users_db[target_uid]["status"] = "approved"
                save_users_db(users_db)
                try: await bot.send_message(int(target_uid), "🎉 **مبارك! تم قبول طلبك لاستخدام البوت بنجاح.**\nأرسل `/start` للبدء في استخدام البوت.", parse_mode="markdown")
                except Exception: pass
                await event.edit(f"✅ **تم قبول المستخدم `{target_uid}` بنجاح وإشعاره!**", buttons=None, parse_mode="markdown")
            elif action == "reject":
                users_db[target_uid]["status"] = "rejected"
                save_users_db(users_db)
                try: await bot.send_message(int(target_uid), "❌ **عذراً، تم رفض طلبك لاستخدام البوت.**", parse_mode="markdown")
                except Exception: pass
                await event.edit(f"❌ **تم رفض طلب المستخدم `{target_uid}`!**", buttons=None, parse_mode="markdown")
        return

    if not is_adm:
        users_db = load_users_db()
        if sender_id_str not in users_db or users_db[sender_id_str].get("status") != "approved":
            await event.answer("⛔ عذراً، حسابك غير معتمد أو بانتظار الموافقة!", alert=True)
            return

    profile = load_user_profile(sender_int_id)
    cfg = profile["config"]

    if data == "stop_ext_prompt":
        confirm_buttons = [[Button.inline("✅ نعم، أوقف الآن", data="stop_ext_confirmed"), Button.inline("❌ إلغاء، تابع الاستخراج", data="stop_ext_cancel")]]
        try: await event.edit("⚠️ **هل أنت متأكد من رغبتك في إيقاف الاستخراج فوراً والاحتفاظ بالنتائج الحالية؟**", buttons=confirm_buttons, parse_mode="markdown")
        except Exception: pass
        return

    if data == "stop_ext_confirmed":
        chat_id = event.chat_id
        if chat_id in active_tasks: active_tasks[chat_id].cancel()
        try: await event.edit("⏳ **تم إيقاف الاستخراج فوراً!**\nجاري حفظ وتصفية الأرقام المستخرجة...", buttons=None, parse_mode="markdown")
        except Exception: pass
        await event.answer("⚠️ تم إيقاف الاستخراج بنجاح!", alert=True)
        return

    if data == "stop_ext_cancel":
        stop_btn = [[Button.inline("🛑 إيقاف والاستخراج بالنتيجة الحالية", data="stop_ext_prompt")]]
        try: await event.edit("🔄 جاري متابعة الاستخراج بناءً على طلبك...", buttons=stop_btn, parse_mode="markdown")
        except Exception: pass
        return

    if data == "stop_act":
        chat_id = event.chat_id
        if chat_id in active_tasks: active_tasks[chat_id].cancel()
        await event.answer("⚠️ يتم إيقاف العملية الحالية...", alert=True)
        return

    if sender_int_id not in user_states: user_states[sender_int_id] = {}
    user_states[sender_int_id]["last_bot_msg_id"] = event.message_id

    if is_adm:
        if data == "admin_requests_panel":
            users_db = load_users_db()
            buttons = []
            for uid, uinfo in users_db.items():
                status_emoji = "⏳ معلق" if uinfo.get("status") == "pending" else ("✅ مقبول" if uinfo.get("status") == "approved" else "❌ مرفوض")
                btn_text = f"{uinfo['name']} (@{uinfo['username']}) - {status_emoji}"
                buttons.append([Button.inline(btn_text, data=f"manage_u_{uid}")])
            buttons.append([Button.inline("🔙 القائمة الرئيسية", data="back_home")])
            try: await event.edit("👥 **إدارة المستخدمين:**\nاختر مستخدماً لتغيير حالته:", buttons=buttons, parse_mode="markdown")
            except Exception: await event.respond("👥 **إدارة المستخدمين:**\nاختر مستخدماً لتغيير حالته:", buttons=buttons, parse_mode="markdown")
            return

        elif data.startswith("manage_u_"):
            target_uid = data.split("_")[2]
            users_db = load_users_db()
            if target_uid in users_db:
                uinfo = users_db[target_uid]
                buttons = [
                    [Button.inline("✅ موافقة", data=f"approve_{target_uid}"), Button.inline("❌ رفض", data=f"reject_{target_uid}")],
                    [Button.inline("🚫 إنهاء الجلسة / سحب الصلاحية", data=f"terminate_{target_uid}")],
                    [Button.inline("🔙 رجوع للطلبات", data="admin_requests_panel")]
                ]
                try: await event.edit(f"👤 **المستخدم:** {uinfo['name']}\n- اليوزر: `@{uinfo['username']}`\n- الحالة الحالية: `{uinfo['status']}`", buttons=buttons, parse_mode="markdown")
                except Exception: pass
            return

        elif data.startswith("approve_") or data.startswith("reject_") or data.startswith("terminate_"):
            parts = data.split("_")
            action = parts[0]
            target_uid = parts[1]
            users_db = load_users_db()
            if target_uid in users_db:
                if action == "approve":
                    users_db[target_uid]["status"] = "approved"
                    try: await bot.send_message(int(target_uid), "🎉 **مبارك! تم قبول طلبك لاستخدام البوت بنجاح.**", parse_mode="markdown")
                    except Exception: pass
                    await event.answer("✅ تم قبول المستخدم!", alert=True)
                elif action == "reject":
                    users_db[target_uid]["status"] = "rejected"
                    await event.answer("❌ تم رفض المستخدم!", alert=True)
                elif action == "terminate":
                    users_db[target_uid]["status"] = "pending"
                    await event.answer("🚫 تم إلغاء التفعيل!", alert=True)
                save_users_db(users_db)
                event.data = f"manage_u_{target_uid}".encode()
                await cb_handler(event)
            return

    if data == "back_home":
        user_states[sender_int_id].pop("wizard", None)
        await render_main_menu(event, is_edit=True, is_adm=is_adm)

    elif data == "view_saved_database":
        ext_members = profile.get("extracted_members", {})
        count = len(ext_members)
        text = (
            f"📁 **إدارة الأرقام والأعضاء المحفوظين بذاكرتك:**\n\n"
            f"• عدد الأعضاء المسجلين حالياً: `{count}` عضواً فريداً.\n"
            f"• يتم استخدام هذه القاعدة تلقائياً لمنع تكرار أي عضو عند فحص جروبات جديدة.\n\n"
            f"يمكنك تفريغ الذاكرة أو مواصلة استخدام الأرقام الحالية في عمليات الإرسال والإضافة."
        )
        buttons = [
            [Button.inline("🗑️ مسح وإعادة تعيين ذاكرة الأعضاء المحفوظين", data="clear_my_saved_db")],
            [Button.inline("🔙 القائمة الرئيسية", data="back_home")]
        ]
        try: await event.edit(text, buttons=buttons, parse_mode="markdown")
        except Exception: pass

    elif data == "clear_my_saved_db":
        profile["extracted_members"] = {}
        save_user_profile(sender_int_id, profile)
        await event.answer("✅ تم مسح ذاكرة الأرقام المحفوظة بنجاح!", alert=True)
        await render_main_menu(event, is_edit=True, is_adm=is_adm)

    elif data == "manual_save_contacts":
        user_states[sender_int_id] = {"wizard": "manual_phone_input"}
        await event.respond("📱 **أدخل رقم الهاتف المراد حفظ جهات الاتصال فيه الآن (مع رمز الدولة):**\nمثال: `+201012345678`")

    elif data == "menu_extract_save":
        await render_wizard_ext(event, sender_int_id, 1)
    elif data == "wiz_ext_next_2": await render_wizard_ext(event, sender_int_id, 2)
    elif data == "wiz_ext_next_3": await render_wizard_ext(event, sender_int_id, 3)
    elif data == "wiz_ext_next_4":
        if not cfg.get("extract_source") or not cfg.get("old_phone"):
            await event.answer("⚠️ يرجى إدخال جروب الاستخراج ورقم حساب السحب أولاً!", alert=True)
            return
        await render_wizard_ext(event, sender_int_id, 4)
    elif data == "wiz_ext_prev_1": await render_wizard_ext(event, sender_int_id, 1)
    elif data == "wiz_ext_prev_2": await render_wizard_ext(event, sender_int_id, 2)
    elif data == "wiz_ext_prev_3": await render_wizard_ext(event, sender_int_id, 3)

    elif data == "menu_actions_wizard":
        await render_wizard_act(event, sender_int_id, 1)
    elif data == "wiz_act_next_2": await render_wizard_act(event, sender_int_id, 2)
    elif data == "wiz_act_next_3":
        if not cfg.get("old_phone"):
            await event.answer("⚠️ يرجى إدخال رقم حساب السحب أولاً!", alert=True)
            return
        await render_wizard_act(event, sender_int_id, 3)
    elif data == "wiz_act_next_4":
        if not cfg.get("new_phone"):
            await event.answer("⚠️ يرجى إدخال رقم حساب الإدارة أولاً!", alert=True)
            return
        await render_wizard_act(event, sender_int_id, 4)
    elif data == "wiz_act_next_5":
        if not cfg.get("target"):
            await event.answer("⚠️ يرجى تحديد الوجهة المستهدفة أولاً!", alert=True)
            return
        await render_wizard_act(event, sender_int_id, 5)
    elif data == "wiz_act_prev_1": await render_wizard_act(event, sender_int_id, 1)
    elif data == "wiz_act_prev_2": await render_wizard_act(event, sender_int_id, 2)
    elif data == "wiz_act_prev_3": await render_wizard_act(event, sender_int_id, 3)
    elif data == "wiz_act_prev_4": await render_wizard_act(event, sender_int_id, 4)

    elif data == "ext_run_save":
        if not cfg.get("extract_source") or not cfg.get("old_phone"):
            await event.answer("⚠️ يرجى تحديد جروب الاستخراج ورقم حساب السحب أولاً!", alert=True)
            return
        user_states.pop(sender_int_id, None)
        progress_msg = await event.respond("⏳ جاري تحضير الحساب وفحص الجروب وتصفية الأعضاء المكررين...")
        task = asyncio.create_task(run_extraction_and_save_task(progress_msg, sender_int_id))
        active_tasks[progress_msg.chat_id] = task

    elif data in ("save_contacts_old", "save_contacts_new", "save_contacts_custom"):
        ext_members = profile.get("extracted_members", {})
        if not ext_members:
            await event.answer("⚠️ لا توجد أرقام مسجلة بذاكرتك للحفظ!", alert=True)
            return

        if data == "save_contacts_old":
            phone = cfg.get("old_phone")
            account_label = "السحب"
        elif data == "save_contacts_new":
            phone = cfg.get("new_phone")
            account_label = "الإدارة"
        else:
            phone = cfg.get("custom_save_phone")
            account_label = "المخصص"

        session_name = "session_save_" + phone.replace("+", "")

        try: await event.edit(f"🔄 جاري الاتصال بحساب ({account_label}) لبدء الحفظ الحقيقي لجهات الاتصال...")
        except Exception: pass
        msg_obj = await event.get_message()
        
        try:
            client = TelegramClient(session_name, API_ID, API_HASH)
            await interactive_login(client, phone, account_label, msg_obj)

            added_contacts = 0
            failed_contacts = 0
            users_list = list(ext_members.values())
            total_users = len(users_list)
            last_update = time.time()
            stop_btn = [[Button.inline("🛑 إيقاف عملية الحفظ", data="stop_act")]]

            for idx, udata in enumerate(users_list, 1):
                try:
                    uid = udata["id"]
                    user_phone = udata.get("phone", "") or ""
                    first_name = udata.get("first_name", "") or "User"

                    await client(AddContactRequest(
                        id=uid,
                        first_name=first_name,
                        last_name="",
                        phone=user_phone,
                        add_phone_privacy_exception=False
                    ))
                    added_contacts += 1

                except FloodWaitError as e:
                    await asyncio.sleep(e.seconds + 2)
                    try:
                        await client(AddContactRequest(
                            id=uid,
                            first_name=first_name,
                            last_name="",
                            phone=user_phone,
                            add_phone_privacy_exception=False
                        ))
                        added_contacts += 1
                    except Exception:
                        failed_contacts += 1

                except Exception:
                    failed_contacts += 1

                if time.time() - last_update >= 3.0 or idx == total_users:
                    last_update = time.time()
                    try:
                        await event.edit(
                            f"📇 **جاري حفظ جهات الاتصال فعلياً بحساب ({account_label})...**\n"
                            f"• التقدم: `{idx}/{total_users}`\n"
                            f"• ✅ تم الحفظ بنجاح: `{added_contacts}`\n"
                            f"• ❌ تعذر (قيود/خطأ): `{failed_contacts}`",
                            buttons=stop_btn,
                            parse_mode="markdown"
                        )
                    except Exception: pass

                await asyncio.sleep(0.3)

            await client.disconnect()

            await event.edit(
                f"✅ **اكتملت عملية الحفظ بحساب ({account_label})!**\n\n"
                f"📊 **التقرير النهائي:**\n"
                f"• 🎯 تم حفظهم كجهات اتصال: `{added_contacts}`\n"
                f"• ⚠️ فشل / قيود الخصوصية: `{failed_contacts}`\n"
                f"• 👥 إجمالي المفحوصين: `{total_users}`",
                buttons=[[Button.inline("🔙 القائمة الرئيسية", data="back_home")]],
                parse_mode="markdown"
            )
        except Exception as e:
            await event.edit(
                f"❌ حدث خطأ أثناء الحفظ: `{str(e)}`",
                buttons=[[Button.inline("🔙 القائمة الرئيسية", data="back_home")]],
            )

    elif data == "skip_saving":
        await event.edit("✅ **تم الانتهاء وتخطي حفظ الأرقام.**", buttons=[[Button.inline("🔙 القائمة الرئيسية", data="back_home")]], parse_mode="markdown")

    elif data == "add_run":
        if not cfg.get("old_phone") or not cfg.get("new_phone"):
            await event.answer("⚠️ يرجى تعيين أرقام الحسابات أولاً!", alert=True)
            return
        user_states.pop(sender_int_id, None)
        progress_msg = await event.respond("🚀 جاري التحضير لعمليات الإرسال والإضافة...")
        task = asyncio.create_task(run_automation_task(progress_msg, sender_int_id))
        active_tasks[progress_msg.chat_id] = task

    elif data == "show_settings":
        try:
            await event.edit(
                "📊 **الإعدادات وقاعدة البيانات الحالية:**\n\n"
                f"🎯 الوجهة: `{cfg.get('target', 'غير محدد')}`\n"
                f"🔍 جروب الاستخراج: `{cfg.get('extract_source') or 'غير محدد'}`\n"
                f"📱 حساب السحب: `{cfg.get('old_phone') or 'غير محدد'}`\n"
                f"📱 حساب الإدارة: `{cfg.get('new_phone') or 'غير محدد'}`\n"
                f"📱 رقم الحفظ المخصص: `{cfg.get('custom_save_phone') or 'غير محدد'}`\n"
                f"💬 حد الرسائل: `{cfg.get('message_limit', 0)}`\n"
                f"📁 الأعضاء المسجلين بذاكرتك: `{len(profile.get('extracted_members', {}))}` عضواً",
                buttons=[[Button.inline("🔙 القائمة الرئيسية", data="back_home")]],
                parse_mode="markdown"
            )
        except Exception: pass

# =========================================================
# 5) استقبال الرسائل وإدارة مدخلات المستخدمين
# =========================================================
@bot.on(events.NewMessage)
async def message_handler(event):
    sender = await event.get_sender()
    if not sender: return

    sender_id = sender.id
    sender_id_str = str(sender_id)
    is_adm = is_admin_user(sender)

    if not is_adm:
        users_db = load_users_db()
        if sender_id_str not in users_db or users_db[sender_id_str].get("status") != "approved":
            return

    if sender_id in auth_futures and not auth_futures[sender_id].done():
        auth_futures[sender_id].set_result(event.raw_text.strip())
        try: await event.delete()
        except Exception: pass
        return

    state_info = user_states.get(sender_id)
    if not state_info: return

    profile = load_user_profile(sender_id)
    cfg = profile["config"]
    text = event.raw_text.strip()

    try: await event.delete()
    except Exception: pass

    if state_info.get("wizard") == "manual_phone_input":
        cfg["custom_save_phone"] = text
        save_user_profile(sender_id, profile)
        user_states[sender_id].pop("wizard", None)
        await event.respond(f"✅ **تم حفظ الرقم المخصص بنجاح:** `{text}`", buttons=[[Button.inline("🔙 القائمة الرئيسية", data="back_home")]])
        return

    if "wizard" in state_info and state_info["wizard"] == "ext":
        current_step = state_info["step"]
        if current_step == 1:
            cfg["extract_source"] = text
            save_user_profile(sender_id, profile)
            await render_wizard_ext(event, sender_id, 2)
            return
        elif current_step == 2:
            if text.isdigit():
                cfg["message_limit"] = int(text)
                save_user_profile(sender_id, profile)
                await render_wizard_ext(event, sender_id, 3)
            return
        elif current_step == 3:
            cfg["old_phone"] = text
            save_user_profile(sender_id, profile)
            await render_wizard_ext(event, sender_id, 4)
            return

    if "wizard" in state_info and state_info["wizard"] == "act":
        current_step = state_info["step"]
        if current_step == 1:
            cfg["old_phone"] = text
            save_user_profile(sender_id, profile)
            await render_wizard_act(event, sender_id, 2)
            return
        elif current_step == 2:
            cfg["new_phone"] = text
            save_user_profile(sender_id, profile)
            await render_wizard_act(event, sender_id, 3)
            return
        elif current_step == 3:
            cfg["target"] = text
            save_user_profile(sender_id, profile)
            await render_wizard_act(event, sender_id, 4)
            return
        elif current_step == 4:
            cfg["message"] = text
            save_user_profile(sender_id, profile)
            await render_wizard_act(event, sender_id, 5)
            return

async def interactive_login(client, phone, account_label, progress_msg):
    session_file_path = f"{client.session.filename}"
    restore_from_github(session_file_path)

    await client.connect()
    if not await client.is_user_authorized():
        chat_id = progress_msg.chat_id

        while True:
            try:
                sent = await client.send_code_request(phone)
                phone_code_hash = sent.phone_code_hash
            except FloodWaitError as e:
                try: await progress_msg.edit(f"⏳ حظر مؤقت من تيليجرام. يجب الانتظار لمدة {e.seconds} ثانية.")
                except Exception: pass
                await asyncio.sleep(e.seconds)
                continue
            except Exception as e:
                try: await progress_msg.edit(f"❌ حدث خطأ أثناء إرسال الكود: `{str(e)}`\n🔄 جاري إعادة المحاولة...")
                except Exception: pass
                await asyncio.sleep(3)
                continue

            try: await progress_msg.edit(f"📱 **أدخل كود التفعيل لحساب ({account_label}):**\n*(اكتب الكود المكون من 5 أرقام في الشات فور وصوله)*")
            except Exception: pass

            future = asyncio.get_running_loop().create_future()
            auth_futures[chat_id] = future
            code = await future

            try:
                await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
                break
            except PhoneCodeExpiredError:
                try: await progress_msg.edit("❌ **انتهت صلاحية الكود.**\n🔄 جاري إرسال كود جديد تلقائياً...")
                except Exception: pass
                await asyncio.sleep(2)
                continue
            except PhoneCodeInvalidError:
                try: await progress_msg.edit("❌ **الكود غير صحيح.**\n🔄 جاري طلب كود جديد...")
                except Exception: pass
                await asyncio.sleep(2)
                continue
            except Exception as e:
                error_str = str(e).lower()
                if "sessionpasswordneeded" in error_str or isinstance(e, SessionPasswordNeededError):
                    while True:
                        try: await progress_msg.edit(f"🔐 **الحساب ({account_label}) محمي بكلمة مرور (التحقق بخطوتين):**\nأدخل كلمة المرور الآن:")
                        except Exception: pass

                        future = asyncio.get_running_loop().create_future()
                        auth_futures[chat_id] = future
                        password = await future

                        try:
                            await client.sign_in(password=password)
                            break
                        except Exception as pass_err:
                            try: await progress_msg.edit(f"❌ كلمة المرور غير صحيحة: `{str(pass_err)}`\n🔄 حاول مجدداً:")
                            except Exception: pass
                            await asyncio.sleep(2)
                            continue
                    break
                else:
                    try: await progress_msg.edit(f"❌ حدث خطأ: `{str(e)}`\n🔄 جاري المتابعة...")
                    except Exception: pass
                    await asyncio.sleep(3)
                    continue

    sync_to_github(session_file_path)

async def safe_edit(msg, text, buttons=None):
    while True:
        try:
            await msg.edit(text, buttons=buttons, parse_mode="markdown")
            break
        except FloodWaitError as e:
            print(f"⏳ تم رصد حظر مؤقت، جاري الانتظار لمدة {e.seconds + 2} ثانية...")
            await asyncio.sleep(e.seconds + 2)
        except Exception:
            break

async def run_extraction_and_save_task(progress_msg, user_id):
    profile = load_user_profile(user_id)
    cfg = profile["config"]
    old_phone = cfg["old_phone"].strip()
    extract_source = clean_target(cfg.get("extract_source"))
    message_limit = cfg.get("message_limit", 0)

    saved_members = profile.get("extracted_members", {})
    existing_ids = set(int(k) for k in saved_members.keys())

    session_old = "session_old_" + old_phone.replace("+", "")
    client_old = None
    newly_extracted = {}
    skipped_duplicates = 0

    try:
        await show_loading(progress_msg, "جاري الاتصال بحساب السحب وفحص الأعضاء")
        client_old = TelegramClient(session_old, API_ID, API_HASH)
        await interactive_login(client_old, old_phone, "السحب", progress_msg)

        stop_btn = [[Button.inline("🛑 إيقاف والاستخراج بالنتيجة الحالية", data="stop_ext_prompt")]]
        await safe_edit(progress_msg, "🔄 جاري بدء الاستخراج وتصفية المكرر تلقائياً...", buttons=stop_btn)

        last_update_time = time.time()
        count = 0

        if message_limit == 0:
            async for user in client_old.iter_participants(extract_source):
                if isinstance(user, User) and not getattr(user, "bot", False):
                    count += 1
                    if user.id in existing_ids:
                        skipped_duplicates += 1
                        continue

                    newly_extracted[str(user.id)] = {
                        "id": user.id,
                        "username": user.username or "",
                        "first_name": user.first_name or "",
                        "phone": getattr(user, "phone", "") or ""
                    }

                    if time.time() - last_update_time >= 3.0:
                        last_update_time = time.time()
                        await safe_edit(
                            progress_msg,
                            f"🔄 **جاري استخراج الأعضاء والفلترة...**\n"
                            f"• تم جلب جدد: `({len(newly_extracted)})` عضواً\n"
                            f"• تم استبعاد مكررين: `({skipped_duplicates})` عضواً",
                            buttons=stop_btn,
                        )
        else:
            async for msg in client_old.iter_messages(extract_source, limit=message_limit):
                count += 1
                if msg.sender and isinstance(msg.sender, User) and not getattr(msg.sender, "bot", False):
                    user = msg.sender
                    if user.id in existing_ids:
                        skipped_duplicates += 1
                        continue

                    newly_extracted[str(user.id)] = {
                        "id": user.id,
                        "username": user.username or "",
                        "first_name": user.first_name or "",
                        "phone": getattr(user, "phone", "") or ""
                    }

                if time.time() - last_update_time >= 3.0 or count == message_limit or count % 500 == 0:
                    last_update_time = time.time()
                    await safe_edit(
                        progress_msg,
                        f"🔄 **جاري فحص الرسائل واستخراج المرسليين...**\n"
                        f"• تم فحص: `({count} / {message_limit})` رسالة\n"
                        f"• أعضاء جدد: `({len(newly_extracted)})`\n"
                        f"• مكررين تم استبعادهم: `({skipped_duplicates})`",
                        buttons=stop_btn,
                    )

    except asyncio.CancelledError:
        print("⚠️ تم قطع اتصال وإلغاء عملية الاستخراج بناءً على طلب المستخدم.")
    except Exception as e:
        print(f"❌ خطأ أثناء الاستخراج: {e}")
    finally:
        if client_old:
            try: await client_old.disconnect()
            except Exception: pass
        active_tasks.pop(progress_msg.chat_id, None)

    # حفظ الأعضاء الجدد في ذاكرة المستخدم الدائمة
    if newly_extracted:
        saved_members.update(newly_extracted)
        profile["extracted_members"] = saved_members
        save_user_profile(user_id, profile)

    total_in_db = len(saved_members)
    if not newly_extracted and skipped_duplicates == 0:
        await safe_edit(
            progress_msg,
            "❌ لم يتم العثور على أي أعضاء جدد في الجروب المحدد!",
            buttons=[[Button.inline("🔙 القائمة الرئيسية", data="back_home")]],
        )
        return

    buttons = [[Button.inline(f"📱 حفظ الكل في حساب السحب ({old_phone})", data="save_contacts_old")]]
    new_phone = cfg.get("new_phone", "").strip()
    if new_phone:
        buttons.append([Button.inline(f"📱 حفظ الكل في حساب الإدارة ({new_phone})", data="save_contacts_new")])
    custom_phone = cfg.get("custom_save_phone", "").strip()
    if custom_phone:
        buttons.append([Button.inline(f"📱 حفظ الكل في الرقم المخصص ({custom_phone})", data="save_contacts_custom")])
    buttons.append([Button.inline("❌ تخطي الحفظ الآن", data="skip_saving")])

    await safe_edit(
        progress_msg,
        f"✅ **تم الانتهاء وحفظ البيانات بذاكرتك!**\n\n"
        f"📊 **التقرير:**\n"
        f"• أعضاء جدد تم إضافتهم للذاكرة: `{len(newly_extracted)}`\n"
        f"• مكررين تم استبعادهم تلقائياً: `{skipped_duplicates}`\n"
        f"• إجمالي الأعضاء بذاكرتك الآن: `{total_in_db}`\n\n"
        f"📱 **هل تريد إضافة هذه الأرقام كجهات اتصال في أحد حساباتك؟**",
        buttons=buttons,
    )

async def run_automation_task(progress_msg, user_id):
    profile = load_user_profile(user_id)
    cfg = profile["config"]
    old_phone = cfg["old_phone"].strip()
    new_phone = cfg["new_phone"].strip()
    target_group = clean_target(cfg.get("target"))
    invitation_message = cfg["message"]

    session_old = "session_old_" + old_phone.replace("+", "")
    session_new = "session_new_" + new_phone.replace("+", "")
    client_old = None
    client_new = None

    try:
        await show_loading(progress_msg, "جاري الاتصال بحساب السحب وقراءة الأرقام")
        client_old = TelegramClient(session_old, API_ID, API_HASH)
        await interactive_login(client_old, old_phone, "السحب", progress_msg)

        contacts_result = await client_old(GetContactsRequest(hash=0))
        contacts_list = [u for u in contacts_result.users if isinstance(u, User) and not getattr(u, "bot", False)]
        await client_old.disconnect()

        if not contacts_list:
            await progress_msg.edit("❌ لا توجد جهات اتصال مسحوبة في الحساب القديم!")
            return

        await show_loading(progress_msg, "جاري الانتقال لحساب الإدارة وبدء الإضافة")
        client_new = TelegramClient(session_new, API_ID, API_HASH)
        await interactive_login(client_new, new_phone, "الإدارة", progress_msg)

        try:
            entity = await client_new.get_entity(target_group)
            is_broadcast_channel = isinstance(entity, Channel) and entity.broadcast
        except Exception as e:
            await progress_msg.edit("❌ تعذر العثور على الوجهة المستهدفة: " + str(e))
            await client_new.disconnect()
            return

        existing_members_ids = set()
        try:
            async for participant in client_new.iter_participants(target_group):
                if isinstance(participant, User):
                    existing_members_ids.add(participant.id)
        except Exception: pass

        sent_history_set = set(profile.get("history_sent", []))
        users_to_process = [u for u in contacts_list if u.id not in existing_members_ids and u.id not in sent_history_set]

        if not users_to_process:
            await progress_msg.edit("🎉 جميع المستخدمين تمت معالجتهم مسبقاً أو موجودون بالوجهة!")
            await client_new.disconnect()
            return

        added_count = 0
        msg_sent_count = 0
        failed_count = 0
        total_users = len(users_to_process)

        stop_btn = [[Button.inline("🛑 إيقاف العملية الحالية", data="stop_act")]]

        for idx, u in enumerate(users_to_process, 1):
            uid = u.id
            try:
                if is_broadcast_channel:
                    await client_new.send_message(uid, invitation_message)
                    msg_sent_count += 1
                else:
                    try:
                        await client_new(InviteToChannelRequest(target_group, [uid]))
                        added_count += 1
                    except Exception:
                        await client_new.send_message(uid, invitation_message)
                        msg_sent_count += 1

                sent_history_set.add(uid)
                profile["history_sent"] = list(sent_history_set)
                save_user_profile(user_id, profile)

                if idx % 10 == 0 or idx == total_users:
                    try:
                        await progress_msg.edit(
                            f"🚀 **جارٍ التنفيذ...** ({idx}/{total_users})\n• رسائل: `{msg_sent_count}`\n• إضافات مباشرة: `{added_count}`",
                            buttons=stop_btn,
                            parse_mode="markdown"
                        )
                    except Exception: pass

                await asyncio.sleep(random.uniform(10, 20))

            except FloodWaitError as e:
                await asyncio.sleep(e.seconds + 5)
            except Exception:
                failed_count += 1
                sent_history_set.add(uid)
                profile["history_sent"] = list(sent_history_set)
                save_user_profile(user_id, profile)

        if client_new: await client_new.disconnect()

        await progress_msg.edit(
            f"🎉 **انتهت العملية بنجاح!**\n\n📊 **التقرير النهائي:**\n• الرسائل المرسلة: `{msg_sent_count}`\n• الإضافات المباشرة: `{added_count}`\n• الأخطاء: `{failed_count}`",
            parse_mode="markdown"
        )

    except asyncio.CancelledError:
        if client_new:
            try: await client_new.disconnect()
            except Exception: pass
        await progress_msg.edit("⚠️ **تم إيقاف عملية الإرسال والإضافة بناءً على طلبك!**", parse_mode="markdown")
    except Exception as e:
        if client_new:
            try: await client_new.disconnect()
            except Exception: pass
        await progress_msg.edit("❌ حدث خطأ أثناء التنفيذ: `" + str(e) + "`")
    finally:
        active_tasks.pop(progress_msg.chat_id, None)

# =========================================================
# 6) حلقة التشغيل الرئيسية
# =========================================================
async def main_loop():
    while True:
        try:
            print("🤖 جاري تشغيل البوت ومراقبة حالة الاتصال...")
            if not bot.is_connected():
                await bot.connect()

            if not await bot.is_user_authorized():
                await bot.start(bot_token=BOT_TOKEN)

            await bot.run_until_disconnected()
        except KeyboardInterrupt:
            print("⚠️ تم إيقاف البوت يدوياً.")
            break
        except Exception as e:
            print(f"❌ حدث خطأ طارئ أدى لتوقف البوت: {e}")
            print("🔄 جاري إعادة تشغيل البوت تلقائياً خلال 5 ثوانٍ...")
            await asyncio.sleep(5)
            try:
                if bot.is_connected():
                    await bot.disconnect()
            except Exception: pass

if __name__ == "__main__":
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        print("⚠️ تم إيقاف البوت نهائياً.")
