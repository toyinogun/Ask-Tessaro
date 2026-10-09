package tessaro.gateway_test

import data.tessaro.gateway

# One fixture tool per scope, named after it ("it:read" becomes tool it_read).
fixture_tools := {name: {"owner": "test", "scope": scope, "version": "1.0"} |
	some scope in all_scopes
	name := replace(scope, ":", "_")
}

all_scopes := {
	"it:read", "hr:read", "finance:read", "workplace:read", "kb:read",
	"queue:handoff", "workflow:read", "team:read", "it:read_any",
	"workflow:read_any", "hr:read_any", "identity:write", "it:write", "workplace:write",
}

write_tools := ["identity_write", "it_write", "workplace_write"]

human_roles := ["employee", "manager", "it_service_desk", "people_advisor"]

employee := {"kind": "human", "roles": ["employee"]}

worker := {"kind": "workflow_worker", "roles": ["workflow_worker"]}

allowed := {"allow": true, "reasons": []}

denied(reasons) := {"allow": false, "reasons": reasons}

invalid := denied(["invalid_input"])

call(principal, tool) := object.union(principal, {"tool": tool})

fixture_decision(principal, tool) := d if {
	d := gateway.decision with input as call(principal, tool) with data.tools as fixture_tools
}

# AC-3: the demo case, against the real generated data

test_demo_employee_may_get_my_leave if {
	gateway.decision == allowed with input as call(employee, "get_my_leave")
}

# AC-4: deny reasons, combined and sorted

test_unknown_tool_is_the_only_reason if {
	gateway.decision == denied(["unknown_tool"]) with input as call(employee, "nope")
}

test_unknown_tool_with_a_mismatch if {
	principal := {"kind": "human", "roles": ["employee", "workflow_worker"]}
	gateway.decision == denied(["kind_role_mismatch", "unknown_tool"]) with input as call(principal, "nope")
}

test_scope_not_granted if {
	fixture_decision(employee, "team_read") == denied(["scope_not_granted"])
}

test_manager_calling_a_write_tool_gets_both_reasons if {
	manager := {"kind": "human", "roles": ["manager"]}
	fixture_decision(manager, "it_write") == denied(["scope_not_granted", "write_needs_worker"])
}

test_worker_lacking_a_read_scope_is_not_granted if {
	fixture_decision(worker, "it_read") == denied(["scope_not_granted"])
}

test_worker_may_write if {
	every tool in write_tools {
		fixture_decision(worker, tool) == allowed
	}
}

test_missing_tool_data_makes_every_tool_unknown if {
	gateway.decision == denied(["unknown_tool"]) with input as call(employee, "get_my_leave")
		with data.tools as {}
}

# AC-5: no human is ever allowed a write scope, even with doctored role data

doctored_role_scopes := {role: ["identity:write", "it:write", "workplace:write"] | some role in human_roles}

test_human_denied_every_write_scope_for_every_role if {
	every role in human_roles {
		every tool in write_tools {
			"write_needs_worker" in fixture_decision({"kind": "human", "roles": [role]}, tool).reasons
		}
	}
}

test_human_denied_writes_even_when_data_grants_them if {
	every role in human_roles {
		every tool in write_tools {
			d := gateway.decision with input as call({"kind": "human", "roles": [role]}, tool)
				with data.tools as fixture_tools
				with data.role_scopes as doctored_role_scopes
			d == denied(["write_needs_worker"])
		}
	}
}

test_human_denied_writes_with_every_human_role_at_once if {
	principal := {"kind": "human", "roles": human_roles}
	every tool in write_tools {
		d := gateway.decision with input as call(principal, tool)
			with data.tools as fixture_tools
			with data.role_scopes as doctored_role_scopes
		d == denied(["write_needs_worker"])
	}
}

# AC-6: kind and role mismatch; role order is irrelevant otherwise

test_human_holding_workflow_worker_is_a_mismatch if {
	principal := {"kind": "human", "roles": ["employee", "workflow_worker"]}
	fixture_decision(principal, "it_write") == denied(["kind_role_mismatch", "write_needs_worker"])
}

test_human_with_only_workflow_worker_is_a_mismatch if {
	principal := {"kind": "human", "roles": ["workflow_worker"]}
	fixture_decision(principal, "hr_read") == denied(["kind_role_mismatch", "scope_not_granted"])
}

test_worker_with_an_extra_role_is_a_mismatch if {
	principal := {"kind": "workflow_worker", "roles": ["workflow_worker", "employee"]}
	fixture_decision(principal, "hr_read") == denied(["kind_role_mismatch"])
}

test_worker_without_the_worker_role_is_a_mismatch if {
	principal := {"kind": "workflow_worker", "roles": ["employee"]}
	fixture_decision(principal, "hr_read") == denied(["kind_role_mismatch"])
}

test_unsorted_roles_are_valid if {
	principal := {"kind": "human", "roles": ["manager", "employee"]}
	fixture_decision(principal, "team_read") == allowed
}

# AC-7: invalid input fails closed with one reason, and both rules are always defined

test_no_input_at_all if {
	gateway.decision == invalid
	gateway.allowed_tools == []
}

invalid_principals := [
	{},
	{"roles": ["employee"]},
	{"kind": "admin", "roles": ["employee"]},
	{"kind": "human"},
	{"kind": "human", "roles": []},
	{"kind": "human", "roles": "employee"},
	{"kind": "human", "roles": [1]},
	{"kind": "human", "roles": ["root"]},
	{"kind": "human", "roles": ["employee", "employee"]},
	{"kind": "human", "roles": null},
	{"kind": "human", "roles": ["employee", 1]},
	{"kind": "human", "roles": ["Employee"]},
	{"kind": "Human", "roles": ["employee"]},
	{"kind": 5, "roles": ["employee"]},
]

test_invalid_principal_with_a_known_tool if {
	every principal in invalid_principals {
		fixture_decision(principal, "hr_read") == invalid
	}
}

test_invalid_principal_with_no_tool if {
	every principal in invalid_principals {
		gateway.decision == invalid with input as principal
	}
}

test_invalid_principal_lists_no_tools if {
	every principal in invalid_principals {
		tools := gateway.allowed_tools with input as principal with data.tools as fixture_tools
		tools == []
	}
}

test_invalid_tool if {
	every tool in ["", 5, null, ["hr_read"]] {
		fixture_decision(employee, tool) == invalid
	}
}

test_absent_tool_on_decision if {
	gateway.decision == invalid with input as employee
}

test_missing_role_data_makes_every_principal_invalid if {
	d := gateway.decision with input as call(employee, "get_my_leave") with data.role_scopes as {}
	d == invalid
}

# AC-8: allowed_tools uses the same reasons as decision

employee_tools := ["finance_read", "hr_read", "it_read", "kb_read", "queue_handoff", "workflow_read", "workplace_read"]

test_employee_lists_its_seven_tools if {
	tools := gateway.allowed_tools with input as employee with data.tools as fixture_tools
	tools == employee_tools
}

test_empty_tool_does_not_affect_the_listing if {
	tools := gateway.allowed_tools with input as call(employee, "") with data.tools as fixture_tools
	tools == employee_tools
}

test_worker_lists_its_four_tools if {
	tools := gateway.allowed_tools with input as worker with data.tools as fixture_tools
	tools == ["hr_read_any", "identity_write", "it_write", "workplace_write"]
}

test_mismatched_principal_lists_nothing if {
	principal := {"kind": "human", "roles": ["employee", "workflow_worker"]}
	tools := gateway.allowed_tools with input as principal with data.tools as fixture_tools
	tools == []
}

test_listing_against_the_real_data if {
	gateway.allowed_tools == ["get_my_leave"] with input as employee
}

test_every_listed_tool_is_callable if {
	every principal in [employee, worker, {"kind": "human", "roles": ["manager", "people_advisor"]}] {
		tools := gateway.allowed_tools with input as principal with data.tools as fixture_tools
		every tool in tools {
			fixture_decision(principal, tool) == allowed
		}
	}
}

# AC-9: every cell of the PRD 8.2 grid, against the real generated data.role_scopes.
# ok: allowed; no: ["scope_not_granted"]; no_write: ["scope_not_granted", "write_needs_worker"].

grid_columns := [
	"it_read", "hr_read", "finance_read", "workplace_read", "kb_read", "queue_handoff",
	"workflow_read", "team_read", "it_read_any", "workflow_read_any", "hr_read_any",
	"identity_write", "it_write", "workplace_write",
]

grid := {
	"employee": ["ok", "ok", "ok", "ok", "ok", "ok", "ok", "no", "no", "no", "no", "no_write", "no_write", "no_write"],
	"manager": ["ok", "ok", "ok", "ok", "ok", "ok", "ok", "ok", "no", "no", "no", "no_write", "no_write", "no_write"],
	"it_service_desk": ["no", "no", "no", "no", "no", "no", "no", "no", "ok", "ok", "no", "no_write", "no_write", "no_write"],
	"people_advisor": ["no", "no", "no", "no", "no", "no", "no", "no", "no", "ok", "ok", "no_write", "no_write", "no_write"],
	"workflow_worker": ["no", "no", "no", "no", "no", "no", "no", "no", "no", "no", "ok", "ok", "ok", "ok"],
}

grid_decisions := {
	"ok": allowed,
	"no": denied(["scope_not_granted"]),
	"no_write": denied(["scope_not_granted", "write_needs_worker"]),
}

grid_kind(role) := "workflow_worker" if role == "workflow_worker"

grid_kind(role) := "human" if role != "workflow_worker"

test_grid_covers_every_scope_and_role if {
	{replace(scope, ":", "_") | some scope in all_scopes} == {tool | some tool in grid_columns}
	object.keys(grid) == object.keys(data.role_scopes)
	every row in grid {
		count(row) == count(grid_columns)
	}
}

test_prd_8_2_grid if {
	every role, row in grid {
		every i, cell in row {
			principal := {"kind": grid_kind(role), "roles": [role]}
			fixture_decision(principal, grid_columns[i]) == grid_decisions[cell]
		}
	}
}

# AC-7: input that is not an object at all fails closed too

test_input_that_is_not_an_object if {
	every bad in ["employee", ["employee"], 42, null, true] {
		gateway.decision == invalid with input as bad
		tools := gateway.allowed_tools with input as bad with data.tools as fixture_tools
		tools == []
	}
}

# AC-3: one granting role is enough, whatever else the caller holds

test_any_one_role_may_grant_the_scope if {
	principal := {"kind": "human", "roles": ["it_service_desk", "employee"]}
	every tool in ["it_read", "it_read_any", "workflow_read_any"] {
		fixture_decision(principal, tool) == allowed
	}
	fixture_decision(principal, "hr_read_any") == denied(["scope_not_granted"])
}

# AC-4: an unknown tool never gets a scope reason, even when its name looks like a write

test_unknown_tool_gets_no_scope_reasons if {
	every principal in [employee, worker] {
		gateway.decision == denied(["unknown_tool"]) with input as call(principal, "it_write")
	}
}

# Data model: extra input keys are ignored, so personal data can never change a decision

test_extra_input_keys_are_ignored if {
	extra := {"email": "a.person@example.com", "employee_id": "TES-00001", "kind_override": "workflow_worker"}
	every tool in ["hr_read", "team_read", "it_write"] {
		with_extra := gateway.decision with input as object.union(call(employee, tool), extra)
			with data.tools as fixture_tools
		with_extra == fixture_decision(employee, tool)
	}
}

# AC-4, review finding 1: a known tool whose data has no usable scope fails closed

broken_tools := {
	"no_scope": {"owner": "test", "version": "1.0"},
	"null_scope": {"owner": "test", "scope": null, "version": "1.0"},
	"number_scope": {"owner": "test", "scope": 7, "version": "1.0"},
	"not_an_object": "hr:read",
}

test_tool_without_a_usable_scope_is_denied if {
	every principal in [employee, worker, {"kind": "human", "roles": human_roles}] {
		every tool, _ in broken_tools {
			d := gateway.decision with input as call(principal, tool) with data.tools as broken_tools
			d == denied(["scope_not_granted"])
		}
	}
}

test_tool_without_a_usable_scope_is_not_listed if {
	every principal in [employee, worker] {
		tools := gateway.allowed_tools with input as principal with data.tools as broken_tools
		tools == []
	}
}
