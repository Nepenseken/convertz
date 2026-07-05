import json
import os
import shutil
from pathlib import Path

def get_texture_0(textures):
    if isinstance(textures, dict):
        if not textures:
            return None
        val = list(textures.values())[0]
    elif isinstance(textures, list):
        if not textures:
            return None
        val = textures[0]
    elif isinstance(textures, str):
        val = textures
    else:
        return None
    
    if not val or not isinstance(val, str):
        return None
    
    if ":" in val:
        ns, path = val.split(":", 1)
    else:
        ns, path = "minecraft", val
    return f"./assets/{ns}/textures/{path}.png"

def main():
    config_path = Path("config.json")
    if not config_path.exists():
        print("config.json not found!")
        return

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    # Let's ensure directories exist
    os.makedirs("scratch_files", exist_ok=True)

    # Open CSV files for writing
    icons_f = open("scratch_files/icons.csv", "w", encoding="utf-8")
    generated_f = open("scratch_files/generated.csv", "w", encoding="utf-8")
    deleted_f = open("scratch_files/deleted.csv", "w", encoding="utf-8")

    # Read parented entries
    parented_entries = []
    for gid, entry in config.items():
        if entry.get("parent") is not None:
            parented_entries.append(entry)

    total = len(parented_entries)
    print(f"Resolving parental info for {total} child models...")

    # We can cache file JSON loads to avoid reading the same file 1000 times
    json_cache = {}
    
    def load_json(path_str):
        if path_str in json_cache:
            return json_cache[path_str]
        p = Path(path_str)
        if not p.exists():
            json_cache[path_str] = None
            return None
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            json_cache[path_str] = data
            return data
        except Exception:
            json_cache[path_str] = None
            return None

    for idx, entry in enumerate(parented_entries, 1):
        gid = entry.get("geyserID")
        file_path_str = entry.get("path")
        initial_parental = entry.get("parent")
        namespace = entry.get("namespace")
        model_path = entry.get("model_path")
        model_name = entry.get("model_name")
        path_hash = entry.get("path_hash")

        # Trace inheritance
        elements = None
        textures = None
        display = None

        # Load child model file first
        child_data = load_json(file_path_str)
        if child_data is not None:
            elements = child_data.get("elements")
            textures = child_data.get("textures")
            display = child_data.get("display")

        parental = initial_parental
        visited = set()

        while True:
            # Stop conditions
            if (elements is not None and textures is not None and display is not None) or \
               (parental == "./assets/minecraft/models/builtin/generated.json") or \
               (parental is None or parental == "./assets/minecraft/models/.json" or parental == "null"):
                break

            if parental in visited:
                # Cycle detected
                break
            visited.add(parental)

            parent_data = load_json(parental)
            if parent_data is None:
                break

            if elements is None:
                elements = parent_data.get("elements")
            if textures is None:
                textures = parent_data.get("textures")
            if display is None:
                display = parent_data.get("display")

            # Get next parent
            p_val = parent_data.get("parent")
            if p_val and isinstance(p_val, str):
                ns, name = p_val.split(":", 1) if ":" in p_val else ("minecraft", p_val)
                parental = f"./assets/{ns}/models/{name}.json"
            else:
                parental = None

        # Determine outcome
        resolved = False
        if elements is not None and textures is not None:
            # Case 1: 3D model
            output_data = {
                "textures": textures,
                "elements": elements
            }
            if display is not None:
                output_data["display"] = display

            # Write file
            try:
                with open(file_path_str, "w", encoding="utf-8") as f:
                    json.dump(output_data, f, indent=2)
                json_cache[file_path_str] = output_data
                resolved = True
            except Exception as e:
                print(f"Error writing 3D model file {file_path_str}: {e}")

        elif textures is not None and parental == "./assets/minecraft/models/builtin/generated.json":
            # Case 2: 2D generated model
            texture_0 = get_texture_0(textures)
            if texture_0 and Path(texture_0).exists():
                first_tex_val = None
                if isinstance(textures, dict):
                    first_tex_val = list(textures.values())[0] if textures else None
                elif isinstance(textures, list):
                    first_tex_val = textures[0] if textures else None
                else:
                    first_tex_val = textures

                output_data = {
                    "textures": first_tex_val
                }
                if display is not None:
                    output_data["display"] = display

                try:
                    with open(file_path_str, "w", encoding="utf-8") as f:
                        json.dump(output_data, f, indent=2)
                    json_cache[file_path_str] = output_data
                    
                    # copy texture to target
                    dest_dir = Path(f"./target/rp/textures/{namespace}/{model_path}")
                    dest_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copy(texture_0, dest_dir / f"{model_name}.png")

                    # write CSV logs
                    path_str = f"textures/{namespace}/{model_path}/{model_name}".replace("//", "/")
                    icons_f.write(f"{path_hash},{path_str}\n")
                    generated_f.write(f"{gid}\n")
                    resolved = True
                except Exception as e:
                    print(f"Error resolving 2D model file {file_path_str}: {e}")

        if not resolved:
            # Case 3: delete/unsuitable
            deleted_f.write(f"{gid}\n")

        # Print progress occasionally
        if idx % 1000 == 0 or idx == total:
            print(f"Processed {idx}/{total} models...")

    icons_f.close()
    generated_f.close()
    deleted_f.close()
    
    # write count.csv
    with open("scratch_files/count.csv", "w", encoding="utf-8") as f:
        f.write("\n" * total)

    print("Parental sweep completed successfully in Python!")

if __name__ == "__main__":
    main()
