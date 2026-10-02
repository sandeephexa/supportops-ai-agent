# Authentication and credential rotation
## Diagnose HTTP 403 after rotation
For Sync API v3, a credential requires both sync:read and sync:write scopes. A credential with only sync:read can inspect jobs but cannot submit synchronization writes. Missing sync:write permission can produce HTTP 403 with error code SCOPE_MISSING.
Check credential metadata and recent failure codes before concluding that a scope is missing. A 403 response by itself does not establish the cause.
## Safe remediation
Ask an authorized customer administrator to review the rotated credential's scopes and grant sync:write only if required by their integration. Never request, print or transmit a credential secret. Validate with a single test job after the permission change. Escalate if failures continue; include the error code, scope metadata and product version.
## Distinguish expired credentials
An expired credential typically produces HTTP 401 with error code TOKEN_EXPIRED. Do not recommend scope changes for a confirmed expired credential. Ask the authorized administrator to rotate the credential through their secure console.
