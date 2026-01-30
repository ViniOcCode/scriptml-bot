# Mercado Livre Bulk Upload Pipeline

Automated bulk product publication system for Mercado Livre (Brazil) using Excel spreadsheets and the Mercado Livre API. This tool transforms messy bulk upload templates into properly formatted API requests with intelligent attribute mapping, validation, and fiscal data submission.

## Table of Contents

- [Project Overview](#project-overview)
- [Architecture](#architecture)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Excel Format](#excel-format)
- [Attribute Mapping](#attribute-mapping)
- [Production Considerations](#production-considerations)
- [Troubleshooting](#troubleshooting)

---

## Project Overview

This application automates the process of publishing products to Mercado Livre from Excel spreadsheets. It handles the complexity of ML's attribute system, category resolution, image uploads, and fiscal data submission.

### Key Features

| Feature | Description |
|---------|-------------|
| **Dynamic Excel Parsing** | Automatically detects header rows in messy ML bulk templates with instructional headers |
| **Cached Attribute Mapping** | Uses pre-fetched category cache files for exact attribute matching with fallback to fuzzy matching |
| **Smart Category Resolution** | Predictor-first strategy using ML's domain discovery API, with fuzzy fallback |
| **Validation Pipeline** | Multi-layer validation: structural, semantic scoring, and sanitization |
| **Fiscal Data Submission** | Automatic submission of NCM, CFOP, CEST, and other tax information after publication |
| **Unit Suffix Handling** | Automatically appends units (cm, kg) to dimension attributes |
| **Image Upload** | Uploads product images from SKU-based folders |
| **Dry-run Mode** | Validate entire pipeline without actually publishing |
| **Configuration-Driven** | YAML-based mappings for standard fields and fiscal data |

### Use Cases

- **Bulk product migration** from other platforms to Mercado Livre
- **Inventory synchronization** for existing sellers
- **New seller onboarding** with large product catalogs
- **Category-specific uploads** with complex attribute requirements

---

## Architecture

The application follows **Clean Architecture** principles with clear separation of concerns:

```
mercadolivre_upload/
├── domain/                    # Pure business logic (no external dependencies)
│   ├── category/resolver.py   # Category resolution strategies
│   ├── product/model.py       # Product entity definitions
│   ├── fiscal/                # Fiscal data models and submission
│   │   ├── data.py           # FiscalData dataclass
│   │   └── service.py        # Fiscal submission service
│   ├── cache_attribute_mapper.py    # Cache-based exact attribute mapping
│   ├── smart_mapper.py       # Fuzzy matching for unknown columns
│   ├── text_normalizer.py    # Portuguese text normalization
│   └── validation/           # Multi-layer validation pipeline
│       ├── structural.py     # Type/pattern validation
│       ├── scoring.py        # Semantic relevance scoring
│       ├── sanitizer.py      # Attribute filtering
│       └── feedback.py       # Error tracking and learning
│
├── application/              # Use cases (orchestration layer)
│   └── publish_product.py    # PublishProductUseCase
│
├── adapters/                 # Input/output adapters
│   ├── image_uploader.py     # Image upload to ML
│   └── spreadsheet/          # Excel parsing
│       ├── parser.py
│       └── header_detector.py
│
├── api/                      # External API adapters
│   ├── client.py             # MLApiClient
│   ├── category_adapter.py
│   └── category_resolver.py
│
├── auth/                     # OAuth2 authentication
│   ├── oauth.py
│   ├── token_manager.py
│   └── exceptions.py
│
├── infrastructure/           # Infrastructure concerns
│   └── cache/                # Attribute cache management
│
└── main.py                   # CLI entry point
```

### Data Flow

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Excel     │────▶│   Parser    │────▶│   Domain    │────▶│    API      │
│  File (.xlsx)│     │  (adapters) │     │  (use case) │     │  (ML API)   │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
                            │
                            ▼
                     ┌─────────────┐
                     │   Images    │
                     │  (SKU dirs) │
                     └─────────────┘
```

### Validation Pipeline

The application implements a sophisticated 4-layer validation system:

1. **Structural Validation** - Type checking, pattern matching, max length enforcement
2. **Attribute Classification** - Categorizes attributes as editorial/technical/commercial/logistics
3. **Semantic Scoring** - Scores attributes 0-100 based on relevance and quality
4. **Sanitization** - Filters low-scoring attributes and removes redundancy

---

## Installation

### Prerequisites

- Python 3.11+
- Mercado Livre API credentials (Client ID and Secret)
- Windows/Linux/macOS

### Using pip

```bash
# Clone or navigate to the project directory
cd mercadolivre-bulk-upload

# Create virtual environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Activate (Linux/Mac)
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Using uv (faster, recommended)

```bash
# Create virtual environment with uv
uv venv

# Activate (Windows)
.venv\Scripts\activate

# Activate (Linux/Mac)
source .venv/bin/activate

# Install dependencies
uv pip install -r requirements.txt

# Or use uv sync (if using uv.lock)
uv sync
```

### Dependencies

```
requests>=2.28.0      # HTTP client for ML API
pandas>=1.5.0         # Excel parsing
openpyxl>=3.0.0       # Excel file support
python-dotenv>=1.0.0  # Environment variables
pyyaml>=6.0.0         # Configuration files
rapidfuzz>=3.0.0      # Fuzzy string matching
pytest>=7.0.0         # Testing (dev)
```

### Environment Setup

1. Copy the example environment file:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` with your Mercado Livre credentials:
   ```env
   MERCADO_LIVRE_CLIENT_ID=your_client_id_here
   MERCADO_LIVRE_CLIENT_SECRET=your_client_secret_here
   MERCADO_LIVRE_REDIRECT_URI=http://localhost:8000/callback
   ```

3. Get your credentials from [Mercado Livre Developers](https://developers.mercadolivre.com.br/)

---

## Configuration

The application uses a YAML-based configuration system in [`config/generic_mappings.yaml`](config/generic_mappings.yaml).

### Configuration Structure

```yaml
# Minimum confidence score for fuzzy matching (0.0 - 1.0)
min_confidence_threshold: 0.85

# Strategy when no match is found: skip | flag | fail
on_unmatched: flag

# Core item fields that are ALWAYS required
core_item_fields:
  required:
    - title
    - price
    - currency_id
    - available_quantity
    - condition
    - listing_type_id
  
  # Default values for fields not in Excel
  defaults:
    currency_id: "BRL"
    listing_type_id: "gold_special"
    buying_mode: "buy_it_now"
    
    # Default warranty terms
    sale_terms:
      - id: "WARRANTY_TYPE"
        value_name: "Garantia do vendedor"
      - id: "WARRANTY_TIME"
        value_struct:
          number: 30
          unit: "dias"
```

### Explicit Mappings

Map specific Excel columns directly to ML attributes:

```yaml
explicit_mappings:
  # Warranty fields
  "Tipo de garantia":
    target: "sale_terms"
    id: "WARRANTY_TYPE"
    value_name: "Garantia do vendedor"
  
  # Dimension fields with automatic unit suffix
  "Largura (cm)":
    target: "attribute"
    id: "WIDTH"
    unit_suffix: " cm"
  
  "Peso físico (kg)":
    target: "attribute"
    id: "WEIGHT"
    unit_suffix: " kg"
```

### Standard Fields

Configure pattern matching for common fields:

```yaml
standard_fields:
  sku:
    description: "Product SKU/identifier"
    required: true
    patterns:
      - "sku"
      - "código"
      - "referência"
    exact_matches:
      - "SKU"
      - "sku"
  
  price:
    description: "Product price"
    required: true
    patterns:
      - "preço"
      - "preco"
      - "valor"
```

### Fiscal Fields

Map tax-related columns:

```yaml
fiscal_fields:
  ncm:
    description: "NCM code (8 digits)"
    required: true
    patterns:
      - "ncm"
      - "código ncm"
    validation:
      pattern: '^\d{8}$'
      message: "NCM deve ter exatamente 8 dígitos"
  
  origin:
    description: "Product origin code"
    value_mappings:
      "nacional": "0"
      "importado": "1"
```

---

## Usage

### Basic Command

```bash
python -m mercadolivre_upload.main \
  --excel "path/to/products.xlsx" \
  --images "path/to/images/" \
  --category "Livros"
```

### Command-Line Arguments

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `--excel` | Yes | - | Path to Excel file with product data |
| `--images` | Yes | - | Path to directory containing SKU subfolders with images |
| `--category` | Yes | - | Category name (e.g., "Livros", "Eletrônicos") |
| `--dry-run` | No | False | Validate only, don't publish |
| `--cache-dir` | No | `cache/categories` | Directory for attribute cache files |
| `--cache-ttl` | No | 24 | Cache TTL in hours (0 = no expiration) |
| `--clear-cache` | No | False | Clear attribute cache before running |

### Examples

#### Dry Run (Validation Only)

```bash
python -m mercadolivre_upload.main \
  --excel "products.xlsx" \
  --images "./images" \
  --category "Celulares e Smartphones" \
  --dry-run
```

#### Clear Cache and Refresh

```bash
python -m mercadolivre_upload.main \
  --excel "products.xlsx" \
  --images "./images" \
  --category "Livros" \
  --clear-cache
```

#### Long Cache Duration

```bash
python -m mercadolivre_upload.main \
  --excel "products.xlsx" \
  --images "./images" \
  --category "Eletrônicos" \
  --cache-ttl 168  # 1 week
```

### Image Directory Structure

Images should be organized in subfolders by SKU:

```
images/
├── SKU001/
│   ├── front.jpg
│   ├── back.jpg
│   └── detail.png
├── SKU002/
│   ├── main.jpg
│   └── side.jpg
└── SKU003/
    └── product.webp
```

---

## Excel Format

### Supported Formats

- `.xlsx` (Excel 2007+)
- `.xls` (Excel 97-2003)

### Header Detection

The parser automatically detects the header row by scanning the first 10 rows and scoring based on:

| Indicator | Weight |
|-----------|--------|
| `sku` | 5 |
| `t[ií]tulo` (but not "Título do livro") | 4 |
| `condi[cç][aã]o` | 3 |
| `pre[cç]o` | 3 |
| `estoque` | 2 |
| `fotos` | 2 |

### Required Columns

| Column | Description | Example |
|--------|-------------|---------|
| **SKU** | Product identifier | `BOOK001` |
| **Título** | Product title | `Meu Querido Pet` |
| **Preço** | Price in BRL | `29.90` |
| **Condição** | new/used/recondicionado | `novo` |

### Optional Columns

| Column | Description | Default |
|--------|-------------|---------|
| **Estoque** | Available quantity | 1 |
| **Descrição** | Product description | Same as title |
| **Fotos** | Image filenames (comma-separated) | Auto-detect from SKU folder |

### Category-Specific Attributes

All other columns are treated as category-specific attributes and mapped to ML API attributes:

| Excel Column | ML Attribute | Example Value |
|--------------|--------------|---------------|
| `Título do livro` | `BOOK_TITLE` | `Meu Querido Pet` |
| `Autor` | `AUTHOR` | `Editora Ridell` |
| `ISBN` | `GTIN` | `9786015211459` |
| `Idioma` | `LANGUAGE` | `Português` |
| `Gênero do livro` | `BOOK_GENRE` | `Infantil` |

### Fiscal Data Columns

| Column | Description | Format |
|--------|-------------|--------|
| `NCM` | NCM code | 8 digits (e.g., `39263000`) |
| `Origem` | Origin code | 0-8 or "nacional"/"importado" |
| `CFOP` | CFOP code | 4 digits (e.g., `5102`) |
| `CEST` | CEST code | 7 digits |
| `Custo` | Product cost | Decimal (e.g., `15.50`) |

### Example Spreadsheet Structure

| SKU | Título | Preço | Condição | Estoque | NCM | Origem | Autor | Idioma |
|-----|--------|-------|----------|---------|-----|--------|-------|--------|
| BK001 | Livro A | 29.90 | novo | 10 | 49019900 | 0 | Autor A | Português |
| BK002 | Livro B | 35.00 | novo | 5 | 49019900 | 0 | Autor B | Português |

---

## Attribute Mapping

The application uses a **two-phase mapping strategy** for maximum accuracy:

### Phase 1: Cache-Based Exact Matching ([`CachedAttributeMapper`](mercadolivre_upload/domain/cache_attribute_mapper.py))

1. **Pre-fetch** category attributes from ML API and cache as JSON
2. **Build indexes** for fast lookup:
   - Normalized name → Attribute definition
   - Value name → Value ID (for list-type attributes)
3. **Exact match** Excel columns against cached attribute names
4. **Map values** to ML API format with proper IDs

**Advantages:**
- Fast (O(1) lookup)
- Works offline after initial cache
- Handles list-type attributes correctly
- No API calls during mapping

### Phase 2: Fuzzy Matching ([`SmartAttributeMapper`](mercadolivre_upload/domain/smart_mapper.py))

When cache doesn't contain a match:

1. **Normalize** both Excel header and ML attribute names
2. **Calculate similarity** using SequenceMatcher
3. **Accept match** if similarity ≥ `min_confidence_threshold` (default: 0.85)
4. **Fallback** to pattern matching from config

**Example Mappings:**

| Excel Column | ML Attribute | Score |
|--------------|--------------|-------|
| `Título do livro` | `BOOK_TITLE` | 1.00 |
| `Autor` | `AUTHOR` | 1.00 |
| `Gênero do livro` | `BOOK_GENRE` | 0.97 |
| `Quantidade de caracteres` | `NUMBER_OF_PAGES` | 0.76 |
| `Largura cm` | `WIDTH` | 0.82 |

### Text Normalization

The [`PortugueseTextNormalizer`](mercadolivre_upload/domain/text_normalizer.py) handles:

- Lowercase conversion
- Accent removal (á → a, ç → c)
- Article removal (do, da, de, dos, das)
- Special character normalization

### Value Mapping

For list-type attributes, the system maps Excel values to ML value IDs:

```python
# Excel value
"Português"

# Mapped to ML API format
{
    "id": "LANGUAGE",
    "name": "Idioma",
    "value_id": "1258229",
    "value_name": "Português",
    "values": [{"id": "1258229", "name": "Português"}]
}
```

---

## Production Considerations

### Rate Limiting

The ML API has rate limits. The application:

- Implements exponential backoff on 429 errors
- Caches category attributes to reduce API calls
- Reuses authentication tokens

**Recommendations:**
- Use `--cache-ttl 168` (1 week) for stable categories
- Run during off-peak hours for large batches
- Monitor `feedback_log.json` for patterns

### Validation Strategy

The validation pipeline is designed to be **permissive but safe**:

| Issue | Action | Rationale |
|-------|--------|-----------|
| Unknown attribute | Drop with warning | Prevents API errors |
| Type mismatch | Drop with warning | Maintains data integrity |
| Missing required | Block payload | ML will reject anyway |
| Value not in domain | Drop with warning | Prevents rejection |
| Exceeds max_length | Truncate | Preserves partial data |
| Low semantic score | Drop | Improves listing quality |

### Fiscal Data Submission

Fiscal data is submitted **after** item publication via the `/items/{item_id}/fiscal_info` endpoint:

1. Item is published first
2. If successful, fiscal data is submitted
3. Fiscal submission failures are logged but don't fail the item

**Required Fiscal Fields:**
- SKU
- Title
- NCM (8 digits)
- Origin code (0-8)

### Known Issues

1. **Category Changes**: ML occasionally changes attribute IDs. Use `--clear-cache` if mappings fail.

2. **Image Upload Limits**: ML has limits on image size and count. Large batches may need throttling.

3. **Conditional Attributes**: Some attributes become required based on other values. The pipeline handles these via ML's conditional attributes endpoint.

4. **Title Uniqueness**: ML requires unique titles. The application doesn't check for duplicates before publishing.

### Monitoring

Check these files for operational insights:

| File | Purpose |
|------|---------|
| `feedback_log.json` | Validation errors and patterns |
| `cache/categories/*.json` | Cached attribute definitions |
| Console output | Real-time progress and errors |

---

## Troubleshooting

### Common Errors

#### "Cache file not found"

**Cause**: Category attributes haven't been fetched yet.

**Solution**:
```bash
# The cache is built automatically on first run
# Or clear and rebuild:
python -m mercadolivre_upload.main --excel ... --clear-cache
```

#### "No images found for SKU"

**Cause**: Image folder structure doesn't match expected format.

**Solution**:
- Ensure images are in `{images_dir}/{SKU}/` subfolders
- Supported formats: `.jpg`, `.jpeg`, `.png`, `.gif`, `.webp`
- Check case sensitivity (SKU must match exactly)

#### "Category not found"

**Cause**: Category name doesn't match ML's naming.

**Solution**:
- Check exact category name from ML website
- Try variations (e.g., "Livros" vs "Livros Físicos")
- Use domain discovery by using a product title as category

#### "Invalid NCM format"

**Cause**: NCM code doesn't match 8-digit pattern.

**Solution**:
- Ensure NCM is exactly 8 digits
- Remove dots, dashes, or spaces
- Verify at [NCM Consulta](https://www.simulador-facil.com.br/ncm)

#### "Attribute value not in allowed domain"

**Cause**: Value doesn't match ML's predefined options.

**Solution**:
- Check the exact allowed values in ML's category page
- Use the cache file to see valid options: `cache/categories/MLBxxxx.json`
- Values are case-sensitive

#### OAuth Authentication Errors

**Cause**: Token expired or invalid credentials.

**Solution**:
```bash
# Delete token file to force re-authentication
del tokens.json  # Windows
rm tokens.json   # Linux/Mac

# Re-run the command - browser will open for authorization
```

### Debug Mode

Enable detailed logging:

```python
# In main.py or your script
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Getting Help

1. Check `feedback_log.json` for detailed error patterns
2. Review the [APP_FLOW.md](APP_FLOW.md) for detailed architecture
3. Examine cache files in `cache/categories/` to understand attribute structure
4. Use `--dry-run` to validate without side effects

### Validation Checklist

Before running production uploads:

- [ ] Excel file opens without errors
- [ ] All SKUs have corresponding image folders
- [ ] NCM codes are 8 digits
- [ ] Prices are positive numbers
- [ ] Category name is valid
- [ ] Run `--dry-run` first
- [ ] Check `feedback_log.json` for warnings
- [ ] Cache is fresh (use `--clear-cache` if unsure)

---

## License

This project is for internal use. Mercado Livre API usage is subject to their [Terms of Service](https://developers.mercadolivre.com.br/terms).

## Contributing

When adding new features:

1. Maintain Clean Architecture separation
2. Add tests for domain logic
3. Update configuration schema in `config/generic_mappings.yaml`
4. Document new CLI arguments
5. Update this README
