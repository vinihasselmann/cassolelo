import { useState } from 'react';

import { Logo } from '../../components/Logo';

interface Props {
  /** sem Microsoft configurado no servidor: undefined */
  onMicrosoft?: (() => Promise<void>) | undefined;
  /** só em dev */
  onDev?: (() => void) | undefined;
  /** mensagem do servidor (ex.: e-mail fora do domínio) */
  error?: string | undefined;
}

/** Tela de entrada: "Entrar com Microsoft" (e, em dev, o usuário simulado). */
export function LoginPage({ onMicrosoft, onDev, error }: Props) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  function microsoft() {
    if (!onMicrosoft) return;
    setBusy(true);
    setFailed(false);
    onMicrosoft().catch(() => {
      setBusy(false);
      setFailed(true);
    });
  }

  return (
    <main className="login">
      <div className="login__card">
        <Logo height={44} />
        <h1 className="login__title">Entrar</h1>
        {onMicrosoft ? (
          <>
            <p className="login__hint">Use sua conta corporativa Microsoft (e-mail da Cassol).</p>
            <button type="button" className="login__ms" onClick={microsoft} disabled={busy}>
              {busy ? 'Abrindo a Microsoft…' : 'Entrar com Microsoft'}
            </button>
          </>
        ) : (
          <p className="login__hint">
            O login ainda não foi configurado neste servidor. Avise a TI: faltam ENTRA_CLIENT_ID
            e ENTRA_TENANT_ID.
          </p>
        )}
        {import.meta.env.DEV && onDev && (
          <button type="button" className="secondary" onClick={onDev}>
            Usar usuário simulado (dev)
          </button>
        )}
        {(error ?? failed) && (
          <p role="alert" className="login__error">
            {error ?? 'Não foi possível abrir o login da Microsoft. Tente de novo.'}
          </p>
        )}
      </div>
    </main>
  );
}
