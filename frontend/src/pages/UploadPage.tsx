import { useState, useCallback } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Upload, FileText, Loader2, CheckCircle2 } from 'lucide-react'
import { uploadDocument, triggerParse, listUseCases } from '../lib/api'

interface UploadStatus {
  filename: string
  status: 'uploading' | 'uploaded' | 'parsing' | 'done' | 'error'
  documentId?: string
  error?: string
}

export default function UploadPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [dragOver, setDragOver] = useState(false)
  const [files, setFiles] = useState<UploadStatus[]>([])
  const [processing, setProcessing] = useState(false)
  const [useCaseName, setUseCaseName] = useState(searchParams.get('use_case') || '')

  const { data: existingUseCases } = useQuery({ queryKey: ['use-cases'], queryFn: listUseCases })

  const handleFiles = useCallback(async (fileList: FileList | null) => {
    if (!fileList || fileList.length === 0) return

    const items: UploadStatus[] = Array.from(fileList).map(f => ({
      filename: f.name,
      status: 'uploading' as const,
    }))
    setFiles(items)
    setProcessing(true)

    const updated = [...items]

    for (let i = 0; i < fileList.length; i++) {
      try {
        // Upload
        updated[i] = { ...updated[i], status: 'uploading' }
        setFiles([...updated])

        const result = await uploadDocument(fileList[i], useCaseName || undefined)
        updated[i] = { ...updated[i], status: 'uploaded', documentId: result.document_id }
        setFiles([...updated])

        // Trigger parse
        updated[i] = { ...updated[i], status: 'parsing' }
        setFiles([...updated])

        await triggerParse(result.document_id)
        updated[i] = { ...updated[i], status: 'done' }
        setFiles([...updated])
      } catch (e) {
        updated[i] = { ...updated[i], status: 'error', error: (e as Error).message }
        setFiles([...updated])
      }
    }

    setProcessing(false)
  }, [useCaseName])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    handleFiles(e.dataTransfer.files)
  }, [handleFiles])

  const allDone = files.length > 0 && files.every(f => f.status === 'done' || f.status === 'error')

  return (
    <div className="max-w-2xl mx-auto py-12 px-4">
      <h2 className="text-2xl font-bold text-gray-900 mb-2">Upload Documents</h2>
      <p className="text-gray-500 mb-8">
        Upload PDFs or images to parse with <code className="bg-gray-100 px-1 rounded">ai_parse_document</code> and review the results.
      </p>

      {/* Use case name input — required before upload */}
      <div className="mb-6 relative">
        <label className="text-sm font-medium text-gray-700 block mb-1">
          Use Case Name <span className="text-red-500">*</span>
        </label>
        <input
          type="text"
          value={useCaseName}
          onChange={(e) => setUseCaseName(e.target.value)}
          disabled={files.length > 0}
          placeholder="Type use case name..."
          className={`w-full max-w-md border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${
            files.length > 0 ? 'bg-gray-100 cursor-not-allowed' :
            useCaseName.trim() ? 'border-green-300 bg-green-50' : 'border-gray-300'
          }`}
        />
        {/* Filtered suggestions dropdown */}
        {useCaseName.trim() && existingUseCases && existingUseCases.length > 0 && (
          (() => {
            const matches = existingUseCases.filter(c =>
              c.use_case_name.toLowerCase().includes(useCaseName.toLowerCase()) &&
              c.use_case_name.toLowerCase() !== useCaseName.toLowerCase()
            )
            if (matches.length === 0) return null
            return (
              <div className="absolute z-10 mt-1 w-full max-w-md bg-white border border-gray-200 rounded-lg shadow-lg max-h-40 overflow-y-auto">
                {matches.map(c => (
                  <button
                    key={c.use_case_name}
                    onClick={() => setUseCaseName(c.use_case_name)}
                    className="w-full text-left px-3 py-2 text-sm hover:bg-blue-50 flex justify-between items-center"
                  >
                    <span>{c.use_case_name}</span>
                    <span className="text-xs text-gray-400">{c.doc_count} docs</span>
                  </button>
                ))}
              </div>
            )
          })()
        )}
        {!useCaseName.trim() && (
          <p className="text-xs text-amber-600 mt-1">Enter a use case name before uploading documents</p>
        )}
        {useCaseName.trim() && (
          <p className="text-xs text-green-600 mt-1">Documents will be grouped under "{useCaseName}"</p>
        )}
      </div>

      {/* Upload area — only enabled when use case name is set */}
      {files.length === 0 && useCaseName.trim() && (
        <div
          onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
          className={`border-2 border-dashed rounded-xl p-12 text-center transition-colors cursor-pointer ${
            dragOver ? 'border-blue-500 bg-blue-50' : 'border-gray-300 hover:border-gray-400'
          }`}
          onClick={() => document.getElementById('file-input')?.click()}
        >
          <input
            id="file-input"
            type="file"
            accept=".pdf,.png,.jpg,.jpeg,.tiff,.tif"
            multiple
            className="hidden"
            onChange={(e) => handleFiles(e.target.files)}
          />
          <Upload className="w-12 h-12 mx-auto text-gray-400 mb-4" />
          <p className="text-lg font-medium text-gray-700">
            Drop files here or click to browse
          </p>
          <p className="text-sm text-gray-400 mt-1">PDF, PNG, JPG, TIFF supported. Select multiple files.</p>
        </div>
      )}

      {files.length === 0 && !useCaseName.trim() && (
        <div className="border-2 border-dashed border-gray-200 rounded-xl p-12 text-center bg-gray-50 opacity-60">
          <Upload className="w-12 h-12 mx-auto text-gray-300 mb-4" />
          <p className="text-lg font-medium text-gray-400">Enter a use case name above to enable uploads</p>
        </div>
      )}

      {/* File progress list */}
      {files.length > 0 && (
        <div className="space-y-3">
          {files.map((f, i) => (
            <div key={i} className="flex items-center gap-3 bg-white border border-gray-200 rounded-lg p-4">
              <FileText className="w-5 h-5 text-gray-400 shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-gray-900 truncate">{f.filename}</p>
                <p className="text-xs text-gray-500">
                  {f.status === 'uploading' && 'Uploading...'}
                  {f.status === 'uploaded' && 'Uploaded, starting parse...'}
                  {f.status === 'parsing' && 'Parsing with ai_parse_document...'}
                  {f.status === 'done' && 'Parse triggered'}
                  {f.status === 'error' && <span className="text-red-500">{f.error}</span>}
                </p>
              </div>
              {(f.status === 'uploading' || f.status === 'uploaded' || f.status === 'parsing') && (
                <Loader2 className="w-4 h-4 animate-spin text-blue-500 shrink-0" />
              )}
              {f.status === 'done' && (
                <CheckCircle2 className="w-4 h-4 text-green-500 shrink-0" />
              )}
            </div>
          ))}

          {allDone && (
            <div className="flex gap-3 mt-4">
              <button
                onClick={() => navigate('/documents')}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
              >
                View Documents
              </button>
              <button
                onClick={() => setFiles([])}
                className="px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50"
              >
                Upload More
              </button>
            </div>
          )}

          {processing && (
            <p className="text-sm text-gray-500 text-center mt-2">
              Processing {files.filter(f => f.status === 'done').length}/{files.length} files...
            </p>
          )}
        </div>
      )}
    </div>
  )
}
