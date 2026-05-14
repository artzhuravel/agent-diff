"""Session-first CRUD operations for Asana.

Functions are added to this file one at a time during the resource
implementation loop. Every function takes a SQLAlchemy Session as the first
argument. No function accesses request state directly.

AGENT INSTRUCTION: Do not write this file from scratch. Each entity
implementation adds its operation functions to this file incrementally.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
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


def create_project(session: Session, data: dict[str, Any], creator_gid: str | None = None) -> AsanaProject:
    now = now_iso()

    # Resolve scalar FK targets, creating stubs if needed
    # If no explicit owner, use the creator (principal user)
    owner_gid = data.get("owner") or creator_gid
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

    project_gid = generate_id("project")
    # Synthesize permalink_url following Asana's pattern: /1/<workspace_gid>/project/<project_gid>
    synthesized_permalink = f"https://app.asana.com/1/{workspace_gid or '0'}/project/{project_gid}"

    project = AsanaProject(
        gid=project_gid,
        permalink_url=synthesized_permalink,
        resource_type="project",
        name=data.get("name"),
        archived=data.get("archived", False),
        color=data.get("color"),
        # default icon is "list" when not specified
        icon=data.get("icon", "list"),
        created_at=now,
        modified_at=now,
        # default empty string for notes, not null
        notes=data.get("notes", ""),
        html_notes=data.get("html_notes"),
        # default public to False
        public=data.get("public", False),
        # default privacy_setting to "private"
        privacy_setting=data.get("privacy_setting", "private"),
        # default default_view to "list"
        default_view=data.get("default_view", "list"),
        due_date=data.get("due_date"),
        due_on=data.get("due_on"),
        start_on=data.get("start_on"),
        # default access levels to "editor"
        default_access_level=data.get("default_access_level", "editor"),
        minimum_access_level_for_customization=data.get("minimum_access_level_for_customization", "editor"),
        minimum_access_level_for_sharing=data.get("minimum_access_level_for_sharing", "editor"),
        completed=data.get("completed", False),
        completed_at=data.get("completed_at"),
        owner_gid=owner_gid,
        completed_by_gid=completed_by_gid,
        # auto-assign workspace as team if no explicit team — Asana always returns a team on projects
        team_gid=data.get("team") or workspace_gid,
        workspace_gid=workspace_gid,
        parent_gid=parent_gid,
        custom_fields=data.get("custom_fields"),
        is_deleted=False,
    )
    session.add(project)
    # Flush to obtain the project PK before inserting association rows
    session.flush()

    # Wire M:N members — auto-add creator as member
    member_gids_added: set[str] = set()
    for member_entry in data.get("members") or []:
        member_gid = member_entry if isinstance(member_entry, str) else member_entry.get("gid")
        if member_gid:
            user = _ensure_user_stub(session, member_gid)
            if user not in project.member_users:
                project.member_users.append(user)
                member_gids_added.add(member_gid)
    # Creator becomes a member automatically
    if creator_gid and creator_gid not in member_gids_added:
        creator = _ensure_user_stub(session, creator_gid)
        if creator not in project.member_users:
            project.member_users.append(creator)

    # Wire M:N followers — auto-add creator as follower
    follower_gids_added: set[str] = set()
    for follower_entry in data.get("followers") or []:
        follower_gid = follower_entry if isinstance(follower_entry, str) else follower_entry.get("gid")
        if follower_gid:
            user = _ensure_user_stub(session, follower_gid)
            if user not in project.follower_users:
                project.follower_users.append(user)
                follower_gids_added.add(follower_gid)
    # Creator becomes a follower automatically
    if creator_gid and creator_gid not in follower_gids_added:
        creator = _ensure_user_stub(session, creator_gid)
        if creator not in project.follower_users:
            project.follower_users.append(creator)

    session.flush()
    return project


def get_project(session: Session, project_gid: str) -> Optional[AsanaProject]:
    return session.execute(
        select(AsanaProject)
        .options(
            selectinload(AsanaProject.member_users),
            selectinload(AsanaProject.follower_users),
            selectinload(AsanaProject.owner),
            selectinload(AsanaProject.workspace),
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
    query = (
        select(AsanaProject)
        .options(
            selectinload(AsanaProject.member_users),
            selectinload(AsanaProject.follower_users),
            selectinload(AsanaProject.owner),
            selectinload(AsanaProject.workspace),
        )
        .where(AsanaProject.is_deleted == False)
    )

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
    session: Session, task_gid: str, data: dict[str, Any], creator_gid: str | None = None
) -> AsanaStory:
    # Ensure the parent task exists before flush
    _ensure_task_stub(session, task_gid)

    # Resolve optional FK targets, creating stubs as needed
    # creator defaults to principal user for API-originated stories
    created_by_gid = data.get("created_by") or creator_gid
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

    # target defaults to the task this story is posted on
    target_gid = data.get("target") or task_gid
    if target_gid:
        _ensure_task_stub(session, target_gid)

    parent_story_gid = data.get("story")
    if parent_story_gid:
        _ensure_story_stub(session, parent_story_gid)

    # Determine story type — user-posted comment vs system event
    is_comment = bool(data.get("text"))
    resource_subtype = data.get("resource_subtype") or ("comment_added" if is_comment else None)
    story_type = data.get("type") or ("comment" if is_comment else "system")

    story = AsanaStory(
        gid=generate_id("story"),
        resource_type="story",
        created_at=now_iso(),
        resource_subtype=resource_subtype,
        story_type=story_type,
        text=data.get("text"),
        html_text=data.get("html_text"),
        # defaults for comment stories
        is_pinned=data.get("is_pinned", False),
        sticker_name=data.get("sticker_name"),
        source=data.get("source", "api"),
        is_editable=data.get("is_editable", True if is_comment else False),
        is_edited=data.get("is_edited", False),
        hearted=data.get("hearted", False),
        liked=data.get("liked", False),
        num_hearts=data.get("num_hearts", 0),
        num_likes=data.get("num_likes", 0),
        hearts=data.get("hearts") or [],
        likes=data.get("likes") or [],
        previews=data.get("previews") or [],
        task_gid=task_gid,
        created_by_gid=created_by_gid,
        target_gid=target_gid,
        assignee_gid=assignee_gid,
        follower_gid=follower_gid,
        old_section_gid=old_section_gid,
        new_section_gid=new_section_gid,
        project_gid=project_gid,
        duplicate_of_gid=duplicate_of_gid,
        duplicated_from_gid=duplicated_from_gid,
        dependency_gid=dependency_gid,
        parent_story_gid=parent_story_gid,
        is_deleted=False,
    )
    session.add(story)
    session.flush()
    return story


def get_story(session: Session, story_gid: str) -> Optional[AsanaStory]:
    return session.execute(
        select(AsanaStory)
        .options(
            selectinload(AsanaStory.created_by),
            selectinload(AsanaStory.target),
        )
        .where(
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

    # Order by creation time ascending, then gid as a stable tiebreaker for
    # same-timestamp system stories (matches real Asana's chronicle order).
    query = query.order_by(AsanaStory.created_at, AsanaStory.gid).limit(limit + 1)
    rows = list(session.execute(query).scalars())

    next_offset = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_offset = rows[-1].gid

    return rows, next_offset


# ---------------------------------------------------------------------------
# Task operations
# ---------------------------------------------------------------------------


def create_task(session: Session, data: dict[str, Any], creator_gid: str | None = None) -> AsanaTask:
    now = now_iso()

    # Ensure any FK target stubs exist before flush
    workspace_gid = data.get("workspace")

    # If no workspace provided, infer from the first project membership
    if not workspace_gid:
        project_gids = data.get("projects") or []
        for project_entry in project_gids:
            project_ref_gid = project_entry if isinstance(project_entry, str) else project_entry.get("gid")
            if project_ref_gid:
                project_row = session.get(AsanaProject, project_ref_gid)
                if project_row and project_row.workspace_gid:
                    workspace_gid = project_row.workspace_gid
                    break

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

    created_by_gid = data.get("created_by") or creator_gid
    if created_by_gid:
        _ensure_user_stub(session, created_by_gid)

    assignee_section_gid = data.get("assignee_section")
    if assignee_section_gid:
        _ensure_section_stub(session, assignee_section_gid)

    parent_gid = data.get("parent")
    if parent_gid:
        _ensure_task_stub(session, parent_gid)

    # Normalize projects to compact objects with name resolved from DB
    raw_projects = data.get("projects") or []
    projects_compact: list[dict] = []
    for project_entry in raw_projects:
        project_ref_gid = project_entry if isinstance(project_entry, str) else project_entry.get("gid")
        if project_ref_gid:
            project_row = session.get(AsanaProject, project_ref_gid)
            projects_compact.append({
                "gid": project_ref_gid,
                "resource_type": "project",
                "name": project_row.name if project_row else None,
            })

    # Normalize memberships to compact objects (project and section as compact objects)
    raw_memberships = data.get("memberships") or []
    memberships_compact: list[dict] = []
    for entry in raw_memberships:
        project_ref = entry.get("project") if isinstance(entry, dict) else None
        section_ref = entry.get("section") if isinstance(entry, dict) else None
        project_ref_gid = project_ref if isinstance(project_ref, str) else (project_ref.get("gid") if project_ref else None)
        section_ref_gid = section_ref if isinstance(section_ref, str) else (section_ref.get("gid") if section_ref else None)
        project_compact_entry = None
        section_compact_entry = None
        if project_ref_gid:
            project_row = session.get(AsanaProject, project_ref_gid)
            project_compact_entry = {
                "gid": project_ref_gid,
                "resource_type": "project",
                "name": project_row.name if project_row else None,
            }
        if section_ref_gid:
            section_row = session.get(AsanaSection, section_ref_gid)
            section_compact_entry = {
                "gid": section_ref_gid,
                "resource_type": "section",
                "name": section_row.name if section_row else None,
            }
        membership_entry: dict = {}
        if project_compact_entry:
            membership_entry["project"] = project_compact_entry
        if section_compact_entry:
            membership_entry["section"] = section_compact_entry
        if membership_entry:
            memberships_compact.append(membership_entry)

    # followers stored as compact objects; default to empty list
    raw_followers = data.get("followers") or []
    followers_compact: list[dict] = []
    follower_gids_seen: set[str] = set()
    for follower_entry in raw_followers:
        follower_ref_gid = follower_entry if isinstance(follower_entry, str) else follower_entry.get("gid")
        if follower_ref_gid and follower_ref_gid not in follower_gids_seen:
            user_row = session.get(AsanaUser, follower_ref_gid)
            followers_compact.append({
                "gid": follower_ref_gid,
                "resource_type": "user",
                "name": user_row.name if user_row else None,
            })
            follower_gids_seen.add(follower_ref_gid)
    # Real Asana auto-adds the creator as a follower on task creation
    if creator_gid and creator_gid not in follower_gids_seen:
        creator_user_row = session.get(AsanaUser, creator_gid)
        followers_compact.append({
            "gid": creator_gid,
            "resource_type": "user",
            "name": creator_user_row.name if creator_user_row else None,
        })

    task_gid = generate_id("task")
    # Synthesize permalink_url; use first project's gid if available, or an explicit
    # hint passed by create_subtask to use the parent's project for the URL.
    first_project_gid = projects_compact[0].get("gid") if projects_compact else data.get("_permalink_project_gid")
    task_permalink = f"https://app.asana.com/1/{workspace_gid or '0'}/project/{first_project_gid or '0'}/task/{task_gid}"

    task = AsanaTask(
        gid=task_gid,
        permalink_url=task_permalink,
        resource_type="task",
        resource_subtype=data.get("resource_subtype", "default_task"),
        name=data.get("name"),
        # default empty string for notes, not null
        notes=data.get("notes", ""),
        html_notes=data.get("html_notes"),
        completed=data.get("completed", False),
        completed_at=data.get("completed_at"),
        created_at=now,
        modified_at=now,
        approval_status=data.get("approval_status"),
        # default assignee_status to "upcoming"
        assignee_status=data.get("assignee_status", "upcoming"),
        due_at=data.get("due_at"),
        due_on=data.get("due_on"),
        start_at=data.get("start_at"),
        start_on=data.get("start_on"),
        # default liked and hearted to False (not null)
        liked=data.get("liked", False),
        hearted=data.get("hearted", False),
        # default counts to 0
        num_likes=data.get("num_likes", 0),
        num_hearts=data.get("num_hearts", 0),
        # actual_time_minutes: real Asana returns 0 on new tasks, not null
        actual_time_minutes=data.get("actual_time_minutes", 0),
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
        # projects and memberships stored as compact objects for faithful read-back
        projects=projects_compact,
        followers=followers_compact,
        memberships=memberships_compact,
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

    # Auto-generate system stories for significant fields set at creation time,
    # matching the audit-trail entries the real Asana API creates.
    # Each story gets a slightly later timestamp (1 ms apart) so the ORDER BY
    # created_at query returns them in the real Asana chronicle order:
    #   added_to_project → section_changed → assigned → added_to_tag
    if creator_gid:
        creator_row = session.get(AsanaUser, creator_gid)
        creator_name = creator_row.name if creator_row else "Unknown"
        # Base timestamp as a datetime so we can add millisecond offsets
        story_base_dt = datetime.now(timezone.utc)
        story_counter = 0

        def _next_story_ts() -> str:
            nonlocal story_counter
            ts = story_base_dt + timedelta(milliseconds=story_counter)
            story_counter += 1
            return ts.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        # one story per project membership
        for compact_entry in projects_compact:
            project_name = compact_entry.get("name") or "Unknown project"
            _auto_story(
                session=session,
                task_gid=task.gid,
                creator_gid=creator_gid,
                target_gid=task.gid,
                resource_subtype="added_to_project",
                text=f"{creator_name} added this task to {project_name}",
                created_at=_next_story_ts(),
            )

        # one story per section membership
        for membership_entry in memberships_compact:
            section_compact_entry = membership_entry.get("section")
            project_compact_entry = membership_entry.get("project")
            if section_compact_entry:
                section_name = section_compact_entry.get("name") or "Unknown section"
                project_name = project_compact_entry.get("name") if project_compact_entry else "Unknown project"
                _auto_story(
                    session=session,
                    task_gid=task.gid,
                    creator_gid=creator_gid,
                    target_gid=task.gid,
                    resource_subtype="section_changed",
                    text=f'{creator_name} moved this task from "Untitled section" to "{section_name}" in {project_name}',
                    created_at=_next_story_ts(),
                )

        # one story for the assignee
        if assignee_gid:
            _auto_story(
                session=session,
                task_gid=task.gid,
                creator_gid=creator_gid,
                target_gid=task.gid,
                resource_subtype="assigned",
                text=f"{creator_name} assigned to you",
                created_at=_next_story_ts(),
            )

        # one story per tag
        for tag_gid in (data.get("tags") or []):
            tag_row = session.get(AsanaTag, tag_gid)
            tag_name = tag_row.name if tag_row else tag_gid
            _auto_story(
                session=session,
                task_gid=task.gid,
                creator_gid=creator_gid,
                target_gid=task.gid,
                resource_subtype="added_to_tag",
                text=f"{creator_name} added this task to {tag_name}",
                created_at=_next_story_ts(),
            )

        session.flush()

    return task


def _auto_story(
    session: Session,
    task_gid: str,
    creator_gid: str,
    target_gid: str,
    resource_subtype: str,
    text: str,
    created_at: str,
) -> AsanaStory:
    """Insert a system-generated story row for audit-trail side effects."""
    story = AsanaStory(
        gid=generate_id("story"),
        resource_type="story",
        created_at=created_at,
        resource_subtype=resource_subtype,
        story_type="system",
        text=text,
        source="api",
        is_pinned=False,
        is_editable=False,
        is_edited=False,
        hearted=False,
        liked=False,
        num_hearts=0,
        num_likes=0,
        hearts=[],
        likes=[],
        previews=[],
        task_gid=task_gid,
        created_by_gid=creator_gid,
        target_gid=target_gid,
        is_deleted=False,
    )
    session.add(story)
    return story


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
        # projects is now stored as compact objects; match by gid field
        query = query.where(
            AsanaTask.projects.cast(_JSONB).contains([{"gid": project_gid}])
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
            # projects stored as compact objects; match by gid field
            AsanaTask.projects.cast(_JSONB).contains([{"gid": project_gid}]),
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
    session: Session, parent_task_gid: str, data: dict[str, Any], creator_gid: str | None = None
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
    # Inject parent gid so create_task wires the FK correctly; also propagate
    # workspace from the parent so the subtask doesn't end up with null workspace.
    subtask_data = dict(data)
    subtask_data["parent"] = parent_task_gid
    if not subtask_data.get("workspace") and parent.workspace_gid:
        subtask_data["workspace"] = parent.workspace_gid
    # Pass the parent's first project for permalink synthesis — real Asana uses
    # the parent's project in the subtask permalink even when the subtask itself
    # has no project memberships.
    if not subtask_data.get("projects"):
        parent_projects = parent.projects or []
        if parent_projects:
            first_parent_project = parent_projects[0]
            parent_project_gid = (
                first_parent_project.get("gid")
                if isinstance(first_parent_project, dict)
                else first_parent_project
            )
            if parent_project_gid:
                subtask_data["_permalink_project_gid"] = parent_project_gid
    return create_task(session, subtask_data, creator_gid=creator_gid)


# ---------------------------------------------------------------------------
# Tag operations
# ---------------------------------------------------------------------------


def create_tag(session: Session, data: dict[str, Any]) -> AsanaTag:
    workspace_gid = data.get("workspace")
    if workspace_gid:
        _ensure_workspace_stub(session, workspace_gid)

    tag_gid = generate_id("tag")
    # Synthesize permalink_url following Asana's pattern
    synthesized_permalink = f"https://app.asana.com/1/{workspace_gid or '0'}/project/{tag_gid}"

    tag = AsanaTag(
        gid=tag_gid,
        resource_type="tag",
        name=data.get("name"),
        color=data.get("color"),
        # default empty string for notes, not null
        notes=data.get("notes", ""),
        created_at=now_iso(),
        permalink_url=synthesized_permalink,
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
