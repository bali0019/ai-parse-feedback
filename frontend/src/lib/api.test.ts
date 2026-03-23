import { describe, it, expect, vi, beforeEach } from 'vitest'
import { listDocuments, uploadDocument, submitFeedback, getPageData, exportDocumentUrl } from './api'

beforeEach(() => {
  vi.restoreAllMocks()
})

describe('API client', () => {
  it('listDocuments calls GET /api/documents', async () => {
    const mockDocs = [{ document_id: '1', filename: 'test.pdf' }]
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => mockDocs,
    } as Response)

    const result = await listDocuments()
    expect(result).toEqual(mockDocs)
    expect(fetch).toHaveBeenCalledWith('/api/documents', undefined)
  })

  it('uploadDocument sends FormData POST', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ document_id: 'abc', status: 'uploaded' }),
    } as Response)

    const file = new File(['content'], 'test.pdf', { type: 'application/pdf' })
    const result = await uploadDocument(file)
    expect(result.document_id).toBe('abc')

    const [url, opts] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(url).toBe('/api/documents/upload')
    expect(opts.method).toBe('POST')
    expect(opts.body).toBeInstanceOf(FormData)
  })

  it('submitFeedback sends JSON POST', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ feedback_id: 'fb1' }),
    } as Response)

    const result = await submitFeedback({
      document_id: 'doc1',
      element_id: 5,
      page_id: 0,
      is_correct: false,
      issue_category: 'ocr_error',
    })
    expect(result.feedback_id).toBe('fb1')

    const [, opts] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(opts.headers['Content-Type']).toBe('application/json')
    expect(JSON.parse(opts.body).element_id).toBe(5)
  })

  it('throws on non-OK response', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: false,
      status: 404,
      text: async () => 'Not found',
    } as Response)

    await expect(listDocuments()).rejects.toThrow('404: Not found')
  })

  it('getPageData calls correct URL with page ID', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ page_id: 3 }),
    } as Response)

    await getPageData('doc-1', 3)
    expect(fetch).toHaveBeenCalledWith('/api/documents/doc-1/page/3', undefined)
  })

  it('exportDocumentUrl builds correct URL', () => {
    expect(exportDocumentUrl('abc-123')).toBe('/api/export/document/abc-123')
  })
})
