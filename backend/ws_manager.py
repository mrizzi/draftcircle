from collections import defaultdict


class WebSocketManager:
    def __init__(self):
        self._connections: dict[str, list] = defaultdict(list)

    def connect(self, session_id: str, websocket) -> None:
        self._connections[session_id].append(websocket)

    def disconnect(self, session_id: str, websocket) -> None:
        conns = self._connections.get(session_id, [])
        if websocket in conns:
            conns.remove(websocket)
        if not conns and session_id in self._connections:
            del self._connections[session_id]

    async def broadcast(self, session_id: str, message: dict) -> None:
        for ws in list(self._connections.get(session_id, [])):
            try:
                await ws.send_json(message)
            except Exception:
                self.disconnect(session_id, ws)

    def connection_count(self, session_id: str) -> int:
        return len(self._connections.get(session_id, []))
