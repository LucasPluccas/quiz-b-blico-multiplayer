from __future__ import annotations

import secrets
import string
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from fastapi import WebSocket


MAX_PLAYERS = 4


def _generate_pin(length: int = 6) -> str:
    alphabet = string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


@dataclass
class Player:
    player_id: str
    name: str
    is_host: bool = False


@dataclass
class Room:
    pin: str
    host_player_id: str
    players: Dict[str, Player] = field(default_factory=dict)
    started: bool = False

    def to_public_dict(self) -> dict:
        return {
            "pin": self.pin,
            "started": self.started,
            "maxPlayers": MAX_PLAYERS,
            "players": [
                {"id": p.player_id, "name": p.name, "isHost": p.is_host}
                for p in self.players.values()
            ],
            "count": len(self.players),
        }


class RoomManager:
    """
    Em memória (MVP).
    Para produção, você migraria isso para Redis/PostgreSQL.
    """

    def __init__(self) -> None:
        self.rooms: Dict[str, Room] = {}
        self.sockets: Dict[str, WebSocket] = {}           # player_id -> websocket
        self.player_room: Dict[str, str] = {}             # player_id -> pin

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()

    async def disconnect(self, player_id: Optional[str]) -> None:
        if not player_id:
            return
        # remover socket
        self.sockets.pop(player_id, None)

        pin = self.player_room.pop(player_id, None)
        if not pin:
            return

        room = self.rooms.get(pin)
        if not room:
            return

        # remover jogador da sala
        was_host = False
        if player_id in room.players:
            was_host = room.players[player_id].is_host
            room.players.pop(player_id, None)

        # se sala vazia, destruir
        if len(room.players) == 0:
            self.rooms.pop(pin, None)
            return

        # se host saiu, transferir host para o primeiro jogador restante
        if was_host:
            new_host = next(iter(room.players.values()))
            new_host.is_host = True
            room.host_player_id = new_host.player_id

        # broadcast estado atualizado
        await self.broadcast_room_state(pin)

    def _ensure_unique_pin(self) -> str:
        for _ in range(50):
            pin = _generate_pin()
            if pin not in self.rooms:
                return pin
        raise RuntimeError("Could not generate unique PIN")

    async def create_room(self, player_id: str, name: str) -> Room:
        pin = self._ensure_unique_pin()
        room = Room(pin=pin, host_player_id=player_id)
        room.players[player_id] = Player(player_id=player_id, name=name, is_host=True)
        self.rooms[pin] = room
        self.player_room[player_id] = pin
        return room

    async def join_room(self, player_id: str, name: str, pin: str) -> Room:
        room = self.rooms.get(pin)
        if not room:
            raise ValueError("ROOM_NOT_FOUND")
        if room.started:
            raise ValueError("ROOM_ALREADY_STARTED")
        if len(room.players) >= MAX_PLAYERS:
            raise ValueError("ROOM_FULL")

        room.players[player_id] = Player(player_id=player_id, name=name, is_host=False)
        self.player_room[player_id] = pin
        return room

    async def leave_room(self, player_id: str) -> None:
        await self.disconnect(player_id)

    async def start_game(self, player_id: str) -> Room:
        pin = self.player_room.get(player_id)
        if not pin:
            raise ValueError("NOT_IN_ROOM")
        room = self.rooms.get(pin)
        if not room:
            raise ValueError("ROOM_NOT_FOUND")
        if room.host_player_id != player_id:
            raise ValueError("NOT_HOST")
        if len(room.players) < 1:
            raise ValueError("NOT_ENOUGH_PLAYERS")

        room.started = True
        return room

    async def register_socket(self, player_id: str, websocket: WebSocket) -> None:
        self.sockets[player_id] = websocket

    async def broadcast_room_state(self, pin: str) -> None:
        room = self.rooms.get(pin)
        if not room:
            return
        payload = room.to_public_dict()
        # enviar para todos os players da sala
        for pid in list(room.players.keys()):
            ws = self.sockets.get(pid)
            if ws:
                await ws.send_json({"type": "room_state", "payload": payload})

    async def broadcast_game_started(self, pin: str) -> None:
        room = self.rooms.get(pin)
        if not room:
            return
        payload = room.to_public_dict()
        for pid in list(room.players.keys()):
            ws = self.sockets.get(pid)
            if ws:
                await ws.send_json({"type": "game_started", "payload": payload})
