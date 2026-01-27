"""Test parsing the Excel file."""
import pandas as pd
from mercadolivre_upload.parser import ExcelParser

print("=== Testing anuncios/teste.xlsx ===")
print()

# First, show the columns
print("Columns in file:")
df = pd.read_excel("anuncios/teste.xlsx")
for i, col in enumerate(df.columns):
    print(f"  {i}: {col[:50]}...")
print()

# Try to parse
parser = ExcelParser()
try:
    products = parser.parse("anuncios/teste.xlsx")
    print(f"✓ Successfully parsed {len(products)} products")
    for p in products[:3]:
        print(f"  - {p.sku}: {p.title[:40]}... R${p.price} ({p.condition})")
except Exception as e:
    print(f"✗ Error: {e}")
    print()
    print("The parser expects these columns (or Portuguese equivalents):")
    print("  - sku, titulo/título, descricao/descrição")
    print("  - preco/preço, estoque, condicao/condição")
    print("  - ncm, cfop, origin/origem, cest (fiscal)")
