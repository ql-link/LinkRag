import { describe, expect, it } from 'vitest';
import {
  CITE3_DOT,
  EXISTING_DOTS,
  HERO_BASE_CHUNKS,
  HERO_CANDIDATES,
  HERO_DURATION,
  HERO_STATIC_TIME,
  LANE_HITS,
  TOP5,
  TOTAL_DOTS,
  dotState,
  getHeroFrame,
  heroCandidates,
  heroExistingFiles,
  heroNewFile,
  heroQuestion,
  heroSegments,
  heroSources,
} from './heroTimeline';

const times = (step = 0.05) => Array.from({ length: Math.round(HERO_DURATION / step) }, (_, i) => i * step);

describe('getHeroFrame', () => {
  it('maps time to the storyboard segments', () => {
    const ids = heroSegments.map((s) => getHeroFrame((s.start + s.end) / 2).segment);
    expect(ids).toEqual(['upload', 'parse', 'ask', 'retrieve', 'rerank', 'answer', 'trace']);
    expect(heroSegments[heroSegments.length - 1].end).toBe(HERO_DURATION);
  });

  it('keeps the existing chunk total while the file is dragged and uploaded', () => {
    for (const t of [0.5, 1.5, 2.5, 3.2, 4.5]) {
      expect(getHeroFrame(t).totalChunks).toBe(HERO_BASE_CHUNKS);
    }
  });

  it('only adds the new file’s chunks as they land in the knowledge base', () => {
    const mid = getHeroFrame(6);
    expect(mid.stage).toBe('chunk');
    expect(mid.totalChunks).toBeGreaterThan(HERO_BASE_CHUNKS);
    expect(mid.totalChunks).toBeLessThan(HERO_BASE_CHUNKS + heroNewFile.chunks);

    const done = getHeroFrame(9);
    expect(done.stage).toBe('ready');
    expect(done.totalChunks).toBe(HERO_BASE_CHUNKS + heroNewFile.chunks);
    expect(done.fileCount).toBe(heroExistingFiles.length + 1);
  });

  it('never decreases the chunk total or file count within a loop', () => {
    let chunks = 0;
    let files = 0;
    for (const t of times()) {
      const f = getHeroFrame(t);
      expect(f.totalChunks).toBeGreaterThanOrEqual(chunks);
      expect(f.fileCount).toBeGreaterThanOrEqual(files);
      chunks = f.totalChunks;
      files = f.fileCount;
    }
  });

  it('fills every empty dot slot exactly when chunking finishes', () => {
    const present = (t: number) => Array.from({ length: TOTAL_DOTS }, (_, i) => dotState(i, t).present);
    expect(present(4.5).filter(Boolean)).toHaveLength(EXISTING_DOTS);
    expect(present(8).every(Boolean)).toBe(true);
  });

  it('tags the document structure while scanning', () => {
    expect(getHeroFrame(4.0).doc.revealY).toBe(0);
    expect(getHeroFrame(4.6).doc.scanY).not.toBeNull();
    expect(getHeroFrame(5.2).doc.revealY).toBeGreaterThan(200);
  });

  it('keeps the camera moving smoothly (no jumps between frames)', () => {
    let prev = getHeroFrame(0).camera;
    for (const t of times(1 / 30).slice(1)) {
      if (t > 27.4) break; // 循环末尾整体淡出后回到开头
      const cam = getHeroFrame(t).camera;
      expect(Math.hypot(cam.x - prev.x, cam.y - prev.y)).toBeLessThan(50);
      expect(Math.abs(cam.z - prev.z)).toBeLessThan(0.12);
      prev = cam;
    }
  });

  it('types the question then sends it', () => {
    expect(getHeroFrame(10.5).input.typed).toBe(heroQuestion);
    expect(getHeroFrame(11).questionSent).toBe(true);
  });

  it('lights exactly the candidate chunks during retrieval', () => {
    const lit = Array.from({ length: TOTAL_DOTS }, (_, i) => dotState(i, 13.2)).filter((d) => d.glow > 0);
    expect(lit).toHaveLength(HERO_CANDIDATES);
    expect(getHeroFrame(13.2).lanes.map((l) => l.count)).toEqual(LANE_HITS.map((l) => l.length));
  });

  it('reranks candidates so the cited chunks end up in the Top 5', () => {
    const hits = LANE_HITS.flat();
    for (const c of heroCandidates) expect(hits).toContain(c.dot);
    expect(TOP5).toHaveLength(5);
    expect(TOP5).toContain(CITE3_DOT);

    const before = getHeroFrame(14.9).rerank.rows;
    const after = getHeroFrame(16.2).rerank.rows;
    // 重排前按融合分排列，重排后按重排分排列
    expect(before.map((r) => Math.round(r.pos))).toEqual(before.map((_, i) => i));
    const sorted = [...after].sort((a, b) => a.pos - b.pos);
    for (let i = 1; i < sorted.length; i++) expect(sorted[i - 1].score).toBeGreaterThan(sorted[i].score);
    // 重排确实改变了顺序
    expect(after.some((r) => Math.round(r.pos) !== r.index)).toBe(true);
  });

  it('cites a chunk from the freshly uploaded file and traces it back', () => {
    expect(CITE3_DOT).toBeGreaterThanOrEqual(EXISTING_DOTS);
    expect(heroSources.find((s) => s.id === 3)?.file).toBe(heroNewFile.name);
    expect(getHeroFrame(23).visibleCitations).toEqual([1, 2, 3]);
    expect(getHeroFrame(24.5).hoveredCitation).toBe(3);
    expect(getHeroFrame(25).excerpt.visible).toBe(true);
  });

  it('shows a complete, fully traced answer on the reduced-motion frame', () => {
    const f = getHeroFrame(HERO_STATIC_TIME);
    expect(f.visibleCitations).toEqual([1, 2, 3]);
    expect(f.excerpt.mark).toBe(1);
    expect(f.contentOpacity).toBe(1);
  });

  it('ends on a wide closing shot before looping back to idle', () => {
    expect(getHeroFrame(27).closing).not.toBeNull();
    const looped = getHeroFrame(HERO_DURATION);
    expect(looped.segment).toBe('upload');
    expect(looped.closing).toBeNull();
    expect(looped.questionSent).toBe(false);
    expect(looped.totalChunks).toBe(HERO_BASE_CHUNKS);
  });
});
