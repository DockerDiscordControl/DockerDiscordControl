# MECH SYSTEM PROGRESS BAR LOGIC - NEVER FORGET! 🔥

## CRITICAL SYSTEM BEHAVIOR

### Evolution Bar (Second Bar)
- **Purpose:** Shows progress to NEXT evolution level
- **Max Value:** `next_threshold - current_threshold`
- **Current Value:** `total_donations_received - current_threshold` 
- **Reset Behavior:** Resets to 0% when evolution occurs
- **Example:** Level 1 → 2: Max=$20, Current=$8.99 → 44.95%

### Fuel Bar (First Bar) 
- **Purpose:** Shows current fuel within evolution level + bonus
- **Max Value:** `next_threshold - current_threshold + 1` (Evolution threshold + 1€ bonus)
- **Current Value:** `current_fuel - current_threshold`
- **Reset Behavior:** Resets to 1€ (current_threshold + 1) when evolution occurs
- **Example:** Level 1: Max=$21, Current=$8.99 → 42.8%

## KEY DIFFERENCES
- **Fuel Bar:** Uses `current_fuel` (decreases with consumption)
- **Evolution Bar:** Uses `total_donations_received` (never decreases)
- **Fuel Bar:** Gets +1€ bonus range (evolution threshold + 1€)
- **Evolution Bar:** Uses exact evolution threshold range

## EVOLUTION BEHAVIOR
When evolution happens (e.g. reaching $20):
1. **Evolution Bar:** Resets to 0% for next level
2. **Fuel Bar:** Resets to 1€ (gets 1€ bonus) and new max range
3. **Fuel Counter:** Shows current fuel amount (with bonus)

## CODE IMPLEMENTATION
```python
# Evolution bar calculation
evolution_level_range = next_threshold - current_threshold  
next_progress_in_level = total_donations_received - current_threshold
next_percentage = (next_progress_in_level / evolution_level_range) * 100

# Fuel bar calculation  
fuel_level_range = evolution_level_range + 1  # +1€ bonus!
fuel_progress_in_level = current_fuel - current_threshold
fuel_percentage = (fuel_progress_in_level / fuel_level_range) * 100
```

## NEVER MAKE THESE MISTAKES AGAIN:
❌ Using same range for both bars
❌ Using `total_donations_received` for fuel bar
❌ Forgetting the +1€ bonus for fuel bar max
❌ Using `current_fuel` for evolution bar

✅ Fuel Bar: `current_fuel` with +1€ bonus range
✅ Evolution Bar: `total_donations_received` with exact range

---
**Last Updated:** 2025-08-24  
**Context:** Fixed 0.0% fuel bar bug - was missing +1€ bonus range