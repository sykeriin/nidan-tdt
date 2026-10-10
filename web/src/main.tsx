import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { HashRouter } from 'react-router-dom'
import App from './App'
import { SessionProvider } from './context/Session'
import './styles/twin3d.css'
import './styles/app.css'

const client = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } })

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={client}>
      <HashRouter>
        <SessionProvider>
          <App />
        </SessionProvider>
      </HashRouter>
    </QueryClientProvider>
  </StrictMode>,
)
