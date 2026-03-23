import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import FeedbackForm from './FeedbackForm'
import type { Element } from '../lib/types'

// Mock the API module
vi.mock('../lib/api', () => ({
  submitFeedback: vi.fn().mockResolvedValue({ feedback_id: 'fb1' }),
  getConfig: vi.fn().mockResolvedValue({
    issue_categories: [
      { value: 'ocr_error', label: 'OCR Error', description: 'Characters misread' },
      { value: 'table_structure_error', label: 'Table Structure Error', description: 'Bad table' },
    ],
    element_colors: {},
  }),
}))

const element: Element = {
  id: 5,
  type: 'text',
  content: 'Hello world sample content for testing',
  bbox: [{ page_id: 0, coord: [10, 20, 300, 40] }],
}

function renderWithProviders(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('FeedbackForm', () => {
  it('renders element info', () => {
    renderWithProviders(
      <FeedbackForm documentId="doc1" element={element} pageId={0} existingFeedback={null} />
    )
    expect(screen.getByText(/text #5/i)).toBeTruthy()
    expect(screen.getByText(/Hello world sample/)).toBeTruthy()
  })

  it('clicking Correct sets state', () => {
    renderWithProviders(
      <FeedbackForm documentId="doc1" element={element} pageId={0} existingFeedback={null} />
    )
    const correctBtn = screen.getByText('Correct')
    fireEvent.click(correctBtn)
    // Button should have green styling
    expect(correctBtn.closest('button')?.className).toContain('green')
  })

  it('clicking Incorrect shows category chips', async () => {
    renderWithProviders(
      <FeedbackForm documentId="doc1" element={element} pageId={0} existingFeedback={null} />
    )
    fireEvent.click(screen.getByText('Incorrect'))

    await waitFor(() => {
      expect(screen.getByText('What went wrong?')).toBeTruthy()
    })
  })

  it('submit button is disabled when no choice made', () => {
    renderWithProviders(
      <FeedbackForm documentId="doc1" element={element} pageId={0} existingFeedback={null} />
    )
    const submitBtn = screen.getByText('Save feedback')
    expect(submitBtn.closest('button')?.disabled).toBe(true)
  })

  it('submit button enabled after selecting correct/incorrect', () => {
    renderWithProviders(
      <FeedbackForm documentId="doc1" element={element} pageId={0} existingFeedback={null} />
    )
    fireEvent.click(screen.getByText('Correct'))
    const submitBtn = screen.getByText('Save feedback')
    expect(submitBtn.closest('button')?.disabled).toBe(false)
  })
})
