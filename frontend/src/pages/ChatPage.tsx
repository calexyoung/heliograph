import { useState, useRef, useEffect } from 'react';
import { useMutation } from '@tanstack/react-query';
import ReactMarkdown from 'react-markdown';
import { Send, Loader, BookOpen, X } from 'lucide-react';
import { queryApi } from '../services/api';
import { useChatStore } from '../stores/chatStore';
import type { Citation, ChatMessage } from '../types';

export default function ChatPage() {
  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const {
    messages,
    isLoading,
    currentCitation,
    addMessage,
    setLoading,
    setCurrentCitation,
  } = useChatStore();

  const queryMutation = useMutation({
    mutationFn: (query: string) =>
      queryApi.query({ query, streaming: false }),
    onSuccess: (data) => {
      addMessage({
        id: crypto.randomUUID(),
        role: 'assistant',
        content: data.answer,
        citations: data.citations,
        timestamp: new Date(),
      });
      setLoading(false);
    },
    onError: () => {
      addMessage({
        id: crypto.randomUUID(),
        role: 'assistant',
        content: 'Sorry, I encountered an error processing your question. Please try again.',
        timestamp: new Date(),
      });
      setLoading(false);
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    // Add user message
    addMessage({
      id: crypto.randomUUID(),
      role: 'user',
      content: input.trim(),
      timestamp: new Date(),
    });

    setLoading(true);
    queryMutation.mutate(input.trim());
    setInput('');
  };

  const handleCitationClick = (citation: Citation) => {
    setCurrentCitation(citation);
  };

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Render message content with citation highlighting
  const renderContent = (content: string, citations?: Citation[]) => {
    if (!citations || citations.length === 0) {
      return <ReactMarkdown>{content}</ReactMarkdown>;
    }

    // Replace [N] with clickable citations
    const parts = content.split(/(\[\d+\])/g);
    return (
      <div className="prose prose-sm max-w-none">
        {parts.map((part, index) => {
          const match = part.match(/\[(\d+)\]/);
          if (match) {
            const citationId = parseInt(match[1]);
            const citation = citations.find((c) => c.citation_id === citationId);
            if (citation) {
              return (
                <button
                  key={index}
                  onClick={() => handleCitationClick(citation)}
                  className="citation"
                >
                  [{citationId}]
                </button>
              );
            }
          }
          return <span key={index}>{part}</span>;
        })}
      </div>
    );
  };

  return (
    <div className="flex-1 flex overflow-hidden">
      {/* Chat Area */}
      <div className="flex-1 flex flex-col">
        {/* Messages */}
        <div className="flex-1 overflow-auto p-6">
          {messages.length === 0 ? (
            <div className="h-full flex items-center justify-center">
              <div className="text-center max-w-md">
                <BookOpen className="w-16 h-16 mx-auto mb-4 text-gray-300" />
                <h2 className="text-xl font-semibold text-gray-700 mb-2">
                  Ask about your research
                </h2>
                <p className="text-gray-500">
                  Ask questions about your document corpus. I'll provide answers
                  with citations to the source papers.
                </p>
                <div className="mt-6 space-y-2">
                  <p className="text-sm text-gray-400">Try asking:</p>
                  <div className="flex flex-wrap gap-2 justify-center">
                    {[
                      'What causes geomagnetic storms?',
                      'How does the solar wind affect Earth?',
                      'Explain magnetic reconnection',
                    ].map((suggestion) => (
                      <button
                        key={suggestion}
                        onClick={() => setInput(suggestion)}
                        className="px-3 py-1.5 bg-gray-100 text-gray-600 rounded-full text-sm hover:bg-gray-200"
                      >
                        {suggestion}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <div className="max-w-3xl mx-auto space-y-6">
              {messages.map((message: ChatMessage) => (
                <div
                  key={message.id}
                  className={`chat-message flex gap-4 ${
                    message.role === 'user' ? 'flex-row-reverse' : ''
                  }`}
                >
                  <div
                    className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 ${
                      message.role === 'user'
                        ? 'bg-primary-500 text-white'
                        : 'bg-gray-200 text-gray-600'
                    }`}
                  >
                    {message.role === 'user' ? 'U' : 'H'}
                  </div>
                  <div
                    className={`flex-1 max-w-[80%] ${
                      message.role === 'user' ? 'text-right' : ''
                    }`}
                  >
                    <div
                      className={`inline-block p-4 rounded-2xl ${
                        message.role === 'user'
                          ? 'bg-primary-500 text-white rounded-tr-sm'
                          : 'bg-white border rounded-tl-sm'
                      }`}
                    >
                      {message.role === 'user' ? (
                        <p>{message.content}</p>
                      ) : (
                        renderContent(message.content, message.citations)
                      )}
                    </div>
                    {message.citations && message.citations.length > 0 && (
                      <div className="mt-2 text-xs text-gray-500">
                        {message.citations.length} source
                        {message.citations.length !== 1 ? 's' : ''} cited
                      </div>
                    )}
                  </div>
                </div>
              ))}
              {isLoading && (
                <div className="flex gap-4">
                  <div className="w-8 h-8 rounded-full bg-gray-200 flex items-center justify-center">
                    H
                  </div>
                  <div className="flex items-center gap-2 text-gray-500">
                    <Loader className="w-4 h-4 animate-spin" />
                    <span>Searching and generating response...</span>
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>
          )}
        </div>

        {/* Input */}
        <div className="border-t bg-white p-4">
          <form onSubmit={handleSubmit} className="max-w-3xl mx-auto">
            <div className="flex gap-3">
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Ask a question about your research..."
                disabled={isLoading}
                className="flex-1 px-4 py-3 border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:opacity-50"
              />
              <button
                type="submit"
                disabled={!input.trim() || isLoading}
                className="px-6 py-3 bg-primary-500 text-white rounded-lg hover:bg-primary-600 disabled:opacity-50 flex items-center gap-2"
              >
                <Send className="w-5 h-5" />
              </button>
            </div>
          </form>
        </div>
      </div>

      {/* Citation Panel */}
      {currentCitation && (
        <div className="w-96 border-l bg-white flex flex-col">
          <div className="p-4 border-b flex items-center justify-between">
            <h3 className="font-semibold">Citation [{currentCitation.citation_id}]</h3>
            <button
              onClick={() => setCurrentCitation(null)}
              className="p-1 hover:bg-gray-100 rounded"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
          <div className="flex-1 overflow-auto p-4">
            <div className="space-y-4">
              <div>
                <p className="text-sm text-gray-500 mb-1">Title</p>
                <p className="font-medium">{currentCitation.title}</p>
              </div>
              {currentCitation.authors.length > 0 && (
                <div>
                  <p className="text-sm text-gray-500 mb-1">Authors</p>
                  <p>{currentCitation.authors.join(', ')}</p>
                </div>
              )}
              {currentCitation.year && (
                <div>
                  <p className="text-sm text-gray-500 mb-1">Year</p>
                  <p>{currentCitation.year}</p>
                </div>
              )}
              {currentCitation.section && (
                <div>
                  <p className="text-sm text-gray-500 mb-1">Section</p>
                  <p>{currentCitation.section}</p>
                </div>
              )}
              {currentCitation.page && (
                <div>
                  <p className="text-sm text-gray-500 mb-1">Page</p>
                  <p>{currentCitation.page}</p>
                </div>
              )}
              <div>
                <p className="text-sm text-gray-500 mb-1">Excerpt</p>
                <div className="p-3 bg-gray-50 rounded-lg text-sm">
                  "{currentCitation.snippet}"
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
