# Modelo de dados (inicial)

> Versão inicial. Será refinada na Fase 1.

- **users**(id, name, email, role, active)
- **obras**(id, code, name, acc_hub_id, acc_project_id, acc_folder_id, acc_item_id)
- **model_versions**(id, obra_id, acc_version_id, version_number, urn, status [pending|translating|processing|ready|failed|no_translation], published_by, published_at, comment, error)
- **elements**(id, version_id, external_id, dbid, mark_raw, category, props JSONB, mark_id)
- **marks**(id, obra_id, code, category, review_status, review_note)
- **param_defs**(id, name, type [text|number|list|date|bool], unit, options JSONB, required, categories JSONB, scope [global|obra], obra_id, active)
- **param_values**(id, mark_id, def_id, value JSONB, row_version, updated_by, updated_at)
- **orphans**(id, mark_id, since_version_id, status [open|relinked|archived], relinked_to)
- **audit_log**(id, entity, entity_id, action, before JSONB, after JSONB, user_id, batch_id, at)
- **webhook_events**(id, event_id, payload JSONB, received_at, processed_at)
