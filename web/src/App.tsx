import { Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import About from './pages/About'
import Alerts from './pages/Alerts'
import DataHealth from './pages/DataHealth'
import FieldData from './pages/FieldData'
import ImportPage from './pages/Import'
import Modules from './pages/Modules'
import Overview from './pages/Overview'
import Records from './pages/Records'
import Reports from './pages/Reports'
import SelfTest from './pages/SelfTest'
import Temps from './pages/Temps'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Overview />} />
        <Route path="records" element={<Records />} />
        <Route path="temps" element={<Temps />} />
        <Route path="modules" element={<Modules />} />
        <Route path="alerts" element={<Alerts />} />
        <Route path="import" element={<ImportPage />} />
        <Route path="data-health" element={<DataHealth />} />
        <Route path="field-data" element={<FieldData />} />
        <Route path="self-test" element={<SelfTest />} />
        <Route path="reports" element={<Reports />} />
        <Route path="about" element={<About />} />
        <Route path="*" element={<About />} />
      </Route>
    </Routes>
  )
}
