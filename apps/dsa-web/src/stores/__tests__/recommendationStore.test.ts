import { beforeEach, describe, expect, it, vi } from 'vitest';
import { recommendationApi } from '../../api/recommendation';
import type { RecommendationHistoryItem } from '../../api/recommendation';
import type { AnalysisReport } from '../../types/analysis';
import type { RecommendationItem } from '../../types/recommendation';
import { useRecommendationStore } from '../recommendationStore';

vi.mock('../../api/recommendation', async () => {
  const actual = await vi.importActual<typeof import('../../api/recommendation')>('../../api/recommendation');
  return {
    ...actual,
    recommendationApi: {
      ...actual.recommendationApi,
      getRecommendations: vi.fn(),
      getHotSectors: vi.fn(),
      getHistory: vi.fn(),
      getSummary: vi.fn(),
      triggerRefresh: vi.fn(),
      deleteHistoryByIds: vi.fn(),
      getDetailByLink: vi.fn(),
    },
  };
});

const resetStore = () => {
  useRecommendationStore.setState({
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
    filters: {},
    detailOpen: false,
    detailLoading: false,
    detailError: null,
    detailRecommendation: null,
    detailAnalysis: null,
  });
};

const linkedAnalysisDetail: AnalysisReport = {
  meta: {
    id: 23,
    queryId: 'hist-23',
    stockCode: '600519',
    stockName: 'Moutai',
    reportType: 'full',
    createdAt: '2026-03-21T08:00:00Z',
  },
  summary: {
    analysisSummary: 'Detail from linked analysis record',
    operationAdvice: 'Hold',
    trendPrediction: 'Bullish',
    sentimentScore: 72,
  },
};

describe('recommendationStore', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetStore();
  });

  it('opens history detail via recommendation-owned detail lookup', async () => {
    const historyItem = {
      id: 7,
      analysisRecordId: 23,
      code: '600519',
      name: 'Moutai',
      sector: 'Liquor',
      compositeScore: 77,
      priority: 'POSITION',
      recommendationDate: '2026-03-21',
      updatedAt: '2026-03-21T08:00:00Z',
      market: 'CN',
      region: 'CN',
      aiSummary: 'Wait for pullback.',
    };

    vi.mocked(recommendationApi.getDetailByLink).mockResolvedValue({
      recommendation: historyItem,
      analysisDetail: linkedAnalysisDetail,
    });

    await useRecommendationStore.getState().openHistoryDetail(historyItem);

    const state = useRecommendationStore.getState();
    expect(recommendationApi.getDetailByLink).toHaveBeenCalledWith({
      recommendationRecordId: 7,
      analysisRecordId: 23,
      fallbackRecommendation: historyItem,
    });
    expect(state.detailOpen).toBe(true);
    expect(state.detailLoading).toBe(false);
    expect(state.detailError).toBeNull();
    expect(state.detailRecommendation?.id).toBe(7);
    expect(state.detailAnalysis?.meta.id).toBe(23);
  });

  it('uses analysisRecordId flow for live detail when recommendation id is missing', async () => {
    const liveItem: RecommendationItem = {
      recommendationRecordId: null,
      stockCode: 'AAPL',
      name: 'Apple',
      stockName: 'Apple',
      market: 'US',
      region: 'US',
      analysisRecordId: 12,
      sector: 'Tech',
      scores: {},
      compositeScore: 88,
      priority: 'BUY_NOW',
      aiSummary: 'Momentum remains strong.',
      updatedAt: '2026-03-21T08:00:00Z',
    };

    vi.mocked(recommendationApi.getDetailByLink).mockResolvedValue({
      recommendation: {},
      analysisDetail: {
        ...linkedAnalysisDetail,
        meta: {
          ...linkedAnalysisDetail.meta,
          id: 12,
          queryId: 'hist-12',
          stockCode: 'AAPL',
          stockName: 'Apple',
        },
      },
    });

    await useRecommendationStore.getState().openLiveDetail(liveItem);

    const state = useRecommendationStore.getState();
    expect(recommendationApi.getDetailByLink).toHaveBeenCalledWith(
      expect.objectContaining({
        recommendationRecordId: null,
        analysisRecordId: 12,
      }),
    );
    expect(state.detailOpen).toBe(true);
    expect(state.detailLoading).toBe(false);
    expect(state.detailRecommendation?.code).toBe('AAPL');
    expect(state.detailAnalysis?.meta.id).toBe(12);
  });

  it('keeps metadata-only fallback when live recommendation has no linked records', async () => {
    const liveItem: RecommendationItem = {
      stockCode: 'TSLA',
      name: 'Tesla',
      stockName: 'Tesla',
      market: 'US',
      region: 'US',
      analysisRecordId: null,
      sector: 'Auto',
      scores: {},
      compositeScore: 70,
      priority: 'WAIT_PULLBACK',
      aiSummary: 'Need confirmation.',
      updatedAt: '2026-03-21T08:00:00Z',
    };

    await useRecommendationStore.getState().openLiveDetail(liveItem);

    const state = useRecommendationStore.getState();
    expect(recommendationApi.getDetailByLink).not.toHaveBeenCalled();
    expect(state.detailOpen).toBe(true);
    expect(state.detailLoading).toBe(false);
    expect(state.detailError).toBeNull();
    expect(state.detailRecommendation?.code).toBe('TSLA');
    expect(state.detailAnalysis).toBeNull();
  });

  it('closes detail state after deleting currently opened recommendation record', async () => {
    useRecommendationStore.setState({
      historyList: [
        {
          id: 7,
          analysisRecordId: 23,
          code: '600519',
          name: 'Moutai',
          sector: 'Liquor',
          compositeScore: 77,
          priority: 'POSITION',
          recommendationDate: '2026-03-21',
          updatedAt: '2026-03-21T08:00:00Z',
          market: 'CN',
          region: 'CN',
        },
      ],
      historyTotal: 1,
      detailOpen: true,
      detailLoading: false,
      detailError: null,
      detailRecommendation: {
        id: 7,
        analysisRecordId: 23,
        code: '600519',
        name: 'Moutai',
        sector: 'Liquor',
        compositeScore: 77,
        priority: 'POSITION',
        recommendationDate: '2026-03-21',
        updatedAt: '2026-03-21T08:00:00Z',
        market: 'CN',
        region: 'CN',
      },
      detailAnalysis: linkedAnalysisDetail,
    });
    vi.mocked(recommendationApi.deleteHistoryByIds).mockResolvedValue({ status: 'ok', deleted: 1 });

    await useRecommendationStore.getState().deleteHistoryByIds([7]);

    const state = useRecommendationStore.getState();
    expect(state.detailOpen).toBe(false);
    expect(state.detailRecommendation).toBeNull();
    expect(state.detailAnalysis).toBeNull();
  });

  it('handles API error when fetching detail via recommendation-owned detail lookup', async () => {
    const historyItem: RecommendationHistoryItem = {
      id: 8,
      code: '000001',
      name: 'Ping An',
    };

    vi.mocked(recommendationApi.getDetailByLink).mockRejectedValue(new Error('Network Error'));

    await useRecommendationStore.getState().openHistoryDetail(historyItem);

    const state = useRecommendationStore.getState();
    expect(state.detailOpen).toBe(true);
    expect(state.detailLoading).toBe(false);
    expect(state.detailError).toContain('浏览器当前无法连接');
    expect(state.detailRecommendation?.code).toBe('000001');
    expect(state.detailAnalysis).toBeNull();
  });

  it('uses recommendationRecordId flow for live detail when present', async () => {
    const liveItem: RecommendationItem = {
      recommendationRecordId: 15,
      stockCode: 'MSFT',
      name: 'Microsoft',
      stockName: 'Microsoft',
      market: 'US',
      region: 'US',
      analysisRecordId: null,
      sector: 'Tech',
      scores: {},
      compositeScore: 90,
      priority: 'BUY_NOW',
      updatedAt: '2026-03-21T08:00:00Z',
    };

    vi.mocked(recommendationApi.getDetailByLink).mockResolvedValue({
      recommendation: { id: 15, code: 'MSFT', name: 'Microsoft' },
      analysisDetail: null,
    });

    await useRecommendationStore.getState().openLiveDetail(liveItem);

    const state = useRecommendationStore.getState();
    expect(recommendationApi.getDetailByLink).toHaveBeenCalledWith(
      expect.objectContaining({
        recommendationRecordId: 15,
        analysisRecordId: null,
      }),
    );
    expect(state.detailOpen).toBe(true);
    expect(state.detailLoading).toBe(false);
    expect(state.detailRecommendation?.id).toBe(15);
  });

  it('does not close detail if a different record is deleted', async () => {
    useRecommendationStore.setState({
      historyList: [
        { id: 7, code: '600519', name: 'Moutai' },
        { id: 8, code: '000001', name: 'Ping An' },
      ] as RecommendationHistoryItem[],
      historyTotal: 2,
      detailOpen: true,
      detailRecommendation: { id: 7, code: '600519', name: 'Moutai' } as RecommendationHistoryItem,
    });
    vi.mocked(recommendationApi.deleteHistoryByIds).mockResolvedValue({ status: 'ok', deleted: 1 });

    await useRecommendationStore.getState().deleteHistoryByIds([8]);

    const state = useRecommendationStore.getState();
    expect(state.detailOpen).toBe(true);
    expect(state.detailRecommendation?.id).toBe(7);
    expect(state.historyTotal).toBe(1);
    expect(state.historyList.length).toBe(1);
    expect(state.historyList[0].id).toBe(7);
  });

  it('closeDetail resets recommendation detail slice', () => {
    useRecommendationStore.setState({
      detailOpen: true,
      detailLoading: true,
      detailError: 'failed',
      detailRecommendation: {
        id: 99,
        code: 'MSFT',
        name: 'Microsoft',
      },
      detailAnalysis: linkedAnalysisDetail,
    });

    useRecommendationStore.getState().closeDetail();

    const state = useRecommendationStore.getState();
    expect(state.detailOpen).toBe(false);
    expect(state.detailLoading).toBe(false);
    expect(state.detailError).toBeNull();
    expect(state.detailRecommendation).toBeNull();
    expect(state.detailAnalysis).toBeNull();
  });
});
