import type React from 'react';
import { useMemo, useState } from 'react';
import type { RecommendationItem, RecommendationHotSector } from '../../types/recommendation';
import { Pagination } from '../common/Pagination';

export interface SectorFiltersProps {
  recommendations: RecommendationItem[];
  selectedSectors: string[];
  onSectorToggle: (sector: string | string[]) => void;
  onClearAll: () => void;
  hotSectors?: RecommendationHotSector[];
  enablePagination?: boolean;
  pageSize?: number;
}

type Group = {
  key: string;
  display: string;
  isHot: boolean;
  hotRank: number | null;
  isSelected: boolean;
  activeTokens: string[];
};

export const SectorFilters: React.FC<SectorFiltersProps> = ({
  recommendations,
  selectedSectors,
  onSectorToggle,
  onClearAll,
  hotSectors = [],
  enablePagination = false,
  pageSize = 20,
}) => {
  const [currentPage, setCurrentPage] = useState(1);

  const { groups } = useMemo(() => {
    const canonicalMap = new Map<string, Group>();
    const aliasToKey = new Map<string, string>();

    const addGroup = (
      primaryKey: string,
      display: string,
      aliases: string[],
      isHot: boolean,
      hotRank: number | null
    ) => {
      const pKeyLower = primaryKey.toLowerCase().replace(/\s+/g, '');
      let keyToUse = aliasToKey.get(pKeyLower) || primaryKey.toLowerCase().trim();

      const allTokens = [
        primaryKey,
        display,
        ...aliases
      ]
        .map(t => t?.trim())
        .filter(Boolean);

      for (const token of allTokens) {
        const compact = token.toLowerCase().replace(/\s+/g, '');
        if (aliasToKey.has(compact)) {
          keyToUse = aliasToKey.get(compact)!;
          break;
        }
      }

      for (const token of allTokens) {
        const compact = token.toLowerCase().replace(/\s+/g, '');
        aliasToKey.set(compact, keyToUse);
      }

      const existing = canonicalMap.get(keyToUse);
      if (existing) {
        if (isHot && !existing.isHot) {
          existing.display = display;
        }
        existing.isHot = existing.isHot || isHot;
        const existingHotRank = existing.hotRank;
        if (existingHotRank === null && hotRank !== null) {
          existing.hotRank = hotRank;
        } else if (existingHotRank !== null && hotRank !== null && hotRank < existingHotRank) {
          existing.hotRank = hotRank;
        }
      } else {
        canonicalMap.set(keyToUse, {
          key: keyToUse,
          display,
          isHot,
          hotRank,
          isSelected: false,
          activeTokens: [],
        });
      }
    };

    hotSectors.forEach((hs) => {
      const name = hs.name?.trim();
      if (!name) return;
      const primaryKey = hs.canonicalKey?.trim() || name;
      const display = hs.displayLabel?.trim() || name;
      const isHot = typeof hs.isHot === 'boolean' ? hs.isHot : true;
      const hotRank =
        typeof hs.hotRank === 'number' && Number.isFinite(hs.hotRank) && hs.hotRank > 0
          ? hs.hotRank
          : null;
      addGroup(primaryKey, display, hs.aliases || [], isHot, hotRank);
    });

    recommendations.forEach((item) => {
      const itemSectors: string[] = [];
      if (item.sector?.trim()) itemSectors.push(item.sector.trim());
      if (Array.isArray(item.sectors)) {
        item.sectors.forEach(s => {
          if (typeof s === 'string' && s.trim()) itemSectors.push(s.trim());
        });
      }

      if (itemSectors.length > 0) {
        const primaryKey = item.sectorCanonicalKey?.trim() || itemSectors[0];
        const display = item.sectorDisplayLabel?.trim() || itemSectors[0];
        const aliases = [...itemSectors, ...(item.sectorAliases || [])];
        addGroup(primaryKey, display, aliases, false, null);
      }
    });

    selectedSectors.forEach((s) => {
      const val = s?.trim();
      if (!val) return;
      addGroup(val, val, [], false, null);
    });

    selectedSectors.forEach((s) => {
      const val = s?.trim();
      if (!val) return;
      const compact = val.toLowerCase().replace(/\s+/g, '');
      const key = aliasToKey.get(compact);
      if (key) {
        const group = canonicalMap.get(key);
        if (group) {
          group.isSelected = true;
          group.activeTokens.push(val);
        }
      }
    });

    return { groups: Array.from(canonicalMap.values()) };
  }, [recommendations, hotSectors, selectedSectors]);

  const sortedGroups = useMemo(() => {
    return [...groups].sort((a, b) => {
      const aSelected = a.isSelected ? 1 : 0;
      const bSelected = b.isSelected ? 1 : 0;
      if (aSelected !== bSelected) return bSelected - aSelected;

      const aHot = a.isHot ? 1 : 0;
      const bHot = b.isHot ? 1 : 0;
      if (aHot !== bHot) return bHot - aHot;

      if (a.isHot && b.isHot) {
        const aRank = a.hotRank ?? Number.MAX_SAFE_INTEGER;
        const bRank = b.hotRank ?? Number.MAX_SAFE_INTEGER;
        if (aRank !== bRank) {
          return aRank - bRank;
        }
      }

      return a.display.localeCompare(b.display, 'zh-CN');
    });
  }, [groups]);

  const normalizedPageSize = Math.max(1, pageSize);
  const totalPages = enablePagination ? Math.max(1, Math.ceil(sortedGroups.length / normalizedPageSize)) : 1;

  const effectiveCurrentPage = Math.min(currentPage, totalPages);

  const visibleGroups = useMemo(() => {
    if (!enablePagination) {
      return sortedGroups;
    }

    const start = (effectiveCurrentPage - 1) * normalizedPageSize;
    return sortedGroups.slice(start, start + normalizedPageSize);
  }, [effectiveCurrentPage, enablePagination, normalizedPageSize, sortedGroups]);

  const sectorCount = sortedGroups.length;
  const totalCount = sectorCount;

  return (
    <div className="flex flex-col gap-2" data-testid="sector-filters">
      <div className="flex items-center justify-between">
        <h3 className="text-[11px] uppercase tracking-[0.2em] font-semibold text-purple-400">
          板块过滤
        </h3>
        <span className="text-xs text-secondary">
          {sectorCount} 个板块
        </span>
      </div>
      
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={onClearAll}
          className={`inline-flex items-center px-3 py-1.5 rounded border text-xs transition-colors ${
            selectedSectors.length === 0
              ? 'bg-cyan/15 text-cyan border-cyan/50 shadow-[0_0_10px_rgba(0,212,255,0.2)]'
              : 'bg-white/5 text-secondary border-white/10 hover:bg-white/10 hover:text-white'
          }`}
          data-testid="sector-tag-All"
        >
          全部 ({totalCount})
        </button>
        
        {visibleGroups.map((group) => {
          return (
            <button
              key={group.key}
              type="button"
              onClick={() => {
                if (group.isSelected && group.activeTokens.length > 0) {
                  onSectorToggle(group.activeTokens);
                } else {
                  onSectorToggle(group.display);
                }
              }}
              className={`inline-flex items-center px-3 py-1.5 rounded border text-xs transition-colors text-left break-words ${
                group.isSelected
                  ? 'bg-cyan/15 text-cyan border-cyan/50 shadow-[0_0_10px_rgba(0,212,255,0.2)]'
                  : group.isHot
                  ? 'bg-orange-500/10 text-orange-300 border-orange-500/30 hover:bg-orange-500/20 hover:text-orange-200'
                  : 'bg-white/5 text-secondary border-white/10 hover:bg-white/10 hover:text-white'
              }`}
              data-testid={`sector-tag-${group.display}`}
              title={group.display}
            >
              <span>{group.display}</span>
              {group.isHot && <span className="ml-1.5 text-[10px] text-orange-400" title="热门板块">🔥</span>}
            </button>
          );
        })}
      </div>

      {enablePagination && totalPages > 1 && (
        <div className="pt-2" data-testid="sector-filters-pagination">
          <Pagination
            currentPage={effectiveCurrentPage}
            totalPages={totalPages}
            onPageChange={(page) => {
              const normalizedPage = Math.min(Math.max(page, 1), totalPages);
              setCurrentPage(normalizedPage);
            }}
          />
        </div>
      )}
    </div>
  );
};
