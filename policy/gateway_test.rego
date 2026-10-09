package tessaro.gateway_test

import data.tessaro.gateway

employee := {"kind": "human", "roles": ["employee"]}

test_demo_employee_may_get_my_leave if {
	gateway.decision == {"allow": true, "reasons": []} with input as object.union(employee, {"tool": "get_my_leave"})
}
