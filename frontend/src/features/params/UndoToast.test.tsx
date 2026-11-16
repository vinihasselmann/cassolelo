import { act, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { installFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';
import { UNDO_SECONDS, UndoToast } from './UndoToast';

describe('UndoToast', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('o "Desfazer" fica 10 s na tela e some sozinho', () => {
    vi.useFakeTimers();
    installFakeApi({});
    const onClose = vi.fn();
    renderWithProviders(<UndoToast batchId="b-1" text="Valores aplicados a 10 marcas." onClose={onClose} />);
    expect(screen.getByRole('status')).toHaveTextContent('Valores aplicados a 10 marcas.Desfazer');
    act(() => { vi.advanceTimersByTime((UNDO_SECONDS - 1) * 1000); });
    expect(onClose).not.toHaveBeenCalled();
    act(() => { vi.advanceTimersByTime(1000); });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
