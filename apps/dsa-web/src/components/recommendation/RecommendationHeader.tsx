import React from 'react';
import { Button } from '../common/Button';

interface RecommendationHeaderProps {
  onRefresh: () => void;
  loading: boolean;
  refreshDisabled: boolean;
  mode?: 'smart' | 'manual';
}

export const RecommendationHeader: React.FC<RecommendationHeaderProps> = ({
  onRefresh,
  loading,
  refreshDisabled,
  mode = 'manual',
}) => {
  return (
    <div
      data-testid="recommendation-header"
      className="flex flex-col sm:flex-row sm:items-center justify-between gap-4"
    >
      <div className="flex flex-col gap-1">
        <span className="text-[11px] uppercase tracking-[0.2em] font-semibold text-purple-400">
          推荐雷达
        </span>
        <h1 className="text-2xl font-bold text-white">
          股票推荐中心
        </h1>
        <p className="text-sm text-slate-400">
          基于板块扫描与评分驱动的优先级排序推荐。
        </p>
      </div>

      <Button
        variant="primary"
        onClick={onRefresh}
        disabled={refreshDisabled}
        isLoading={loading}
        data-testid="manual-refresh-button"
      >
        {mode === 'smart' ? '智能推荐' : '推荐'}
      </Button>
    </div>
  );
};
