# Mercado Livre Bulk Upload Pipeline

Automated bulk product publication system for Mercado Livre (Brazil) using Excel spreadsheets and the Mercado Livre API.

## Features

- **Dynamic Excel Parsing**: Handles messy ML bulk templates with instructional headers
- **Dynamic Attribute Mapping**: Fuzzy matches Excel columns to ML API attributes (name and ID)
- **Category Resolution**: Auto-resolves category IDs from names using predictor-first strategy
- **Conditional Attributes**: Handles ML's conditional attribute requirements
- **Image Upload**: Uploads product images from SKU-based folders
- **Pre-validation**: Validates items before publishing
- **Dry-run Mode**: Test without actually publishing

## Architecture

Clean Architecture implementation:

```
mercadolivre_upload/
├── domain/                 # Pure business logic
│   ├── category/           # Category resolution
│   │   └── resolver.py
│   ├── product/            # Product models
│   │   └── model.py
│   ├── fiscal/             # Fiscal data (NCM, CFOP, etc.)
│   │   └── data.py
│   └── attribute_mapper.py # Dynamic fuzzy attribute mapping
├── application/            # Use cases
│   └── publish_product.py  # PublishProductUseCase
├── adapters/               # Input/output adapters
│   ├── image_uploader.py
│   └── spreadsheet/
│       ├── parser.py       # SpreadsheetParser
│       └── header_detector.py
├── api/                    # External API adapters
│   ├── client.py           # MLApiClient
│   ├── category_adapter.py
│   └── category_resolver.py
├── auth/                   # Authentication
│   ├── oauth.py
│   ├── token_manager.py
│   └── exceptions.py
├── parser/                 # Legacy parser module
│   ├── dynamic_parser.py
│   ├── excel_parser.py
│   └── models.py
├── pipeline.py             # 3-layer pipeline (see note below)
└── main.py                 # CLI entry point
```

**Note**: The `pipeline.py` file implements a 3-layer pipeline architecture but references a `publisher.publisher` module that doesn't exist yet. Use `main.py` as the primary entry point.

## Installation

### Using pip

```bash
# Create virtual environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Activate (Linux/Mac)
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Using uv (faster)

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

## Dependencies

Create `requirements.txt`:

```
pandas>=2.0.0
openpyxl>=3.1.0
requests>=2.31.0
rapidfuzz>=3.0.0
pytest>=7.4.0
pytest-mock>=3.11.0
```

Or use `pyproject.toml`:

```toml
[project]
name = "mercadolivre-upload"
version = "0.1.0"
dependencies = [
    "pandas>=2.0.0",
    "openpyxl>=3.1.0",
    "requests>=2.31.0",
    "rapidfuzz>=3.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.4.0",
    "pytest-mock>=3.11.0",
]
```

## Setup

### 1. Mercado Livre API Credentials

1. Go to [Mercado Livre Developers](https://developers.mercadolivre.com.br/)
2. Create an application to get `client_id` and `client_secret`
3. Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
# Edit .env with your credentials
```

4. Generate OAuth tokens and save to `tokens.json`:

```json
{
  "access_token": "APP_USR-...",
  "refresh_token": "TG-...",
  "expires_at": 1700000000
}
```

### 2. Prepare Input Data

Create folder structure:

```
project/
├── anuncios/
│   ├── produtos.xlsx          # Excel with product data
│   ├── SKU001/                # Images for SKU001
│   │   ├── img1.jpg
│   │   └── img2.jpg
│   └── SKU002/                # Images for SKU002
│       └── img1.png
```

### Excel Format

The parser detects columns dynamically. Supported column names (case-insensitive):

| Field | Portuguese | English |
|-------|------------|---------|
| SKU | SKU, Código | SKU, Code |
| Title | Título, Nome | Title, Name |
| Description | Descrição | Description |
| Price | Preço [R$] | Price |
| Stock | Estoque | Stock, Quantity |
| Condition | Condição | Condition (Novo/Usado) |
| NCM | NCM | - |
| CFOP | CFOP | - |
| Origin | Origem | Origin |

Additional columns are captured as product attributes.

## Usage

### Command Line

```bash
# Publish all products
python -m mercadolivre_upload.main \
  --excel anuncios/produtos.xlsx \
  --images anuncios/ \
  --category "Livros"

# Dry run (validate only)
python -m mercadolivre_upload.main \
  --excel anuncios/produtos.xlsx \
  --images anuncios/ \
  --category "Livros" \
  --dry-run
```

### Python API

```python
from pathlib import Path
from mercadolivre_upload.adapters.spreadsheet.parser import SpreadsheetParser
from mercadolivre_upload.adapters.image_uploader import ImageUploader
from mercadolivre_upload.api.category_adapter import CategoryAdapter
from mercadolivre_upload.api.client import MLApiClient
from mercadolivre_upload.application.publish_product import PublishProductUseCase
from mercadolivre_upload.auth import AuthManager
from mercadolivre_upload.domain.category.resolver import CategoryResolver

# Parse products
parser = SpreadsheetParser()
products = parser.parse("anuncios/produtos.xlsx")

# Setup dependencies
auth = AuthManager()
client = MLApiClient(auth)
category_adapter = CategoryAdapter(client)
category_resolver = CategoryResolver(category_adapter)
image_uploader = ImageUploader(client, Path("anuncios/"))

# Create use case
use_case = PublishProductUseCase(
    category_resolver=category_resolver,
    publisher=client,
    image_uploader=image_uploader,
    dry_run=False
)

# Execute
results = use_case.execute(products, "Livros")
print(f"Published: {results['published']}")
print(f"Failed: {results['failed']}")
```

## Testing

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_parser.py -v

# Run with coverage
pytest --cov=mercadolivre_upload
```

## Development

### Project Structure

```
.
├── mercadolivre_upload/    # Main package
├── tests/                   # Test suite
├── anuncios/               # Sample data (not in repo)
├── tokens.json             # API tokens (not in repo)
├── requirements.txt        # Pip dependencies
├── pyproject.toml          # Project metadata
└── README.md               # This file
```

### Adding New Features

1. **Domain Layer**: Add pure business logic in `domain/`
2. **Application Layer**: Add use cases in `application/`
3. **Adapters**: Add I/O implementations in `adapters/`
4. **Tests**: Add tests in `tests/`

## API Endpoints Used

- `GET /sites/MLB/categories` - Category discovery
- `GET /categories/{id}/attributes` - Base attributes
- `POST /categories/{id}/attributes/conditional` - Conditional attributes
- `POST /pictures` - Image upload
- `POST /items/validate` - Pre-validation
- `POST /items` - Product publication

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `MERCADO_LIVRE_CLIENT_ID` | Mercado Livre app client ID | Required |
| `MERCADO_LIVRE_CLIENT_SECRET` | Mercado Livre app client secret | Required |
| `MERCADO_LIVRE_REDIRECT_URI` | OAuth callback URL | `http://localhost:8000/callback` |
| `MERCADO_LIVRE_TOKEN_PATH` | Path to tokens.json | `tokens.json` |

Credentials can be set via environment variables or in a `.env` file.

## License

MIT

## References

- [Mercado Livre API Docs](https://developers.mercadolivre.com.br/pt_br/guia-para-produtos)
