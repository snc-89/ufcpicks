import base64
from discord.ext import commands, tasks
from discord import File, Embed
import os
from psycopg2 import pool
import psycopg2.extras
from datetime import datetime, timedelta
import pandas as pd
import re
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from io import BytesIO
import requests
from bs4 import BeautifulSoup
import random
from time import sleep


client = commands.Bot(command_prefix='$')
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


def query_db(query, params=None):
    conn = connection.getconn()
    with conn.cursor(cursor_factory = psycopg2.extras.DictCursor) as cursor:
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)
        if query.startswith("select"):
            result = cursor.fetchall()
    conn.commit()
    connection.putconn(conn)
    if query.startswith("select"):
        return result


def get_bouts(vs_or_def, card_title):
    raw_text = get_raw_text(card_title)
    raw_text = re.search("\{\{MMAevent card\|Main card(.*\n)*\{\{MMAevent card\|Preliminary", raw_text, re.IGNORECASE)
    raw_text = raw_text.group()
    if vs_or_def == "vs.":
        matches = re.findall(f"\|.*\n\|{vs_or_def}\n\|.*", raw_text, re.IGNORECASE)
    else:
        matches = re.findall(f"\|.*\n\|{vs_or_def}\n\|.*|\|.*\n\|vs.\n\|.*\n\|Draw|\|.*\n\|vs.\n\|.*\n\|No Contest", raw_text, re.IGNORECASE)

    clean_matches = []
    for match in matches:
        for i in ['|', '[', ']', ' (c)']:
            match = match.replace(i, '')
        match = match.replace('\n', ' ')
        if match.endswith(" Draw"):
            match = match.replace(" Draw", "").replace("vs.", "Draw")
        if match.endswith("No Contest"):
            match = match.replace(" No Contest", "").replace("vs.", "No Contest")
        match = re.sub("[a-zA-Z\u0080-\uFFFF]+ \(fighter\)[a-zA-Z\u0080-\uFFFF]+ ","",match)
        match = re.sub("\s+", " ", match)
        clean_matches.append(match)
    return clean_matches


def get_raw_text(card_title):
    url = "https://en.wikipedia.org/w/api.php"
    params = {
        "action": "parse",
        "page": card_title,
        "prop": "wikitext",
        "format": "json"
    }
    raw_text = ""
    response = requests.get(url, params=params)
    if response.status_code == 200:
        raw_text = response.json()['parse']['wikitext']['*']
    else:
        print(f"request failed:     \nstatus code:        {response.status_code}\nreason:     {response.reason}")
    return raw_text


def get_timestamp_from_tapology(card_title):
    google_search = requests.get(f"http://www.google.com/search?q=tapology {card_title}&btnI", allow_redirects=True).text
    tapology_url = re.search("\"https://www.tapology.com/fightcenter/events/.*?\"", google_search).group()[1:-1]
    page = requests.get(tapology_url, headers={'User-Agent': 'a user agentff'})
    soup = BeautifulSoup(page.content, 'html.parser')
    div = soup.find('div',class_='details details_with_poster clearfix')
    timestamp = div.find(class_='header').text
    timestamp = datetime.strptime(timestamp[:-3], "%A %m.%d.%Y at %I:%M %p")
    return timestamp + timedelta(hours=16)


def get_current_card():
    card_details = get_card_details()
    card_title = card_details['title']
    date = str(get_timestamp_from_tapology(card_title))
    bouts = get_bouts("vs.", card_title.replace(' ', '_'))

    card_json = {
        'title': card_title,
        'wiki_title': card_title.replace(' ', '_'),
        'num_fights': len(bouts),
        'start_time': date,
        'fights_ended': 0,
        "html": "",
        "pick_messages": "",
        "current_state": "opening_post" 
    }
    return card_json


def get_next_card(last_card_title):
    last_card_raw_text = get_raw_text(last_card_title)
    card_title = re.search("\|followingevent= \[\[(.*)(\|.*)?\]\]", last_card_raw_text)
    card_title = card_title.group(1)
    if re.match("UFC [0-9]{3}", card_title[:7]):
        card_title = card_title[:7]
    date = str(get_timestamp_from_tapology(card_title))
    bouts = get_bouts("vs.", card_title.replace(' ', '_'))
    card_json = {
        'title': card_title,
        'wiki_title': card_title.replace(' ', '_'),
        'num_fights': len(bouts),
        'start_time': date,
        'fights_ended': 0,
        "html": "",
        "pick_messages": "",
        "current_state": "opening_post" 
    }
    return card_json


def screenshot(html_content):
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
    browser.set_window_size(1920,1080)
    html_content = base64.b64encode(html_content.encode('utf-8')).decode()
    browser.get(f"data:text/html;base64,{html_content}")
    S = lambda X: browser.execute_script('return document.body.parentNode.scroll'+X)
    browser.set_window_size(S('Width'),S('Height'))
    full_page = browser.find_element_by_tag_name('body')
    return BytesIO(full_page.screenshot_as_png)


def get_card_details():
    card_details = query_db("select * from information where id = 1 limit 1;")[0]
    if card_details['pick_messages']:
        card_details['pick_messages'] = [int(x) for x in card_details['pick_messages'].split()]
    return card_details
        

def insert_picks(card_title, bout, users, fighter):
    for user in users:
        if user != client.user:
            query_db("insert into users(username) values(%s) on conflict (username) do nothing", (str(user),))
            query_db("""insert into picks(username, card, bout, pick) values(%s,%s,%s,%s)
                on conflict (username, card, bout)
                do nothing""", (str(user), card_title, bout, fighter))


def make_html_table(card_title):
    data = query_db("select username, pick, bout from picks where card = %s;", (card_title,))
    foobar = {}
    for row in data:
        if row['username'] not in foobar:
            foobar[row['username']] = {}
        foobar[row['username']][row['bout']] = row['pick']

    bout_order = get_bouts("vs.", card_title)
    bout_order.reverse()

    html = f"""<!DOCTYPE html>
<html>
<head>
<link rel="stylesheet" href="https://stackpath.bootstrapcdn.com/bootstrap/4.5.2/css/bootstrap.min.css" integrity="sha384-JcKb8q3iqJ61gNV9KGb8thSsNjpSL0n8PARn9HuZOnIxN0hoP+VmmDGMN5t9UJ0Z" crossorigin="anonymous">
<style>
</style>
</head>
<body>
<div class="jumbotron" style="text-align: center;">
  <h1>UFC PICKS</h1>      
  <h3>{card_title}</h3>
</div>
<div class="row">
  <div class="col-md-8" align="center">
{pd.DataFrame(foobar).fillna('Blank').T[bout_order].to_html()}
  </div>
  <div class="col-md-2" align="center">
      <img id="winners_image" src="">
      <br>
      <span id="winners"></span>
  </div>  
  <div class="col-md-2" align="center">
      <img id="losers_image" src="">
      <br>
      <span id="losers"></span>
  </div>
</div>
</body>
</html>"""
    html = re.sub("\"dataframe\"", "'table'", html)
    return html


def update_column(column, value):
    if column == "pick_messages":
        value = ' '.join(str(e) for e in value)
    sql = f"""
            update information
            set {column} = %s
            where id = 1    
        """
    query_db(sql, (value,))


def update_information(card_details):
    query_db("""update information
        set
            title = %(title)s,
            wiki_title = %(wiki_title)s,
            num_fights = %(num_fights)s,
            fights_ended = %(fights_ended)s,
            start_time = %(start_time)s,
            current_state = %(current_state)s,
            pick_messages = %(pick_messages)s,
            html = %(html)s
        where id = 1""", card_details)


def update_html(winner, loser, html, winners, losers, decision_type):
    goofs = '<br>'.join(losers)
    goofs = f"<h5>LOSERS</h5>{goofs}"
    heemsters = '<br>'.join(winners)
    heemsters = f"<h5>Still in the game</h5>{heemsters}"
    if decision_type == "normal":
        html = re.sub(f"<td>{loser}</td>", f"<td class='bg-danger'>{loser}</td>", html)
        html = re.sub(f"<td>{winner}</td>", f"<td class='bg-success'>{winner}</td>", html)
    elif decision_type == "draw":
        html = re.sub(f"<td>{loser}</td>", f"<td class='bg-danger'>{loser}</td>", html)
        html = re.sub(f"<td>{winner}</td>", f"<td class='bg-danger'>{winner}</td>", html)
    elif decision_type == "no contest":
        html = re.sub(f"<td>{loser}</td>", f"<td class='bg-success'>{loser}</td>", html)
        html = re.sub(f"<td>{winner}</td>", f"<td class='bg-success'>{winner}</td>", html)

    good_image = random.choice(os.listdir("files/good"))
    good_image = f"files/good/{good_image}"
    bad_image = random.choice(os.listdir("files/bad"))
    bad_image = f"files/bad/{bad_image}"
    html = re.sub('<img id="winners_image" src=".*">', f'<img id="winners_image" src="{good_image}">', html)
    html = re.sub('<img id="losers_image" src=".*">', f'<img id="losers_image" src="{bad_image}">', html)    
    html = re.sub('<span id="losers">.*</span>', goofs, html)
    html = re.sub('<span id="winners">.*</span>', heemsters, html)
    update_column("html", html)
    return html


def update_is_correct(truth_value, title, fighter):
    query_db(f"""update picks
        set is_correct = {truth_value}
        where pick = %s and
        card = %s""", (fighter, title))


def get_winners_and_losers(card_title, fights_ended):
    winners = query_db("select distinct(username) from picks where card = %s and is_correct = TRUE group by username having count(*) = %s;", (card_title, fights_ended))
    winners = {x[0] for x in winners}
    all_users = query_db("select distinct(username) from picks where card = %s", (card_title,))
    all_users = {x[0] for x in all_users}
    losers = list(all_users - winners)
    winners = list(winners)
    return winners, losers


@tasks.loop(seconds=43200)
async def opening_post():
    print(f"{datetime.now()}    opening_post")
    card_details = get_card_details()
    if card_details['current_state'] != "opening_post":
        opening_post.stop()
        take_picks.start()
        return
    current_card = get_current_card()
    update_information(current_card)
    current_time = datetime.now()
    fight_start_time = datetime.strptime(card_details['start_time'], "%Y-%m-%d %H:%M:%S")
    if current_time >= (fight_start_time - timedelta(hours=48)):
        ctx = await client.fetch_channel(CHANNEL)
        card_title = card_details['title']
        bouts = get_bouts("vs.", card_details['wiki_title'])
        embed=Embed(title=f"UFC PICKS: {card_title}", description="react to the following messages with :one: to pick the first fighter, and react with :two: to pick the second fighter. you have until the prelims start to get your picks in. picks are not final until then. if you select both, your pick will be void.")
        await ctx.send(embed=embed)
        card_details['pick_messages'] = []
        for bout in bouts:
            sleep(121)
            fighter1, fighter2 = bout.split(" vs. ")
            string = f":one: {fighter1.strip()} vs. {fighter2.strip()} :two:"
            message = await ctx.send(string)
            await message.add_reaction('1️⃣')
            await message.add_reaction('2️⃣')
            card_details['pick_messages'].append(message.id)
        update_column("pick_messages", card_details['pick_messages'])
        update_column("current_state", "take_picks")
        opening_post.stop()
        take_picks.start()
        print("\ntransitioning to take_picks\n")


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
    if current_time >= fight_start_time:
        card_title = card_details['title']
        message_ids = card_details['pick_messages']
        ctx = await client.fetch_channel(CHANNEL)
        for message_id in message_ids:    
            message = await ctx.fetch_message(int(message_id))
            bout = message.content[5:-5].strip()
            fighter1, fighter2 = bout.split(" vs. ")
            fighter1, fighter2 = fighter1.strip(), fighter2.strip()
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
        ctx = await client.fetch_channel(CHANNEL)
        embed=Embed(title="picks taken", description="enjoy the fights")
        await ctx.send(embed=embed)
        sleep(121)
        await ctx.send(file=File(screenshot(html), 'picks.png'))
        take_picks.stop()
        detect_change.start()
        print(f'\n{"transitioning to detect_change"}\n')


@tasks.loop(seconds=300)
async def detect_change():
    print(f"{datetime.now()}    detect change")
    card_details = get_card_details()
    if card_details['current_state'] != "detect_change":
        detect_change.stop()
        opening_post.start()
        return
    fight_results = get_bouts("def.", card_details['wiki_title'])
    if len(fight_results) > card_details['fights_ended']:
        channel = await client.fetch_channel(CHANNEL)
        card_details['fights_ended'] += 1
        update_column("fights_ended", card_details['fights_ended'])
        decision_type, winner, loser = get_winner_loser(card_details, fight_results)
        winners, losers = get_winners_and_losers(card_details['title'], card_details['fights_ended'])
        if card_details['fights_ended'] == card_details['num_fights']:    # if the card is over
            next_card = get_next_card(card_details['wiki_title'])
            for w in winners:
                query_db("update users set wins = wins+1 where username = %s", (w,))
            for l in losers:    
                query_db("update users set goofs = goofs+1 where username = %s", (l,))
            update_information(next_card)
            print("\ntransitioning to opening post\n")
            detect_change.stop()
            opening_post.start()
            await leaderboard(channel)
        html = update_html(winner, loser, card_details['html'], winners, losers, decision_type)
        await channel.send(file=File(screenshot(html), 'results.png'))


def get_winner_loser(card_details, fight_results):
    if " def. " in fight_results[0]:
        winner, loser = fight_results[0].strip().split(' def. ')
        winner, loser = winner.strip(), loser.strip()
        update_is_correct("FALSE", card_details['title'], loser)
        update_is_correct("TRUE", card_details['title'], winner)
        decision_type = "normal"
    elif " Draw " in fight_results[0]:   # must be a draw
        winner, loser = fight_results[0].strip().split(' Draw ')
        winner, loser = winner.strip(), loser.strip()
        update_is_correct("FALSE", card_details['title'], loser)
        update_is_correct("FALSE", card_details['title'], winner)
        decision_type = "draw"
    else:   # must be a no contest
        winner, loser = fight_results[0].strip().split(' No Contest ')
        winner, loser = winner.strip(), loser.strip()
        update_is_correct("TRUE", card_details['title'], loser)
        update_is_correct("TRUE", card_details['title'], winner)
        decision_type = "no contest"
    return decision_type, winner, loser


@client.command()
async def leaderboard(ctx, arg=None):
    if arg == "me":
        my_stats = query_db("select username, wins, goofs from users where username = %s", (str(ctx.author),))[0]
        correct_picks = query_db("select count(*) from picks where username = %s and is_correct = TRUE", (str(ctx.author),))[0]
        embed=Embed(title=f"Stats for {ctx.author}")
        embed.add_field(name=f"**{my_stats['username']}**", value=f"> Wins: {my_stats['wins']}\n> Goofs: {my_stats['goofs']}\n> Correct picks: {correct_picks[0]}",inline=False)
        await ctx.send(embed=embed)
    elif not arg:
        leaderboard = query_db("select username, wins from users order by wins desc limit 10")    
        embed=Embed(title="UFC picks leaderboard")
        for leader in leaderboard:
            embed.add_field(name=f"**{leader['username']}**", value=f"> Wins: {leader['wins']}",inline=False)
        await ctx.send(embed=embed)

# def insert_dummy_data(n):
#     card_details = get_card_details()
#     bouts = get_bouts("vs.", card_details['wiki_title'])
#     users = [f"user{i}" for i in range(n)]        
#     for bout in bouts:
#         fighter1, fighter2 = bout.split(" vs. ")
#         fighter1, fighter2 = fighter1.strip(), fighter2.strip()
#         a, b = split_list(users)
#         insert_picks(card_details['title'], bout, a, fighter1)
#         insert_picks(card_details['title'], bout, b, fighter2)


# def split_list(users):
#     random_number = random.randrange(len(users))
#     random.shuffle(users)
#     return users[random_number:], users[:random_number]

# insert_dummy_data(20)

# TODO commands for seeing the ladderboard, number of correct picks
client.run(token)

# print(make_html_table('UFC on ESPN: Brunson vs. Holland'))