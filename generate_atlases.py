import json
import os
import sys
from pathlib import Path
from PIL import Image

def main():
    print("Starting fast Python sprite sheet compiler...")
    
    union_atlas_path = Path("scratch_files/union_atlas.temp")
    all_textures_path = Path("scratch_files/all_textures.temp")
    
    if not union_atlas_path.exists():
        print(f"ERROR: {union_atlas_path} does not exist!")
        sys.exit(1)
        
    try:
        with open(union_atlas_path, "r", encoding="utf-8") as f:
            union_atlas = json.load(f)
    except Exception as e:
        print(f"ERROR reading union_atlas: {e}")
        sys.exit(1)
        
    try:
        with open(all_textures_path, "r", encoding="utf-8") as f:
            all_textures = set(json.load(f))
    except Exception:
        all_textures = set()

    spritesheet_dir = Path("scratch_files/spritesheet")
    spritesheet_dir.mkdir(exist_ok=True)
    
    atlases = []
    
    fallback_path = Path("./assets/minecraft/textures/0.png")
    fallback_img = None
    if fallback_path.exists():
        try:
            fallback_img = Image.open(fallback_path).convert("RGBA")
        except Exception:
            pass

    for i, tex_group in enumerate(union_atlas):
        # Find which textures actually exist
        existing_paths = []
        fallback_needed = False
        
        for tex_path in tex_group:
            p = Path(tex_path)
            if p.exists() and p.is_file():
                existing_paths.append(p)
            else:
                fallback_needed = True
                
        # Load images
        images = []
        for p in existing_paths:
            try:
                images.append(Image.open(p).convert("RGBA"))
            except Exception as e:
                print(f"Warning: failed to load {p}: {e}")
                
        if fallback_needed or not images:
            if fallback_img:
                images.append(fallback_img)
            else:
                # Create a 16x16 transparent image if no fallback available
                images.append(Image.new("RGBA", (16, 16), (0, 0, 0, 0)))
                
        # Stitch images horizontally
        widths = [img.size[0] for img in images]
        heights = [img.size[1] for img in images]
        total_width = sum(widths)
        max_height = max(heights)
        
        stitched = Image.new("RGBA", (total_width, max_height))
        x_offset = 0
        for img in images:
            stitched.paste(img, (x_offset, 0))
            x_offset += img.size[0]
            
        # Save sheet
        dest = spritesheet_dir / f"{i}.png"
        try:
            stitched.save(dest, "PNG")
            atlases.append(str(i))
        except Exception as e:
            print(f"ERROR saving spritesheet {i}: {e}")
            sys.exit(1)
            
        if i % 100 == 0:
            print(f"Compiled {i}/{len(union_atlas)} sprite sheets...")

    # Write atlases.csv
    try:
        with open("scratch_files/atlases.csv", "w", encoding="utf-8") as f:
            f.write("\n".join(atlases) + "\n")
    except Exception as e:
        print(f"ERROR writing atlases.csv: {e}")
        sys.exit(1)
        
    print(f"Successfully compiled {len(union_atlas)} sprite sheets in Python!")

if __name__ == "__main__":
    main()
