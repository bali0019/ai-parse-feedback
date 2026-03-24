/**
 * Core component: renders page image with clickable bounding box overlays.
 * Supports two modes: pre-rendered image (from ai_parse_document) or PDF.js rendering.
 */

import { useMemo, useState, useCallback } from 'react'
import type { Element, BBox, Feedback, QualityFlag } from '../lib/types'
import { getElementColor } from '../lib/constants'
import PdfPageRenderer from './PdfPageRenderer'

interface Props {
  imageDataUri: string | null
  imageWidth: number
  imageHeight: number
  maxWidth?: number // dynamic max display width from container
  pdfUrl?: string | null
  pageNumber?: number // 1-indexed for PDF.js
  elements: Element[]
  pageId: number
  selectedElementId: number | null
  feedbackMap: Record<number, Feedback>
  qualityFlags?: Record<number, QualityFlag[]>
  onSelectElement: (id: number) => void
}

export default function PageAnnotator({
  imageDataUri,
  imageWidth,
  imageHeight,
  maxWidth,
  pdfUrl,
  pageNumber,
  elements,
  pageId,
  selectedElementId,
  feedbackMap,
  qualityFlags,
  onSelectElement,
}: Props) {
  // For PDF mode: dimensions come from PDF.js after render
  const [pdfDimensions, setPdfDimensions] = useState<{ width: number; height: number } | null>(null)

  const usePdf = !imageDataUri && !!pdfUrl && !!pageNumber
  const effectiveWidth = usePdf ? (pdfDimensions?.width || 900) : imageWidth
  const effectiveHeight = usePdf ? (pdfDimensions?.height || 1200) : imageHeight

  // Scale to fit within max display width (dynamic from container, fallback 900)
  const maxDisplayWidth = maxWidth || 900
  const scale = useMemo(() => {
    if (usePdf) return 1 // PDF.js already renders at the right size
    if (effectiveWidth <= maxDisplayWidth) return 1
    return maxDisplayWidth / effectiveWidth
  }, [effectiveWidth, usePdf])

  const displayWidth = usePdf ? effectiveWidth : Math.round(effectiveWidth * scale)
  const displayHeight = usePdf ? effectiveHeight : Math.round(effectiveHeight * scale)

  // For PDF mode, we need to compute scale from original bbox coords to display size
  // ai_parse_document bbox coords are in original page image pixel space
  // PDF.js renders at its own scale — we need to map bbox coords to PDF.js display coords
  // The PDF.js viewport width maps to the same page as the original image width
  const pdfScale = useMemo(() => {
    if (!usePdf || !pdfDimensions) return 1
    // If we have the original image dimensions (from parsed_result), use them for mapping
    // Otherwise fall back to assuming bbox coords match PDF.js dimensions
    if (imageWidth > 0) {
      return pdfDimensions.width / imageWidth
    }
    return 1
  }, [usePdf, pdfDimensions, imageWidth])

  const bboxScale = usePdf ? pdfScale : scale

  const handlePdfDimensions = useCallback((w: number, h: number) => {
    setPdfDimensions({ width: w, height: h })
  }, [])

  // Collect bboxes per element for this page
  const pageBoxes = useMemo(() => {
    const boxes: Array<{ element: Element; bbox: BBox; color: string }> = []
    for (const elem of elements) {
      for (const bbox of elem.bbox || []) {
        if (bbox.page_id === pageId && bbox.coord?.length >= 4) {
          boxes.push({ element: elem, bbox, color: getElementColor(elem.type) })
        }
      }
    }
    return boxes
  }, [elements, pageId])

  if (!imageDataUri && !usePdf) {
    return (
      <div className="flex items-center justify-center h-64 bg-gray-100 rounded-lg text-gray-400">
        No image available for this page
      </div>
    )
  }

  return (
    <div
      className="relative inline-block rounded-xl ring-1 ring-gray-200 shadow-sm overflow-visible bg-white"
      style={{ width: displayWidth, height: displayHeight }}
    >
      {usePdf ? (
        <PdfPageRenderer
          pdfUrl={pdfUrl!}
          pageNumber={pageNumber!}
          maxWidth={maxDisplayWidth}
          onDimensionsReady={handlePdfDimensions}
        />
      ) : (
        <img
          src={imageDataUri!}
          alt={`Page ${pageId + 1}`}
          style={{ display: 'block', width: displayWidth, height: displayHeight }}
          draggable={false}
        />
      )}

      {/* Bbox overlays — only render when dimensions are known */}
      {(!usePdf || pdfDimensions) && pageBoxes.map(({ element, bbox, color }, idx) => {
        const [x1, y1, x2, y2] = bbox.coord
        const left = x1 * bboxScale
        const top = y1 * bboxScale
        const width = (x2 - x1) * bboxScale
        const height = (y2 - y1) * bboxScale
        if (width <= 0 || height <= 0) return null

        const isSelected = element.id === selectedElementId
        const fb = feedbackMap[element.id]
        const hasIssue = fb?.is_correct === false
        const isReviewed = fb != null
        const isFlagged = !!(qualityFlags?.[element.id]?.length)

        return (
          <div
            key={`${element.id}-${idx}`}
            onClick={() => onSelectElement(element.id)}
            title={`${element.type.toUpperCase()} #${element.id}`}
            style={{
              position: 'absolute',
              left, top, width, height,
              border: isSelected ? '3px solid #2563eb'
                : isFlagged && !isReviewed ? '2px dashed #f59e0b'
                : `2px solid ${color}`,
              background: isSelected
                ? 'rgba(37, 99, 235, 0.15)'
                : hasIssue
                ? 'rgba(239, 68, 68, 0.12)'
                : isFlagged && !isReviewed
                ? 'rgba(245, 158, 11, 0.10)'
                : isReviewed
                ? 'rgba(34, 197, 94, 0.08)'
                : `${color}18`,
              cursor: 'pointer',
              zIndex: isSelected ? 1000 : 100,
              transition: 'all 0.15s ease',
              boxSizing: 'border-box',
            }}
            className="hover:brightness-110"
          >
            {/* Label */}
            <div
              style={{
                position: 'absolute',
                top: top >= 18 ? -18 : 2,
                left: 0,
                background: isSelected ? '#2563eb' : color,
                color: 'white',
                padding: '1px 4px',
                fontSize: 9,
                fontWeight: 'bold',
                whiteSpace: 'nowrap',
                borderRadius: 2,
                pointerEvents: 'none',
                maxWidth: Math.max(50, width - 4),
                overflow: 'hidden',
              }}
            >
              {element.type.toUpperCase().slice(0, 6)}#{element.id}
              {hasIssue && ' ⚠'}
              {isReviewed && !hasIssue && ' ✓'}
            </div>
          </div>
        )
      })}
    </div>
  )
}
