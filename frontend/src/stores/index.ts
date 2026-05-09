import { create } from 'zustand';

interface KB {
  id: string;
  name: string;
  description: string;
  top_k: number;
  similarity_threshold: number;
  document_count: number;
  created_at: string;
  updated_at: string;
}

interface AppState {
  kbs: KB[];
  selectedKB: KB | null;
  loading: boolean;
  setKBs: (kbs: KB[]) => void;
  setSelectedKB: (kb: KB | null) => void;
  setLoading: (loading: boolean) => void;
}

export const useAppStore = create<AppState>((set) => ({
  kbs: [],
  selectedKB: null,
  loading: false,
  setKBs: (kbs) => set({ kbs }),
  setSelectedKB: (kb) => set({ selectedKB: kb }),
  setLoading: (loading) => set({ loading }),
}));

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  citations?: Array<{
    chunk_id: string;
    document_name: string;
    content: string;
    score: number;
  }>;
}

interface ChatState {
  messages: ChatMessage[];
  streaming: boolean;
  addMessage: (msg: ChatMessage) => void;
  setStreaming: (s: boolean) => void;
  clearMessages: () => void;
}

export const useChatStore = create<ChatState>((set) => ({
  messages: [],
  streaming: false,
  addMessage: (msg) => set((s) => ({ messages: [...s.messages, msg] })),
  setStreaming: (streaming) => set({ streaming }),
  clearMessages: () => set({ messages: [] }),
}));
