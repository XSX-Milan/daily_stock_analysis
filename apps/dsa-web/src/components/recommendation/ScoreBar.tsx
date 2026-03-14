import type React from 'react';
import type { ScoringWeights } from '../../types/recommendation';

interface ScoreBarProps {
  scores: Record<string, number>;
  compositeScore: number;
  weights?: ScoringWeights;
}

const DEFAULT_WEIGHTS: ScoringWeights = {
  technical: 30,
  fundamental: 25,
  sentiment: 20,
  macro: 15,
  risk: 10,
};

const DIMENSIONS = [
  { key: 'technical', label: 'TECH' },
  { key: 'fundamental', label: 'FUND' },
  { key: 'sentiment', label: 'SENT' },
  { key: 'macro', label: 'MACR' },
  { key: 'risk', label: 'RISK' },
] as const;

const clamp = (val: number) => Math.max(0, Math.min(100, val));

const getScoreColor = (score: number) => {
  if (score >= 60) return '#00d4ff';
  if (score >= 40) return '#f59e0b';
  return '#ff4466';
};

export const ScoreBar: React.FC<ScoreBarProps> = ({
  scores,
  compositeScore,
  weights = DEFAULT_WEIGHTS,
}) => {
  const hasScores = scores && Object.keys(scores).length > 0;

  if (!hasScores) {
    const clampedScore = clamp(compositeScore);
    const color = getScoreColor(clampedScore);
    return (
      <div className="flex flex-col w-full" data-testid="score-bar">
        <style>{`
          .score-segment-tooltip {
            position: relative;
          }
          .score-segment-tooltip::after {
            content: attr(data-tooltip);
            position: absolute;
            bottom: 100%;
            left: 50%;
            transform: translateX(-50%);
            margin-bottom: 8px;
            background-color: #111827;
            color: #d1d5db;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 12px;
            white-space: nowrap;
            border: 1px solid #374151;
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
            opacity: 0;
            visibility: hidden;
            transition: opacity 0.2s;
            z-index: 10;
            pointer-events: none;
            font-family: monospace;
          }
          .score-segment-tooltip:hover::after {
            opacity: 1;
            visibility: visible;
          }
        `}</style>
        <div className="flex h-2 w-full rounded overflow-visible bg-gray-800">
          <div
            data-testid="score-segment-composite"
            className="h-full transition-all duration-500 rounded score-segment-tooltip"
            style={{ width: '100%', backgroundColor: color }}
            data-tooltip={`COMPOSITE: ${clampedScore.toFixed(1)}`}
          />
        </div>
        <div className="flex justify-between mt-1 text-[10px] font-mono text-gray-500">
          <span>COMPOSITE</span>
        </div>
      </div>
    );
  }

  const totalWeight = Object.values(weights).reduce((sum, w) => sum + w, 0);

  return (
    <div className="flex flex-col w-full" data-testid="score-bar">
      <style>{`
        .score-segment-tooltip {
          position: relative;
        }
        .score-segment-tooltip::after {
          content: attr(data-tooltip);
          position: absolute;
          bottom: 100%;
          left: 50%;
          transform: translateX(-50%);
          margin-bottom: 8px;
          background-color: #111827;
          color: #d1d5db;
          padding: 4px 8px;
          border-radius: 4px;
          font-size: 12px;
          white-space: nowrap;
          border: 1px solid #374151;
          box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
          opacity: 0;
          visibility: hidden;
          transition: opacity 0.2s;
          z-index: 10;
          pointer-events: none;
          font-family: monospace;
        }
        .score-segment-tooltip:hover::after {
          opacity: 1;
          visibility: visible;
        }
      `}</style>
      <div className="flex h-2 w-full rounded overflow-visible bg-gray-800 gap-[1px]">
        {DIMENSIONS.map(({ key, label }) => {
          const rawScore = scores[key] ?? 0;
          const score = clamp(rawScore);
          const weight = weights[key as keyof ScoringWeights] ?? 0;
          const widthPercent = totalWeight > 0 ? (weight / totalWeight) * 100 : 0;

          if (widthPercent === 0) return null;

          const color = getScoreColor(score);

          return (
            <div
              key={key}
              data-testid={`score-segment-${key}`}
              className="h-full transition-all duration-500 first:rounded-l last:rounded-r score-segment-tooltip"
              style={{ width: `${widthPercent}%`, backgroundColor: color }}
              data-tooltip={`${label}: ${score.toFixed(1)} (W: ${weight}%)`}
            />
          );
        })}
      </div>
      <div className="flex w-full mt-1 text-[10px] font-mono text-gray-500">
        {DIMENSIONS.map(({ key, label }) => {
          const weight = weights[key as keyof ScoringWeights] ?? 0;
          const widthPercent = totalWeight > 0 ? (weight / totalWeight) * 100 : 0;
          
          if (widthPercent === 0) return null;
          
          return (
            <div 
              key={`label-${key}`} 
              className="text-center truncate px-0.5" 
              style={{ width: `${widthPercent}%` }}
              title={label}
            >
              {label}
            </div>
          );
        })}
      </div>
    </div>
  );
};
