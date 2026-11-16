import { useId } from 'react';

/** Cores da marca Cassol Elo (logotipo oficial). */
export const BRAND_ORANGE = '#F2A31B';
export const BRAND_GRAPHITE = '#3C3C3C';

interface Props {
  /** altura em px (a largura acompanha a proporção) */
  height?: number;
  className?: string;
}

/**
 * Logotipo "ELO CASSOL": dois quadrados que se encaixam (o elo) + o nome.
 * Vetorial (nítido em qualquer tela) e com fundo transparente: vai sobre fundo claro.
 */
export function Logo({ height = 40, className }: Props) {
  const id = useId().replace(/:/g, '');
  const left = `${id}-l`;
  const right = `${id}-r`;
  return (
    <svg
      className={className}
      role="img"
      aria-label="Cassol Elo"
      viewBox="0 0 1000 240"
      height={height}
      width={(height * 1000) / 240}
    >
      <defs>
        {/* recorte de cada quadrado: o círculo + a passagem até a borda do meio */}
        <mask id={left}>
          <rect width="240" height="240" fill="#fff" />
          <circle cx="120" cy="120" r="67" fill="#000" />
          <rect x="175" y="91" width="66" height="57" fill="#000" />
        </mask>
        <mask id={right}>
          <rect x="254" width="240" height="240" fill="#fff" />
          <circle cx="374" cy="120" r="67" fill="#000" />
          <rect x="253" y="91" width="66" height="57" fill="#000" />
        </mask>
      </defs>
      <rect width="240" height="240" fill={BRAND_ORANGE} mask={`url(#${left})`} />
      <rect x="254" width="240" height="240" fill={BRAND_GRAPHITE} mask={`url(#${right})`} />
      <text
        x="580"
        y="152"
        fill={BRAND_GRAPHITE}
        fontFamily="'Arial Black', 'Segoe UI Black', 'Helvetica Neue', Arial, sans-serif"
        fontWeight="900"
        fontSize="200"
        textLength="418"
        lengthAdjust="spacingAndGlyphs"
      >
        ELO
      </text>
      <text
        x="568"
        y="235"
        fill={BRAND_ORANGE}
        fontFamily="'Arial Black', 'Segoe UI Black', 'Helvetica Neue', Arial, sans-serif"
        fontWeight="900"
        fontSize="62"
        textLength="360"
        lengthAdjust="spacing"
      >
        CASSOL
      </text>
    </svg>
  );
}
