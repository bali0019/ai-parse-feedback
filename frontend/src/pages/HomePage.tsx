import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { FolderOpen, FileText, AlertCircle, CheckCircle2, Loader2, Upload, Search, MousePointerClick, Download, BarChart3, PackageOpen, ChevronRight } from 'lucide-react'
import { listUseCases, startImport, getImportStatus } from '../lib/api'
import type { UseCaseSummary } from '../lib/types'

const STEPS = [
  { icon: Upload, title: 'Upload', desc: 'Upload PDFs tagged to a use case' },
  { icon: Search, title: 'Parse', desc: 'ai_parse_document extracts text, tables, and bounding boxes' },
  { icon: MousePointerClick, title: 'Review', desc: 'Page-by-page view with color-coded bbox overlays — click to inspect' },
  { icon: CheckCircle2, title: 'Feedback', desc: 'Mark elements correct or flag issues with category + comment' },
  { icon: Download, title: 'Export', desc: 'Two formats: ZIP bundle (full PDF + images + feedback, re-importable) or lightweight HTML report' },
  { icon: PackageOpen, title: 'Import', desc: 'Re-import ZIP bundles to continue review on another instance' },
  { icon: BarChart3, title: 'Analyze', desc: 'View issue breakdown by category across documents' },
]

export default function HomePage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [importing, setImporting] = useState(false)

  const handleImport = () => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = '.zip'
    input.onchange = async (e) => {
      const file = (e.target as HTMLInputElement).files?.[0]
      if (!file) return
      setImporting(true)
      try {
        const { import_id, mode } = await startImport(file)
        while (true) {
          const s = await getImportStatus(import_id)
          if (s.status === 'ready') {
            alert(`Import complete! ${s.documents_imported || 1} document(s) with ${s.total_feedback_imported || 0} feedback items`)
            break
          }
          if (s.status === 'error') { throw new Error(s.error || 'Import failed') }
          await new Promise(r => setTimeout(r, mode === 'job' ? 5000 : 2000))
        }
        queryClient.invalidateQueries({ queryKey: ['use-cases'] })
      } catch (err) {
        alert(`Import failed: ${(err as Error).message}`)
      } finally {
        setImporting(false)
      }
    }
    input.click()
  }

  const { data: useCases, isLoading } = useQuery({
    queryKey: ['use-cases'],
    queryFn: listUseCases,
    refetchInterval: 10000,
  })

  return (
    <div className="max-w-screen-xl mx-auto py-8 px-4">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">AI Parse Feedback</h2>
          <p className="text-sm text-gray-500 mt-1">Review and report ai_parse_document quality issues by use case</p>
        </div>
      </div>

      <div className="flex gap-8">
        {/* Left: Use case list */}
        <div className="flex-1 min-w-0">
          {isLoading && (
            <div className="flex items-center gap-3 text-gray-500 py-12 justify-center">
              <Loader2 className="w-5 h-5 animate-spin" /> Loading...
            </div>
          )}

          {useCases && useCases.length === 0 && (
            <div className="text-center py-16 text-gray-400">
              <FolderOpen className="w-12 h-12 mx-auto mb-3 opacity-50" />
              <p>No documents yet. Upload one to get started.</p>
              <button
                onClick={() => navigate('/upload')}
                className="mt-4 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
              >
                Upload Documents
              </button>
            </div>
          )}

          <div className="flex flex-col gap-3">
            {useCases?.map((uc: UseCaseSummary) => (
              <button
                key={uc.use_case_name}
                onClick={() => navigate(`/documents?use_case=${encodeURIComponent(uc.use_case_name)}`)}
                className="group bg-white border border-gray-200 rounded-xl px-5 py-4 text-left hover:border-blue-300 hover:shadow-md transition-all flex items-center gap-4 cursor-pointer"
              >
                <div className="w-9 h-9 rounded-lg bg-blue-50 flex items-center justify-center shrink-0">
                  <FolderOpen className="w-4.5 h-4.5 text-blue-600" />
                </div>
                <h3 className="font-semibold text-gray-900 text-base min-w-0 flex-1 truncate">{uc.use_case_name}</h3>
                <div className="flex items-center gap-5 text-sm shrink-0">
                  <div className="flex items-center gap-1.5 text-gray-500">
                    <FileText className="w-3.5 h-3.5" />
                    <span>{uc.doc_count} docs</span>
                  </div>
                  <div className="flex items-center gap-1.5 text-gray-500">
                    <span>{uc.total_elements} elements</span>
                  </div>
                  <div className="flex items-center gap-1.5 text-green-600">
                    <CheckCircle2 className="w-3.5 h-3.5" />
                    <span>{uc.total_feedback} reviewed</span>
                  </div>
                  <div className="flex items-center gap-1.5 text-red-600">
                    <AlertCircle className="w-3.5 h-3.5" />
                    <span>{uc.total_issues} issues</span>
                  </div>
                </div>
                <ChevronRight className="w-4 h-4 text-gray-300 group-hover:text-blue-500 transition-colors shrink-0" />
              </button>
            ))}
          </div>
        </div>

        {/* Right: How It Works */}
        <div className="w-72 shrink-0 hidden lg:block">
          <div className="bg-white border border-gray-200 rounded-xl p-5 sticky top-20">
            <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-4">How It Works</h3>
            <div className="space-y-4">
              {STEPS.map((step, i) => (
                <div key={step.title} className="flex gap-3">
                  <div className="shrink-0 w-8 h-8 rounded-full bg-blue-50 flex items-center justify-center text-blue-600 text-xs font-bold">
                    {i + 1}
                  </div>
                  <div>
                    <div className="text-sm font-medium text-gray-900 flex items-center gap-1.5">
                      <step.icon className="w-3.5 h-3.5 text-blue-500" />
                      {step.title}
                    </div>
                    <p className="text-xs text-gray-500 mt-0.5">{step.desc}</p>
                  </div>
                </div>
              ))}
            </div>
            <div className="mt-5 pt-4 border-t border-gray-100 flex flex-col gap-2">
              <button
                onClick={() => navigate('/upload')}
                className="w-full px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm font-medium"
              >
                Get Started
              </button>
              <button
                onClick={handleImport}
                disabled={importing}
                className="w-full px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 text-sm font-medium flex items-center justify-center gap-2 disabled:opacity-50"
              >
                {importing ? <Loader2 className="w-4 h-4 animate-spin" /> : <PackageOpen className="w-4 h-4" />}
                {importing ? 'Importing...' : 'Import ZIP'}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
