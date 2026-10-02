import json
import time

from langchain_core.tools import StructuredTool
from pydantic import Field

from supportops.schemas import Evidence, StrictModel
from supportops.security import authorize_account, mask


class AccountArgs(StrictModel):
    account_id: str = Field(min_length=1, max_length=64, description="The account being investigated")


class ToolGateway:
    def __init__(self, db, telemetry):
        self.db, self.telemetry = db, telemetry
        self.descriptions = {
            "get_account_entitlement": "Read the current account support plan.",
            "get_sync_failures": "Read redacted recent sync-service error codes, job counts, service and region.",
            "get_credential_metadata": "Read permission scopes and rotation age; never returns credentials.",
            "get_service_incidents": "Read active service incidents affecting the account region.",
        }

    def definitions(self, principal, case_id, account_id):
        tools = []
        for name, description in self.descriptions.items():

            def execute(account_id: str, _name=name):
                return self.call(principal, case_id, account_id, _name)

            tools.append(
                StructuredTool.from_function(
                    func=execute, name=name, description=description, args_schema=AccountArgs
                )
            )
        return tools

    def call(self, principal, case_id, account_id, name):
        AccountArgs(account_id=account_id)
        if name not in self.descriptions:
            raise ValueError("Tool is not registered")
        account = authorize_account(self.db, principal, account_id)
        with self.telemetry.span(case_id, f"tool.{name}", tool=name, connector="synthetic"):
            d = account.diagnostics
            if name == "get_account_entitlement":
                result = {
                    "account_id": account.id,
                    "support_plan": account.plan,
                    "product_version": account.product_version,
                }
            elif name == "get_sync_failures":
                # This synthetic adapter only models sync-service jobs; expose its scope explicitly.
                result = {
                    "service": "sync-service",
                    **{key: d.get(key) for key in ["failure_code", "http_status", "failed_jobs", "region"]},
                }
            elif name == "get_credential_metadata":
                result = {key: d.get(key) for key in ["credential_scopes", "rotated_hours_ago"]}
            else:
                result = {"region": d.get("region"), "active_incident": d.get("incident")}
            content, _ = mask(json.dumps(result, sort_keys=True))
            if len(content) > 8000:
                raise ValueError("Tool response exceeds budget")
            # This compact schema excludes arbitrary remote text entirely.
            return Evidence(
                id=f"tool:{account.id}:{name}",
                source="tool",
                title=name.replace("_", " "),
                content=content,
                version="synthetic-v2" if name == "get_sync_failures" else "synthetic-v1",
                observed_at=time.time(),
            ).model_dump()
