import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

# Try importing Azure Data Tables
try:
    from azure.data.tables import TableServiceClient, UpdateMode
    from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
    AZURE_TABLES_AVAILABLE = True
except ImportError:
    AZURE_TABLES_AVAILABLE = False


def sanitize_table_key(key: str) -> str:
    """Disallow invalid Azure Table partition/row key characters: / \ # ? and control chars."""
    if not key:
        return "UNKNOWN"
    cleaned = re.sub(r'[/\\#?\x00-\x1f\x7f-\x9f]', '_', key.strip())
    return cleaned[:1024] or "UNKNOWN"


class TimeTrackerStorage:
    def __init__(self, connection_string: str = None):
        # Load environment variables
        env_paths = [
            Path(__file__).resolve().parent / ".env",
            Path(__file__).resolve().parent.parent / ".env",
        ]
        for p in env_paths:
            if p.exists():
                load_dotenv(dotenv_path=p)
                break
        load_dotenv()

        self.connection_string = connection_string or os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        if not self.connection_string:
            raise ValueError(
                "AZURE_STORAGE_CONNECTION_STRING is not set in environment or passed to TimeTrackerStorage."
            )

        if not AZURE_TABLES_AVAILABLE:
            raise ImportError(
                "The 'azure-data-tables' library is not installed. Run: pip install azure-data-tables"
            )

        self.service_client = TableServiceClient.from_connection_string(self.connection_string)
        self.targets_table_name = "TimeTargets"
        self.logs_table_name = "TimeLogs"

        self._ensure_tables_exist()

    def _ensure_tables_exist(self):
        """Create required tables in Azure Storage if they don't already exist."""
        try:
            self.service_client.create_table_if_not_exists(table_name=self.targets_table_name)
            self.service_client.create_table_if_not_exists(table_name=self.logs_table_name)
        except Exception as ex:
            print(f"[Storage Warning] Could not ensure tables exist: {ex}")

        self.targets_client = self.service_client.get_table_client(self.targets_table_name)
        self.logs_client = self.service_client.get_table_client(self.logs_table_name)

    def list_targets(self) -> list[dict]:
        """Fetch all registered targets."""
        try:
            entities = self.targets_client.list_entities()
            targets = []
            for e in entities:
                targets.append({
                    "name": e.get("Name", e["RowKey"]),
                    "description": e.get("Description", ""),
                    "total_minutes": int(e.get("TotalMinutes", 0)),
                    "created_at": e.get("CreatedAt", "")
                })
            # Sort alphabetically by name
            targets.sort(key=lambda t: t["name"].lower())
            return targets
        except Exception as ex:
            print(f"[Storage Error] Error listing targets: {ex}")
            return []

    def get_target(self, target_name: str) -> dict | None:
        """Get a single target by name."""
        row_key = sanitize_table_key(target_name)
        try:
            entity = self.targets_client.get_entity(partition_key="TARGET", row_key=row_key)
            return {
                "name": entity.get("Name", entity["RowKey"]),
                "description": entity.get("Description", ""),
                "total_minutes": int(entity.get("TotalMinutes", 0)),
                "created_at": entity.get("CreatedAt", "")
            }
        except ResourceNotFoundError:
            return None
        except Exception as ex:
            print(f"[Storage Error] Error getting target: {ex}")
            return None

    def create_target(self, target_name: str, description: str = "") -> dict:
        """Create a new target if it doesn't already exist."""
        name = target_name.strip()
        row_key = sanitize_table_key(name)
        now_str = datetime.now(timezone.utc).isoformat()

        # Check if already exists
        existing = self.get_target(name)
        if existing:
            return {"status": "exists", "target": existing}

        entity = {
            "PartitionKey": "TARGET",
            "RowKey": row_key,
            "Name": name,
            "Description": description or "",
            "TotalMinutes": 0,
            "CreatedAt": now_str
        }

        self.targets_client.upsert_entity(entity=entity, mode=UpdateMode.MERGE)
        return {
            "status": "created",
            "target": {
                "name": name,
                "description": description,
                "total_minutes": 0,
                "created_at": now_str
            }
        }

    def log_time(self, target_name: str, minutes: int, notes: str = "") -> dict:
        """Log minutes for a target and increment the target's total minutes."""
        name = target_name.strip()
        row_key_target = sanitize_table_key(name)
        minutes = int(minutes)

        # Ensure target exists, create if not
        target = self.get_target(name)
        if not target:
            self.create_target(name)
            current_total = 0
        else:
            current_total = target["total_minutes"]

        new_total = current_total + minutes

        # 1. Update target total minutes
        self.targets_client.upsert_entity(
            entity={
                "PartitionKey": "TARGET",
                "RowKey": row_key_target,
                "Name": name,
                "TotalMinutes": new_total
            },
            mode=UpdateMode.MERGE
        )

        # 2. Insert time log entry
        now = datetime.now(timezone.utc)
        # Reverse timestamp so latest entries appear first when queried by row key
        reverse_ticks = f"{(9999999999999 - int(now.timestamp() * 1000)):013d}"
        log_row_key = f"{reverse_ticks}_{uuid.uuid4().hex[:6]}"

        log_entity = {
            "PartitionKey": row_key_target,
            "RowKey": log_row_key,
            "Target": name,
            "Minutes": minutes,
            "Notes": notes or "",
            "LoggedAt": now.isoformat()
        }

        self.logs_client.create_entity(entity=log_entity)

        return {
            "status": "success",
            "target": name,
            "minutes_logged": minutes,
            "target_total_minutes": new_total,
            "target_total_hours": round(new_total / 60, 2),
            "logged_at": now.isoformat()
        }

    def get_summary(self, target_name: str = None) -> dict:
        """Get summary of tracked time overall or for a specific target."""
        if target_name:
            target = self.get_target(target_name)
            if not target:
                return {"error": f"Target '{target_name}' not found."}
            return {
                "target": target["name"],
                "total_minutes": target["total_minutes"],
                "total_hours": round(target["total_minutes"] / 60, 2)
            }

        targets = self.list_targets()
        overall_minutes = sum(t["total_minutes"] for t in targets)
        return {
            "overall_minutes": overall_minutes,
            "overall_hours": round(overall_minutes / 60, 2),
            "target_count": len(targets),
            "targets": [
                {
                    "name": t["name"],
                    "total_minutes": t["total_minutes"],
                    "total_hours": round(t["total_minutes"] / 60, 2)
                }
                for t in targets
            ]
        }

