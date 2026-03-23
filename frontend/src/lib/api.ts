import type { Document, PageData, Feedback, AppConfig, UseCaseSummary } from './types'

const BASE = '/api'

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`${res.status}: ${text}`)
  }
  return res.json()
}

// Use Cases
export const listUseCases = () => request<UseCaseSummary[]>(`${BASE}/documents/use-cases`)

// Documents
export const listDocuments = (useCase?: string) =>
  request<Document[]>(`${BASE}/documents${useCase ? `?use_case=${encodeURIComponent(useCase)}` : ''}`)

export const getDocument = (id: string) => request<Document>(`${BASE}/documents/${id}`)

export const getPageData = (id: string, pageId: number) =>
  request<PageData>(`${BASE}/documents/${id}/page/${pageId}`)

export const uploadDocument = async (file: File, useCaseName?: string) => {
  const form = new FormData()
  form.append('file', file)
  if (useCaseName) form.append('use_case_name', useCaseName)
  return request<{ document_id: string; status: string }>(`${BASE}/documents/upload`, {
    method: 'POST',
    body: form,
  })
}

export const triggerParse = (id: string) =>
  request<{ document_id: string; status: string }>(`${BASE}/documents/${id}/parse`, { method: 'POST' })

export const deleteDocument = (id: string) =>
  request<{ status: string }>(`${BASE}/documents/${id}`, { method: 'DELETE' })

export const runAiQuery = (documentId: string, elementId: number, pageId: number, prompt: string) =>
  request<{ result: string; model: string; crop_size: string }>(`${BASE}/documents/${documentId}/element/${elementId}/ai-query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ page_id: pageId, prompt }),
  })

// Feedback
export const submitFeedback = (body: {
  document_id: string
  element_id: number
  page_id: number
  element_type?: string
  bbox_coords?: number[]
  is_correct?: boolean
  issue_category?: string
  comment?: string
  suggested_content?: string
  suggested_type?: string
}) => request<{ feedback_id: string }>(`${BASE}/feedback`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const getDocumentFeedback = (docId: string) =>
  request<Feedback[]>(`${BASE}/feedback/document/${docId}`)

export const bulkSubmitFeedback = (documentId: string, items: Array<{
  element_id: number; page_id: number; element_type?: string;
  bbox_coords?: number[]; is_correct?: boolean;
}>) => request<{ status: string; count: number }>(`${BASE}/feedback/bulk`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ document_id: documentId, items }),
})

// Analytics
export const getAnalytics = (useCase?: string) =>
  request<{
    issue_breakdown: Array<{ issue_category: string; count: number }>
    summary: { total_docs: number; total_elements: number; total_reviewed: number; total_correct: number; total_issues: number }
  }>(`${BASE}/documents/analytics${useCase ? `?use_case=${encodeURIComponent(useCase)}` : ''}`)

// Active background jobs
export const getActiveJobs = () =>
  request<Array<{ id: string; mode: string; status: string; progress: string; type: string; filename?: string }>>(
    `${BASE}/export/active-jobs`
  )

// Config
export const getConfig = () => request<AppConfig>(`${BASE}/documents/config`)

// PDF
export const getDocumentPdfUrl = (id: string) => `${BASE}/documents/${id}/pdf`

// Export
export const exportDocumentUrl = (id: string) => `${BASE}/export/document/${id}`

export const reportUrl = (id: string) => `${BASE}/export/report/${id}`

export const openBulkReport = async (documentIds: string[]) => {
  const res = await fetch(`${BASE}/export/bulk-report`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ document_ids: documentIds }),
  })
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`)
  const html = await res.text()
  const win = window.open('', '_blank')
  if (win) { win.document.write(html); win.document.close() }
}

export const startImport = async (file: File) => {
  const form = new FormData()
  form.append('file', file)
  return request<{
    import_id: string; status: string; mode: string; size_mb?: number;
  }>(`${BASE}/export/import`, { method: 'POST', body: form })
}

export const getImportStatus = (importId: string) =>
  request<{
    status: string; mode?: string; progress?: string; error?: string;
    documents_imported?: number; total_feedback_imported?: number;
  }>(`${BASE}/export/import-status/${importId}`)

// Legacy: blocking import (kept for backward compat)
export const importBundle = async (file: File) => {
  const { import_id, mode } = await startImport(file)
  while (true) {
    const s = await getImportStatus(import_id)
    if (s.status === 'ready') return s
    if (s.status === 'error') throw new Error(s.error || 'Import failed')
    await new Promise(r => setTimeout(r, mode === 'job' ? 5000 : 2000))
  }
}

export const startExport = (documentIds: string[]) =>
  request<{ export_id: string; status: string; mode: string; total_pages?: number }>(`${BASE}/export/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ document_ids: documentIds }),
  })

export const getExportStatus = (exportId: string) =>
  request<{ status: string; mode?: string; progress?: string; error?: string; filename?: string }>(
    `${BASE}/export/status/${exportId}`
  )

export const downloadExportUrl = (exportId: string) => `${BASE}/export/download/${exportId}`

// Legacy inline export for backward compat
export const bulkExport = async (documentIds: string[]) => {
  // Use background export + polling
  const { export_id } = await startExport(documentIds)

  // Poll until ready
  while (true) {
    const status = await getExportStatus(export_id)
    if (status.status === 'ready') {
      window.location.href = downloadExportUrl(export_id)
      return
    }
    if (status.status === 'error') {
      throw new Error(status.error || 'Export failed')
    }
    await new Promise(r => setTimeout(r, 2000))
  }
}
