#!/usr/bin/env python3
"""
ItemsAdder armor converter for java2bedrock.sh.
Reads ItemsAdder armors.yml configs directly instead of OptiFine .properties files.
Generates proper .player attachables so armor renders as 3D layer textures on the player model,
not the item icon.

Usage: python armor.py <contents_dir>
  contents_dir: path to ItemsAdder contents/ directory containing armors.yml configs
"""

import os, json, shutil, glob, sys
from pathlib import Path

# Try to load yaml, if not available, provide clear error
try:
    import yaml
except ImportError:
    print("[ERROR] PyYAML is required. Install with: pip install pyyaml")
    sys.exit(1)

ARMOR_SLOTS = ["leather_helmet", "leather_chestplate", "leather_leggings", "leather_boots"]
SLOT_GEOMETRY = {
    0: "geometry.player.armor.helmet",
    1: "geometry.player.armor.chestplate",
    2: "geometry.player.armor.leggings",
    3: "geometry.player.armor.boots",
}
SLOT_NAMES = ["helmet", "chestplate", "leggings", "boots"]


def load_armor_configs(contents_dir: str) -> dict:
    """Load all armors*.yml files and build item -> equipment -> layer texture maps."""
    contents = Path(contents_dir)
    if not contents.exists():
        print(f"[WARN] Contents dir not found: {contents_dir}")
        return {}

    configs = {}

    for armors_file in sorted(contents.rglob("armors*.yml")):
        try:
            with open(armors_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if not data:
                continue

            namespace = data.get("info", {}).get("namespace", "")
            if not namespace:
                continue

            equipments = data.get("equipments", {})
            items = data.get("items", {})

            ns_eq = {}
            for eq_id, eq_data in equipments.items():
                ns_eq[eq_id] = {
                    "layer_1": eq_data.get("layer_1", ""),
                    "layer_2": eq_data.get("layer_2", ""),
                }

            ns_items = {}
            for item_name, item_data in items.items():
                eq_info = item_data.get("equipment", {})
                eq_id = eq_info.get("id", "")
                slot = eq_info.get("slot", "")
                if eq_id and slot:
                    ns_items[item_name] = {
                        "equipment_id": eq_id,
                        "slot": slot,
                    }

            if ns_items:
                configs[namespace] = {"equipments": ns_eq, "items": ns_items}
                print(f"  [OK] {armors_file.name} ({namespace}): {len(ns_items)} items")

        except Exception as e:
            print(f"  [ERR] {armors_file.name}: {e}")

    return configs


def write_player_attachable(file_path: str, gmdl: str, layer_name: str, slot_index: int):
    """Write a .player attachable JSON for armor rendering on the player model."""
    geometry = SLOT_GEOMETRY.get(slot_index, "geometry.player.armor.helmet")
    ajson = {
        "format_version": "1.10.0",
        "minecraft:attachable": {
            "description": {
                "identifier": f"geyser_custom:{gmdl}.player",
                "item": {f"geyser_custom:{gmdl}": "query.owner_identifier == 'minecraft:player'"},
                "materials": {
                    "default": "armor_leather",
                    "enchanted": "armor_leather_enchanted",
                },
                "textures": {
                    "default": f"textures/armor_layer/{layer_name}",
                    "enchanted": "textures/misc/enchanted_item_glint",
                },
                "geometry": {"default": geometry},
                "scripts": {"parent_setup": "variable.helmet_layer_visible = 0.0;"},
                "render_controllers": ["controller.render.armor"],
            }
        },
    }
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "w") as f:
        json.dump(ajson, f)


def main():
    if len(sys.argv) < 2:
        print("Usage: python armor.py <contents_dir>")
        sys.exit(1)

    contents_dir = sys.argv[1]
    pack_dir = "pack"
    staging_dir = "staging"

    print("[ARMOR] Loading ItemsAdder armor configs...")
    configs = load_armor_configs(contents_dir)

    if not configs:
        print("[WARN] No ItemsAdder armor configs found. Nothing to convert.")
        return

    armor_layer_dir = Path(staging_dir) / "target" / "rp" / "textures" / "armor_layer"
    armor_layer_dir.mkdir(parents=True, exist_ok=True)

    total_processed = 0
    total_errors = 0

    for slot_idx, (item_type, slot_name) in enumerate(zip(ARMOR_SLOTS, SLOT_NAMES)):
        item_file = Path(pack_dir) / "assets" / "minecraft" / "models" / "item" / f"{item_type}.json"
        if not item_file.exists():
            continue

        with open(item_file, "r") as f:
            data = json.load(f)

        overrides = data.get("overrides", [])
        print(f"\n[{slot_name.upper()}] {len(overrides)} items")

        for override in overrides:
            try:
                model = override.get("model", "")
                if not model:
                    continue

                namespace = model.split(":")[0]
                model_path = model.split(":")[1]
                item_name = model_path.split("/")[-1]

                if item_name in ARMOR_SLOTS:
                    continue

                # Look up this item in configs
                ns_config = configs.get(namespace)
                if not ns_config:
                    continue

                items = ns_config.get("items", {})
                equipments = ns_config.get("equipments", {})

                # Find matching item (try exact, then prefix match for color variants)
                matched_item = items.get(item_name)
                if not matched_item:
                    for cfg_name, cfg_item in items.items():
                        if cfg_name.startswith(item_name):
                            matched_item = cfg_item
                            break

                if not matched_item:
                    # Try the other direction: item_name might be longer (color variant)
                    for cfg_name, cfg_item in items.items():
                        if item_name.startswith(cfg_name):
                            matched_item = cfg_item
                            break

                if not matched_item:
                    # Try suffix match: cfg key ends with model name (roman_armor_* items)
                    for cfg_name, cfg_item in items.items():
                        if cfg_name.endswith(item_name):
                            matched_item = cfg_item
                            break

                if not matched_item:
                    continue

                eq_id = matched_item["equipment_id"]
                eq_data = equipments.get(eq_id)
                if not eq_data:
                    continue

                # Determine which layer to use
                layer_key = "layer_2" if slot_idx == 2 else "layer_1"
                layer_path = eq_data.get(layer_key, "")
                if not layer_path:
                    continue

                # Find the armor layer PNG in the Java pack
                # Try old format path first: assets/{ns}/textures/{layer_path}.png
                layer_png = Path(pack_dir) / "assets" / namespace / "textures" / f"{layer_path}.png"
                found_png = layer_png if layer_png.exists() else None

                if not found_png:
                    # Try modern ItemsAdder overlay format (1.21.2+)
                    # Textures are in ia_overlay_*/assets/{ns}/textures/entity/equipment/humanoid/
                    # Named by equipment ID, not by layer_path
                    layer_sub = "humanoid_leggings" if layer_key == "layer_2" else "humanoid"
                    for overlay_dir in sorted(Path(pack_dir).glob("ia_overlay_*/")):
                        # Try equipment ID name first
                        p = overlay_dir / "assets" / namespace / "textures" / "entity" / "equipment" / layer_sub / f"{eq_id}.png"
                        if p.exists():
                            found_png = p
                            break
                        # Try basename of layer_path
                        layer_base = Path(layer_path).name
                        p = overlay_dir / "assets" / namespace / "textures" / "entity" / "equipment" / layer_sub / f"{layer_base}.png"
                        if p.exists():
                            found_png = p
                            break
                        # Try old path inside overlay
                        p = overlay_dir / "assets" / namespace / "textures" / f"{layer_path}.png"
                        if p.exists():
                            found_png = p
                            break

                if not found_png:
                    print(f"  [SKIP] {item_name}: layer PNG not found for eq={eq_id} ({layer_path})")
                    total_errors += 1
                    continue

                # Copy to armor_layer directory
                layer_name = f"{namespace}_{eq_id}"
                layer_dest = armor_layer_dir / f"{layer_name}.png"
                if not layer_dest.exists():
                    shutil.copy2(found_png, layer_dest)

                # Find existing attachable for this item
                # Try nested format first: attachables/{namespace}/{model_path}/*.json
                attachable_pattern = f"{staging_dir}/target/rp/attachables/{namespace}/{model_path}*.json"
                afiles = glob.glob(attachable_pattern)
                afile = next((f for f in afiles if not f.endswith(".player.json")), None)
                if not afile:
                    # Try flat format (after consolidate_files): attachables/{model_name}*.json
                    item_filename = Path(model_path).name
                    flat_pattern = f"{staging_dir}/target/rp/attachables/{item_filename}*.json"
                    afiles = glob.glob(flat_pattern)
                    afile = next((f for f in afiles if not f.endswith(".player.json")), None)
                if not afile:
                    print(f"  [SKIP] {item_name}: no attachable found")
                    total_errors += 1
                    continue

                with open(afile, "r") as f:
                    attach_data = json.load(f)
                gmdl = attach_data["minecraft:attachable"]["description"]["identifier"].split(":")[1]

                # Generate .player attachable
                pfile = afile.replace(".json", ".player.json")
                write_player_attachable(pfile, gmdl, layer_name, slot_idx)
                print(f"  [OK]   {item_name} -> {layer_name} (gmdl={gmdl})")
                total_processed += 1

            except Exception as e:
                print(f"  [ERR]  {override.get('model', '?')}: {e}")
                total_errors += 1

    print(f"\n{'='*50}")
    print(f"Armor conversion: {total_processed} OK, {total_errors} errors")


if __name__ == "__main__":
    main()
