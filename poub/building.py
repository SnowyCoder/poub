import logging
import re
import time
import urllib.parse
from dataclasses import dataclass
from datetime import date
from typing import Optional, NamedTuple, Tuple

import requests
from bs4 import BeautifulSoup

import timetable
from timeutils import TimeRange


@dataclass
class EdifPresences:
    edif: str
    name: str
    turni: list[tuple[TimeRange, str]]


class BuildingTurn(NamedTuple):
    room: str
    trange: TimeRange
    book_link: str


CACHE = {}  # type: dict[str, Tuple[date, list[EdifPresences]]]


def build_url(edif):
    return 'https://www.unimore.it/covid19/aulexedificio.html?e=' + urllib.parse.quote(edif)


def normalize_name(name: str) -> str:
    tokens = name.lower().split()
    tokens.sort()
    return ' '.join(tokens)


def parse_table(soup: BeautifulSoup) -> list[EdifPresences]:
    TURN_PREFIX = 'Turno Aula '

    tab = soup.find('table', {'class': 'tabella-responsiva'})
    res = []
    for row in tab.find_all('tr', recursive=False):
        datas = row.find_all('td')
        edif = datas[1].text
        name = normalize_name(datas[2].text)
        turni = [(TimeRange.parse(x.text.removeprefix(TURN_PREFIX)), x['href']) for x in
                 datas[3].find_all('a') if x.text.startswith(TURN_PREFIX)]
        res.append(EdifPresences(
            edif, name, turni
        ))
    return res


def _download_building(edif: str, today: date) -> list[EdifPresences]:
    MONTHS = ['Gennaio', 'Febbraio', 'Marzo', 'Aprile', 'Maggio',
              'Giugno', 'Luglio', 'Agosto', 'Settembre', 'Ottobre',
              'Novembre', 'Dicembre']
    datestr = f'{today.day} {MONTHS[today.month - 1]} {today.year}'

    while True:
        retry = 0
        req = None
        while retry < 3:
            url = build_url(edif)
            req = requests.get(url, timeout=120)
            if req.status_code != 200:
                logging.error("Failed to load for edif: " + edif + ": " + str(req))
                retry += 1
                continue
            break
        if req.status_code != 200:
            raise Exception('Error contacting site')
        html = req.text
        if datestr in html:
            break
        else:
            time.sleep(0.2)

    return parse_table(BeautifulSoup(html, features='lxml'))


def get_presences_from_building(edif: str) -> list[EdifPresences]:
    today = date.today()
    if edif not in CACHE or CACHE[edif][0] != today:
        CACHE[edif] = (today, _download_building(edif, today))
    return CACHE[edif][1]


def get_link_from_fim_time_table(cell: timetable.TableCell) -> Optional[BuildingTurn]:
    edif = re.search(r'[A-Z][0-9.]+[A-Za-z]*', cell.room).group(0)
    edif_char = edif[0]

    if edif_char == 'M':
        # Math
        edif = 'MO-18'
    elif edif_char == 'L':
        # Physics
        edif = 'MO-17'
    else:
        return None

    pres = get_presences_from_building(edif)

    room_name = normalize_name(cell.room)

    for p in pres:
        if p.name != room_name:
            continue
        for (orario, link) in p.turni:
            if cell.trange.overlaps(orario):
                return BuildingTurn(cell.room, orario, link)

    return None


def clear_cache():
    global CACHE
    CACHE = {}

