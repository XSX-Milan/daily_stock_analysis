import React, { useMemo } from 'react';
import { Card } from '../common/Card';
import { Badge } from '../common/Badge';
import { ScoreGauge } from '../common/ScoreGauge';
import type { RecommendationItem, PrioritySummary } from '../../types/recommendation';

interface SummaryCardsProps {
  summary: PrioritySummary | null;
  recommendations: RecommendationItem[];
  loading?: boolean;
}

export const SummaryCards: React.FC<SummaryCardsProps> = ({ summary, recommendations, loading }) => {
  const avgScore = useMemo(() => {
    if (!recommendations || recommendations.length === 0) return 0;
    const totalScore = recommendations.reduce((sum, item) => sum + (item.compositeScore || 0), 0);
    return totalScore / recommendations.length;
  }, [recommendations]);

  const total = summary ? (summary.buyNow + summary.position + summary.waitPullback + summary.noEntry) : 0;

  const getPercentage = (count: number | undefined) => {
    if (!count || total === 0) return '0%';
    return `${Math.round((count / total) * 100)}%`;
  };

  const buyNowCount = summary?.buyNow || 0;
  const positionCount = summary?.position || 0;
  const waitPullbackCount = summary?.waitPullback || 0;
  const noEntryCount = summary?.noEntry || 0;

  return (
    <div data-testid="summary-cards" className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
      <div data-testid="summary-card-buy-now" className="h-full">
        <Card className="flex flex-col justify-between h-full">
          <div className="flex justify-between items-start mb-2">
            <span className="text-xs font-bold tracking-wider text-gray-400 uppercase">立即可买</span>
            <Badge variant="success" glow>{loading ? '-' : getPercentage(buyNowCount)}</Badge>
          </div>
          <div className="mt-2">
            <div className="text-3xl font-bold text-white">{loading ? '-' : buyNowCount}</div>
          </div>
        </Card>
      </div>

      <div data-testid="summary-card-position" className="h-full">
        <Card className="flex flex-col justify-between h-full">
          <div className="flex justify-between items-start mb-2">
            <span className="text-xs font-bold tracking-wider text-gray-400 uppercase">可建仓</span>
            <Badge variant="info" glow>{loading ? '-' : getPercentage(positionCount)}</Badge>
          </div>
          <div className="mt-2">
            <div className="text-3xl font-bold text-white">{loading ? '-' : positionCount}</div>
          </div>
        </Card>
      </div>

      <div data-testid="summary-card-wait-pullback" className="h-full">
        <Card className="flex flex-col justify-between h-full">
          <div className="flex justify-between items-start mb-2">
            <span className="text-xs font-bold tracking-wider text-gray-400 uppercase">等待回调</span>
            <Badge variant="warning" glow>{loading ? '-' : getPercentage(waitPullbackCount)}</Badge>
          </div>
          <div className="mt-2">
            <div className="text-3xl font-bold text-white">{loading ? '-' : waitPullbackCount}</div>
          </div>
        </Card>
      </div>

      <div data-testid="summary-card-no-entry" className="h-full">
        <Card className="flex flex-col justify-between h-full">
          <div className="flex justify-between items-start mb-2">
            <span className="text-xs font-bold tracking-wider text-gray-400 uppercase">暂不入场</span>
            <Badge variant="danger" glow>{loading ? '-' : getPercentage(noEntryCount)}</Badge>
          </div>
          <div className="mt-2">
            <div className="text-3xl font-bold text-white">{loading ? '-' : noEntryCount}</div>
          </div>
        </Card>
      </div>

      <div data-testid="summary-card-dynamic-score" className="h-full">
        <Card className="flex flex-col justify-between h-full">
          <span className="text-xs font-bold tracking-wider text-gray-400 uppercase mb-2">动态评分</span>
          <div className="flex items-center justify-center flex-1 gap-4">
            <ScoreGauge score={avgScore} size="sm" showLabel={false} />
            <div className="text-3xl font-bold text-white">
              {loading ? '-' : avgScore.toFixed(1)}
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
};
