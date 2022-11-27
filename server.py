import asyncio
import json
import os
import pathlib
import typing
import weakref

import aiohttp
import aiohttp_jinja2
import chess
import chess.engine
import jinja2
from aiohttp import web

app = web.Application()
app['websockets'] = weakref.WeakSet()
app['chessgames'] = weakref.WeakSet()

basepath = pathlib.Path(__file__).parent.absolute()
print(f"Loading templates from {basepath}")
aiohttp_jinja2.setup(app, loader=jinja2.FileSystemLoader(basepath))


@aiohttp_jinja2.template('index.html')
async def index(request: web.Request):
    return {}


async def handle_socket(request: web.Request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    request.app['websockets'].add(ws)
    engine: typing.Optional[chess.engine.UciProtocol] = None
    try:
        board = chess.Board()
        transport, engine = await chess.engine.popen_uci('stockfish')
        await ws.send_json(dict(event="ready", player_color='white', board=board.fen()))

        async def send_to_user(message: dict):
            message['board'] = board.fen()
            message['legalmoves'] = [m.uci() for m in board.legal_moves]
            await ws.send_json(message)

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
                    board.push(user_move)
                    await send_to_user(dict(event="accept_move", lastmove=user_move.uci()))
                    candidates: typing.List[chess.engine.InfoDict] = await engine.analyse(
                        board, chess.engine.Limit(time=1), multipv=100)

                    def appraise(sit: chess.engine.InfoDict):
                        score: chess.engine.PovScore = sit['score']
                        numscore = score.relative.score(mate_score=100000)
                        return abs(numscore)

                    if board.is_game_over():
                        await send_to_user(dict(event="game_over", result=board.result()))
                        break

                    most_drawy_move: chess.engine.InfoDict = min(candidates, key=appraise)
                    my_move: chess.Move = (most_drawy_move['pv'][0])
                    board.push(my_move)
                    await send_to_user(dict(
                        event="computer_moved",
                        lastmove=my_move.uci(),
                    ))
                    if board.is_game_over(claim_draw=True):
                        await send_to_user(dict(event="game_over", result=board.result(claim_draw=True)))
                        break

    finally:
        if not ws.closed:
            await ws.close()
        print("Cleaning up websocket")
        request.app['websockets'].discard(ws)
        if engine is not None:
            asyncio.create_task(engine.quit())
    return ws


async def on_shutdown(app):
    print("On shutdown called")
    for ws in set(app['websockets']):
        ws: web.WebSocketResponse
        await ws.close(code=aiohttp.WSCloseCode.GOING_AWAY,
                       message=b'Server shutdown')
        print("Closing websocket")


async def handle_status(request: web.Request):
    return web.json_response(dict(
        all_tasks=len(asyncio.all_tasks(asyncio.get_running_loop())),
        websockets=len(request.app['websockets']),
        games=len(request.app['chessgames']),
    ))


app.add_routes([
    web.get('/', index),
    web.get('/socket', handle_socket),
    web.get('/status', handle_status),
])

app.on_shutdown.append(on_shutdown)

if __name__ == '__main__':
    web.run_app(app, port=int(os.environ.get('PORT', '3000')))
