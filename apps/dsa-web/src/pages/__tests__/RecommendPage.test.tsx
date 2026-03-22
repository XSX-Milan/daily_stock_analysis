import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import RecommendPage from '../RecommendPage';

const navigateMock = vi.fn();
const mockStoreState = vi.hoisted(() => ({
  recommendations: [] as Array<Record<string, unknown>>,
  summary: null,
  filters: { market: 'CN' } as {
    market?: string;
    region?: string;
    priority?: string;
    sector?: string;
    sectors?: string[];
  },
  loading: false,
  error: null,
  hotSectors: [] as Array<Record<string, unknown>>,
  hotSectorsMarket: undefined as string | undefined,
  hotSectorsByMarket: {} as Record<string, Array<Record<string, unknown>>>,
  selectedSectorsByMarket: {} as Record<string, string[]>,
  historyList: [] as Array<Record<string, unknown>>,
  historyTotal: 0,
  historyLimit: 50,
  historyOffset: 0,
  historyMarket: undefined,
  detailOpen: false,
  detailLoading: false,
  detailError: null,
  detailRecommendation: null,
  detailAnalysis: null,
  fetchRecommendations: vi.fn().mockResolvedValue(undefined),
  fetchSummary: vi.fn().mockResolvedValue(undefined),
  fetchHotSectors: vi.fn().mockResolvedValue(true),
  triggerRefresh: vi.fn().mockResolvedValue(undefined),
  setFilter: vi.fn(),
  setSelectedSectorsForMarket: vi.fn((market: string, sectors: string[]) => {
    const normalizedMarket = String(market ?? '').trim().toUpperCase();
    if (!normalizedMarket) {
      return;
    }
    const normalizedSectors = Array.from(
      new Set(
        (Array.isArray(sectors) ? sectors : [])
          .map((sector) => String(sector ?? '').trim())
          .filter((sector) => sector.length > 0),
      ),
    );
    if (normalizedSectors.length === 0) {
      const nextSelectedSectorsByMarket = { ...mockStoreState.selectedSectorsByMarket };
      delete nextSelectedSectorsByMarket[normalizedMarket];
      mockStoreState.selectedSectorsByMarket = nextSelectedSectorsByMarket;
      return;
    }
    mockStoreState.selectedSectorsByMarket = {
      ...mockStoreState.selectedSectorsByMarket,
      [normalizedMarket]: normalizedSectors,
    };
  }),
  clearSelectedSectorsForMarket: vi.fn((market?: string) => {
    const normalizedMarket = String(market ?? '').trim().toUpperCase();
    if (!normalizedMarket) {
      mockStoreState.selectedSectorsByMarket = {};
      return;
    }
    const nextSelectedSectorsByMarket = { ...mockStoreState.selectedSectorsByMarket };
    delete nextSelectedSectorsByMarket[normalizedMarket];
    mockStoreState.selectedSectorsByMarket = nextSelectedSectorsByMarket;
  }),
  fetchHistory: vi.fn().mockResolvedValue(undefined),
  deleteHistoryByIds: vi.fn().mockResolvedValue(undefined),
  openHistoryDetail: vi.fn().mockResolvedValue(undefined),
  openLiveDetail: vi.fn().mockResolvedValue(undefined),
  closeDetail: vi.fn(),
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

vi.mock('../../stores/recommendationStore', () => ({
  useRecommendationStore: () => mockStoreState,
}));

vi.mock('../../components/report', () => ({
  ReportSummary: ({ data }: { data: { summary?: { analysisSummary?: string } } }) => (
    <div data-testid="report-summary">{data.summary?.analysisSummary}</div>
  ),
  ReportMarkdown: () => null,
}));

describe('RecommendPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    navigateMock.mockReset();
    Object.assign(mockStoreState, {
      recommendations: [],
      summary: null,
      filters: { market: 'CN' },
      loading: false,
      error: null,
      hotSectors: [],
      hotSectorsMarket: undefined,
      hotSectorsByMarket: {},
      selectedSectorsByMarket: {},
      historyList: [],
      historyTotal: 0,
      historyLimit: 50,
      historyOffset: 0,
      historyMarket: undefined,
      detailOpen: false,
      detailLoading: false,
      detailError: null,
      detailRecommendation: null,
      detailAnalysis: null,
      fetchRecommendations: vi.fn().mockResolvedValue(undefined),
      fetchSummary: vi.fn().mockResolvedValue(undefined),
      fetchHotSectors: vi.fn().mockResolvedValue(true),
      triggerRefresh: vi.fn().mockResolvedValue(undefined),
      setFilter: vi.fn(),
      fetchHistory: vi.fn().mockResolvedValue(undefined),
      deleteHistoryByIds: vi.fn().mockResolvedValue(undefined),
      openHistoryDetail: vi.fn().mockResolvedValue(undefined),
      openLiveDetail: vi.fn().mockResolvedValue(undefined),
      closeDetail: vi.fn(),
    });

    mockStoreState.setSelectedSectorsForMarket = vi.fn((market: string, sectors: string[]) => {
      const normalizedMarket = String(market ?? '').trim().toUpperCase();
      if (!normalizedMarket) {
        return;
      }
      const normalizedSectors = Array.from(
        new Set(
          (Array.isArray(sectors) ? sectors : [])
            .map((sector) => String(sector ?? '').trim())
            .filter((sector) => sector.length > 0),
        ),
      );
      if (normalizedSectors.length === 0) {
        const nextSelectedSectorsByMarket = { ...mockStoreState.selectedSectorsByMarket };
        delete nextSelectedSectorsByMarket[normalizedMarket];
        mockStoreState.selectedSectorsByMarket = nextSelectedSectorsByMarket;
        return;
      }
      mockStoreState.selectedSectorsByMarket = {
        ...mockStoreState.selectedSectorsByMarket,
        [normalizedMarket]: normalizedSectors,
      };
    });

    mockStoreState.clearSelectedSectorsForMarket = vi.fn((market?: string) => {
      const normalizedMarket = String(market ?? '').trim().toUpperCase();
      if (!normalizedMarket) {
        mockStoreState.selectedSectorsByMarket = {};
        return;
      }
      const nextSelectedSectorsByMarket = { ...mockStoreState.selectedSectorsByMarket };
      delete nextSelectedSectorsByMarket[normalizedMarket];
      mockStoreState.selectedSectorsByMarket = nextSelectedSectorsByMarket;
    });
  });

  it('opens live recommendation detail through recommendationStore action', async () => {
    mockStoreState.filters = { market: 'US' };
    mockStoreState.recommendations = [
      {
        stockCode: 'AAPL',
        stockName: 'Apple',
        name: 'Apple',
        market: 'US',
        region: 'US',
        analysisRecordId: 12,
        sector: 'Tech',
        scores: {},
        compositeScore: 88,
        priority: 'BUY_NOW',
        aiSummary: 'Momentum remains strong.',
        updatedAt: '2026-03-21T08:00:00Z',
      },
    ];

    render(
      <MemoryRouter>
        <RecommendPage />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByTestId('table-row-AAPL'));

    expect(mockStoreState.openLiveDetail).toHaveBeenCalledWith(
      expect.objectContaining({
        stockCode: 'AAPL',
        analysisRecordId: 12,
      }),
    );
    expect(navigateMock).not.toHaveBeenCalledWith(expect.stringContaining('/?stock='));
  });

  it('auto-fetches hot sectors on init when sector data is empty', async () => {
    mockStoreState.filters = {};
    mockStoreState.recommendations = [];
    mockStoreState.hotSectors = [];
    mockStoreState.hotSectorsMarket = undefined;
    mockStoreState.hotSectorsByMarket = {};

    render(
      <MemoryRouter>
        <RecommendPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(mockStoreState.fetchHotSectors).toHaveBeenCalledWith('CN');
    });
  });

  it('auto-fetches hot sectors when market cache is missing even with recommendation sectors', async () => {
    mockStoreState.filters = { market: 'US' };
    mockStoreState.recommendations = [
      {
        stockCode: 'AAPL',
        stockName: 'Apple',
        name: 'Apple',
        market: 'US',
        region: 'US',
        analysisRecordId: 12,
        sector: 'Tech',
        scores: {},
        compositeScore: 88,
        priority: 'BUY_NOW',
        aiSummary: 'Momentum remains strong.',
        updatedAt: '2026-03-21T08:00:00Z',
      },
    ];
    mockStoreState.hotSectors = [];
    mockStoreState.hotSectorsMarket = undefined;
    mockStoreState.hotSectorsByMarket = {};

    render(
      <MemoryRouter>
        <RecommendPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(mockStoreState.fetchHotSectors).toHaveBeenCalledWith('US');
    });
  });

  it('opens history recommendation detail through recommendationStore action', async () => {
    mockStoreState.historyList = [
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
        aiSummary: 'Wait for pullback.',
      },
    ];
    mockStoreState.historyTotal = 1;

    render(
      <MemoryRouter>
        <RecommendPage />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole('button', { name: '历史记录' }));

    fireEvent.click(await screen.findByText('Moutai'));

    expect(mockStoreState.openHistoryDetail).toHaveBeenCalledWith(
      expect.objectContaining({
        id: 7,
        analysisRecordId: 23,
        code: '600519',
      }),
    );
    expect(navigateMock).not.toHaveBeenCalledWith(expect.stringContaining('/?stock='));
  });

  it('keeps per-market hot sector cache when switching markets', async () => {
    mockStoreState.filters = { market: 'CN' };
    mockStoreState.recommendations = [];
    mockStoreState.hotSectors = [];
    mockStoreState.hotSectorsMarket = undefined;
    mockStoreState.hotSectorsByMarket = {};

    const { rerender } = render(
      <MemoryRouter>
        <RecommendPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(mockStoreState.fetchHotSectors).toHaveBeenCalledWith('CN');
    });

    mockStoreState.filters = { market: 'US' };
    mockStoreState.hotSectorsMarket = 'CN';
    mockStoreState.hotSectors = [{ name: '银行' }];
    mockStoreState.hotSectorsByMarket = {
      CN: [{ name: '银行' }],
    };

    rerender(
      <MemoryRouter>
        <RecommendPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(mockStoreState.fetchHotSectors).toHaveBeenCalledWith('US');
    });

    mockStoreState.filters = { market: 'CN' };
    mockStoreState.hotSectorsMarket = 'US';
    mockStoreState.hotSectors = [{ name: 'Technology' }];
    mockStoreState.hotSectorsByMarket = {
      CN: [{ name: '银行' }],
      US: [{ name: 'Technology' }],
    };

    rerender(
      <MemoryRouter>
        <RecommendPage />
      </MemoryRouter>,
    );

    expect(mockStoreState.fetchHotSectors).toHaveBeenCalledTimes(2);
  });

  it('auto-refetches once when cached market result is empty', async () => {
    mockStoreState.filters = { market: 'CN' };
    mockStoreState.recommendations = [];
    mockStoreState.hotSectors = [];
    mockStoreState.hotSectorsMarket = 'CN';
    mockStoreState.hotSectorsByMarket = {
      CN: [],
    };

    render(
      <MemoryRouter>
        <RecommendPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(mockStoreState.fetchRecommendations).toHaveBeenCalledTimes(1);
      expect(mockStoreState.fetchHotSectors).toHaveBeenCalledWith('CN');
    });
  });

  it('does not loop auto-fetch after one failed market fetch attempt', async () => {
    mockStoreState.filters = { market: 'CN' };
    mockStoreState.recommendations = [];
    mockStoreState.hotSectors = [];
    mockStoreState.hotSectorsMarket = undefined;
    mockStoreState.hotSectorsByMarket = {};
    mockStoreState.fetchHotSectors = vi.fn().mockResolvedValue(false);

    const { rerender } = render(
      <MemoryRouter>
        <RecommendPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(mockStoreState.fetchHotSectors).toHaveBeenCalledTimes(1);
    });

    rerender(
      <MemoryRouter>
        <RecommendPage />
      </MemoryRouter>,
    );

    expect(mockStoreState.fetchHotSectors).toHaveBeenCalledTimes(1);
  });

  it('renders sector tags from hot-sector cache when recommendation sectors are empty', async () => {
    mockStoreState.filters = { market: 'CN' };
    mockStoreState.recommendations = [
      {
        stockCode: '600519',
        stockName: 'Moutai',
        name: 'Moutai',
        market: 'CN',
        region: 'CN',
        analysisRecordId: 12,
        scores: {},
        compositeScore: 88,
        priority: 'BUY_NOW',
        aiSummary: 'Momentum remains strong.',
        updatedAt: '2026-03-21T08:00:00Z',
      },
    ];
    mockStoreState.hotSectors = [
      { name: '逆变器' },
      { name: '算力' },
    ];
    mockStoreState.hotSectorsMarket = 'CN';
    mockStoreState.hotSectorsByMarket = {
      CN: [{ name: '逆变器' }, { name: '算力' }],
    };

    render(
      <MemoryRouter>
        <RecommendPage />
      </MemoryRouter>,
    );

    expect(await screen.findByTestId('sector-tag-逆变器')).toBeInTheDocument();
    expect(screen.getByTestId('sector-tag-算力')).toBeInTheDocument();
    expect(screen.getByText('2 个板块')).toBeInTheDocument();
    await waitFor(() => {
      expect(mockStoreState.fetchHotSectors).toHaveBeenCalledWith('CN');
    });
  });

  it('paginates CN sector chips when hot-sector list is large', async () => {
    mockStoreState.filters = { market: 'CN' };
    mockStoreState.recommendations = [];
    const sectors = Array.from({ length: 30 }, (_, index) => {
      const rank = index + 1;
      return {
        name: `板块${String(rank).padStart(2, '0')}`,
        isHot: rank <= 3,
        hotRank: rank <= 3 ? rank : null,
      };
    });

    mockStoreState.hotSectors = sectors;
    mockStoreState.hotSectorsMarket = 'CN';
    mockStoreState.hotSectorsByMarket = {
      CN: sectors,
    };

    render(
      <MemoryRouter>
        <RecommendPage />
      </MemoryRouter>,
    );

    expect(await screen.findByTestId('sector-tag-板块01')).toBeInTheDocument();
    expect(screen.queryByTestId('sector-tag-板块30')).not.toBeInTheDocument();
    expect(screen.getByTestId('sector-filters-pagination')).toBeInTheDocument();
    expect(document.querySelectorAll('[data-testid^="sector-tag-"]').length).toBe(25);
  });

  it('restores selected sectors from market-scoped store state and keeps hidden chips visible', async () => {
    mockStoreState.filters = { market: 'US' };
    mockStoreState.recommendations = [
      {
        stockCode: 'AAPL',
        stockName: 'Apple',
        name: 'Apple',
        market: 'US',
        region: 'US',
        analysisRecordId: 12,
        sector: 'Technology',
        scores: {},
        compositeScore: 88,
        priority: 'BUY_NOW',
        aiSummary: 'Momentum remains strong.',
        updatedAt: '2026-03-21T08:00:00Z',
      },
    ];
    mockStoreState.hotSectors = [{ name: 'Technology' }];
    mockStoreState.hotSectorsMarket = 'US';
    mockStoreState.hotSectorsByMarket = {
      US: [{ name: 'Technology' }],
    };
    mockStoreState.selectedSectorsByMarket = {
      US: ['Communication Services'],
    };

    render(
      <MemoryRouter>
        <RecommendPage />
      </MemoryRouter>,
    );

    expect(await screen.findByTestId('sector-tag-Communication Services')).toBeInTheDocument();
    expect(screen.getByTestId('manual-refresh-button')).toHaveTextContent('推荐');
  });

  it('restores retained selections for the active market when switching markets', async () => {
    mockStoreState.filters = { market: 'US' };
    mockStoreState.recommendations = [
      {
        stockCode: 'AAPL',
        stockName: 'Apple',
        name: 'Apple',
        market: 'US',
        region: 'US',
        analysisRecordId: 12,
        sector: 'Technology',
        sectors: ['Technology'],
        sectorCanonicalKey: 'technology',
        scores: {},
        compositeScore: 88,
        priority: 'BUY_NOW',
        aiSummary: 'Momentum remains strong.',
        updatedAt: '2026-03-21T08:00:00Z',
      },
      {
        stockCode: '300750',
        stockName: 'CATL',
        name: 'CATL',
        market: 'CN',
        region: 'CN',
        analysisRecordId: 13,
        sector: '新能源',
        sectors: ['新能源'],
        scores: {},
        compositeScore: 86,
        priority: 'POSITION',
        aiSummary: 'Battery cycle remains constructive.',
        updatedAt: '2026-03-21T08:00:00Z',
      },
    ];
    mockStoreState.hotSectors = [{ name: 'Technology', canonicalKey: 'technology' }];
    mockStoreState.hotSectorsMarket = 'US';
    mockStoreState.hotSectorsByMarket = {
      US: [{ name: 'Technology', canonicalKey: 'technology' }],
      CN: [{ name: '新能源' }],
    };
    mockStoreState.selectedSectorsByMarket = {
      US: ['Technology'],
      CN: ['新能源'],
    };

    const { rerender } = render(
      <MemoryRouter>
        <RecommendPage />
      </MemoryRouter>,
    );

    expect(await screen.findByTestId('sector-tag-Technology')).toBeInTheDocument();
    expect(screen.queryByTestId('sector-tag-新能源')).not.toBeInTheDocument();
    expect(screen.getByTestId('manual-refresh-button')).toHaveTextContent('推荐');

    mockStoreState.filters = { market: 'CN' };
    mockStoreState.hotSectors = [{ name: '新能源' }];
    mockStoreState.hotSectorsMarket = 'CN';

    rerender(
      <MemoryRouter>
        <RecommendPage />
      </MemoryRouter>,
    );

    expect(await screen.findByTestId('sector-tag-新能源')).toBeInTheDocument();
    expect(screen.queryByTestId('sector-tag-Technology')).not.toBeInTheDocument();
    expect(screen.getByTestId('manual-refresh-button')).toHaveTextContent('推荐');

    mockStoreState.filters = { market: 'US' };
    mockStoreState.hotSectors = [{ name: 'Technology', canonicalKey: 'technology' }];
    mockStoreState.hotSectorsMarket = 'US';

    rerender(
      <MemoryRouter>
        <RecommendPage />
      </MemoryRouter>,
    );

    expect(await screen.findByTestId('sector-tag-Technology')).toBeInTheDocument();
    expect(screen.queryByTestId('sector-tag-新能源')).not.toBeInTheDocument();
  });

  it('applies OR filtering across selected sectors using canonical metadata', async () => {
    mockStoreState.filters = { market: 'US' };
    mockStoreState.recommendations = [
      {
        stockCode: 'AAPL',
        stockName: 'Apple',
        name: 'Apple',
        market: 'US',
        region: 'US',
        analysisRecordId: 12,
        sector: 'Technology',
        sectors: ['Technology'],
        sectorCanonicalKey: 'technology',
        scores: {},
        compositeScore: 88,
        priority: 'BUY_NOW',
        aiSummary: 'Momentum remains strong.',
        updatedAt: '2026-03-21T08:00:00Z',
      },
      {
        stockCode: 'META',
        stockName: 'Meta',
        name: 'Meta',
        market: 'US',
        region: 'US',
        analysisRecordId: 13,
        sector: 'Communication Services',
        sectors: ['Communication Services'],
        sectorCanonicalKey: 'communicationservices',
        sectorAliases: ['communication services'],
        scores: {},
        compositeScore: 86,
        priority: 'POSITION',
        aiSummary: 'Platform engagement stabilizing.',
        updatedAt: '2026-03-21T08:00:00Z',
      },
      {
        stockCode: 'JPM',
        stockName: 'JPMorgan',
        name: 'JPMorgan',
        market: 'US',
        region: 'US',
        analysisRecordId: 14,
        sector: 'Financials',
        sectors: ['Financials'],
        sectorCanonicalKey: 'financials',
        scores: {},
        compositeScore: 80,
        priority: 'WAIT_PULLBACK',
        aiSummary: 'Range-bound setup.',
        updatedAt: '2026-03-21T08:00:00Z',
      },
    ];
    mockStoreState.hotSectors = [
      { name: 'Technology', canonicalKey: 'technology' },
      { name: 'Communication Services', canonicalKey: 'communicationservices', aliases: ['communication services'] },
    ];
    mockStoreState.hotSectorsMarket = 'US';
    mockStoreState.hotSectorsByMarket = {
      US: [
        { name: 'Technology', canonicalKey: 'technology' },
        { name: 'Communication Services', canonicalKey: 'communicationservices', aliases: ['communication services'] },
      ],
    };
    mockStoreState.selectedSectorsByMarket = {
      US: ['Technology', 'communicationservices'],
    };

    render(
      <MemoryRouter>
        <RecommendPage />
      </MemoryRouter>,
    );

    expect(await screen.findByTestId('table-row-AAPL')).toBeInTheDocument();
    expect(screen.getByTestId('table-row-META')).toBeInTheDocument();
    expect(screen.queryByTestId('table-row-JPM')).not.toBeInTheDocument();
  });

  it('sends sectors[] during manual refresh when market has active selections', async () => {
    mockStoreState.filters = { market: 'US' };
    mockStoreState.selectedSectorsByMarket = {
      US: ['Technology', 'Semiconductors'],
    };

    render(
      <MemoryRouter>
        <RecommendPage />
      </MemoryRouter>,
    );

    const hotSectorsCallCountBeforeRefresh = mockStoreState.fetchHotSectors.mock.calls.length;

    fireEvent.click(screen.getByTestId('manual-refresh-button'));

    await waitFor(() => {
      expect(mockStoreState.triggerRefresh).toHaveBeenCalledWith({
        market: 'US',
        sector: 'Technology',
        sectors: ['Technology', 'Semiconductors'],
      });
    });
    expect(mockStoreState.fetchHotSectors).toHaveBeenCalledTimes(hotSectorsCallCountBeforeRefresh);
  });

  it('keeps smart refresh flow when no sectors are selected for market', async () => {
    mockStoreState.filters = { market: 'US' };
    mockStoreState.selectedSectorsByMarket = {};

    render(
      <MemoryRouter>
        <RecommendPage />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByTestId('manual-refresh-button'));

    await waitFor(() => {
      expect(mockStoreState.fetchHotSectors).toHaveBeenCalledWith('US');
      expect(mockStoreState.triggerRefresh).toHaveBeenCalledWith({ market: 'US' });
    });
  });

  it('updates store-managed market sector selection when toggling chips', async () => {
    mockStoreState.filters = { market: 'CN' };
    mockStoreState.recommendations = [];
    mockStoreState.hotSectors = [{ name: '逆变器' }, { name: '算力' }];
    mockStoreState.hotSectorsMarket = 'CN';
    mockStoreState.hotSectorsByMarket = {
      CN: [{ name: '逆变器' }, { name: '算力' }],
    };

    const { rerender } = render(
      <MemoryRouter>
        <RecommendPage />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByTestId('sector-tag-逆变器'));

    expect(mockStoreState.setSelectedSectorsForMarket).toHaveBeenCalledWith('CN', ['逆变器']);

    mockStoreState.selectedSectorsByMarket = {
      CN: ['逆变器'],
    };

    rerender(
      <MemoryRouter>
        <RecommendPage />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByTestId('sector-tag-算力'));

    expect(mockStoreState.setSelectedSectorsForMarket).toHaveBeenCalledWith('CN', ['逆变器', '算力']);

    mockStoreState.selectedSectorsByMarket = {
      CN: ['逆变器', '算力'],
    };

    rerender(
      <MemoryRouter>
        <RecommendPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('manual-refresh-button')).toHaveTextContent('推荐');
    });

    fireEvent.click(screen.getByTestId('sector-tag-逆变器'));

    expect(mockStoreState.setSelectedSectorsForMarket).toHaveBeenCalledWith('CN', ['算力']);
  });

  it('renders one visible chip for canonical aliases across hot sectors, recommendations, and selections', async () => {
    mockStoreState.filters = { market: 'US' };
    mockStoreState.recommendations = [
      {
        stockCode: 'META',
        stockName: 'Meta',
        name: 'Meta',
        market: 'US',
        region: 'US',
        analysisRecordId: 12,
        sector: 'Communication Services',
        sectors: ['Communication Services'],
        sectorCanonicalKey: 'communicationservices',
        sectorAliases: ['communication services', 'communications'],
        scores: {},
        compositeScore: 88,
        priority: 'BUY_NOW',
        aiSummary: 'Engagement remains resilient.',
        updatedAt: '2026-03-21T08:00:00Z',
      },
    ];
    mockStoreState.hotSectors = [
      {
        name: 'Communication Services',
        canonicalKey: 'communicationservices',
        displayLabel: 'Communication Services',
        aliases: ['communication services', 'communications'],
      },
    ];
    mockStoreState.hotSectorsMarket = 'US';
    mockStoreState.hotSectorsByMarket = {
      US: [
        {
          name: 'Communication Services',
          canonicalKey: 'communicationservices',
          displayLabel: 'Communication Services',
          aliases: ['communication services', 'communications'],
        },
      ],
    };
    mockStoreState.selectedSectorsByMarket = {
      US: ['communications'],
    };

    render(
      <MemoryRouter>
        <RecommendPage />
      </MemoryRouter>,
    );

    expect(await screen.findByTestId('sector-tag-Communication Services')).toBeInTheDocument();
    expect(screen.queryAllByTestId('sector-tag-Communication Services')).toHaveLength(1);
    expect(screen.queryByTestId('sector-tag-communications')).not.toBeInTheDocument();
  });

  it('removes the selected store canonical token instead of adding display label when chip clicked', async () => {
    mockStoreState.filters = { market: 'US' };
    mockStoreState.recommendations = [];
    mockStoreState.hotSectors = [
      { name: 'Communication Services', canonicalKey: 'communicationservices', aliases: ['communication services'] }
    ];
    mockStoreState.hotSectorsMarket = 'US';
    mockStoreState.hotSectorsByMarket = {
      US: [{ name: 'Communication Services', canonicalKey: 'communicationservices', aliases: ['communication services'] }],
    };
    
    mockStoreState.selectedSectorsByMarket = {
      US: ['communicationservices'],
    };

    const { rerender } = render(
      <MemoryRouter>
        <RecommendPage />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByTestId('sector-tag-Communication Services'));

    expect(mockStoreState.clearSelectedSectorsForMarket).toHaveBeenCalledWith('US');

    mockStoreState.selectedSectorsByMarket = {
      US: ['communicationservices', 'technology'],
    };

    rerender(
      <MemoryRouter>
        <RecommendPage />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByTestId('sector-tag-Communication Services'));
    expect(mockStoreState.setSelectedSectorsForMarket).toHaveBeenCalledWith('US', ['technology']);
  });
});
