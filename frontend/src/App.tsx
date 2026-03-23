import { Routes, Route, Link, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Loader2, Upload as UploadIcon, Download } from 'lucide-react'
import { getActiveJobs } from './lib/api'
import HomePage from './pages/HomePage'
import UploadPage from './pages/UploadPage'
import DocumentsPage from './pages/DocumentsPage'
import ReviewPage from './pages/ReviewPage'
import AnalyticsPage from './pages/AnalyticsPage'

function NavLink({ to, children }: { to: string; children: React.ReactNode }) {
  const location = useLocation()
  const active = location.pathname === to || (to !== '/' && to !== '/upload' && to !== '/analytics' && location.pathname.startsWith(to))
  return (
    <Link
      to={to}
      className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
        active
          ? 'bg-blue-600 text-white'
          : 'text-gray-600 hover:bg-gray-100'
      }`}
    >
      {children}
    </Link>
  )
}

function ActiveJobsBar() {
  const { data: jobs } = useQuery({
    queryKey: ['active-jobs'],
    queryFn: getActiveJobs,
    refetchInterval: 3000,
  })

  if (!jobs || jobs.length === 0) return null

  const imports = jobs.filter(j => j.type === 'import')
  const exports = jobs.filter(j => j.type === 'export')

  return (
    <div className="bg-blue-600 text-white px-4 py-1.5 text-sm flex items-center gap-4">
      <Loader2 className="w-4 h-4 animate-spin shrink-0" />
      <div className="flex items-center gap-4">
        {imports.length > 0 && (
          <span className="flex items-center gap-1.5">
            <UploadIcon className="w-3.5 h-3.5" />
            {imports.length} import{imports.length > 1 ? 's' : ''} running
            {imports[0].filename && <span className="font-medium">{imports[0].filename}</span>}
            {imports[0].progress && <span className="opacity-75">— {imports[0].progress}</span>}
          </span>
        )}
        {exports.length > 0 && (
          <span className="flex items-center gap-1.5">
            <Download className="w-3.5 h-3.5" />
            {exports.length} export{exports.length > 1 ? 's' : ''} running
            {exports[0].filename && <span className="font-medium">{exports[0].filename}</span>}
            {exports[0].progress && <span className="opacity-75">— {exports[0].progress}</span>}
          </span>
        )}
      </div>
    </div>
  )
}

export default function App() {
  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200 sticky top-0 z-50">
        <div className="max-w-screen-2xl mx-auto px-4 py-3 flex items-center gap-6">
          <Link to="/" className="text-lg font-bold text-gray-900 hover:text-blue-600">AI Parse Feedback</Link>
          <nav className="flex gap-2">
            <NavLink to="/">Home</NavLink>
            <NavLink to="/upload">Upload</NavLink>
            <NavLink to="/documents">Documents</NavLink>
            <NavLink to="/analytics">Analytics</NavLink>
          </nav>
        </div>
        <ActiveJobsBar />
      </header>
      <main>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/upload" element={<UploadPage />} />
          <Route path="/documents" element={<DocumentsPage />} />
          <Route path="/review/:documentId" element={<ReviewPage />} />
          <Route path="/analytics" element={<AnalyticsPage />} />
        </Routes>
      </main>
    </div>
  )
}
