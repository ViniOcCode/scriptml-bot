# Mercado Livre Bulk Upload - Application Flow

## Overview

This document describes the complete data flow from Excel spreadsheet to Mercado Livre API publication.

## Architecture

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

## Data Flow Steps

### 1. CLI Entry (`main.py`)

**Input:**
- `--excel path/to/file.xlsx`
- `--images path/to/images/`
- `--category "Category Name"`
- `--dry-run` (optional)

**Output:** Publication results (success/fail counts)

**Flow:**
1. Parse CLI arguments
2. Initialize `AuthManager` and `MLApiClient`
3. Create adapters (`CategoryAdapter`, `ImageUploader`)
4. Create domain services (`CategoryResolver`, `ShippingResolver`)
5. Create `PublishProductUseCase`
6. Parse spreadsheet with `SpreadsheetParser`
7. Execute use case with category name
8. Report results

---

### 2. Spreadsheet Parsing (`adapters/spreadsheet/`)

#### 2.1 Header Detection (`header_detector.py`)

**Input:** Raw Excel DataFrame (no headers)

**Process:**
1. Scan first 10 rows to find header row
2. Score each row based on header indicators:
   - `sku` (weight: 5)
   - `t[ií]tulo` (weight: 4) - but NOT "Título do livro"
   - `condi[cç][aã]o` (weight: 3)
   - `pre[cç]o` (weight: 3)
   - `estoque` (weight: 2)
   - `fotos` (weight: 2)
3. Return row with highest score as header row

**Output:** Header row index

#### 2.2 Column Mapping (`header_detector.py`)

**Maps Excel columns to canonical names:**

| Excel Header | Canonical | Notes |
|-------------|-----------|-------|
| "Título: informe o produto..." | `title` | Main product title |
| "SKU" | `sku` | Product code |
| "Condição" | `condition` | new/used |
| "Preço [R$]" | `price` | Product price |
| "Estoque" | `available_quantity` | Quantity (default: 1) |
| "Descrição" | `description` | Defaults to title if absent |
| "Fotos" | `fotos` | Image URLs/names (handled separately) |
| "ISBN" | `isbn`/`gtin` | Also stored as GTIN |
| **All other columns** | **attributes** | Passed to ML as attributes |

**Output:** `{canonical_name: actual_column_name}` mapping

#### 2.3 Data Parsing (`parser.py`)

**Input:** DataFrame with detected headers

**Process:**
1. For each row:
   - Extract `sku`, `title` (required)
   - Extract `price`, `condition` (required)
   - Extract `available_quantity` (default: 1)
   - Extract `description` (default: title)
   - Extract fiscal data: `ncm`, `cfop`, `origin`, `cest`
   - Extract `fotos` (stored in attributes as `_fotos`)
   - **All other columns → attributes dict**

**Output:** List of `Product` entities

```python
Product(
    sku="17515PETU",
    title="Meu Querido Pet",
    description="Livro infantil...",
    price=10.00,
    available_quantity=1,
    condition="new",
    fiscal=FiscalData(ncm="", cfop="", origin="", cest=""),
    attributes={
        "Título do livro": "Meu Querido Pet",
        "Autor": "Editora Ridell",
        "ISBN": "6015211459404",
        ...
    }
)
```

---

### 3. Image Upload (`adapters/image_uploader.py`)

**Input:** SKU string

**Process:**
1. Look for folder `/{images_dir}/{SKU}/`
2. Find all images (*.jpg, *.jpeg, *.png, *.gif, *.webp)
3. Upload each image to ML `/pictures` endpoint
4. Collect picture URLs

**Output:** List of picture URLs

```python
[
    "http://http2.mlstatic.com/D_626594-MLB105497129028_012026-O.jpg",
    ...
]
```

---

### 4. Category Resolution (`domain/category/resolver.py`)

**Input:** Category name string (e.g., "Livros Físicos")

**Process:**
1. **Predictor-First Strategy:**
   - Call ML `/sites/MLB/domain_discovery/search?q={title}`
   - Get predicted category from product title
   - Return if confidence is high

2. **Fuzzy Matching:**
   - Get all categories from `/sites/MLB/categories`
   - Fuzzy match category name against list
   - Return best match

3. **Fallback:** Try domain discovery with each product title

**Output:** Category ID (e.g., "MLB437616")

---

### 5. Attribute Mapping (`domain/attribute_mapper.py`)

**Input:**
- Product attributes dict (from Excel)
- ML category attributes (from API)

**Process:**
1. Get required/optional attributes for category from `/categories/{id}/attributes`
2. For each Excel column, fuzzy match against ML attribute names:
   - Normalize text (lowercase, remove accents)
   - Compare using SequenceMatcher
   - Match against both `name` and `id`
3. If similarity >= 0.7, consider it a match

**Example Mappings:**

| Excel Column | ML Attribute | Score |
|-------------|--------------|-------|
| "Título do livro" | "Título do livro" (BOOK_TITLE) | 1.00 |
| "Autor" | "Autor" (AUTHOR) | 1.00 |
| "Editora do livro" | "Editora do livro" | 1.00 |
| "Gênero do livro" | "Gênero do livro" | 0.97 |
| "Quantidade de caracteres" | "Quantidade de páginas" | 0.76 |
| "Largura cm" | "Largura" | 0.82 |

**Output:** List of ML-formatted attributes

```python
[
    {"id": "BOOK_TITLE", "name": "Título do livro", "value_name": "Meu Querido Pet"},
    {"id": "AUTHOR", "name": "Autor", "value_name": "Editora Ridell"},
    ...
]
```

---

### 6. Shipping Resolution (`domain/shipping/resolver.py`)

**Input:** None (uses API client)

**Process:**
1. Call `/users/me` to get user info
2. Check `status.mercadoenvios`:
   - If `"accepted"` → return `["me1", "me2"]`
   - If `"not_accepted"` → return `["me2"]` (can still use me2)
3. Select best mode: `me2` > `me1` > `not_specified`

**Output:** Shipping mode string ("me2", "me1", or "not_specified")

---

### 7. Item Building (`application/publish_product.py`)

**Input:**
- Product entity
- Category ID
- Picture URLs
- Shipping mode
- ML attributes

**Process:**
1. Build item payload:

```python
{
    "title": product.title,
    "category_id": category_id,
    "price": product.price,
    "currency_id": "BRL",
    "available_quantity": product.available_quantity,
    "buying_mode": "buy_it_now",
    "condition": product.condition,
    "listing_type_id": "gold_special" (or "free" if no pics),
    "description": {"plain_text": product.description},
    "pictures": [{"source": url}, ...],
    "attributes": ml_attributes,
    "shipping": {
        "mode": "me2",
        "free_shipping": True
    }
}
```

2. Normalize dimension attributes (add "cm" to numeric values)

**Output:** Complete item payload

---

### 8. Validation (`application/publish_product.py`)

**Input:** Item payload

**Process:**
1. POST to `/items/validate`
2. Check response for errors
3. If validation fails, log errors and skip item

**Output:** Validation result (valid/invalid)

---

### 9. Publication (`application/publish_product.py`)

**Input:** Validated item payload

**Process:**
1. POST to `/items`
2. Get published item ID
3. Log success

**Output:** Published item with MLB ID

---

## Complete Flow Example

### Input Excel Structure

| SKU | Título: informe... | Condição | Preço [R$] | Estoque | Título do livro | Autor | ISBN | Capa do livro | ... |
|-----|-------------------|----------|------------|---------|-----------------|-------|------|---------------|-----|
| 17515PETU | Meu Querido Pet | Novo | 10.00 | 1 | Meu Querido Pet | Editora Ridell | 6015211459404 | Mole | ... |

### Step-by-Step Transformation

1. **Header Detection:** Row 0 detected as header (contains "SKU", "Título", "Condição")

2. **Column Mapping:**
   ```python
   {
       "sku": "SKU",
       "title": "Título: informe o produto...",
       "condition": "Condição",
       "price": "Preço [R$]",
       "available_quantity": "Estoque",
       "fotos": "Fotos"
   }
   ```

3. **Product Entity:**
   ```python
   Product(
       sku="17515PETU",
       title="Meu Querido Pet",
       description="Meu Querido Pet",  # defaults to title
       price=10.00,
       available_quantity=1,
       condition="new",
       fiscal=FiscalData(...),
       attributes={
           "Título do livro": "Meu Querido Pet",
           "Autor": "Editora Ridell",
           "ISBN": "6015211459404",
           "Capa do livro": "Mole",
           ...
       }
   )
   ```

4. **Category Resolution:** "Livros Físicos" → "MLB437616"

5. **ML Attributes (via API):** BOOK_TITLE, AUTHOR, PUBLISHER, etc.

6. **Attribute Mapping:**
   - "Título do livro" → BOOK_TITLE
   - "Autor" → AUTHOR
   - "ISBN" → GTIN
   - "Capa do livro" → BOOK_COVER
   - ...

7. **Image Upload:** `/images/17515PETU/` → 7 picture URLs

8. **Shipping Mode:** "me2" + free_shipping=True

9. **Final Payload:**
   ```json
   {
     "title": "Meu Querido Pet",
     "category_id": "MLB437616",
     "price": 10.00,
     "shipping": {"mode": "me2", "free_shipping": true},
     "attributes": [
       {"id": "BOOK_TITLE", "value_name": "Meu Querido Pet"},
       {"id": "AUTHOR", "value_name": "Editora Ridell"},
       ...
     ],
     "pictures": [...]
   }
   ```

10. **Publication:** POST /items → MLB6206773772

---

## Key Files

| File | Purpose |
|------|---------|
| `main.py` | CLI entry point, wires dependencies |
| `adapters/spreadsheet/parser.py` | Parses Excel to Product entities |
| `adapters/spreadsheet/header_detector.py` | Detects header row, maps columns |
| `adapters/image_uploader.py` | Uploads images to ML |
| `domain/category/resolver.py` | Resolves category names to IDs |
| `domain/attribute_mapper.py` | Fuzzy maps Excel columns to ML attributes |
| `domain/shipping/resolver.py` | Determines available shipping modes |
| `application/publish_product.py` | Orchestrates publication use case |
| `api/client.py` | ML API client |

---

## Extension Points

To add support for new product types:

1. **New Attributes:** Add columns to Excel - automatically fuzzy-matched
2. **New Categories:** Pass category name via `--category` - dynamically resolved
3. **Custom Shipping:** Modify `ShippingResolver` for special cases
4. **Image Sources:** Extend `ImageUploader` for external URLs

The system is designed to be **category-agnostic** - any ML category works as long as the Excel columns match (fuzzy) the category's required attributes.
