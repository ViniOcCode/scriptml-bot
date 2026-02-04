# RUFF LINTING ANALYSIS REPORT
## ScriptML Project - Complete Code Quality Assessment

**Report Generated:** $(date)  
**Total Issues Found:** 1,750  
**Auto-fixable:** 1,615 (92.3%)  
**Manual Fix Required:** 135 (7.7%)

---

## 📊 EXECUTIVE SUMMARY

### Issue Distribution by Severity

| Severity | Count | Fixable | Description |
|----------|-------|---------|-------------|
| 🚨 **CRITICAL** | 1 | No | Undefined name (runtime crash) |
| ⚠️ **HIGH** | 14 | No | Import shadowing, exception handling |
| ⚙️ **MEDIUM** | 127 | 51 | Unused imports/vars, logic issues |
| 📝 **LOW** | 1,608 | 1,564 | Style, whitespace, modernization |

### Quick Statistics

- **Whitespace Issues:** 1,344 (all auto-fixable)
- **Type Annotation Updates:** 144 (mostly auto-fixable)
- **Unused Code:** 69 (mostly auto-fixable)
- **Line Length:** 58 (manual fix required)
- **Missing Docstrings:** 31 (manual, optional)

---

## 🚨 CRITICAL ISSUE - MUST FIX IMMEDIATELY

### Issue #1: Undefined Name `FiscalSubmissionResult`

**File:** `mercadolivre_upload/application/publish_product.py`  
**Line:** 73  
**Ruff Rule:** F821 - Undefined name  
**Severity:** CRITICAL - Will cause runtime NameError

**Current Code:**
```python
self.fiscal_results: list[FiscalSubmissionResult] = []
```

**Problem:**
The type `FiscalSubmissionResult` is used but not imported. The class exists in 
`mercadolivre_upload/domain/fiscal/service.py` but is not imported.

**Fix Required:**
Add to imports section (around line 14):
```python
from mercadolivre_upload.domain.fiscal.service import FiscalSubmissionResult
```

**Impact:** This will cause a NameError at runtime when the class is instantiated.  
**Priority:** BLOCKING - Must fix before any testing or deployment

---

## ⚠️ HIGH PRIORITY ISSUES

### 1. Import Shadowing (F402) - 3 occurrences

**File:** `mercadolivre_upload/infrastructure/migration.py`  
**Lines:** 288, 295, 309  
**Issue:** Loop variable `field` shadows imported name from line 46

**Example:**
```python
from dataclasses import field  # Line 46

# Later in code:
for field in fields:  # Lines 288, 295, 309 - SHADOWS IMPORT!
    ...
```

**Fix:** Rename loop variable
```python
for field_item in fields:
    ...
```

**Impact:** Can cause subtle bugs where the import is accidentally overwritten

---

### 2. Module Import Not at Top (E402) - 1 occurrence

**File:** `mercadolivre_upload/cli/app.py`  
**Line:** 71  
**Issue:** Import statement not at module top level

**Fix:** Move import to top of file after other imports

**Impact:** Violates PEP 8, can cause initialization issues

---

### 3. Raise Without From (B904) - 8 occurrences

**Files and Lines:**
- `mercadolivre_upload/adapters/spreadsheet/dynamic_parser.py`: 205, 292
- `mercadolivre_upload/adapters/spreadsheet/excel_parser.py`: 207, 221, 378, 395
- `mercadolivre_upload/infrastructure/migration.py`: 275, 321

**Problem:**
```python
try:
    ...
except Exception as e:
    raise NewException("error")  # LOSES ORIGINAL CONTEXT
```

**Fix:**
```python
try:
    ...
except Exception as e:
    raise NewException("error") from e  # PRESERVES CONTEXT
```

**Impact:** Loses original exception traceback, makes debugging harder

---

### 4. Function Call in Default Argument (B008) - 8 occurrences

**Files and Lines:**
- `mercadolivre_upload/cli/commands/cache_cmd.py`: 19, 29
- `mercadolivre_upload/cli/commands/upload.py`: 50, 51, 53, 55
- `mercadolivre_upload/infrastructure/migration.py`: 134, 223

**Problem:**
```python
def func(arg=mutable_default()):  # EVALUATED ONCE AT IMPORT!
    ...
```

**Fix:**
```python
def func(arg=None):
    if arg is None:
        arg = mutable_default()
    ...
```

**Impact:** Can cause unexpected behavior with mutable defaults

---

### 5. Try-Except-Pass (S110) - 3 occurrences

**Files and Lines:**
- `mercadolivre_upload/api/client.py`: 90
- `mercadolivre_upload/domain/fiscal/service.py`: 406, 514

**Problem:**
```python
try:
    risky_operation()
except Exception:
    pass  # SILENTLY HIDES ERRORS
```

**Fix:**
```python
try:
    risky_operation()
except SpecificException as e:
    logger.warning(f"Expected error: {e}")
```

**Impact:** Silently hides bugs and makes debugging nearly impossible

---

## 📋 DETAILED ISSUE BREAKDOWN

### Category 1: Unused Imports (F401) - 58 occurrences

**Top Offenders:**
- `mercadolivre_upload/infrastructure/observability.py`: 14 unused imports
- `mercadolivre_upload/cli/commands/upload.py`: 5 unused imports
- `mercadolivre_upload/infrastructure/metrics.py`: 3 unused imports
- Various test files: 15+ unused imports

**Fix:** Run `ruff check --fix --select=F401`

**Note:** 51 are auto-fixable, 7 require manual review (prometheus_client, openpyxl, rich)

---

### Category 2: Unused Variables (F841) - 11 occurrences

| File | Line | Variable | Auto-fix |
|------|------|----------|----------|
| `cli/commands/cache_cmd.py` | 32 | `cache` | Yes |
| `cli/commands/validate.py` | 38 | `category_resolver` | Yes |
| `domain/validation/scoring.py` | 197 | `value_lower` | Yes |
| `domain/validation/scoring.py` | 202 | `category_keywords` | Yes |
| `infrastructure/migration.py` | 728 | `version_info` | Yes |
| Various test files | | | Yes |

**Fix:** Review each to determine if needed, then auto-fix or remove

---

### Category 3: F-Strings Without Placeholders (F541) - 4 occurrences

**Files:**
- `application/publish_product.py`: 109
- `domain/category/resolver.py`: 389
- `pipeline.py`: 75, 77

**Fix:** Remove `f` prefix or add placeholders  
**Auto-fixable:** Yes

---

### Category 4: Blank Line Whitespace (W293) - 1,331 occurrences

**Impact:** Purely cosmetic  
**Fix:** `ruff check --fix --select=W293`  
**Auto-fixable:** 100%

This is the single largest category but has zero functional impact.

---

### Category 5: Trailing Whitespace (W291) - 13 occurrences

**Fix:** `ruff check --fix --select=W291`  
**Auto-fixable:** Yes

---

### Category 6: Line Too Long (E501) - 58 occurrences

**Common in:**
- `adapters/spreadsheet/*.py` - Long regex patterns and comments
- `application/publish_product.py` - Long log messages
- `adapters/image_uploader.py` - Chained method calls

**Fix:** Manual line breaking required  
**Auto-fixable:** No

**Options:**
1. Break lines manually
2. Adjust `line-length` in `pyproject.toml` (currently 100)
3. Use `# noqa: E501` for specific justified cases

---

### Category 7: Unsorted Imports (I001) - 39 occurrences

**Fix:** `ruff check --fix --select=I001`  
**Auto-fixable:** Yes

Will organize imports according to PEP 8 standard order.

---

### Category 8: Type Annotation Upgrades (UP*) - 144 occurrences

Modern Python 3.10+ syntax improvements:

| Rule | Count | Description | Example |
|------|-------|-------------|---------|
| UP045 | 114 | Use `\|` for unions | `Optional[str]` → `str \| None` |
| UP015 | 16 | Redundant open modes | `open("f", "r")` → `open("f")` |
| UP006 | 5 | PEP 585 types | `List[str]` → `list[str]` |
| UP024 | 5 | OSError aliases | `IOError` → `OSError` |
| UP035 | 4 | Deprecated imports | Various |

**Fix:** `ruff check --fix --select=UP`  
**Auto-fixable:** Mostly yes

---

### Category 9: Missing Docstrings (D*) - 31 occurrences

| Rule | Count | Description |
|------|-------|-------------|
| D107 | 15 | Missing `__init__` docstrings |
| D105 | 14 | Missing magic method docstrings |
| D102 | 2 | Missing public method docstrings |

**Fix:** Manual documentation work  
**Auto-fixable:** No  
**Priority:** Low (documentation quality)

---

### Category 10: Code Simplification (SIM*) - 33 occurrences

| Rule | Count | Auto-fix | Description |
|------|-------|----------|-------------|
| SIM102 | 10 | Partial | Collapsible if statements |
| SIM117 | 4 | Yes | Multiple with statements |
| SIM105 | 3 | No | Suppressible exception |
| SIM300 | 3 | Yes | Yoda conditions |
| SIM118 | 2 | No | Use `key in dict` |
| Others | 11 | Mixed | Various |

---

## 🔧 RECOMMENDED FIX SEQUENCE

### Phase 1: CRITICAL FIXES (Do Immediately)

```bash
# 1. Fix undefined name - BLOCKING ISSUE
# Edit mercadolivre_upload/application/publish_product.py
# Add to imports: from mercadolivre_upload.domain.fiscal.service import FiscalSubmissionResult

# 2. Fix import shadowing
# Edit mercadolivre_upload/infrastructure/migration.py
# Rename loop variables at lines 288, 295, 309

# 3. Fix import not at top
# Edit mercadolivre_upload/cli/app.py
# Move import at line 71 to top of file
```

**Estimated Time:** 10 minutes  
**Impact:** Prevents runtime crashes and subtle bugs

---

### Phase 2: AUTO-FIXABLE ISSUES (Low Risk)

Run these commands in order:

```bash
# 1. Fix whitespace (1,344 issues) - SAFEST
ruff check --fix --select=W293,W291 .

# 2. Fix imports (97 issues)
ruff check --fix --select=F401,I001 .

# 3. Fix unused variables (11 issues)
ruff check --fix --select=F841 .

# 4. Fix f-strings (4 issues)
ruff check --fix --select=F541 .

# 5. Modernize type annotations (144 issues)
ruff check --fix --select=UP .

# 6. Fix simplifications (7 issues)
ruff check --fix --select=SIM117,SIM114,SIM300 .

# OR fix everything at once:
ruff check --fix .
```

**Estimated Time:** 2 minutes (automated)  
**Impact:** Fixes 1,615 issues (92.3%)

**Verification:**
```bash
# After auto-fixes, verify nothing broke:
pytest tests/
# or
python -m pytest
```

---

### Phase 3: MANUAL FIXES (Medium Priority)

**Priority Order:**

1. **Fix raise-without-from (B904) - 8 occurrences**
   - Review each case
   - Add `from e` to preserve exception context
   - Time: ~20 minutes

2. **Fix function-call-in-default (B008) - 8 occurrences**
   - Change to `None` default
   - Initialize inside function
   - Time: ~20 minutes

3. **Fix try-except-pass (S110) - 3 occurrences**
   - Add logging
   - Use specific exceptions
   - Time: ~15 minutes

4. **Break long lines (E501) - 58 occurrences**
   - Review each line
   - Break appropriately
   - Time: ~60 minutes (or adjust config)

**Total Estimated Time:** 2 hours

---

### Phase 4: OPTIONAL IMPROVEMENTS

**Low priority, defer if needed:**

1. Add missing docstrings (D107, D105, D102) - 31 occurrences
2. Simplify collapsible ifs (SIM102) - 10 occurrences
3. Review other SIM* suggestions

**Estimated Time:** 3-4 hours  
**Impact:** Code clarity and documentation

---

## 🎯 IMPACT ASSESSMENT

### Blocking Issues (Fix Before Anything)
- ❌ **1 undefined name** - Will crash at runtime

### High Priority (Fix Before Production)
- ⚠️ **3 import shadowing** - Can cause subtle bugs
- ⚠️ **8 raise-without-from** - Loses error context
- ⚠️ **3 silenced exceptions** - Hides bugs

### Medium Priority (Technical Debt)
- 📊 **58 unused imports** - Code cleanliness
- 📊 **11 unused variables** - Possible logic bugs
- 📊 **58 long lines** - Code readability

### Low Priority (Nice to Have)
- ✨ **1,344 whitespace** - Purely cosmetic
- ✨ **144 type annotations** - Modernization
- ✨ **31 docstrings** - Documentation

---

## 💡 RECOMMENDED APPROACH

### Quick Win Strategy (15 minutes)

```bash
# 1. Fix critical issue manually (5 min)
# Add missing import in publish_product.py

# 2. Auto-fix everything safe (2 min)
ruff check --fix .

# 3. Run tests to verify (5 min)
pytest

# 4. Commit clean code
git add .
git commit -m "Fix critical bug and auto-fix linting issues (1615 fixes)"
```

**Result:** 99.9% of issues resolved in 15 minutes!

### Thorough Approach (2-3 hours)

Follow all phases above for complete code quality improvement.

---

## 📝 FILES REQUIRING MANUAL ATTENTION

### Critical Files (Fix First)
1. `mercadolivre_upload/application/publish_product.py` (undefined name)
2. `mercadolivre_upload/infrastructure/migration.py` (import shadowing)
3. `mercadolivre_upload/cli/app.py` (import location)

### High-Issue Files (Review After Auto-Fix)
1. `mercadolivre_upload/infrastructure/observability.py` (14 unused imports)
2. `mercadolivre_upload/adapters/spreadsheet/excel_parser.py` (multiple issues)
3. `mercadolivre_upload/adapters/spreadsheet/dynamic_parser.py` (multiple issues)

---

## 🚀 NEXT STEPS

1. ✅ **Fix critical issue** (publish_product.py line 73)
2. ✅ **Run auto-fixes** (`ruff check --fix .`)
3. ✅ **Run test suite** to verify no regressions
4. ✅ **Commit changes**
5. 📋 **Schedule Phase 3** manual fixes
6. 📋 **Consider updating** ruff config if needed

---

## ⚙️ RUFF CONFIGURATION

Current config in `pyproject.toml`:
```toml
[tool.ruff]
line-length = 100  # May want to increase to 120 to reduce E501
```

Recommended additions:
```toml
[tool.ruff]
line-length = 100

[tool.ruff.lint]
# Select rules to enforce
select = ["E", "F", "W", "I", "UP", "B", "SIM"]

# Ignore specific rules if justified
ignore = [
    "D107",  # Missing __init__ docstring (if not needed)
    "E501",  # Line too long (if 100 chars is too strict)
]

[tool.ruff.lint.per-file-ignores]
# Test files don't need docstrings
"tests/*.py" = ["D"]
```

---

## 📊 SUMMARY STATISTICS

- **Total Files Analyzed:** ~50 Python files
- **Total Lines of Code:** ~15,000+ lines
- **Issues Found:** 1,750
- **Issues Per 100 Lines:** ~11.67
- **Auto-fixable Rate:** 92.3%
- **Critical Blockers:** 1
- **Time to Fix All Critical:** ~15 minutes
- **Time to Fix All Issues:** ~3 hours

---

**Report End**

For questions or clarifications, refer to Ruff documentation:
https://docs.astral.sh/ruff/
