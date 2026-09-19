import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Load environment
from dotenv import load_dotenv
env_paths = [
    Path(__file__).resolve().parent / ".env",
    Path(__file__).resolve().parent.parent / ".env",
]
for p in env_paths:
    if p.exists():
        load_dotenv(dotenv_path=p)
        break
load_dotenv()

from storage import TimeTrackerStorage
from purchase_client import PurchaseCalcClient


def parse_iso_datetime(dt_str: str) -> datetime | None:
    """Safely parse ISO 8601 timestamp string into a datetime object."""
    if not dt_str:
        return None
    try:
        # Handle Zulu 'Z' suffix for Python 3.10 compatibility
        cleaned = dt_str.replace("Z", "+00:00")
        return datetime.fromisoformat(cleaned)
    except Exception:
        return None


def extract_timeline_entities(json_path: Path) -> list[dict]:
    """Parse Google Takeout / Maps Timeline JSON and return Azure Table entities."""
    with open(json_path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except Exception as ex:
            print(f"  [Error] Skipping {json_path.name}: Failed to parse JSON ({ex})")
            return []

    entities = []

    # Format 1: Google Takeout Semantic Location History (timelineObjects array)
    timeline_objects = data.get("timelineObjects", [])
    if timeline_objects:
        for obj in timeline_objects:
            # Place Visit
            if "placeVisit" in obj:
                pv = obj["placeVisit"]
                loc = pv.get("location", {})
                duration = pv.get("duration", {})

                start_str = duration.get("startTimestamp", "")
                end_str = duration.get("endTimestamp", "")
                start_dt = parse_iso_datetime(start_str)
                end_dt = parse_iso_datetime(end_str)

                if not start_dt:
                    continue

                date_str = start_dt.strftime("%Y-%m-%d")
                time_str = start_dt.strftime("%H%M%S")
                duration_mins = int((end_dt - start_dt).total_seconds() / 60) if (start_dt and end_dt) else 0

                place_name = loc.get("name") or loc.get("address") or "Unknown Place"
                place_id = loc.get("placeId") or ""
                address = loc.get("address") or ""

                # Lat / Lon in Google Takeout are multiplied by 10^7 (latitudeE7)
                lat = loc.get("latitudeE7") / 1e7 if loc.get("latitudeE7") is not None else None
                lon = loc.get("longitudeE7") / 1e7 if loc.get("longitudeE7") is not None else None

                # Generate deterministic RowKey: YYYYMMDD_HHMMSS_<hash>
                hash_seed = f"{place_name}_{place_id}_{start_str}".encode("utf-8")
                hash_id = hashlib.md5(hash_seed).hexdigest()[:8]
                row_key = f"{date_str.replace('-', '')}_{time_str}_{hash_id}"

                entities.append({
                    "PartitionKey": date_str,
                    "RowKey": row_key,
                    "PlaceName": place_name,
                    "Address": address,
                    "Latitude": lat,
                    "Longitude": lon,
                    "StartTime": start_str,
                    "EndTime": end_str,
                    "DurationMinutes": duration_mins,
                    "GooglePlaceId": place_id,
                    "ActivityType": "PLACE_VISIT"
                })

    # Format 2: Raw / Mobile list format (placeVisits array or visits array)
    elif "placeVisits" in data or "visits" in data:
        visits_list = data.get("placeVisits") or data.get("visits") or []
        for pv in visits_list:
            start_str = pv.get("startTimestamp") or pv.get("startTime") or pv.get("date") or ""
            start_dt = parse_iso_datetime(start_str)
            if not start_dt:
                continue

            date_str = start_dt.strftime("%Y-%m-%d")
            time_str = start_dt.strftime("%H%M%S")
            place_name = pv.get("name") or pv.get("placeName") or "Unknown Place"
            address = pv.get("address") or ""
            place_id = pv.get("placeId") or pv.get("googlePlaceId") or ""

            lat = pv.get("latitude")
            lon = pv.get("longitude")
            if lat is not None and abs(lat) > 90:
                lat = lat / 1e7
            if lon is not None and abs(lon) > 180:
                lon = lon / 1e7

            hash_seed = f"{place_name}_{start_str}".encode("utf-8")
            hash_id = hashlib.md5(hash_seed).hexdigest()[:8]
            row_key = f"{date_str.replace('-', '')}_{time_str}_{hash_id}"

            entities.append({
                "PartitionKey": date_str,
                "RowKey": row_key,
                "PlaceName": place_name,
                "Address": address,
                "Latitude": lat,
                "Longitude": lon,
                "StartTime": start_str,
                "EndTime": pv.get("endTime") or "",
                "DurationMinutes": int(pv.get("durationMinutes", 0)),
                "GooglePlaceId": place_id,
                "ActivityType": "PLACE_VISIT"
            })

    return entities


def import_timeline(target_path: Path, sync_pcalc: bool = False):
    """Main ingestion runner."""
    print("=" * 65)
    print(" Google Timeline / Takeout Ingestion Tool")
    print(f" Target: {target_path}")
    print(f" Sync Locations to purchase-calc Cloud Run: {sync_pcalc}")
    print("=" * 65)

    # Collect files
    files_to_process = []
    if target_path.is_file():
        files_to_process.append(target_path)
    elif target_path.is_dir():
        for root, _, filenames in os.walk(target_path):
            for fn in filenames:
                if fn.endswith(".json"):
                    files_to_process.append(Path(root) / fn)
    else:
        print(f"[Error]: Path does not exist: {target_path}")
        return

    if not files_to_process:
        print("No JSON files found to process.")
        return

    print(f"\nFound {len(files_to_process)} JSON file(s) to process.\n")

    # Initialize storage & pcalc
    try:
        storage = TimeTrackerStorage()
    except Exception as ex:
        print(f"[Error]: Could not connect to Azure Table Storage: {ex}")
        return

    pcalc = PurchaseCalcClient() if sync_pcalc else None

    total_imported = 0
    synced_locations = set()
    dates_covered = set()

    for idx, fpath in enumerate(files_to_process, 1):
        print(f"[{idx}/{len(files_to_process)}] Processing {fpath.name}...")
        entities = extract_timeline_entities(fpath)

        if not entities:
            print(f"  No place visits found in {fpath.name}.")
            continue

        # Save to Azure Table Storage
        saved = storage.batch_save_timeline_visits(entities)
        total_imported += saved

        for e in entities:
            dates_covered.add(e["PartitionKey"])

            # Optionally sync new locations to purchase-calc
            if sync_pcalc and pcalc:
                p_name = e["PlaceName"]
                if p_name and p_name not in synced_locations and p_name != "Unknown Place":
                    try:
                        pcalc.add_location(
                            name=p_name,
                            latitude=e.get("Latitude"),
                            longitude=e.get("Longitude"),
                            google_place_id=e.get("GooglePlaceId"),
                            address=e.get("Address")
                        )
                        synced_locations.add(p_name)
                    except Exception:
                        pass

        print(f"  Imported {saved} visit(s).")

    print("\n" + "=" * 65)
    print(" Ingestion Summary")
    print(f" Total Place Visits Saved to Azure: {total_imported}")
    print(f" Unique Dates Covered: {len(dates_covered)}")
    if dates_covered:
        sorted_dates = sorted(dates_covered)
        print(f" Date Range: {sorted_dates[0]} to {sorted_dates[-1]}")
    if sync_pcalc:
        print(f" Locations Synced to purchase-calc: {len(synced_locations)}")
    print("=" * 65)


def main():
    parser = argparse.ArgumentParser(description="Import Google Timeline / Takeout JSON into Azure Table Storage and purchase-calc.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--file", type=str, help="Path to a single Google Takeout JSON file (e.g. 2026_JANUARY.json).")
    group.add_argument("--dir", type=str, help="Path to a directory containing Google Takeout JSON files.")
    parser.add_argument("--sync-pcalc", action="store_true", help="Sync discovered place names & addresses to purchase-calc Cloud Run.")

    args = parser.parse_args()
    target = Path(args.file or args.dir)
    import_timeline(target, sync_pcalc=args.sync_pcalc)


if __name__ == "__main__":
    main()

