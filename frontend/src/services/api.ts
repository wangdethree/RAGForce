import axios from 'axios';

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 120000,
  headers: { 'Content-Type': 'application/json' },
});

// 仪表盘 API
export const dashboardApi = {
  stats: () => api.get('/dashboard/stats'),
  recentKBs: () => api.get('/dashboard/recent-kbs'),
};

// 知识库 API
export const kbApi = {
  list: () => api.get('/knowledge-bases'),
  get: (id: string) => api.get(`/knowledge-bases/${id}`),
  create: (data: { name: string; description?: string; top_k?: number; similarity_threshold?: number }) =>
    api.post('/knowledge-bases', data),
  update: (id: string, data: Record<string, unknown>) => api.patch(`/knowledge-bases/${id}`, data),
  delete: (id: string) => api.delete(`/knowledge-bases/${id}`),
};

// 文档 API
export const docApi = {
  list: (kbId: string) => api.get(`/documents/kb/${kbId}`),
  get: (id: string) => api.get(`/documents/${id}`),
  upload: (kbId: string, file: File) => {
    const formData = new FormData();
    formData.append('kb_id', kbId);
    formData.append('file', file);
    return api.post('/documents/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
  delete: (id: string) => api.delete(`/documents/${id}`),
};

// 检索 API
export const retrievalApi = {
  search: (data: { kb_id: string; query: string; top_k?: number; similarity_threshold?: number; use_hybrid?: boolean; use_rerank?: boolean }) =>
    api.post('/retrieval', data),
};

// 对话 API
export const chatApi = {
  send: (data: { kb_id: string; query: string; top_k?: number; history?: Array<{ role: string; content: string }> }) =>
    api.post('/chat', data),
};

// 审计日志 API
export const auditApi = {
  list: (params?: { action?: string; resource_type?: string; limit?: number; offset?: number }) =>
    api.get('/audit-logs', { params }),
};

export default api;
