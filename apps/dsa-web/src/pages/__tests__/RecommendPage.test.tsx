import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import RecommendPage from '../RecommendPage';

const navigateMock = vi.fn();
const mockStoreState = vi.hoisted(() => ({
  recommendations: [] as Array<Record<string, unknown>>,
  summary: null,
  filters: {},
  loading: false,
  error: null,
  hotSectors: [] as Array<Record<string, unknown>>,
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
  fetchHotSectors: vi.fn().mockResolvedValue(undefined),
  triggerRefresh: vi.fn().mockResolvedValue(undefined),
  setFilter: vi.fn(),
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
      filters: {},
      loading: false,
      error: null,
      hotSectors: [],
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
    });
  });

  it('opens live recommendation detail through recommendationStore action', async () => {
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
});
