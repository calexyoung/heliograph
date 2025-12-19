import { useState, useEffect, useRef, useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import * as d3 from 'd3';
import {
  Search,
  Loader,
  X,
  Filter,
  Download,
  ZoomIn,
  ZoomOut,
  Maximize2,
  ChevronDown,
  FileText,
  Link2,
} from 'lucide-react';
import { graphApi } from '../services/api';
import type { GraphNode, GraphEdge, EvidencePointer } from '../types';

const NODE_COLORS: Record<string, string> = {
  article: '#3B82F6',
  entity: '#10B981',
  scientific_concept: '#8B5CF6',
  method: '#F59E0B',
  instrument: '#EF4444',
  phenomenon: '#EC4899',
  mission: '#06B6D4',
  spacecraft: '#14B8A6',
  celestial_body: '#F97316',
  dataset: '#84CC16',
  organization: '#6366F1',
  author: '#A855F7',
};

const ENTITY_TYPES = [
  'scientific_concept',
  'method',
  'instrument',
  'phenomenon',
  'mission',
  'spacecraft',
  'celestial_body',
  'dataset',
  'organization',
  'author',
];

const RELATIONSHIP_TYPES = [
  'mentions',
  'cites',
  'uses_method',
  'uses_dataset',
  'uses_instrument',
  'studies',
  'related_to',
  'part_of',
  'causes',
  'observes',
];

interface SelectedEdge {
  edge: GraphEdge;
  evidence: EvidencePointer[];
}

export default function GraphPage() {
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const zoomRef = useRef<d3.ZoomBehavior<SVGSVGElement, unknown> | null>(null);

  const [searchQuery, setSearchQuery] = useState('');
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<SelectedEdge | null>(null);
  const [centerNodeId, setCenterNodeId] = useState<string | null>(null);
  const [depth, setDepth] = useState(2);
  const [minConfidence, setMinConfidence] = useState(0.5);
  const [showFilters, setShowFilters] = useState(false);
  const [enabledEntityTypes, setEnabledEntityTypes] = useState<Set<string>>(
    new Set(ENTITY_TYPES)
  );
  const [enabledRelTypes, setEnabledRelTypes] = useState<Set<string>>(
    new Set(RELATIONSHIP_TYPES)
  );

  const { data: graphData, isLoading } = useQuery({
    queryKey: ['graph', centerNodeId, depth, minConfidence],
    queryFn: () =>
      centerNodeId
        ? graphApi.getSubgraph(centerNodeId, depth, { minConfidence })
        : null,
    enabled: !!centerNodeId,
  });

  const { data: searchResults } = useQuery({
    queryKey: ['graphSearch', searchQuery],
    queryFn: () => graphApi.search(searchQuery, undefined, 10),
    enabled: searchQuery.length > 2,
  });

  const { data: stats } = useQuery({
    queryKey: ['graphStats'],
    queryFn: graphApi.getStats,
  });

  // Filter graph data based on enabled types
  const filteredGraphData = graphData
    ? {
        ...graphData,
        nodes: graphData.nodes.filter((node) => {
          if (node.node_type === 'article') return true;
          const entityType = node.properties?.entity_type as string;
          return !entityType || enabledEntityTypes.has(entityType);
        }),
        edges: graphData.edges.filter((edge) => {
          const relType = edge.relationship_type.toLowerCase();
          return enabledRelTypes.has(relType);
        }),
      }
    : null;

  // Handle edge click to fetch evidence
  const handleEdgeClick = useCallback(async (edge: GraphEdge) => {
    try {
      const evidence = await graphApi.getEdgeEvidence(
        edge.source_id,
        edge.target_id,
        edge.relationship_type
      );
      setSelectedEdge({ edge, evidence });
      setSelectedNode(null);
    } catch {
      setSelectedEdge({ edge, evidence: [] });
    }
  }, []);

  // D3 visualization
  useEffect(() => {
    if (!filteredGraphData || !svgRef.current) return;

    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    const width = svgRef.current.clientWidth;
    const height = svgRef.current.clientHeight;

    // Create zoom behavior
    const zoom = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.1, 4])
      .on('zoom', (event) => {
        container.attr('transform', event.transform);
      });

    zoomRef.current = zoom;
    svg.call(zoom);

    const container = svg.append('g');

    // Create arrow markers for directed edges
    svg
      .append('defs')
      .selectAll('marker')
      .data(['arrow'])
      .join('marker')
      .attr('id', 'arrow')
      .attr('viewBox', '0 -5 10 10')
      .attr('refX', 25)
      .attr('refY', 0)
      .attr('markerWidth', 6)
      .attr('markerHeight', 6)
      .attr('orient', 'auto')
      .append('path')
      .attr('fill', '#999')
      .attr('d', 'M0,-5L10,0L0,5');

    // Calculate node degrees for sizing
    const nodeDegrees: Record<string, number> = {};
    filteredGraphData.edges.forEach((edge) => {
      nodeDegrees[edge.source_id] = (nodeDegrees[edge.source_id] || 0) + 1;
      nodeDegrees[edge.target_id] = (nodeDegrees[edge.target_id] || 0) + 1;
    });

    // Prepare nodes and links for D3
    const nodeMap = new Map(
      filteredGraphData.nodes.map((n) => [n.node_id, n])
    );

    // Map edges to D3 link format (source/target instead of source_id/target_id)
    const validEdges = filteredGraphData.edges
      .filter((e) => nodeMap.has(e.source_id) && nodeMap.has(e.target_id))
      .map((e) => ({
        ...e,
        source: e.source_id,
        target: e.target_id,
      }));

    // Create simulation
    const simulation = d3
      .forceSimulation(filteredGraphData.nodes as d3.SimulationNodeDatum[])
      .force(
        'link',
        d3
          .forceLink(validEdges as any[])
          .id((d: any) => d.node_id)
          .distance(120)
      )
      .force('charge', d3.forceManyBody().strength(-400))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide().radius(50));

    // Draw edges
    const links = container
      .append('g')
      .attr('class', 'edges')
      .selectAll('line')
      .data(validEdges)
      .join('line')
      .attr('class', 'graph-edge cursor-pointer')
      .attr('stroke', '#94A3B8')
      .attr('stroke-width', (d) => Math.max(1.5, d.confidence * 4))
      .attr('stroke-opacity', 0.6)
      .attr('marker-end', 'url(#arrow)')
      .on('click', (_, d) => handleEdgeClick(d))
      .on('mouseenter', function () {
        d3.select(this).attr('stroke', '#3B82F6').attr('stroke-opacity', 1);
      })
      .on('mouseleave', function () {
        d3.select(this).attr('stroke', '#94A3B8').attr('stroke-opacity', 0.6);
      });

    // Draw edge labels
    const edgeLabels = container
      .append('g')
      .attr('class', 'edge-labels')
      .selectAll('text')
      .data(validEdges)
      .join('text')
      .attr('class', 'text-[10px] fill-gray-400 pointer-events-none')
      .attr('text-anchor', 'middle')
      .attr('dy', -5)
      .text((d) => d.relationship_type.replace(/_/g, ' '));

    // Draw nodes
    const nodes = container
      .append('g')
      .attr('class', 'nodes')
      .selectAll<SVGGElement, GraphNode>('g')
      .data(filteredGraphData.nodes)
      .join('g')
      .attr('class', 'graph-node cursor-pointer')
      .call(
        d3
          .drag<SVGGElement, GraphNode>()
          .on('start', (event, d: any) => {
            if (!event.active) simulation.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
          })
          .on('drag', (event, d: any) => {
            d.fx = event.x;
            d.fy = event.y;
          })
          .on('end', (event, d: any) => {
            if (!event.active) simulation.alphaTarget(0);
            d.fx = null;
            d.fy = null;
          })
      );

    // Node circles with size based on degree
    nodes
      .append('circle')
      .attr('r', (d) => {
        const degree = nodeDegrees[d.node_id] || 1;
        const baseSize = d.node_type === 'article' ? 22 : 18;
        return Math.min(baseSize + Math.sqrt(degree) * 3, 40);
      })
      .attr('fill', (d) => {
        const entityType = d.properties?.entity_type as string;
        return (
          NODE_COLORS[entityType] ||
          NODE_COLORS[d.node_type] ||
          '#6B7280'
        );
      })
      .attr('stroke', '#fff')
      .attr('stroke-width', 2)
      .attr('filter', 'drop-shadow(0 1px 2px rgba(0,0,0,0.1))');

    // Node icons for articles
    nodes
      .filter((d) => d.node_type === 'article')
      .append('text')
      .attr('text-anchor', 'middle')
      .attr('dy', 5)
      .attr('fill', 'white')
      .attr('font-size', '14px')
      .text('📄');

    // Node labels
    nodes
      .append('text')
      .attr('dy', (d) => {
        const degree = nodeDegrees[d.node_id] || 1;
        const baseSize = d.node_type === 'article' ? 22 : 18;
        return Math.min(baseSize + Math.sqrt(degree) * 3, 40) + 14;
      })
      .attr('text-anchor', 'middle')
      .attr('class', 'text-xs font-medium fill-gray-700')
      .text((d) =>
        d.label.length > 25 ? d.label.slice(0, 25) + '...' : d.label
      );

    // Hover effects
    nodes
      .on('mouseenter', function (_, d) {
        d3.select(this).select('circle').attr('stroke', '#3B82F6').attr('stroke-width', 3);
        // Highlight connected edges
        links.attr('stroke-opacity', (e: any) =>
          e.source.node_id === d.node_id || e.target.node_id === d.node_id
            ? 1
            : 0.2
        );
      })
      .on('mouseleave', function () {
        d3.select(this).select('circle').attr('stroke', '#fff').attr('stroke-width', 2);
        links.attr('stroke-opacity', 0.6);
      });

    // Click handler
    nodes.on('click', (_, d) => {
      setSelectedNode(d);
      setSelectedEdge(null);
    });

    // Double-click to recenter
    nodes.on('dblclick', (_, d) => {
      setCenterNodeId(d.node_id);
    });

    // Update positions on tick
    simulation.on('tick', () => {
      links
        .attr('x1', (d: any) => d.source.x)
        .attr('y1', (d: any) => d.source.y)
        .attr('x2', (d: any) => d.target.x)
        .attr('y2', (d: any) => d.target.y);

      edgeLabels
        .attr('x', (d: any) => (d.source.x + d.target.x) / 2)
        .attr('y', (d: any) => (d.source.y + d.target.y) / 2);

      nodes.attr('transform', (d: any) => `translate(${d.x},${d.y})`);
    });

    return () => {
      simulation.stop();
    };
  }, [filteredGraphData, handleEdgeClick]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
  };

  const handleSearchResultClick = (nodeId: string) => {
    setCenterNodeId(nodeId);
    setSearchQuery('');
  };

  const toggleEntityType = (type: string) => {
    setEnabledEntityTypes((prev) => {
      const next = new Set(prev);
      if (next.has(type)) {
        next.delete(type);
      } else {
        next.add(type);
      }
      return next;
    });
  };

  const toggleRelType = (type: string) => {
    setEnabledRelTypes((prev) => {
      const next = new Set(prev);
      if (next.has(type)) {
        next.delete(type);
      } else {
        next.add(type);
      }
      return next;
    });
  };

  const handleZoom = (direction: 'in' | 'out' | 'fit') => {
    if (!svgRef.current || !zoomRef.current) return;
    const svg = d3.select(svgRef.current);

    if (direction === 'fit') {
      svg.transition().duration(300).call(zoomRef.current.transform, d3.zoomIdentity);
    } else {
      const factor = direction === 'in' ? 1.3 : 0.7;
      svg.transition().duration(200).call(zoomRef.current.scaleBy, factor);
    }
  };

  const handleExport = (format: 'svg' | 'png') => {
    if (!svgRef.current) return;

    const svgElement = svgRef.current;
    const serializer = new XMLSerializer();
    const svgString = serializer.serializeToString(svgElement);

    if (format === 'svg') {
      const blob = new Blob([svgString], { type: 'image/svg+xml' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'knowledge-graph.svg';
      a.click();
      URL.revokeObjectURL(url);
    } else {
      const canvas = document.createElement('canvas');
      const ctx = canvas.getContext('2d');
      if (!ctx) return;

      const img = new Image();
      img.onload = () => {
        canvas.width = svgElement.clientWidth * 2;
        canvas.height = svgElement.clientHeight * 2;
        ctx.scale(2, 2);
        ctx.fillStyle = 'white';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(img, 0, 0);

        canvas.toBlob((blob) => {
          if (blob) {
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'knowledge-graph.png';
            a.click();
            URL.revokeObjectURL(url);
          }
        }, 'image/png');
      };
      img.src = 'data:image/svg+xml;base64,' + btoa(unescape(encodeURIComponent(svgString)));
    }
  };

  return (
    <div className="flex-1 flex overflow-hidden">
      {/* Sidebar Filters */}
      {showFilters && (
        <div className="w-64 border-r bg-white flex flex-col overflow-hidden">
          <div className="p-4 border-b flex items-center justify-between">
            <h3 className="font-semibold text-sm">Filters</h3>
            <button
              onClick={() => setShowFilters(false)}
              className="p-1 hover:bg-gray-100 rounded"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
          <div className="flex-1 overflow-auto p-4 space-y-6">
            {/* Confidence Slider */}
            <div>
              <label className="text-sm font-medium text-gray-700">
                Min Confidence: {minConfidence.toFixed(1)}
              </label>
              <input
                type="range"
                min="0"
                max="1"
                step="0.1"
                value={minConfidence}
                onChange={(e) => setMinConfidence(parseFloat(e.target.value))}
                className="w-full mt-2"
              />
            </div>

            {/* Entity Types */}
            <div>
              <h4 className="text-sm font-medium text-gray-700 mb-2">Entity Types</h4>
              <div className="space-y-1">
                {ENTITY_TYPES.map((type) => (
                  <label
                    key={type}
                    className="flex items-center gap-2 text-sm cursor-pointer"
                  >
                    <input
                      type="checkbox"
                      checked={enabledEntityTypes.has(type)}
                      onChange={() => toggleEntityType(type)}
                      className="rounded text-primary-500"
                    />
                    <span
                      className="w-2 h-2 rounded-full"
                      style={{ backgroundColor: NODE_COLORS[type] }}
                    />
                    <span className="capitalize">{type.replace(/_/g, ' ')}</span>
                  </label>
                ))}
              </div>
            </div>

            {/* Relationship Types */}
            <div>
              <h4 className="text-sm font-medium text-gray-700 mb-2">
                Relationship Types
              </h4>
              <div className="space-y-1">
                {RELATIONSHIP_TYPES.map((type) => (
                  <label
                    key={type}
                    className="flex items-center gap-2 text-sm cursor-pointer"
                  >
                    <input
                      type="checkbox"
                      checked={enabledRelTypes.has(type)}
                      onChange={() => toggleRelType(type)}
                      className="rounded text-primary-500"
                    />
                    <span className="capitalize">{type.replace(/_/g, ' ')}</span>
                  </label>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Graph Area */}
      <div className="flex-1 flex flex-col">
        {/* Toolbar */}
        <div className="border-b bg-white p-3 flex items-center gap-3">
          <button
            onClick={() => setShowFilters(!showFilters)}
            className={`p-2 rounded-lg border ${
              showFilters ? 'bg-primary-50 border-primary-200' : 'hover:bg-gray-50'
            }`}
            title="Toggle filters"
          >
            <Filter className="w-4 h-4" />
          </button>

          <div className="w-px h-6 bg-gray-200" />

          <form onSubmit={handleSearch} className="relative flex-1 max-w-md">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search entities..."
              className="w-full pl-10 pr-4 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm"
            />
            {searchResults && searchResults.length > 0 && searchQuery && (
              <div className="absolute top-full left-0 right-0 mt-1 bg-white border rounded-lg shadow-lg z-10 max-h-60 overflow-auto">
                {searchResults.map((result: any) => (
                  <button
                    key={result.node.node_id}
                    onClick={() => handleSearchResultClick(result.node.node_id)}
                    className="w-full px-4 py-2 text-left hover:bg-gray-50 flex items-center gap-2 text-sm"
                  >
                    <div
                      className="w-3 h-3 rounded-full flex-shrink-0"
                      style={{
                        backgroundColor:
                          NODE_COLORS[result.node.properties?.entity_type] ||
                          NODE_COLORS[result.node.node_type] ||
                          '#6B7280',
                      }}
                    />
                    <span className="truncate">{result.node.label}</span>
                    <span className="text-gray-400 text-xs ml-auto">
                      {(result.score * 100).toFixed(0)}%
                    </span>
                  </button>
                ))}
              </div>
            )}
          </form>

          <div className="flex items-center gap-2">
            <label className="text-sm text-gray-500">Depth:</label>
            <select
              value={depth}
              onChange={(e) => setDepth(Number(e.target.value))}
              className="border rounded px-2 py-1 text-sm"
            >
              {[1, 2, 3, 4, 5].map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          </div>

          <div className="w-px h-6 bg-gray-200" />

          <div className="flex items-center gap-1">
            <button
              onClick={() => handleZoom('out')}
              className="p-2 hover:bg-gray-100 rounded"
              title="Zoom out"
            >
              <ZoomOut className="w-4 h-4" />
            </button>
            <button
              onClick={() => handleZoom('in')}
              className="p-2 hover:bg-gray-100 rounded"
              title="Zoom in"
            >
              <ZoomIn className="w-4 h-4" />
            </button>
            <button
              onClick={() => handleZoom('fit')}
              className="p-2 hover:bg-gray-100 rounded"
              title="Fit to view"
            >
              <Maximize2 className="w-4 h-4" />
            </button>
          </div>

          <div className="w-px h-6 bg-gray-200" />

          <div className="relative group">
            <button className="p-2 hover:bg-gray-100 rounded flex items-center gap-1">
              <Download className="w-4 h-4" />
              <ChevronDown className="w-3 h-3" />
            </button>
            <div className="absolute right-0 top-full mt-1 bg-white border rounded-lg shadow-lg hidden group-hover:block z-10">
              <button
                onClick={() => handleExport('svg')}
                className="block w-full px-4 py-2 text-left text-sm hover:bg-gray-50"
              >
                Export as SVG
              </button>
              <button
                onClick={() => handleExport('png')}
                className="block w-full px-4 py-2 text-left text-sm hover:bg-gray-50"
              >
                Export as PNG
              </button>
            </div>
          </div>
        </div>

        {/* Graph SVG */}
        <div ref={containerRef} className="flex-1 relative bg-gradient-to-br from-gray-50 to-gray-100">
          {isLoading && (
            <div className="absolute inset-0 flex items-center justify-center bg-white/80 z-10">
              <Loader className="w-8 h-8 animate-spin text-primary-500" />
            </div>
          )}
          {!centerNodeId && !isLoading && (
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="text-center max-w-md">
                <div className="w-20 h-20 mx-auto mb-4 bg-gray-100 rounded-full flex items-center justify-center">
                  <Search className="w-10 h-10 text-gray-300" />
                </div>
                <p className="text-gray-500 mb-2">
                  Search for an entity to explore the knowledge graph
                </p>
                {stats && stats.total_nodes > 0 ? (
                  <>
                    <div className="text-sm text-gray-400 mb-4">
                      <span className="font-medium">{stats.total_nodes}</span> nodes ·{' '}
                      <span className="font-medium">{stats.total_relationships}</span>{' '}
                      relationships
                    </div>
                    <p className="text-xs text-gray-400 mb-2">Try searching:</p>
                    <div className="flex flex-wrap justify-center gap-2">
                      {['solar', 'Earth', 'NASA', 'flares'].map((term) => (
                        <button
                          key={term}
                          onClick={() => setSearchQuery(term)}
                          className="px-3 py-1 text-sm bg-gray-100 hover:bg-gray-200 rounded-full text-gray-600"
                        >
                          {term}
                        </button>
                      ))}
                    </div>
                  </>
                ) : (
                  <div className="text-sm text-gray-400">
                    {stats === undefined ? (
                      <span>Loading graph statistics...</span>
                    ) : (
                      <span>No entities in the graph yet. Upload and process a document to populate the knowledge graph.</span>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}
          <svg ref={svgRef} className="w-full h-full" />
        </div>

        {/* Legend */}
        <div className="border-t bg-white p-2 flex items-center gap-4 text-xs overflow-x-auto">
          {Object.entries(NODE_COLORS)
            .filter(([type]) => type !== 'entity')
            .map(([type, color]) => (
              <div key={type} className="flex items-center gap-1 flex-shrink-0">
                <div
                  className="w-3 h-3 rounded-full"
                  style={{ backgroundColor: color }}
                />
                <span className="capitalize text-gray-600">
                  {type.replace(/_/g, ' ')}
                </span>
              </div>
            ))}
        </div>
      </div>

      {/* Node Detail Panel */}
      {selectedNode && (
        <div className="w-80 border-l bg-white flex flex-col">
          <div className="p-4 border-b flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div
                className="w-4 h-4 rounded-full"
                style={{
                  backgroundColor:
                    NODE_COLORS[selectedNode.properties?.entity_type as string] ||
                    NODE_COLORS[selectedNode.node_type] ||
                    '#6B7280',
                }}
              />
              <h3 className="font-semibold truncate">{selectedNode.label}</h3>
            </div>
            <button
              onClick={() => setSelectedNode(null)}
              className="p-1 hover:bg-gray-100 rounded"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
          <div className="flex-1 overflow-auto p-4">
            <div className="space-y-4">
              <div>
                <p className="text-sm text-gray-500 mb-1">Type</p>
                <p className="capitalize font-medium">
                  {selectedNode.node_type === 'entity'
                    ? ((selectedNode.properties?.entity_type as string) || 'Entity').replace(
                        /_/g,
                        ' '
                      )
                    : 'Article'}
                </p>
              </div>

              {typeof selectedNode.properties?.canonical_name === 'string' && (
                <div>
                  <p className="text-sm text-gray-500 mb-1">Canonical Name</p>
                  <p className="text-sm">{selectedNode.properties.canonical_name}</p>
                </div>
              )}

              {Array.isArray(selectedNode.properties?.aliases) &&
                selectedNode.properties.aliases.length > 0 && (
                  <div>
                    <p className="text-sm text-gray-500 mb-1">Aliases</p>
                    <div className="flex flex-wrap gap-1">
                      {selectedNode.properties.aliases.map((alias, i) => (
                        <span
                          key={i}
                          className="px-2 py-0.5 bg-gray-100 rounded text-xs"
                        >
                          {String(alias)}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

              {selectedNode.node_type === 'article' && (
                <>
                  {selectedNode.properties?.year && (
                    <div>
                      <p className="text-sm text-gray-500 mb-1">Year</p>
                      <p className="text-sm">{String(selectedNode.properties.year)}</p>
                    </div>
                  )}
                  {selectedNode.properties?.doi && (
                    <div>
                      <p className="text-sm text-gray-500 mb-1">DOI</p>
                      <a
                        href={`https://doi.org/${selectedNode.properties.doi}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-sm text-primary-500 hover:underline flex items-center gap-1"
                      >
                        {selectedNode.properties.doi as string}
                        <Link2 className="w-3 h-3" />
                      </a>
                    </div>
                  )}
                  {selectedNode.properties?.authors &&
                    Array.isArray(selectedNode.properties.authors) && (
                    <div>
                      <p className="text-sm text-gray-500 mb-1">Authors</p>
                      <p className="text-sm">
                        {selectedNode.properties.authors.map(String).join(', ')}
                      </p>
                    </div>
                  )}
                </>
              )}

              <div>
                <p className="text-sm text-gray-500 mb-1">ID</p>
                <p className="font-mono text-xs break-all text-gray-600">
                  {selectedNode.node_id}
                </p>
              </div>
            </div>

            <button
              onClick={() => setCenterNodeId(selectedNode.node_id)}
              className="mt-6 w-full px-4 py-2 bg-primary-500 text-white rounded-lg hover:bg-primary-600 text-sm font-medium"
            >
              Center on this node
            </button>
          </div>
        </div>
      )}

      {/* Edge Evidence Panel */}
      {selectedEdge && (
        <div className="w-96 border-l bg-white flex flex-col">
          <div className="p-4 border-b flex items-center justify-between">
            <div>
              <h3 className="font-semibold">Relationship Evidence</h3>
              <p className="text-sm text-gray-500 capitalize mt-1">
                {selectedEdge.edge.relationship_type.replace(/_/g, ' ')}
              </p>
            </div>
            <button
              onClick={() => setSelectedEdge(null)}
              className="p-1 hover:bg-gray-100 rounded"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
          <div className="flex-1 overflow-auto p-4">
            <div className="mb-4 p-3 bg-gray-50 rounded-lg">
              <div className="flex items-center gap-2 text-sm">
                <span className="font-medium">Confidence:</span>
                <div className="flex-1 h-2 bg-gray-200 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-primary-500 rounded-full"
                    style={{ width: `${selectedEdge.edge.confidence * 100}%` }}
                  />
                </div>
                <span className="text-gray-600">
                  {(selectedEdge.edge.confidence * 100).toFixed(0)}%
                </span>
              </div>
            </div>

            {selectedEdge.evidence.length === 0 ? (
              <p className="text-sm text-gray-500 text-center py-4">
                No evidence snippets available
              </p>
            ) : (
              <div className="space-y-3">
                <h4 className="text-sm font-medium text-gray-700">
                  Evidence Snippets ({selectedEdge.evidence.length})
                </h4>
                {selectedEdge.evidence.map((ev, i) => (
                  <div key={i} className="p-3 bg-gray-50 rounded-lg border border-gray-100">
                    <p className="text-sm text-gray-700 italic">"{ev.snippet}"</p>
                    <div className="mt-2 flex items-center gap-2 text-xs text-gray-500">
                      <FileText className="w-3 h-3" />
                      <span className="font-mono truncate">{ev.document_id.slice(0, 8)}...</span>
                      <span>·</span>
                      <span>chars {ev.char_start}-{ev.char_end}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
