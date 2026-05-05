import json
from datetime import datetime, timezone

from backend.models import (
    Comment,
    Participant,
    Proposal,
    ProposalStatus,
    SectionMeta,
    SectionPriority,
    SectionStatus,
    Session,
    SessionStatus,
    Template,
    TemplateSection,
    User,
    UserRegistry,
)


class TestTemplate:
    def test_round_trip(self):
        section = TemplateSection(
            id="overview",
            title="Overview",
            priority=SectionPriority.REQUIRED,
            guidance="Write an overview",
            suggested_roles=["product-manager"],
        )
        template = Template(
            name="Test",
            description="A test template",
            ai_context="You are helping.",
            sections=[section],
        )
        data = json.loads(template.model_dump_json())
        restored = Template.model_validate(data)
        assert restored.name == "Test"
        assert restored.sections[0].priority == SectionPriority.REQUIRED

    def test_suggested_roles_defaults_empty(self):
        section = TemplateSection(id="x", title="X", priority="required", guidance="g")
        assert section.suggested_roles == []


class TestSession:
    def test_round_trip(self):
        session = Session(
            id="test-20260430-090000",
            template="test",
            coordinator="alice",
            participants=[
                Participant(
                    user_id="alice",
                    token="tok-alice",
                    assigned_sections=["overview"],
                    role="product-manager",
                )
            ],
            section_meta={
                "overview": SectionMeta(filename="01-overview"),
            },
            created_at=datetime(2026, 4, 30, 9, 0, 0, tzinfo=timezone.utc),
        )
        data = json.loads(session.model_dump_json())
        restored = Session.model_validate(data)
        assert restored.status == SessionStatus.ACTIVE
        assert restored.section_meta["overview"].status == SectionStatus.DRAFT

    def test_defaults(self):
        session = Session(
            id="s",
            template="t",
            coordinator="c",
            participants=[],
            section_meta={},
            created_at=datetime.now(timezone.utc),
        )
        assert session.status == SessionStatus.ACTIVE
        assert session.agent_session_id is None
        assert session.published_at is None
        assert session.output_ref is None


class TestUserRegistry:
    def test_round_trip(self):
        registry = UserRegistry(
            users=[
                User(
                    id="alice",
                    name="Alice",
                    email="a@b.com",
                    default_roles=["pm"],
                )
            ]
        )
        data = json.loads(registry.model_dump_json())
        restored = UserRegistry.model_validate(data)
        assert len(restored.users) == 1
        assert restored.users[0].id == "alice"


class TestComment:
    def test_fields(self):
        c = Comment(
            id="comment-001",
            author="alice",
            text="Looks good",
            timestamp=datetime(2026, 4, 30, 10, 0, 0, tzinfo=timezone.utc),
        )
        assert c.author == "alice"


class TestProposal:
    def test_defaults(self):
        p = Proposal(
            id="proposal-001",
            section_id="overview",
            triggered_by_comment="comment-001",
            revised_text="New text",
            summary="Updated overview",
            created_at=datetime(2026, 4, 30, 10, 5, 0, tzinfo=timezone.utc),
        )
        assert p.status == ProposalStatus.PENDING
