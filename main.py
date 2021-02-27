import time
from discord.ext import commands, tasks
from discord import File, Embed
import os
from psycopg2 import pool
import psycopg2.extras
import post_bouts
import json
from datetime import datetime, timedelta
import pandas as pd
import re
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from io import BytesIO


client = commands.Bot(command_prefix='!')
with open('token.txt', 'r') as f:
    token = f.read()

CHANNEL = None
DATABASE_URL = None
try:
    DATABASE_URL = os.environ['DATABASE_URL']
    connection = pool.SimpleConnectionPool(1,20, DATABASE_URL, sslmode='require')
    CHANNEL = 813751690515185685
except KeyError:
    params = {
        'database':'heem_picks',
        'host':'localhost',
        'user':'postgres',
        'password':'abc'
    }
    connection = pool.SimpleConnectionPool(1,20, **params)
    CHANNEL = 811176962172649472


conn = connection.getconn()
with conn.cursor() as cursor:
    cursor.execute("""
        CREATE table if not exists users(
            id serial PRIMARY KEY,
            username varchar unique,
            wins int default 0,
            goofs int default 0
        );
    """)
    cursor.execute("""
        CREATE table if not exists picks(
            id serial PRIMARY KEY,
            username varchar REFERENCES users(username),
            card varchar,
            bout varchar,
            pick varchar,
            is_correct boolean,
            unique(username, card, bout)
        );
    """)
conn.commit()
connection.putconn(conn)

@client.event
async def on_ready():
    opening_post.start()
    print(f'{client.user} has logged in')
    # channel = await client.fetch_channel(CHANNEL)
    # await channel.send(file=File(screenshot(os.path.abspath('result_table.html')), "results.png"))


def screenshot(html_file):
    if os.environ['HOME'] != '/home/simon':
        GOOGLE_CHROME_PATH = '/app/.apt/usr/bin/google-chrome'
        CHROMEDRIVER_PATH = '/app/.chromedriver/bin/chromedriver'
    else:
        GOOGLE_CHROME_PATH = '/usr/bin/google-chrome'
        CHROMEDRIVER_PATH = '/usr/bin/chromedriver'
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--disable-gpu')
    options.add_argument('--no-sandbox')
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-browser-side-navigation")
    options.add_argument("--disable-features=VizDisplayCompositor")
    options.binary_location = GOOGLE_CHROME_PATH
    browser = webdriver.Chrome(options=options, executable_path=CHROMEDRIVER_PATH)
    browser.get(f"file://{html_file}")
    S = lambda X: browser.execute_script('return document.body.parentNode.scroll'+X)
    browser.set_window_size(S('Width'),S('Height'))
    full_page = browser.find_element_by_tag_name('body')
    return BytesIO(full_page.screenshot_as_png)


def get_card_details():
    conn = connection.getconn()
    with conn.cursor(cursor_factory = psycopg2.extras.DictCursor) as cursor:
        cursor.execute("""
            select * from information where id = 1 limit 1;
        """)
        card_details = cursor.fetchone()
    conn.commit()
    connection.putconn(conn)
    if card_details['pick_messages']:
        card_details['pick_messages'] = [int(x) for x in card_details['pick_messages'].split()]
    return card_details


@tasks.loop(seconds=43200)
async def opening_post():
    print(f"{datetime.now()}    opening_post")
    card_details = get_card_details()
    if card_details['current_state'] != "opening_post":
        opening_post.stop()
        take_picks.start()
        return
    current_time = datetime.now()
    fight_start_time = datetime.strptime(card_details['start_time'], "%Y-%m-%d %H:%M:%S")
    if current_time >= (fight_start_time - timedelta(hours=48)):
        ctx = await client.fetch_channel(CHANNEL)
        card_title = card_details['title']
        bouts = post_bouts.get_bouts("vs.", card_details['wiki_title'])
        await ctx.send(f"UFC PICKS: {card_title}\n\nreact to the following messages with :one: to pick the first fighter, and react with :two: to pick the second fighter. you have until the prelims start to get your picks in. picks are not final until then. if you select both, your pick will be void.")
        card_details['pick_messages'] = []
        for bout in bouts:
            fighter1, fighter2 = bout.split(" vs. ")
            string = f":one: {fighter1} vs. {fighter2} :two:"
            message = await ctx.send(string)
            await message.add_reaction('1️⃣')
            await message.add_reaction('2️⃣')
            card_details['pick_messages'].append(message.id)
        update_column("pick_messages", card_details['pick_messages'])
        update_column("current_state", "take_picks")
        opening_post.stop()
        take_picks.start()
        print("\ntransitioning to take_picks\n")
        

def insert_picks(card_title, bout, users, fighter):
    conn = connection.getconn()
    with conn.cursor(cursor_factory = psycopg2.extras.DictCursor) as cursor:
        for user in users:
            if user != client.user:
                cursor.execute("insert into users(username) values(%s) on conflict (username) do nothing", (str(user),))
                cursor.execute("""insert into picks(username, card, bout, pick) values(%s,%s,%s,%s)
                    on conflict (username, card, bout)
                    do nothing""", (str(user), card_title, bout, fighter))
    conn.commit()
    connection.putconn(conn)


def make_html_table(card_title):
    conn = connection.getconn()
    with conn.cursor(cursor_factory = psycopg2.extras.DictCursor) as cursor:
        cursor.execute("""
            select username, pick, bout from picks where card = %s;
        """, (card_title,))
        data = cursor.fetchall()
    conn.commit()
    connection.putconn(conn)

    foobar = {}
    for row in data:
        if row['username'] not in foobar:
            foobar[row['username']] = {}
        foobar[row['username']][row['bout']] = row['pick']

    html = f"""
<!DOCTYPE html>
<html>
<head>
<link rel="stylesheet" href="https://stackpath.bootstrapcdn.com/bootstrap/4.5.2/css/bootstrap.min.css" integrity="sha384-JcKb8q3iqJ61gNV9KGb8thSsNjpSL0n8PARn9HuZOnIxN0hoP+VmmDGMN5t9UJ0Z" crossorigin="anonymous">
<style>
</style>
</head>
<body>
{pd.DataFrame(foobar).T.to_html()}
</body>
</html>"""

    html = re.sub("\"dataframe\"", "'table'", html)
    return html


def update_column(column, value):
    if column == "pick_messages":
        value = ' '.join(str(e) for e in value)
    conn = connection.getconn()
    sql = f"""
            update information
            set {column} = %s
            where id = 1    
        """
    with conn.cursor(cursor_factory = psycopg2.extras.DictCursor) as cursor:
        cursor.execute(sql, (value, ))
    conn.commit()
    connection.putconn(conn)


def update_information(card_details):
    conn = connection.getconn()
    with conn.cursor(cursor_factory = psycopg2.extras.DictCursor) as cursor:
        cursor.execute("""
            update information
            set
                title = %(title)s,
                wiki_title = %(wiki_title)s,
                num_fights = %(num_fights)s,
                fights_ended = %(fights_ended)s,
                start_time = %(start_time)s,
                current_state = %(current_state)s,
                pick_messages = %(pick_messages)s,
                html = %(html)s
            where id = 1
        """, card_details)
    conn.commit()
    connection.putconn(conn)

def update_html(winner, loser, html):
    html = re.sub(f"<td>{loser}</td>", f"<td class='bg-danger'>{loser}</td>", html)
    html = re.sub(f"<td>{winner}</td>", f"<td class='bg-success'>{winner}</td>", html)
    update_column("html", html)
    with open('result_table.html', 'w') as f:
        f.write(html)


@tasks.loop(seconds=300)
async def detect_change():
    print(f"{datetime.now()}    detect change")
    card_details = get_card_details()
    if card_details['current_state'] != "detect_change":
        detect_change.stop()
        opening_post.start()
        return
    fight_results = post_bouts.get_bouts("def.", card_details['wiki_title'])
    if len(fight_results) > card_details['fights_ended']:
        channel = await client.fetch_channel(CHANNEL)
        winner, loser = fight_results[0].strip().split(' def. ')
        card_details['fights_ended'] += 1
        update_column("fights_ended", card_details['fights_ended'])
        conn = connection.getconn()
        with conn.cursor(cursor_factory = psycopg2.extras.DictCursor) as cursor:
            cursor.execute("""
                update picks
                set is_correct = FALSE
                where pick = %s and
                card = %s
            """, (loser, card_details['title']))
            cursor.execute("""
                update picks
                set is_correct = TRUE
                where pick = %s and
                card = %s
            """, (winner, card_details['title']))
            cursor.execute("select distinct(username) from picks where is_correct = %s and card = %s", (False, card_details['title']))
            losers = cursor.fetchall()
            goofs = ""
            for user in losers:
                goofs += f"{user['username']}, "
            if card_details['fights_ended'] != card_details['num_fights']:    
                await channel.send(f"LOSERS: {goofs[:-2]}")
            else:
                await channel.send(f"EVENT OVER. LOSERS: {goofs[:-2]}")
                update_html(winner, loser, card_details['html'])
                await channel.send(screenshot(os.path.abspath('result_table.html')), 'results.png')
                next_card = post_bouts.get_next_card(card_details['wiki_title'])
                next_card['html'] = ""
                next_card['pick_messages'] = ""
                next_card['current_state'] = "opening_post"
                update_information(next_card)
                detect_change.stop()
                opening_post.start()
                print("\ntransitioning to opening post\n")
        conn.commit()
        connection.putconn(conn)
        update_html(winner, loser, card_details['html'])
        await channel.send(screenshot(os.path.abspath('result_table.html')), 'results.png')


@tasks.loop(seconds=3600)
async def take_picks():
    print(f"{datetime.now()}    take_picks")
    card_details = get_card_details()
    if card_details['current_state'] != "take_picks":
        take_picks.stop()
        detect_change.start()
        return
    current_time = datetime.now()
    fight_start_time = datetime.strptime(card_details['start_time'], "%Y-%m-%d %H:%M:%S")
    if current_time < fight_start_time and current_time >= (fight_start_time - timedelta(hours=1)):
        card_title = card_details['title']
        message_ids = card_details['pick_messages']
        ctx = await client.fetch_channel(CHANNEL)
        for message_id in message_ids:    
            message = await ctx.fetch_message(int(message_id))
            bout = message.content[5:-5].strip()
            fighter1, fighter2 = bout.split(" vs. ")
            for reaction in message.reactions:
                if reaction.emoji == '1️⃣':
                    one_react_users = list(await reaction.users().flatten())
                elif reaction.emoji == '2️⃣':
                    two_react_users = list(await reaction.users().flatten())
            in_both_lists = set(one_react_users) & set(two_react_users)
            one_react_users = list(set(one_react_users) - in_both_lists)
            two_react_users = list(set(two_react_users) - in_both_lists)
            insert_picks(card_title, bout, one_react_users, fighter1)
            insert_picks(card_title, bout, two_react_users, fighter2)
        html = make_html_table(card_details['title'])
        update_column("html", html)
        update_column("current_state", "detect_change")
        take_picks.stop()
        detect_change.start()
        ctx = await client.fetch_channel(CHANNEL)
        embed=Embed(title="picks taken", description="enjoy the fights")
        await ctx.send(embed=embed)
        print(f'\n{"transitioning to detect_change"}\n')


client.run(token)
