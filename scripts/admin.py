"""Local operator commands. These operations require trusted database credentials."""

import argparse
from pathlib import Path

from supportops.config import Settings
from supportops.db import Account, Database, User
from supportops.retrieval import Retriever
from supportops.telemetry import Telemetry


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    user = sub.add_parser("provision-user")
    user.add_argument("--subject", required=True)
    user.add_argument("--name", required=True)
    user.add_argument("--tenant", required=True)
    user.add_argument("--role", choices=["viewer", "engineer"], default="viewer")
    user.add_argument("--accounts", nargs="+", required=True)
    ingest = sub.add_parser("ingest")
    ingest.add_argument("path", type=Path)
    ingest.add_argument("--tenant", required=True)
    ingest.add_argument("--version", required=True)
    args = parser.parse_args()
    settings = Settings()
    db = Database(settings.database_url)
    db.initialize(settings.auto_create_schema)
    if args.command == "provision-user":
        with db.session() as session:
            for account_id in args.accounts:
                account = session.get(Account, account_id)
                if not account or account.tenant_id != args.tenant:
                    raise SystemExit("Every account must exist and belong to the specified tenant.")
            record = session.get(User, args.subject) or User(id=args.subject)
            record.name, record.tenant_id, record.role = args.name, args.tenant, args.role
            record.account_ids, record.active = args.accounts, True
            session.add(record)
        print("User provisioned with server-side account permissions.")
    else:
        telemetry = Telemetry(db, settings)
        try:
            ids = Retriever(db, settings, telemetry).ingest(args.path, args.tenant, args.version)
            print(f"Indexed {len(ids)} authorized, versioned chunks.")
        finally:
            telemetry.shutdown()
    db.engine.dispose()


if __name__ == "__main__":
    main()
