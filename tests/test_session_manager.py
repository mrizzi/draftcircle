import json

import pytest

from backend.git_store import GitStore
from backend.models import (
    ParticipantInput,
    ProposalStatus,
    SectionStatus,
    SessionStatus,
)
from backend.session_manager import SessionManager
from backend.template_loader import TemplateLoader
from tests.conftest import SAMPLE_TEMPLATE, SAMPLE_USERS


@pytest.fixture()
def manager(populated_data_repo):
    git = GitStore(populated_data_repo)
    git.commit(
        "init",
        {
            "templates/test-template.json": json.dumps(SAMPLE_TEMPLATE),
            "users.json": json.dumps(SAMPLE_USERS),
        },
    )
    templates = TemplateLoader(populated_data_repo)
    return SessionManager(git, templates)


class TestCreateSession:
    def test_creates_session_directory(self, manager):
        session = manager.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[
                ParticipantInput(
                    user_id="alice",
                    assigned_sections=["overview"],
                    role="product-manager",
                ),
                ParticipantInput(
                    user_id="bob",
                    assigned_sections=["details"],
                    role="architect",
                ),
            ],
        )
        assert session.template == "test-template"
        assert session.coordinator == "alice"
        assert session.status == SessionStatus.ACTIVE

    def test_session_id_format(self, manager):
        session = manager.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[],
        )
        assert session.id.startswith("test-template-")
        parts = session.id.split("-")
        assert len(parts[-1]) == 6
        assert len(parts[-2]) == 8

    def test_assigns_tokens_to_participants(self, manager):
        session = manager.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[
                ParticipantInput(
                    user_id="alice", assigned_sections=["overview"], role="pm"
                ),
            ],
        )
        assert len(session.participants) == 1
        assert len(session.participants[0].token) > 0

    def test_initializes_section_meta(self, manager):
        session = manager.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[],
        )
        assert len(session.section_meta) == 3
        assert session.section_meta["overview"].filename == "01-overview"
        assert session.section_meta["overview"].status == SectionStatus.DRAFT
        assert session.section_meta["details"].filename == "02-details"
        assert session.section_meta["notes"].filename == "03-notes"

    def test_creates_empty_section_files(self, manager):
        session = manager.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[],
        )
        content = manager.git.read_file(
            f"sessions/{session.id}/sections/01-overview.md"
        )
        assert content == ""

    def test_creates_session_json(self, manager):
        session = manager.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[],
        )
        raw = manager.git.read_file(f"sessions/{session.id}/session.json")
        assert raw is not None
        data = json.loads(raw)
        assert data["template"] == "test-template"

    def test_rejects_unknown_template(self, manager):
        with pytest.raises(ValueError, match="not found"):
            manager.create_session(
                template_slug="nonexistent",
                coordinator="alice",
                participants=[],
            )

    def test_rejects_path_traversal_in_slug(self, manager):
        with pytest.raises(ValueError, match="Invalid template slug"):
            manager.create_session(
                template_slug="../../etc/passwd",
                coordinator="alice",
                participants=[],
            )

    def test_rejects_uppercase_slug(self, manager):
        with pytest.raises(ValueError, match="Invalid template slug"):
            manager.create_session(
                template_slug="Test-Template",
                coordinator="alice",
                participants=[],
            )

    def test_collision_suffix(self, manager):
        s1 = manager.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[],
        )
        s2 = manager.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[],
            timestamp=s1.created_at,
        )
        assert s2.id != s1.id
        assert s2.id.endswith("-2")


class TestGetSession:
    def test_returns_session(self, manager):
        created = manager.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[],
        )
        fetched = manager.get_session(created.id)
        assert fetched.id == created.id
        assert fetched.coordinator == "alice"

    def test_returns_none_for_missing(self, manager):
        assert manager.get_session("no-such-session") is None


class TestListSessions:
    def test_returns_all_sessions(self, manager):
        manager.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[],
        )
        manager.create_session(
            template_slug="test-template",
            coordinator="bob",
            participants=[],
        )
        sessions = manager.list_sessions()
        assert len(sessions) == 2

    def test_empty_when_no_sessions(self, manager):
        assert manager.list_sessions() == []


class TestAddComment:
    def test_adds_comment_to_section(self, manager):
        session = manager.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[
                ParticipantInput(
                    user_id="alice", assigned_sections=["overview"], role="pm"
                ),
            ],
        )
        comment = manager.add_comment(
            session_id=session.id,
            section_id="overview",
            author="alice",
            text="Needs more detail on the problem statement",
        )
        assert comment.id.startswith("comment-")
        assert comment.author == "alice"
        assert comment.text == "Needs more detail on the problem statement"

    def test_multiple_comments_accumulate(self, manager):
        session = manager.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[],
        )
        manager.add_comment(session.id, "overview", "alice", "First comment")
        manager.add_comment(session.id, "overview", "bob", "Second comment")
        comments = manager.get_comments(session.id, "overview")
        assert len(comments) == 2

    def test_section_transitions_to_in_review(self, manager):
        session = manager.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[],
        )
        manager.add_comment(session.id, "overview", "alice", "A comment")
        updated = manager.get_session(session.id)
        assert updated.section_meta["overview"].status == SectionStatus.IN_REVIEW

    def test_rejects_comment_on_unknown_section(self, manager):
        session = manager.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[],
        )
        with pytest.raises(ValueError, match="not found"):
            manager.add_comment(session.id, "nonexistent", "alice", "hi")


class TestGetComments:
    def test_returns_empty_initially(self, manager):
        session = manager.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[],
        )
        assert manager.get_comments(session.id, "overview") == []


class TestCreateProposal:
    def test_creates_proposal(self, manager):
        session = manager.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[],
        )
        comment = manager.add_comment(session.id, "overview", "alice", "Add more")
        proposal = manager.create_proposal(
            session_id=session.id,
            section_id="overview",
            triggered_by_comment=comment.id,
            revised_text="Updated overview text with more detail.",
            summary="Added detail per Alice's comment",
        )
        assert proposal.id == "proposal-001"
        assert proposal.status == ProposalStatus.PENDING

    def test_proposals_increment_number(self, manager):
        session = manager.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[],
        )
        c = manager.add_comment(session.id, "overview", "alice", "Add more")
        p1 = manager.create_proposal(session.id, "overview", c.id, "text 1", "change 1")
        p2 = manager.create_proposal(session.id, "overview", c.id, "text 2", "change 2")
        assert p1.id == "proposal-001"
        assert p2.id == "proposal-002"


class TestAcceptProposal:
    def test_updates_section_content(self, manager):
        session = manager.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[
                ParticipantInput(
                    user_id="alice", assigned_sections=["overview"], role="pm"
                ),
            ],
        )
        c = manager.add_comment(session.id, "overview", "alice", "Fix it")
        p = manager.create_proposal(
            session.id, "overview", c.id, "Better text", "improved"
        )
        manager.accept_proposal(session.id, p.id, "alice")

        section_path = f"sessions/{session.id}/sections/01-overview.md"
        assert manager.git.read_file(section_path) == "Better text"

    def test_marks_proposal_accepted(self, manager):
        session = manager.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[
                ParticipantInput(
                    user_id="alice", assigned_sections=["overview"], role="pm"
                ),
            ],
        )
        c = manager.add_comment(session.id, "overview", "alice", "Fix it")
        p = manager.create_proposal(session.id, "overview", c.id, "new", "fix")
        manager.accept_proposal(session.id, p.id, "alice")

        proposals = manager.get_proposals(session.id, "overview")
        assert proposals[0].status == ProposalStatus.ACCEPTED

    def test_rejects_if_not_section_owner(self, manager):
        session = manager.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[
                ParticipantInput(
                    user_id="alice", assigned_sections=["overview"], role="pm"
                ),
            ],
        )
        c = manager.add_comment(session.id, "overview", "bob", "Fix it")
        p = manager.create_proposal(session.id, "overview", c.id, "new", "fix")
        with pytest.raises(ValueError, match="not authorized"):
            manager.accept_proposal(session.id, p.id, "bob")


class TestRejectProposal:
    def test_marks_proposal_rejected(self, manager):
        session = manager.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[
                ParticipantInput(
                    user_id="alice", assigned_sections=["overview"], role="pm"
                ),
            ],
        )
        c = manager.add_comment(session.id, "overview", "alice", "Fix it")
        p = manager.create_proposal(session.id, "overview", c.id, "new", "fix")
        manager.reject_proposal(session.id, p.id, "alice")

        proposals = manager.get_proposals(session.id, "overview")
        assert proposals[0].status == ProposalStatus.REJECTED

    def test_does_not_change_section_content(self, manager):
        session = manager.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[
                ParticipantInput(
                    user_id="alice", assigned_sections=["overview"], role="pm"
                ),
            ],
        )
        c = manager.add_comment(session.id, "overview", "alice", "Fix it")
        p = manager.create_proposal(session.id, "overview", c.id, "new text", "fix")
        manager.reject_proposal(session.id, p.id, "alice")

        section_path = f"sessions/{session.id}/sections/01-overview.md"
        assert manager.git.read_file(section_path) == ""


class TestGetProposals:
    def test_returns_empty_initially(self, manager):
        session = manager.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[],
        )
        assert manager.get_proposals(session.id, "overview") == []


class TestApproveSection:
    def test_marks_section_approved(self, manager):
        session = manager.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[
                ParticipantInput(
                    user_id="alice", assigned_sections=["overview"], role="pm"
                ),
            ],
        )
        manager.approve_section(session.id, "overview", "alice")
        updated = manager.get_session(session.id)
        assert updated.section_meta["overview"].status == SectionStatus.APPROVED

    def test_coordinator_can_approve_any_section(self, manager):
        session = manager.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[
                ParticipantInput(
                    user_id="bob", assigned_sections=["details"], role="arch"
                ),
            ],
        )
        manager.approve_section(session.id, "details", "alice")
        updated = manager.get_session(session.id)
        assert updated.section_meta["details"].status == SectionStatus.APPROVED

    def test_rejects_if_not_authorized(self, manager):
        session = manager.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[
                ParticipantInput(
                    user_id="bob", assigned_sections=["details"], role="arch"
                ),
            ],
        )
        with pytest.raises(ValueError, match="not authorized"):
            manager.approve_section(session.id, "details", "bob-other")

    def test_approved_section_rejects_comments(self, manager):
        session = manager.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[
                ParticipantInput(
                    user_id="alice", assigned_sections=["overview"], role="pm"
                ),
            ],
        )
        manager.approve_section(session.id, "overview", "alice")
        with pytest.raises(ValueError, match="approved"):
            manager.add_comment(session.id, "overview", "bob", "too late")


class TestReopenSection:
    def test_reopens_approved_section(self, manager):
        session = manager.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[
                ParticipantInput(
                    user_id="alice", assigned_sections=["overview"], role="pm"
                ),
            ],
        )
        manager.approve_section(session.id, "overview", "alice")
        manager.reopen_section(session.id, "overview", "alice")
        updated = manager.get_session(session.id)
        assert updated.section_meta["overview"].status == SectionStatus.IN_REVIEW

    def test_rejects_if_not_approved(self, manager):
        session = manager.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[],
        )
        with pytest.raises(ValueError, match="not approved"):
            manager.reopen_section(session.id, "overview", "alice")


class TestSkipSection:
    def test_skips_optional_section(self, manager):
        session = manager.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[],
        )
        manager.skip_section(session.id, "notes", "alice")
        updated = manager.get_session(session.id)
        assert updated.section_meta["notes"].status == SectionStatus.SKIPPED

    def test_skips_recommended_section(self, manager):
        session = manager.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[],
        )
        manager.skip_section(session.id, "details", "alice")
        updated = manager.get_session(session.id)
        assert updated.section_meta["details"].status == SectionStatus.SKIPPED

    def test_rejects_skipping_required_section(self, manager):
        session = manager.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[],
        )
        with pytest.raises(ValueError, match="required"):
            manager.skip_section(session.id, "overview", "alice")


class TestCompletionCheck:
    def test_complete_when_all_required_approved(self, manager):
        session = manager.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[
                ParticipantInput(
                    user_id="alice", assigned_sections=["overview"], role="pm"
                ),
            ],
        )
        assert manager.is_ready_to_publish(session.id) is False
        manager.approve_section(session.id, "overview", "alice")
        assert manager.is_ready_to_publish(session.id) is True

    def test_complete_with_skipped_optional(self, manager):
        session = manager.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[
                ParticipantInput(
                    user_id="alice", assigned_sections=["overview"], role="pm"
                ),
            ],
        )
        manager.approve_section(session.id, "overview", "alice")
        manager.skip_section(session.id, "notes", "alice")
        assert manager.is_ready_to_publish(session.id) is True

    def test_get_progress(self, manager):
        session = manager.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[
                ParticipantInput(
                    user_id="alice", assigned_sections=["overview"], role="pm"
                ),
            ],
        )
        progress = manager.get_progress(session.id)
        assert progress["total"] == 3
        assert progress["approved"] == 0
        assert progress["skipped"] == 0
        assert progress["required_remaining"] == 1

        manager.approve_section(session.id, "overview", "alice")
        progress = manager.get_progress(session.id)
        assert progress["approved"] == 1
        assert progress["required_remaining"] == 0


class TestPublishedSessionIsReadOnly:
    def _publish(self, manager):
        session = manager.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[
                ParticipantInput(
                    user_id="alice", assigned_sections=["overview"], role="pm"
                ),
            ],
        )
        manager.approve_section(session.id, "overview", "alice")
        manager.mark_published(session.id, "ref-001")
        return session

    def test_rejects_comment(self, manager):
        session = self._publish(manager)
        with pytest.raises(ValueError, match="not active"):
            manager.add_comment(session.id, "overview", "alice", "nope")

    def test_rejects_create_proposal(self, manager):
        session = self._publish(manager)
        with pytest.raises(ValueError, match="not active"):
            manager.create_proposal(session.id, "overview", "c1", "text", "sum")

    def test_rejects_approve_section(self, manager):
        session = self._publish(manager)
        with pytest.raises(ValueError, match="not active"):
            manager.approve_section(session.id, "overview", "alice")

    def test_rejects_skip_section(self, manager):
        session = self._publish(manager)
        with pytest.raises(ValueError, match="not active"):
            manager.skip_section(session.id, "notes", "alice")


class TestNonExistentProposal:
    def test_accept_nonexistent_raises(self, manager):
        session = manager.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[
                ParticipantInput(
                    user_id="alice", assigned_sections=["overview"], role="pm"
                ),
            ],
        )
        with pytest.raises(ValueError, match="not found"):
            manager.accept_proposal(session.id, "proposal-999", "alice")

    def test_reject_nonexistent_raises(self, manager):
        session = manager.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[
                ParticipantInput(
                    user_id="alice", assigned_sections=["overview"], role="pm"
                ),
            ],
        )
        with pytest.raises(ValueError, match="not found"):
            manager.reject_proposal(session.id, "proposal-999", "alice")


class TestCoordinatorAsParticipant:
    def test_coordinator_added_as_participant(self, populated_data_repo):
        from backend.git_store import GitStore
        from backend.session_manager import SessionManager
        from backend.template_loader import TemplateLoader

        git = GitStore(populated_data_repo)
        templates = TemplateLoader(populated_data_repo)
        sm = SessionManager(git, templates)

        session = sm.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[],
        )
        user_ids = [p.user_id for p in session.participants]
        assert "alice" in user_ids
        alice_p = next(p for p in session.participants if p.user_id == "alice")
        assert alice_p.role == "coordinator"
        assert alice_p.token
        assert set(alice_p.assigned_sections) == {"overview", "details", "notes"}

    def test_coordinator_not_duplicated_if_already_participant(
        self, populated_data_repo
    ):
        from backend.git_store import GitStore
        from backend.models import ParticipantInput
        from backend.session_manager import SessionManager
        from backend.template_loader import TemplateLoader

        git = GitStore(populated_data_repo)
        templates = TemplateLoader(populated_data_repo)
        sm = SessionManager(git, templates)

        session = sm.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[
                ParticipantInput(
                    user_id="alice", assigned_sections=["overview"], role="coordinator"
                ),
            ],
        )
        alice_entries = [p for p in session.participants if p.user_id == "alice"]
        assert len(alice_entries) == 1


class TestSectionStatusTransitions:
    def test_begin_drafting_sets_all_to_drafting(self, manager):
        session = manager.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[],
        )
        manager.begin_drafting(session.id)
        session = manager.get_session(session.id)
        for meta in session.section_meta.values():
            assert meta.status == SectionStatus.DRAFTING

    def test_recover_drafting_resets_to_draft(self, manager):
        session = manager.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[],
        )
        manager.begin_drafting(session.id)
        manager.set_section_status(session.id, "overview", SectionStatus.DRAFT)
        manager.recover_drafting(session.id)
        session = manager.get_session(session.id)
        for meta in session.section_meta.values():
            assert meta.status == SectionStatus.DRAFT

    def test_recover_drafting_noop_when_no_drafting(self, manager):
        session = manager.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[],
        )
        manager.recover_drafting(session.id)
        session = manager.get_session(session.id)
        for meta in session.section_meta.values():
            assert meta.status == SectionStatus.DRAFT

    def test_set_section_status(self, manager):
        session = manager.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[],
        )
        manager.set_section_status(session.id, "overview", SectionStatus.IN_REVIEW)
        session = manager.get_session(session.id)
        assert session.section_meta["overview"].status == SectionStatus.IN_REVIEW

    def test_set_section_status_unknown_section(self, manager):
        session = manager.create_session(
            template_slug="test-template",
            coordinator="alice",
            participants=[],
        )
        with pytest.raises(ValueError, match="not found"):
            manager.set_section_status(session.id, "nonexistent", SectionStatus.DRAFT)
