import { MIXED_KEEP, type FieldShape } from './fieldDraft';

interface InputProps {
  f: FieldShape;
  value: string;
  onChange: (v: string) => void;
  /** Lote com valores diferentes entre as marcas: vazio = manter o de cada uma. */
  mixed?: boolean;
}

export function FieldInput({ f, value, onChange, mixed = false }: InputProps) {
  const id = `pv-${String(f.def_id)}`;
  const common = { id, value, onChange: (e: { target: { value: string } }) => { onChange(e.target.value); } };
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
      return <input type="date" {...common} {...placeholder} />;
    case 'number':
      return <input inputMode="decimal" placeholder={mixed ? MIXED_KEEP : 'Ex.: 12,5'} {...common} />;
    default:
      return <input {...common} {...placeholder} />;
  }
}
