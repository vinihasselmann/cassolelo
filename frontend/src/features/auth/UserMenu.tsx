import { ROLE_LABELS } from '../../api/users';
import { useCurrentUser } from '../dev-user/useCurrentUser';
import { useAuth } from './AuthContext';

/** Cabeçalho com login Microsoft: quem está logado, o papel e "Sair". */
export function UserMenu() {
  const auth = useAuth();
  const me = useCurrentUser();
  if (auth.mode !== 'microsoft') return null;
  return (
    <div className="dev-user">
      <span title={auth.email}>{me.data?.name ?? auth.name}</span>
      {me.data && (
        <span className="dev-user__role" data-testid="current-role">
          Papel: {ROLE_LABELS[me.data.role]}
        </span>
      )}
      <button type="button" className="ghost btn-sm" onClick={auth.signOut}>
        Sair
      </button>
    </div>
  );
}
