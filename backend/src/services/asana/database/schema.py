"""ORM schema for the Asana API replica.

Entities are added to this file one at a time during the resource
implementation loop. Each entity implementation may also add stub models
for FK dependencies marked with: # STUB — expand when implementing this resource

AGENT INSTRUCTION: Do not write this file from scratch. Each entity
implementation adds its model class to this file incrementally.
"""

from typing import Any, Optional

from sqlalchemy import Boolean, Column, ForeignKey, Index, Integer, String, Table, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


# Association table: users <-> workspaces (M:N)
asana_user_workspaces = Table(
    "asana_user_workspaces",
    Base.metadata,
    Column("user_gid", ForeignKey("asana_users.gid"), primary_key=True),
    Column("workspace_gid", ForeignKey("asana_workspaces.gid"), primary_key=True),
)

# Association table: projects <-> members (users)
asana_project_members = Table(
    "asana_project_members",
    Base.metadata,
    Column("project_gid", ForeignKey("asana_projects.gid"), primary_key=True),
    Column("user_gid", ForeignKey("asana_users.gid"), primary_key=True),
)

# Association table: projects <-> followers (users)
asana_project_followers = Table(
    "asana_project_followers",
    Base.metadata,
    Column("project_gid", ForeignKey("asana_projects.gid"), primary_key=True),
    Column("user_gid", ForeignKey("asana_users.gid"), primary_key=True),
)

# Association table: tags <-> followers (users) (M:N)
asana_tag_followers = Table(
    "asana_tag_followers",
    Base.metadata,
    Column("tag_gid", ForeignKey("asana_tags.gid"), primary_key=True),
    Column("user_gid", ForeignKey("asana_users.gid"), primary_key=True),
)

# Association table: tasks <-> tags (M:N).
# Hand-patched after the extend stage that added the ``tags`` resource —
# tasks Pass 2 didn't re-run, so the relationship would otherwise have
# stayed as a JSONB column on AsanaTask.
asana_task_tags = Table(
    "asana_task_tags",
    Base.metadata,
    Column("task_gid", ForeignKey("asana_tasks.gid"), primary_key=True),
    Column("tag_gid", ForeignKey("asana_tags.gid"), primary_key=True),
)


class AsanaUser(Base):
    __tablename__ = "asana_users"

    # Primary key — Asana GIDs are opaque numeric strings (e.g. "12345")
    gid: Mapped[str] = mapped_column(String(50), primary_key=True)
    resource_type: Mapped[str] = mapped_column(String(50), default="user")

    # UserCompact fields
    name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # UserBaseResponse fields
    email: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # photo is a map of image sizes — stored as JSONB
    photo: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)

    # Soft-delete support
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)

    # M:N to asana_workspaces — a user belongs to multiple workspaces
    workspaces: Mapped[list["AsanaWorkspace"]] = relationship(
        secondary=asana_user_workspaces, back_populates="users"
    )

    owned_projects: Mapped[list["AsanaProject"]] = relationship(
        back_populates="owner", foreign_keys="AsanaProject.owner_gid"
    )
    completed_projects: Mapped[list["AsanaProject"]] = relationship(
        back_populates="completed_by", foreign_keys="AsanaProject.completed_by_gid"
    )
    member_projects: Mapped[list["AsanaProject"]] = relationship(
        secondary=asana_project_members, back_populates="member_users"
    )
    follower_projects: Mapped[list["AsanaProject"]] = relationship(
        secondary=asana_project_followers, back_populates="follower_users"
    )

    # Back-reference from AsanaTag (followers M:N)
    follower_tags: Mapped[list["AsanaTag"]] = relationship(
        secondary=asana_tag_followers, back_populates="follower_users"
    )

    # Back-references from AsanaStory (three FK roles pointing at users)
    created_stories: Mapped[list["AsanaStory"]] = relationship(
        back_populates="created_by", foreign_keys="AsanaStory.created_by_gid"
    )
    assignee_stories: Mapped[list["AsanaStory"]] = relationship(
        back_populates="assignee", foreign_keys="AsanaStory.assignee_gid"
    )
    follower_stories: Mapped[list["AsanaStory"]] = relationship(
        back_populates="follower", foreign_keys="AsanaStory.follower_gid"
    )

    # Back-references from AsanaTask (four FK roles pointing at users)
    assigned_tasks: Mapped[list["AsanaTask"]] = relationship(
        back_populates="assignee", foreign_keys="AsanaTask.assignee_gid"
    )
    assigned_by_tasks: Mapped[list["AsanaTask"]] = relationship(
        back_populates="assigned_by", foreign_keys="AsanaTask.assigned_by_gid"
    )
    completed_tasks: Mapped[list["AsanaTask"]] = relationship(
        back_populates="completed_by", foreign_keys="AsanaTask.completed_by_gid"
    )
    created_tasks: Mapped[list["AsanaTask"]] = relationship(
        back_populates="created_by", foreign_keys="AsanaTask.created_by_gid"
    )


class AsanaWorkspace(Base):
    __tablename__ = "asana_workspaces"

    # Primary key — Asana GIDs are opaque numeric strings (e.g. "12345")
    gid: Mapped[str] = mapped_column(String(50), primary_key=True)
    resource_type: Mapped[str] = mapped_column(String(50), default="workspace")

    # WorkspaceCompact fields
    name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # WorkspaceResponse-only fields
    # email_domains is an array of strings — stored as JSONB
    email_domains: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    is_organization: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    # Soft-delete support
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)

    # Back-reference: users who belong to this workspace
    users: Mapped[list["AsanaUser"]] = relationship(
        secondary=asana_user_workspaces, back_populates="workspaces"
    )
    projects: Mapped[list["AsanaProject"]] = relationship(back_populates="workspace")
    tasks: Mapped[list["AsanaTask"]] = relationship(
        back_populates="workspace", foreign_keys="AsanaTask.workspace_gid"
    )
    tags: Mapped[list["AsanaTag"]] = relationship(back_populates="workspace")


class AsanaProject(Base):
    __tablename__ = "asana_projects"
    __table_args__ = (
        Index("ix_asana_projects_parent", "parent_gid"),
        Index("ix_asana_projects_owner", "owner_gid"),
        Index("ix_asana_projects_workspace", "workspace_gid"),
        Index("ix_asana_projects_completed_by", "completed_by_gid"),
    )

    # Primary key — Asana GIDs are opaque numeric strings (e.g. "12345")
    gid: Mapped[str] = mapped_column(String(50), primary_key=True)
    resource_type: Mapped[str] = mapped_column(String(50), default="project")
    name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ProjectBase fields
    archived: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    color: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    icon: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    modified_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    html_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # public is deprecated, kept for backwards compat
    public: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    privacy_setting: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    default_view: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    due_date: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    due_on: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    start_on: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    default_access_level: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    minimum_access_level_for_customization: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    minimum_access_level_for_sharing: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # ProjectResponse-only fields
    completed: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    completed_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    permalink_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Self-referential FK: a project may be nested under a parent project
    parent_gid: Mapped[Optional[str]] = mapped_column(
        ForeignKey("asana_projects.gid"), nullable=True
    )
    parent: Mapped[Optional["AsanaProject"]] = relationship(
        remote_side="AsanaProject.gid",
        back_populates="sub_projects",
        foreign_keys="[AsanaProject.parent_gid]",
    )
    sub_projects: Mapped[list["AsanaProject"]] = relationship(
        back_populates="parent",
        foreign_keys="[AsanaProject.parent_gid]",
    )

    # FK to asana_users (owner — scalar, one project has one owner)
    owner_gid: Mapped[Optional[str]] = mapped_column(
        ForeignKey("asana_users.gid"), nullable=True
    )
    owner: Mapped[Optional["AsanaUser"]] = relationship(
        back_populates="owned_projects",
        foreign_keys="[AsanaProject.owner_gid]",
    )

    # FK to asana_users (completed_by — scalar)
    completed_by_gid: Mapped[Optional[str]] = mapped_column(
        ForeignKey("asana_users.gid"), nullable=True
    )
    completed_by: Mapped[Optional["AsanaUser"]] = relationship(
        back_populates="completed_projects",
        foreign_keys="[AsanaProject.completed_by_gid]",
    )

    # M:N to asana_users via association tables
    member_users: Mapped[list["AsanaUser"]] = relationship(
        secondary=asana_project_members, back_populates="member_projects"
    )
    follower_users: Mapped[list["AsanaUser"]] = relationship(
        secondary=asana_project_followers, back_populates="follower_projects"
    )

    # FK to asana_workspaces
    workspace_gid: Mapped[Optional[str]] = mapped_column(
        ForeignKey("asana_workspaces.gid"), nullable=True
    )
    workspace: Mapped[Optional["AsanaWorkspace"]] = relationship(back_populates="projects")

    # One-to-many: a project owns many sections
    sections: Mapped[list["AsanaSection"]] = relationship(
        back_populates="project", cascade="all,delete-orphan"
    )

    # Back-reference from AsanaStory (stories that reference this project)
    stories: Mapped[list["AsanaStory"]] = relationship(
        back_populates="project", foreign_keys="AsanaStory.project_gid"
    )

    # team_gid is kept as a plain string — teams are not part of this implementation
    team_gid: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Nested/array fields stored as JSONB
    current_status: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    current_status_update: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    custom_field_settings: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    custom_fields: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    project_brief: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    created_from_template: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)

    # Soft-delete support
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class AsanaTask(Base):
    __tablename__ = "asana_tasks"
    __table_args__ = (
        Index("ix_asana_tasks_workspace", "workspace_gid"),
        Index("ix_asana_tasks_assignee", "assignee_gid"),
        Index("ix_asana_tasks_parent", "parent_gid"),
        Index("ix_asana_tasks_assignee_section", "assignee_section_gid"),
        Index("ix_asana_tasks_assigned_by", "assigned_by_gid"),
        Index("ix_asana_tasks_completed_by", "completed_by_gid"),
        Index("ix_asana_tasks_created_by", "created_by_gid"),
    )

    # Primary key — Asana GIDs are opaque numeric strings (e.g. "12345")
    gid: Mapped[str] = mapped_column(String(50), primary_key=True)
    resource_type: Mapped[str] = mapped_column(String(50), default="task")
    resource_subtype: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # TaskBase / TaskCompact fields
    name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    html_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    completed: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    completed_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    modified_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Approval / scheduling
    approval_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    assignee_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Due / start dates and times
    due_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    due_on: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    start_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    start_on: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Like / heart counts (readOnly aggregates)
    liked: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    num_likes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    hearted: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    num_hearts: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    num_subtasks: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_rendered_as_separator: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    # Time tracking
    actual_time_minutes: Mapped[Optional[float]] = mapped_column(nullable=True)

    # Permalink
    permalink_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # FK to asana_workspaces
    workspace_gid: Mapped[Optional[str]] = mapped_column(
        ForeignKey("asana_workspaces.gid"), nullable=True
    )
    workspace: Mapped[Optional["AsanaWorkspace"]] = relationship(
        back_populates="tasks", foreign_keys="[AsanaTask.workspace_gid]"
    )

    # FK to asana_users (assignee — who the task is assigned to)
    assignee_gid: Mapped[Optional[str]] = mapped_column(
        ForeignKey("asana_users.gid"), nullable=True
    )
    assignee: Mapped[Optional["AsanaUser"]] = relationship(
        back_populates="assigned_tasks", foreign_keys="[AsanaTask.assignee_gid]"
    )

    # FK to asana_sections (assignee_section — section in the assignee's My Tasks)
    assignee_section_gid: Mapped[Optional[str]] = mapped_column(
        ForeignKey("asana_sections.gid"), nullable=True
    )
    assignee_section: Mapped[Optional["AsanaSection"]] = relationship(
        back_populates="assignee_section_tasks", foreign_keys="[AsanaTask.assignee_section_gid]"
    )

    # FK to asana_users (assigned_by — user who performed the assignment)
    assigned_by_gid: Mapped[Optional[str]] = mapped_column(
        ForeignKey("asana_users.gid"), nullable=True
    )
    assigned_by: Mapped[Optional["AsanaUser"]] = relationship(
        back_populates="assigned_by_tasks", foreign_keys="[AsanaTask.assigned_by_gid]"
    )

    # FK to asana_users (completed_by — user who marked the task complete)
    completed_by_gid: Mapped[Optional[str]] = mapped_column(
        ForeignKey("asana_users.gid"), nullable=True
    )
    completed_by: Mapped[Optional["AsanaUser"]] = relationship(
        back_populates="completed_tasks", foreign_keys="[AsanaTask.completed_by_gid]"
    )

    # FK to asana_users (created_by — user who created the task)
    created_by_gid: Mapped[Optional[str]] = mapped_column(
        ForeignKey("asana_users.gid"), nullable=True
    )
    created_by: Mapped[Optional["AsanaUser"]] = relationship(
        back_populates="created_tasks", foreign_keys="[AsanaTask.created_by_gid]"
    )

    # Self-referential FK: a task may have a parent task (subtasks)
    parent_gid: Mapped[Optional[str]] = mapped_column(
        ForeignKey("asana_tasks.gid"), nullable=True
    )
    parent: Mapped[Optional["AsanaTask"]] = relationship(
        remote_side="AsanaTask.gid",
        back_populates="subtasks",
        foreign_keys="[AsanaTask.parent_gid]",
    )
    subtasks: Mapped[list["AsanaTask"]] = relationship(
        back_populates="parent",
        foreign_keys="[AsanaTask.parent_gid]",
    )

    # custom_type / custom_type_status_option kept as plain strings — not implemented resources
    custom_type_gid: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    custom_type_status_option_gid: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Nested object / array fields stored as JSONB
    external: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    likes: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    hearts: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    memberships: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    dependencies: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    dependents: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    custom_fields: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    # projects and followers stored as JSONB arrays of compact objects.
    # tags is a proper M:N via asana_task_tags (see relationship below).
    projects: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    followers: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)

    # M:N to asana_tags via asana_task_tags
    tags: Mapped[list["AsanaTag"]] = relationship(
        secondary=asana_task_tags, back_populates="tasks"
    )

    # Soft-delete support
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)

    # Back-references from AsanaStory (multiple FK roles pointing at tasks)
    stories: Mapped[list["AsanaStory"]] = relationship(
        back_populates="task", foreign_keys="AsanaStory.task_gid"
    )
    duplicate_of_stories: Mapped[list["AsanaStory"]] = relationship(
        back_populates="duplicate_of", foreign_keys="AsanaStory.duplicate_of_gid"
    )
    duplicated_from_stories: Mapped[list["AsanaStory"]] = relationship(
        back_populates="duplicated_from", foreign_keys="AsanaStory.duplicated_from_gid"
    )
    dependency_stories: Mapped[list["AsanaStory"]] = relationship(
        back_populates="dependency", foreign_keys="AsanaStory.dependency_gid"
    )
    target_stories: Mapped[list["AsanaStory"]] = relationship(
        back_populates="target", foreign_keys="AsanaStory.target_gid"
    )


class AsanaStory(Base):
    __tablename__ = "asana_stories"
    __table_args__ = (
        Index("ix_asana_stories_task", "task_gid"),
        Index("ix_asana_stories_created_by", "created_by_gid"),
        Index("ix_asana_stories_assignee", "assignee_gid"),
        Index("ix_asana_stories_follower", "follower_gid"),
        Index("ix_asana_stories_old_section", "old_section_gid"),
        Index("ix_asana_stories_new_section", "new_section_gid"),
        Index("ix_asana_stories_project", "project_gid"),
        Index("ix_asana_stories_duplicate_of", "duplicate_of_gid"),
        Index("ix_asana_stories_duplicated_from", "duplicated_from_gid"),
        Index("ix_asana_stories_dependency", "dependency_gid"),
        Index("ix_asana_stories_target", "target_gid"),
        Index("ix_asana_stories_parent_story", "parent_story_gid"),
    )

    # Primary key — Asana GIDs are opaque numeric strings (e.g. "12345")
    gid: Mapped[str] = mapped_column(String(50), primary_key=True)
    resource_type: Mapped[str] = mapped_column(String(50), default="story")

    # StoryBase / StoryCompact fields
    created_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    resource_subtype: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    html_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_pinned: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    sticker_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # StoryResponse-only scalar fields
    story_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # "type" is reserved
    is_editable: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    is_edited: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    hearted: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    num_hearts: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    liked: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    num_likes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    old_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    new_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    old_resource_subtype: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    new_resource_subtype: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    old_text_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    new_text_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    old_number_value: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    new_number_value: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    new_approval_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    old_approval_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Nested object / array fields stored as JSONB
    hearts: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    likes: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    reaction_summary: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    previews: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    old_dates: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    new_dates: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    old_date_value: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    new_date_value: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    old_enum_value: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    new_enum_value: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    old_multi_enum_values: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    new_multi_enum_values: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    old_people_value: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    new_people_value: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)

    # FK to asana_tasks (the task this story is on)
    task_gid: Mapped[Optional[str]] = mapped_column(
        ForeignKey("asana_tasks.gid"), nullable=True
    )
    task: Mapped[Optional["AsanaTask"]] = relationship(
        back_populates="stories", foreign_keys=[task_gid]
    )

    # FK to asana_users (created_by)
    created_by_gid: Mapped[Optional[str]] = mapped_column(
        ForeignKey("asana_users.gid"), nullable=True
    )
    created_by: Mapped[Optional["AsanaUser"]] = relationship(
        back_populates="created_stories", foreign_keys=[created_by_gid]
    )

    # FK to asana_users (assignee — user whose assignment changed)
    assignee_gid: Mapped[Optional[str]] = mapped_column(
        ForeignKey("asana_users.gid"), nullable=True
    )
    assignee: Mapped[Optional["AsanaUser"]] = relationship(
        back_populates="assignee_stories", foreign_keys=[assignee_gid]
    )

    # FK to asana_users (follower — user added/removed as follower)
    follower_gid: Mapped[Optional[str]] = mapped_column(
        ForeignKey("asana_users.gid"), nullable=True
    )
    follower: Mapped[Optional["AsanaUser"]] = relationship(
        back_populates="follower_stories", foreign_keys=[follower_gid]
    )

    # FK to asana_sections (old_section and new_section for section-change stories)
    old_section_gid: Mapped[Optional[str]] = mapped_column(
        ForeignKey("asana_sections.gid"), nullable=True
    )
    old_section: Mapped[Optional["AsanaSection"]] = relationship(
        back_populates="old_section_stories", foreign_keys=[old_section_gid]
    )

    new_section_gid: Mapped[Optional[str]] = mapped_column(
        ForeignKey("asana_sections.gid"), nullable=True
    )
    new_section: Mapped[Optional["AsanaSection"]] = relationship(
        back_populates="new_section_stories", foreign_keys=[new_section_gid]
    )

    # FK to asana_projects (project referenced in story)
    project_gid: Mapped[Optional[str]] = mapped_column(
        ForeignKey("asana_projects.gid"), nullable=True
    )
    project: Mapped[Optional["AsanaProject"]] = relationship(
        back_populates="stories", foreign_keys=[project_gid]
    )

    # Multiple FKs to asana_tasks for task-reference story subtypes
    duplicate_of_gid: Mapped[Optional[str]] = mapped_column(
        ForeignKey("asana_tasks.gid"), nullable=True
    )
    duplicate_of: Mapped[Optional["AsanaTask"]] = relationship(
        back_populates="duplicate_of_stories", foreign_keys=[duplicate_of_gid]
    )

    duplicated_from_gid: Mapped[Optional[str]] = mapped_column(
        ForeignKey("asana_tasks.gid"), nullable=True
    )
    duplicated_from: Mapped[Optional["AsanaTask"]] = relationship(
        back_populates="duplicated_from_stories", foreign_keys=[duplicated_from_gid]
    )

    dependency_gid: Mapped[Optional[str]] = mapped_column(
        ForeignKey("asana_tasks.gid"), nullable=True
    )
    dependency: Mapped[Optional["AsanaTask"]] = relationship(
        back_populates="dependency_stories", foreign_keys=[dependency_gid]
    )

    target_gid: Mapped[Optional[str]] = mapped_column(
        ForeignKey("asana_tasks.gid"), nullable=True
    )
    target: Mapped[Optional["AsanaTask"]] = relationship(
        back_populates="target_stories", foreign_keys=[target_gid]
    )

    # Self-referential FK: a story may reference a parent story (data.story)
    parent_story_gid: Mapped[Optional[str]] = mapped_column(
        ForeignKey("asana_stories.gid"), nullable=True
    )
    parent_story: Mapped[Optional["AsanaStory"]] = relationship(
        remote_side="AsanaStory.gid",
        back_populates="child_stories",
        foreign_keys="[AsanaStory.parent_story_gid]",
    )
    child_stories: Mapped[list["AsanaStory"]] = relationship(
        back_populates="parent_story",
        foreign_keys="[AsanaStory.parent_story_gid]",
    )

    # tag_gid and custom_field_gid kept as plain strings — those resources
    # are not part of this implementation
    tag_gid: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    custom_field_gid: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Soft-delete support
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class AsanaTag(Base):
    __tablename__ = "asana_tags"
    __table_args__ = (
        Index("ix_asana_tags_workspace", "workspace_gid"),
    )

    # Primary key — Asana GIDs are opaque numeric strings (e.g. "12345")
    gid: Mapped[str] = mapped_column(String(50), primary_key=True)
    resource_type: Mapped[str] = mapped_column(String(50), default="tag")

    # TagCompact fields
    name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # TagBase fields
    color: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # TagResponse fields
    created_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    permalink_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # FK to asana_workspaces (a tag belongs to one workspace)
    workspace_gid: Mapped[Optional[str]] = mapped_column(
        ForeignKey("asana_workspaces.gid"), nullable=True
    )
    workspace: Mapped[Optional["AsanaWorkspace"]] = relationship(back_populates="tags")

    # M:N to asana_users via association table (tag followers)
    follower_users: Mapped[list["AsanaUser"]] = relationship(
        secondary=asana_tag_followers, back_populates="follower_tags"
    )

    # M:N to asana_tasks via asana_task_tags. Hand-patched: tags' Pass 2
    # didn't surface tasks as a related resource (the per-resource
    # endpoint_filter was scrubbing incoming evidence whose source
    # subject was tasks rather than tags). The relationship is real:
    # task.tags ↔ tag.tasks.
    tasks: Mapped[list["AsanaTask"]] = relationship(
        secondary=asana_task_tags, back_populates="tags"
    )

    # Soft-delete support
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class AsanaSection(Base):
    __tablename__ = "asana_sections"
    __table_args__ = (
        Index("ix_asana_sections_project", "project_gid"),
    )

    # Primary key — Asana GIDs are opaque numeric strings (e.g. "12345")
    gid: Mapped[str] = mapped_column(String(50), primary_key=True)
    resource_type: Mapped[str] = mapped_column(String(50), default="section")
    name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # SectionResponse-only fields
    created_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # FK to asana_projects
    project_gid: Mapped[Optional[str]] = mapped_column(
        ForeignKey("asana_projects.gid"), nullable=True
    )
    project: Mapped[Optional["AsanaProject"]] = relationship(back_populates="sections")

    # Back-references from AsanaStory (two FK roles: old_section and new_section)
    old_section_stories: Mapped[list["AsanaStory"]] = relationship(
        back_populates="old_section", foreign_keys="AsanaStory.old_section_gid"
    )
    new_section_stories: Mapped[list["AsanaStory"]] = relationship(
        back_populates="new_section", foreign_keys="AsanaStory.new_section_gid"
    )

    # Back-reference from AsanaTask (tasks whose assignee_section is this section)
    assignee_section_tasks: Mapped[list["AsanaTask"]] = relationship(
        back_populates="assignee_section", foreign_keys="AsanaTask.assignee_section_gid"
    )

    # Soft-delete support
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
