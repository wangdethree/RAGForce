import { useState, useRef, useEffect } from 'react';
import { Input, Button, Select, Card, Typography, Space, Tag, Spin } from 'antd';
import { SendOutlined, ClearOutlined } from '@ant-design/icons';
import { kbApi, chatApi } from '../../services/api';
import { useChatStore } from '../../stores';

export default function ChatPage() {
  const [kbs, setKBs] = useState<Array<{ id: string; name: string }>>([]);
  const [selectedKB, setSelectedKB] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const { messages, streaming, addMessage, setStreaming, clearMessages } = useChatStore();

  useEffect(() => {
    kbApi.list().then((res) => setKBs(res.data.items || []));
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = async () => {
    if (!query.trim() || !selectedKB) return;
    const userMsg = query;
    addMessage({ role: 'user', content: userMsg });
    setQuery('');
    setStreaming(true);

    try {
      const res = await chatApi.send({
        kb_id: selectedKB,
        query: userMsg,
        history: messages.map((m) => ({ role: m.role, content: m.content })),
      });
      addMessage({ role: 'assistant', content: res.data.answer, citations: res.data.citations });
    } catch {
      addMessage({ role: 'assistant', content: 'Error calling the API. Please check your backend connection.' });
    } finally {
      setStreaming(false);
    }
  };

  return (
    <div style={{ maxWidth: 800, margin: '0 auto' }}>
      <Space style={{ marginBottom: 16, width: '100%' }} direction="vertical">
        <Space>
          <Select
            placeholder="Select a knowledge base"
            style={{ width: 300 }}
            value={selectedKB}
            onChange={setSelectedKB}
            options={kbs.map((kb) => ({ value: kb.id, label: kb.name }))}
          />
          <Button icon={<ClearOutlined />} onClick={clearMessages} disabled={messages.length === 0}>
            Clear
          </Button>
        </Space>
      </Space>

      <Card style={{ height: 500, overflow: 'auto', marginBottom: 16 }}>
        {messages.length === 0 && (
          <Typography.Text type="secondary" style={{ display: 'block', textAlign: 'center', marginTop: 200 }}>
            Select a knowledge base and start asking questions.
          </Typography.Text>
        )}
        {messages.map((msg, i) => (
          <div key={i} style={{ marginBottom: 16, textAlign: msg.role === 'user' ? 'right' : 'left' }}>
            <Tag color={msg.role === 'user' ? 'blue' : 'green'}>{msg.role === 'user' ? 'You' : 'RAGForce'}</Tag>
            <div style={{
              display: 'inline-block',
              maxWidth: '80%',
              padding: '8px 12px',
              borderRadius: 8,
              background: msg.role === 'user' ? '#e6f4ff' : '#f6ffed',
              textAlign: 'left',
              whiteSpace: 'pre-wrap',
            }}>
              {msg.content}
            </div>
            {msg.citations && msg.citations.length > 0 && (
              <div style={{ marginTop: 4 }}>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  Sources: {msg.citations.map((c, j) => (
                    <Tag key={j} style={{ fontSize: 11 }}>{c.document_name || `Source ${j + 1}`}</Tag>
                  ))}
                </Typography.Text>
              </div>
            )}
          </div>
        ))}
        {streaming && <Spin size="small" />}
        <div ref={messagesEndRef} />
      </Card>

      <Space.Compact style={{ width: '100%' }}>
        <Input.TextArea
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onPressEnter={(e) => { if (!e.shiftKey) { e.preventDefault(); handleSend(); } }}
          placeholder="Ask a question about your knowledge base... (Enter to send, Shift+Enter for new line)"
          rows={2}
          disabled={!selectedKB}
        />
        <Button type="primary" icon={<SendOutlined />} onClick={handleSend} loading={streaming} disabled={!selectedKB}>
          Send
        </Button>
      </Space.Compact>
    </div>
  );
}
