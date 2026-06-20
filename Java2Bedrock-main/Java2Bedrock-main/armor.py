import os
import json
import shutil
import glob
import sys
from jproperties import Properties

# ============================================================
# Armor Conversion for Geyser/Bedrock
# ============================================================
# This converts ItemsAdder armor items to Bedrock attachables:
# 1. Copies armor layer textures -> textures/armor_layer/
# 2. Creates .player.json attachables (armor rendering on player)
# 3. Patches the main attachable to hide 3D item when in armor slot
# ============================================================

item_type = ["leather_helmet", "leather_chestplate", "leather_leggings", "leather_boots"]
slot_names = ["helmet", "chestplate", "leggings", "boots"]

def resolve_paths():
    """
    Try to find the actual input(assets) and output(target/rp) directories.
    The converter extracts to ./assets/ and outputs to ./target/rp/,
    but this script may be called from different working directories.
    """
    candidates = [
        os.getcwd(),
        os.path.join(os.getcwd(), "staging"),
        os.path.dirname(os.path.abspath(__file__)),
    ]

    in_base = None
    out_base = None

    for c in candidates:
        # Look for the extracted Java pack
        test = os.path.join(c, "assets", "minecraft", "models", "item")
        if os.path.isdir(test):
            in_base = c
            print(f"[Armor] Input base found: {c}")
            break

        # Also check parent of staging
        test2 = os.path.join(c, "pack", "assets", "minecraft", "models", "item")
        if os.path.isdir(test2):
            in_base = os.path.join(c, "pack")
            print(f"[Armor] Input base found (pack/): {os.path.join(c, 'pack')}")
            break

    for c in candidates:
        # Look for the RP output
        test = os.path.join(c, "target", "rp", "attachables")
        if os.path.isdir(test):
            out_base = os.path.join(c, "target")
            print(f"[Armor] Output base found: {os.path.join(c, 'target')}")
            break

        test2 = os.path.join(c, "staging", "target", "rp", "attachables")
        if os.path.isdir(test2):
            out_base = os.path.join(c, "staging", "target")
            print(f"[Armor] Output base found (staging/): {os.path.join(c, 'staging', 'target')}")
            break

    if not in_base:
        print("[Armor] ERROR: Could not find input assets directory")
        print(f"[Armor] Searched in: {candidates}")
    if not out_base:
        print("[Armor] ERROR: Could not find output target directory")
        print(f"[Armor] Searched in: {candidates}")

    return in_base, out_base


def write_player_attachable(filepath, gmdl, layer_path, slot_index):
    """
    Write a .player.json Bedrock attachable for armor rendering.
    Uses the standard player armor geometry and armor render controller.
    """
    type_name = slot_names[slot_index]
    ajson = {
        "format_version": "1.10.0",
        "minecraft:attachable": {
            "description": {
                "identifier": f"geyser_custom:{gmdl}.player",
                "item": {f"geyser_custom:{gmdl}": "query.owner_identifier == 'minecraft:player'"},
                "materials": {
                    "default": "armor_leather",
                    "enchanted": "armor_leather_enchanted"
                },
                "textures": {
                    "default": f"textures/armor_layer/{layer_path}",
                    "enchanted": "textures/misc/enchanted_item_glint"
                },
                "geometry": {
                    "default": f"geometry.player.armor.{type_name}"
                },
                "scripts": {
                    "parent_setup": "variable.helmet_layer_visible = 0.0;"
                },
                "render_controllers": ["controller.render.armor"]
            }
        }
    }
    with open(filepath, "w") as f:
        json.dump(ajson, f, indent=2)
    print(f"[Armor]  -> Created player attachable: {os.path.basename(filepath)}")


def patch_main_attachable(attachable_path):
    """
    Patch the main 3D-item attachable so it does NOT render the 3D model
    when the item is equipped in an armour slot (head/chest/legs/feet).

    The .player attachable handles armour-on-player rendering instead.
    Without this patch the 3D item model (with the icon texture) renders
    on top of the armour layer, making it look like the icon is being used.
    """
    try:
        with open(attachable_path, "r") as f:
            attachable = json.load(f)
    except Exception as e:
        print(f"[Armor]  ! Could not read attachable for patching: {e}")
        return

    desc = attachable.get("minecraft:attachable", {}).get("description", {})
    scripts = desc.get("scripts", {})

    pre = scripts.get("pre_animation", [])
    if any("v.is_armor" in line for line in pre):
        return  # already patched

    # Add armour-slot detection variables
    pre.extend([
        "v.chest = c.item_slot == 'chest';",
        "v.legs = c.item_slot == 'legs';",
        "v.feet = c.item_slot == 'feet';",
        "v.is_armor = v.head || v.chest || v.legs || v.feet;",
    ])
    scripts["pre_animation"] = pre

    # Hide the 3D item when it is in any armour slot
    animate = scripts.get("animate", [])
    animate.append({"animation.geyser_custom.disable": "v.is_armor"})
    scripts["animate"] = animate
    desc["scripts"] = scripts

    # Re-point the head animation to 'disable' as well (belt-and-braces)
    anims = desc.get("animations", {})
    if "thirdperson_head" in anims:
        anims["thirdperson_head"] = "animation.geyser_custom.disable"
    desc["animations"] = anims

    with open(attachable_path, "w") as f:
        json.dump(attachable, f, indent=2)
    print(f"[Armor]  -> Patched main attachable (disabled rendering in armour slots)")


def process_armor():
    in_base, out_base = resolve_paths()
    if not in_base or not out_base:
        print("[Armor] Aborting – could not resolve base paths.")
        return

    rp_path = os.path.join(out_base, "rp")
    armor_layer_dir = os.path.join(rp_path, "textures", "armor_layer")
    os.makedirs(armor_layer_dir, exist_ok=True)

    optifine_dir = os.path.join(in_base, "assets/minecraft/optifine/cit/ia_generated_armors")

    total_processed = 0

    for i in range(4):
        item_json = os.path.join(
            in_base, "assets", "minecraft", "models", "item", f"{item_type[i]}.json"
        )
        if not os.path.isfile(item_json):
            print(f"[Armor] Skipping {item_type[i]}: file not found")
            continue

        with open(item_json, "r") as f:
            data = json.load(f)

        overrides = data.get("overrides", [])
        if not overrides:
            continue

        for override in overrides:
            try:
                predicate = override.get("predicate", {})
                custom_model_data = predicate.get("custom_model_data")
                model = override.get("model", "")
                if not custom_model_data or not model:
                    continue

                namespace = model.split(":")[0] if ":" in model else "minecraft"
                model_path_full = model.split(":")[1] if ":" in model else model
                item_name = model_path_full.split("/")[-1]

                # Skip base armour type models
                if item_name in item_type:
                    continue

                # ---- 1. Read OptiFine CIT properties ----
                optifine_file = f"{namespace}_{item_name}"
                optifine_path = os.path.join(optifine_dir, f"{optifine_file}.properties")

                if not os.path.isfile(optifine_path):
                    continue

                props = Properties()
                with open(optifine_path, "rb") as f:
                    props.load(f)

                # Layer 1 for helmet/chestplate/boots, Layer 2 for leggings
                layer_key = "texture.leather_layer_2" if i == 2 else "texture.leather_layer_1"
                layer_prop = props.get(layer_key)

                if not layer_prop:
                    continue

                # The layer value may be "armor/set/name.png" or just "name"
                raw = str(layer_prop.data)
                layer_texture = raw.split(".")[0] if "." in raw else raw
                layer_basename = os.path.basename(layer_texture)

                # ---- 2. Copy armour layer PNG to RP ----
                # Search in the optifine dir (may be nested or flat)
                layer_png_dest = os.path.join(armor_layer_dir, f"{layer_basename}.png")
                if not os.path.exists(layer_png_dest):
                    found = False
                    # Try the exact sub-path first
                    exact_src = os.path.join(optifine_dir, f"{layer_texture}.png")
                    if os.path.isfile(exact_src):
                        shutil.copy2(exact_src, layer_png_dest)
                        found = True
                    else:
                        # Walk the optifine dir looking for the basename
                        for root, _dirs, files in os.walk(optifine_dir):
                            for fn in files:
                                if fn == f"{layer_basename}.png":
                                    shutil.copy2(os.path.join(root, fn), layer_png_dest)
                                    found = True
                                    break
                            if found:
                                break
                    if found:
                        print(f"[Armor]  -> Copied armour layer: {layer_basename}.png")
                    else:
                        print(f"[Armor]  ! Armour layer PNG not found: {layer_texture}.png")

                # ---- 3. Copy item texture for the atlas ----
                model_json = os.path.join(
                    in_base, "assets", namespace, "models", f"{model_path_full}.json"
                )
                if os.path.isfile(model_json):
                    with open(model_json, "r") as f:
                        mm = json.load(f)
                    tex = mm.get("textures", {}).get("layer1", "")
                    if tex and ":" in tex:
                        tpath = tex.split(":")[1]
                        tex_src = os.path.join(
                            in_base, "assets", namespace, "textures", f"{tpath}.png"
                        )
                        if os.path.isfile(tex_src):
                            tex_dst_dir = os.path.join(
                                rp_path, "textures", namespace,
                                os.path.dirname(model_path_full)
                            )
                            os.makedirs(tex_dst_dir, exist_ok=True)
                            tex_dst = os.path.join(
                                tex_dst_dir, f"{os.path.basename(model_path_full)}.png"
                            )
                            if not os.path.exists(tex_dst):
                                shutil.copy2(tex_src, tex_dst)

                # ---- 4. Find the main attachable ----
                # Try namespace-scoped path first, then flat
                search_paths = [
                    os.path.join(rp_path, "attachables", namespace, model_path_full),
                    os.path.join(rp_path, "attachables", model_path_full),
                ]
                attachable_file = None
                for sp in search_paths:
                    matches = sorted(glob.glob(f"{sp}*.attachable.json"))
                    if matches:
                        attachable_file = matches[0]
                        break

                if not attachable_file:
                    # Last resort: scan all attachables (slow)
                    matches = sorted(glob.glob(
                        os.path.join(rp_path, "attachables", "**", f"{model_path_full}*.attachable.json"),
                        recursive=True
                    ))
                    if matches:
                        attachable_file = matches[0]
                    else:
                        print(f"[Armor]  ! No attachable found for {model_path_full}")
                        continue

                # ---- 5. Extract Geyser identifier ----
                with open(attachable_file, "r") as f:
                    adata = json.load(f)
                gmdl = adata["minecraft:attachable"]["description"]["identifier"].split(":")[1]

                # ---- 6. Create .player attachable ----
                player_file = attachable_file.replace(".attachable.json", ".attachable.player.json")
                if not os.path.exists(player_file):
                    write_player_attachable(
                        player_file, gmdl, layer_basename, i
                    )
                else:
                    print(f"[Armor]  ~ Player attachable already exists: {os.path.basename(player_file)}")

                # ---- 7. Patch the main attachable ----
                patch_main_attachable(attachable_file)

                total_processed += 1

            except Exception as e:
                print(f"[Armor]  ! Error processing {override.get('model', '?')}: {e}")
                continue

    print(f"[Armor] Done. Processed {total_processed} armour piece(s).")


if __name__ == "__main__":
    process_armor()
