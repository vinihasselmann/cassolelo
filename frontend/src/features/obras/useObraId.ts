import { useParams } from 'react-router-dom';

/** Id numérico da obra na rota /obras/:obraId. */
export function useObraId(): number {
  const { obraId } = useParams();
  return Number(obraId);
}
