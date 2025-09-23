# Mech Animation VFX System Plan

## Overview
Enhanced animation system using VFX maps to precisely control particle effects, smoke, and other visual enhancements for the Mech evolution system.

## Asset Structure
```
/assets/mech/
├── frames/       # mech_01.png to mech_06.png (base animation frames)
├── vfx_maps/     # vfx_01.png to vfx_06.png (effect placement maps)
└── effects/      # smoke.png, sparks.png, energy.png, etc.
```

## VFX Map Color Coding
Each VFX map uses specific colors to indicate where effects should spawn:

| Color | Hex Code | Effect Type | Description |
|-------|----------|-------------|-------------|
| 🔴 RED | #FF0000 | Smoke/Steam/Heat | Exhaust ports, vents, overheating parts |
| 🟢 GREEN | #00FF00 | Sparks/Electric | Joints, damaged areas, friction points |
| 🔵 BLUE | #0000FF | Energy/Plasma | Weapons, reactor, eyes, power cores |
| 🟡 YELLOW | #FFFF00 | Light/Glow | Lights, displays, warning indicators |
| 🟣 PURPLE | #FF00FF | Dust/Debris | Feet contact, ground effects |
| 🟠 ORANGE | #FF8800 | Fire/Explosion | Weapon fire, damage effects |

### Intensity Control via Color Brightness
- **Full brightness (255)**: Maximum effect intensity
- **Half brightness (128)**: Reduced effect intensity
- **Quarter brightness (64)**: Minimal effect intensity

Example:
- `rgb(255,0,0)` = Heavy smoke
- `rgb(128,0,0)` = Light smoke
- `rgb(64,0,0)` = Wisps of smoke

## Effect Behavior Configuration

### Speed Independence
Animation speed increases with power/donations, but effect intensity remains consistent:

```python
# Animation speed scales with power
animation_fps = base_fps * (1 + power_level * 0.1)

# Effect intensity is independent
effect_config = {
    "sparks": {
        "trigger": "always",         # Always active
        "intensity": 0.7,            # Constant intensity
        "frequency": "per_frame"     # Every frame
    },
    "smoke": {
        "trigger": "movement",       # Only during movement
        "intensity": power_level/10, # Scales with mech level
        "frequency": "continuous"    # Continuous emission
    },
    "dust": {
        "trigger": "foot_contact",   # Only on ground impact
        "intensity": 1.0,            # Always full intensity
        "frequency": "on_impact"     # Only at impact moment
    }
}
```

## Implementation Phases

### Phase 1: Basic VFX System
- [x] Color detection from VFX maps
- [ ] Basic particle spawning at colored positions
- [ ] Frame synchronization

### Phase 2: Effect Library
- [ ] Smoke particle system
- [ ] Spark generator
- [ ] Energy glow effects
- [ ] Dust clouds
- [ ] Light flares

### Phase 3: Advanced Features
- [ ] Particle physics (gravity, wind)
- [ ] Effect blending and layering
- [ ] Performance optimization (particle pooling)
- [ ] Level-based effect scaling

### Phase 4: Polish
- [ ] Motion blur for fast-moving mechs
- [ ] Heat distortion effects
- [ ] Screen shake on heavy steps
- [ ] Environmental interactions

## Technical Implementation

### VFX Map Processing
```python
def process_vfx_map(vfx_image, frame_number):
    """Process VFX map and return effect positions"""
    effects = {
        'smoke': [],
        'sparks': [],
        'energy': [],
        'lights': [],
        'dust': [],
        'fire': []
    }
    
    # Scan VFX map pixels
    for x in range(vfx_image.width):
        for y in range(vfx_image.height):
            pixel = vfx_image.getpixel((x, y))
            
            # Check color and intensity
            if pixel[0] > 128 and pixel[1] < 50:  # Red channel dominant
                intensity = pixel[0] / 255.0
                effects['smoke'].append({
                    'position': (x, y),
                    'intensity': intensity
                })
            # ... similar for other colors
    
    return effects
```

### Effect Rendering Pipeline
1. Load base mech frame
2. Load corresponding VFX map
3. Process VFX map for effect positions
4. Generate particles at marked positions
5. Apply particle physics/animation
6. Composite effects onto base frame
7. Apply post-processing (blur, glow)
8. Output final frame

## Performance Considerations

### Optimization Strategies
- **Particle Pooling**: Reuse particle objects instead of creating new ones
- **LOD System**: Reduce particles for smaller mech levels
- **Caching**: Pre-generate common effects
- **Smart Culling**: Don't render off-screen particles
- **Frame Caching**: Cache completed frames for common states

### Target Performance
- 60 FPS for web display
- < 500KB final animation size
- < 100ms generation time per frame
- Support for mobile devices

## File Naming Convention
```
mech_01.png    -> vfx_01.png
mech_02.png    -> vfx_02.png
mech_03.png    -> vfx_03.png
mech_04.png    -> vfx_04.png
mech_05.png    -> vfx_05.png
mech_06.png    -> vfx_06.png
```

## Notes for Artist
- VFX maps should be same resolution as mech frames
- Use pure colors (no anti-aliasing) for cleaner detection
- Vary effect positions between frames for natural movement
- Consider mech motion when placing effects (momentum, physics)
- Test with different brightness levels for variety

## Future Enhancements
- **Weather Effects**: Rain, snow interacting with hot mech parts
- **Battle Damage**: Progressive damage showing more sparks/smoke
- **Power-Up Effects**: Special effects for donation milestones
- **Environmental Reflections**: Mech reflecting in water/glass
- **Crowd Reactions**: Background elements responding to mech

## Questions for Design Team
1. Should effects persist between frames (smoke trails)?
2. Do we want directional information in VFX maps?
3. Should certain effects only trigger at specific power levels?
4. How should effects scale with mech size (levels 1-11)?
5. Do we want interactive effects (user can trigger)?

---
*Last Updated: 2025-01-14*
*Status: Planning Phase - Awaiting first Mech assets*