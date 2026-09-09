import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import 'leaflet/dist/leaflet.css'
import './styles.css'
import App from './App'
import ErrorBoundary from './components/ErrorBoundary'
import { applyTheme, readTheme } from './theme'

// Applied before the first paint so a reload never flashes the default
// palette before the operator's choice loads.
applyTheme(readTheme())

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <ErrorBoundary>
        <App />
      </ErrorBoundary>
    </BrowserRouter>
  </React.StrictMode>,
)
