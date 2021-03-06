import requests
import re
from bs4 import BeautifulSoup
from datetime import datetime, timedelta


def get_bouts(vs_or_def, card_title):
    raw_text = get_raw_text(card_title)
    raw_text = re.search("{{MMAevent card\|Main card(.*\n)*{{MMAevent card\|Preliminary", raw_text).group()
    if vs_or_def == "vs.":
        matches = re.findall(f"\|.*\n\|{vs_or_def}\n\|.*", raw_text)
    else:
        matches = re.findall(f"\|.*\n\|{vs_or_def}\n\|.*|\|.*\n\|vs.\n\|.*\n\|Draw", raw_text)

    clean_matches = []
    for match in matches:
        for i in ['|', '[', ']', ' (c)']:
            match = match.replace(i, '')
        match = match.replace('\n', ' ')
        if match.endswith(" Draw"):
            match = match.replace(" Draw", "").replace("vs.", "Draw")
        match = re.sub("[a-zA-Z\u0080-\uFFFF]+ \(fighter\)[a-zA-Z\u0080-\uFFFF]+ ","",match)
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


def get_next_card(last_card_title):
    last_card_raw_text = get_raw_text(last_card_title)
    card_title = re.search("\|followingevent= \[\[(.*)(\|.*)?\]\]", last_card_raw_text).group(1)
    if re.match("UFC [0-9]{3}", card_title[:7]):
        card_title = card_title[0:7]
    date = str(get_timestamp_from_tapology(card_title))
    bouts = get_bouts("vs.", card_title.replace(' ', '_'))

    card_json = {
        'title': card_title,
        'wiki_title': card_title.replace(' ', '_'),
        'num_fights': len(bouts),
        'start_time': date,
        'fights_ended': 0,
    }
    return card_json
