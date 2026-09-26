// The mech panel's client-side power system. Moved out of config.html on
// 2026-09-23: it was 1222 of the page's 1996 lines and 60 KB of its 89 KB, and
// _base.html sends the page Cache-Control: no-cache, so all of it was re-sent on
// every load of the panel. A static file is cached like any other asset.
//
// NOT deferred and not async, on purpose: it was inline at this point in the
// document and ran while the page was being parsed, and initializePowerSystem()
// depends on that. It must also stay AFTER progress_bars.js, which defines
// barWidth - loading it before was the race that had the mech reading OFFLINE
// with empty bars this afternoon.
//
// No Jinja in here - checked before the move and pinned by
// tests/spec/test_the_page_is_not_mostly_one_script.py
document.addEventListener('DOMContentLoaded', function() {
            const donationButtons = document.querySelectorAll('.donation-button');
            const thankYouOverlay = document.getElementById('thankYouOverlay');
            
            donationButtons.forEach(button => {
                button.addEventListener('click', function(e) {
                    const donationType = this.getAttribute('data-donation-type');
                    console.info('💰 [MATRIX] Donation button clicked:', donationType, 'from button:', this);
                    
                    // Record donation click to server
                    fetch('/api/donation/click', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({
                            type: donationType
                        })
                    })
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            // Store for thank you display
                            const donationClickData = {
                                type: donationType,
                                timestamp: Date.now() // Use milliseconds for easier comparison
                            };
                            localStorage.setItem('ddcDonationClick', JSON.stringify(donationClickData));
                            console.info('💰 [MATRIX] Donation button clicked, data stored:', donationClickData);
                            
                            // Update mech immediately
                            // Use new efficient Power system instead
                            syncWithServer();
                        } else {
                            console.error('💰 [MATRIX] Donation click recording failed:', data);
                        }
                    })
                    .catch(error => {
                        console.error('💰 [MATRIX] Error recording donation click:', error);
                    });
                    
                    // Allow normal link behavior (open in new tab)
                    // No e.preventDefault() - let the browser handle the link normally
                });
            });
            
            // Check for donation return on page focus/load
            let isProcessingDonationReturn = false;
            function checkForDonationReturn() {
                console.info('🔍 [MATRIX] checkForDonationReturn called');
                if (isProcessingDonationReturn) {
                    console.info('🔍 [MATRIX] Already processing, returning');
                    return; // Prevent multiple simultaneous calls
                }
                
                const donationData = localStorage.getItem('ddcDonationClick');
                console.info('🔍 [MATRIX] localStorage data:', donationData);
                if (donationData) {
                    try {
                        isProcessingDonationReturn = true;
                        const data = JSON.parse(donationData);
                        const timeSinceClick = Date.now() - data.timestamp;
                        
                        console.info('🔍 [MATRIX] Time since click:', timeSinceClick, 'ms (', Math.round(timeSinceClick/1000), 'seconds )');
                        // Show thank you if donation was clicked within last 60 minutes
                        if (timeSinceClick < 60 * 60 * 1000) {
                            // Mark as shown with timestamp to prevent multiple shows of SAME click
                            const shownKey = `ddcDonationShown_${data.timestamp}`;
                            console.info('🔍 [MATRIX] Checking if already shown:', shownKey);
                            
                            const alreadyShown = localStorage.getItem(shownKey);
                            console.info('🔍 [MATRIX] Already shown result:', alreadyShown);
                            
                            if (!alreadyShown) {
                                console.info('✅ [MATRIX] SHOWING THANK YOU OVERLAY!');
                                // Mark this specific donation click as shown
                                localStorage.setItem(shownKey, 'true');
                                
                                // Clean up old shown markers (older than 1 hour)
                                cleanupOldDonationMarkers();
                                
                                // Show the thank you overlay
                                showThankYouOverlay(data.type);
                                
                                // Also show the donation modal immediately (behind the Matrix overlay)
                                console.log('Also showing donation modal behind Matrix overlay');
                                if (typeof window.showDonationModal === 'function') {
                                    window.showDonationModal();
                                } else {
                                    // Fallback if function not yet available
                                    const modal = document.getElementById('donationModal');
                                    if (modal) {
                                        modal.style.display = 'flex';
                                    }
                                }
                            } else {
                                console.log('Already shown this donation');
                            }
                        } else {
                            console.log('Donation too old');
                        }
                        
                        // Clear the click data after showing (but preserve for future multiple checks)
                        localStorage.removeItem('ddcDonationClick');
                    } catch (e) {
                        // Clean up invalid data
                        localStorage.removeItem('ddcDonationClick');
                    } finally {
                        isProcessingDonationReturn = false;
                    }
                } else {
                    isProcessingDonationReturn = false;
                }
            }
            
            function cleanupOldDonationMarkers() {
                const oneHourAgo = Date.now() - (60 * 60 * 1000);
                const keysToRemove = [];
                let totalCleaned = 0;
                
                // Find old donation markers and other DDC data
                for (let i = 0; i < localStorage.length; i++) {
                    const key = localStorage.key(i);
                    if (key) {
                        // Clean old donation markers
                        if (key.startsWith('ddcDonationShown_')) {
                            const timestamp = parseInt(key.replace('ddcDonationShown_', ''));
                            if (isNaN(timestamp) || timestamp < oneHourAgo) {
                                keysToRemove.push(key);
                                totalCleaned++;
                            }
                        }
                        // Also clean any malformed DDC keys
                        else if (key.startsWith('ddc') && key.includes('undefined')) {
                            keysToRemove.push(key);
                            totalCleaned++;
                        }
                    }
                }
                
                // Remove old markers
                keysToRemove.forEach(key => localStorage.removeItem(key));
                
                if (totalCleaned > 0) {
                    console.log(`Cleaned ${totalCleaned} old localStorage entries`);
                }
            }
            
            function showThankYouOverlay(donationType) {
                console.info('🚀 [MATRIX] showThankYouOverlay called with type:', donationType);
                showMatrixTerminal();
            }
            
            // Make function globally available for testing
            window.checkForDonationReturn = checkForDonationReturn;
            
            // Check on page load
            checkForDonationReturn();
            
            // Check when window gets focus (user returns from donation page)
            window.addEventListener('focus', function() {
                console.info('👁️ [MATRIX] Window focus event triggered');
                // Small delay to ensure page is fully focused
                setTimeout(checkForDonationReturn, 500);
            });
            
            // Check on visibility change (better detection for modern browsers)
            document.addEventListener('visibilitychange', function() {
                console.info('👁️ [MATRIX] Visibility change event triggered, hidden:', document.hidden);
                if (!document.hidden) {
                    setTimeout(checkForDonationReturn, 500);
                }
            });
            
            // Additional periodic check for new tab scenarios
            // Check every 5 seconds if there's a pending donation click
            setInterval(function() {
                const donationData = localStorage.getItem('ddcDonationClick');
                if (donationData) {
                    try {
                        const data = JSON.parse(donationData);
                        const timeSinceClick = Date.now() - data.timestamp;
                        // If donation was clicked within last 60 minutes and no processing in progress
                        if (timeSinceClick < 60 * 60 * 1000 && !isProcessingDonationReturn) {
                            const shownKey = `ddcDonationShown_${data.timestamp}`;
                            // Only check if not already shown
                            if (!localStorage.getItem(shownKey)) {
                                console.info('🔄 [MATRIX] Periodic check found pending donation - checking for return');
                                checkForDonationReturn();
                            } else {
                                console.info('🔄 [MATRIX] Periodic check: donation already shown');
                            }
                        }
                    } catch (e) {
                        // Invalid data, clean up
                        localStorage.removeItem('ddcDonationClick');
                    }
                }
            }, 5000); // Check every 5 seconds
            
            // Auto-close after 8 seconds OR click overlay to close immediately
            let autoCloseTimer = null;
            
            function closeThankYou() {
                if (autoCloseTimer) {
                    clearTimeout(autoCloseTimer);
                    autoCloseTimer = null;
                }
                thankYouOverlay.style.animation = 'thankYouFadeOut 0.5s ease-out';
                setTimeout(() => {
                    thankYouOverlay.style.display = 'none';
                    thankYouOverlay.style.animation = '';
                    console.log('Matrix Thank You closed, donation modal should already be visible');
                    // Modal should already be open, just focus on input
                    const amountInput = document.getElementById('donationAmount');
                    if (amountInput) {
                        amountInput.focus();
                        console.log('Amount input focused');
                    }
                }, 500);
            }
            
            // Click overlay to close immediately
            thankYouOverlay.addEventListener('click', closeThankYou);
            
            // Auto-close after 8 seconds if no interaction
            thankYouOverlay.addEventListener('animationend', function(e) {
                if (e.animationName === 'thankYouFadeIn') {
                    autoCloseTimer = setTimeout(closeThankYou, 8000);
                }
            });
        });
        
        // Matrix Terminal Animation
        
        function showMatrixTerminal() {
            console.info('🎬 [MATRIX] showMatrixTerminal called');
            const overlay = document.getElementById('thankYouOverlay');
            const textElement = document.getElementById('thankYouText');
            
            console.info('🎬 [MATRIX] Matrix overlay:', overlay);
            console.info('🎬 [MATRIX] Matrix text element:', textElement);
            
            if (!overlay || !textElement) {
                console.error('🎬 [MATRIX] Matrix elements not found!');
                return;
            }
            
            // Show overlay
            overlay.style.display = 'flex';
            textElement.innerHTML = '';
            
            // Timeline: 10 seconds total
            // 0-2s: Cursor blinks
            // 2-4s: Type "Thank You!"
            // 4-6s: Cursor blinks alone 
            // 6-8s: Type "You rule!"
            // 8-10s: Cursor blinks alone
            // 10s: Close
            
            setTimeout(() => {
                typeText(textElement, 'Thank You!', 100, () => {
                    setTimeout(() => {
                        textElement.innerHTML += ' ';
                        typeText(textElement, 'You rule!', 100, () => {
                            setTimeout(() => {
                                overlay.style.display = 'none';
                                textElement.innerHTML = '';
                            }, 2000); // Wait 2s then close
                        });
                    }, 2000); // Wait 2s between messages
                });
            }, 2000); // Wait 2s before first message
        }
        
        function typeText(element, text, speed, callback) {
            let i = 0;
            const timer = setInterval(() => {
                if (i < text.length) {
                    element.innerHTML += text.charAt(i);
                    i++;
                } else {
                    clearInterval(timer);
                    if (callback) callback();
                }
            }, speed);
        }
        
        // Donator Heart Management
        function updateDonatorHeart(donationTimestamp) {
            // No longer storing locally - server handles it
            // Just refresh the mech status from server
            // Use new efficient Power system instead
            syncWithServer();
        }
        
        // Speed description function (simplified version of Python speed_levels.py)
        function getSpeedDescription(level) {
            const speeds = {
                0: {text: "OFFLINE", color: "#888888"},
                1: {text: "Motionless", color: "#4a4a4a"},
                2: {text: "Barely perceptible", color: "#525252"},
                3: {text: "Extremely sluggish", color: "#5a5a5a"},
                4: {text: "Painfully hesitant", color: "#626262"},
                5: {text: "Excruciatingly lethargic", color: "#6a6a6a"},
                10: {text: "Glacially slow", color: "#929292"},
                15: {text: "Faltering pace", color: "#bababa"},
                20: {text: "Slow but continuous", color: "#e2e2e2"},
                25: {text: "Measured walking", color: "#ccaa00"},
                30: {text: "Decisive stride", color: "#88cc00"},
                35: {text: "Fast stride", color: "#33cc00"},
                40: {text: "Quick-paced", color: "#00cc22"},
                45: {text: "Hurrying intensely", color: "#00cc77"},
                50: {text: "Sharply swift", color: "#00cccc"},
                55: {text: "Racing step", color: "#0077cc"},
                60: {text: "Almost running", color: "#0022cc"},
                65: {text: "Fast jogging", color: "#3300cc"},
                70: {text: "Rapid running", color: "#8800cc"},
                75: {text: "Relentless sprint", color: "#cc00bb"},
                80: {text: "Supersonic pace", color: "#cc0066"},
                85: {text: "Breakneck velocity", color: "#cc0011"},
                90: {text: "Star-chasing speed", color: "#ff3300"},
                95: {text: "Warp-level 5", color: "#ff8800"},
                100: {text: "Beyond-lightspeed", color: "#ffdd00"},
                101: {text: "Godspeed", color: "#ffff00"}
            };
            
            // Find the closest level match
            let bestMatch = speeds[0];
            for (let speedLevel in speeds) {
                if (level >= parseInt(speedLevel)) {
                    bestMatch = speeds[speedLevel];
                }
            }
            
            return bestMatch;
        }
        
        // Animation cache - persistent across page reloads
        let lastAnimationPowerLevel = localStorage.getItem('ddcLastAnimationPowerLevel') ? 
            parseInt(localStorage.getItem('ddcLastAnimationPowerLevel')) : null;
        
        // ===================================================================
        // POWER SYSTEM v3.0 - Ultra-Efficient Client-Server Hybrid
        // ===================================================================
        // Performance: 100 DOM updates/day, 60 API calls/hour (99% reduction)
        // ===================================================================
        
        // Configuration
        const POWER_CONFIG = {
            DECAY_RATE: 1 / 86400,           // Default: 1 Power per day (in seconds) - updated dynamically
            UPDATE_PRECISION: 0.01,          // Update display on 0.01 changes
            CLIENT_CHECK_INTERVAL: 10000,    // Check every 10 seconds
            SERVER_SYNC_INTERVAL: 60000,     // Sync with server every 60 seconds
            DONATION_THRESHOLD: 0.5          // Detect donations > $0.50
        };
        
        // State management
        const PowerState = {
            serverPower: 0,                   // Last known server Power value
            serverTime: Date.now(),          // When we got server value
            lastDisplayDecimal: null,        // Last displayed decimal value
            lastAnimationLevel: null,        // Last animation integer level
            serverData: null                 // Full server response data
        };
        
        // ===================================================================
        // INITIALIZATION
        // ===================================================================
        
        (function initializePowerSystem() {
            console.log('[POWER v3.0] Initializing ultra-efficient Power system');
            
            // Clear any old intervals from previous page loads
            const maxInterval = setInterval(() => {}, 0);
            for (let i = 0; i < maxInterval; i++) clearInterval(i);
            
            // Start the system
            loadInitialPowerData();
            
            // Schedule periodic updates
            setInterval(updateClientSidePower, POWER_CONFIG.CLIENT_CHECK_INTERVAL);
            setInterval(syncWithServer, POWER_CONFIG.SERVER_SYNC_INTERVAL);
            
            // Expose global update function for external triggers
            window.forcePowerUpdate = function() {
                console.log('[POWER v3.0] Force update triggered');
                PowerState.lastDisplayDecimal = null;
                updateClientSidePower();
                syncWithServer();
            };
        })();
        
        // ===================================================================
        // CORE FUNCTIONS
        // ===================================================================
        
        async function loadInitialPowerData() {
            try {
                const response = await fetch('/api/donation/status');
                const data = await response.json();
                
                PowerState.serverPower = data.current_Power_raw || data.current_Power || 0;
                PowerState.serverTime = Date.now();
                PowerState.serverData = data;

                // Take the level-specific decay rate straight away. Until v2.4.1 only
                // syncWithServer() did this, and that first runs after SERVER_SYNC_INTERVAL
                // (60 s) - so for the first minute the display counted down with the default
                // of 1 $/day instead of the real rate (1.50 $/day on level 6), which made the
                // power appear to drain more slowly than it does.
                if (data.decay_per_day !== undefined) {
                    POWER_CONFIG.DECAY_RATE = data.decay_per_day / 86400;
                    updateConsumptionOverlay(data.decay_per_day);
                }
                
                console.log(`[POWER v3.0] Initial load: $${PowerState.serverPower.toFixed(2)}`);
                updatePowerDisplay(PowerState.serverPower);
                updateBarsFromServerData(data);
                
                // Load initial animation immediately (force load)
                const PowerInteger = Math.floor(PowerState.serverPower);
                PowerState.lastAnimationLevel = null; // Force initial load
                updateMechAnimation(PowerInteger);
                
                console.log(`[POWER v3.0] Initial animation loaded for Power level: ${PowerInteger}`);
            } catch (error) {
                console.error('[POWER v3.0] Initial load failed:', error);
            }
        }
        
        function updateClientSidePower() {
            const now = Date.now();
            const elapsedSeconds = (now - PowerState.serverTime) / 1000;
            
            // Calculate current Power with decay
            const decayAmount = elapsedSeconds * POWER_CONFIG.DECAY_RATE;
            const currentPower = Math.max(0, PowerState.serverPower - decayAmount);
            
            // Only update display if decimal changed
            const currentDecimal = Math.floor(currentPower * 100) / 100;
            if (PowerState.lastDisplayDecimal !== currentDecimal) {
                PowerState.lastDisplayDecimal = currentDecimal;
                updatePowerDisplay(currentPower);
                
                // Also update NEXT bar with local calculation
                updateNextBarLocal(currentPower);
                
                // Check for animation update (integer change)
                const PowerInteger = Math.floor(currentPower);
                if (PowerState.lastAnimationLevel !== PowerInteger) {
                    PowerState.lastAnimationLevel = PowerInteger;
                    updateMechAnimation(PowerInteger);
                }
            }
        }
        
        async function syncWithServer() {
            try {
                const response = await fetch('/api/donation/status');
                const data = await response.json();

                // Update decay rate from server (level-specific)
                if (data.decay_per_day !== undefined) {
                    POWER_CONFIG.DECAY_RATE = data.decay_per_day / 86400;  // Convert per-day to per-second
                    updateConsumptionOverlay(data.decay_per_day);
                    console.log(`[POWER v3.0] Decay rate updated: ${data.decay_per_day}/day (${POWER_CONFIG.DECAY_RATE.toFixed(8)}/s)`);
                }

                const serverPower = data.current_Power_raw || data.current_Power || 0;
                const expectedPower = PowerState.serverPower - ((Date.now() - PowerState.serverTime) / 1000 * POWER_CONFIG.DECAY_RATE);
                const difference = Math.abs(serverPower - expectedPower);
                
                // Always update bars with server calculations
                updateBarsFromServerData(data);
                
                // Sync Power if significant difference detected (new donation)
                if (difference > POWER_CONFIG.DONATION_THRESHOLD) {
                    console.log(`[POWER v3.0] Donation detected: $${PowerState.serverPower.toFixed(2)} → $${serverPower.toFixed(2)}`);
                    PowerState.serverPower = serverPower;
                    PowerState.serverTime = Date.now();
                    PowerState.lastDisplayDecimal = null;
                    PowerState.serverData = data;
                }
            } catch (error) {
                // Silent fail to avoid console spam
            }
        }
        
        function updatePowerDisplay(powerAmount) {
            // Simple display update - all complex calculations come from server
            const powerAmountEl = document.getElementById('powerAmount');
            if (powerAmountEl) {
                powerAmountEl.textContent = `${powerAmount.toFixed(2)}`;
            }
            
            // For bars, we need the full server data, not just Power amount
            // This will be updated when we get server response
        }
        
        function updateNextBarLocal(powerAmount) {
            // There is no NEXT bar in HTML - this function does nothing currently
            // The Evolution bar shows progress to next evolution level, not next dollar
            // If we want a "next dollar" bar, we need to add it to the HTML
        }
        
        function updateBarsFromServerData(data) {
            // Use ACTUAL server calculations from MechService
            const powerLevel = document.getElementById('powerLevel');
            const evolutionProgress = document.getElementById('evolutionProgress');
            const nextEvolutionName = document.getElementById('nextEvolutionName');
            const nextEvolutionAmount = document.getElementById('nextEvolutionAmount');
            const speedStatusOverlay = document.getElementById('speedStatusOverlay');
            
            // Update POWER Bar using server's bar calculations
            if (powerLevel && data.bars) {
                // barWidth() answers null when the server could not measure the
                // maximum; dividing here made that a FULL bar (5 / null is Infinity).
                const percentage = barWidth(data.bars.Power_current, data.bars.Power_max_for_level);
                powerLevel.style.width = percentage === null ? '0%' : `${percentage}%`;
                powerLevel.title = percentage === null ? 'Power could not be read' : '';
                
                // Color based on actual Power amount
                const Power = data.current_Power_raw || data.current_Power || 0;
                if (Power >= 500) {
                    powerLevel.style.background = 'linear-gradient(90deg, #00ffff 0%, #0099ff 50%, #00ffff 100%)';
                } else if (Power >= 250) {
                    powerLevel.style.background = 'linear-gradient(90deg, #00ff00 0%, #00dd00 50%, #00ff00 100%)';
                } else if (Power >= 100) {
                    powerLevel.style.background = 'linear-gradient(90deg, #ffcc00 0%, #ff9900 50%, #ffcc00 100%)';
                } else if (Power >= 50) {
                    powerLevel.style.background = 'linear-gradient(90deg, #ff6600 0%, #ff3300 50%, #ff6600 100%)';
                } else {
                    powerLevel.style.background = 'linear-gradient(90deg, #cc0000 0%, #990000 50%, #cc0000 100%)';
                }
            }
            
            // Update Evolution Bar (the "NEXT" bar for evolution progress)
            if (evolutionProgress && data) {
                // Use server data for evolution progress
                if (data.bars) {
                    const percentage = barWidth(data.bars.mech_progress_current, data.bars.mech_progress_max);
                    evolutionProgress.style.width = percentage === null ? '0%' : `${percentage}%`;
                    evolutionProgress.title = percentage === null ? 'Progress could not be read' : '';
                }
                
                // Update evolution text
                if (nextEvolutionName && nextEvolutionAmount) {
                    const currentLevel = data.mech_level || 1;

                    // Check if we're at MAX LEVEL (Level 11)
                    if (currentLevel >= 11) {
                        nextEvolutionName.textContent = "MAX EVOLUTION REACHED";
                        nextEvolutionAmount.textContent = "🌟 OMEGA MECH ACHIEVED";
                    } else {
                        // The next evolution's name comes from the server, which reads the same
                        // configured list Discord uses. This used to be a hardcoded array here
                        // ("STANDARD MECH", ...) that had drifted from the configured names
                        // ("The Corewalker Standard", ...), so the panel and Discord disagreed
                        // about the same level.
                        if (data.next_level_name) {
                            nextEvolutionName.textContent = data.next_level_name;
                        }

                        // Update amount needed
                        if (data.bars && data.bars.mech_progress_max !== undefined) {
                            const currentProgress = data.bars.mech_progress_current || 0;
                            const maxProgress = data.bars.mech_progress_max || 0;
                            const needed = Math.max(0, maxProgress - currentProgress);
                            nextEvolutionAmount.textContent = `$${needed.toFixed(2)} needed`;
                        }
                    }
                }
            }

            // Update Speed Status based on mech level and power
            if (speedStatusOverlay && data) {
                const currentLevel = data.mech_level || 1;
                const currentPower = data.current_Power_raw || data.current_Power || 0;

                // For Level 11 (OMEGA MECH), show special status
                if (currentLevel >= 11) {
                    speedStatusOverlay.textContent = "REALITY BENDING";
                    speedStatusOverlay.style.color = "#ff00ff";
                    speedStatusOverlay.style.textShadow = "0 0 10px #ff00ff";
                } else {
                    // Use backend API for accurate speed calculation instead of flawed Math.floor
                    if (data && data.speed) {
                        // Use speed info from API response (includes correct power ratio calculation)
                        speedStatusOverlay.textContent = data.speed.description;
                        speedStatusOverlay.style.color = data.speed.color;
                        speedStatusOverlay.style.textShadow = "none";
                    } else {
                        // Fallback for missing speed data - fetch from API
                        fetch('/api/donation/status')
                            .then(response => response.json())
                            .then(apiData => {
                                if (apiData && apiData.speed) {
                                    speedStatusOverlay.textContent = apiData.speed.description;
                                    speedStatusOverlay.style.color = apiData.speed.color;
                                    speedStatusOverlay.style.textShadow = "none";
                                } else {
                                    // Final fallback: Use simple 1:1 mapping (1 Power = 1 Speed Level)
                                    // This is not evolution-aware but better than nothing
                                    const glvl = currentPower <= 0 ? 0 : Math.max(1, Math.min(100, Math.floor(currentPower)));
                                    const speedInfo = getSpeedDescription(glvl);
                                    speedStatusOverlay.textContent = speedInfo.text;
                                    speedStatusOverlay.style.color = speedInfo.color;
                                    speedStatusOverlay.style.textShadow = "none";
                                }
                            })
                            .catch(() => {
                                // Final fallback: Use simple 1:1 mapping (1 Power = 1 Speed Level)
                                // This is not evolution-aware but better than nothing
                                const glvl = currentPower <= 0 ? 0 : Math.max(1, Math.min(100, Math.floor(currentPower)));
                                const speedInfo = getSpeedDescription(glvl);
                                speedStatusOverlay.textContent = speedInfo.text;
                                speedStatusOverlay.style.color = speedInfo.color;
                                speedStatusOverlay.style.textShadow = "none";
                            });
                    }
                }
            }
        }
        
        function updateMechAnimation(PowerInteger) {
            const mechImg = document.getElementById('donatorMechAnimation');
            if (mechImg) {
                // Cache key for localStorage
                const cacheKey = `ddcMechAnimation_${PowerInteger}`;
                const lastLevel = localStorage.getItem('ddcLastAnimationPowerLevel');
                
                // Force reload if no previous level stored OR level changed
                if (lastLevel === null || lastLevel !== PowerInteger.toString()) {
                    mechImg.src = `/mech_animation?t=${Date.now()}`;
                    localStorage.setItem('ddcLastAnimationPowerLevel', PowerInteger.toString());
                    console.log(`[POWER] Animation updated for Power level: ${PowerInteger} (was: ${lastLevel || 'none'})`);
                } else {
                    console.log(`[POWER] Animation unchanged for Power level: ${PowerInteger}`);
                }
            } else {
                console.error('[POWER] Mech animation element not found!');
            }
        }
        
        // Show the ACTUAL consumption per second, derived from the server's level-specific
        // decay rate. This element used to carry the fixed literal -$0.00003472 (about 3 $/day),
        // which matched no configured rate - the real one is 1.50 $/day on level 6 - and nothing
        // ever recomputed it.
        function updateConsumptionOverlay(decayPerDay) {
            const overlay = document.getElementById('powerConsumptionOverlay');
            if (!overlay) return;
            const perDay = Number(decayPerDay);
            if (!isFinite(perDay) || perDay <= 0) {
                overlay.textContent = '';   // level 11 never decays - show nothing rather than a zero
                return;
            }
            overlay.textContent = `-$${(perDay / 86400).toFixed(8)}`;
        }

        // Flash consumption overlay with fade animation every 3 seconds (only if Power > 0)
        function flashConsumptionOverlay() {
            const overlay = document.getElementById('powerConsumptionOverlay');
            const powerAmount = document.getElementById('powerAmount');
            
            if (overlay && powerAmount) {
                // Parse current Power amount
                const currentPower = parseFloat(powerAmount.textContent.replace('$', ''));
                
                // Only show consumption animation if we have Power
                if (currentPower > 0) {
                    overlay.style.transition = 'opacity 0.3s ease-in';
                    overlay.style.opacity = '1';
                    
                    // Hide after 1 second (same timing as Next Bar)
                    setTimeout(() => {
                        overlay.style.transition = 'opacity 0.5s ease-out';
                        overlay.style.opacity = '0';
                    }, 1000);
                }
            }
        }
        
        // OLD: Consumption overlay moved to efficient client-side system
        // setInterval(flashConsumptionOverlay, 3000); // DISABLED - using client-side calculation
        
        // Donation Modal Functions
        function showDonationModal() {
            const modal = document.getElementById('donationModal');
            if (modal) {
                // Prevent double-opening
                if (modal.style.display === 'flex') {
                    return;
                }
                
                modal.style.display = 'flex';
                // Focus on amount input
                setTimeout(() => {
                    const amountInput = document.getElementById('donationAmount');
                    if (amountInput) {
                        amountInput.focus();
                    }
                }, 100);
            }
        }
        
        // Make modal functions globally available
        window.showDonationModal = showDonationModal;
        
        function closeDonationModal() {
            const modal = document.getElementById('donationModal');
            if (modal) {
                modal.style.display = 'none';
                // Reset form
                document.getElementById('donationForm').reset();
                document.getElementById('publishToDiscord').checked = true; // Default to checked
            }
        }
        
        function submitDonation() {
            const amountInput = document.getElementById('donationAmount');
            const donorNameInput = document.getElementById('donorName');
            const publishCheckbox = document.getElementById('publishToDiscord');
            
            // Check if elements exist
            if (!amountInput || !donorNameInput || !publishCheckbox) {
                alert('Error: Form elements not found. Please try again.');
                return;
            }
            
            const amount = amountInput.value.trim();
            const donorName = donorNameInput.value.trim() || 'Anonymous';
            const publishToDiscord = publishCheckbox.checked;
            
            // Enhanced amount validation
            if (!amount) {
                alert('Please enter a donation amount.');
                amountInput.focus();
                return;
            }
            
            const parsedAmount = parseFloat(amount);
            if (isNaN(parsedAmount) || parsedAmount <= 0) {
                alert('Please enter a valid positive donation amount.');
                amountInput.focus();
                return;
            }
            
            if (parsedAmount > 999999) {
                alert('Maximum donation amount is $999,999.');
                amountInput.focus();
                return;
            }
            
            // Validate donor name length
            if (donorName.length > 50) {
                alert('Donor name must be 50 characters or less.');
                donorNameInput.focus();
                return;
            }
            
            // Disable submit button to prevent double-submission
            const submitBtn = document.querySelector('button[onclick="submitDonation()"]');
            if (submitBtn) {
                submitBtn.disabled = true;
                submitBtn.textContent = '⏳ Processing...';
            }
            
            // Helper function to re-enable button
            function resetSubmitButton() {
                if (submitBtn) {
                    submitBtn.disabled = false;
                    submitBtn.textContent = '🚀 ⚡ Power the Mech!';
                }
            }
            
            // One-shot token per submission. It is created on the first submit and
            // only retired after a confirmed booking, so a retry after the 30s
            // timeout carries the SAME token and books once. crypto.randomUUID
            // exists only in a secure context; DDC deliberately runs plain HTTP on
            // the LAN (SPEC.md B3), hence the fallback - without it no token would
            // be generated at all and the submission would go out unprotected.
            // See SPEC.md Z4.
            if (!window.__ddcDonationToken) {
                window.__ddcDonationToken = (window.crypto && crypto.randomUUID)
                    ? crypto.randomUUID()
                    : 'web-' + Date.now().toString(16) + '-' + Math.random().toString(16).slice(2);
            }

            // Prepare donation data
            const donationData = {
                amount: parseFloat(amount),
                donor_name: donorName,
                publish_to_discord: publishToDiscord,
                source: 'web_ui_manual',
                idempotency_key: window.__ddcDonationToken
            };
            
            // Debug: Log what we're sending
            console.log('🔍 DONATION DEBUG: Sending data:', donationData);
            console.log('🔍 DONATION DEBUG: publish_to_discord =', publishToDiscord, '(type:', typeof publishToDiscord, ')');
            
            // Submit donation to server with timeout
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 30000); // 30 second timeout
            
            fetch('/api/donation/submit', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(donationData),
                signal: controller.signal
            })
            .then(response => {
                clearTimeout(timeoutId);
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }
                return response.json();
            })
            .then(data => {
                if (data.success) {
                    // Booking confirmed - retire the token so the next donation gets
                    // a fresh one. A page reload is a genuinely new donation.
                    window.__ddcDonationToken = null;

                    // Reset button first
                    resetSubmitButton();
                    
                    // Close modal
                    closeDonationModal();
                    
                    // Refresh mech status to show new Power
                    // Use new efficient Power system instead
            syncWithServer();
                    
                    // Show success message
                    showSuccessMessage(`🚀 Thank you ${donorName}! $${amount} added to mech Power!`);
                } else {
                    alert('Error processing donation: ' + (data.error || 'Unknown error'));
                    resetSubmitButton();
                }
            })
            .catch(error => {
                clearTimeout(timeoutId);
                console.error('Error submitting donation:', error);
                
                // Better error messages for users
                let userMessage = 'Error submitting donation. Please try again.';
                if (error.name === 'AbortError') {
                    userMessage = 'Request timeout. Please check your connection and try again.';
                } else if (error.message.includes('HTTP')) {
                    userMessage = `Server error: ${error.message}. Please try again later.`;
                } else if (!navigator.onLine) {
                    userMessage = 'No internet connection. Please check your connection.';
                }
                
                alert(userMessage);
                resetSubmitButton();
            });
        }
        
        function showSuccessMessage(message) {
            // Create temporary success message using safe DOM manipulation
            const alertDiv = document.createElement('div');
            alertDiv.className = 'alert alert-success';
            alertDiv.style.cssText = 'position: fixed; top: 20px; right: 20px; z-index: 3000; animation: slideInRight 0.3s ease;';

            // Use textContent to safely insert message (auto-escapes HTML)
            alertDiv.textContent = message;

            document.body.appendChild(alertDiv);

            // Remove after 4 seconds
            setTimeout(() => {
                alertDiv.style.animation = 'slideOutRight 0.3s ease';
                setTimeout(() => document.body.removeChild(alertDiv), 300);
            }, 4000);
        }
        
        // Close modal when clicking overlay background
        document.addEventListener('click', function(event) {
            const modal = document.getElementById('donationModal');
            if (event.target === modal) {
                closeDonationModal();
            }
        });
        
        // Close modal with Escape key
        document.addEventListener('keydown', function(event) {
            if (event.key === 'Escape') {
                closeDonationModal();
            }
        });
        
        
        
                
        
        // Additional animations for different donation types
        const additionalStyles = `
            @keyframes thankYouFadeOut {
                from { opacity: 1; transform: scale(1); }
                to { opacity: 0; transform: scale(0.9); }
            }
            
            @keyframes thankYouCoffeeShake {
                0%, 100% { transform: rotate(0deg); }
                25% { transform: rotate(-2deg); }
                75% { transform: rotate(2deg); }
            }
            
            @keyframes thankYouPaypalGlow {
                0%, 100% { box-shadow: 0 0 0 rgba(0,112,186,0.5); }
                50% { box-shadow: 0 0 30px rgba(0,112,186,0.8); }
            }
        `;
        
        const styleSheet = document.createElement('style');
        styleSheet.textContent = additionalStyles;
        document.head.appendChild(styleSheet);
        
        // Mech Animation Test Functions
        
        
