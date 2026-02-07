
# Import Analysis Report


Total issues found: 41

- Duplicate auth package: 0
- Circular imports: 0
- Architecture violations: 0
- Unused imports: 22
- Duplicate imports: 19
- Style issues: 0

## Unused Imports

| File | Line | Import | Problem | Impact | Minimal Suggestion |
|------|------|--------|---------|--------|--------------------|
| analyze_imports.py | 9 | from typing import Tuple | Unused import | LOW | Remove this line |
| analyze_imports.py | 10 | import sys | Unused import | LOW | Remove this line |
| auth/authenticator.py | 2 | from __future__ import annotations | Unused import | LOW | Remove this line |
| check_auth_detail.py | 4 | import os | Unused import | LOW | Remove this line |
| mercadolivre_upload/adapters/async_image_uploader.py | 3 | from __future__ import annotations | Unused import | LOW | Remove this line |
| mercadolivre_upload/adapters/spreadsheet/parser.py | 6 | from __future__ import annotations | Unused import | LOW | Remove this line |
| mercadolivre_upload/api/cbt_extractor.py | 11 | from mercadolivre_upload.api.client import MLApiClient | Unused import | LOW | Remove this line |
| mercadolivre_upload/application/builders/product_builder.py | 3 | from __future__ import annotations | Unused import | LOW | Remove this line |
| mercadolivre_upload/infrastructure/cache/attribute_cache.py | 1 | from __future__ import annotations | Unused import | LOW | Remove this line |
| mercadolivre_upload/infrastructure/config.py | 10 | from __future__ import annotations | Unused import | LOW | Remove this line |
| mercadolivre_upload/infrastructure/logging.py | 10 | from __future__ import annotations | Unused import | LOW | Remove this line |
| mercadolivre_upload/infrastructure/metrics.py | 10 | from __future__ import annotations | Unused import | LOW | Remove this line |
| mercadolivre_upload/infrastructure/metrics.py | 23 | from prometheus_client import generate_latest | Unused import | LOW | Remove this line |
| mercadolivre_upload/infrastructure/metrics.py | 23 | from prometheus_client import CONTENT_TYPE_LATEST | Unused import | LOW | Remove this line |
| mercadolivre_upload/infrastructure/migration.py | 42 | from __future__ import annotations | Unused import | LOW | Remove this line |
| mercadolivre_upload/infrastructure/migration.py | 62 | import openpyxl | Unused import | LOW | Remove this line |
| mercadolivre_upload/infrastructure/observability.py | 11 | from __future__ import annotations | Unused import | LOW | Remove this line |
| mercadolivre_upload/infrastructure/observability.py | 38 | from rich.progress import SpinnerColumn | Unused import | LOW | Remove this line |
| mercadolivre_upload/infrastructure/observability.py | 38 | from rich.progress import Progress | Unused import | LOW | Remove this line |
| mercadolivre_upload/infrastructure/observability.py | 38 | from rich.progress import TextColumn | Unused import | LOW | Remove this line |
| mercadolivre_upload/infrastructure/observability.py | 38 | from rich.progress import BarColumn | Unused import | LOW | Remove this line |
| mercadolivre_upload/main.py | 3 | from __future__ import annotations | Unused import | LOW | Remove this line |

## Duplicate Imports

| File | Line | Import | Problem | Impact | Minimal Suggestion |
|------|------|--------|---------|--------|--------------------|
| auth/authenticator.py | 245 | import json | Duplicate import (already on line 5) | LOW | Delete line 245 |
| mercadolivre_upload/api/client.py | 348 | from pathlib import Path | Duplicate import (already on line 231) | LOW | Delete line 348 |
| mercadolivre_upload/application/publish_product.py | 875 | from auth.authenticator import AuthManager | Duplicate import (already on line 10) | LOW | Delete line 875 |
| mercadolivre_upload/cli/app.py | 110 | from importlib import import_module | Duplicate import (already on line 8) | LOW | Delete line 110 |
| mercadolivre_upload/cli/app.py | 151 | from importlib import import_module | Duplicate import (already on line 8) | LOW | Delete line 151 |
| mercadolivre_upload/infrastructure/migration.py | 149 | import json | Duplicate import (already on line 961) | LOW | Delete line 149 |
| mercadolivre_upload/utils/errors.py | 266 | from rich.table import Table | Duplicate import (already on line 8) | LOW | Delete line 266 |
| tests/test_cli.py | 319 | import sys | Duplicate import (already on line 3) | LOW | Delete line 319 |
| tests/test_cli.py | 320 | from pathlib import Path | Duplicate import (already on line 4) | LOW | Delete line 320 |
| tests/test_main.py | 28 | from mercadolivre_upload.main import main_entry | Duplicate import (already on line 19) | LOW | Delete line 28 |
| tests/test_main.py | 54 | from mercadolivre_upload.main import run_as_module | Duplicate import (already on line 43) | LOW | Delete line 54 |
| tests/test_main.py | 87 | from mercadolivre_upload.main import setup_environment | Duplicate import (already on line 66) | LOW | Delete line 87 |
| tests/test_main.py | 131 | from mercadolivre_upload.main import setup_environment | Duplicate import (already on line 66) | LOW | Delete line 131 |
| tests/test_main.py | 152 | import sys | Duplicate import (already on line 3) | LOW | Delete line 152 |
| tests/test_main.py | 153 | from pathlib import Path | Duplicate import (already on line 4) | LOW | Delete line 153 |
| tests/test_observability.py | 18 | import sys | Duplicate import (already on line 11) | LOW | Delete line 18 |
| tests/test_observability.py | 21 | from pathlib import Path | Duplicate import (already on line 12) | LOW | Delete line 21 |
| tests/test_spreadsheet_parser.py | 413 | from mercadolivre_upload.application.builders.product_builder import ProductBuilder | Duplicate import (already on line 381) | LOW | Delete line 413 |
| tests/test_spreadsheet_parser_extended.py | 1290 | import logging | Duplicate import (already on line 1263) | LOW | Delete line 1290 |