import type { Ref } from 'react';

import { MIXED_KEEP, type FieldShape } from './fieldDraft';

interface InputProps {
  f: FieldShape;
  value: string;
  onChange: (v: string) => void;
  /** Lote com valores diferentes entre as marcas: vazio = manter o de cada uma. */
  mixed?: boolean;
  /** Campo sem <label> visível (célula da tabela por peça): id e nome acessível próprios. */
  id?: string;
  ariaLabel?: string;
  autoFocus?: boolean;
  onBlur?: () => void;
  onKeyDown?: (e: { key: string; preventDefault: () => void }) => void;
  /** Mensagem de erro do campo (ex.: data inválida), mostrada abaixo dele. */
  error?: string | null | undefined;
  inputRef?: Ref<HTMLInputElement> | undefined;
}

export function FieldInput({ error, inputRef, ...props }: InputProps) {
  const errId = `${props.id ?? `pv-${String(props.f.def_id)}`}-err`;
  const control = <Control {...props} inputRef={inputRef} errId={error ? errId : undefined} />;
  if (!error) return control;
  return (
    <>
      {control}
      <p id={errId} role="alert" className="error small field-error">
        {error}
      </p>
    </>
  );
}

function Control({
  f,
  value,
  onChange,
  mixed = false,
  id,
  ariaLabel,
  autoFocus,
  onBlur,
  onKeyDown,
  inputRef,
  errId,
}: Omit<InputProps, 'error'> & { errId: string | undefined }) {
  const common = {
    id: id ?? `pv-${String(f.def_id)}`,
    value,
    onChange: (e: { target: { value: string } }) => { onChange(e.target.value); },
    ...(errId ? { 'aria-invalid': true, 'aria-describedby': errId } : {}),
    ...(ariaLabel ? { 'aria-label': ariaLabel } : {}),
    ...(autoFocus ? { autoFocus } : {}),
    ...(onBlur ? { onBlur } : {}),
    ...(onKeyDown ? { onKeyDown } : {}),
  };
  const empty = mixed ? MIXED_KEEP : '—';
  const placeholder = mixed ? { placeholder: MIXED_KEEP } : {};
  switch (f.type) {
    case 'list':
      return (
        <select {...common}>
          <option value="">{empty}</option>
          {f.options?.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      );
    case 'bool':
      return (
        <select {...common}>
          <option value="">{empty}</option>
          <option value="true">Sim</option>
          <option value="false">Não</option>
        </select>
      );
    case 'date':
      return <input type="date" ref={inputRef} {...common} {...placeholder} />;
    case 'number':
      return <input inputMode="decimal" placeholder={mixed ? MIXED_KEEP : 'Ex.: 12,5'} {...common} />;
    default:
      return <input {...common} {...placeholder} />;
  }
}
