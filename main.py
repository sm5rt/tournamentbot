import json
import os
import random
from datetime import datetime
from typing import List, Optional

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
    ConversationHandler
)

# Состояния
SELECT_SIZE, COLLECTING_TEAMS, ENTERING_RESULT = range(3)

# Файл истории
HISTORY_FILE = "tournaments.json"

# ======================
# Вспомогательные функции
# ======================

def load_history() -> dict:
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_history(data: dict):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def format_team(team: Optional[dict]) -> str:
    if not team:
        return "—"
    lines = [f"**{team['name']}**"]
    for i, player in enumerate(team["players"], 1):
        lines.append(f"Участник {i}: {player}")
    return "\n".join(lines)

def generate_bracket(teams: List[dict]) -> List[dict]:
    if len(teams) == 1:
        return [{"team1": teams[0], "team2": None, "score1": None, "score2": None, "winner": teams[0]}]
    shuffled = teams[:]
    random.shuffle(shuffled)
    matches = []
    for i in range(0, len(shuffled), 2):
        team1 = shuffled[i]
        team2 = shuffled[i + 1] if i + 1 < len(shuffled) else None
        matches.append({
            "team1": team1,
            "team2": team2,
            "score1": None,
            "score2": None,
            "winner": None
        })
    return matches

# ======================
# Обработчики команд
# ======================

async def start_tournament(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("Используй: /tournament <название турнира>")
        return ConversationHandler.END

    tournament_name = " ".join(args)
    context.user_data.clear()
    context.user_data["tournament_name"] = tournament_name
    context.user_data["teams"] = []

    keyboard = [
        [InlineKeyboardButton("Турнир 2 команды", callback_data="size_2")],
        [InlineKeyboardButton("Турнир 4 команды", callback_data="size_4")],
        [InlineKeyboardButton("Турнир 8 команд", callback_data="size_8")],
        [InlineKeyboardButton("Турнир 16 команд", callback_data="size_16")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выбери размер турнира:", reply_markup=reply_markup)
    return SELECT_SIZE

async def select_size(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    size = int(query.data.split("_")[1])
    allowed_sizes = {2, 4, 8, 16}
    if size not in allowed_sizes:
        await query.edit_message_text("Недопустимый размер турнира.")
        return ConversationHandler.END

    context.user_data["size"] = size
    context.user_data["current_team_index"] = 0

    await query.edit_message_text(
        f"Начинаем сбор данных для турнира на {size} команд.\n"
        "Отправь данные первой команды в формате:\n"
        "Название команды\nУчастник 1\nУчастник 2\nУчастник 3"
    )
    return COLLECTING_TEAMS

async def collect_teams(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().split("\n")
    if len(text) != 4:
        await update.message.reply_text("❌ Неверный формат!\nДолжно быть ровно 4 строки:\nНазвание\nУчастник 1\nУчастник 2\nУчастник 3")
        return COLLECTING_TEAMS

    name, p1, p2, p3 = [line.strip() for line in text]
    if not name or not p1 or not p2 or not p3:
        await update.message.reply_text("❌ Все поля обязательны!")
        return COLLECTING_TEAMS

    team = {"name": name, "players": [p1, p2, p3]}
    context.user_data["teams"].append(team)
    current = len(context.user_data["teams"])
    total = context.user_data["size"]

    if current < total:
        await update.message.reply_text(
            f"✅ Команда '{name}' добавлена!\nОсталось: {total - current}\n"
            "Отправь следующую команду (в том же формате):"
        )
        return COLLECTING_TEAMS
    else:
        bracket = generate_bracket(context.user_data["teams"])
        context.user_data["bracket"] = [bracket]
        await show_bracket(update, context)
        return ENTERING_RESULT

async def show_bracket(update: Update, context: ContextTypes.DEFAULT_TYPE, edit=False):
    stages = context.user_data["bracket"]
    current_stage = stages[-1]

    # Проверка завершения
    if len(current_stage) == 1 and current_stage[0]["winner"]:
        winner_name = current_stage[0]["winner"]["name"]
        msg = f"🏆 **Победитель турнира '{context.user_data['tournament_name']}'**: {winner_name}!\n\n"
        history = load_history()
        tournament_id = str(int(datetime.now().timestamp()))
        history[tournament_id] = {
            "name": context.user_data["tournament_name"],
            "date": datetime.now().strftime("%d.%m.%Y %H:%M"),
            "stages": context.user_data["bracket"]
        }
        save_history(history)
        msg += "✅ Турнир сохранён в историю."
        if edit:
            await update.callback_query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        return

    full_msg = f"**Турнир: {context.user_data['tournament_name']}**\n\n"
    for i, stage in enumerate(stages):
        full_msg += f"**Стадия {i + 1}:**\n"
        for match in stage:
            team2_name = match["team2"]["name"] if match["team2"] else "—"
            if match["score1"] is not None:
                full_msg += f"{match['team1']['name']} {match['score1']}:{match['score2']} {team2_name}\n"
            else:
                full_msg += f"{match['team1']['name']} — {team2_name}\n"
        full_msg += "\n"

    buttons = []
    for idx, match in enumerate(current_stage):
        if match["score1"] is None:
            buttons.append([InlineKeyboardButton(f"Ввести результат матча {idx + 1}", callback_data=f"match_{idx}")])

    reply_markup = InlineKeyboardMarkup(buttons) if buttons else None

    if edit:
        await update.callback_query.edit_message_text(full_msg, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    else:
        await update.message.reply_text(full_msg, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

async def match_result_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    match_idx = int(query.data.split("_")[1])
    context.user_data["current_match_idx"] = match_idx
    await query.message.reply_text("🔢 Отправь результат в формате: `3:2` (счёт команды 1 : команда 2)")
    return ENTERING_RESULT

async def enter_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if ":" not in text:
        await update.message.reply_text("❌ Неверный формат! Используй `X:Y`, например `3:1`")
        return ENTERING_RESULT

    try:
        s1, s2 = map(int, text.split(":"))
        if s1 < 0 or s2 < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Счёт должен содержать неотрицательные целые числа!")
        return ENTERING_RESULT

    match_idx = context.user_data["current_match_idx"]
    stages = context.user_data["bracket"]
    current_stage = stages[-1]
    match = current_stage[match_idx]
    match["score1"] = s1
    match["score2"] = s2
    match["winner"] = match["team1"] if s1 > s2 else match["team2"]

    if all(m["score1"] is not None for m in current_stage):
        winners = [m["winner"] for m in current_stage if m["winner"]]
        if len(winners) > 1:
            next_stage = generate_bracket(winners)
            context.user_data["bracket"].append(next_stage)

    await show_bracket(update, context)
    return ENTERING_RESULT

async def history_tournament(update: Update, context: ContextTypes.DEFAULT_TYPE):
    history = load_history()
    if not history:
        await update.message.reply_text("📁 История турниров пуста.")
        return

    buttons = []
    for tid, data in history.items():
        label = f"{data['name']} ({data['date']})"
        buttons.append([InlineKeyboardButton(label, callback_data=f"view_{tid}")])

    buttons.append([InlineKeyboardButton("➕ Создать новый турнир", callback_data="new_tournament")])
    reply_markup = InlineKeyboardMarkup(buttons)
    await update.message.reply_text("📁 История турниров:", reply_markup=reply_markup)

async def view_tournament_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "new_tournament":
        await query.message.reply_text("Используй команду: /tournament <название>")
        return

    tid = data.split("_", 1)[1]
    history = load_history()
    tournament = history.get(tid)
    if not tournament:
        await query.edit_message_text("❌ Турнир не найден.")
        return

    msg = f"**{tournament['name']}**\n📅 Дата: {tournament['date']}\n\n"
    for i, stage in enumerate(tournament["stages"]):
        msg += f"**Стадия {i + 1}:**\n"
        for match in stage:
            team2_name = match["team2"]["name"] if match["team2"] else "—"
            if match["score1"] is not None:
                msg += f"{match['team1']['name']} {match['score1']}:{match['score2']} {team2_name}\n"
                msg += f"👥 Участники:\n{format_team(match['team1'])}\n{format_team(match['team2'])}\n\n"
            else:
                msg += f"{match['team1']['name']} — {team2_name}\n\n"

    del_button = InlineKeyboardButton("🗑 Удалить турнир", callback_data=f"delete_{tid}")
    back_button = InlineKeyboardButton("⬅ Назад к списку", callback_data="back_to_history")
    reply_markup = InlineKeyboardMarkup([[del_button], [back_button]])

    await query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

async def delete_tournament_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tid = query.data.split("_", 1)[1]
    history = load_history()
    if tid in history:
        del history[tid]
        save_history(history)
        await query.edit_message_text("✅ Турнир удалён из истории.")
    else:
        await query.edit_message_text("❌ Турнир уже удалён.")

async def back_to_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await history_tournament(update, context)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏹ Создание турнира отменено.")
    return ConversationHandler.END

# ======================
# Запуск бота
# ======================

def main():
    TOKEN = os.environ.get("BOT_TOKEN")
    if not TOKEN:
        raise ValueError("❌ Переменная окружения BOT_TOKEN не установлена!")

    application = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("tournament", start_tournament)],
        states={
            SELECT_SIZE: [CallbackQueryHandler(select_size, pattern="^size_")],
            COLLECTING_TEAMS: [MessageHandler(filters.TEXT & ~filters.COMMAND, collect_teams)],
            ENTERING_RESULT: [
                CallbackQueryHandler(match_result_callback, pattern="^match_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_result)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("historytournament", history_tournament))
    application.add_handler(CallbackQueryHandler(view_tournament_callback, pattern="^view_"))
    application.add_handler(CallbackQueryHandler(delete_tournament_callback, pattern="^delete_"))
    application.add_handler(CallbackQueryHandler(back_to_history, pattern="^back_to_history"))
    application.add_handler(CallbackQueryHandler(
        lambda u, c: u.callback_query.message.reply_text("Используй: /tournament <название>"),
        pattern="^new_tournament"
    ))

    print("✅ Бот запущен!")
    application.run_polling()

if __name__ == "__main__":
    main()
