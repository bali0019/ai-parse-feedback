/**
 * Main review page: page-by-page annotated viewer with feedback panel.
 * Features: auto-advance, mark all correct, keyboard shortcuts, page jump.
 */

import { useState, useMemo, useEffect, useCallback } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, ArrowLeft, Download, Loader2, CheckCircle2, AlertCircle, CheckCheck, Keyboard } from 'lucide-react'
import { getDocument, getPageData, getDocumentFeedback, getDocumentPdfUrl, startExport, getExportStatus, downloadExportUrl, reportUrl, submitFeedback, bulkSubmitFeedback } from '../lib/api'
import { FileText as FileTextIcon } from 'lucide-react'
import PageAnnotator from '../components/PageAnnotator'
import FeedbackForm from '../components/FeedbackForm'
import type { Element } from '../lib/types'

export default function ReviewPage() {
  const { documentId } = useParams<{ documentId: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [currentPage, setCurrentPage] = useState(0)
  const [selectedElementId, setSelectedElementId] = useState<number | null>(null)
  const [showShortcuts, setShowShortcuts] = useState(false)
  const [autoSelectFirst, setAutoSelectFirst] = useState(false)
  const [pageInputValue, setPageInputValue] = useState('1')

  // Fetch document metadata
  const { data: doc, isLoading: docLoading } = useQuery({
    queryKey: ['document', documentId],
    queryFn: () => getDocument(documentId!),
    enabled: !!documentId,
    refetchInterval: (query) => query.state.data?.status === 'parsing' ? 3000 : false,
  })

  // Fetch current page data
  const { data: pageData, isLoading: pageLoading } = useQuery({
    queryKey: ['pageData', documentId, currentPage],
    queryFn: () => getPageData(documentId!, currentPage),
    enabled: !!documentId && doc?.status === 'parsed',
    refetchOnWindowFocus: false,
  })

  const totalPages = doc?.page_count || pageData?.total_pages || 0

  // Keep page input in sync with currentPage
  useEffect(() => {
    setPageInputValue(String(currentPage + 1))
  }, [currentPage])

  // Auto-select first element when advancing to a new page
  useEffect(() => {
    if (autoSelectFirst && pageData && pageData.elements.length > 0) {
      setSelectedElementId(pageData.elements[0].id)
      setAutoSelectFirst(false)
    }
  }, [autoSelectFirst, pageData])

  // Find the selected element
  const selectedElement = useMemo(() => {
    if (!pageData || selectedElementId === null) return null
    return pageData.elements.find(e => e.id === selectedElementId) || null
  }, [pageData, selectedElementId])

  const selectedFeedback = useMemo(() => {
    if (!pageData || selectedElementId === null) return null
    return pageData.feedback[selectedElementId] || null
  }, [pageData, selectedElementId])

  // Count reviewed elements on current page
  const reviewStats = useMemo(() => {
    if (!pageData) return { total: 0, reviewed: 0, issues: 0, unreviewed: 0 }
    const total = pageData.elements.length
    const reviewed = Object.keys(pageData.feedback).length
    const issues = Object.values(pageData.feedback).filter(f => f.is_correct === false).length
    return { total, reviewed, issues, unreviewed: total - reviewed }
  }, [pageData])

  // Get unreviewed elements on current page
  const unreviewedElements = useMemo(() => {
    if (!pageData) return []
    return pageData.elements.filter(e => !(e.id in pageData.feedback))
  }, [pageData])

  // Auto-advance: find next unreviewed element after feedback
  const handleFeedbackSubmitted = useCallback((elementId: number) => {
    if (!pageData) return
    const currentIdx = pageData.elements.findIndex(e => e.id === elementId)
    // Find next unreviewed element after current
    for (let i = currentIdx + 1; i < pageData.elements.length; i++) {
      if (!(pageData.elements[i].id in pageData.feedback)) {
        setSelectedElementId(pageData.elements[i].id)
        return
      }
    }
    // Check before current
    for (let i = 0; i < currentIdx; i++) {
      if (!(pageData.elements[i].id in pageData.feedback)) {
        setSelectedElementId(pageData.elements[i].id)
        return
      }
    }
    // All reviewed on this page — advance to next page and auto-select first element
    if (currentPage < totalPages - 1) {
      setCurrentPage(p => p + 1)
      setAutoSelectFirst(true)
    }
  }, [pageData, currentPage, totalPages])

  // Mark all remaining on current page correct
  const markPageCorrectMut = useMutation({
    mutationFn: async () => {
      if (!pageData) return
      const promises = unreviewedElements.map(elem => {
        const bbox = elem.bbox?.find(b => b.page_id === currentPage)
        return submitFeedback({
          document_id: documentId!,
          element_id: elem.id,
          page_id: currentPage,
          element_type: elem.type,
          bbox_coords: bbox?.coord,
          is_correct: true,
        })
      })
      await Promise.all(promises)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['pageData'] })
      if (currentPage < totalPages - 1) {
        setCurrentPage(p => p + 1)
        setAutoSelectFirst(true)
      }
    },
  })

  // Mark ALL elements across ALL pages correct (whole document)
  const [markAllStatus, setMarkAllStatus] = useState<string | null>(null)
  const markAllDocCorrectMut = useMutation({
    mutationFn: async () => {
      setMarkAllStatus('Loading document data...')
      // Fetch full document with parsed_result
      const fullDoc = await getDocument(documentId!)
      const allElements = fullDoc.parsed_result?.document?.elements || []
      if (allElements.length === 0) {
        setMarkAllStatus('No elements found in document')
        return 0
      }

      setMarkAllStatus('Checking existing feedback...')
      const existingFeedback = await getDocumentFeedback(documentId!)
      const reviewedIds = new Set(existingFeedback.map(f => f.element_id))
      const unreviewed = allElements.filter((e: Element) => !reviewedIds.has(e.id))

      if (unreviewed.length === 0) {
        setMarkAllStatus('All elements already reviewed!')
        return 0
      }

      setMarkAllStatus(`Marking ${unreviewed.length} elements correct...`)
      const items = unreviewed.map((elem: Element) => {
        const bbox = elem.bbox?.[0]
        return {
          element_id: elem.id,
          page_id: bbox?.page_id ?? 0,
          element_type: elem.type,
          bbox_coords: bbox?.coord,
          is_correct: true,
        }
      })

      await bulkSubmitFeedback(documentId!, items)
      return unreviewed.length
    },
    onSuccess: (count) => {
      queryClient.invalidateQueries({ queryKey: ['pageData'] })
      queryClient.invalidateQueries({ queryKey: ['document'] })
      setMarkAllStatus(count ? `Done! Marked ${count} elements correct.` : null)
      setTimeout(() => setMarkAllStatus(null), 3000)
    },
    onError: (err) => {
      setMarkAllStatus(`Error: ${(err as Error).message}`)
      setTimeout(() => setMarkAllStatus(null), 5000)
    },
  })

  // Quick mark correct for keyboard shortcut
  const quickMarkCorrect = useCallback(() => {
    if (!selectedElement || !pageData) return
    const bbox = selectedElement.bbox?.find(b => b.page_id === currentPage)
    submitFeedback({
      document_id: documentId!,
      element_id: selectedElement.id,
      page_id: currentPage,
      element_type: selectedElement.type,
      bbox_coords: bbox?.coord,
      is_correct: true,
    }).then(() => {
      queryClient.invalidateQueries({ queryKey: ['pageData'] })
      handleFeedbackSubmitted(selectedElement.id)
    })
  }, [selectedElement, pageData, currentPage, documentId, queryClient, handleFeedbackSubmitted])

  // Navigate elements
  const selectNextElement = useCallback(() => {
    if (!pageData || pageData.elements.length === 0) return
    if (selectedElementId === null) {
      setSelectedElementId(pageData.elements[0].id)
      return
    }
    const currentIdx = pageData.elements.findIndex(e => e.id === selectedElementId)
    const nextIdx = currentIdx + 1 < pageData.elements.length ? currentIdx + 1 : 0
    setSelectedElementId(pageData.elements[nextIdx].id)
  }, [pageData, selectedElementId])

  const selectPrevElement = useCallback(() => {
    if (!pageData || pageData.elements.length === 0) return
    if (selectedElementId === null) {
      setSelectedElementId(pageData.elements[pageData.elements.length - 1].id)
      return
    }
    const currentIdx = pageData.elements.findIndex(e => e.id === selectedElementId)
    const prevIdx = currentIdx - 1 >= 0 ? currentIdx - 1 : pageData.elements.length - 1
    setSelectedElementId(pageData.elements[prevIdx].id)
  }, [pageData, selectedElementId])

  // Page jump from input
  const commitPageInput = () => {
    const num = parseInt(pageInputValue)
    if (!isNaN(num) && num >= 1 && num <= totalPages) {
      setCurrentPage(num - 1)
      setSelectedElementId(null)
    } else {
      setPageInputValue(String(currentPage + 1))
    }
  }

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
      // Block shortcuts during any pending mutation
      if (markAllDocCorrectMut.isPending || markPageCorrectMut.isPending) return

      switch (e.key) {
        case 'c':
          e.preventDefault()
          quickMarkCorrect()
          break
        case 'n':
          e.preventDefault()
          selectNextElement()
          break
        case 'p':
          e.preventDefault()
          selectPrevElement()
          break
        case 'ArrowRight':
          e.preventDefault()
          if (currentPage < totalPages - 1) {
            setCurrentPage(p => p + 1)
            setSelectedElementId(null)
          }
          break
        case 'ArrowLeft':
          e.preventDefault()
          if (currentPage > 0) {
            setCurrentPage(p => p - 1)
            setSelectedElementId(null)
          }
          break
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [quickMarkCorrect, selectNextElement, selectPrevElement, currentPage, totalPages])

  if (docLoading) {
    return (
      <div className="flex items-center justify-center h-96 text-gray-500">
        <Loader2 className="w-6 h-6 animate-spin mr-2" /> Loading document...
      </div>
    )
  }

  if (!doc) {
    return (
      <div className="max-w-2xl mx-auto py-12 px-4 text-center text-gray-500">
        Document not found.
        <Link to="/documents" className="text-blue-600 ml-2 hover:underline">Back to documents</Link>
      </div>
    )
  }

  if (doc.status === 'parsing') {
    return (
      <div className="max-w-2xl mx-auto py-12 px-4 text-center">
        <Loader2 className="w-8 h-8 animate-spin mx-auto text-blue-500 mb-4" />
        <p className="text-gray-600">Document is being parsed...</p>
        <p className="text-sm text-gray-400 mt-1">This may take a few minutes for large documents.</p>
      </div>
    )
  }

  if (doc.status !== 'parsed') {
    return (
      <div className="max-w-2xl mx-auto py-12 px-4 text-center text-gray-500">
        Document status: {doc.status}. Cannot review yet.
        <Link to="/documents" className="text-blue-600 ml-2 hover:underline">Back to documents</Link>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-[calc(100vh-57px)]">
      {/* Top bar */}
      <div className="bg-white border-b border-gray-200 px-4 py-2 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-3">
          <button onClick={() => navigate('/documents')} className="text-gray-500 hover:text-gray-700">
            <ArrowLeft className="w-5 h-5" />
          </button>
          <span className="font-medium text-gray-900">{doc.filename}</span>
          {doc.use_case_name && <span className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full">{doc.use_case_name}</span>}
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm text-gray-500">
            {reviewStats.reviewed}/{reviewStats.total} reviewed
            {reviewStats.issues > 0 && (
              <span className="text-red-500 ml-1">({reviewStats.issues} issues)</span>
            )}
          </span>
          <button
            onClick={() => markAllDocCorrectMut.mutate()}
            disabled={markAllDocCorrectMut.isPending || markPageCorrectMut.isPending}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-green-50 text-green-700 border border-green-200 rounded-lg hover:bg-green-100 disabled:opacity-50 disabled:cursor-wait"
          >
            {markAllDocCorrectMut.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCheck className="w-4 h-4" />}
            {markAllDocCorrectMut.isPending ? 'Saving all elements...' : 'Mark All Correct'}
          </button>
          <button
            onClick={() => setShowShortcuts(!showShortcuts)}
            className="p-1.5 text-gray-400 hover:text-gray-600 rounded"
            title="Keyboard shortcuts"
          >
            <Keyboard className="w-4 h-4" />
          </button>
          <a
            href={reportUrl(documentId!)}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200"
          >
            <FileTextIcon className="w-4 h-4" /> Report
          </a>
          <button
            onClick={async () => {
              try {
                setMarkAllStatus('Starting export...')
                const { export_id, mode } = await startExport([documentId!])
                const isJob = mode === 'job'
                while (true) {
                  const s = await getExportStatus(export_id)
                  if (s.status === 'ready') {
                    window.location.href = downloadExportUrl(export_id)
                    setMarkAllStatus('Export ready — downloading...')
                    setTimeout(() => setMarkAllStatus(null), 3000)
                    return
                  }
                  if (s.status === 'error') { setMarkAllStatus(`Export error: ${s.error}`); return }
                  setMarkAllStatus(isJob ? `Exporting via background job... ${s.progress || ''}` : (s.progress || 'Exporting...'))
                  await new Promise(r => setTimeout(r, isJob ? 5000 : 2000))
                }
              } catch (e) { setMarkAllStatus(`Export failed: ${(e as Error).message}`) }
            }}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200"
          >
            <Download className="w-4 h-4" /> Export ZIP
          </button>
        </div>
      </div>

      {/* Global status bar for mark-all / bulk operations */}
      {(markAllDocCorrectMut.isPending || markPageCorrectMut.isPending || markAllStatus) && (
        <div className={`px-4 py-2 text-sm flex items-center gap-2 shrink-0 ${
          markAllStatus && !markAllDocCorrectMut.isPending && !markPageCorrectMut.isPending
            ? (markAllStatus.startsWith('Error') ? 'bg-red-100 text-red-700 border-b border-red-200'
               : markAllStatus.startsWith('All elements') ? 'bg-yellow-100 text-yellow-700 border-b border-yellow-200'
               : 'bg-green-100 text-green-700 border-b border-green-200')
            : 'bg-blue-100 text-blue-700 border-b border-blue-200'
        }`}>
          {(markAllDocCorrectMut.isPending || markPageCorrectMut.isPending) && <Loader2 className="w-4 h-4 animate-spin" />}
          {markAllStatus || (markPageCorrectMut.isPending ? 'Marking page elements correct...' : 'Processing...')}
          {markAllDocCorrectMut.isPending && <span className="text-xs opacity-70 ml-2">(stay on this page)</span>}
        </div>
      )}

      {/* Keyboard shortcuts hint */}
      {showShortcuts && (
        <div className="bg-gray-800 text-gray-200 px-4 py-2 text-xs flex items-center gap-6 shrink-0">
          <span><kbd className="bg-gray-600 px-1.5 py-0.5 rounded text-white">C</kbd> Mark correct + next</span>
          <span><kbd className="bg-gray-600 px-1.5 py-0.5 rounded text-white">N</kbd> Next element</span>
          <span><kbd className="bg-gray-600 px-1.5 py-0.5 rounded text-white">P</kbd> Prev element</span>
          <span><kbd className="bg-gray-600 px-1.5 py-0.5 rounded text-white">&larr;</kbd><kbd className="bg-gray-600 px-1.5 py-0.5 rounded text-white">&rarr;</kbd> Prev/Next page</span>
        </div>
      )}

      {/* Page navigator with jump-to input */}
      <div className="bg-gray-50 border-b border-gray-200 px-4 py-2 flex items-center justify-center gap-4 shrink-0">
        <button
          onClick={() => { setCurrentPage(p => Math.max(0, p - 1)); setSelectedElementId(null) }}
          disabled={currentPage === 0}
          className="p-1 rounded hover:bg-gray-200 disabled:opacity-30"
        >
          <ChevronLeft className="w-5 h-5" />
        </button>

        <div className="flex items-center gap-1.5">
          <span className="text-sm text-gray-500">Page</span>
          <input
            type="number"
            min={1}
            max={totalPages}
            value={pageInputValue}
            onChange={(e) => setPageInputValue(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') { commitPageInput(); (e.target as HTMLInputElement).blur() } }}
            onBlur={commitPageInput}
            className="w-14 text-center text-sm font-medium bg-white border border-gray-300 rounded px-1 py-0.5 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-400"
          />
          <span className="text-sm text-gray-500">of {totalPages}</span>
        </div>

        <button
          onClick={() => { setCurrentPage(p => Math.min(totalPages - 1, p + 1)); setSelectedElementId(null) }}
          disabled={currentPage >= totalPages - 1}
          className="p-1 rounded hover:bg-gray-200 disabled:opacity-30"
        >
          <ChevronRight className="w-5 h-5" />
        </button>
      </div>

      {/* Main content: annotator + panel */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left: Page annotator */}
        <div className="flex-1 overflow-auto p-4 bg-gray-100">
          {pageLoading ? (
            <div className="flex items-center justify-center h-64 text-gray-500">
              <Loader2 className="w-5 h-5 animate-spin mr-2" /> Loading page...
            </div>
          ) : pageData ? (
            <PageAnnotator
              imageDataUri={pageData.image?.data_uri || null}
              imageWidth={pageData.image?.width || 800}
              imageHeight={pageData.image?.height || 1000}
              pdfUrl={!pageData.image ? getDocumentPdfUrl(documentId!) : null}
              pageNumber={currentPage + 1}
              elements={pageData.elements}
              pageId={currentPage}
              selectedElementId={selectedElementId}
              feedbackMap={pageData.feedback}
              qualityFlags={pageData.quality_flags}
              onSelectElement={setSelectedElementId}
            />
          ) : (
            <div className="text-gray-400 text-center py-12">No page data</div>
          )}
        </div>

        {/* Right: Element list + feedback */}
        <div className="w-[400px] border-l border-gray-200 bg-white flex flex-col overflow-hidden shrink-0">
          {/* Element list header + mark page correct */}
          <div className="p-3 border-b border-gray-100 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">
              Elements ({pageData?.elements.length || 0})
            </h3>
            {reviewStats.unreviewed > 0 && (
              <button
                onClick={() => markPageCorrectMut.mutate()}
                disabled={markPageCorrectMut.isPending || markAllDocCorrectMut.isPending}
                className="flex items-center gap-1 px-2 py-1 text-xs bg-green-50 text-green-700 border border-green-200 rounded-md hover:bg-green-100 disabled:opacity-50 disabled:cursor-wait"
              >
                {markPageCorrectMut.isPending ? (
                  <Loader2 className="w-3 h-3 animate-spin" />
                ) : (
                  <CheckCheck className="w-3 h-3" />
                )}
                {markPageCorrectMut.isPending ? 'Saving...' : `Mark ${reviewStats.unreviewed} correct`}
              </button>
            )}
          </div>

          {/* Element list */}
          <div className="flex-1 overflow-y-auto">
            <div className="divide-y divide-gray-50">
              {pageData?.elements
                .slice()
                .sort((a, b) => {
                  // Sort: flagged unreviewed first, then unreviewed, then reviewed
                  const aFlagged = !!(pageData.quality_flags?.[a.id]?.length) && !(a.id in pageData.feedback)
                  const bFlagged = !!(pageData.quality_flags?.[b.id]?.length) && !(b.id in pageData.feedback)
                  if (aFlagged !== bFlagged) return aFlagged ? -1 : 1
                  return 0
                })
                .map((elem: Element) => {
                const fb = pageData.feedback[elem.id]
                const isSelected = elem.id === selectedElementId
                const flags = pageData.quality_flags?.[elem.id]
                return (
                  <button
                    key={elem.id}
                    onClick={() => setSelectedElementId(elem.id)}
                    className={`w-full text-left px-3 py-2 text-sm transition-colors ${
                      isSelected ? 'bg-blue-50 border-l-2 border-blue-600' : 'hover:bg-gray-50 border-l-2 border-transparent'
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-medium text-gray-800">
                        #{elem.id} <span className="text-gray-500">{elem.type}</span>
                      </span>
                      <span className="flex items-center gap-1">
                        {flags?.length && !fb && <span className="text-amber-500" title={flags.map(f => f.message).join('; ')}>⚠</span>}
                        {fb?.is_correct === true && <CheckCircle2 className="w-4 h-4 text-green-500" />}
                        {fb?.is_correct === false && <AlertCircle className="w-4 h-4 text-red-500" />}
                      </span>
                    </div>
                    {elem.content && (
                      <p className="text-xs text-gray-400 truncate mt-0.5">
                        {elem.content.replace(/<[^>]*>/g, '').slice(0, 60)}
                      </p>
                    )}
                  </button>
                )
              })}
            </div>
          </div>

          {/* Feedback form */}
          {selectedElement && (
            <div className="border-t border-gray-200 p-4 overflow-y-auto max-h-[50%]">
              <FeedbackForm
                documentId={documentId!}
                element={selectedElement}
                pageId={currentPage}
                existingFeedback={selectedFeedback}
                onSubmitSuccess={handleFeedbackSubmitted}
              />
            </div>
          )}

          {!selectedElement && (
            <div className="border-t border-gray-200 p-6 text-center text-gray-400 text-sm">
              Click a bounding box or press <kbd className="bg-gray-100 px-1 rounded">N</kbd> to start reviewing
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
