# Changelog

## v1.1.2-alpine (2025-01-26)

### 🐛 Bug Fixes
- **ConfigManager Critical Fixes**: Fixed missing attributes `_last_cache_invalidation` and `_min_invalidation_interval` in ConfigManager initialization
- **Configuration Save Errors**: Fixed `'ConfigManager' object has no attribute '_notify_subscribers'` error that prevented configuration saves
- **Cache Invalidation**: Resolved cache invalidation failures that caused repeated config reloads and system instability
- **Observer Pattern**: Added proper subscriber management with `add_subscriber()` and `remove_subscriber()` methods

### 🔧 Technical Improvements
- **Anti-Thrashing**: Implemented minimum 1-second interval between cache invalidations to prevent thrashing
- **Error Handling**: Enhanced error handling in subscriber notifications with individual exception catching
- **System Stability**: Eliminated config cache reload loops that caused excessive log spam
- **Code Quality**: Added comprehensive method documentation and proper initialization of all ConfigManager attributes

### 📋 Notes
- This release focuses on critical stability fixes for the configuration management system
- No breaking changes - fully backward compatible
- Resolves runtime errors that were affecting system reliability

---

## v1.1.1-alpine (2025-01-25)

### 🚀 **Major Performance & Security Update**

**Ultra-Optimized Alpine Linux Image:**
- ✅ **84% size reduction:** From 924MB to 150MB
- ✅ **Alpine Linux 3.22.1:** Latest secure base image
- ✅ **Security fixes:** Flask 3.1.1 & Werkzeug 3.1.3 (all CVEs resolved)
- ✅ **Improved startup time:** Faster container initialization
- ✅ **Reduced memory footprint:** Optimized for resource-constrained environments

**Technical Improvements:**
- ✅ **Docker Socket permissions:** Fixed for proper container management
- ✅ **Configuration persistence:** Resolved volume mount issues
- ✅ **Logging enhancement:** Full application logs visible in `docker logs`
- ✅ **Non-root execution:** Enhanced security with proper user permissions

**Compatibility:**
- ✅ **Full backward compatibility:** All existing features preserved
- ✅ **Unraid optimized:** Perfect integration with Unraid systems
- ✅ **Multi-architecture:** Supports AMD64 and ARM64

--- 