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

export interface RecommendationItem {
  recommendationRecordId?: number | null;
  stockCode: string;
  name: string;
  stockName?: string;
  market: MarketRegion | string;
  region?: MarketRegion;
  analysisRecordId?: number | null;
  sector?: string | null;
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

export interface StockRecommendation {
  code: string;
  name: string;
  region: MarketRegion;
  sector: string | null;
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

export interface PrioritySummary {
  buyNow: number;
  position: number;
  waitPullback: number;
  noEntry: number;
}

export type RecommendationListFilters = RecommendationFilters;
export type RecommendationSummary = PrioritySummary;

export interface RecommendationListResponse {
  items: RecommendationItem[];
  total: number;
  filters: RecommendationFilters;
}

export interface RecommendationListParams extends RecommendationFilters {
  limit?: number;
  offset?: number;
}

export interface RecommendationRefreshRequest {
  market: MarketRegion | string;
  region?: MarketRegion | string;
  sector: string;
  force?: boolean;
  forceRefresh?: boolean;
  stockCodes?: string[];
}

export interface RecommendationRefreshResponse {
  items: RecommendationItem[];
  total: number;
  filters: Record<string, unknown>;
}
