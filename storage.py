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
    r"""Disallow invalid Azure Table partition/row key characters: / \ # ? and control chars."""
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
        self.timeline_table_name = "TimelineVisits"
        self.active_timers_table_name = "ActiveTimers"

        self._ensure_tables_exist()

    def _ensure_tables_exist(self):
        """Create required tables in Azure Storage if they don't already exist."""
        try:
            self.service_client.create_table_if_not_exists(table_name=self.targets_table_name)
            self.service_client.create_table_if_not_exists(table_name=self.logs_table_name)
            self.service_client.create_table_if_not_exists(table_name=self.timeline_table_name)
            self.service_client.create_table_if_not_exists(table_name=self.active_timers_table_name)
        except Exception as ex:
            print(f"[Storage Warning] Could not ensure tables exist: {ex}")

        self.targets_client = self.service_client.get_table_client(self.targets_table_name)
        self.logs_client = self.service_client.get_table_client(self.logs_table_name)
        self.timeline_client = self.service_client.get_table_client(self.timeline_table_name)
        self.active_timers_client = self.service_client.get_table_client(self.active_timers_table_name)

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

    # -------------------------------------------------------------------------
    # Timeline Visits Endpoints (Google Maps Timeline)
    # -------------------------------------------------------------------------

    def save_timeline_visit(self, visit_entity: dict) -> None:
        """Upsert a single timeline visit into Azure Table Storage."""
        self.timeline_client.upsert_entity(entity=visit_entity, mode=UpdateMode.MERGE)

    def batch_save_timeline_visits(self, visits: list[dict]) -> int:
        """Save a list of timeline visit entities."""
        saved_count = 0
        for v in visits:
            try:
                self.save_timeline_visit(v)
                saved_count += 1
            except Exception as ex:
                print(f"[Storage Warning] Could not save visit {v.get('RowKey')}: {ex}")
        return saved_count

    def get_timeline_visits(self, start_date: str, end_date: str = None) -> list[dict]:
        """Fetch timeline visits between start_date and end_date (YYYY-MM-DD)."""
        if not end_date:
            end_date = start_date

        try:
            if start_date == end_date:
                query_filter = f"PartitionKey eq '{start_date}'"
            else:
                query_filter = f"PartitionKey ge '{start_date}' and PartitionKey le '{end_date}'"

            entities = self.timeline_client.query_entities(query_filter=query_filter)
            visits = []
            for e in entities:
                st = e.get("StartTime", "")
                visits.append({
                    "date": e.get("PartitionKey"),
                    "start_time": st,
                    "end_time": e.get("EndTime", ""),
                    "time": st[11:16] if len(st) >= 16 else "",
                    "duration_minutes": int(e.get("DurationMinutes", 0)),
                    "place_name": e.get("PlaceName", "Unknown"),
                    "address": e.get("Address", ""),
                    "latitude": float(e["Latitude"]) if "Latitude" in e and e["Latitude"] is not None else None,
                    "longitude": float(e["Longitude"]) if "Longitude" in e and e["Longitude"] is not None else None,
                    "activity_type": e.get("ActivityType", ""),
                    "google_place_id": e.get("GooglePlaceId", ""),
                    "source": "google-timeline"
                })
            visits.sort(key=lambda x: x.get("start_time", ""))
            return visits
        except Exception as ex:
            print(f"[Storage Error] Error fetching timeline visits: {ex}")
            return []

    # -------------------------------------------------------------------------
    # Active Timer Methods ("started X" / "end")
    # -------------------------------------------------------------------------

    def start_timer(self, target_name: str, notes: str = "", overwrite: bool = False) -> dict:
        """Start a live timer for an activity/target.
        
        If a timer is already running and overwrite is False, returns status 'already_running'.
        """
        name = target_name.strip()
        current = self.get_active_timer()
        if current and not overwrite:
            return {
                "status": "already_running",
                "active_timer": current,
                "message": f"Timer is already running for '{current['target_name']}' (started {current['elapsed_minutes']} minutes ago)."
            }

        # Ensure target exists in TimeTargets table
        target = self.get_target(name)
        if not target:
            self.create_target(name)

        now = datetime.now(timezone.utc)
        now_str = now.isoformat()
        entity = {
            "PartitionKey": "TIMER",
            "RowKey": "CURRENT",
            "TargetName": name,
            "Notes": notes or "",
            "StartedAt": now_str
        }
        self.active_timers_client.upsert_entity(entity=entity, mode=UpdateMode.MERGE)
        return {
            "status": "started",
            "target_name": name,
            "notes": notes or "",
            "started_at": now_str,
            "message": f"Started timer for '{name}'."
        }

    def get_active_timer(self) -> dict | None:
        """Fetch the currently running timer with live elapsed duration."""
        try:
            entity = self.active_timers_client.get_entity(partition_key="TIMER", row_key="CURRENT")
            started_at_str = entity.get("StartedAt", "")
            target_name = entity.get("TargetName", "")
            notes = entity.get("Notes", "")

            if not started_at_str:
                return None

            started_at = datetime.fromisoformat(started_at_str)
            now = datetime.now(timezone.utc)
            elapsed_seconds = max(0, int((now - started_at).total_seconds()))
            elapsed_minutes = round(elapsed_seconds / 60, 1)

            return {
                "target_name": target_name,
                "notes": notes,
                "started_at": started_at_str,
                "elapsed_seconds": elapsed_seconds,
                "elapsed_minutes": elapsed_minutes,
                "elapsed_hours": round(elapsed_seconds / 3600, 2)
            }
        except ResourceNotFoundError:
            return None
        except Exception as ex:
            print(f"[Storage Error] Error getting active timer: {ex}")
            return None

    def stop_timer(self, notes: str = "") -> dict:
        """Stop the active timer, calculate elapsed duration, log to storage, and delete the active timer entity."""
        timer = self.get_active_timer()
        if not timer:
            return {
                "status": "no_active_timer",
                "message": "No active timer is currently running."
            }

        target_name = timer["target_name"]
        started_at_str = timer["started_at"]
        started_at = datetime.fromisoformat(started_at_str)
        now = datetime.now(timezone.utc)
        elapsed_seconds = max(0, int((now - started_at).total_seconds()))

        # Minimum 1 minute if at least 1 second has elapsed
        minutes = max(1, round(elapsed_seconds / 60))

        # Combine notes if provided
        combined_notes_parts = []
        if timer.get("notes"):
            combined_notes_parts.append(timer["notes"])
        if notes:
            combined_notes_parts.append(notes)
        combined_notes = " - ".join(combined_notes_parts)

        # Log to TimeLogs and update TimeTargets
        log_res = self.log_time(target_name=target_name, minutes=minutes, notes=combined_notes)

        # Remove the active timer entity
        try:
            self.active_timers_client.delete_entity(partition_key="TIMER", row_key="CURRENT")
        except Exception as ex:
            print(f"[Storage Warning] Could not delete active timer entity: {ex}")

        return {
            "status": "stopped",
            "target_name": target_name,
            "minutes_logged": minutes,
            "elapsed_seconds": elapsed_seconds,
            "target_total_minutes": log_res["target_total_minutes"],
            "target_total_hours": log_res["target_total_hours"],
            "started_at": started_at_str,
            "stopped_at": now.isoformat(),
            "notes": combined_notes,
            "message": f"Stopped timer for '{target_name}'. Logged {minutes} minutes ({log_res['target_total_hours']} hrs total)."
        }

    def cancel_timer(self) -> dict:
        """Cancel and discard the active timer without logging any time."""
        timer = self.get_active_timer()
        if not timer:
            return {
                "status": "no_active_timer",
                "message": "No active timer is currently running."
            }

        try:
            self.active_timers_client.delete_entity(partition_key="TIMER", row_key="CURRENT")
        except Exception as ex:
            print(f"[Storage Warning] Could not delete active timer entity: {ex}")

        return {
            "status": "cancelled",
            "target_name": timer["target_name"],
            "started_at": timer["started_at"],
            "message": f"Timer for '{timer['target_name']}' has been cancelled without logging time."
        }



