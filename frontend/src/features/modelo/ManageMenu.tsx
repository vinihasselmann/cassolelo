interface Props {
  /** "N parâmetros no catálogo…" (ou o erro / carregando). */
  summary: string;
  canEditParams: boolean;
  onNewParam: () => void;
  onCatalog: () => void;
  onMarkOrphans: () => void;
  onUnitOrphans: () => void;
}

/**
 * Gestão da obra (parâmetros e órfãs) no topo da coluna esquerda, sempre à mostra
 * (2026-11-18: o "Gerenciar" que recolhia estas ações saiu, a pedido do usuário).
 */
export function ManageMenu({ summary, canEditParams, onNewParam, onCatalog, onMarkOrphans, onUnitOrphans }: Props) {
  return (
    <div className="model-sec manage">
      <p className="hint params-count">{summary}</p>
      <div className="manage__list">
        {canEditParams && (
          <button type="button" className="list-item" onClick={onNewParam}>
            + Novo parâmetro
          </button>
        )}
        <button type="button" className="list-item" onClick={onCatalog}>
          Catálogo
        </button>
        <button type="button" className="list-item" onClick={onMarkOrphans}>
          Marcas órfãs
        </button>
        <button type="button" className="list-item" onClick={onUnitOrphans}>
          Peças órfãs
        </button>
      </div>
    </div>
  );
}
