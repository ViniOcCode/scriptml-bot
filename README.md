# Mercado Livre Bulk Upload 🚀

Upload em massa de produtos para o Mercado Livre via CLI.

## Instalação

```bash
# Clone o repositório
git clone https://github.com/vinicius/scriptml.git
cd scriptml

# Instale com uv (recomendado)
uv pip install -e ".[dev]"

# Ou com pip
pip install -e ".[dev]"
```

## Configuração

1. Crie uma aplicação em https://developers.mercadolivre.com.br/
2. Obtenha seu Client ID e Client Secret
3. Configure no arquivo `.env`:

```bash
MERCADO_LIVRE_CLIENT_ID=seu_client_id
MERCADO_LIVRE_CLIENT_SECRET=seu_client_secret
MERCADO_LIVRE_REDIRECT_URI=http://localhost:8000/callback
```

## Comandos

### Health Check
```bash
ml-upload doctor
```

### Validar Planilha
```bash
ml-upload validate -e planilha.xlsx -i pasta_imagens/ -c "Categoria"
```

### Publicar Produtos
```bash
# Modo dry-run (teste sem publicar)
ml-upload upload -e planilha.xlsx -i pasta_imagens/ -c "Categoria" -n

# Publicação real
ml-upload upload -e planilha.xlsx -i pasta_imagens/ -c "Categoria"
```

## Formato da Planilha

Colunas obrigatórias:
- `sku` - Identificador único do produto
- `title` - Título do produto
- `price` - Preço em Reais
- `condition` - novo ou usado

Colunas opcionais:
- `available_quantity` - Quantidade em estoque
- `description` - Descrição do produto
- `isbn` - ISBN para livros
- `ean` - Código de barras
- `ncm` - Código fiscal

## Estrutura de Imagens

```
pasta_imagens/
├── SKU1/           # Pasta com nome do SKU
│   ├── foto1.jpg
│   └── foto2.jpg
├── SKU2/
│   └── foto.jpg
```

## Arquitetura

```
mercadolivre_upload/
├── api/              # Clientes HTTP para API ML
├── adapters/         # Excel parser, image uploader
├── application/      # Casos de uso
├── domain/           # Entidades e regras de negócio
├── auth/             # OAuth e gerenciamento de tokens
├── cli/              # Interface de linha de comando
└── infrastructure/   # Cache, configurações
```

## Desenvolvimento

```bash
# Testes
pytest

# Formatação
black .

# Lint
ruff check .

# Type check
mypy .
```

## Tokens

Os tokens de autenticação são armazenados em:
- `tokens.json` - Tokens em formato JSON
- `tokens.json.enc` - Tokens criptografados (mais seguro)

## Licença

MIT
