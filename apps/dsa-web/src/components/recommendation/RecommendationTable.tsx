import React, { useState, useMemo } from 'react';
import { Sparkles } from 'lucide-react';
import type { RecommendationItem } from '../../types/recommendation';
import { RecommendationPriority, MarketRegion } from '../../types/recommendation';
import { ScoreBar } from './ScoreBar';
import { Badge } from '../common/Badge';

interface RecommendationTableProps {
  recommendations: RecommendationItem[];
  onRowClick: (stockCode: string) => void;
  loading: boolean;
}

type SortColumn = 'compositeScore' | 'priority' | 'price';
type SortDirection = 'asc' | 'desc';

const PRIORITY_LABELS: Record<string, string> = {
  [RecommendationPriority.BUY_NOW]: '立即买入',
  [RecommendationPriority.POSITION]: '可建仓',
  [RecommendationPriority.WAIT_PULLBACK]: '等待回调',
  [RecommendationPriority.NO_ENTRY]: '暂不介入',
};

const PRIORITY_BADGE_VARIANT: Record<string, 'success' | 'info' | 'warning' | 'danger' | 'default'> = {
  [RecommendationPriority.BUY_NOW]: 'success',
  [RecommendationPriority.POSITION]: 'info',
  [RecommendationPriority.WAIT_PULLBACK]: 'warning',
  [RecommendationPriority.NO_ENTRY]: 'danger',
};

const PRIORITY_WEIGHT: Record<string, number> = {
  [RecommendationPriority.BUY_NOW]: 4,
  [RecommendationPriority.POSITION]: 3,
  [RecommendationPriority.WAIT_PULLBACK]: 2,
  [RecommendationPriority.NO_ENTRY]: 1,
};

const MARKET_LABELS: Record<string, string> = {
  [MarketRegion.CN]: 'A股',
  [MarketRegion.HK]: '港股',
  [MarketRegion.US]: '美股',
};

const formatPrice = (value?: number | null): string => {
  if (value == null) return '--';
  return value.toFixed(2);
};

export const RecommendationTable: React.FC<RecommendationTableProps> = ({ 
  recommendations, 
  onRowClick,
  loading
}) => {
  const [sortState, setSortState] = useState<{ column: SortColumn; direction: SortDirection }>({
    column: 'compositeScore',
    direction: 'desc'
  });

  const handleSort = (column: SortColumn) => {
    if (sortState.column === column) {
      setSortState({
        column,
        direction: sortState.direction === 'asc' ? 'desc' : 'asc'
      });
    } else {
      setSortState({
        column,
        direction: 'desc'
      });
    }
  };

  const sortedData = useMemo(() => {
    return [...recommendations].sort((a, b) => {
      let comparison = 0;
      if (sortState.column === 'compositeScore') {
        comparison = a.compositeScore - b.compositeScore;
      } else if (sortState.column === 'priority') {
        const weightA = PRIORITY_WEIGHT[a.priority] ?? 0;
        const weightB = PRIORITY_WEIGHT[b.priority] ?? 0;
        comparison = weightA - weightB;
      } else if (sortState.column === 'price') {
        const priceA = a.idealBuyPrice ?? a.suggestedBuy ?? 0;
        const priceB = b.idealBuyPrice ?? b.suggestedBuy ?? 0;
        comparison = priceA - priceB;
      }

      return sortState.direction === 'asc' ? comparison : -comparison;
    });
  }, [recommendations, sortState]);

  if (loading && recommendations.length === 0) {
    return (
      <div className="glass-card p-6 text-center" data-testid="recommendation-table">
        <div className="flex flex-col items-center justify-center h-32">
          <div className="w-8 h-8 border-2 border-cyan/20 border-t-cyan rounded-full animate-spin" />
          <p className="mt-3 text-secondary text-sm">加载推荐中...</p>
        </div>
      </div>
    );
  }

  if (!recommendations || recommendations.length === 0) {
    return (
      <div className="glass-card p-6 text-center" data-testid="recommendation-table">
        <h3 className="text-base font-medium text-white mb-1">暂无推荐数据</h3>
        <p className="text-xs text-muted">当前没有符合条件的推荐股票</p>
      </div>
    );
  }

  const renderSortIndicator = (column: SortColumn) => {
    if (sortState.column !== column) return '↕';
    return sortState.direction === 'asc' ? '▲' : '▼';
  };

  return (
    <div className="overflow-x-auto overscroll-x-contain" data-testid="recommendation-table">
      <div className="rounded-xl border border-white/5">
        <table className="w-full min-w-[800px] text-xs sm:text-sm">
          <thead>
            <tr className="bg-elevated text-left">
              <th className="px-3 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider whitespace-nowrap">分类</th>
              <th className="px-3 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider whitespace-nowrap">代码</th>
              <th className="px-3 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider whitespace-nowrap">名称</th>
              <th 
                className="px-3 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider whitespace-nowrap cursor-pointer hover:text-white transition-colors"
                onClick={() => handleSort('price')}
                data-testid="sort-price"
              >
                现价 {renderSortIndicator('price')}
              </th>
              <th 
                className="px-3 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider whitespace-nowrap cursor-pointer hover:text-white transition-colors"
                onClick={() => handleSort('compositeScore')}
                data-testid="sort-compositeScore"
              >
                动态 {renderSortIndicator('compositeScore')}
              </th>
              <th className="px-3 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider whitespace-nowrap w-48">评分结构</th>
              <th className="px-3 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider text-right whitespace-nowrap">建议入场价</th>
              <th className="px-3 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider text-right whitespace-nowrap">止盈</th>
              <th className="px-3 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider text-right whitespace-nowrap">止损</th>
              <th 
                className="px-3 py-3 text-xs font-medium text-slate-500 uppercase tracking-wider whitespace-nowrap cursor-pointer hover:text-white transition-colors"
                onClick={() => handleSort('priority')}
                data-testid="sort-priority"
              >
                优先级 {renderSortIndicator('priority')}
              </th>
            </tr>
          </thead>
          <tbody>
            {sortedData.map((item) => {
              const marketLabel = MARKET_LABELS[item.market ?? item.region ?? ''] ?? item.market ?? item.region ?? '--';
              const priorityLabel = PRIORITY_LABELS[item.priority] ?? item.priority;
              const priorityVariant = PRIORITY_BADGE_VARIANT[item.priority] ?? 'default';
              const price = item.idealBuyPrice ?? item.suggestedBuy;

              const showSummaryRow = item.aiRefined || item.aiSummary;

              return (
                <React.Fragment key={`${item.stockCode}-${item.updatedAt}`}>
                  <tr
                    className={`bg-card hover:bg-elevated transition-colors cursor-pointer ${
                      showSummaryRow ? '' : 'border-b border-white/5'
                    }`}
                    onClick={() => onRowClick?.(item.stockCode)}
                    data-testid={`table-row-${item.stockCode}`}
                  >
                    <td className="px-3 py-2 text-secondary whitespace-nowrap">
                      {item.sector ? (
                        <div className="flex items-center gap-1.5">
                          <svg className="w-3 h-3 text-cyan-400/70" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 7h.01M7 3h5c.512 0 1.024.195 1.414.586l7 7a2 2 0 010 2.828l-7 7a2 2 0 01-2.828 0l-7-7A1.994 1.994 0 013 12V7a4 4 0 014-4z" />
                          </svg>
                          <span>{item.sector}</span>
                        </div>
                      ) : (
                        <span className="text-white/30">-</span>
                      )}
                    </td>
                    <td className="px-3 py-2 font-mono text-cyan-400 whitespace-nowrap">{item.stockCode}</td>
                    <td className="px-3 py-2 max-w-[10rem] truncate" title={item.stockName || item.name}>
                      <div className="text-white">{item.stockName || item.name || '--'}</div>
                      <div className="text-[10px] text-muted mt-0.5">{marketLabel}</div>
                    </td>
                    <td className="px-3 py-2 font-mono text-white whitespace-nowrap">{formatPrice(price)}</td>
                    <td className="px-3 py-2 font-mono text-white whitespace-nowrap">{item.compositeScore.toFixed(1)}</td>
                    <td className="px-3 py-2 w-48">
                      <ScoreBar scores={item.scores} compositeScore={item.compositeScore} />
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-secondary whitespace-nowrap">{formatPrice(item.suggestedBuy)}</td>
                    <td className="px-3 py-2 text-right font-mono text-secondary whitespace-nowrap">{formatPrice(item.takeProfit)}</td>
                    <td className="px-3 py-2 text-right font-mono text-secondary whitespace-nowrap">{formatPrice(item.stopLoss)}</td>
                    <td className="px-3 py-2 whitespace-nowrap">
                      <Badge variant={priorityVariant}>{priorityLabel}</Badge>
                    </td>
                  </tr>
                  {showSummaryRow && (
                    <tr
                      className="border-b border-white/5 bg-card hover:bg-elevated transition-colors cursor-pointer"
                      onClick={() => onRowClick?.(item.stockCode)}
                    >
                      <td colSpan={10} className="px-3 pb-3 pt-0 text-xs whitespace-normal">
                        <div className="flex items-start gap-1.5 text-muted">
                          <Sparkles className="w-3.5 h-3.5 text-cyan-400/70 shrink-0 mt-0.5" />
                          <span className="line-clamp-2" title={item.aiSummary || ''}>
                            {item.aiSummary ? (
                              <span className="text-secondary/90">{item.aiSummary}</span>
                            ) : (
                              <span className="text-white/30 italic">AI 已精炼评分，暂无详细摘要</span>
                            )}
                          </span>
                        </div>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};
