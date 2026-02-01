# PLANO DE PRODUÇÃO 10/10
## Mercado Livre Bulk Upload

**Objetivo:** Deixar o projeto pronto para produção com qualidade enterprise  
**Prazo estimado:** 4-6 semanas (1 desenvolvedor full-time)  
**Status atual:** 5.8/10  
**Meta:** 10/10  

---

## 📋 CRONOGRAMA POR FASES

### FASE 1: SEGURANÇA E INFRAESTRUTURA (Semana 1)
**Objetivo:** Eliminar vulnerabilidades críticas e estabelecer base segura

#### Dia 1-2: Segurança Imediata
- [ ] **REVOCAR credenciais expostas**
  - Acessar https://developers.mercadolibre.com.br/
  - Revogar CLIENT_ID/CLIENT_SECRET atual
  - Revogar access_token e refresh_token
  - Gerar novas credenciais
  
- [ ] **Limpar histórico do git**
  - Verificar se `.env` ou `tokens.json` já foram commitados
  - Se sim: usar `git filter-branch` ou BFG Repo-Cleaner
  - Forçar push para rewrite do histórico
  
- [ ] **Adicionar ao `.gitignore`:**
  ```
  .env
  .env.local
  .env.*.local
  tokens.json
  *.token
  secrets/
  credentials/
  ```

#### Dia 3-4: Proteção de Dados Sensíveis
- [ ] **Implementar criptografia para tokens**
  - Instalar: `pip install cryptography keyring`
  - Criar `mercadolivre_upload/auth/secure_storage.py`
  - Usar AES-256 para criptografar `tokens.json`
  - Chave derivada do sistema operacional (keyring) ou variável de ambiente
  - Criar backup de recuperação

- [ ] **Validação de paths (path traversal)**
  - Modificar `upload_image()` para validar caminho
  - Garantir que arquivo está dentro de `base_path`
  - Rejeitar paths com `..` ou absolutos não autorizados

#### Dia 5: Infraestrutura de Configuração
- [ ] **Reorganizar pyproject.toml completo:**
  ```toml
  [project]
  name = "mercado-livre-bulk-upload"
  version = "0.1.0"
  description = "Automated bulk product publication for Mercado Livre"
  readme = "README.md"
  requires-python = ">=3.13"
  license = {text = "MIT"}
  authors = [
      {name = "Seu Nome", email = "seu@email.com"}
  ]
  
  [project.optional-dependencies]
  dev = [
      "pytest>=7.4.0",
      "pytest-mock>=3.12.0",
      "pytest-cov>=4.1.0",
      "pytest-asyncio>=0.21.0",
      "black>=23.0.0",
      "ruff>=0.1.0",
      "mypy>=1.7.0",
      "pre-commit>=3.5.0",
      "safety>=2.3.0",
  ]
  
  [tool.black]
  line-length = 88
  target-version = ['py313']
  include = '\.pyi?$'
  
  [tool.ruff]
  line-length = 88
  select = [
      "E",   # pycodestyle errors
      "F",   # Pyflakes
      "W",   # pycodestyle warnings
      "I",   # isort
      "N",   # pep8-naming
      "D",   # pydocstyle
      "UP",  # pyupgrade
      "B",   # flake8-bugbear
      "C4",  # flake8-comprehensions
      "SIM", # flake8-simplify
  ]
  ignore = ["D100", "D104"]  # Module docstrings opcionais
  
  [tool.mypy]
  python_version = "3.13"
  strict = true
  warn_return_any = true
  warn_unused_ignores = true
  ignore_missing_imports = true
  show_error_codes = true
  
  [tool.pytest.ini_options]
  testpaths = ["tests"]
  python_files = ["test_*.py"]
  python_classes = ["Test*"]
  python_functions = ["test_*"]
  addopts = "--tb=short -v --cov=mercadolivre_upload --cov-report=term-missing"
  asyncio_mode = "auto"
  ```

- [ ] **Criar .github/workflows/ci.yml:**
  ```yaml
  name: CI/CD Pipeline
  
  on:
    push:
      branches: [main, develop]
    pull_request:
      branches: [main]
  
  jobs:
    lint-and-test:
      runs-on: ubuntu-latest
      strategy:
        matrix:
          python-version: ['3.13']
      
      steps:
        - uses: actions/checkout@v4
        
        - name: Set up Python
          uses: actions/setup-python@v5
          with:
            python-version: ${{ matrix.python-version }}
        
        - name: Install dependencies
          run: |
            pip install -e ".[dev]"
        
        - name: Check formatting with black
          run: black --check --diff .
        
        - name: Lint with ruff
          run: ruff check .
        
        - name: Type check with mypy
          run: mypy mercadolivre_upload/
        
        - name: Run tests with pytest
          run: pytest --cov=mercadolivre_upload --cov-report=xml
        
        - name: Upload coverage to Codecov
          uses: codecov/codecov-action@v3
          with:
            file: ./coverage.xml
            fail_ci_if_error: true
  
    security-scan:
      runs-on: ubuntu-latest
      steps:
        - uses: actions/checkout@v4
        - name: Run Safety CLI
          uses: pyupio/safety-action@v1
          with:
            api-key: ${{ secrets.SAFETY_API_KEY }}
  ```

---

### FASE 2: TESTES E QUALIDADE (Semanas 2-3)
**Objetivo:** Atingir 70%+ de cobertura de testes

#### Semana 2: Testes Core

**Dia 1-2: Setup de Testes**
- [ ] Criar estrutura de diretórios:
  ```
  tests/
  ├── __init__.py
  ├── conftest.py              # Fixtures compartilhadas
  ├── unit/
  │   ├── __init__.py
  │   ├── domain/
  │   │   ├── test_product.py
  │   │   ├── test_fiscal_data.py
  │   │   └── test_attribute_mapper.py
  │   ├── adapters/
  │   │   ├── test_spreadsheet_parser.py
  │   │   └── test_image_uploader.py
  │   └── application/
  │       ├── test_publish_product.py
  │       └── test_attribute_builder.py
  ├── integration/
  │   ├── __init__.py
  │   ├── test_api_client.py
  │   └── test_end_to_end.py
  └── fixtures/
      ├── sample_excel.xlsx
      ├── sample_images/
      └── mock_responses/
  ```

- [ ] Criar `conftest.py` com fixtures:
  - `mock_ml_api()` - Mock do cliente API
  - `sample_product()` - Produto de teste
  - `temp_excel_file()` - Arquivo Excel temporário
  - `mock_category_cache()` - Cache de categoria mockado

**Dia 3-5: Testes para publish_product.py**
- [ ] Testar `_build_attributes()` - mapeamento de atributos
- [ ] Testar `_publish_one()` - fluxo completo de publicação
  - Mock de todas as dependências
  - Testar caminho feliz
  - Testar falhas (API error, validação falha)
  - Testar retry
- [ ] Testar `_normalize_item_attributes()`
- [ ] Testar integração com FiscalService

**Meta:** 50% de cobertura no módulo `application/`

#### Semana 3: Testes Restantes

**Dia 1-2: Testes de Parser**
- [ ] `SpreadsheetParser.parse()` - diferentes formatos de Excel
- [ ] `HeaderDetector` - detecção de header
- [ ] `_parse_price()` - formatos brasileiros e americanos
- [ ] `_parse_condition()` - mapeamentos
- [ ] Testes de edge cases: planilha vazia, colunas faltando

**Dia 3-4: Testes de Domain**
- [ ] `FiscalData` - validações e transformações
- [ ] `FiscalService` - fluxo de submissão
- [ ] `AttributeMapper` - fuzzy matching
- [ ] `CachedAttributeMapper` - cache hits/misses
- [ ] Validadores (structural, scoring, sanitizer)

**Dia 5: Testes de Integração**
- [ ] Teste com API sandbox (se disponível)
- [ ] Teste de autenticação OAuth
- [ ] Teste de upload de imagem (mock server)

**Meta:** 70%+ cobertura total do projeto

---

### FASE 3: PERFORMANCE E ESCABILIDADE (Semana 4)
**Objetivo:** Reduzir tempo de processamento de 4h para ~25min (para 1.000 produtos)

#### Dia 1-2: Async/Await Base
- [ ] Converter `APIClient` para async:
  ```python
  class AsyncMLApiClient:
      def __init__(self):
          self.session = aiohttp.ClientSession()
      
      async def create_item(self, item: dict) -> dict:
          async with self.session.post(...) as resp:
              return await resp.json()
  ```

- [ ] Converter `ImageUploader` para async
- [ ] Criar `AsyncPublishProductUseCase`

#### Dia 3: Paralelização
- [ ] **Upload de imagens paralelo:**
  ```python
  async def upload_images_parallel(self, sku: str, max_concurrent: int = 5) -> list[str]:
      semaphore = asyncio.Semaphore(max_concurrent)
      async with semaphore:
          # Upload concurrently
  ```

- [ ] **Publicação de produtos em batch:**
  ```python
  async def publish_batch(self, products: list[Product], max_concurrent: int = 3):
      # Processar N produtos simultaneamente
      # Rate limiting respeitando API ML
  ```

#### Dia 4: Otimizações
- [ ] Substituir `SequenceMatcher` por `rapidfuzz` (10x mais rápido)
- [ ] Otimizar `DynamicExcelParser` - usar operações vetorizadas pandas
- [ ] Implementar cache em disco para categorias (com expiração)
- [ ] Adicionar memoização para `AttributeMapper`

#### Dia 5: Benchmarks
- [ ] Criar `benchmarks/` com scripts de performance
- [ ] Medir antes/depois das otimizações
- [ ] Documentar resultados

---

### FASE 4: REFATORAÇÃO E ARQUITETURA (Semana 5)
**Objetivo:** Melhorar manutenibilidade e separação de concerns

#### Dia 1-2: Quebrar PublishProductUseCase
- [ ] Extrair `AttributeBuilder`:
  ```python
  class AttributeBuilder:
      def build(self, product: Product, category_id: str) -> list[dict]:
          # Lógica de _build_attributes()
  ```

- [ ] Extrair `ItemBuilder`:
  ```python
  class ItemBuilder:
      def build(self, product: Product, attributes: list[dict]) -> dict:
          # Construir payload ML
  ```

- [ ] Extrair `ShippingResolver` (já existe, melhorar)
- [ ] Extrair `FiscalProcessor`:
  ```python
  class FiscalProcessor:
      def process(self, product: Product, item_id: str) -> bool:
          # Lógica de submissão fiscal
  ```

#### Dia 3: Consolidar Normalização de Texto
- [ ] Criar `mercadolivre_upload/utils/text.py`:
  ```python
  def normalize_column_name(name: str) -> str:
      """Normaliza nome de coluna para matching."""
      # Centralizar lógica usada em parser e mapper
  
  def sanitize_fiscal_value(value: str, field_type: str) -> str:
      """Sanitiza valores fiscais."""
      # Extrair número de origin_detail, etc
  ```

- [ ] Refatorar todos os módulos para usar funções centralizadas

#### Dia 4: Sistema de Plugins/Extensões
- [ ] Criar interface para `AttributeHandler`:
  ```python
  class AttributeHandler(Protocol):
      def can_handle(self, column: str) -> bool:
          ...
      def handle(self, value: Any) -> dict:
          ...
  ```

- [ ] Implementar handlers para casos especiais (fiscal, dimensões, etc)

#### Dia 5: Clean Up
- [ ] Remover código morto (pipeline.py se não usado)
- [ ] Consolidar exceções em `exceptions.py`
- [ ] Melhorar docstrings onde faltam

---

### FASE 5: UX E MONITORAMENTO (Semana 6)
**Objetivo:** Melhorar experiência do usuário e observabilidade

#### Dia 1: CLI Aprimorado
- [ ] Adicionar `tqdm` ou `rich` para barras de progresso
- [ ] Criar comando `doctor`:
  ```bash
  python -m mercadolivre_upload doctor
  # Verifica:
  # - Credenciais configuradas
  # - Conexão com API
  # - Permissões de diretórios
  # - Versões de dependências
  ```

- [ ] Adicionar `--output json` para automação:
  ```bash
  python -m mercadolivre_upload ... --output json > results.json
  ```

#### Dia 2: Logging e Observabilidade
- [ ] Implementar logging estruturado (JSON) para produção
- [ ] Adicionar correlation_id para tracing
- [ ] Criar `logs/` com rotação automática
- [ ] Integrar com Sentry para error tracking (opcional)

#### Dia 3: Validação Pré-publicação
- [ ] Criar `validate` command:
  ```bash
  python -m mercadolivre_upload validate --excel planilha.xlsx
  # Valida schema, tipos, ranges
  # Mostra preview do que será publicado
  # Lista erros encontrados
  ```

- [ ] Adicionar confirmação interativa:
  ```
  Serão publicados 150 produtos. Continuar? [y/N]
  ```

#### Dia 4: Documentação
- [ ] Atualizar README com:
  - Guia de instalação passo a passo
  - Configuração de credenciais
  - Exemplos de planilhas
  - Troubleshooting
- [ ] Criar `CONTRIBUTING.md` para desenvolvedores
- [ ] Criar `CHANGELOG.md`

#### Dia 5: Testes Finais e Release
- [ ] Rodar suite completa de testes
- [ ] Verificar cobertura >= 70%
- [ ] Teste end-to-end com planilha real
- [ ] Criar tag `v1.0.0`
- [ ] Deploy (se aplicável)

---

## 📊 MÉTRICAS DE SUCESSO

| Métrica | Atual | Meta | Como medir |
|---------|-------|------|------------|
| Cobertura de testes | ~15% | ≥70% | `pytest --cov` |
| Tempo (1.000 produtos) | ~4h | ≤30min | Benchmark script |
| Vulnerabilidades | 3 críticas | 0 | Safety scan |
| Erros de tipo | ? | 0 | `mypy --strict` |
| Warnings de lint | ? | 0 | `ruff check` |
| CI/CD pass rate | 0% | 100% | GitHub Actions |

---

## 🛠️ FERRAMENTAS RECOMENDADAS

### Desenvolvimento
- **IDE:** VS Code ou PyCharm
- **Formatador:** Black
- **Linter:** Ruff (substitui flake8, isort, pydocstyle)
- **Type Checker:** mypy (strict mode)
- **Testes:** pytest + pytest-asyncio + pytest-cov
- **Pre-commit:** pre-commit hooks

### CI/CD
- **GitHub Actions:** Automatização de testes
- **Codecov:** Relatórios de cobertura
- **Safety:** Scan de vulnerabilidades em dependências

### Performance
- **Benchmark:** pytest-benchmark
- **Profiling:** py-spot ou cProfile
- **Async:** asyncio + aiohttp

---

## ⚠️ RISCOS E MITIGAÇÕES

| Risco | Probabilidade | Impacto | Mitigação |
|-------|--------------|---------|-----------|
| Refatoração quebra funcionalidade | Média | Alto | Testes completos antes |
| API ML muda comportamento | Baixa | Alto | Testes de integração, mocks |
| Performance não atinge meta | Média | Médio | Benchmarks incrementais |
| Credenciais vazam novamente | Baixa | Crítico | Pre-commit hooks, validação |

---

## ✅ CHECKLIST PRÉ-PRODUÇÃO

Antes de deployar para produção:

- [ ] Todas as credenciais antigas revogadas
- [ ] `.env` nunca commitado
- [ ] CI/CD passando (verde)
- [ ] Cobertura ≥ 70%
- [ ] mypy sem erros
- [ ] ruff sem warnings
- [ ] Testes de integração passando
- [ ] Benchmark de performance aceitável
- [ ] Documentação atualizada
- [ ] Changelog criado
- [ ] Tag de release criada
- [ ] Rollback plan documentado

---

## 🎯 RESULTADO ESPERADO

Após execução deste plano, o projeto terá:

✅ **Segurança:** Zero vulnerabilidades críticas, dados criptografados  
✅ **Qualidade:** 70%+ cobertura, CI/CD automatizado, código padronizado  
✅ **Performance:** 9x mais rápido, async/await, paralelização  
✅ **Manutenibilidade:** Arquitetura limpa, bem testado, documentado  
✅ **UX:** CLI amigável, progresso visível, erros claros  

**Score final estimado: 9.5/10** 🚀

---

**Próximo passo:** Definir qual fase começar primeiro.
