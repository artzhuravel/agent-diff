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


def serialize_workspace(workspace: AsanaWorkspace) -> dict[str, Any]:
    """Serialize a workspace to match the WorkspaceResponse shape."""
    return {
        "gid": workspace.gid,
        "resource_type": workspace.resource_type or "workspace",
        "name": workspace.name,
        "email_domains": workspace.email_domains or [],
        "is_organization": workspace.is_organization,
    }


def serialize_workspace_list(
    workspaces: list[AsanaWorkspace],
    next_offset: str | None = None,
) -> dict[str, Any]:
    """Serialize a list of workspaces with optional pagination info."""
    result: dict[str, Any] = {"data": [serialize_workspace(w) for w in workspaces]}
    if next_offset is not None:
        result["next_page"] = {
            "offset": next_offset,
            "path": f"/workspaces?offset={next_offset}",
            "uri": f"/workspaces?offset={next_offset}",
        }
    else:
        result["next_page"] = None
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
    else:
        result["next_page"] = None
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
        "html_notes": project.html_notes,
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
        # Scalar FK reference fields serialized as compact objects
        "owner": {"gid": project.owner_gid, "resource_type": "user"} if project.owner_gid else None,
        "team": {"gid": project.team_gid, "resource_type": "team"} if project.team_gid else None,
        "workspace": {"gid": project.workspace_gid, "resource_type": "workspace"} if project.workspace_gid else None,
        "completed_by": {"gid": project.completed_by_gid, "resource_type": "user"} if project.completed_by_gid else None,
        # Self-referential parent
        "parent": {"gid": project.parent_gid, "resource_type": "project"} if project.parent_gid else None,
        # M:N relationships serialized as compact user lists
        "members": [{"gid": u.gid, "resource_type": "user"} for u in project.member_users],
        "followers": [{"gid": u.gid, "resource_type": "user"} for u in project.follower_users],
        # JSONB fields passed through as-is
        "current_status": project.current_status,
        "current_status_update": project.current_status_update,
        "custom_field_settings": project.custom_field_settings or [],
        "custom_fields": project.custom_fields or [],
        "project_brief": project.project_brief,
        "created_from_template": project.created_from_template,
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
    else:
        result["next_page"] = None
    return result


def serialize_section(section: AsanaSection) -> dict[str, Any]:
    """Serialize a section to match the SectionResponse shape."""
    project_compact = (
        {"gid": section.project_gid, "resource_type": "project"}
        if section.project_gid
        else None
    )
    return {
        "gid": section.gid,
        "resource_type": section.resource_type or "section",
        "name": section.name,
        "created_at": section.created_at,
        "project": project_compact,
        # Deprecated plural alias — Asana still returns it for backwards compat
        "projects": [project_compact] if project_compact else [],
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
    else:
        result["next_page"] = None
    return result


def serialize_story(story: AsanaStory) -> dict[str, Any]:
    """Serialize a story to match the StoryResponse shape."""
    return {
        "gid": story.gid,
        "resource_type": story.resource_type or "story",
        "created_at": story.created_at,
        "resource_subtype": story.resource_subtype,
        "text": story.text,
        "html_text": story.html_text,
        "is_pinned": story.is_pinned,
        "sticker_name": story.sticker_name,
        # StoryResponse scalar fields
        "type": story.story_type,
        "is_editable": story.is_editable,
        "is_edited": story.is_edited,
        "hearted": story.hearted,
        "num_hearts": story.num_hearts,
        "liked": story.liked,
        "num_likes": story.num_likes,
        "old_name": story.old_name,
        "new_name": story.new_name,
        "old_resource_subtype": story.old_resource_subtype,
        "new_resource_subtype": story.new_resource_subtype,
        "old_text_value": story.old_text_value,
        "new_text_value": story.new_text_value,
        "old_number_value": story.old_number_value,
        "new_number_value": story.new_number_value,
        "new_approval_status": story.new_approval_status,
        "old_approval_status": story.old_approval_status,
        "source": story.source,
        # JSONB array / object fields passed through as-is
        "hearts": story.hearts or [],
        "likes": story.likes or [],
        "reaction_summary": story.reaction_summary or [],
        "previews": story.previews or [],
        "old_dates": story.old_dates,
        "new_dates": story.new_dates,
        "old_date_value": story.old_date_value,
        "new_date_value": story.new_date_value,
        "old_enum_value": story.old_enum_value,
        "new_enum_value": story.new_enum_value,
        "old_multi_enum_values": story.old_multi_enum_values or [],
        "new_multi_enum_values": story.new_multi_enum_values or [],
        "old_people_value": story.old_people_value or [],
        "new_people_value": story.new_people_value or [],
        # FK reference fields as compact objects; Pass 2 will refine these
        "created_by": {"gid": story.created_by_gid, "resource_type": "user"} if story.created_by_gid else None,
        "task": {"gid": story.task_gid, "resource_type": "task"} if story.task_gid else None,
        "story": {"gid": story.parent_story_gid, "resource_type": "story"} if story.parent_story_gid else None,
        "assignee": {"gid": story.assignee_gid, "resource_type": "user"} if story.assignee_gid else None,
        "follower": {"gid": story.follower_gid, "resource_type": "user"} if story.follower_gid else None,
        "old_section": {"gid": story.old_section_gid, "resource_type": "section"} if story.old_section_gid else None,
        "new_section": {"gid": story.new_section_gid, "resource_type": "section"} if story.new_section_gid else None,
        "project": {"gid": story.project_gid, "resource_type": "project"} if story.project_gid else None,
        "tag": {"gid": story.tag_gid, "resource_type": "tag"} if story.tag_gid else None,
        "custom_field": {"gid": story.custom_field_gid, "resource_type": "custom_field"} if story.custom_field_gid else None,
        "duplicate_of": {"gid": story.duplicate_of_gid, "resource_type": "task"} if story.duplicate_of_gid else None,
        "duplicated_from": {"gid": story.duplicated_from_gid, "resource_type": "task"} if story.duplicated_from_gid else None,
        "dependency": {"gid": story.dependency_gid, "resource_type": "task"} if story.dependency_gid else None,
        "target": {"gid": story.target_gid, "resource_type": "task"} if story.target_gid else None,
    }


def serialize_story_list(
    stories: list[AsanaStory],
    next_offset: str | None = None,
    task_gid: str | None = None,
) -> dict[str, Any]:
    """Serialize a list of stories with optional pagination info."""
    result: dict[str, Any] = {"data": [serialize_story(s) for s in stories]}
    if next_offset is not None:
        path_suffix = f"/tasks/{task_gid}/stories?offset={next_offset}" if task_gid else f"?offset={next_offset}"
        result["next_page"] = {
            "offset": next_offset,
            "path": path_suffix,
            "uri": path_suffix,
        }
    else:
        result["next_page"] = None
    return result


def serialize_task(task: AsanaTask) -> dict[str, Any]:
    """Serialize a task to match the TaskResponse shape."""
    return {
        "gid": task.gid,
        "resource_type": task.resource_type or "task",
        "resource_subtype": task.resource_subtype,
        "name": task.name,
        "notes": task.notes,
        "html_notes": task.html_notes,
        "completed": task.completed,
        "completed_at": task.completed_at,
        "created_at": task.created_at,
        "modified_at": task.modified_at,
        "approval_status": task.approval_status,
        "assignee_status": task.assignee_status,
        "due_at": task.due_at,
        "due_on": task.due_on,
        "start_at": task.start_at,
        "start_on": task.start_on,
        "liked": task.liked,
        "hearted": task.hearted,
        "num_likes": task.num_likes,
        "num_hearts": task.num_hearts,
        "num_subtasks": task.num_subtasks,
        "is_rendered_as_separator": task.is_rendered_as_separator,
        "actual_time_minutes": task.actual_time_minutes,
        "permalink_url": task.permalink_url,
        "external": task.external,
        # FK reference fields as compact objects, populating ``name`` from
        # the eager-loaded relationship when present (matches Asana's
        # UserCompact / SectionCompact / WorkspaceCompact shape).
        "workspace": _named_compact(task.workspace, task.workspace_gid, "workspace"),
        "assignee": _named_compact(task.assignee, task.assignee_gid, "user"),
        "assignee_section": _named_compact(task.assignee_section, task.assignee_section_gid, "section"),
        "assigned_by": _named_compact(task.assigned_by, task.assigned_by_gid, "user"),
        "completed_by": _named_compact(task.completed_by, task.completed_by_gid, "user"),
        "created_by": _named_compact(task.created_by, task.created_by_gid, "user"),
        "parent": _named_compact(task.parent, task.parent_gid, "task"),
        # custom_type / custom_type_status_option aren't modeled resources, so
        # there's no relationship to read a name from.
        "custom_type": {"gid": task.custom_type_gid, "resource_type": "custom_type"} if task.custom_type_gid else None,
        "custom_type_status_option": {"gid": task.custom_type_status_option_gid, "resource_type": "custom_type_status_option"} if task.custom_type_status_option_gid else None,
        # JSONB array fields passed through as-is
        "hearts": task.hearts or [],
        "likes": task.likes or [],
        "memberships": task.memberships or [],
        "dependencies": task.dependencies or [],
        "dependents": task.dependents or [],
        "custom_fields": task.custom_fields or [],
        # projects/followers stored as GID strings or compact objects; upgrade
        "projects": [
            entry if isinstance(entry, dict) else {"gid": entry, "resource_type": "project", "name": None}
            for entry in (task.projects or [])
        ],
        # tags is a proper M:N relationship; serialize each AsanaTag as a
        # TagCompact-shaped dict.
        "tags": [
            {"gid": tag.gid, "resource_type": tag.resource_type or "tag", "name": tag.name}
            for tag in (task.tags or [])
        ],
        "followers": [
            entry if isinstance(entry, dict) else {"gid": entry, "resource_type": "user", "name": None}
            for entry in (task.followers or [])
        ],
    }


def serialize_task_list(
    tasks: list[AsanaTask],
    next_offset: str | None = None,
    path_prefix: str = "/tasks",
) -> dict[str, Any]:
    """Serialize a list of tasks with optional pagination info."""
    result: dict[str, Any] = {"data": [serialize_task(t) for t in tasks]}
    if next_offset is not None:
        result["next_page"] = {
            "offset": next_offset,
            "path": f"{path_prefix}?offset={next_offset}",
            "uri": f"{path_prefix}?offset={next_offset}",
        }
    else:
        result["next_page"] = None
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
        # workspace FK relationship serialized as compact object
        "workspace": {"gid": tag.workspace_gid, "resource_type": "workspace"} if tag.workspace_gid else None,
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
    else:
        result["next_page"] = None
    return result
