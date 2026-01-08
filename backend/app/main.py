from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from backend.app.ws.manager import RoomManager
from backend.app.ws.messages import WSIn, WSOut, err

app = FastAPI(title="Quiz Bíblico Multiplayer (MVP)")

# CORS (para facilitar durante desenvolvimento)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # em produção, restrinja para seu domínio
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

manager = RoomManager()

# ---------------------------
# Servir frontend (raiz /)
# ---------------------------
# Arquivo atual: .../backend/app/main.py
# parents[2] -> raiz do repo
ROOT_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = ROOT_DIR / "frontend"

# Servir arquivos estáticos (css/js) em /static
# Importante: no seu index.html use /static/styles.css e /static/app.js
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
def home():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/health")
def health():
    return JSONResponse({"status": "ok"})


# ---------------------------
# WebSocket
# ---------------------------
@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await manager.connect(websocket)

    player_id: str | None = None

    try:
        # playerId pode vir como querystring; se não, geramos
        query_player_id = websocket.query_params.get("playerId")
        player_id = query_player_id or str(uuid.uuid4())

        await manager.register_socket(player_id, websocket)

        # handshake: informa ao cliente qual playerId ele tem
        await websocket.send_json(
            WSOut(type="room_joined", payload={"playerId": player_id}).model_dump()
        )

        while True:
            raw = await websocket.receive_json()
            msg = WSIn(**raw)

            # Ping
            if msg.action == "ping":
                await websocket.send_json(WSOut(type="pong", payload={}).model_dump())
                continue

            # Criar sala
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

            # Entrar na sala
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

            # Sair da sala
            if msg.action == "leave_room":
                await manager.leave_room(player_id)
                await websocket.send_json(WSOut(type="room_state", payload={"left": True}).model_dump())
                continue

            # Iniciar jogo (host)
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

                # Atualiza lobby e informa início
                pin = room.pin
                await manager.broadcast_room_state(pin)
                await manager.broadcast_to_room(pin, {"type": "game_started", "payload": room.to_public_dict()})
                # A pergunta (question) é enviada pelo manager.start_game() -> start_round()
                continue

            # Responder pergunta
            if msg.action == "answer":
                try:
                    option_index = int(msg.payload.get("optionIndex"))
                except Exception:
                    await websocket.send_json(err("INVALID_ANSWER", "Resposta inválida.").model_dump())
                    continue

                try:
                    await manager.submit_answer(player_id, option_index)
                except ValueError as e:
                    code = str(e)
                    mapping = {
                        "NOT_IN_ROOM": "Você não está em uma sala.",
                        "NO_ACTIVE_ROUND": "Não há rodada ativa.",
                        "ALREADY_ANSWERED": "Você já respondeu.",
                        "TIME_OVER": "Tempo esgotado.",
                    }
                    await websocket.send_json(err(code, mapping.get(code, "Erro ao responder.")).model_dump())
                continue

            # Ação desconhecida
            await websocket.send_json(err("UNKNOWN_ACTION", "Ação desconhecida.").model_dump())

    except WebSocketDisconnect:
        await manager.disconnect(player_id)
    except Exception:
        await manager.disconnect(player_id)
