"""Seed hooks for the Linear seeder.

Linear's models contain unresolvable FK cycles (``users``, ``teams``,
``issues``, ``projects``, etc. mutually reference one another), so
``Base.metadata.sorted_tables`` cannot derive an FK-safe insertion
order. The generic seeder picks up ``TABLE_ORDER`` from this module
when present and uses it instead.

Discovered automatically by ``backend/utils/seed_template.py``;
the constant name and module location are part of the contract.
"""

from __future__ import annotations


# Hand-maintained insertion order. Each child table appears after every
# parent it FK-references. Any new table added to ``schema.py`` must be
# inserted at the right position here — the generic seeder cross-checks
# this list against the live metadata and refuses to run on a stale entry.
TABLE_ORDER = [
    "organizations",
    "users",
    "external_users",
    "teams",
    "workflow_states",
    "team_memberships",
    "user_settings",
    "user_flags",
    "templates",
    "projects",
    "project_labels",
    "project_milestones",
    "project_statuses",
    "cycles",
    "issue_labels",
    "issues",
    "issue_label_issue_association",
    "comments",
    "attachments",
    "reactions",
    "favorites",
    "issue_histories",
    "issue_suggestions",
    "issue_relations",
    "customer_needs",
    "documents",
    "document_contents",
    "drafts",
    "issue_drafts",
    "initiatives",
    "initiative_updates",
    "initiative_histories",
    "initiative_relations",
    "initiative_to_projects",
    "project_updates",
    "project_histories",
    "project_relations",
    "posts",
    "notifications",
    "webhooks",
    "integrations",
    "integrations_settings",
    "git_automation_states",
    "facets",
    "triage_responsibilities",
    "agent_sessions",
    "organization_invites",
    "organization_domains",
    "paid_subscriptions",
    "entity_external_links",
    "issue_imports",
]
