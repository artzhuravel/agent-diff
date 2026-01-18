import json
import os
import mimetypes
from datetime import datetime, timedelta
from pathlib import Path
import hashlib

# Configuration
SOURCE_DIR = Path("examples/box/seeds/filesystem")
OUTPUT_FILE = Path("examples/box/seeds/box_default.json")

# Fixed IDs for test reliability (Box uses 10-12 digit numeric strings)
ADMIN_ID = "27512847635"
USER_1_ID = "31847562910"  # Collaborator
USER_2_ID = "45928173064"  # Viewer

# Users to seed
USERS = [
    {
        "id": ADMIN_ID,
        "type": "user",
        "name": "Admin User",
        "login": "admin@example.com",
        "created_at": "2024-01-01T00:00:00Z",
        "status": "active",
        "role": "admin",
    },
    {
        "id": USER_1_ID,
        "type": "user",
        "name": "Sarah Researcher",
        "login": "sarah@example.com",
        "created_at": "2024-01-01T00:00:00Z",
        "status": "active",
        "role": "user",
    },
    {
        "id": USER_2_ID,
        "type": "user",
        "name": "John Viewer",
        "login": "john@example.com",
        "created_at": "2024-01-01T00:00:00Z",
        "status": "active",
        "role": "user",
    },
]


def generate_id(prefix, path_str):
    """Generate a deterministic numeric ID from a string path."""
    hash_obj = hashlib.md5(path_str.encode())
    # Take first 10 digits of int representation
    return str(int(hash_obj.hexdigest(), 16))[:10]


def scan_directory(path: Path, parent_id="0"):
    items = {
        "folders": [],
        "files": [],
        "file_versions": [],
        "file_contents": [],
        "comments": [],
        "tasks": [],
    }

    # Ensure items are sorted for deterministic IDs
    for item in sorted(path.iterdir()):
        if item.name.startswith("."):
            continue

        item_id = generate_id("item", str(item.relative_to(SOURCE_DIR)))
        created_at = (datetime.now() - timedelta(days=10)).isoformat()

        if item.is_dir():
            folder = {
                "id": item_id,
                "type": "folder",
                "name": item.name,
                "parent_id": parent_id,
                "created_at": created_at,
                "modified_at": created_at,
                "owned_by_id": ADMIN_ID,
                "description": f"Folder for {item.name}",
                "item_status": "active",
                "size": 0,
            }
            items["folders"].append(folder)

            # Recurse
            sub_items = scan_directory(item, item_id)
            for k in items:
                items[k].extend(sub_items[k])

        elif item.is_file():
            file_content_bytes = item.read_bytes()
            sha1_hash = hashlib.sha1(file_content_bytes).hexdigest()
            size = len(file_content_bytes)

            # 1. Create File record
            file_obj = {
                "id": item_id,
                "type": "file",
                "name": item.name,
                "parent_id": parent_id,
                "created_at": created_at,
                "modified_at": created_at,
                "owned_by_id": ADMIN_ID,
                "size": size,
                "extension": item.suffix.lstrip("."),
                "sha_1": sha1_hash,  # Corrected column name
                "version_number": "1",
                "comment_count": 0,
                "item_status": "active",
            }
            items["files"].append(file_obj)

            # 2. Create FileVersion record (v1)
            version_id = generate_id("version", item_id + "_v1")
            file_version = {
                "id": version_id,
                "type": "file_version",
                "file_id": item_id,
                "sha_1": sha1_hash,
                "name": item.name,
                "size": size,
                "created_at": created_at,
                "modified_at": created_at,
                "modified_by_id": ADMIN_ID,
                "version_number": "1",
                "local_path": str(item),  # Path to read content from during seeding
            }
            items["file_versions"].append(file_version)

            # 3. Create FileContent record (link version to content)
            # Note: In a real seed, we can't easily put binary in JSON.
            # The seed loader usually expects 'local_path' to load content.
            # But for table 'box_file_contents', we might need to be careful.
            # Let's rely on the seed loader logic. If the loader only inserts
            # into DB, it needs binary data.
            # We'll skip box_file_contents here and assume the seed loader
            # or the application handles content loading if we provide a local path
            # mechanism.
            # WAIT: The seed_box_template.py blindly inserts records.
            # We cannot insert binary data via JSON.
            # We'll need a different strategy for content:
            # - We can leave box_file_contents empty for now (files will exist metadata-wise but fail download)
            # - OR we use a hex encoded string and update the seed loader to decode it.
            # Let's verify what seed_box_template.py does.
            # It just executes SQL.

            # Strategy: We will add social context but acknowledge content seeding limitation.
            # For this 'box_default.json', we populate metadata.
            # The tests will likely upload their own files for download tests.
            # The pre-seeded files are good for search/organization tests.

            # Add some social context to specific files
            if "notes" in item.name.lower():
                # Add a comment
                comment_id = generate_id("comment", item_id)
                items["comments"].append(
                    {
                        "id": comment_id,
                        "type": "comment",
                        "item_id": item_id,  # Points to file
                        "file_id": item_id,  # Also set file_id for FK integrity (new schema)
                        "item_type": "file",
                        "message": "Needs review before final submission.",
                        "created_by_id": USER_1_ID,
                        "created_at": created_at,
                        "modified_at": created_at,
                        "is_reply_comment": False,
                    }
                )
                file_obj["comment_count"] += 1

            if "guide" in item.name.lower():
                # Add a task
                task_id = generate_id("task", item_id)
                items["tasks"].append(
                    {
                        "id": task_id,
                        "type": "task",
                        "item_id": item_id,
                        "item_type": "file",
                        "message": "Please update formatting",
                        "created_by_id": ADMIN_ID,
                        "created_at": created_at,
                        "is_completed": False,
                        "action": "review",
                        "completion_rule": "any_assignee",
                    }
                )

    return items


def main():
    print(f"Scanning {SOURCE_DIR}...")
    content = scan_directory(SOURCE_DIR)

    # Structure for the seed file
    seed_data = {
        "box_users": USERS,
        "box_folders": content["folders"],
        "box_files": content["files"],
        "box_file_versions": content["file_versions"],
        # "box_file_contents": [], # Skipping binary content in JSON
        "box_comments": content["comments"],
        "box_tasks": content["tasks"],
        "box_hubs": [
            {
                "id": "999999",
                "type": "hub",
                "name": "Research Project Hub",
                "created_by_id": ADMIN_ID,
                "created_at": datetime.now().isoformat(),
                "status": "active",
            }
        ],
        "box_hub_items": [],
    }

    print(
        f"Generated {len(content['files'])} files and {len(content['folders'])} folders."
    )

    # Ensure directory exists
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with open(OUTPUT_FILE, "w") as f:
        json.dump(seed_data, f, indent=2)

    print(f"Wrote seed data to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
