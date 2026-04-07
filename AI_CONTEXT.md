# Mercado Livre Bulk Upload CLI - Comprehensive AI Context

**Project Name:** mercado-livre-bulk-upload (`ml-upload`)  
**Primary Purpose:** Automated CLI tool for bulk publishing Mercado Livre product listings from Excel spreadsheets with category/attribute resolution, image handling, and encrypted token storage.  
**Language:** Python 3.13+  
**Package:** `mercadolivre_upload`  
**CLI Entrypoint:** `ml-upload` (→ `mercadolivre_upload.main:main`)

---

## 1. High-Level Problem Domain

### What Problem Does This Solve?

**Mercado Livre** is a large Latin American e-commerce platform. This tool automates the repetitive process of:

1. **Bulk reading** product data from Excel spreadsheets (`.xlsx`, `.xls`)
2. **Normalizing** Portuguese/English column headers and data
3. **Resolving categories** (matching user input to Mercado Livre's category taxonomy)
4. **Validating attributes** (price, dimensions, materials, etc. required by the category)
5. **Uploading images** and optional video clips to Mercado Livre's media servers
6. **Publishing products** to the Mercado Livre API
7. **Reporting** results (validation summaries, upload failures) in machine-readable JSON/Excel

### Core Workflows

| Workflow | Command | Purpose | Output |
|----------|---------|---------|--------|
| **Validate** | `ml-upload validate` | Check spreadsheet format, category resolution, attributes before publishing | `validation-summary-<ts>.json` + console report |
| **Publish** | `ml-upload upload` | Upload images, then publish items to Mercado Livre via API | `upload-summary-<ts>.json` + optional failed-items export |
| **Auth** | `ml-upload auth` | Set/refresh Mercado Livre OAuth tokens, inspect auth status | Token storage in `tokens.json.enc` |
| **Cache** | `ml-upload cache {clear,status}` | Manage cached category metadata and predictions | Cache stats or cleared cache |
| **Health** | `ml-upload doctor` | Environment diagnostic checks | Diagnostic output |

---

## 2. Architecture Overview

### Structural Layers

```
mercadolivre_upload/
├── cli/                          # Command-line interface layer
│   ├── app.py                    # Typer app, command registration, theme setup
│   ├── commands/
│   │   ├── upload.py             # Composition root: wires adapters & use-cases
│   │   ├── validate.py
│   │   └── auth.py
│   └── __init__.py               # Export PublishProductService for backward compat
│
├── application/                  # Business logic and use-case orchestration
│   ├── publish_product.py        # PublishProductUseCase (core orchestration)
│   ├── ports.py                  # Protocol/interface definitions
│   ├── builders/
│   │   └── product_builder.py    # Converts row dicts → Product domain model
│   ├── attribute_builder.py      # Combines attributes from multiple sources
│   ├── publish/
│   │   └── internals/            # Stateless publish pipeline steps
│   │       ├── category.py       # Category resolution
│   │       ├── payload.py        # Payload construction
│   │       ├── shipping.py       # Shipping policy resolution
│   │       ├── flow.py           # Orchestrates publish steps
│   │       ├── execution.py      # Execution and state tracking
│   │       └── ...               # Other internal steps
│   └── ...
│
├── domain/                       # Core domain models and rules
│   ├── product.py                # Product aggregate root
│   ├── category.py               # Category domain model
│   ├── attribute.py              # Attribute model
│   ├── fiscal/                   # Fiscal/tax domain
│   └── ...
│
├── adapters/                     # External interface implementations
│   ├── image_uploader.py         # Uploads images to Mercado Livre
│   ├── clip_uploader.py          # Uploads video clips
│   ├── auth_manager.py           # Token lifecycle management
│   └── ...
│
├── infrastructure/               # Technical/cross-cutting concerns
│   ├── http.py                   # Resilient HTTP client (retry, backoff, rate limit)
│   ├── config.py                 # Configuration loading (YAML + env)
│   ├── logging.py                # Logging setup
│   ├── cache/
│   │   ├── attribute_cache.py    # File-based category metadata cache
│   │   └── prediction_cache.py   # Domain discovery results cache
│   └── ...
│
├── api/
│   └── client.py                 # Mercado Livre API client (REST HTTP wrapper)
│
├── shared/
│   └── utils/
│       ├── text_utils.py         # Portuguese text normalization
│       └── config_loader.py
│
└── main.py                       # Entry point → calls CLI app

config/                           # Runtime configuration (YAML)
├── standard_fields.yaml          # Field mappings and explicit category mappings
├── shipping.yaml                 # Shipping policy toggles
├── attribute_rules.yaml          # Attribute classification & sanitization rules
└── fiscal_config.yaml

tests/                            # Test suite
├── test_cli.py                   # CLI command tests
├── test_spreadsheet_parser.py    # Spreadsheet parsing tests
├── test_publish_product.py       # Use-case tests
└── ... (50+ test files)

cache/                            # Runtime caches and reports
├── categories/
│   ├── .attribute_cache.json     # Cached category attributes (TTL)
│   └── prediction/               # Domain discovery predictions (SHA-256 filenames)
└── reports/                      # Generated validation/upload reports

anuncios/                         # Example fixtures and sample data
├── 2.xlsx                        # Example spreadsheet (used in docs)
└── <SKU>/                        # Example image folders

pyproject.toml                    # Project metadata, deps, toolchain config
```

### Core Data Flow

```
[Excel File] → [SpreadsheetParser] → [Normalized Row Dicts]
                                           ↓
[PublishProductUseCase]
  ├─→ [CategoryResolver]
  │    ├─→ Match user category input to ML taxonomy
  │    ├─→ Fall back to title-based prediction if no match
  │    └─→ Resolve to leaf category ID
  ├─→ [Product Builder]
  │    ├─→ Convert row dict → Product domain model
  │    └─→ Validate required fields per category
  ├─→ [Attribute Builder]
  │    ├─→ Resolve attributes from cache + rules
  │    └─→ Validate and sanitize per category spec
  ├─→ [Shipping Resolver]
  │    └─→ Apply shipping policies
  ├─→ [Image/Clip Uploader]
  │    ├─→ Upload images to ML media server
  │    └─→ Upload optional video clips
  ├─→ [Payload Constructor]
  │    └─→ Build JSON payload for ML API
  └─→ [Item Publisher]
       ├─→ Call ML API to publish item
       └─→ Track success/failure + generate report

[Report Writer] → [JSON Summary] + [Optional Failed Items Excel]
```

---

## 3. Key Components & Their Responsibilities

### A. CLI Layer (`cli/`)

**Files:** `app.py`, `commands/upload.py`, `commands/validate.py`, `commands/auth.py`

**Responsibility:**
- Parse command-line arguments via Typer
- Set up logging, configure theme
- Wire adapters and use-cases (dependency injection in `commands/upload.py`)
- Delegate to application layer

**Key Functions:**
- `upload()` / `validate()` – Main entry points; call use-case
- Composition root in `commands/upload.py` – Creates `PublishProductUseCase` + adapters

---

### B. Application Layer (`application/`)

#### B.1 PublishProductUseCase (`publish_product.py`)

**Responsibility:** Orchestrate the entire publish/validate pipeline

**Key Methods:**
- `execute(spreadsheet_path, category, images_dir, ...)` – Main entry point
- Internal flow via `publish/internals/flow.py`

**Inputs:**
- Spreadsheet path
- Category name (user input)
- Images directory
- Batch size, report directory
- Optional flags (publish_inactive, etc.)

**Outputs:**
- List of `PublishResult` (success/failure per item)
- Generated reports (JSON summary + optional failed-items Excel)

#### B.2 Ports (`ports.py`)

**Responsibility:** Define interfaces (Protocols) that adapters must implement

**Key Ports:**
- `AuthManagerPort` – Token lifecycle
- `MLApiClientPort` – API calls
- `ImageUploaderPort` – Image upload
- `ItemPublisherPort` – Item publication
- `AttributeCachePort` – Category metadata caching
- `PredictionCachePort` – Category prediction caching

**Pattern:** Use-cases depend on Protocols; adapters provide implementations. This enables:
- Testability (mock adapters)
- Loose coupling
- Dependency injection

#### B.3 Product Builder (`builders/product_builder.py`)

**Responsibility:** Convert spreadsheet row (dict) → `Product` domain model

**Validates:**
- Required fields for category
- Data types and ranges
- SKU/price/title/description presence

**Output:** `Product` domain object (aggregate root)

#### B.4 Attribute Builder (`attribute_builder.py`)

**Responsibility:** Resolve and validate product attributes

**Sources:**
1. Category metadata (from cache)
2. Attribute rules (from YAML config)
3. Explicit mappings (from standard_fields.yaml)

**Output:** List of `Attribute` objects (id, value, source)

#### B.5 Publish Internals (`publish/internals/`)

Stateless pipeline steps:

- **`category.py`** – Category resolution (name match → predictor → fallback)
- **`payload.py`** – Construct ML API payload (JSON)
- **`shipping.py`** – Apply shipping policies
- **`flow.py`** – Orchestrate publish steps in sequence
- **`execution.py`** – Execute batch publishing (retry logic, rate limiting)
- **`state.py`** – Track publish state (rollout flags, stats, problematic items)
- **`preflight.py` / `validation.py`** – Pre-publish validation
- **`api_validation_repair.py`** – Handle API validation errors and suggest fixes

---

### C. Domain Layer (`domain/`)

**Models & Rules:** Core business logic independent of UI/API

**Key Models:**
- `Product` – Aggregate root (id, title, price, category, attributes, images)
- `Category` – ML category taxonomy representation
- `Attribute` – Product attribute (id, value, validation rules)
- `Fiscal` – Tax/fiscal policy rules

**Responsibilities:**
- Validate domain invariants
- Enforce business rules
- No external dependencies (no HTTP, no file I/O)

---

### D. Adapter Layer (`adapters/`)

**Responsibility:** Implement ports, bridge to external systems

**Key Adapters:**
- `AuthManager` / `TokenManager` – Manages OAuth tokens (secure encrypted storage)
- `ImageUploader` – Uploads images to Mercado Livre media servers
- `ClipUploader` – Uploads video clips
- `MLApiClient` (in `api/client.py`) – HTTP client for Mercado Livre API calls

**Pattern:**
- Adapters are not directly imported by use-cases
- Use-cases depend on Protocols (interfaces)
- Adapters are injected at composition root

---

### E. Infrastructure Layer (`infrastructure/`)

**Responsibility:** Technical concerns and cross-cutting utilities

**Key Modules:**
- **`http.py`** – Resilient HTTP client:
  - Exponential backoff + jitter (retry on 5xx, 429)
  - Token-bucket rate limiter
  - `Retry-After` header support
  - Request tracing
  
- **`config.py`** – Load YAML configs + environment overrides

- **`cache/`**:
  - `AttributeCache` – File-based cache (`cache/categories/.attribute_cache.json`)
  - `PredictionCache` – Stores category predictions (SHA-256 filenames)

- **`logging.py`** – Structured logging setup

---

### F. API Client (`api/client.py`)

**Responsibility:** Wrap Mercado Livre REST API

**Endpoints Used:**
- `GET /sites/{SITE_ID}/categories/{CATEGORY_ID}` – Category metadata
- `POST /mclics/acp/publish` or similar – Publish item
- `POST /mclics/media/pictures` – Upload images
- And others for attribute resolution, predictions, etc.

**Uses:** Resilient HTTP client from `infrastructure/http.py`

---

## 4. Configuration System

### YAML Configuration Files

Located in `config/`:

#### `standard_fields.yaml`
- **Purpose:** Column mapping and explicit category mappings
- **Key Sections:**
  ```yaml
  mappings:
    Portuguese headers → English field names
  explicit_mappings:
    Category name → ML category ID (fallback when predictor fails)
  global_explicit_mappings:
    Armação → (Armação category ID)
    Vidro → (Vidro category ID)
  ```

#### `shipping.yaml`
- **Purpose:** Shipping policy toggles
- **Key Toggles:**
  - `require_mandatory_shipping` – Must items have shipping?
  - `default_shipping_type` – Default carrier type
  - `free_shipping_threshold` – Price threshold for free shipping

#### `attribute_rules.yaml`
- **Purpose:** Attribute classification & sanitization
- **Sections:**
  - Rules for what attributes are required per category
  - Sanitization rules (trim whitespace, case conversion, etc.)

#### `fiscal_config.yaml`
- **Purpose:** Tax and fiscal policies

### Environment Variables

**Token & Auth:**
- `MERCADO_LIVRE_CLIENT_ID` – OAuth client ID
- `MERCADO_LIVRE_CLIENT_SECRET` – OAuth client secret
- `MERCADO_LIVRE_REDIRECT_URI` – Callback URL (optional)
- `MERCADO_LIVRE_TOKEN_PATH` – Custom token file location
- `ENCRYPTION_KEY` – Master encryption key for tokens (from keyring or env)

**Storage Mode:**
- `MERCADO_LIVRE_USE_SECURE_STORAGE` – Default enabled; set `0` to disable
- `MERCADO_LIVRE_AUTO_MIGRATE_TOKENS` – Auto-migrate plaintext tokens to encrypted

**Runtime:**
- `PYTHONPATH`, `DEBUG`, etc. (standard Python vars)

---

## 5. Token & Security Model

### Secure Token Storage (Default)

**Location:** `tokens.json.enc` (encrypted file, next to `tokens.json` if migrating)

**Contents:**
```json
{
  "access_token": "...",
  "refresh_token": "...",
  "expires_at": "2026-03-20T14:30:00Z"
}
```

**Encryption:**
- Uses `cryptography.Fernet` (symmetric encryption)
- Key from keyring (system credential store) or `ENCRYPTION_KEY` env var

**Lifecycle:**
1. `get_access_token()` – Reads persisted `access_token`
2. If expired + `auto_refresh=True` → Use `refresh_token` to get new credentials
3. Persist updated token + expiry

**Migration (Automatic):**
- If plaintext `tokens.json` exists → Encrypt to `tokens.json.enc` + backup original
- Requires secure mode enabled

### External Secret Managers (1Password, Vault, etc.)

**No code changes required.** Inject at runtime:

```bash
op run --env-file=.env.1password -- \
  uv run ml-upload validate anuncios/2.xlsx -i anuncios/ -c "quadros decorativos"
```

---

## 6. Publishing Pipeline (Detailed)

### Step 1: Spreadsheet Parsing

**Module:** Handled by `SpreadsheetParser` (imported in `upload.py`)

**Input:** `.xlsx` or `.xls` file

**Process:**
1. Read Excel using `openpyxl` or `xlrd`
2. Normalize headers using `PortugueseTextNormalizer`
3. Validate required columns exist
4. Return list of row dicts

**Output:** `List[Dict[str, Any]]`

---

### Step 2: Category Resolution

**Module:** `application/publish/internals/category.py`

**Process:**
1. **Name Match:** Check if user-provided category matches ML category name exactly (or after normalization)
2. **Predictor Fallback:** If no match, use ML's title-based category predictor
   - Send product title → ML API → Get predicted category
   - Hardcodes site code `MLB` (Mercado Livre Brasil)
3. **Explicit Mapping Fallback:** If predictor fails, check `config/standard_fields.yaml` explicit mappings
4. **Resolve to Leaf:** If multiple categories match, navigate to the leaf category

**Output:** Category ID (str) + metadata

---

### Step 3: Product Building

**Module:** `application/builders/product_builder.py`

**Input:** Row dict + category metadata

**Validates:**
- Required fields (title, price, SKU, etc.) present
- Data types correct (price is number, etc.)
- Images exist in specified directory

**Output:** `Product` domain model

---

### Step 4: Attribute Resolution

**Module:** `application/attribute_builder.py`

**Sources:**
1. Category metadata (from cache)
2. Attribute rules (YAML)
3. Explicit mappings (YAML)

**Process:**
1. Fetch category attributes from cache (or API if cache miss)
2. For each attribute:
   - Get from row dict or use default
   - Validate against category spec
   - Sanitize per rules
   - Reject if unsupported by category (skip mapped IDs not in category)

**Output:** `List[Attribute]`

---

### Step 5: Image Upload

**Module:** `adapters/image_uploader.py`

**Process:**
1. Search for images:
   - `<images_dir>/<SKU>/*.jpg` (preferred)
   - `<images_dir>/*.jpg` (fallback if SKU folder missing)
2. Upload each image to Mercado Livre media server
3. Get back media URL + media ID
4. Annotate product with image URLs

**Output:** `Product` with image URLs populated

---

### Step 6: Payload Construction

**Module:** `application/publish/internals/payload.py`

**Inputs:** Product + attributes + metadata

**Constructs:** JSON payload for Mercado Livre API

**Includes:**
- Title, description, category ID
- Price, quantity, condition
- Attributes (customized per category)
- Images, shipping policies, listing type
- Variations (if applicable)

**Output:** JSON dict (serializable)

---

### Step 7: API Publication

**Module:** `application/publish/internals/execution.py` (via `MLApiClient`)

**Process:**
1. Call ML API endpoint to publish item
2. On API validation errors → `api_validation_repair.py` suggests fixes
3. Retry on transient errors (5xx, 429) with exponential backoff
4. On success → Get item ID (junk ID for new items)
5. On failure → Log error, track for retry

**Output:** `PublishResult` (success/failure + item ID or error msg)

---

### Step 8: Report Generation

**Module:** `cli/commands/upload.py` (after use-case completes)

**Outputs:**
- **`upload-summary-<timestamp>.json`** – Stats, success/failure per item, runtime metadata
- **`failed-items-<timestamp>.xlsx`** – Export of failed items (only if failures exist)

**Location:** `cache/reports/` (default, overridable)

---

## 7. Testing Strategy

### Test Suite Structure

**Location:** `tests/`

**Coverage:** ~60% (enforced by pytest config)

**Key Test Files:**
- `test_cli.py` – CLI command integration tests
- `test_publish_product.py` – Use-case orchestration tests
- `test_spreadsheet_parser*.py` – Parsing & normalization tests
- `test_image_uploader.py` – Image upload logic
- `test_attribute_builder.py` – Attribute resolution
- `test_config_consolidation.py` – YAML config merging
- Many more domain & adapter tests

### Test Patterns

**Unit Tests:**
- Mock external adapters (HTTP, file I/O)
- Test domain logic in isolation
- Use `unittest.mock.patch`

**Integration Tests:**
- Use `CliRunner.isolated_filesystem()` (Typer testing utility)
- Create temporary files, run CLI commands
- Assert output, report generation

**Fixtures:**
- Example spreadsheets in `anuncios/` (e.g., `2.xlsx`)
- Shared builders in `tests/cli_report_builders.py`

### Running Tests

```bash
# Full suite (enforces 60% coverage)
uv run pytest -q

# Single file (skip coverage gate)
uv run pytest tests/test_cli.py -q --override-ini addopts=''

# Single test node
uv run pytest tests/test_cli.py::TestUploadCommand::test_upload_success -q --override-ini addopts=''
```

---

## 8. Quality Assurance & Tooling

### Code Quality Tools

| Tool | Command | Purpose |
|------|---------|---------|
| **Ruff** | `uv run ruff check .` | Fast Python linter (PEP 8, security) |
| **Black** | `uv run black --check --diff .` | Code formatter (uncompromising style) |
| **MyPy** | `uv run mypy mercadolivre_upload/` | Static type checker (strict mode) |
| **Pytest** | `uv run pytest -q` | Unit/integration tests + coverage |
| **Bandit** | `uv run bandit -q -c pyproject.toml -r mercadolivre_upload` | Security vulnerability scanner |
| **Pre-commit** | `uv run pre-commit run --all-files` | Git hooks (linting before commit) |

### Quality Gate (Before Commits)

```bash
uv pip install -e "[dev]"
uv run ruff check .
uv run black --check --diff .
uv run mypy mercadolivre_upload/
uv run pytest -q
uv run bandit -q -c pyproject.toml -r mercadolivre_upload
```

All must pass. Fix issues before committing.

---

## 9. Common Use Cases & Code Paths

### Use Case 1: User Runs `validate`

```
User: uv run ml-upload validate anuncios/2.xlsx -i anuncios/ -c "quadros decorativos"
  ↓
cli/commands/upload.py::validate_cmd()
  ↓
PublishProductUseCase(mode='validate').execute(...)
  ↓
1. Parse spreadsheet → List[Dict]
2. For each row:
   a. Resolve category ("quadros decorativos" → category ID)
   b. Build Product model
   c. Resolve attributes
   d. Validate against ML specs
3. Write validation-summary-<ts>.json
  ↓
Output: Report + console summary
```

### Use Case 2: User Runs `upload`

```
User: uv run ml-upload upload anuncios/2.xlsx -i anuncios/ -c "quadros decorativos" --batch-size 5
  ↓
cli/commands/upload.py::upload_cmd()
  ↓
PublishProductUseCase(mode='publish').execute(...)
  ↓
1. Parse spreadsheet → List[Dict]
2. For each row (batched by --batch-size):
   a. Resolve category, build product, resolve attributes
   b. Upload images → Get media URLs
   c. Build payload
   d. Publish via ML API
   e. Handle errors / retry
3. Write upload-summary-<ts>.json + optional failed-items-<ts>.xlsx
  ↓
Output: Report + console summary
```

### Use Case 3: Category Resolution Failure

```
User category: "unexpected name"
  ↓
1. Name match → No match
2. Predictor (title-based) → No prediction
3. Explicit mappings → No match
  ↓
Fail: Mark item as problematic, log error, skip publish
```

---

## 10. Extension Points & Customization

### A. Adding a New Adapter

**Steps:**
1. Define Protocol in `ports.py` (e.g., `CustomUploaderPort`)
2. Create adapter class implementing Protocol (e.g., `class CustomUploader`)
3. Inject in composition root (`commands/upload.py`)
4. Use-case receives via constructor parameter

**Example:**
```python
# ports.py
class CustomUploaderPort(Protocol):
    def upload(self, data: bytes) -> str: ...

# adapters/custom_uploader.py
class CustomUploader:
    def upload(self, data: bytes) -> str:
        # Implementation

# commands/upload.py
uploader = CustomUploader(config)
use_case = PublishProductUseCase(..., custom_uploader=uploader)
```

### B. Adding a New YAML Configuration

1. Create file in `config/` (e.g., `my_rules.yaml`)
2. Load in `commands/upload.py` via `config_loader.load_yaml()`
3. Inject into use-case or adapters

### C. Adding Domain Validation Rules

1. Add invariant check in domain model (e.g., `Product.__init__`)
2. Raise domain exception if violated
3. Catch in use-case, log as validation error

---

## 11. Known Architectural Patterns

### Pattern 1: Hexagonal Architecture (Ports & Adapters)

- **Ports:** Interfaces in `ports.py`
- **Adapters:** External implementations
- **Isolates** core logic from technical details

### Pattern 2: Test-Driven Generation (TDG)

- Write failing tests first
- Implement to pass tests
- Ensure quality from inception

### Pattern 3: Dependency Injection

- Use-cases depend on Protocols, not concrete classes
- Injection at composition root (`commands/upload.py`)
- Testability + modularity

### Pattern 4: Domain-Driven Design (DDD)

- Core domain models (`Product`, `Category`, `Attribute`)
- Business logic in domain, not service layer
- Aggregate roots for consistency

### Pattern 5: Resilience (HTTP)

- Exponential backoff + jitter (transient errors)
- Rate-limit handling (token bucket + `Retry-After`)
- Request tracing + observability

---

## 12. Common Troubleshooting

### "Token expired"
→ Run `uv run ml-upload auth` to refresh or re-authenticate

### "Category not found"
→ Check `config/standard_fields.yaml` explicit_mappings; run `validate` first to see predictor suggestion

### "Image upload failed"
→ Check image path format (`<images>/<SKU>/` or `<images>/`), file permissions

### "Attribute validation failed"
→ Check `config/attribute_rules.yaml`, ensure attribute ID is supported by category

### "pytest coverage gate failed"
→ Use `--override-ini addopts=''` to skip coverage gate during targeted test runs

---

## 13. Dependencies & Technology Stack

### Runtime Dependencies
- **openpyxl**, **xlrd** – Excel parsing
- **pandas** – Dataframe manipulation
- **pyyaml** – Config loading
- **requests** – HTTP client
- **aiohttp** – Async HTTP (optional)
- **cryptography**, **keyring** – Secure token storage
- **typer** – CLI framework
- **pydantic** – Data validation
- **rich** – CLI output formatting

### Dev Dependencies
- **pytest**, **pytest-cov**, **pytest-mock** – Testing
- **black** – Code formatting
- **ruff** – Linting
- **mypy** – Type checking
- **bandit** – Security scanning
- **pre-commit** – Git hooks

---

## 14. Repository Layout Summary

```
scriptml/
├── .github/
│   ├── agents/                   # Reusable copilot agents
│   │   ├── code-review-agent.md
│   │   ├── mercadolivre-docs-agent.md
│   │   └── pr-engineer-agent.md
│   ├── copilot-instructions.md   # Copilot coding guidelines
│   └── workflows/                # CI/CD pipelines
│
├── mercadolivre_upload/          # Main package
│   ├── cli/
│   ├── application/
│   ├── domain/
│   ├── adapters/
│   ├── infrastructure/
│   ├── api/
│   └── shared/
│
├── tests/                        # Test suite (~60 test files)
├── config/                       # YAML configs
├── cache/                        # Runtime caches & reports
├── anuncios/                     # Example fixtures
├── plans/                        # Feature planning (SDD)
├── skills/                       # Domain knowledge (SKILL.md files)
├── docs/                         # Additional documentation
├── pyproject.toml                # Project metadata & toolchain
├── README.md                     # User-facing documentation
├── AGENTS.md                     # Agent-focused guide
├── llms.txt                      # LLM-focused navigation
└── AI_CONTEXT.md                 # This file
```

---

## 15. For AI/LLM Consumption

### Entry Points for Analysis

**Priority 1 (Start Here):**
1. `README.md` – High-level overview & CLI reference
2. `mercadolivre_upload/cli/app.py` – Command registration & setup
3. `mercadolivre_upload/cli/commands/upload.py` – Composition root & wiring

**Priority 2 (Understand Core Logic):**
4. `mercadolivre_upload/application/publish_product.py` – Orchestration
5. `mercadolivre_upload/application/ports.py` – Interface definitions
6. `mercadolivre_upload/application/publish/internals/` – Pipeline steps

**Priority 3 (Infrastructure & Adapters):**
7. `mercadolivre_upload/infrastructure/http.py` – HTTP resilience
8. `mercadolivre_upload/api/client.py` – API client
9. `mercadolivre_upload/adapters/` – External integrations

**Priority 4 (Domain & Tests):**
10. `mercadolivre_upload/domain/` – Domain models
11. `tests/test_publish_product.py` – Use-case tests
12. `tests/test_cli.py` – CLI integration tests

### Key Files for Specific Tasks

| Task | Primary File | Secondary Files |
|------|--------------|-----------------|
| Add a CLI command | `cli/app.py`, `cli/commands/` | `cli/__init__.py` |
| Add a new adapter | `adapters/`, `ports.py` | `cli/commands/upload.py` (injection) |
| Fix API client | `api/client.py` | `infrastructure/http.py` |
| Improve category resolution | `application/publish/internals/category.py` | `config/standard_fields.yaml` |
| Handle new validation rule | `domain/` + `application/` | `config/attribute_rules.yaml` |
| Add tests | `tests/` | Existing test pattern files |

### Useful Queries

**What happens when a user runs `ml-upload upload`?**
→ Trace `cli/app.py::upload()` → `commands/upload.py::upload_cmd()` → `PublishProductUseCase.execute()`

**How is a category resolved?**
→ `application/publish/internals/category.py` – Name match → Predictor → Explicit mappings

**How are images uploaded?**
→ `adapters/image_uploader.py` – Searches `<images>/<SKU>/` or `<images>/` → Uploads to ML

**How are tokens stored securely?**
→ `adapters/auth_manager.py` or `auth/authenticator.py` – Encrypts with `cryptography.Fernet` + `keyring`

**How is the publish pipeline structured?**
→ `application/publish/internals/flow.py` – Stateless orchestration of steps; `state.py` tracks results

---

## 16. Conventions & Best Practices (For Code Generation)

### Naming
- **Packages:** snake_case
- **Classes:** PascalCase
- **Functions/methods:** snake_case
- **Constants:** UPPER_SNAKE_CASE

### Type Hints
- All public functions must have type hints
- Strict MyPy mode enabled
- Use `Protocol` for interfaces

### Comments
- Only comment non-obvious logic
- Avoid over-commenting
- Docstrings for public modules/classes/functions

### Error Handling
- Raise domain exceptions for business logic violations
- Log and track errors for retry/audit
- Provide actionable error messages to users

### Testing
- Write tests before implementation (TDG)
- Mock external dependencies
- Use fixtures for shared test data
- Aim for >60% coverage (enforced)

### Commits
- Use Conventional Commits format: `feat(area): description`
- Include `Co-authored-by: Copilot <...>` trailer for agent commits
- Small, reversible commits (single logical step)

---

## Summary

This repository is a **production-grade Python CLI for automating Mercado Livre product bulk uploads**. It combines:

- **Hexagonal architecture** for testability and modularity
- **Domain-driven design** for clear business logic
- **Test-driven development** for quality assurance
- **Resilient HTTP & token management** for reliability
- **YAML-based configuration** for customization
- **Encrypted token storage** for security

The codebase demonstrates best practices in Python application design, making it an excellent reference for learning clean architecture, testing strategies, and API integration patterns.

---

**Last Updated:** 2026-03-20  
**For Questions:** Refer to README.md, AGENTS.md, or llms.txt
