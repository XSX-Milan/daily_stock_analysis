import apiClient from './index';
import { toCamelCase } from './utils';
import type { AnalysisReport } from '../types/analysis';
import type {
  MarketRegion,
  RecommendationItem,
  RecommendationListParams,
  RecommendationListResponse,
  RecommendationRefreshRequest,
  RecommendationRefreshResponse,
  PrioritySummary,
  WatchlistItem,
} from '../types/recommendation';

type RawCompositeScore = {
  totalScore?: number;
  priority?: string;
  aiSummary?: string | null;
  aiRefined?: boolean;
  dimensionScores?: Array<{ dimension?: string; score?: number }>;
};

type RawRecommendationItem = Omit<Partial<RecommendationItem>, 'compositeScore'> & {
  id?: number;
  recommendationRecordId?: number | null;
  code?: string;
  region?: MarketRegion | string;
  currentPrice?: number;
  idealBuyPrice?: number | null;
  compositeScore?: number | RawCompositeScore;
};

export interface RecommendationHotSector {
  name: string;
  changePct?: number | null;
  stockCount?: number | null;
}

export interface RecommendationHotSectorsResponse {
  sectors: RecommendationHotSector[];
}

export interface RecommendationHistoryParams {
  market?: MarketRegion | string;
  limit?: number;
  offset?: number;
}

export interface RecommendationHistoryItem {
  id?: number;
  queryId?: string | null;
  analysisRecordId?: number | null;
  code?: string;
  name?: string;
  sector?: string | null;
  compositeScore?: number;
  priority?: string;
  recommendationDate?: string;
  updatedAt?: string | null;
  aiSummary?: string | null;
  region?: MarketRegion | string;
  market?: MarketRegion | string;
  [key: string]: unknown;
}

export interface RecommendationHistoryDeleteResponse {
  status: string;
  deleted: number;
}

export interface RecommendationHistoryResponse {
  items: RecommendationHistoryItem[];
  total: number;
  filters?: RecommendationHistoryParams;
}

export interface RecommendationDetailResponse {
  recommendation: RecommendationHistoryItem;
  analysisDetail?: AnalysisReport | null;
}

export interface RecommendationDetailLookupParams {
  recommendationRecordId?: number | null;
  analysisRecordId?: number | null;
  fallbackRecommendation?: RecommendationHistoryItem;
}

const isRawCompositeScore = (value: RawRecommendationItem['compositeScore']): value is RawCompositeScore => {
  return typeof value === 'object' && value !== null;
};

const toPositiveIntOrNull = (value: unknown): number | null => {
  if (typeof value !== 'number') {
    return null;
  }
  const normalized = Number(value);
  return Number.isInteger(normalized) && normalized > 0 ? normalized : null;
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
  const aiSummary = item.aiSummary ?? (isRawCompositeScore(composite) ? composite.aiSummary : undefined);
  const aiRefined = item.aiRefined ?? (isRawCompositeScore(composite) ? composite.aiRefined : undefined);

  return {
    recommendationRecordId: toPositiveIntOrNull(item.recommendationRecordId ?? item.id),
    stockCode: item.stockCode ?? item.code ?? '',
    name: item.name ?? item.stockName ?? '',
    stockName: item.stockName ?? item.name ?? '',
    market: item.market ?? item.region ?? 'CN',
    region: (item.region ?? item.market) as MarketRegion,
    analysisRecordId:
      typeof item.analysisRecordId === 'number' ? item.analysisRecordId : null,
    sector: item.sector ?? null,
    scores: item.scores ?? scoresFromComposite,
    compositeScore,
    priority,
    suggestedBuy: item.suggestedBuy ?? item.idealBuyPrice ?? null,
    idealBuyPrice: item.idealBuyPrice ?? item.suggestedBuy ?? null,
    stopLoss: item.stopLoss ?? null,
    takeProfit: item.takeProfit ?? null,
    aiSummary,
    aiRefined,
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

const normalizeHotSectorsResponse = (input: Record<string, unknown>): RecommendationHotSectorsResponse => {
  const data = toCamelCase<{ sectors?: Array<Record<string, unknown>> }>(input);
  return {
    sectors: (data.sectors ?? []).map((sector) => ({
      name: String(sector.name ?? ''),
      changePct: typeof sector.changePct === 'number' ? sector.changePct : null,
      stockCount: typeof sector.stockCount === 'number' ? sector.stockCount : null,
    })),
  };
};

const normalizeRecommendationHistory = (input: unknown): RecommendationHistoryItem[] => {
  if (!Array.isArray(input)) {
    return [];
  }
  return input.map((row) => toCamelCase<RecommendationHistoryItem>(row));
};

const normalizeRecommendationHistoryResponse = (input: Record<string, unknown>): RecommendationHistoryResponse => {
  const data = toCamelCase<{ items?: unknown; total?: number; filters?: RecommendationHistoryParams }>(input);
  return {
    items: normalizeRecommendationHistory(data.items),
    total: data.total ?? 0,
    filters: data.filters,
  };
};

const normalizeRecommendationDetailResponse = (
  input: Record<string, unknown>,
): RecommendationDetailResponse => {
  const data = toCamelCase<{
    recommendation?: RecommendationHistoryItem;
    analysisDetail?: AnalysisReport | null;
  }>(input);
  return {
    recommendation: data.recommendation ?? {},
    analysisDetail: data.analysisDetail ?? null,
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
  const sector = typeof request.sector === 'string' ? request.sector.trim() : '';

  const payload: Record<string, unknown> = {
    market,
    force: request.forceRefresh ?? request.force ?? false,
  };
  if (sector) {
    payload.sector = sector;
  }
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

export const getHotSectors = async (market: MarketRegion | string): Promise<RecommendationHotSectorsResponse> => {
  const response = await apiClient.get<Record<string, unknown>>('/api/v1/recommendation/hot-sectors', {
    params: { market },
    timeout: 90000,
  });
  return normalizeHotSectorsResponse(response.data);
};

export const getHistory = async (params: RecommendationHistoryParams = {}): Promise<RecommendationHistoryResponse> => {
  const queryParams: Record<string, string | number> = {};
  if (params.market) queryParams.market = params.market;
  if (params.limit != null) queryParams.limit = params.limit;
  if (params.offset != null) queryParams.offset = params.offset;

  const response = await apiClient.get<Record<string, unknown>>('/api/v1/recommendation/history', {
    params: queryParams,
  });
  return normalizeRecommendationHistoryResponse(response.data);
};

export const deleteHistoryByIds = async (recordIds: number[]): Promise<RecommendationHistoryDeleteResponse> => {
  const response = await apiClient.delete<Record<string, unknown>>('/api/v1/recommendation/history', {
    data: { record_ids: recordIds },
  });
  return toCamelCase<RecommendationHistoryDeleteResponse>(response.data);
};

export const getDetail = async (recordId: number): Promise<RecommendationDetailResponse> => {
  const response = await apiClient.get<Record<string, unknown>>(`/api/v1/recommendation/detail/${recordId}`);
  return normalizeRecommendationDetailResponse(response.data);
};

const getAnalysisDetailById = async (analysisRecordId: number): Promise<AnalysisReport> => {
  const response = await apiClient.get<Record<string, unknown>>(`/api/v1/history/${analysisRecordId}`);
  return toCamelCase<AnalysisReport>(response.data);
};

export const getDetailByLink = async (
  params: RecommendationDetailLookupParams,
): Promise<RecommendationDetailResponse> => {
  const recommendationRecordId = toPositiveIntOrNull(params.recommendationRecordId);
  if (recommendationRecordId) {
    return getDetail(recommendationRecordId);
  }

  const analysisRecordId = toPositiveIntOrNull(params.analysisRecordId);
  if (!analysisRecordId) {
    return {
      recommendation: params.fallbackRecommendation ?? {},
      analysisDetail: null,
    };
  }

  const analysisDetail = await getAnalysisDetailById(analysisRecordId);
  return {
    recommendation: params.fallbackRecommendation ?? {},
    analysisDetail,
  };
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

export const triggerRefresh = refreshRecommendations;

export const recommendationApi = {
  getRecommendations,
  refreshRecommendations,
  getHotSectors,
  getHistory,
  getDetail,
  getDetailByLink,
  deleteHistoryByIds,
  getSummary,
  getWatchlist,
  addToWatchlist,
  removeFromWatchlist,
  triggerRefresh,
};
