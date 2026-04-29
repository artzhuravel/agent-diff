# Entity Implementation (Pass 2 — Relationships): goals

You are adding foreign key relationships to the **goals** resource
(`AsanaGoal` in `asana_goals`). The base model, operations,
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

These resources have a demonstrated relationship with **goals**
through shared endpoints, FK-shaped property names, or schema cross-references.

Direction key:
- **outgoing** — goals's schemas contain fields that reference
  the related resource (e.g. a `_id` field or nested object pointing there).
  **Action**: add a FK column on `asana_goals` pointing at the related
  resource's table, plus a `relationship()` on both sides.
- **incoming** — the related resource's endpoints reference goals
  (the subject of those endpoints is the other resource, not goals).
  **Action**: do NOT add a FK column on `asana_goals`. The FK lives on the
  other resource's table. Add only a `relationship()` on the goals
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

### goals
- **SELF-REFERENTIAL** — this resource references itself
- Use the Self Referential pattern: nullable FK to own table,
  `remote_side=[id]` on the parent relationship
- Table: `asana_goals`
- Primary key: `gid`
- Direction: outgoing
- **Fields referencing goals**: `data`

These fields create a self-referential hierarchy. Add a nullable FK column (e.g. `parent_id`) pointing at `asana_goals.gid` with `remote_side=[gid]`.

Evidence:
  - GET /goals/{goal_gid}/custom_field_settings — url_segment: goals
  - GET /goals/{goal_gid}/custom_field_settings — url_segment: goal_gid
  - POST /goals/{goal_gid}/addSupportingRelationship — url_segment: goals
  - POST /goals/{goal_gid}/addSupportingRelationship — url_segment: goal_gid
  - POST /goals/{goal_gid}/addSupportingRelationship — property: data.supported_goal
  - POST /goals/{goal_gid}/removeSupportingRelationship — url_segment: goals
  - POST /goals/{goal_gid}/removeSupportingRelationship — url_segment: goal_gid
  - DELETE /goals/{goal_gid} — url_segment: goals
  - DELETE /goals/{goal_gid} — url_segment: goal_gid
  - GET /goals/{goal_gid} — url_segment: goals
  - GET /goals/{goal_gid} — url_segment: goal_gid
  - GET /goals/{goal_gid} — property: data
  - GET /goals/{goal_gid} — property: data.metric
  - PUT /goals/{goal_gid} — url_segment: goals
  - PUT /goals/{goal_gid} — url_segment: goal_gid
  - PUT /goals/{goal_gid} — property: data
  - PUT /goals/{goal_gid} — property: data.metric
  - GET /goals — url_segment: goals
  - GET /goals — property: data
  - POST /goals — url_segment: goals
  - POST /goals — property: data
  - POST /goals — property: data
  - POST /goals — property: data.metric
  - POST /goals/{goal_gid}/setMetric — url_segment: goals
  - POST /goals/{goal_gid}/setMetric — url_segment: goal_gid
  - POST /goals/{goal_gid}/setMetric — property: data
  - POST /goals/{goal_gid}/setMetric — property: data
  - POST /goals/{goal_gid}/setMetric — property: data.metric
  - POST /goals/{goal_gid}/setMetricCurrentValue — url_segment: goals
  - POST /goals/{goal_gid}/setMetricCurrentValue — url_segment: goal_gid
  - POST /goals/{goal_gid}/setMetricCurrentValue — property: data
  - POST /goals/{goal_gid}/setMetricCurrentValue — property: data.metric
  - POST /goals/{goal_gid}/addFollowers — url_segment: goals
  - POST /goals/{goal_gid}/addFollowers — url_segment: goal_gid
  - POST /goals/{goal_gid}/addFollowers — property: data
  - POST /goals/{goal_gid}/addFollowers — property: data.metric
  - POST /goals/{goal_gid}/removeFollowers — url_segment: goals
  - POST /goals/{goal_gid}/removeFollowers — url_segment: goal_gid
  - POST /goals/{goal_gid}/removeFollowers — property: data
  - POST /goals/{goal_gid}/removeFollowers — property: data.metric
  - GET /goals/{goal_gid}/parentGoals — url_segment: goals
  - GET /goals/{goal_gid}/parentGoals — url_segment: goal_gid
  - GET /goals/{goal_gid}/parentGoals — property: data
  - POST /goals/{goal_gid}/addCustomFieldSetting — url_segment: goals
  - POST /goals/{goal_gid}/addCustomFieldSetting — url_segment: goal_gid
  - POST /goals/{goal_gid}/removeCustomFieldSetting — url_segment: goals
  - POST /goals/{goal_gid}/removeCustomFieldSetting — url_segment: goal_gid

Key fields (PK + fields referencing goals):
```json
{
  "GoalCompact": {
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
  "GoalMetricBase": {
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

### projects
- Table: `asana_projects`
- Primary key: `gid`
- Direction: outgoing
- **Fields referencing projects**: `data.custom_field_settings.parent`, `data.custom_field_settings.project`, `data.parent`, `data.project`, `data.supporting_resource`

These fields all point at the `asana_projects` table. Infer the correct FK relationship type and apply using the reference patterns above.

Evidence:
  - GET /goals/{goal_gid}/custom_field_settings — property: data.project
  - GET /goals/{goal_gid}/custom_field_settings — property: data.parent
  - POST /goals/{goal_gid}/addSupportingRelationship — property: data.supporting_resource
  - GET /goals/{goal_gid} — property: data.custom_field_settings.project
  - GET /goals/{goal_gid} — property: data.custom_field_settings.parent
  - PUT /goals/{goal_gid} — property: data.custom_field_settings.project
  - PUT /goals/{goal_gid} — property: data.custom_field_settings.parent
  - GET /goals — query: project
  - POST /goals — query: project
  - POST /goals — property: data.custom_field_settings.project
  - POST /goals — property: data.custom_field_settings.parent
  - POST /goals/{goal_gid}/setMetric — property: data.custom_field_settings.project
  - POST /goals/{goal_gid}/setMetric — property: data.custom_field_settings.parent
  - POST /goals/{goal_gid}/setMetricCurrentValue — property: data.custom_field_settings.project
  - POST /goals/{goal_gid}/setMetricCurrentValue — property: data.custom_field_settings.parent
  - POST /goals/{goal_gid}/addFollowers — property: data.custom_field_settings.project
  - POST /goals/{goal_gid}/addFollowers — property: data.custom_field_settings.parent
  - POST /goals/{goal_gid}/removeFollowers — property: data.custom_field_settings.project
  - POST /goals/{goal_gid}/removeFollowers — property: data.custom_field_settings.parent
  - POST /goals/{goal_gid}/addCustomFieldSetting — property: data.project
  - POST /goals/{goal_gid}/addCustomFieldSetting — property: data.parent

Key fields (PK + fields referencing goals):
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

### stories
- Table: `asana_stories`
- Primary key: `gid`
- Direction: incoming

Evidence:
  - GET /goals/{goal_gid}/stories — url_segment: goals (incoming)
  - GET /goals/{goal_gid}/stories — url_segment: goal_gid (incoming)
  - POST /goals/{goal_gid}/stories — url_segment: goals (incoming)
  - POST /goals/{goal_gid}/stories — url_segment: goal_gid (incoming)

Key fields (PK + fields referencing goals):
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
- Direction: outgoing
- **Fields referencing tasks**: `data.custom_field_settings.parent`, `data.parent`

These fields all point at the `asana_tasks` table. Infer the correct FK relationship type and apply using the reference patterns above.

Evidence:
  - GET /goals/{goal_gid}/custom_field_settings — property: data.parent
  - GET /goals/{goal_gid} — property: data.custom_field_settings.parent
  - PUT /goals/{goal_gid} — property: data.custom_field_settings.parent
  - GET /goals — query: task
  - POST /goals — query: task
  - POST /goals — property: data.custom_field_settings.parent
  - POST /goals/{goal_gid}/setMetric — property: data.custom_field_settings.parent
  - POST /goals/{goal_gid}/setMetricCurrentValue — property: data.custom_field_settings.parent
  - POST /goals/{goal_gid}/addFollowers — property: data.custom_field_settings.parent
  - POST /goals/{goal_gid}/removeFollowers — property: data.custom_field_settings.parent
  - POST /goals/{goal_gid}/addCustomFieldSetting — property: data.parent

Key fields (PK + fields referencing goals):
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
- Direction: outgoing
- **Fields referencing teams**: `data.team`

These fields all point at the `asana_teams` table. Infer the correct FK relationship type and apply using the reference patterns above.

Evidence:
  - GET /goals/{goal_gid} — property: data.team
  - PUT /goals/{goal_gid} — property: data.team
  - PUT /goals/{goal_gid} — property: data.team
  - GET /goals — query: team
  - POST /goals — query: team
  - POST /goals — property: data.team
  - POST /goals — property: data.team
  - POST /goals/{goal_gid}/setMetric — property: data.team
  - POST /goals/{goal_gid}/setMetricCurrentValue — property: data.team
  - POST /goals/{goal_gid}/addFollowers — property: data.team
  - POST /goals/{goal_gid}/removeFollowers — property: data.team

Key fields (PK + fields referencing goals):
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
- **Fields referencing users**: `data.custom_field.created_by`, `data.custom_field.people_value`, `data.custom_field_settings.custom_field.created_by`, `data.custom_field_settings.custom_field.people_value`, `data.followers`, `data.likes.user`, `data.owner`, `data.supported_goal.owner`

These fields all point at the `asana_users` table. Infer the correct FK relationship type and apply using the reference patterns above.

Evidence:
  - GET /goals/{goal_gid}/custom_field_settings — property: data.custom_field.created_by
  - GET /goals/{goal_gid}/custom_field_settings — property: data.custom_field.people_value
  - POST /goals/{goal_gid}/addSupportingRelationship — property: data.supported_goal.owner
  - GET /goals/{goal_gid} — property: data.likes.user
  - GET /goals/{goal_gid} — property: data.followers
  - GET /goals/{goal_gid} — property: data.owner
  - GET /goals/{goal_gid} — property: data.custom_field_settings.custom_field.created_by
  - GET /goals/{goal_gid} — property: data.custom_field_settings.custom_field.people_value
  - PUT /goals/{goal_gid} — property: data.owner
  - PUT /goals/{goal_gid} — property: data.likes.user
  - PUT /goals/{goal_gid} — property: data.followers
  - PUT /goals/{goal_gid} — property: data.owner
  - PUT /goals/{goal_gid} — property: data.custom_field_settings.custom_field.created_by
  - PUT /goals/{goal_gid} — property: data.custom_field_settings.custom_field.people_value
  - GET /goals — property: data.owner
  - POST /goals — property: data.owner
  - POST /goals — property: data.followers
  - POST /goals — property: data.likes.user
  - POST /goals — property: data.followers
  - POST /goals — property: data.owner
  - POST /goals — property: data.custom_field_settings.custom_field.created_by
  - POST /goals — property: data.custom_field_settings.custom_field.people_value
  - POST /goals/{goal_gid}/setMetric — property: data.likes.user
  - POST /goals/{goal_gid}/setMetric — property: data.followers
  - POST /goals/{goal_gid}/setMetric — property: data.owner
  - POST /goals/{goal_gid}/setMetric — property: data.custom_field_settings.custom_field.created_by
  - POST /goals/{goal_gid}/setMetric — property: data.custom_field_settings.custom_field.people_value
  - POST /goals/{goal_gid}/setMetricCurrentValue — property: data.likes.user
  - POST /goals/{goal_gid}/setMetricCurrentValue — property: data.followers
  - POST /goals/{goal_gid}/setMetricCurrentValue — property: data.owner
  - POST /goals/{goal_gid}/setMetricCurrentValue — property: data.custom_field_settings.custom_field.created_by
  - POST /goals/{goal_gid}/setMetricCurrentValue — property: data.custom_field_settings.custom_field.people_value
  - POST /goals/{goal_gid}/addFollowers — property: data.followers
  - POST /goals/{goal_gid}/addFollowers — property: data.likes.user
  - POST /goals/{goal_gid}/addFollowers — property: data.followers
  - POST /goals/{goal_gid}/addFollowers — property: data.owner
  - POST /goals/{goal_gid}/addFollowers — property: data.custom_field_settings.custom_field.created_by
  - POST /goals/{goal_gid}/addFollowers — property: data.custom_field_settings.custom_field.people_value
  - POST /goals/{goal_gid}/removeFollowers — property: data.followers
  - POST /goals/{goal_gid}/removeFollowers — property: data.likes.user
  - POST /goals/{goal_gid}/removeFollowers — property: data.followers
  - POST /goals/{goal_gid}/removeFollowers — property: data.owner
  - POST /goals/{goal_gid}/removeFollowers — property: data.custom_field_settings.custom_field.created_by
  - POST /goals/{goal_gid}/removeFollowers — property: data.custom_field_settings.custom_field.people_value
  - GET /goals/{goal_gid}/parentGoals — property: data.owner
  - POST /goals/{goal_gid}/addCustomFieldSetting — property: data.custom_field.created_by
  - POST /goals/{goal_gid}/addCustomFieldSetting — property: data.custom_field.people_value

Key fields (PK + fields referencing goals):
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
  - GET /goals/{goal_gid} — property: data.workspace
  - PUT /goals/{goal_gid} — property: data.workspace
  - PUT /goals/{goal_gid} — property: data.workspace
  - GET /goals — query: workspace
  - POST /goals — query: workspace
  - POST /goals — property: data.workspace
  - POST /goals — property: data.workspace
  - POST /goals/{goal_gid}/setMetric — property: data.workspace
  - POST /goals/{goal_gid}/setMetricCurrentValue — property: data.workspace
  - POST /goals/{goal_gid}/addFollowers — property: data.workspace
  - POST /goals/{goal_gid}/removeFollowers — property: data.workspace
  - POST /goals/{goal_gid}/addCustomFieldSetting — property: data.custom_field.workspace

Key fields (PK + fields referencing goals):
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

These schemas reference **goals** but belong to entities that are
**not part of this implementation**. Do NOT create FK columns, relationship
declarations, or stub models for them. They are shown only so you understand
how goals appears in the broader API.

### GoalAddSubgoalRequest
```json
{
  "type": "object",
  "required": [
    "subgoal"
  ],
  "properties": {
    "subgoal": {
      "description": "The goal gid to add as subgoal to a parent goal",
      "type": "string",
      "example": "1331"
    },
    "insert_before": {
      "description": "An id of a subgoal of this parent goal. The new subgoal will be added before the one specified here. `insert_before` and `insert_after` parameters cannot both be specified.",
      "type": "string",
      "example": "1331"
    },
    "insert_after": {
      "description": "An id of a subgoal of this parent goal. The new subgoal will be added after the one specified here. `insert_before` and `insert_after` parameters cannot both be specified.",
      "type": "string",
      "example": "1331"
    }
  }
}
```

### GoalAddSupportingRelationshipRequest
```json
{
  "type": "object",
  "required": [
    "supporting_resource"
  ],
  "properties": {
    "supporting_resource": {
      "description": "The gid of the supporting resource to add to the parent goal. Must be the gid of a goal, project, task, or portfolio.",
      "type": "string",
      "example": "12345"
    },
    "insert_before": {
      "description": "An id of a subgoal of this parent goal. The new subgoal will be added before the one specified here. `insert_before` and `insert_after` parameters cannot both be specified. Currently only supported when adding a subgoal.",
      "type": "string",
      "example": "1331"
    },
    "insert_after": {
      "description": "An id of a subgoal of this parent goal. The new subgoal will be added after the one specified here. `insert_before` and `insert_after` parameters cannot both be specified. Currently only supported when adding a subgoal.",
      "type": "string",
      "example": "1331"
    },
    "contribution_weight": {
      "description": "Defines how much the supporting goal\u2019s progress contributes to the parent goal\u2019s overall progress. When used with automatically calculated [Goal Metrics](/reference/creategoalmetric) (such as `progress_source = subgoal_progress`), this value must be greater than 0 for the subgoal to count toward the parent goal\u2019s progress.\nAccepts a number between 0 and 1 (inclusive). Defaults to `0`.",
      "type": "number",
      "example": 0
    }
  }
}
```

### GoalAddSupportingWorkRequest
```json
{
  "type": "object",
  "required": [
    "supporting_work"
  ],
  "properties": {
    "supporting_work": {
      "description": "The project/task/portfolio gid to add as supporting work for a goal",
      "type": "string",
      "example": "1331"
    }
  }
}
```

### GoalBase
```json
{
  "description": "A generic Asana Resource, containing a globally unique identifier.",
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
      "example": "goal",
      "x-insert-after": "gid"
    },
    "name": {
      "type": "string",
      "description": "The name of the goal.",
      "example": "Grow web traffic by 30%"
    },
    "html_notes": {
      "type": "string",
      "description": "The notes of the goal with formatting as HTML.",
      "example": "<body>Start building brand awareness.</body>"
    },
    "notes": {
      "type": "string",
      "description": "Free-form textual information associated with the goal (i.e. its description).",
      "example": "Start building brand awareness."
    },
    "due_on": {
      "type": "string",
      "description": "The localized day on which this goal is due. This takes a date with format `YYYY-MM-DD`.",
      "example": "2019-09-15",
      "nullable": true
    },
    "start_on": {
      "type": "string",
      "description": "The day on which work for this goal begins, or null if the goal has no start date. This takes a date with `YYYY-MM-DD` format, and cannot be set unless there is an accompanying due date.",
      "example": "2019-09-14",
      "nullable": true
    },
    "is_workspace_level": {
      "type": "boolean",
      "description": "*Conditional*. This property is only present when the `workspace` provided is an organization. Whether the goal belongs to the `workspace` (and is listed as part of the workspace\u2019s goals) or not. If it isn\u2019t a workspace-level goal, it is a team-level goal, and is associated with the goal\u2019s team.",
      "example": true
    },
    "liked": {
      "type": "boolean",
      "description": "True if the goal is liked by the authorized user, false if not.",
      "example": false
    }
  }
}
```

### GoalMembershipCompact
```json
{
  "allOf": [
    {
      "$ref": "#/components/schemas/GoalMembershipBase"
    },
    {
      "type": "object",
      "properties": {
        "is_commenter": {
          "type": "boolean",
          "deprecated": true,
          "readOnly": true,
          "description": "*Deprecated: new integrations should prefer the `access_level` field.* Describes if the member is comment only in goal. This field is deprecated and will always be null.",
          "example": false
        },
        "is_editor": {
          "type": "boolean",
          "deprecated": true,
          "readOnly": true,
          "description": "*Deprecated: new integrations should prefer the `access_level` field.* Describes if the member is editor in goal. This field is deprecated and will always be null.",
          "example": false
        }
      }
    }
  ]
}
```

### GoalMembershipResponse
```json
{
  "allOf": [
    {
      "$ref": "#/components/schemas/GoalMembershipBase"
    },
    {
      "type": "object",
      "properties": {
        "user": {
          "allOf": [
            {
              "$ref": "#/components/schemas/UserCompact"
            },
            {
              "type": "object",
              "deprecated": true,
              "readOnly": true,
              "description": "*Deprecated: new integrations should prefer the `member` field.* A *user* object represents an account in Asana that can be given access to various workspaces, projects, and tasks."
            }
          ]
        },
        "workspace": {
          "allOf": [
            {
              "$ref": "#/components/schemas/WorkspaceCompact"
            },
            {
              "type": "object",
              "deprecated": true,
              "readOnly": true,
              "description": "*Deprecated:* A *workspace* is the highest-level organizational unit in Asana. All projects and tasks have an associated workspace."
            }
          ]
        }
      }
    }
  ]
}
```

### GoalMetricCurrentValueRequest
```json
{
  "description": "A generic Asana Resource, containing a globally unique identifier.",
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
      "example": "task",
      "x-insert-after": "gid"
    },
    "current_number_value": {
      "description": "*Conditional*. This number is the current value of a goal metric of type number.",
      "type": "number",
      "example": 8.12
    }
  }
}
```

### GoalRelationshipCompact
```json
{
  "description": "A *goal relationship* is an object representing the relationship between a goal and another goal, a project, a task, or a portfolio.",
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
      "example": "goal_relationship",
      "x-insert-after": "gid"
    },
    "resource_subtype": {
      "description": "The subtype of this resource. Different subtypes retain many of the same fields and behavior, but may render differently in Asana or represent resources with different semantic meaning.",
      "type": "string",
      "readOnly": true,
      "example": "subgoal",
      "enum": [
        "subgoal",
        "supporting_work"
      ]
    },
    "supporting_resource": {
      "allOf": [
        {
          "$ref": "#/components/schemas/ProjectCompact"
        },
        {
          "type": "object",
          "readOnly": true,
          "description": "The supporting resource that supports the goal. This can be either a project, task, portfolio, or goal."
        }
      ]
    },
    "contribution_weight": {
      "description": "The weight that the supporting resource's progress contributes to the supported goal's progress. This can be 0, 1, or any value in between.",
      "type": "number",
      "example": 1.0
    }
  }
}
```

### GoalRelationshipRequest
```json
{
  "allOf": [
    {
      "$ref": "#/components/schemas/GoalRelationshipBase"
    },
    {
      "type": "object"
    }
  ]
}
```

### GoalRelationshipResponse
```json
{
  "allOf": [
    {
      "$ref": "#/components/schemas/GoalRelationshipBase"
    },
    {
      "type": "object"
    }
  ]
}
```

### GoalRemoveSubgoalRequest
```json
{
  "type": "object",
  "required": [
    "subgoal"
  ],
  "properties": {
    "subgoal": {
      "description": "The goal gid to remove as subgoal from the parent goal",
      "type": "string",
      "example": "1331"
    }
  }
}
```

### GoalRemoveSupportingRelationshipRequest
```json
{
  "type": "object",
  "required": [
    "supporting_resource"
  ],
  "properties": {
    "supporting_resource": {
      "description": "The gid of the supporting resource to remove from the parent goal. Must be the gid of a goal, project, task, or portfolio.",
      "type": "string",
      "example": "12345"
    }
  }
}
```

### GoalRequestBase
```json
{
  "allOf": [
    {
      "$ref": "#/components/schemas/GoalBase"
    },
    {
      "type": "object",
      "properties": {
        "team": {
          "type": "string",
          "description": "*Conditional*. This property is only present when the `workspace` provided is an organization.",
          "example": "12345",
          "nullable": true
        },
        "workspace": {
          "type": "string",
          "description": "The `gid` of a workspace.",
          "example": "12345"
        },
        "time_period": {
          "type": "string",
          "description": "The `gid` of a time period.",
          "example": "12345",
          "nullable": true
        },
        "owner": {
          "type": "string",
          "description": "The `gid` of a user.",
          "example": "12345",
          "nullable": true
        }
      }
    }
  ]
}
```

### GoalUpdateRequest
```json
{
  "allOf": [
    {
      "$ref": "#/components/schemas/GoalRequestBase"
    },
    {
      "type": "object",
      "properties": {
        "status": {
          "type": "string",
          "description": "The current status of this goal. When the goal is open, its status can be `green`, `yellow`, and `red` to reflect \"On Track\", \"At Risk\", and \"Off Track\", respectively. When the goal is closed, the value can be `missed`, `achieved`, `partial`, or `dropped`.\n*Note* you can only write to this property if `metric` is set.",
          "example": "green",
          "nullable": true
        },
        "custom_fields": {
          "description": "An object where each key is the GID of a custom field and its corresponding value is either an enum GID, string, number, or object (depending on the custom field type). See the [custom fields guide](/docs/custom-fields-guide) for details on creating and updating custom field values.",
          "type": "object",
          "additionalProperties": {
            "type": "string",
            "description": "\"{custom_field_gid}\" => Value (can be text, enum GID, a number, etc.). For date, use format \"YYYY-MM-DD\" (e.g., 2019-09-15). For date-time, use ISO 8601 date string in UTC (e.g., 2019-09-15T02:06:58.147Z)."
          },
          "example": {
            "5678904321": "On Hold",
            "4578152156": "Not Started"
          }
        }
      }
    }
  ]
}
```

Other schemas that reference this resource (context only):
- `GoalMembershipBase` (refs: GoalCompact)
- `GoalRelationshipBase` (refs: GoalCompact)

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
