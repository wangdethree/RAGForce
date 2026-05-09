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
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchKBs(); }, []);

  const handleCreate = async () => {
    try {
      const values = await form.validateFields();
      await kbApi.create(values);
      message.success('Knowledge base created');
      setModalOpen(false);
      form.resetFields();
      fetchKBs();
    } catch {
      // validation failed
    }
  };

  const handleDelete = async (id: string) => {
    await kbApi.delete(id);
    message.success('Knowledge base deleted');
    fetchKBs();
  };

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between' }}>
        <h2>Knowledge Bases</h2>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>
          Create KB
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
          { title: 'Name', dataIndex: 'name' },
          { title: 'Description', dataIndex: 'description', ellipsis: true },
          { title: 'Documents', dataIndex: 'document_count' },
          { title: 'Top K', dataIndex: 'top_k', width: 80 },
          { title: 'Similarity', dataIndex: 'similarity_threshold', width: 100 },
          {
            title: 'Created',
            dataIndex: 'created_at',
            render: (v: string) => new Date(v).toLocaleDateString(),
          },
          {
            title: 'Actions',
            render: (_: unknown, record: { id: string }) => (
              <Popconfirm title="Delete this KB and all documents?" onConfirm={(e) => { e?.stopPropagation(); handleDelete(record.id); }} onCancel={(e) => e?.stopPropagation()}>
                <Button type="text" danger icon={<DeleteOutlined />} onClick={(e) => e.stopPropagation()} />
              </Popconfirm>
            ),
          },
        ]}
      />

      <Modal
        title="Create Knowledge Base"
        open={modalOpen}
        onOk={handleCreate}
        onCancel={() => { setModalOpen(false); form.resetFields(); }}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="Name" rules={[{ required: true, message: 'Name is required' }]}>
            <Input placeholder="e.g. Technical Docs" />
          </Form.Item>
          <Form.Item name="description" label="Description">
            <Input.TextArea rows={3} placeholder="Brief description of this knowledge base" />
          </Form.Item>
          <Space size="large">
            <Form.Item name="top_k" label="Top K" initialValue={5}>
              <InputNumber min={1} max={100} />
            </Form.Item>
            <Form.Item name="similarity_threshold" label="Similarity Threshold" initialValue={0.7}>
              <InputNumber min={0} max={1} step={0.05} />
            </Form.Item>
          </Space>
        </Form>
      </Modal>
    </div>
  );
}
