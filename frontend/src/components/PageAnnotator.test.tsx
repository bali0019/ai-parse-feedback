import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import PageAnnotator from './PageAnnotator'
import type { Element } from '../lib/types'

const elements: Element[] = [
  {
    id: 1, type: 'text', content: 'Hello world',
    bbox: [{ page_id: 0, coord: [50, 50, 300, 80] }],
  },
  {
    id: 2, type: 'table', content: '<table></table>',
    bbox: [{ page_id: 0, coord: [50, 100, 500, 300] }],
  },
  {
    id: 3, type: 'text', content: 'Page 2 only',
    bbox: [{ page_id: 1, coord: [50, 50, 300, 80] }],
  },
]

const baseProps = {
  imageDataUri: 'data:image/png;base64,abc123',
  imageWidth: 800,
  imageHeight: 1000,
  elements,
  pageId: 0,
  selectedElementId: null,
  feedbackMap: {},
  onSelectElement: vi.fn(),
}

describe('PageAnnotator', () => {
  it('renders image with correct dimensions', () => {
    const { container } = render(<PageAnnotator {...baseProps} />)
    const img = container.querySelector('img')
    expect(img).toBeTruthy()
    expect(img!.style.width).toBe('800px')
    expect(img!.style.height).toBe('1000px')
  })

  it('renders bbox overlays only for current page', () => {
    const { container } = render(<PageAnnotator {...baseProps} />)
    // Only 2 elements on page 0 (ids 1, 2), not element 3 (page 1)
    const overlays = container.querySelectorAll('[title]')
    expect(overlays.length).toBe(2)
  })

  it('click on bbox calls onSelectElement', () => {
    const onSelect = vi.fn()
    const { container } = render(<PageAnnotator {...baseProps} onSelectElement={onSelect} />)
    const overlays = container.querySelectorAll('[title]')
    fireEvent.click(overlays[0])
    expect(onSelect).toHaveBeenCalledWith(1) // element id 1
  })

  it('selected element gets blue border', () => {
    const { container } = render(<PageAnnotator {...baseProps} selectedElementId={2} />)
    const overlays = container.querySelectorAll('[title]')
    const selectedOverlay = Array.from(overlays).find(el => el.getAttribute('title')?.includes('#2'))
    expect(selectedOverlay).toBeTruthy()
    expect((selectedOverlay as HTMLElement).style.border).toContain('rgb(37, 99, 235)')
  })

  it('shows message when no image', () => {
    render(<PageAnnotator {...baseProps} imageDataUri={null} />)
    expect(screen.getByText(/No image available/)).toBeTruthy()
  })
})
