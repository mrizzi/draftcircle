import json
import re
import secrets
from datetime import datetime, timezone

from backend.git_store import GitStore
from backend.models import (
    Comment,
    Participant,
    ParticipantInput,
    ProgressInfo,
    Proposal,
    ProposalStatus,
    SectionContent,
    SectionContentResponse,
    SectionMeta,
    SectionPriority,
    SectionStatus,
    Session,
    SessionStatus,
    Template,
)
from backend.template_loader import TemplateLoader


class SessionManager:
    def __init__(self, git: GitStore, templates: TemplateLoader):
        self.git = git
        self.templates = templates

    # --- Private helpers ---

    _SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

    def _require_session(self, session_id: str) -> Session:
        session = self.get_session(session_id)
        if session is None:
            raise ValueError(f"Session '{session_id}' not found")
        return session

    def _require_template(self, session: Session) -> Template:
        template = self.templates.get_template(session.template)
        if template is None:
            raise ValueError(f"Template '{session.template}' not found")
        return template

    def _require_active(self, session: Session) -> None:
        if session.status != SessionStatus.ACTIVE:
            raise ValueError(f"Session '{session.id}' is not active")

    def _generate_session_id(self, template_slug: str, timestamp: datetime) -> str:
        base = f"{template_slug}-{timestamp.strftime('%Y%m%d')}-{timestamp.strftime('%H%M%S')}"
        if not self.git.file_exists(f"sessions/{base}"):
            return base
        suffix = 2
        while self.git.file_exists(f"sessions/{base}-{suffix}"):
            suffix += 1
        return f"{base}-{suffix}"

    def _session_dir(self, session_id: str) -> str:
        return f"sessions/{session_id}"

    def _section_filename(self, session: Session, section_id: str) -> str:
        meta = session.section_meta.get(section_id)
        if meta is None:
            raise ValueError(f"Section '{section_id}' not found")
        return meta.filename

    def _is_authorized_for_section(
        self, session: Session, section_id: str, user_id: str
    ) -> bool:
        if session.coordinator == user_id:
            return True
        return any(
            p.user_id == user_id and section_id in p.assigned_sections
            for p in session.participants
        )

    def _save_session(self, session: Session, message: str) -> str:
        path = f"{self._session_dir(session.id)}/session.json"
        return self.git.commit(message, {path: session.model_dump_json(indent=2)})

    def _load_comments(self, session: Session, section_id: str) -> list[Comment]:
        filename = self._section_filename(session, section_id)
        path = f"{self._session_dir(session.id)}/comments/{filename}.json"
        content = self.git.read_file(path)
        if content is None:
            return []
        return [Comment.model_validate(c) for c in json.loads(content)]

    def _load_proposals(self, session: Session, section_id: str) -> list[Proposal]:
        filename = self._section_filename(session, section_id)
        proposals_dir = f"{self._session_dir(session.id)}/proposals/{filename}"
        proposal_files = self.git.list_directory(proposals_dir)
        proposals = []
        for pfile in sorted(proposal_files):
            content = self.git.read_file(f"{proposals_dir}/{pfile}")
            if content:
                proposals.append(Proposal.model_validate(json.loads(content)))
        return proposals

    def _find_proposal(
        self, session: Session, proposal_id: str
    ) -> tuple[str, Proposal] | None:
        for section_id in session.section_meta:
            for proposal in self._load_proposals(session, section_id):
                if proposal.id == proposal_id:
                    return (section_id, proposal)
        return None

    # --- Public API ---

    def create_session(
        self,
        template_slug: str,
        coordinator: str,
        participants: list[ParticipantInput],
        timestamp: datetime | None = None,
    ) -> Session:
        if not self._SLUG_RE.match(template_slug):
            raise ValueError(
                f"Invalid template slug '{template_slug}': "
                "must be lowercase alphanumeric with hyphens"
            )
        template = self.templates.get_template(template_slug)
        if template is None:
            raise ValueError(f"Template '{template_slug}' not found")

        ts = timestamp or datetime.now(timezone.utc)
        session_id = self._generate_session_id(template_slug, ts)
        base = self._session_dir(session_id)

        session_participants = [
            Participant(
                user_id=p.user_id,
                token=secrets.token_urlsafe(24),
                assigned_sections=p.assigned_sections,
                role=p.role,
            )
            for p in participants
        ]

        coordinator_in_list = any(
            p.user_id == coordinator for p in session_participants
        )
        if not coordinator_in_list:
            all_section_ids = [s.id for s in template.sections]
            session_participants.insert(
                0,
                Participant(
                    user_id=coordinator,
                    token=secrets.token_urlsafe(24),
                    assigned_sections=all_section_ids,
                    role="coordinator",
                ),
            )

        section_meta = {
            section.id: SectionMeta(filename=f"{i:02d}-{section.id}")
            for i, section in enumerate(template.sections, start=1)
        }

        session = Session(
            id=session_id,
            template=template_slug,
            coordinator=coordinator,
            participants=session_participants,
            section_meta=section_meta,
            created_at=ts,
        )

        files = {f"{base}/session.json": session.model_dump_json(indent=2)}
        for meta in section_meta.values():
            files[f"{base}/sections/{meta.filename}.md"] = ""
            files[f"{base}/comments/{meta.filename}.json"] = "[]"

        self.git.commit(f"init: session created from template {template_slug}", files)
        return session

    def get_session(self, session_id: str) -> Session | None:
        path = f"{self._session_dir(session_id)}/session.json"
        content = self.git.read_file(path)
        if content is None:
            return None
        return Session.model_validate(json.loads(content))

    def list_sessions(self) -> list[Session]:
        entries = self.git.list_directory("sessions")
        sessions = []
        for name in sorted(entries):
            session = self.get_session(name)
            if session is not None:
                sessions.append(session)
        return sessions

    def get_comments(self, session_id: str, section_id: str) -> list[Comment]:
        session = self._require_session(session_id)
        return self._load_comments(session, section_id)

    def add_comment(
        self, session_id: str, section_id: str, author: str, text: str
    ) -> Comment:
        session = self._require_session(session_id)
        self._require_active(session)

        meta = session.section_meta.get(section_id)
        if meta is None:
            raise ValueError(f"Section '{section_id}' not found")
        if meta.status in (SectionStatus.APPROVED, SectionStatus.DRAFTING):
            raise ValueError(
                f"Cannot comment on section '{section_id}' while status is"
                f" '{meta.status.value}'"
            )

        existing = self._load_comments(session, section_id)
        comment = Comment(
            id=f"comment-{len(existing) + 1:03d}",
            author=author,
            text=text,
            timestamp=datetime.now(timezone.utc),
        )
        existing.append(comment)

        filename = meta.filename
        comments_path = f"{self._session_dir(session_id)}/comments/{filename}.json"
        files: dict[str, str] = {
            comments_path: json.dumps(
                [c.model_dump(mode="json") for c in existing], indent=2
            )
        }

        if meta.status == SectionStatus.DRAFT:
            session.section_meta[section_id].status = SectionStatus.IN_REVIEW
            files[f"{self._session_dir(session_id)}/session.json"] = (
                session.model_dump_json(indent=2)
            )

        self.git.commit(f"comment: {author} on {filename}", files)
        return comment

    def get_proposals(self, session_id: str, section_id: str) -> list[Proposal]:
        session = self._require_session(session_id)
        return self._load_proposals(session, section_id)

    def create_proposal(
        self,
        session_id: str,
        section_id: str,
        triggered_by_comment: str,
        revised_text: str,
        summary: str,
    ) -> Proposal:
        session = self._require_session(session_id)
        self._require_active(session)

        filename = self._section_filename(session, section_id)
        proposals_dir = f"{self._session_dir(session_id)}/proposals/{filename}"
        existing = self.git.list_directory(proposals_dir)

        proposal = Proposal(
            id=f"proposal-{len(existing) + 1:03d}",
            section_id=section_id,
            triggered_by_comment=triggered_by_comment,
            revised_text=revised_text,
            summary=summary,
            created_at=datetime.now(timezone.utc),
        )

        self.git.commit(
            f"proposal: {proposal.id} for {filename}",
            {f"{proposals_dir}/{proposal.id}.json": proposal.model_dump_json(indent=2)},
        )
        return proposal

    def accept_proposal(self, session_id: str, proposal_id: str, user_id: str) -> str:
        session = self._require_session(session_id)
        self._require_active(session)

        result = self._find_proposal(session, proposal_id)
        if result is None:
            raise ValueError(f"Proposal '{proposal_id}' not found")
        section_id, proposal = result

        if proposal.status != ProposalStatus.PENDING:
            raise ValueError(
                f"Proposal '{proposal_id}' is already {proposal.status.value}"
            )

        if not self._is_authorized_for_section(session, section_id, user_id):
            raise ValueError(
                f"User '{user_id}' not authorized for section '{section_id}'"
            )

        proposal.status = ProposalStatus.ACCEPTED
        filename = self._section_filename(session, section_id)
        base = self._session_dir(session_id)

        self.git.commit(
            f"accept: {proposal_id} on {filename}",
            {
                f"{base}/proposals/{filename}/{proposal_id}.json": proposal.model_dump_json(
                    indent=2
                ),
                f"{base}/sections/{filename}.md": proposal.revised_text,
            },
        )
        return section_id

    def reject_proposal(self, session_id: str, proposal_id: str, user_id: str) -> str:
        session = self._require_session(session_id)
        self._require_active(session)

        result = self._find_proposal(session, proposal_id)
        if result is None:
            raise ValueError(f"Proposal '{proposal_id}' not found")
        section_id, proposal = result

        if proposal.status != ProposalStatus.PENDING:
            raise ValueError(
                f"Proposal '{proposal_id}' is already {proposal.status.value}"
            )

        if not self._is_authorized_for_section(session, section_id, user_id):
            raise ValueError(
                f"User '{user_id}' not authorized for section '{section_id}'"
            )

        proposal.status = ProposalStatus.REJECTED
        filename = self._section_filename(session, section_id)
        base = self._session_dir(session_id)

        self.git.commit(
            f"reject: {proposal_id} on {filename}",
            {
                f"{base}/proposals/{filename}/{proposal_id}.json": proposal.model_dump_json(
                    indent=2
                )
            },
        )
        return section_id

    def approve_section(self, session_id: str, section_id: str, user_id: str) -> None:
        session = self._require_session(session_id)
        self._require_active(session)
        if section_id not in session.section_meta:
            raise ValueError(f"Section '{section_id}' not found")

        status = session.section_meta[section_id].status
        if status not in (SectionStatus.DRAFT, SectionStatus.IN_REVIEW):
            raise ValueError(
                f"Section '{section_id}' cannot be approved from status '{status.value}'"
            )

        if not self._is_authorized_for_section(session, section_id, user_id):
            raise ValueError(
                f"User '{user_id}' not authorized for section '{section_id}'"
            )
        session.section_meta[section_id].status = SectionStatus.APPROVED
        self._save_session(session, f"approve: section {section_id}")

    def reopen_section(self, session_id: str, section_id: str, user_id: str) -> None:
        session = self._require_session(session_id)
        self._require_active(session)
        if section_id not in session.section_meta:
            raise ValueError(f"Section '{section_id}' not found")
        if session.section_meta[section_id].status != SectionStatus.APPROVED:
            raise ValueError(f"Section '{section_id}' is not approved")
        session.section_meta[section_id].status = SectionStatus.IN_REVIEW
        self._save_session(session, f"reopen: section {section_id}")

    def skip_section(self, session_id: str, section_id: str, user_id: str) -> None:
        session = self._require_session(session_id)
        self._require_active(session)
        if section_id not in session.section_meta:
            raise ValueError(f"Section '{section_id}' not found")

        status = session.section_meta[section_id].status
        if status in (
            SectionStatus.APPROVED,
            SectionStatus.SKIPPED,
            SectionStatus.DRAFTING,
        ):
            raise ValueError(
                f"Section '{section_id}' cannot be skipped from status '{status.value}'"
            )

        if not self._is_authorized_for_section(session, section_id, user_id):
            raise ValueError(
                f"User '{user_id}' not authorized for section '{section_id}'"
            )

        template = self._require_template(session)
        section_def = next((s for s in template.sections if s.id == section_id), None)
        if section_def is None:
            raise ValueError(f"Section '{section_id}' not in template")
        if section_def.priority == SectionPriority.REQUIRED:
            raise ValueError(
                f"Section '{section_id}' is required and cannot be skipped"
            )

        session.section_meta[section_id].status = SectionStatus.SKIPPED
        self._save_session(session, f"skip: section {section_id}")

    def assign_section(self, session_id: str, section_id: str, user_id: str) -> None:
        session = self._require_session(session_id)
        self._require_active(session)

        if section_id not in session.section_meta:
            raise ValueError(f"Section '{section_id}' not found")

        for p in session.participants:
            if section_id in p.assigned_sections:
                p.assigned_sections.remove(section_id)

        target = next((p for p in session.participants if p.user_id == user_id), None)
        if target:
            target.assigned_sections.append(section_id)
        else:
            session.participants.append(
                Participant(
                    user_id=user_id,
                    token=secrets.token_urlsafe(24),
                    assigned_sections=[section_id],
                    role="participant",
                )
            )

        self._save_session(session, f"assign: {section_id} to {user_id}")

    def is_ready_to_publish(self, session_id: str) -> bool:
        session = self._require_session(session_id)
        template = self._require_template(session)
        for section in template.sections:
            if section.priority == SectionPriority.REQUIRED:
                meta = session.section_meta.get(section.id)
                if meta is None or meta.status != SectionStatus.APPROVED:
                    return False
        return True

    def get_progress(self, session_id: str) -> ProgressInfo:
        session = self._require_session(session_id)
        template = self._require_template(session)
        return ProgressInfo(
            total=len(template.sections),
            approved=sum(
                1
                for m in session.section_meta.values()
                if m.status == SectionStatus.APPROVED
            ),
            skipped=sum(
                1
                for m in session.section_meta.values()
                if m.status == SectionStatus.SKIPPED
            ),
            required_remaining=sum(
                1
                for s in template.sections
                if s.priority == SectionPriority.REQUIRED
                and session.section_meta.get(s.id)
                and session.section_meta[s.id].status != SectionStatus.APPROVED
            ),
        )

    def get_section_content(
        self, session_id: str, section_id: str
    ) -> SectionContentResponse:
        session = self._require_session(session_id)
        meta = session.section_meta.get(section_id)
        if meta is None:
            raise ValueError(f"Section '{section_id}' not found")
        content = self.git.read_file(
            f"{self._session_dir(session_id)}/sections/{meta.filename}.md"
        )
        return SectionContentResponse(
            section_id=section_id,
            content=content or "",
            status=meta.status.value,
        )

    def get_approved_sections(self, session_id: str) -> list[SectionContent]:
        session = self._require_session(session_id)
        template = self._require_template(session)
        sections: list[SectionContent] = []
        for section_def in template.sections:
            meta = session.section_meta.get(section_def.id)
            if meta and meta.status == SectionStatus.APPROVED:
                content = self.git.read_file(
                    f"{self._session_dir(session_id)}/sections/{meta.filename}.md"
                )
                sections.append(
                    SectionContent(title=section_def.title, content=content or "")
                )
        return sections

    def mark_published(self, session_id: str, output_ref: str) -> None:
        session = self._require_session(session_id)
        session.status = SessionStatus.PUBLISHED
        session.published_at = datetime.now(timezone.utc)
        session.output_ref = output_ref
        self._save_session(session, f"publish: session published to {output_ref}")

    def set_agent_session_id(self, session_id: str, agent_session_id: str) -> None:
        session = self._require_session(session_id)
        session.agent_session_id = agent_session_id
        self._save_session(session, f"session: store agent session ID for {session_id}")

    def set_section_status(
        self, session_id: str, section_id: str, status: SectionStatus
    ) -> None:
        session = self._require_session(session_id)
        if section_id not in session.section_meta:
            raise ValueError(f"Section '{section_id}' not found")
        session.section_meta[section_id].status = status
        self._save_session(session, f"status: {section_id} → {status.value}")

    def begin_drafting(self, session_id: str) -> None:
        session = self._require_session(session_id)
        for meta in session.section_meta.values():
            meta.status = SectionStatus.DRAFTING
        self._save_session(session, f"draft: begin AI drafts for {session_id}")

    def recover_drafting(self, session_id: str) -> None:
        session = self._require_session(session_id)
        changed = False
        for meta in session.section_meta.values():
            if meta.status == SectionStatus.DRAFTING:
                meta.status = SectionStatus.DRAFT
                changed = True
        if changed:
            self._save_session(
                session,
                f"draft: recover stuck sections for {session_id}",
            )
