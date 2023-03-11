import datetime
import json


class PgnWriter:

    def __init__(self):
        self.pgn_string = ""

    def visit_tag(self, label: str, value: str):
        self.pgn_string += "[" + label + " " + json.dumps(str(value)) + "]"

    def visit_event(self, event_name: str):
        self.visit_tag("Event", event_name)

    def visit_site(self, site: str):
        self.visit_tag("Site", site)

    def visit_start_time(self, date: datetime.datetime):
        self.visit_tag("Date", date.strftime('%Y.%m.%d'))
        self.visit_tag("Time", date.strftime('%H:%M:%S'))

    def visit_is_online(self, is_online: bool):
        self.visit_tag("Mode", "ICS" if is_online else "OTB")

    def visit_fen(self, fen: str):
        self.visit_tag("FEN", fen)

    def visit_round(self, round: int | str):
        self.visit_tag("Round", str(round))

    def visit_players(self, white: str, black: str):
        self.visit_tag("White", white)
        self.visit_tag("Black", black)


