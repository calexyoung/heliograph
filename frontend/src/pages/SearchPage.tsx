import { useState, useMemo, useEffect } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Search, Download, Loader, ExternalLink, Check } from 'lucide-react';
import toast from 'react-hot-toast';
import { searchApi, documentApi } from '../services/api';
import type { SearchResult } from '../types';

const SOURCES = [
  { id: 'crossref', label: 'Crossref' },
  { id: 'semantic_scholar', label: 'Semantic Scholar' },
  { id: 'arxiv', label: 'arXiv' },
  { id: 'scixplorer', label: 'NASA ADS' },
];

export default function SearchPage() {
  const [query, setQuery] = useState('');
  const [selectedSources, setSelectedSources] = useState<string[]>(['crossref', 'arxiv']);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [sessionImportedDois, setSessionImportedDois] = useState<Set<string>>(new Set());
  const [importingDoi, setImportingDoi] = useState<string | null>(null);
  const queryClient = useQueryClient();

  // Fetch existing documents to know which DOIs are already imported
  const { data: existingDocs, isLoading: docsLoading, error: docsError } = useQuery({
    queryKey: ['corpus-dois'],
    queryFn: () => documentApi.list({ limit: 1000 }),
    staleTime: 0, // Always consider stale to ensure fresh data
    refetchOnMount: 'always',
  });

  // Log query state for debugging
  useEffect(() => {
    if (docsError) console.error('[SearchPage] Error loading docs:', docsError);
    console.log('[SearchPage] Docs loading:', docsLoading, 'Count:', existingDocs?.length);
  }, [docsLoading, docsError, existingDocs]);

  // Build set of already-imported DOIs from corpus
  const corpusDois = useMemo(() => {
    const dois = new Set<string>();
    existingDocs?.forEach((doc) => {
      if (doc.doi) {
        dois.add(doc.doi.toLowerCase());
      }
    });
    return dois;
  }, [existingDocs]);

  // Debug logging
  useEffect(() => {
    console.log('[SearchPage] existingDocs:', existingDocs?.length, 'corpusDois:', Array.from(corpusDois));
  }, [existingDocs, corpusDois]);

  // Combined check: in corpus OR imported this session
  const isImported = (doi: string | undefined) => {
    if (!doi) return false;
    const normalizedDoi = doi.toLowerCase();
    const found = corpusDois.has(normalizedDoi) || sessionImportedDois.has(normalizedDoi);
    if (found) console.log('[SearchPage] DOI found in corpus:', normalizedDoi);
    return found;
  };

  const searchMutation = useMutation({
    mutationFn: () =>
      searchApi.search({
        query,
        sources: selectedSources,
        limit: 20,
      }),
    onSuccess: (data) => setResults(data),
  });

  const importMutation = useMutation({
    mutationFn: ({ source, identifier }: { source: string; identifier: string }) =>
      searchApi.import(source, identifier),
    onSuccess: (data, variables) => {
      const status = data?.status || 'imported';
      if (status === 'duplicate') {
        toast.success('Paper already in corpus', { icon: '📄' });
      } else if (status === 'imported' || status === 'completed') {
        toast.success('Paper imported successfully!', { icon: '✅' });
      } else {
        toast.success(`Import complete: ${status}`);
      }
      setSessionImportedDois((prev) => new Set(prev).add(variables.identifier.toLowerCase()));
      setImportingDoi(null);
      // Force refetch documents cache so corpus page and DOI lookup show new imports
      queryClient.refetchQueries({ queryKey: ['documents'] });
      queryClient.refetchQueries({ queryKey: ['corpus-dois'] });
    },
    onError: (error: Error) => {
      toast.error(`Import failed: ${error.message}`);
      setImportingDoi(null);
    },
  });

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (query.trim()) {
      searchMutation.mutate();
    }
  };

  const toggleSource = (sourceId: string) => {
    setSelectedSources((prev) =>
      prev.includes(sourceId)
        ? prev.filter((s) => s !== sourceId)
        : [...prev, sourceId]
    );
  };

  const handleImport = (result: SearchResult) => {
    if (result.doi) {
      setImportingDoi(result.doi);
      importMutation.mutate({ source: result.source, identifier: result.doi });
    }
  };

  const isImporting = (doi: string | undefined) => doi === importingDoi;

  return (
    <div className="flex-1 p-8 overflow-auto">
      <div className="max-w-4xl mx-auto">
        <h1 className="text-2xl font-bold mb-6">Search & Import</h1>

        {/* Search Form */}
        <form onSubmit={handleSearch} className="mb-6">
          <div className="flex gap-3">
            <div className="flex-1 relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search for papers by title, author, or topic..."
                className="w-full pl-10 pr-4 py-3 border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
              />
            </div>
            <button
              type="submit"
              disabled={searchMutation.isPending}
              className="px-6 py-3 bg-primary-500 text-white rounded-lg hover:bg-primary-600 disabled:opacity-50 flex items-center gap-2"
            >
              {searchMutation.isPending ? (
                <Loader className="w-5 h-5 animate-spin" />
              ) : (
                <Search className="w-5 h-5" />
              )}
              Search
            </button>
          </div>

          {/* Source Selection */}
          <div className="flex gap-3 mt-4">
            {SOURCES.map((source) => (
              <button
                key={source.id}
                type="button"
                onClick={() => toggleSource(source.id)}
                className={`px-4 py-2 rounded-full text-sm transition-colors ${
                  selectedSources.includes(source.id)
                    ? 'bg-primary-500 text-white'
                    : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                }`}
              >
                {source.label}
              </button>
            ))}
          </div>
        </form>

        {/* Results */}
        {results.length > 0 && (
          <div className="space-y-4">
            <p className="text-sm text-gray-500">
              Found {results.length} results
            </p>
            {results.map((result, index) => (
              <div
                key={index}
                className="p-4 bg-white rounded-lg border hover:shadow-md transition-shadow"
              >
                <div className="flex justify-between items-start gap-4">
                  <div className="flex-1 min-w-0">
                    <h3 className="font-semibold text-lg line-clamp-2">
                      {result.title}
                    </h3>
                    <p className="text-sm text-gray-600 mt-1">
                      {result.authors.slice(0, 3).join(', ')}
                      {result.authors.length > 3 && ' et al.'}
                      {result.year && ` (${result.year})`}
                    </p>
                    {result.abstract && (
                      <p className="text-sm text-gray-500 mt-2 line-clamp-2">
                        {result.abstract}
                      </p>
                    )}
                    <div className="flex items-center gap-3 mt-3">
                      <span className="px-2 py-1 bg-gray-100 rounded text-xs text-gray-600">
                        {result.source}
                      </span>
                      {result.doi && (
                        <a
                          href={`https://doi.org/${result.doi}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-xs text-primary-600 hover:underline flex items-center gap-1"
                        >
                          DOI <ExternalLink className="w-3 h-3" />
                        </a>
                      )}
                    </div>
                  </div>
                  {isImported(result.doi) ? (
                    <button
                      disabled
                      className="px-4 py-2 bg-green-500 text-white rounded-lg flex items-center gap-2 shrink-0"
                    >
                      <Check className="w-4 h-4" />
                      Imported
                    </button>
                  ) : (
                    <button
                      onClick={() => handleImport(result)}
                      disabled={!result.doi || isImporting(result.doi)}
                      className="px-4 py-2 bg-primary-500 text-white rounded-lg hover:bg-primary-600 disabled:opacity-50 flex items-center gap-2 shrink-0"
                    >
                      {isImporting(result.doi) ? (
                        <>
                          <Loader className="w-4 h-4 animate-spin" />
                          Importing...
                        </>
                      ) : (
                        <>
                          <Download className="w-4 h-4" />
                          Import
                        </>
                      )}
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Empty State */}
        {!searchMutation.isPending && results.length === 0 && query && (
          <div className="text-center py-12 text-gray-500">
            <Search className="w-12 h-12 mx-auto mb-4 opacity-50" />
            <p>No results found. Try different keywords or sources.</p>
          </div>
        )}
      </div>
    </div>
  );
}
