import apiClient from './index';
import { toCamelCase } from './utils';
import type { AnalysisReport } from '../types/analysis';
import type {
  MarketRegion,
  RecommendationHotSector,
  RecommendationHotSectorsResponse,
  RecommendationItem,
  RecommendationListFilters,
  RecommendationListParams,
  RecommendationListResponse,
  RecommendationRefreshRequest,
  RecommendationRefreshResponse,
  PrioritySummary,
  WatchlistItem,
} from '../types/recommendation';

export type { RecommendationHotSector, RecommendationHotSectorsResponse } from '../types/recommendation';

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
  sectors?: unknown;
  sectorCanonicalKey?: unknown;
  canonicalKey?: unknown;
  sectorDisplayLabel?: unknown;
  displayLabel?: unknown;
  sectorAliases?: unknown;
  aliases?: unknown;
};

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
  sectors?: string[];
  sectorCanonicalKey?: string | null;
  sectorDisplayLabel?: string | null;
  sectorAliases?: string[];
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

const toNonEmptyStringOrNull = (value: unknown): string | null => {
  if (typeof value !== 'string') {
    return null;
  }
  const normalized = value.trim();
  return normalized.length > 0 ? normalized : null;
};

const normalizeStringArray = (value: unknown): string[] => {
  if (!Array.isArray(value)) {
    return [];
  }

  const normalized: string[] = [];
  for (const entry of value) {
    const resolved = toNonEmptyStringOrNull(entry);
    if (resolved && !normalized.includes(resolved)) {
      normalized.push(resolved);
    }
  }
  return normalized;
};

const normalizeSectors = (sectors: unknown, legacySector?: unknown): string[] => {
  const normalized: string[] = [];
  const legacy = toNonEmptyStringOrNull(legacySector);
  if (legacy) {
    normalized.push(legacy);
  }

  for (const item of normalizeStringArray(sectors)) {
    if (!normalized.includes(item)) {
      normalized.push(item);
    }
  }

  return normalized;
};

const normalizeListFilters = (filters: unknown): RecommendationListFilters => {
  if (!filters || typeof filters !== 'object') {
    return {};
  }

  const rawFilters = toCamelCase<Record<string, unknown>>(filters);
  const normalizedSectors = normalizeSectors(rawFilters.sectors, rawFilters.sector);
  const normalizedSector = toNonEmptyStringOrNull(rawFilters.sector) ?? normalizedSectors[0];

  return {
    priority: toNonEmptyStringOrNull(rawFilters.priority) ?? undefined,
    sector: normalizedSector ?? undefined,
    sectors: normalizedSectors.length > 0 ? normalizedSectors : undefined,
    market: toNonEmptyStringOrNull(rawFilters.market) ?? undefined,
    region: toNonEmptyStringOrNull(rawFilters.region) ?? undefined,
  };
};

const normalizeRefreshFilters = (filters: unknown): Record<string, unknown> => {
  if (!filters || typeof filters !== 'object') {
    return {};
  }

  const normalized = toCamelCase<Record<string, unknown>>(filters);
  const normalizedSectors = normalizeSectors(normalized.sectors, normalized.sector);
  if (normalizedSectors.length === 0) {
    return normalized;
  }

  return {
    ...normalized,
    sector: toNonEmptyStringOrNull(normalized.sector) ?? normalizedSectors[0],
    sectors: normalizedSectors,
  };
};

const normalizeRecommendationItem = (input: unknown): RecommendationItem => {
  const item = input as RawRecommendationItem;
  const composite = item.compositeScore;
  const normalizedSectors = normalizeSectors(item.sectors, item.sector);
  const normalizedSector = toNonEmptyStringOrNull(item.sector) ?? normalizedSectors[0] ?? null;
  const sectorCanonicalKey = toNonEmptyStringOrNull(item.sectorCanonicalKey) ?? toNonEmptyStringOrNull(item.canonicalKey);
  const sectorDisplayLabel =
    toNonEmptyStringOrNull(item.sectorDisplayLabel)
    ?? toNonEmptyStringOrNull(item.displayLabel)
    ?? normalizedSector;
  const sectorAliases = normalizeStringArray(item.sectorAliases ?? item.aliases);

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
    sector: normalizedSector,
    sectors: normalizedSectors,
    sectorCanonicalKey,
    sectorDisplayLabel,
    sectorAliases,
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
  const data = toCamelCase<{ items?: unknown[]; total?: number; filters?: unknown }>(input);
  return {
    items: (data.items ?? []).map((item) => normalizeRecommendationItem(item)),
    total: data.total ?? 0,
    filters: normalizeListFilters(data.filters),
  };
};

const normalizeRecommendationRefreshResponse = (input: Record<string, unknown>): RecommendationRefreshResponse => {
  const data = toCamelCase<{ items?: unknown[]; total?: number; filters?: Record<string, unknown> }>(input);
  return {
    items: (data.items ?? []).map((item) => normalizeRecommendationItem(item)),
    total: data.total ?? 0,
    filters: normalizeRefreshFilters(data.filters),
  };
};

const normalizeHotSectorsResponse = (input: Record<string, unknown>): RecommendationHotSectorsResponse => {
  const data = toCamelCase<{ sectors?: Array<Record<string, unknown>> }>(input);
  return {
    sectors: (data.sectors ?? []).map((sector) => {
      const displayLabel = toNonEmptyStringOrNull(sector.displayLabel);
      const legacyName = toNonEmptyStringOrNull(sector.name);
      const normalizedName = displayLabel ?? legacyName ?? '';

      return {
        name: normalizedName,
        canonicalKey: toNonEmptyStringOrNull(sector.canonicalKey),
        displayLabel: displayLabel ?? legacyName,
        aliases: normalizeStringArray(sector.aliases),
        rawName: toNonEmptyStringOrNull(sector.rawName) ?? legacyName,
        source: toNonEmptyStringOrNull(sector.source),
        changePct: typeof sector.changePct === 'number' ? sector.changePct : null,
        stockCount: typeof sector.stockCount === 'number' ? sector.stockCount : null,
        snapshotAt: toNonEmptyStringOrNull(sector.snapshotAt),
        fetchedAt: toNonEmptyStringOrNull(sector.fetchedAt),
      } satisfies RecommendationHotSector;
    }),
  };
};

const normalizeRecommendationHistory = (input: unknown): RecommendationHistoryItem[] => {
  if (!Array.isArray(input)) {
    return [];
  }

  return input.map((row) => {
    const item = toCamelCase<RecommendationHistoryItem>(row);
    const normalizedSectors = normalizeSectors(item.sectors, item.sector);
    const normalizedSector = toNonEmptyStringOrNull(item.sector) ?? normalizedSectors[0] ?? null;
    return {
      ...item,
      sector: normalizedSector,
      sectors: normalizedSectors,
    };
  });
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
  const normalizedRecommendation = normalizeRecommendationHistory(
    data.recommendation ? [data.recommendation] : [],
  )[0] ?? {};

  return {
    recommendation: normalizedRecommendation,
    analysisDetail: data.analysisDetail ?? null,
  };
};

export const getRecommendations = async (params: RecommendationListParams = {}): Promise<RecommendationListResponse> => {
  const queryParams = new URLSearchParams();
  if (params.priority) queryParams.append('priority', String(params.priority));

  const normalizedSectors = normalizeSectors(params.sectors, params.sector);
  for (const sector of normalizedSectors) {
    queryParams.append('sectors', sector);
  }
  if (normalizedSectors.length > 0) {
    queryParams.append('sector', normalizedSectors[0]);
  }

  if (params.market) queryParams.append('market', String(params.market));
  if (!params.market && params.region) queryParams.append('market', String(params.region));
  if (params.limit != null) queryParams.append('limit', String(params.limit));
  if (params.offset != null) queryParams.append('offset', String(params.offset));

  const response = await apiClient.get<Record<string, unknown>>('/api/v1/recommendation/list', {
    params: queryParams,
  });
  return normalizeRecommendationListResponse(response.data);
};

export const refreshRecommendations = async (
  request: RecommendationRefreshRequest,
): Promise<RecommendationRefreshResponse> => {
  const market = String(request.market ?? request.region ?? '').trim().toUpperCase();
  const sectors = normalizeSectors(request.sectors, request.sector);

  const payload: Record<string, unknown> = {
    market,
    force: request.forceRefresh ?? request.force ?? false,
  };
  if (sectors.length > 0) {
    payload.sectors = sectors;
    payload.sector = sectors[0];
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
