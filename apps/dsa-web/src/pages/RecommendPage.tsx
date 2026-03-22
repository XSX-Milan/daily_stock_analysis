import type React from 'react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { RecommendationHistoryItem } from '../api/recommendation';
import { Select } from '../components/common/Select';
import {
  RecommendationDetailDrawer,
  RecommendationHeader,
  SummaryCards,
  SectorFilters,
  RecommendationTable,
} from '../components/recommendation';
import { RecommendationHistory } from '../components/recommendation/RecommendationHistory';
import { useRecommendationStore } from '../stores/recommendationStore';
import type { RecommendationItem, RecommendationListFilters } from '../types/recommendation';
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

const toNonEmptySectorValue = (value: unknown): string | null => {
  if (typeof value !== 'string') {
    return null;
  }
  const normalized = value.trim();
  return normalized.length > 0 ? normalized : null;
};

const normalizeSectors = (sectors: unknown, legacySector?: unknown): string[] => {
  const normalized: string[] = [];
  const appendSector = (value: unknown) => {
    const resolved = toNonEmptySectorValue(value);
    if (resolved && !normalized.includes(resolved)) {
      normalized.push(resolved);
    }
  };

  appendSector(legacySector);
  if (Array.isArray(sectors)) {
    sectors.forEach((sector) => {
      appendSector(sector);
    });
  }

  return normalized;
};

const appendSectorMatchTokens = (tokenSet: Set<string>, value: unknown) => {
  const resolved = toNonEmptySectorValue(value);
  if (!resolved) {
    return;
  }

  const normalized = resolved.toLowerCase();
  tokenSet.add(normalized);

  const compact = normalized.replace(/\s+/g, '');
  if (compact.length > 0) {
    tokenSet.add(compact);
  }
};

const buildRecommendationSectorTokens = (item: RecommendationItem): Set<string> => {
  const tokenSet = new Set<string>();

  normalizeSectors(item.sectors, item.sector).forEach((sector) => {
    appendSectorMatchTokens(tokenSet, sector);
  });
  appendSectorMatchTokens(tokenSet, item.sectorCanonicalKey);
  appendSectorMatchTokens(tokenSet, item.sectorDisplayLabel);
  (item.sectorAliases ?? []).forEach((alias) => {
    appendSectorMatchTokens(tokenSet, alias);
  });

  return tokenSet;
};

const RecommendPage: React.FC = () => {
  const navigate = useNavigate();
  const {
    recommendations,
    summary,
    filters,
    loading,
    error,
    hotSectors,
    hotSectorsMarket,
    hotSectorsByMarket,
    historyList,
    historyTotal,
    historyLimit,
    historyOffset,
    historyMarket,
    detailOpen,
    detailLoading,
    detailError,
    detailRecommendation,
    detailAnalysis,
    fetchRecommendations,
    fetchSummary,
    fetchHotSectors,
    triggerRefresh,
    setFilter,
    selectedSectorsByMarket,
    setSelectedSectorsForMarket,
    clearSelectedSectorsForMarket,
    fetchHistory,
    deleteHistoryByIds,
    openHistoryDetail,
    openLiveDetail: openLiveRecommendationDetail,
    closeDetail,
  } = useRecommendationStore();
  
  const [viewMode, setViewMode] = useState<'live' | 'history'>('live');
  const [smartRecommendAttempted, setSmartRecommendAttempted] = useState(false);
  const [selectedHistoryIds, setSelectedHistoryIds] = useState<Set<number>>(new Set());
  const attemptedHotSectorFetchByMarketRef = useRef<Set<string>>(new Set());
  const inFlightHotSectorFetchByMarketRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    void Promise.all([fetchRecommendations(), fetchSummary()]);
  }, [fetchRecommendations, fetchSummary]);

  const visibleHistoryIds = useMemo(
    () =>
      historyList
        .map((item) => Number(item.id))
        .filter((id) => Number.isInteger(id) && id > 0),
    [historyList],
  );

  const visibleSelectedHistoryIds = useMemo(
    () => new Set(visibleHistoryIds.filter((id) => selectedHistoryIds.has(id))),
    [selectedHistoryIds, visibleHistoryIds],
  );

  const handleViewModeChange = (mode: 'live' | 'history') => {
    setViewMode(mode);
    if (mode === 'history') {
      setSelectedHistoryIds(new Set());
      void fetchHistory(historyMarket, historyLimit, 0);
    }
  };

  const handleHistoryOpenDetail = (item: RecommendationHistoryItem) => {
    void openHistoryDetail(item);
  };

  const handleToggleHistorySelection = (recordId: number) => {
    setSelectedHistoryIds((previous) => {
      const next = new Set(previous);
      if (next.has(recordId)) {
        next.delete(recordId);
      } else {
        next.add(recordId);
      }
      return next;
    });
  };

  const handleToggleSelectAllHistory = () => {
    const allSelected =
      visibleHistoryIds.length > 0 &&
      visibleHistoryIds.every((id) => visibleSelectedHistoryIds.has(id));

    setSelectedHistoryIds((previous) => {
      const next = new Set(previous);
      if (allSelected) {
        visibleHistoryIds.forEach((id) => {
          next.delete(id);
        });
      } else {
        visibleHistoryIds.forEach((id) => {
          next.add(id);
        });
      }
      return next;
    });
  };

  const handleDeleteHistoryIds = async (recordIds: number[]) => {
    await deleteHistoryByIds(recordIds, historyMarket, historyLimit, historyOffset);
    setSelectedHistoryIds((previous) => {
      const next = new Set(previous);
      recordIds.forEach((id) => {
        next.delete(id);
      });
      return next;
    });
  };

  const selectedMarket = normalizeMarket(filters.market ?? filters.region);
  const selectedPriority = String(filters.priority ?? '');

  const fallbackHotSectorMarket = useMemo(() => {
    if (selectedMarket) {
      return selectedMarket;
    }

    const firstRecommendationMarket = recommendations
      .map((item) => normalizeMarket(item.market ?? item.region))
      .find((market) => market.length > 0);

    return firstRecommendationMarket || MarketRegion.CN;
  }, [selectedMarket, recommendations]);

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

  const activeHotSectors = useMemo(
    () => {
      const marketScopedHotSectors = hotSectorsByMarket[fallbackHotSectorMarket];
      if (Array.isArray(marketScopedHotSectors)) {
        return marketScopedHotSectors;
      }
      if (hotSectorsMarket === fallbackHotSectorMarket) {
        return hotSectors;
      }
      return [];
    },
    [fallbackHotSectorMarket, hotSectors, hotSectorsByMarket, hotSectorsMarket],
  );

  const activeSectorMarket = selectedMarket || fallbackHotSectorMarket;
  const selectedSectors = useMemo(
    () => normalizeSectors(selectedSectorsByMarket[activeSectorMarket]),
    [activeSectorMarket, selectedSectorsByMarket],
  );
  const hasSelectedSectors = selectedSectors.length > 0;

  const canonicalKeyByToken = useMemo(() => {
    const aliasToCanonical = new Map<string, string>();
    activeHotSectors.forEach((sector) => {
      const canonicalKey = toNonEmptySectorValue(sector.canonicalKey);
      if (!canonicalKey) {
        return;
      }
      const candidateLabels: unknown[] = [
        sector.name,
        sector.displayLabel,
        sector.canonicalKey,
        ...(sector.aliases ?? []),
      ];
      candidateLabels.forEach((candidateLabel) => {
        const candidateTokens = new Set<string>();
        appendSectorMatchTokens(candidateTokens, candidateLabel);
        candidateTokens.forEach((token) => {
          aliasToCanonical.set(token, canonicalKey);
        });
      });
    });
    return aliasToCanonical;
  }, [activeHotSectors]);

  const selectedSectorTokens = useMemo(() => {
    const tokens = new Set<string>();
    selectedSectors.forEach((sector) => {
      appendSectorMatchTokens(tokens, sector);

      const sectorLookupTokens = new Set<string>();
      appendSectorMatchTokens(sectorLookupTokens, sector);
      sectorLookupTokens.forEach((lookupToken) => {
        const canonicalKey = canonicalKeyByToken.get(lookupToken);
        if (canonicalKey) {
          appendSectorMatchTokens(tokens, canonicalKey);
        }
      });
    });
    return tokens;
  }, [canonicalKeyByToken, selectedSectors]);

  const filteredRecommendations = useMemo(
    () => recommendationPool.filter((item) => {
      if (!hasSelectedSectors) {
        return true;
      }

      const itemTokens = buildRecommendationSectorTokens(item);
      for (const selectedToken of selectedSectorTokens) {
        if (itemTokens.has(selectedToken)) {
          return true;
        }
      }

      return false;
    }),
    [hasSelectedSectors, recommendationPool, selectedSectorTokens],
  );

  const hasActiveHotSectorData = activeHotSectors.length > 0;
  const hasMarketScopedHotSectorRecord = useMemo(
    () => Object.prototype.hasOwnProperty.call(hotSectorsByMarket, fallbackHotSectorMarket),
    [fallbackHotSectorMarket, hotSectorsByMarket],
  );

  useEffect(() => {
    if (loading || viewMode !== 'live') {
      return;
    }
    if (hasActiveHotSectorData || hasMarketScopedHotSectorRecord) {
      return;
    }
    if (inFlightHotSectorFetchByMarketRef.current.has(fallbackHotSectorMarket)) {
      return;
    }
    if (attemptedHotSectorFetchByMarketRef.current.has(fallbackHotSectorMarket)) {
      return;
    }

    attemptedHotSectorFetchByMarketRef.current.add(fallbackHotSectorMarket);
    inFlightHotSectorFetchByMarketRef.current.add(fallbackHotSectorMarket);
    void fetchHotSectors(fallbackHotSectorMarket)
      .finally(() => {
        inFlightHotSectorFetchByMarketRef.current.delete(fallbackHotSectorMarket);
      });
  }, [
    fallbackHotSectorMarket,
    fetchHotSectors,
    hasActiveHotSectorData,
    hasMarketScopedHotSectorRecord,
    loading,
    viewMode,
  ]);

  const refreshDisabled = loading || !selectedMarket;

  const buildNextFilters = (market?: string, priority?: string): RecommendationListFilters => {
    const nextFilters: RecommendationListFilters = {
      ...filters,
      market,
      priority,
    };

    delete nextFilters.region;

    if (!nextFilters.market) {
      delete nextFilters.market;
    }
    if (!nextFilters.priority) {
      delete nextFilters.priority;
    }
    delete nextFilters.sector;
    delete nextFilters.sectors;

    return nextFilters;
  };

  const handleMarketChange = (value: string) => {
    const market = normalizeMarket(value) || undefined;
    setSmartRecommendAttempted(false);
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

  const handleSectorToggle = (sectorOrSectors: string | string[]) => {
    const current = new Set(selectedSectors);
    const sectorsToToggle = Array.isArray(sectorOrSectors) ? sectorOrSectors : [sectorOrSectors];
    
    let isRemoving = false;
    for (const s of sectorsToToggle) {
      if (current.has(s)) {
        isRemoving = true;
        break;
      }
    }

    if (isRemoving) {
      for (const s of sectorsToToggle) {
        current.delete(s);
      }
    } else {
      for (const s of sectorsToToggle) {
        current.add(s);
      }
    }

    const nextArr = Array.from(current);
    if (nextArr.length > 0) {
      setSelectedSectorsForMarket(activeSectorMarket, nextArr);
    } else {
      clearSelectedSectorsForMarket(activeSectorMarket);
    }
    setSmartRecommendAttempted(false);
  };

  const handleClearAllSectors = () => {
    clearSelectedSectorsForMarket(activeSectorMarket);
    setSmartRecommendAttempted(false);
  };

  const handleRefresh = async () => {
    if (!selectedMarket) return;
    
    if (!hasSelectedSectors) {
      setSmartRecommendAttempted(true);
      await fetchHotSectors(selectedMarket);
      await triggerRefresh({ market: selectedMarket });
    } else {
      await triggerRefresh({
        market: selectedMarket,
        sector: selectedSectors[0],
        sectors: selectedSectors,
      });
    }
  };

  const handleOpenLiveDetail = (item: RecommendationItem) => {
    void openLiveRecommendationDetail(item);
  };

  return (
    <div className="min-h-screen flex flex-col" data-testid="recommend-page">
      <main className="flex-1 overflow-y-auto p-3 space-y-4">
        <div className="flex justify-center sm:justify-start mb-2">
          <div className="inline-flex bg-white/5 rounded-lg p-1 border border-white/10">
            <button
              type="button"
              onClick={() => handleViewModeChange('live')}
              className={`px-5 py-1.5 rounded-md text-sm font-medium transition-all ${
                viewMode === 'live'
                  ? 'bg-cyan/15 text-cyan shadow-sm border border-cyan/30'
                  : 'text-secondary-text hover:text-white border border-transparent'
              }`}
            >
              最新推荐
            </button>
            <button
              type="button"
              onClick={() => handleViewModeChange('history')}
              className={`px-5 py-1.5 rounded-md text-sm font-medium transition-all ${
                viewMode === 'history'
                  ? 'bg-cyan/15 text-cyan shadow-sm border border-cyan/30'
                  : 'text-secondary-text hover:text-white border border-transparent'
              }`}
            >
              历史记录
            </button>
          </div>
        </div>

        {viewMode === 'live' ? (
          <>
            <section className="glass-card p-4 border border-white/10">
              <RecommendationHeader
                loading={loading}
                refreshDisabled={refreshDisabled}
                mode={!hasSelectedSectors ? 'smart' : 'manual'}
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
              selectedSectors={selectedSectors}
              onSectorToggle={handleSectorToggle}
              onClearAll={handleClearAllSectors}
              hotSectors={activeHotSectors}
            />

            {!hasSelectedSectors && smartRecommendAttempted && (
              <div className="glass-card border border-orange-500/30 bg-orange-500/5 p-3 flex items-center gap-2 text-sm" data-testid="hot-sectors-display">
                <span className="text-orange-400 font-medium whitespace-nowrap">🔥 智能推荐热门板块：</span>
                {activeHotSectors.length > 0 ? (
                  <div className="flex flex-wrap gap-2">
                    {activeHotSectors.map((sector) => (
                      <span key={sector.name} className="px-2 py-0.5 rounded bg-orange-500/20 text-orange-300 text-xs">
                        {sector.name}
                        {sector.changePct !== undefined && sector.changePct !== null && (
                          <span className="ml-1 opacity-80">
                            {sector.changePct > 0 ? '+' : ''}{sector.changePct.toFixed(2)}%
                          </span>
                        )}
                      </span>
                    ))}
                  </div>
                ) : (
                  <span className="text-orange-300/80 text-xs">暂无热门板块数据，已为您推荐全市场优质标的</span>
                )}
              </div>
            )}

            {error ? (
              <div className="glass-card border border-danger/30 text-danger text-sm p-3">{error}</div>
            ) : null}

            <RecommendationTable
              recommendations={filteredRecommendations}
              loading={loading}
              onRowClick={handleOpenLiveDetail}
            />
          </>
        ) : (
          <RecommendationHistory
            items={historyList}
            loading={loading}
            deleting={loading}
            total={historyTotal}
            limit={historyLimit}
            offset={historyOffset}
            market={historyMarket}
            selectedIds={visibleSelectedHistoryIds}
            onMarketChange={(market) => {
              setSelectedHistoryIds(new Set());
              void fetchHistory(market, historyLimit, 0);
            }}
            onPageChange={(offset) => {
              setSelectedHistoryIds(new Set());
              void fetchHistory(historyMarket, historyLimit, offset);
            }}
            onOpenDetail={handleHistoryOpenDetail}
            onToggleItemSelection={handleToggleHistorySelection}
            onToggleSelectAll={handleToggleSelectAllHistory}
            onDeleteItem={async (recordId) => {
              await handleDeleteHistoryIds([recordId]);
            }}
            onDeleteSelected={async () => {
              await handleDeleteHistoryIds(Array.from(selectedHistoryIds));
            }}
          />
        )}
      </main>
      <RecommendationDetailDrawer
        isOpen={detailOpen}
        loading={detailLoading}
        error={detailError}
        recommendation={detailRecommendation}
        analysisDetail={detailAnalysis}
        onClose={() => {
          closeDetail();
        }}
        onAskAi={(report) => {
          if (report.meta.id === undefined) {
            return;
          }
          navigate(
            `/chat?stock=${encodeURIComponent(report.meta.stockCode)}&name=${encodeURIComponent(report.meta.stockName || '')}&recordId=${report.meta.id}`,
          );
        }}
      />
    </div>
  );
};

export default RecommendPage;
