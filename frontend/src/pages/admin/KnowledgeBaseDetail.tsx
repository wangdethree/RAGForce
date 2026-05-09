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

const statusLabels: Record<string, string> = {
  uploaded: '已上传',
  parsing: '解析中',
  chunking: '分块中',
  embedding: '向量化中',
  indexing: '索引中',
  ready: '就绪',
  failed: '失败',
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
    } catch {
      message.error('获取数据失败');
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
        message.success(`${(file as File).name} 上传成功`);
        onSuccess?.(null);
        fetchData();
      } catch {
        message.error(`${(file as File).name} 上传失败`);
        onError?.(new Error('上传失败'));
      }
    },
  };

  const handleDeleteDoc = async (docId: string) => {
    await docApi.delete(docId);
    message.success('文档已删除');
    fetchData();
  };

  if (!kb) return null;

  return (
    <div>
      <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/knowledge-bases')} style={{ marginBottom: 16 }}>
        返回
      </Button>

      <Card title={kb.name} style={{ marginBottom: 24 }}>
        <Descriptions column={3}>
          <Descriptions.Item label="描述">{kb.description || '-'}</Descriptions.Item>
          <Descriptions.Item label="文档数">{kb.document_count}</Descriptions.Item>
          <Descriptions.Item label="Top K">{kb.top_k}</Descriptions.Item>
          <Descriptions.Item label="相似度阈值">{kb.similarity_threshold}</Descriptions.Item>
        </Descriptions>
      </Card>

      <Card
        title="文档列表"
        extra={
          <Upload {...uploadProps}>
            <Button type="primary" icon={<UploadOutlined />}>上传文档</Button>
          </Upload>
        }
      >
        <Table
          dataSource={docs}
          rowKey="id"
          loading={loading}
          columns={[
            { title: '文件名', dataIndex: 'filename' },
            { title: '类型', dataIndex: 'file_type', width: 80 },
            { title: '大小', dataIndex: 'file_size', render: (v: number) => `${(v / 1024).toFixed(1)} KB` },
            { title: '分块数', dataIndex: 'chunk_count', width: 80 },
            {
              title: '状态', dataIndex: 'status', width: 100,
              render: (v: string) => <Tag color={statusColors[v] || 'default'}>{statusLabels[v] || v}</Tag>,
            },
            { title: '上传时间', dataIndex: 'created_at', render: (v: string) => new Date(v).toLocaleDateString() },
            {
              title: '操作',
              render: (_: unknown, record: { id: string }) => (
                <Popconfirm title="确定删除该文档？" onConfirm={() => handleDeleteDoc(record.id)}>
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
