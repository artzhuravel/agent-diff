# Entity Implementation (Pass 2 — Relationships): projects

You are adding foreign key relationships to the **projects** resource
(`AsanaProject` in `asana_projects`). The base model, operations,
serializers, and routes already exist from Pass 1.

The full OpenAPI spec is available at: `/Users/azh/agent-diff/automatic_schema_generation/apps/asana/inputs/openapi.scoped.json`
If any information in this prompt is unclear or seems incorrect, read the
spec directly to resolve ambiguities.

Read the existing files in the target directory first. You will modify them
to add FK columns, relationship() declarations, indexes, association tables,
and update operations/serializers to handle the new relationships.

Files to edit (all under `/Users/azh/agent-diff/backend/src/services/asana`):
- `database/schema.py`
- `database/operations.py`
- `core/serializers.py`
- `api/routes.py`

---

## Relationship Reference Patterns

The examples below are **fictional mocks** showing how each FK relationship
type maps to SQLAlchemy 2.0 models. Use them as structural guidance — do not
copy the mock names or table names.

### Many To Many
```python
"""Pattern: Many-to-Many (M:N) — REFERENCE MOCK, not real code.

These models are fictional examples showing how to implement an M:N
relationship via an association table. Do not reuse these names —
build your own models based on the actual resource schemas provided
in the prompt.

Use an association Table when both sides carry a list and no extra
metadata is needed on the link itself. If the link needs extra
columns (e.g. joined_at, role), use an explicit mapped class with
a composite primary key instead of a bare Table.
"""

from sqlalchemy import Boolean, Column, ForeignKey, String, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


# Association table — bare Table, not a mapped class.
# Composite primary key prevents duplicate links.
example_item_tag_association = Table(
    "mock_item_tag_association",
    Base.metadata,
    Column("item_id", ForeignKey("mock_items.id"), primary_key=True),
    Column("tag_id", ForeignKey("mock_tags.id"), primary_key=True),
)


class ExampleItem(Base):
    __tablename__ = "mock_items"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)

    # secondary= points at the association table.
    # Both sides use back_populates to keep the ORM in sync.
    tags: Mapped[list["ExampleTag"]] = relationship(
        secondary=example_item_tag_association, back_populates="items"
    )


class ExampleTag(Base):
    __tablename__ = "mock_tags"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)

    items: Mapped[list["ExampleItem"]] = relationship(
        secondary=example_item_tag_association, back_populates="tags"
    )


# --- Operations (key patterns) ---
#
# Adding / removing links operates on the relationship list directly.
# SQLAlchemy handles the association table inserts and deletes.
#
# def add_tag_to_item(session, item_id, tag_id):
#     item = session.get(ExampleItem, item_id)
#     tag = session.get(ExampleTag, tag_id)
#     if tag not in item.tags:
#         item.tags.append(tag)
#     session.flush()
#
# def remove_tag_from_item(session, item_id, tag_id):
#     item = session.get(ExampleItem, item_id)
#     tag = session.get(ExampleTag, tag_id)
#     if tag in item.tags:
#         item.tags.remove(tag)
#     session.flush()
#
# Querying items by tag:
#
# def list_items_by_tag(session, tag_id):
#     return session.execute(
#         select(ExampleItem)
#         .join(ExampleItem.tags)
#         .where(ExampleTag.id == tag_id,
#                ExampleItem.is_deleted.is_(False))
#     ).scalars().all()
```

### Multiple Fks Same Target
```python
"""Pattern: Multiple FKs to the Same Target — REFERENCE MOCK, not real code.

These models are fictional examples showing how to disambiguate
when two or more FK columns reference the same table. Do not reuse
these names — build your own models based on the actual resource
schemas provided in the prompt.

When multiple FK columns point at the same target, SQLAlchemy
cannot infer which relationship uses which column. Disambiguate
with the foreign_keys= argument. Each relationship on the target
side also needs its own back_populates name.
"""

from typing import Optional

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class ExamplePerson(Base):
    __tablename__ = "mock_persons"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # One back_populates list per FK role on the referencing side.
    created_tickets: Mapped[list["ExampleTicket"]] = relationship(
        back_populates="creator", foreign_keys="ExampleTicket.creator_id"
    )
    assigned_tickets: Mapped[list["ExampleTicket"]] = relationship(
        back_populates="assignee", foreign_keys="ExampleTicket.assignee_id"
    )


class ExampleTicket(Base):
    __tablename__ = "mock_tickets"
    __table_args__ = (
        Index("ix_mock_tickets_creator", "creator_id"),
        Index("ix_mock_tickets_assignee", "assignee_id"),
    )

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)

    # Two FK columns to the same table.
    creator_id: Mapped[str] = mapped_column(
        ForeignKey("mock_persons.id"), nullable=False
    )
    assignee_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("mock_persons.id"), nullable=True
    )

    # foreign_keys= resolves the ambiguity. Without it, SQLAlchemy
    # raises AmbiguousForeignKeysError at mapper configuration time.
    creator: Mapped["ExamplePerson"] = relationship(
        back_populates="created_tickets", foreign_keys=[creator_id]
    )
    assignee: Mapped[Optional["ExamplePerson"]] = relationship(
        back_populates="assigned_tickets", foreign_keys=[assignee_id]
    )


# --- Serializer hint ---
#
# def serialize_ticket(ticket: ExampleTicket) -> dict:
#     return {
#         "id": ticket.id,
#         "title": ticket.title,
#         "creator_id": ticket.creator_id,
#         "assignee_id": ticket.assignee_id,
#     }
```

### One To Many
```python
"""Pattern: One-to-Many (1:N) — REFERENCE MOCK, not real code.

These models are fictional examples showing how to implement a 1:N
FK relationship. Do not reuse these names — build your own models
based on the actual resource schemas provided in the prompt.

Use this pattern when one entity "belongs to" another and the child
carries the FK column.
"""

from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class ExampleParent(Base):
    __tablename__ = "mock_parents"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)

    # Parent side: list relationship, no FK column on this table.
    # cascade="all,delete-orphan" ensures children are removed when
    # the parent is deleted.
    children: Mapped[list["ExampleChild"]] = relationship(
        back_populates="parent", cascade="all,delete-orphan"
    )


class ExampleChild(Base):
    __tablename__ = "mock_children"
    __table_args__ = (
        Index("ix_mock_children_parent", "parent_id"),
    )

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)

    # Child side: FK column + scalar relationship.
    # nullable=False means every child must belong to a parent.
    # Use nullable=True when the parent is optional.
    parent_id: Mapped[str] = mapped_column(
        ForeignKey("mock_parents.id"), nullable=False
    )
    parent: Mapped["ExampleParent"] = relationship(back_populates="children")


# --- Operations (key patterns) ---
#
# def create_child(session, *, parent_id, title):
#     child = ExampleChild(
#         id=generate_id("child"),
#         parent_id=parent_id,             # FK set at creation
#         title=title,
#     )
#     session.add(child)
#     session.flush()
#     return child
#
# def list_children_by_parent(session, parent_id):
#     return session.execute(
#         select(ExampleChild)
#         .where(ExampleChild.parent_id == parent_id,
#                ExampleChild.is_deleted.is_(False))
#     ).scalars().all()
```

### Self Referential
```python
"""Pattern: Self-Referential FK — REFERENCE MOCK, not real code.

These models are fictional examples showing how to implement a
self-referential tree hierarchy. Do not reuse these names — build
your own models based on the actual resource schemas provided in
the prompt.

Use this pattern for any entity that nests within itself: folders,
comments, org units, task subtasks, etc. The FK is nullable because
root nodes have parent_id = NULL.
"""

from typing import Optional

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class ExampleNode(Base):
    __tablename__ = "mock_nodes"
    __table_args__ = (
        Index("ix_mock_nodes_parent", "parent_id"),
    )

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)

    # FK to own table. Nullable because root nodes have no parent.
    parent_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("mock_nodes.id"), nullable=True
    )

    # remote_side=[id] tells SQLAlchemy which column is the "one"
    # side. Without it, SQLAlchemy can't distinguish parent from
    # children since both reference the same table.
    parent: Mapped[Optional["ExampleNode"]] = relationship(
        remote_side=[id], back_populates="children"
    )
    children: Mapped[list["ExampleNode"]] = relationship(
        back_populates="parent"
    )


# --- Operations (key patterns) ---
#
# def get_root_nodes(session):
#     return session.execute(
#         select(ExampleNode).where(ExampleNode.parent_id.is_(None))
#     ).scalars().all()
#
# def get_children(session, node_id):
#     return session.execute(
#         select(ExampleNode)
#         .where(ExampleNode.parent_id == node_id)
#     ).scalars().all()
#
# def move_node(session, node_id, new_parent_id):
#     node = session.get(ExampleNode, node_id)
#     node.parent_id = new_parent_id
#     session.flush()
```


---

## Related Resources

These resources have a demonstrated relationship with **projects**
through shared endpoints, FK-shaped property names, or schema cross-references.

Direction key:
- **outgoing** — projects's schemas contain fields that reference
  the related resource (e.g. a `_id` field or nested object pointing there).
  **Action**: add a FK column on `asana_projects` pointing at the related
  resource's table, plus a `relationship()` on both sides.
- **incoming** — the related resource's endpoints reference projects
  (the subject of those endpoints is the other resource, not projects).
  **Action**: do NOT add a FK column on `asana_projects`. The FK lives on the
  other resource's table. Add only a `relationship()` on the projects
  side (the "many" side) if the other resource's model already exists or will
  be created as a stub. If the incoming evidence is only URL segments (no
  property-level field), it may just be endpoint nesting — no FK needed.

For each related resource below, **infer the relationship type** from the
evidence and schema shapes:

- **One-to-Many**: this resource carries a FK column pointing at the related
  resource (e.g. `project_id` on a task), OR the related resource carries a
  FK pointing here. Look for singular ID fields and nested objects.
- **Many-to-Many**: both sides reference each other as arrays, or an endpoint
  returns a list of related entities that can independently belong to multiple
  parents. Build an association table.
- **Self-Referential**: a field like `parent_id` points at the same table.
  Use `remote_side=[id]`.

Then build the appropriate FK columns, indexes, and `relationship()`
declarations using the reference patterns above.

### projects
- **SELF-REFERENTIAL** — this resource references itself
- Use the Self Referential pattern: nullable FK to own table,
  `remote_side=[id]` on the parent relationship
- Table: `asana_projects`
- Primary key: `gid`
- Direction: outgoing
- **Fields referencing projects**: `data`

These fields create a self-referential hierarchy. Add a nullable FK column (e.g. `parent_id`) pointing at `asana_projects.gid` with `remote_side=[gid]`.

Evidence:
  - GET /projects/{project_gid}/custom_field_settings — url_segment: projects
  - GET /projects/{project_gid}/custom_field_settings — url_segment: project_gid
  - GET /projects/{project_gid}/custom_field_settings — property: data.project
  - GET /projects/{project_gid}/custom_field_settings — property: data.parent
  - POST /projects/{project_gid}/project_briefs — url_segment: projects
  - POST /projects/{project_gid}/project_briefs — url_segment: project_gid
  - POST /projects/{project_gid}/project_briefs — property: data.project
  - GET /projects/{project_gid}/project_memberships — url_segment: projects
  - GET /projects/{project_gid}/project_memberships — url_segment: project_gid
  - GET /projects/{project_gid}/project_memberships — property: data.parent
  - GET /projects/{project_gid}/project_portfolio_settings — url_segment: projects
  - GET /projects/{project_gid}/project_portfolio_settings — url_segment: project_gid
  - GET /projects/{project_gid}/project_portfolio_settings — property: data.project
  - POST /projects/{project_gid}/project_statuses — url_segment: projects
  - POST /projects/{project_gid}/project_statuses — url_segment: project_gid
  - GET /projects/{project_gid}/project_statuses — url_segment: projects
  - GET /projects/{project_gid}/project_statuses — url_segment: project_gid
  - POST /projects — url_segment: projects
  - POST /projects — property: data
  - POST /projects — property: data.custom_field_settings.project
  - POST /projects — property: data.custom_field_settings.parent
  - POST /projects — property: data
  - POST /projects — property: data.custom_field_settings.project
  - POST /projects — property: data.custom_field_settings.parent
  - GET /projects — url_segment: projects
  - GET /projects — property: data
  - PUT /projects/{project_gid} — url_segment: projects
  - PUT /projects/{project_gid} — url_segment: project_gid
  - PUT /projects/{project_gid} — property: data
  - PUT /projects/{project_gid} — property: data.custom_field_settings.project
  - PUT /projects/{project_gid} — property: data.custom_field_settings.parent
  - PUT /projects/{project_gid} — property: data
  - PUT /projects/{project_gid} — property: data.custom_field_settings.project
  - PUT /projects/{project_gid} — property: data.custom_field_settings.parent
  - GET /projects/{project_gid} — url_segment: projects
  - GET /projects/{project_gid} — url_segment: project_gid
  - GET /projects/{project_gid} — property: data
  - GET /projects/{project_gid} — property: data.custom_field_settings.project
  - GET /projects/{project_gid} — property: data.custom_field_settings.parent
  - DELETE /projects/{project_gid} — url_segment: projects
  - DELETE /projects/{project_gid} — url_segment: project_gid
  - POST /projects/{project_gid}/duplicate — url_segment: projects
  - POST /projects/{project_gid}/duplicate — url_segment: project_gid
  - POST /projects/{project_gid}/duplicate — property: data.new_project
  - GET /tasks/{task_gid}/projects — url_segment: projects
  - GET /tasks/{task_gid}/projects — property: data
  - POST /teams/{team_gid}/projects — url_segment: projects
  - POST /teams/{team_gid}/projects — property: data
  - POST /teams/{team_gid}/projects — property: data.custom_field_settings.project
  - POST /teams/{team_gid}/projects — property: data.custom_field_settings.parent
  - POST /teams/{team_gid}/projects — property: data
  - POST /teams/{team_gid}/projects — property: data.custom_field_settings.project
  - POST /teams/{team_gid}/projects — property: data.custom_field_settings.parent
  - GET /teams/{team_gid}/projects — url_segment: projects
  - GET /teams/{team_gid}/projects — property: data
  - POST /workspaces/{workspace_gid}/projects — url_segment: projects
  - POST /workspaces/{workspace_gid}/projects — property: data
  - POST /workspaces/{workspace_gid}/projects — property: data.custom_field_settings.project
  - POST /workspaces/{workspace_gid}/projects — property: data.custom_field_settings.parent
  - POST /workspaces/{workspace_gid}/projects — property: data
  - POST /workspaces/{workspace_gid}/projects — property: data.custom_field_settings.project
  - POST /workspaces/{workspace_gid}/projects — property: data.custom_field_settings.parent
  - GET /workspaces/{workspace_gid}/projects — url_segment: projects
  - GET /workspaces/{workspace_gid}/projects — property: data
  - GET /workspaces/{workspace_gid}/projects/search — url_segment: projects
  - GET /workspaces/{workspace_gid}/projects/search — property: data
  - POST /projects/{project_gid}/addCustomFieldSetting — url_segment: projects
  - POST /projects/{project_gid}/addCustomFieldSetting — url_segment: project_gid
  - POST /projects/{project_gid}/addCustomFieldSetting — property: data.project
  - POST /projects/{project_gid}/addCustomFieldSetting — property: data.parent
  - POST /projects/{project_gid}/removeCustomFieldSetting — url_segment: projects
  - POST /projects/{project_gid}/removeCustomFieldSetting — url_segment: project_gid
  - GET /projects/{project_gid}/task_counts — url_segment: projects
  - GET /projects/{project_gid}/task_counts — url_segment: project_gid
  - POST /projects/{project_gid}/addMembers — url_segment: projects
  - POST /projects/{project_gid}/addMembers — url_segment: project_gid
  - POST /projects/{project_gid}/addMembers — property: data
  - POST /projects/{project_gid}/addMembers — property: data.custom_field_settings.project
  - POST /projects/{project_gid}/addMembers — property: data.custom_field_settings.parent
  - POST /projects/{project_gid}/removeMembers — url_segment: projects
  - POST /projects/{project_gid}/removeMembers — url_segment: project_gid
  - POST /projects/{project_gid}/removeMembers — property: data
  - POST /projects/{project_gid}/removeMembers — property: data.custom_field_settings.project
  - POST /projects/{project_gid}/removeMembers — property: data.custom_field_settings.parent
  - POST /projects/{project_gid}/addFollowers — url_segment: projects
  - POST /projects/{project_gid}/addFollowers — url_segment: project_gid
  - POST /projects/{project_gid}/addFollowers — property: data
  - POST /projects/{project_gid}/addFollowers — property: data.custom_field_settings.project
  - POST /projects/{project_gid}/addFollowers — property: data.custom_field_settings.parent
  - POST /projects/{project_gid}/removeFollowers — url_segment: projects
  - POST /projects/{project_gid}/removeFollowers — url_segment: project_gid
  - POST /projects/{project_gid}/removeFollowers — property: data
  - POST /projects/{project_gid}/removeFollowers — property: data.custom_field_settings.project
  - POST /projects/{project_gid}/removeFollowers — property: data.custom_field_settings.parent
  - POST /projects/{project_gid}/saveAsTemplate — url_segment: projects
  - POST /projects/{project_gid}/saveAsTemplate — url_segment: project_gid
  - POST /projects/{project_gid}/saveAsTemplate — property: data.new_project

Key fields (PK + fields referencing projects):
```json
{
  "ProjectCompact": {
    "properties": {
      "gid": {
        "description": "Globally unique identifier of the resource, as a string.",
        "type": "string",
        "readOnly": true,
        "example": "12345",
        "x-insert-after": false
      }
    }
  }
}
```

### sections
- Table: `asana_sections`
- Primary key: `gid`
- Direction: incoming
- **Fields referencing sections**: `data.project`, `data.projects`

These fields all point at the `asana_sections` table. Infer the correct FK relationship type and apply using the reference patterns above.

Evidence:
  - PUT /sections/{section_gid} — property: data.project (incoming)
  - PUT /sections/{section_gid} — property: data.projects (incoming)
  - GET /sections/{section_gid} — property: data.project (incoming)
  - GET /sections/{section_gid} — property: data.projects (incoming)
  - POST /projects/{project_gid}/sections — url_segment: projects (incoming)
  - POST /projects/{project_gid}/sections — url_segment: project_gid (incoming)
  - POST /projects/{project_gid}/sections — property: data.project (incoming)
  - POST /projects/{project_gid}/sections — property: data.projects (incoming)
  - GET /projects/{project_gid}/sections — url_segment: projects (incoming)
  - GET /projects/{project_gid}/sections — url_segment: project_gid (incoming)
  - POST /projects/{project_gid}/sections/insert — url_segment: projects (incoming)
  - POST /projects/{project_gid}/sections/insert — url_segment: project_gid (incoming)

Key fields (PK + fields referencing projects):
```json
{
  "SectionCompact": {
    "properties": {
      "gid": {
        "description": "Globally unique identifier of the resource, as a string.",
        "type": "string",
        "readOnly": true,
        "example": "12345",
        "x-insert-after": false
      }
    }
  }
}
```

### stories
- Table: `asana_stories`
- Primary key: `gid`
- Direction: incoming
- **Fields referencing stories**: `data.project`

These fields all point at the `asana_stories` table. Infer the correct FK relationship type and apply using the reference patterns above.

Evidence:
  - PUT /stories/{story_gid} — property: data.project (incoming)
  - GET /stories/{story_gid} — property: data.project (incoming)
  - POST /tasks/{task_gid}/stories — property: data.project (incoming)
  - POST /goals/{goal_gid}/stories — property: data.project (incoming)

Key fields (PK + fields referencing projects):
```json
{
  "StoryBase": {
    "properties": {
      "gid": {
        "description": "Globally unique identifier of the resource, as a string.",
        "type": "string",
        "readOnly": true,
        "example": "12345",
        "x-insert-after": false
      }
    }
  },
  "StoryCompact": {
    "properties": {
      "gid": {
        "description": "Globally unique identifier of the resource, as a string.",
        "type": "string",
        "readOnly": true,
        "example": "12345",
        "x-insert-after": false
      }
    }
  }
}
```

### tasks
- Table: `asana_tasks`
- Primary key: `gid`
- Direction: outgoing, incoming
- **Fields referencing tasks**: `data.attributable_to`, `data.custom_field_settings.parent`, `data.memberships.project`, `data.new_project`, `data.new_task`, `data.parent`, `data.project`, `data.projects`

These fields all point at the `asana_tasks` table. Infer the correct FK relationship type and apply using the reference patterns above.

Evidence:
  - GET /projects/{project_gid}/custom_field_settings — property: data.parent
  - GET /projects/{project_gid}/project_memberships — property: data.parent
  - POST /projects — property: data.custom_field_settings.parent
  - POST /projects — property: data.custom_field_settings.parent
  - PUT /projects/{project_gid} — property: data.custom_field_settings.parent
  - PUT /projects/{project_gid} — property: data.custom_field_settings.parent
  - GET /projects/{project_gid} — property: data.custom_field_settings.parent
  - POST /projects/{project_gid}/duplicate — property: data.new_task
  - GET /tasks/{task_gid}/projects — url_segment: tasks
  - GET /tasks/{task_gid}/projects — url_segment: task_gid
  - POST /teams/{team_gid}/projects — property: data.custom_field_settings.parent
  - POST /teams/{team_gid}/projects — property: data.custom_field_settings.parent
  - POST /workspaces/{workspace_gid}/projects — property: data.custom_field_settings.parent
  - POST /workspaces/{workspace_gid}/projects — property: data.custom_field_settings.parent
  - POST /projects/{project_gid}/addCustomFieldSetting — property: data.parent
  - POST /projects/{project_gid}/addMembers — property: data.custom_field_settings.parent
  - POST /projects/{project_gid}/removeMembers — property: data.custom_field_settings.parent
  - POST /projects/{project_gid}/addFollowers — property: data.custom_field_settings.parent
  - POST /projects/{project_gid}/removeFollowers — property: data.custom_field_settings.parent
  - POST /projects/{project_gid}/saveAsTemplate — property: data.new_task
  - POST /tasks — query: project (incoming)
  - POST /tasks — property: data.memberships.project (incoming)
  - POST /tasks — property: data.projects (incoming)
  - POST /tasks — property: data.memberships.project (incoming)
  - POST /tasks — property: data.projects (incoming)
  - GET /tasks — query: project (incoming)
  - PUT /tasks/{task_gid} — property: data.memberships.project (incoming)
  - PUT /tasks/{task_gid} — property: data.projects (incoming)
  - PUT /tasks/{task_gid} — property: data.memberships.project (incoming)
  - PUT /tasks/{task_gid} — property: data.projects (incoming)
  - GET /tasks/{task_gid} — property: data.memberships.project (incoming)
  - GET /tasks/{task_gid} — property: data.projects (incoming)
  - POST /tasks/{task_gid}/duplicate — property: data.new_project (incoming)
  - GET /projects/{project_gid}/tasks — url_segment: projects (incoming)
  - GET /projects/{project_gid}/tasks — url_segment: project_gid (incoming)
  - POST /tasks/{task_gid}/subtasks — property: data.memberships.project (incoming)
  - POST /tasks/{task_gid}/subtasks — property: data.projects (incoming)
  - POST /tasks/{task_gid}/subtasks — property: data.memberships.project (incoming)
  - POST /tasks/{task_gid}/subtasks — property: data.projects (incoming)
  - POST /tasks/{task_gid}/setParent — property: data.memberships.project (incoming)
  - POST /tasks/{task_gid}/setParent — property: data.projects (incoming)
  - POST /tasks/{task_gid}/addProject — property: data.project (incoming)
  - POST /tasks/{task_gid}/removeProject — property: data.project (incoming)
  - POST /tasks/{task_gid}/addFollowers — property: data.memberships.project (incoming)
  - POST /tasks/{task_gid}/addFollowers — property: data.projects (incoming)
  - POST /tasks/{task_gid}/removeFollowers — property: data.memberships.project (incoming)
  - POST /tasks/{task_gid}/removeFollowers — property: data.projects (incoming)
  - GET /workspaces/{workspace_gid}/tasks/custom_id/{custom_id} — property: data.memberships.project (incoming)
  - GET /workspaces/{workspace_gid}/tasks/custom_id/{custom_id} — property: data.projects (incoming)
  - POST /tasks/{task_gid}/time_tracking_entries — property: data.attributable_to (incoming)
  - GET /tasks/{task_gid}/time_tracking_entries — property: data.attributable_to (incoming)

Key fields (PK + fields referencing projects):
```json
{
  "TaskCompact": {
    "properties": {
      "gid": {
        "description": "Globally unique identifier of the resource, as a string.",
        "type": "string",
        "readOnly": true,
        "example": "12345",
        "x-insert-after": false
      }
    }
  }
}
```

### teams
- Table: `asana_teams`
- Primary key: `gid`
- Direction: outgoing, incoming
- **Fields referencing teams**: `data.custom_field_settings.parent`, `data.custom_field_settings.project`, `data.parent`, `data.project`, `data.team`

These fields all point at the `asana_teams` table. Infer the correct FK relationship type and apply using the reference patterns above.

Evidence:
  - POST /projects — query: team
  - POST /projects — property: data.team
  - POST /projects — property: data.team
  - GET /projects — query: team
  - PUT /projects/{project_gid} — property: data.team
  - PUT /projects/{project_gid} — property: data.team
  - GET /projects/{project_gid} — property: data.team
  - POST /projects/{project_gid}/duplicate — property: data.team
  - POST /teams/{team_gid}/projects — url_segment: teams
  - POST /teams/{team_gid}/projects — url_segment: team_gid
  - POST /teams/{team_gid}/projects — property: data.team
  - POST /teams/{team_gid}/projects — property: data.team
  - GET /teams/{team_gid}/projects — url_segment: teams
  - GET /teams/{team_gid}/projects — url_segment: team_gid
  - POST /workspaces/{workspace_gid}/projects — property: data.team
  - POST /workspaces/{workspace_gid}/projects — property: data.team
  - POST /projects/{project_gid}/addMembers — property: data.team
  - POST /projects/{project_gid}/removeMembers — property: data.team
  - POST /projects/{project_gid}/addFollowers — property: data.team
  - POST /projects/{project_gid}/removeFollowers — property: data.team
  - POST /projects/{project_gid}/saveAsTemplate — property: data.team
  - GET /teams/{team_gid}/custom_field_settings — property: data.project (incoming)
  - GET /teams/{team_gid}/custom_field_settings — property: data.parent (incoming)
  - POST /teams — property: data.custom_field_settings.project (incoming)
  - POST /teams — property: data.custom_field_settings.parent (incoming)
  - PUT /teams/{team_gid} — property: data.custom_field_settings.project (incoming)
  - PUT /teams/{team_gid} — property: data.custom_field_settings.parent (incoming)
  - GET /teams/{team_gid} — property: data.custom_field_settings.project (incoming)
  - GET /teams/{team_gid} — property: data.custom_field_settings.parent (incoming)

Key fields (PK + fields referencing projects):
```json
{
  "TeamCompact": {
    "properties": {
      "gid": {
        "description": "Globally unique identifier of the resource, as a string.",
        "type": "string",
        "readOnly": true,
        "example": "12345",
        "x-insert-after": false
      }
    }
  }
}
```

### users
- Table: `asana_users`
- Primary key: `gid`
- Direction: outgoing
- **Fields referencing users**: `data.author`, `data.completed_by`, `data.created_by`, `data.current_status.author`, `data.current_status.created_by`, `data.custom_field.created_by`, `data.custom_field.people_value`, `data.custom_field_settings.custom_field.created_by`, `data.custom_field_settings.custom_field.people_value`, `data.followers`, `data.members`, `data.new_task.created_by`, `data.owner`

These fields all point at the `asana_users` table. Infer the correct FK relationship type and apply using the reference patterns above.

Evidence:
  - GET /projects/{project_gid}/custom_field_settings — property: data.custom_field.created_by
  - GET /projects/{project_gid}/custom_field_settings — property: data.custom_field.people_value
  - POST /projects/{project_gid}/project_statuses — property: data.author
  - POST /projects/{project_gid}/project_statuses — property: data.created_by
  - POST /projects — property: data.current_status.author
  - POST /projects — property: data.current_status.created_by
  - POST /projects — property: data.custom_field_settings.custom_field.created_by
  - POST /projects — property: data.custom_field_settings.custom_field.people_value
  - POST /projects — property: data.members
  - POST /projects — property: data.followers
  - POST /projects — property: data.owner
  - POST /projects — property: data.current_status.author
  - POST /projects — property: data.current_status.created_by
  - POST /projects — property: data.custom_field_settings.custom_field.created_by
  - POST /projects — property: data.custom_field_settings.custom_field.people_value
  - POST /projects — property: data.members
  - POST /projects — property: data.completed_by
  - POST /projects — property: data.followers
  - POST /projects — property: data.owner
  - PUT /projects/{project_gid} — property: data.current_status.author
  - PUT /projects/{project_gid} — property: data.current_status.created_by
  - PUT /projects/{project_gid} — property: data.custom_field_settings.custom_field.created_by
  - PUT /projects/{project_gid} — property: data.custom_field_settings.custom_field.people_value
  - PUT /projects/{project_gid} — property: data.members
  - PUT /projects/{project_gid} — property: data.followers
  - PUT /projects/{project_gid} — property: data.owner
  - PUT /projects/{project_gid} — property: data.current_status.author
  - PUT /projects/{project_gid} — property: data.current_status.created_by
  - PUT /projects/{project_gid} — property: data.custom_field_settings.custom_field.created_by
  - PUT /projects/{project_gid} — property: data.custom_field_settings.custom_field.people_value
  - PUT /projects/{project_gid} — property: data.members
  - PUT /projects/{project_gid} — property: data.completed_by
  - PUT /projects/{project_gid} — property: data.followers
  - PUT /projects/{project_gid} — property: data.owner
  - GET /projects/{project_gid} — property: data.current_status.author
  - GET /projects/{project_gid} — property: data.current_status.created_by
  - GET /projects/{project_gid} — property: data.custom_field_settings.custom_field.created_by
  - GET /projects/{project_gid} — property: data.custom_field_settings.custom_field.people_value
  - GET /projects/{project_gid} — property: data.members
  - GET /projects/{project_gid} — property: data.completed_by
  - GET /projects/{project_gid} — property: data.followers
  - GET /projects/{project_gid} — property: data.owner
  - POST /projects/{project_gid}/duplicate — property: data.new_task.created_by
  - POST /teams/{team_gid}/projects — property: data.current_status.author
  - POST /teams/{team_gid}/projects — property: data.current_status.created_by
  - POST /teams/{team_gid}/projects — property: data.custom_field_settings.custom_field.created_by
  - POST /teams/{team_gid}/projects — property: data.custom_field_settings.custom_field.people_value
  - POST /teams/{team_gid}/projects — property: data.members
  - POST /teams/{team_gid}/projects — property: data.followers
  - POST /teams/{team_gid}/projects — property: data.owner
  - POST /teams/{team_gid}/projects — property: data.current_status.author
  - POST /teams/{team_gid}/projects — property: data.current_status.created_by
  - POST /teams/{team_gid}/projects — property: data.custom_field_settings.custom_field.created_by
  - POST /teams/{team_gid}/projects — property: data.custom_field_settings.custom_field.people_value
  - POST /teams/{team_gid}/projects — property: data.members
  - POST /teams/{team_gid}/projects — property: data.completed_by
  - POST /teams/{team_gid}/projects — property: data.followers
  - POST /teams/{team_gid}/projects — property: data.owner
  - POST /workspaces/{workspace_gid}/projects — property: data.current_status.author
  - POST /workspaces/{workspace_gid}/projects — property: data.current_status.created_by
  - POST /workspaces/{workspace_gid}/projects — property: data.custom_field_settings.custom_field.created_by
  - POST /workspaces/{workspace_gid}/projects — property: data.custom_field_settings.custom_field.people_value
  - POST /workspaces/{workspace_gid}/projects — property: data.members
  - POST /workspaces/{workspace_gid}/projects — property: data.followers
  - POST /workspaces/{workspace_gid}/projects — property: data.owner
  - POST /workspaces/{workspace_gid}/projects — property: data.current_status.author
  - POST /workspaces/{workspace_gid}/projects — property: data.current_status.created_by
  - POST /workspaces/{workspace_gid}/projects — property: data.custom_field_settings.custom_field.created_by
  - POST /workspaces/{workspace_gid}/projects — property: data.custom_field_settings.custom_field.people_value
  - POST /workspaces/{workspace_gid}/projects — property: data.members
  - POST /workspaces/{workspace_gid}/projects — property: data.completed_by
  - POST /workspaces/{workspace_gid}/projects — property: data.followers
  - POST /workspaces/{workspace_gid}/projects — property: data.owner
  - POST /projects/{project_gid}/addCustomFieldSetting — property: data.custom_field.created_by
  - POST /projects/{project_gid}/addCustomFieldSetting — property: data.custom_field.people_value
  - POST /projects/{project_gid}/addMembers — property: data.current_status.author
  - POST /projects/{project_gid}/addMembers — property: data.current_status.created_by
  - POST /projects/{project_gid}/addMembers — property: data.custom_field_settings.custom_field.created_by
  - POST /projects/{project_gid}/addMembers — property: data.custom_field_settings.custom_field.people_value
  - POST /projects/{project_gid}/addMembers — property: data.members
  - POST /projects/{project_gid}/addMembers — property: data.completed_by
  - POST /projects/{project_gid}/addMembers — property: data.followers
  - POST /projects/{project_gid}/addMembers — property: data.owner
  - POST /projects/{project_gid}/removeMembers — property: data.current_status.author
  - POST /projects/{project_gid}/removeMembers — property: data.current_status.created_by
  - POST /projects/{project_gid}/removeMembers — property: data.custom_field_settings.custom_field.created_by
  - POST /projects/{project_gid}/removeMembers — property: data.custom_field_settings.custom_field.people_value
  - POST /projects/{project_gid}/removeMembers — property: data.members
  - POST /projects/{project_gid}/removeMembers — property: data.completed_by
  - POST /projects/{project_gid}/removeMembers — property: data.followers
  - POST /projects/{project_gid}/removeMembers — property: data.owner
  - POST /projects/{project_gid}/addFollowers — property: data.followers
  - POST /projects/{project_gid}/addFollowers — property: data.current_status.author
  - POST /projects/{project_gid}/addFollowers — property: data.current_status.created_by
  - POST /projects/{project_gid}/addFollowers — property: data.custom_field_settings.custom_field.created_by
  - POST /projects/{project_gid}/addFollowers — property: data.custom_field_settings.custom_field.people_value
  - POST /projects/{project_gid}/addFollowers — property: data.members
  - POST /projects/{project_gid}/addFollowers — property: data.completed_by
  - POST /projects/{project_gid}/addFollowers — property: data.followers
  - POST /projects/{project_gid}/addFollowers — property: data.owner
  - POST /projects/{project_gid}/removeFollowers — property: data.followers
  - POST /projects/{project_gid}/removeFollowers — property: data.current_status.author
  - POST /projects/{project_gid}/removeFollowers — property: data.current_status.created_by
  - POST /projects/{project_gid}/removeFollowers — property: data.custom_field_settings.custom_field.created_by
  - POST /projects/{project_gid}/removeFollowers — property: data.custom_field_settings.custom_field.people_value
  - POST /projects/{project_gid}/removeFollowers — property: data.members
  - POST /projects/{project_gid}/removeFollowers — property: data.completed_by
  - POST /projects/{project_gid}/removeFollowers — property: data.followers
  - POST /projects/{project_gid}/removeFollowers — property: data.owner
  - POST /projects/{project_gid}/saveAsTemplate — property: data.new_task.created_by

Key fields (PK + fields referencing projects):
```json
{
  "UserCompact": {
    "properties": {
      "gid": {
        "description": "Globally unique identifier of the resource, as a string.",
        "type": "string",
        "readOnly": true,
        "example": "12345",
        "x-insert-after": false
      }
    }
  }
}
```

### workspaces
- Table: `asana_workspaces`
- Primary key: `gid`
- Direction: outgoing
- **Fields referencing workspaces**: `data.custom_field.workspace`, `data.workspace`

These fields all point at the `asana_workspaces` table. Infer the correct FK relationship type and apply using the reference patterns above.

Evidence:
  - POST /projects — query: workspace
  - POST /projects — property: data.workspace
  - POST /projects — property: data.workspace
  - GET /projects — query: workspace
  - PUT /projects/{project_gid} — property: data.workspace
  - GET /projects/{project_gid} — property: data.workspace
  - POST /teams/{team_gid}/projects — property: data.workspace
  - POST /teams/{team_gid}/projects — property: data.workspace
  - POST /workspaces/{workspace_gid}/projects — url_segment: workspaces
  - POST /workspaces/{workspace_gid}/projects — url_segment: workspace_gid
  - POST /workspaces/{workspace_gid}/projects — property: data.workspace
  - POST /workspaces/{workspace_gid}/projects — property: data.workspace
  - GET /workspaces/{workspace_gid}/projects — url_segment: workspaces
  - GET /workspaces/{workspace_gid}/projects — url_segment: workspace_gid
  - GET /workspaces/{workspace_gid}/projects/search — url_segment: workspaces
  - GET /workspaces/{workspace_gid}/projects/search — url_segment: workspace_gid
  - POST /projects/{project_gid}/addCustomFieldSetting — property: data.custom_field.workspace
  - POST /projects/{project_gid}/addMembers — property: data.workspace
  - POST /projects/{project_gid}/removeMembers — property: data.workspace
  - POST /projects/{project_gid}/addFollowers — property: data.workspace
  - POST /projects/{project_gid}/removeFollowers — property: data.workspace
  - POST /projects/{project_gid}/saveAsTemplate — property: data.workspace

Key fields (PK + fields referencing projects):
```json
{
  "WorkspaceCompact": {
    "properties": {
      "gid": {
        "description": "Globally unique identifier of the resource, as a string.",
        "type": "string",
        "readOnly": true,
        "example": "12345",
        "x-insert-after": false
      }
    }
  }
}
```


---

## External Schemas

These schemas reference **projects** but belong to entities that are
**not part of this implementation**. Do NOT create FK columns, relationship
declarations, or stub models for them. They are shown only so you understand
how projects appears in the broader API.

### ProjectBriefBase
```json
{
  "allOf": [
    {
      "$ref": "#/components/schemas/ProjectBriefCompact"
    },
    {
      "type": "object",
      "properties": {
        "title": {
          "description": "The title of the project brief.",
          "type": "string",
          "example": "Stuff to buy \u2014 Project Brief"
        },
        "html_text": {
          "description": "HTML formatted text for the project brief.",
          "type": "string",
          "example": "<body>This is a <strong>project brief</strong>.</body>"
        }
      }
    }
  ]
}
```

### ProjectBriefCompact
```json
{
  "description": "A *Project Brief* allows you to explain the what and why of the project to your team.",
  "type": "object",
  "properties": {
    "gid": {
      "description": "Globally unique identifier of the resource, as a string.",
      "type": "string",
      "readOnly": true,
      "example": "12345",
      "x-insert-after": false
    },
    "resource_type": {
      "description": "The base type of this resource.",
      "type": "string",
      "readOnly": true,
      "example": "project_brief",
      "x-insert-after": "gid"
    }
  }
}
```

### ProjectBriefRequest
```json
{
  "allOf": [
    {
      "$ref": "#/components/schemas/ProjectBriefBase"
    },
    {
      "type": "object",
      "properties": {
        "text": {
          "description": "The plain text of the project brief. When writing to a project brief, you can specify either `html_text` (preferred) or `text`, but not both.",
          "type": "string",
          "example": "This is a project brief."
        }
      }
    }
  ]
}
```

### ProjectDuplicateRequest
```json
{
  "type": "object",
  "required": [
    "name"
  ],
  "properties": {
    "name": {
      "description": "The name of the new project.",
      "type": "string",
      "example": "New Project Name"
    },
    "team": {
      "description": "Sets the team of the new project. If team is not defined, the new project will be in the same team as the the original project.",
      "type": "string",
      "example": "12345"
    },
    "include": {
      "description": "A comma-separated list of elements to include when duplicating a project.\nSome elements are automatically included and cannot be excluded,\nwhile others are **optional** and must be explicitly specified in this field.\n\n**Auto-included fields (non-configurable)**\n- Tasks\n- [Project Views](https://asana.com/features/project-management/project-views)\n(i.e., tabs in a project such as List, Board, Dashboard, etc.)\n- [Rules](https://help.asana.com/s/article/rules)\n\n*Note: The Owner of the Rules copied to the new project is the user who performs the API call.\nIf the duplication is performed using a [Service Account](/docs/authentication#/service-account),\nnote that Service Accounts cannot access the UI to modify or pause Rules.\nTo prevent unwanted automation behavior, consider pausing Rules in the source project before duplication \u2014\ntheir active/paused state is preserved in the new project.*\n\n**Optional fields (configurable)**\n- allocations\n- forms\n- members\n- notes\n- permissions\n- task_assignee\n- task_attachments\n- task_dates\n- task_dependencies\n- task_followers\n- task_notes\n- task_projects\n- task_subtasks\n- task_tags\n- task_templates\n- task_type_default",
      "type": "string",
      "pattern": "([allocations|forms|members|notes|permissions|task_assignee|task_attachments|task_dates|task_dependencies|task_followers|task_notes|task_projects|task_subtasks|task_tags|task_templates|task_type_default])(,\\1)*",
      "example": [
        "allocations,forms,members,notes,permissions,task_assignee,task_attachments,task_dates,task_dependencies,task_followers,task_notes,task_projects,task_subtasks,task_tags,task_templates,task_type_default"
      ]
    },
    "schedule_dates": {
      "description": "A dictionary of options to auto-shift dates. `task_dates` must be included to use this option. Requires `should_skip_weekends` and either `start_on` or `due_on`, but not both.",
      "type": "object",
      "properties": {
        "should_skip_weekends": {
          "description": "**Required**: Determines if the auto-shifted dates should skip weekends.",
          "type": "boolean",
          "example": true
        },
        "due_on": {
          "description": "Sets the last due date in the duplicated project to the given date. The rest of the due dates will be offset by the same amount as the due dates in the original project.",
          "type": "string",
          "example": "2019-05-21"
        },
        "start_on": {
          "description": "Sets the first start date in the duplicated project to the given date. The rest of the start dates will be offset by the same amount as the start dates in the original project.",
          "type": "string",
          "example": "2019-05-21"
        }
      }
    }
  }
}
```

### ProjectMembershipBase
```json
{
  "$ref": "#/components/schemas/ProjectMembershipCompact"
}
```

### ProjectMembershipCompactResponse
```json
{
  "allOf": [
    {
      "$ref": "#/components/schemas/ProjectMembershipCompact"
    },
    {
      "type": "object",
      "properties": {
        "resource_type": {
          "description": "The base type of this resource.",
          "type": "string",
          "example": "membership"
        },
        "resource_subtype": {
          "description": "Type of the membership.",
          "type": "string",
          "example": "project_membership"
        }
      }
    }
  ]
}
```

### ProjectPortfolioSettingResponse
```json
{
  "allOf": [
    {
      "$ref": "#/components/schemas/ProjectPortfolioSettingCompact"
    },
    {
      "type": "object",
      "properties": {
        "created_at": {
          "description": "The time at which this project portfolio setting was created.",
          "type": "string",
          "format": "date-time",
          "readOnly": true,
          "example": "2012-02-22T02:06:58.147Z"
        }
      }
    }
  ]
}
```

### ProjectPortfolioSettingUpdateRequest
```json
{
  "type": "object",
  "properties": {
    "is_access_control_inherited": {
      "description": "When true, the portfolio members gain access to the project.",
      "type": "boolean",
      "example": true
    }
  }
}
```

### ProjectSaveAsTemplateRequest
```json
{
  "type": "object",
  "required": [
    "name",
    "public"
  ],
  "properties": {
    "name": {
      "description": "The name of the new project template.",
      "type": "string",
      "example": "New Project Template"
    },
    "team": {
      "description": "Sets the team of the new project template. If the project exists in an organization, specify team and not workspace.",
      "type": "string",
      "example": "12345"
    },
    "workspace": {
      "description": "Sets the workspace of the new project template. Only specify workspace if the project exists in a workspace.",
      "type": "string",
      "example": "12345"
    },
    "public": {
      "description": "Sets the project template to public to its team.",
      "type": "boolean",
      "example": true
    }
  }
}
```

### ProjectSectionInsertRequest
```json
{
  "type": "object",
  "properties": {
    "section": {
      "description": "The section to reorder.",
      "type": "string",
      "example": "321654"
    },
    "before_section": {
      "description": "Insert the given section immediately before the section specified by this parameter.",
      "type": "string",
      "example": "86420"
    },
    "after_section": {
      "description": "Insert the given section immediately after the section specified by this parameter.",
      "type": "string",
      "example": "987654"
    }
  },
  "required": [
    "section"
  ]
}
```

### ProjectStatusBase
```json
{
  "allOf": [
    {
      "$ref": "#/components/schemas/ProjectStatusCompact"
    },
    {
      "type": "object",
      "properties": {
        "text": {
          "description": "The text content of the status update.",
          "type": "string",
          "example": "The project is moving forward according to plan..."
        },
        "html_text": {
          "description": "[Opt In](/docs/inputoutput-options). The text content of the status update with formatting as HTML.",
          "type": "string",
          "example": "<body>The project <strong>is</strong> moving forward according to plan...</body>"
        },
        "color": {
          "description": "The color associated with the status update.",
          "type": "string",
          "enum": [
            "green",
            "yellow",
            "red",
            "blue",
            "complete"
          ]
        }
      }
    }
  ]
}
```

### ProjectStatusCompact
```json
{
  "description": "*Deprecated: new integrations should prefer the `status_update` resource.*\nA *project status* is an update on the progress of a particular project, and is sent out to all project followers when created. These updates include both text describing the update and a color code intended to represent the overall state of the project: \"green\" for projects that are on track, \"yellow\" for projects at risk, and \"red\" for projects that are behind.",
  "type": "object",
  "properties": {
    "gid": {
      "description": "Globally unique identifier of the resource, as a string.",
      "type": "string",
      "readOnly": true,
      "example": "12345",
      "x-insert-after": false
    },
    "resource_type": {
      "description": "The base type of this resource.",
      "type": "string",
      "readOnly": true,
      "example": "project_status",
      "x-insert-after": "gid"
    },
    "title": {
      "description": "The title of the project status update.",
      "type": "string",
      "example": "Status Update - Jun 15"
    }
  }
}
```

### ProjectStatusRequest
```json
{
  "$ref": "#/components/schemas/ProjectStatusBase"
}
```

### ProjectStatusResponse
```json
{
  "allOf": [
    {
      "$ref": "#/components/schemas/ProjectStatusBase"
    },
    {
      "type": "object",
      "properties": {
        "author": {
          "$ref": "#/components/schemas/UserCompact"
        },
        "created_at": {
          "description": "The time at which this resource was created.",
          "type": "string",
          "format": "date-time",
          "readOnly": true,
          "example": "2012-02-22T02:06:58.147Z"
        },
        "created_by": {
          "$ref": "#/components/schemas/UserCompact"
        },
        "modified_at": {
          "description": "The time at which this project status was last modified.\n*Note: This does not currently reflect any changes in associations such as comments that may have been added or removed from the project status.*",
          "type": "string",
          "format": "date-time",
          "readOnly": true,
          "example": "2012-02-22T02:06:58.147Z"
        }
      }
    }
  ]
}
```

### ProjectTemplateBase
```json
{
  "allOf": [
    {
      "$ref": "#/components/schemas/ProjectTemplateCompact"
    },
    {
      "type": "object",
      "properties": {
        "description": {
          "description": "Free-form textual information associated with the project template",
          "type": "string",
          "example": "These are things we need to pack for a trip."
        },
        "html_description": {
          "description": "The description of the project template with formatting as HTML.",
          "type": "string",
          "example": "<body>These are things we need to pack for a trip.</body>"
        },
        "public": {
          "description": "True if the project template is public to its team.",
          "type": "boolean",
          "example": false
        },
        "owner": {
          "description": "The current owner of the project template, may be null.",
          "allOf": [
            {
              "$ref": "#/components/schemas/UserCompact"
            },
            {
              "type": "object",
              "nullable": true
            }
          ]
        },
        "team": {
          "allOf": [
            {
              "$ref": "#/components/schemas/TeamCompact"
            }
          ]
        },
        "requested_dates": {
          "description": "Array of date variables in this project template. Calendar dates must be provided for these variables when instantiating a project.",
          "type": "array",
          "items": {
            "$ref": "#/components/schemas/DateVariableCompact"
          },
          "readOnly": true
        },
        "color": {
          "description": "Color of the project template.",
          "type": "string",
          "nullable": true,
          "enum": [
            "dark-pink",
            "dark-green",
            "dark-blue",
            "dark-red",
            "dark-teal",
            "dark-brown",
            "dark-orange",
            "dark-purple",
            "dark-warm-gray",
            "light-pink",
            "light-green",
            "light-blue",
            "light-red",
            "light-teal",
            "light-brown",
            "light-orange",
            "light-purple",
            "light-warm-gray",
            null
          ],
          "example": "light-green"
        },
        "requested_roles": {
          "description": "Array of template roles in this project template. User Ids can be provided for these variables when instantiating a project to assign template tasks to the user.",
          "type": "array",
          "items": {
            "$ref": "#/components/schemas/TemplateRole"
          }
        }
      }
    }
  ]
}
```

### ProjectTemplateCompact
```json
{
  "description": "A *project template* is an object that allows new projects to be created with a predefined setup, which may include tasks, sections, Rules, etc. It simplifies the process of running a workflow that involves a similar set of work every time.",
  "type": "object",
  "properties": {
    "gid": {
      "description": "Globally unique identifier of the resource, as a string.",
      "type": "string",
      "readOnly": true,
      "example": "12345",
      "x-insert-after": false
    },
    "resource_type": {
      "description": "The base type of this resource.",
      "type": "string",
      "readOnly": true,
      "example": "project_template",
      "x-insert-after": "gid"
    },
    "name": {
      "description": "Name of the project template.",
      "type": "string",
      "example": "Packing list"
    }
  }
}
```

### ProjectTemplateInstantiateProjectRequest
```json
{
  "type": "object",
  "required": [
    "name"
  ],
  "properties": {
    "name": {
      "description": "The name of the new project.",
      "type": "string",
      "example": "New Project Name"
    },
    "team": {
      "description": "*Optional*. Sets the team of the new project. If the project template exists in an _organization_, you may specify a value for `team`. If no value is provided then it defaults to the same team as the project template.",
      "type": "string",
      "example": "12345"
    },
    "public": {
      "description": "*Deprecated:* new integrations use `privacy_setting` instead.",
      "deprecated": true,
      "type": "boolean",
      "example": true
    },
    "privacy_setting": {
      "description": "The privacy setting of the project. *Note: Administrators in your organization may restrict the values of `privacy_setting`.* The value `private_to_team` is deprecated. Use `POST /memberships` to share a project with a team after creation.",
      "type": "string",
      "enum": [
        "public_to_workspace",
        "private_to_team",
        "private"
      ],
      "example": "public_to_workspace"
    },
    "is_strict": {
      "description": "*Optional*. If set to `true`, the endpoint returns an \"Unprocessable Entity\" error if you fail to provide a calendar date value for any date variable. If set to `false`, a default date is used for each unfulfilled date variable (e.g., the current date is used as the Start Date of a project).",
      "type": "boolean",
      "example": true
    },
    "requested_dates": {
      "description": "*Conditional*. Array of mappings of date variables to calendar dates. This property is required in the instantiation request if the project template includes dates (e.g., a start date on a task).",
      "type": "array",
      "items": {
        "$ref": "#/components/schemas/DateVariableRequest"
      }
    },
    "requested_roles": {
      "description": "Array of mappings of template roles to users.",
      "type": "array",
      "items": {
        "$ref": "#/components/schemas/RequestedRoleRequest"
      }
    }
  }
}
```

### ProjectTemplateResponse
```json
{
  "allOf": [
    {
      "$ref": "#/components/schemas/ProjectTemplateBase"
    }
  ]
}
```

### TaskAddProjectRequest
```json
{
  "type": "object",
  "properties": {
    "project": {
      "description": "The project to add the task to.",
      "type": "string",
      "example": "13579"
    },
    "insert_after": {
      "description": "A task in the project to insert the task after, or `null` to insert at the beginning of the list. When used with `section`, `null` will insert at the beginning of the specified section, otherwise the task must be in the specified section.",
      "type": "string",
      "nullable": true,
      "example": "124816"
    },
    "insert_before": {
      "description": "A task in the project to insert the task before, or `null` to insert at the end of the list. When used with `section`, `null` will insert at the end of the specified section, otherwise the task must be in the specified section.",
      "type": "string",
      "nullable": true,
      "example": "432134"
    },
    "section": {
      "description": "A section in the project to insert the task into. The task will be inserted at the bottom of the section unless combined with `insert_before: null` (end of section) or `insert_after: null` (beginning of section). Can also be combined with non-null `insert_before` or `insert_after` to position relative to a task within the section.",
      "type": "string",
      "nullable": true,
      "example": "987654"
    }
  },
  "required": [
    "project"
  ]
}
```

### TaskRemoveProjectRequest
```json
{
  "type": "object",
  "properties": {
    "project": {
      "description": "The project to remove the task from.",
      "type": "string",
      "example": "13579"
    }
  },
  "required": [
    "project"
  ]
}
```

Other schemas that reference this resource (context only):
- `AllocationResponse` (refs: ProjectCompact)
- `BudgetResponse` (refs: ProjectCompact)
- `CustomFieldSettingResponse` (refs: ProjectCompact)
- `GoalRelationshipCompact` (refs: ProjectCompact)
- `JobCompact` (refs: ProjectCompact)
- `ProjectBriefResponse` (refs: ProjectCompact)
- `ProjectMembershipCompact` (refs: ProjectCompact)
- `ProjectMembershipNormalResponse` (refs: ProjectCompact)
- `ProjectPortfolioSettingCompact` (refs: ProjectCompact)
- `RateCompact` (refs: ProjectCompact)
- `StatusUpdateResponse` (refs: ProjectCompact)
- `TaskTemplateRecipe` (refs: ProjectCompact)
- `TaskTemplateResponse` (refs: ProjectCompact)
- `TimeTrackingEntryCompact` (refs: ProjectCompact)

---

## Implementation Rules for Pass 2

### What to add

- **FK columns** in `database/schema.py`: add `mapped_column(ForeignKey(...))`
  for each identified relationship. Use the evidence and schema shapes above
  to determine:
  - Which fields become FK columns (look for `_id` suffixed fields, nested
    objects with `id`, and `$ref` pointers to related resource schemas)
  - Whether `nullable=False` (required) or `nullable=True` (optional),
    based on the schema's `required` list
  - The correct column type (must match the target table's PK type)
- **Indexes** in `__table_args__`: add `Index()` for every new FK column
- **relationship() declarations**: add on both sides (this model and the
  target model). Use `foreign_keys=[col]` when multiple FKs point at the
  same table. Use `remote_side=[id]` for self-referential relationships.
- **Association tables**: for M:N relationships, add a `Table()` with
  composite primary key above the model classes
- **Stub models**: if a FK target model does not yet exist in schema.py,
  create a minimal stub marked with `# STUB — expand when implementing this resource`.
  If a stub already exists for the target model, leave it as-is — it will be
  expanded when that resource is implemented
- **Update operations**: for every create/update function that sets a FK
  column, ensure the FK target row exists before flushing. Add a helper
  (e.g. `_ensure_<entity>_stub(session, gid)`) that creates a minimal stub
  row if the target doesn't exist, and call it before assigning the FK
  value. Without this, `session.flush()` will raise a ForeignKeyViolation.
  Also add eager loading (`joinedload`/`selectinload`) where FK-related
  queries need it.
- **Update serializers**: where the API response includes nested related
  objects (not just an ID), update the serializer to include them

### What NOT to do

- Do not modify the base columns, CRUD logic, or route handlers from Pass 1
  unless necessary for FK support
- Do not create FK columns or relationships for entities listed in
  External Schemas — those are context only
- Do not guess relationships that aren't supported by the evidence above
