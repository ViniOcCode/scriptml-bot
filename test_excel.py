"""Test parsing the Excel file with Clean Architecture SpreadsheetParser."""

import pandas as pd

from mercadolivre_upload.adapters.spreadsheet.parser import SpreadsheetParser

print("=== Testing anuncios/teste.xlsx (Clean Architecture) ===")
print()

# First, show raw columns
print("Raw columns in file (first few rows):")
df = pd.read_excel("anuncios/teste.xlsx", header=None)
print(f"Shape: {df.shape}")
print("First 5 rows:")
for row_idx in range(min(5, len(df))):
    row_text = " ".join([str(x) for x in df.iloc[row_idx].dropna().tolist()])
    print(f"  Row {row_idx}: {row_text[:100]}...")
print()

# Try to parse with SpreadsheetParser
parser = SpreadsheetParser()
try:
    products = parser.parse("anuncios/teste.xlsx")
    print(f"[OK] Successfully parsed {len(products)} products")
    print()

    # Show column mapping
    print("Column mapping detected:")
    for canonical, actual in parser.column_mapping.items():
        print(f"  {canonical} -> {actual[:50]}...")
    print()

    # Show first 3 products
    print("First 3 products:")
    for p in products[:3]:
        print(f"  - {p.sku}: {p.title[:40]}... R${p.price} ({p.condition})")
        if p.attributes:
            print(f"    Attributes: {list(p.attributes.keys())[:5]}")
except Exception as e:
    print(f"[ERROR] {e}")
    import traceback
    traceback.print_exc()
    print()
    print("The SpreadsheetParser uses fuzzy matching to find columns.")
    print("It searches for keywords like 'Título', 'Preço', 'SKU', etc.")
