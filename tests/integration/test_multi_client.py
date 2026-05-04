# tests/integration/test_multi_client.py
import time

import pytest

from tests.integration.conftest import drain_join_messages

pytestmark = pytest.mark.integration


class TestThreeClientBroadcast:
    def test_join_messages_received_by_all(self, api, session_with_drafts):
        sid = session_with_drafts["id"]
        t = session_with_drafts["tokens"]

        with api.websocket_connect(f"/ws/sessions/{sid}?token={t['alice']}") as ws_a:
            msg = ws_a.receive_json()
            assert msg["type"] == "participant_joined"
            assert msg["user"]["user_id"] == "alice"

            with api.websocket_connect(f"/ws/sessions/{sid}?token={t['bob']}") as ws_b:
                msg = ws_a.receive_json()
                assert msg["type"] == "participant_joined"
                assert msg["user"]["user_id"] == "bob"

                msg = ws_b.receive_json()
                assert msg["type"] == "participant_joined"
                assert msg["user"]["user_id"] == "bob"

    def test_comment_broadcasts_to_all_three(self, api, session_with_drafts):
        sid = session_with_drafts["id"]
        t = session_with_drafts["tokens"]

        with api.websocket_connect(f"/ws/sessions/{sid}?token={t['alice']}") as ws_a:
            with api.websocket_connect(f"/ws/sessions/{sid}?token={t['bob']}") as ws_b:
                with api.websocket_connect(f"/ws/sessions/{sid}?token={t['carol']}") as ws_c:
                    drain_join_messages(ws_a, ws_b, ws_c)

                    api.post(
                        f"/api/sessions/{sid}/comments",
                        json={
                            "section_id": "overview",
                            "author": "bob",
                            "text": "Needs more detail.",
                        },
                    )

                    for ws in (ws_a, ws_b, ws_c):
                        msg = ws.receive_json()
                        assert msg["type"] == "comment_added"
                        assert msg["section_id"] == "overview"
                        assert msg["comment"]["author"] == "bob"

    def test_proposal_created_broadcasts_to_all(self, api, session_with_drafts):
        sid = session_with_drafts["id"]
        t = session_with_drafts["tokens"]

        with api.websocket_connect(f"/ws/sessions/{sid}?token={t['alice']}") as ws_a:
            with api.websocket_connect(f"/ws/sessions/{sid}?token={t['bob']}") as ws_b:
                with api.websocket_connect(f"/ws/sessions/{sid}?token={t['carol']}") as ws_c:
                    drain_join_messages(ws_a, ws_b, ws_c)

                    api.post(
                        f"/api/sessions/{sid}/comments",
                        json={
                            "section_id": "overview",
                            "author": "bob",
                            "text": "Expand this section.",
                        },
                    )

                    for ws in (ws_a, ws_b, ws_c):
                        msg = ws.receive_json()
                        assert msg["type"] == "comment_added"

                    for ws in (ws_a, ws_b, ws_c):
                        msg = ws.receive_json()
                        assert msg["type"] == "proposal_created"
                        assert msg["section_id"] == "overview"

    def test_accept_proposal_broadcasts_to_all(self, api, session_with_drafts):
        sid = session_with_drafts["id"]
        t = session_with_drafts["tokens"]

        api.post(
            f"/api/sessions/{sid}/comments",
            json={
                "section_id": "overview",
                "author": "bob",
                "text": "Change needed.",
            },
        )
        proposals = api.get(f"/api/sessions/{sid}/sections/overview/proposals").json()
        proposal_id = proposals[0]["id"]

        with api.websocket_connect(f"/ws/sessions/{sid}?token={t['alice']}") as ws_a:
            with api.websocket_connect(f"/ws/sessions/{sid}?token={t['bob']}") as ws_b:
                with api.websocket_connect(f"/ws/sessions/{sid}?token={t['carol']}") as ws_c:
                    drain_join_messages(ws_a, ws_b, ws_c)

                    api.post(
                        f"/api/sessions/{sid}/proposals/{proposal_id}/accept",
                        json={"user_id": "bob"},
                    )

                    for ws in (ws_a, ws_b, ws_c):
                        msg = ws.receive_json()
                        assert msg["type"] == "proposal_accepted"
                        assert msg["proposal_id"] == proposal_id

    def test_approve_broadcasts_to_all(self, api, session_with_drafts):
        sid = session_with_drafts["id"]
        t = session_with_drafts["tokens"]

        with api.websocket_connect(f"/ws/sessions/{sid}?token={t['alice']}") as ws_a:
            with api.websocket_connect(f"/ws/sessions/{sid}?token={t['bob']}") as ws_b:
                with api.websocket_connect(f"/ws/sessions/{sid}?token={t['carol']}") as ws_c:
                    drain_join_messages(ws_a, ws_b, ws_c)

                    api.post(
                        f"/api/sessions/{sid}/sections/overview/approve",
                        json={"user_id": "alice"},
                    )

                    for ws in (ws_a, ws_b, ws_c):
                        msg = ws.receive_json()
                        assert msg["type"] == "section_approved"
                        assert msg["section_id"] == "overview"

    def test_publish_broadcasts_to_all(self, api, session_with_drafts):
        sid = session_with_drafts["id"]
        t = session_with_drafts["tokens"]
        data_repo = api.app.state.data_repo_path

        api.post(f"/api/sessions/{sid}/sections/overview/approve", json={"user_id": "alice"})
        api.post(f"/api/sessions/{sid}/sections/details/approve", json={"user_id": "alice"})
        api.post(f"/api/sessions/{sid}/sections/notes/skip", json={"user_id": "alice"})

        with api.websocket_connect(f"/ws/sessions/{sid}?token={t['alice']}") as ws_a:
            with api.websocket_connect(f"/ws/sessions/{sid}?token={t['bob']}") as ws_b:
                with api.websocket_connect(f"/ws/sessions/{sid}?token={t['carol']}") as ws_c:
                    drain_join_messages(ws_a, ws_b, ws_c)

                    api.post(
                        f"/api/sessions/{sid}/publish",
                        json={
                            "config": {
                                "output_path": str(data_repo / "pub.md"),
                                "allowed_dir": str(data_repo),
                            }
                        },
                    )

                    for ws in (ws_a, ws_b, ws_c):
                        msg = ws.receive_json()
                        assert msg["type"] == "session_published"
                        assert "output_ref" in msg

    def test_disconnect_notifies_remaining(self, api, session_with_drafts):
        sid = session_with_drafts["id"]
        t = session_with_drafts["tokens"]

        with api.websocket_connect(f"/ws/sessions/{sid}?token={t['alice']}") as ws_a:
            with api.websocket_connect(f"/ws/sessions/{sid}?token={t['bob']}") as ws_b:
                ws_a.receive_json()  # alice joined
                ws_a.receive_json()  # bob joined
                ws_b.receive_json()  # bob joined

                with api.websocket_connect(f"/ws/sessions/{sid}?token={t['carol']}") as ws_c:
                    ws_a.receive_json()  # carol joined
                    ws_b.receive_json()  # carol joined
                    ws_c.receive_json()  # carol joined
                    ws_c.close()

                # carol disconnected (exited context)
                time.sleep(0.5)  # allow disconnect to propagate
                msg_a = ws_a.receive_json()
                msg_b = ws_b.receive_json()
                assert msg_a["type"] == "participant_left"
                assert msg_a["user"]["user_id"] == "carol"
                assert msg_b["type"] == "participant_left"
                assert msg_b["user"]["user_id"] == "carol"

    def test_broadcast_survives_one_client_disconnect(self, api, session_with_drafts):
        """If one client disconnects, remaining clients still receive broadcasts."""
        sid = session_with_drafts["id"]
        t = session_with_drafts["tokens"]

        with api.websocket_connect(f"/ws/sessions/{sid}?token={t['alice']}") as ws_a:
            with api.websocket_connect(f"/ws/sessions/{sid}?token={t['bob']}") as ws_b:
                ws_a.receive_json()  # alice joined
                ws_a.receive_json()  # bob joined
                ws_b.receive_json()  # bob joined

                with api.websocket_connect(f"/ws/sessions/{sid}?token={t['carol']}") as ws_c:
                    ws_a.receive_json()  # carol joined
                    ws_b.receive_json()  # carol joined
                    ws_c.receive_json()  # carol joined
                    ws_c.close()

                # carol disconnected — drain participant_left
                time.sleep(0.5)  # allow disconnect to propagate
                ws_a.receive_json()
                ws_b.receive_json()

                # Now comment — should still reach alice and bob
                api.post(
                    f"/api/sessions/{sid}/comments",
                    json={
                        "section_id": "overview",
                        "author": "bob",
                        "text": "After carol left.",
                    },
                )

                for ws in (ws_a, ws_b):
                    msg = ws.receive_json()
                    assert msg["type"] == "comment_added"
