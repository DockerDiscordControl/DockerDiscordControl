# RAM Optimization Plan for DockerDiscordControl (Mech Animations)

## Problem Analysis
The high RAM consumption in `dockerdiscordcontrol` is primarily caused by the dynamic generation of mech animations in `services/mech/animation_cache_service.py`.

**Root Cause:**
1.  **Dynamic Speed Adjustment:** The feature that adjusts animation speed based on power level (70% - 130%) triggers frequent re-encoding of animations.
2.  **In-Memory Frame Buffer:** To change the speed (duration) of a WebP animation, the current implementation loads **all frames** into a Python list (`frames.append(img.copy())`) as uncompressed RGBA data.
    *   *Impact:* A ~500KB WebP file on disk expands to ~40MB+ in RAM during processing.
3.  **Frequent Triggers:** Every donation or daily decay changes the Power level, potentially invalidating caches and triggering this RAM-intensive process for multiple users simultaneously.

## Optimization Strategy

### 1. Strict Speed Quantization (High Impact, Low Risk)
**Goal:** Increase cache hit rate and reduce re-encoding frequency.
*   **Action:** Modify `_quantize_speed` or the speed calculation logic to enforce strict 5% or 10% steps.
*   **Benefit:** Minor power fluctuations (e.g., 100.1 -> 100.2) will map to the same speed bucket (e.g., 100%), allowing the cached animation to be reused without re-processing.

### 2. "Fast Path" for 100% Speed (Immediate Win)
**Goal:** Bypass PIL/Image processing entirely for the default state.
*   **Action:** In `get_animation_with_speed_and_power`, explicitly check if the target speed is effectively 100% (e.g., speed level 50).
*   **Implementation:** If 100%, return the raw bytes read from the disk cache immediately. Do **not** call `Image.open()`.

### 3. Memory-Efficient Re-Encoding (Technical Fix)
**Goal:** Reduce the peak RAM usage during the speed adjustment process.
*   **Action:** Refactor the frame processing loop.
    *   Explicitly call `gc.collect()` after large operations.
    *   Ensure `frames` list is cleared immediately after saving.
    *   Investigate streaming approaches (processing frames one-by-one) if `Pillow` supports it for WebP saving (limited support, but optimization of the list handling is possible).

### 4. Cache Management (Stability)
**Goal:** Prevent unbounded memory growth.
*   **Action:** Replace the manual `_focused_cache` dictionary with `cachetools.LRUCache(maxsize=2)`.
*   **Benefit:** Guaranteed hard limit on the number of cached animations in RAM, regardless of logic errors or race conditions.

## Implementation Roadmap (services/mech/animation_cache_service.py)

1.  **Refactor `get_animation_with_speed_and_power`:**
    *   Insert "Fast Path" check at the very beginning.
    *   Apply strict quantization to `speed_level` before processing.

2.  **Optimize Frame Processing:**
    *   Wrap the `Image.open` and processing block in a `try...finally` block to ensure resources are closed.
    *   Add explicit `del frames` and `gc.collect()` calls.

3.  **Upgrade Caching:**
    *   Import `cachetools`.
    *   Replace `self._focused_cache = {}` with `self._focused_cache = LRUCache(maxsize=2)`.

---
*Created: November 20, 2025*
