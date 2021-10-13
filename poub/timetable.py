import re
from dataclasses import dataclass
from datetime import datetime
from multiprocessing.dummy import Pool
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from lxml import html
from lxml.html import HtmlElement

from timeutils import TimeRange

DOCENTI_INDEX_URL = 'https://www.orariolezioni.unimore.it//Orario/Dipartimento_di_Scienze_Fisiche-_Informatiche_e_Matematiche/2021-2022/1641/index.html'


@dataclass
class TableCell:
    trange: TimeRange
    name: str
    teacher: str
    room: str


@dataclass
class OrarioDocenti:
    date: datetime
    # {(teacher, weekday): Lecture}
    data: dict[(str, str), list[TableCell]]


def normalize_teacher_name(name: str) -> str:
    return ' '.join(sorted(name.lower().split(' ')))


def update_docenti(last_time: Optional[datetime]) -> Optional[OrarioDocenti]:
    data = requests.get(DOCENTI_INDEX_URL).content
    page = html.fromstring(data)

    dt = re.search(r'\d+/\d+/\d+ \d+:\d+', page.xpath('//td[contains(text(), "Pubblicato il")]')[0].text).group(0)
    dt = datetime.strptime(dt, '%d/%m/%Y %H:%M')

    if last_time is not None and dt <= last_time:
        return None

    profs = page.xpath('//a[contains(text(), "Orario docenti")]/../ul/li/ul/li/a')
    profs = [(normalize_teacher_name(x.text.lower()), urljoin(DOCENTI_INDEX_URL, x.get('href'))) for x in profs]

    def par(teacher: str, url: str) -> {(str, str): list[TableCell]}:
        page = html.fromstring(requests.get(url).content)
        grid = page.xpath('//table[contains(@class, "timegrid")]')[0]
        table = _join_table(_extract_table(grid))
        # Add missing teacher info
        for y in table.values():
            for x in y:
                x.teacher = teacher
        return {
            (teacher, day): cells for day, cells in table.items() if len(cells) > 0
        }

    results = Pool(8).starmap(par, profs)
    combined = {k: v for d in results for k, v in d.items()}

    return OrarioDocenti(dt, combined)


def _extract_table(grid: HtmlElement) -> Dict[str, List[TableCell]]:
    days = [x.text for x in grid.xpath('./tr[1]/td')[1:]]
    res = {day: [] for day in days}

    for row in grid.xpath('./tr')[1:]:
        cells = row.xpath('./td')
        trange = TimeRange.parse(cells[0].text)
        # print(hour)
        for day, cell in zip(days, cells[1:]):
            data = cell.xpath('.//table//td[contains(@class, "subject_pos")]')
            if len(data) == 0:
                continue
            name, teacher, room = None, None, None

            for d in data:
                # The name is always present without any link
                # then there might be a room link or a prof link (or both)
                links = d.xpath('.//a')
                if len(links) == 0:
                    name = d.text
                    continue
                href = links[0].get('href')

                if href.startswith('../Aule'):
                    room = links[0].text
                elif href.startswith('../Docenti'):
                    teacher = normalize_teacher_name(links[0].text)

            res[day].append(TableCell(trange, name, teacher, room))

    return res


def _join_table(table: Dict[str, List[TableCell]]) -> Dict[str, List[TableCell]]:
    def dedup_day(cells: list[TableCell]):
        res = []
        for cell in cells:
            if len(res) == 0:
                res.append(cell)
                continue

            o = res[-1]
            can_join = (o.name == cell.name and o.room == cell.room and
                        o.teacher == cell.teacher and o.trange[1] == cell.trange[0])
            if can_join:
                o.trange = TimeRange(o.trange[0], cell.trange[1])
            else:
                res.append(cell)

        return res

    return {day: dedup_day(entries) for day, entries in table.items()}


def get_lectures(tab: OrarioDocenti, day: str, lectures: list[tuple[str, str]]) -> list[TableCell]:
    res = []

    for (teacher, lname) in lectures:
        teacher = normalize_teacher_name(teacher)
        lname = lname.lower()
        if (teacher, day) not in tab.data:
            continue
        cells = tab.data[(teacher, day)]
        for x in cells:
            if x.name.lower() == lname:
                res.append(x)

    return res


if __name__ == '__main__':
    print(update_docenti(None))

