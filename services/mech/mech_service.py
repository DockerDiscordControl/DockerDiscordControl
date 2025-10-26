from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import List, Optional, Dict, Any
import json
import math
import logging
import threading

logger = logging.getLogger(__name__)

# =============================================================
#   DDC Mech Service (instance-wide)
#   - Single donation pool per DDC instance (no guild dimension)
#   - JSON persistence
#   - Level thresholds per spec
#   - Power rules per spec (fresh level = 1 + overshoot)
#   - Decay always second-accurate (rolling)
#   - Clean DTOs for UI (progress bars, glvl mapping)
# =============================================================

# ---------------------------
#   Domain: Levels & Names
# ---------------------------

@dataclass(frozen=True)
class MechLevel:
    level: int
    name: str
    threshold: int  # cumulative dollars required to START this level


MECH_LEVELS: List[MechLevel] = [
    MechLevel(1,  "The Rustborn Husk",       0),
    MechLevel(2,  "The Battle-Scarred Survivor", 20),
    MechLevel(3,  "The Corewalker Standard", 50),
    MechLevel(4,  "The Titanframe",          100),
    MechLevel(5,  "The Pulseforged Guardian", 200),
    MechLevel(6,  "The Abyss Engine",        400),
    MechLevel(7,  "The Rift Strider",        800),
    MechLevel(8,  "The Radiant Bastion",     1500),
    MechLevel(9,  "The Overlord Ascendant",  2500),
    MechLevel(10, "The Celestial Exarch",    4000),
    MechLevel(11, "OMEGA MECH",              10000),
]


# ---------------------------
#   SERVICE FIRST: Request/Result Patterns
# ---------------------------

@dataclass(frozen=True)
class GetMechStateRequest:
    """Request to get current mech state."""
    include_decimals: bool = False  # For power with decimal precision


@dataclass(frozen=True)
class GetMechStateResult:
    """Result containing current mech state."""
    success: bool
    level: int
    power: float
    total_donated: float
    speed: float
    name: str
    threshold: int
    progress_to_next: float
    glvl: int = 0
    glvl_max: int = 100
    bars: Optional['MechBars'] = None
    error_message: Optional[str] = None


@dataclass(frozen=True)
class AddDonationRequest:
    """Request to add a donation."""
    donor_name: str
    amount: float
    use_bot_integration: bool = False  # For Discord bot notifications


@dataclass(frozen=True)
class AddDonationResult:
    """Result of adding a donation."""
    success: bool
    old_level: int
    new_level: int
    old_power: float
    new_power: float
    total_donated: float
    level_changed: bool
    error_message: Optional[str] = None


@dataclass(frozen=True)
class CreateMechAnimationRequest:
    """Request to create mech animation."""
    animation_type: str = "collapsed_status"  # Type of animation
    force_regenerate: bool = False


@dataclass(frozen=True)
class CreateMechAnimationResult:
    """Result containing mech animation file."""
    success: bool
    animation_file: Optional[Any] = None  # Discord File object
    error_message: Optional[str] = None


@dataclass(frozen=True)
class GetStoreDataRequest:
    """Request to get store data with proper abstraction."""
    pass


@dataclass(frozen=True)
class GetStoreDataResult:
    """Result containing store data."""
    success: bool
    data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None


@dataclass(frozen=True)
class SaveStoreDataRequest:
    """Request to save store data with validation."""
    data: Dict[str, Any]


@dataclass(frozen=True)
class SaveStoreDataResult:
    """Result of saving store data."""
    success: bool
    error_message: Optional[str] = None


def _next_level(curr: MechLevel) -> Optional[MechLevel]:
    try:
        return MECH_LEVELS[curr.level]  # 1-based levels vs 0-based list
    except IndexError:
        return None


def _stage_delta(curr: MechLevel) -> Optional[int]:
    nxt = _next_level(curr)
    return None if not nxt else (nxt.threshold - curr.threshold)


# ---------------------------
#   Persistence
# ---------------------------

class _Store:
    """Tiny JSON store. Atomic writes; schema:
    {
      "donations": [
         {"username": "...", "amount": 25, "ts": "2025-08-24T18:00:00+02:00"}
      ]
    }
    """
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {"donations": []}
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError:
            return {"donations": []}
        if "donations" not in data or not isinstance(data["donations"], list):
            data["donations"] = []
        return data

    def save(self, data: Dict[str, Any]) -> None:
        tmp = None
        try:
            # Try atomic write with temp file
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            tmp.replace(self.path)
            tmp = None  # Successfully replaced, no cleanup needed
        except PermissionError:
            # Fallback: direct write (less safe but works with restricted permissions)
            with self.path.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        finally:
            # Clean up temp file if it still exists
            if tmp and tmp.exists():
                try:
                    tmp.unlink()
                except Exception:
                    pass  # Best effort cleanup


# ---------------------------
#   Public State DTOs
# ---------------------------

@dataclass(frozen=True)
class MechBars:
    mech_progress_current: int
    mech_progress_max: int
    Power_current: int
    Power_max_for_level: int


@dataclass(frozen=True)
class MechState:
    total_donated: int
    level: int
    level_name: str
    next_level_threshold: Optional[int]  # None when at MAX
    Power: int
    glvl: int
    glvl_max: int
    bars: MechBars


# ---------------------------
#   Core Service
# ---------------------------

class MechService:
    """Instance-wide mech service for DDC using SimpleEvolutionService.

    Rules:
    - Donations persist in JSON (username, amount, timestamp).
    - Mech level from cumulative donations using STATIC evolution costs.
    - Power increases by donation dollars.
    - On level-up, Power resets to 1 plus overshoot beyond the new level threshold.
    - Power decays continuously: 1 Power per 86400 seconds (second-accurate).
    - Evolution costs are STATIC: Level 1=$0, Level 2=$20, Level 3=$50, etc.
    - Bars:
        * Mech progress: 0..Δ (Δ = distance to next level)
        * Power bar: 0..(Δ + 1) (fresh level = 1); at MAX level 0..100
    - glvl mapping:
        * If Δ ≤ 100: glvl = Power, capped at (Δ - 1)
        * If Δ > 100: linear mapping Power → 0..100 over (Δ + 1)
    """

    def __init__(self, json_path: str | Path, tz: str = "Europe/Zurich") -> None:
        self.store = _Store(Path(json_path))
        self.tz = ZoneInfo(tz)
        self._store_lock = threading.Lock()  # Protect load-modify-save operations
        self.dynamic_thresholds = None  # Cache for dynamic thresholds

    # -------- SERVICE FIRST API --------

    def get_mech_state_service(self, request: GetMechStateRequest) -> GetMechStateResult:
        """SERVICE FIRST: Get current mech state with Request/Result pattern."""
        try:
            state = self.get_state()

            # Get power with appropriate precision
            if request.include_decimals:
                power = self.get_power_with_decimals()
            else:
                power = float(state.Power)

            # Calculate progress to next level
            progress_to_next = 0.0
            if state.next_level_threshold:
                current_progress = float(state.total_donated)
                threshold = float(state.next_level_threshold)
                if threshold > 0:
                    progress_to_next = min(100.0, (current_progress / threshold) * 100.0)

            return GetMechStateResult(
                success=True,
                level=state.level,
                power=power,
                total_donated=float(state.total_donated),
                speed=50.0,  # Default speed (middle of 0-100 range)
                name=state.level_name,
                threshold=state.next_level_threshold or 0,
                progress_to_next=progress_to_next,
                glvl=state.glvl,
                glvl_max=state.glvl_max,
                bars=state.bars
            )
        except Exception as e:
            logger.error(f"Error getting mech state: {e}", exc_info=True)
            return GetMechStateResult(
                success=False,
                level=1,
                power=0.0,
                total_donated=0.0,
                speed=0.0,
                name="Error",
                threshold=0,
                progress_to_next=0.0,
                glvl=0,
                glvl_max=100,
                bars=MechBars(
                    mech_progress_current=0,
                    mech_progress_max=100,
                    Power_current=0,
                    Power_max_for_level=100
                ),
                error_message=str(e)
            )

    def add_donation_service(self, request: AddDonationRequest) -> AddDonationResult:
        """
        DEPRECATED: Use UnifiedDonationService instead.

        This method is deprecated and will be removed in a future version.
        Use services.donation.unified_donation_service.process_donation() instead.
        """
        try:
            # Get old state
            old_state = self.get_state()
            old_level = old_state.level
            old_power = float(old_state.Power)

            # Add donation
            if request.use_bot_integration:
                new_state = self.add_donation_with_bot(request.donor_name, request.amount)
            else:
                new_state = self.add_donation(request.donor_name, request.amount)

            # SERVICE FIRST: Emit donation event for other services to handle (animation cache, etc.)
            try:
                from services.infrastructure.event_manager import get_event_manager
                event_manager = get_event_manager()
                new_power = float(new_state.Power)
                power_change = abs(new_power - old_power)

                event_data = {
                    'donation_amount': request.amount,
                    'donor_name': request.donor_name,
                    'old_power': old_power,
                    'new_power': new_power,
                    'old_level': old_level,
                    'new_level': new_state.level,
                    'power_change': power_change,
                    'level_changed': old_level != new_state.level,
                    'total_donated': float(new_state.total_donated)
                }

                event_manager.emit_event('donation_completed', 'mech_service', event_data)
                logger.info(f"Donation event emitted: ${request.amount} (power {old_power:.2f}→{new_power:.2f})")
            except Exception as e:
                logger.warning(f"Failed to emit donation event: {e}")

            return AddDonationResult(
                success=True,
                old_level=old_level,
                new_level=new_state.level,
                old_power=old_power,
                new_power=float(new_state.Power),
                total_donated=float(new_state.total_donated),
                level_changed=(old_level != new_state.level)
            )
        except Exception as e:
            logger.error(f"Error adding donation: {e}", exc_info=True)
            return AddDonationResult(
                success=False,
                old_level=1,
                new_level=1,
                old_power=0.0,
                new_power=0.0,
                total_donated=0.0,
                level_changed=False,
                error_message=str(e)
            )

    async def create_mech_animation_service(self, request: CreateMechAnimationRequest) -> CreateMechAnimationResult:
        """SERVICE FIRST: Create mech animation with Request/Result pattern."""
        try:
            if request.animation_type == "collapsed_status":
                # Use PNG to WebP service for animation creation
                from services.mech.png_to_webp_service import get_png_to_webp_service
                webp_service = get_png_to_webp_service()

                # Get current state for animation
                state = self.get_state()
                animation_file = await webp_service.create_collapsed_status_animation_async(
                    power_level=float(state.Power),
                    total_donations=float(state.total_donated)
                )

                return CreateMechAnimationResult(
                    success=True,
                    animation_file=animation_file
                )
            else:
                return CreateMechAnimationResult(
                    success=False,
                    error_message=f"Unknown animation type: {request.animation_type}"
                )
        except Exception as e:
            logger.error(f"Error creating animation: {e}", exc_info=True)
            return CreateMechAnimationResult(
                success=False,
                error_message=str(e)
            )

    def add_donation(self, username: str, amount: int, ts_iso: Optional[str] = None) -> MechState:
        """
        SINGLE POINT OF TRUTH: Persist a donation with level-up tracking.

        This method now handles level-ups directly and stores all level information
        in the donation itself, eliminating the need for achieved_levels.json.
        """
        if not isinstance(amount, int):
            raise TypeError("amount must be an integer")
        if amount <= 0:
            raise ValueError("amount must be a positive integer number of dollars")
        if amount > 1000000:
            raise ValueError("amount exceeds maximum allowed value (1,000,000)")
        if not username or len(username) > 100:
            raise ValueError("username must be between 1 and 100 characters")

        ts = self._now() if ts_iso is None else self._parse_iso(ts_iso)

        # Thread-safe load-modify-save with level-up logic
        with self._store_lock:
            data = self.store.load()
            data.setdefault("donations", [])

            # Calculate state BEFORE this donation
            existing_donations = data["donations"]
            old_total = sum(int(d["amount"]) for d in existing_donations)
            old_level = self._calculate_level_from_donations(existing_donations)

            # Calculate state AFTER this donation
            new_total = old_total + amount
            new_level = self._calculate_level_from_total(new_total)

            # Check if level-up occurred
            level_upgrade = new_level > old_level

            # Get the threshold that was used for level-up (if any)
            threshold_used = None
            is_dynamic = False
            if level_upgrade:
                level_info = self._get_level_info_for_calculation(new_level)
                threshold_used = level_info['threshold']
                is_dynamic = level_info['is_dynamic']

            # Create enhanced donation record
            donation_record = {
                "username": username,
                "amount": int(amount),
                "ts": ts.isoformat(),
                "level_upgrade": level_upgrade,
                "level_reached": new_level if level_upgrade else None,
                "threshold_used": threshold_used,
                "is_dynamic": is_dynamic
            }

            data["donations"].append(donation_record)
            self.store.save(data)

            # Log level-up if it occurred
            if level_upgrade:
                logger.info(f"LEVEL UP! {username} donated ${amount}, level {old_level} → {new_level} (threshold: ${threshold_used}, dynamic: {is_dynamic})")

        return self.get_state(now_iso=ts.isoformat())
    
    async def add_donation_with_bot(self, username: str, amount: int, bot=None, ts_iso: Optional[str] = None) -> MechState:
        """
        DEPRECATED: Use UnifiedDonationService instead.

        This method is deprecated and will be removed in a future version.
        Use services.donation.unified_donation_service.process_discord_donation() instead.
        """
        if amount <= 0:
            raise ValueError("amount must be a positive integer number of dollars")

        # No more dynamic member cache updates needed (using simple static evolution)

        # Fast path: Record donation immediately (thread-safe)
        ts = self._now() if ts_iso is None else self._parse_iso(ts_iso)
        with self._store_lock:
            data = self.store.load()
            data.setdefault("donations", [])
            data["donations"].append({
                "username": username,
                "amount": int(amount),
                "ts": ts.isoformat(),
            })
            self.store.save(data)
        
        # Get state for Discord sharing
        new_state = self.get_state(now_iso=ts.isoformat())
        
        # Send Discord notification if bot is provided
        if bot:
            try:
                await self._send_donation_discord_message(bot, username, amount, new_state)
            except Exception as e:
                logger.error(f"Error sending Discord donation message: {e}")
                # Don't fail the donation if Discord fails
        
        return new_state

    async def _send_donation_discord_message(self, bot, username: str, amount: int, mech_state):
        """Send Discord message for donation"""
        try:
            import discord
            from .speed_levels import get_combined_mech_status
            
            # Clean username for display
            display_name = username.replace("WebUI:", "").replace("Discord:", "").strip()
            
            # Find a suitable channel (general, announcements, donations, etc.)
            target_channel = None
            for guild in bot.guilds:
                for channel in guild.text_channels:
                    if channel.name.lower() in ['general', 'announcements', 'donations', 'mech', 'chat']:
                        target_channel = channel
                        break
                if target_channel:
                    break
            
            if not target_channel:
                logger.warning("No suitable Discord channel found for donation notification")
                return
            
            # Get mech status text
            status_text = get_combined_mech_status(
                mech_state.power, 
                mech_state.total_donations, 
                'en'
            )
            
            # Create embed
            embed = discord.Embed(
                title="💰 New Donation Received!",
                description=f"**{display_name}** donated **${amount}**",
                color=0x00ff00,
                timestamp=datetime.now(timezone.utc)
            )
            
            embed.add_field(
                name="🤖 Mech Status",
                value=status_text,
                inline=False
            )
            
            embed.add_field(
                name="📊 Power Level",
                value=f"${mech_state.power:.2f}",
                inline=True
            )
            
            embed.add_field(
                name="🎯 Total Donations",
                value=f"${mech_state.total_donations}",
                inline=True
            )
            
            embed.add_field(
                name="🚀 Evolution Level",
                value=f"Level {mech_state.level} - {mech_state.level_name}",
                inline=True
            )
            
            source = "Web UI" if "WebUI:" in username else "Discord"
            embed.set_footer(text=f"Donated via {source} • Thank you for your support!")
            
            await target_channel.send(embed=embed)
            logger.info(f"Donation notification sent to Discord: #{target_channel.name}")
            
        except Exception as e:
            logger.error(f"Error creating Discord donation message: {e}")
            raise

    def get_state(self, now_iso: Optional[str] = None) -> MechState:
        """Compute the live state from persisted donations."""
        now = self._now() if now_iso is None else self._parse_iso(now_iso)
        donations = list(self.store.load().get("donations", []))
        donations.sort(key=lambda d: d["ts"])  # chronological

        # Calculate total donated amount
        total_donated = sum(int(d["amount"]) for d in donations)

        # Check evolution mode: dynamic (default) vs static override
        evolution_mode = self._get_evolution_mode()

        if evolution_mode['use_dynamic']:
            # DYNAMIC EVOLUTION: Community-based costs (default)
            dynamic_thresholds = self.get_dynamic_thresholds()

            # CRITICAL: Protect achieved levels - dynamic costs can never be higher than what was paid
            achieved_levels = self._get_achieved_levels(total_donated)

            # Build dynamic MechLevel objects with achieved level protection
            levels = []
            for i, static_level in enumerate(MECH_LEVELS):
                if static_level.level in dynamic_thresholds:
                    dynamic_threshold = dynamic_thresholds[static_level.level]

                    # PROTECT ACHIEVED LEVELS: If level was already achieved, keep original cost
                    if static_level.level in achieved_levels:
                        # Use the minimum between dynamic and what was actually paid
                        protected_threshold = min(dynamic_threshold, achieved_levels[static_level.level]['cost_paid'])
                        logger.debug(f"Level {static_level.level} protected: dynamic=${dynamic_threshold}, paid=${achieved_levels[static_level.level]['cost_paid']}, using=${protected_threshold}")
                        levels.append(MechLevel(
                            level=static_level.level,
                            name=static_level.name,
                            threshold=protected_threshold
                        ))
                    else:
                        # Not achieved yet - use dynamic cost with 1.0x minimum
                        safe_threshold = max(dynamic_threshold, static_level.threshold)  # Never below base cost
                        levels.append(MechLevel(
                            level=static_level.level,
                            name=static_level.name,
                            threshold=safe_threshold
                        ))
                else:
                    levels.append(static_level)
        else:
            # STATIC EVOLUTION: SimpleEvolutionService with custom difficulty
            from services.mech.simple_evolution_service import get_simple_evolution_service
            simple_service = get_simple_evolution_service()

            difficulty = evolution_mode.get('difficulty_multiplier', 1.0)
            simple_state = simple_service.get_current_state(total_donated=float(total_donated), difficulty=difficulty)

            # Build static levels with custom difficulty
            levels = []
            for static_level in MECH_LEVELS:
                if static_level.level == 1:
                    levels.append(static_level)  # Level 1 always $0
                else:
                    # Apply difficulty multiplier to base cost
                    adjusted_threshold = int(static_level.threshold * difficulty)
                    levels.append(MechLevel(
                        level=static_level.level,
                        name=static_level.name,
                        threshold=adjusted_threshold
                    ))

        # SINGLE POINT OF TRUTH: Calculate current level from donations only
        current_level_number = self._calculate_level_from_donations(donations)

        # Find the MechLevel object for the current level
        lvl = levels[0]  # Default to Level 1
        for level in levels:
            if level.level == current_level_number:
                lvl = level
                break
        total = int(total_donated)

        # Calculate Power with decay from donations
        Power: float = 0.0
        last_ts: Optional[datetime] = None
        last_evolution_ts: Optional[datetime] = None

        for d in donations:
            ts = self._parse_iso(d["ts"])
            if last_ts is not None:
                Power = max(0.0, Power - self._decay_amount(last_ts, ts, lvl.level))
            last_ts = ts

            amount = int(d["amount"])
            Power += amount

            # Handle level-ups using current levels system
            temp_total = sum(int(dd["amount"]) for dd in donations[:donations.index(d)+1])

            # Check if we can achieve NEW levels (only levels higher than current persistent level)
            current_persistent_level = self._calculate_level_from_donations(donations[:donations.index(d)])

            for level in levels:
                if temp_total >= level.threshold and level.level > current_persistent_level:
                    # NEW level up occurred - save to JSON and reset Power
                    old_level = lvl.level
                    lvl = level
                    Power = 1.0 + max(0, temp_total - lvl.threshold)
                    last_evolution_ts = ts

                    # SINGLE POINT OF TRUTH: Level achievement now stored in donation record above

                    # Enhanced logging with evolution mode details
                    mode_info = "Dynamic (community-based)" if evolution_mode['use_dynamic'] else f"Static ({evolution_mode.get('difficulty_multiplier', 1.0)}x)"

                    if evolution_mode['use_dynamic']:
                        # Get community info for dynamic mode
                        try:
                            from .monthly_member_cache import get_monthly_member_cache
                            cache = get_monthly_member_cache()
                            cache_info = cache.get_cache_info()
                            community_info = f", Community: {cache_info.get('total_members', 'Unknown')} members"
                        except:
                            community_info = ""
                    else:
                        community_info = ""

                    logger.info(
                        f"🚀 MECH EVOLUTION: Level {old_level} → {lvl.level} "
                        f"(Cost: ${lvl.threshold}, Donated: ${temp_total}, "
                        f"Mode: {mode_info}{community_info}) - SAVED TO JSON"
                    )
                    break  # Only one level up per donation

        # POWER FIX: For already achieved levels, reset power correctly
        # If no new level-up occurred, but we're at an achieved level, reset power properly
        if last_evolution_ts is None:  # No evolution happened in this calculation
            current_persistent_level = self._calculate_level_from_donations(donations)
            if current_persistent_level > 1:  # We're at an achieved level
                # Find the current level threshold
                current_level_obj = None
                for level in levels:
                    if level.level == current_persistent_level:
                        current_level_obj = level
                        break

                if current_level_obj:
                    # Reset power correctly: 1.0 + overshoot
                    total_donations = sum(int(d["amount"]) for d in donations)
                    old_power = Power
                    Power = 1.0 + max(0, total_donations - current_level_obj.threshold)

        # decay from last donation to "now" - but only if enough time passed since evolution OR power reset
        if last_ts is not None:
            # If evolution just happened (within 1 minute), don't apply immediate decay
            evolution_was_recent = (last_evolution_ts is not None and
                                  (now - last_evolution_ts).total_seconds() < 60)

            if evolution_was_recent:
                # Evolution just occurred - no decay yet, mech has fresh Power
                pass
            else:
                # Normal decay from last donation (even for already achieved levels)
                Power = max(0.0, Power - self._decay_amount(last_ts, now, lvl.level))

        # Compose bars & glvl using current levels system
        # Get next level from levels (dynamic or static)
        try:
            if lvl.level >= 10:
                # Create corrupted OMEGA MECH entry for Level 10 users
                from types import SimpleNamespace
                nxt = SimpleNamespace()
                nxt.level = 11
                nxt.name = "ERR#R: [DATA_C0RR*PTED]"
                nxt.threshold = 10000  # Real threshold for percentage calculation
            else:
                nxt = levels[lvl.level] if lvl.level < len(levels) else None
        except IndexError:
            nxt = None

        # Calculate delta using current threshold system (dynamic or static)
        delta = None if not nxt else (nxt.threshold - lvl.threshold)
        progress_current = 0 if delta is None else max(0, total - lvl.threshold)
        progress_max = 0 if delta is None else delta

        # Power bar max - Level 1 starts at 0, Level 2+ starts at 1 + overshoot
        if delta is None:
            Power_max = 100
        elif lvl.level == 1:
            Power_max = delta  # Level 1 starts at 0, so max = delta
        else:
            Power_max = delta + 1  # Level 2+ starts at 1 + overshoot, so max = delta + 1

        # glvl mapping - consistent with Power_max calculation
        if delta is None:
            glvl_max = 100
            glvl = min(glvl_max, int(math.floor(Power)))
        elif delta <= 100:
            if lvl.level == 1:
                glvl_max = delta  # Level 1: full delta range
                glvl = min(glvl_max, int(math.floor(Power)))
            else:
                glvl_max = max(0, delta - 1)  # Level 2+: delta-1 to account for +1 start
                glvl = min(glvl_max, int(math.floor(Power)))
        else:
            glvl_max = 100
            if lvl.level == 1:
                glvl = int(math.floor((Power * 100) / delta))  # Level 1: simple mapping
            else:
                glvl = int(math.floor((Power * 100) / (delta + 1)))  # Level 2+: account for +1
            if glvl > glvl_max:
                glvl = glvl_max

        bars = MechBars(
            mech_progress_current=int(progress_current),
            mech_progress_max=int(progress_max),
            Power_current=int(max(0, round(Power))),  # Round instead of floor for more accurate representation
            Power_max_for_level=int(Power_max),
        )

        return MechState(
            total_donated=int(total),
            level=lvl.level,
            level_name=lvl.name,
            next_level_threshold=None if not nxt else nxt.threshold,
            Power=int(max(0, round(Power))),
            glvl=int(glvl),
            glvl_max=int(glvl_max),
            bars=bars,
        )

    def get_power_with_decimals(self) -> float:
        """Get raw Power value with decimal places for Web UI display using current evolution mode."""
        data = self.store.load()
        donations = data["donations"]

        # Calculate total donated amount
        total_donated = sum(int(d["amount"]) for d in donations)

        # Use same evolution mode as get_state() for consistency
        evolution_mode = self._get_evolution_mode()

        if evolution_mode['use_dynamic']:
            # DYNAMIC EVOLUTION: Use dynamic thresholds with achieved level protection
            dynamic_thresholds = self.get_dynamic_thresholds()
            achieved_levels = self._get_achieved_levels(total_donated)

            # Build levels with protection
            levels = []
            for static_level in MECH_LEVELS:
                if static_level.level in dynamic_thresholds:
                    dynamic_threshold = dynamic_thresholds[static_level.level]

                    if static_level.level in achieved_levels:
                        protected_threshold = min(dynamic_threshold, achieved_levels[static_level.level]['cost_paid'])
                        levels.append(MechLevel(static_level.level, static_level.name, protected_threshold))
                    else:
                        safe_threshold = max(dynamic_threshold, static_level.threshold)
                        levels.append(MechLevel(static_level.level, static_level.name, safe_threshold))
                else:
                    levels.append(static_level)
        else:
            # STATIC EVOLUTION: Use custom difficulty multiplier
            difficulty = evolution_mode.get('difficulty_multiplier', 1.0)
            levels = []
            for static_level in MECH_LEVELS:
                if static_level.level == 1:
                    levels.append(static_level)
                else:
                    adjusted_threshold = int(static_level.threshold * difficulty)
                    levels.append(MechLevel(static_level.level, static_level.name, adjusted_threshold))

        # SINGLE POINT OF TRUTH: Calculate current level from donations only
        current_level_number = self._calculate_level_from_donations(donations)

        # Find the MechLevel object for the current level
        current_level = levels[0]  # Default to Level 1
        for level in levels:
            if level.level == current_level_number:
                current_level = level
                break

        total = 0.0
        Power = 0.0
        lvl = current_level
        now = self._now()
        last_ts = None
        last_evolution_ts = None

        for d in donations:
            ts = self._parse_iso(d["ts"])

            # Apply decay from last donation to current donation
            if last_ts is not None:
                Power = max(0.0, Power - self._decay_amount(last_ts, ts, lvl.level))
            last_ts = ts

            amount = int(d["amount"])
            total += amount
            Power += amount

            # Level-up check using current levels system
            temp_total = sum(int(dd["amount"]) for dd in donations[:donations.index(d)+1])

            # Check if we can achieve NEW levels (only levels higher than current persistent level)
            current_persistent_level = self._calculate_level_from_donations(donations[:donations.index(d)])

            for level in levels:
                if temp_total >= level.threshold and level.level > current_persistent_level:
                    # NEW level up occurred - save to JSON and reset Power
                    old_level = lvl.level
                    lvl = level
                    Power = 1.0 + max(0, temp_total - lvl.threshold)
                    last_evolution_ts = ts

                    # SINGLE POINT OF TRUTH: Level achievement now stored in donation record above

                    logger.debug(f"Level up in power calculation: {old_level} → {lvl.level} (saved to JSON)")
                    break  # Only one level up per donation

        # POWER FIX (DUPLICATE): For already achieved levels, reset power correctly
        # Same fix as in get_state() method - this is code duplication that needs the same fix
        if last_evolution_ts is None:  # No evolution happened in this calculation
            current_persistent_level = self._calculate_level_from_donations(donations)
            if current_persistent_level > 1:  # We're at an achieved level
                # Find the current level threshold
                current_level_obj = None
                for level in levels:
                    if level.level == current_persistent_level:
                        current_level_obj = level
                        break

                if current_level_obj:
                    # Reset power correctly: 1.0 + overshoot
                    total_donations = sum(int(d["amount"]) for d in donations)
                    Power = 1.0 + max(0, total_donations - current_level_obj.threshold)

        # Final decay from last donation to now
        if last_ts is not None:
            # If evolution just happened (within 1 minute), don't apply immediate decay
            evolution_was_recent = (last_evolution_ts is not None and
                                  (now - last_evolution_ts).total_seconds() < 60)
            if evolution_was_recent:
                pass  # No decay if evolution just occurred
            else:
                Power = max(0.0, Power - self._decay_amount(last_ts, now, lvl.level))

        return Power  # Return raw float with decimals

    # -------- Evolution Mode Management --------

    def _get_evolution_mode(self) -> Dict[str, Any]:
        """Get current evolution mode: dynamic (default) vs static override."""
        try:
            # SERVICE FIRST: Use ConfigService instead of direct JSON access
            from services.config.config_service import get_config_service, GetEvolutionModeRequest

            config_service = get_config_service()
            request = GetEvolutionModeRequest()
            result = config_service.get_evolution_mode_service(request)

            if result.success:
                return {
                    'use_dynamic': result.use_dynamic,
                    'difficulty_multiplier': result.difficulty_multiplier
                }
            else:
                logger.warning(f"Could not load evolution mode config: {result.error}")

        except Exception as e:
            logger.warning(f"Error using ConfigService for evolution mode: {e}")

        # Default: Dynamic evolution system active
        return {'use_dynamic': True, 'difficulty_multiplier': 1.0}

    def _load_achieved_levels_json(self) -> Dict[str, Any]:
        """Load achieved levels from persistent JSON file."""
        try:
            config_path = Path("config/achieved_levels.json")
            if config_path.exists():
                with config_path.open('r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load achieved levels JSON: {e}")

        # Default structure if file doesn't exist
        return {
            "current_level": 1,
            "achieved_levels": {
                "1": {
                    "level": 1,
                    "cost_paid": 0,
                    "achieved_at": datetime.now().isoformat(),
                    "locked": True
                }
            },
            "last_updated": datetime.now().isoformat()
        }

    def _get_achieved_levels(self, total_donated: int) -> Dict[int, Dict[str, Any]]:
        """
        SINGLE POINT OF TRUTH: Get achieved levels from donation history.

        This method now uses the new _get_achieved_levels_from_donations().
        """
        return self._get_achieved_levels_from_donations()

    def _save_level_achievement(self, level: int, total_donated: int, cost_paid: int) -> None:
        """Save level achievement to persistent JSON file."""
        try:
            config_path = Path("config/achieved_levels.json")
            config_path.parent.mkdir(exist_ok=True)

            # Load existing data
            achieved_data = self._load_achieved_levels_json()

            # Update achieved levels
            achieved_data['achieved_levels'][str(level)] = {
                'level': level,
                'cost_paid': cost_paid,
                'achieved_at': datetime.now().isoformat(),
                'locked': True
            }

            # Update current level (total_donated is calculated from mech_donations.json)
            achieved_data['current_level'] = level
            achieved_data['last_updated'] = datetime.now().isoformat()

            # Save to file
            with config_path.open('w', encoding='utf-8') as f:
                json.dump(achieved_data, f, indent=2, ensure_ascii=False)

            logger.info(f"Level {level} achievement saved to JSON (cost: ${cost_paid})")

        except Exception as e:
            logger.error(f"Failed to save level achievement: {e}")

    def get_dynamic_thresholds(self) -> Dict[int, int]:
        """Get dynamic thresholds based on current member count with 1.0x minimum."""
        if self.dynamic_thresholds is not None:
            return self.dynamic_thresholds

        try:
            from .monthly_member_cache import get_monthly_member_cache
            from .dynamic_evolution import get_evolution_calculator

            cache = get_monthly_member_cache()
            calculator = get_evolution_calculator()

            # Build dynamic threshold mapping with level-based member counts
            thresholds = {}
            for level in range(1, 12):
                if level == 1:
                    thresholds[level] = 0
                else:
                    # Use appropriate member count based on level protection rules
                    member_count = cache.get_member_count_for_level(level)
                    threshold, _, _ = calculator.calculate_evolution_cost(level, member_count)

                    # MINIMUM 1.0x: Never below base cost
                    base_cost = MECH_LEVELS[level-1].threshold if level <= len(MECH_LEVELS) else 10000
                    safe_threshold = max(threshold, base_cost)
                    thresholds[level] = safe_threshold

            self.dynamic_thresholds = thresholds
            cache_info = cache.get_cache_info()
            logger.debug(f"Dynamic thresholds calculated with 1.0x minimum from {cache_info.get('month_year', 'N/A')}")
            return thresholds

        except Exception as e:
            logger.error(f"Error calculating dynamic thresholds: {e}")
            # Fallback to static thresholds
            fallback = {level.level: level.threshold for level in MECH_LEVELS}
            return fallback

    def set_evolution_mode(self, use_dynamic: bool, difficulty_multiplier: float = 1.0) -> None:
        """Set evolution mode: dynamic (community-based) vs static (custom difficulty)."""
        try:
            config_path = Path("config/evolution_mode.json")
            config_path.parent.mkdir(exist_ok=True)

            mode_config = {
                'use_dynamic': use_dynamic,
                'difficulty_multiplier': difficulty_multiplier,
                'last_updated': datetime.now().isoformat()
            }

            with config_path.open('w', encoding='utf-8') as f:
                json.dump(mode_config, f, indent=2, ensure_ascii=False)

            # Clear cache to force recalculation
            self.dynamic_thresholds = None

            mode_name = "Dynamic (community-based)" if use_dynamic else f"Static ({difficulty_multiplier}x)"
            logger.info(f"Evolution mode changed to: {mode_name}")

        except Exception as e:
            logger.error(f"Failed to save evolution mode: {e}")

    # -------- Helpers --------

    def _now(self) -> datetime:
        return datetime.now(self.tz)

    def _parse_iso(self, s: str) -> datetime:
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=self.tz)

    def _decay_amount(self, a: datetime, b: datetime, level: int = 1) -> float:
        """Power consumption between a→b, level-specific decay rate (second-accurate).

        This method now delegates to MechDecayService for consistent decay calculations.

        Args:
            a: Start time
            b: End time
            level: Mech level (default: 1)

        Returns:
            Power decay amount based on level-specific decay_per_day
        """
        from services.mech.mech_decay_service import get_mech_decay_service, DecayCalculationRequest

        decay_service = get_mech_decay_service()
        request = DecayCalculationRequest(
            start_time=a,
            end_time=b,
            mech_level=level
        )

        result = decay_service.calculate_decay_amount(request)

        if result.success and result.decay_amount is not None:
            return result.decay_amount
        else:
            # Fallback to legacy calculation if service fails
            logger.warning(f"MechDecayService failed, using fallback: {result.error}")
            sec = (b.astimezone(self.tz) - a.astimezone(self.tz)).total_seconds()
            return max(0.0, (sec / 86400.0) * 1.0)  # Default 1.0 decay rate

    # -------- Store Data Service Abstraction --------

    def get_store_data_service(self, request: GetStoreDataRequest) -> GetStoreDataResult:
        """
        SERVICE FIRST: Get store data with proper abstraction.

        Args:
            request: GetStoreDataRequest

        Returns:
            GetStoreDataResult with store data or error
        """
        try:
            # Load store data through proper internal mechanism
            store_data = self.store.load()

            # Return sanitized copy (don't expose internal references)
            return GetStoreDataResult(
                success=True,
                data=dict(store_data)  # Create defensive copy
            )
        except Exception as e:
            logger.error(f"Error getting store data via service: {e}")
            return GetStoreDataResult(
                success=False,
                error_message=str(e)
            )

    def save_store_data_service(self, request: SaveStoreDataRequest) -> SaveStoreDataResult:
        """
        SERVICE FIRST: Save store data with validation.

        Args:
            request: SaveStoreDataRequest with data to save

        Returns:
            SaveStoreDataResult indicating success or failure
        """
        try:
            # Validate data structure (basic validation)
            if not isinstance(request.data, dict):
                return SaveStoreDataResult(
                    success=False,
                    error_message="Store data must be a dictionary"
                )

            # Save through proper internal mechanism
            self.store.save(request.data)

            return SaveStoreDataResult(success=True)

        except Exception as e:
            logger.error(f"Error saving store data via service: {e}")
            return SaveStoreDataResult(
                success=False,
                error_message=str(e)
            )

    # ---------------------------
    #   SINGLE POINT OF TRUTH: Helper Methods
    # ---------------------------

    def _calculate_level_from_donations(self, donations: List[Dict[str, Any]]) -> int:
        """
        Calculate current level from donations using Single Point of Truth logic.

        This is the NEW way to calculate level - purely from donation data,
        no more dependency on achieved_levels.json!
        """
        if not donations:
            return 1

        # Find the highest level that was reached via level_upgrade donations
        highest_level = 1
        for donation in donations:
            if donation.get('level_upgrade') and donation.get('level_reached'):
                highest_level = max(highest_level, donation['level_reached'])

        return highest_level

    def _calculate_level_from_total(self, total_amount: int) -> int:
        """
        Calculate what level this total amount should achieve based on current thresholds.

        Uses dynamic/static pricing but respects already achieved levels.
        """
        if total_amount <= 0:
            return 1

        # Get current evolution mode and thresholds
        evolution_mode = self._get_evolution_mode()
        current_thresholds = self._get_current_thresholds(evolution_mode)

        # Find highest level achievable with this amount
        level = 1
        for threshold_level, threshold_amount in current_thresholds.items():
            if total_amount >= threshold_amount:
                level = max(level, threshold_level)

        return level

    def _get_level_info_for_calculation(self, level: int) -> Dict[str, Any]:
        """
        Get threshold and pricing info for a specific level.

        Returns info about whether it was calculated using dynamic or static pricing.
        """
        evolution_mode = self._get_evolution_mode()

        if evolution_mode['use_dynamic']:
            # Dynamic pricing
            dynamic_thresholds = self.get_dynamic_thresholds()
            threshold = dynamic_thresholds.get(level, MECH_LEVELS[level-1].threshold)
            is_dynamic = True
        else:
            # Static pricing with difficulty multiplier
            difficulty = evolution_mode.get('difficulty_multiplier', 1.0)
            base_threshold = MECH_LEVELS[level-1].threshold if level <= len(MECH_LEVELS) else 10000
            threshold = int(base_threshold * difficulty) if level > 1 else 0
            is_dynamic = False

        return {
            'level': level,
            'threshold': threshold,
            'is_dynamic': is_dynamic
        }

    def _get_current_thresholds(self, evolution_mode: Dict[str, Any]) -> Dict[int, int]:
        """
        Get current threshold amounts for all levels based on evolution mode.

        This respects already achieved levels - they keep their original thresholds.
        """
        thresholds = {}

        if evolution_mode['use_dynamic']:
            # Dynamic pricing, but protect achieved levels
            dynamic_thresholds = self.get_dynamic_thresholds()
            achieved_levels = self._get_achieved_levels_from_donations()

            for level in range(1, 12):  # Levels 1-11
                if level in achieved_levels:
                    # Use original threshold for achieved levels
                    thresholds[level] = achieved_levels[level]['threshold_used']
                else:
                    # Use dynamic threshold for future levels
                    base_threshold = MECH_LEVELS[level-1].threshold if level <= len(MECH_LEVELS) else 10000
                    dynamic_threshold = dynamic_thresholds.get(level, base_threshold)
                    thresholds[level] = max(dynamic_threshold, base_threshold)
        else:
            # Static pricing with difficulty multiplier
            difficulty = evolution_mode.get('difficulty_multiplier', 1.0)
            for level in range(1, 12):
                base_threshold = MECH_LEVELS[level-1].threshold if level <= len(MECH_LEVELS) else 10000
                thresholds[level] = int(base_threshold * difficulty) if level > 1 else 0

        return thresholds

    def _get_achieved_levels_from_donations(self) -> Dict[int, Dict[str, Any]]:
        """
        Extract achieved level information from donation history.

        This replaces the old achieved_levels.json dependency.
        """
        try:
            data = self.store.load()
            donations = data.get("donations", [])
            achieved = {}

            for donation in donations:
                if donation.get('level_upgrade') and donation.get('level_reached'):
                    level = donation['level_reached']
                    achieved[level] = {
                        'level': level,
                        'threshold_used': donation.get('threshold_used', 0),
                        'is_dynamic': donation.get('is_dynamic', False),
                        'achieved_at': donation.get('ts'),
                        'donor': donation.get('username')
                    }

            return achieved
        except Exception as e:
            logger.error(f"Error extracting achieved levels from donations: {e}")
            return {}


# ---------------------------
#   Singleton Factory
# ---------------------------

_mech_service_instance: Optional[MechService] = None

def get_mech_service() -> MechService:
    """Get or create the singleton MechService instance."""
    global _mech_service_instance
    if _mech_service_instance is None:
        _mech_service_instance = MechService("config/mech_donations.json")
    return _mech_service_instance


__all__ = [
    "MechService", 
    "MechState",
    "MechBars", 
    "MechLevel",
    "MECH_LEVELS",
    "get_mech_service",
]