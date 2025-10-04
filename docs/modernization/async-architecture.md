# Async/Await Architecture Design

## Overview

This document details the migration from synchronous, thread-based architecture to asynchronous, event-driven architecture using Python's asyncio.

**Related Issue:** #2  
**Status:** Design Phase  
**Dependencies:** None (Foundation)

---

## Current Architecture Problems

### Threading Model Issues

1. **Thread Overhead**
   - Each controller runs in a separate thread
   - High memory consumption (~8MB per thread)
   - Context switching overhead
   - Race conditions require extensive locking

2. **Blocking I/O**
   - Sensor readings block threads
   - Database queries block threads
   - API calls block threads
   - Limited concurrent operations

### Code Example - Current Synchronous Pattern

```python
# mycodo/controllers/controller_input.py (Current)
class InputController:
    def loop(self):
        while self.running:
            # Blocking sensor read
            measurement = self.sensor.read()
            
            # Blocking database write
            self.write_to_database(measurement)
            
            # Blocking sleep
            time.sleep(self.period)
```

---

## Target Architecture

### Asyncio Event Loop Model

Benefits:
- Single event loop per process
- Cooperative multitasking
- Efficient I/O multiplexing
- Lower memory footprint

### Code Example - Target Async Pattern

```python
# mycodo/controllers/controller_input.py (Target)
class InputController:
    async def loop(self):
        while self.running:
            # Non-blocking sensor read
            measurement = await self.sensor.read_async()
            
            # Non-blocking database write
            await self.write_to_database_async(measurement)
            
            # Non-blocking sleep
            await asyncio.sleep(self.period)
```

---

## Implementation Strategy

See full implementation details in MODERNIZATION_ROADMAP.md

---

**Status:** Ready for Implementation  
**Next Steps:** Implement Phase 1 - Core Event Loop
