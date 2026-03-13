import apiClient from './index';
import { toCamelCase } from './utils';
import type {
  MarketRegion,
  RecommendationItem,
  RecommendationListParams,
  RecommendationListResponse,
  RecommendationRefreshRequest,
  RecommendationRefreshResponse,
  PrioritySummary,
  ScoringWeights,
  WatchlistItem,
} from '../types/recommendation';

type RawCompositeScore = {
  totalScore?: number;
  priority?: string;
  dimensionScores?: Array<{ dimension?: string; score?: number }>;
};

type RawRecommendationItem = Omit<Partial<RecommendationItem>, 'compositeScore'> & {
  code?: string;
  region?: MarketRegion | string;
  currentPrice?: number;
  idealBuyPrice?: number | null;
  compositeScore?: number | RawCompositeScore;
};

const isRawCompositeScore = (value: RawRecommendationItem['compositeScore']): value is RawCompositeScore => {
  return typeof value === 'object' && value !== null;
};

const normalizeRecommendationItem = (input: unknown): RecommendationItem => {
  const item = input as RawRecommendationItem;
  const composite = item.compositeScore;

  const scoresFromComposite: Record<string, number> =
    isRawCompositeScore(composite) && Array.isArray(composite.dimensionScores)
      ? composite.dimensionScores.reduce<Record<string, number>>(
          (accumulator: Record<string, number>, scoreItem: { dimension?: string; score?: number }) => {
            if (scoreItem.dimension && typeof scoreItem.score === 'number') {
              accumulator[scoreItem.dimension] = scoreItem.score;
            }
            return accumulator;
          },
          {},
        )
      : {};

  const compositeScore = typeof composite === 'number'
    ? composite
    : (isRawCompositeScore(composite) && typeof composite.totalScore === 'number' ? composite.totalScore : 0);
  const priority = item.priority ?? (isRawCompositeScore(composite) ? composite.priority : undefined) ?? 'NO_ENTRY';

  return {
    stockCode: item.stockCode ?? item.code ?? '',
    name: item.name ?? item.stockName ?? '',
    stockName: item.stockName ?? item.name ?? '',
    market: item.market ?? item.region ?? 'CN',
    region: (item.region ?? item.market) as MarketRegion,
    sector: item.sector ?? null,
    scores: item.scores ?? scoresFromComposite,
    compositeScore,
    priority,
    suggestedBuy: item.suggestedBuy ?? item.idealBuyPrice ?? null,
    idealBuyPrice: item.idealBuyPrice ?? item.suggestedBuy ?? null,
    stopLoss: item.stopLoss ?? null,
    takeProfit: item.takeProfit ?? null,
    updatedAt: item.updatedAt ?? '',
  };
};

const normalizeRecommendationListResponse = (input: Record<string, unknown>): RecommendationListResponse => {
  const data = toCamelCase<{ items?: unknown[]; total?: number; filters?: RecommendationListParams }>(input);
  return {
    items: (data.items ?? []).map((item) => normalizeRecommendationItem(item)),
    total: data.total ?? 0,
    filters: data.filters ?? {},
  };
};

const normalizeRecommendationRefreshResponse = (input: Record<string, unknown>): RecommendationRefreshResponse => {
  const data = toCamelCase<{ items?: unknown[]; total?: number; filters?: Record<string, unknown> }>(input);
  return {
    items: (data.items ?? []).map((item) => normalizeRecommendationItem(item)),
    total: data.total ?? 0,
    filters: data.filters ?? {},
  };
};

export const getRecommendations = async (params: RecommendationListParams = {}): Promise<RecommendationListResponse> => {
  const queryParams: Record<string, string | number> = {};
  if (params.priority) queryParams.priority = params.priority;
  if (params.sector) queryParams.sector = params.sector;
  if (params.market) queryParams.market = params.market;
  if (!params.market && params.region) queryParams.market = params.region;
  if (params.limit != null) queryParams.limit = params.limit;
  if (params.offset != null) queryParams.offset = params.offset;

  const response = await apiClient.get<Record<string, unknown>>('/api/v1/recommendation/list', {
    params: queryParams,
  });
  return normalizeRecommendationListResponse(response.data);
};

export const refreshRecommendations = async (
  request: RecommendationRefreshRequest,
): Promise<RecommendationRefreshResponse> => {
  const market = String(request.market ?? request.region ?? '').trim().toUpperCase();
  const sector = String(request.sector ?? '').trim();

  const payload: Record<string, unknown> = {
    market,
    sector,
    force: request.forceRefresh ?? request.force ?? false,
  };
  if (request.stockCodes && request.stockCodes.length > 0) {
    payload.stock_codes = request.stockCodes;
  }

  const response = await apiClient.post<Record<string, unknown>>('/api/v1/recommendation/refresh', payload, {
    timeout: 90000,
  });
  return normalizeRecommendationRefreshResponse(response.data);
};

export const getSummary = async (): Promise<PrioritySummary> => {
  const response = await apiClient.get<Record<string, unknown>>('/api/v1/recommendation/summary');
  return toCamelCase<PrioritySummary>(response.data);
};

export const getScoringWeights = async (): Promise<ScoringWeights> => {
  const response = await apiClient.get<Record<string, unknown>>('/api/v1/recommendation/weights');
  return toCamelCase<ScoringWeights>(response.data);
};

export const updateScoringWeights = async (weights: ScoringWeights): Promise<ScoringWeights> => {
  const response = await apiClient.put<Record<string, unknown>>('/api/v1/recommendation/weights', weights);
  return toCamelCase<ScoringWeights>(response.data);
};

export const getWatchlist = async (): Promise<WatchlistItem[]> => {
  const response = await apiClient.get<Record<string, unknown>>('/api/v1/recommendation/watchlist');
  return toCamelCase<WatchlistItem[]>(response.data);
};

export const addToWatchlist = async (
  code: string,
  name: string,
  region: MarketRegion,
): Promise<WatchlistItem> => {
  const response = await apiClient.post<Record<string, unknown>>('/api/v1/recommendation/watchlist', {
    code,
    name,
    region,
  });
  return toCamelCase<WatchlistItem>(response.data);
};

export const removeFromWatchlist = async (code: string): Promise<void> => {
  await apiClient.delete(`/api/v1/recommendation/watchlist/${encodeURIComponent(code)}`);
};

export const getWeights = getScoringWeights;
export const updateWeights = updateScoringWeights;
export const triggerRefresh = refreshRecommendations;

export const recommendationApi = {
  getRecommendations,
  refreshRecommendations,
  getSummary,
  getScoringWeights,
  updateScoringWeights,
  getWatchlist,
  addToWatchlist,
  removeFromWatchlist,
  getWeights,
  updateWeights,
  triggerRefresh,
};
