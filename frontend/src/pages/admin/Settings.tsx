import { Card, Form, InputNumber, Button, Divider, Typography, message } from 'antd';
import { SaveOutlined } from '@ant-design/icons';

export default function Settings() {
  const [form] = Form.useForm();

  const handleSave = () => {
    message.success('设置已保存');
  };

  return (
    <div style={{ maxWidth: 600 }}>
      <Card title="系统设置">
        <Form form={form} layout="vertical">
          <Typography.Title level={5}>检索默认参数</Typography.Title>
          <Form.Item name="default_top_k" label="默认 Top K" initialValue={5}>
            <InputNumber min={1} max={100} style={{ width: 200 }} />
          </Form.Item>
          <Form.Item name="default_similarity_threshold" label="默认相似度阈值" initialValue={0.7}>
            <InputNumber min={0} max={1} step={0.05} style={{ width: 200 }} />
          </Form.Item>
          <Form.Item name="max_chunk_size" label="最大分块大小" initialValue={512}>
            <InputNumber min={128} max={4096} step={64} style={{ width: 200 }} />
          </Form.Item>
          <Form.Item name="chunk_overlap" label="分块重叠大小" initialValue={50}>
            <InputNumber min={0} max={512} style={{ width: 200 }} />
          </Form.Item>

          <Divider />
          <Typography.Title level={5}>DeepSeek API 配置</Typography.Title>
          <Form.Item name="deepseek_model" label="对话模型" initialValue="deepseek-chat">
            <InputNumber disabled style={{ width: 200 }} />
          </Form.Item>
          <Form.Item name="max_tokens" label="最大回复 Token 数" initialValue={2048}>
            <InputNumber min={256} max={8192} step={256} style={{ width: 200 }} />
          </Form.Item>

          <Button type="primary" icon={<SaveOutlined />} onClick={handleSave}>
            保存设置
          </Button>
        </Form>
      </Card>
    </div>
  );
}
