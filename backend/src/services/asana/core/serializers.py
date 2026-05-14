"""Serialization helpers for the Asana API replica.

Each serialize function converts an ORM model into a dict matching the
source API's response shape. Functions are added one at a time during the
resource implementation loop.

AGENT INSTRUCTION: Do not write this file from scratch. Each entity
implementation adds its serializer functions to this file incrementally.
"""

from __future__ import annotations

from typing import Any

from ..database.schema import AsanaProject, AsanaSection, AsanaStory, AsanaTag, AsanaTask, AsanaUser, AsanaWorkspace


def _named_compact(obj: Any, fallback_gid: str | None, resource_type: str) -> dict[str, Any] | None:
    """Emit {gid, resource_type, name} from a loaded relationship.

    Falls back to {gid, resource_type} when the FK column is set but the
    related row wasn't eager-loaded — keeps the response shape valid even
    if a caller forgot to add a selectinload.
    """
    if obj is not None:
        return {
            "gid": obj.gid,
            "resource_type": getattr(obj, "resource_type", None) or resource_type,
            "name": getattr(obj, "name", None),
        }
    if fallback_gid:
        return {"gid": fallback_gid, "resource_type": resource_type}
    return None


def serialize_workspace_compact(workspace: AsanaWorkspace) -> dict[str, Any]:
    """Serialize a workspace to the compact shape (gid, resource_type, name)."""
    return {
        "gid": workspace.gid,
        "resource_type": workspace.resource_type or "workspace",
        "name": workspace.name,
    }


def serialize_workspace(workspace: AsanaWorkspace) -> dict[str, Any]:
    """Serialize a workspace to match the WorkspaceResponse shape (compact only — real Asana omits email_domains/is_organization from standard list/get)."""
    return {
        "gid": workspace.gid,
        "resource_type": workspace.resource_type or "workspace",
        "name": workspace.name,
    }


def serialize_workspace_list(
    workspaces: list[AsanaWorkspace],
    next_offset: str | None = None,
) -> dict[str, Any]:
    """Serialize a list of workspaces with optional pagination info."""
    # Real Asana omits the next_page key entirely when there is no next page
    result: dict[str, Any] = {"data": [serialize_workspace(w) for w in workspaces]}
    if next_offset is not None:
        result["next_page"] = {
            "offset": next_offset,
            "path": f"/workspaces?offset={next_offset}",
            "uri": f"/workspaces?offset={next_offset}",
        }
    return result


def serialize_user_compact(user: AsanaUser) -> dict[str, Any]:
    """Serialize a user to match the UserCompact shape (gid, resource_type, name only)."""
    return {
        "gid": user.gid,
        "resource_type": user.resource_type or "user",
        "name": user.name,
    }


def serialize_user(user: AsanaUser) -> dict[str, Any]:
    """Serialize a user to match the UserResponse shape."""
    return {
        "gid": user.gid,
        "resource_type": user.resource_type or "user",
        "name": user.name,
        "email": user.email,
        "photo": user.photo,
        "workspaces": [
            {"gid": w.gid, "resource_type": "workspace", "name": w.name} for w in user.workspaces
        ],
        "custom_fields": [],
    }


def serialize_user_list(
    users: list[AsanaUser],
    next_offset: str | None = None,
    path_prefix: str = "/users",
) -> dict[str, Any]:
    """Serialize a list of users with optional pagination info."""
    result: dict[str, Any] = {"data": [serialize_user_compact(u) for u in users]}
    if next_offset is not None:
        result["next_page"] = {
            "offset": next_offset,
            "path": f"{path_prefix}?offset={next_offset}",
            "uri": f"{path_prefix}?offset={next_offset}",
        }
    # Real Asana omits the next_page key entirely when there is no next page
    return result


def serialize_project(project: AsanaProject) -> dict[str, Any]:
    """Serialize a project to match the ProjectResponse shape."""
    return {
        "gid": project.gid,
        "resource_type": project.resource_type or "project",
        "name": project.name,
        "archived": project.archived,
        "color": project.color,
        "icon": project.icon,
        "created_at": project.created_at,
        "modified_at": project.modified_at,
        "notes": project.notes,
        "public": project.public,
        "privacy_setting": project.privacy_setting,
        "default_view": project.default_view,
        "due_date": project.due_date,
        "due_on": project.due_on,
        "start_on": project.start_on,
        "default_access_level": project.default_access_level,
        "minimum_access_level_for_customization": project.minimum_access_level_for_customization,
        "minimum_access_level_for_sharing": project.minimum_access_level_for_sharing,
        "completed": project.completed,
        "completed_at": project.completed_at,
        "permalink_url": project.permalink_url,
        # Scalar FK reference fields serialized as compact objects with name
        "owner": _named_compact(project.owner, project.owner_gid, "user"),
        # team name is the workspace name (Asana's convention for workspace-level teams)
        "team": {
            "gid": project.team_gid,
            "resource_type": "team",
            "name": project.workspace.name if project.workspace else None,
        } if project.team_gid else None,
        "workspace": _named_compact(project.workspace, project.workspace_gid, "workspace"),
        "completed_by": _named_compact(project.completed_by, project.completed_by_gid, "user"),
        # Self-referential parent
        "parent": {"gid": project.parent_gid, "resource_type": "project"} if project.parent_gid else None,
        # M:N relationships serialized as compact user lists with name
        "members": [{"gid": u.gid, "resource_type": "user", "name": u.name} for u in project.member_users],
        "followers": [{"gid": u.gid, "resource_type": "user", "name": u.name} for u in project.follower_users],
        # JSONB fields passed through as-is
        "current_status": project.current_status,
        "current_status_update": project.current_status_update,
        "custom_field_settings": project.custom_field_settings or [],
        "custom_fields": project.custom_fields or [],
    }


def serialize_project_list(
    projects: list[AsanaProject],
    next_offset: str | None = None,
) -> dict[str, Any]:
    """Serialize a list of projects with optional pagination info."""
    result: dict[str, Any] = {"data": [serialize_project(p) for p in projects]}
    if next_offset is not None:
        result["next_page"] = {
            "offset": next_offset,
            "path": f"/projects?offset={next_offset}",
            "uri": f"/projects?offset={next_offset}",
        }
    # Real Asana omits the next_page key entirely when there is no next page
    return result


def serialize_section(section: AsanaSection) -> dict[str, Any]:
    """Serialize a section to match the SectionResponse shape."""
    # Use the loaded relationship for the project compact if available (provides name)
    if section.project is not None:
        project_compact = {
            "gid": section.project.gid,
            "resource_type": section.project.resource_type or "project",
            "name": section.project.name,
        }
    elif section.project_gid:
        project_compact = {"gid": section.project_gid, "resource_type": "project"}
    else:
        project_compact = None
    return {
        "gid": section.gid,
        "resource_type": section.resource_type or "section",
        "created_at": section.created_at,
        "name": section.name,
        "project": project_compact,
        # Real Asana does NOT return the deprecated "projects" array on POST /projects/:id/sections
    }


def serialize_section_list(
    sections: list[AsanaSection],
    next_offset: str | None = None,
) -> dict[str, Any]:
    """Serialize a list of sections with optional pagination info."""
    result: dict[str, Any] = {"data": [serialize_section(s) for s in sections]}
    if next_offset is not None:
        result["next_page"] = {
            "offset": next_offset,
            "path": f"/sections?offset={next_offset}",
            "uri": f"/sections?offset={next_offset}",
        }
    # Real Asana omits the next_page key entirely when there is no next page
    return result


def serialize_story(story: AsanaStory) -> dict[str, Any]:
    """Serialize a story to match the StoryResponse shape (used for POST response)."""
    # created_by compact with name from loaded relationship
    created_by_compact = _named_compact(story.created_by, story.created_by_gid, "user")

    # target compact — task with name and resource_subtype
    if story.target is not None:
        target_compact = {
            "gid": story.target.gid,
            "resource_type": story.target.resource_type or "task",
            "name": story.target.name,
            "resource_subtype": story.target.resource_subtype,
        }
    elif story.target_gid:
        target_compact = {"gid": story.target_gid, "resource_type": "task"}
    else:
        target_compact = None

    return {
        "gid": story.gid,
        "resource_type": story.resource_type or "story",
        "created_at": story.created_at,
        "source": story.source,
        "type": story.story_type,
        "is_pinned": story.is_pinned,
        "is_edited": story.is_edited,
        "num_hearts": story.num_hearts,
        "num_likes": story.num_likes,
        "text": story.text,
        "resource_subtype": story.resource_subtype,
        "hearted": story.hearted,
        "liked": story.liked,
        "hearts": story.hearts or [],
        "likes": story.likes or [],
        "previews": story.previews or [],
        "is_editable": story.is_editable,
        "created_by": created_by_compact,
        "target": target_compact,
    }


def serialize_story_compact(story: AsanaStory) -> dict[str, Any]:
    """Serialize a story to the compact shape used in list responses."""
    created_by_compact = _named_compact(story.created_by, story.created_by_gid, "user")
    return {
        "gid": story.gid,
        "created_at": story.created_at,
        "created_by": created_by_compact,
        "resource_type": story.resource_type or "story",
        "text": story.text,
        "type": story.story_type,
        "resource_subtype": story.resource_subtype,
    }


def serialize_story_list(
    stories: list[AsanaStory],
    next_offset: str | None = None,
    task_gid: str | None = None,
) -> dict[str, Any]:
    """Serialize a list of stories with optional pagination info (compact shape)."""
    # Real Asana returns compact story objects in lists (no reaction_summary, previews etc.)
    result: dict[str, Any] = {"data": [serialize_story_compact(s) for s in stories]}
    if next_offset is not None:
        path_suffix = f"/tasks/{task_gid}/stories?offset={next_offset}" if task_gid else f"?offset={next_offset}"
        result["next_page"] = {
            "offset": next_offset,
            "path": path_suffix,
            "uri": path_suffix,
        }
    return result


def serialize_task(task: AsanaTask) -> dict[str, Any]:
    """Serialize a task to match the TaskResponse shape."""
    return {
        "gid": task.gid,
        "resource_type": task.resource_type or "task",
        "created_at": task.created_at,
        "modified_at": task.modified_at,
        "name": task.name,
        "notes": task.notes,
        "actual_time_minutes": task.actual_time_minutes,
        "completed": task.completed,
        "completed_at": task.completed_at,
        "due_on": task.due_on,
        "due_at": task.due_at,
        "start_on": task.start_on,
        "start_at": task.start_at,
        "resource_subtype": task.resource_subtype,
        "num_hearts": task.num_hearts,
        "num_likes": task.num_likes,
        "assignee_status": task.assignee_status,
        "hearted": task.hearted,
        "liked": task.liked,
        # FK reference fields as compact objects, populating ``name`` from
        # the eager-loaded relationship when present.
        "workspace": _named_compact(task.workspace, task.workspace_gid, "workspace"),
        "assignee": _named_compact(task.assignee, task.assignee_gid, "user"),
        "assignee_section": _named_compact(task.assignee_section, task.assignee_section_gid, "section"),
        "parent": (
            {
                "gid": task.parent.gid,
                "resource_type": task.parent.resource_type or "task",
                "name": task.parent.name,
                "resource_subtype": task.parent.resource_subtype,
            }
            if task.parent is not None
            else ({"gid": task.parent_gid, "resource_type": "task"} if task.parent_gid else None)
        ),
        # JSONB array fields passed through as-is
        "hearts": task.hearts or [],
        "likes": task.likes or [],
        "followers": [
            entry if isinstance(entry, dict) else {"gid": entry, "resource_type": "user", "name": None}
            for entry in (task.followers or [])
        ],
        "tags": [
            {"gid": tag.gid, "resource_type": tag.resource_type or "tag", "name": tag.name}
            for tag in (task.tags or [])
        ],
        "permalink_url": task.permalink_url,
        # projects stored as compact objects with name
        "projects": [
            entry if isinstance(entry, dict) else {"gid": entry, "resource_type": "project", "name": None}
            for entry in (task.projects or [])
        ],
        "custom_fields": task.custom_fields or [],
        # memberships stored as compact objects {project: {...}, section: {...}}
        "memberships": task.memberships or [],
    }


def serialize_task_compact(task: AsanaTask) -> dict[str, Any]:
    """Serialize a task to the compact shape used in subtask lists."""
    return {
        "gid": task.gid,
        "name": task.name,
        "resource_type": task.resource_type or "task",
        "resource_subtype": task.resource_subtype,
    }


def serialize_task_list(
    tasks: list[AsanaTask],
    next_offset: str | None = None,
    path_prefix: str = "/tasks",
    compact: bool = False,
) -> dict[str, Any]:
    """Serialize a list of tasks with optional pagination info."""
    serializer = serialize_task_compact if compact else serialize_task
    result: dict[str, Any] = {"data": [serializer(t) for t in tasks]}
    if next_offset is not None:
        result["next_page"] = {
            "offset": next_offset,
            "path": f"{path_prefix}?offset={next_offset}",
            "uri": f"{path_prefix}?offset={next_offset}",
        }
    # Real Asana omits the next_page key entirely when there is no next page
    return result


def serialize_tag(tag: AsanaTag) -> dict[str, Any]:
    """Serialize a tag to match the TagResponse shape."""
    return {
        "gid": tag.gid,
        "resource_type": tag.resource_type or "tag",
        "name": tag.name,
        "color": tag.color,
        "notes": tag.notes,
        "created_at": tag.created_at,
        "permalink_url": tag.permalink_url,
        # workspace FK relationship serialized as compact object with name
        "workspace": _named_compact(tag.workspace, tag.workspace_gid, "workspace"),
        # followers from M:N relationship
        "followers": [
            {"gid": user.gid, "resource_type": "user", "name": user.name}
            for user in tag.follower_users
        ],
    }


def serialize_tag_list(
    tags: list[AsanaTag],
    next_offset: str | None = None,
    path_prefix: str = "/tags",
) -> dict[str, Any]:
    """Serialize a list of tags with optional pagination info."""
    result: dict[str, Any] = {"data": [serialize_tag(t) for t in tags]}
    if next_offset is not None:
        result["next_page"] = {
            "offset": next_offset,
            "path": f"{path_prefix}?offset={next_offset}",
            "uri": f"{path_prefix}?offset={next_offset}",
        }
    # Real Asana omits the next_page key entirely when there is no next page
    return result
