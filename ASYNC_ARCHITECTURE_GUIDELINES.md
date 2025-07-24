# Async Architecture Guidelines - DockerDiscordControl (DDC)

## 🎯 Purpose
This document provides essential guidelines for maintaining consistent async/await patterns in the DockerDiscordControl codebase. **Follow these rules to prevent async/sync conflicts.**

---

## 🔄 Core Async Functions - DO NOT CHANGE TO SYNC

### Docker Client Management
```python
# ✅ CORRECT - These functions are ASYNC by design
async def get_docker_client() -> docker.DockerClient
async def release_docker_client() -> None
async def docker_action(docker_container_name: str, action: str) -> bool
async def get_docker_stats(docker_container_name: str) -> Tuple[Optional[Dict], Optional[Dict]]
```

**⚠️ CRITICAL**: Never convert `get_docker_client()` to synchronous. It uses:
- Thread-safe locks (`_docker_client_lock`)
- `asyncio.to_thread()` for Docker API calls
- Async ping operations with caching

### Container Operations
```python
# ✅ CORRECT - These functions are ASYNC
async def list_docker_containers() -> List[Dict[str, Any]]
async def is_container_exists(docker_container_name: str) -> bool
async def get_containers_data() -> List[Dict[str, Any]]
```

---

## 🔧 How to Call Async Functions

### From Async Context (Discord.py commands, cogs)
```python
# ✅ CORRECT
client = await get_docker_client()
stats = await get_docker_stats(container_name)
containers = await list_docker_containers()
```

### From Sync Context (Web UI, utilities)
```python
# ✅ CORRECT - Use asyncio.run() or asyncio.to_thread()
import asyncio

# Option 1: Run in event loop
containers = asyncio.run(list_docker_containers())

# Option 2: For web frameworks like Flask
async def get_data():
    return await get_docker_stats(container_name)

result = asyncio.run(get_data())
```

### ❌ NEVER DO THIS
```python
# ❌ WRONG - This will cause TypeError
client = get_docker_client()  # Missing await

# ❌ WRONG - Don't convert async functions to sync
def get_docker_client():  # Should be async def
    return docker.from_env()
```

---

## 🧵 Thread Safety Patterns

### Docker Client Access
```python
# ✅ CORRECT - Uses thread-safe patterns
async def get_docker_client():
    global _docker_client, _client_last_used
    
    # Thread-safe access with lock
    with _docker_client_lock:
        # Implementation with double-check pattern
        pass
```

### Global State Management
```python
# ✅ CORRECT - Always use locks for shared state
import threading

_some_cache = {}
_cache_lock = threading.Lock()

def update_cache(key, value):
    with _cache_lock:
        _some_cache[key] = value
```

---

## 🚀 Performance Patterns

### Smart Caching
```python
# ✅ CORRECT - Use caching for expensive operations
_client_ping_cache = 0
_PING_CACHE_TTL = 120

async def get_docker_client():
    # Only ping if cache expired
    if current_time - _client_ping_cache > _PING_CACHE_TTL:
        await asyncio.to_thread(_docker_client.ping)
        _client_ping_cache = current_time
```

### Async Retries
```python
# ✅ CORRECT - Use async retry patterns
from utils.common_helpers import async_retry_with_backoff

@async_retry_with_backoff(max_retries=3)
async def resilient_docker_operation():
    client = await get_docker_client()
    return await asyncio.to_thread(client.containers.list)
```

---

## 🛡️ Error Handling Best Practices

### Specific Exceptions
```python
# ✅ CORRECT - Use specific exception types
try:
    client = await get_docker_client()
except docker.errors.DockerException as e:
    logger.error(f"Docker error: {e}")
except ConnectionError as e:
    logger.error(f"Connection error: {e}")
```

### ❌ Avoid Bare Except
```python
# ❌ WRONG - Too broad
try:
    client = await get_docker_client()
except:  # Don't do this
    pass
```

---

## 📂 File Structure Guidelines

### utils/docker_utils.py
- **Purpose**: Core Docker operations (ALL ASYNC)
- **Key Functions**: `get_docker_client()`, `docker_action()`, `get_docker_stats()`
- **Thread Safety**: Uses `_docker_client_lock`

### cogs/docker_control.py  
- **Purpose**: Discord.py integration (ASYNC context)
- **Pattern**: All command handlers are async
- **Usage**: Direct `await` calls to docker_utils functions

### app/web_ui.py
- **Purpose**: Flask web interface (SYNC context)
- **Pattern**: Use `asyncio.run()` for async calls
- **Important**: Don't block the web thread

---

## 🔍 Testing Async Functions

```python
# ✅ CORRECT - Test async functions properly
import pytest
import asyncio

@pytest.mark.asyncio
async def test_get_docker_stats():
    stats, info = await get_docker_stats("test_container")
    assert stats is not None

# For sync test environments
def test_docker_stats_sync():
    stats, info = asyncio.run(get_docker_stats("test_container"))
    assert stats is not None
```

---

## 🚨 Common Pitfalls to Avoid

### 1. Mixing Async/Sync Patterns
```python
# ❌ WRONG
def some_function():
    client = await get_docker_client()  # await in sync function

# ✅ CORRECT
async def some_function():
    client = await get_docker_client()
```

### 2. Converting Async to Sync
```python
# ❌ WRONG - Breaking thread safety
def get_docker_client():  # Should be async
    return docker.from_env()

# ✅ CORRECT - Keep as async
async def get_docker_client():
    with _docker_client_lock:
        # Thread-safe implementation
```

### 3. Blocking the Event Loop
```python
# ❌ WRONG - Blocks event loop
import time
async def bad_function():
    time.sleep(5)  # Blocks everything

# ✅ CORRECT - Non-blocking
async def good_function():
    await asyncio.sleep(5)  # Non-blocking
```

---

## 🔄 Migration Guidelines

### When Adding New Docker Operations
1. **Always make them async** if they call Docker API
2. **Use thread-safe patterns** for shared state
3. **Add proper error handling** with specific exceptions
4. **Test both async and sync contexts**

### When Modifying Existing Functions
1. **Never convert async to sync** without understanding dependencies
2. **Maintain thread safety** with existing locks
3. **Keep performance optimizations** (caching, timeouts)
4. **Update all callers** if signatures change

---

## 📋 Checklist for New Code

- [ ] Async functions use `async def`
- [ ] All `await` calls are in async contexts  
- [ ] Thread safety with locks for shared state
- [ ] Specific exception handling (no bare `except:`)
- [ ] Performance caching where appropriate
- [ ] Proper testing for both async/sync contexts
- [ ] Documentation updates if API changes

---

## 🎯 Quick Reference

**Always Async:**
- `get_docker_client()`
- `docker_action()` 
- `get_docker_stats()`
- `list_docker_containers()`
- Discord.py command handlers

**Thread-Safe Globals:**
- `_docker_client` + `_docker_client_lock`
- `_containers_cache` + cache locks
- Any shared state

**Performance Patterns:**
- Smart caching with TTL
- `asyncio.to_thread()` for blocking calls
- Async retry decorators

---

*This document should be consulted before making changes to async patterns in the DDC codebase. Following these guidelines prevents runtime errors and maintains optimal performance.* 