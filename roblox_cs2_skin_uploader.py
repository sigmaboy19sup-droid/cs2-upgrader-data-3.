
import json
import re
import time
import hashlib
from pathlib import Path

import requests

USER_ID = "3186059055"

SKINS_URL = (
    "https://raw.githubusercontent.com/ByMykel/CSGO-API/"
    "main/public/api/en/skins_not_grouped.json"
)

CREATE_URL = "https://apis.roblox.com/assets/v1/assets"
OPS_URL = "https://apis.roblox.com/assets/v1/operations/"

IMAGE_FILE = Path("skin_images.json")
DATABASE_FILE = Path("skins_database.json")
CACHE = Path("skin_image_cache")

session = requests.Session()


def read_json(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_json(path, data):
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    temp_path.replace(path)


def get_value(obj, key, default=""):
    if not isinstance(obj, dict):
        return default

    value = obj.get(key, default)

    if isinstance(value, dict):
        return value.get("name", default)

    return value if value is not None else default


def design_key(item):
    weapon = item.get("weapon") or {}
    pattern = item.get("pattern") or {}

    weapon_id = (
        weapon.get("id")
        or weapon.get("name")
        or "unknown"
    )

    pattern_id = (
        pattern.get("id")
        or item.get("paint_index")
        or pattern.get("name")
        or item.get("name", "unknown")
    )

    return f"{weapon_id}__{pattern_id}"


def clean_name(name):
    return re.sub(
        r"[^A-Za-z0-9 _().'-]",
        "",
        str(name)
    ).strip()[:50] or "CS2 Skin"


def cache_filename(key, ext):
    short_name = hashlib.sha256(
        key.encode("utf-8")
    ).hexdigest()[:20]

    return CACHE / (short_name + ext)


def download_image(item, key):
    image_url = item.get("image")

    if not image_url:
        raise RuntimeError("No image URL")

    response = session.get(image_url, timeout=60)
    response.raise_for_status()

    mime = response.headers.get(
        "Content-Type", ""
    ).split(";")[0].lower()

    extensions = {
        "image/png": (".png", "image/png"),
        "image/jpeg": (".jpg", "image/jpeg"),
        "image/bmp": (".bmp", "image/bmp"),
        "image/tga": (".tga", "image/tga"),
    }

    if mime not in extensions:
        raise RuntimeError(f"Unsupported image type: {mime}")

    if len(response.content) > 20 * 1024 * 1024:
        raise RuntimeError("Image exceeds 20 MB")

    ext, mime = extensions[mime]

    CACHE.mkdir(exist_ok=True)

    file_path = cache_filename(key, ext)

    if not file_path.exists():
        file_path.write_bytes(response.content)

    return file_path, mime


def upload_image(item, design_key_value, api_key):
    file_path, mime = download_image(
        item,
        design_key_value
    )

    payload = {
        "assetType": "Decal",
        "displayName": clean_name(
            item.get("name", "CS2 Skin")
        ),
        "description": "CS2 skin image",
        "creationContext": {
            "creator": {"userId": USER_ID}
        }
    }

    with file_path.open("rb") as file:
        result = session.post(
            CREATE_URL,
            headers={"x-api-key": api_key},
            data={"request": json.dumps(payload)},
            files={
                "fileContent": (
                    file_path.name,
                    file,
                    mime
                )
            },
            timeout=120
        )

    if not result.ok:
        raise RuntimeError(
            f"Upload HTTP {result.status_code}: "
            f"{result.text[:500]}"
        )

    operation = result.json()

    operation_id = (
        operation.get("path", "").rsplit("/", 1)[-1]
        or operation.get("operationId")
    )

    if not operation_id:
        raise RuntimeError(
            f"No operation ID: {operation}"
        )

    deadline = time.time() + 180

    while time.time() < deadline:
        poll = session.get(
            OPS_URL + operation_id,
            headers={"x-api-key": api_key},
            timeout=30
        )

        poll.raise_for_status()
        status = poll.json()

        if status.get("done"):
            if status.get("error"):
                raise RuntimeError(
                    str(status["error"])
                )

            asset_id = (
                status.get("response") or {}
            ).get("assetId")

            if asset_id:
                return str(asset_id)

            raise RuntimeError(
                f"No asset ID: {status}"
            )

        time.sleep(2)

    raise RuntimeError("Roblox processing timeout")


def make_variant_record(variant, key, asset_id):
    weapon = variant.get("weapon") or {}
    rarity = variant.get("rarity") or {}
    pattern = variant.get("pattern") or {}

    return {
        "id": str(variant["id"]),
        "name": variant.get("name", ""),
        "weapon": get_value(weapon, "name"),
        "weaponId": weapon.get("id", ""),
        "pattern": pattern.get("name", ""),
        "rarity": rarity.get("name", ""),
        "rarityColor": rarity.get("color", ""),
        "minFloat": variant.get("min_float"),
        "maxFloat": variant.get("max_float"),
        "stattrak": bool(variant.get("stattrak", False)),
        "souvenir": bool(variant.get("souvenir", False)),
        "designKey": key,
        "assetId": str(asset_id),
        "image": f"rbxassetid://{asset_id}"
    }


def main():
    print("=" * 50)
    print("CS2 UNIQUE SKIN IMAGE UPLOADER")
    print("Roblox creator:", USER_ID)
    print("=" * 50)

    print(
        "\nВставь Roblox API Key."
        "\nКлюч не отправляй никому и не публикуй."
    )

    api_key = input("\nRoblox API Key: ").strip()

    if not api_key:
        print("API key is empty.")
        return

    print("\nDownloading CS2 database...")

    response = session.get(SKINS_URL, timeout=90)
    response.raise_for_status()
    items = response.json()

    print("Total source records:", len(items))

    images = read_json(IMAGE_FILE)
    old_images = images.copy()

    database = read_json(DATABASE_FILE)
    new_database = database.copy()

    groups = {}

    for item in items:
        if not item.get("id"):
            continue

        key = design_key(item)
        groups.setdefault(key, []).append(item)

    print("Unique designs:", len(groups))

    pending = []

    for key, variants in groups.items():
        asset_id = None

        existing = images.get(key)

        if isinstance(existing, dict):
            asset_id = existing.get("assetId")

        if not asset_id:
            for variant in variants:
                old = old_images.get(str(variant["id"]))

                if isinstance(old, dict) and old.get("assetId"):
                    asset_id = str(old["assetId"])

                    images[key] = {
                        "designKey": key,
                        "name": variant.get("name", key),
                        "assetId": asset_id,
                        "image": f"rbxassetid://{asset_id}"
                    }
                    break

        if asset_id:
            for variant in variants:
                record = make_variant_record(
                    variant,
                    key,
                    asset_id
                )
                new_database[record["id"]] = record
        else:
            representative = next(
                (x for x in variants if x.get("image")),
                None
            )

            if representative:
                pending.append(
                    (key, variants, representative)
                )

    save_json(IMAGE_FILE, images)
    save_json(DATABASE_FILE, new_database)

    print("\nAlready mapped designs:", len(images))
    print("Designs waiting for upload:", len(pending))
    print("Database records already saved:", len(new_database))

    if not pending:
        print("\nAll designs already have images.")
        return

    print("\nChoose upload mode:")
    print("1 - Test: upload only 5 images")
    print("2 - Upload all remaining images")
    print("0 - Exit without uploading")

    choice = input("\nYour choice: ").strip()

    if choice == "0":
        print("Exited. No images uploaded.")
        return

    if choice == "1":
        upload_limit = 5
    elif choice == "2":
        print(
            "\nWARNING: This will upload "
            f"{len(pending)} images to Roblox."
        )

        confirmation = input(
            "Type UPLOAD to confirm: "
        ).strip()

        if confirmation != "UPLOAD":
            print("Cancelled.")
            return

        upload_limit = len(pending)
    else:
        print("Invalid choice.")
        return

    uploaded = 0
    failed = 0
    processed = 0

    for number, (key, variants, representative) in enumerate(
        pending[:upload_limit],
        1
    ):
        print(
            f"\n[{number}/{min(upload_limit, len(pending))}] "
            f"Uploading: {representative.get('name', key)}"
        )

        try:
            asset_id = upload_image(
                representative,
                key,
                api_key
            )

            images[key] = {
                "designKey": key,
                "name": representative.get("name", key),
                "assetId": asset_id,
                "image": f"rbxassetid://{asset_id}"
            }

            for variant in variants:
                record = make_variant_record(
                    variant,
                    key,
                    asset_id
                )
                new_database[record["id"]] = record

            save_json(IMAGE_FILE, images)
            save_json(DATABASE_FILE, new_database)

            uploaded += 1
            processed += 1

            print("OK:", asset_id)

        except KeyboardInterrupt:
            print("\nStopped by user.")
            break

        except Exception as error:
            failed += 1
            print("ERROR:", error)

            save_json(IMAGE_FILE, images)
            save_json(DATABASE_FILE, new_database)

            if "429" in str(error):
                print("Roblox rate limit. Stopping.")
                break

        time.sleep(1)

    save_json(IMAGE_FILE, images)
    save_json(DATABASE_FILE, new_database)

    print("\n" + "=" * 50)
    print("UPLOAD SESSION FINISHED")
    print("Uploaded this run:", uploaded)
    print("Failed this run:", failed)
    print("Image mappings:", len(images))
    print("Database records saved:", len(new_database))
    print("Image file:", IMAGE_FILE.resolve())
    print("Database file:", DATABASE_FILE.resolve())
    print("=" * 50)


if __name__ == "__main__":
    try:
        main()
    except requests.RequestException as error:
        print("Network error:", error)
    except Exception as error:
        print("Error:", error)

    input("\nPress Enter to close...")

