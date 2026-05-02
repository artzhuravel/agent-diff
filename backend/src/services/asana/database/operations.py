"""Session-first CRUD operations for Asana.

Functions are added to this file one at a time during the resource
implementation loop. Every function takes a SQLAlchemy Session as the first
argument. No function accesses request state directly.

AGENT INSTRUCTION: Do not write this file from scratch. Each entity
implementation adds its operation functions to this file incrementally.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..core.utils import generate_id, now_iso
from .schema import AsanaProject, AsanaSection, AsanaStory, AsanaTag, AsanaTask, AsanaUser, AsanaWorkspace, asana_tag_followers, asana_user_workspaces


# ---------------------------------------------------------------------------
# Stub-creation helpers — ensure FK target rows exist before flush
# ---------------------------------------------------------------------------


def _ensure_user_stub(session: Session, gid: str) -> AsanaUser:
    """Return existing AsanaUser or insert a minimal stub row."""
    user = session.get(AsanaUser, gid)
    if user is None:
        user = AsanaUser(gid=gid)
        session.add(user)
    return user


def _ensure_workspace_stub(session: Session, gid: str) -> AsanaWorkspace:
    """Return existing AsanaWorkspace or insert a minimal stub row."""
    workspace = session.get(AsanaWorkspace, gid)
    if workspace is None:
        workspace = AsanaWorkspace(gid=gid)
        session.add(workspace)
    return workspace


def _ensure_project_stub(session: Session, gid: str) -> AsanaProject:
    """Return existing AsanaProject or insert a minimal stub row."""
    project = session.get(AsanaProject, gid)
    if project is None:
        project = AsanaProject(gid=gid)
        session.add(project)
    return project


# ---------------------------------------------------------------------------
# Workspace operations
# ---------------------------------------------------------------------------


def get_workspace(session: Session, workspace_gid: str) -> Optional[AsanaWorkspace]:
    return session.execute(
        select(AsanaWorkspace).where(
            AsanaWorkspace.gid == workspace_gid,
            AsanaWorkspace.is_deleted == False,
        )
    ).scalar_one_or_none()


def list_workspaces(
    session: Session,
    offset: Optional[str] = None,
    limit: int = 50,
) -> tuple[list[AsanaWorkspace], Optional[str]]:
    query = select(AsanaWorkspace).where(AsanaWorkspace.is_deleted == False)

    # Cursor pagination: offset is the last-seen gid
    if offset is not None:
        query = query.where(AsanaWorkspace.gid > offset)

    query = query.order_by(AsanaWorkspace.gid).limit(limit + 1)
    rows = list(session.execute(query).scalars())

    next_offset = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_offset = rows[-1].gid

    return rows, next_offset


# ---------------------------------------------------------------------------
# User operations
# ---------------------------------------------------------------------------


def create_user(session: Session, data: dict[str, Any]) -> AsanaUser:
    user = AsanaUser(
        gid=generate_id("user"),
        resource_type="user",
        name=data.get("name"),
        email=data.get("email"),
        photo=data.get("photo"),
        is_deleted=False,
    )
    session.add(user)
    session.flush()

    # Wire workspace memberships
    for workspace_entry in data.get("workspaces") or []:
        workspace_gid = workspace_entry if isinstance(workspace_entry, str) else workspace_entry.get("gid")
        if workspace_gid:
            workspace = _ensure_workspace_stub(session, workspace_gid)
            if workspace not in user.workspaces:
                user.workspaces.append(workspace)

    session.flush()
    return user


def get_user(session: Session, user_gid: str) -> Optional[AsanaUser]:
    return session.execute(
        select(AsanaUser)
        .options(selectinload(AsanaUser.workspaces))
        .where(
            AsanaUser.gid == user_gid,
            AsanaUser.is_deleted == False,
        )
    ).scalar_one_or_none()


def list_users(
    session: Session,
    workspace_gid: Optional[str] = None,
    offset: Optional[str] = None,
    limit: int = 50,
) -> tuple[list[AsanaUser], Optional[str]]:
    query = select(AsanaUser).where(AsanaUser.is_deleted == False)

    if workspace_gid is not None:
        # Filter to users who are members of the given workspace via the M:N table
        query = query.where(
            AsanaUser.gid.in_(
                select(asana_user_workspaces.c.user_gid).where(
                    asana_user_workspaces.c.workspace_gid == workspace_gid
                )
            )
        )

    if offset is not None:
        query = query.where(AsanaUser.gid > offset)

    query = query.order_by(AsanaUser.gid).limit(limit + 1)
    rows = list(session.execute(query).scalars())

    next_offset = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_offset = rows[-1].gid

    return rows, next_offset


def update_user(
    session: Session, user_gid: str, data: dict[str, Any]
) -> Optional[AsanaUser]:
    user = get_user(session, user_gid)
    if user is None:
        return None

    if "name" in data:
        user.name = data["name"]
    if "email" in data:
        user.email = data["email"]
    if "photo" in data:
        user.photo = data["photo"]

    # Replace workspace memberships if provided
    if "workspaces" in data:
        user.workspaces.clear()
        for workspace_entry in data["workspaces"] or []:
            workspace_gid = workspace_entry if isinstance(workspace_entry, str) else workspace_entry.get("gid")
            if workspace_gid:
                workspace = _ensure_workspace_stub(session, workspace_gid)
                if workspace not in user.workspaces:
                    user.workspaces.append(workspace)

    session.flush()
    return user


def delete_user(session: Session, user_gid: str) -> bool:
    user = get_user(session, user_gid)
    if user is None:
        return False
    user.is_deleted = True
    session.flush()
    return True


# ---------------------------------------------------------------------------
# Project operations
# ---------------------------------------------------------------------------


def create_project(session: Session, data: dict[str, Any]) -> AsanaProject:
    now = now_iso()

    # Resolve scalar FK targets, creating stubs if needed
    owner_gid = data.get("owner")
    if owner_gid:
        _ensure_user_stub(session, owner_gid)

    completed_by_gid = data.get("completed_by")
    if completed_by_gid:
        _ensure_user_stub(session, completed_by_gid)

    workspace_gid = data.get("workspace")
    if workspace_gid:
        _ensure_workspace_stub(session, workspace_gid)

    parent_gid = data.get("parent")
    # No stub needed for self-referential parent — caller must create the parent first

    project = AsanaProject(
        gid=generate_id("project"),
        resource_type="project",
        name=data.get("name"),
        archived=data.get("archived", False),
        color=data.get("color"),
        icon=data.get("icon"),
        created_at=now,
        modified_at=now,
        notes=data.get("notes"),
        html_notes=data.get("html_notes"),
        public=data.get("public"),
        privacy_setting=data.get("privacy_setting"),
        default_view=data.get("default_view"),
        due_date=data.get("due_date"),
        due_on=data.get("due_on"),
        start_on=data.get("start_on"),
        default_access_level=data.get("default_access_level"),
        minimum_access_level_for_customization=data.get("minimum_access_level_for_customization"),
        minimum_access_level_for_sharing=data.get("minimum_access_level_for_sharing"),
        completed=data.get("completed", False),
        completed_at=data.get("completed_at"),
        owner_gid=owner_gid,
        completed_by_gid=completed_by_gid,
        team_gid=data.get("team"),
        workspace_gid=workspace_gid,
        parent_gid=parent_gid,
        custom_fields=data.get("custom_fields"),
        is_deleted=False,
    )
    session.add(project)
    # Flush to obtain the project PK before inserting association rows
    session.flush()

    # Wire M:N members
    for member_entry in data.get("members") or []:
        member_gid = member_entry if isinstance(member_entry, str) else member_entry.get("gid")
        if member_gid:
            user = _ensure_user_stub(session, member_gid)
            if user not in project.member_users:
                project.member_users.append(user)

    # Wire M:N followers
    for follower_entry in data.get("followers") or []:
        follower_gid = follower_entry if isinstance(follower_entry, str) else follower_entry.get("gid")
        if follower_gid:
            user = _ensure_user_stub(session, follower_gid)
            if user not in project.follower_users:
                project.follower_users.append(user)

    session.flush()
    return project


def get_project(session: Session, project_gid: str) -> Optional[AsanaProject]:
    return session.execute(
        select(AsanaProject)
        .options(
            selectinload(AsanaProject.member_users),
            selectinload(AsanaProject.follower_users),
        )
        .where(
            AsanaProject.gid == project_gid,
            AsanaProject.is_deleted == False,
        )
    ).scalar_one_or_none()


def list_projects(
    session: Session,
    workspace_gid: Optional[str] = None,
    team_gid: Optional[str] = None,
    archived: Optional[bool] = None,
    offset: Optional[str] = None,
    limit: int = 50,
) -> tuple[list[AsanaProject], Optional[str]]:
    query = select(AsanaProject).where(AsanaProject.is_deleted == False)

    if workspace_gid is not None:
        query = query.where(AsanaProject.workspace_gid == workspace_gid)
    if team_gid is not None:
        query = query.where(AsanaProject.team_gid == team_gid)
    if archived is not None:
        query = query.where(AsanaProject.archived == archived)

    # Cursor pagination: offset is the last-seen gid
    if offset is not None:
        query = query.where(AsanaProject.gid > offset)

    query = query.order_by(AsanaProject.gid).limit(limit + 1)
    rows = list(session.execute(query).scalars())

    next_offset = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_offset = rows[-1].gid

    return rows, next_offset


def update_project(
    session: Session, project_gid: str, data: dict[str, Any]
) -> Optional[AsanaProject]:
    project = get_project(session, project_gid)
    if project is None:
        return None

    updatable_fields = [
        "name", "archived", "color", "icon", "notes", "html_notes",
        "public", "privacy_setting", "default_view", "due_date", "due_on",
        "start_on", "default_access_level", "minimum_access_level_for_customization",
        "minimum_access_level_for_sharing", "completed",
    ]
    for field in updatable_fields:
        if field in data:
            setattr(project, field, data[field])

    # Scalar FK fields
    if "owner" in data:
        owner_gid = data["owner"]
        if owner_gid:
            _ensure_user_stub(session, owner_gid)
        project.owner_gid = owner_gid

    if "completed_by" in data:
        completed_by_gid = data["completed_by"]
        if completed_by_gid:
            _ensure_user_stub(session, completed_by_gid)
        project.completed_by_gid = completed_by_gid

    if "workspace" in data:
        workspace_gid = data["workspace"]
        if workspace_gid:
            _ensure_workspace_stub(session, workspace_gid)
        project.workspace_gid = workspace_gid

    if "parent" in data:
        project.parent_gid = data["parent"]

    if "team" in data:
        project.team_gid = data["team"]

    if "custom_fields" in data:
        project.custom_fields = data["custom_fields"]

    # Replace M:N members list if provided
    if "members" in data:
        project.member_users.clear()
        for member_entry in data["members"] or []:
            member_gid = member_entry if isinstance(member_entry, str) else member_entry.get("gid")
            if member_gid:
                user = _ensure_user_stub(session, member_gid)
                if user not in project.member_users:
                    project.member_users.append(user)

    # Replace M:N followers list if provided
    if "followers" in data:
        project.follower_users.clear()
        for follower_entry in data["followers"] or []:
            follower_gid = follower_entry if isinstance(follower_entry, str) else follower_entry.get("gid")
            if follower_gid:
                user = _ensure_user_stub(session, follower_gid)
                if user not in project.follower_users:
                    project.follower_users.append(user)

    if project.completed and project.completed_at is None:
        project.completed_at = now_iso()
    elif not project.completed:
        project.completed_at = None

    project.modified_at = now_iso()
    session.flush()
    return project


def delete_project(session: Session, project_gid: str) -> bool:
    project = get_project(session, project_gid)
    if project is None:
        return False
    project.is_deleted = True
    session.flush()
    return True


# ---------------------------------------------------------------------------
# Section operations
# ---------------------------------------------------------------------------


def create_section(
    session: Session, project_gid: str, data: dict[str, Any]
) -> Optional[AsanaSection]:
    # 404 if the project doesn't exist — do not auto-create a stub
    project = session.execute(
        select(AsanaProject).where(AsanaProject.gid == project_gid)
    ).scalar_one_or_none()
    if project is None:
        return None

    section = AsanaSection(
        gid=generate_id("section"),
        resource_type="section",
        name=data.get("name"),
        created_at=now_iso(),
        project_gid=project_gid,
        is_deleted=False,
    )
    session.add(section)
    session.flush()
    return section


def get_section(session: Session, section_gid: str) -> Optional[AsanaSection]:
    return session.execute(
        select(AsanaSection)
        .options(selectinload(AsanaSection.project))
        .where(
            AsanaSection.gid == section_gid,
            AsanaSection.is_deleted == False,
        )
    ).scalar_one_or_none()


def list_sections(
    session: Session,
    project_gid: str,
    offset: Optional[str] = None,
    limit: int = 50,
) -> Optional[tuple[list[AsanaSection], Optional[str]]]:
    # 404 if the project doesn't exist
    project = session.execute(
        select(AsanaProject).where(AsanaProject.gid == project_gid)
    ).scalar_one_or_none()
    if project is None:
        return None

    query = select(AsanaSection).where(
        AsanaSection.project_gid == project_gid,
        AsanaSection.is_deleted == False,
    )

    if offset is not None:
        query = query.where(AsanaSection.gid > offset)

    query = query.order_by(AsanaSection.gid).limit(limit + 1)
    rows = list(session.execute(query).scalars())

    next_offset = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_offset = rows[-1].gid

    return rows, next_offset


def update_section(
    session: Session, section_gid: str, data: dict[str, Any]
) -> Optional[AsanaSection]:
    section = get_section(session, section_gid)
    if section is None:
        return None

    if "name" in data:
        section.name = data["name"]

    session.flush()
    return section


def delete_section(session: Session, section_gid: str) -> bool:
    section = get_section(session, section_gid)
    if section is None:
        return False
    section.is_deleted = True
    session.flush()
    return True


# ---------------------------------------------------------------------------
# Story operations
# ---------------------------------------------------------------------------


def _ensure_task_stub(session: Session, gid: str) -> AsanaTask:
    """Return existing AsanaTask or insert a minimal stub row."""
    task = session.get(AsanaTask, gid)
    if task is None:
        task = AsanaTask(gid=gid)
        session.add(task)
    return task


def _ensure_section_stub(session: Session, gid: str) -> AsanaSection:
    """Return existing AsanaSection or insert a minimal stub row."""
    section = session.get(AsanaSection, gid)
    if section is None:
        section = AsanaSection(gid=gid)
        session.add(section)
    return section


def _ensure_story_stub(session: Session, gid: str) -> AsanaStory:
    """Return existing AsanaStory or insert a minimal stub row."""
    story = session.get(AsanaStory, gid)
    if story is None:
        story = AsanaStory(gid=gid)
        session.add(story)
    return story


def _ensure_tag_stub(session: Session, gid: str) -> AsanaTag:
    """Return existing AsanaTag or insert a minimal stub row."""
    tag = session.get(AsanaTag, gid)
    if tag is None:
        tag = AsanaTag(gid=gid)
        session.add(tag)
    return tag


def create_story(
    session: Session, task_gid: str, data: dict[str, Any]
) -> AsanaStory:
    # Ensure the parent task exists before flush
    _ensure_task_stub(session, task_gid)

    # Resolve optional FK targets, creating stubs as needed
    created_by_gid = data.get("created_by")
    if created_by_gid:
        _ensure_user_stub(session, created_by_gid)

    assignee_gid = data.get("assignee")
    if assignee_gid:
        _ensure_user_stub(session, assignee_gid)

    follower_gid = data.get("follower")
    if follower_gid:
        _ensure_user_stub(session, follower_gid)

    old_section_gid = data.get("old_section")
    if old_section_gid:
        _ensure_section_stub(session, old_section_gid)

    new_section_gid = data.get("new_section")
    if new_section_gid:
        _ensure_section_stub(session, new_section_gid)

    project_gid = data.get("project")
    if project_gid:
        _ensure_project_stub(session, project_gid)

    duplicate_of_gid = data.get("duplicate_of")
    if duplicate_of_gid:
        _ensure_task_stub(session, duplicate_of_gid)

    duplicated_from_gid = data.get("duplicated_from")
    if duplicated_from_gid:
        _ensure_task_stub(session, duplicated_from_gid)

    dependency_gid = data.get("dependency")
    if dependency_gid:
        _ensure_task_stub(session, dependency_gid)

    target_gid = data.get("target")
    if target_gid:
        _ensure_task_stub(session, target_gid)

    parent_story_gid = data.get("story")
    if parent_story_gid:
        _ensure_story_stub(session, parent_story_gid)

    story = AsanaStory(
        gid=generate_id("story"),
        resource_type="story",
        created_at=now_iso(),
        resource_subtype=data.get("resource_subtype"),
        text=data.get("text"),
        html_text=data.get("html_text"),
        is_pinned=data.get("is_pinned"),
        sticker_name=data.get("sticker_name"),
        task_gid=task_gid,
        created_by_gid=created_by_gid,
        assignee_gid=assignee_gid,
        follower_gid=follower_gid,
        old_section_gid=old_section_gid,
        new_section_gid=new_section_gid,
        project_gid=project_gid,
        duplicate_of_gid=duplicate_of_gid,
        duplicated_from_gid=duplicated_from_gid,
        dependency_gid=dependency_gid,
        target_gid=target_gid,
        parent_story_gid=parent_story_gid,
        is_deleted=False,
    )
    session.add(story)
    session.flush()
    return story


def get_story(session: Session, story_gid: str) -> Optional[AsanaStory]:
    return session.execute(
        select(AsanaStory).where(
            AsanaStory.gid == story_gid,
            AsanaStory.is_deleted == False,
        )
    ).scalar_one_or_none()


def delete_story(session: Session, story_gid: str) -> bool:
    story = get_story(session, story_gid)
    if story is None:
        return False
    story.is_deleted = True
    session.flush()
    return True


def list_stories(
    session: Session,
    task_gid: str,
    offset: Optional[str] = None,
    limit: int = 50,
) -> tuple[list[AsanaStory], Optional[str]]:
    query = (
        select(AsanaStory)
        .options(
            selectinload(AsanaStory.task),
            selectinload(AsanaStory.created_by),
            selectinload(AsanaStory.assignee),
            selectinload(AsanaStory.follower),
            selectinload(AsanaStory.old_section),
            selectinload(AsanaStory.new_section),
            selectinload(AsanaStory.project),
            selectinload(AsanaStory.parent_story),
        )
        .where(
            AsanaStory.task_gid == task_gid,
            AsanaStory.is_deleted == False,
        )
    )

    if offset is not None:
        query = query.where(AsanaStory.gid > offset)

    query = query.order_by(AsanaStory.gid).limit(limit + 1)
    rows = list(session.execute(query).scalars())

    next_offset = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_offset = rows[-1].gid

    return rows, next_offset


# ---------------------------------------------------------------------------
# Task operations
# ---------------------------------------------------------------------------


def create_task(session: Session, data: dict[str, Any]) -> AsanaTask:
    now = now_iso()

    # Ensure any FK target stubs exist before flush
    workspace_gid = data.get("workspace")
    if workspace_gid:
        _ensure_workspace_stub(session, workspace_gid)

    assignee_gid = data.get("assignee")
    if assignee_gid:
        _ensure_user_stub(session, assignee_gid)

    assigned_by_gid = data.get("assigned_by")
    if assigned_by_gid:
        _ensure_user_stub(session, assigned_by_gid)

    completed_by_gid = data.get("completed_by")
    if completed_by_gid:
        _ensure_user_stub(session, completed_by_gid)

    created_by_gid = data.get("created_by")
    if created_by_gid:
        _ensure_user_stub(session, created_by_gid)

    assignee_section_gid = data.get("assignee_section")
    if assignee_section_gid:
        _ensure_section_stub(session, assignee_section_gid)

    parent_gid = data.get("parent")
    if parent_gid:
        _ensure_task_stub(session, parent_gid)

    task = AsanaTask(
        gid=generate_id("task"),
        resource_type="task",
        resource_subtype=data.get("resource_subtype", "default_task"),
        name=data.get("name"),
        notes=data.get("notes"),
        html_notes=data.get("html_notes"),
        completed=data.get("completed", False),
        completed_at=data.get("completed_at"),
        created_at=now,
        modified_at=now,
        approval_status=data.get("approval_status"),
        assignee_status=data.get("assignee_status"),
        due_at=data.get("due_at"),
        due_on=data.get("due_on"),
        start_at=data.get("start_at"),
        start_on=data.get("start_on"),
        liked=data.get("liked"),
        external=data.get("external"),
        workspace_gid=workspace_gid,
        assignee_gid=assignee_gid,
        assigned_by_gid=assigned_by_gid,
        completed_by_gid=completed_by_gid,
        created_by_gid=created_by_gid,
        assignee_section_gid=assignee_section_gid,
        parent_gid=parent_gid,
        custom_type_gid=data.get("custom_type"),
        custom_type_status_option_gid=data.get("custom_type_status_option"),
        custom_fields=data.get("custom_fields"),
        # projects/followers stored as JSONB arrays of gid strings.
        # tags is now a proper M:N — wired below via asana_task_tags.
        projects=data.get("projects") or [],
        followers=data.get("followers") or [],
        memberships=data.get("memberships") or [],
        is_deleted=False,
    )
    session.add(task)
    session.flush()

    # Wire M:N tags. The request body's ``tags`` field is an array of
    # tag gids; ensure each target exists (creating a stub if not), then
    # attach via the relationship.
    for tag_gid in (data.get("tags") or []):
        tag = _ensure_tag_stub(session, tag_gid)
        if tag not in task.tags:
            task.tags.append(tag)
    if data.get("tags"):
        session.flush()
    return task


# Relationship eager-load options shared by every task query so the
# serializer can populate ``name`` on embedded compact objects without
# N+1.
_TASK_LOAD_OPTIONS = (
    selectinload(AsanaTask.assignee),
    selectinload(AsanaTask.assigned_by),
    selectinload(AsanaTask.completed_by),
    selectinload(AsanaTask.created_by),
    selectinload(AsanaTask.assignee_section),
    selectinload(AsanaTask.workspace),
    selectinload(AsanaTask.parent),
    selectinload(AsanaTask.tags),
)


def get_task(session: Session, task_gid: str) -> Optional[AsanaTask]:
    return session.execute(
        select(AsanaTask)
        .options(*_TASK_LOAD_OPTIONS)
        .where(
            AsanaTask.gid == task_gid,
            AsanaTask.is_deleted == False,
        )
    ).scalar_one_or_none()


def list_tasks(
    session: Session,
    workspace_gid: Optional[str] = None,
    project_gid: Optional[str] = None,
    section_gid: Optional[str] = None,
    assignee_gid: Optional[str] = None,
    completed_since: Optional[str] = None,
    modified_since: Optional[str] = None,
    offset: Optional[str] = None,
    limit: int = 50,
) -> tuple[list[AsanaTask], Optional[str]]:
    from sqlalchemy.dialects.postgresql import JSONB as _JSONB

    query = (
        select(AsanaTask)
        .options(*_TASK_LOAD_OPTIONS)
        .where(AsanaTask.is_deleted == False)
    )

    if workspace_gid is not None:
        query = query.where(AsanaTask.workspace_gid == workspace_gid)
    if assignee_gid is not None:
        query = query.where(AsanaTask.assignee_gid == assignee_gid)
    if project_gid is not None:
        query = query.where(
            AsanaTask.projects.cast(_JSONB).contains([project_gid])
        )
    if section_gid is not None:
        query = query.where(
            AsanaTask.memberships.cast(_JSONB).contains(
                [{"section": {"gid": section_gid}}]
            )
        )
    if completed_since is not None:
        query = query.where(AsanaTask.completed_at >= completed_since)
    if modified_since is not None:
        query = query.where(AsanaTask.modified_at >= modified_since)

    if offset is not None:
        query = query.where(AsanaTask.gid > offset)

    query = query.order_by(AsanaTask.gid).limit(limit + 1)
    rows = list(session.execute(query).scalars())

    next_offset = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_offset = rows[-1].gid

    return rows, next_offset


def list_tasks_for_project(
    session: Session,
    project_gid: str,
    offset: Optional[str] = None,
    limit: int = 50,
) -> tuple[list[AsanaTask], Optional[str]]:
    """Return tasks whose projects array contains project_gid."""
    from sqlalchemy.dialects.postgresql import JSONB as _JSONB

    query = (
        select(AsanaTask)
        .options(*_TASK_LOAD_OPTIONS)
        .where(
            AsanaTask.is_deleted == False,
            AsanaTask.projects.cast(_JSONB).contains([project_gid]),
        )
    )

    if offset is not None:
        query = query.where(AsanaTask.gid > offset)

    query = query.order_by(AsanaTask.gid).limit(limit + 1)
    rows = list(session.execute(query).scalars())

    next_offset = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_offset = rows[-1].gid

    return rows, next_offset


def update_task(
    session: Session, task_gid: str, data: dict[str, Any]
) -> Optional[AsanaTask]:
    task = get_task(session, task_gid)
    if task is None:
        return None

    scalar_fields = [
        "name", "notes", "html_notes", "completed", "approval_status",
        "assignee_status", "due_at", "due_on", "start_at", "start_on",
        "liked", "external", "resource_subtype",
    ]
    for field in scalar_fields:
        if field in data:
            setattr(task, field, data[field])

    if "assignee" in data:
        assignee_gid = data["assignee"]
        if assignee_gid:
            _ensure_user_stub(session, assignee_gid)
        task.assignee_gid = assignee_gid

    if "assigned_by" in data:
        assigned_by_gid = data["assigned_by"]
        if assigned_by_gid:
            _ensure_user_stub(session, assigned_by_gid)
        task.assigned_by_gid = assigned_by_gid

    if "completed_by" in data:
        completed_by_gid = data["completed_by"]
        if completed_by_gid:
            _ensure_user_stub(session, completed_by_gid)
        task.completed_by_gid = completed_by_gid

    if "created_by" in data:
        created_by_gid = data["created_by"]
        if created_by_gid:
            _ensure_user_stub(session, created_by_gid)
        task.created_by_gid = created_by_gid

    if "assignee_section" in data:
        assignee_section_gid = data["assignee_section"]
        if assignee_section_gid:
            _ensure_section_stub(session, assignee_section_gid)
        task.assignee_section_gid = assignee_section_gid

    if "workspace" in data:
        workspace_gid = data["workspace"]
        if workspace_gid:
            _ensure_workspace_stub(session, workspace_gid)
        task.workspace_gid = workspace_gid

    if "parent" in data:
        parent_gid = data["parent"]
        if parent_gid:
            _ensure_task_stub(session, parent_gid)
        task.parent_gid = parent_gid

    if "custom_type" in data:
        task.custom_type_gid = data["custom_type"]
    if "custom_type_status_option" in data:
        task.custom_type_status_option_gid = data["custom_type_status_option"]
    if "custom_fields" in data:
        task.custom_fields = data["custom_fields"]

    # Replace the M:N tag set if the body specifies ``tags``. PATCH-style
    # semantics: presence of the key means "set to exactly this list",
    # absence means "leave untouched."
    if "tags" in data:
        new_tag_gids = data.get("tags") or []
        new_tags = [_ensure_tag_stub(session, gid) for gid in new_tag_gids]
        task.tags.clear()
        for tag in new_tags:
            if tag not in task.tags:
                task.tags.append(tag)

    # Sync completed_at when completion state changes
    if task.completed and task.completed_at is None:
        task.completed_at = now_iso()
    elif not task.completed:
        task.completed_at = None

    task.modified_at = now_iso()
    session.flush()
    return task


def delete_task(session: Session, task_gid: str) -> bool:
    task = get_task(session, task_gid)
    if task is None:
        return False
    task.is_deleted = True
    session.flush()
    return True


def list_tasks_for_section(
    session: Session,
    section_gid: str,
    offset: Optional[str] = None,
    limit: int = 50,
) -> tuple[list[AsanaTask], Optional[str]]:
    """Return tasks whose memberships array contains the given section_gid."""
    from sqlalchemy.dialects.postgresql import JSONB as _JSONB

    query = (
        select(AsanaTask)
        .options(*_TASK_LOAD_OPTIONS)
        .where(
            AsanaTask.is_deleted == False,
            AsanaTask.memberships.cast(_JSONB).contains(
                [{"section": {"gid": section_gid}}]
            ),
        )
    )

    if offset is not None:
        query = query.where(AsanaTask.gid > offset)

    query = query.order_by(AsanaTask.gid).limit(limit + 1)
    rows = list(session.execute(query).scalars())

    next_offset = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_offset = rows[-1].gid

    return rows, next_offset


def list_subtasks(
    session: Session,
    parent_task_gid: str,
    offset: Optional[str] = None,
    limit: int = 50,
) -> Optional[tuple[list[AsanaTask], Optional[str]]]:
    """Return direct subtasks of the given parent task, or None if parent not found."""
    # 404 if the parent task doesn't exist
    parent = session.execute(
        select(AsanaTask).where(
            AsanaTask.gid == parent_task_gid,
            AsanaTask.is_deleted == False,
        )
    ).scalar_one_or_none()
    if parent is None:
        return None

    query = (
        select(AsanaTask)
        .options(*_TASK_LOAD_OPTIONS)
        .where(
            AsanaTask.is_deleted == False,
            AsanaTask.parent_gid == parent_task_gid,
        )
    )

    if offset is not None:
        query = query.where(AsanaTask.gid > offset)

    query = query.order_by(AsanaTask.gid).limit(limit + 1)
    rows = list(session.execute(query).scalars())

    next_offset = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_offset = rows[-1].gid

    return rows, next_offset


def create_subtask(
    session: Session, parent_task_gid: str, data: dict[str, Any]
) -> Optional[AsanaTask]:
    """Create a new task whose parent is parent_task_gid. Returns None if parent not found."""
    # 404 if the parent task doesn't exist — do not auto-create a stub
    parent = session.execute(
        select(AsanaTask).where(
            AsanaTask.gid == parent_task_gid,
            AsanaTask.is_deleted == False,
        )
    ).scalar_one_or_none()
    if parent is None:
        return None
    # Inject the parent so create_task wires the FK correctly
    subtask_data = dict(data)
    subtask_data["parent"] = parent_task_gid
    return create_task(session, subtask_data)


# ---------------------------------------------------------------------------
# Tag operations
# ---------------------------------------------------------------------------


def create_tag(session: Session, data: dict[str, Any]) -> AsanaTag:
    workspace_gid = data.get("workspace")
    if workspace_gid:
        _ensure_workspace_stub(session, workspace_gid)

    tag = AsanaTag(
        gid=generate_id("tag"),
        resource_type="tag",
        name=data.get("name"),
        color=data.get("color"),
        notes=data.get("notes"),
        created_at=now_iso(),
        workspace_gid=workspace_gid,
        is_deleted=False,
    )
    session.add(tag)
    session.flush()

    # Wire M:N followers
    for follower_entry in data.get("followers") or []:
        follower_gid = follower_entry if isinstance(follower_entry, str) else follower_entry.get("gid")
        if follower_gid:
            user = _ensure_user_stub(session, follower_gid)
            if user not in tag.follower_users:
                tag.follower_users.append(user)

    session.flush()
    return tag


def get_tag(session: Session, tag_gid: str) -> Optional[AsanaTag]:
    return session.execute(
        select(AsanaTag)
        .options(
            selectinload(AsanaTag.workspace),
            selectinload(AsanaTag.follower_users),
        )
        .where(
            AsanaTag.gid == tag_gid,
            AsanaTag.is_deleted == False,
        )
    ).scalar_one_or_none()


def list_tags(
    session: Session,
    workspace_gid: Optional[str] = None,
    offset: Optional[str] = None,
    limit: int = 50,
) -> tuple[list[AsanaTag], Optional[str]]:
    query = (
        select(AsanaTag)
        .options(
            selectinload(AsanaTag.workspace),
            selectinload(AsanaTag.follower_users),
        )
        .where(AsanaTag.is_deleted == False)
    )

    if workspace_gid is not None:
        query = query.where(AsanaTag.workspace_gid == workspace_gid)

    # Cursor pagination: offset is the last-seen gid
    if offset is not None:
        query = query.where(AsanaTag.gid > offset)

    query = query.order_by(AsanaTag.gid).limit(limit + 1)
    rows = list(session.execute(query).scalars())

    next_offset = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_offset = rows[-1].gid

    return rows, next_offset


def update_tag(
    session: Session, tag_gid: str, data: dict[str, Any]
) -> Optional[AsanaTag]:
    tag = get_tag(session, tag_gid)
    if tag is None:
        return None

    for field in ("name", "color", "notes"):
        if field in data:
            setattr(tag, field, data[field])

    if "workspace" in data:
        workspace_gid = data["workspace"]
        if workspace_gid:
            _ensure_workspace_stub(session, workspace_gid)
        tag.workspace_gid = workspace_gid

    # Replace followers list if provided
    if "followers" in data:
        tag.follower_users.clear()
        for follower_entry in data["followers"] or []:
            follower_gid = follower_entry if isinstance(follower_entry, str) else follower_entry.get("gid")
            if follower_gid:
                user = _ensure_user_stub(session, follower_gid)
                if user not in tag.follower_users:
                    tag.follower_users.append(user)

    session.flush()
    return tag


def delete_tag(session: Session, tag_gid: str) -> bool:
    tag = get_tag(session, tag_gid)
    if tag is None:
        return False
    tag.is_deleted = True
    session.flush()
    return True
