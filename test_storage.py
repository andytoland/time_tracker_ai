import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env
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

def main():
    print("Testing connection to Azure Table Storage...")
    try:
        storage = TimeTrackerStorage()
        print("Connected to Azure Table Storage successfully!")
        
        # Test listing targets
        targets = storage.list_targets()
        print(f"Current targets count: {len(targets)}")
        for t in targets:
            print(f" - {t['name']} (Total: {t['total_minutes']} mins / {round(t['total_minutes']/60, 2)} hrs)")

        # Test Active Timer flow
        print("\nTesting Active Timer flow ('started X' / 'end')...")
        test_activity = "Test Activity Metering"
        
        # 1. Start timer
        start_res = storage.start_timer(target_name=test_activity, notes="Integration test start")
        print(f" - start_timer result: {start_res['status']} for '{start_res['target_name']}'")
        assert start_res["status"] == "started"

        # 2. Check active timer
        active = storage.get_active_timer()
        print(f" - get_active_timer: active target = '{active['target_name']}', elapsed = {active['elapsed_seconds']}s")
        assert active is not None
        assert active["target_name"] == test_activity

        # 3. Test duplicate start prevention
        dup_res = storage.start_timer(target_name="Another Activity")
        print(f" - duplicate start prevention: {dup_res['status']} ({dup_res.get('message')})")
        assert dup_res["status"] == "already_running"

        # 4. Stop timer
        stop_res = storage.stop_timer(notes="Integration test finish")
        print(f" - stop_timer: {stop_res['status']}, logged {stop_res['minutes_logged']} min(s) on '{stop_res['target_name']}'")
        assert stop_res["status"] == "stopped"
        assert stop_res["target_name"] == test_activity

        # 5. Verify timer is cleared
        cleared = storage.get_active_timer()
        print(f" - active timer after stop: {cleared}")
        assert cleared is None

        # 6. Test cancel flow
        storage.start_timer(target_name="Cancel Test")
        cancel_res = storage.cancel_timer()
        print(f" - cancel_timer result: {cancel_res['status']}")
        assert cancel_res["status"] == "cancelled"
        assert storage.get_active_timer() is None

        # Clean up test targets
        try:
            from storage import sanitize_table_key
            storage.targets_client.delete_entity(partition_key="TARGET", row_key=sanitize_table_key(test_activity))
            storage.targets_client.delete_entity(partition_key="TARGET", row_key=sanitize_table_key("Cancel Test"))
            print(f" - Cleaned up test targets")
        except Exception:
            pass
        
        print("\nAll checks passed! Tables and Active Timer features are ready.")
    except Exception as ex:
        print(f"Error connecting to Azure Table Storage: {ex}")

if __name__ == "__main__":
    main()

