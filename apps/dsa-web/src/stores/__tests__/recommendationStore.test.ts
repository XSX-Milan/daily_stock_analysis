import { beforeEach, describe, expect, it, vi } from 'vitest';
import { recommendationApi } from '../../api/recommendation';
import type { RecommendationHistoryItem } from '../../api/recommendation';
import type { AnalysisReport } from '../../types/analysis';
import type { RecommendationItem } from '../../types/recommendation';
import { useRecommendationStore } from '../recommendationStore';

const RECOMMENDATION_STORE_PERSIST_KEY = 'dsa-web-recommendation-store';

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
    filters: { market: 'CN' },
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
  beforeEach(async () => {
    vi.clearAllMocks();
    await useRecommendationStore.persist.clearStorage();
    localStorage.removeItem(RECOMMENDATION_STORE_PERSIST_KEY);
    resetStore();
  });

  it('resets filters to CN market by default', () => {
    useRecommendationStore.setState({
      filters: {
        market: 'US',
        priority: 'BUY_NOW',
      },
    });

    useRecommendationStore.getState().clearFilters();

    expect(useRecommendationStore.getState().filters).toEqual({ market: 'CN' });
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

  it('stores normalized market when fetching hot sectors succeeds', async () => {
    vi.mocked(recommendationApi.getHotSectors).mockResolvedValue({
      sectors: [
        {
          name: '科技',
          canonicalKey: 'technology',
          displayLabel: '科技',
          aliases: ['科技', 'Technology'],
          rawName: '科技板块',
          source: 'eastmoney',
          changePct: 1.2,
          stockCount: 18,
          snapshotAt: '2026-03-21T08:00:00Z',
          fetchedAt: '2026-03-21T08:05:00Z',
        },
      ],
    });

    const result = await useRecommendationStore.getState().fetchHotSectors(' cn ');

    const state = useRecommendationStore.getState();
    expect(result).toBe(true);
    expect(recommendationApi.getHotSectors).toHaveBeenCalledWith('CN');
    expect(state.hotSectorsMarket).toBe('CN');
    expect(state.hotSectors).toEqual([
      {
        name: '科技',
        canonicalKey: 'technology',
        displayLabel: '科技',
        aliases: ['科技', 'Technology'],
        rawName: '科技板块',
        source: 'eastmoney',
        changePct: 1.2,
        stockCount: 18,
        snapshotAt: '2026-03-21T08:00:00Z',
        fetchedAt: '2026-03-21T08:05:00Z',
      },
    ]);
    expect(state.hotSectorsByMarket.CN).toEqual([
      {
        name: '科技',
        canonicalKey: 'technology',
        displayLabel: '科技',
        aliases: ['科技', 'Technology'],
        rawName: '科技板块',
        source: 'eastmoney',
        changePct: 1.2,
        stockCount: 18,
        snapshotAt: '2026-03-21T08:00:00Z',
        fetchedAt: '2026-03-21T08:05:00Z',
      },
    ]);
    expect(state.hotSectorCacheMetaByMarket.CN).toEqual(
      expect.objectContaining({
        snapshotAt: '2026-03-21T08:00:00Z',
        fetchedAt: '2026-03-21T08:05:00Z',
      }),
    );
    expect(typeof state.hotSectorCacheMetaByMarket.CN.cachedAt).toBe('string');
  });

  it('returns false when fetching hot sectors without market', async () => {
    const result = await useRecommendationStore.getState().fetchHotSectors('');

    const state = useRecommendationStore.getState();
    expect(result).toBe(false);
    expect(recommendationApi.getHotSectors).not.toHaveBeenCalled();
    expect(state.hotSectorsMarket).toBeUndefined();
    expect(state.hotSectorsByMarket).toEqual({});
    expect(state.error).toBe('请先选择市场后再获取热门板块。');
  });

  it('drops stale region filter when refreshing recommendations with market', async () => {
    useRecommendationStore.setState({
      filters: {
        region: 'CN',
        priority: 'BUY_NOW',
      },
    });
    vi.mocked(recommendationApi.triggerRefresh).mockResolvedValue({
      items: [],
      total: 0,
      filters: {},
    });
    vi.mocked(recommendationApi.getRecommendations).mockResolvedValue({
      items: [],
      total: 0,
      filters: {},
    });
    vi.mocked(recommendationApi.getSummary).mockResolvedValue({
      buyNow: 0,
      position: 0,
      waitPullback: 0,
      noEntry: 0,
    });

    await useRecommendationStore.getState().triggerRefresh({
      market: 'US',
      sector: 'Technology',
    });

    const refreshFilters = vi.mocked(recommendationApi.getRecommendations).mock.calls[0]?.[0];
    expect(refreshFilters).toBeDefined();
    expect(refreshFilters?.market).toBe('US');
    expect('region' in (refreshFilters ?? {})).toBe(false);
  });

  it('rehydrates selected sectors and hot-sector cache by market from persisted store', async () => {
    useRecommendationStore.getState().setSelectedSectorsForMarket('cn', ['科技', '新能源']);
    useRecommendationStore.getState().setSelectedSectorsForMarket('us', ['Technology']);
    useRecommendationStore.setState({
      hotSectorsByMarket: {
        CN: [
          {
            name: '科技',
            canonicalKey: 'technology',
            displayLabel: '科技',
            aliases: ['科技', 'Technology'],
            rawName: '科技板块',
            source: 'eastmoney',
            changePct: 1.5,
            stockCount: 20,
            snapshotAt: '2026-03-21T08:00:00Z',
            fetchedAt: '2026-03-21T08:05:00Z',
          },
        ],
        US: [
          {
            name: 'Technology',
            canonicalKey: 'technology',
            displayLabel: 'Technology',
            aliases: ['Technology', 'tech'],
            rawName: 'technology',
            source: 'yfinance',
            changePct: 2.1,
            stockCount: 24,
            snapshotAt: '2026-03-21T10:00:00Z',
            fetchedAt: '2026-03-21T10:03:00Z',
          },
        ],
      },
      hotSectorCacheMetaByMarket: {
        CN: {
          snapshotAt: '2026-03-21T08:00:00Z',
          fetchedAt: '2026-03-21T08:05:00Z',
          cachedAt: '2026-03-21T08:05:10Z',
        },
        US: {
          snapshotAt: '2026-03-21T10:00:00Z',
          fetchedAt: '2026-03-21T10:03:00Z',
          cachedAt: '2026-03-21T10:03:10Z',
        },
      },
    });

    const persistedSnapshot = localStorage.getItem(RECOMMENDATION_STORE_PERSIST_KEY);
    expect(persistedSnapshot).toBeTruthy();

    resetStore();
    localStorage.setItem(RECOMMENDATION_STORE_PERSIST_KEY, persistedSnapshot ?? '');
    await useRecommendationStore.persist.rehydrate();

    const state = useRecommendationStore.getState();
    expect(state.selectedSectorsByMarket.CN).toEqual(['科技', '新能源']);
    expect(state.selectedSectorsByMarket.US).toEqual(['Technology']);
    expect(state.hotSectorsByMarket.CN).toEqual([
      expect.objectContaining({
        name: '科技',
        canonicalKey: 'technology',
      }),
    ]);
    expect(state.hotSectorsByMarket.US).toEqual([
      expect.objectContaining({
        name: 'Technology',
        canonicalKey: 'technology',
      }),
    ]);
    expect(state.hotSectorCacheMetaByMarket.CN).toEqual(
      expect.objectContaining({
        snapshotAt: '2026-03-21T08:00:00Z',
        fetchedAt: '2026-03-21T08:05:00Z',
      }),
    );
    expect(state.hotSectorCacheMetaByMarket.US).toEqual(
      expect.objectContaining({
        snapshotAt: '2026-03-21T10:00:00Z',
        fetchedAt: '2026-03-21T10:03:00Z',
      }),
    );
  });

  it('keeps fresher in-memory hot-sector snapshot when persisted cache is stale', async () => {
    useRecommendationStore.setState({
      hotSectorsByMarket: {
        CN: [
          {
            name: '科技',
            canonicalKey: 'technology',
            displayLabel: '科技',
            aliases: ['科技', 'Technology'],
            rawName: '科技板块',
            source: 'eastmoney',
            changePct: 2.3,
            stockCount: 30,
            snapshotAt: '2026-03-22T09:00:00Z',
            fetchedAt: '2026-03-22T09:01:00Z',
          },
        ],
      },
      hotSectorCacheMetaByMarket: {
        CN: {
          snapshotAt: '2026-03-22T09:00:00Z',
          fetchedAt: '2026-03-22T09:01:00Z',
          cachedAt: '2026-03-22T09:01:05Z',
        },
      },
    });

    localStorage.setItem(
      RECOMMENDATION_STORE_PERSIST_KEY,
      JSON.stringify({
        state: {
          selectedSectorsByMarket: {
            CN: ['旧板块'],
          },
          hotSectorsByMarket: {
            CN: [
              {
                name: '旧科技',
                canonicalKey: 'technology',
                displayLabel: '旧科技',
                aliases: ['旧科技'],
                rawName: '旧科技',
                source: 'legacy-cache',
                changePct: 0.2,
                stockCount: 9,
                snapshotAt: '2026-03-20T09:00:00Z',
                fetchedAt: '2026-03-20T09:01:00Z',
              },
            ],
          },
          hotSectorCacheMetaByMarket: {
            CN: {
              snapshotAt: '2026-03-20T09:00:00Z',
              fetchedAt: '2026-03-20T09:01:00Z',
              cachedAt: '2026-03-20T09:01:05Z',
            },
          },
        },
        version: 1,
      }),
    );

    await useRecommendationStore.persist.rehydrate();

    const state = useRecommendationStore.getState();
    expect(state.hotSectorsByMarket.CN).toEqual([
      expect.objectContaining({
        name: '科技',
        snapshotAt: '2026-03-22T09:00:00Z',
      }),
    ]);
    expect(state.hotSectorCacheMetaByMarket.CN.snapshotAt).toBe('2026-03-22T09:00:00Z');
    expect(state.selectedSectorsByMarket.CN).toEqual(['旧板块']);
  });

  it('normalizes triggerRefresh sectors[] and clears stale single-sector filter state', async () => {
    useRecommendationStore.setState({
      filters: {
        market: 'US',
        region: 'US',
        priority: 'BUY_NOW',
        sector: 'OldSector',
        sectors: ['OldSector'],
      },
    });
    vi.mocked(recommendationApi.triggerRefresh).mockResolvedValue({
      items: [],
      total: 0,
      filters: {},
    });
    vi.mocked(recommendationApi.getRecommendations).mockResolvedValue({
      items: [],
      total: 0,
      filters: {},
    });
    vi.mocked(recommendationApi.getSummary).mockResolvedValue({
      buyNow: 0,
      position: 0,
      waitPullback: 0,
      noEntry: 0,
    });

    await useRecommendationStore.getState().triggerRefresh({
      market: ' us ',
      sectors: ['Technology', 'Finance', 'Technology'],
    });

    expect(recommendationApi.triggerRefresh).toHaveBeenCalledWith(
      expect.objectContaining({
        market: 'US',
        sector: 'Technology',
        sectors: ['Technology', 'Finance'],
      }),
    );

    await vi.waitFor(() => {
      const refreshedFilters = vi.mocked(recommendationApi.getRecommendations).mock.calls[0]?.[0];
      expect(refreshedFilters).toEqual(
        expect.objectContaining({
          market: 'US',
          sector: 'Technology',
          sectors: ['Technology', 'Finance'],
        }),
      );
      expect('region' in (refreshedFilters ?? {})).toBe(false);
      expect(useRecommendationStore.getState().selectedSectorsByMarket.US).toEqual(['Technology', 'Finance']);
      expect(useRecommendationStore.getState().filters).toEqual(
        expect.objectContaining({
          market: 'US',
          priority: 'BUY_NOW',
          sector: 'Technology',
          sectors: ['Technology', 'Finance'],
        }),
      );
    });

    vi.mocked(recommendationApi.getRecommendations).mockClear();

    await useRecommendationStore.getState().triggerRefresh({ market: 'US' });

    await vi.waitFor(() => {
      const refreshFilters = vi.mocked(recommendationApi.getRecommendations).mock.calls[0]?.[0] as
        | Record<string, unknown>
        | undefined;
      expect(refreshFilters?.market).toBe('US');
      expect(refreshFilters).toBeDefined();
      expect('sector' in (refreshFilters ?? {})).toBe(false);
      expect('sectors' in (refreshFilters ?? {})).toBe(false);
      expect(useRecommendationStore.getState().selectedSectorsByMarket.US).toBeUndefined();
      expect('sector' in useRecommendationStore.getState().filters).toBe(false);
      expect('sectors' in useRecommendationStore.getState().filters).toBe(false);
    });
  });

  it('clears only the active market sector selection when refresh scope is removed', async () => {
    useRecommendationStore.setState({
      filters: {
        market: 'US',
        region: 'US',
        sector: 'Technology',
        sectors: ['Technology'],
      },
      selectedSectorsByMarket: {
        CN: ['科技'],
        US: ['Technology'],
      },
    });
    vi.mocked(recommendationApi.triggerRefresh).mockResolvedValue({
      items: [],
      total: 0,
      filters: {},
    });
    vi.mocked(recommendationApi.getRecommendations).mockResolvedValue({
      items: [],
      total: 0,
      filters: {},
    });
    vi.mocked(recommendationApi.getSummary).mockResolvedValue({
      buyNow: 0,
      position: 0,
      waitPullback: 0,
      noEntry: 0,
    });

    await useRecommendationStore.getState().triggerRefresh({ market: 'US' });

    await vi.waitFor(() => {
      const refreshFilters = vi.mocked(recommendationApi.getRecommendations).mock.calls[0]?.[0] as
        | Record<string, unknown>
        | undefined;
      expect(refreshFilters?.market).toBe('US');
      expect('sector' in (refreshFilters ?? {})).toBe(false);
      expect('sectors' in (refreshFilters ?? {})).toBe(false);
      expect(useRecommendationStore.getState().selectedSectorsByMarket.CN).toEqual(['科技']);
      expect(useRecommendationStore.getState().selectedSectorsByMarket.US).toBeUndefined();
    });
  });
});
