import { useEffect, useState } from 'react';

/** O valor só muda depois de `delayMs` sem alterações (ex.: digitação na busca). */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => { setDebounced(value); }, delayMs);
    return () => { clearTimeout(timer); };
  }, [value, delayMs]);
  return debounced;
}
