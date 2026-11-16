import { apiFetch } from './client';

export interface AccNamed {
  id: string;
  name: string;
}

export interface AccEntry extends AccNamed {
  kind: 'folder' | 'item';
  file_type: string | null;
  supported: boolean;
}

const seg = encodeURIComponent;

export const fetchHubs = (): Promise<AccNamed[]> => apiFetch('/acc/hubs');

export const fetchProjects = (hubId: string): Promise<AccNamed[]> =>
  apiFetch(`/acc/hubs/${seg(hubId)}/projects`);

export const fetchTopFolders = (hubId: string, projectId: string): Promise<AccEntry[]> =>
  apiFetch(`/acc/hubs/${seg(hubId)}/projects/${seg(projectId)}/top-folders`);

export const fetchFolder = (projectId: string, folderId: string): Promise<AccEntry[]> =>
  apiFetch(`/acc/projects/${seg(projectId)}/folders/${seg(folderId)}`);
