import { createRoot } from 'react-dom/client'
import './hindsight.css'
import App from './App.tsx'

// NOTE: StrictMode intentionally disabled — the live knowledge graph runs an imperative
// requestAnimationFrame physics loop, and StrictMode's dev-only double-mount left a
// stale/detached loop that broke the verdict fly-to-focus. StrictMode is stripped in
// production anyway, so this only affects the dev double-invoke behaviour.
createRoot(document.getElementById('root')!).render(<App />)
