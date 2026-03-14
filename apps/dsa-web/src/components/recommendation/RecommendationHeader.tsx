import React from 'react';
import { Button } from '../common/Button';

interface RecommendationHeaderProps {
  onRefresh: () => void;
  loading: boolean;
  refreshDisabled: boolean;
}

export const RecommendationHeader: React.FC<RecommendationHeaderProps> = ({
  onRefresh,
  loading,
  refreshDisabled,
}) => {
  return (
    <div
      data-testid="recommendation-header"
      className="flex flex-col sm:flex-row sm:items-center justify-between gap-4"
    >
      <div className="flex flex-col gap-1">
        <span className="text-[11px] uppercase tracking-[0.2em] font-semibold text-purple-400">
          RECOMMENDATION RADAR
        </span>
        <h1 className="text-2xl font-bold text-white">
          Stock Recommendation Hub
        </h1>
        <p className="text-sm text-slate-400">
          Ranked ideas with sector scanning and score-driven priority.
        </p>
      </div>

      <Button
        variant="primary"
        onClick={onRefresh}
        disabled={refreshDisabled}
        isLoading={loading}
        data-testid="manual-refresh-button"
      >
        Manual Refresh
      </Button>
    </div>
  );
};
