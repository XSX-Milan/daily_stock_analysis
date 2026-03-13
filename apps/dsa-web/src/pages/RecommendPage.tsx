import type React from 'react';
import { useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { MarketRegion, RecommendationPriority } from '../types/recommendation';
import { useRecommendationStore } from '../stores/recommendationStore';

const PRIORITY_LABELS: Record<string, string> = {
  [RecommendationPriority.BUY_NOW]: '立即买入',
  [RecommendationPriority.POSITION]: '可建仓',
  [RecommendationPriority.WAIT_PULLBACK]: '等待回调',
  [RecommendationPriority.NO_ENTRY]: '暂不介入',
};

const PRIORITY_BADGE_CLASS: Record<string, string> = {
  [RecommendationPriority.BUY_NOW]: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
  [RecommendationPriority.POSITION]: 'bg-cyan/15 text-cyan border-cyan/30',
  [RecommendationPriority.WAIT_PULLBACK]: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
  [RecommendationPriority.NO_ENTRY]: 'bg-red-500/15 text-red-300 border-red-500/30',
};

const MARKET_ORDER = [MarketRegion.CN, MarketRegion.HK, MarketRegion.US];
const MARKET_LABELS: Record<string, string> = {
  [MarketRegion.CN]: 'A股',
  [MarketRegion.HK]: '港股',
  [MarketRegion.US]: '美股',
};

const formatPrice = (value?: number | null): string => {
  if (value == null) return '--';
  return value.toFixed(2);
};

const formatDateTime = (value: string): string => {
  if (!value) return '--';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString('zh-CN', { hour12: false });
};

const RecommendPage: React.FC = () => {
  const navigate = useNavigate();
  const {
    recommendations,
    summary,
    filters,
    loading,
    error,
    fetchRecommendations,
    fetchSummary,
    triggerRefresh,
    setFilter,
    clearFilters,
  } = useRecommendationStore();

  useEffect(() => {
    void Promise.all([fetchRecommendations(), fetchSummary()]);
  }, [fetchRecommendations, fetchSummary]);

  const marketOptions = useMemo(() => {
    const markets = new Set<string>(MARKET_ORDER);
    recommendations.forEach((item) => {
      const market = String(item.market ?? item.region ?? '').trim().toUpperCase();
      if (market) markets.add(market);
    });
    return Array.from(markets).sort((left, right) => {
      const leftIndex = MARKET_ORDER.indexOf(left as MarketRegion);
      const rightIndex = MARKET_ORDER.indexOf(right as MarketRegion);
      if (leftIndex !== -1 || rightIndex !== -1) {
        if (leftIndex === -1) return 1;
        if (rightIndex === -1) return -1;
        return leftIndex - rightIndex;
      }
      return left.localeCompare(right, 'zh-CN');
    });
  }, [recommendations]);

  const sectorsByMarket = useMemo(() => {
    const grouped = new Map<string, Set<string>>();
    recommendations.forEach((item) => {
      const market = String(item.market ?? item.region ?? '').trim().toUpperCase();
      const sector = item.sector?.trim();
      if (!market || !sector) return;
      const sectorSet = grouped.get(market) ?? new Set<string>();
      sectorSet.add(sector);
      grouped.set(market, sectorSet);
    });
    return grouped;
  }, [recommendations]);

  const selectedMarket = String(filters.market ?? filters.region ?? '').trim().toUpperCase();
  const selectedSector = filters.sector ?? '';
  const sectorOptions = useMemo(() => {
    if (!selectedMarket) return [];
    const sectors = sectorsByMarket.get(selectedMarket);
    if (!sectors) return [];
    return Array.from(sectors).sort((a, b) => a.localeCompare(b, 'zh-CN'));
  }, [selectedMarket, sectorsByMarket]);

  const refreshDisabled = loading || !selectedMarket || !selectedSector;
  const hasSectorOptions = sectorOptions.length > 0;
  const refreshHint = !selectedMarket
    ? '请先选择市场，再选择行业后刷新推荐。'
    : (!selectedSector
      ? (hasSectorOptions ? '请先选择行业后再刷新推荐。' : '当前市场暂无行业列表，请手动输入行业后刷新推荐。')
      : '将按已选市场和行业刷新推荐结果。');

  const buildNextFilters = (market?: string, sector?: string) => {
    const nextFilters = {
      ...filters,
      market,
      sector,
    };

    if (!nextFilters.market) {
      delete nextFilters.market;
      delete nextFilters.region;
    }
    if (!nextFilters.sector) {
      delete nextFilters.sector;
    }

    return nextFilters;
  };

  const handleMarketChange = (value: string) => {
    const market = value ? value.toUpperCase() : undefined;
    const nextFilters = buildNextFilters(market, undefined);
    void fetchRecommendations(nextFilters);
  };

  const handleSectorChange = (value: string) => {
    const sector = value || undefined;
    const nextFilters = buildNextFilters(selectedMarket || undefined, sector);
    void fetchRecommendations(nextFilters);
  };

  const handleSectorInputChange = (value: string) => {
    setFilter('sector', value.trim() || undefined);
  };

  const handleClearFilters = () => {
    clearFilters();
    void fetchRecommendations();
  };

  const handleRefresh = async () => {
    if (!selectedMarket || !selectedSector) return;
    await triggerRefresh({
      market: selectedMarket,
      sector: selectedSector,
    });
  };

  return (
    <div className="min-h-screen flex flex-col">
      <header className="flex-shrink-0 px-4 py-3 border-b border-white/5">
        <div className="max-w-6xl space-y-2">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto_auto] gap-2 sm:gap-3 items-end">
            <div className="flex flex-col gap-1">
              <label htmlFor="recommend-market" className="text-xs text-muted whitespace-nowrap">市场</label>
              <select
                id="recommend-market"
                value={selectedMarket}
                onChange={(e) => handleMarketChange(e.target.value)}
                className="input-terminal text-sm py-2.5 pr-8 w-full"
              >
                <option value="">请选择市场</option>
                {marketOptions.map((market) => (
                  <option key={market} value={market}>{MARKET_LABELS[market] ?? market}</option>
                ))}
              </select>
            </div>

            <div className="flex flex-col gap-1">
              <label htmlFor="recommend-sector" className="text-xs text-muted whitespace-nowrap">行业</label>
              {selectedMarket && !hasSectorOptions ? (
                <input
                  id="recommend-sector"
                  value={selectedSector}
                  onChange={(e) => handleSectorInputChange(e.target.value)}
                    className="input-terminal text-sm py-2.5 px-3 w-full"
                  placeholder="请输入行业名称"
                />
              ) : (
                <select
                  id="recommend-sector"
                  value={selectedSector}
                  onChange={(e) => handleSectorChange(e.target.value)}
                    className="input-terminal text-sm py-2.5 pr-8 w-full"
                  disabled={!selectedMarket}
                >
                  <option value="">{selectedMarket ? '请选择行业' : '请先选择市场'}</option>
                  {sectorOptions.map((sector) => (
                    <option key={sector} value={sector}>{sector}</option>
                  ))}
                </select>
              )}
            </div>

            <button type="button" onClick={handleClearFilters} className="btn-secondary text-sm h-10 w-full sm:w-auto">清空筛选</button>
            <button
              type="button"
              onClick={() => void handleRefresh()}
              className="btn-primary text-sm h-10 w-full sm:w-auto"
              disabled={refreshDisabled}
            >
              {loading ? '刷新中...' : '刷新推荐'}
            </button>
          </div>

          <p className={`text-xs leading-relaxed ${refreshDisabled ? 'text-amber-300' : 'text-secondary'}`}>{refreshHint}</p>
        </div>
      </header>

      <main className="flex-1 overflow-y-auto p-3 space-y-3">
        <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="glass-card p-3 border border-emerald-500/20">
            <p className="text-xs text-secondary mb-1">立即买入</p>
            <p className="text-2xl font-semibold text-emerald-300">{summary?.buyNow ?? 0}</p>
          </div>
          <div className="glass-card p-3 border border-cyan/20">
            <p className="text-xs text-secondary mb-1">可建仓</p>
            <p className="text-2xl font-semibold text-cyan">{summary?.position ?? 0}</p>
          </div>
          <div className="glass-card p-3 border border-amber-500/20">
            <p className="text-xs text-secondary mb-1">等待回调</p>
            <p className="text-2xl font-semibold text-amber-300">{summary?.waitPullback ?? 0}</p>
          </div>
          <div className="glass-card p-3 border border-red-500/20">
            <p className="text-xs text-secondary mb-1">暂不介入</p>
            <p className="text-2xl font-semibold text-red-300">{summary?.noEntry ?? 0}</p>
          </div>
        </section>

        {error ? (
          <div className="glass-card border border-danger/30 text-danger text-sm p-3">{error}</div>
        ) : null}

        {loading && recommendations.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-48">
            <div className="w-10 h-10 border-3 border-cyan/20 border-t-cyan rounded-full animate-spin" />
            <p className="mt-3 text-secondary text-sm">加载推荐中...</p>
          </div>
        ) : recommendations.length === 0 ? (
          <div className="glass-card p-6 text-center">
            <h3 className="text-base font-medium text-white mb-1">暂无推荐数据</h3>
            <p className="text-xs text-muted">请先选择市场和行业后，点击“刷新推荐”获取最新列表</p>
          </div>
        ) : (
          <div className="-mx-3 overflow-x-auto overscroll-x-contain px-3 pb-1 sm:mx-0 sm:px-0">
            <div className="rounded-xl border border-white/5">
              <table className="w-full min-w-[520px] text-xs sm:text-sm">
              <thead>
                <tr className="bg-elevated text-left">
                  <th className="px-2 sm:px-3 py-2.5 text-xs font-medium text-secondary uppercase tracking-wider whitespace-nowrap">代码</th>
                  <th className="px-2 sm:px-3 py-2.5 text-xs font-medium text-secondary uppercase tracking-wider whitespace-nowrap">名称</th>
                  <th className="hidden sm:table-cell px-2 sm:px-3 py-2.5 text-xs font-medium text-secondary uppercase tracking-wider whitespace-nowrap">行业</th>
                  <th className="px-2 sm:px-3 py-2.5 text-xs font-medium text-secondary uppercase tracking-wider whitespace-nowrap">优先级</th>
                  <th className="px-2 sm:px-3 py-2.5 text-xs font-medium text-secondary uppercase tracking-wider text-right whitespace-nowrap">综合分</th>
                  <th className="hidden md:table-cell px-2 sm:px-3 py-2.5 text-xs font-medium text-secondary uppercase tracking-wider text-right whitespace-nowrap">建议买入</th>
                  <th className="hidden md:table-cell px-2 sm:px-3 py-2.5 text-xs font-medium text-secondary uppercase tracking-wider text-right whitespace-nowrap">止损</th>
                  <th className="hidden md:table-cell px-2 sm:px-3 py-2.5 text-xs font-medium text-secondary uppercase tracking-wider text-right whitespace-nowrap">止盈</th>
                  <th className="hidden sm:table-cell px-2 sm:px-3 py-2.5 text-xs font-medium text-secondary uppercase tracking-wider whitespace-nowrap">更新时间</th>
                </tr>
              </thead>
              <tbody>
                {recommendations.map((item) => {
                  const priorityLabel = PRIORITY_LABELS[item.priority] ?? item.priority;
                  const priorityClass = PRIORITY_BADGE_CLASS[item.priority] ?? 'bg-white/5 text-secondary border-white/10';
                  return (
                    <tr
                      key={`${item.stockCode}-${item.updatedAt}`}
                      className="border-t border-white/5 hover:bg-hover active:bg-hover transition-colors cursor-pointer"
                      onClick={() => navigate(`/?stock=${encodeURIComponent(item.stockCode)}`)}
                    >
                      <td className="px-2 sm:px-3 py-2 font-mono text-cyan whitespace-nowrap">{item.stockCode}</td>
                       <td className="px-2 sm:px-3 py-2 text-white max-w-[7.5rem] sm:max-w-none truncate">{item.stockName || item.name || '--'}</td>
                       <td className="hidden sm:table-cell px-2 sm:px-3 py-2 text-secondary whitespace-nowrap">{item.sector || '--'}</td>
                      <td className="px-2 sm:px-3 py-2 whitespace-nowrap">
                         <span className={`inline-flex items-center px-2 py-0.5 rounded border text-[11px] sm:text-xs ${priorityClass}`}>
                           {priorityLabel}
                         </span>
                       </td>
                      <td className="px-2 sm:px-3 py-2 text-right font-mono text-white whitespace-nowrap">{item.compositeScore.toFixed(1)}</td>
                      <td className="hidden md:table-cell px-2 sm:px-3 py-2 text-right font-mono text-secondary whitespace-nowrap">{formatPrice(item.idealBuyPrice ?? item.suggestedBuy)}</td>
                      <td className="hidden md:table-cell px-2 sm:px-3 py-2 text-right font-mono text-secondary whitespace-nowrap">{formatPrice(item.stopLoss)}</td>
                      <td className="hidden md:table-cell px-2 sm:px-3 py-2 text-right font-mono text-secondary whitespace-nowrap">{formatPrice(item.takeProfit)}</td>
                       <td className="hidden sm:table-cell px-2 sm:px-3 py-2 text-secondary whitespace-nowrap">{formatDateTime(item.updatedAt)}</td>
                    </tr>
                  );
                })}
              </tbody>
              </table>
            </div>
          </div>
        )}
      </main>
    </div>
  );
};

export default RecommendPage;
