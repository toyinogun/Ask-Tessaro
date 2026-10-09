# Layer 1 of Tessaro's authorization (spec 0005): may this caller's roles use this tool at all?
#
# Input is {kind, roles, tool} from a principal tessaro-auth already verified. Both rules
# are always defined, so an empty OPA result means OPA failed, never "no rule matched".
package tessaro.gateway

kinds := {"human", "workflow_worker"}

reason_names := {"unknown_tool", "scope_not_granted", "write_needs_worker", "kind_role_mismatch"}

# The decision for input.tool: allow is true exactly when there is no reason to deny.
default decision := {"allow": false, "reasons": ["invalid_input"]}

decision := {"allow": count(r) == 0, "reasons": sort(r)} if {
	r := deny_reasons(input.tool)
}

# Every tool in data.tools the same kind and roles may call; input.tool is ignored.
default allowed_tools := []

allowed_tools := sort([name |
	some name, _ in data.tools
	count(deny_reasons(name)) == 0
]) if {
	valid_principal
}

valid_principal if {
	input.kind in kinds
	is_array(input.roles)
	count(input.roles) > 0
	every role in input.roles {
		is_string(role)
		role in object.keys(data.role_scopes)
	}
	count({role | some role in input.roles}) == count(input.roles)
}

valid_tool(t) if {
	is_string(t)
	t != ""
}

# The set of reasons to deny tool t for the input kind and roles.
deny_reasons(t) := {reason | some reason in reason_names; applies(reason, t)} if {
	valid_principal
	valid_tool(t)
} else := {"invalid_input"}

applies("unknown_tool", t) if not data.tools[t]

# Reported for known tools only; an unknown tool has no scope to grant.
applies("scope_not_granted", t) if {
	scope := data.tools[t].scope
	not granted(scope)
}

# Holds whatever data.role_scopes says: no human ever uses a write scope.
applies("write_needs_worker", t) if {
	endswith(data.tools[t].scope, ":write")
	input.kind != "workflow_worker"
}

applies("kind_role_mismatch", _) if kind_role_mismatch

granted(scope) if {
	some role in input.roles
	scope in data.role_scopes[role]
}

kind_role_mismatch if {
	input.kind == "human"
	"workflow_worker" in input.roles
}

kind_role_mismatch if {
	input.kind == "workflow_worker"
	input.roles != ["workflow_worker"]
}
