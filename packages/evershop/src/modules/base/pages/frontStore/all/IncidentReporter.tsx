import IncidentReporter from '@components/common/IncidentReporter.js';
import React from 'react';

interface IncidentReporterBlockProps {
  reportIncidentApi?: string;
  orchestratorMessageApi?: string;
}

export default function IncidentReporterBlock({
  reportIncidentApi,
  orchestratorMessageApi
}: IncidentReporterBlockProps) {
  const resolvedReportIncidentApi = reportIncidentApi || '/api/incidents';
  const resolvedOrchestratorApi =
    orchestratorMessageApi || '/api/incidents/orchestrator/message';

  return (
    <IncidentReporter
      apiUrl={resolvedReportIncidentApi}
      orchestratorApiUrl={resolvedOrchestratorApi}
      source="frontStore"
    />
  );
}

export const layout = {
  areaId: 'body',
  sortOrder: 95
};
