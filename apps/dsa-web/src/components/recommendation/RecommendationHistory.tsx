import React, { useState } from 'react';
import type { RecommendationHistoryItem } from '../../api/recommendation';
import { RecommendationPriority } from '../../types/recommendation';
import { Badge } from '../common/Badge';
import { Button } from '../common/Button';
import { ConfirmDialog } from '../common/ConfirmDialog';
import { Pagination } from '../common/Pagination';
import { formatDateTime } from '../../utils/format';

interface RecommendationHistoryProps {
  items: RecommendationHistoryItem[];
  loading: boolean;
  total: number;
  limit: number;
  offset: number;
  market?: string;
  onMarketChange: (market?: string) => void;
  onPageChange: (offset: number) => void;
  onDelete: (code: string) => Promise<void>;
}

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

const MARKET_TABS = [
  { label: '全部', value: undefined },
  { label: 'A股', value: 'CN' },
  { label: '港股', value: 'HK' },
  { label: '美股', value: 'US' },
];

export const RecommendationHistory: React.FC<RecommendationHistoryProps> = ({
  items,
  loading,
  total,
  limit,
  offset,
  market,
  onMarketChange,
  onPageChange,
  onDelete,
}) => {
  const [deleteCode, setDeleteCode] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  const currentPage = Math.floor(offset / limit) + 1;
  const totalPages = Math.max(1, Math.ceil(total / limit));

  const handleDeleteConfirm = async () => {
    if (!deleteCode) return;
    setIsDeleting(true);
    try {
      await onDelete(deleteCode);
    } finally {
      setIsDeleting(false);
      setDeleteCode(null);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap gap-2">
        {MARKET_TABS.map((tab) => {
          const isActive = market === tab.value;
          return (
            <button
              key={tab.label}
              type="button"
              onClick={() => onMarketChange(tab.value)}
              className={`inline-flex items-center px-3 py-1.5 rounded border text-xs transition-colors ${
                isActive
                  ? 'bg-cyan/15 text-cyan border-cyan/50 shadow-[0_0_10px_rgba(0,212,255,0.2)]'
                  : 'bg-white/5 text-secondary border-white/10 hover:bg-white/10 hover:text-white'
              }`}
            >
              {tab.label}
            </button>
          );
        })}
      </div>

      <div className="glass-card flex-1 min-h-[400px] flex flex-col overflow-hidden">
        {loading && items.length === 0 ? (
          <div className="flex-1 flex flex-col items-center justify-center p-12 text-center">
            <div className="w-8 h-8 border-2 border-cyan/20 border-t-cyan rounded-full animate-spin" />
            <p className="mt-4 text-secondary text-sm">加载推荐历史中...</p>
          </div>
        ) : items.length === 0 ? (
          <div className="flex-1 flex flex-col items-center justify-center p-12 text-center">
            <div className="mx-auto w-12 h-12 rounded-full bg-white/5 flex items-center justify-center text-muted-text/30 mb-4">
              <svg aria-hidden="true" className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <p className="text-secondary text-sm">暂无推荐历史记录</p>
            <p className="text-xs text-muted-text mt-1">切换市场或等待新的推荐产生。</p>
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto p-4 space-y-3">
            {items.map((item) => {
              const code = item.code || '--';
              const name = item.name || '--';
              const priorityLabel = PRIORITY_LABELS[item.priority || ''] || item.priority || '未知';
              const priorityVariant = PRIORITY_BADGE_VARIANT[item.priority || ''] || 'default';
              const score = item.compositeScore != null ? item.compositeScore.toFixed(0) : '--';

              return (
                <div 
                  key={code} 
                  className="bg-white/5 border border-transparent hover:bg-white/10 hover:border-white/10 rounded-xl p-4 transition-all duration-200"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-3 mb-1">
                        <span className="text-base font-semibold text-white tracking-tight">
                          {name}
                        </span>
                        <span className="text-xs text-secondary-text font-mono">
                          {code}
                        </span>
                        <Badge variant={priorityVariant} size="sm">
                          {priorityLabel}
                        </Badge>
                        <span className="text-xs font-semibold text-cyan">
                          {score}分
                        </span>
                      </div>
                      
                      <div className="flex items-center gap-2 text-[11px] text-muted-text mb-3">
                        {item.sector && (
                          <>
                            <span>{item.sector}</span>
                            <span className="w-1 h-1 rounded-full bg-white/10" />
                          </>
                        )}
                        <span>{item.recommendationDate ? formatDateTime(item.recommendationDate) : '暂无日期'}</span>
                      </div>

                      {item.aiSummary && (
                        <p className="text-xs text-secondary-text leading-relaxed line-clamp-2" title={item.aiSummary}>
                          {item.aiSummary}
                        </p>
                      )}
                    </div>

                    <div className="shrink-0 flex items-center pt-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setDeleteCode(code)}
                        className="text-muted-text hover:text-danger hover:bg-danger/10 px-2"
                        title="删除记录"
                      >
                        <svg aria-hidden="true" className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                        </svg>
                      </Button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* 分页控制 */}
        {totalPages > 1 && (
          <div className="border-t border-white/5 p-4 flex justify-center bg-black/20">
            <Pagination
              currentPage={currentPage}
              totalPages={totalPages}
              onPageChange={(page) => onPageChange((page - 1) * limit)}
            />
          </div>
        )}
      </div>

      {/* 删除确认弹窗 */}
      <ConfirmDialog
        isOpen={!!deleteCode}
        title="确认删除"
        message={`确定要删除 ${deleteCode} 的推荐记录吗？此操作不可恢复。`}
        confirmText={isDeleting ? '删除中...' : '确认删除'}
        cancelText="取消"
        isDanger={true}
        onConfirm={handleDeleteConfirm}
        onCancel={() => {
          if (!isDeleting) setDeleteCode(null);
        }}
      />
    </div>
  );
};
