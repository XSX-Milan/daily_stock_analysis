import { create } from 'zustand';
import { recommendationApi } from '../api/recommendation';
import { getParsedApiError } from '../api/error';
import type {
  PrioritySummary,
  RecommendationFilters,
  RecommendationItem,
  RecommendationRefreshRequest,
  ScoringWeights,
} from '../types/recommendation';

interface RecommendationState {
  recommendations: RecommendationItem[];
  summary: PrioritySummary | null;
  weights: ScoringWeights;
  loading: boolean;
  error: string | null;
  filters: RecommendationFilters;
}

interface RecommendationActions {
  fetchRecommendations: (filters?: RecommendationFilters) => Promise<void>;
  fetchSummary: () => Promise<void>;
  fetchWeights: () => Promise<void>;
  updateWeights: (weights: ScoringWeights) => Promise<void>;
  triggerRefresh: (request: RecommendationRefreshRequest) => Promise<void>;
  setFilter: (key: keyof RecommendationFilters, value?: string) => void;
  clearFilters: () => void;
}

const DEFAULT_FILTERS: RecommendationFilters = {};
const DEFAULT_WEIGHTS: ScoringWeights = {
  technical: 30,
  fundamental: 25,
  sentiment: 20,
  macro: 15,
  risk: 10,
};

export const useRecommendationStore = create<RecommendationState & RecommendationActions>((set, get) => ({
  recommendations: [],
  summary: null,
  weights: DEFAULT_WEIGHTS,
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

  fetchSummary: async () => {
    set({ loading: true, error: null });
    try {
      const summary = await recommendationApi.getSummary();
      set({ summary, loading: false, error: null });
    } catch (error: unknown) {
      set({ loading: false, error: getParsedApiError(error).message });
    }
  },

  fetchWeights: async () => {
    set({ loading: true, error: null });
    try {
      const weights = await recommendationApi.getWeights();
      set({ weights, loading: false, error: null });
    } catch (error: unknown) {
      set({ loading: false, error: getParsedApiError(error).message });
    }
  },

  updateWeights: async (weights) => {
    set({ loading: true, error: null });
    try {
      await recommendationApi.updateWeights(weights);
      const [latestWeights, latestList, latestSummary] = await Promise.all([
        recommendationApi.getWeights(),
        recommendationApi.getRecommendations(get().filters),
        recommendationApi.getSummary(),
      ]);
      set({
        weights: latestWeights,
        recommendations: latestList.items,
        summary: latestSummary,
        loading: false,
        error: null,
      });
    } catch (error: unknown) {
      set({ loading: false, error: getParsedApiError(error).message });
    }
  },

  triggerRefresh: async (request) => {
    const market = String(request.market ?? request.region ?? '').trim().toUpperCase();
    const sector = String(request.sector ?? '').trim();

    if (!market || !sector) {
      set({ error: '请先选择市场和行业后再刷新推荐。' });
      return;
    }

    set({ loading: true, error: null });
    try {
      await recommendationApi.triggerRefresh({
        ...request,
        market,
        sector,
      });
    } catch (error: unknown) {
      set({ error: getParsedApiError(error).message });
      return;
    } finally {
      set({ loading: false });
    }

    const nextFilters: RecommendationFilters = {
      ...get().filters,
      market,
      sector,
    };

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
