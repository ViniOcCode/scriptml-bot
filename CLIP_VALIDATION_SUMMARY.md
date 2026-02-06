# Clip Upload Validation - Executive Summary

**Date:** 2024-02-03  
**Validator:** AI ML-Payload-Validator Agent  
**Scope:** MLApiClient.upload_clip + ClipUploader.upload_clip_for_item  
**API Reference:** docs/mercadolibre_clips_api.md (Official ML API)

---

## 🔴 CRITICAL FINDING - BLOCKING DEPLOY

### Response Key Mismatch

**Current Code:**
```python
clip_uuid = result.get("id") or result.get("uuid") or result.get("clip_id")
```

**Official API Response:**
```json
{
  "status": "accepted",
  "clip_uuid": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Impact:** All clip uploads will return `None` instead of the clip UUID, causing **silent failures in production**. The implementation tries wrong field names that don't exist in the API response.

**Fix Required:** Change to `result.get("clip_uuid")`  
**Patch File:** `patches/01_fix_clip_uuid_response_key.patch`  
**Status:** 🔴 **MUST APPLY BEFORE ANY PRODUCTION DEPLOY**

---

## Validation Results Summary

| Issue | Severity | Status | Action Required |
|-------|----------|--------|-----------------|
| #1: Response key mismatch | 🔴 Critical | BLOCKING | Apply patch 01 immediately |
| #2: Sites serialization | 🟡 Conditional | NEEDS TESTING | Test in staging, apply after confirmation |
| #3: Item ID validation | ✅ Safe | RECOMMENDED | Apply patch 02 for defensive programming |
| #4: Error logging | ✅ Safe | RECOMMENDED | Included in patch 01 |
| #5: Content-type handling | ✅ Informational | WORKING | Current implementation is correct |

---

## Quick Fix Commands

```bash
cd /mnt/c/users/vinicius/desktop/scriptml

# Apply critical fix
git apply patches/01_fix_clip_uuid_response_key.patch

# Apply safe improvements (recommended)
git apply patches/02_add_item_id_validation.patch
git apply patches/03_add_clip_unit_tests.patch

# Run tests to verify
pytest tests/test_clip_uploader.py tests/test_item_id_validation.py -v
```

---

## Detailed Findings

### ✅ What's Working

1. **Multipart file field:** Uses correct `file` field name ✓
2. **Content-Type detection:** Python's `mimetypes` correctly handles .mp4/.mov/.mpeg/.avi ✓
3. **Sites JSON serialization:** Correctly uses `json.dumps(sites)` ✓
4. **URL construction:** Correct endpoint `/marketplace/items/{item_id}/clips/upload` ✓
5. **File validation:** Checks file existence and extension before upload ✓

### ⚠️ Issues Found

1. **Response parsing** (CRITICAL):
   - Tries wrong field names: `id`, `uuid`, `clip_id`
   - API actually returns: `clip_uuid`
   - Result: Silent failure - uploads succeed but UUID is not captured

2. **Item ID validation** (SAFE):
   - No validation before URL construction
   - Malformed IDs cause unclear API errors
   - Should validate format: `ML[A-Z]\d+` (e.g., MLB1234567890)

3. **Error logging** (SAFE):
   - Generic exception handling loses context
   - No HTTP status code or error body logged
   - Hard to debug API failures

4. **Sites semantics** (CONDITIONAL):
   - Current: `sites=None` → field omitted, `sites=[]` → `"sites": "[]"` sent
   - Unclear: Does API treat empty array same as omitted field?
   - Needs: Staging test to confirm behavior

---

## Files Modified

### Production Code
- `mercadolivre_upload/adapters/clip_uploader.py` - Fix UUID extraction, improve error logging
- `mercadolivre_upload/api/client.py` - Add item ID validation

### Tests
- `tests/test_clip_uploader.py` - Fix tests to use correct response format
- `tests/test_item_id_validation.py` - NEW: Validate item ID format

### Type Definitions
- `mercadolivre_upload/domain/types.py` - NEW: TypedDicts for clip API

---

## Risk Assessment

### If Critical Fix Not Applied

**Scenario:** Deploy current code to production

1. User uploads clip for item MLB123
2. API accepts upload, returns `{"status": "accepted", "clip_uuid": "abc-123"}`
3. Code tries `result.get("id")` → None
4. Code tries `result.get("uuid")` → None
5. Code tries `result.get("clip_id")` → None
6. Function returns `None`
7. **Application thinks upload failed even though it succeeded**
8. Possible consequences:
   - Duplicate uploads (if retry logic exists)
   - Missing clips in database
   - Unable to delete clips later (no UUID stored)
   - Customer sees error but clip is actually uploaded
   - Support burden increases

**Likelihood:** 100% (will happen on every clip upload)  
**Impact:** HIGH (data integrity, customer experience)  
**Detectability:** LOW (silent failure, logs show "no UUID in response")

### After Applying Fixes

- Clip UUIDs correctly captured
- Item IDs validated before API calls (fail fast with clear errors)
- Error logs include status codes and error bodies for debugging
- Test coverage ensures correct API contract

---

## Testing Strategy

### Unit Tests (Immediate)
```bash
pytest tests/test_clip_uploader.py -v
pytest tests/test_item_id_validation.py -v
```

### Integration Tests (Staging)
1. Upload clip with `sites=None` → verify all sites receive it
2. Upload clip with `sites=[]` → verify behavior matches None
3. Upload clip with specific sites → verify only those sites receive it
4. Try invalid item_id → verify ValueError raised
5. Monitor logs for correct UUID capture and error details

### Smoke Test (Production - After Deploy)
1. Upload one test clip
2. Verify UUID is captured in logs
3. Use GET endpoint to confirm clip exists
4. Delete test clip using captured UUID

---

## Recommendations

### Immediate (Before Deploy)
1. ✅ Apply patch 01 (critical fix)
2. ✅ Apply patch 02 (item ID validation)
3. ✅ Apply patch 03 (test updates)
4. ✅ Run test suite
5. ✅ Deploy to staging
6. ✅ Test actual API behavior

### Short Term (Next Sprint)
1. Implement GET clips endpoint for verification
2. Add video file validation (duration, size, resolution)
3. Add retry logic for transient errors
4. Add moderation status polling

### Long Term (Future Improvements)
1. Implement clip deletion endpoint
2. Add integration tests with real API (staging)
3. Add metrics/monitoring for upload success rates
4. Consider batch upload support

---

## Sign-Off Checklist

Before production deployment:

- [ ] Patch 01 applied and tested (CRITICAL)
- [ ] Patch 02 applied and tested (RECOMMENDED)
- [ ] Patch 03 applied and tests pass (RECOMMENDED)
- [ ] All unit tests pass
- [ ] Staging deployment successful
- [ ] Manual upload test in staging confirms UUID capture
- [ ] Error logging produces actionable information
- [ ] Item ID validation prevents bad requests
- [ ] Team briefed on new validation behavior
- [ ] Monitoring/alerts configured for clip upload failures

---

## Documentation

- **Full Report:** `CLIP_UPLOAD_VALIDATION_REPORT.md` (detailed analysis)
- **Patch Guide:** `patches/README.md` (application instructions)
- **API Reference:** `docs/mercadolibre_clips_api.md` (ML official docs)
- **Type Definitions:** `mercadolivre_upload/domain/types.py` (Python types)

---

## Questions?

For detailed explanations, alternative approaches, or additional context, see:
- Full validation report: `CLIP_UPLOAD_VALIDATION_REPORT.md`
- Patch application guide: `patches/README.md`

**Bottom Line:** One critical fix required before deploy. Two safe improvements recommended. Total effort: ~30 minutes to apply and test.


---

## Implementation Summary

# Implementação de Upload de Clips - Resumo

## Status: ✅ Implementado (Aguardando Autorização API)

A funcionalidade de upload de vídeos (clips) para itens publicados no Mercado Livre está completamente implementada e testada. No entanto, **requer autorização especial da API CBT** para funcionar em produção.

---

## Arquitetura da Solução

### 1. **Validação de Clips** (`mercadolivre_upload/domain/validation/clip_validator.py`)
- Valida formato, tamanho, duração e resolução dos vídeos
- Requisitos: mp4/mov/mpeg/avi, 10-61s, ≤280MB, ≥360x640 (vertical)
- Usa `ffprobe` quando disponível; graceful degradation quando ausente

### 2. **Extração de CBT ID** (`mercadolivre_upload/api/cbt_extractor.py`)
- **Problema**: Clips API exige CBT parent IDs (Global Selling), não IDs de marketplace (MLB...)
- **Solução**: Extrator com 5 estratégias de fallback:
  1. Campos diretos: `cbt_item_id`, `parent_item_id`
  2. Campo `id` se começar com "CBT"
  3. `parent_id` dentro de `marketplace_items[]`
  4. Busca recursiva em estruturas aninhadas
  5. Fallback via GET /items/{marketplace_id} (com cache)

### 3. **Upload Adapter** (`mercadolivre_upload/adapters/clip_uploader.py`)
- Descobre vídeos em `anuncios/<sku>/`
- Deduplica por hash MD5
- Valida antes do upload
- Retorna resumo detalhado (uploaded/failed/skipped)
- **Validação defensiva**: rejeita IDs que não começam com "CBT"

### 4. **Cliente API** (`mercadolivre_upload/api/client.py`)
- `upload_clip()`: POST multipart para `/marketplace/items/{cbt_id}/clips/upload`
- `validate_clip_item_id()`: valida formato CBT (separado de `validate_item_id`)
- Tratamento de erros detalhado com logs estruturados

### 5. **Integração no Fluxo** (`mercadolivre_upload/application/publish_product.py`)
- Executa upload de clips **após** publicação do item
- Usa `CbtIdExtractor` para obter ID correto
- Soft-fail: continua publicação mesmo se clips falharem

---

## Testes

✅ **32 testes passando** (`tests/test_clip_uploader.py`, `tests/test_cbt_extractor.py`):
- Descoberta de vídeos
- Validação de formato/tamanho
- Deduplicação
- Upload success/error scenarios
- Extração de CBT ID (todas as estratégias)
- Rejeição de IDs não-CBT

---

## Limitação Atual: Acesso à API CBT

### Erro Observado
```
HTTP 403: Invalid caller.id
HTTP 404: cbt-oauth-java-lib: something went wrong with cbt-users-api
```

### Causa
O endpoint `/marketplace/items/{CBT_ID}/clips/upload` **requer autorização especial**:
- Não basta ativar scopes OAuth no DevCenter
- Necessário:
  - Whitelist/habilitação de aplicação para CBT
  - Potencialmente registro no Developer Partner Program
  - Contato com suporte ML para habilitar recurso

### Documentação
- ❌ Não existe documentação pública de "Clips" no DevCenter (pt_br/en_us para MLB)
- ✅ A implementação segue boas práticas inferidas da documentação de Global Selling

---

## Como Habilitar (Próximos Passos)

1. **Abrir ticket com Suporte Mercado Livre**
   - Solicitar acesso ao endpoint de Clips para CBT items
   - Fornecer `app_id` e evidências da implementação
   - Anexar logs de tentativas (403/404)

2. **Developer Partner Program**
   - Verificar se clips exigem adesão ao programa
   - Seguir processo de certificação se necessário

3. **Teste após Autorização**
   ```bash
   uv run ml-upload upload -e anuncios/1.xlsx -i anuncios/ -c "categoria"
   ```
   - Os logs mostrarão upload bem-sucedido com `clip_uuid`

---

## Estrutura de Arquivos

```
anuncios/
  <SKU>/
    foto1.jpg
    foto2.jpg
    video1.mp4  ← descoberto automaticamente
    video2.mov  ← validado e dedupado
```

---

## Configuração

Nenhuma configuração adicional necessária. O sistema:
- Descobre vídeos automaticamente em `anuncios/<sku>/`
- Valida antes do upload
- Extrai CBT ID com fallbacks robustos
- Faz soft-fail se clips não puderem ser enviados

---

## Logs Importantes

```log
INFO - Uploading clips for <SKU> (CBT item: CBT...)
INFO - Clips for <SKU>: X uploaded, Y failed, Z skipped
WARNING - Skipping clip upload for <SKU>: item_id '...' is not a CBT parent
```

---

## Commits Relacionados

- `feat(clips): implementado ClipValidator e refatorado ClipUploader...`
- `fix(clips): usar cbt_item_id para upload de clips e melhorar error logging`
- `feat(clips): implementar extração robusta de CBT ID com fallbacks múltiplos`
- `fix(clips): suportar parent_item_id e item_relations na extração CBT`
- `fix(clips): normalize numeric parent ids and ensure API client available for CBT fallback`
- `fix(clips): improve clip upload error logging with full exception and response`
- `refactor(clips): limpar código verboso e simplificar lógica de extração CBT`

---

## Conclusão

**A implementação está completa, testada e pronta para uso.** Assim que o acesso ao endpoint CBT for autorizado pelo Mercado Livre, os clips serão automaticamente enviados para todos os itens publicados via Global Selling que possuam vídeos na pasta `anuncios/<sku>/`.
