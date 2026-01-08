from __future__ import annotations

import secrets
import string
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

from fastapi import WebSocket

from backend.app.game.questions import get_random_question
from backend.app.game.rules import BASE_POINTS, DIFFICULTY_TIME_SECONDS, MAX_SPEED_BONUS

MAX_PLAYERS = 4


def _generate_pin(length: int = 6) -> str:
    alphabet = string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


@dataclass
class Player:
    player_id: str
    name: str
    is_host: bool = False
    score: int = 0


@dataclass
class RoundState:
    question_id: str
    difficulty: str
    question: str
    options: list[str]
    correct_index: int
    started_at: float
    duration: int
    answers: Dict[str, int] = field(default_factory=dict)  # player_id -> optionIndex


@dataclass
class Room:
    pin: str
    host_player_id: str
    players: Dict[str, Player] = field(default_factory=dict)
    started: bool = False
    round: Optional[RoundState] = None

    def to_public_dict(self) -> dict:
        return {
            "pin": self.pin,
            "started": self.started,
            "maxPlayers": MAX_PLAYERS,
            "players": [
                {"id": p.player_id, "name": p.name, "isHost": p.is_host, "score": p.score}
                for p in self.players.values()
            ],
            "count": len(self.players),
        }


class RoomManager:
    def __init__(self) -> None:
        self.rooms: Dict[str, Room] = {}
        self.sockets: Dict[str, WebSocket] = {}   # player_id -> websocket
        self.player_room: Dict[str, str] = {}     # player_id -> pin

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()

    async def register_socket(self, player_id: str, websocket: WebSocket) -> None:
        self.sockets[player_id] = websocket

    def _ensure_unique_pin(self) -> str:
        for _ in range(50):
            pin = _generate_pin()
            if pin not in self.rooms:
                return pin
        raise RuntimeError("Could not generate unique PIN")

    async def disconnect(self, player_id: Optional[str]) -> None:
        if not player_id:
            return

        self.sockets.pop(player_id, None)

        pin = self.player_room.pop(player_id, None)
        if not pin:
            return

        room = self.rooms.get(pin)
        if not room:
            return

        was_host = False
        if player_id in room.players:
            was_host = room.players[player_id].is_host
            room.players.pop(player_id, None)

        if len(room.players) == 0:
            self.rooms.pop(pin, None)
            return

        if was_host:
            new_host = next(iter(room.players.values()))
            new_host.is_host = True
            room.host_player_id = new_host.player_id

        await self.broadcast_room_state(pin)

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

        room.started = True
        # inicia primeira rodada imediatamente
        await self.start_round(pin)
        return room

    async def start_round(self, pin: str) -> None:
        room = self.rooms.get(pin)
        if not room:
            return

        q = get_random_question()
        difficulty = q["difficulty"]
        duration = DIFFICULTY_TIME_SECONDS[difficulty]

        room.round = RoundState(
            question_id=q["id"],
            difficulty=difficulty,
            question=q["question"],
            options=q["options"],
            correct_index=q["correctIndex"],
            started_at=time.time(),
            duration=duration,
        )

        # envia pergunta para todos
        await self.broadcast_question(pin)

    async def submit_answer(self, player_id: str, option_index: int) -> None:
        pin = self.player_room.get(player_id)
        if not pin:
            raise ValueError("NOT_IN_ROOM")
        room = self.rooms.get(pin)
        if not room or not room.round:
            raise ValueError("NO_ACTIVE_ROUND")

        rnd = room.round
        if player_id in rnd.answers:
            raise ValueError("ALREADY_ANSWERED")

        # checa tempo
        now = time.time()
        if now > rnd.started_at + rnd.duration:
            raise ValueError("TIME_OVER")

        rnd.answers[player_id] = int(option_index)

        # calcula resultado individual imediato
        correct = (int(option_index) == rnd.correct_index)
        gained = 0
        if correct:
            elapsed = now - rnd.started_at
            remaining = max(0.0, rnd.duration - elapsed)
            speed_bonus = int(MAX_SPEED_BONUS * (remaining / rnd.duration))
            gained = BASE_POINTS + speed_bonus
            room.players[player_id].score += gained

        await self.send_to_player(player_id, {
            "type": "answer_result",
            "payload": {
                "correct": correct,
                "gained": gained,
                "correctIndex": rnd.correct_index,
            }
        })

        # se todos responderam, encerra rodada
        if len(rnd.answers) >= len(room.players):
            await self.end_round(pin)

    async def end_round(self, pin: str) -> None:
        room = self.rooms.get(pin)
        if not room or not room.round:
            return

        rnd = room.round

        # broadcast placar
        await self.broadcast_scoreboard(pin)

        # encerra rodada
        room.round = None

        await self.broadcast_to_room(pin, {
            "type": "round_ended",
            "payload": {
                "questionId": rnd.question_id
            }
        })

        # MVP: iniciar nova rodada automaticamente após 2s (opcional)
        # Você pode comentar isto se preferir botão "Próxima" do host.
        # await asyncio.sleep(2)
        # await self.start_round(pin)

    async def broadcast_room_state(self, pin: str) -> None:
        room = self.rooms.get(pin)
        if not room:
            return
        await self.broadcast_to_room(pin, {"type": "room_state", "payload": room.to_public_dict()})

    async def broadcast_question(self, pin: str) -> None:
        room = self.rooms.get(pin)
        if not room or not room.round:
            return
        rnd = room.round
        payload = {
            "questionId": rnd.question_id,
            "difficulty": rnd.difficulty,
            "duration": rnd.duration,
            "question": rnd.question,
            "options": rnd.options,
        }
        await self.broadcast_to_room(pin, {"type": "question", "payload": payload})

    async def broadcast_scoreboard(self, pin: str) -> None:
        room = self.rooms.get(pin)
        if not room:
            return
        payload = {
            "pin": room.pin,
            "players": sorted(
                [{"id": p.player_id, "name": p.name, "score": p.score, "isHost": p.is_host} for p in room.players.values()],
                key=lambda x: x["score"],
                reverse=True
            )
        }
        await self.broadcast_to_room(pin, {"type": "scoreboard", "payload": payload})

    async def broadcast_to_room(self, pin: str, message: dict) -> None:
        room = self.rooms.get(pin)
        if not room:
            return
        for pid in list(room.players.keys()):
            ws = self.sockets.get(pid)
            if ws:
                await ws.send_json(message)

    async def send_to_player(self, player_id: str, message: dict) -> None:
        ws = self.sockets.get(player_id)
        if ws:
            await ws.send_json(message)

