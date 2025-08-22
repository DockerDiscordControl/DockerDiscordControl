# DDC Mech Systems Documentation

## 🎮 Overview

The DDC Mech System is a comprehensive donation-powered virtual mech that evolves and operates based on community support. It consists of four independent but coordinated subsystems:

### System Architecture

```
┌─────────────────┐
│   MechMaster    │  ← Main Interface
├─────────────────┤
│  FuelSystem     │  ← Donation Processing & Fuel Management
│  EvolutionSystem│  ← Mech Tier Progression (1-11)
│  SpeedSystem    │  ← Speed Calculation (Glvl 0-101)
│  AnimationSystem│  ← Visual Creation & Effects
└─────────────────┘
```

## 🔧 Core Systems

### 1. Fuel System (`fuel_system.py`)
**Manages donation amounts and fuel calculations**

- **Current Fuel**: Available energy for mech operation
- **Total Donations**: Lifetime achievement tracking
- **Donation Processing**: Validates and processes new donations

```python
from systems.fuel_system import FuelSystem

fuel = FuelSystem()
result = fuel.add_donation(50.0, "Donor123")
print(f"Current fuel: ${fuel.current_fuel}")
```

### 2. Evolution System (`evolution_system.py`)
**Handles mech evolution tiers and upgrades**

- **11 Evolution Levels**: SCRAP (1) → OMEGA (11)
- **Based on Total Donations**: Lifetime achievement
- **Progressive Thresholds**: $0, $20, $50, $100, $200, $400, $800, $1500, $2500, $4000, $10000

```python
from systems.evolution_system import EvolutionSystem

evolution = EvolutionSystem()
level = evolution.get_evolution_level(1000.0)  # Returns evolution level
tier_info = evolution.get_evolution_tier(1000.0)  # Returns complete tier info
```

### 3. Speed System (`speed_system.py`)
**Calculates speed levels (Glvl) based on fuel and evolution**

- **Glvl Range**: 0 (OFFLINE) → 101 (TRANSCENDENT)
- **Dynamic Calculation**: Varies by evolution level
- **Special Rules**: 
  - Levels 1-4: 1$ = 1 Glvl (max 100)
  - Levels 5-10: Dynamic scaling within tier range
  - Level 11: Special OMEGA calculation (Glvl 101 possible)

```python
from systems.speed_system import SpeedSystem

speed = SpeedSystem()
glvl = speed.calculate_speed_level(current_fuel=100.0, evolution_level=5)
speed_info = speed.get_speed_level_info(100.0, 5)
```

### 4. Animation System (`animation_system.py`)
**Creates visual representations of mech state**

- **Encrypted Sprites**: Base64-encoded .mech files
- **Visual Effects**: Based on speed level
- **Evolution Graphics**: Different sprites per evolution level
- **Special Effects**: TRANSCENDENT mode (Glvl 101)

```python
from systems.animation_system import AnimationSystem

animation = AnimationSystem()
discord_file = await animation.create_mech_animation(
    evolution_level=5,
    speed_level=75,
    donor_name="Donor123"
)
```

## 🎯 Master System (`mech_master.py`)

The `MechMaster` class provides a unified interface to all subsystems:

```python
from systems.mech_master import MechMaster

# Initialize complete system
mech = MechMaster()

# Process donation
result = mech.add_donation(100.0, "BigDonor")

# Get complete status
status = mech.get_complete_status()

# Create animation
animation = await mech.create_animation("BigDonor", "$100")
```

## 📊 Key Concepts

### Fuel vs Total Donations
- **Total Donations**: Used for **Evolution Level** (lifetime achievement)
- **Current Fuel**: Used for **Speed Level** (operational capability)

### Speed Level (Glvl) Calculation Rules

| Evolution Level | Fuel Range | Glvl Calculation |
|----------------|-------------|------------------|
| 1-4 | $0-$100+ | Direct 1:1 (1$ = 1 Glvl, max 100) |
| 5-10 | Variable | Dynamic scaling within evolution tier |
| 11 (OMEGA) | $10,000+ | Special: Glvl 101 at $20,000+ |

### Visual Effects by Speed Level

| Glvl Range | Effects |
|------------|---------|
| 0 | OFFLINE (darkened, no effects) |
| 1-29 | Basic animation |
| 30+ | Speed lines |
| 50+ | Glow effects |
| 90+ | Lightning effects |
| 101 | TRANSCENDENT (rainbow portals, reality tears) |

## 🚀 Usage Examples

### Basic Usage
```python
from systems.mech_master import MechMaster

# Create mech system
mech = MechMaster()

# Process a donation
result = mech.add_donation(250.0, "SuperFan")
if result['success']:
    print(f"Evolution: Level {result['evolution']['current_level']}")
    print(f"Speed: Glvl {result['speed']['current_glvl']}")
    
    # Check for evolution upgrade
    if result['evolution']['upgraded']:
        print("🎉 EVOLUTION UPGRADE!")
```

### Get Current Status
```python
status = mech.get_complete_status()

print(f"Mech: {status['summary']['name']}")
print(f"Speed: {status['summary']['description']}")
print(f"Fuel: ${status['fuel']['current']:.2f}")
print(f"Total Donations: ${status['fuel']['total_donations']:.2f}")

if status['summary']['is_transcendent']:
    print("⚡ TRANSCENDENT MODE ACTIVE!")
```

### Create Animation
```python
# Create animation for current state
animation = await mech.create_animation("Donor", "$50")

# Or create animation for specific donation
animation = await mech.create_donation_animation(
    donor_name="BigDonor",
    amount="$500",
    total_donations=1500.0
)
```

## 🔒 Sprite Security

Mech sprites are stored as encrypted `.mech` files to prevent spoilers:

```python
# Encode sprites (run once when adding new graphics)
python prepare_mech_sprites.py create  # Create placeholders
python prepare_mech_sprites.py encode  # Encode PNGs to .mech files
python prepare_mech_sprites.py test    # Test encoding/decoding
```

**File Structure:**
- `/app/static/mechs/` - Encrypted .mech files (committed to repo)
- `/app/static/mech_sprites/` - Original PNG files (gitignored)

## 🎨 Evolution Levels

| Level | Name | Threshold | Description |
|-------|------|-----------|-------------|
| 1 | SCRAP MECH | $0 | Barely holding together |
| 2 | REPAIRED MECH | $20 | Basic repairs complete |
| 3 | STANDARD MECH | $50 | Military-grade chassis |
| 4 | ENHANCED MECH | $100 | Reinforced armor |
| 5 | ADVANCED MECH | $200 | Advanced targeting |
| 6 | ELITE MECH | $400 | Elite combat protocols |
| 7 | CYBER MECH | $800 | Cybernetic interface |
| 8 | PLASMA MECH | $1500 | Plasma-powered core |
| 9 | QUANTUM MECH | $2500 | Quantum entanglement |
| 10 | DIVINE MECH | $4000 | Transcendent technology |
| 11 | OMEGA MECH | $10000 | **SECRET!** Reality-bending |

## ⚡ Speed Descriptions

**Notable Speed Levels:**
- Glvl 0: "OFFLINE"
- Glvl 1: "Motionless"
- Glvl 25: "Measured walking"
- Glvl 50: "Sharply swift"
- Glvl 75: "Relentless sprint"
- Glvl 90: "Star-chasing speed"
- Glvl 100: "Beyond-lightspeed"
- Glvl 101: "REALITY-BENDING OMNISPEED" ⚡

## 🧪 Testing

```python
# Test individual systems
from systems.fuel_system import FuelSystem
from systems.evolution_system import EvolutionSystem
from systems.speed_system import SpeedSystem

# Test complete system
from systems.mech_master import MechMaster

mech = MechMaster()
result = mech.add_donation(10000.0, "TestDonor")  # Reach OMEGA MECH
animation = await mech.create_animation("TestDonor", "$10000")
```

## 🔧 Maintenance

### Adding New Evolution Levels
1. Update `EVOLUTION_THRESHOLDS` in `evolution_system.py`
2. Add new entries to `EVOLUTION_NAMES`, `EVOLUTION_DESCRIPTIONS`, `EVOLUTION_COLORS`
3. Create new sprite: `mech_level_X.png`
4. Run: `python prepare_mech_sprites.py encode`

### Adjusting Speed Calculations
- Modify calculation logic in `speed_system.py`
- Update `SPEED_DESCRIPTIONS` for new ranges
- Test with various fuel/evolution combinations

### Adding Visual Effects
- Extend effect methods in `animation_system.py`
- Add new effect conditions in `_apply_visual_effects()`
- Test performance impact

## 📋 Dependencies

- **PIL (Pillow)**: Image processing and sprite manipulation
- **discord.py**: Discord file creation
- **logging**: System logging and debugging
- **pathlib**: File path management
- **dataclasses**: Clean data structures

## 🚨 Important Notes

1. **Evolution is permanent** - Based on total donations (never decreases)
2. **Speed is dynamic** - Based on current fuel (can go up/down)
3. **Glvl 101 is special** - Only achievable by OMEGA MECH at $20,000+ fuel
4. **Sprites are encrypted** - Use encoding tools, don't commit raw PNGs
5. **Thread-safe design** - Each subsystem can be used independently

## 🎯 Future Enhancements

- **Mech Abilities**: Special powers unlocked by evolution levels
- **Fuel Efficiency**: Different consumption rates by evolution
- **Battle System**: Combat mechanics using speed and evolution
- **Leaderboards**: Top donors and evolution achievements
- **Sound Effects**: Audio feedback for donations and upgrades