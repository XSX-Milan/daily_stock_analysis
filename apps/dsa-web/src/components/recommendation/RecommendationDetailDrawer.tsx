import React, { useMemo, useState } from 'react';
import type { RecommendationHistoryItem } from '../../api/recommendation';
import type { AnalysisReport } from '../../types/analysis';
import { getReportText, normalizeReportLanguage } from '../../utils/reportLanguage';
import { Button, Drawer, InlineAlert } from '../common';
import { ReportMarkdown, ReportSummary } from '../report';

interface RecommendationDetailDrawerProps {
  isOpen: boolean;
  loading: boolean;
  error: string | null;
  recommendation: RecommendationHistoryItem | null;
  analysisDetail: AnalysisReport | null;
  onClose: () => void;
  onAskAi: (report: AnalysisReport) => void;
}

const formatScore = (value: unknown): string => {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    return '--';
  }
  return value.toFixed(1);
};

export const RecommendationDetailDrawer: React.FC<RecommendationDetailDrawerProps> = ({
  isOpen,
  loading,
  error,
  recommendation,
  analysisDetail,
  onClose,
  onAskAi,
}) => {
  const [markdownOpen, setMarkdownOpen] = useState(false);

  const drawerTitle = useMemo(() => {
    const stockName = analysisDetail?.meta.stockName || recommendation?.name || 'Recommendation';
    const stockCode = analysisDetail?.meta.stockCode || recommendation?.code || '';
    return stockCode ? `${stockName} (${stockCode})` : stockName;
  }, [analysisDetail?.meta.stockCode, analysisDetail?.meta.stockName, recommendation?.code, recommendation?.name]);

  const reportLanguage = normalizeReportLanguage(analysisDetail?.meta.reportLanguage);
  const reportText = getReportText(reportLanguage);
  const reportId = analysisDetail?.meta.id;

  return (
    <>
      <Drawer
        isOpen={isOpen}
        onClose={onClose}
        title={drawerTitle}
        width="max-w-4xl"
      >
        <div data-testid="recommendation-detail-drawer">
        {loading ? (
          <div className="flex min-h-[18rem] flex-col items-center justify-center">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-cyan/20 border-t-cyan" />
            <p className="mt-3 text-sm text-secondary-text">Loading recommendation detail...</p>
          </div>
        ) : null}

        {!loading && error ? (
          <InlineAlert
            variant="danger"
            title="Failed to load detail"
            message={error}
          />
        ) : null}

        {!loading && !error && recommendation ? (
          <div className="space-y-4">
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="text-xs uppercase tracking-[0.24em] text-muted-text">Recommendation</p>
                  <h3 className="mt-1 text-lg font-semibold text-white">
                    {recommendation.name || recommendation.code || 'Recommendation'}
                  </h3>
                  <p className="mt-1 text-sm text-secondary-text">
                    {(recommendation.market || recommendation.region || '--')} · {recommendation.sector || 'Uncategorized'}
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-xs uppercase tracking-[0.24em] text-muted-text">Score</p>
                  <p className="mt-1 text-2xl font-semibold text-cyan">
                    {formatScore(recommendation.compositeScore)}
                  </p>
                  <p className="mt-1 text-sm text-secondary-text">{recommendation.priority || 'NO_ENTRY'}</p>
                </div>
              </div>
              {recommendation.aiSummary ? (
                <p className="mt-3 text-sm leading-6 text-secondary-text">{recommendation.aiSummary}</p>
              ) : null}
            </div>

            {analysisDetail ? (
              <>
                <div className="flex flex-wrap items-center justify-end gap-2">
                  <Button
                    variant="home-action-ai"
                    size="sm"
                    disabled={reportId === undefined}
                    onClick={() => {
                      if (analysisDetail) {
                        onAskAi(analysisDetail);
                      }
                    }}
                  >
                    Ask AI
                  </Button>
                  <Button
                    variant="home-action-report"
                    size="sm"
                    disabled={reportId === undefined}
                    onClick={() => setMarkdownOpen(true)}
                  >
                    {reportText.fullReport}
                  </Button>
                </div>
                <ReportSummary data={analysisDetail} isHistory />
              </>
            ) : (
              <InlineAlert
                variant="warning"
                title="Analysis detail unavailable"
                message="This recommendation record does not currently have a linked analysis report. Legacy fallback may still be rebuilding."
              />
            )}
          </div>
        ) : null}
        </div>
      </Drawer>

      {markdownOpen && reportId !== undefined ? (
        <ReportMarkdown
          recordId={reportId}
          stockName={analysisDetail?.meta.stockName || recommendation?.name || ''}
          stockCode={analysisDetail?.meta.stockCode || recommendation?.code || ''}
          reportLanguage={reportLanguage}
          onClose={() => setMarkdownOpen(false)}
        />
      ) : null}
    </>
  );
};
