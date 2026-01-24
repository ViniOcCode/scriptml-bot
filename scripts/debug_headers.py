import json
import openpyxl
import pandas as pd
import unicodedata, re

def normalize(s):
    if s is None:
        return ''
    s = str(s)
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', s).strip()

cfg = json.load(open('config/livros_info.json', 'r', encoding='utf-8'))
wb = openpyxl.load_workbook('TESTE_ANUNCIOS/anunciar.xlsx', data_only=True)
sheet_name = None
for name in wb.sheetnames:
    if 'livros' in name.lower() and 'fis' in name.lower():
        sheet_name = name
        break
if sheet_name is None:
    sheet_name = cfg.get('sheet_name')

header_row_idx = cfg.get('header_row', 2) - 1
print('Using sheet:', sheet_name)
print('Header row (0-based):', header_row_idx)

df = pd.read_excel('TESTE_ANUNCIOS/anunciar.xlsx', sheet_name=sheet_name, header=header_row_idx, engine='openpyxl')
print('\nRaw columns:')
for i, c in enumerate(df.columns, start=1):
    print(i, repr(c))

print('\nNormalized columns:')
for i, c in enumerate(df.columns, start=1):
    print(i, normalize(c))
