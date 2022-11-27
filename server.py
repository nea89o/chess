import asyncio
import json
import random
import typing
import weakref

import aiohttp
import chess
import chess.engine
from aiohttp import web

app = web.Application()
app['websockets'] = weakref.WeakSet()
app['chessgames'] = weakref.WeakSet()


async def index(request: web.Request) -> web.Response:
    return web.Response(text="Welcome to the chess hell backend!")


async def handle_socket(request: web.Request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    request.app['websockets'].add(ws)
    engine: typing.Optional[chess.engine.UciProtocol] = None
    try:
        board = chess.Board()
        transport, engine = await chess.engine.popen_uci('stockfish')
        await ws.send_json(dict(event="ready", player_color='white', board=board.fen()))
        async for msg in ws:
            msg: aiohttp.WSMessage
            if msg.type == aiohttp.WSMsgType.TEXT:
                req = json.loads(msg.data)
                m = req["method"]
                if m == "move":
                    user_move = chess.Move.from_uci(req['params']['move'])
                    if user_move not in board.legal_moves:
                        await ws.send_json(dict(
                            event="reject_move",
                            board=board.fen(),
                        ))
                        continue
                    board.push(user_move)
                    await ws.send_json(dict(
                        event='accept_move',
                        board=board.fen(),
                        lastmove=user_move.uci(),
                    ))
                    await asyncio.sleep(1.5)
                    # candidates = await engine.analyse(board, chess.engine.Limit(time=1), multipv=100)
                    my_move: chess.Move = random.choice(list(board.legal_moves))
                    board.push(my_move)
                    await ws.send_json(dict(
                        event="computer_moved", board=board.fen(),
                        lastmove=my_move.uci(),
                    ))

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
    web.run_app(app, )
