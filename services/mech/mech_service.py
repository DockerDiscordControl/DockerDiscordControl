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
    """Instance-wide black-box for DDC.

    Rules:
    - Donations persist in JSON (username, amount, timestamp).
    - Mech level from cumulative donations.
    - Power increases by donation dollars.
    - On level-up, Power resets to 1 plus overshoot beyond the new level threshold.
    - Power decays continuously: 1 Power per 86400 seconds (second-accurate).
    - Evolution costs are dynamic based on unique Discord members in status channels.
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
        self.member_count_cache = None  # Cache for member count
        self.dynamic_thresholds = None  # Cache for dynamic thresholds
        self._store_lock = threading.Lock()  # Protect load-modify-save operations

    # -------- Public API --------

    def set_member_count(self, count: int) -> None:
        """Update the member count for dynamic evolution costs."""
        self.member_count_cache = count

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
                glvl_max=state.glvl_max
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
                error_message=str(e)
            )

    def add_donation_service(self, request: AddDonationRequest) -> AddDonationResult:
        """SERVICE FIRST: Add donation with Request/Result pattern."""
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
        self.dynamic_thresholds = None  # Clear threshold cache
        logger.info(f"MechService: Member count updated to {count}")
    
    def get_dynamic_thresholds(self) -> Dict[int, int]:
        """Get dynamic thresholds based on current member count."""
        if self.dynamic_thresholds is not None:
            return self.dynamic_thresholds
            
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
                thresholds[level] = threshold
        
        self.dynamic_thresholds = thresholds
        cache_info = cache.get_cache_info()
        logger.debug(f"Dynamic thresholds calculated using monthly cache from {cache_info.get('month_year', 'N/A')}")
        return thresholds

    def add_donation(self, username: str, amount: int, ts_iso: Optional[str] = None) -> MechState:
        """Persist a donation and return the fresh state."""
        if not isinstance(amount, int):
            raise TypeError("amount must be an integer")
        if amount <= 0:
            raise ValueError("amount must be a positive integer number of dollars")
        if amount > 1000000:
            raise ValueError("amount exceeds maximum allowed value (1,000,000)")
        if not username or len(username) > 100:
            raise ValueError("username must be between 1 and 100 characters")

        ts = self._now() if ts_iso is None else self._parse_iso(ts_iso)

        # Thread-safe load-modify-save
        with self._store_lock:
            data = self.store.load()
            data.setdefault("donations", [])
            data["donations"].append({
                "username": username,
                "amount": int(amount),
                "ts": ts.isoformat(),
            })
            self.store.save(data)

        return self.get_state(now_iso=ts.isoformat())
    
    async def add_donation_with_bot(self, username: str, amount: int, bot=None, ts_iso: Optional[str] = None) -> MechState:
        """Persist a donation with optimized community count check and return the fresh state."""
        if amount <= 0:
            raise ValueError("amount must be a positive integer number of dollars")

        # Check if monthly member cache needs updating (random monthly updates)
        if bot:
            try:
                from .monthly_member_cache import get_monthly_member_cache
                cache = get_monthly_member_cache()
                
                # Non-blocking cache update check
                updated = await cache.update_member_count_if_needed(bot)
                if updated:
                    logger.info(f"Monthly member cache updated during donation from {username}")
                    # Clear dynamic thresholds cache to force recalculation
                    self.dynamic_thresholds = None
                    
            except Exception as e:
                logger.error(f"Error checking monthly member cache: {e}")
                # Continue with existing cache

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

        # Get dynamic thresholds based on current member count
        dynamic_thresholds = self.get_dynamic_thresholds()
        
        # Build dynamic MechLevel objects
        dynamic_levels = []
        for i, static_level in enumerate(MECH_LEVELS):
            if static_level.level in dynamic_thresholds:
                dynamic_levels.append(MechLevel(
                    level=static_level.level,
                    name=static_level.name,
                    threshold=dynamic_thresholds[static_level.level]
                ))
            else:
                dynamic_levels.append(static_level)

        total: int = 0
        Power: float = 0.0  # internal float to support fractional decay
        lvl: MechLevel = dynamic_levels[0]
        last_ts: Optional[datetime] = None
        last_evolution_ts: Optional[datetime] = None

        for d in donations:
            ts = self._parse_iso(d["ts"])
            if last_ts is not None:
                Power = max(0.0, Power - self._decay_amount(last_ts, ts, lvl.level))
            last_ts = ts

            amount = int(d["amount"])
            total += amount
            Power += amount

            # Handle (possibly multi-step) level-ups in one donation
            # Recalculate dynamic thresholds at each level-up check
            while True:
                # Recalculate thresholds for current community size
                current_dynamic_thresholds = self.get_dynamic_thresholds()
                
                # Rebuild dynamic levels with current thresholds
                current_dynamic_levels = []
                for i, static_level in enumerate(MECH_LEVELS):
                    if static_level.level in current_dynamic_thresholds:
                        current_dynamic_levels.append(MechLevel(
                            level=static_level.level,
                            name=static_level.name,
                            threshold=current_dynamic_thresholds[static_level.level]
                        ))
                    else:
                        current_dynamic_levels.append(static_level)
                
                # Get next level from recalculated dynamic levels
                try:
                    nxt = current_dynamic_levels[lvl.level] if lvl.level < len(current_dynamic_levels) else None
                except IndexError:
                    nxt = None
                if not nxt:
                    break
                if total >= nxt.threshold:
                    old_level = lvl.level
                    lvl = nxt
                    # fresh level starts with 1 + overshoot beyond this level's threshold
                    Power = 1.0 + max(0, total - lvl.threshold)
                    last_evolution_ts = ts  # Track when evolution occurred
                    
                    # Log the level-up with dynamic cost information
                    logger.info(
                        f"Mech evolved from Level {old_level} to Level {lvl.level} "
                        f"(threshold: ${lvl.threshold}, total donations: ${total})"
                    )
                    continue
                break

        # decay from last donation to "now" - but only if enough time passed since evolution
        if last_ts is not None:
            # If evolution just happened (within 1 minute), don't apply immediate decay
            evolution_was_recent = (last_evolution_ts is not None and
                                  (now - last_evolution_ts).total_seconds() < 60)
            if evolution_was_recent:
                # Evolution just occurred - no decay yet, mech has fresh Power
                pass
            else:
                # Normal decay from last donation
                Power = max(0.0, Power - self._decay_amount(last_ts, now, lvl.level))

        # Compose bars & glvl
        # Get next level from dynamic levels
        # For Level 10+: Show corrupted/hacked Level 11 data as easter egg
        try:
            if lvl.level >= 10:
                # Create corrupted OMEGA MECH entry for Level 10 users
                from types import SimpleNamespace
                nxt = SimpleNamespace()
                nxt.level = 11
                nxt.name = "ERR#R: [DATA_C0RR*PTED]"
                nxt.threshold = 10000  # Real threshold for percentage calculation
            else:
                nxt = dynamic_levels[lvl.level] if lvl.level < len(dynamic_levels) else None
        except IndexError:
            nxt = None
        
        # Calculate delta using dynamic thresholds
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
            Power_current=int(max(0, math.floor(Power))),
            Power_max_for_level=int(Power_max),
        )

        return MechState(
            total_donated=int(total),
            level=lvl.level,
            level_name=lvl.name,
            next_level_threshold=None if not nxt else nxt.threshold,
            Power=int(max(0, math.floor(Power))),
            glvl=int(glvl),
            glvl_max=int(glvl_max),
            bars=bars,
        )

    def get_power_with_decimals(self) -> float:
        """Get raw Power value with decimal places for Web UI display"""
        data = self.store.load()
        donations = data["donations"]
        
        # Get dynamic thresholds
        dynamic_thresholds = self.get_dynamic_thresholds()
        
        # Build dynamic MechLevel objects
        dynamic_levels = []
        for i, static_level in enumerate(MECH_LEVELS):
            if static_level.level in dynamic_thresholds:
                dynamic_levels.append(MechLevel(
                    level=static_level.level,
                    name=static_level.name,
                    threshold=dynamic_thresholds[static_level.level]
                ))
            else:
                dynamic_levels.append(static_level)
        
        total = 0.0
        Power = 0.0
        lvl = dynamic_levels[0]  # Start at level 1
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

            # Handle level-ups using dynamic levels with real-time recalculation
            while True:
                # Recalculate thresholds for current community size at each level-up
                current_dynamic_thresholds = self.get_dynamic_thresholds()
                
                # Rebuild dynamic levels with current thresholds
                current_dynamic_levels = []
                for i, static_level in enumerate(MECH_LEVELS):
                    if static_level.level in current_dynamic_thresholds:
                        current_dynamic_levels.append(MechLevel(
                            level=static_level.level,
                            name=static_level.name,
                            threshold=current_dynamic_thresholds[static_level.level]
                        ))
                    else:
                        current_dynamic_levels.append(static_level)
                
                try:
                    nxt = current_dynamic_levels[lvl.level] if lvl.level < len(current_dynamic_levels) else None
                except IndexError:
                    nxt = None
                if not nxt:
                    break
                if total >= nxt.threshold:
                    lvl = nxt
                    Power = 1.0 + max(0, total - lvl.threshold)
                    last_evolution_ts = ts
                    continue
                break

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
            self.logger.warning(f"MechDecayService failed, using fallback: {result.error}")
            sec = (b.astimezone(self.tz) - a.astimezone(self.tz)).total_seconds()
            return max(0.0, (sec / 86400.0) * 1.0)  # Default 1.0 decay rate


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