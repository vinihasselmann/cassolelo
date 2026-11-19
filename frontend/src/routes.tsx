import { Navigate, Route, Routes } from 'react-router-dom';

import { ModelPage } from './features/modelo/ModelPage';
import { IdentificationTab } from './features/obras/IdentificationTab';
import { ObraFileGate } from './features/obras/ObraBlocked';
import { ObraPage } from './features/obras/ObraPage';
import { ObrasPage } from './features/obras/ObrasPage';
import { VersionsTab } from './features/obras/VersionsTab';
import { UsersPage } from './features/usuarios/UsersPage';
import { Layout } from './Layout';

function NotFoundPage() {
  return <p>Página não encontrada.</p>;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/obras" replace />} />
        <Route path="obras" element={<ObrasPage />} />
        <Route path="obras/:obraId" element={<ObraPage />}>
          <Route index element={<Navigate to="versoes" replace />} />
          <Route path="versoes" element={<VersionsTab />} />
          <Route path="identificacao" element={<IdentificationTab />} />
        </Route>
        <Route
          path="obras/:obraId/modelo"
          element={
            <ObraFileGate>
              <ModelPage />
            </ObraFileGate>
          }
        />
        <Route path="usuarios" element={<UsersPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
