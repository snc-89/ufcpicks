import requests
import re
import json


def get_bouts(vs_or_def, card_title):
    raw_text = get_raw_text(card_title)
    raw_text = re.search("{{MMAevent card\|Main card(.*\n)*{{MMAevent card\|Preliminary", raw_text).group()
    matches = re.findall(f"\|.*\n\|{vs_or_def}\n\|.*", raw_text)

    clean_matches = []
    for match in matches:
        for i in ['|', '[', ']', ' (c)']:
            match = match.replace(i, '')
        match = match.replace('\n', ' ')
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
        exit()
    return raw_text


def get_next_card(last_card_title):
    last_card_raw_text = get_raw_text(last_card_title)
    card_title = re.search("\|followingevent= \[\[(.*)\]\]", last_card_raw_text).group(1)
    next_card_raw_text = get_raw_text(card_title)
    date = re.search("\|date= \{\{start date\|(.*)\}\}", next_card_raw_text).group(1).replace("|","-")
    date = f"{date} 12:00:00"
    bouts = get_bouts("vs.", card_title.replace(' ', '_'))

    card_json = {
        'title': card_title,
        'wiki title': card_title.replace(' ', '_'),
        'num fights': len(bouts),
        'start time': date,
        'fights ended': 0
    }

    return card_json