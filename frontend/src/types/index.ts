// Document types
export interface Document {
  document_id: string;
  doi?: string;
  content_hash?: string | null;
  title: string;
  authors: Author[];
  journal?: string;
  year?: number;
  status: DocumentStatus;
  created_at: string;
  updated_at: string;
}

export interface Author {
  name?: string;
  given_name?: string;
  family_name?: string;
  affiliation?: string;
  orcid?: string;
  email?: string;
  sequence?: string;
}

export type DocumentStatus = 'registered' | 'processing' | 'indexed' | 'failed';

// Upload types
export interface UploadProgress {
  upload_id: string;
  filename: string;
  progress: number;
  status: 'pending' | 'uploading' | 'processing' | 'complete' | 'error';
  error?: string;
}

export interface PresignedUrlResponse {
  upload_id: string;
  presigned_url: string;
  expires_at: string;
}

// Search types
export interface SearchResult {
  source: string;
  doi?: string;
  title: string;
  authors: Author[];
  year?: number;
  abstract?: string;
  pdf_url?: string;
}

export interface SearchRequest {
  query: string;
  sources: string[];
  limit: number;
}

// Chat types
export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  citations?: Citation[];
  timestamp: Date;
}

export interface Citation {
  citation_id: number;
  chunk_id: string;
  document_id: string;
  title: string;
  authors: string[];
  year?: number;
  page?: number;
  section?: string;
  snippet: string;
}

export interface QueryRequest {
  query: string;
  corpus_ids?: string[];
  max_results?: number;
  include_graph?: boolean;
  streaming?: boolean;
}

export interface QueryResponse {
  answer: string;
  citations: Citation[];
  confidence: number;
  processing_time_ms: number;
}

// Graph types
export interface GraphNode {
  node_id: string;
  entity_id?: string;
  document_id?: string;
  label: string;
  node_type: 'entity' | 'article';
  properties: Record<string, unknown>;
}

export interface GraphEdge {
  edge_id: string;
  source_id: string;
  target_id: string;
  relationship_type: string;
  confidence: number;
}

export interface SubgraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
  center_node?: GraphNode;
  evidence_refs?: Record<string, EvidencePointer[]>;
}

export interface EvidencePointer {
  chunk_id: string;
  document_id: string;
  char_start: number;
  char_end: number;
  snippet: string;
}

export interface GraphStats {
  nodes: Record<string, number>;
  relationships: Record<string, number>;
  total_nodes: number;
  total_relationships: number;
}

// Chunk types
export interface Chunk {
  chunk_id: string;
  document_id: string;
  text: string;
  section?: string;
  page_start?: number;
  page_end?: number;
}

// Auth types
export interface User {
  user_id: string;
  email: string;
  full_name?: string;
  is_active: boolean;
  email_verified: boolean;
}

export interface AuthTokens {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface RegisterRequest {
  email: string;
  password: string;
  full_name?: string;
}

// User preferences types
export interface StoragePreferences {
  type: 's3' | 'local';
  local_path?: string;
  bucket?: string;
}

export interface UserPreferences {
  storage: StoragePreferences;
}

export interface UpdatePreferencesRequest {
  storage?: StoragePreferences;
}
