# convertz postfix for ItemsAdder armor/weapon packs

This post-conversion fixer is intended for packs where `convertz` produces:

- 3D armor item icons but missing player armor layers.
- swords/weapons with broken or mixed textures because Java `texture_size` was flattened to `16x16`.
- ItemsAdder packs that contain both root `assets/` and `contents/*/resource_pack/assets/` copies, where the root copy is stale or wrong.
- animated 3D item models that do not translate cleanly to Bedrock/Geyser.

## Usage

Run the normal converter first, then run:

```bash
python3 convertz_postfix.py packtwin.zip geyser_resources.mcpack -o geyser_resources.fixed.mcpack
```

The script writes a fixed `.mcpack` and a `*.postfix-report.txt` report.

## What it changes

1. Reads Java model JSON from the original ItemsAdder/source pack.
2. Prioritizes `contents/*/resource_pack/assets/` over root `assets/`.
3. Restores Bedrock geometry `texture_width` / `texture_height` from Java `texture_size`.
4. Generates missing `.player` armor attachables when it can infer the equipment layer from ItemsAdder overlay equipment JSON.
5. Reports animated 3D model candidates instead of pretending they are fully supported.

