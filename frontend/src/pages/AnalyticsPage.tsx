import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { BarChart3, Loader2 } from 'lucide-react'
import { getAnalytics, listUseCases } from '../lib/api'

export default function AnalyticsPage() {
  const [useCase, setUseCase] = useState<string>('All')

  const { data: useCases } = useQuery({ queryKey: ['use-cases'], queryFn: listUseCases })
  const { data, isLoading } = useQuery({
    queryKey: ['analytics', useCase],
    queryFn: () => getAnalytics(useCase === 'All' ? undefined : useCase),
  })

  const maxCount = data?.issue_breakdown?.[0]?.count || 1

  return (
    <div className="max-w-4xl mx-auto py-8 px-4">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">Issue Analytics</h2>
          <p className="text-sm text-gray-500 mt-1">Aggregated feedback across documents</p>
        </div>
        <select
          value={useCase}
          onChange={(e) => setUseCase(e.target.value)}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="All">All Use Cases</option>
          {useCases?.map(c => (
            <option key={c.use_case_name} value={c.use_case_name}>{c.use_case_name}</option>
          ))}
        </select>
      </div>

      {isLoading && (
        <div className="flex items-center gap-3 text-gray-500 py-12 justify-center">
          <Loader2 className="w-5 h-5 animate-spin" /> Loading analytics...
        </div>
      )}

      {data && (
        <>
          {/* Summary stats */}
          <div className="grid grid-cols-5 gap-4 mb-8">
            {[
              { label: 'Documents', value: data.summary.total_docs, color: 'bg-blue-50 text-blue-700' },
              { label: 'Elements', value: data.summary.total_elements, color: 'bg-gray-50 text-gray-700' },
              { label: 'Reviewed', value: data.summary.total_reviewed, color: 'bg-purple-50 text-purple-700' },
              { label: 'Correct', value: data.summary.total_correct, color: 'bg-green-50 text-green-700' },
              { label: 'Issues', value: data.summary.total_issues, color: 'bg-red-50 text-red-700' },
            ].map(s => (
              <div key={s.label} className={`rounded-xl p-4 ${s.color}`}>
                <div className="text-2xl font-bold">{s.value}</div>
                <div className="text-sm opacity-80">{s.label}</div>
              </div>
            ))}
          </div>

          {/* Issue breakdown */}
          <h3 className="text-lg font-semibold text-gray-800 mb-4 flex items-center gap-2">
            <BarChart3 className="w-5 h-5" /> Issues by Category
          </h3>

          {data.issue_breakdown.length === 0 ? (
            <p className="text-gray-400 text-center py-8">No issues reported yet</p>
          ) : (
            <div className="space-y-3">
              {data.issue_breakdown.map(item => (
                <div key={item.issue_category} className="flex items-center gap-4">
                  <div className="w-48 text-sm text-gray-700 text-right shrink-0">
                    {(item.issue_category || 'other').replace(/_/g, ' ')}
                  </div>
                  <div className="flex-1 bg-gray-100 rounded-full h-6 overflow-hidden">
                    <div
                      className="bg-red-400 h-full rounded-full flex items-center justify-end pr-2"
                      style={{ width: `${Math.max(5, (item.count / maxCount) * 100)}%` }}
                    >
                      <span className="text-xs text-white font-medium">{item.count}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
