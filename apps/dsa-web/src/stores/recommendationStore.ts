import { create } from 'zustand';
import { recommendationApi } from '../api/recommendation';
import { getParsedApiError } from '../api/error';
import type { RecommendationHistoryItem, RecommendationHotSector } from '../api/recommendation';
import type {
  PrioritySummary,
  RecommendationFilters,
  RecommendationItem,
  RecommendationRefreshRequest,
} from '../types/recommendation';

interface RecommendationState {
  recommendations: RecommendationItem[];
  hotSectors: RecommendationHotSector[];
  historyList: RecommendationHistoryItem[];
  historyTotal: number;
  historyLimit: number;
  historyOffset: number;
  historyMarket?: string;
  summary: PrioritySummary | null;
  loading: boolean;
  error: string | null;
  filters: RecommendationFilters;
}

type RecommendationStoreRefreshRequest = Omit<RecommendationRefreshRequest, 'sector'> & {
  sector?: string | null;
};

interface RecommendationActions {
  fetchRecommendations: (filters?: RecommendationFilters) => Promise<void>;
  fetchHotSectors: (market: string) => Promise<void>;
  fetchHistory: (market?: string, limit?: number, offset?: number) => Promise<void>;
  deleteHistoryStock: (code: string, market?: string, limit?: number, offset?: number) => Promise<void>;
  fetchSummary: () => Promise<void>;
  triggerRefresh: (request: RecommendationStoreRefreshRequest) => Promise<void>;
  setFilter: (key: keyof RecommendationFilters, value?: string) => void;
  clearFilters: () => void;
}

const DEFAULT_FILTERS: RecommendationFilters = {};

export const useRecommendationStore = create<RecommendationState & RecommendationActions>((set, get) => ({
  recommendations: [],
  hotSectors: [],
  historyList: [],
  historyTotal: 0,
  historyLimit: 50,
  historyOffset: 0,
  historyMarket: undefined,
  summary: null,
  loading: false,
  error: null,
  filters: { ...DEFAULT_FILTERS },

  fetchRecommendations: async (filters) => {
    const nextFilters = filters ? { ...get().filters, ...filters } : get().filters;
    set({ loading: true, error: null });
    try {
      const response = await recommendationApi.getRecommendations(nextFilters);
      set({ recommendations: response.items, filters: nextFilters, loading: false, error: null });
    } catch (error: unknown) {
      set({ loading: false, error: getParsedApiError(error).message });
    }
  },

  fetchHotSectors: async (market) => {
    const normalizedMarket = String(market ?? '').trim().toUpperCase();
    if (!normalizedMarket) {
      set({ error: '请先选择市场后再获取热门板块。' });
      return;
    }

    set({ loading: true, error: null });
    try {
      const response = await recommendationApi.getHotSectors(normalizedMarket);
      set({ hotSectors: response.sectors, loading: false, error: null });
    } catch (error: unknown) {
      set({ loading: false, error: getParsedApiError(error).message });
    }
  },

  fetchHistory: async (market, limit = 50, offset = 0) => {
    const normalizedMarket = String(market ?? '').trim().toUpperCase();

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

  deleteHistoryStock: async (code, market, limit, offset) => {
    const normalizedCode = String(code ?? '').trim();
    if (!normalizedCode) {
      set({ error: '股票代码不能为空。' });
      return;
    }

    set({ loading: true, error: null });
    try {
      await recommendationApi.deleteHistory(normalizedCode);
      const state = get();
      const nextMarket = String(market ?? state.historyMarket ?? '').trim().toUpperCase();
      const nextLimit = limit ?? state.historyLimit;
      const nextOffset = offset ?? state.historyOffset;
      const response = await recommendationApi.getHistory({
        market: nextMarket || undefined,
        limit: nextLimit,
        offset: nextOffset,
      });
      set({
        historyList: response.items,
        historyTotal: response.total,
        historyLimit: nextLimit,
        historyOffset: nextOffset,
        historyMarket: nextMarket || undefined,
        loading: false,
        error: null,
      });
    } catch (error: unknown) {
      set({ loading: false, error: getParsedApiError(error).message });
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
    const market = String(request.market ?? request.region ?? '').trim().toUpperCase();
    const sector = String(request.sector ?? '').trim();
    const hasSector = sector.length > 0;

    if (!market) {
      set({ error: '请先选择市场后再刷新推荐。' });
      return;
    }

    set({ loading: true, error: null });
    try {
      const refreshRequest = hasSector
        ? {
            ...request,
            market,
            sector,
          }
        : {
            ...request,
            market,
          };
      await recommendationApi.triggerRefresh(refreshRequest as RecommendationRefreshRequest);
    } catch (error: unknown) {
      set({ error: getParsedApiError(error).message });
      return;
    } finally {
      set({ loading: false });
    }

    const currentFilters = get().filters;
    const nextFilters: RecommendationFilters = hasSector
      ? {
          ...currentFilters,
          market,
          sector,
        }
      : (() => {
          const restFilters = { ...currentFilters };
          delete restFilters.sector;
          return {
            ...restFilters,
            market,
          };
        })();

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

  setFilter: (key, value) => {
    set((state) => {
      if (!value) {
        const nextFilters = { ...state.filters };
        delete nextFilters[key];
        return { filters: nextFilters };
      }

      return {
        filters: {
          ...state.filters,
          [key]: value,
        },
      };
    });
  },

  clearFilters: () => set({ filters: { ...DEFAULT_FILTERS } }),
}));
