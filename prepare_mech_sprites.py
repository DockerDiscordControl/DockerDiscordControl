#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Prepare Mech Sprites - Helper script to encode/prepare mech graphics

Usage:
    python prepare_mech_sprites.py encode  # Encode all PNGs to .mech files
    python prepare_mech_sprites.py test    # Test the encoding/decoding
    python prepare_mech_sprites.py create  # Create placeholder sprites
"""

import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from utils.mech_sprite_encoder import encode_sprite_to_file, decode_sprite_from_file

def create_placeholder_sprites():
    """Create placeholder sprites for each mech level"""
    
    # Create directories
    sprites_dir = Path("app/static/mech_sprites")
    sprites_dir.mkdir(exist_ok=True)
    
    mechs_dir = Path("app/static/mechs")
    mechs_dir.mkdir(exist_ok=True)
    
    # Mech names for each level
    mech_names = {
        1: "SCRAP",
        2: "REPAIRED",
        3: "STANDARD",
        4: "ENHANCED",
        5: "ADVANCED",
        6: "ELITE",
        7: "CYBER",
        8: "PLASMA",
        9: "QUANTUM",
        10: "DIVINE",
        11: "OMEGA"
    }
    
    # Colors for each level (getting progressively cooler)
    mech_colors = {
        1: (100, 100, 100),   # Dark gray
        2: (120, 120, 120),   # Gray
        3: (150, 150, 150),   # Light gray
        4: (100, 150, 200),   # Blue
        5: (100, 200, 250),   # Cyan
        6: (250, 200, 100),   # Gold
        7: (250, 150, 100),   # Orange
        8: (200, 100, 250),   # Purple
        9: (100, 250, 250),   # Bright cyan
        10: (250, 250, 100),  # Bright yellow
        11: (250, 100, 250)   # Magenta
    }
    
    for level in range(1, 12):
        # Create a 2x3 grid spritesheet (1024x1024 like the original)
        spritesheet = Image.new('RGBA', (1024, 1024), (0, 0, 0, 0))
        draw = ImageDraw.Draw(spritesheet)
        
        sprite_width = 1024 // 3
        sprite_height = 1024 // 2
        
        color = mech_colors[level]
        name = mech_names[level]
        
        # Draw 6 frames (slightly different positions for animation)
        for frame in range(6):
            col = frame % 3
            row = frame // 3
            
            x = col * sprite_width + sprite_width // 2
            y = row * sprite_height + sprite_height // 2
            
            # Draw a simple mech shape
            # Body
            body_offset = frame * 2  # Slight animation
            draw.rectangle([x-40, y-30+body_offset, x+40, y+50+body_offset], 
                          fill=color, outline=(255, 255, 255, 255), width=2)
            
            # Head
            draw.ellipse([x-25, y-50+body_offset, x+25, y-10+body_offset], 
                        fill=color, outline=(255, 255, 255, 255), width=2)
            
            # Eyes (different for each level)
            if level <= 3:
                # Dead/dim eyes for low levels
                eye_color = (50, 50, 50)
            elif level <= 6:
                # Blue eyes for mid levels
                eye_color = (100, 200, 255)
            elif level <= 9:
                # Bright eyes for high levels
                eye_color = (255, 255, 100)
            else:
                # Rainbow/special for omega
                eye_color = (255, 100, 255)
            
            draw.ellipse([x-15, y-35+body_offset, x-5, y-25+body_offset], fill=eye_color)
            draw.ellipse([x+5, y-35+body_offset, x+15, y-25+body_offset], fill=eye_color)
            
            # Arms
            draw.line([x-40, y-10+body_offset, x-60, y+10+body_offset], 
                     fill=color, width=8)
            draw.line([x+40, y-10+body_offset, x+60, y+10+body_offset], 
                     fill=color, width=8)
            
            # Legs
            draw.line([x-20, y+50+body_offset, x-25, y+80+body_offset], 
                     fill=color, width=10)
            draw.line([x+20, y+50+body_offset, x+25, y+80+body_offset], 
                     fill=color, width=10)
            
            # Level indicator
            try:
                # Try to use a font, fallback to simple text if not available
                font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 20)
            except:
                font = None
            
            draw.text((x-30, y+90+body_offset), f"L{level}-{name}", 
                     fill=(255, 255, 255, 255), font=font)
        
        # Save as PNG
        png_path = sprites_dir / f"mech_level_{level}.png"
        spritesheet.save(str(png_path))
        print(f"Created placeholder sprite: {png_path}")
        
        # Encode to .mech file
        mech_path = mechs_dir / f"lvl_{level}.mech"
        encode_sprite_to_file(str(png_path), str(mech_path))
        print(f"Encoded to: {mech_path}")
    
    # Also encode the default sprite if it exists
    default_sprite = Path("app/static/animatedmech.png")
    if default_sprite.exists():
        default_mech = mechs_dir / "default.mech"
        encode_sprite_to_file(str(default_sprite), str(default_mech))
        print(f"Encoded default sprite to: {default_mech}")

def test_encoding():
    """Test that encoding and decoding works"""
    mechs_dir = Path("app/static/mechs")
    
    if not mechs_dir.exists():
        print("No mechs directory found. Run 'create' first.")
        return
    
    for mech_file in mechs_dir.glob("*.mech"):
        print(f"Testing {mech_file}...")
        img = decode_sprite_from_file(str(mech_file))
        if img:
            print(f"  ✓ Successfully decoded: {img.size}")
        else:
            print(f"  ✗ Failed to decode")

def main():
    if len(sys.argv) < 2:
        print("Usage: python prepare_mech_sprites.py [create|encode|test]")
        return
    
    command = sys.argv[1]
    
    if command == "create":
        create_placeholder_sprites()
    elif command == "encode":
        from utils.mech_sprite_encoder import encode_all_sprites
        encode_all_sprites()
    elif command == "test":
        test_encoding()
    else:
        print(f"Unknown command: {command}")
        print("Usage: python prepare_mech_sprites.py [create|encode|test]")

if __name__ == "__main__":
    main()