import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Table, Button, Modal, Form, Input, InputNumber, Space, Popconfirm, message } from 'antd';
import { PlusOutlined, DeleteOutlined } from '@ant-design/icons';
import { kbApi } from '../../services/api';

export default function KnowledgeBaseList() {
  const [kbs, setKBs] = useState([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [form] = Form.useForm();
  const navigate = useNavigate();

  const fetchKBs = async () => {
    setLoading(true);
    try {
      const res = await kbApi.list();
      setKBs(res.data.items || []);
    } catch {
      message.error('获取知识库列表失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchKBs(); }, []);

  const handleCreate = async () => {
    try {
      const values = await form.validateFields();
      await kbApi.create(values);
      message.success('知识库创建成功');
      setModalOpen(false);
      form.resetFields();
      fetchKBs();
    } catch {
      // 表单校验失败
    }
  };

  const handleDelete = async (id: string) => {
    await kbApi.delete(id);
    message.success('知识库已删除');
    fetchKBs();
  };

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between' }}>
        <h2>知识库管理</h2>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>
          创建知识库
        </Button>
      </div>

      <Table
        dataSource={kbs}
        rowKey="id"
        loading={loading}
        onRow={(record: { id: string }) => ({
          onClick: () => navigate(`/knowledge-bases/${record.id}`),
          style: { cursor: 'pointer' },
        })}
        columns={[
          { title: '名称', dataIndex: 'name' },
          { title: '描述', dataIndex: 'description', ellipsis: true },
          { title: '文档数', dataIndex: 'document_count' },
          { title: 'Top K', dataIndex: 'top_k', width: 80 },
          { title: '相似度阈值', dataIndex: 'similarity_threshold', width: 100 },
          {
            title: '创建时间',
            dataIndex: 'created_at',
            render: (v: string) => new Date(v).toLocaleDateString(),
          },
          {
            title: '操作',
            render: (_: unknown, record: { id: string }) => (
              <Popconfirm title="确定删除该知识库及其所有文档？" onConfirm={(e) => { e?.stopPropagation(); handleDelete(record.id); }} onCancel={(e) => e?.stopPropagation()}>
                <Button type="text" danger icon={<DeleteOutlined />} onClick={(e) => e.stopPropagation()} />
              </Popconfirm>
            ),
          },
        ]}
      />

      <Modal
        title="创建知识库"
        open={modalOpen}
        onOk={handleCreate}
        onCancel={() => { setModalOpen(false); form.resetFields(); }}
        okText="创建"
        cancelText="取消"
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入知识库名称' }]}>
            <Input placeholder="例如：技术文档库" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={3} placeholder="简要描述该知识库的内容" />
          </Form.Item>
          <Space size="large">
            <Form.Item name="top_k" label="Top K" initialValue={5}>
              <InputNumber min={1} max={100} />
            </Form.Item>
            <Form.Item name="similarity_threshold" label="相似度阈值" initialValue={0.7}>
              <InputNumber min={0} max={1} step={0.05} />
            </Form.Item>
          </Space>
        </Form>
      </Modal>
    </div>
  );
}
