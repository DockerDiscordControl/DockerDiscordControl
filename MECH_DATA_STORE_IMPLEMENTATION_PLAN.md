# MECH DATA STORE - COMPLETE IMPLEMENTATION PLAN

## 🎯 OBJECTIVE
Create a centralized **MechDataStore** service that serves as the single source of truth for ALL mech-related data queries across the entire system.

## 📋 CURRENT PROBLEM
Multiple services calculate the same data independently:
- `mech_service.py` - calculates level, power, state
- `mech_evolutions.py` - calculates evolution info, thresholds
- `speed_levels.py` - calculates speed descriptions
- `mech_web_service.py` - duplicates calculations for Web UI
- `status_overview_service.py` - duplicates for Discord

## 🏗️ SOLUTION ARCHITECTURE

### Core Principle: **ONE SERVICE, ALL DATA**
```
┌─────────────────────────────┐
│      MechDataStore          │
│  (Single Source of Truth)   │
├─────────────────────────────┤
│ • get_current_level()       │
│ • get_current_power()       │
│ • get_amount_needed()       │
│ • get_decay_rate()          │
│ • get_speed_info()          │
│ • get_evolution_status()    │
│ • get_comprehensive_data()  │
└─────────────────────────────┘
           ▲
           │ (All services use this)
┌──────────┴──────────────────┐
│ Web UI │ Discord │ Evolution │
│        │         │   APIs    │
└─────────────────────────────┘
```

## 📝 IMPLEMENTATION PHASES

### PHASE 1: CREATE CORE MECHDATASTORE
1. **File**: `services/mech/mech_data_store.py`
2. **Request/Result Patterns**: Define all data query types
3. **Core Methods**: All basic data queries
4. **Caching Layer**: Intelligent caching for performance
5. **Integration**: Use existing Single Point of Truth (donations)

### PHASE 2: MIGRATION OF EXISTING SERVICES
1. **mech_web_service.py** → Use MechDataStore
2. **status_overview_service.py** → Use MechDataStore
3. **mech_evolutions.py** → Simplify to data provider only
4. **speed_levels.py** → Move logic to MechDataStore

### PHASE 3: CLEANUP & OPTIMIZATION
1. Remove duplicated calculation logic
2. Simplify service interfaces
3. Add comprehensive testing
4. Performance optimization
5. Documentation update

---

## 🔧 DETAILED IMPLEMENTATION STEPS

### STEP 1: Create MechDataStore Service
```python
# services/mech/mech_data_store.py
class MechDataStore:
    def get_comprehensive_data(request) -> MechDataResult
    def get_level_info(request) -> LevelDataResult
    def get_power_info(request) -> PowerDataResult
    def get_evolution_info(request) -> EvolutionDataResult
    def get_speed_info(request) -> SpeedDataResult
    def get_decay_info(request) -> DecayDataResult
```

### STEP 2: Define Request/Result Patterns
```python
@dataclass
class MechDataRequest:
    include_decimals: bool = False
    force_refresh: bool = False
    include_projections: bool = False
    language: str = "en"

@dataclass
class MechDataResult:
    success: bool
    # All mech data fields...
```

### STEP 3: Implement Core Data Logic
- Consolidate all calculation logic from existing services
- Use Single Point of Truth (donations) as data source
- Add intelligent caching layer
- Proper error handling

### STEP 4: Update Dependent Services
- Update each service to use MechDataStore
- Remove duplicated logic
- Maintain existing APIs for compatibility

### STEP 5: Testing & Validation
- Test all existing functionality still works
- Verify performance improvements
- Check data consistency across services

---

## 🎯 SUCCESS CRITERIA

### ✅ Functional Requirements
- [ ] All existing APIs continue to work
- [ ] Data consistency across all services
- [ ] Performance equal or better than current
- [ ] Single source of truth maintained

### ✅ Technical Requirements
- [ ] SERVICE FIRST patterns throughout
- [ ] Proper Request/Result dataclasses
- [ ] Intelligent caching implementation
- [ ] Comprehensive error handling
- [ ] Full backward compatibility

### ✅ Architecture Requirements
- [ ] No duplicated calculation logic
- [ ] Clean service boundaries
- [ ] Easy to extend for new features
- [ ] Documentation complete

---

## 📊 MIGRATION STRATEGY

### Phase 1 - Parallel Implementation (SAFE)
1. Create MechDataStore alongside existing services
2. Test extensively with current data
3. Verify all calculations match existing results

### Phase 2 - Gradual Migration (CONTROLLED)
1. Update one service at a time
2. Test after each migration
3. Rollback capability maintained

### Phase 3 - Cleanup (FINAL)
1. Remove old calculation logic
2. Optimize and refactor
3. Update documentation

---

## 🔍 TESTING PLAN

### Unit Tests
- Test each MechDataStore method individually
- Verify cache behavior
- Test error conditions

### Integration Tests
- Test with real donation data
- Verify service-to-service communication
- Test performance under load

### Regression Tests
- Ensure all existing functionality works
- Compare outputs before/after migration
- Test edge cases and error scenarios

---

## 📋 IMPLEMENTATION CHECKLIST

### Core Implementation
- [ ] Create MechDataStore class structure
- [ ] Define all Request/Result dataclasses
- [ ] Implement comprehensive_data() method
- [ ] Implement specialized query methods
- [ ] Add intelligent caching layer
- [ ] Add proper error handling

### Service Migrations
- [ ] Update mech_web_service.py
- [ ] Update status_overview_service.py
- [ ] Update mech_evolutions.py usage
- [ ] Update speed_levels.py usage
- [ ] Test each migration

### Cleanup & Optimization
- [ ] Remove duplicated logic
- [ ] Optimize cache settings
- [ ] Add comprehensive tests
- [ ] Update documentation
- [ ] Performance validation

### Final Validation
- [ ] All tests pass
- [ ] Performance benchmarks met
- [ ] Documentation complete
- [ ] Ready for production

---

## 🚨 CRITICAL SUCCESS FACTORS

1. **NO BREAKING CHANGES** - All existing APIs must continue working
2. **DATA CONSISTENCY** - All services must return identical data
3. **PERFORMANCE** - Must be equal or better than current implementation
4. **MAINTAINABILITY** - Code must be easier to maintain than current
5. **EXTENSIBILITY** - Easy to add new data queries in future

---

## 📈 EXPECTED BENEFITS

### Performance
- Reduced computation through caching
- Fewer duplicate calculations
- Optimized data access patterns

### Maintainability
- Single place for all mech calculations
- Easier to add new features
- Simplified debugging

### Reliability
- Consistent data across all services
- Better error handling
- Reduced complexity

### Developer Experience
- Clear, consistent API
- Easy to understand data flow
- Better documentation

---

*This plan serves as the complete guide for implementing the MechDataStore. Follow each step systematically to ensure successful implementation without data loss or breaking changes.*