import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { FileText, Loader2, Trash2, RefreshCw, ExternalLink, CheckCircle2, AlertCircle, Clock, Download, FileBarChart, Upload } from 'lucide-react'
import { listDocuments, listUseCases, triggerParse, deleteDocument, bulkExport, openBulkReport, startImport, getImportStatus } from '../lib/api'
import type { Document } from '../lib/types'

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    uploaded: 'bg-gray-100 text-gray-700',
    parsing: 'bg-yellow-100 text-yellow-700',
    parsed: 'bg-green-100 text-green-700',
    failed: 'bg-red-100 text-red-700',
  }
  const icons: Record<string, React.ReactNode> = {
    uploaded: <Clock className="w-3.5 h-3.5" />,
    parsing: <Loader2 className="w-3.5 h-3.5 animate-spin" />,
    parsed: <CheckCircle2 className="w-3.5 h-3.5" />,
    failed: <AlertCircle className="w-3.5 h-3.5" />,
  }
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${styles[status] || styles.uploaded}`}>
      {icons[status]} {status}
    </span>
  )
}

function UseCaseFilter({ useCase, onChange }: { useCase: string | null; onChange: (c: string | null) => void }) {
  const { data: useCases } = useQuery({ queryKey: ['use-cases'], queryFn: listUseCases })
  return (
    <select
      value={useCase || ''}
      onChange={(e) => onChange(e.target.value || null)}
      className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
    >
      <option value="">All Use Cases</option>
      {useCases?.map(c => (
        <option key={c.use_case_name} value={c.use_case_name}>{c.use_case_name} ({c.doc_count})</option>
      ))}
    </select>
  )
}

export default function DocumentsPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const useCase = searchParams.get('use_case')
  const queryClient = useQueryClient()
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [exporting, setExporting] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [importing, setImporting] = useState(false)

  const { data: docs, isLoading, error } = useQuery({
    queryKey: ['documents', useCase],
    queryFn: () => listDocuments(useCase || undefined),
    refetchInterval: 5000,
  })

  const parseMut = useMutation({
    mutationFn: triggerParse,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['documents'] }),
  })

  const deleteMut = useMutation({
    mutationFn: deleteDocument,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] })
      queryClient.invalidateQueries({ queryKey: ['use-cases'] })
    },
  })

  const parsedDocs = docs?.filter(d => d.status === 'parsed') || []

  const toggleSelect = (id: string) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleAll = () => {
    if (selected.size === parsedDocs.length) {
      setSelected(new Set())
    } else {
      setSelected(new Set(parsedDocs.map(d => d.document_id)))
    }
  }

  const handleBulkExport = async () => {
    setExporting(true)
    try {
      await bulkExport(Array.from(selected))
    } catch (e) {
      alert(`Export failed: ${(e as Error).message}`)
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="max-w-5xl mx-auto py-8 px-4">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-4">
          <h2 className="text-2xl font-bold text-gray-900">Documents</h2>
          <UseCaseFilter useCase={useCase} onChange={(c) => navigate(c ? `/documents?use_case=${encodeURIComponent(c)}` : '/documents')} />
        </div>
        <div className="flex items-center gap-2">
          {selected.size > 0 && (
            <button
              onClick={() => openBulkReport(Array.from(selected)).catch(e => alert((e as Error).message))}
              className="flex items-center gap-2 px-3 py-1.5 text-sm bg-purple-600 text-white rounded-lg hover:bg-purple-700"
            >
              <FileBarChart className="w-4 h-4" /> Report
            </button>
          )}
          {selected.size > 0 && (
            <button
              onClick={handleBulkExport}
              disabled={exporting}
              className="flex items-center gap-2 px-3 py-1.5 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
            >
              {exporting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
              Export {selected.size} selected
            </button>
          )}
          {selected.size > 0 && (
            <button
              disabled={deleting}
              onClick={async () => {
                if (!confirm(`Delete ${selected.size} selected document(s)? This cannot be undone.`)) return
                setDeleting(true)
                await Promise.all(Array.from(selected).map(id => deleteDocument(id).catch(() => {})))
                setDeleting(false)
                setSelected(new Set())
                queryClient.invalidateQueries({ queryKey: ['documents'] })
                queryClient.invalidateQueries({ queryKey: ['use-cases'] })
              }}
              className="flex items-center gap-2 px-3 py-1.5 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 disabled:cursor-wait"
            >
              {deleting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
              {deleting ? 'Deleting...' : `Delete ${selected.size} selected`}
            </button>
          )}
          <button
            onClick={() => {
              const input = document.createElement('input')
              input.type = 'file'
              input.accept = '.zip'
              input.onchange = async (e) => {
                const file = (e.target as HTMLInputElement).files?.[0]
                if (!file) return
                setImporting(true)
                try {
                  const { import_id, mode } = await startImport(file)
                  // Poll until done
                  while (true) {
                    const s = await getImportStatus(import_id)
                    if (s.status === 'ready') {
                      alert(`Import complete! ${s.documents_imported || 1} document(s) with ${s.total_feedback_imported || 0} feedback items`)
                      break
                    }
                    if (s.status === 'error') { throw new Error(s.error || 'Import failed') }
                    await new Promise(r => setTimeout(r, mode === 'job' ? 5000 : 2000))
                  }
                  queryClient.invalidateQueries({ queryKey: ['documents'] })
                } catch (err) {
                  alert(`Import failed: ${(err as Error).message}`)
                } finally {
                  setImporting(false)
                }
              }
              input.click()
            }}
            disabled={importing}
            className="flex items-center gap-2 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100 rounded-lg disabled:opacity-50"
          >
            {importing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
            {importing ? 'Importing...' : 'Import ZIP'}
          </button>
          <button
            onClick={() => queryClient.invalidateQueries({ queryKey: ['documents'] })}
            className="flex items-center gap-2 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100 rounded-lg"
          >
            <RefreshCw className="w-4 h-4" /> Refresh
          </button>
        </div>
      </div>

      {isLoading && (
        <div className="flex items-center gap-3 text-gray-500 py-12 justify-center">
          <Loader2 className="w-5 h-5 animate-spin" /> Loading documents...
        </div>
      )}

      {error && (
        <div className="p-4 bg-red-50 border border-red-200 rounded-lg text-red-700">
          Failed to load documents: {(error as Error).message}
        </div>
      )}

      {docs && docs.length === 0 && (
        <div className="text-center py-16 text-gray-400">
          <FileText className="w-12 h-12 mx-auto mb-3 opacity-50" />
          <p>No documents yet. Upload one to get started.</p>
        </div>
      )}

      {/* Select all */}
      {parsedDocs.length > 0 && (
        <div className="mb-3 flex items-center gap-2">
          <input
            type="checkbox"
            checked={selected.size === parsedDocs.length && parsedDocs.length > 0}
            onChange={toggleAll}
            className="w-4 h-4 rounded border-gray-300"
          />
          <span className="text-sm text-gray-500">Select all parsed documents</span>
        </div>
      )}

      <div className="grid gap-4">
        {docs?.map((doc: Document) => (
          <div
            key={doc.document_id}
            onClick={() => doc.status === 'parsed' && navigate(`/review/${doc.document_id}`)}
            className={`bg-white border border-gray-200 rounded-xl p-5 transition-colors ${
              doc.status === 'parsed' ? 'hover:border-blue-300 hover:shadow-md cursor-pointer' : 'hover:border-gray-300'
            }`}
          >
            <div className="flex items-start justify-between">
              <div className="flex items-start gap-3">
                {doc.status === 'parsed' ? (
                  <input
                    type="checkbox"
                    checked={selected.has(doc.document_id)}
                    onChange={() => toggleSelect(doc.document_id)}
                    onClick={(e) => e.stopPropagation()}
                    className="w-4 h-4 rounded border-gray-300 mt-1 shrink-0"
                  />
                ) : (
                  <FileText className="w-5 h-5 text-gray-400 mt-0.5 shrink-0" />
                )}
                <div>
                  <h3 className="font-medium text-gray-900 flex items-center gap-2">
                    {doc.filename}
                    {doc.use_case_name && <span className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full font-normal">{doc.use_case_name}</span>}
                  </h3>
                  <div className="flex items-center gap-3 mt-1 text-sm text-gray-500">
                    <StatusBadge status={doc.status} />
                    {doc.page_count != null && <span>{doc.page_count} pages</span>}
                    {doc.element_count != null && <span>{doc.element_count} elements</span>}
                    {doc.feedback_stats && doc.feedback_stats.total_feedback > 0 && (
                      <span className="text-blue-600">
                        {doc.feedback_stats.total_feedback} reviewed
                        {doc.feedback_stats.issue_count > 0 && ` (${doc.feedback_stats.issue_count} issues)`}
                      </span>
                    )}
                  </div>
                  {doc.error_message && (
                    <p className="text-xs text-red-500 mt-1">{doc.error_message}</p>
                  )}
                </div>
              </div>
              <div className="flex gap-2 shrink-0" onClick={(e) => e.stopPropagation()}>
                {doc.status === 'uploaded' && (
                  <button
                    onClick={() => parseMut.mutate(doc.document_id)}
                    disabled={parseMut.isPending}
                    className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
                  >
                    Parse
                  </button>
                )}
                {doc.status === 'failed' && (
                  <button
                    onClick={() => parseMut.mutate(doc.document_id)}
                    disabled={parseMut.isPending}
                    className="px-3 py-1.5 text-sm bg-yellow-600 text-white rounded-lg hover:bg-yellow-700 disabled:opacity-50"
                  >
                    Retry
                  </button>
                )}
                {doc.status === 'parsed' && (
                  <button
                    onClick={() => navigate(`/review/${doc.document_id}`)}
                    className="px-3 py-1.5 text-sm bg-green-600 text-white rounded-lg hover:bg-green-700 flex items-center gap-1"
                  >
                    <ExternalLink className="w-3.5 h-3.5" /> Review
                  </button>
                )}
                <button
                  onClick={() => { if (confirm('Delete this document?')) deleteMut.mutate(doc.document_id) }}
                  className="p-1.5 text-gray-400 hover:text-red-500 rounded-lg hover:bg-red-50"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
