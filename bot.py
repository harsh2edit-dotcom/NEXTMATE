"""
XYVEN ADS BOT — Smart Telegram Advertising Automation
Polling bot with 3 languages (en / hi / ru). No website, no webhook.
"""
import asyncio
import logging
import os
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand, CallbackQuery, ChatMemberUpdated, InlineKeyboardButton,
    InlineKeyboardMarkup, Message, Update,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# ════════════════════════════════════════════════════════════════════
# CONFIG
# ════════════════════════════════════════════════════════════════════
BOT_TOKEN       = os.environ.get("BOT_TOKEN", "8935830429:AAHVMuTqsO2rU1n1xxZhEPHFWhhMUhG_HbA")
OWNER_ID        = int(os.environ.get("OWNER_ID", "8969622561"))
DATABASE_URL    = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///xyven.db")
WEBSITE_URL     = os.environ.get("WEBSITE_URL", "https://uc-store-xyven.onrender.com")
AD_INTERVAL_MIN = int(os.environ.get("AD_INTERVAL_MINUTES", "180"))
MAX_ADS_PER_DAY = int(os.environ.get("MAX_ADS_PER_DAY", "5"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("xyven")


def _norm(url: str) -> str:
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


engine = create_async_engine(_norm(DATABASE_URL), pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


# ════════════════════════════════════════════════════════════════════
# MODELS
# ════════════════════════════════════════════════════════════════════
class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username:   Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    language:   Mapped[str]        = mapped_column(String(8), default="en")
    created_at: Mapped[datetime]   = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen:  Mapped[datetime]   = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Group(Base):
    __tablename__ = "groups"
    telegram_group_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    group_name:    Mapped[str | None]     = mapped_column(String(255), nullable=True)
    enabled:       Mapped[bool]           = mapped_column(Boolean, default=True)
    ad_enabled:    Mapped[bool]           = mapped_column(Boolean, default=True)
    created_at:    Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_ad_sent:  Mapped[datetime | None]= mapped_column(DateTime(timezone=True), nullable=True)
    ads_sent_today:Mapped[int]            = mapped_column(Integer, default=0)
    counter_date:  Mapped[str | None]     = mapped_column(String(10), nullable=True)


class Ad(Base):
    __tablename__ = "ads"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    content:       Mapped[str]        = mapped_column(Text, default="")
    media_type:    Mapped[str | None] = mapped_column(String(16), nullable=True)
    media_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    enabled:       Mapped[bool]       = mapped_column(Boolean, default=True)
    created_at:    Mapped[datetime]   = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at:    Mapped[datetime]   = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Setting(Base):
    __tablename__ = "settings"
    key:   Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# ════════════════════════════════════════════════════════════════════
# TRANSLATIONS — 3 languages (en / hi / ru)
# ════════════════════════════════════════════════════════════════════
LANGS = {"en": "🇬🇧 English", "hi": "🇮🇳 हिन्दी", "ru": "🇷🇺 Русский"}
DEFAULT_LANG = "en"

TR: dict[str, dict[str, str]] = {
"en": {
 "lang.choose":  "🌍 <b>Choose your language</b>",
 "lang.saved":   "✅ Language set to <b>English</b>.",
 "owner_only":   "⛔ <b>Owner/Admin only.</b>",
 "unsupported":  "⚠️ Unsupported content.",
 "start.welcome":("👋 <b>Welcome to XYVEN ADS BOT</b>\n<i>Smart Telegram Advertising Automation</i>\n\n"
                  "Use the buttons below, or send /help for all commands."),
 "help": ("ℹ️ <b>XYVEN ADS BOT — Commands</b>\n\n"
          "👤 <b>Everyone</b>\n• /start • /help • /web • /language\n\n"
          "🛡 <b>Owner/Admin only</b>\n"
          "• /setads — Configure the advertisement\n"
          "• /setmessage — Set welcome message\n"
          "• /admin — Control panel\n\n"
          "🌐 Website: uc-store-xyven.onrender.com"),
 "web.title":  "🌐 <b>XYVEN Official Store</b>",
 "web.body":   "Premium Telegram advertising automation, delivered.",
 "web.button": "🌐 Visit Website",
 "setads.ask":    "📢 <b>Send the advertisement you want me to save.</b>\n\nText, or media + caption.",
 "setads.saved":  "✅ <b>Advertisement saved successfully.</b>\nI’ll use this ad for automatic group advertising.",
 "setads.edit":   "✏️ Send the <b>new</b> ad content.",
 "setads.updated":"✅ Advertisement updated.",
 "setads.deleted":"🗑 Advertisement deleted.",
 "setads.notfound":"⚠️ Advertisement not found.",
 "setads.preview":"👁 <b>Preview</b>",
 "setmsg.ask":    "✉️ <b>Send the message users should receive when they start the bot.</b>",
 "setmsg.saved":  "✅ Welcome message saved. It will now be shown on /start.",
 "group.registered": "✅ <b>New group registered</b>\nName: <b>{name}</b>\nID: <code>{gid}</code>",
 "group.noperm":     "⚠️ <b>Permission issue</b> in <b>{name}</b> (<code>{gid}</code>). Please grant Send Messages.",
 "group.adfail":     "⚠️ Ad delivery failed in <code>{gid}</code>: {reason}",
 "admin.ask_int":"⏱ Send new interval in <b>minutes</b> (e.g. 180).",
 "admin.ask_max":"📈 Send new <b>max ads/day per group</b> (e.g. 5).",
 "admin.set":   "✅ Set to <b>{value}</b>.",
 "admin.noads":"📭 No ads saved yet.",
 "admin.nogrps":"📭 No groups registered yet.",
},
"hi": {
 "lang.choose":  "🌍 <b>अपनी भाषा चुनें</b>",
 "lang.saved":   "✅ भाषा <b>हिन्दी</b> पर सेट हो गई।",
 "owner_only":   "⛔ <b>केवल ओनर/एडमिन।</b>",
 "unsupported":  "⚠️ असमर्थित सामग्री।",
 "start.welcome":("👋 <b>XYVEN ADS BOT में आपका स्वागत है</b>\n<i>स्मार्ट टेलीग्राम विज्ञापन ऑटोमेशन</i>\n\n"
                  "नीचे बटन का उपयोग करें, या /help भेजें।"),
 "help": ("ℹ️ <b>XYVEN ADS BOT — कमांड्स</b>\n\n"
          "👤 <b>सभी के लिए</b>\n• /start • /help • /web • /language\n\n"
          "🛡 <b>केवल ओनर/एडमिन</b>\n• /setads • /setmessage • /admin\n\n"
          "🌐 वेबसाइट: uc-store-xyven.onrender.com"),
 "web.title":  "🌐 <b>XYVEN ऑफिशियल स्टोर</b>",
 "web.body":   "प्रीमियम टेलीग्राम विज्ञापन ऑटोमेशन।",
 "web.button": "🌐 वेबसाइट खोलें",
 "setads.ask":    "📢 <b>वह विज्ञापन भेजें जिसे सेव करना है।</b>\n\nटेक्स्ट या मीडिया+कैप्शन।",
 "setads.saved":  "✅ <b>विज्ञापन सेव हो गया।</b>",
 "setads.edit":   "✏️ <b>नया</b> विज्ञापन भेजें।",
 "setads.updated":"✅ विज्ञापन अपडेट हुआ।",
 "setads.deleted":"🗑 विज्ञापन हटा दिया गया।",
 "setads.notfound":"⚠️ विज्ञापन नहीं मिला।",
 "setads.preview":"👁 <b>प्रीव्यू</b>",
 "setmsg.ask":    "✉️ <b>/start पर दिखने वाला संदेश भेजें।</b>",
 "setmsg.saved":  "✅ स्वागत संदेश सेव हुआ।",
 "group.registered": "✅ <b>नया ग्रुप रजिस्टर</b>\nनाम: <b>{name}</b>\nID: <code>{gid}</code>",
 "group.noperm":     "⚠️ <b>{name}</b> (<code>{gid}</code>) में अनुमति समस्या। Send Messages दें।",
 "group.adfail":     "⚠️ <code>{gid}</code> में विज्ञापन असफल: {reason}",
 "admin.ask_int":"⏱ नया अंतराल मिनटों में भेजें (जैसे 180)।",
 "admin.ask_max":"📈 प्रति दिन अधिकतम भेजें (जैसे 5)।",
 "admin.set":   "✅ सेट: <b>{value}</b>",
 "admin.noads":"📭 कोई विज्ञापन नहीं।",
 "admin.nogrps":"📭 कोई ग्रुप नहीं।",
},
"ru": {
 "lang.choose":  "🌍 <b>Выберите язык</b>",
 "lang.saved":   "✅ Язык изменён на <b>Русский</b>.",
 "owner_only":   "⛔ <b>Только владелец/админ.</b>",
 "unsupported":  "⚠️ Неподдерживаемый контент.",
 "start.welcome":("👋 <b>Добро пожаловать в XYVEN ADS BOT</b>\n<i>Умная автоматизация рекламы в Telegram</i>\n\n"
                  "Используйте кнопки ниже или /help."),
 "help": ("ℹ️ <b>XYVEN ADS BOT — Команды</b>\n\n"
          "👤 <b>Для всех</b>\n• /start • /help • /web • /language\n\n"
          "🛡 <b>Только владелец/админ</b>\n• /setads • /setmessage • /admin\n\n"
          "🌐 Сайт: uc-store-xyven.onrender.com"),
 "web.title":  "🌐 <b>XYVEN Официальный магазин</b>",
 "web.body":   "Премиум-автоматизация рекламы в Telegram.",
 "web.button": "🌐 Открыть сайт",
 "setads.ask":    "📢 <b>Отправьте рекламу для сохранения.</b>\n\nТекст или медиа+подпись.",
 "setads.saved":  "✅ <b>Реклама сохранена.</b>",
 "setads.edit":   "✏️ Отправьте <b>новую</b> рекламу.",
 "setads.updated":"✅ Реклама обновлена.",
 "setads.deleted":"🗑 Реклама удалена.",
 "setads.notfound":"⚠️ Реклама не найдена.",
 "setads.preview":"👁 <b>Предпросмотр</b>",
 "setmsg.ask":    "✉️ <b>Отправьте приветствие для /start.</b>",
 "setmsg.saved":  "✅ Приветствие сохранено.",
 "group.registered": "✅ <b>Группа зарегистрирована</b>\nИмя: <b>{name}</b>\nID: <code>{gid}</code>",
 "group.noperm":     "⚠️ <b>Проблема с правами</b> в <b>{name}</b> (<code>{gid}</code>). Разрешите Send Messages.",
 "group.adfail":     "⚠️ Ошибка в <code>{gid}</code>: {reason}",
 "admin.ask_int":"⏱ Отправьте интервал в минутах (например 180).",
 "admin.ask_max":"📈 Максимум объявлений в день (например 5).",
 "admin.set":   "✅ Установлено: <b>{value}</b>",
 "admin.noads":"📭 Реклам нет.",
 "admin.nogrps":"📭 Групп нет.",
},
}


def t(key: str, lang: str | None = None, **fmt) -> str:
    lang = lang if lang in LANGS else DEFAULT_LANG
    text = TR[lang].get(key) or TR[DEFAULT_LANG].get(key) or key
    try:
        return text.format(**fmt) if fmt else text
    except (KeyError, IndexError):
        return text


# ════════════════════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════════════════════
def is_owner(uid: int) -> bool:
    return uid == OWNER_ID


async def get_setting(db: AsyncSession, key: str, default: str | None = None) -> str | None:
    row = await db.get(Setting, key)
    return row.value if row else default


async def set_setting(db: AsyncSession, key: str, value: str) -> None:
    row = await db.get(Setting, key)
    if row: row.value = value
    else:   db.add(Setting(key=key, value=value))
    await db.commit()


async def user_lang(db: AsyncSession, uid: int) -> str:
    u = await db.get(User, uid)
    return (u.language if u and u.language else DEFAULT_LANG)


async def send_ad(bot: Bot, chat_id: int, ad: Ad) -> None:
    cap = ad.content or None
    if ad.media_type == "photo":       await bot.send_photo(chat_id, ad.media_file_id, caption=cap)
    elif ad.media_type == "video":     await bot.send_video(chat_id, ad.media_file_id, caption=cap)
    elif ad.media_type == "animation": await bot.send_animation(chat_id, ad.media_file_id, caption=cap)
    elif ad.media_type == "document":  await bot.send_document(chat_id, ad.media_file_id, caption=cap)
    else: await bot.send_message(chat_id, ad.content or "📢")


# ════════════════════════════════════════════════════════════════════
# KEYBOARDS
# ════════════════════════════════════════════════════════════════════
def welcome_kb(lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text=t("web.button", lang), url=WEBSITE_URL))
    b.row(InlineKeyboardButton(text="ℹ️ Help", callback_data="menu:help"),
          InlineKeyboardButton(text="🌍 Language", callback_data="menu:lang"))
    return b.as_markup()


def web_kb(lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text=t("web.button", lang), url=WEBSITE_URL))
    return b.as_markup()


def lang_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for code, label in LANGS.items():
        b.row(InlineKeyboardButton(text=label, callback_data=f"lang:{code}"))
    return b.as_markup()


def ad_saved_kb(ad_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="✏️ Edit",    callback_data=f"ad:edit:{ad_id}"),
        InlineKeyboardButton(text="🗑 Delete",  callback_data=f"ad:delete:{ad_id}"),
        InlineKeyboardButton(text="👁 Preview", callback_data=f"ad:preview:{ad_id}"),
    )
    return b.as_markup()


def admin_kb(ads_on: bool, grps_on: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(
        text=f"{'🟢' if ads_on else '🔴'} Advertising: {'ON' if ads_on else 'OFF'}",
        callback_data="adm:toggle_ads"))
    b.row(InlineKeyboardButton(
        text=f"{'🟢' if grps_on else '🔴'} Group posting: {'ON' if grps_on else 'OFF'}",
        callback_data="adm:toggle_groups"))
    b.row(InlineKeyboardButton(text="⏱ Set interval", callback_data="adm:set_interval"),
          InlineKeyboardButton(text="📈 Set max/day",  callback_data="adm:set_max"))
    b.row(InlineKeyboardButton(text="🧾 Ads list",     callback_data="adm:ads_list"))
    b.row(InlineKeyboardButton(text="👥 Groups list",  callback_data="adm:groups"))
    return b.as_markup()


# ════════════════════════════════════════════════════════════════════
# MIDDLEWARES
# ════════════════════════════════════════════════════════════════════
class DbMW:
    async def __call__(self, handler, event, data):
        async with SessionLocal() as s:
            data["db"] = s
            return await handler(event, data)


class UserMW:
    @staticmethod
    def _u(event):
        if isinstance(event, Update):
            if event.message:        return event.message.from_user
            if event.callback_query: return event.callback_query.from_user
            if event.my_chat_member: return event.my_chat_member.from_user
        return getattr(event, "from_user", None)

    async def __call__(self, handler, event, data):
        db = data.get("db"); u = self._u(event)
        lang = DEFAULT_LANG
        if db is not None and u is not None and not u.is_bot:
            row = await db.get(User, u.id)
            if row is None:
                row = User(telegram_user_id=u.id, username=u.username, first_name=u.first_name, language=DEFAULT_LANG)
                db.add(row)
            else:
                row.username, row.first_name = u.username, u.first_name
            await db.commit()
            lang = row.language or DEFAULT_LANG
        data["lang"] = lang
        return await handler(event, data)


# ════════════════════════════════════════════════════════════════════
# FSM
# ════════════════════════════════════════════════════════════════════
class SetAdStates(StatesGroup):   waiting = State();  editing = State()
class SetMsgStates(StatesGroup):  waiting = State()
class AdminStates(StatesGroup):   interval = State(); maxday = State()


# ════════════════════════════════════════════════════════════════════
# ROUTER
# ════════════════════════════════════════════════════════════════════
router = Router()


@router.message(CommandStart())
async def cmd_start(m: Message, db: AsyncSession, lang: str):
    custom = await get_setting(db, "welcome_message")
    text = custom or t("start.welcome", lang)
    try:
        await m.answer(text, reply_markup=welcome_kb(lang), disable_web_page_preview=True)
    except Exception:
        await m.answer(t("start.welcome", lang), reply_markup=welcome_kb(lang))


@router.message(Command("help"))
async def cmd_help(m: Message, lang: str):
    await m.answer(t("help", lang), disable_web_page_preview=True)


@router.message(Command("web"))
async def cmd_web(m: Message, lang: str):
    await m.answer(f"{t('web.title', lang)}\n\n{t('web.body', lang)}",
                   reply_markup=web_kb(lang), disable_web_page_preview=True)


@router.message(Command("language"))
async def cmd_language(m: Message, lang: str):
    await m.answer(t("lang.choose", lang), reply_markup=lang_kb())


@router.callback_query(F.data.startswith("lang:"))
async def cb_lang(c: CallbackQuery, db: AsyncSession):
    code = c.data.split(":", 1)[1]
    if code not in LANGS:
        await c.answer("Unsupported language", show_alert=True); return
    u = await db.get(User, c.from_user.id)
    if u:
        u.language = code
        await db.commit()
    await c.message.answer(t("lang.saved", code))
    await c.answer()


# ── /setads ──────────────────────────────────────────────────────
@router.message(Command("setads"))
async def cmd_setads(m: Message, state: FSMContext, lang: str):
    if not is_owner(m.from_user.id):
        await m.answer(t("owner_only", lang)); return
    await state.set_state(SetAdStates.waiting)
    await m.answer(t("setads.ask", lang))


@router.message(SetAdStates.waiting)
async def recv_ad(m: Message, state: FSMContext, db: AsyncSession, lang: str):
    if not is_owner(m.from_user.id): return
    mt, fid, txt = None, None, ""
    if   m.photo:     mt, fid, txt = "photo", m.photo[-1].file_id, m.caption or ""
    elif m.video:     mt, fid, txt = "video", m.video.file_id, m.caption or ""
    elif m.animation: mt, fid, txt = "animation", m.animation.file_id, m.caption or ""
    elif m.document:  mt, fid, txt = "document", m.document.file_id, m.caption or ""
    elif m.text:      txt = m.text
    else:
        await m.answer(t("unsupported", lang)); return
    ad = Ad(content=txt, media_type=mt, media_file_id=fid, enabled=True)
    db.add(ad); await db.commit(); await db.refresh(ad)
    await state.clear()
    await m.answer(t("setads.saved", lang), reply_markup=ad_saved_kb(ad.id))


@router.callback_query(F.data.startswith("ad:edit:"))
async def cb_ad_edit(c: CallbackQuery, state: FSMContext, lang: str):
    if not is_owner(c.from_user.id):
        await c.answer("Owner only", show_alert=True); return
    ad_id = int(c.data.split(":")[2])
    await state.set_state(SetAdStates.editing)
    await state.update_data(ad_id=ad_id)
    await c.message.answer(t("setads.edit", lang))
    await c.answer()


@router.message(SetAdStates.editing)
async def recv_ad_edit(m: Message, state: FSMContext, db: AsyncSession, lang: str):
    if not is_owner(m.from_user.id): return
    data = await state.get_data(); ad = await db.get(Ad, data.get("ad_id"))
    if not ad:
        await state.clear(); await m.answer(t("setads.notfound", lang)); return
    if   m.photo:     ad.media_type, ad.media_file_id, ad.content = "photo",     m.photo[-1].file_id, m.caption or ""
    elif m.video:     ad.media_type, ad.media_file_id, ad.content = "video",     m.video.file_id,     m.caption or ""
    elif m.animation: ad.media_type, ad.media_file_id, ad.content = "animation", m.animation.file_id, m.caption or ""
    elif m.document:  ad.media_type, ad.media_file_id, ad.content = "document",  m.document.file_id,  m.caption or ""
    elif m.text:      ad.media_type, ad.media_file_id, ad.content = None, None, m.text
    else:
        await m.answer(t("unsupported", lang)); return
    await db.commit(); await state.clear()
    await m.answer(t("setads.updated", lang), reply_markup=ad_saved_kb(ad.id))


@router.callback_query(F.data.startswith("ad:delete:"))
async def cb_ad_del(c: CallbackQuery, db: AsyncSession, lang: str):
    if not is_owner(c.from_user.id):
        await c.answer("Owner only", show_alert=True); return
    ad = await db.get(Ad, int(c.data.split(":")[2]))
    if ad:
        await db.delete(ad); await db.commit()
        await c.message.answer(t("setads.deleted", lang))
    else:
        await c.message.answer(t("setads.notfound", lang))
    await c.answer()


@router.callback_query(F.data.startswith("ad:preview:"))
async def cb_ad_prev(c: CallbackQuery, db: AsyncSession, lang: str):
    if not is_owner(c.from_user.id):
        await c.answer("Owner only", show_alert=True); return
    ad = await db.get(Ad, int(c.data.split(":")[2]))
    if not ad:
        await c.message.answer(t("setads.notfound", lang)); await c.answer(); return
    await c.message.answer(t("setads.preview", lang))
    try: await send_ad(c.bot, c.from_user.id, ad)
    except Exception as e: await c.message.answer(f"⚠️ {e}")
    await c.answer()


# ── /setmessage ──────────────────────────────────────────────────
@router.message(Command("setmessage"))
async def cmd_setmsg(m: Message, state: FSMContext, lang: str):
    if not is_owner(m.from_user.id):
        await m.answer(t("owner_only", lang)); return
    await state.set_state(SetMsgStates.waiting)
    await m.answer(t("setmsg.ask", lang))


@router.message(SetMsgStates.waiting)
async def recv_msg(m: Message, state: FSMContext, db: AsyncSession, lang: str):
    if not is_owner(m.from_user.id): return
    if not m.text:
        await m.answer(t("unsupported", lang)); return
    await set_setting(db, "welcome_message", m.html_text)
    await state.clear()
    await m.answer(t("setmsg.saved", lang))


# ── /admin ───────────────────────────────────────────────────────
async def _admin_text(db: AsyncSession) -> str:
    from sqlalchemy import func as f
    ads_on  = (await get_setting(db, "advertising_enabled", "true")) == "true"
    grps_on = (await get_setting(db, "groups_posting_enabled", "true")) == "true"
    iv = await get_setting(db, "ad_interval_minutes", str(AD_INTERVAL_MIN))
    mx = await get_setting(db, "max_ads_per_day", str(MAX_ADS_PER_DAY))
    users   = (await db.execute(select(f.count()).select_from(User))).scalar_one()
    groups  = (await db.execute(select(f.count()).select_from(Group))).scalar_one()
    act_ads = (await db.execute(select(f.count()).select_from(Ad).where(Ad.enabled.is_(True)))).scalar_one()
    return (f"🛡 <b>XYVEN ADS BOT — Admin Panel</b>\n\n"
            f"👥 Users: <b>{users}</b>\n👥 Groups: <b>{groups}</b>\n"
            f"📢 Active ads: <b>{act_ads}</b>\n\n"
            f"⏱ Interval: <b>{iv} min</b>\n📈 Max/day: <b>{mx}</b>\n"
            f"📣 Advertising: <b>{'ON' if ads_on else 'OFF'}</b>\n"
            f"👥 Group posting: <b>{'ON' if grps_on else 'OFF'}</b>")


@router.message(Command("admin"))
async def cmd_admin(m: Message, db: AsyncSession, lang: str):
    if not is_owner(m.from_user.id):
        await m.answer(t("owner_only", lang)); return
    ads_on  = (await get_setting(db, "advertising_enabled", "true")) == "true"
    grps_on = (await get_setting(db, "groups_posting_enabled", "true")) == "true"
    await m.answer(await _admin_text(db), reply_markup=admin_kb(ads_on, grps_on))


@router.callback_query(F.data.startswith("adm:"))
async def cb_admin(c: CallbackQuery, db: AsyncSession, state: FSMContext, lang: str):
    if not is_owner(c.from_user.id):
        await c.answer("Owner only", show_alert=True); return
    action = c.data.split(":", 1)[1]

    if action in ("toggle_ads", "toggle_groups"):
        key = "advertising_enabled" if action == "toggle_ads" else "groups_posting_enabled"
        cur = (await get_setting(db, key, "true")) == "true"
        await set_setting(db, key, "false" if cur else "true")
        ads_on  = (await get_setting(db, "advertising_enabled", "true")) == "true"
        grps_on = (await get_setting(db, "groups_posting_enabled", "true")) == "true"
        await c.message.edit_text(await _admin_text(db), reply_markup=admin_kb(ads_on, grps_on))
        await c.answer("Updated"); return

    if action == "set_interval":
        await state.set_state(AdminStates.interval)
        await c.message.answer(t("admin.ask_int", lang)); await c.answer(); return

    if action == "set_max":
        await state.set_state(AdminStates.maxday)
        await c.message.answer(t("admin.ask_max", lang)); await c.answer(); return

    if action == "ads_list":
        ads = (await db.execute(select(Ad).order_by(Ad.id))).scalars().all()
        if not ads:
            await c.message.answer(t("admin.noads", lang))
        else:
            lines = ["🧾 <b>Ads</b>\n"]
            for a in ads:
                prev = (a.content or "")[:60].replace("\n", " ")
                lines.append(f"• <b>#{a.id}</b> [{'🟢' if a.enabled else '🔴'}] {a.media_type or 'text'} — <i>{prev or '(media)'}</i>")
            await c.message.answer("\n".join(lines))
        await c.answer(); return

    if action == "groups":
        gs = (await db.execute(select(Group).order_by(Group.created_at.desc()).limit(50))).scalars().all()
        if not gs:
            await c.message.answer(t("admin.nogrps", lang))
        else:
            lines = ["👥 <b>Groups</b>\n"]
            for g in gs:
                lines.append(f"• <b>{g.group_name or '?'}</b> <code>{g.telegram_group_id}</code> "
                             f"{'🟢' if g.enabled else '🔴'}/{'🟢' if g.ad_enabled else '🔴'} sent:{g.ads_sent_today}")
            await c.message.answer("\n".join(lines))
        await c.answer(); return


@router.message(AdminStates.interval)
async def recv_interval(m: Message, state: FSMContext, db: AsyncSession, lang: str):
    if not is_owner(m.from_user.id): return
    if not (m.text or "").strip().isdigit():
        await m.answer("⚠️ Number only."); return
    await set_setting(db, "ad_interval_minutes", m.text.strip())
    await state.clear()
    await m.answer(t("admin.set", lang, value=f"{m.text.strip()} min"))


@router.message(AdminStates.maxday)
async def recv_max(m: Message, state: FSMContext, db: AsyncSession, lang: str):
    if not is_owner(m.from_user.id): return
    if not (m.text or "").strip().isdigit():
        await m.answer("⚠️ Number only."); return
    await set_setting(db, "max_ads_per_day", m.text.strip())
    await state.clear()
    await m.answer(t("admin.set", lang, value=m.text.strip()))


@router.callback_query(F.data == "menu:help")
async def cb_menu_help(c: CallbackQuery, lang: str):
    await c.message.answer(t("help", lang)); await c.answer()


@router.callback_query(F.data == "menu:lang")
async def cb_menu_lang(c: CallbackQuery, lang: str):
    await c.message.answer(t("lang.choose", lang), reply_markup=lang_kb()); await c.answer()


# ── Group added / removed ────────────────────────────────────────
@router.my_chat_member()
async def on_chat_member(upd: ChatMemberUpdated, bot: Bot, db: AsyncSession):
    chat = upd.chat
    if chat.type not in ("group", "supergroup"): return
    status = upd.new_chat_member.status
    owner_lang = await user_lang(db, OWNER_ID)

    if status in ("member", "administrator", "creator"):
        g = await db.get(Group, chat.id)
        if not g:
            g = Group(telegram_group_id=chat.id, group_name=chat.title, enabled=True, ad_enabled=True)
            db.add(g)
        else:
            g.group_name, g.enabled = chat.title, True
        await db.commit()

        can_post = True
        try:
            me = await bot.get_chat_member(chat.id, bot.id)
            if me.status == "administrator":
                can_post = bool(getattr(me, "can_post_messages", True))
            elif me.status == "restricted":
                can_post = bool(getattr(me, "can_send_messages", False))
        except Exception:
            can_post = False

        try:
            if can_post:
                await bot.send_message(OWNER_ID, t("group.registered", owner_lang, name=chat.title, gid=chat.id))
            else:
                await bot.send_message(OWNER_ID, t("group.noperm", owner_lang, name=chat.title, gid=chat.id))
        except Exception:
            pass

    elif status in ("left", "kicked"):
        g = await db.get(Group, chat.id)
        if g:
            g.enabled = False
            await db.commit()


# ════════════════════════════════════════════════════════════════════
# SCHEDULER
# ════════════════════════════════════════════════════════════════════
async def ad_tick(bot: Bot) -> None:
    async with SessionLocal() as db:
        if (await get_setting(db, "advertising_enabled", "true")) != "true": return
        if (await get_setting(db, "groups_posting_enabled", "true")) != "true": return
        try:
            interval = int(await get_setting(db, "ad_interval_minutes", str(AD_INTERVAL_MIN)))
            max_day  = int(await get_setting(db, "max_ads_per_day", str(MAX_ADS_PER_DAY)))
            rot_idx  = int(await get_setting(db, "ad_rotation_index", "0"))
        except (TypeError, ValueError):
            interval, max_day, rot_idx = AD_INTERVAL_MIN, MAX_ADS_PER_DAY, 0

        ads = (await db.execute(select(Ad).where(Ad.enabled.is_(True)).order_by(Ad.id))).scalars().all()
        if not ads: return
        groups = (await db.execute(select(Group).where(Group.enabled.is_(True), Group.ad_enabled.is_(True)))).scalars().all()
        if not groups: return

        now = datetime.now(timezone.utc); today = now.strftime("%Y-%m-%d")
        owner_lang = await user_lang(db, OWNER_ID)
        sent_any = False

        for g in groups:
            if g.counter_date != today:
                g.ads_sent_today, g.counter_date = 0, today
            if g.ads_sent_today >= max_day: continue
            if g.last_ad_sent is not None:
                last = g.last_ad_sent
                if last.tzinfo is None: last = last.replace(tzinfo=timezone.utc)
                if (now - last).total_seconds() < interval * 60: continue
            ad = ads[rot_idx % len(ads)]
            try:
                await send_ad(bot, g.telegram_group_id, ad)
                g.last_ad_sent, g.ads_sent_today = now, g.ads_sent_today + 1
                rot_idx += 1; sent_any = True
                log.info("Ad #%s sent to group %s", ad.id, g.telegram_group_id)
            except Exception as e:
                log.warning("Ad fail %s: %s", g.telegram_group_id, e)
                try:
                    await bot.send_message(OWNER_ID,
                        t("group.adfail", owner_lang, gid=g.telegram_group_id, reason=str(e)[:180]))
                except Exception: pass
                g.ad_enabled = False

        if sent_any:
            await set_setting(db, "ad_rotation_index", str(rot_idx % max(len(ads), 1)))
        await db.commit()


def start_scheduler(bot: Bot) -> AsyncIOScheduler:
    sch = AsyncIOScheduler(timezone="UTC")
    sch.add_job(ad_tick, "interval", minutes=1, args=[bot],
                id="ad_tick", max_instances=1, coalesce=True, replace_existing=True)
    sch.start()
    log.info("Scheduler started")
    return sch


# ════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════
async def main() -> None:
    await init_db()
    log.info("Database ready")

    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(
        parse_mode=ParseMode.HTML, link_preview_is_disabled=True))

    dp = Dispatcher(storage=MemoryStorage())
    dp.update.outer_middleware(DbMW())
    dp.update.outer_middleware(UserMW())
    dp.include_router(router)

    await bot.set_my_commands([
        BotCommand(command="start",      description="Start the bot"),
        BotCommand(command="help",       description="Show all commands"),
        BotCommand(command="web",        description="Open the official website"),
        BotCommand(command="language",   description="Change language"),
        BotCommand(command="setads",     description="Owner: configure advertisement"),
        BotCommand(command="setmessage", description="Owner: set welcome message"),
        BotCommand(command="admin",      description="Owner: admin panel"),
    ])

    # Clean webhook in case it was set before — polling needs none
    await bot.delete_webhook(drop_pending_updates=True)

    scheduler = start_scheduler(bot)

    log.info("XYVEN ADS BOT started (polling)")
    try:
        await dp.start_polling(bot, allowed_updates=["message", "callback_query", "my_chat_member"])
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot stopped")
