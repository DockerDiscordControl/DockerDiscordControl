#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mech Sprite Encoder/Decoder - Simple obfuscation to hide spoilers
Not meant for security, just to prevent accidental spoilers!
"""

import base64
import os
from pathlib import Path
from PIL import Image
import io

def encode_sprite_to_file(image_path: str, output_path: str):
    """
    Encode a PNG sprite to a .mech file (base64 encoded)
    
    Args:
        image_path: Path to the PNG sprite
        output_path: Path for the .mech output file
    """
    with open(image_path, 'rb') as img_file:
        img_data = img_file.read()
    
    # Add a simple header to make it less obvious
    header = b"MECH_SPRITE_V1:"
    encoded = base64.b64encode(header + img_data)
    
    # Save with .mech extension
    with open(output_path, 'wb') as out_file:
        out_file.write(encoded)
    
    print(f"Encoded {image_path} -> {output_path}")

def decode_sprite_from_file(mech_file_path: str) -> Image.Image:
    """
    Decode a .mech file back to a PIL Image
    
    Args:
        mech_file_path: Path to the .mech file
        
    Returns:
        PIL Image object
    """
    try:
        with open(mech_file_path, 'rb') as mech_file:
            encoded_data = mech_file.read()
        
        # Decode base64
        decoded = base64.b64decode(encoded_data)
        
        # Remove header
        header = b"MECH_SPRITE_V1:"
        if decoded.startswith(header):
            img_data = decoded[len(header):]
        else:
            img_data = decoded  # Fallback if no header
        
        # Convert to PIL Image
        return Image.open(io.BytesIO(img_data))
    
    except Exception as e:
        print(f"Error decoding {mech_file_path}: {e}")
        return None

def encode_all_sprites():
    """
    Encode all mech sprites in the static directory
    """
    static_dir = Path("app/static")
    sprites_dir = static_dir / "mech_sprites"
    encoded_dir = static_dir / "mechs"
    
    # Create encoded directory
    encoded_dir.mkdir(exist_ok=True)
    
    # Process each level
    for level in range(1, 12):
        sprite_path = sprites_dir / f"mech_level_{level}.png"
        encoded_path = encoded_dir / f"lvl_{level}.mech"
        
        if sprite_path.exists():
            encode_sprite_to_file(str(sprite_path), str(encoded_path))
        else:
            print(f"Warning: {sprite_path} not found")
    
    # Also encode the default sprite if it exists
    default_sprite = static_dir / "animatedmech.png"
    if default_sprite.exists():
        encode_sprite_to_file(str(default_sprite), str(encoded_dir / "default.mech"))

def decode_all_sprites():
    """
    Decode all .mech files for testing
    """
    encoded_dir = Path("app/static/mechs")
    test_dir = Path("app/static/test_decoded")
    
    # Create test directory
    test_dir.mkdir(exist_ok=True)
    
    for mech_file in encoded_dir.glob("*.mech"):
        img = decode_sprite_from_file(str(mech_file))
        if img:
            output_path = test_dir / f"{mech_file.stem}_decoded.png"
            img.save(str(output_path))
            print(f"Decoded {mech_file} -> {output_path}")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "encode":
            encode_all_sprites()
        elif sys.argv[1] == "decode":
            decode_all_sprites()
        else:
            print("Usage: python mech_sprite_encoder.py [encode|decode]")
    else:
        print("Usage: python mech_sprite_encoder.py [encode|decode]")