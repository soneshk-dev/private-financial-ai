/** Chart.js with the dataviz mark specs baked in: thin marks, hairline solid grid,
 * 4px rounded data-ends, 2px lines, 8px markers on hover, legend only for >=2 series. */
import {
  Chart, LineController, LineElement, PointElement, BarController, BarElement,
  CategoryScale, LinearScale, TimeScale, Filler, Tooltip, Legend, type ChartConfiguration,
} from 'chart.js';

Chart.register(LineController, LineElement, PointElement, BarController, BarElement, CategoryScale, LinearScale, TimeScale, Filler, Tooltip, Legend);

export const cssVar = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
export const series = (i: number) => cssVar(`--series-${i}`);
export const withAlpha = (hex: string, a: number) => {
  const n = parseInt(hex.replace('#', ''), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
};

const fmtMoney = (v: number) => (v < 0 ? '-' : '') + '$' + Math.abs(v).toLocaleString('en-US', { maximumFractionDigits: 0 });
const compactTick = (v: number) => {
  const a = Math.abs(v), s = v < 0 ? '-' : '';
  if (a >= 1e6) return `${s}$${(a / 1e6).toFixed(1)}M`;
  if (a >= 1e3) return `${s}$${Math.round(a / 1e3)}K`;
  return `${s}$${a}`;
};

export function baseOptions(): any {
  const ink2 = cssVar('--ink-2'), muted = cssVar('--muted'), grid = cssVar('--grid'), axis = cssVar('--axis'), surface = cssVar('--surface');
  Chart.defaults.font.family = cssVar('--font') || 'system-ui, sans-serif';
  Chart.defaults.color = muted;
  return {
    responsive: true, maintainAspectRatio: false, animation: { duration: 250 },
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: { position: 'bottom', labels: { boxWidth: 10, boxHeight: 10, usePointStyle: false, color: ink2, padding: 14, font: { size: 12 } } },
      tooltip: {
        backgroundColor: cssVar('--ink'), titleColor: surface, bodyColor: surface, padding: 10, cornerRadius: 8, displayColors: true,
        boxWidth: 8, boxHeight: 2, boxPadding: 4,
        callbacks: { label: (c: any) => ` ${fmtMoney(c.parsed.y ?? c.parsed.x)}  ${c.dataset.label ?? ''}` },
      },
    },
    scales: {
      x: { grid: { display: false }, border: { color: axis }, ticks: { color: muted, maxRotation: 0, autoSkip: true, font: { size: 11 } } },
      y: { grid: { color: grid, lineWidth: 1, drawTicks: false }, border: { display: false }, ticks: { color: muted, callback: (v: any) => compactTick(Number(v)), font: { size: 11 }, maxTicksLimit: 6 } },
    },
  };
}

export const lineDataset = (label: string, data: number[], color: string, fill = false) => ({
  label, data, borderColor: color, borderWidth: 2, tension: 0.25, pointRadius: 0, pointHoverRadius: 4, pointHoverBorderWidth: 2,
  pointHoverBorderColor: cssVar('--surface'), pointHoverBackgroundColor: color, pointHitRadius: 12,
  fill: fill ? 'origin' : false, backgroundColor: withAlpha(color, 0.10), borderJoinStyle: 'round', borderCapStyle: 'round',
});

export const barDataset = (label: string, data: number[], color: string, opts: Record<string, any> = {}) => ({
  label, data, backgroundColor: color, hoverBackgroundColor: withAlpha(color, 0.8), maxBarThickness: 24,
  borderRadius: 4, borderSkipped: 'start', borderColor: cssVar('--surface'), borderWidth: 0, ...opts,
});

/** Svelte action: `<canvas use:chart={config}>`. Rebuilds on config change and on theme change. */
export function chart(node: HTMLCanvasElement, config: ChartConfiguration | null) {
  let inst: Chart | null = null;
  const build = (c: ChartConfiguration | null) => {
    inst?.destroy();
    inst = c ? new Chart(node, c) : null;
  };
  build(config);
  const mq = window.matchMedia('(prefers-color-scheme: dark)');
  const onTheme = () => build(config);
  mq.addEventListener('change', onTheme);
  return {
    update(c: ChartConfiguration | null) { config = c; build(c); },
    destroy() { mq.removeEventListener('change', onTheme); inst?.destroy(); },
  };
}
