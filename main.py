import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (ApplicationBuilder, CallbackContext,
                          CallbackQueryHandler, CommandHandler, ContextTypes)
from datetime import datetime
import re
import json
import requests

TELEGRAM_TOKEN = ''
VK_TOKEN = ''
search_keys = ['Котлас', 'Коряжма', 'Котласский', 'Коряжемский', 'Вычегодск', 'Сольвычегодск']
vk_api = f'https://api.vk.com/method/newsfeed.search?v=5.131&access_token={VK_TOKEN}'
delay_posts_send_in_seconds = 120
start_time_posts = 360
extract_id_pattern = r"wall-(\d+)_(\d+)"


with open('banned_groups.json', 'r') as file:
    banned_groups = json.load(file)


logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    jobs = context.job_queue.jobs()
    for job in jobs:
        job.schedule_removal()

    context.job_queue.run_once(
        callback=get_and_send_posts,
        when=0,
        chat_id=update.effective_chat.id,
        data={"start_time": start_time_posts}
    )

    context.job_queue.run_repeating(
        get_and_send_posts,
        interval=delay_posts_send_in_seconds,
        first=0,
        chat_id=update.effective_chat.id,
        data={"start_time": delay_posts_send_in_seconds}
    )


async def get_and_send_posts(context: ContextTypes.DEFAULT_TYPE):
    current_time = datetime.now().timestamp()
    start_time = context.job.data['start_time']
    time_before_delay = int(current_time - start_time)
    all_posts = []
    seen_posts = set()

    for search_key in search_keys:
        response = requests.post(
            url=f'{vk_api}&q={search_key}&start_time={time_before_delay}'
        )
        result = response.json()['response']
        posts = result['items']
        await collect_posts(posts, all_posts, seen_posts, search_key)
        offset = result.get("next_from")

        while offset:
            vk_api_with_pagination = f'{vk_api}&q={search_key}&start_time={time_before_delay}&start_from={offset}'

            response = requests.post(
                url=vk_api_with_pagination
            )
            result = response.json()['response']
            posts = result['items']
            await collect_posts(posts, all_posts, seen_posts, search_key)
            offset = result.get("next_from")

    await send_posts(context, all_posts)


async def collect_posts(
    posts: list,
    all_posts: list,
    seen_posts: set,
    search_key: str,
):
    for post in posts:
        if post['owner_id'] > 0:
            continue

        group_id = str(abs(post['owner_id']))
        post_and_group_id = f"{post['id']}_{group_id}"

        if group_id in banned_groups or post_and_group_id in seen_posts:
            continue

        seen_posts.add(post_and_group_id)

        all_posts.append({
            'id': post['id'],
            'group_id': group_id,
            'date': post['date'],
            'search_key': search_key,
        })


async def send_posts(
    context: ContextTypes.DEFAULT_TYPE,
    all_posts: list,
):
    for post in all_posts[::-1]:
        post_time = get_time_difference(post['date'])

        button = InlineKeyboardButton("🔔", callback_data="notifications_disable")
        keyboard = InlineKeyboardMarkup([[button]])

        await context.bot.send_message(
            chat_id=context.job.chat_id,
            text=f"""
Новое упоминание #{post['search_key']}
https://vk.com/wall-{post['group_id']}_{post['id']}
{post_time}
#{post['search_key']}
            """,
            reply_markup=keyboard
        )


def get_time_difference(post_time):
    current_time = datetime.now().timestamp()
    time_difference = int(current_time - post_time)

    if time_difference < 60:
        return f'{time_difference} сек. назад'
    elif time_difference > 60 and time_difference < 3600:
        return f'{time_difference // 60} мин. назад'
    elif time_difference > 3600 and time_difference < 86400:
        return f'{time_difference // 3600} ч. назад'
    elif time_difference > 86400 and time_difference < 2592000:
        return f'{time_difference // 86400} дн. назад'
    elif time_difference > 2592000 and time_difference < 31536000:
        return f'{time_difference // 2592000} мес. назад'
    elif time_difference > 31536000:
        return f'{time_difference // 31536000} г. назад'


async def notifications_disable(update: Update, context: CallbackContext):
    query = update.callback_query
    button = InlineKeyboardButton("🔕", callback_data="notifications_enable")
    keyboard = InlineKeyboardMarkup([[button]])
    await query.edit_message_reply_markup(reply_markup=keyboard)
    matches = re.search(extract_id_pattern, query.message.to_dict()['text'])
    group_id = matches.group(1)

    if group_id not in banned_groups:
        banned_groups[group_id] = True
        with open('banned_groups.json', 'w') as file:
            json.dump(banned_groups, file, indent=4)


async def notifications_enable(update: Update, context: CallbackContext):
    query = update.callback_query
    button = InlineKeyboardButton("🔔", callback_data="notifications_disable")
    keyboard = InlineKeyboardMarkup([[button]])
    await query.edit_message_reply_markup(reply_markup=keyboard)

    matches = re.search(extract_id_pattern, query.message.to_dict()['text'])
    group_id = matches.group(1)

    if group_id in banned_groups:
        del banned_groups[group_id]
        with open('banned_groups.json', 'w') as file:
            json.dump(banned_groups, file, indent=4)


if __name__ == '__main__':
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    start_handler = CommandHandler('start', start)

    notifications_disable_handler = CallbackQueryHandler(
        notifications_disable,
        "notifications_disable"
    )
    notifications_enable_handler = CallbackQueryHandler(
        notifications_enable,
        "notifications_enable"
    )

    application.add_handler(start_handler)
    application.add_handler(notifications_disable_handler)
    application.add_handler(notifications_enable_handler)

    application.run_polling()
