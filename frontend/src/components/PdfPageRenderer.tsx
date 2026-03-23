/**
 * Renders a single PDF page using PDF.js and returns dimensions for bbox overlay.
 */

import { useEffect, useRef, useState } from 'react'
import * as pdfjsLib from 'pdfjs-dist'

// Use the bundled worker
pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.mjs',
  import.meta.url,
).toString()

interface Props {
  pdfUrl: string
  pageNumber: number // 1-indexed
  maxWidth?: number
  onDimensionsReady?: (width: number, height: number) => void
}

export default function PdfPageRenderer({ pdfUrl, pageNumber, maxWidth = 900, onDimensionsReady }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    async function render() {
      setLoading(true)
      setError(null)

      try {
        const pdf = await pdfjsLib.getDocument(pdfUrl).promise
        if (cancelled) return

        if (pageNumber < 1 || pageNumber > pdf.numPages) {
          setError(`Page ${pageNumber} out of range (1-${pdf.numPages})`)
          return
        }

        const page = await pdf.getPage(pageNumber)
        if (cancelled) return

        // Get natural viewport at scale 1
        const naturalViewport = page.getViewport({ scale: 1 })

        // Scale to fit maxWidth
        const scale = Math.min(1, maxWidth / naturalViewport.width)
        // Use higher resolution for clarity (2x device pixel ratio)
        const renderScale = scale * 2
        const viewport = page.getViewport({ scale: renderScale })

        const canvas = canvasRef.current
        if (!canvas || cancelled) return

        canvas.width = viewport.width
        canvas.height = viewport.height
        // Display at CSS dimensions (half the render size for retina)
        canvas.style.width = `${viewport.width / 2}px`
        canvas.style.height = `${viewport.height / 2}px`

        const ctx = canvas.getContext('2d')
        if (!ctx) return

        await page.render({ canvasContext: ctx, viewport, canvas } as any).promise

        // Report display dimensions (CSS size) for bbox positioning
        if (onDimensionsReady && !cancelled) {
          onDimensionsReady(viewport.width / 2, viewport.height / 2)
        }
      } catch (e) {
        if (!cancelled) {
          setError(`Failed to render PDF: ${(e as Error).message}`)
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    render()
    return () => { cancelled = true }
  }, [pdfUrl, pageNumber, maxWidth])

  if (error) {
    return (
      <div className="flex items-center justify-center h-64 bg-red-50 rounded-lg text-red-500 text-sm">
        {error}
      </div>
    )
  }

  return (
    <div className="relative inline-block">
      {loading && (
        <div className="absolute inset-0 flex items-center justify-center bg-gray-100 rounded-lg text-gray-400 text-sm z-10">
          Rendering page...
        </div>
      )}
      <canvas ref={canvasRef} className="block rounded-lg border border-gray-300" />
    </div>
  )
}
