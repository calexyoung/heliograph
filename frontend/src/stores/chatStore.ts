import { create } from 'zustand';
import type { ChatMessage, Citation } from '../types';

interface ChatState {
  messages: ChatMessage[];
  isLoading: boolean;
  currentCitation: Citation | null;
  addMessage: (message: ChatMessage) => void;
  updateLastMessage: (content: string, citations?: Citation[]) => void;
  setLoading: (loading: boolean) => void;
  setCurrentCitation: (citation: Citation | null) => void;
  clearMessages: () => void;
}

export const useChatStore = create<ChatState>((set) => ({
  messages: [],
  isLoading: false,
  currentCitation: null,

  addMessage: (message) =>
    set((state) => ({
      messages: [...state.messages, message],
    })),

  updateLastMessage: (content, citations) =>
    set((state) => {
      const messages = [...state.messages];
      if (messages.length > 0) {
        const last = messages[messages.length - 1];
        messages[messages.length - 1] = {
          ...last,
          content: content,
          citations: citations || last.citations,
        };
      }
      return { messages };
    }),

  setLoading: (loading) => set({ isLoading: loading }),

  setCurrentCitation: (citation) => set({ currentCitation: citation }),

  clearMessages: () => set({ messages: [] }),
}));
