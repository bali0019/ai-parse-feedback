/**
 * Feedback form for a selected element: correct/incorrect, issue category, comment.
 */

import { useState, useEffect } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle, XCircle, Loader2, Save, Sparkles, Copy } from 'lucide-react'
import { submitFeedback, getConfig, runAiQuery } from '../lib/api'
import type { Element, Feedback } from '../lib/types'

interface Props {
  documentId: string
  element: Element
  pageId: number
  existingFeedback: Feedback | null
  onSubmitSuccess?: (elementId: number) => void
}

export default function FeedbackForm({ documentId, element, pageId, existingFeedback, onSubmitSuccess }: Props) {
  const queryClient = useQueryClient()
  const { data: config } = useQuery({ queryKey: ['config'], queryFn: getConfig })

  const [isCorrect, setIsCorrect] = useState<boolean | null>(null)
  const [category, setCategory] = useState('')
  const [comment, setComment] = useState('')
  const [suggestedContent, setSuggestedContent] = useState('')
  const [suggestedType, setSuggestedType] = useState('')
  const [showAiQuery, setShowAiQuery] = useState(false)
  const [aiPrompt, setAiPrompt] = useState('')
  const [aiResult, setAiResult] = useState<string | null>(null)
  const [aiLoading, setAiLoading] = useState(false)
  const [aiError, setAiError] = useState<string | null>(null)

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
    setAiError(null)
  }, [existingFeedback, element.id])

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
      queryClient.invalidateQueries({ queryKey: ['pageData'] })
      onSubmitSuccess?.(element.id)
    },
  })

  const categories = config?.issue_categories || []

  return (
    <div className="space-y-4">
      {/* Element info */}
      <div className="bg-gray-50 rounded-lg p-3">
        <div className="text-xs text-gray-500 uppercase font-medium mb-1">
          {element.type} #{element.id}
        </div>
        {element.content && (
          <div className="text-sm text-gray-700 max-h-64 overflow-y-auto">
            {element.type === 'table' ? (
              <div className="text-xs" dangerouslySetInnerHTML={{ __html: element.content }} />
            ) : (
              <p className="whitespace-pre-wrap">{element.content}</p>
            )}
          </div>
        )}
        {element.description && !element.content && (
          <p className="text-sm text-gray-500 italic max-h-64 overflow-y-auto">{element.description}</p>
        )}
        {!element.content && !element.description && (
          <p className="text-sm text-gray-400 italic">No content</p>
        )}
      </div>

      {/* Re-parse with ai_query */}
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
          {showAiQuery ? 'Hide ai_query' : 'Re-parse with ai_query'}
        </button>

        {showAiQuery && (
          <div className="mt-3 space-y-2">
            <textarea
              value={aiPrompt}
              onChange={(e) => setAiPrompt(e.target.value)}
              placeholder="Enter your prompt..."
              rows={3}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500 resize-none"
            />
            <button
              onClick={async () => {
                setAiLoading(true)
                setAiError(null)
                setAiResult(null)
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

            {aiError && (
              <p className="text-xs text-red-600">{aiError}</p>
            )}

            {aiResult && (
              <div className="bg-gray-50 border border-gray-200 rounded-lg p-3">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-medium text-gray-500 uppercase">ai_query Result</span>
                  <button
                    onClick={() => navigator.clipboard.writeText(aiResult)}
                    className="p-1 text-gray-400 hover:text-gray-600 rounded"
                    title="Copy to clipboard"
                  >
                    <Copy className="w-3.5 h-3.5" />
                  </button>
                </div>
                <pre className="text-xs text-gray-700 whitespace-pre-wrap max-h-48 overflow-y-auto">{aiResult}</pre>
                <button
                  onClick={() => {
                    setIsCorrect(false)
                    setSuggestedContent(aiResult)
                    setComment(`ai_query suggested different content (model: databricks-claude-sonnet-4)`)
                  }}
                  className="w-full mt-3 flex items-center justify-center gap-2 px-3 py-2 text-sm bg-purple-600 text-white rounded-lg hover:bg-purple-700 font-medium"
                >
                  <Sparkles className="w-4 h-4" />
                  Apply as Suggested Correction
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Correct / Incorrect */}
      <div>
        <label className="text-sm font-medium text-gray-700 block mb-2">Is this correct?</label>
        <div className="flex gap-2">
          <button
            onClick={() => setIsCorrect(true)}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg border text-sm font-medium transition-colors ${
              isCorrect === true
                ? 'bg-green-50 border-green-300 text-green-700'
                : 'border-gray-200 text-gray-600 hover:bg-gray-50'
            }`}
          >
            <CheckCircle className="w-4 h-4" /> Correct
          </button>
          <button
            onClick={() => setIsCorrect(false)}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg border text-sm font-medium transition-colors ${
              isCorrect === false
                ? 'bg-red-50 border-red-300 text-red-700'
                : 'border-gray-200 text-gray-600 hover:bg-gray-50'
            }`}
          >
            <XCircle className="w-4 h-4" /> Incorrect
          </button>
        </div>
      </div>

      {/* Issue category (shown when incorrect) */}
      {isCorrect === false && (
        <div>
          <label className="text-sm font-medium text-gray-700 block mb-1">Issue Category</label>
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">Select category...</option>
            {categories.map((c) => (
              <option key={c.value} value={c.value}>{c.label}</option>
            ))}
          </select>
        </div>
      )}

      {/* Comment */}
      <div>
        <label className="text-sm font-medium text-gray-700 block mb-1">Comment</label>
        <textarea
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder="Describe the issue..."
          rows={3}
          className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
        />
      </div>

      {/* Suggested corrections (shown when incorrect) */}
      {isCorrect === false && (
        <>
          <div>
            <label className="text-sm font-medium text-gray-700 block mb-1">Suggested Corrected Content</label>
            <textarea
              value={suggestedContent}
              onChange={(e) => setSuggestedContent(e.target.value)}
              placeholder="What should the content be?"
              rows={2}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
            />
          </div>
          <div>
            <label className="text-sm font-medium text-gray-700 block mb-1">Suggested Element Type</label>
            <select
              value={suggestedType}
              onChange={(e) => setSuggestedType(e.target.value)}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="">Keep current type</option>
              {['text', 'table', 'figure', 'section_header', 'caption', 'page_header', 'page_footer', 'list'].map(t => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>
        </>
      )}

      {/* Submit */}
      <button
        onClick={() => mutation.mutate()}
        disabled={isCorrect === null || mutation.isPending}
        className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed font-medium text-sm"
      >
        {mutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
        {existingFeedback ? 'Update Feedback' : 'Submit Feedback'}
      </button>

      {mutation.isSuccess && (
        <p className="text-sm text-green-600 text-center">Saved!</p>
      )}
      {mutation.isError && (
        <p className="text-sm text-red-600">{(mutation.error as Error).message}</p>
      )}
    </div>
  )
}
