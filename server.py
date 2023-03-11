import asyncio
import datetime
import json
import os
import pathlib
import typing
from collections import namedtuple

import aiohttp
import aiohttp_jinja2
import chess
import chess.engine
import chess.pgn
import jinja2
from aiohttp import web

RunningGame = namedtuple('RunningGame', 'websocket pgn')

app = web.Application()
app['games'] = set()
app['game_count'] = 0

basepath = pathlib.Path(__file__).parent.absolute()
print(f"Loading templates from {basepath}")
aiohttp_jinja2.setup(app, loader=jinja2.FileSystemLoader(basepath))


@aiohttp_jinja2.template('index.html')
async def index(request: web.Request):
    return {}


async def handle_socket(request: web.Request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    pgn = chess.pgn.GameBuilder()
    app['game_count'] += 1
    chess.pgn.Game()
    pgn.begin_game()
    pgn.begin_headers()
    pgn.visit_header("White", "Player")
    pgn.visit_header("Black", "Giri, Anish")
    pgn.visit_header("Date", datetime.date.today().strftime('%Y.%m.%d'))
    pgn.visit_header("Round", "-")
    pgn.visit_header("Site", "https://chess.nea.moe")
    pgn.end_headers()
    running_game = RunningGame(ws, pgn)

    request.app['games'].add(running_game)
    engine: typing.Optional[chess.engine.UciProtocol] = None

    try:
        board = chess.Board()
        transport, engine = await chess.engine.popen_uci('stockfish')

        async def send_to_user(message: dict):
            message['board'] = board.fen()
            message['legalmoves'] = [m.uci() for m in board.legal_moves]
            await ws.send_json(message)

        await send_to_user(dict(event="ready", player_color='white'))

        async def check_outcome():
            outcome = board.outcome(claim_draw=True)
            if outcome:
                pgn.visit_result(outcome.result())
                pgn.visit_header("Termination", "normal")
                pgn.end_game()
                pgn_str = pgn.result().accept(chess.pgn.StringExporter())
                await send_to_user(dict(event="pgn", pgn=pgn_str))
                await send_to_user(dict(event="game_over", result=outcome.result()))

            return bool(outcome)

        async for msg in ws:
            msg: aiohttp.WSMessage
            if msg.type == aiohttp.WSMsgType.TEXT:
                req = json.loads(msg.data)
                m = req["method"]
                if m == "move":
                    try:
                        user_move = chess.Move.from_uci(req['params']['move'])
                    except ValueError:
                        await send_to_user(dict(event="reject_move"))
                        continue

                    if user_move not in board.legal_moves:
                        await send_to_user(dict(event="reject_move"))
                        continue
                    pgn.visit_move(board, user_move)
                    board.push(user_move)
                    await send_to_user(dict(event="accept_move", lastmove=user_move.uci()))
                    candidates: typing.List[chess.engine.InfoDict] = await engine.analyse(
                        board, chess.engine.Limit(time=1), multipv=100)

                    def appraise(sit: chess.engine.InfoDict):
                        score: chess.engine.PovScore = sit['score']
                        numscore = score.relative.score(mate_score=100000)
                        return abs(numscore)

                    if await check_outcome():
                        break

                    most_drawy_move: chess.engine.InfoDict = min(candidates, key=appraise)
                    my_move: chess.Move = (most_drawy_move['pv'][0])
                    pgn.visit_move(board, my_move)
                    board.push(my_move)
                    await send_to_user(dict(
                        event="computer_moved",
                        lastmove=my_move.uci(),
                    ))
                    if await check_outcome():
                        break
    finally:
        if not ws.closed:
            await ws.close()
        print("Cleaning up websocket")
        request.app['games'].discard(running_game)
        if engine is not None:
            asyncio.create_task(engine.quit())
    return ws


async def on_shutdown(app):
    print("On shutdown called")
    for game in set(app['games']):
        game: RunningGame
        ws: web.WebSocketResponse = game.websocket
        game.pgn.end_game()
        pgn_str = game.pgn.result().accept(chess.pgn.StringExporter())
        await ws.send_json(dict(event="pgn", pgn=pgn_str))
        await ws.close(code=aiohttp.WSCloseCode.GOING_AWAY,
                       message=b'Server shutdown')
        print("Closing websocket")


async def handle_status(request: web.Request):
    return web.json_response(dict(
        all_tasks=len(asyncio.all_tasks(asyncio.get_running_loop())),
        games=len(request.app['games']),
        total_recent_games=app['game_count'],
    ))


app.add_routes([
    web.get('/', index),
    web.get('/socket', handle_socket),
    web.get('/status', handle_status),
])

app.on_shutdown.append(on_shutdown)

if __name__ == '__main__':
    web.run_app(app, port=int(os.environ.get('PORT', '3000')))
