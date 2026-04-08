import IncidentReporter from '@components/common/IncidentReporter.js';
import React from 'react';

interface IncidentReporterBlockProps {
  reportIncidentApi: string;
}

export default function IncidentReporterBlock({
  reportIncidentApi
}: IncidentReporterBlockProps) {
  return <IncidentReporter apiUrl={reportIncidentApi} source="frontStore" />;
}

export const layout = {
  areaId: 'body',
  sortOrder: 95
};

export const query = `
  query Query {
    reportIncidentApi: url(routeId: "reportIncident")
  }
`;
