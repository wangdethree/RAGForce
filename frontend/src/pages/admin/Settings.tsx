import { Card, Form, InputNumber, Button, Divider, Typography, message } from 'antd';
import { SaveOutlined } from '@ant-design/icons';

export default function Settings() {
  const [form] = Form.useForm();

  const handleSave = () => {
    message.success('Settings saved');
  };

  return (
    <div style={{ maxWidth: 600 }}>
      <Card title="System Settings">
        <Form form={form} layout="vertical">
          <Typography.Title level={5}>Retrieval Defaults</Typography.Title>
          <Form.Item name="default_top_k" label="Default Top K" initialValue={5}>
            <InputNumber min={1} max={100} style={{ width: 200 }} />
          </Form.Item>
          <Form.Item name="default_similarity_threshold" label="Default Similarity Threshold" initialValue={0.7}>
            <InputNumber min={0} max={1} step={0.05} style={{ width: 200 }} />
          </Form.Item>
          <Form.Item name="max_chunk_size" label="Max Chunk Size" initialValue={512}>
            <InputNumber min={128} max={4096} step={64} style={{ width: 200 }} />
          </Form.Item>
          <Form.Item name="chunk_overlap" label="Chunk Overlap" initialValue={50}>
            <InputNumber min={0} max={512} style={{ width: 200 }} />
          </Form.Item>

          <Divider />
          <Typography.Title level={5}>DeepSeek API</Typography.Title>
          <Form.Item name="deepseek_model" label="Chat Model" initialValue="deepseek-chat">
            <InputNumber disabled style={{ width: 200 }} />
          </Form.Item>
          <Form.Item name="max_tokens" label="Max Response Tokens" initialValue={2048}>
            <InputNumber min={256} max={8192} step={256} style={{ width: 200 }} />
          </Form.Item>

          <Button type="primary" icon={<SaveOutlined />} onClick={handleSave}>
            Save Settings
          </Button>
        </Form>
      </Card>
    </div>
  );
}
