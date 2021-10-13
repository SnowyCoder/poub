from typing import NamedTuple


def parse_time(data: str) -> int:
    h, m = data.split(':', 1)
    return int(h) * 60 + int(m)


def print_time(x: int) -> str:
    return f"{x // 60:02d}:{x % 60:02d}"


class TimeRange(NamedTuple):
    start: int
    end: int

    def overlaps(self, other: 'TimeRange') -> bool:
        return self[1] > other[0] and self[1] > other[0]

    @staticmethod
    def parse(data: str) -> 'TimeRange':
        s, e = data.split('-', 1)
        return TimeRange(parse_time(s), parse_time(e))

    def __str__(self) -> str:
        return print_time(self[0]) + '-' + print_time(self[1])
