import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Table, Upload, Button, message, Tag, Descriptions, Card, Popconfirm } from 'antd';
import { UploadOutlined, ArrowLeftOutlined, DeleteOutlined } from '@ant-design/icons';
import type { UploadProps } from 'antd';
import { kbApi, docApi } from '../../services/api';

const statusColors: Record<string, string> = {
  uploaded: 'default',
  parsing: 'processing',
  chunking: 'processing',
  embedding: 'processing',
  indexing: 'processing',
  ready: 'success',
  failed: 'error',
};

export default function KnowledgeBaseDetail() {
  const { kbId } = useParams<{ kbId: string }>();
  const navigate = useNavigate();
  const [kb, setKB] = useState<{ id: string; name: string; description: string; document_count: number; top_k: number; similarity_threshold: number } | null>(null);
  const [docs, setDocs] = useState([]);
  const [loading, setLoading] = useState(false);

  const fetchData = async () => {
    if (!kbId) return;
    setLoading(true);
    try {
      const [kbRes, docRes] = await Promise.all([kbApi.get(kbId), docApi.list(kbId)]);
      setKB(kbRes.data);
      setDocs(docRes.data.items || []);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchData(); }, [kbId]);

  const uploadProps: UploadProps = {
    name: 'file',
    multiple: true,
    showUploadList: { showPreviewIcon: false },
    customRequest: async ({ file, onSuccess, onError }) => {
      try {
        await docApi.upload(kbId!, file as File);
        message.success(`${(file as File).name} uploaded`);
        onSuccess?.(null);
        fetchData();
      } catch {
        onError?.(new Error('Upload failed'));
      }
    },
  };

  const handleDeleteDoc = async (docId: string) => {
    await docApi.delete(docId);
    message.success('Document deleted');
    fetchData();
  };

  if (!kb) return null;

  return (
    <div>
      <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/knowledge-bases')} style={{ marginBottom: 16 }}>
        Back
      </Button>

      <Card title={kb.name} style={{ marginBottom: 24 }}>
        <Descriptions column={3}>
          <Descriptions.Item label="Description">{kb.description || '-'}</Descriptions.Item>
          <Descriptions.Item label="Documents">{kb.document_count}</Descriptions.Item>
          <Descriptions.Item label="Top K">{kb.top_k}</Descriptions.Item>
          <Descriptions.Item label="Similarity Threshold">{kb.similarity_threshold}</Descriptions.Item>
        </Descriptions>
      </Card>

      <Card
        title="Documents"
        extra={
          <Upload {...uploadProps}>
            <Button type="primary" icon={<UploadOutlined />}>Upload</Button>
          </Upload>
        }
      >
        <Table
          dataSource={docs}
          rowKey="id"
          loading={loading}
          columns={[
            { title: 'Filename', dataIndex: 'filename' },
            { title: 'Type', dataIndex: 'file_type', width: 80 },
            { title: 'Size', dataIndex: 'file_size', render: (v: number) => `${(v / 1024).toFixed(1)} KB` },
            { title: 'Chunks', dataIndex: 'chunk_count', width: 80 },
            {
              title: 'Status', dataIndex: 'status', width: 100,
              render: (v: string) => <Tag color={statusColors[v] || 'default'}>{v}</Tag>,
            },
            { title: 'Uploaded', dataIndex: 'created_at', render: (v: string) => new Date(v).toLocaleDateString() },
            {
              title: 'Actions',
              render: (_: unknown, record: { id: string }) => (
                <Popconfirm title="Delete this document?" onConfirm={() => handleDeleteDoc(record.id)}>
                  <Button type="text" danger icon={<DeleteOutlined />} />
                </Popconfirm>
              ),
            },
          ]}
        />
      </Card>
    </div>
  );
}
