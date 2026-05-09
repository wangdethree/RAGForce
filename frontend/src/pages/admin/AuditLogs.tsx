import { useEffect, useState } from 'react';
import { Table, Select, Card, Tag, message } from 'antd';
import { auditApi } from '../../services/api';

const actionColors: Record<string, string> = {
  GET: 'green',
  POST: 'blue',
  PATCH: 'orange',
  DELETE: 'red',
};

export default function AuditLogs() {
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(false);
  const [actionFilter, setActionFilter] = useState<string | undefined>();

  const fetchLogs = async () => {
    setLoading(true);
    try {
      const res = await auditApi.list({ action: actionFilter, limit: 100 });
      setLogs(res.data.items || []);
    } catch {
      message.error('获取审计日志失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchLogs(); }, [actionFilter]);

  return (
    <Card
      title="审计日志"
      extra={
        <Select
          placeholder="按操作类型筛选"
          style={{ width: 150 }}
          allowClear
          value={actionFilter}
          onChange={setActionFilter}
          options={['GET', 'POST', 'PATCH', 'DELETE'].map((a) => ({ value: a, label: a }))}
        />
      }
    >
      <Table
        dataSource={logs}
        rowKey="id"
        loading={loading}
        columns={[
          { title: '时间', dataIndex: 'created_at', render: (v: string) => new Date(v).toLocaleString() },
          {
            title: '操作', dataIndex: 'action', width: 100,
            render: (v: string) => <Tag color={actionColors[v] || 'default'}>{v}</Tag>,
          },
          { title: '资源类型', dataIndex: 'resource_type', width: 120 },
          { title: '资源ID', dataIndex: 'resource_id', ellipsis: true, width: 200 },
          { title: 'IP 地址', dataIndex: 'ip_address', width: 140 },
          { title: '耗时(ms)', dataIndex: 'duration_ms', width: 100 },
          {
            title: '详情', dataIndex: 'detail',
            render: (v: object) => <code style={{ fontSize: 12 }}>{JSON.stringify(v)}</code>,
          },
        ]}
      />
    </Card>
  );
}
