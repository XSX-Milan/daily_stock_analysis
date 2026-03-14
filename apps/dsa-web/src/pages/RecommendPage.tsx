import type React from 'react';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Select } from '../components/common/Select';
import {
  RecommendationHeader,
  SummaryCards,
  SectorFilters,
  RecommendationTable,
} from '../components/recommendation';
import { useRecommendationStore } from '../stores/recommendationStore';
import type { RecommendationFilters } from '../types/recommendation';
import { MarketRegion, RecommendationPriority } from '../types/recommendation';

const PRIORITY_LABELS: Record<string, string> = {
  [RecommendationPriority.BUY_NOW]: '立即买入',
  [RecommendationPriority.POSITION]: '可建仓',
  [RecommendationPriority.WAIT_PULLBACK]: '等待回调',
  [RecommendationPriority.NO_ENTRY]: '暂不介入',
};

const PRIORITY_BADGE_CLASS: Record<string, string> = {
  [RecommendationPriority.BUY_NOW]: 'success',
  [RecommendationPriority.POSITION]: 'info',
  [RecommendationPriority.WAIT_PULLBACK]: 'warning',
  [RecommendationPriority.NO_ENTRY]: 'danger',
};

const MARKET_ORDER = [MarketRegion.CN, MarketRegion.HK, MarketRegion.US];
const MARKET_LABELS: Record<string, string> = {
  [MarketRegion.CN]: 'A股',
  [MarketRegion.HK]: '港股',
  [MarketRegion.US]: '美股',
};

const normalizeMarket = (value?: string): string => String(value ?? '').trim().toUpperCase();

const RecommendPage: React.FC = () => {
  const navigate = useNavigate();
  const {
    recommendations,
    summary,
    weights,
    filters,
    loading,
    error,
    fetchRecommendations,
    fetchSummary,
    fetchWeights,
    triggerRefresh,
    setFilter,
  } = useRecommendationStore();
  const [selectedSector, setSelectedSector] = useState<string | null>(null);

  useEffect(() => {
    void Promise.all([fetchRecommendations(), fetchSummary(), fetchWeights()]);
  }, [fetchRecommendations, fetchSummary, fetchWeights]);

  const selectedMarket = normalizeMarket(filters.market ?? filters.region);
  const selectedPriority = String(filters.priority ?? '');

  const marketOptions = useMemo(
    () => MARKET_ORDER.map((market) => ({ value: market, label: MARKET_LABELS[market] ?? market })),
    [],
  );

  const priorityOptions = useMemo(
    () => [
      {
        value: RecommendationPriority.BUY_NOW,
        label: PRIORITY_LABELS[RecommendationPriority.BUY_NOW],
        badgeClass: PRIORITY_BADGE_CLASS[RecommendationPriority.BUY_NOW],
      },
      {
        value: RecommendationPriority.POSITION,
        label: PRIORITY_LABELS[RecommendationPriority.POSITION],
        badgeClass: PRIORITY_BADGE_CLASS[RecommendationPriority.POSITION],
      },
      {
        value: RecommendationPriority.WAIT_PULLBACK,
        label: PRIORITY_LABELS[RecommendationPriority.WAIT_PULLBACK],
        badgeClass: PRIORITY_BADGE_CLASS[RecommendationPriority.WAIT_PULLBACK],
      },
      {
        value: RecommendationPriority.NO_ENTRY,
        label: PRIORITY_LABELS[RecommendationPriority.NO_ENTRY],
        badgeClass: PRIORITY_BADGE_CLASS[RecommendationPriority.NO_ENTRY],
      },
    ],
    [],
  );

  const recommendationPool = useMemo(
    () => recommendations.filter((item) => (!selectedMarket || normalizeMarket(item.market ?? item.region) === selectedMarket)),
    [recommendations, selectedMarket],
  );

  const availableSectors = useMemo(() => {
    const sectors = new Set<string>();
    recommendationPool.forEach((item) => {
      const sector = item.sector?.trim();
      if (sector) sectors.add(sector);
    });
    return sectors;
  }, [recommendationPool]);

  const activeSector = selectedSector && availableSectors.has(selectedSector) ? selectedSector : null;

  const filteredRecommendations = useMemo(
    () => recommendationPool.filter((item) => !activeSector || item.sector?.trim() === activeSector),
    [recommendationPool, activeSector],
  );

  const refreshDisabled = loading || !selectedMarket || !activeSector;

  const buildNextFilters = (market?: string, priority?: string): RecommendationFilters => {
    const nextFilters: RecommendationFilters = {
      ...filters,
      market,
      priority,
    };

    if (!nextFilters.market) {
      delete nextFilters.market;
      delete nextFilters.region;
    }
    if (!nextFilters.priority) {
      delete nextFilters.priority;
    }
    delete nextFilters.sector;

    return nextFilters;
  };

  const handleMarketChange = (value: string) => {
    const market = normalizeMarket(value) || undefined;
    setSelectedSector(null);
    setFilter('market', market);
    setFilter('region', undefined);
    const nextFilters = buildNextFilters(market, selectedPriority || undefined);
    void fetchRecommendations(nextFilters);
  };

  const handlePriorityChange = (value: string) => {
    const priority = value || undefined;
    setFilter('priority', priority);
    const nextFilters = buildNextFilters(selectedMarket || undefined, priority);
    void fetchRecommendations(nextFilters);
  };

  const handleSectorChange = (sector: string | null) => {
    setSelectedSector(sector);
  };

  const handleRefresh = async () => {
    if (!selectedMarket || !activeSector) return;
    await triggerRefresh({
      market: selectedMarket,
      sector: activeSector,
    });
  };

  return (
    <div className="min-h-screen flex flex-col" data-testid="recommend-page">
      <main className="flex-1 overflow-y-auto p-3 space-y-4">
        <section className="glass-card p-4 border border-white/10">
          <RecommendationHeader
            loading={loading}
            refreshDisabled={refreshDisabled}
            onRefresh={() => {
              void handleRefresh();
            }}
          />
        </section>

        <SummaryCards summary={summary} recommendations={filteredRecommendations} loading={loading} />

        <section className="glass-card p-4 border border-white/10" data-testid="recommendation-filter-row">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 items-end">
            <div data-testid="market-filter-control" className="space-y-1">
              <span className="text-xs text-muted">市场过滤</span>
              <Select
                value={selectedMarket}
                onChange={handleMarketChange}
                options={marketOptions}
                placeholder="全部市场"
              />
            </div>

            <div data-testid="priority-filter-control" className="space-y-1">
              <span className="text-xs text-muted">优先级过滤</span>
              <Select
                value={selectedPriority}
                onChange={handlePriorityChange}
                options={priorityOptions}
                placeholder="全部优先级"
              />
            </div>
          </div>
        </section>

        <SectorFilters
          recommendations={recommendationPool}
          selectedSector={activeSector}
          onSectorChange={handleSectorChange}
        />

        {error ? (
          <div className="glass-card border border-danger/30 text-danger text-sm p-3">{error}</div>
        ) : null}

        <RecommendationTable
          recommendations={filteredRecommendations}
          weights={weights}
          loading={loading}
          onRowClick={(stockCode) => {
            navigate(`/?stock=${encodeURIComponent(stockCode)}`);
          }}
        />
      </main>
    </div>
  );
};

export default RecommendPage;
