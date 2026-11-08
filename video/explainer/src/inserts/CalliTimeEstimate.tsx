import React from 'react';
import {AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame} from 'remotion';
import '../fonts';
import model from '../../../inserts/calli-time-estimate/model.json';
import {C, EASE, FONT, appear, headline, ramp, sec} from '../theme';

// Silent chart insert: a scenario model of human active time, not a measurement. Every number on
// screen is read from the model JSON. The historical writer run in that JSON is not plotted.
export const CALLI_ESTIMATE_FRAMES = sec(9);

const A = model.assumptions;
const CPM = 225;
const SCENARIO = model.scenarios.find((s) => s.typing_characters_per_minute === CPM)!;
const PCTS = model.scenarios.map((s) => s.human_active_percent_saved_estimated);
const NB = '\u00a0';
// On-screen percentages are rounded to the nearest 10 % (48.521 -> 50, 36.806-62.445 -> 40-60).
const round10 = (v: number) => Math.round(v / 10) * 10;
const CENTRAL_PCT = round10(SCENARIO.human_active_percent_saved_estimated);
const RANGE_LO = round10(Math.min(...PCTS));
const RANGE_HI = round10(Math.max(...PCTS));

const mmss = (s: number) => {
  const t = Math.round(s);
  return `${Math.floor(t / 60)}${NB}min${NB}${String(t % 60).padStart(2, '0')}${NB}s`;
};

const MAX_MIN = 9;
const X0 = 600;
const AXIS_W = 1080;
const px = (seconds: number) => (seconds / 60 / MAX_MIN) * AXIS_W;

const BARS = [
  {label: 'Saisie manuelle · estimée', seconds: SCENARIO.manual_human_active_s_estimated, color: C.muted, soft: '#E4E0D6', y: 300, start: sec(0.9)},
  {label: 'Avec Calli · estimé', seconds: SCENARIO.calli_human_active_s_estimated, color: C.vermilion, soft: C.vermilionSoft, y: 420, start: sec(1.7)},
];
const BAR_H = 88;
const GROW = sec(1.4);
const SAVED = sec(3.4);
const RANGE = sec(4.0);
const ASSUMPTIONS = sec(4.6);

const hatch = (color: string, soft: string) =>
  `repeating-linear-gradient(135deg, ${color} 0 14px, ${soft} 14px 22px)`;

const Logo: React.FC = () => <Img src={staticFile('brand/calli-logo.svg')} style={{width: 168, height: 56, borderRadius: 8}} />;

export const CalliTimeEstimate: React.FC = () => {
  const frame = useCurrentFrame();
  const saved = SCENARIO.human_active_s_saved_estimated;
  const assumptions = [
    `Hypothèses${NB}: frappe ${CPM} caractères/min · dictée ${A.spoken_words_per_minute} mots/min`,
    `Navigation ${A.manual_navigation_and_save_seconds_per_item}${NB}s/commentaire · transition dictée ${A.dictation_turn_overhead_seconds_per_item}${NB}s · relecture ${A.human_final_review_seconds_per_item_both_modes}${NB}s dans les deux cas`,
    'Textes déjà rédigés · hors erreurs et reprises · aucun test utilisateur réalisé',
  ];
  const calliEnd = X0 + px(BARS[1].seconds);
  const manualEnd = X0 + px(BARS[0].seconds);
  const dim = ramp(frame, SAVED, sec(0.6));
  return (
    <AbsoluteFill style={{background: C.paper, color: C.ink, fontFamily: FONT, padding: '84px 140px'}}>
      <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start'}}>
        <div style={appear(frame, 0)}>
          <div style={{fontSize: 26, fontWeight: 700, letterSpacing: 4, color: C.vermilion}}>
            ESTIMATION · {model.corpus.items} APPRÉCIATIONS
          </div>
          <div style={{...headline, fontSize: 72, marginTop: 14}}>Du temps rendu à l’enseignant</div>
        </div>
        <div style={{display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 16, ...appear(frame, 4)}}>
          <Logo />
          <div style={{border: `2px solid ${C.amber}`, background: C.amberSoft, color: C.amber, borderRadius: 10, padding: '8px 16px', fontSize: 24, fontWeight: 600}}>
            Scénario modélisé · pas une mesure
          </div>
        </div>
      </div>

      {BARS.map((b) => {
        const p = interpolate(frame, [b.start, b.start + GROW], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: EASE});
        const w = px(b.seconds) * p;
        return (
          <React.Fragment key={b.label}>
            <div style={{position: 'absolute', left: 140, top: b.y, height: BAR_H, width: X0 - 140 - 30, display: 'flex', alignItems: 'center', justifyContent: 'flex-end', fontSize: 32, fontWeight: 600, textAlign: 'right', ...appear(frame, b.start - 6, 0)}}>
              {b.label}
            </div>
            <div style={{position: 'absolute', left: X0, top: b.y, height: BAR_H, width: w, background: hatch(b.color, b.soft), border: w > 0 ? `3px solid ${b.color}` : undefined, boxSizing: 'border-box', borderRadius: 6}} />
            <div style={{position: 'absolute', left: X0 + px(b.seconds) + 22, top: b.y, height: BAR_H, display: 'flex', alignItems: 'center', fontSize: 44, fontWeight: 700, color: b.color, fontVariantNumeric: 'tabular-nums', opacity: ramp(frame, b.start + GROW)}}>
              {mmss(b.seconds)}
            </div>
          </React.Fragment>
        );
      })}

      <div style={{position: 'absolute', left: X0, top: 550, width: AXIS_W, opacity: ramp(frame, sec(0.6))}}>
        <div style={{height: 2, background: C.line}} />
        {Array.from({length: MAX_MIN + 1}, (_, m) => (
          <div key={m} style={{position: 'absolute', left: (m / MAX_MIN) * AXIS_W, top: 0}}>
            <div style={{width: 2, height: 12, background: C.line, marginLeft: -1}} />
            <div style={{position: 'absolute', top: 18, transform: 'translateX(-50%)', fontSize: 22, color: C.muted, whiteSpace: 'nowrap'}}>
              {m === MAX_MIN ? `${m}${NB}min` : m}
            </div>
          </div>
        ))}
        <div style={{position: 'absolute', left: -X0 + 140, top: 18, width: X0 - 140 - 30, textAlign: 'right', fontSize: 22, color: C.muted}}>
          minutes de temps actif
        </div>
      </div>

      <svg style={{position: 'absolute', left: 0, top: 0, opacity: dim}} width={1920} height={1080} aria-hidden>
        <line x1={calliEnd} y1={526} x2={calliEnd + (manualEnd - calliEnd) * dim} y2={526} stroke={C.vermilion} strokeWidth={3} strokeDasharray="8 6" />
        <line x1={calliEnd} y1={516} x2={calliEnd} y2={536} stroke={C.vermilion} strokeWidth={3} />
        <line x1={manualEnd} y1={516} x2={manualEnd} y2={536} stroke={C.vermilion} strokeWidth={3} opacity={ramp(frame, SAVED + sec(0.5))} />
      </svg>

      <div style={{position: 'absolute', left: X0, right: 140, top: 614, ...appear(frame, SAVED + 6)}}>
        <div style={{display: 'flex', alignItems: 'center', gap: 22}}>
          <div style={{fontSize: 60, fontWeight: 800, letterSpacing: -1, color: C.vermilion}}>
            ≈{NB}{CENTRAL_PCT}{NB}% de temps actif en moins
          </div>
          <div style={{border: `2px solid ${C.amber}`, background: C.amberSoft, color: C.amber, borderRadius: 10, padding: '4px 14px', fontSize: 26, fontWeight: 700}}>
            estimation
          </div>
        </div>
        <div style={{fontSize: 26, color: C.ink, marginTop: 8, ...appear(frame, RANGE, 12)}}>
          ≈{NB}{mmss(saved).replace(/\u00a0s$/, '')} économisées sur {model.corpus.items}{NB}appréciations (estimation)
        </div>
        <div style={{fontSize: 22, color: C.muted, marginTop: 4, ...appear(frame, RANGE, 12)}}>
          Ordre de grandeur approximatif{NB}: {RANGE_LO}–{RANGE_HI}{NB}% selon la vitesse de frappe (scénarios, pas un intervalle de confiance)
        </div>
      </div>

      <div style={{position: 'absolute', left: 140, right: 140, bottom: 64, background: C.cell, border: `2px solid ${C.line}`, borderRadius: 12, padding: '20px 28px', display: 'flex', flexDirection: 'column', gap: 10, fontSize: 27, lineHeight: 1.3, ...appear(frame, ASSUMPTIONS, 16)}}>
        {assumptions.map((t) => (
          <div key={t}>{t}</div>
        ))}
        <div style={{fontSize: 21, color: C.muted, marginTop: 4}}>
          Corpus{NB}: {model.corpus.items} appréciations fictives de {model.corpus.path} · {model.corpus.comment_characters_including_spaces.toLocaleString('fr-FR').replace(/\s/g, NB)} caractères · {model.corpus.spoken_words_including_student_names_whitespace_count} mots dictés (prénoms inclus)
        </div>
      </div>
    </AbsoluteFill>
  );
};
