# Entity Implementation (Pass 1 — Base): goals

You are implementing the **goals** resource for the Asana API
replica. Build the base model, CRUD operations, serializers, and route handlers.

**Do NOT add ForeignKey columns, relationship() declarations, or association
tables in this pass.** Those will be added in a separate step. Focus only on
the resource's own columns, operations, and endpoints.

The full OpenAPI spec is available at: `/Users/azh/agent-diff/automatic_schema_generation/apps/asana/inputs/openapi.scoped.json`
If any information in this prompt is unclear or seems incorrect, read the
spec directly to resolve ambiguities.

Files to edit (all under `/Users/azh/agent-diff/backend/src/services/asana`):
- `database/schema.py`
- `database/operations.py`
- `core/serializers.py`
- `api/routes.py`

---

## Section 1: goals

### Identity

- Table name: `asana_goals`
- Model class: `AsanaGoal`
- Primary key: `gid`

### Schemas

These component schemas represent **goals** in the API. Build your
ORM model to cover the union of all fields across these schemas. Fields that
appear in only some schemas should be nullable.

```json
{
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
  "GoalMetricRequest": {
    "$ref": "#/schemas/GoalMetricBase"
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
  }
}
```

### Endpoints

Each entry below is an endpoint that operates on **goals**. Build
one operation function and one route handler per endpoint.

#### DELETE /goals/{goal_gid}
_Delete a goal_
Errors: 400, 401, 402, 403, 404, 500

#### GET /goals
_Get goals_
Parameters:
  - portfolio (query, optional): string
  - project (query, optional): string
  - task (query, optional): string
  - is_workspace_level (query, optional): boolean
  - team (query, optional): string
  - workspace (query, optional): string
  - time_periods (query, optional): array
  - limit (query, optional): integer
  - offset (query, optional): string
  - opt_fields (query, optional): array
Errors: 400, 401, 402, 403, 404, 500

#### GET /goals/{goal_gid}
_Get a goal_
Parameters:
  - opt_fields (query, optional): array
Errors: 400, 401, 402, 403, 404, 500

#### POST /goals
_Create a goal_
Parameters:
  - opt_fields (query, optional): array
Request body (application/json):
  - data: object
Errors: 400, 401, 402, 403, 404, 500

#### POST /goals/{goal_gid}/addFollowers
_Add a collaborator to a goal_
Parameters:
  - opt_fields (query, optional): array
Request body (application/json):
  - data: object
Errors: 400, 401, 402, 403, 404, 500


### Referenced Schemas

These schemas appear in the endpoints above (as response bodies or request
bodies) but are not direct representations of **goals**. They
define the shapes your serializers must produce and your operations must
accept.

```json
{
  "AddCustomFieldSettingRequest": {
    "type": "object",
    "required": [
      "custom_field"
    ],
    "properties": {
      "custom_field": {
        "oneOf": [
          {
            "type": "string",
            "description": "The custom field to associate with this container.",
            "example": "14916"
          },
          {
            "$ref": "#/schemas/CustomFieldCreateRequest"
          }
        ]
      },
      "is_important": {
        "description": "Whether this field should be considered important to this container (for instance, to display in the list view of items in the container).",
        "type": "boolean",
        "example": true
      },
      "insert_before": {
        "description": "A gid of a Custom Field Setting on this container, before which the new Custom Field Setting will be added.  `insert_before` and `insert_after` parameters cannot both be specified.",
        "type": "string",
        "example": "1331"
      },
      "insert_after": {
        "description": "A gid of a Custom Field Setting on this container, after which the new Custom Field Setting will be added.  `insert_before` and `insert_after` parameters cannot both be specified.",
        "type": "string",
        "example": "1331"
      }
    }
  },
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
  "CustomFieldCreateRequest": {
    "allOf": [
      {
        "$ref": "#/schemas/CustomFieldRequest"
      },
      {
        "type": "object",
        "required": [
          "resource_subtype"
        ],
        "properties": {
          "resource_subtype": {
            "description": "The type of the custom field. Must be one of the given values.",
            "type": "string",
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
  "CustomFieldRequest": {
    "allOf": [
      {
        "$ref": "#/schemas/CustomFieldBase"
      },
      {
        "type": "object",
        "required": [
          "workspace"
        ],
        "properties": {
          "workspace": {
            "type": "string",
            "description": "*Create-Only* The workspace to create a custom field in.",
            "example": "1331"
          },
          "owned_by_app": {
            "type": "boolean",
            "description": "*Allow-listed*. Instructs the API that this Custom Field is app-owned. This parameter is allow-listed to specific apps at this point in time. For apps that are not allow-listed, providing this parameter will result in a `403 Forbidden`."
          },
          "people_value": {
            "description": "*Conditional*. Only relevant for custom fields of type `people`. This array of user GIDs, emails, or the string \"me\", reflects the users to be written to a `people` custom field. Note that *write* operations will replace existing users (if any) in the custom field with the users specified in this array.",
            "type": "array",
            "items": {
              "type": "string",
              "description": "A string identifying a user. This can either be the string \"me\", an email, or the gid of a user."
            },
            "example": [
              "12345"
            ]
          },
          "reference_value": {
            "description": "*Conditional*. Only relevant for custom fields of type `reference`. This array of GIDs reflects the objects to be written to a `reference` custom field. Note that *write* operations will replace existing objects (if any) in the custom field with the objects specified in this array.",
            "type": "array",
            "items": {
              "type": "string",
              "description": "The GID of an object."
            },
            "example": [
              "12345"
            ]
          }
        }
      }
    ]
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
  "GoalMetricCurrentValueRequest": {
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
  "GoalUpdateRequest": {
    "allOf": [
      {
        "$ref": "#/schemas/GoalRequestBase"
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
  "RemoveCustomFieldSettingRequest": {
    "type": "object",
    "required": [
      "custom_field"
    ],
    "properties": {
      "custom_field": {
        "description": "The custom field to remove from this portfolio.",
        "type": "string",
        "example": "14916"
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
  }
}
```

---

## Implementation Rules

### Files you will edit

1. **`database/schema.py`** — add the ORM model class
2. **`database/operations.py`** — add CRUD functions
3. **`core/serializers.py`** — add serialization functions
4. **`api/routes.py`** — add handler functions and Route entries

### ORM model (`database/schema.py`)

- Add a class `AsanaGoal(Base)` with `__tablename__ = "asana_goals"`
- **Primary key**: look at the `gid` field in the bound schemas —
  check its `type`, `format`, and `examples` to determine the correct column
  type. Use `Integer` for integer IDs, `String(50)` for opaque string IDs,
  `String(36)` for UUID-formatted strings, etc.
- One column per field in the schemas above. Use these type mappings:
  - `string` → `String(N)` or `Text` for long content
  - `integer` → `Integer`
  - `boolean` → `Boolean`
  - `object` (nested) → `JSONB`. Use JSONB for nested objects that represent
    settings, metadata, permissions, file maps, or any structure the API
    returns as-is without filtering on individual sub-fields
  - nullable fields → `Mapped[Optional[T]]` with `nullable=True`
- Store timestamps as `String(50)` when the API returns ISO strings
- Add `is_deleted: Mapped[bool]` with `default=False` for soft-delete support
- **Do NOT add any ForeignKey columns or relationship() declarations** — those
  will be added in Pass 2

### CRUD operations (`database/operations.py`)

- Every function takes `Session` as the first argument
- Use `generate_id("goal")` for new IDs
- Use `now_iso()` for timestamp fields
- Use `session.flush()` after mutations — never `session.commit()`
- Filter out `is_deleted` rows in all read queries
- Cursor pagination: fetch `limit + 1` rows, return next cursor from the last row

### Serializers (`core/serializers.py`)

- Return a dict matching the API response shape exactly
- Use the same key names and casing as the original API
- Include a `serialize_goal_list()` for collection endpoints
- For fields that reference other resources (e.g. `owner`, `user`), serialize
  them as the raw column value for now — Pass 2 will refine these

### Route handlers (`api/routes.py`)

- One async handler per endpoint, following the pattern in the file
- Insert Route entries **above** the `/{_unknown_path:path}` catch-all
- Fixed paths before parameterized paths
- Use `_session(request)`, `_principal_user_id(request)`, `_parse_json_body(request)`,
- **Error responses**: Already implemented in `core/errors.py`: `bad_request()`, `unauthorized()`, `payment_required()`, `forbidden()`, `not_found()`, `internal_server_error()`, `handle_exception()`

For error codes not covered above, implement the response inline or add a new constructor to `core/errors.py`.
  `_pagination_params(request)` from the existing request helpers

### Stubs from previous implementations

Previous resource implementations may have created **stub models** for
goals in `database/schema.py`, marked with
`# STUB — expand when implementing this resource`. If you find a stub
for `AsanaGoal`, **replace it** with the full implementation.
Do not create a duplicate class — expand the stub in place.

### What NOT to do

- Do not modify `database/base.py`
- Do not remove or modify existing *completed* implementations for other
  resources — but DO expand any stubs that exist for goals
- Do not invent API behavior not present in the endpoint definitions above
- Do not hard-delete records — use soft-delete via `is_deleted`
- Do not add ForeignKey, relationship(), or association tables — Pass 2 handles those

Read the existing files in the target directory before editing. Preserve
all existing code for other resources — add your new models, functions,
and routes alongside what is already there.
