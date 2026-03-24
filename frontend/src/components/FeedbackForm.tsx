/**
 * Feedback form: correct/incorrect, issue category chips, comment, ai re-extraction.
 * V2: auto-grow textareas, expandable AI result, category chips, green flash on save.
 */

import { useState, useEffect, useRef } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle, XCircle, Loader2, Save, Sparkles, Copy } from 'lucide-react'
import { submitFeedback, getConfig, runAiQuery } from '../lib/api'
import { ELEMENT_TYPES } from '../lib/constants'
import type { Element, Feedback } from '../lib/types'

interface Props {
  documentId: string
  element: Element
  pageId: number
  existingFeedback: Feedback | null
  onSubmitSuccess?: (elementId: number) => void
}

/** Auto-resize a textarea to fit its content up to maxPx. */
function autoGrow(el: HTMLTextAreaElement | null, maxPx: number) {
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, maxPx) + 'px'
}

export default function FeedbackForm({ documentId, element, pageId, existingFeedback, onSubmitSuccess }: Props) {
  const queryClient = useQueryClient()
  const { data: config } = useQuery({ queryKey: ['config'], queryFn: getConfig })

  const [isCorrect, setIsCorrect] = useState<boolean | null>(null)
  const [category, setCategory] = useState('')
  const [comment, setComment] = useState('')
  const [suggestedContent, setSuggestedContent] = useState('')
  const [suggestedType, setSuggestedType] = useState('')
  const [showFlash, setShowFlash] = useState(false)

  // ai_query state
  const [showAiQuery, setShowAiQuery] = useState(false)
  const [aiPrompt, setAiPrompt] = useState('')
  const [aiResult, setAiResult] = useState<string | null>(null)
  const [aiResultExpanded, setAiResultExpanded] = useState(false)
  const [aiResultApplied, setAiResultApplied] = useState(false)
  const [aiLoading, setAiLoading] = useState(false)
  const [aiError, setAiError] = useState<string | null>(null)
  const [contentExpanded, setContentExpanded] = useState(false)

  // Refs for auto-growing textareas
  const commentRef = useRef<HTMLTextAreaElement>(null)
  const suggestedRef = useRef<HTMLTextAreaElement>(null)

  // Load existing feedback when element changes
  useEffect(() => {
    if (existingFeedback) {
      setIsCorrect(existingFeedback.is_correct)
      setCategory(existingFeedback.issue_category || '')
      setComment(existingFeedback.comment || '')
      setSuggestedContent(existingFeedback.suggested_content || '')
      setSuggestedType(existingFeedback.suggested_type || '')
    } else {
      setIsCorrect(null)
      setCategory('')
      setComment('')
      setSuggestedContent('')
      setSuggestedType('')
    }
    setShowAiQuery(false)
    setAiResult(null)
    setAiResultExpanded(false)
    setAiResultApplied(false)
    setAiError(null)
    setShowFlash(false)
    setContentExpanded(false)
  }, [existingFeedback, element.id])

  // Auto-grow textareas when content changes programmatically
  useEffect(() => { autoGrow(commentRef.current, 200) }, [comment])
  useEffect(() => { autoGrow(suggestedRef.current, 300) }, [suggestedContent])

  const mutation = useMutation({
    mutationFn: () => {
      const bbox = element.bbox?.find(b => b.page_id === pageId)
      return submitFeedback({
        document_id: documentId,
        element_id: element.id,
        page_id: pageId,
        element_type: element.type,
        bbox_coords: bbox?.coord,
        is_correct: isCorrect ?? undefined,
        issue_category: isCorrect === false ? category || undefined : undefined,
        comment: comment || undefined,
        suggested_content: suggestedContent || undefined,
        suggested_type: suggestedType || undefined,
      })
    },
    onSuccess: () => {
      setShowFlash(true)
      setTimeout(() => setShowFlash(false), 600)
      queryClient.invalidateQueries({ queryKey: ['pageData'] })
      onSubmitSuccess?.(element.id)
    },
  })

  const categories = config?.issue_categories || []

  return (
    <div className="space-y-3">
      {/* Element info — collapsible */}
      <div className="bg-gray-50 rounded-lg p-2.5">
        <div className="flex items-center justify-between">
          <div className="text-xs text-gray-500 uppercase font-medium">
            {element.type} #{element.id}
          </div>
          {(element.content || element.description) && (
            <button onClick={() => setContentExpanded(!contentExpanded)} className="text-xs text-blue-600 hover:text-blue-700">
              {contentExpanded ? 'Collapse' : 'Show content'}
            </button>
          )}
        </div>
        {!contentExpanded && element.content && (
          <p className="text-xs text-gray-400 truncate mt-1">{element.content.replace(/<[^>]*>/g, '').slice(0, 80)}</p>
        )}
        {contentExpanded && element.content && (
          <div className="text-sm text-gray-700 max-h-[50vh] overflow-y-auto overflow-x-auto mt-1">
            {element.type === 'table' ? (
              <div className="text-xs overflow-x-auto" dangerouslySetInnerHTML={{ __html: element.content }} />
            ) : (
              <p className="whitespace-pre-wrap">{element.content}</p>
            )}
          </div>
        )}
        {contentExpanded && element.description && !element.content && (
          <p className="text-sm text-gray-500 italic max-h-[50vh] overflow-y-auto mt-1">{element.description}</p>
        )}
        {!element.content && !element.description && (
          <p className="text-xs text-gray-400 italic mt-1">No text was extracted for this element</p>
        )}
      </div>

      {/* Ask AI to re-read */}
      <div>
        <button
          onClick={() => {
            if (!showAiQuery) {
              const defaults: Record<string, string> = {
                table: 'Extract the table structure with all rows and columns from this image. Return as markdown table.',
                text: 'Extract all text content from this image region exactly as it appears.',
                figure: 'Describe what is shown in this image region in detail.',
                section_header: 'Extract the heading/title text from this image region.',
                list: 'Extract all list items from this image region.',
                caption: 'Extract the caption text from this image region.',
              }
              setAiPrompt(defaults[element.type] || 'What content is in this image region? Extract it accurately.')
            }
            setShowAiQuery(!showAiQuery)
          }}
          className="w-full flex items-center justify-center gap-2 px-3 py-2 text-sm border border-purple-200 text-purple-700 bg-purple-50 rounded-lg hover:bg-purple-100 transition-colors font-medium"
        >
          <Sparkles className="w-4 h-4" />
          {showAiQuery ? 'Hide ai_query' : 'Re-extract with ai_query'}
        </button>

        {showAiQuery && (
          <div className="mt-2 space-y-2">
            <textarea
              value={aiPrompt}
              onChange={(e) => setAiPrompt(e.target.value)}
              placeholder="Enter your prompt..."
              rows={3}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500/40 focus:border-purple-500 resize-y min-h-[60px] max-h-[200px]"
            />
            <button
              onClick={async () => {
                setAiLoading(true)
                setAiError(null)
                setAiResult(null)
                setAiResultApplied(false)
                setAiResultExpanded(false)
                try {
                  const res = await runAiQuery(documentId, element.id, pageId, aiPrompt)
                  setAiResult(res.result)
                } catch (e) {
                  setAiError((e as Error).message)
                } finally {
                  setAiLoading(false)
                }
              }}
              disabled={aiLoading || !aiPrompt.trim()}
              className="w-full flex items-center justify-center gap-2 px-3 py-2 text-sm bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50 font-medium"
            >
              {aiLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
              {aiLoading ? 'Running ai_query...' : 'Run'}
            </button>

            {aiError && <p className="text-xs text-red-600">{aiError}</p>}

            {aiResult && !aiResultApplied && (
              <div className="bg-gray-50 border border-gray-200 rounded-lg p-3">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-medium text-gray-500 uppercase">ai_query Result</span>
                  <button onClick={() => navigator.clipboard.writeText(aiResult)} className="p-1 text-gray-400 hover:text-gray-600 rounded" title="Copy">
                    <Copy className="w-3.5 h-3.5" />
                  </button>
                </div>
                <pre className={`text-xs text-gray-700 whitespace-pre-wrap overflow-y-auto ${aiResultExpanded ? 'max-h-[60vh]' : 'max-h-64'}`}>
                  {aiResult}
                </pre>
                {aiResult.length > 500 && (
                  <button onClick={() => setAiResultExpanded(!aiResultExpanded)} className="text-xs text-blue-600 hover:text-blue-700 mt-1">
                    {aiResultExpanded ? 'Collapse' : 'Show full result'}
                  </button>
                )}
                <button
                  onClick={() => {
                    setIsCorrect(false)
                    setSuggestedContent(aiResult)
                    setComment(`ai_query suggested different content (model: databricks-claude-sonnet-4)\n\nPrompt used:\n${aiPrompt}`)
                    setAiResultApplied(true)
                  }}
                  className="w-full mt-3 flex items-center justify-center gap-2 px-3 py-2 text-sm bg-purple-600 text-white rounded-lg hover:bg-purple-700 font-medium"
                >
                  <Sparkles className="w-4 h-4" />
                  Use this as the correction
                </button>
              </div>
            )}

            {aiResultApplied && (
              <button
                onClick={() => setAiResultApplied(false)}
                className="w-full text-left px-3 py-2 text-xs text-purple-600 bg-purple-50 rounded-lg border border-purple-200 hover:bg-purple-100"
              >
                ai_query suggestion applied. Click to review.
              </button>
            )}
          </div>
        )}
      </div>

      {/* Correct / Incorrect */}
      <div>
        <label className="text-xs font-medium text-gray-500 uppercase tracking-wider block mb-1.5">Is this correct?</label>
        <div className="flex gap-2">
          <button
            onClick={() => setIsCorrect(true)}
            className={`flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded-lg border text-sm font-medium transition-colors ${
              isCorrect === true
                ? 'bg-green-50 border-green-300 text-green-700 ring-1 ring-green-200'
                : 'border-gray-200 text-gray-600 hover:bg-gray-50'
            }`}
          >
            <CheckCircle className="w-4 h-4" /> Correct
          </button>
          <button
            onClick={() => setIsCorrect(false)}
            className={`flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded-lg border text-sm font-medium transition-colors ${
              isCorrect === false
                ? 'bg-red-50 border-red-300 text-red-700 ring-1 ring-red-200'
                : 'border-gray-200 text-gray-600 hover:bg-gray-50'
            }`}
          >
            <XCircle className="w-4 h-4" /> Incorrect
          </button>
        </div>
      </div>

      {/* Issue category chips (shown when incorrect) */}
      {isCorrect === false && (
        <div>
          <label className="text-xs font-medium text-gray-500 uppercase tracking-wider block mb-1.5">What went wrong?</label>
          <div className="flex flex-wrap gap-1.5">
            {categories.map((c) => (
              <button
                key={c.value}
                type="button"
                onClick={() => setCategory(category === c.value ? '' : c.value)}
                title={c.description}
                className={`px-2 py-1 rounded-lg text-xs font-medium border transition-colors ${
                  category === c.value
                    ? 'bg-blue-50 border-blue-300 text-blue-700 ring-1 ring-blue-200'
                    : 'border-gray-200 text-gray-600 hover:bg-gray-50 hover:border-gray-300'
                }`}
              >
                {c.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Comment */}
      <div>
        <label className="text-xs font-medium text-gray-500 uppercase tracking-wider block mb-1.5">Comment</label>
        <textarea
          ref={commentRef}
          value={comment}
          onChange={(e) => { setComment(e.target.value); autoGrow(e.target, 200) }}
          placeholder="What's wrong? e.g., 'Table is missing the last two columns'"
          rows={2}
          className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500 resize-y min-h-[48px] max-h-[200px]"
        />
      </div>

      {/* Suggested corrections (shown when incorrect) */}
      {isCorrect === false && (
        <>
          <div>
            <label className="text-xs font-medium text-gray-500 uppercase tracking-wider block mb-1.5">Suggested Corrected Content</label>
            <textarea
              ref={suggestedRef}
              value={suggestedContent}
              onChange={(e) => { setSuggestedContent(e.target.value); autoGrow(e.target, 300) }}
              placeholder="Paste or type the correct content here"
              rows={3}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500 resize-y min-h-[72px] max-h-[300px]"
            />
          </div>
          <div>
            <label className="text-xs font-medium text-gray-500 uppercase tracking-wider block mb-1.5">Suggested Element Type</label>
            <select
              value={suggestedType}
              onChange={(e) => setSuggestedType(e.target.value)}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500"
            >
              <option value="">Keep current type</option>
              {ELEMENT_TYPES.map(t => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>
        </>
      )}

      {/* Submit — sticky at bottom */}
      <div className="sticky bottom-0 pt-3 -mx-3 px-3 pb-1 bg-gradient-to-t from-white via-white to-transparent">
        <button
          onClick={() => mutation.mutate()}
          disabled={isCorrect === null || mutation.isPending}
          className={`w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed font-medium text-sm transition-colors ${
            showFlash
              ? 'bg-green-500 text-white animate-feedback-flash'
              : 'bg-blue-600 text-white hover:bg-blue-700'
          }`}
        >
          {mutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
          {existingFeedback ? 'Update feedback' : 'Save feedback'}
        </button>
      </div>

      {mutation.isError && (
        <p className="text-xs text-red-600">{(mutation.error as Error).message}</p>
      )}
    </div>
  )
}
