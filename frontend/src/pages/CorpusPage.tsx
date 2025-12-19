import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import {
  FileText,
  Clock,
  CheckCircle,
  XCircle,
  Loader,
  Filter,
  RefreshCw,
} from 'lucide-react';
import { documentApi } from '../services/api';
import type { Document, DocumentStatus } from '../types';

const STATUS_CONFIG: Record<DocumentStatus, { icon: typeof Clock; color: string; label: string }> = {
  registered: { icon: Clock, color: 'text-yellow-500', label: 'Registered' },
  processing: { icon: Loader, color: 'text-blue-500', label: 'Processing' },
  indexed: { icon: CheckCircle, color: 'text-green-500', label: 'Indexed' },
  failed: { icon: XCircle, color: 'text-red-500', label: 'Failed' },
};

export default function CorpusPage() {
  const [statusFilter, setStatusFilter] = useState<DocumentStatus | 'all'>('all');

  const { data: documents, isLoading, refetch } = useQuery({
    queryKey: ['documents', statusFilter],
    queryFn: () =>
      documentApi.list({
        status: statusFilter === 'all' ? undefined : statusFilter,
        limit: 100,
      }),
    refetchOnMount: 'always',
    staleTime: 0,
  });

  const filteredDocs = documents || [];

  return (
    <div className="flex-1 p-8 overflow-auto">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold">Document Corpus</h1>
          <div className="flex items-center gap-3">
            <button
              onClick={() => refetch()}
              className="p-2 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg"
            >
              <RefreshCw className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Filters */}
        <div className="flex items-center gap-3 mb-6">
          <Filter className="w-5 h-5 text-gray-400" />
          <div className="flex gap-2">
            {(['all', 'registered', 'processing', 'indexed', 'failed'] as const).map(
              (status) => (
                <button
                  key={status}
                  onClick={() => setStatusFilter(status)}
                  className={`px-3 py-1.5 rounded-full text-sm transition-colors ${
                    statusFilter === status
                      ? 'bg-primary-500 text-white'
                      : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                  }`}
                >
                  {status === 'all' ? 'All' : STATUS_CONFIG[status].label}
                </button>
              )
            )}
          </div>
        </div>

        {/* Document List */}
        {isLoading ? (
          <div className="flex items-center justify-center py-12">
            <Loader className="w-8 h-8 animate-spin text-primary-500" />
          </div>
        ) : filteredDocs.length > 0 ? (
          <div className="bg-white rounded-lg border overflow-hidden">
            <table className="w-full">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-sm font-medium text-gray-500">
                    Document
                  </th>
                  <th className="px-4 py-3 text-left text-sm font-medium text-gray-500">
                    Authors
                  </th>
                  <th className="px-4 py-3 text-left text-sm font-medium text-gray-500">
                    Year
                  </th>
                  <th className="px-4 py-3 text-left text-sm font-medium text-gray-500">
                    Status
                  </th>
                  <th className="px-4 py-3 text-left text-sm font-medium text-gray-500">
                    Added
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {filteredDocs.map((doc: Document) => {
                  const status = STATUS_CONFIG[doc.status];
                  const StatusIcon = status.icon;

                  return (
                    <tr
                      key={doc.document_id}
                      className="hover:bg-gray-50 transition-colors"
                    >
                      <td className="px-4 py-3">
                        <Link
                          to={`/documents/${doc.document_id}`}
                          className="flex items-center gap-3 group"
                        >
                          <FileText className="w-5 h-5 text-gray-400" />
                          <span className="font-medium text-gray-900 group-hover:text-primary-600 line-clamp-1">
                            {doc.title}
                          </span>
                        </Link>
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-600">
                        {doc.authors.slice(0, 2).map((a) =>
                          a.family_name ? `${a.given_name || ''} ${a.family_name}`.trim() : a.name
                        ).join(', ')}
                        {doc.authors.length > 2 && ' et al.'}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-600">
                        {doc.year || '-'}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center gap-1.5 text-sm ${status.color}`}
                        >
                          <StatusIcon
                            className={`w-4 h-4 ${
                              doc.status === 'processing' ? 'animate-spin' : ''
                            }`}
                          />
                          {status.label}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-500">
                        {new Date(doc.created_at).toLocaleDateString()}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="text-center py-12 text-gray-500">
            <FileText className="w-12 h-12 mx-auto mb-4 opacity-50" />
            <p>No documents found.</p>
            <p className="text-sm mt-1">Upload or import documents to get started.</p>
          </div>
        )}

        {/* Stats */}
        <div className="mt-6 text-sm text-gray-500">
          Showing {filteredDocs.length} documents
        </div>
      </div>
    </div>
  );
}
