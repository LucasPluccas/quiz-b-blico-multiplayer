from __future__ import annotations

import uuid
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.app.ws.manager import RoomManager
from backend.app.ws.messages import WSIn, WSOut, err


app = FastAPI(title="Quiz Bíblico Multiplayer (MVP)")

# CORS para facilitar frontend local / codespaces
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # em produção, restrinja
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

manager = RoomManager()


@app.get("/health")
def health():
    return JSONResponse({"status": "ok"})


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await manager.connect(websocket)

    # player_id fica associado ao socket; o front manda ou geramos
    player_id: str | None = None

    try:
        # handshake simples: client pode mandar ?playerId=...
        query_player_id = websocket.query_params.get("playerId")
        player_id = query_player_id or str(uuid.uuid4())
        await manager.register_socket(player_id, websocket)

        # informe ao cliente o playerId definitivo
        await websocket.send_json({"type": "room_joined", "payload": {"playerId": player_id}})

        while True:
            raw = await websocket.receive_json()
            msg = WSIn(**raw)

            if msg.action == "ping":
                await websocket.send_json(WSOut(type="pong", payload={}).model_dump())
                continue

            if msg.action == "create_room":
                name = str(msg.payload.get("name", "")).strip()
                if not name:
                    await websocket.send_json(err("INVALID_NAME", "Informe seu nome.").model_dump())
                    continue

                room = await manager.create_room(player_id, name)
                await websocket.send_json(
                    WSOut(type="room_created", payload={"playerId": player_id, "room": room.to_public_dict()}).model_dump()
                )
                await manager.broadcast_room_state(room.pin)
                continue

            if msg.action == "join_room":
                name = str(msg.payload.get("name", "")).strip()
                pin = str(msg.payload.get("pin", "")).strip()
                if not name:
                    await websocket.send_json(err("INVALID_NAME", "Informe seu nome.").model_dump())
                    continue
                if not pin.isdigit() or len(pin) < 4:
                    await websocket.send_json(err("INVALID_PIN", "PIN inválido.").model_dump())
                    continue

                try:
                    room = await manager.join_room(player_id, name, pin)
                except ValueError as e:
                    code = str(e)
                    mapping = {
                        "ROOM_NOT_FOUND": "Sala não encontrada.",
                        "ROOM_ALREADY_STARTED": "A partida já começou.",
                        "ROOM_FULL": "Sala cheia (máximo 4 jogadores).",
                    }
                    await websocket.send_json(err(code, mapping.get(code, "Erro ao entrar na sala.")).model_dump())
                    continue

                await websocket.send_json(
                    WSOut(type="room_joined", payload={"playerId": player_id, "room": room.to_public_dict()}).model_dump()
                )
                await manager.broadcast_room_state(pin)
                continue

            if msg.action == "leave_room":
                await manager.leave_room(player_id)
                await websocket.send_json(WSOut(type="room_state", payload={"left": True}).model_dump())
                continue

            if msg.action == "start_game":
                try:
                    room = await manager.start_game(player_id)
                except ValueError as e:
                    code = str(e)
                    mapping = {
                        "NOT_IN_ROOM": "Você não está em uma sala.",
                        "ROOM_NOT_FOUND": "Sala não encontrada.",
                        "NOT_HOST": "Apenas o host pode iniciar.",
                        "NOT_ENOUGH_PLAYERS": "Não há jogadores suficientes.",
                    }
                    await websocket.send_json(err(code, mapping.get(code, "Erro ao iniciar.")).model_dump())
                    continue

                await manager.broadcast_room_state(room.pin)
                await manager.broadcast_game_started(room.pin)
                continue

            await websocket.send_json(err("UNKNOWN_ACTION", "Ação desconhecida.").model_dump())

    except WebSocketDisconnect:
        await manager.disconnect(player_id)
    except Exception:
        # em MVP, evitar quebrar o servidor; em produção, log detalhado
        await manager.disconnect(player_id)
