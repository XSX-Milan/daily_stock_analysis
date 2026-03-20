import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { RecommendationHistory } from '../RecommendationHistory';

const items = [
  {
    id: 1,
    queryId: 'rec_600519_20260319_1',
    code: '600519',
    name: '贵州茅台',
    sector: '白酒',
    compositeScore: 88,
    priority: 'BUY_NOW',
    recommendationDate: '2026-03-19',
    updatedAt: '2026-03-19T10:00:00',
    aiSummary: '维持强势趋势',
    market: 'CN',
    region: 'CN',
  },
];

describe('RecommendationHistory', () => {
  it('opens detail when clicking a history item', () => {
    const onOpenDetail = vi.fn();

    render(
      <RecommendationHistory
        items={items}
        loading={false}
        total={1}
        limit={50}
        offset={0}
        selectedIds={new Set()}
        onMarketChange={vi.fn()}
        onPageChange={vi.fn()}
        onOpenDetail={onOpenDetail}
        onToggleItemSelection={vi.fn()}
        onToggleSelectAll={vi.fn()}
        onDeleteItem={vi.fn().mockResolvedValue(undefined)}
        onDeleteSelected={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /贵州茅台/i }));
    expect(onOpenDetail).toHaveBeenCalledWith(items[0]);
  });

  it('supports select-all and batch delete confirmation', async () => {
    const onToggleSelectAll = vi.fn();
    const onDeleteSelected = vi.fn().mockResolvedValue(undefined);
    const batchItems = [
      ...items,
      {
        ...items[0],
        id: 2,
        code: '000001',
        name: '平安银行',
        queryId: 'rec_000001_20260319_2',
      },
    ];

    render(
      <RecommendationHistory
        items={batchItems}
        loading={false}
        total={2}
        limit={50}
        offset={0}
        selectedIds={new Set([1, 2])}
        onMarketChange={vi.fn()}
        onPageChange={vi.fn()}
        onOpenDetail={vi.fn()}
        onToggleItemSelection={vi.fn()}
        onToggleSelectAll={onToggleSelectAll}
        onDeleteItem={vi.fn().mockResolvedValue(undefined)}
        onDeleteSelected={onDeleteSelected}
      />,
    );

    fireEvent.click(screen.getByLabelText('全选当前推荐历史'));
    expect(onToggleSelectAll).toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: '批量删除' }));
    fireEvent.click(screen.getByRole('button', { name: '确认删除' }));

    await waitFor(() => {
      expect(onDeleteSelected).toHaveBeenCalled();
    });
  });

  it('supports deleting a single history row by record id', async () => {
    const onDeleteItem = vi.fn().mockResolvedValue(undefined);

    render(
      <RecommendationHistory
        items={items}
        loading={false}
        total={1}
        limit={50}
        offset={0}
        selectedIds={new Set()}
        onMarketChange={vi.fn()}
        onPageChange={vi.fn()}
        onOpenDetail={vi.fn()}
        onToggleItemSelection={vi.fn()}
        onToggleSelectAll={vi.fn()}
        onDeleteItem={onDeleteItem}
        onDeleteSelected={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    fireEvent.click(screen.getByTitle('删除记录'));
    fireEvent.click(screen.getByRole('button', { name: '确认删除' }));

    await waitFor(() => {
      expect(onDeleteItem).toHaveBeenCalledWith(1);
    });
  });
});
