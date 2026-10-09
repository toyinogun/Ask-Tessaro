# Layer 1 of Tessaro's authorization (spec 0005): may this caller's roles use this tool at all?
package tessaro.gateway

granted(scope) if {
	some role in input.roles
	scope in data.role_scopes[role]
}

decision := {"allow": true, "reasons": []} if {
	granted(data.tools[input.tool].scope)
}
