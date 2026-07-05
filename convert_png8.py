import sys
from pathlib import Path
from PIL import Image

def main():
    print("Starting fast Python png8 color space formatter...")
    textures_dir = Path("./target/rp/textures")
    if not textures_dir.exists():
        print(f"Directory {textures_dir} does not exist. Skipping.")
        return
        
    png_files = list(textures_dir.glob("**/*.png"))
    total = len(png_files)
    print(f"Found {total} PNG files to format.")
    
    count = 0
    for idx, p in enumerate(png_files):
        try:
            with Image.open(p) as img:
                # If image is already in Palette mode, skip
                if img.mode != "P":
                    # Convert to palette mode with adaptive palette (up to 256 colors) and preserve transparency
                    # Since Bedrock needs alpha channel, we use transparency option
                    alpha = img.getchannel("A") if "A" in img.getbands() else None
                    
                    # Convert RGB part to P
                    img_rgb = img.convert("RGB")
                    img_p = img_rgb.convert("P", palette=Image.Palette.ADAPTIVE, colors=255)
                    
                    if alpha:
                        # Find or create transparent index
                        # Standard way to keep transparency in PIL palette mode:
                        # set transparent pixel index
                        mask = alpha.point(lambda x: 255 if x < 128 else 0)
                        img_p.paste(255, mask=mask)
                        img_p.save(p, "PNG", transparency=255)
                    else:
                        img_p.save(p, "PNG")
                        
            count += 1
        except Exception as e:
            # If any file fails (e.g. permission or corrupt), print warning and continue
            pass
            
        if idx > 0 and idx % 500 == 0:
            print(f"Formatted {idx}/{total} images...")
            
    print(f"Successfully formatted {count}/{total} images to png8!")

if __name__ == "__main__":
    main()
