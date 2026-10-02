# Synchronization operations
## Rate limiting
HTTP 429 with error code RATE_LIMIT indicates that the integration exceeded its request quota. Honor Retry-After and use exponential backoff with jitter. Cap concurrent jobs and do not retry every job immediately. A retry storm can prolong recovery.
## Schema validation failures
HTTP 422 with error code SCHEMA_MISMATCH indicates incompatible fields or a missing required mapping. Compare the input mapping with the v3 schema. Preserve the original dataset and validate on a small sample before replaying failed jobs.
## Recovery evidence
Record first and last failure timestamps, affected job count and error codes. Avoid copying customer payloads into an escalation. Include only redacted metadata and approved evidence references.
