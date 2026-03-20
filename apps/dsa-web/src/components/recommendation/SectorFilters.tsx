import type React from 'react';
import { useMemo } from 'react';
import type { RecommendationItem } from '../../types/recommendation';

export interface SectorFiltersProps {
  recommendations: RecommendationItem[];
  selectedSector: string | null;
  onSectorChange: (sector: string | null) => void;
  hotSectorNames?: string[];
}

export const SectorFilters: React.FC<SectorFiltersProps> = ({
  recommendations,
  selectedSector,
  onSectorChange,
  hotSectorNames = [],
}) => {
  const sectors = useMemo(() => {
    const uniqueSectors = new Set<string>();
    recommendations.forEach((item) => {
      const sector = item.sector?.trim();
      if (sector) {
        uniqueSectors.add(sector);
      }
    });
    return Array.from(uniqueSectors).sort((a, b) => a.localeCompare(b, 'zh-CN'));
  }, [recommendations]);

  const totalCount = recommendations.length;
  const sectorCount = sectors.length;

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
          onClick={() => onSectorChange(null)}
          className={`inline-flex items-center px-3 py-1.5 rounded border text-xs transition-colors ${
            selectedSector === null
              ? 'bg-cyan/15 text-cyan border-cyan/50 shadow-[0_0_10px_rgba(0,212,255,0.2)]'
              : 'bg-white/5 text-secondary border-white/10 hover:bg-white/10 hover:text-white'
          }`}
          data-testid="sector-tag-All"
        >
          全部 ({totalCount})
        </button>
        
        {sectors.map((sector) => {
          const isActive = selectedSector === sector;
          const isHot = hotSectorNames.includes(sector);
          return (
            <button
              key={sector}
              type="button"
              onClick={() => onSectorChange(isActive ? null : sector)}
              className={`inline-flex items-center px-3 py-1.5 rounded border text-xs transition-colors text-left break-words ${
                isActive
                  ? 'bg-cyan/15 text-cyan border-cyan/50 shadow-[0_0_10px_rgba(0,212,255,0.2)]'
                  : isHot
                  ? 'bg-orange-500/10 text-orange-300 border-orange-500/30 hover:bg-orange-500/20 hover:text-orange-200'
                  : 'bg-white/5 text-secondary border-white/10 hover:bg-white/10 hover:text-white'
              }`}
              data-testid={`sector-tag-${sector}`}
              title={sector}
            >
              <span>{sector}</span>
              {isHot && <span className="ml-1.5 text-[10px] text-orange-400" title="热门板块">🔥</span>}
            </button>
          );
        })}
      </div>
    </div>
  );
};
