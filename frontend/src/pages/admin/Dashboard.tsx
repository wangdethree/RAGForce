import { useEffect, useState } from 'react';
import { Row, Col, Card, Statistic, Table, Tag } from 'antd';
import { DatabaseOutlined, FileTextOutlined, MessageOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { kbApi } from '../../services/api';

export default function Dashboard() {
  const [loading, setLoading] = useState(false);
  const [stats, setStats] = useState({ kbs: 0, docs: 0, queries: 0, avgLatency: 0 });

  useEffect(() => {
    setLoading(true);
    kbApi.list()
      .then((res) => {
        const kbs = res.data.items || [];
        const totalDocs = kbs.reduce((sum: number, kb: { document_count: number }) => sum + kb.document_count, 0);
        setStats({ kbs: kbs.length, docs: totalDocs, queries: 0, avgLatency: 0 });
      })
      .finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} lg={6}>
          <Card loading={loading}>
            <Statistic title="Knowledge Bases" value={stats.kbs} prefix={<DatabaseOutlined />} />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card loading={loading}>
            <Statistic title="Documents" value={stats.docs} prefix={<FileTextOutlined />} />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card loading={loading}>
            <Statistic title="Queries Today" value={stats.queries} prefix={<MessageOutlined />} />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card loading={loading}>
            <Statistic title="Avg Latency (ms)" value={stats.avgLatency} prefix={<ThunderboltOutlined />} precision={0} />
          </Card>
        </Col>
      </Row>

      <Card title="Recent Knowledge Bases" style={{ marginTop: 24 }}>
        <Table
          dataSource={[]}
          rowKey="id"
          columns={[
            { title: 'Name', dataIndex: 'name' },
            { title: 'Documents', dataIndex: 'document_count' },
            { title: 'Created', dataIndex: 'created_at' },
          ]}
        />
      </Card>
    </div>
  );
}
