import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import { fetchFolder, fetchHubs, fetchProjects, fetchTopFolders, type AccNamed } from '../../api/acc';
import { ApiError } from '../../api/client';

export interface AccSelection {
  hubId: string;
  projectId: string;
  folderId: string;
  itemId: string;
  itemName: string;
}

interface Props {
  onSelect: (selection: AccSelection) => void;
  selectedItemId?: string | undefined;
}

type Level = 'hubs' | 'projects' | 'top' | 'folder';

interface Row {
  kind: 'hub' | 'project' | 'folder' | 'item';
  id: string;
  name: string;
  supported: boolean;
}

const asRows = (kind: 'hub' | 'project', list: AccNamed[]): Row[] =>
  list.map((x) => ({ kind, id: x.id, name: x.name, supported: false }));

function forbiddenText(error: ApiError): string {
  return `Sem permissão para ver este conteúdo. ${error.message}`;
}

/** Navega hub › projeto › pastas › arquivo (.rvt, .nwd, .ifc) do Autodesk Docs. */
export function AccPicker({ onSelect, selectedItemId }: Props) {
  const [hub, setHub] = useState<AccNamed | null>(null);
  const [project, setProject] = useState<AccNamed | null>(null);
  const [folders, setFolders] = useState<AccNamed[]>([]);

  const level: Level = !hub ? 'hubs' : !project ? 'projects' : folders.length === 0 ? 'top' : 'folder';
  const folder = folders.at(-1);

  const query = useQuery<Row[]>({
    queryKey: ['acc', level, hub?.id, project?.id, folder?.id],
    queryFn: async () => {
      if (!hub) return asRows('hub', await fetchHubs());
      if (!project) return asRows('project', await fetchProjects(hub.id));
      const entries = folder
        ? await fetchFolder(project.id, folder.id)
        : await fetchTopFolders(hub.id, project.id);
      return entries.map((e) => ({ kind: e.kind, id: e.id, name: e.name, supported: e.supported }));
    },
    retry: false,
    staleTime: 60_000,
  });

  function open(row: Row) {
    if (row.kind === 'hub') setHub({ id: row.id, name: row.name });
    else if (row.kind === 'project') setProject({ id: row.id, name: row.name });
    else if (row.kind === 'folder') setFolders([...folders, { id: row.id, name: row.name }]);
    else if (hub && project && folder) {
      onSelect({
        hubId: hub.id,
        projectId: project.id,
        folderId: folder.id,
        itemId: row.id,
        itemName: row.name,
      });
    }
  }

  function goTo(depth: number) {
    // 0 = hubs, 1 = projetos do hub, 2 = pastas de topo, 3+ = pastas
    if (depth === 0) setHub(null);
    if (depth <= 1) setProject(null);
    setFolders(depth <= 2 ? [] : folders.slice(0, depth - 2));
  }

  const rows = query.data ?? [];
  const visible = rows.filter((r) => r.kind !== 'item' || r.supported);
  const hiddenFiles = rows.length - visible.length;

  const crumbs: string[] = ['Autodesk Docs'];
  if (hub) crumbs.push(hub.name);
  if (project) crumbs.push(project.name);
  folders.forEach((f) => crumbs.push(f.name));

  let message: string | null = null;
  if (query.isSuccess && visible.length === 0) {
    if (level === 'hubs') {
      message = 'Nenhum hub do ACC visível. Verifique se o app foi liberado em Custom Integrations.';
    } else if (level === 'projects') {
      message = 'Nenhum projeto neste hub.';
    } else if (rows.length === 0) {
      message = 'Esta pasta está vazia.';
    } else {
      message = 'Nenhum modelo .rvt, .nwd ou .ifc nesta pasta.';
    }
  }

  return (
    <div className="acc-picker">
      <nav aria-label="Caminho no Docs" className="acc-picker__crumbs">
        {crumbs.map((name, depth) =>
          depth < crumbs.length - 1 ? (
            <span key={`${depth}-${name}`}>
              <button type="button" className="link" onClick={() => { goTo(depth); }}>
                {name}
              </button>
              {' › '}
            </span>
          ) : (
            <strong key={`${depth}-${name}`}>{name}</strong>
          ),
        )}
      </nav>

      {query.isPending && <p className="muted">Carregando…</p>}
      {query.isError && (
        <p role="alert" className="error">
          {query.error instanceof ApiError && query.error.status === 403
            ? forbiddenText(query.error)
            : `Não foi possível carregar: ${query.error.message}`}
        </p>
      )}
      {message && <p className="muted">{message}</p>}

      {visible.length > 0 && (
        <ul className="acc-picker__list">
          {visible.map((row) => (
            <li key={row.id}>
              <button
                type="button"
                className={row.id === selectedItemId ? 'acc-picker__row is-selected' : 'acc-picker__row'}
                aria-pressed={row.kind === 'item' ? row.id === selectedItemId : undefined}
                onClick={() => { open(row); }}
              >
                <span aria-hidden="true">{row.kind === 'item' ? '📄' : '📁'}</span> {row.name}
              </button>
            </li>
          ))}
        </ul>
      )}
      {hiddenFiles > 0 && visible.length > 0 && (
        <p className="muted small">
          {hiddenFiles} arquivo(s) de outros formatos oculto(s). Só .rvt, .nwd e .ifc podem ser
          vinculados.
        </p>
      )}
    </div>
  );
}
