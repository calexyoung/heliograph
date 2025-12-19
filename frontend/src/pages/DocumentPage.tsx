import { useParams, Link } from 'react-router-dom';
import { useQuery, useMutation } from '@tanstack/react-query';
import {
  ArrowLeft,
  FileText,
  Clock,
  CheckCircle,
  XCircle,
  Loader,
  RefreshCw,
  ExternalLink,
  User,
  Calendar,
  BookOpen,
} from 'lucide-react';
import { documentApi } from '../services/api';
import type { DocumentStatus } from '../types';

const STATUS_CONFIG: Record<DocumentStatus, { icon: typeof Clock; color: string; label: string }> = {
  registered: { icon: Clock, color: 'text-yellow-500 bg-yellow-50', label: 'Registered' },
  processing: { icon: Loader, color: 'text-blue-500 bg-blue-50', label: 'Processing' },
  indexed: { icon: CheckCircle, color: 'text-green-500 bg-green-50', label: 'Indexed' },
  failed: { icon: XCircle, color: 'text-red-500 bg-red-50', label: 'Failed' },
};

export default function DocumentPage() {
  const { documentId } = useParams<{ documentId: string }>();

  const { data: document, isLoading, refetch } = useQuery({
    queryKey: ['document', documentId],
    queryFn: () => documentApi.get(documentId!),
    enabled: !!documentId,
  });

  const reprocessMutation = useMutation({
    mutationFn: () => documentApi.reprocess(documentId!),
    onSuccess: () => refetch(),
  });

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader className="w-8 h-8 animate-spin text-primary-500" />
      </div>
    );
  }

  if (!document) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center">
          <FileText className="w-16 h-16 mx-auto mb-4 text-gray-300" />
          <p className="text-gray-500">Document not found</p>
          <Link to="/corpus" className="text-primary-500 hover:underline mt-2 inline-block">
            Back to Corpus
          </Link>
        </div>
      </div>
    );
  }

  const status = STATUS_CONFIG[document.status];
  const StatusIcon = status.icon;

  return (
    <div className="flex-1 overflow-auto">
      {/* Header */}
      <div className="border-b bg-white sticky top-0 z-10">
        <div className="max-w-5xl mx-auto px-6 py-4">
          <Link
            to="/corpus"
            className="inline-flex items-center gap-2 text-gray-500 hover:text-gray-700 mb-4"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Corpus
          </Link>
          <div className="flex items-start justify-between gap-6">
            <div className="flex-1 min-w-0">
              <h1 className="text-2xl font-bold text-gray-900 line-clamp-2">
                {document.title}
              </h1>
              <div className="flex items-center gap-4 mt-2">
                <span
                  className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-sm ${status.color}`}
                >
                  <StatusIcon
                    className={`w-4 h-4 ${document.status === 'processing' ? 'animate-spin' : ''}`}
                  />
                  {status.label}
                </span>
                {document.doi && (
                  <a
                    href={`https://doi.org/${document.doi}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-primary-600 hover:underline text-sm flex items-center gap-1"
                  >
                    {document.doi}
                    <ExternalLink className="w-3 h-3" />
                  </a>
                )}
              </div>
            </div>
            {document.status === 'failed' && (
              <button
                onClick={() => reprocessMutation.mutate()}
                disabled={reprocessMutation.isPending}
                className="px-4 py-2 bg-primary-500 text-white rounded-lg hover:bg-primary-600 disabled:opacity-50 flex items-center gap-2"
              >
                <RefreshCw className={`w-4 h-4 ${reprocessMutation.isPending ? 'animate-spin' : ''}`} />
                Reprocess
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="max-w-5xl mx-auto px-6 py-8">
        <div className="grid grid-cols-3 gap-8">
          {/* Main Info */}
          <div className="col-span-2 space-y-8">
            {/* Authors */}
            {document.authors.length > 0 && (
              <section>
                <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                  <User className="w-5 h-5 text-gray-400" />
                  Authors
                </h2>
                <div className="space-y-2">
                  {document.authors.map((author, index) => {
                    const authorName = author.family_name
                      ? `${author.given_name || ''} ${author.family_name}`.trim()
                      : author.name || 'Unknown';
                    return (
                      <div
                        key={index}
                        className="flex items-center gap-3 p-3 bg-gray-50 rounded-lg"
                      >
                        <div className="w-10 h-10 bg-gray-200 rounded-full flex items-center justify-center text-gray-600 font-medium">
                          {authorName.charAt(0)}
                        </div>
                        <div>
                          <p className="font-medium">{authorName}</p>
                          {author.affiliation && (
                            <p className="text-sm text-gray-500">{author.affiliation}</p>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </section>
            )}

            {/* Metadata */}
            <section>
              <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                <BookOpen className="w-5 h-5 text-gray-400" />
                Publication Details
              </h2>
              <div className="grid grid-cols-2 gap-4">
                {document.journal && (
                  <div className="p-4 bg-gray-50 rounded-lg">
                    <p className="text-sm text-gray-500 mb-1">Journal</p>
                    <p className="font-medium">{document.journal}</p>
                  </div>
                )}
                {document.year && (
                  <div className="p-4 bg-gray-50 rounded-lg">
                    <p className="text-sm text-gray-500 mb-1">Year</p>
                    <p className="font-medium">{document.year}</p>
                  </div>
                )}
              </div>
            </section>
          </div>

          {/* Sidebar */}
          <div className="space-y-6">
            {/* Timeline */}
            <div className="bg-gray-50 rounded-lg p-4">
              <h3 className="font-semibold mb-4 flex items-center gap-2">
                <Calendar className="w-4 h-4 text-gray-400" />
                Timeline
              </h3>
              <div className="space-y-3 text-sm">
                <div className="flex justify-between">
                  <span className="text-gray-500">Added</span>
                  <span>{new Date(document.created_at).toLocaleDateString()}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-500">Updated</span>
                  <span>{new Date(document.updated_at).toLocaleDateString()}</span>
                </div>
              </div>
            </div>

            {/* Actions */}
            <div className="space-y-2">
              <Link
                to={`/chat?document=${documentId}`}
                className="w-full px-4 py-2 bg-primary-500 text-white rounded-lg hover:bg-primary-600 flex items-center justify-center gap-2"
              >
                Ask about this document
              </Link>
              <Link
                to={`/graph?document=${documentId}`}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50 flex items-center justify-center gap-2"
              >
                View in knowledge graph
              </Link>
            </div>

            {/* IDs */}
            <div className="bg-gray-50 rounded-lg p-4">
              <h3 className="font-semibold mb-4">Identifiers</h3>
              <div className="space-y-3 text-sm">
                <div>
                  <p className="text-gray-500 mb-1">Document ID</p>
                  <p className="font-mono text-xs break-all">{document.document_id}</p>
                </div>
                <div>
                  <p className="text-gray-500 mb-1">Content Hash</p>
                  <p className="font-mono text-xs break-all">{document.content_hash}</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
