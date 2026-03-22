import { create } from 'zustand';
import { createJSONStorage, persist, type StateStorage } from 'zustand/middleware';
import { recommendationApi } from '../api/recommendation';
import { getParsedApiError } from '../api/error';
import type { RecommendationHistoryItem, RecommendationHotSector } from '../api/recommendation';
import type { AnalysisReport } from '../types/analysis';
import type {
  PrioritySummary,
  RecommendationFilters,
  RecommendationItem,
  RecommendationListFilters,
  RecommendationRefreshRequest,
} from '../types/recommendation';

interface RecommendationHotSectorCacheMeta {
  snapshotAt: string | null;
  fetchedAt: string | null;
  cachedAt: string;
}

type RecommendationStoreFilters = RecommendationListFilters;

interface RecommendationState {
  recommendations: RecommendationItem[];
  hotSectors: RecommendationHotSector[];
  hotSectorsMarket?: string;
  hotSectorsByMarket: Record<string, RecommendationHotSector[]>;
  hotSectorCacheMetaByMarket: Record<string, RecommendationHotSectorCacheMeta>;
  selectedSectorsByMarket: Record<string, string[]>;
  historyList: RecommendationHistoryItem[];
  historyTotal: number;
  historyLimit: number;
  historyOffset: number;
  historyMarket?: string;
  summary: PrioritySummary | null;
  loading: boolean;
  error: string | null;
  filters: RecommendationStoreFilters;
  detailOpen: boolean;
  detailLoading: boolean;
  detailError: string | null;
  detailRecommendation: RecommendationHistoryItem | null;
  detailAnalysis: AnalysisReport | null;
}

type RecommendationStoreRefreshRequest = Omit<RecommendationRefreshRequest, 'sector'> & {
  sector?: string | null;
};

interface RecommendationActions {
  fetchRecommendations: (filters?: RecommendationStoreFilters) => Promise<void>;
  fetchHotSectors: (market: string) => Promise<boolean>;
  fetchHistory: (market?: string, limit?: number, offset?: number) => Promise<void>;
  deleteHistoryByIds: (recordIds: number[], market?: string, limit?: number, offset?: number) => Promise<void>;
  fetchSummary: () => Promise<void>;
  triggerRefresh: (request: RecommendationStoreRefreshRequest) => Promise<void>;
  openHistoryDetail: (item: RecommendationHistoryItem) => Promise<void>;
  openLiveDetail: (item: RecommendationItem) => Promise<void>;
  closeDetail: () => void;
  setFilter: (key: keyof RecommendationFilters, value?: string) => void;
  setSelectedSectorsForMarket: (market: string, sectors: string[]) => void;
  clearSelectedSectorsForMarket: (market?: string) => void;
  clearFilters: () => void;
}

interface RecommendationStorePersistedSlice {
  selectedSectorsByMarket: Record<string, string[]>;
  hotSectorsByMarket: Record<string, RecommendationHotSector[]>;
  hotSectorCacheMetaByMarket: Record<string, RecommendationHotSectorCacheMeta>;
}

const DEFAULT_FILTERS: RecommendationStoreFilters = {
  market: 'CN',
};
const RECOMMENDATION_STORE_PERSIST_KEY = 'dsa-web-recommendation-store';

const createNoopStorage = (): StateStorage => ({
  getItem: () => null,
  setItem: () => undefined,
  removeItem: () => undefined,
});

const getRecommendationStoreStorage = (): StateStorage => {
  const maybeStorage = (globalThis as { localStorage?: Storage }).localStorage;
  return maybeStorage ?? createNoopStorage();
};

const normalizeMarket = (value: unknown): string => String(value ?? '').trim().toUpperCase();

const toNonEmptyStringOrNull = (value: unknown): string | null => {
  if (typeof value !== 'string') {
    return null;
  }
  const normalized = value.trim();
  return normalized.length > 0 ? normalized : null;
};

const normalizeSectors = (sectors: unknown, legacySector?: unknown): string[] => {
  const normalized: string[] = [];

  const appendSector = (value: unknown) => {
    const resolved = toNonEmptyStringOrNull(value);
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

const normalizeRecommendationFilters = (filters: RecommendationStoreFilters): RecommendationStoreFilters => {
  const normalizedFilters: RecommendationStoreFilters = {
    ...filters,
  };
  const normalizedMarket = normalizeMarket(filters.market ?? filters.region);
  const normalizedSectors = normalizeSectors(filters.sectors, filters.sector);

  if (normalizedMarket) {
    normalizedFilters.market = normalizedMarket;
  } else {
    delete normalizedFilters.market;
  }

  if (normalizedSectors.length > 0) {
    normalizedFilters.sectors = normalizedSectors;
    normalizedFilters.sector = normalizedSectors[0];
  } else {
    delete normalizedFilters.sectors;
    delete normalizedFilters.sector;
  }

  delete normalizedFilters.region;
  if (!normalizedFilters.priority) {
    delete normalizedFilters.priority;
  }

  return normalizedFilters;
};

const normalizeSelectedSectorsByMarket = (value: unknown): Record<string, string[]> => {
  if (!value || typeof value !== 'object') {
    return {};
  }

  return Object.entries(value as Record<string, unknown>).reduce<Record<string, string[]>>((accumulator, [market, sectors]) => {
    const normalizedMarket = normalizeMarket(market);
    if (!normalizedMarket) {
      return accumulator;
    }

    const normalizedSectors = normalizeSectors(sectors);
    if (normalizedSectors.length > 0) {
      accumulator[normalizedMarket] = normalizedSectors;
    }
    return accumulator;
  }, {});
};

const normalizeHotSectorsByMarket = (value: unknown): Record<string, RecommendationHotSector[]> => {
  if (!value || typeof value !== 'object') {
    return {};
  }

  return Object.entries(value as Record<string, unknown>).reduce<Record<string, RecommendationHotSector[]>>((accumulator, [market, sectors]) => {
    const normalizedMarket = normalizeMarket(market);
    if (!normalizedMarket || !Array.isArray(sectors)) {
      return accumulator;
    }

    accumulator[normalizedMarket] = sectors as RecommendationHotSector[];
    return accumulator;
  }, {});
};

const toTimestamp = (value: string | null | undefined): number => {
  if (!value) {
    return 0;
  }
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
};

const pickNewestTimestamp = (values: Array<string | null | undefined>): string | null => {
  let newest: string | null = null;
  let newestTimestamp = 0;

  values.forEach((value) => {
    const resolved = toNonEmptyStringOrNull(value);
    if (!resolved) {
      return;
    }
    const timestamp = toTimestamp(resolved);
    if (timestamp > newestTimestamp) {
      newestTimestamp = timestamp;
      newest = resolved;
    }
  });

  return newest;
};

const buildHotSectorCacheMeta = (
  sectors: RecommendationHotSector[],
  fallback?: Partial<RecommendationHotSectorCacheMeta> | null,
): RecommendationHotSectorCacheMeta => {
  const fallbackSnapshotAt = toNonEmptyStringOrNull(fallback?.snapshotAt);
  const fallbackFetchedAt = toNonEmptyStringOrNull(fallback?.fetchedAt);
  const fallbackCachedAt = toNonEmptyStringOrNull(fallback?.cachedAt);

  return {
    snapshotAt: pickNewestTimestamp([
      ...sectors.map((sector) => toNonEmptyStringOrNull(sector.snapshotAt)),
      fallbackSnapshotAt,
    ]),
    fetchedAt: pickNewestTimestamp([
      ...sectors.map((sector) => toNonEmptyStringOrNull(sector.fetchedAt)),
      fallbackFetchedAt,
    ]),
    cachedAt: fallbackCachedAt ?? new Date().toISOString(),
  };
};

const normalizeHotSectorCacheMetaByMarket = (value: unknown): Record<string, RecommendationHotSectorCacheMeta> => {
  if (!value || typeof value !== 'object') {
    return {};
  }

  return Object.entries(value as Record<string, unknown>).reduce<Record<string, RecommendationHotSectorCacheMeta>>(
    (accumulator, [market, meta]) => {
      const normalizedMarket = normalizeMarket(market);
      if (!normalizedMarket || !meta || typeof meta !== 'object') {
        return accumulator;
      }

      accumulator[normalizedMarket] = buildHotSectorCacheMeta([], meta as RecommendationHotSectorCacheMeta);
      return accumulator;
    },
    {},
  );
};

const getHotSectorCacheFreshnessScore = (
  sectors: RecommendationHotSector[],
  meta?: RecommendationHotSectorCacheMeta,
): number => {
  const timestampCandidates = [
    toTimestamp(meta?.snapshotAt),
    toTimestamp(meta?.fetchedAt),
    ...sectors.map((sector) => toTimestamp(toNonEmptyStringOrNull(sector.snapshotAt))),
    ...sectors.map((sector) => toTimestamp(toNonEmptyStringOrNull(sector.fetchedAt))),
  ];

  return Math.max(0, ...timestampCandidates);
};

interface HotSectorCacheRecord {
  sectors: RecommendationHotSector[];
  meta: RecommendationHotSectorCacheMeta;
}

const selectPreferredHotSectorCacheRecord = (
  primaryRecord: HotSectorCacheRecord,
  secondaryRecord: HotSectorCacheRecord,
  preferPrimaryOnEqual: boolean,
): HotSectorCacheRecord => {
  const primaryFreshness = getHotSectorCacheFreshnessScore(primaryRecord.sectors, primaryRecord.meta);
  const secondaryFreshness = getHotSectorCacheFreshnessScore(secondaryRecord.sectors, secondaryRecord.meta);

  if (primaryFreshness > secondaryFreshness) {
    return primaryRecord;
  }
  if (secondaryFreshness > primaryFreshness) {
    return secondaryRecord;
  }

  if (primaryRecord.sectors.length !== secondaryRecord.sectors.length) {
    return primaryRecord.sectors.length > secondaryRecord.sectors.length ? primaryRecord : secondaryRecord;
  }

  return preferPrimaryOnEqual ? primaryRecord : secondaryRecord;
};

const withSelectedSectorsForMarket = (
  selectedSectorsByMarket: Record<string, string[]>,
  market: string,
  sectors: string[],
): Record<string, string[]> => {
  const normalizedMarket = normalizeMarket(market);
  if (!normalizedMarket) {
    return selectedSectorsByMarket;
  }

  const nextSelectedSectorsByMarket = { ...selectedSectorsByMarket };
  const normalizedSectors = normalizeSectors(sectors);
  if (normalizedSectors.length === 0) {
    delete nextSelectedSectorsByMarket[normalizedMarket];
  } else {
    nextSelectedSectorsByMarket[normalizedMarket] = normalizedSectors;
  }

  return nextSelectedSectorsByMarket;
};

const buildHotSectorCacheRecord = (
  sectors: RecommendationHotSector[],
  meta?: RecommendationHotSectorCacheMeta,
): HotSectorCacheRecord => ({
  sectors,
  meta: buildHotSectorCacheMeta(sectors, meta),
});

const mergePersistedRecommendationState = (
  persistedState: unknown,
  currentState: RecommendationState & RecommendationActions,
): RecommendationState & RecommendationActions => {
  if (!persistedState || typeof persistedState !== 'object') {
    return currentState;
  }

  const persistedSlice = persistedState as Partial<RecommendationStorePersistedSlice>;
  const persistedSelectedSectorsByMarket = normalizeSelectedSectorsByMarket(persistedSlice.selectedSectorsByMarket);
  const persistedHotSectorsByMarket = normalizeHotSectorsByMarket(persistedSlice.hotSectorsByMarket);
  const persistedHotSectorCacheMetaByMarket = normalizeHotSectorCacheMetaByMarket(persistedSlice.hotSectorCacheMetaByMarket);

  const mergedSelectedSectorsByMarket = {
    ...persistedSelectedSectorsByMarket,
    ...normalizeSelectedSectorsByMarket(currentState.selectedSectorsByMarket),
  };

  const mergedHotSectorsByMarket: Record<string, RecommendationHotSector[]> = {
    ...normalizeHotSectorsByMarket(currentState.hotSectorsByMarket),
  };
  const mergedHotSectorCacheMetaByMarket: Record<string, RecommendationHotSectorCacheMeta> = {
    ...normalizeHotSectorCacheMetaByMarket(currentState.hotSectorCacheMetaByMarket),
  };

  Object.entries(persistedHotSectorsByMarket).forEach(([market, persistedSectors]) => {
    const currentRecord = buildHotSectorCacheRecord(
      mergedHotSectorsByMarket[market] ?? [],
      mergedHotSectorCacheMetaByMarket[market],
    );
    const persistedRecord = buildHotSectorCacheRecord(
      persistedSectors,
      persistedHotSectorCacheMetaByMarket[market],
    );
    const preferredRecord = selectPreferredHotSectorCacheRecord(currentRecord, persistedRecord, true);

    mergedHotSectorsByMarket[market] = preferredRecord.sectors;
    mergedHotSectorCacheMetaByMarket[market] = preferredRecord.meta;
  });

  Object.entries(mergedHotSectorsByMarket).forEach(([market, sectors]) => {
    mergedHotSectorCacheMetaByMarket[market] = buildHotSectorCacheMeta(
      sectors,
      mergedHotSectorCacheMetaByMarket[market],
    );
  });

  return {
    ...currentState,
    hotSectorsByMarket: mergedHotSectorsByMarket,
    hotSectorCacheMetaByMarket: mergedHotSectorCacheMetaByMarket,
    selectedSectorsByMarket: mergedSelectedSectorsByMarket,
  };
};

const toPositiveRecordId = (value: unknown): number | null => {
  if (typeof value !== 'number') {
    return null;
  }
  return Number.isInteger(value) && value > 0 ? value : null;
};

const normalizeLiveDetailRecommendation = (item: RecommendationItem): RecommendationHistoryItem => {
  const recommendationRecordId = toPositiveRecordId(item.recommendationRecordId);
  const analysisRecordId = toPositiveRecordId(item.analysisRecordId);
  return {
    id: recommendationRecordId ?? undefined,
    analysisRecordId,
    code: item.stockCode,
    name: item.stockName ?? item.name,
    sector: item.sector ?? null,
    compositeScore: item.compositeScore,
    priority: item.priority,
    updatedAt: item.updatedAt,
    market: item.market,
    region: item.region ?? item.market,
    aiSummary: item.aiSummary ?? null,
  };
};

const hasDetailRecommendation = (item: RecommendationHistoryItem | null | undefined): boolean => {
  if (!item) {
    return false;
  }
  return Boolean(item.id || item.code || item.name || item.analysisRecordId);
};

export const useRecommendationStore = create<RecommendationState & RecommendationActions>()(
  persist(
    (set, get) => ({
      recommendations: [],
      hotSectors: [],
      hotSectorsMarket: undefined,
      hotSectorsByMarket: {},
      hotSectorCacheMetaByMarket: {},
      selectedSectorsByMarket: {},
      historyList: [],
      historyTotal: 0,
      historyLimit: 50,
      historyOffset: 0,
      historyMarket: undefined,
      summary: null,
      loading: false,
      error: null,
      filters: { ...DEFAULT_FILTERS },
      detailOpen: false,
      detailLoading: false,
      detailError: null,
      detailRecommendation: null,
      detailAnalysis: null,

      fetchRecommendations: async (filters) => {
        const mergedFilters = filters ? { ...get().filters, ...filters } : get().filters;
        const nextFilters = normalizeRecommendationFilters(mergedFilters);
        set({ loading: true, error: null });
        try {
          const response = await recommendationApi.getRecommendations(nextFilters);
          set({ recommendations: response.items, filters: nextFilters, loading: false, error: null });
        } catch (error: unknown) {
          set({ loading: false, error: getParsedApiError(error).message });
        }
      },

      fetchHotSectors: async (market) => {
        const normalizedMarket = normalizeMarket(market);
        if (!normalizedMarket) {
          set({ error: '请先选择市场后再获取热门板块。' });
          return false;
        }

        set({ loading: true, error: null });
        try {
          const response = await recommendationApi.getHotSectors(normalizedMarket);
          set((state) => {
            const incomingRecord = buildHotSectorCacheRecord(response.sectors);
            const currentRecord = buildHotSectorCacheRecord(
              state.hotSectorsByMarket[normalizedMarket] ?? [],
              state.hotSectorCacheMetaByMarket[normalizedMarket],
            );
            const preferredRecord = response.sectors.length === 0
              ? incomingRecord
              : selectPreferredHotSectorCacheRecord(incomingRecord, currentRecord, true);

            return {
              hotSectors: preferredRecord.sectors,
              hotSectorsMarket: normalizedMarket,
              hotSectorsByMarket: {
                ...state.hotSectorsByMarket,
                [normalizedMarket]: preferredRecord.sectors,
              },
              hotSectorCacheMetaByMarket: {
                ...state.hotSectorCacheMetaByMarket,
                [normalizedMarket]: {
                  ...preferredRecord.meta,
                  cachedAt: new Date().toISOString(),
                },
              },
              loading: false,
              error: null,
            };
          });
          return true;
        } catch (error: unknown) {
          set({ loading: false, error: getParsedApiError(error).message });
          return false;
        }
      },

      fetchHistory: async (market, limit = 50, offset = 0) => {
        const normalizedMarket = normalizeMarket(market);

        set({ loading: true, error: null });
        try {
          const response = await recommendationApi.getHistory({
            market: normalizedMarket || undefined,
            limit,
            offset,
          });
          set({
            historyList: response.items,
            historyTotal: response.total,
            historyLimit: limit,
            historyOffset: offset,
            historyMarket: normalizedMarket || undefined,
            loading: false,
            error: null,
          });
        } catch (error: unknown) {
          set({ loading: false, error: getParsedApiError(error).message });
        }
      },

      deleteHistoryByIds: async (recordIds, market, limit, offset) => {
        const normalizedIds = Array.from(
          new Set(recordIds.map((recordId) => Number(recordId)).filter((recordId) => Number.isInteger(recordId) && recordId > 0)),
        );
        if (normalizedIds.length === 0) {
          set({ error: '请选择至少一条推荐记录。' });
          return;
        }

        const previousState = get();
        const nextMarket = normalizeMarket(market ?? previousState.historyMarket);
        const nextLimit = limit ?? previousState.historyLimit;
        const nextOffset = offset ?? previousState.historyOffset;
        const idSet = new Set(normalizedIds);
        const nextHistoryList = previousState.historyList.filter((item) => !idSet.has(Number(item.id)));
        const removedVisibleCount = previousState.historyList.length - nextHistoryList.length;
        const activeDetailRecordId = Number(previousState.detailRecommendation?.id);
        const shouldCloseDetail = Number.isInteger(activeDetailRecordId) && idSet.has(activeDetailRecordId);
        const previousDetailState = {
          detailOpen: previousState.detailOpen,
          detailLoading: previousState.detailLoading,
          detailError: previousState.detailError,
          detailRecommendation: previousState.detailRecommendation,
          detailAnalysis: previousState.detailAnalysis,
        };

        set({
          historyList: nextHistoryList,
          historyTotal: Math.max(0, previousState.historyTotal - removedVisibleCount),
          historyLimit: nextLimit,
          historyOffset: nextOffset,
          historyMarket: nextMarket || undefined,
          loading: true,
          error: null,
          ...(shouldCloseDetail
            ? {
                detailOpen: false,
                detailLoading: false,
                detailError: null,
                detailRecommendation: null,
                detailAnalysis: null,
              }
            : {}),
        });

        try {
          const response = await recommendationApi.deleteHistoryByIds(normalizedIds);
          const shouldRefetchPage =
            response.deleted !== normalizedIds.length
            || (nextHistoryList.length === 0 && Math.max(0, previousState.historyTotal - response.deleted) > 0);

          if (shouldRefetchPage) {
            const fallbackOffset = nextHistoryList.length === 0 && nextOffset > 0
              ? Math.max(0, nextOffset - nextLimit)
              : nextOffset;
            const refreshed = await recommendationApi.getHistory({
              market: nextMarket || undefined,
              limit: nextLimit,
              offset: fallbackOffset,
            });
            set({
              historyList: refreshed.items,
              historyTotal: refreshed.total,
              historyLimit: nextLimit,
              historyOffset: fallbackOffset,
              historyMarket: nextMarket || undefined,
              loading: false,
              error: null,
            });
            return;
          }

          set({
            historyTotal: Math.max(0, previousState.historyTotal - response.deleted),
            historyLimit: nextLimit,
            historyOffset: nextOffset,
            historyMarket: nextMarket || undefined,
            loading: false,
            error: null,
          });
        } catch (error: unknown) {
          set({
            historyList: previousState.historyList,
            historyTotal: previousState.historyTotal,
            historyLimit: previousState.historyLimit,
            historyOffset: previousState.historyOffset,
            historyMarket: previousState.historyMarket,
            loading: false,
            error: getParsedApiError(error).message,
            ...(shouldCloseDetail ? previousDetailState : {}),
          });
        }
      },

      fetchSummary: async () => {
        set({ loading: true, error: null });
        try {
          const summary = await recommendationApi.getSummary();
          set({ summary, loading: false, error: null });
        } catch (error: unknown) {
          set({ loading: false, error: getParsedApiError(error).message });
        }
      },

      triggerRefresh: async (request) => {
        const market = normalizeMarket(request.market ?? request.region);
        const normalizedSectors = normalizeSectors(request.sectors, request.sector);
        const hasSectors = normalizedSectors.length > 0;

        if (!market) {
          set({ error: '请先选择市场后再刷新推荐。' });
          return;
        }

        set((state) => ({
          loading: true,
          error: null,
          selectedSectorsByMarket: withSelectedSectorsForMarket(state.selectedSectorsByMarket, market, normalizedSectors),
        }));
        try {
          const refreshRequest: RecommendationRefreshRequest = {
            market,
            region: request.region,
            force: request.force,
            forceRefresh: request.forceRefresh,
            stockCodes: request.stockCodes,
          };
          if (hasSectors) {
            refreshRequest.sector = normalizedSectors[0];
            refreshRequest.sectors = normalizedSectors;
          } else {
            delete refreshRequest.sector;
            delete refreshRequest.sectors;
          }
          await recommendationApi.triggerRefresh(refreshRequest);
        } catch (error: unknown) {
          set({ error: getParsedApiError(error).message });
          return;
        } finally {
          set({ loading: false });
        }

        const currentFilters = normalizeRecommendationFilters(get().filters);
        const nextFilters = normalizeRecommendationFilters({
          ...currentFilters,
          market,
          sectors: hasSectors ? normalizedSectors : undefined,
          sector: hasSectors ? normalizedSectors[0] : undefined,
        });

        if (!hasSectors) {
          delete nextFilters.sector;
          delete nextFilters.sectors;
        }

        void Promise.all([
          recommendationApi.getRecommendations(nextFilters),
          recommendationApi.getSummary(),
        ])
          .then(([latestList, latestSummary]) => {
            set({
              recommendations: latestList.items,
              summary: latestSummary,
              filters: nextFilters,
              error: null,
            });
          })
          .catch((error: unknown) => {
            set({ error: getParsedApiError(error).message });
          });
      },

      openHistoryDetail: async (item) => {
        const fallbackRecommendation = item;
        const recommendationRecordId = toPositiveRecordId(item.id);

        set({
          detailOpen: true,
          detailLoading: true,
          detailError: null,
          detailRecommendation: fallbackRecommendation,
          detailAnalysis: null,
        });

        if (!recommendationRecordId) {
          set({ detailLoading: false });
          return;
        }

        try {
          const response = await recommendationApi.getDetailByLink({
            recommendationRecordId,
            analysisRecordId: toPositiveRecordId(item.analysisRecordId),
            fallbackRecommendation,
          });
          set({
            detailRecommendation: hasDetailRecommendation(response.recommendation)
              ? response.recommendation
              : fallbackRecommendation,
            detailAnalysis: response.analysisDetail ?? null,
            detailError: null,
          });
        } catch (error: unknown) {
          set({
            detailAnalysis: null,
            detailError: getParsedApiError(error).message,
          });
        } finally {
          set({ detailLoading: false });
        }
      },

      openLiveDetail: async (item) => {
        const fallbackRecommendation = normalizeLiveDetailRecommendation(item);
        const recommendationRecordId = toPositiveRecordId(item.recommendationRecordId);
        const analysisRecordId = toPositiveRecordId(item.analysisRecordId);

        set({
          detailOpen: true,
          detailLoading: true,
          detailError: null,
          detailRecommendation: fallbackRecommendation,
          detailAnalysis: null,
        });

        if (!recommendationRecordId && !analysisRecordId) {
          set({ detailLoading: false });
          return;
        }

        try {
          const response = await recommendationApi.getDetailByLink({
            recommendationRecordId,
            analysisRecordId,
            fallbackRecommendation,
          });
          set({
            detailRecommendation: hasDetailRecommendation(response.recommendation)
              ? response.recommendation
              : fallbackRecommendation,
            detailAnalysis: response.analysisDetail ?? null,
            detailError: null,
          });
        } catch (error: unknown) {
          set({
            detailAnalysis: null,
            detailError: getParsedApiError(error).message,
          });
        } finally {
          set({ detailLoading: false });
        }
      },

      closeDetail: () => {
        set({
          detailOpen: false,
          detailLoading: false,
          detailError: null,
          detailRecommendation: null,
          detailAnalysis: null,
        });
      },

      setFilter: (key, value) => {
        set((state) => {
          const nextFilters: RecommendationStoreFilters = {
            ...state.filters,
          };

          if (!value) {
            if (key === 'sector') {
              delete nextFilters.sector;
              delete nextFilters.sectors;
            } else if (key === 'market') {
              delete nextFilters.market;
              delete nextFilters.region;
            } else {
              delete nextFilters[key];
            }
            return { filters: normalizeRecommendationFilters(nextFilters) };
          }

          if (key === 'market') {
            const normalizedMarket = normalizeMarket(value);
            if (normalizedMarket) {
              nextFilters.market = normalizedMarket;
              delete nextFilters.region;
            }
            return { filters: normalizeRecommendationFilters(nextFilters) };
          }

          if (key === 'sector') {
            const normalizedSectors = normalizeSectors(undefined, value);
            if (normalizedSectors.length > 0) {
              nextFilters.sector = normalizedSectors[0];
              nextFilters.sectors = normalizedSectors;
            }
            return { filters: normalizeRecommendationFilters(nextFilters) };
          }

          nextFilters[key] = value;
          return { filters: normalizeRecommendationFilters(nextFilters) };
        });
      },

      setSelectedSectorsForMarket: (market, sectors) => {
        set((state) => ({
          selectedSectorsByMarket: withSelectedSectorsForMarket(state.selectedSectorsByMarket, market, sectors),
        }));
      },

      clearSelectedSectorsForMarket: (market) => {
        set((state) => {
          if (!market) {
            return { selectedSectorsByMarket: {} };
          }
          const normalizedMarket = normalizeMarket(market);
          if (!normalizedMarket) {
            return { selectedSectorsByMarket: state.selectedSectorsByMarket };
          }

          const nextSelectedSectorsByMarket = { ...state.selectedSectorsByMarket };
          delete nextSelectedSectorsByMarket[normalizedMarket];
          return { selectedSectorsByMarket: nextSelectedSectorsByMarket };
        });
      },

      clearFilters: () => set({ filters: { ...DEFAULT_FILTERS } }),
    }),
    {
      name: RECOMMENDATION_STORE_PERSIST_KEY,
      version: 1,
      storage: createJSONStorage(() => getRecommendationStoreStorage()),
      partialize: (state): RecommendationStorePersistedSlice => ({
        selectedSectorsByMarket: state.selectedSectorsByMarket,
        hotSectorsByMarket: state.hotSectorsByMarket,
        hotSectorCacheMetaByMarket: state.hotSectorCacheMetaByMarket,
      }),
      merge: (persistedState, currentState) =>
        mergePersistedRecommendationState(
          persistedState,
          currentState as RecommendationState & RecommendationActions,
        ),
    },
  ),
);
