"""Asana REST API routes.

Mounted under /api/env/{env_id}/services/__SERVICE_MOUNT_NAME__
DB session comes from request.state.db_session (IsolationMiddleware).
User impersonation comes from request.state.impersonate_user_id.

Route handlers and route entries are added one at a time during the resource
implementation loop. The request helpers below are universal.
"""

from __future__ import annotations

from typing import Any

from starlette import status
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from sqlalchemy.orm import Session

from ..core.errors import (
    AppAPIError,
    handle_exception,
    not_found,
)
from ..core.serializers import (
    serialize_project,
    serialize_project_list,
    serialize_section,
    serialize_section_list,
    serialize_story,
    serialize_story_list,
    serialize_tag,
    serialize_tag_list,
    serialize_task,
    serialize_task_list,
    serialize_user,
    serialize_user_list,
    serialize_workspace,
    serialize_workspace_list,
)
from ..database import operations as ops


# ---------------------------------------------------------------------------
# Request helpers — universal across apps
# ---------------------------------------------------------------------------


def _session(request: Request) -> Session:
    """Get the environment-scoped DB session from request.state."""
    session = getattr(request.state, "db_session", None)
    if session is None:
        raise AppAPIError(
            message="Missing database session",
            http_code=status.HTTP_401_UNAUTHORIZED,
        )
    return session


def _principal_user_id(request: Request) -> str:
    """Resolve the acting principal from request state."""
    principal = getattr(request.state, "impersonate_user_id", None)
    if principal is not None and str(principal).strip() != "":
        return str(principal)
    raise AppAPIError(
        message="Missing user authentication",
        http_code=status.HTTP_401_UNAUTHORIZED,
    )


async def _parse_json_body(request: Request) -> dict[str, Any]:
    """Parse JSON body. Raises an app-shaped 400 on malformed input."""
    try:
        return await request.json()
    except Exception as exc:
        raise AppAPIError(
            message=f"Invalid JSON body: {exc}",
            http_code=status.HTTP_400_BAD_REQUEST,
        ) from exc


def _pagination_params(request: Request) -> tuple[str | None, int]:
    """Extract cursor and limit from query params (cursor-based pagination)."""
    cursor = request.query_params.get("cursor")
    limit_str = request.query_params.get("limit")
    limit = 50
    if limit_str is not None:
        try:
            limit = max(1, min(200, int(limit_str)))
        except ValueError:
            pass
    return cursor, limit


# ---------------------------------------------------------------------------
# Endpoint handlers — added per entity by entity scaffold
# ---------------------------------------------------------------------------

# AGENT INSTRUCTION: Add endpoint handler functions here during entity
# implementation. Each handler follows this pattern:
#
#   async def <operation>_<entity>(request: Request) -> JSONResponse:
#       try:
#           session = _session(request)
#           # ... extract params, call ops, serialize ...
#           return JSONResponse(payload, status_code=status.HTTP_200_OK)
#       except AppAPIError as exc:
#           return exc.to_response()
#       except Exception as exc:
#           return handle_exception(exc)


# ---------------------------------------------------------------------------
# Workspace handlers
# ---------------------------------------------------------------------------


async def list_workspaces(request: Request) -> JSONResponse:
    try:
        session = _session(request)
        _principal_user_id(request)
        offset, limit = _pagination_params(request)
        workspaces, next_offset = ops.list_workspaces(session, offset=offset, limit=limit)
        return JSONResponse(
            serialize_workspace_list(workspaces, next_offset),
            status_code=status.HTTP_200_OK,
        )
    except AppAPIError as exc:
        return exc.to_response()
    except Exception as exc:
        return handle_exception(exc)


async def get_workspace(request: Request) -> JSONResponse:
    try:
        session = _session(request)
        _principal_user_id(request)
        workspace_gid = request.path_params["workspace_gid"]
        workspace = ops.get_workspace(session, workspace_gid)
        if workspace is None:
            raise AppAPIError(f"Workspace {workspace_gid} not found", http_code=status.HTTP_404_NOT_FOUND)
        return JSONResponse(
            {"data": serialize_workspace(workspace)},
            status_code=status.HTTP_200_OK,
        )
    except AppAPIError as exc:
        return exc.to_response()
    except Exception as exc:
        return handle_exception(exc)


# ---------------------------------------------------------------------------
# User handlers
# ---------------------------------------------------------------------------


async def list_users(request: Request) -> JSONResponse:
    try:
        session = _session(request)
        offset, limit = _pagination_params(request)
        users, next_offset = ops.list_users(session, offset=offset, limit=limit)
        return JSONResponse(
            serialize_user_list(users, next_offset),
            status_code=status.HTTP_200_OK,
        )
    except AppAPIError as exc:
        return exc.to_response()
    except Exception as exc:
        return handle_exception(exc)


async def get_user(request: Request) -> JSONResponse:
    try:
        session = _session(request)
        user_gid = request.path_params["user_gid"]
        user = ops.get_user(session, user_gid)
        if user is None:
            raise AppAPIError(f"User {user_gid} not found", http_code=status.HTTP_404_NOT_FOUND)
        return JSONResponse(
            {"data": serialize_user(user)},
            status_code=status.HTTP_200_OK,
        )
    except AppAPIError as exc:
        return exc.to_response()
    except Exception as exc:
        return handle_exception(exc)


async def list_workspace_users(request: Request) -> JSONResponse:
    try:
        session = _session(request)
        workspace_gid = request.path_params["workspace_gid"]
        if ops.get_workspace(session, workspace_gid) is None:
            raise AppAPIError(f"Workspace {workspace_gid} not found", http_code=status.HTTP_404_NOT_FOUND)
        offset, limit = _pagination_params(request)
        users, next_offset = ops.list_users(
            session,
            workspace_gid=workspace_gid,
            offset=offset,
            limit=limit,
        )
        return JSONResponse(
            serialize_user_list(
                users,
                next_offset,
                path_prefix=f"/workspaces/{workspace_gid}/users",
            ),
            status_code=status.HTTP_200_OK,
        )
    except AppAPIError as exc:
        return exc.to_response()
    except Exception as exc:
        return handle_exception(exc)


# ---------------------------------------------------------------------------
# Project handlers
# ---------------------------------------------------------------------------


async def list_projects(request: Request) -> JSONResponse:
    try:
        session = _session(request)
        _principal_user_id(request)
        offset, limit = _pagination_params(request)
        workspace_gid = request.query_params.get("workspace") or None
        team_gid = request.query_params.get("team") or None
        archived_param = request.query_params.get("archived")
        archived = None
        if archived_param is not None:
            archived = archived_param.lower() in ("true", "1", "yes")
        projects, next_offset = ops.list_projects(
            session,
            workspace_gid=workspace_gid,
            team_gid=team_gid,
            archived=archived,
            offset=offset,
            limit=limit,
        )
        return JSONResponse(
            serialize_project_list(projects, next_offset),
            status_code=status.HTTP_200_OK,
        )
    except AppAPIError as exc:
        return exc.to_response()
    except Exception as exc:
        return handle_exception(exc)


async def create_project(request: Request) -> JSONResponse:
    try:
        session = _session(request)
        _principal_user_id(request)
        body = await _parse_json_body(request)
        data = body.get("data", {})
        if not isinstance(data, dict):
            raise AppAPIError("Request body must contain a 'data' object")
        project = ops.create_project(session, data)
        return JSONResponse(
            {"data": serialize_project(project)},
            status_code=status.HTTP_201_CREATED,
        )
    except AppAPIError as exc:
        return exc.to_response()
    except Exception as exc:
        return handle_exception(exc)


async def get_project(request: Request) -> JSONResponse:
    try:
        session = _session(request)
        _principal_user_id(request)
        project_gid = request.path_params["project_gid"]
        project = ops.get_project(session, project_gid)
        if project is None:
            raise AppAPIError(f"Project {project_gid} not found", http_code=status.HTTP_404_NOT_FOUND)
        return JSONResponse(
            {"data": serialize_project(project)},
            status_code=status.HTTP_200_OK,
        )
    except AppAPIError as exc:
        return exc.to_response()
    except Exception as exc:
        return handle_exception(exc)


async def update_project(request: Request) -> JSONResponse:
    try:
        session = _session(request)
        _principal_user_id(request)
        project_gid = request.path_params["project_gid"]
        body = await _parse_json_body(request)
        data = body.get("data", {})
        if not isinstance(data, dict):
            raise AppAPIError("Request body must contain a 'data' object")
        project = ops.update_project(session, project_gid, data)
        if project is None:
            raise AppAPIError(f"Project {project_gid} not found", http_code=status.HTTP_404_NOT_FOUND)
        return JSONResponse(
            {"data": serialize_project(project)},
            status_code=status.HTTP_200_OK,
        )
    except AppAPIError as exc:
        return exc.to_response()
    except Exception as exc:
        return handle_exception(exc)


async def delete_project(request: Request) -> JSONResponse:
    try:
        session = _session(request)
        _principal_user_id(request)
        project_gid = request.path_params["project_gid"]
        deleted = ops.delete_project(session, project_gid)
        if not deleted:
            raise AppAPIError(f"Project {project_gid} not found", http_code=status.HTTP_404_NOT_FOUND)
        return JSONResponse({"data": {}}, status_code=status.HTTP_200_OK)
    except AppAPIError as exc:
        return exc.to_response()
    except Exception as exc:
        return handle_exception(exc)


# ---------------------------------------------------------------------------
# Section handlers
# ---------------------------------------------------------------------------


async def list_sections(request: Request) -> JSONResponse:
    try:
        session = _session(request)
        project_gid = request.path_params["project_gid"]
        offset, limit = _pagination_params(request)
        result = ops.list_sections(
            session,
            project_gid=project_gid,
            offset=offset,
            limit=limit,
        )
        if result is None:
            raise AppAPIError(
                message=f"Project {project_gid} not found",
                http_code=status.HTTP_404_NOT_FOUND,
            )
        sections, next_offset = result
        return JSONResponse(
            serialize_section_list(sections, next_offset),
            status_code=status.HTTP_200_OK,
        )
    except AppAPIError as exc:
        return exc.to_response()
    except Exception as exc:
        return handle_exception(exc)


async def create_section(request: Request) -> JSONResponse:
    try:
        session = _session(request)
        project_gid = request.path_params["project_gid"]
        body = await _parse_json_body(request)
        data = body.get("data", {})
        if not isinstance(data, dict):
            raise AppAPIError("Request body must contain a 'data' object")
        if not data.get("name"):
            raise AppAPIError(
                message="name is required",
                http_code=status.HTTP_400_BAD_REQUEST,
            )
        section = ops.create_section(session, project_gid, data)
        if section is None:
            raise AppAPIError(
                message=f"Project {project_gid} not found",
                http_code=status.HTTP_404_NOT_FOUND,
            )
        return JSONResponse(
            {"data": serialize_section(section)},
            status_code=status.HTTP_201_CREATED,
        )
    except AppAPIError as exc:
        return exc.to_response()
    except Exception as exc:
        return handle_exception(exc)


async def get_section(request: Request) -> JSONResponse:
    try:
        session = _session(request)
        section_gid = request.path_params["section_gid"]
        section = ops.get_section(session, section_gid)
        if section is None:
            raise AppAPIError(f"Section {section_gid} not found", http_code=status.HTTP_404_NOT_FOUND)
        return JSONResponse(
            {"data": serialize_section(section)},
            status_code=status.HTTP_200_OK,
        )
    except AppAPIError as exc:
        return exc.to_response()
    except Exception as exc:
        return handle_exception(exc)


async def update_section(request: Request) -> JSONResponse:
    try:
        session = _session(request)
        section_gid = request.path_params["section_gid"]
        body = await _parse_json_body(request)
        data = body.get("data", {})
        if not isinstance(data, dict):
            raise AppAPIError("Request body must contain a 'data' object")
        section = ops.update_section(session, section_gid, data)
        if section is None:
            raise AppAPIError(f"Section {section_gid} not found", http_code=status.HTTP_404_NOT_FOUND)
        return JSONResponse(
            {"data": serialize_section(section)},
            status_code=status.HTTP_200_OK,
        )
    except AppAPIError as exc:
        return exc.to_response()
    except Exception as exc:
        return handle_exception(exc)


async def delete_section(request: Request) -> JSONResponse:
    try:
        session = _session(request)
        section_gid = request.path_params["section_gid"]
        deleted = ops.delete_section(session, section_gid)
        if not deleted:
            raise AppAPIError(f"Section {section_gid} not found", http_code=status.HTTP_404_NOT_FOUND)
        return JSONResponse({"data": {}}, status_code=status.HTTP_200_OK)
    except AppAPIError as exc:
        return exc.to_response()
    except Exception as exc:
        return handle_exception(exc)


# ---------------------------------------------------------------------------
# Story handlers
# ---------------------------------------------------------------------------


async def list_task_stories(request: Request) -> JSONResponse:
    try:
        session = _session(request)
        _principal_user_id(request)
        task_gid = request.path_params["task_gid"]
        if ops.get_task(session, task_gid) is None:
            raise AppAPIError(f"Task {task_gid} not found", http_code=status.HTTP_404_NOT_FOUND)
        offset, limit = _pagination_params(request)
        stories, next_offset = ops.list_stories(
            session,
            task_gid=task_gid,
            offset=offset,
            limit=limit,
        )
        return JSONResponse(
            serialize_story_list(stories, next_offset, task_gid=task_gid),
            status_code=status.HTTP_200_OK,
        )
    except AppAPIError as exc:
        return exc.to_response()
    except Exception as exc:
        return handle_exception(exc)


async def delete_story(request: Request) -> JSONResponse:
    try:
        session = _session(request)
        _principal_user_id(request)
        story_gid = request.path_params["story_gid"]
        deleted = ops.delete_story(session, story_gid)
        if not deleted:
            raise AppAPIError(f"Story {story_gid} not found", http_code=status.HTTP_404_NOT_FOUND)
        return JSONResponse({"data": {}}, status_code=status.HTTP_200_OK)
    except AppAPIError as exc:
        return exc.to_response()
    except Exception as exc:
        return handle_exception(exc)


async def create_task_story(request: Request) -> JSONResponse:
    try:
        session = _session(request)
        _principal_user_id(request)
        task_gid = request.path_params["task_gid"]
        if ops.get_task(session, task_gid) is None:
            raise AppAPIError(f"Task {task_gid} not found", http_code=status.HTTP_404_NOT_FOUND)
        body = await _parse_json_body(request)
        data = body.get("data", {})
        if not isinstance(data, dict):
            raise AppAPIError("Request body must contain a 'data' object")
        story = ops.create_story(session, task_gid, data)
        return JSONResponse(
            {"data": serialize_story(story)},
            status_code=status.HTTP_201_CREATED,
        )
    except AppAPIError as exc:
        return exc.to_response()
    except Exception as exc:
        return handle_exception(exc)


# ---------------------------------------------------------------------------
# Task handlers
# ---------------------------------------------------------------------------


async def list_tasks(request: Request) -> JSONResponse:
    try:
        session = _session(request)
        _principal_user_id(request)
        offset, limit = _pagination_params(request)
        workspace_gid = request.query_params.get("workspace") or None
        project_gid = request.query_params.get("project") or None
        section_gid = request.query_params.get("section") or None
        assignee_gid = request.query_params.get("assignee") or None
        completed_since = request.query_params.get("completed_since") or None
        modified_since = request.query_params.get("modified_since") or None
        tasks, next_offset = ops.list_tasks(
            session,
            workspace_gid=workspace_gid,
            project_gid=project_gid,
            section_gid=section_gid,
            assignee_gid=assignee_gid,
            completed_since=completed_since,
            modified_since=modified_since,
            offset=offset,
            limit=limit,
        )
        return JSONResponse(
            serialize_task_list(tasks, next_offset),
            status_code=status.HTTP_200_OK,
        )
    except AppAPIError as exc:
        return exc.to_response()
    except Exception as exc:
        return handle_exception(exc)


async def create_task(request: Request) -> JSONResponse:
    try:
        session = _session(request)
        _principal_user_id(request)
        body = await _parse_json_body(request)
        data = body.get("data", {})
        if not isinstance(data, dict):
            raise AppAPIError("Request body must contain a 'data' object")
        task = ops.create_task(session, data)
        return JSONResponse(
            {"data": serialize_task(task)},
            status_code=status.HTTP_201_CREATED,
        )
    except AppAPIError as exc:
        return exc.to_response()
    except Exception as exc:
        return handle_exception(exc)


async def get_task(request: Request) -> JSONResponse:
    try:
        session = _session(request)
        _principal_user_id(request)
        task_gid = request.path_params["task_gid"]
        task = ops.get_task(session, task_gid)
        if task is None:
            raise AppAPIError(f"Task {task_gid} not found", http_code=status.HTTP_404_NOT_FOUND)
        return JSONResponse(
            {"data": serialize_task(task)},
            status_code=status.HTTP_200_OK,
        )
    except AppAPIError as exc:
        return exc.to_response()
    except Exception as exc:
        return handle_exception(exc)


async def update_task(request: Request) -> JSONResponse:
    try:
        session = _session(request)
        _principal_user_id(request)
        task_gid = request.path_params["task_gid"]
        body = await _parse_json_body(request)
        data = body.get("data", {})
        if not isinstance(data, dict):
            raise AppAPIError("Request body must contain a 'data' object")
        task = ops.update_task(session, task_gid, data)
        if task is None:
            raise AppAPIError(f"Task {task_gid} not found", http_code=status.HTTP_404_NOT_FOUND)
        return JSONResponse(
            {"data": serialize_task(task)},
            status_code=status.HTTP_200_OK,
        )
    except AppAPIError as exc:
        return exc.to_response()
    except Exception as exc:
        return handle_exception(exc)


async def delete_task(request: Request) -> JSONResponse:
    try:
        session = _session(request)
        _principal_user_id(request)
        task_gid = request.path_params["task_gid"]
        deleted = ops.delete_task(session, task_gid)
        if not deleted:
            raise AppAPIError(f"Task {task_gid} not found", http_code=status.HTTP_404_NOT_FOUND)
        return JSONResponse({"data": {}}, status_code=status.HTTP_200_OK)
    except AppAPIError as exc:
        return exc.to_response()
    except Exception as exc:
        return handle_exception(exc)


async def list_project_tasks(request: Request) -> JSONResponse:
    try:
        session = _session(request)
        _principal_user_id(request)
        project_gid = request.path_params["project_gid"]
        offset, limit = _pagination_params(request)
        tasks, next_offset = ops.list_tasks_for_project(
            session,
            project_gid=project_gid,
            offset=offset,
            limit=limit,
        )
        return JSONResponse(
            serialize_task_list(
                tasks,
                next_offset,
                path_prefix=f"/projects/{project_gid}/tasks",
            ),
            status_code=status.HTTP_200_OK,
        )
    except AppAPIError as exc:
        return exc.to_response()
    except Exception as exc:
        return handle_exception(exc)


async def list_section_tasks(request: Request) -> JSONResponse:
    try:
        session = _session(request)
        _principal_user_id(request)
        section_gid = request.path_params["section_gid"]
        offset, limit = _pagination_params(request)
        tasks, next_offset = ops.list_tasks_for_section(
            session,
            section_gid=section_gid,
            offset=offset,
            limit=limit,
        )
        return JSONResponse(
            serialize_task_list(
                tasks,
                next_offset,
                path_prefix=f"/sections/{section_gid}/tasks",
            ),
            status_code=status.HTTP_200_OK,
        )
    except AppAPIError as exc:
        return exc.to_response()
    except Exception as exc:
        return handle_exception(exc)


async def list_subtasks(request: Request) -> JSONResponse:
    try:
        session = _session(request)
        _principal_user_id(request)
        task_gid = request.path_params["task_gid"]
        offset, limit = _pagination_params(request)
        result = ops.list_subtasks(
            session,
            parent_task_gid=task_gid,
            offset=offset,
            limit=limit,
        )
        if result is None:
            raise AppAPIError(f"Task {task_gid} not found", http_code=status.HTTP_404_NOT_FOUND)
        tasks, next_offset = result
        return JSONResponse(
            serialize_task_list(
                tasks,
                next_offset,
                path_prefix=f"/tasks/{task_gid}/subtasks",
            ),
            status_code=status.HTTP_200_OK,
        )
    except AppAPIError as exc:
        return exc.to_response()
    except Exception as exc:
        return handle_exception(exc)


# ---------------------------------------------------------------------------
# Tag handlers
# ---------------------------------------------------------------------------


async def list_tags(request: Request) -> JSONResponse:
    try:
        session = _session(request)
        _principal_user_id(request)
        offset, limit = _pagination_params(request)
        workspace_gid = request.query_params.get("workspace") or None
        tags, next_offset = ops.list_tags(
            session,
            workspace_gid=workspace_gid,
            offset=offset,
            limit=limit,
        )
        return JSONResponse(
            serialize_tag_list(tags, next_offset),
            status_code=status.HTTP_200_OK,
        )
    except AppAPIError as exc:
        return exc.to_response()
    except Exception as exc:
        return handle_exception(exc)


async def create_tag(request: Request) -> JSONResponse:
    try:
        session = _session(request)
        _principal_user_id(request)
        body = await _parse_json_body(request)
        data = body.get("data", {})
        if not isinstance(data, dict):
            raise AppAPIError("Request body must contain a 'data' object")
        tag = ops.create_tag(session, data)
        return JSONResponse(
            {"data": serialize_tag(tag)},
            status_code=status.HTTP_201_CREATED,
        )
    except AppAPIError as exc:
        return exc.to_response()
    except Exception as exc:
        return handle_exception(exc)


async def get_tag(request: Request) -> JSONResponse:
    try:
        session = _session(request)
        _principal_user_id(request)
        tag_gid = request.path_params["tag_gid"]
        tag = ops.get_tag(session, tag_gid)
        if tag is None:
            raise AppAPIError(f"Tag {tag_gid} not found", http_code=status.HTTP_404_NOT_FOUND)
        return JSONResponse(
            {"data": serialize_tag(tag)},
            status_code=status.HTTP_200_OK,
        )
    except AppAPIError as exc:
        return exc.to_response()
    except Exception as exc:
        return handle_exception(exc)


async def update_tag(request: Request) -> JSONResponse:
    try:
        session = _session(request)
        _principal_user_id(request)
        tag_gid = request.path_params["tag_gid"]
        body = await _parse_json_body(request)
        data = body.get("data", {})
        if not isinstance(data, dict):
            raise AppAPIError("Request body must contain a 'data' object")
        tag = ops.update_tag(session, tag_gid, data)
        if tag is None:
            raise AppAPIError(f"Tag {tag_gid} not found", http_code=status.HTTP_404_NOT_FOUND)
        return JSONResponse(
            {"data": serialize_tag(tag)},
            status_code=status.HTTP_200_OK,
        )
    except AppAPIError as exc:
        return exc.to_response()
    except Exception as exc:
        return handle_exception(exc)


async def delete_tag(request: Request) -> JSONResponse:
    try:
        session = _session(request)
        _principal_user_id(request)
        tag_gid = request.path_params["tag_gid"]
        deleted = ops.delete_tag(session, tag_gid)
        if not deleted:
            raise AppAPIError(f"Tag {tag_gid} not found", http_code=status.HTTP_404_NOT_FOUND)
        return JSONResponse({"data": {}}, status_code=status.HTTP_200_OK)
    except AppAPIError as exc:
        return exc.to_response()
    except Exception as exc:
        return handle_exception(exc)


async def list_workspace_tags(request: Request) -> JSONResponse:
    try:
        session = _session(request)
        _principal_user_id(request)
        workspace_gid = request.path_params["workspace_gid"]
        if ops.get_workspace(session, workspace_gid) is None:
            raise AppAPIError(f"Workspace {workspace_gid} not found", http_code=status.HTTP_404_NOT_FOUND)
        offset, limit = _pagination_params(request)
        tags, next_offset = ops.list_tags(
            session,
            workspace_gid=workspace_gid,
            offset=offset,
            limit=limit,
        )
        return JSONResponse(
            serialize_tag_list(
                tags,
                next_offset,
                path_prefix=f"/workspaces/{workspace_gid}/tags",
            ),
            status_code=status.HTTP_200_OK,
        )
    except AppAPIError as exc:
        return exc.to_response()
    except Exception as exc:
        return handle_exception(exc)


async def create_subtask(request: Request) -> JSONResponse:
    try:
        session = _session(request)
        _principal_user_id(request)
        task_gid = request.path_params["task_gid"]
        body = await _parse_json_body(request)
        data = body.get("data", {})
        if not isinstance(data, dict):
            raise AppAPIError("Request body must contain a 'data' object")
        task = ops.create_subtask(session, task_gid, data)
        if task is None:
            raise AppAPIError(f"Task {task_gid} not found", http_code=status.HTTP_404_NOT_FOUND)
        return JSONResponse(
            {"data": serialize_task(task)},
            status_code=status.HTTP_201_CREATED,
        )
    except AppAPIError as exc:
        return exc.to_response()
    except Exception as exc:
        return handle_exception(exc)


# ---------------------------------------------------------------------------
# Unknown-endpoint catch-all — universal across apps
# ---------------------------------------------------------------------------
#
# Any request whose path does not match a real route in the table below
# lands here. Returning the replica's native not-found envelope (via
# ``not_found().to_response()``) means agents calling unimplemented
# endpoints during development receive a response that is shape-compatible
# with the target API, instead of Starlette's default plain-text
# ``"Not Found"`` or — worse — an IsolationMiddleware 500.
#
# This makes the replica behave authentically even before every endpoint
# has been implemented: the agent cannot tell from the shape of a 404
# whether the endpoint is unimplemented or genuinely missing upstream.

async def unknown_endpoint(request: Request) -> JSONResponse:
    """Catch-all handler for requests that match no real route."""
    return not_found(
        f"Endpoint not found: {request.method} {request.url.path}"
    ).to_response()


# ---------------------------------------------------------------------------
# Route table — entries added per entity by entity scaffold
# ---------------------------------------------------------------------------

# AGENT INSTRUCTION: Add new Route entries ABOVE the catch-all at the
# bottom of this list. Two hard rules:
#
#   1. Fixed paths (e.g. /projects/archived) must come before parameterized
#      paths (e.g. /projects/{project_id}) so Starlette matches them first.
#   2. The ``/{_unknown_path:path}`` catch-all must always remain the LAST
#      entry in the list. Starlette matches in order, so any route placed
#      after it would be unreachable.

routes: list[Route] = [
    # --- Real endpoints go here (added by the entity implementation loop) ---

    # Workspaces — fixed path before parameterized
    Route("/workspaces", list_workspaces, methods=["GET"]),
    Route("/workspaces/{workspace_gid}", get_workspace, methods=["GET"]),

    # Users — fixed path before parameterized
    Route("/users", list_users, methods=["GET"]),
    Route("/users/{user_gid}", get_user, methods=["GET"]),
    Route("/workspaces/{workspace_gid}/users", list_workspace_users, methods=["GET"]),

    # Projects
    Route("/projects", list_projects, methods=["GET"]),
    Route("/projects", create_project, methods=["POST"]),
    Route("/projects/{project_gid}", get_project, methods=["GET"]),
    Route("/projects/{project_gid}", update_project, methods=["PUT"]),
    Route("/projects/{project_gid}", delete_project, methods=["DELETE"]),

    # Sections
    Route("/projects/{project_gid}/sections", list_sections, methods=["GET"]),
    Route("/projects/{project_gid}/sections", create_section, methods=["POST"]),
    Route("/sections/{section_gid}", get_section, methods=["GET"]),
    Route("/sections/{section_gid}", update_section, methods=["PUT"]),
    Route("/sections/{section_gid}", delete_section, methods=["DELETE"]),

    # Stories
    Route("/tasks/{task_gid}/stories", list_task_stories, methods=["GET"]),
    Route("/tasks/{task_gid}/stories", create_task_story, methods=["POST"]),
    Route("/stories/{story_gid}", delete_story, methods=["DELETE"]),

    # Tasks — fixed paths before parameterized
    Route("/tasks", list_tasks, methods=["GET"]),
    Route("/tasks", create_task, methods=["POST"]),
    Route("/projects/{project_gid}/tasks", list_project_tasks, methods=["GET"]),
    Route("/sections/{section_gid}/tasks", list_section_tasks, methods=["GET"]),
    Route("/tasks/{task_gid}/subtasks", list_subtasks, methods=["GET"]),
    Route("/tasks/{task_gid}/subtasks", create_subtask, methods=["POST"]),
    Route("/tasks/{task_gid}", get_task, methods=["GET"]),
    Route("/tasks/{task_gid}", update_task, methods=["PUT"]),
    Route("/tasks/{task_gid}", delete_task, methods=["DELETE"]),

    # Tags — fixed paths before parameterized
    Route("/tags", list_tags, methods=["GET"]),
    Route("/tags", create_tag, methods=["POST"]),
    Route("/workspaces/{workspace_gid}/tags", list_workspace_tags, methods=["GET"]),
    Route("/tags/{tag_gid}", get_tag, methods=["GET"]),
    Route("/tags/{tag_gid}", update_tag, methods=["PUT"]),
    Route("/tags/{tag_gid}", delete_tag, methods=["DELETE"]),

    # --- Catch-all — MUST be the last entry ---
    Route(
        "/{_unknown_path:path}",
        unknown_endpoint,
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    ),
]
