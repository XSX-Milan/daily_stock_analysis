export const RecommendationPriority = {
  BUY_NOW: 'BUY_NOW',
  POSITION: 'POSITION',
  WAIT_PULLBACK: 'WAIT_PULLBACK',
  NO_ENTRY: 'NO_ENTRY',
} as const;

export type RecommendationPriority =
  (typeof RecommendationPriority)[keyof typeof RecommendationPriority];

export const MarketRegion = {
  CN: 'CN',
  HK: 'HK',
  US: 'US',
} as const;

export type MarketRegion = (typeof MarketRegion)[keyof typeof MarketRegion];

export interface RecommendationSectorMetadata {
  sectorCanonicalKey?: string | null;
  sectorDisplayLabel?: string | null;
  sectorAliases?: string[];
}

export interface RecommendationItem extends RecommendationSectorMetadata {
  recommendationRecordId?: number | null;
  stockCode: string;
  name: string;
  stockName?: string;
  market: MarketRegion | string;
  region?: MarketRegion;
  analysisRecordId?: number | null;
  sector?: string | null;
  sectors?: string[];
  scores: Record<string, number>;
  compositeScore: number;
  priority: RecommendationPriority | string;
  suggestedBuy?: number | null;
  idealBuyPrice?: number | null;
  stopLoss?: number | null;
  takeProfit?: number | null;
  aiSummary?: string | null;
  aiRefined?: boolean;
  updatedAt: string;
}

export interface DimensionScore {
  dimension: string;
  score: number;
  weight: number;
  details: Record<string, unknown>;
}

export interface CompositeScore {
  totalScore: number;
  priority: RecommendationPriority;
  dimensionScores: DimensionScore[];
  aiRefined: boolean;
  aiSummary: string | null;
}

export interface StockRecommendation extends RecommendationSectorMetadata {
  code: string;
  name: string;
  region: MarketRegion;
  sector: string | null;
  sectors?: string[];
  currentPrice: number;
  compositeScore: CompositeScore;
  idealBuyPrice: number | null;
  stopLoss: number | null;
  takeProfit: number | null;
  updatedAt: string;
}

export interface WatchlistItem {
  code: string;
  name: string;
  region: MarketRegion;
  addedAt: string;
}

export interface RecommendationFilters {
  priority?: RecommendationPriority | string;
  sector?: string;
  market?: MarketRegion | string;
  region?: MarketRegion | string;
}

export interface RecommendationListFilters extends RecommendationFilters {
  sectors?: string[];
}

export interface PrioritySummary {
  buyNow: number;
  position: number;
  waitPullback: number;
  noEntry: number;
}

export type RecommendationSummary = PrioritySummary;

export interface RecommendationListResponse {
  items: RecommendationItem[];
  total: number;
  filters: RecommendationListFilters;
}

export interface RecommendationListParams extends RecommendationListFilters {
  limit?: number;
  offset?: number;
}

export interface RecommendationRefreshRequest {
  market: MarketRegion | string;
  region?: MarketRegion | string;
  sector?: string;
  sectors?: string[];
  force?: boolean;
  forceRefresh?: boolean;
  stockCodes?: string[];
}

export interface RecommendationRefreshResponse {
  items: RecommendationItem[];
  total: number;
  filters: Record<string, unknown>;
}

export interface RecommendationHotSector {
  name: string;
  canonicalKey?: string | null;
  displayLabel?: string | null;
  aliases?: string[];
  rawName?: string | null;
  source?: string | null;
  changePct?: number | null;
  stockCount?: number | null;
  isHot?: boolean;
  hotRank?: number | null;
  snapshotAt?: string | null;
  fetchedAt?: string | null;
}

export interface RecommendationHotSectorsResponse {
  sectors: RecommendationHotSector[];
}
