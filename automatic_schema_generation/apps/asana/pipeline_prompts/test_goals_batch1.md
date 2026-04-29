# Endpoint Verification: Asana — goals (batch 1/3)

You are verifying that **7** endpoints of the `asana`
replica behave correctly when called over HTTP. The replica has already been
implemented; your job is to drive it, observe the responses, fix the
implementation when it is wrong, and report the outcome.

## How the platform is wired

The backend runs in Docker on `http://localhost:8000`. It exposes a
control-plane API at `/api/platform/*` and mounts each service replica at
`/api/env/{env_id}/services/{app_slug}`.

To call any endpoint of `asana` you first need an environment id:

```bash
# 1. List templates and pick one for this service
curl -s http://localhost:8000/api/platform/templates | jq '.templates[] | select(.service == "asana")'

# 2. Initialise an isolated runtime environment from a template.
#    impersonateUserId is required when there is no testId — pick any
#    stable string ("test-user" works) and reuse it in the request header.
curl -s -X POST http://localhost:8000/api/platform/initEnv \
  -H 'Content-Type: application/json' \
  -d '{"templateService": "asana", "templateName": "<template-name-from-step-1>", "impersonateUserId": "test-user"}'
# -> returns {"environmentId": "...", ...}
```

Then call the replica with the returned environmentId and the impersonation
header (the platform middleware requires it):

```bash
ENV_ID=<environmentId>
curl -s -H 'x-impersonate-user-id: test-user' \
  http://localhost:8000/api/env/$ENV_ID/services/asana/<endpoint-path>
```

Each endpoint test must run inside its own freshly initialised environment.
Do not reuse one environmentId across multiple endpoint tests — state leaks
between tests will cause false failures.

## How to fix bugs and re-run

If an endpoint misbehaves, edit the replica source under
`backend/src/services/asana` (typically `database/operations.py`,
`core/serializers.py`, or `api/routes.py`). The dev backend runs uvicorn
with `--reload`, so file edits take effect within ~1 second — **no restart
is needed**. If you ever do need a hard restart (rare — only for
import-time errors), run from the repo's `ops/` directory:

```bash
cd <repo>/ops && SEED=false docker compose up -d --force-recreate backend
```

`SEED=false` is critical: a normal restart re-seeds every template database
from scratch, which wipes any environment you have already initialised.

After any code edit, re-test the endpoint that triggered the fix from a
**fresh environment** (init a new env), since the previous env may hold state
from the broken behaviour.

You may not edit any file outside `backend/src/services/asana` and may not
restart postgres or run alembic migrations.

## Iteration budget

For each endpoint, you have **at most 3 fix-and-retry
iterations**. If after that many attempts the endpoint still fails, mark it
as `passed: false` with a clear `diagnosis` and move on — do not block the
batch.

## Endpoints to verify

### POST /goals
Query parameters: opt_fields: array
Request body (application/json): inline: {"type":"object","properties":{"data":{"$ref":"#/schemas/GoalRequest"}}}
Responses:
  - 201: inline: {"type":"object","properties":{"data":{"$ref":"#/schemas/GoalResponse"}}} — Successfully created a new goal.
  - 400: `#/schemas/ErrorResponse` — This usually occurs because of a missing or malformed parameter. Check the documentation and the syntax of your request and try again.
  - 401: `#/schemas/ErrorResponse` — A valid authentication token was not provided with the request, so the API could not associate a user with the request.
  - 402: `#/schemas/ErrorResponse` — The request was valid, but the queried object or object mutation specified in the request is above your current premium level.
  - 403: `#/schemas/ErrorResponse` — The authentication and request syntax was valid but the server is refusing to complete the request. This can happen if you try to read or write to objects or properties that the user does not have access to.
  - 404: `#/schemas/ErrorResponse` — Either the request method and path supplied do not specify a known action in the API, or the object specified by the request does not exist.
  - 500: `#/schemas/ErrorResponse` — There was a problem on Asana’s end. In the event of a server error the response body should contain an error phrase. These phrases can be used by Asana support to quickly look up the incident that caused the server error. Some errors are due to server load, and will not supply an error phrase.

### GET /goals
Query parameters: portfolio: string, project: string, task: string, is_workspace_level: boolean, team: string, workspace: string, time_periods: array, opt_fields: array
Responses:
  - 200: inline: {"type":"object","properties":{"data":{"type":"array","items":{"$ref":"#/schemas/GoalCompact"}},"next_page":{"$ref":"#/schemas/NextPage"}}} — Successfully retrieved the requested goals.
  - 400: `#/schemas/ErrorResponse` — This usually occurs because of a missing or malformed parameter. Check the documentation and the syntax of your request and try again.
  - 401: `#/schemas/ErrorResponse` — A valid authentication token was not provided with the request, so the API could not associate a user with the request.
  - 402: `#/schemas/ErrorResponse` — The request was valid, but the queried object or object mutation specified in the request is above your current premium level.
  - 403: `#/schemas/ErrorResponse` — The authentication and request syntax was valid but the server is refusing to complete the request. This can happen if you try to read or write to objects or properties that the user does not have access to.
  - 404: `#/schemas/ErrorResponse` — Either the request method and path supplied do not specify a known action in the API, or the object specified by the request does not exist.
  - 500: `#/schemas/ErrorResponse` — There was a problem on Asana’s end. In the event of a server error the response body should contain an error phrase. These phrases can be used by Asana support to quickly look up the incident that caused the server error. Some errors are due to server load, and will not supply an error phrase.

### POST /goals/{goal_gid}/addFollowers
Query parameters: opt_fields: array
Request body (application/json): inline: {"type":"object","properties":{"data":{"$ref":"#/schemas/TaskAddFollowersRequest"}}}
Responses:
  - 200: inline: {"type":"object","properties":{"data":{"$ref":"#/schemas/GoalResponse"}}} — Successfully added users as collaborators.
  - 400: `#/schemas/ErrorResponse` — This usually occurs because of a missing or malformed parameter. Check the documentation and the syntax of your request and try again.
  - 401: `#/schemas/ErrorResponse` — A valid authentication token was not provided with the request, so the API could not associate a user with the request.
  - 402: `#/schemas/ErrorResponse` — The request was valid, but the queried object or object mutation specified in the request is above your current premium level.
  - 403: `#/schemas/ErrorResponse` — The authentication and request syntax was valid but the server is refusing to complete the request. This can happen if you try to read or write to objects or properties that the user does not have access to.
  - 404: `#/schemas/ErrorResponse` — Either the request method and path supplied do not specify a known action in the API, or the object specified by the request does not exist.
  - 500: `#/schemas/ErrorResponse` — There was a problem on Asana’s end. In the event of a server error the response body should contain an error phrase. These phrases can be used by Asana support to quickly look up the incident that caused the server error. Some errors are due to server load, and will not supply an error phrase.

### POST /goals/{goal_gid}/removeFollowers
Query parameters: opt_fields: array
Request body (application/json): inline: {"type":"object","properties":{"data":{"$ref":"#/schemas/TaskAddFollowersRequest"}}}
Responses:
  - 200: inline: {"type":"object","properties":{"data":{"$ref":"#/schemas/GoalResponse"}}} — Successfully removed users as collaborators.
  - 400: `#/schemas/ErrorResponse` — This usually occurs because of a missing or malformed parameter. Check the documentation and the syntax of your request and try again.
  - 401: `#/schemas/ErrorResponse` — A valid authentication token was not provided with the request, so the API could not associate a user with the request.
  - 402: `#/schemas/ErrorResponse` — The request was valid, but the queried object or object mutation specified in the request is above your current premium level.
  - 403: `#/schemas/ErrorResponse` — The authentication and request syntax was valid but the server is refusing to complete the request. This can happen if you try to read or write to objects or properties that the user does not have access to.
  - 404: `#/schemas/ErrorResponse` — Either the request method and path supplied do not specify a known action in the API, or the object specified by the request does not exist.
  - 500: `#/schemas/ErrorResponse` — There was a problem on Asana’s end. In the event of a server error the response body should contain an error phrase. These phrases can be used by Asana support to quickly look up the incident that caused the server error. Some errors are due to server load, and will not supply an error phrase.

### GET /goals/{goal_gid}/parentGoals
Needs a seeded row before this endpoint can be exercised.
Query parameters: opt_fields: array
Responses:
  - 200: inline: {"type":"object","properties":{"data":{"type":"array","items":{"$ref":"#/schemas/GoalCompact"}}}} — Successfully retrieved the specified goal's parent goals.
  - 400: `#/schemas/ErrorResponse` — This usually occurs because of a missing or malformed parameter. Check the documentation and the syntax of your request and try again.
  - 401: `#/schemas/ErrorResponse` — A valid authentication token was not provided with the request, so the API could not associate a user with the request.
  - 402: `#/schemas/ErrorResponse` — The request was valid, but the queried object or object mutation specified in the request is above your current premium level.
  - 403: `#/schemas/ErrorResponse` — The authentication and request syntax was valid but the server is refusing to complete the request. This can happen if you try to read or write to objects or properties that the user does not have access to.
  - 404: `#/schemas/ErrorResponse` — Either the request method and path supplied do not specify a known action in the API, or the object specified by the request does not exist.
  - 500: `#/schemas/ErrorResponse` — There was a problem on Asana’s end. In the event of a server error the response body should contain an error phrase. These phrases can be used by Asana support to quickly look up the incident that caused the server error. Some errors are due to server load, and will not supply an error phrase.

### POST /goals/{goal_gid}/addSupportingRelationship
Query parameters: opt_fields: array
Request body (application/json): inline: {"type":"object","properties":{"data":{"$ref":"#/schemas/GoalAddSupportingRelationshipRequest"}}}
Responses:
  - 200: inline: {"type":"object","properties":{"data":{"$ref":"#/schemas/GoalRelationshipResponse"}}} — Successfully created the goal relationship.
  - 400: `#/schemas/ErrorResponse` — This usually occurs because of a missing or malformed parameter. Check the documentation and the syntax of your request and try again.
  - 401: `#/schemas/ErrorResponse` — A valid authentication token was not provided with the request, so the API could not associate a user with the request.
  - 403: `#/schemas/ErrorResponse` — The authentication and request syntax was valid but the server is refusing to complete the request. This can happen if you try to read or write to objects or properties that the user does not have access to.
  - 404: `#/schemas/ErrorResponse` — Either the request method and path supplied do not specify a known action in the API, or the object specified by the request does not exist.
  - 500: `#/schemas/ErrorResponse` — There was a problem on Asana’s end. In the event of a server error the response body should contain an error phrase. These phrases can be used by Asana support to quickly look up the incident that caused the server error. Some errors are due to server load, and will not supply an error phrase.

### POST /goals/{goal_gid}/removeSupportingRelationship
Request body (application/json): inline: {"type":"object","properties":{"data":{"$ref":"#/schemas/GoalRemoveSupportingRelationshipRequest"}}}
Responses:
  - 200: inline: {"type":"object","properties":{"data":{"$ref":"#/schemas/EmptyResponse"}}} — Successfully removed the goal relationship.
  - 400: `#/schemas/ErrorResponse` — This usually occurs because of a missing or malformed parameter. Check the documentation and the syntax of your request and try again.
  - 401: `#/schemas/ErrorResponse` — A valid authentication token was not provided with the request, so the API could not associate a user with the request.
  - 403: `#/schemas/ErrorResponse` — The authentication and request syntax was valid but the server is refusing to complete the request. This can happen if you try to read or write to objects or properties that the user does not have access to.
  - 404: `#/schemas/ErrorResponse` — Either the request method and path supplied do not specify a known action in the API, or the object specified by the request does not exist.
  - 500: `#/schemas/ErrorResponse` — There was a problem on Asana’s end. In the event of a server error the response body should contain an error phrase. These phrases can be used by Asana support to quickly look up the incident that caused the server error. Some errors are due to server load, and will not supply an error phrase.


## Schema definitions referenced above

```json
{
  "AsanaNamedResource": {
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
      "name": {
        "description": "The name of the object.",
        "type": "string",
        "example": "Bug Task"
      }
    }
  },
  "CustomFieldBase": {
    "allOf": [
      {
        "$ref": "#/schemas/CustomFieldCompact"
      },
      {
        "type": "object",
        "properties": {
          "description": {
            "description": "[Opt In](/docs/inputoutput-options). The description of the custom field.",
            "type": "string",
            "example": "Development team priority"
          },
          "enum_options": {
            "description": "*Conditional*. Only relevant for custom fields of type `enum` or `multi_enum`. This array specifies the possible values which an `enum` custom field can adopt. To modify the enum options, refer to [working with enum options](/reference/createenumoptionforcustomfield).",
            "type": "array",
            "items": {
              "$ref": "#/schemas/EnumOption"
            }
          },
          "precision": {
            "description": "Only relevant for custom fields of type `Number`. This field dictates the number of places after the decimal to round to, i.e. 0 is integer values, 1 rounds to the nearest tenth, and so on. Must be between 0 and 6, inclusive.\nFor percentage format, this may be unintuitive, as a value of 0.25 has a precision of 0, while a value of 0.251 has a precision of 1. This is due to 0.25 being displayed as 25%.\nThe identifier format will always have a precision of 0.",
            "type": "integer",
            "example": 2
          },
          "format": {
            "description": "The format of this custom field.",
            "type": "string",
            "enum": [
              "currency",
              "identifier",
              "percentage",
              "custom",
              "duration",
              "none"
            ],
            "example": "custom"
          },
          "currency_code": {
            "description": "ISO 4217 currency code to format this custom field. This will be null if the `format` is not `currency`.",
            "type": "string",
            "nullable": true,
            "example": "EUR"
          },
          "custom_label": {
            "description": "This is the string that appears next to the custom field value. This will be null if the `format` is not `custom`.",
            "type": "string",
            "nullable": true,
            "example": "gold pieces"
          },
          "custom_label_position": {
            "description": "Only relevant for custom fields with `custom` format. This depicts where to place the custom label. This will be null if the `format` is not `custom`.",
            "type": "string",
            "nullable": true,
            "enum": [
              "prefix",
              "suffix",
              null
            ],
            "example": "suffix"
          },
          "is_global_to_workspace": {
            "description": "This flag describes whether this custom field is available to every container in the workspace. Before project-specific custom fields, this field was always true.",
            "type": "boolean",
            "example": true,
            "readOnly": true
          },
          "has_notifications_enabled": {
            "description": "*Conditional*. This flag describes whether a follower of a task with this field should receive inbox notifications from changes to this field.",
            "type": "boolean",
            "example": true
          },
          "asana_created_field": {
            "description": "*Conditional*. A unique identifier to associate this field with the template source of truth.",
            "type": "string",
            "readOnly": true,
            "nullable": true,
            "enum": [
              "a_v_requirements",
              "account_name",
              "actionable",
              "align_shipping_link",
              "align_status",
              "allotted_time",
              "appointment",
              "approval_stage",
              "approved",
              "article_series",
              "board_committee",
              "browser",
              "campaign_audience",
              "campaign_project_status",
              "campaign_regions",
              "channel_primary",
              "client_topic_type",
              "complete_by",
              "contact",
              "contact_email_address",
              "content_channels",
              "content_channels_needed",
              "content_stage",
              "content_type",
              "contract",
              "contract_status",
              "cost",
              "creation_stage",
              "creative_channel",
              "creative_needed",
              "creative_needs",
              "data_sensitivity",
              "deal_size",
              "delivery_appt",
              "delivery_appt_date",
              "department",
              "department_responsible",
              "design_request_needed",
              "design_request_type",
              "discussion_category",
              "do_this_task",
              "editorial_content_status",
              "editorial_content_tag",
              "editorial_content_type",
              "effort",
              "effort_level",
              "est_completion_date",
              "estimated_time",
              "estimated_value",
              "expected_cost",
              "external_steps_needed",
              "favorite_idea",
              "feedback_type",
              "financial",
              "funding_amount",
              "grant_application_process",
              "hiring_candidate_status",
              "idea_status",
              "ids_link",
              "ids_patient_link",
              "implementation_stage",
              "insurance",
              "interview_area",
              "interview_question_score",
              "itero_scan_link",
              "job_s_applied_to",
              "lab",
              "launch_status",
              "lead_status",
              "localization_language",
              "localization_market_team",
              "localization_status",
              "meeting_minutes",
              "meeting_needed",
              "minutes",
              "mrr",
              "must_localize",
              "name_of_foundation",
              "need_to_follow_up",
              "next_appointment",
              "next_steps_sales",
              "num_people",
              "number_of_user_reports",
              "office_location",
              "onboarding_activity",
              "owner",
              "participants_needed",
              "patient_date_of_birth",
              "patient_email",
              "patient_phone",
              "patient_status",
              "phone_number",
              "planning_category",
              "point_of_contact",
              "position",
              "post_format",
              "prescription",
              "priority",
              "priority_level",
              "product",
              "product_stage",
              "progress",
              "project_size",
              "project_status",
              "proposed_budget",
              "publish_status",
              "reason_for_scan",
              "referral",
              "request_type",
              "research_status",
              "responsible_department",
              "responsible_team",
              "risk_assessment_status",
              "room_name",
              "sales_counterpart",
              "sentiment",
              "shipping_link",
              "social_channels",
              "stage",
              "status",
              "status_design",
              "status_of_initiative",
              "system_setup",
              "task_progress",
              "team",
              "team_marketing",
              "team_responsible",
              "time_it_takes_to_complete_tasks",
              "timeframe",
              "treatment_type",
              "type_work_requests_it",
              "use_agency",
              "user_name",
              "vendor_category",
              "vendor_type",
              "word_count",
              null
            ],
            "example": "priority"
          }
        }
      }
    ]
  },
  "CustomFieldCompact": {
    "description": "Custom Fields store the metadata that is used in order to add user-specified information to tasks in Asana. Be sure to reference the [custom fields](/reference/custom-fields) developer documentation for more information about how custom fields relate to various resources in Asana.\n\nUsers in Asana can [lock custom fields](https://asana.com/guide/help/premium/custom-fields#gl-lock-fields), which will make them read-only when accessed by other users. Attempting to edit a locked custom field will return HTTP error code `403 Forbidden`.",
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
        "example": "custom_field",
        "x-insert-after": "gid"
      },
      "name": {
        "description": "The name of the custom field.",
        "type": "string",
        "example": "Status"
      },
      "type": {
        "description": "*Deprecated: new integrations should prefer the resource_subtype field.* The type of the custom field. Must be one of the given values.\n",
        "type": "string",
        "readOnly": true,
        "enum": [
          "text",
          "enum",
          "multi_enum",
          "number",
          "date",
          "people"
        ]
      },
      "enum_options": {
        "description": "*Conditional*. Only relevant for custom fields of type `enum` or `multi_enum`. This array specifies the possible values which an `enum` custom field can adopt. To modify the enum options, refer to [working with enum options](/reference/createenumoptionforcustomfield).",
        "type": "array",
        "items": {
          "$ref": "#/schemas/EnumOption"
        }
      },
      "enabled": {
        "description": "*Conditional*. This field applies only to [custom field values](/docs/custom-fields-guide#/accessing-custom-field-values-on-tasks-or-projects) and is not available for [custom field definitions](/docs/custom-fields-guide#/accessing-custom-field-definitions).\nDetermines if the custom field is enabled or not. For more details, see the [Custom Fields documentation](/docs/custom-fields-guide#/enabled-and-disabled-values).",
        "type": "boolean",
        "readOnly": true,
        "example": true
      },
      "representation_type": {
        "description": "This field tells the type of the custom field.",
        "type": "string",
        "example": "number",
        "readOnly": true,
        "enum": [
          "text",
          "enum",
          "multi_enum",
          "number",
          "date",
          "people",
          "formula",
          "custom_id"
        ]
      },
      "id_prefix": {
        "description": "This field is the unique custom ID string for the custom field.",
        "type": "string",
        "nullable": true,
        "example": "ID"
      },
      "input_restrictions": {
        "description": "*Conditional*. Only relevant for custom fields of type `reference`. This array of strings reflects the allowed types of objects that can be written to a `reference` custom field value.",
        "type": "array",
        "items": {
          "type": "string"
        },
        "example": "task"
      },
      "is_formula_field": {
        "description": "*Conditional*. This flag describes whether a custom field is a formula custom field.",
        "type": "boolean",
        "example": false
      },
      "date_value": {
        "description": "*Conditional*. Only relevant for custom fields of type `date`. This object reflects the chosen date (and optionally, time) value of a `date` custom field. If no date is selected, the value of `date_value` will be `null`.",
        "type": "object",
        "nullable": true,
        "properties": {
          "date": {
            "type": "string",
            "description": "A string representing the date in YYYY-MM-DD format.",
            "example": "2024-08-23"
          },
          "date_time": {
            "type": "string",
            "description": "A string representing the date in ISO 8601 format. If no time value is selected, the value of `date-time` will be `null`.",
            "example": "2024-08-23T22:00:00.000Z"
          }
        }
      },
      "enum_value": {
        "allOf": [
          {
            "$ref": "#/schemas/EnumOption"
          },
          {
            "type": "object",
            "nullable": true,
            "description": "*Conditional*. Only relevant for custom fields of type `enum`. This object is the chosen value of an `enum` custom field."
          }
        ]
      },
      "multi_enum_values": {
        "description": "*Conditional*. Only relevant for custom fields of type `multi_enum`. This object is the chosen values of a `multi_enum` custom field.",
        "type": "array",
        "items": {
          "$ref": "#/schemas/EnumOption"
        }
      },
      "number_value": {
        "description": "*Conditional*. This number is the value of a `number` custom field.",
        "type": "number",
        "nullable": true,
        "example": 5.2
      },
      "text_value": {
        "description": "*Conditional*. This string is the value of a `text` custom field.",
        "type": "string",
        "nullable": true,
        "example": "Some Value"
      },
      "display_value": {
        "description": "A string representation for the value of the custom field. Integrations that don't require the underlying type should use this field to read values. Using this field will future-proof an app against new custom field types.",
        "type": "string",
        "readOnly": true,
        "example": "blue",
        "nullable": true
      }
    }
  },
  "CustomFieldResponse": {
    "allOf": [
      {
        "$ref": "#/schemas/CustomFieldBase"
      },
      {
        "type": "object",
        "properties": {
          "representation_type": {
            "description": "This field tells the type of the custom field.",
            "type": "string",
            "example": "number",
            "readOnly": true,
            "enum": [
              "text",
              "enum",
              "multi_enum",
              "number",
              "date",
              "people",
              "formula",
              "custom_id",
              "reference"
            ]
          },
          "id_prefix": {
            "description": "This field is the unique custom ID string for the custom field.",
            "type": "string",
            "nullable": true,
            "example": "ID"
          },
          "input_restrictions": {
            "description": "*Conditional*. Only relevant for custom fields of type `reference`. This array of strings reflects the allowed types of objects that can be written to a `reference` custom field value.",
            "type": "array",
            "items": {
              "type": "string"
            },
            "example": "task"
          },
          "is_formula_field": {
            "description": "*Conditional*. This flag describes whether a custom field is a formula custom field.",
            "type": "boolean",
            "example": false
          },
          "is_value_read_only": {
            "description": "*Conditional*. This flag describes whether a custom field is read only.",
            "type": "boolean",
            "example": false
          },
          "created_by": {
            "allOf": [
              {
                "$ref": "#/schemas/UserCompact"
              },
              {
                "nullable": true
              }
            ]
          },
          "people_value": {
            "description": "*Conditional*. Only relevant for custom fields of type `people`. This array of [compact user](/reference/users) objects reflects the values of a `people` custom field.",
            "type": "array",
            "items": {
              "$ref": "#/schemas/UserCompact"
            }
          },
          "reference_value": {
            "description": "*Conditional*. Only relevant for custom fields of type `reference`. This array of objects reflects the values of a `reference` custom field.",
            "type": "array",
            "items": {
              "$ref": "#/schemas/AsanaNamedResource"
            }
          },
          "privacy_setting": {
            "description": "The privacy setting of the custom field. *Note: Administrators in your organization may restrict the values of `privacy_setting`.*",
            "type": "string",
            "enum": [
              "public_with_guests",
              "public",
              "private"
            ],
            "example": "public_with_guests"
          },
          "default_access_level": {
            "description": "The default access level when inviting new members to the custom field. This isn't applied when the `privacy_setting` is `private`, or the user is a guest. For local fields in a project or portfolio, the user must additionally have permission to modify the container itself.",
            "type": "string",
            "enum": [
              "admin",
              "editor",
              "user"
            ],
            "example": "user"
          },
          "resource_subtype": {
            "description": "The type of the custom field. Must be one of the given values.\n",
            "type": "string",
            "readOnly": true,
            "example": "text",
            "enum": [
              "text",
              "enum",
              "multi_enum",
              "number",
              "date",
              "people",
              "reference"
            ]
          }
        }
      }
    ]
  },
  "CustomFieldSettingBase": {
    "$ref": "#/schemas/CustomFieldSettingCompact"
  },
  "CustomFieldSettingCompact": {
    "description": "Custom Fields Settings objects represent the many-to-many join of the Custom Field and Project as well as stores information that is relevant to that particular pairing.",
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
        "example": "custom_field_setting",
        "x-insert-after": "gid"
      }
    }
  },
  "CustomFieldSettingResponse": {
    "allOf": [
      {
        "$ref": "#/schemas/CustomFieldSettingBase"
      },
      {
        "type": "object",
        "properties": {
          "project": {
            "allOf": [
              {
                "$ref": "#/schemas/ProjectCompact"
              },
              {
                "type": "object",
                "description": "*Deprecated: new integrations should prefer the `parent` field.* The id of the project that this custom field settings refers to.",
                "readOnly": true
              }
            ]
          },
          "is_important": {
            "description": "`is_important` is used in the Asana web application to determine if this custom field is displayed in the list/grid view of a project or portfolio.",
            "type": "boolean",
            "readOnly": true,
            "example": false
          },
          "parent": {
            "allOf": [
              {
                "$ref": "#/schemas/ProjectCompact"
              },
              {
                "type": "object",
                "description": "The parent to which the custom field is applied. This can be a project or portfolio and indicates that the tasks or projects that the parent contains may be given custom field values for this custom field.",
                "readOnly": true
              }
            ]
          },
          "custom_field": {
            "allOf": [
              {
                "$ref": "#/schemas/CustomFieldResponse"
              },
              {
                "type": "object",
                "description": "The custom field that is applied to the `parent`.",
                "readOnly": true
              }
            ]
          }
        }
      }
    ]
  },
  "EmptyResponse": {
    "type": "object",
    "description": "An empty object. Some endpoints do not return an object on success. The success is conveyed through a 2-- status code and returning an empty object."
  },
  "EnumOption": {
    "description": "Enum options are the possible values which an enum custom field can adopt. An enum custom field must contain at least 1 enum option but no more than 500.\n\nYou can add enum options to a custom field by using the `POST /custom_fields/custom_field_gid/enum_options` endpoint.\n\n**It is not possible to remove or delete an enum option**. Instead, enum options can be disabled by updating the `enabled` field to false with the `PUT /enum_options/enum_option_gid` endpoint. Other attributes can be updated similarly.\n\nOn creation of an enum option, `enabled` is always set to `true`, meaning the enum option is a selectable value for the custom field. Setting `enabled=false` is equivalent to \u201ctrashing\u201d the enum option in the Asana web app within the \u201cEdit Fields\u201d dialog. The enum option will no longer be selectable but, if the enum option value was previously set within a task, the task will retain the value.\n\nEnum options are an ordered list and by default new enum options are inserted at the end. Ordering in relation to existing enum options can be specified on creation by using `insert_before` or `insert_after` to reference an existing enum option. Only one of `insert_before` and `insert_after` can be provided when creating a new enum option.\n\nAn enum options list can be reordered with the `POST /custom_fields/custom_field_gid/enum_options/insert` endpoint.",
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
        "example": "enum_option",
        "x-insert-after": "gid"
      },
      "name": {
        "description": "The name of the enum option.",
        "type": "string",
        "example": "Low"
      },
      "enabled": {
        "description": "Whether or not the enum option is a selectable value for the custom field.",
        "type": "boolean",
        "example": true
      },
      "color": {
        "description": "The color of the enum option. Defaults to `none`.",
        "type": "string",
        "example": "blue"
      }
    }
  },
  "Error": {
    "type": "object",
    "properties": {
      "message": {
        "type": "string",
        "readOnly": true,
        "description": "Message providing more detail about the error that occurred, if available.",
        "example": "project: Missing input"
      },
      "help": {
        "type": "string",
        "readOnly": true,
        "description": "Additional information directing developers to resources on how to address and fix the problem, if available.",
        "example": "For more information on API status codes and how to handle them, read the docs on errors: https://asana.github.io/developer-docs/#errors'"
      },
      "phrase": {
        "type": "string",
        "readOnly": true,
        "description": "*500 errors only*. A unique error phrase which can be used when contacting developer support to help identify the exact occurrence of the problem in Asana's logs.",
        "example": "6 sad squid snuggle softly"
      }
    }
  },
  "ErrorResponse": {
    "description": "Sadly, sometimes requests to the API are not successful. Failures can\noccur for a wide range of reasons. In all cases, the API should return\nan HTTP Status Code that indicates the nature of the failure,\nwith a response body in JSON format containing additional information.\n\n\nIn the event of a server error the response body will contain an error\nphrase. These phrases are automatically generated using the\n[node-asana-phrase\nlibrary](https://github.com/Asana/node-asana-phrase) and can be used by\nAsana support to quickly look up the incident that caused the server\nerror.",
    "type": "object",
    "properties": {
      "errors": {
        "type": "array",
        "items": {
          "$ref": "#/schemas/Error"
        }
      }
    }
  },
  "GoalAddSupportingRelationshipRequest": {
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
  },
  "GoalBase": {
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
  },
  "GoalCompact": {
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
      "owner": {
        "allOf": [
          {
            "$ref": "#/schemas/UserCompact"
          },
          {
            "type": "object",
            "nullable": true
          }
        ]
      }
    }
  },
  "GoalMetricBase": {
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
      "resource_subtype": {
        "description": "The subtype of this resource. Different subtypes retain many of the same fields and behavior, but may render differently in Asana or represent resources with different semantic meaning.",
        "type": "string",
        "readOnly": true,
        "example": "number",
        "enum": [
          "number"
        ]
      },
      "precision": {
        "description": "*Conditional*. Only relevant for goal metrics of type `Number`. This field dictates the number of places after the decimal to round to, i.e. 0 is integer values, 1 rounds to the nearest tenth, and so on. Must be between 0 and 6, inclusive.\nFor percentage format, this may be unintuitive, as a value of 0.25 has a precision of 0, while a value of 0.251 has a precision of 1. This is due to 0.25 being displayed as 25%.",
        "type": "integer",
        "example": 2
      },
      "unit": {
        "description": "A supported unit of measure for the goal metric, or none.",
        "type": "string",
        "enum": [
          "none",
          "currency",
          "percentage"
        ]
      },
      "currency_code": {
        "description": "ISO 4217 currency code to format this custom field. This will be null if the `unit` is not `currency`.",
        "type": "string",
        "nullable": true,
        "example": "EUR"
      },
      "initial_number_value": {
        "description": "This number is the start value of a goal metric of type number.",
        "type": "number",
        "example": 5.2
      },
      "target_number_value": {
        "description": "This number is the end value of a goal metric of type number. This number cannot equal `initial_number_value`.",
        "type": "number",
        "example": 10.2
      },
      "current_number_value": {
        "description": "This number is the current value of a goal metric of type number.",
        "type": "number",
        "example": 8.12
      },
      "current_display_value": {
        "description": "This string is the current value of a goal metric of type string.",
        "type": "string",
        "readOnly": true,
        "example": "8.12"
      },
      "progress_source": {
        "description": "This field defines how the progress value of a goal metric is being calculated. A goal's progress can be provided manually by the user, calculated automatically from contributing subgoals, projects, or tasks, or managed by an integration with an external data source, such as Salesforce.",
        "type": "string",
        "enum": [
          "manual",
          "subgoal_progress",
          "project_task_completion",
          "project_milestone_completion",
          "task_completion",
          "external"
        ],
        "example": "manual"
      },
      "is_custom_weight": {
        "description": "*Conditional*. Only relevant if `metric.progress_source` is one of `subgoal_progress`, `project_task_completion`, `project_milestone_completion`, or `task_completion`. If true, we use the supporting object's custom weight to calculate the goal's progress. If false, we treat all supporting objects as equally weighted",
        "type": "boolean",
        "example": false
      }
    }
  },
  "GoalRelationshipBase": {
    "allOf": [
      {
        "$ref": "#/schemas/GoalRelationshipCompact"
      },
      {
        "type": "object",
        "properties": {
          "supported_goal": {
            "allOf": [
              {
                "$ref": "#/schemas/GoalCompact"
              },
              {
                "type": "object",
                "readOnly": true,
                "description": "The goal that the supporting resource supports."
              }
            ]
          }
        }
      }
    ]
  },
  "GoalRelationshipCompact": {
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
            "$ref": "#/schemas/ProjectCompact"
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
  },
  "GoalRelationshipResponse": {
    "allOf": [
      {
        "$ref": "#/schemas/GoalRelationshipBase"
      },
      {
        "type": "object"
      }
    ]
  },
  "GoalRemoveSupportingRelationshipRequest": {
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
  },
  "GoalRequest": {
    "allOf": [
      {
        "$ref": "#/schemas/GoalRequestBase"
      },
      {
        "type": "object",
        "properties": {
          "followers": {
            "type": "array",
            "items": {
              "type": "string",
              "description": "The `gid` of a user."
            },
            "example": [
              "12345"
            ]
          }
        }
      }
    ]
  },
  "GoalRequestBase": {
    "allOf": [
      {
        "$ref": "#/schemas/GoalBase"
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
  },
  "GoalResponse": {
    "allOf": [
      {
        "$ref": "#/schemas/GoalBase"
      },
      {
        "type": "object",
        "properties": {
          "likes": {
            "description": "Array of likes for users who have liked this goal.",
            "type": "array",
            "items": {
              "$ref": "#/schemas/Like"
            },
            "readOnly": true
          },
          "num_likes": {
            "description": "The number of users who have liked this goal.",
            "type": "integer",
            "readOnly": true,
            "example": 5
          },
          "team": {
            "allOf": [
              {
                "$ref": "#/schemas/TeamCompact"
              },
              {
                "type": "object",
                "nullable": true,
                "description": "*Conditional*. This property is only present when the `workspace` provided is an organization."
              }
            ]
          },
          "workspace": {
            "allOf": [
              {
                "$ref": "#/schemas/WorkspaceCompact"
              },
              {
                "type": "object"
              }
            ]
          },
          "followers": {
            "type": "array",
            "items": {
              "$ref": "#/schemas/UserCompact"
            },
            "description": "Array of users who are members of this goal."
          },
          "time_period": {
            "allOf": [
              {
                "$ref": "#/schemas/TimePeriodCompact"
              },
              {
                "type": "object",
                "nullable": true
              }
            ]
          },
          "metric": {
            "allOf": [
              {
                "$ref": "#/schemas/GoalMetricBase"
              },
              {
                "type": "object",
                "nullable": true,
                "properties": {
                  "can_manage": {
                    "description": "*Conditional*. Only relevant for `progress_source` of type `external`. This boolean indicates whether the requester has the ability to update the current value of this metric. This returns `true` if the external metric was created by the requester, `false` otherwise.",
                    "type": "boolean",
                    "readOnly": true,
                    "example": true
                  }
                }
              }
            ]
          },
          "owner": {
            "allOf": [
              {
                "$ref": "#/schemas/UserCompact"
              },
              {
                "type": "object",
                "nullable": true
              }
            ]
          },
          "current_status_update": {
            "allOf": [
              {
                "$ref": "#/schemas/StatusUpdateCompact"
              },
              {
                "description": "The latest `status_update` posted to this goal.",
                "nullable": true
              }
            ]
          },
          "status": {
            "type": "string",
            "readOnly": true,
            "description": "The current status of this goal. When the goal is open, its status can be `green`, `yellow`, and `red` to reflect \"On Track\", \"At Risk\", and \"Off Track\", respectively. When the goal is closed, the value can be `missed`, `achieved`, `partial`, or `dropped`.\n*Note* you can only write to this property if `metric` is set.",
            "example": "green",
            "nullable": true
          },
          "privacy_setting": {
            "type": "string",
            "description": "The privacy setting of the goal.",
            "enum": [
              "public_to_workspace",
              "members_only"
            ],
            "example": "public_to_workspace"
          },
          "default_access_level": {
            "type": "string",
            "description": "The default access level when inviting new members to the goal",
            "enum": [
              "admin",
              "editor",
              "commenter",
              "viewer"
            ],
            "example": "editor"
          },
          "custom_fields": {
            "description": "Array of custom field values applied directly to the goal itself. These represent the values set on the goal, not the fields available for items in the goal.",
            "type": "array",
            "items": {
              "$ref": "#/schemas/CustomFieldCompact"
            }
          },
          "custom_field_settings": {
            "description": "Array of custom field definitions that are enabled for the goal. These represent which custom fields are available to be used on items within the goal, but do not include any values.",
            "type": "array",
            "items": {
              "$ref": "#/schemas/CustomFieldSettingResponse"
            }
          }
        }
      }
    ]
  },
  "Like": {
    "type": "object",
    "description": "An object to represent a user's like.",
    "properties": {
      "gid": {
        "description": "Globally unique identifier of the object, as a string.",
        "type": "string",
        "readOnly": true,
        "example": "12345"
      },
      "user": {
        "$ref": "#/schemas/UserCompact"
      }
    }
  },
  "NextPage": {
    "type": "object",
    "nullable": true,
    "description": "*Conditional*. This property is only present when a limit query parameter is provided in the request. When making a paginated request, the API will return a number of results as specified by the limit parameter. If more results exist, then the response will contain a next_page attribute, which will include an offset, a relative path attribute, and a full uri attribute. If there are no more pages available, next_page will be null and no offset will be provided. Note that an offset token will expire after some time, as data may have changed.",
    "properties": {
      "offset": {
        "type": "string",
        "readOnly": true,
        "description": "Pagination offset for the request.",
        "example": "eyJ0eXAiOJiKV1iQLCJhbGciOiJIUzI1NiJ9"
      },
      "path": {
        "type": "string",
        "readOnly": true,
        "description": "A relative path containing the query parameters to fetch for next_page",
        "example": "/tasks/12345/attachments?limit=2&offset=eyJ0eXAiOJiKV1iQLCJhbGciOiJIUzI1NiJ9"
      },
      "uri": {
        "type": "string",
        "format": "uri",
        "readOnly": true,
        "description": "A full uri containing the query parameters to fetch for next_page",
        "example": "https://app.asana.com/api/1.0/tasks/12345/attachments?limit=2&offset=eyJ0eXAiOJiKV1iQLCJhbGciOiJIUzI1NiJ9"
      }
    }
  },
  "ProjectCompact": {
    "description": "A *project* represents a prioritized list of tasks in Asana or a board with columns of tasks represented as cards. It exists in a single workspace or organization and is accessible to a subset of users in that workspace or organization, depending on its permissions.",
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
        "example": "project",
        "x-insert-after": "gid"
      },
      "name": {
        "description": "Name of the project. This is generally a short sentence fragment that fits on a line in the UI for maximum readability. However, it can be longer.",
        "type": "string",
        "example": "Stuff to buy"
      }
    }
  },
  "StatusUpdateCompact": {
    "description": "A *status update* is an update on the progress of a particular project, portfolio, or goal, and is sent out to all of its parent's followers when created. These updates include both text describing the update and a `status_type` intended to represent the overall state of the object.",
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
        "example": "status_update",
        "x-insert-after": "gid"
      },
      "title": {
        "description": "The title of the status update.",
        "type": "string",
        "example": "Status Update - Jun 15"
      },
      "resource_subtype": {
        "type": "string",
        "description": "The subtype of this resource. Different subtypes retain many of the same fields and behavior, but may render differently in Asana or represent resources with different semantic meaning.\nThe `resource_subtype`s for `status` objects represent the type of their parent.",
        "enum": [
          "project_status_update",
          "portfolio_status_update",
          "goal_status_update"
        ],
        "example": "project_status_update",
        "readOnly": true
      }
    }
  },
  "TaskAddFollowersRequest": {
    "type": "object",
    "properties": {
      "followers": {
        "description": "An array of strings identifying users. These can either be the string \"me\", an email, or the gid of a user.",
        "type": "array",
        "items": {
          "type": "string"
        },
        "example": [
          "13579",
          "321654"
        ]
      }
    },
    "required": [
      "followers"
    ]
  },
  "TeamCompact": {
    "description": "<p><strong style={{ color: \"#4573D2\" }}>Full object requires scope: </strong><code>teams:read</code></p>\n\nA *team* is used to group related projects and people together within an organization. Each project in an organization is associated with a team.",
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
        "example": "team",
        "x-insert-after": "gid"
      },
      "name": {
        "description": "The name of the team.",
        "type": "string",
        "example": "Marketing"
      }
    }
  },
  "TimePeriodCompact": {
    "description": "<p><strong style={{ color: \"#4573D2\" }}>Full object requires scope: </strong><code>time_periods:read</code></p>\n\nA generic Asana Resource, containing a globally unique identifier.",
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
        "example": "time_period",
        "x-insert-after": "gid"
      },
      "end_on": {
        "type": "string",
        "description": "The localized end date of the time period in `YYYY-MM-DD` format.",
        "example": "2019-09-14"
      },
      "start_on": {
        "type": "string",
        "description": "The localized start date of the time period in `YYYY-MM-DD` format.",
        "example": "2019-09-13"
      },
      "period": {
        "type": "string",
        "description": "The cadence and index of the time period.",
        "enum": [
          "FY",
          "H1",
          "H2",
          "Q1",
          "Q2",
          "Q3",
          "Q4"
        ],
        "example": "Q1"
      },
      "display_name": {
        "type": "string",
        "description": "A string representing the cadence code and the fiscal year.",
        "example": "Q1 FY22"
      }
    }
  },
  "UserCompact": {
    "description": "A *user* object represents an account in Asana that can be given access to various workspaces, projects, and tasks.",
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
        "example": "user",
        "x-insert-after": "gid"
      },
      "name": {
        "type": "string",
        "description": "*Read-only except when same user as requester*. The user's name.",
        "example": "Greg Sanchez"
      }
    }
  },
  "WorkspaceCompact": {
    "description": "A *workspace* is the highest-level organizational unit in Asana. All projects and tasks have an associated workspace.",
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
        "example": "workspace",
        "x-insert-after": "gid"
      },
      "name": {
        "description": "The name of the workspace.",
        "type": "string",
        "example": "My Company Workspace"
      }
    }
  }
}
```

## What "verified" means for each endpoint

For every endpoint:

1. **Happy path** — call it with valid input. Response status must match the
   declared 2xx code; response body must match the declared schema shape
   (correct keys, correct types, lists where lists are declared, etc.).
   Where the endpoint requires referenced rows to exist (e.g. a `project_gid`
   for a task endpoint), seed them first via the relevant `POST` endpoint.
2. **Not-found path** — for `GET`, `PUT`, `PATCH`, `DELETE` on a path with a
   `{...}` parameter, call it with a clearly fake id. Response must be a 404
   shaped like the `Asana` error envelope, not a 500.
3. **Soft-delete consistency** — if an endpoint deletes, a subsequent `GET`
   for the same id must return 404, not the deleted row.

Skip checks that do not apply (e.g. no not-found check for collection
`GET /...` endpoints with no path parameter).

## Output

When you finish the batch, write the results as JSON to:

```
automatic_schema_generation/apps/asana/pipeline_out/test_results/goals_batch1.json
```

The file must be valid JSON with this exact shape — the pipeline parses it
and merges it back into `test_registry.json`:

```json
{
  "results": [
    {
      "method": "GET",
      "path": "/tasks/{task_gid}",
      "passed": true,
      "iterations": 1,
      "diagnosis": "Returns task by gid; 404 on bogus id; soft-deleted task returns 404.",
      "curl_examples": [
        "curl -H 'x-impersonate-user-id: test-user' http://localhost:8000/api/env/$ENV/services/asana/tasks/<gid>"
      ],
      "code_changes": []
    },
    {
      "method": "POST",
      "path": "/tasks",
      "passed": false,
      "iterations": 3,
      "diagnosis": "Create returns 200 but response body omits the 'gid' field.",
      "curl_examples": ["..."],
      "code_changes": [
        {"file": "backend/src/services/asana/core/serializers.py", "summary": "Added gid to serialize_task output"}
      ]
    }
  ]
}
```

`diagnosis` should be one or two sentences describing what you observed
(pass) or what is broken and why your fix did not resolve it (fail).
`code_changes` lists every file you edited during this batch with a one-line
summary of the change. Leave it empty if you made no edits.

Write **one entry per endpoint listed above**, in the same order. Do not
omit endpoints — if you ran out of time on one, write it with `passed:
false` and an honest diagnosis.

Do not write any other files. Do not modify `test_registry.json` directly —
the pipeline will do that after parsing your JSON output.
