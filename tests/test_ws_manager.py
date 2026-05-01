import pytest

from backend.ws_manager import WebSocketManager


class FakeWebSocket:
    def __init__(self):
        self.sent: list[dict] = []
        self.closed = False

    async def send_json(self, data: dict):
        self.sent.append(data)

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
class TestWebSocketManager:
    async def test_connect_and_broadcast(self):
        mgr = WebSocketManager()
        ws1 = FakeWebSocket()
        ws2 = FakeWebSocket()
        mgr.connect("session-1", ws1)
        mgr.connect("session-1", ws2)

        await mgr.broadcast("session-1", {"type": "comment_added", "text": "hi"})
        assert len(ws1.sent) == 1
        assert len(ws2.sent) == 1
        assert ws1.sent[0]["type"] == "comment_added"

    async def test_broadcast_to_correct_session(self):
        mgr = WebSocketManager()
        ws1 = FakeWebSocket()
        ws2 = FakeWebSocket()
        mgr.connect("session-1", ws1)
        mgr.connect("session-2", ws2)

        await mgr.broadcast("session-1", {"type": "test"})
        assert len(ws1.sent) == 1
        assert len(ws2.sent) == 0

    async def test_disconnect_removes_connection(self):
        mgr = WebSocketManager()
        ws = FakeWebSocket()
        mgr.connect("session-1", ws)
        mgr.disconnect("session-1", ws)

        await mgr.broadcast("session-1", {"type": "test"})
        assert len(ws.sent) == 0

    async def test_broadcast_to_empty_session(self):
        mgr = WebSocketManager()
        await mgr.broadcast("no-such-session", {"type": "test"})

    async def test_connection_count(self):
        mgr = WebSocketManager()
        ws1 = FakeWebSocket()
        ws2 = FakeWebSocket()
        mgr.connect("session-1", ws1)
        mgr.connect("session-1", ws2)
        assert mgr.connection_count("session-1") == 2
        mgr.disconnect("session-1", ws1)
        assert mgr.connection_count("session-1") == 1

    async def test_broadcast_disconnects_failing_socket(self):
        mgr = WebSocketManager()
        good_ws = FakeWebSocket()
        bad_ws = FakeWebSocket()
        bad_ws.send_json = self._raise_on_send
        mgr.connect("s1", good_ws)
        mgr.connect("s1", bad_ws)

        await mgr.broadcast("s1", {"type": "test"})
        assert len(good_ws.sent) == 1
        assert mgr.connection_count("s1") == 1

    @staticmethod
    async def _raise_on_send(data):
        raise ConnectionError("gone")
