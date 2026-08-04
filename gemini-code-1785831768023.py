import asyncio
import json
import os
import random
import time
from telethon import Button, TelegramClient, events
from telethon.errors import (
    FloodWaitError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
)
from telethon.tl.functions.channels import InviteToChannelRequest
from telethon.tl.functions.contacts import AddContactRequest, GetContactsRequest
from telethon.tl.types import Channel, User

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
    "extract_source": "",
    "message_limit": 0,
}

extracted_cache = {}
active_tasks = {}


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
  with open(CONFIG_FILE, "w", encoding="utf-8") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=4)


def load_users():
  if os.path.exists(USERS_FILE):
    try:
      with open(USERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)
    except Exception:
      pass
  return {}


def save_users(users):
  with open(USERS_FILE, "w", encoding="utf-8") as f:
    json.dump(users, f, ensure_ascii=False, indent=4)


user_states = {}
auth_futures = {}

print("🔄 جاري تهيئة نظام التشغيل والمكونات...")
bot = TelegramClient("bot_session_main", API_ID, API_HASH)


async def show_loading(msg, text):
  for i in range(4):
    dots = "." * ((i % 3) + 1)
    try:
      await msg.edit(f"🔄 {text}{dots}")
    except Exception:
      pass
    await asyncio.sleep(0.4)


async def send_or_update_wizard(event, sender_id, text, buttons):
  state = user_states.get(sender_id, {})
  last_msg_id = state.get("last_bot_msg_id")
  chat_id = event.chat_id if hasattr(event, "chat_id") else event.chat_id

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
      if hasattr(event, "edit") and not isinstance(
          event, events.NewMessage.Event
      ):
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
    pending_count = sum(
        1 for u in users.values() if u.get("status") == "pending"
    )
    buttons.append([
        Button.inline(
            f"👥 إدارة طلبات المستخدمين ({pending_count} طلب جديد)",
            data="admin_requests_panel",
        )
    ])

  buttons.extend([
      [
          Button.inline(
              "📥 1. معالج استخراج وحفظ الأرقام (خطوة بخطوة)",
              data="menu_extract_save",
          )
      ],
      [
          Button.inline(
              "🚀 2. معالج الإرسال والإضافة التلقائية (خطوة بخطوة)",
              data="menu_actions_wizard",
          )
      ],
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
        " الآن يوزر أو رابط الجروب المراد الاستخراج منه في الشات.\n\n🔗 القيمة"
        f" الحالية: `{cfg.get('extract_source') or 'غير محدد'}`"
    )
    buttons = [
        [Button.inline("التالي ➡️", data="wiz_ext_next_2")],
        [Button.inline("🔙 إلغاء والقائمة الرئيسية", data="back_home")],
    ]
  elif step == 2:
    text = (
        "🧙‍♂️ **معالج الاستخراج (الخطوة 2 من 3)**\n\n📊 **حد الرسائل:**\nأرسل عدد"
        " الرسائل المراد فحصها (اكتب `0` لاستخراج الأعضاء مباشرة بلا حدود)."
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
        "🧙‍♂️ **معالج الاستخراج (الخطوة 3 من 3)**\n\n📱 **حساب السحب:**\nأرسل رقم"
        " هاتف حساب السحب (مع مفتاح الدولة).\n\n🔗 القيمة الحالية:"
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
        f" `{cfg.get('message_limit', 0)}`\n• حساب السحب:"
        f" `{cfg.get('old_phone', 'غير محدد')}`\n\nهل أنت متأكد من البدء في"
        " تنفيذ الاستخراج؟"
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
        "🚀 **معالج الإرسال والإضافة (الخطوة 1 من 4)**\n\n📱 **حساب السحب:**\nأرسل"
        " رقم هاتف الحساب القديم (المسحوب منه جهات الاتصال).\n\n🔗 القيمة"
        f" الحالية: `{cfg.get('old_phone') or 'غير محدد'}`"
    )
    buttons = [
        [Button.inline("التالي ➡️", data="wiz_act_next_2")],
        [Button.inline("🔙 إلغاء والقائمة الرئيسية", data="back_home")],
    ]
  elif step == 2:
    text = (
        "🚀 **معالج الإرسال والإضافة (الخطوة 2 من 4)**\n\n📱 **حساب الإدارة:**\nأرسل"
        " رقم هاتف الحساب الجديد (المسؤول عن الإرسال والإضافة).\n\n🔗 القيمة"
        f" الحالية: `{cfg.get('new_phone') or 'غير محدد'}`"
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
        "🚀 **معالج الإرسال والإضافة (الخطوة 3 من 4)**\n\n🎯 **الوجهة المستهدفة:**\nأرسل"
        " يوزر أو رابط القناة/الجروب المستهدف للإضافة أو إرسال الرسائل.\n\n🔗"
        f" القيمة الحالية: `{cfg.get('target', 'غير محدد')}`"
    )
    buttons = [
        [
            Button.inline("⬅️ السابق", data="wiz_act_prev_2"),
            Button.inline("التالي ➡️", data="wiz_act_next_4"),
        ],
        [Button.inline("🔙 إلغاء والقائمة الرئيسية", data="back_home")],
    ]
  elif step == 4:
    text = (
        "🚀 **معالج الإرسال والإضافة (الخطوة 4 من 4)**\n\n✏️ **رسالة الدعوة:**\nأرسل"
        " نص رسالة الدعوة الجديد الذي سيتم إرساله للمستخدمين.\n\n🔗 النص"
        f" الحالي:\n`{cfg.get('message', 'غير محدد')}`"
    )
    buttons = [
        [
            Button.inline("⬅️ السابق", data="wiz_act_prev_3"),
            Button.inline("🔍 مراجعة وتأكيد التنفيذ 🚀", data="wiz_act_next_5"),
        ],
        [Button.inline("🔙 إلغاء والقائمة الرئيسية", data="back_home")],
    ]
  elif step == 5:
    text = (
        "📋 **مراجعة بيانات الإرسال والإضافة النهائية:**\n\n• حساب السحب:"
        f" `{cfg.get('old_phone', 'غير محدد')}`\n• حساب الإدارة:"
        f" `{cfg.get('new_phone', 'غير محدد')}`\n• الوجهة المستهدفة:"
        f" `{cfg.get('target', 'غير محدد')}`\n• رسالة الدعوة:\n`{cfg.get('message', 'غير محدد')}`\n\nهل أنت متأكد من بدء عملية الإرسال والإضافة التلقائية؟"
    )
    buttons = [
        [Button.inline("⬅️ تعديل البيانات", data="wiz_act_prev_4")],
        [Button.inline("▶️ تأكيد وبدء التنفيذ الفوري", data="add_run")],
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
  is_adm = (
      sender.username and sender.username.lower() == ADMIN_USERNAME.lower()
  )

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

    try:
      await bot.send_message(
          f"@{ADMIN_USERNAME}",
          f"🔔 **طلب استخدام جديد للبوت!**\n\n👤 الاسم: `{sender.first_name}`\n🔗"
          f" اليوزر: `@{sender.username or 'لا يوجد'}`\n🆔 الآيدي:"
          f" `{sender.id}`",
          parse_mode="markdown",
      )
    except Exception:
      pass

    await event.respond(
        "⏳ **تم إرسال طلبك بنجاح إلى مالك البوت (@m7mallah).**\nيرجى الانتظار"
        " حتى يتم قبول طلبك.",
        parse_mode="markdown",
    )
    return

  status = users[sender_id].get("status")
  if status == "pending":
    await event.respond(
        "⏳ **طلبك قيد الانتظار...**\nلم يتم الموافقة عليه بعد.",
        parse_mode="markdown",
    )
  elif status == "rejected":
    await event.respond(
        "❌ **عذراً، تم رفض طلبك لاستخدام البوت.**", parse_mode="markdown"
    )
  elif status == "approved":
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
  is_adm = (
      sender.username and sender.username.lower() == ADMIN_USERNAME.lower()
  )

  if not is_adm:
    users = load_users()
    if sender_id not in users or users[sender_id].get("status") != "approved":
      await event.answer(
          "⛔ عذراً، حسابك غير معتمد أو بانتظار الموافقة!", alert=True
      )
      return

  data = event.data.decode("utf-8")
  cfg = load_config()

  if data == "stop_ext_prompt":
    confirm_buttons = [
        [
            Button.inline("✅ نعم، أوقف الآن", data="stop_ext_confirmed"),
            Button.inline("❌ إلغاء، تابع الاستخراج", data="stop_ext_cancel"),
        ]
    ]
    try:
      await event.edit(
          "⚠️ **هل أنت متأكد من رغبتك في إيقاف الاستخراج فوراً والاحتفاظ"
          " بالنتائج الحالية؟**",
          buttons=confirm_buttons,
          parse_mode="markdown",
      )
    except Exception:
      pass
    return

  if data == "stop_ext_confirmed":
    chat_id = event.chat_id
    if chat_id in active_tasks:
      active_tasks[chat_id].cancel()

    try:
      await event.edit(
          "⏳ **تم إيقاف الاستخراج فوراً!**\nجاري تجهيز النتائج وحفظها...",
          buttons=None,
          parse_mode="markdown",
      )
    except Exception:
      pass
    await event.answer("⚠️ تم إيقاف الاستخراج بنجاح!", alert=True)
    return

  if data == "stop_ext_cancel":
    stop_btn = [
        [
            Button.inline(
                "🛑 إيقاف والاستخراج بالنتيجة الحالية", data="stop_ext_prompt"
            )
        ]
    ]
    try:
      await event.edit(
          "🔄 جاري متابعة الاستخراج بناءً على طلبك...",
          buttons=stop_btn,
          parse_mode="markdown",
      )
    except Exception:
      pass
    return

  if data == "stop_act":
    chat_id = event.chat_id
    if chat_id in active_tasks:
      active_tasks[chat_id].cancel()
    await event.answer("⚠️ يتم إيقاف العملية الحالية...", alert=True)
    return

  if sender_int_id not in user_states:
    user_states[sender_int_id] = {}
  user_states[sender_int_id]["last_bot_msg_id"] = event.message_id

  if is_adm:
    if data == "admin_requests_panel":
      users = load_users()
      buttons = []
      for uid, uinfo in users.items():
        status_emoji = (
            "⏳ معلق"
            if uinfo.get("status") == "pending"
            else ("✅ مقبول" if uinfo.get("status") == "approved" else "❌ مرفوض")
        )
        btn_text = f"{uinfo['name']} (@{uinfo['username']}) - {status_emoji}"
        buttons.append([Button.inline(btn_text, data=f"manage_u_{uid}")])
      buttons.append([Button.inline("🔙 القائمة الرئيسية", data="back_home")])
      try:
        await event.edit(
            "👥 **إدارة المستخدمين:**\nاختر مستخدماً لتغيير حالته أو إنهاء"
            " جلسته:",
            buttons=buttons,
            parse_mode="markdown",
        )
      except Exception:
        await event.respond(
            "👥 **إدارة المستخدمين:**\nاختر مستخدماً لتغيير حالته أو إنهاء"
            " جلسته:",
            buttons=buttons,
            parse_mode="markdown",
        )
      return

    elif data.startswith("manage_u_"):
      target_uid = data.split("_")[2]
      users = load_users()
      if target_uid in users:
        uinfo = users[target_uid]
        buttons = [
            [
                Button.inline("✅ موافقة", data=f"approve_{target_uid}"),
                Button.inline("❌ رفض", data=f"reject_{target_uid}"),
            ],
            [
                Button.inline(
                    "🚫 إنهاء الجلسة / سحب الصلاحية",
                    data=f"terminate_{target_uid}",
                )
            ],
            [Button.inline("🔙 رجوع للطلبات", data="admin_requests_panel")],
        ]
        try:
          await event.edit(
              f"👤 **المستخدم:** {uinfo['name']}\n- اليوزر:"
              f" `@{uinfo['username']}`\n- الحالة الحالية:"
              f" `{uinfo['status']}`",
              buttons=buttons,
              parse_mode="markdown",
          )
        except Exception:
          pass
      return

    elif data.startswith("approve_") or data.startswith(
        "reject_"
    ) or data.startswith("terminate_"):
      parts = data.split("_")
      action = parts[0]
      target_uid = parts[1]
      users = load_users()
      if target_uid in users:
        if action == "approve":
          users[target_uid]["status"] = "approved"
          try:
            await bot.send_message(
                int(target_uid),
                "🎉 **مبارك! تم قبول طلبك لاستخدام البوت بنجاح.**\nيمكنك الآن"
                " إرسال `/start` للبدء.",
                parse_mode="markdown",
            )
          except Exception:
            pass
          await event.answer("✅ تم قبول المستخدم وإرسال إشعار له!", alert=True)
        elif action == "reject":
          users[target_uid]["status"] = "rejected"
          await event.answer("❌ تم رفض المستخدم!", alert=True)
        elif action == "terminate":
          users[target_uid]["status"] = "pending"
          await event.answer(
              "🚫 تم إنهاء جلسة المستخدم وإرجاعه لقائمة الانتظار!", alert=True
          )
        save_users(users)
        event.data = b"admin_requests_panel"
        await cb_handler(event)
      return

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
      await event.answer(
          "⚠️ يرجى إدخال جروب الاستخراج ورقم حساب السحب أولاً!", alert=True
      )
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
  elif data == "wiz_act_prev_1":
    await render_wizard_act(event, sender_int_id, 1)
  elif data == "wiz_act_prev_2":
    await render_wizard_act(event, sender_int_id, 2)
  elif data == "wiz_act_prev_3":
    await render_wizard_act(event, sender_int_id, 3)
  elif data == "wiz_act_prev_4":
    await render_wizard_act(event, sender_int_id, 4)

  elif data == "ext_run_save":
    if not cfg.get("extract_source") or not cfg.get("old_phone"):
      await event.answer(
          "⚠️ يرجى تحديد جروب الاستخراج ورقم حساب السحب أولاً!", alert=True
      )
      return
    user_states.pop(sender_int_id, None)
    progress_msg = await event.respond("⏳ جاري التحضير واستخراج الأعضاء...")
    task = asyncio.create_task(run_extraction_and_save_task(progress_msg, cfg))
    active_tasks[progress_msg.chat_id] = task

  elif data == "save_contacts_old" or data == "save_contacts_new":
    users_list = extracted_cache.get(event.chat_id)
    if not users_list:
      await event.answer(
          "⚠️ انتهت صلاحية الجلسة المؤقتة، يرجى إعادة الاستخراج.", alert=True
      )
      return

    phone = (
        cfg.get("old_phone")
        if data == "save_contacts_old"
        else cfg.get("new_phone")
    )
    account_label = "السحب" if data == "save_contacts_old" else "الإدارة"
    session_name = (
        "session_old_"
        if data == "save_contacts_old"
        else "session_new_"
    ) + phone.replace("+", "")

    try:
      await event.edit(
          f"🔄 جاري الاتصال بحساب ({account_label}) لحفظ الأرقام..."
      )
    except Exception:
      pass
    msg_obj = await event.get_message()
    try:
      client = TelegramClient(session_name, API_ID, API_HASH)
      await interactive_login(client, phone, account_label, msg_obj)

      added_contacts = 0
      for idx, u in enumerate(users_list, 1):
        if getattr(u, "phone", None):
          try:
            await client(
                AddContactRequest(
                    id=u.id,
                    first_name=u.first_name or "مستخدم",
                    last_name=u.last_name or "",
                    phone=u.phone,
                )
            )
            added_contacts += 1
          except FloodWaitError as e:
            await asyncio.sleep(e.seconds)
          except Exception:
            pass
        if idx % 50 == 0 or idx == len(users_list):
          try:
            await event.edit(
                f"📇 جاري الحفظ في جهات اتصال ({account_label})... ({idx}/{len(users_list)})"
            )
          except FloodWaitError as e:
            await asyncio.sleep(e.seconds)
          except Exception:
            pass

      await client.disconnect()
      extracted_cache.pop(event.chat_id, None)
      await event.edit(
          f"✅ **تم حفظ الأرقام بنجاح في حساب ({account_label})!**\n• تمت إضافة"
          f" **{added_contacts}** رقم جديد إلى جهات الاتصال.",
          buttons=[[Button.inline("🔙 القائمة الرئيسية", data="back_home")]],
          parse_mode="markdown",
      )
    except Exception as e:
      await event.edit(
          f"❌ حدث خطأ أثناء الحفظ: `{str(e)}`",
          buttons=[[Button.inline("🔙 القائمة الرئيسية", data="back_home")]],
      )

  elif data == "skip_saving":
    extracted_cache.pop(event.chat_id, None)
    await event.edit(
        "✅ **تم تخطي حفظ الأرقام بنجاح.**",
        buttons=[[Button.inline("🔙 القائمة الرئيسية", data="back_home")]],
        parse_mode="markdown",
    )

  elif data == "add_run":
    if not cfg.get("old_phone") or not cfg.get("new_phone"):
      await event.answer("⚠️ يرجى تعيين أرقام الحسابات أولاً!", alert=True)
      return
    user_states.pop(sender_int_id, None)
    progress_msg = await event.respond(
        "🚀 جاري التحضير لعمليات الإرسال والإضافة..."
    )
    task = asyncio.create_task(run_automation_task(progress_msg, cfg))
    active_tasks[progress_msg.chat_id] = task

  elif data == "show_settings":
    try:
      await event.edit(
          "📊 **الإعدادات الحالية:**\n\n🎯 الوجهة: `"
          + cfg["target"]
          + "`\n🔍 جروب الاستخراج: `"
          + (cfg.get("extract_source") or "غير محدد")
          + "`\n📱 حساب السحب: `"
          + (cfg.get("old_phone") or "غير محدد")
          + "`\n📱 حساب الإدارة: `"
          + (cfg.get("new_phone") or "غير محدد")
          + "`\n💬 حد الرسائل: `"
          + str(cfg.get("message_limit", 0))
          + "`",
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
  sender_id_str = str(sender_id)
  is_adm = (
      sender.username and sender.username.lower() == ADMIN_USERNAME.lower()
  )

  if not is_adm:
    users = load_users()
    if (
        sender_id_str not in users
        or users[sender_id_str].get("status") != "approved"
    ):
      return

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

  if "wizard" in state_info and state_info["wizard"] == "ext":
    current_step = state_info["step"]
    if current_step == 1:
      cfg["extract_source"] = text
      save_config(cfg)
      await render_wizard_ext(event, sender_id, 2)
      return
    elif current_step == 2:
      if text.isdigit():
        cfg["message_limit"] = int(text)
        save_config(cfg)
        await render_wizard_ext(event, sender_id, 3)
      return
    elif current_step == 3:
      cfg["old_phone"] = text
      save_config(cfg)
      await render_wizard_ext(event, sender_id, 4)
      return

  if "wizard" in state_info and state_info["wizard"] == "act":
    current_step = state_info["step"]
    if current_step == 1:
      cfg["old_phone"] = text
      save_config(cfg)
      await render_wizard_act(event, sender_id, 2)
      return
    elif current_step == 2:
      cfg["new_phone"] = text
      save_config(cfg)
      await render_wizard_act(event, sender_id, 3)
      return
    elif current_step == 3:
      cfg["target"] = text
      save_config(cfg)
      await render_wizard_act(event, sender_id, 4)
      return
    elif current_step == 4:
      cfg["message"] = text
      save_config(cfg)
      await render_wizard_act(event, sender_id, 5)
      return


async def interactive_login(client, phone, account_label, progress_msg):
  await client.connect()
  if not await client.is_user_authorized():
    chat_id = progress_msg.chat_id

    while True:
      try:
        sent = await client.send_code_request(phone)
        phone_code_hash = sent.phone_code_hash
      except FloodWaitError as e:
        try:
          await progress_msg.edit(
              f"⏳ حظر مؤقت من تيليجرام. يجب الانتظار لمدة {e.seconds} ثانية."
          )
        except Exception:
          pass
        await asyncio.sleep(e.seconds)
        continue
      except Exception as e:
        try:
          await progress_msg.edit(
              f"❌ حدث خطأ أثناء إرسال الكود: `{str(e)}`\n🔄 جاري إعادة المحاولة..."
          )
        except Exception:
          pass
        await asyncio.sleep(3)
        continue

      try:
        await progress_msg.edit(
            f"📱 **أدخل كود التفعيل لحساب ({account_label}):**\n*(تم إرسال كود"
            " جديد، يرجى كتابته في الشات بسرعة فور وصوله)*"
        )
      except Exception:
        pass

      future = asyncio.get_running_loop().create_future()
      auth_futures[chat_id] = future
      code = await future

      try:
        await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
        break
      except PhoneCodeExpiredError:
        try:
          await progress_msg.edit(
              "❌ **انتهت صلاحية الكود (Code Expired).**\n🔄 جاري إرسال كود"
              " جديد تلقائياً، استعد لإدخاله..."
          )
        except Exception:
          pass
        await asyncio.sleep(2)
        continue
      except PhoneCodeInvalidError:
        try:
          await progress_msg.edit(
              "❌ **الكود غير صحيح (Invalid Code).**\n🔄 جاري إرسال كود جديد"
              " لتجربة أخرى..."
          )
        except Exception:
          pass
        await asyncio.sleep(2)
        continue
      except Exception as e:
        error_str = str(e).lower()
        if (
            "sessionpasswordneeded" in error_str
            or isinstance(e, SessionPasswordNeededError)
        ):
          while True:
            try:
              await progress_msg.edit(
                  f"🔐 **الحساب ({account_label}) محمي بكلمة مرور (التحقق"
                  " بخطوتين):**\nأدخل كلمة المرور الآن:"
              )
            except Exception:
              pass

            future = asyncio.get_running_loop().create_future()
            auth_futures[chat_id] = future
            password = await future

            try:
              await client.sign_in(password=password)
              break
            except Exception as pass_err:
              try:
                await progress_msg.edit(
                    f"❌ كلمة المرور غير صحيحة: `{str(pass_err)}`\n🔄 حاول"
                    " إدخال كلمة المرور مرة أخرى:"
                )
              except Exception:
                pass
              await asyncio.sleep(2)
              continue
          break
        else:
          try:
            await progress_msg.edit(
                f"❌ حدث خطأ غير متوقع: `{str(e)}`\n🔄 جاري إعادة المحاولة..."
            )
          except Exception:
            pass
          await asyncio.sleep(3)
          continue


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


async def run_extraction_and_save_task(progress_msg, cfg):
  old_phone = cfg["old_phone"].strip()
  extract_source = clean_target(cfg.get("extract_source"))
  message_limit = cfg.get("message_limit", 0)
  session_old = "session_old_" + old_phone.replace("+", "")
  client_old = None
  users_map = {}

  try:
    await show_loading(
        progress_msg, "جاري الاتصال بحساب السحب وجلب الأعضاء"
    )
    client_old = TelegramClient(session_old, API_ID, API_HASH)
    await interactive_login(client_old, old_phone, "السحب", progress_msg)

    stop_btn = [
        [
            Button.inline(
                "🛑 إيقاف والاستخراج بالنتيجة الحالية", data="stop_ext_prompt"
            )
        ]
    ]
    await safe_edit(
        progress_msg,
        "🔄 جاري بدء الاستخراج... يرجى الانتظار.",
        buttons=stop_btn,
    )

    last_update_time = time.time()
    count = 0

    if message_limit == 0:
      async for user in client_old.iter_participants(extract_source):
        if isinstance(user, User) and not getattr(user, "bot", False):
          users_map[user.id] = user
          count += 1

          if time.time() - last_update_time >= 3.0:
            last_update_time = time.time()
            await safe_edit(
                progress_msg,
                f"🔄 **جاري استخراج الأعضاء مباشرة...**\n• تم جلب:"
                f" `({len(users_map)})` عضواً فريداً حتى الآن.",
                buttons=stop_btn,
            )
    else:
      async for msg in client_old.iter_messages(
          extract_source, limit=message_limit
      ):
        count += 1
        if (
            msg.sender
            and isinstance(msg.sender, User)
            and not getattr(msg.sender, "bot", False)
        ):
          users_map[msg.sender.id] = msg.sender

        if (
            time.time() - last_update_time >= 3.0
            or count == message_limit
            or count % 500 == 0
        ):
          last_update_time = time.time()
          await safe_edit(
              progress_msg,
              f"🔄 **جاري فحص الرسائل واستخراج المرسلين...**\n• تم فحص:"
              f" `({count} / {message_limit})` رسالة\n• تم جلب:"
              f" `({len(users_map)})` مرسلاً فريداً حتى الآن.",
              buttons=stop_btn,
          )

  except asyncio.CancelledError:
    print("⚠️ تم قطع اتصال وإلغاء عملية الاستخراج فوراً بناءً على طلب المستخدم.")
  except Exception as e:
    print(f"❌ خطأ أثناء الاستخراج: {e}")
  finally:
    if client_old:
      try:
        await client_old.disconnect()
      except Exception:
        pass
    active_tasks.pop(progress_msg.chat_id, None)

  users_list = list(users_map.values())
  if not users_list:
    await safe_edit(
        progress_msg,
        "❌ لم يتم العثور على أي أعضاء أو تم الإيقاف مبكراً جداً دون نتائج!",
        buttons=[[Button.inline("🔙 القائمة الرئيسية", data="back_home")]],
    )
    return

  extracted_cache[progress_msg.chat_id] = users_list

  buttons = [
      [
          Button.inline(
              f"📱 حفظ في حساب السحب ({old_phone})", data="save_contacts_old"
          )
      ]
  ]
  new_phone = cfg.get("new_phone", "").strip()
  if new_phone:
    buttons.append([
        Button.inline(
            f"📱 حفظ في حساب الإدارة ({new_phone})", data="save_contacts_new"
        )
    ])
  buttons.append([Button.inline("❌ تخطي الحفظ", data="skip_saving")])

  await safe_edit(
      progress_msg,
      f"✅ **تم استخراج ({len(users_list)}) عضو/مرسل بنجاح!**\n\n📱 **أين تريد"
      " حفظ هذه الأرقام؟ اختر الحساب المناسب:**",
      buttons=buttons,
  )


async def run_automation_task(progress_msg, cfg):
  old_phone = cfg["old_phone"].strip()
  new_phone = cfg["new_phone"].strip()
  target_group = clean_target(cfg.get("target"))
  invitation_message = cfg["message"]

  session_old = "session_old_" + old_phone.replace("+", "")
  session_new = "session_new_" + new_phone.replace("+", "")
  client_old = None
  client_new = None

  try:
    await show_loading(
        progress_msg, "جاري الاتصال بحساب السحب وقراءة الأرقام"
    )
    client_old = TelegramClient(session_old, API_ID, API_HASH)
    await interactive_login(client_old, old_phone, "السحب", progress_msg)

    contacts_result = await client_old(GetContactsRequest(hash=0))
    contacts_list = [
        user
        for user in contacts_result.users
        if isinstance(user, User) and not getattr(user, "bot", False)
    ]
    await client_old.disconnect()

    if not contacts_list:
      await progress_msg.edit("❌ لا توجد جهات اتصال مسحوبة في الحساب القديم!")
      return

    await show_loading(progress_msg, "جاري التبديل والانتقال لحساب الإدارة")
    client_new = TelegramClient(session_new, API_ID, API_HASH)
    await interactive_login(client_new, new_phone, "الإدارة", progress_msg)

    try:
      entity = await client_new.get_entity(target_group)
      is_broadcast_channel = isinstance(entity, Channel) and entity.broadcast
    except Exception as e:
      await progress_msg.edit("❌ تعذر العثور على الوجهة: " + str(e))
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
      with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        for line in f:
          clean_id = line.strip()
          if clean_id.isdigit():
            sent_users_set.add(int(clean_id))

    users_to_process = [
        u
        for u in contacts_list
        if u.id not in existing_members_ids and u.id not in sent_users_set
    ]

    if not users_to_process:
      await progress_msg.edit(
          "🎉 جميع المستخدمين تمت معالجتهم أو موجودون مسبقاً في الوجهة!"
      )
      await client_new.disconnect()
      return

    added_count = 0
    msg_sent_count = 0
    failed_count = 0
    total_users = len(users_to_process)

    stop_btn = [[Button.inline("🛑 إيقاف العملية الحالية", data="stop_act")]]

    for idx, user in enumerate(users_to_process, 1):
      user_id = user.id
      try:
        if is_broadcast_channel:
          await client_new.send_message(user_id, invitation_message)
          msg_sent_count += 1
        else:
          try:
            await client_new(InviteToChannelRequest(target_group, [user_id]))
            added_count += 1
          except Exception:
            await client_new.send_message(user_id, invitation_message)
            msg_sent_count += 1

        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
          f.write(str(user_id) + "\n")

        if idx % 10 == 0 or idx == total_users:
          try:
            await progress_msg.edit(
                "🚀 **جارٍ التنفيذ...** ("
                + str(idx)
                + "/"
                + str(total_users)
                + ")\n• رسائل: "
                + str(msg_sent_count)
                + "\n• إضافات: "
                + str(added_count),
                buttons=stop_btn,
                parse_mode="markdown",
            )
          except Exception:
            pass

        await asyncio.sleep(random.uniform(10, 20))

      except FloodWaitError as e:
        await asyncio.sleep(e.seconds + 5)
      except Exception:
        failed_count += 1
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
          f.write(str(user_id) + "\n")

    if client_new:
      await client_new.disconnect()

    await progress_msg.edit(
        "🎉 **انتهت العملية بنجاح!**\n\n📊 **التقرير النهائي:**\n• الرسائل المرسلة:"
        f" `{msg_sent_count}`\n• الإضافات المباشرة: `{added_count}`\n• الأخطاء:"
        f" `{failed_count}`",
        parse_mode="markdown",
    )

  except asyncio.CancelledError:
    if client_new:
      try:
        await client_new.disconnect()
      except Exception:
        pass
    await progress_msg.edit(
        "⚠️ **تم إيقاف عملية الإرسال والإضافة بناءً على طلبك!**",
        parse_mode="markdown",
    )
  except Exception as e:
    if client_new:
      try:
        await client_new.disconnect()
      except Exception:
        pass
    await progress_msg.edit("❌ حدث خطأ أثناء التنفيذ: `" + str(e) + "`")
  finally:
    active_tasks.pop(progress_msg.chat_id, None)


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
      print("⚠️ تم إيقاف البوت يدوياً بواسطة المستخدم.")
      break
    except Exception as e:
      print(f"❌ حدث خطأ طارئ أدى لتوقف البوت: {e}")
      print("🔄 جاري إعادة تشغيل البوت تلقائياً خلال 5 ثوانٍ...")
      await asyncio.sleep(5)
      try:
        if bot.is_connected():
          await bot.disconnect()
      except Exception:
        pass


if __name__ == "__main__":
  try:
    asyncio.run(main_loop())
  except KeyboardInterrupt:
    print("⚠️ تم إيقاف البوت نهائياً.")