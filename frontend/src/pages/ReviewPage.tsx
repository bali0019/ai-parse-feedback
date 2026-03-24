/**
 * V2 Review page: resizable panels, compact toolbar, extended shortcuts, progress bar.
 * Tagged v1-ui for rollback if needed.
 */

import { useState, useMemo, useEffect, useCallback, useRef } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ELEMENT_COLORS } from '../lib/constants'
import { ChevronLeft, ChevronRight, ArrowLeft, Download, Loader2, CheckCircle2, AlertCircle, CheckCheck, Filter, X, FileText as FileTextIcon } from 'lucide-react'
import { getDocument, getPageData, getDocumentFeedback, getDocumentPdfUrl, startExport, getExportStatus, downloadExportUrl, reportUrl, submitFeedback, bulkSubmitFeedback } from '../lib/api'
import PageAnnotator from '../components/PageAnnotator'
import FeedbackForm from '../components/FeedbackForm'
import type { Element } from '../lib/types'

export default function ReviewPage() {
  const { documentId } = useParams<{ documentId: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [currentPage, setCurrentPage] = useState(0)
  const [selectedElementId, setSelectedElementId] = useState<number | null>(null)
  const [autoSelectFirst, setAutoSelectFirst] = useState(false)
  const [pageInputValue, setPageInputValue] = useState('1')
  const [activeTypeFilters, setActiveTypeFilters] = useState<Set<string>>(new Set())
  const [elementListExpanded, setElementListExpanded] = useState(true)
  const [markAllStatus, setMarkAllStatus] = useState<string | null>(null)
  const selectedElementRef = useRef<HTMLButtonElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const annotatorRef = useRef<HTMLDivElement>(null)
  const [annotatorWidth, setAnnotatorWidth] = useState(0)

  // Measure annotator container width for dynamic image scaling
  useEffect(() => {
    const el = annotatorRef.current
    if (!el) return
    const ro = new ResizeObserver(entries => {
      for (const entry of entries) {
        setAnnotatorWidth(entry.contentRect.width - 32) // subtract padding (p-4 = 16px * 2)
      }
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  const [inspectorPct, setInspectorPct] = useState(() => {
    const saved = localStorage.getItem('review-inspector-pct')
    return saved ? parseFloat(saved) : 40
  })
  const isDragging = useRef(false)

  const handleDragStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    isDragging.current = true
    const startX = e.clientX
    const startPct = inspectorPct
    const containerWidth = containerRef.current?.offsetWidth || window.innerWidth
    const onMove = (ev: MouseEvent) => {
      if (!isDragging.current) return
      const deltaPx = startX - ev.clientX
      const deltaPct = (deltaPx / containerWidth) * 100
      const newPct = Math.min(55, Math.max(25, startPct + deltaPct))
      setInspectorPct(newPct)
    }
    const onUp = () => {
      isDragging.current = false
      localStorage.setItem('review-inspector-pct', String(inspectorPct))
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }, [inspectorPct])

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

  // Build page→element types index from parsed_result (for filtering)
  const { pageTypeIndex, allElementTypes } = useMemo(() => {
    const index = new Map<number, Set<string>>()
    const types = new Set<string>()
    const elements = doc?.parsed_result?.document?.elements || []
    for (const elem of elements) {
      if (elem.type) types.add(elem.type)
      for (const bbox of elem.bbox || []) {
        if (bbox.page_id != null) {
          if (!index.has(bbox.page_id)) index.set(bbox.page_id, new Set())
          index.get(bbox.page_id)!.add(elem.type)
        }
      }
    }
    return { pageTypeIndex: index, allElementTypes: Array.from(types).sort() }
  }, [doc?.parsed_result])

  // Document-level review stats for progress bar
  const docReviewStats = useMemo(() => {
    const allElements = doc?.parsed_result?.document?.elements || []
    const total = allElements.length
    return { total }
  }, [doc?.parsed_result])

  // Filtered pages
  const filteredPages = useMemo(() => {
    if (activeTypeFilters.size === 0) return null
    const pages: number[] = []
    for (let i = 0; i < totalPages; i++) {
      const types = pageTypeIndex.get(i)
      if (types) {
        for (const t of activeTypeFilters) {
          if (types.has(t)) { pages.push(i); break }
        }
      }
    }
    return pages
  }, [activeTypeFilters, pageTypeIndex, totalPages])

  useEffect(() => {
    if (filteredPages && filteredPages.length > 0 && !filteredPages.includes(currentPage)) {
      setCurrentPage(filteredPages[0])
      setSelectedElementId(null)
    }
  }, [filteredPages])

  const toggleTypeFilter = useCallback((type: string) => {
    setActiveTypeFilters(prev => {
      const next = new Set(prev)
      if (next.has(type)) next.delete(type)
      else next.add(type)
      return next
    })
  }, [])

  useEffect(() => { setPageInputValue(String(currentPage + 1)) }, [currentPage])

  useEffect(() => {
    if (autoSelectFirst && pageData && pageData.elements.length > 0) {
      setSelectedElementId(pageData.elements[0].id)
      setAutoSelectFirst(false)
    }
  }, [autoSelectFirst, pageData])

  const visibleElements = useMemo(() => {
    if (!pageData) return []
    if (activeTypeFilters.size === 0) return pageData.elements
    return pageData.elements.filter(e => activeTypeFilters.has(e.type))
  }, [pageData, activeTypeFilters])

  useEffect(() => {
    if (selectedElementId !== null) setElementListExpanded(false)
  }, [selectedElementId])

  // Scroll selected element into view
  useEffect(() => {
    if (selectedElementRef.current) {
      selectedElementRef.current.scrollIntoView({ block: 'nearest' })
    }
  }, [selectedElementId])

  const selectedElement = useMemo(() => {
    if (!pageData || selectedElementId === null) return null
    return pageData.elements.find(e => e.id === selectedElementId) || null
  }, [pageData, selectedElementId])

  const selectedFeedback = useMemo(() => {
    if (!pageData || selectedElementId === null) return null
    return pageData.feedback[selectedElementId] || null
  }, [pageData, selectedElementId])

  const reviewStats = useMemo(() => {
    if (!pageData) return { total: 0, reviewed: 0, issues: 0, unreviewed: 0, correct: 0 }
    const total = pageData.elements.length
    const reviewed = Object.keys(pageData.feedback).length
    const issues = Object.values(pageData.feedback).filter(f => f.is_correct === false).length
    const correct = Object.values(pageData.feedback).filter(f => f.is_correct === true).length
    return { total, reviewed, issues, unreviewed: total - reviewed, correct }
  }, [pageData])

  const unreviewedElements = useMemo(() => {
    if (!pageData) return []
    return pageData.elements.filter(e => !(e.id in pageData.feedback))
  }, [pageData])

  // Auto-advance after feedback
  const handleFeedbackSubmitted = useCallback((elementId: number) => {
    if (!pageData) return
    const currentIdx = pageData.elements.findIndex(e => e.id === elementId)
    for (let i = currentIdx + 1; i < pageData.elements.length; i++) {
      if (!(pageData.elements[i].id in pageData.feedback)) {
        setSelectedElementId(pageData.elements[i].id)
        return
      }
    }
    for (let i = 0; i < currentIdx; i++) {
      if (!(pageData.elements[i].id in pageData.feedback)) {
        setSelectedElementId(pageData.elements[i].id)
        return
      }
    }
    if (currentPage < totalPages - 1) {
      setCurrentPage(p => p + 1)
      setAutoSelectFirst(true)
    }
  }, [pageData, currentPage, totalPages])

  // Mark page correct
  const markPageCorrectMut = useMutation({
    mutationFn: async () => {
      if (!pageData) return
      await Promise.all(unreviewedElements.map(elem => {
        const bbox = elem.bbox?.find(b => b.page_id === currentPage)
        return submitFeedback({
          document_id: documentId!, element_id: elem.id, page_id: currentPage,
          element_type: elem.type, bbox_coords: bbox?.coord, is_correct: true,
        })
      }))
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['pageData'] })
      if (currentPage < totalPages - 1) { setCurrentPage(p => p + 1); setAutoSelectFirst(true) }
    },
  })

  // Mark all doc correct
  const markAllDocCorrectMut = useMutation({
    mutationFn: async () => {
      setMarkAllStatus('Loading document data...')
      const fullDoc = await getDocument(documentId!)
      const allElements = fullDoc.parsed_result?.document?.elements || []
      if (allElements.length === 0) { setMarkAllStatus('No elements found'); return 0 }
      setMarkAllStatus('Checking existing feedback...')
      const existingFeedback = await getDocumentFeedback(documentId!)
      const reviewedIds = new Set(existingFeedback.map(f => f.element_id))
      const unreviewed = allElements.filter((e: Element) => !reviewedIds.has(e.id))
      if (unreviewed.length === 0) { setMarkAllStatus('All elements already reviewed!'); return 0 }
      setMarkAllStatus(`Approving ${unreviewed.length} elements...`)
      const items = unreviewed.map((elem: Element) => {
        const bbox = elem.bbox?.[0]
        return { element_id: elem.id, page_id: bbox?.page_id ?? 0, element_type: elem.type, bbox_coords: bbox?.coord, is_correct: true }
      })
      await bulkSubmitFeedback(documentId!, items)
      return unreviewed.length
    },
    onSuccess: (count) => {
      queryClient.invalidateQueries({ queryKey: ['pageData'] })
      queryClient.invalidateQueries({ queryKey: ['document'] })
      setMarkAllStatus(count ? `Approved ${count} elements.` : null)
      setTimeout(() => setMarkAllStatus(null), 3000)
    },
    onError: (err) => { setMarkAllStatus(`Error: ${(err as Error).message}`); setTimeout(() => setMarkAllStatus(null), 5000) },
  })

  // Quick mark correct
  const quickMarkCorrect = useCallback(() => {
    if (!selectedElement || !pageData) return
    const bbox = selectedElement.bbox?.find(b => b.page_id === currentPage)
    submitFeedback({
      document_id: documentId!, element_id: selectedElement.id, page_id: currentPage,
      element_type: selectedElement.type, bbox_coords: bbox?.coord, is_correct: true,
    }).then(() => { queryClient.invalidateQueries({ queryKey: ['pageData'] }); handleFeedbackSubmitted(selectedElement.id) })
  }, [selectedElement, pageData, currentPage, documentId, queryClient, handleFeedbackSubmitted])

  // Element navigation
  const selectNextElement = useCallback(() => {
    if (!pageData || pageData.elements.length === 0) return
    if (selectedElementId === null) { setSelectedElementId(pageData.elements[0].id); return }
    const idx = pageData.elements.findIndex(e => e.id === selectedElementId)
    setSelectedElementId(pageData.elements[(idx + 1) % pageData.elements.length].id)
  }, [pageData, selectedElementId])

  const selectPrevElement = useCallback(() => {
    if (!pageData || pageData.elements.length === 0) return
    if (selectedElementId === null) { setSelectedElementId(pageData.elements[pageData.elements.length - 1].id); return }
    const idx = pageData.elements.findIndex(e => e.id === selectedElementId)
    setSelectedElementId(pageData.elements[(idx - 1 + pageData.elements.length) % pageData.elements.length].id)
  }, [pageData, selectedElementId])

  // Cross-page jump to next unreviewed
  const jumpToNextUnreviewed = useCallback(async () => {
    const allElements = doc?.parsed_result?.document?.elements || []
    if (allElements.length === 0) return
    // Find current element's position in the global list
    const currentGlobalIdx = selectedElementId !== null
      ? allElements.findIndex((e: Element) => e.id === selectedElementId)
      : -1
    // Search forward from current position
    const existingFeedback = await getDocumentFeedback(documentId!)
    const reviewedIds = new Set(existingFeedback.map(f => f.element_id))
    for (let offset = 1; offset <= allElements.length; offset++) {
      const idx = (currentGlobalIdx + offset) % allElements.length
      const elem = allElements[idx]
      if (!reviewedIds.has(elem.id)) {
        const pageId = elem.bbox?.[0]?.page_id ?? 0
        if (pageId !== currentPage) setCurrentPage(pageId)
        setSelectedElementId(elem.id)
        return
      }
    }
  }, [doc?.parsed_result, selectedElementId, currentPage, documentId])

  // Page navigation
  const commitPageInput = () => {
    const num = parseInt(pageInputValue)
    if (!isNaN(num) && num >= 1 && num <= totalPages) { setCurrentPage(num - 1); setSelectedElementId(null) }
    else setPageInputValue(String(currentPage + 1))
  }

  const goNextPage = useCallback(() => {
    if (filteredPages) {
      const idx = filteredPages.indexOf(currentPage)
      if (idx < filteredPages.length - 1) { setCurrentPage(filteredPages[idx + 1]); setSelectedElementId(null) }
    } else if (currentPage < totalPages - 1) { setCurrentPage(p => p + 1); setSelectedElementId(null) }
  }, [filteredPages, currentPage, totalPages])

  const goPrevPage = useCallback(() => {
    if (filteredPages) {
      const idx = filteredPages.indexOf(currentPage)
      if (idx > 0) { setCurrentPage(filteredPages[idx - 1]); setSelectedElementId(null) }
    } else if (currentPage > 0) { setCurrentPage(p => p - 1); setSelectedElementId(null) }
  }, [filteredPages, currentPage, totalPages])

  // Extended keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
      if (markAllDocCorrectMut.isPending || markPageCorrectMut.isPending) return

      switch (e.key) {
        case 'c': e.preventDefault(); quickMarkCorrect(); break
        case 'n': e.preventDefault(); selectNextElement(); break
        case 'p': e.preventDefault(); selectPrevElement(); break
        case 'ArrowRight': e.preventDefault(); goNextPage(); break
        case 'ArrowLeft': e.preventDefault(); goPrevPage(); break
        case 'u': e.preventDefault(); jumpToNextUnreviewed(); break
        case 'm': e.preventDefault(); markPageCorrectMut.mutate(); break
        case 'Escape':
          e.preventDefault()
          if (selectedElementId !== null) { setSelectedElementId(null); setElementListExpanded(true) }
          break
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [quickMarkCorrect, selectNextElement, selectPrevElement, goNextPage, goPrevPage, jumpToNextUnreviewed, selectedElementId])

  // Loading / error states
  if (docLoading) {
    return (
      <div className="flex items-center justify-center h-screen text-gray-500">
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
        <p className="text-gray-600">Analyzing your document...</p>
        <p className="text-sm text-gray-400 mt-1">Most documents finish in under 2 minutes. Large files (50+ pages) may take up to 10 minutes.</p>
      </div>
    )
  }

  if (doc.status !== 'parsed') {
    return (
      <div className="max-w-2xl mx-auto py-12 px-4 text-center text-gray-500">
        This document isn't ready for review yet (status: {doc.status}).
        <Link to="/documents" className="text-blue-600 ml-2 hover:underline">Back to documents</Link>
      </div>
    )
  }

  // Progress bar percentages
  const progressCorrect = docReviewStats.total > 0 ? (reviewStats.correct / docReviewStats.total) * 100 : 0
  const progressIssues = docReviewStats.total > 0 ? (reviewStats.issues / docReviewStats.total) * 100 : 0

  return (
    <div className="flex flex-col h-full bg-gray-50">
      {/* Compact toolbar */}
      <div className="h-10 bg-white border-b border-gray-200 px-3 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-3 min-w-0">
          <button onClick={() => navigate('/documents')} className="text-gray-400 hover:text-gray-700" title="Back to documents">
            <ArrowLeft className="w-4 h-4" />
          </button>
          <span className="text-sm font-medium text-gray-900 truncate max-w-[200px]">{doc.filename}</span>
          {doc.use_case_name && <span className="text-xs bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded-full">{doc.use_case_name}</span>}

          {/* Segmented progress bar */}
          <div className="flex items-center gap-2 ml-2">
            <div className="flex w-28 h-2 rounded-full overflow-hidden bg-gray-200">
              <div className="bg-green-500 transition-all duration-300" style={{ width: `${progressCorrect}%` }} />
              <div className="bg-red-500 transition-all duration-300" style={{ width: `${progressIssues}%` }} />
            </div>
            <span className="text-xs text-gray-500">{reviewStats.reviewed}/{reviewStats.total}</span>
          </div>
        </div>

        <div className="flex items-center gap-1.5">
          <button
            onClick={() => markAllDocCorrectMut.mutate()}
            disabled={markAllDocCorrectMut.isPending || markPageCorrectMut.isPending}
            className="flex items-center gap-1 px-2.5 py-1 text-xs bg-green-50 text-green-700 border border-green-200 rounded-lg hover:bg-green-100 disabled:opacity-50"
            title="Approve every element in this document"
          >
            {markAllDocCorrectMut.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <CheckCheck className="w-3.5 h-3.5" />}
            Approve all
          </button>
          <a
            href={reportUrl(documentId!)} target="_blank" rel="noopener noreferrer"
            className="p-1.5 text-gray-400 hover:text-gray-700 rounded hover:bg-gray-100" title="View report"
          >
            <FileTextIcon className="w-4 h-4" />
          </a>
          <button
            onClick={async () => {
              try {
                setMarkAllStatus('Starting export...')
                const { export_id, mode } = await startExport([documentId!])
                const isJob = mode === 'job'
                while (true) {
                  const s = await getExportStatus(export_id)
                  if (s.status === 'ready') { window.location.href = downloadExportUrl(export_id); setMarkAllStatus('Download started'); setTimeout(() => setMarkAllStatus(null), 3000); return }
                  if (s.status === 'error') { setMarkAllStatus(`Export error: ${s.error}`); return }
                  setMarkAllStatus(isJob ? `Exporting... ${s.progress || ''}` : (s.progress || 'Exporting...'))
                  await new Promise(r => setTimeout(r, isJob ? 5000 : 2000))
                }
              } catch (e) { setMarkAllStatus(`Export failed: ${(e as Error).message}`) }
            }}
            className="p-1.5 text-gray-400 hover:text-gray-700 rounded hover:bg-gray-100" title="Download as ZIP"
          >
            <Download className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Status bar for bulk operations */}
      {(markAllDocCorrectMut.isPending || markPageCorrectMut.isPending || markAllStatus) && (
        <div className={`px-3 py-1.5 text-xs flex items-center gap-2 shrink-0 ${
          markAllStatus && !markAllDocCorrectMut.isPending && !markPageCorrectMut.isPending
            ? (markAllStatus.startsWith('Error') ? 'bg-red-100 text-red-700' : 'bg-green-100 text-green-700')
            : 'bg-blue-100 text-blue-700'
        }`}>
          {(markAllDocCorrectMut.isPending || markPageCorrectMut.isPending) && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
          {markAllStatus || (markPageCorrectMut.isPending ? 'Approving page elements...' : 'Processing...')}
        </div>
      )}

      {/* Main content: resizable split */}
      <div className="flex-1 min-h-0 flex" ref={containerRef}>
        {/* Left: Annotator */}
        <div className="flex-1 min-w-0">
          <div className="flex flex-col h-full">
            {/* Page navigator */}
            <div className="h-9 flex items-center justify-center gap-3 bg-gray-50 border-b border-gray-100 shrink-0">
              <button onClick={goPrevPage} disabled={filteredPages ? filteredPages.indexOf(currentPage) <= 0 : currentPage === 0} className="p-0.5 rounded hover:bg-gray-200 disabled:opacity-30">
                <ChevronLeft className="w-4 h-4" />
              </button>
              <div className="flex items-center gap-1.5 text-sm">
                <span className="text-gray-500">Page</span>
                <input
                  type="number" min={1} max={totalPages} value={pageInputValue}
                  onChange={(e) => setPageInputValue(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') { commitPageInput(); (e.target as HTMLInputElement).blur() } }}
                  onBlur={commitPageInput}
                  className="w-12 text-center text-sm font-medium bg-white border border-gray-300 rounded px-1 py-0.5 focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                <span className="text-gray-500">of {totalPages}</span>
                {filteredPages && <span className="text-xs text-blue-600">({filteredPages.length} match)</span>}
              </div>
              <button onClick={goNextPage} disabled={filteredPages ? filteredPages.indexOf(currentPage) >= filteredPages.length - 1 : currentPage >= totalPages - 1} className="p-0.5 rounded hover:bg-gray-200 disabled:opacity-30">
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>

            {/* Page image */}
            <div ref={annotatorRef} key={currentPage} className="flex-1 overflow-auto p-4 bg-gray-100 animate-page-enter">
              {pageLoading ? (
                <div className="flex items-center justify-center h-64 text-gray-500">
                  <Loader2 className="w-5 h-5 animate-spin mr-2" /> Rendering page {currentPage + 1}...
                </div>
              ) : pageData ? (
                <PageAnnotator
                  imageDataUri={pageData.image?.data_uri || null}
                  imageWidth={pageData.image?.width || 800}
                  imageHeight={pageData.image?.height || 1000}
                  maxWidth={annotatorWidth > 0 ? annotatorWidth : undefined}
                  pdfUrl={!pageData.image ? getDocumentPdfUrl(documentId!) : null}
                  pageNumber={currentPage + 1}
                  elements={visibleElements}
                  pageId={currentPage}
                  selectedElementId={selectedElementId}
                  feedbackMap={pageData.feedback}
                  qualityFlags={pageData.quality_flags}
                  onSelectElement={setSelectedElementId}
                />
              ) : (
                <div className="text-gray-400 text-center py-12">Nothing to show on this page</div>
              )}
            </div>
          </div>
        </div>

        {/* Resize handle */}
        <div
          onMouseDown={handleDragStart}
          className="w-1.5 bg-gray-200 hover:bg-blue-400 active:bg-blue-500 transition-colors cursor-col-resize shrink-0"
        />

        {/* Right: Inspector panel */}
        <div style={{ width: `${inspectorPct}%` }} className="shrink-0">
          <div className="flex flex-col h-full bg-white">
            {/* Filter chips */}
            {allElementTypes.length > 1 && (
              <div className="p-2 border-b border-gray-100 flex flex-wrap gap-1.5 items-center shrink-0">
                <Filter className="w-3.5 h-3.5 text-gray-400 shrink-0" />
                {allElementTypes.map(type => {
                  const active = activeTypeFilters.has(type)
                  const color = ELEMENT_COLORS[type] || '#BDC3C7'
                  return (
                    <button key={type} onClick={() => toggleTypeFilter(type)}
                      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium border transition-colors ${
                        active ? 'border-current' : 'border-gray-200 text-gray-500 hover:border-gray-300'
                      }`}
                      style={active ? { color, borderColor: color, backgroundColor: color + '20' } : undefined}
                    >
                      <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: color }} />
                      {type.replace('_', ' ')}
                    </button>
                  )
                })}
                {activeTypeFilters.size > 0 && (
                  <button onClick={() => setActiveTypeFilters(new Set())} className="inline-flex items-center gap-0.5 px-1.5 py-0.5 text-xs text-gray-400 hover:text-gray-600">
                    <X className="w-3 h-3" /> Clear
                  </button>
                )}
              </div>
            )}

            {/* Element list header */}
            <div className="p-2.5 border-b border-gray-100 flex items-center justify-between shrink-0">
              <button onClick={() => setElementListExpanded(!elementListExpanded)}
                className="text-xs font-semibold text-gray-500 uppercase tracking-wider flex items-center gap-1 hover:text-gray-700"
              >
                <ChevronRight className={`w-3 h-3 transition-transform ${elementListExpanded ? 'rotate-90' : ''}`} />
                Elements ({visibleElements.length}{activeTypeFilters.size > 0 && pageData ? `/${pageData.elements.length}` : ''})
              </button>
              {reviewStats.unreviewed > 0 && (
                <button onClick={() => markPageCorrectMut.mutate()}
                  disabled={markPageCorrectMut.isPending || markAllDocCorrectMut.isPending}
                  className="flex items-center gap-1 px-2 py-0.5 text-xs bg-green-50 text-green-700 border border-green-200 rounded-md hover:bg-green-100 disabled:opacity-50"
                  title={`Approve ${reviewStats.unreviewed} remaining on this page (M)`}
                >
                  {markPageCorrectMut.isPending ? <Loader2 className="w-3 h-3 animate-spin" /> : <CheckCheck className="w-3 h-3" />}
                  Approve {reviewStats.unreviewed}
                </button>
              )}
            </div>

            {/* Element list */}
            <div className={`overflow-y-auto transition-all duration-200 ${
              selectedElement ? elementListExpanded ? 'max-h-[45%] shrink-0' : 'max-h-0 overflow-hidden shrink-0' : 'flex-1'
            }`}
              role="listbox" aria-label="Page elements"
            >
              <div className="divide-y divide-gray-100">
                {pageData && visibleElements.slice().sort((a, b) => {
                  const aFlagged = !!(pageData.quality_flags?.[a.id]?.length) && !(a.id in pageData.feedback)
                  const bFlagged = !!(pageData.quality_flags?.[b.id]?.length) && !(b.id in pageData.feedback)
                  if (aFlagged !== bFlagged) return aFlagged ? -1 : 1
                  return 0
                }).map((elem: Element) => {
                  const fb = pageData.feedback[elem.id]
                  const isSelected = elem.id === selectedElementId
                  const flags = pageData.quality_flags?.[elem.id]
                  return (
                    <button key={elem.id} ref={isSelected ? selectedElementRef : undefined}
                      onClick={() => setSelectedElementId(elem.id)}
                      role="option" aria-selected={isSelected}
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
                        <p className="text-xs text-gray-400 truncate mt-0.5">{elem.content.replace(/<[^>]*>/g, '').slice(0, 60)}</p>
                      )}
                    </button>
                  )
                })}
              </div>
            </div>

            {/* Feedback form */}
            {selectedElement && (
              <div className="border-t border-gray-200 p-3 overflow-y-auto flex-1 min-h-0">
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
              <div className="border-t border-gray-200 p-6 text-center text-gray-400 text-sm flex-1 flex items-center justify-center">
                <div>
                  <p>Select an element to review</p>
                  <p className="text-xs mt-1">Click any highlighted region, or press <kbd className="bg-gray-100 px-1 rounded">N</kbd></p>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Persistent keyboard hint bar */}
      <div className="h-7 bg-gray-50 border-t border-gray-200 px-3 flex items-center justify-between text-xs text-gray-400 shrink-0">
        <span>{selectedElement ? `#${selectedElement.id} ${selectedElement.type}` : 'No element selected'}</span>
        <span className="flex items-center gap-3">
          <span><kbd className="bg-gray-200 text-gray-600 px-1 rounded">C</kbd> correct</span>
          <span><kbd className="bg-gray-200 text-gray-600 px-1 rounded">I</kbd> incorrect</span>
          <span><kbd className="bg-gray-200 text-gray-600 px-1 rounded">U</kbd> next unreviewed</span>
          <span><kbd className="bg-gray-200 text-gray-600 px-1 rounded">N</kbd>/<kbd className="bg-gray-200 text-gray-600 px-1 rounded">P</kbd> nav</span>
          <span><kbd className="bg-gray-200 text-gray-600 px-1 rounded">M</kbd> approve page</span>
          <span><kbd className="bg-gray-200 text-gray-600 px-1 rounded">Esc</kbd> deselect</span>
        </span>
      </div>
    </div>
  )
}
