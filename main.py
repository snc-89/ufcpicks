from discord.ext import commands, tasks
from discord import File
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
    channel = await client.fetch_channel(CHANNEL)
    await channel.send(file=File(screenshot('result_table.html'), "results.png"))


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
    # options.add_argument("--disable-browser-side-navigation")
    # options.add_argument("--disable-features=VizDisplayCompositor")
    options.binary_location = GOOGLE_CHROME_PATH
    browser = webdriver.Chrome(options=options, executable_path=CHROMEDRIVER_PATH)
    browser.get(f"file://{html_file}")
    S = lambda X: browser.execute_script('return document.body.parentNode.scroll'+X)
    browser.set_window_size(S('Width'),S('Height'))
    full_page = browser.find_element_by_tag_name('body')
    return BytesIO(full_page.screenshot_as_png)


@tasks.loop(seconds=43200)
async def opening_post():
    print(f"{datetime.now()}    opening_post")
    with open('card_details.json', 'r') as f:
        card_details = json.load(f)
    current_time = datetime.now()
    fight_start_time = datetime.strptime(card_details['start time'], "%Y-%m-%d %H:%M:%S")
    if current_time >= (fight_start_time - timedelta(hours=48)):
        ctx = await client.fetch_channel(CHANNEL)
        card_title = card_details['title']
        bouts = post_bouts.get_bouts("vs.", card_details['wiki title'])
        await ctx.send(f"UFC PICKS: {card_title}\n\nreact to the following messages with :one: to pick the first fighter, and react with :two: to pick the second fighter. you have until the prelims start to get your picks in. picks are not final until then. if you select both, your pick will be void.")
        card_details['pick messages'] = []
        for bout in bouts:
            fighter1, fighter2 = bout.split(" vs. ")
            string = f":one: {fighter1} vs. {fighter2} :two:"
            message = await ctx.send(string)
            await message.add_reaction('1️⃣')
            await message.add_reaction('2️⃣')
            card_details['pick messages'].append(message.id)
        with open('card_details.json', 'w') as f:
            json.load(card_details, f)
        opening_post.stop()
        take_picks.start()
        print("transitioning to take_picks")
        

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
        </html>
        """

        html = re.sub("\"dataframe\"", "'table'", html)
        return html


def update_html(winner, loser):
    with open('result_table.html', 'r') as f:
        html = f.read()
    html = re.sub(f"<td>{loser}</td>", f"<td class='bg-danger'>{loser}</td>", html)
    html = re.sub(f"<td>{winner}</td>", f"<td class='bg-success'>{winner}</td>", html)
    with open('result_table.html', 'w') as f:
        f.write(html)


@tasks.loop(seconds=300)
async def detect_change():
    print(f"{datetime.now()}    detect change")
    with open('card_details.json', 'r') as f:
        card_details = json.load(f)
    fight_results = post_bouts.get_bouts("def.", card_details['wiki title'])
    if len(fight_results) > card_details['fights ended']:
        channel = await client.fetch_channel(CHANNEL)
        winner, loser = fight_results[0].strip().split(' def. ')
        card_details['fights ended'] += 1
        with open('card_details.json', 'w') as f:
            json.dump(card_details, f)
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
            if card_details['fights ended'] != card_details['num fights']:    
                await channel.send(f"LOSERS: {goofs[:-2]}")
            else:
                await channel.send(f"EVENT OVER. LOSERS: {goofs[:-2]}")
                next_card = post_bouts.get_next_card(card_details['wiki title'])
                with open('card_details.json', 'w') as f:
                    json.dump(next_card, f)
        conn.commit()
        connection.putconn(conn)
        update_html(winner, loser)
        await channel.send(screenshot('result_table.html'), 'results.png')
        detect_change.stop()
        opening_post.start()
        print("transitioning to opening post")


@tasks.loop(seconds=3600)
async def take_picks():
    print(f"{datetime.now()}    take_picks")
    with open('card_details.json', 'r') as f:
        card_details = json.load(f)
    current_time = datetime.now()
    fight_start_time = datetime.strptime(card_details['start time'], "%Y-%m-%d %H:%M:%S")
    if current_time < fight_start_time and current_time >= (fight_start_time - timedelta(hours=1)):
        card_title = card_details['title']
        message_ids = card_details['pick messages']
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
        with open('result_table.html', 'w') as f:
            f.write(html)
        take_picks.stop()
        detect_change.start()
        print(f'\n{"transitioning to detect_change"}\n')


client.run(token)

