import axios from 'axios';
import type {
  Document,
  PresignedUrlResponse,
  SearchResult,
  SearchRequest,
  QueryRequest,
  QueryResponse,
  SubgraphResponse,
} from '../types';

const TOKEN_KEY = 'heliograph_tokens';

const api = axios.create({
  baseURL: '/api',
  headers: {
    'Content-Type': 'application/json',
  },
});

// Add auth token to requests
api.interceptors.request.use((config) => {
  const storedTokens = localStorage.getItem(TOKEN_KEY);
  if (storedTokens) {
    try {
      const tokens = JSON.parse(storedTokens);
      if (tokens.access_token) {
        config.headers.Authorization = `Bearer ${tokens.access_token}`;
      }
    } catch {
      // Invalid token data
    }
  }
  return config;
});

// Handle 401 responses
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Clear tokens and redirect to login
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem('heliograph_user');
      // Only redirect if not already on login page
      if (!window.location.pathname.includes('/login')) {
        window.location.href = '/login';
      }
    }
    return Promise.reject(error);
  }
);

// Document APIs
export const documentApi = {
  list: async (params?: { status?: string; limit?: number; offset?: number }) => {
    const response = await api.get<Document[]>('/documents', { params });
    return response.data;
  },

  get: async (documentId: string) => {
    const response = await api.get<Document>(`/documents/${documentId}`);
    return response.data;
  },

  getPresignedUrl: async (filename: string, contentType: string, sizeBytes: number) => {
    const response = await api.post<PresignedUrlResponse>('/upload/presigned-url', {
      filename,
      content_type: contentType,
      size_bytes: sizeBytes,
    });
    return response.data;
  },

  completeUpload: async (uploadId: string) => {
    const response = await api.post(`/upload/${uploadId}/complete`, {});
    return response.data;
  },

  reprocess: async (documentId: string) => {
    const response = await api.post(`/documents/${documentId}/reprocess`);
    return response.data;
  },
};

// Search APIs
export const searchApi = {
  search: async (request: SearchRequest) => {
    const response = await api.post<{ results: SearchResult[] }>('/search', request);
    return response.data.results;
  },

  import: async (source: string, identifier: string) => {
    // Map source to the correct field for ImportRequest
    const importRequest: Record<string, string | boolean> = { download_pdf: true };

    if (identifier.startsWith('10.')) {
      // DOI format
      importRequest.doi = identifier;
    } else if (source === 'arxiv' || /^\d{4}\.\d+/.test(identifier)) {
      // arXiv ID format
      importRequest.arxiv_id = identifier;
    } else if (source === 'scixplorer' || /^\d{4}[A-Za-z]/.test(identifier)) {
      // ADS bibcode format
      importRequest.bibcode = identifier;
    } else if (identifier.startsWith('http')) {
      // URL
      importRequest.url = identifier;
    } else {
      // Default to DOI
      importRequest.doi = identifier;
    }

    const response = await api.post('/import', importRequest);
    return response.data;
  },
};

// Query APIs
export const queryApi = {
  query: async (request: QueryRequest) => {
    const response = await api.post<QueryResponse>('/query', request);
    return response.data;
  },

  queryStream: (request: QueryRequest) => {
    return new EventSource(`/api/query/stream?${new URLSearchParams({
      query: request.query,
      ...(request.corpus_ids && { corpus_ids: request.corpus_ids.join(',') }),
    })}`);
  },
};

// Graph APIs
export const graphApi = {
  getSubgraph: async (
    nodeId: string,
    depth: number = 2,
    options?: {
      minConfidence?: number;
      maxNodes?: number;
      nodeTypes?: string[];
      edgeTypes?: string[];
    }
  ) => {
    const response = await api.get<SubgraphResponse>(`/graph/subgraph/${nodeId}`, {
      params: {
        depth,
        min_confidence: options?.minConfidence,
        max_nodes: options?.maxNodes,
        node_types: options?.nodeTypes?.join(','),
        edge_types: options?.edgeTypes?.join(','),
      },
    });
    return response.data;
  },

  search: async (query: string, nodeType?: string, limit: number = 20) => {
    const response = await api.get('/graph/search', {
      params: { query, node_type: nodeType, limit },
    });
    return response.data;
  },

  getStats: async () => {
    const response = await api.get<{
      nodes: Record<string, number>;
      relationships: Record<string, number>;
      total_nodes: number;
      total_relationships: number;
    }>('/graph/stats');
    return response.data;
  },

  getEdgeEvidence: async (sourceId: string, targetId: string, relationshipType: string) => {
    const response = await api.get(`/graph/edges/${sourceId}/${targetId}/evidence`, {
      params: { relationship_type: relationshipType },
    });
    return response.data;
  },

  getDocumentEntities: async (documentId: string) => {
    const response = await api.get(`/graph/documents/${documentId}/entities`);
    return response.data;
  },

  getRelatedEntities: async (
    entityId: string,
    options?: { relationshipTypes?: string[]; minConfidence?: number; limit?: number }
  ) => {
    const response = await api.get<SubgraphResponse>(`/graph/entities/${entityId}/related`, {
      params: {
        relationship_types: options?.relationshipTypes,
        min_confidence: options?.minConfidence,
        limit: options?.limit,
      },
    });
    return response.data;
  },
};

export default api;
