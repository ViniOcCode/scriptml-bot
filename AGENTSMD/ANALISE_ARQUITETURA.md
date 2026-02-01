# Relatório de Análise de Arquitetura e Código
## Mercado Livre Bulk Upload

**Data da análise:** 2025-02-01

---

## 1. Visão Geral da Arquitetura

O projeto segue uma arquitetura em camadas inspirada em **Clean Architecture**, com separação clara entre:

```
mercadolivre_upload/
├── adapters/          # Camada de adaptadores (entrada/saída)
├── api/               # Clientes de API externos
├── application/       # Casos de uso (orquestração)
├── auth/              # Autenticação (OAuth, tokens)
├── domain/            # Regras de negócio puras
│   ├── category/
│   ├── fiscal/
│   ├── product/
│   ├── shipping/
│   └── validation/
├── infrastructure/    # Cache, persistência
└── parser/            # Parsing de entrada (Excel)
```

---

## 2. Análise por Critérios

### 2.1 Clean Architecture ⭐⭐⭐⭐☆

**Pontos Positivos:**
- ✅ Separação clara entre camadas (domain, application, adapters, infrastructure)
- ✅ Domain layer independente de frameworks externos
- ✅ Uso de Protocolos (Ports) para dependências externas
- ✅ Dependências apontam para dentro (regra de dependência)

**Problemas Encontrados:**

| Arquivo | Linha | Severidade | Problema |
|---------|-------|------------|----------|
| `application/publish_product.py` | 1-50 | **Média** | Use case muito grande (~550 linhas), viola SRP |
| `pipeline.py` | 20-25 | **Baixa** | Importa de `auth.manager` que não existe (código quebrado) |
| `parser/dynamic_parser.py` | 1-30 | **Baixa** | Pertence à camada de adapters, mas está em pasta separada |

**Sugestão:** Dividir `PublishProductUseCase` em serviços menores (AttributeBuilder, ItemBuilder, Publisher)

---

### 2.2 Princípios SOLID

#### Single Responsibility Principle (SRP)

| Severidade | Problema | Local |
|------------|----------|-------|
| **Alta** | `PublishProductUseCase` tem múltiplas responsabilidades: orquestração, build de atributos, build de shipping, publicação, fiscal | `application/publish_product.py` |
| **Média** | `DynamicExcelParser` faz parsing E mapeamento de colunas E extração de atributos | `parser/dynamic_parser.py` |
| **Média** | `MLApiClient` mistura operações de itens, imagens E fiscal | `api/client.py` |

**Exemplo de violação:**
```python
# publish_product.py - método _publish_one() tem ~200 linhas
def _publish_one(self, product: Product, category_id: str) -> bool:
    # 1. Build attributes
    # 2. Upload images
    # 3. Build shipping config
    # 4. Build item payload
    # 5. Validate
    # 6. Publish
    # 7. Queue fiscal data
```

#### Open/Closed Principle (OCP)

| Severidade | Problema | Local |
|------------|----------|-------|
| **Média** | `AttributeMapper` usa if/else para tipos de valores (list, number_unit, string) - difícil estender | `domain/attribute_mapper.py` |

#### Liskov Substitution Principle (LSP)

✅ **Bem aplicado:** Uso de Protocols permite substituição de implementações

#### Interface Segregation Principle (ISP)

| Severidade | Problema | Local |
|------------|----------|-------|
| **Baixa** | `ItemPublisherPort` combina validação e publicação - poderia separar | `application/publish_product.py` |

#### Dependency Inversion Principle (DIP)

✅ **Bem aplicado:**
- Domain depende de abstrações (Protocols)
- Injeção de dependências no construtor

---

### 2.3 Code Smells

#### Métodos/Funções Longas

| Arquivo | Método | Linhas | Severidade |
|---------|--------|--------|------------|
| `publish_product.py` | `_publish_one` | ~180 | **Alta** |
| `publish_product.py` | `_build_attributes` | ~120 | **Alta** |
| `publish_product.py` | `execute` | ~80 | **Média** |
| `fiscal/service.py` | `submit_fiscal_data_workflow` | ~100 | **Média** |
| `dynamic_parser.py` | `parse` | ~60 | **Média** |

#### Classes Grandes

| Arquivo | Classe | Linhas | Responsabilidades | Severidade |
|---------|--------|--------|-------------------|------------|
| `publish_product.py` | `PublishProductUseCase` | ~550 | 7+ | **Alta** |
| `fiscal/service.py` | `FiscalService` | ~400 | 5+ | **Média** |
| `dynamic_parser.py` | `DynamicExcelParser` | ~300 | 4+ | **Média** |

#### Duplicação de Código

| Severidade | Problema | Localização |
|------------|----------|-------------|
| **Média** | Normalização de texto duplicada em `category/resolver.py` e `attribute_mapper.py` | `normalize_text()`, `similarity()` |
| **Média** | Lógica de retry duplicada (embora encapsulada, poderia ser um decorator) | `fiscal/service.py` |
| **Baixa** | Parsing de preço/quantidade similar em `dynamic_parser.py` | `_parse_price()`, `_parse_quantity()` |

#### God Class / God Method

```python
# PROBLEMA: PublishProductUseCase faz tudo
class PublishProductUseCase:
    # 13 parâmetros no __init__
    def __init__(self, category_resolver, publisher, image_uploader, 
                 shipping_resolver, fiscal_service, config, dry_run, ...):
        ...
    
    # Método com 7 etapas diferentes
    def _build_attributes(self, ...):
        # 1. Get metadata
        # 2. Cache mapping
        # 3. Fuzzy mapping
        # 4. Structural validation
        # 5. Semantic scoring
        # 6. Sanitization
        # 7. Conditional attributes
```

---

### 2.4 Dependências

#### Ciclos de Dependência

✅ **Nenhum ciclo detectado** - A estrutura de imports está correta

#### Acoplamento Excessivo

| Arquivo | Severidade | Problema |
|---------|------------|----------|
| `publish_product.py` | **Alta** | Depende de 5+ serviços externos |
| `main.py` | **Média** | Wiring manual de muitas dependências |

**Sugestão:** Usar um container de injeção de dependências ou factory pattern

---

### 2.5 Tratamento de Erros

**Pontos Positivos:**
- ✅ Hierarquia de exceções bem definida (`auth/exceptions.py`)
- ✅ Exceções específicas do domínio (`OAuthError`, `TokenExpiredError`)
- ✅ Retry logic com exponential backoff (`fiscal/service.py`)

**Problemas Encontrados:**

| Arquivo | Linha | Severidade | Problema |
|---------|-------|------------|----------|
| `api/client.py` | 40-50 | **Alta** | `response.raise_for_status()` expõe detalhes de HTTP para camada de domínio |
| `publish_product.py` | 200+ | **Média** | Múltiplos try/except aninhados, código difícil de seguir |
| `publish_product.py` | 150-160 | **Média** | `hasattr(e, 'response')` - verificação frágil |
| `category/resolver.py` | 45-50 | **Baixa** | Silencia exceções em `get_conditional_attributes` |

**Exemplo de problema:**
```python
# Código frágil - assume estrutura específica da exceção
try:
    result = self.publisher.create_item(item)
except Exception as e:
    error_msg = str(e)
    if hasattr(e, 'response') and e.response is not None:  # FRÁGIL
        try:
            error_detail = e.response.json()
        ...
```

---

### 2.6 Logging

**Pontos Positivos:**
- ✅ Uso consistente de `logging.getLogger(__name__)`
- ✅ Níveis de log apropriados (debug, info, warning, error)
- ✅ Contexto rico nas mensagens (SKU, item_id)

**Problemas Encontrados:**

| Arquivo | Linha | Severidade | Problema |
|---------|-------|------------|----------|
| `publish_product.py` | Vários | **Baixa** | Log muito verboso em nível INFO (flood de logs) |
| `dynamic_parser.py` | 45 | **Baixa** | `logger.debug` dentro de loop pode ser custoso |
| `fiscal/service.py` | 80 | **Baixa** | Faltam logs em caso de retry bem-sucedido |

**Sugestões:**
1. Reduzir verbosidade de logs de mapeamento de atributos para DEBUG
2. Adicionar log rotation para arquivos grandes
3. Usar structured logging (JSON) para facilitar análise

---

## 3. Resumo de Problemas

### Severidade Alta 🔴

1. **`PublishProductUseCase` muito grande** (~550 linhas)
   - **Impacto:** Difícil manutenção, testes complexos
   - **Solução:** Extrair builders (ItemBuilder, AttributeBuilder)

2. **Método `_publish_one` excessivamente longo** (~180 linhas)
   - **Impacto:** Complexidade ciclomática alta
   - **Solução:** Dividir em métodos privados menores

3. **Exposição de HTTP para domínio** (`api/client.py`)
   - **Impacto:** Acoplamento com requests
   - **Solução:** Criar exceções de domínio (ApiError, ValidationError)

### Severidade Média 🟡

1. **Duplicação de normalização de texto**
   - **Local:** `category/resolver.py` e `attribute_mapper.py`
   - **Solução:** Criar módulo `domain/text_utils.py`

2. **`DynamicExcelParser` com múltiplas responsabilidades**
   - **Solução:** Separar HeaderDetector em classe própria

3. **Wiring manual complexo em `main.py`**
   - **Solução:** Usar factory ou container DI

### Severidade Baixa 🟢

1. Imports quebrados em `pipeline.py` (`auth.manager`)
2. Logs verbosos demais
3. Verificações frágeis com `hasattr`

---

## 4. Sugestões de Melhoria

### Arquitetura

```python
# ANTES: PublishProductUseCase gigante
class PublishProductUseCase:
    def _publish_one(self, product, category_id):
        # 180 linhas de código...

# DEPOIS: Separação em serviços especializados
class PublishProductUseCase:
    def __init__(self, item_builder: ItemBuilder, 
                 attribute_builder: AttributeBuilder,
                 publisher: ItemPublisher):
        ...

class AttributeBuilder:
    def build(self, product, category_id) -> list[dict]:
        ...

class ItemBuilder:
    def build(self, product, attributes, pictures) -> dict:
        ...
```

### Padrões Sugeridos

1. **Builder Pattern** para construção de itens ML
2. **Strategy Pattern** para diferentes tipos de mapeamento de atributos
3. **Decorator Pattern** para retry logic (reusável)

### Testes

- ✅ Boa cobertura de testes em `test_auth.py`
- ⚠️ Faltam testes para `publish_product.py` (complexidade dificulta)
- ⚠️ Faltam testes de integração para `fiscal/service.py`

---

## 5. Métricas

| Métrica | Valor | Status |
|---------|-------|--------|
| Total de arquivos Python | 35+ | - |
| Linhas de código (estimado) | ~4000 | - |
| Média de linhas por classe | ~80 | ⚠️ |
| Métodos > 50 linhas | 5 | 🔴 |
| Classes > 300 linhas | 3 | 🔴 |
| Duplicação de código | ~5% | 🟡 |
| Cobertura de testes (estimada) | ~30% | 🟡 |

---

## 6. Conclusão

O projeto demonstra **boa compreensão de Clean Architecture** com separação adequada de camadas e uso correto de Ports e Adapters. No entanto, há **problemas significativos de tamanho de classes/métodos** que dificultam manutenção e testes.

### Pontos Fortes 💪
- Arquitetura em camadas bem definida
- Uso adequado de Protocols para inversão de dependência
- Boa estrutura de exceções customizadas
- Logging consistente

### Pontos de Atenção ⚠️
- Classes e métodos excessivamente grandes
- Complexidade ciclomática elevada em casos de uso
- Algumas verificações frágeis no tratamento de erros

### Prioridade de Correções
1. 🔴 Refatorar `PublishProductUseCase` (dividir em serviços menores)
2. 🟡 Criar abstração para erros de API
3. 🟡 Extrair código duplicado de normalização de texto
4. 🟢 Corrigir imports quebrados em `pipeline.py`
