import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { HashRouter } from 'react-router-dom'
import App from './App'
import { DemoProvider } from './components/Demo'
import { ProfileProvider } from './context/Profile'
import { SessionProvider } from './context/Session'
import '@fontsource-variable/geist/wght.css'
import '@fontsource-variable/geist-mono/wght.css'
import './styles/twin3d.css'
import './styles/tokens.css'
import './styles/app.css'

const client = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } })

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={client}>
      <HashRouter>
        <ProfileProvider>
          <SessionProvider>
            <DemoProvider>
              <App />
            </DemoProvider>
          </SessionProvider>
        </ProfileProvider>
      </HashRouter>
    </QueryClientProvider>
  </StrictMode>,
)
