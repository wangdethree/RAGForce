import { useEffect, useState } from 'react';
import { Row, Col, Card, Statistic, Table, message } from 'antd';
import { DatabaseOutlined, FileTextOutlined, AuditOutlined, SplitCellsOutlined } from '@ant-design/icons';
import { dashboardApi } from '../../services/api';

interface Stats {
  kb_count: number;
  document_count: number;
  chunk_count: number;
  audit_log_count: number;
}

interface RecentKB {
  id: string;
  name: string;
  document_count: number;
  created_at: string;
}

export default function Dashboard() {
  const [loading, setLoading] = useState(false);
  const [stats, setStats] = useState<Stats>({ kb_count: 0, document_count: 0, chunk_count: 0, audit_log_count: 0 });
  const [recentKBs, setRecentKBs] = useState<RecentKB[]>([]);

  useEffect(() => {
    setLoading(true);
    Promise.all([dashboardApi.stats(), dashboardApi.recentKBs()])
      .then(([statsRes, kbRes]) => {
        setStats(statsRes.data);
        setRecentKBs(kbRes.data || []);
      })
      .catch(() => message.error('获取仪表盘数据失败'))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} lg={6}>
          <Card loading={loading}>
            <Statistic title="知识库" value={stats.kb_count} prefix={<DatabaseOutlined />} />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card loading={loading}>
            <Statistic title="文档" value={stats.document_count} prefix={<FileTextOutlined />} />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card loading={loading}>
            <Statistic title="分块" value={stats.chunk_count} prefix={<SplitCellsOutlined />} />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card loading={loading}>
            <Statistic title="审计日志" value={stats.audit_log_count} prefix={<AuditOutlined />} />
          </Card>
        </Col>
      </Row>

      <Card title="最近创建的知识库" style={{ marginTop: 24 }}>
        <Table
          dataSource={recentKBs}
          rowKey="id"
          loading={loading}
          columns={[
            { title: '名称', dataIndex: 'name' },
            { title: '文档数', dataIndex: 'document_count', width: 100 },
            {
              title: '创建时间',
              dataIndex: 'created_at',
              render: (v: string) => v ? new Date(v).toLocaleString() : '-',
            },
          ]}
        />
      </Card>
    </div>
  );
}
