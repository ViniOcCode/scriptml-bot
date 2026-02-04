# Ruff Quick Fix Guide - Action Items

## 🚨 CRITICAL - FIX IMMEDIATELY (5 minutes)

### 1. Undefined Name Error (BLOCKING)
**File:** `mercadolivre_upload/application/publish_product.py`  
**Line:** 73  

**Add this import at line 14:**
```python
from mercadolivre_upload.domain.fiscal.service import FiscalSubmissionResult
```

---

## ⚠️ HIGH PRIORITY - FIX BEFORE PRODUCTION (30 minutes)

### 2. Import Shadowing (3 places)
**File:** `mercadolivre_upload/infrastructure/migration.py`  
**Lines:** 288, 295, 309

**Change:**
```python
for field in fields:  # BAD
```

**To:**
```python
for field_item in fields:  # GOOD
```

### 3. Import Not at Top
**File:** `mercadolivre_upload/cli/app.py`  
**Line:** 71

Move the import statement to top of file with other imports.

---

## 🔧 AUTO-FIX (2 minutes)

Run this single command to fix 1,615 issues automatically:

```bash
cd /mnt/c/users/vinicius/desktop/scriptml
ruff check --fix .
```

Then verify nothing broke:
```bash
pytest
```

---

## 📋 MANUAL FIXES - DO AFTER AUTO-FIX (1-2 hours)

### Priority 1: Exception Handling (8 places)

**Files to fix:**
- `mercadolivre_upload/adapters/spreadsheet/dynamic_parser.py`: lines 205, 292
- `mercadolivre_upload/adapters/spreadsheet/excel_parser.py`: lines 207, 221, 378, 395
- `mercadolivre_upload/infrastructure/migration.py`: lines 275, 321

**Change pattern:**
```python
# BEFORE
try:
    something()
except Exception as e:
    raise NewError("msg")

# AFTER
try:
    something()
except Exception as e:
    raise NewError("msg") from e
```

### Priority 2: Default Arguments (8 places)

**Files to fix:**
- `mercadolivre_upload/cli/commands/cache_cmd.py`: lines 19, 29
- `mercadolivre_upload/cli/commands/upload.py`: lines 50, 51, 53, 55
- `mercadolivre_upload/infrastructure/migration.py`: lines 134, 223

**Change pattern:**
```python
# BEFORE
def func(arg=mutable_call()):
    ...

# AFTER
def func(arg=None):
    if arg is None:
        arg = mutable_call()
    ...
```

### Priority 3: Silent Exceptions (3 places)

**Files to fix:**
- `mercadolivre_upload/api/client.py`: line 90
- `mercadolivre_upload/domain/fiscal/service.py`: lines 406, 514

**Change pattern:**
```python
# BEFORE
try:
    risky()
except Exception:
    pass

# AFTER
try:
    risky()
except SpecificException as e:
    logger.warning(f"Expected error: {e}")
```

---

## ✅ COMPLETION CHECKLIST

- [ ] Fixed undefined name in publish_product.py (CRITICAL)
- [ ] Fixed import shadowing in migration.py
- [ ] Fixed import location in cli/app.py
- [ ] Ran `ruff check --fix .`
- [ ] Ran test suite successfully
- [ ] Committed changes
- [ ] Fixed exception handling (8 places)
- [ ] Fixed default arguments (8 places)
- [ ] Fixed silent exceptions (3 places)

---

## 📊 Expected Results

After completing all fixes:
- Issues reduced from 1,750 → ~58 (line length)
- Critical bugs: 1 → 0
- Auto-fixed: 1,615 issues
- Manual fixed: ~20 issues
- Remaining: 58 line-too-long (optional)

Total time: **15 minutes (critical) + 2 hours (complete)**
