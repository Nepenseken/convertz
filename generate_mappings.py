import sys
import json
from pathlib import Path

def main():
    print("Starting fast Python Geyser mappings generator...")
    generate_3d_icons = True
    if len(sys.argv) > 1 and sys.argv[1].lower() == "false":
        generate_3d_icons = False

    config_path = Path("config.json")
    if not config_path.exists():
        print("ERROR: config.json not found!")
        return
        
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except Exception as e:
        print(f"ERROR reading config.json: {e}")
        return
        
    items = {}
    for key, entry in config.items():
        item_type = entry.get("item")
        path_hash = entry.get("path_hash")
        nbt = entry.get("nbt", {})
        
        if not item_type or not path_hash:
            continue
            
        full_key = f"minecraft:{item_type}"
        mapping = {
            "name": path_hash,
            "allow_offhand": True,
            "icon": path_hash if generate_3d_icons else item_type
        }
        
        if "CustomModelData" in nbt:
            mapping["custom_model_data"] = int(nbt["CustomModelData"])
        if "Damage" in nbt:
            mapping["damage_predicate"] = int(nbt["Damage"])
        if "Unbreakable" in nbt:
            mapping["unbreakable"] = bool(nbt["Unbreakable"])
            
        if full_key not in items:
            items[full_key] = []
        items[full_key].append(mapping)
        
    mappings_data = {
        "format_version": "1",
        "items": items
    }
    
    dest = Path("./target/geyser_mappings.json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(mappings_data, f, ensure_ascii=False, separators=(",", ":"))
        print("Successfully generated geyser_mappings.json!")
    except Exception as e:
        print(f"ERROR writing mappings: {e}")

if __name__ == "__main__":
    main()
